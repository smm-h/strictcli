/**
 * Registration and validation: createApp plus the App and Group classes
 * storing commands, groups, deprecated entries, and global flags in insertion
 * order.
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

import { readFileSync, statSync } from "node:fs";
import { format } from "node:util";
import { enableChecks } from "./checks/cmd.js";
import { initTestCoverage, recordCoverage } from "./checks/coverage.js";
import {
	addCheckDef,
	type CheckContext,
	type CheckDef,
	type CheckOutcome,
	type CheckRunResult,
	type ChecksState,
	ErrorReporter,
	newChecksState,
	parseChecksToml,
	registerCheckImpl,
	validateCheckRegistrations,
	WarnReporter,
} from "./checks/framework.js";
import {
	type CheckSpec,
	materializeCheckProviders,
	resetCheckProviderCache,
} from "./checks/provider.js";
import {
	filterChecks,
	resolveCheckOrder,
	runOrderedChecks,
} from "./checks/runner.js";
import {
	type ConfigFieldRt,
	type ConfigFieldSpec,
	checkFlagConfigFieldDefault,
	makeConfigProvider,
	registerConfigField,
	registerConfigGroup,
} from "./config.js";
import { confirmMutating } from "./confirm.js";
import {
	Context,
	type InfraAccess,
	type ReservedFlags,
	type Writer,
} from "./context.js";
import {
	type Effect,
	EffectLog,
	Effects,
	effectTypeName,
	type Grant,
} from "./effects.js";
import {
	DryRunTruncated,
	errAppConfigConflictModeBad,
	errAppConfigFormatBad,
	errAppHelpEmpty,
	errCannotUseBothChecksAndEmbed,
	errCheckProviderMustBeCallable,
	errChecksNotEnabled,
	errChecksPathNotExist,
	errChecksTomlAppMismatch,
	errCommandCollidesWithGroup,
	errCommandConfigFieldsUnknownField,
	errCommandEffectInvalid,
	errCommandEffectMissing,
	errCommandEnvVarPrefix,
	errCommandFlagCollidesGlobal,
	errConnectionEnvIsAlreadyHandshake,
	errConnectionEnvIsAlreadyInfraRoot,
	errConnectionEnvVarEmptyHelp,
	errConnectionEnvWithoutURLFlag,
	errConnectionEnvWithPerFlagEnv,
	errConnectionURLFlagUnbound,
	errDeprecatedAlreadyRegistered,
	errDeprecatedCollidesCommand,
	errDeprecatedCollidesGroup,
	errDeprecatedCommandEffect,
	errDeprecatedMessageEmpty,
	errDeprecatedNameEmpty,
	errFlagConnectionEnvUndeclared,
	errFlagNameReservedByFramework,
	errFrameworkInternalHandlerForeign,
	errGlobalFlagNameReserved,
	errGlobalShortFlagReserved,
	errGroupAlreadyRegistered,
	errGroupCollidesWithCommand,
	errGroupHelpEmpty,
	errHandshakeEnvVarEmptyHelp,
	errHandshakeIsAlreadyInfraRoot,
	errInvalidTagName,
	errProcObserveAllowlistEmptyPrefix,
	errProcObserveAllowlistNotStrings,
	errTagContractViolation,
	RegistrationError,
} from "./errors.js";
import {
	type AnyArg,
	type AnyCommand,
	type AnyFlag,
	type AnyMutexGroup,
	type ConflictMode,
	type DeprecatedDef,
	defineMutatingCommand,
	defineReadOnlyCommand,
	type FlagMap,
	flagOpts,
	type MutatingCommandSpec,
	type PassthroughDef,
	pyRepr,
	RESERVED_FRAMEWORK_FLAG_NAMES,
	type ReadOnlyCommandSpec,
	validateAndDedupTags,
} from "./factories.js";
import { formatAppHelp, formatCommandHelp, formatGroupHelp } from "./help.js";
import {
	buildInfraAccess,
	expandTilde,
	type InfraRootPath,
	isInfraRootPath,
	resolveInfraRootPath,
	validateFlagInfraMarker,
} from "./infra.js";
import { invokeApp } from "./invoke.js";
import { type McpIO, serveMcp } from "./mcp.js";
import { interpretHandlerReturn, jsonCompact } from "./outcome.js";
import { doParse, flagParamName, formatParseErrorOutput } from "./parse.js";
import { dumpSchemaCore, writeSchema } from "./schema.js";
import { asToolsForApp, jsonSchemaForApp, type Tool } from "./tool.js";
import type { HandlerReturn } from "./types.js";

// --- Public surface ---

/** Configuration for creating a new strictcli application via createApp(). */
export interface AppSpec {
	readonly name: string;
	readonly version: string;
	readonly help: string;
	readonly envPrefix?: string;
	/** Global flags, keyed by the underscore form of each flag's name. */
	readonly flags?: FlagMap;
	// Config subsystem (config.ts).
	readonly config?: boolean;
	/** Explicit config file path; a relativeToRoot() marker resolves eagerly. */
	readonly configPath?: string | InfraRootPath;
	readonly configFormat?: "json" | "toml";
	readonly configConflictMode?: ConflictMode;
	readonly noDefaultConfigPath?: boolean;
	/** Infra roots: env var name -> default path (resolved eagerly, hermetic-immune). */
	readonly infraRoot?: Readonly<Record<string, string>>;
	/** Handshake env vars: env var name -> help text (read live, never captured). */
	readonly handshakeEnv?: Readonly<Record<string, string>>;
	/**
	 * Connection env vars: env var name -> help text. Behavioral "reach outside
	 * the process" signals (e.g. a database/service URL). Read live, no default,
	 * and hermetic-SUPPRESSED: under --hermetic they resolve as absent. Flags
	 * bind to them via a flag's connectionUrl/connectionEnv options.
	 */
	readonly connectionEnv?: Readonly<Record<string, string>>;
	/** Enables the check system with a path to checks.toml (must exist). */
	readonly checksPath?: string;
	/** Enables the check system with inline checks.toml text. */
	readonly checksEmbed?: string;
	/** Enables CLI test-coverage instrumentation (shards + built-in check). */
	readonly testCoverage?: boolean;
	/**
	 * Argv PREFIXES that make an `effects.run` an OBSERVE: it executes even in
	 * dry mode, returns a real value, is never written to the would-do log, and
	 * is legal in a read_only command. Matching is element-wise string equality
	 * against the leading argv elements -- no normalization of any kind.
	 */
	readonly procObserveAllowlist?: readonly (readonly string[])[];
}

/** Configuration for creating a command group via app.group() or group.group(). */
export interface GroupSpec {
	readonly help: string;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
}

/** A named container for commands and nested groups, organizing the CLI hierarchy. */
export interface Group {
	/** The group's registered name (used as the CLI token). */
	readonly name: string;
	/** Help text displayed in usage output. */
	readonly help: string;
	/** Tags inherited by all commands registered within this group. */
	readonly tags: readonly string[];
	/** When true, the group and its contents are hidden from help output. */
	readonly hidden: boolean;
	/** Registers a command or passthrough command within this group. */
	command(def: AnyCommand | PassthroughDef<string>): void;
	/** Creates and registers a nested subgroup. */
	group(name: string, spec: GroupSpec): Group;
	/** Registers a deprecated command name that prints a message and exits 1. */
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

/** The top-level CLI application, created via createApp(). */
export interface App {
	/** The application name (used in help output, MCP server info, and schema). */
	readonly name: string;
	/** The application version string (displayed by --version). */
	readonly version: string;
	/** Top-level help text displayed in usage output. */
	readonly help: string;
	/** Registers a command or passthrough command at the top level. */
	command(def: AnyCommand | PassthroughDef<string>): void;
	/** Creates and registers a top-level command group. */
	group(name: string, spec: GroupSpec): Group;
	/** Registers a deprecated command name that prints a message and exits 1. */
	deprecate(def: DeprecatedDef<string>): void;
	/**
	 * Declares a typed config file field. Fields with no default are required
	 * (the config system errors when they are missing from the config file);
	 * fields with a default are optional. Dots in the name form TOML sections.
	 */
	configField<Out>(name: string, spec: ConfigFieldSpec<Out>): void;
	/** Declare that any command tagged with `tag` must have the named flag. */
	tagContract(tag: string, requiresFlag: string): void;
	/**
	 * Registers an error-severity check implementation for a check declared
	 * with severity = "error" in checks.toml. The impl receives an
	 * ErrorReporter (which can mint both error- and warn-severity problems)
	 * and must return a CheckOutcome obtained from that reporter.
	 */
	errorCheck(
		name: string,
		fn: (
			ctx: CheckContext,
			reporter: ErrorReporter,
		) => CheckOutcome | Promise<CheckOutcome>,
	): void;
	/**
	 * Registers a warn-severity check implementation for a check declared
	 * with severity = "warn" in checks.toml. The impl receives a
	 * WarnReporter, which structurally lacks error-minting: a warn check
	 * cannot produce an error-severity problem, so it can never cascade.
	 */
	warnCheck(
		name: string,
		fn: (
			ctx: CheckContext,
			reporter: WarnReporter,
		) => CheckOutcome | Promise<CheckOutcome>,
	): void;
	/** Sets the factory that builds the CheckContext handed to check impls. */
	setCheckContext(factory: () => CheckContext): void;
	/**
	 * Registers a provider that supplies check specs at materialization time
	 * (lazy, memoized per cwd). Registering a provider enables the check
	 * system, so a TOML-less app gains a working `check` command.
	 */
	registerCheckProvider(provider: () => readonly CheckSpec[] | undefined): void;
	/**
	 * Drops provider-sourced definitions and clears the materialization memo
	 * so the next registry read re-runs all providers. Intended for tests and
	 * long-lived singletons; does NOT unregister the providers themselves.
	 */
	resetCheckProviderCache(): void;
	/**
	 * Runs checks programmatically with filtering and dependency resolution.
	 * Returns the executed results, the ordered names left unexecuted by the
	 * purity partition (empty unless pureOnly), and the exit code (0 for all
	 * pass, or all warn with ignoreWarnings; 1 otherwise).
	 */
	runChecks(
		context: CheckContext,
		opts?: RunChecksOptions,
	): Promise<RunChecksResult>;
	/**
	 * Returns the app's full schema as a dict, excluding project_id.
	 *
	 * This is the public, CWD-free accessor for the schema (Go DumpSchemaDict
	 * / Python dump_schema_dict). Unlike --dump-schema (which writes
	 * .strictcli/schema.json and derives project_id from package.json in the
	 * current working directory), this method reads only the in-memory App,
	 * performs no filesystem or CWD access, and cannot fail. The returned
	 * dict is equivalent to the written schema file with the project_id field
	 * removed. Integer values are bigint; float values are number.
	 */
	dumpSchemaDict(): Record<string, unknown>;
	/**
	 * Invokes a command programmatically with pre-typed kwargs, bypassing CLI
	 * parsing, env var resolution, config loading, and stdin handling.
	 * commandPath is dot-separated ("deploy", "dns.zone.create"); kwargs keys
	 * use underscored parameter names. Passthrough commands take the raw
	 * argument list under the "_args" key. Returns the handler's structured
	 * data when present, undefined for a bare void return, else the exit
	 * code. Throws InvokeError on invocation failures (unknown command,
	 * missing required flags, mutex violations, dependency errors).
	 */
	call(commandPath: string, kwargs?: Record<string, unknown>): Promise<unknown>;
	/**
	 * Produces a JSON Schema parameters object for a command's flags and
	 * positional args. Throws InvokeError if the path is invalid or resolves
	 * to a group.
	 */
	jsonSchema(commandPath: string): Record<string, unknown>;
	/**
	 * Exports non-hidden, non-interactive leaf commands as Tool descriptors,
	 * one per eligible command plus a trailing router tool. Each tool's
	 * execute wraps call().
	 */
	asTools(): Tool[];
	/**
	 * Runs a JSON-RPC 2.0 MCP server, reading one JSON object per line from
	 * input (default process.stdin) and writing one per line to output
	 * (default process.stdout), until EOF. Also reachable via the reserved
	 * --mcp global flag on run().
	 */
	serveMcp(io?: McpIO): Promise<void>;
	/**
	 * Runs the CLI: parses argv (default process.argv.slice(2)), awaits the
	 * handler, prints outcome data as one compact JSON line, and sets
	 * process.exitCode (never calls process.exit, so stdout drains safely).
	 */
	run(argv?: readonly string[]): Promise<void>;
	/** Runs the CLI in-process, capturing stdout/stderr/exit code (and data). */
	test(argv: readonly string[]): Promise<Result>;
}

/** Options for App.runChecks (Go RunChecksOptions / Python run_checks kwargs). */
export interface RunChecksOptions {
	readonly tagExpr?: string;
	readonly nameGlob?: string;
	readonly runAll?: boolean;
	readonly ignoreWarnings?: boolean;
	/**
	 * Purity partition: only checks that are declared pure AND do not need
	 * network access execute; every other selected check is returned in
	 * impureListed without being run and without contributing to the exit
	 * code. Off by default.
	 */
	readonly pureOnly?: boolean;
}

/** Result of App.runChecks. */
export interface RunChecksResult {
	readonly results: readonly CheckRunResult[];
	readonly impureListed: readonly string[];
	readonly exitCode: number;
}

/**
 * Creates a new strictcli application. This is the primary entry point for
 * building a CLI: configure the app via AppSpec, register commands and groups
 * on the returned App, then call app.run() to parse argv and dispatch.
 */
export function createApp(spec: AppSpec): App {
	return new AppImpl(spec);
}

// --- Internals (not re-exported through index.ts) ---

/**
 * Names reserved by the framework for global flags. The pre-existing set is
 * also what a SHORT flag name is checked against (the effects-regime quartet
 * bans long names only -- it has no short forms).
 */
export const RESERVED_GLOBAL_SHORT_NAMES: ReadonlySet<string> = new Set([
	"help",
	"h",
	"version",
	"v",
	"dump-schema",
	"mcp",
	"config",
	"hermetic",
]);

export const RESERVED_GLOBAL_FLAG_NAMES: ReadonlySet<string> = new Set([
	...RESERVED_GLOBAL_SHORT_NAMES,
	...RESERVED_FRAMEWORK_FLAG_NAMES,
]);

/**
 * The identities of handlers strictcli itself minted. This is the TS spelling
 * of the framework-internal module verification: the marker on a command
 * carrier is only honored when the handler is one of ours.
 *
 * It keys on FUNCTION IDENTITY, not on handler.name, Function.prototype
 * .toString() output or a marker property, because each of those is forgeable
 * and identity is not; and it is a WeakSet rather than a Set so a handler that
 * goes out of scope remains collectible. It is package-internal and NEVER
 * re-exported from index.ts, exactly as the marker itself is.
 */
const FRAMEWORK_HANDLERS = new WeakSet<object>();

/** Records a handler as framework-minted. Package-internal. */
export function markFrameworkHandler<T extends object>(fn: T): T {
	FRAMEWORK_HANDLERS.add(fn);
	return fn;
}

/**
 * The one reason string strictcli's own auto-registered commands use. Their
 * handlers must absorb the app's app-defined global flag values, which a
 * framework-authored handler cannot name.
 */
export const FRAMEWORK_INTERNAL_FORWARDING_REASON =
	"framework-internal: absorbs app-defined global flag values";

/**
 * The internal carrier shape: the framework-internal marker rides here, never
 * on the public CommandDef/AnyCommand types. It is not reachable from any
 * public factory, option or spec -- there is no `frameworkInternal` key in any
 * options object -- and it is not emitted in the schema.
 */
interface MaybeFrameworkInternal {
	readonly frameworkInternal?: boolean;
}

/**
 * Builds one of strictcli's own auto-registered commands (`check` and the five
 * `config` subcommands). They go through the same single validated
 * registration path as every consumer command -- there is no direct-carrier
 * construction bypass left.
 */
export function defineFrameworkCommand(
	name: string,
	effect: Effect,
	spec: {
		readonly help: string;
		readonly flags?: FlagMap;
		readonly args?: readonly AnyArg[];
		readonly mutex?: readonly AnyMutexGroup[];
		readonly interactive?: boolean;
		readonly handler: (
			args: never,
			ctx: never,
		) => HandlerReturn | Promise<HandlerReturn>;
	},
): AnyCommand {
	const withForwarding = {
		...spec,
		forwarding: { reason: FRAMEWORK_INTERNAL_FORWARDING_REASON },
	} as unknown as MutatingCommandSpec<FlagMap, readonly AnyArg[]>;
	const def = (effect === "read_only"
		? defineReadOnlyCommand(
				name,
				withForwarding as unknown as ReadOnlyCommandSpec<
					FlagMap,
					readonly AnyArg[]
				>,
			)
		: defineMutatingCommand(name, withForwarding)) as unknown as AnyCommand;
	return { ...def, frameworkInternal: true } as AnyCommand;
}

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
	/** Bound config field names (empty for passthrough commands). */
	readonly configFields: readonly string[];
}

/** Merges two tag lists, deduplicates, and sorts (Go mergeTags). */
function mergeTags(
	a: readonly string[],
	b: readonly string[],
): readonly string[] {
	return [...new Set([...a, ...b])].sort();
}

/** Validates the app-level observe allowlist (lists of non-empty strings). */
function validateProcObserveAllowlist(
	prefixes: readonly (readonly string[])[] | undefined,
): readonly (readonly string[])[] {
	const out: (readonly string[])[] = [];
	for (const prefix of prefixes ?? []) {
		if (!Array.isArray(prefix)) {
			throw new RegistrationError(
				errProcObserveAllowlistNotStrings(effectTypeName(prefix)),
			);
		}
		if (prefix.length === 0) {
			throw new RegistrationError(errProcObserveAllowlistEmptyPrefix());
		}
		for (const element of prefix) {
			if (typeof element !== "string") {
				throw new RegistrationError(
					errProcObserveAllowlistNotStrings(effectTypeName(element)),
				);
			}
		}
		out.push([...prefix]);
	}
	return out;
}

function requireNonEmpty(value: unknown, label: string): void {
	if (typeof value !== "string" || value.trim() === "") {
		throw new RegistrationError(`${label} must be a non-empty string`);
	}
}

/**
 * Enforces the connection-URL binding rules at registration time (mechanical
 * enforcement, not review): a URL-class flag must bind to a declared connection
 * env, the binding cannot be combined with a per-flag env, and the referenced
 * connection env must be declared. Mirrors Go validateFlagConnection / Python
 * _validate_connection_binding. The binding drives env resolution via
 * parse.ts's env loop (which reads connectionEnv when env is unset), so there
 * is no mutation of the immutable flag descriptor here.
 */
function validateFlagConnection(
	f: AnyFlag,
	connectionEnvs: ReadonlyMap<string, string>,
): void {
	const o = flagOpts(f);
	const connEnv = o.connectionEnv;
	const isUrl = o.connectionUrl === true;
	if (!isUrl && connEnv === undefined) {
		return;
	}
	if (connEnv !== undefined && o.env !== undefined && o.env !== connEnv) {
		throw new RegistrationError(errConnectionEnvWithPerFlagEnv(f.name));
	}
	if (isUrl && connEnv === undefined) {
		throw new RegistrationError(errConnectionURLFlagUnbound(f.name));
	}
	if (connEnv !== undefined && !isUrl) {
		throw new RegistrationError(errConnectionEnvWithoutURLFlag(f.name));
	}
	if (connEnv !== undefined && !connectionEnvs.has(connEnv)) {
		throw new RegistrationError(
			errFlagConnectionEnvUndeclared(f.name, connEnv),
		);
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
	if (def.kind !== "command" && def.kind !== "passthrough") {
		// TS-only guard for hand-forged carriers from untyped callers.
		throw new RegistrationError(
			"command() requires a command or passthrough carrier",
		);
	}
	// Classification is mandatory and has no default. Re-validated here (not
	// just in the factories) so hand-forged carriers from untyped callers
	// cannot bypass it.
	if (def.effect === undefined || def.effect === null) {
		throw new RegistrationError(errCommandEffectMissing(def.name));
	}
	if (def.effect !== "read_only" && def.effect !== "mutating") {
		throw new RegistrationError(
			errCommandEffectInvalid(def.name, String(def.effect)),
		);
	}
	// The framework-internal marker is only honored for handlers strictcli
	// itself minted. A consumer that reaches the marker by any route --
	// monkey-patching, prototype tampering, reflection -- fails loudly here.
	if ((def as MaybeFrameworkInternal).frameworkInternal === true) {
		if (!FRAMEWORK_HANDLERS.has(def.handler as unknown as object)) {
			throw new RegistrationError(errFrameworkInternalHandlerForeign(def.name));
		}
	}
	if (def.kind === "passthrough") {
		into.set(def.name, {
			kind: "passthrough",
			name: def.name,
			help: def.help,
			def,
			flags: [],
			tags: mergeTags(inheritedTags, def.tags),
			hidden: def.hidden,
			configFields: [],
		});
		return;
	}
	// Config-field bindings must reference declared fields (Python validates
	// them first in _build_and_validate_command).
	for (const cfName of def.configFields) {
		if (!app.configFields.has(cfName)) {
			throw new RegistrationError(
				errCommandConfigFieldsUnknownField(def.name, cfName),
			);
		}
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
	for (const f of def.allFlags) {
		validateFlagInfraMarker(f, app.infraRoots, def.name);
		validateFlagConnection(f, app.connectionEnvs);
	}
	// A command flag colliding with a config field (validation-only
	// coexistence) must have an agreeing default. Config fields registered
	// after this command are checked from the configField() side instead.
	for (const f of def.allFlags) {
		const cf = app.configFields.get(flagParamName(f.name));
		if (cf !== undefined) {
			checkFlagConfigFieldDefault(f.name, flagOpts(f).default, cf);
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
		configFields: def.configFields,
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
	// Deprecated commands are classification-EXEMPT: they have no handler and
	// execute nothing, so carrying an effect is a registration-time error.
	if ((def as { effect?: unknown }).effect !== undefined) {
		throw new RegistrationError(errDeprecatedCommandEffect(def.name));
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
	// Connection env vars: behavioral, hermetic-suppressed, no default.
	readonly connectionEnvs = new Map<string, string>();
	// Config subsystem state (config.ts owns the behavior).
	readonly configEnabled: boolean;
	/** Explicit config path override, marker-resolved at construction. */
	readonly configPathOverride: string | undefined;
	readonly configFormat: "json" | "toml";
	readonly configConflictMode: ConflictMode;
	readonly noDefaultConfigPath: boolean;
	/** Declared config fields, in declaration order. */
	readonly configFields = new Map<string, ConfigFieldRt>();
	/** Framework-owned config fields (underscore-prefixed, key-recognition only). */
	readonly frameworkFields = new Map<string, ConfigFieldRt>();
	/** Config data loaded at parse time (the config subcommands read it). */
	configData: Record<string, unknown> | undefined;
	/** Config parse error captured at parse time (config show reports it). */
	configParseErr: string | undefined;
	// Check-system state (checks/ modules own the behavior).
	readonly checksPath: string | undefined;
	readonly checksEmbed: string | undefined;
	readonly checks: ChecksState = newChecksState();
	// Test-coverage instrumentation state (checks/coverage.ts). All three
	// paths are absolute, anchored to the cwd at construction time (sibling
	// parity: tests which chdir still record into the repo, and a check
	// evaluated from a foreign cwd reads the app's own repo state).
	readonly testCoverage: boolean;
	/** App-level observe allowlist, validated and frozen at construction. */
	readonly procObserveAllowlist: readonly (readonly string[])[];
	/** The structured effect log of the most recent dispatch. */
	effectLogState: EffectLog = new EffectLog();
	/** Absolute shard-file path (<coverageDir>/<pid>.jsonl, append semantics). */
	coverageShardPath: string | undefined;
	/** Absolute .strictcli/coverage/ directory. */
	coverageDir: string | undefined;
	/** Absolute .strictcli/test-coverage.json manifest path. */
	coverageManifestPath: string | undefined;

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
			if (RESERVED_FRAMEWORK_FLAG_NAMES.has(f.name)) {
				// Unreachable through flag() (validateFlagConfig bans the quartet
				// first); kept so the global-flag validation path carries the same
				// message for any other construction route.
				throw new RegistrationError(errFlagNameReservedByFramework(f.name));
			}
			if (RESERVED_GLOBAL_FLAG_NAMES.has(f.name)) {
				throw new RegistrationError(errGlobalFlagNameReserved(f.name));
			}
			const short = flagOpts(f).short;
			if (short !== undefined && RESERVED_GLOBAL_SHORT_NAMES.has(short)) {
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
		for (const [envVar, helpText] of Object.entries(spec.connectionEnv ?? {})) {
			if (typeof helpText !== "string" || helpText.trim() === "") {
				throw new RegistrationError(errConnectionEnvVarEmptyHelp(envVar));
			}
			if (this.infraRoots.has(envVar)) {
				throw new RegistrationError(errConnectionEnvIsAlreadyInfraRoot(envVar));
			}
			if (this.handshakeEnvs.has(envVar)) {
				throw new RegistrationError(errConnectionEnvIsAlreadyHandshake(envVar));
			}
			this.connectionEnvs.set(envVar, helpText);
		}
		// Resolve the config-path marker (if any) now that the roots exist
		// (Python __post_init__ order: before global-flag marker validation).
		if (spec.configPath !== undefined && isInfraRootPath(spec.configPath)) {
			try {
				this.configPathOverride = resolveInfraRootPath(
					spec.configPath,
					this.infraRoots,
				);
			} catch (e) {
				throw new RegistrationError((e as Error).message);
			}
		} else {
			this.configPathOverride = spec.configPath;
		}
		// Validate global-flag default markers now that the roots are resolved
		// (mirroring Python __post_init__; registerCommand covers command flags).
		for (const f of globals) {
			validateFlagInfraMarker(f, this.infraRoots);
			validateFlagConnection(f, this.connectionEnvs);
		}

		this.configEnabled = spec.config ?? false;
		this.configFormat = spec.configFormat ?? "json";
		this.configConflictMode = spec.configConflictMode ?? "cli-wins";
		this.noDefaultConfigPath = spec.noDefaultConfigPath ?? false;
		// Runtime validation for untyped callers (Python App.__post_init__).
		if (this.configFormat !== "json" && this.configFormat !== "toml") {
			throw new RegistrationError(
				errAppConfigFormatBad(pyRepr(this.configFormat)),
			);
		}
		if (
			this.configConflictMode !== "cli-wins" &&
			this.configConflictMode !== "error"
		) {
			throw new RegistrationError(
				errAppConfigConflictModeBad(pyRepr(this.configConflictMode)),
			);
		}
		// Register the config subcommand group (config data loads at parse time).
		if (this.configEnabled) {
			registerConfigGroup(this);
		}
		this.checksPath = spec.checksPath;
		this.checksEmbed = spec.checksEmbed;
		this.testCoverage = spec.testCoverage ?? false;
		this.procObserveAllowlist = validateProcObserveAllowlist(
			spec.procObserveAllowlist,
		);

		// Enable the check system when checksPath or checksEmbed was provided.
		if (this.checksPath !== undefined && this.checksEmbed !== undefined) {
			throw new RegistrationError(errCannotUseBothChecksAndEmbed());
		}
		if (this.checksPath !== undefined) {
			let isFile = false;
			try {
				isFile = statSync(this.checksPath).isFile();
			} catch {
				isFile = false;
			}
			if (!isFile) {
				throw new RegistrationError(errChecksPathNotExist(this.checksPath));
			}
			this.loadChecks(readFileSync(this.checksPath, "utf8"));
		} else if (this.checksEmbed !== undefined) {
			this.loadChecks(this.checksEmbed);
		}

		// Test-coverage instrumentation: shard template, eager directory
		// creation, and the built-in cli-test-coverage provider.
		if (this.testCoverage) {
			initTestCoverage(this);
		}
	}

	/** Parses checks TOML text, verifies the app name, and enables checks. */
	private loadChecks(text: string): void {
		const { appName, defs, order } = parseChecksToml(text);
		if (appName !== this.name) {
			throw new RegistrationError(errChecksTomlAppMismatch(appName, this.name));
		}
		enableChecks(this);
		for (const name of order) {
			addCheckDef(this.checks, defs.get(name) as CheckDef);
		}
	}

	configField<Out>(name: string, spec: ConfigFieldSpec<Out>): void {
		registerConfigField(this, name, spec as ConfigFieldSpec);
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

	errorCheck(
		name: string,
		fn: (
			ctx: CheckContext,
			reporter: ErrorReporter,
		) => CheckOutcome | Promise<CheckOutcome>,
	): void {
		registerCheckImpl(this.checks, name, "error", (ctx) =>
			fn(ctx, new ErrorReporter()),
		);
	}

	warnCheck(
		name: string,
		fn: (
			ctx: CheckContext,
			reporter: WarnReporter,
		) => CheckOutcome | Promise<CheckOutcome>,
	): void {
		registerCheckImpl(this.checks, name, "warn", (ctx) =>
			fn(ctx, new WarnReporter()),
		);
	}

	setCheckContext(factory: () => CheckContext): void {
		this.checks.contextFactory = factory;
	}

	registerCheckProvider(
		provider: () => readonly CheckSpec[] | undefined,
	): void {
		if (typeof provider !== "function") {
			throw new RegistrationError(errCheckProviderMustBeCallable());
		}
		enableChecks(this);
		this.checks.providers.push(provider);
		// Registering a new provider invalidates any prior materialization.
		this.checks.providerMaterializedCwd = undefined;
	}

	resetCheckProviderCache(): void {
		resetCheckProviderCache(this.checks);
	}

	async runChecks(
		context: CheckContext,
		opts: RunChecksOptions = {},
	): Promise<RunChecksResult> {
		if (!this.checks.enabled) {
			throw new Error(errChecksNotEnabled());
		}
		// Materialize provider-sourced checks before any registry read.
		materializeCheckProviders(this.checks);
		const regErr = validateCheckRegistrations(this.checks);
		if (regErr !== undefined) {
			throw new Error(regErr);
		}
		const selected = filterChecks(
			this.checks.defs,
			opts.tagExpr,
			opts.nameGlob,
			opts.runAll ?? false,
		);
		if (selected.size === 0) {
			return { results: [], impureListed: [], exitCode: 0 };
		}
		const order = resolveCheckOrder(this.checks.defs, selected);
		return runOrderedChecks(
			this.checks.defs,
			order,
			context,
			opts.ignoreWarnings ?? false,
			opts.pureOnly ?? false,
		);
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

	dumpSchemaDict(): Record<string, unknown> {
		return dumpSchemaCore(this);
	}

	call(
		commandPath: string,
		kwargs: Record<string, unknown> = {},
	): Promise<unknown> {
		return invokeApp(this, commandPath, kwargs);
	}

	jsonSchema(commandPath: string): Record<string, unknown> {
		return jsonSchemaForApp(this, commandPath);
	}

	asTools(): Tool[] {
		return asToolsForApp(this);
	}

	serveMcp(io: McpIO = {}): Promise<void> {
		return serveMcp(this, io);
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
		const checkErr = validateCheckRegistrations(this.checks);
		if (checkErr !== undefined) {
			err.write(`error: ${checkErr}\n`);
			return { exitCode: 1, hasData: false, data: undefined };
		}
		const tagErr = this.validateTagContracts();
		if (tagErr !== undefined) {
			err.write(`error: ${tagErr}\n`);
			return { exitCode: 1, hasData: false, data: undefined };
		}

		const outcome = doParse(this, argv, { config: makeConfigProvider(this) });
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
			case "dump-schema": {
				let path: string;
				try {
					path = writeSchema(this);
				} catch (e) {
					err.write(`error: ${(e as Error).message}\n`);
					return { exitCode: 1, hasData: false, data: undefined };
				}
				out.write(`${path}\n`);
				return { exitCode: 0, hasData: false, data: undefined };
			}
			case "mcp":
				if (mode === "test") {
					// Python's in-process test surface (the divergence ground truth).
					err.write("error: --mcp requires interactive stdin/stdout\n");
					return { exitCode: 1, hasData: false, data: undefined };
				}
				// Run mode: serve MCP over stdin and this dispatch's stdout until
				// EOF, then exit 0 (Python: serve_mcp() then sys.exit(0)).
				await serveMcp(this, { output: out });
				return { exitCode: 0, hasData: false, data: undefined };
			case "parse-error":
				err.write(
					formatParseErrorOutput(this, outcome.message, outcome.commandPrefix),
				);
				return { exitCode: 1, hasData: false, data: undefined };
			case "passthrough": {
				// beginDispatch runs BEFORE coverage recording so pre-handler
				// CACHE_WRITEs land in this dispatch's log.
				this.beginDispatch();
				// Record test-coverage hit (command-level only, test mode only).
				if (mode === "test" && this.testCoverage) {
					recordCoverage(this, outcome.cmdPath);
				}
				const ctx = new Context(
					out,
					err,
					{},
					this.infraAccess(outcome.hermetic),
					outcome.reserved,
					this.armEffects(
						outcome.cmd,
						outcome.cmdPath,
						outcome.reserved.dryRun,
					),
				);
				const def = outcome.cmd.def as PassthroughDef<string>;
				const declined = this.runConfirm(mode, outcome.cmd, outcome, err);
				if (declined !== undefined) {
					return declined;
				}
				return await this.runHandler(
					() =>
						def.handler(
							{
								name: outcome.cmd.name,
								args: outcome.args,
								globals: outcome.globalKwargs,
							},
							ctx,
						),
					outcome.reserved.dryRun,
					out,
					err,
				);
			}
			case "command": {
				this.beginDispatch();
				// Record test-coverage hit (command-level only, test mode only).
				if (mode === "test" && this.testCoverage) {
					recordCoverage(this, outcome.cmdPath);
				}
				const ctx = new Context(
					out,
					err,
					outcome.sources,
					this.infraAccess(outcome.hermetic),
					outcome.reserved,
					this.armEffects(
						outcome.cmd,
						outcome.cmdPath,
						outcome.reserved.dryRun,
					),
				);
				const def = outcome.cmd.def as AnyCommand;
				const declined = this.runConfirm(mode, outcome.cmd, outcome, err);
				if (declined !== undefined) {
					return declined;
				}
				return await this.runHandler(
					() => def.handler(outcome.kwargs as never, ctx),
					outcome.reserved.dryRun,
					out,
					err,
				);
			}
		}
	}

	/**
	 * The confirm protocol, on the real CLI path only. Returns a dispatch
	 * result when the run was declined, or undefined to proceed.
	 */
	private runConfirm(
		mode: "run" | "test",
		cmd: RegisteredCommand,
		outcome: { readonly reserved: ReservedFlags; readonly cmdPath: string },
		err: Writer,
	): DispatchResult | undefined {
		if (mode !== "run") {
			// test/call/invoke/MCP behave as if --yes were passed.
			return undefined;
		}
		const def = cmd.def as { readonly effect?: Effect };
		if (def.effect !== "mutating") {
			return undefined;
		}
		if (outcome.reserved.dryRun || outcome.reserved.yes) {
			return undefined;
		}
		if (confirmMutating(outcome.cmdPath, err)) {
			return undefined;
		}
		return { exitCode: 1, hasData: false, data: undefined };
	}

	/**
	 * Runs the handler under the runtime seal: an extraction from an Unsettled
	 * carrier truncates the preview honestly instead of inventing a value. The
	 * post-return check on the log's `truncated` record is the TS-specific
	 * backstop -- unlike Python's BaseException-derived twin, a handler's
	 * `catch (e)` here CAN swallow the throw, and the run still fails closed.
	 */
	private async runHandler(
		invoke: () => unknown,
		dryRun: boolean,
		out: Writer,
		err: Writer,
	): Promise<DispatchResult> {
		let result: unknown;
		try {
			result = await invoke();
		} catch (e) {
			if (e instanceof DryRunTruncated) {
				return this.emitTruncated(e, out, err);
			}
			throw e;
		}
		const swallowed = this.effectLogState.truncated;
		if (swallowed !== null) {
			return this.emitTruncated(swallowed, out, err);
		}
		const interpreted = this.emitInterpreted(result, out);
		if (dryRun) {
			// The would-do log is dry mode's primary output and is NEVER
			// suppressed by --quiet.
			out.write(`${this.effectLogState.render()}\n`);
		}
		return interpreted;
	}

	/** Prints the already-recorded log to stdout and the error to stderr. */
	private emitTruncated(
		trunc: DryRunTruncated,
		out: Writer,
		err: Writer,
	): DispatchResult {
		out.write(`${this.effectLogState.render()}\n`);
		err.write(`${trunc.message}\n`);
		return { exitCode: 1, hasData: false, data: undefined };
	}

	/** Starts a new dispatch: resets the structured effect log. */
	beginDispatch(): void {
		this.effectLogState = new EffectLog();
	}

	/**
	 * Arms the effects handle for one dispatch (the runtime seal). Called at
	 * EVERY ctx-construction site that dispatches a handler, so there is no
	 * path on which ctx.effects is missing or a carrier escapes unpoisoned.
	 */
	armEffects(
		cmd: RegisteredCommand,
		cmdPath: string,
		dryRun: boolean,
	): Effects {
		const def = cmd.def as {
			readonly effect: Effect;
			readonly grants?: readonly Grant[];
		};
		return new Effects(
			{ cmdPath, effect: def.effect, grants: def.grants ?? [] },
			dryRun,
			this.effectLogState,
			this.procObserveAllowlist,
		);
	}

	/**
	 * Records a framework-blessed CACHE_WRITE. The closed list of sites is
	 * exactly three: the schema dump, the test-coverage shards, and the
	 * test-coverage manifest. CACHE_WRITEs have no public method, never appear
	 * in the would-do log, never trip read-only enforcement, and EXECUTE even in
	 * dry mode -- which is why they always carry `recorded: false`.
	 */
	recordCacheWrite(path: string): void {
		this.effectLogState.recordCacheWrite(path);
	}

	/**
	 * The structured effect records of the most recent dispatch, in either
	 * mode. Test-only surface (beside test()); deliberately NOT on the public
	 * App interface, so it stays out of the api-surface catalog.
	 */
	effectLog(): Record<string, unknown>[] {
		return this.effectLogState.toList();
	}

	/** Snapshots infra data for a Context (Go infraAccess): null when none declared. */
	private infraAccess(hermetic = false): InfraAccess | null {
		return buildInfraAccess(
			this.infraRoots,
			this.handshakeEnvs,
			this.connectionEnvs,
			hermetic,
		);
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
