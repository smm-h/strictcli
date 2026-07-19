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
import { format } from "node:util";
import { Context, type Writer } from "./context.js";
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
	errTagContractViolation,
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
import { formatAppHelp, formatCommandHelp, formatGroupHelp } from "./help.js";
import { interpretHandlerReturn, jsonCompact } from "./outcome.js";
import { doParse, formatParseErrorOutput } from "./parse.js";

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

/** Returned by app.test(): captured output, exit code, and outcome data. */
export interface Result {
	readonly stdout: string;
	readonly stderr: string;
	readonly exitCode: number;
	/** Structured outcome data; absent when the handler emitted none. */
	readonly data?: unknown;
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
	/**
	 * Runs the CLI: parses argv (default process.argv.slice(2)), awaits the
	 * handler, prints outcome data as one compact JSON line, and sets
	 * process.exitCode (never calls process.exit, so stdout drains safely).
	 */
	run(argv?: readonly string[]): Promise<void>;
	/** Runs the CLI in-process, capturing stdout/stderr/exit code (and data). */
	test(argv: readonly string[]): Promise<Result>;
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

	/**
	 * Checks every registered command (recursively through groups) against the
	 * declared tag contracts. Returns the first violation message, or
	 * undefined (Python returns the first; Go joins all -- no conformance case
	 * distinguishes them, and Python is the divergence ground truth).
	 */
	validateTagContracts(): string | undefined {
		if (this.tagContracts.size === 0) {
			return undefined;
		}
		const globalNames = this.globalFlagNames;
		const checkCommands = (
			commands: ReadonlyMap<string, RegisteredCommand>,
		): string | undefined => {
			for (const cmd of commands.values()) {
				if (cmd.kind === "passthrough") {
					continue;
				}
				for (const tag of cmd.tags) {
					const requiredFlag = this.tagContracts.get(tag);
					if (requiredFlag === undefined) {
						continue;
					}
					const has =
						cmd.flags.some((f) => f.name === requiredFlag) ||
						globalNames.has(requiredFlag);
					if (!has) {
						return errTagContractViolation(cmd.name, tag, requiredFlag);
					}
				}
			}
			return undefined;
		};
		const checkGroups = (
			groups: ReadonlyMap<string, GroupImpl>,
		): string | undefined => {
			for (const group of groups.values()) {
				const err = checkCommands(group.commands) ?? checkGroups(group.groups);
				if (err !== undefined) {
					return err;
				}
			}
			return undefined;
		};
		return checkCommands(this.commands) ?? checkGroups(this.groups);
	}

	async run(argv?: readonly string[]): Promise<void> {
		const tokens = argv ?? process.argv.slice(2);
		const r = await this.dispatch(
			tokens,
			process.stdout,
			process.stderr,
			"run",
		);
		process.exitCode = r.exitCode;
	}

	async test(argv: readonly string[]): Promise<Result> {
		// Unbounded string buffers, mirroring Go's io.Copy drain and Python's
		// StringIO. Dispatch (ctx, help, errors, data) writes straight into
		// them; console.* is rerouted during the window so handlers that
		// bypass ctx are captured too (the Python redirect_stdout analog).
		// Patching process.stdout.write itself is NOT safe here: the node:test
		// runner multiplexes its reporter protocol over process.stdout, so an
		// async handler that yields would interleave runner frames into the
		// capture.
		const stdoutChunks: string[] = [];
		const stderrChunks: string[] = [];
		const out: Writer = { write: (s) => stdoutChunks.push(s) };
		const err: Writer = { write: (s) => stderrChunks.push(s) };
		const consolePatch =
			(w: Writer) =>
			(...args: unknown[]): void => {
				w.write(`${format(...args)}\n`);
			};
		const saved = {
			log: console.log,
			info: console.info,
			debug: console.debug,
			warn: console.warn,
			error: console.error,
		};
		console.log = consolePatch(out);
		console.info = consolePatch(out);
		console.debug = consolePatch(out);
		console.warn = consolePatch(err);
		console.error = consolePatch(err);
		let r: DispatchResult;
		try {
			r = await this.dispatch(argv, out, err, "test");
		} finally {
			console.log = saved.log;
			console.info = saved.info;
			console.debug = saved.debug;
			console.warn = saved.warn;
			console.error = saved.error;
		}
		return {
			stdout: stdoutChunks.join(""),
			stderr: stderrChunks.join(""),
			exitCode: r.exitCode,
			...(r.hasData ? { data: r.data } : {}),
		};
	}

	/** Shared run/test dispatch: parse, render, execute, interpret. */
	private async dispatch(
		argv: readonly string[],
		out: Writer,
		err: Writer,
		mode: "run" | "test",
	): Promise<DispatchResult> {
		const tagErr = this.validateTagContracts();
		if (tagErr !== undefined) {
			err.write(`error: ${tagErr}\n`);
			return { exitCode: 1, hasData: false, data: undefined };
		}

		const outcome = doParse(this, argv);
		switch (outcome.kind) {
			case "help": {
				const target = outcome.target;
				let text: string;
				if (target.level === "app") {
					text = formatAppHelp(this);
				} else if (target.level === "group") {
					text = formatGroupHelp(this, target.group, target.path);
				} else {
					const prefix =
						target.path.length > 0 ? `${target.path.join(" ")} ` : "";
					text = formatCommandHelp(this, target.cmd, prefix);
				}
				out.write(`${text}\n`);
				return { exitCode: 0, hasData: false, data: undefined };
			}
			case "version":
				out.write(`${outcome.text}\n`);
				return { exitCode: 0, hasData: false, data: undefined };
			case "dump-schema":
				// Loud hard error until the schema subphase lands -- never a
				// silent no-op.
				throw new Error(
					"internal: --dump-schema is not implemented yet (schema subphase)",
				);
			case "mcp":
				if (mode === "test") {
					// Python's in-process test surface (the divergence ground truth).
					err.write("error: --mcp requires interactive stdin/stdout\n");
					return { exitCode: 1, hasData: false, data: undefined };
				}
				throw new Error(
					"internal: --mcp is not implemented yet (mcp subphase)",
				);
			case "parse-error":
				err.write(
					formatParseErrorOutput(this, outcome.message, outcome.commandPrefix),
				);
				return { exitCode: 1, hasData: false, data: undefined };
			case "passthrough": {
				const ctx = new Context(out, err, {}, null);
				const def = outcome.cmd.def as PassthroughDef<string>;
				const result = await def.handler(
					{
						name: outcome.cmd.name,
						args: outcome.args,
						globals: outcome.globalKwargs,
					},
					ctx,
				);
				return this.emitInterpreted(result, out);
			}
			case "command": {
				const ctx = new Context(out, err, outcome.sources, null);
				const def = outcome.cmd.def as AnyCommand;
				const result = await def.handler(outcome.kwargs as never, ctx);
				return this.emitInterpreted(result, out);
			}
		}
	}

	/** Interprets a handler return and prints the data line when present. */
	private emitInterpreted(result: unknown, out: Writer): DispatchResult {
		const interpreted = interpretHandlerReturn(result);
		if (interpreted.hasData) {
			out.write(`${jsonCompact(interpreted.data)}\n`);
		}
		return interpreted;
	}
}

interface DispatchResult {
	readonly exitCode: number;
	readonly hasData: boolean;
	readonly data: unknown;
}
