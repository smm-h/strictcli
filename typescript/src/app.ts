/**
 * Registration and validation: createApp plus the App/Group internals.
 *
 * The runtime classes (AppImpl/GroupImpl) are internal -- index.ts exports
 * only createApp and the App/Group interfaces. Later modules (parse, routing,
 * help) import the classes from this module directly.
 *
 * Registration order is data: commands, groups, deprecated commands, and
 * global flags are stored in insertion order (Maps/arrays) for later help
 * rendering. Mirroring the siblings, top-level command/group registration
 * does NOT check name collisions (last registration wins); nested groups DO
 * (group/command/deprecated collision checks), exactly like Python and Go.
 */

import { homedir } from "node:os";
import { join } from "node:path";
import {
	errAppHelpEmpty,
	errCommandCollidesWithGroup,
	errCommandEnvVarPrefix,
	errCommandFlagCollidesGlobal,
	errDeprecatedAlreadyRegistered,
	errDeprecatedCollidesCommand,
	errDeprecatedCollidesGroup,
	errDeprecatedMessageEmpty,
	errDeprecatedNameEmpty,
	errGlobalFlagNameReserved,
	errGlobalShortFlagReserved,
	errGroupAlreadyRegistered,
	errGroupCollidesWithCommand,
	errGroupHelpEmpty,
	errHandshakeEnvVarEmptyHelp,
	errHandshakeIsAlreadyInfraRoot,
	errInvalidTagName,
	RegistrationError,
} from "./errors.js";
import {
	type AnyCommand,
	type AnyFlag,
	type ConflictMode,
	type DeprecatedDef,
	type FlagMap,
	flagOpts,
	type PassthroughDef,
	validateAndDedupTags,
} from "./factories.js";

// --- Public surface ---

export interface AppSpec {
	readonly name: string;
	readonly version: string;
	readonly help: string;
	readonly envPrefix?: string;
	/** Global flags, keyed by the underscore form of each flag's name. */
	readonly flags?: FlagMap;
	// Config-related fields: typed but inert until the config subphase.
	readonly config?: boolean;
	readonly configPath?: string;
	readonly configFormat?: "json" | "toml";
	readonly configConflictMode?: ConflictMode;
	readonly noDefaultConfigPath?: boolean;
	/** Infra roots: env var name -> default path (resolved eagerly, hermetic-immune). */
	readonly infraRoot?: Readonly<Record<string, string>>;
	/** Handshake env vars: env var name -> help text (read live, never captured). */
	readonly handshakeEnv?: Readonly<Record<string, string>>;
	// Check-system fields: typed but inert until the checks subphase.
	readonly checksPath?: string;
	readonly checksEmbed?: string;
	// Typed but inert until the coverage subphase.
	readonly testCoverage?: boolean;
}

export interface GroupSpec {
	readonly help: string;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
}

export interface Group {
	readonly name: string;
	readonly help: string;
	readonly tags: readonly string[];
	readonly hidden: boolean;
	command(def: AnyCommand | PassthroughDef<string>): void;
	group(name: string, spec: GroupSpec): Group;
	deprecate(def: DeprecatedDef<string>): void;
}

export interface App {
	readonly name: string;
	readonly version: string;
	readonly help: string;
	command(def: AnyCommand | PassthroughDef<string>): void;
	group(name: string, spec: GroupSpec): Group;
	deprecate(def: DeprecatedDef<string>): void;
	/** Declare that any command tagged with `tag` must have the named flag. */
	tagContract(tag: string, requiresFlag: string): void;
}

export function createApp(spec: AppSpec): App {
	return new AppImpl(spec);
}

// --- Internals (not re-exported through index.ts) ---

export const RESERVED_GLOBAL_FLAG_NAMES: ReadonlySet<string> = new Set([
	"help",
	"h",
	"version",
	"v",
	"dump-schema",
	"mcp",
	"config",
	"hermetic",
]);

/** A registered command: the carrier plus registration-time derived data. */
export interface RegisteredCommand {
	readonly kind: "command" | "passthrough";
	readonly name: string;
	readonly help: string;
	readonly def: AnyCommand | PassthroughDef<string>;
	/** Merged flag list; empty for passthrough commands. */
	readonly flags: readonly AnyFlag[];
	/** Own tags merged with inherited group tags, deduplicated and sorted. */
	readonly tags: readonly string[];
	readonly hidden: boolean;
}

/** Merges two tag lists, deduplicates, and sorts (Go mergeTags). */
function mergeTags(
	a: readonly string[],
	b: readonly string[],
): readonly string[] {
	return [...new Set([...a, ...b])].sort();
}

/** Expands a leading ~ (as ~ or ~/...) to the user's home directory. */
function expandTilde(p: string): string {
	if (p === "~") {
		return homedir();
	}
	if (p.startsWith("~/")) {
		return join(homedir(), p.slice(2));
	}
	return p;
}

function requireNonEmpty(value: unknown, label: string): void {
	if (typeof value !== "string" || value.trim() === "") {
		throw new RegistrationError(`${label} must be a non-empty string`);
	}
}

/**
 * Shared registration path for command/passthrough carriers. Runs the
 * app-context checks the carrier factories cannot: global-flag collisions and
 * env-prefix conformance.
 */
function registerCommand(
	into: Map<string, RegisteredCommand>,
	def: AnyCommand | PassthroughDef<string>,
	app: AppImpl,
	inheritedTags: readonly string[],
): void {
	if (def.kind === "passthrough") {
		into.set(def.name, {
			kind: "passthrough",
			name: def.name,
			help: def.help,
			def,
			flags: [],
			tags: mergeTags(inheritedTags, def.tags),
			hidden: def.hidden,
		});
		return;
	}
	if (def.kind !== "command") {
		// TS-only guard for hand-forged carriers from untyped callers.
		throw new RegistrationError(
			"command() requires a command or passthrough carrier",
		);
	}
	for (const f of def.allFlags) {
		if (app.globalFlagNames.has(f.name)) {
			throw new RegistrationError(
				errCommandFlagCollidesGlobal(def.name, f.name),
			);
		}
	}
	if (app.envPrefix !== undefined) {
		const expectedPrefix = `${app.envPrefix}_`;
		for (const f of def.allFlags) {
			const o = flagOpts(f);
			if (
				o.env !== undefined &&
				o.prefixed !== false &&
				!o.env.startsWith(expectedPrefix)
			) {
				throw new RegistrationError(
					errCommandEnvVarPrefix(def.name, o.env, f.name, expectedPrefix),
				);
			}
		}
	}
	into.set(def.name, {
		kind: "command",
		name: def.name,
		help: def.help,
		def,
		flags: def.allFlags,
		tags: mergeTags(inheritedTags, def.tags),
		hidden: def.hidden,
	});
}

/** Shared deprecated-command registration (App and Group levels). */
function registerDeprecated(
	commands: ReadonlyMap<string, RegisteredCommand>,
	groups: ReadonlyMap<string, GroupImpl>,
	deprecated: Map<string, string>,
	def: DeprecatedDef<string>,
): void {
	// Re-validated here (not just in the factory) so hand-forged carriers from
	// untyped callers cannot bypass the sibling checks.
	if (typeof def.name !== "string" || def.name.trim() === "") {
		throw new RegistrationError(errDeprecatedNameEmpty());
	}
	if (typeof def.message !== "string" || def.message.trim() === "") {
		throw new RegistrationError(errDeprecatedMessageEmpty(def.name));
	}
	if (commands.has(def.name)) {
		throw new RegistrationError(errDeprecatedCollidesCommand(def.name));
	}
	if (groups.has(def.name)) {
		throw new RegistrationError(errDeprecatedCollidesGroup(def.name));
	}
	if (deprecated.has(def.name)) {
		throw new RegistrationError(errDeprecatedAlreadyRegistered(def.name));
	}
	deprecated.set(def.name, def.message);
}

export class GroupImpl implements Group {
	readonly commands = new Map<string, RegisteredCommand>();
	readonly groups = new Map<string, GroupImpl>();
	readonly deprecated = new Map<string, string>();

	constructor(
		readonly name: string,
		readonly help: string,
		readonly tags: readonly string[],
		readonly accumulatedTags: readonly string[],
		readonly hidden: boolean,
		private readonly app: AppImpl,
	) {}

	command(def: AnyCommand | PassthroughDef<string>): void {
		if (this.groups.has(def.name)) {
			throw new RegistrationError(errCommandCollidesWithGroup(def.name));
		}
		registerCommand(this.commands, def, this.app, this.accumulatedTags);
	}

	group(name: string, spec: GroupSpec): Group {
		if (typeof spec.help !== "string" || spec.help.trim() === "") {
			throw new RegistrationError(errGroupHelpEmpty());
		}
		if (this.commands.has(name)) {
			throw new RegistrationError(errGroupCollidesWithCommand(name));
		}
		if (this.groups.has(name)) {
			throw new RegistrationError(errGroupAlreadyRegistered(name));
		}
		const ownTags = validateAndDedupTags(spec.tags ?? []);
		const sub = new GroupImpl(
			name,
			spec.help,
			ownTags,
			mergeTags(this.accumulatedTags, ownTags),
			spec.hidden ?? false,
			this.app,
		);
		this.groups.set(name, sub);
		return sub;
	}

	deprecate(def: DeprecatedDef<string>): void {
		registerDeprecated(this.commands, this.groups, this.deprecated, def);
	}
}

const TAG_RE = /^[a-z][a-z0-9-]*$/;

export class AppImpl implements App {
	readonly name: string;
	readonly version: string;
	readonly help: string;
	readonly envPrefix: string | undefined;
	readonly globalFlags: readonly AnyFlag[];
	readonly globalFlagNames: ReadonlySet<string>;
	readonly commands = new Map<string, RegisteredCommand>();
	readonly groups = new Map<string, GroupImpl>();
	readonly deprecated = new Map<string, string>();
	readonly tagContracts = new Map<string, string>();
	// Infra roots: resolved eagerly at construction. Resolution has no argv
	// dependency, which is exactly why it is hermetic-immune.
	readonly infraRoots = new Map<string, string>();
	readonly infraRootFromEnv = new Map<string, boolean>();
	readonly infraRootDefaults = new Map<string, string>();
	readonly handshakeEnvs = new Map<string, string>();
	// Config- and check-related fields: stored but inert until later subphases.
	readonly configEnabled: boolean;
	readonly configPath: string | undefined;
	readonly configFormat: "json" | "toml";
	readonly configConflictMode: ConflictMode;
	readonly noDefaultConfigPath: boolean;
	readonly checksPath: string | undefined;
	readonly checksEmbed: string | undefined;
	readonly testCoverage: boolean;

	constructor(spec: AppSpec) {
		requireNonEmpty(spec.version, "App.version");
		if (typeof spec.help !== "string" || spec.help.trim() === "") {
			throw new RegistrationError(errAppHelpEmpty());
		}
		this.name = spec.name;
		this.version = spec.version;
		this.help = spec.help;
		this.envPrefix = spec.envPrefix;

		const globals: AnyFlag[] = [];
		const globalNames = new Set<string>();
		for (const [key, f] of Object.entries(spec.flags ?? {})) {
			const expected = f.name.replaceAll("-", "_");
			if (key !== expected) {
				throw new RegistrationError(
					`App.flags key '${key}' must be the underscore form of flag '${f.name}' ('${expected}')`,
				);
			}
			if (RESERVED_GLOBAL_FLAG_NAMES.has(f.name)) {
				throw new RegistrationError(errGlobalFlagNameReserved(f.name));
			}
			const short = flagOpts(f).short;
			if (short !== undefined && RESERVED_GLOBAL_FLAG_NAMES.has(short)) {
				throw new RegistrationError(errGlobalShortFlagReserved(short));
			}
			globals.push(f);
			globalNames.add(f.name);
		}
		this.globalFlags = globals;
		this.globalFlagNames = globalNames;

		for (const [envVar, defaultPath] of Object.entries(spec.infraRoot ?? {})) {
			const envVal = process.env[envVar];
			if (envVal !== undefined) {
				this.infraRoots.set(envVar, expandTilde(envVal));
				this.infraRootFromEnv.set(envVar, true);
			} else {
				this.infraRoots.set(envVar, expandTilde(defaultPath));
				this.infraRootFromEnv.set(envVar, false);
			}
			this.infraRootDefaults.set(envVar, defaultPath);
		}
		for (const [envVar, helpText] of Object.entries(spec.handshakeEnv ?? {})) {
			if (typeof helpText !== "string" || helpText.trim() === "") {
				throw new RegistrationError(errHandshakeEnvVarEmptyHelp(envVar));
			}
			if (this.infraRoots.has(envVar)) {
				throw new RegistrationError(errHandshakeIsAlreadyInfraRoot(envVar));
			}
			this.handshakeEnvs.set(envVar, helpText);
		}

		this.configEnabled = spec.config ?? false;
		this.configPath = spec.configPath;
		this.configFormat = spec.configFormat ?? "json";
		this.configConflictMode = spec.configConflictMode ?? "cli-wins";
		this.noDefaultConfigPath = spec.noDefaultConfigPath ?? false;
		this.checksPath = spec.checksPath;
		this.checksEmbed = spec.checksEmbed;
		this.testCoverage = spec.testCoverage ?? false;
	}

	command(def: AnyCommand | PassthroughDef<string>): void {
		registerCommand(this.commands, def, this, []);
	}

	group(name: string, spec: GroupSpec): Group {
		if (typeof spec.help !== "string" || spec.help.trim() === "") {
			throw new RegistrationError(errGroupHelpEmpty());
		}
		const ownTags = validateAndDedupTags(spec.tags ?? []);
		const grp = new GroupImpl(
			name,
			spec.help,
			ownTags,
			ownTags,
			spec.hidden ?? false,
			this,
		);
		this.groups.set(name, grp);
		return grp;
	}

	deprecate(def: DeprecatedDef<string>): void {
		registerDeprecated(this.commands, this.groups, this.deprecated, def);
	}

	tagContract(tag: string, requiresFlag: string): void {
		if (!TAG_RE.test(tag)) {
			throw new RegistrationError(errInvalidTagName(tag));
		}
		this.tagContracts.set(tag, requiresFlag);
	}
}
