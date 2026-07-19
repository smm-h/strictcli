/**
 * Parse pipeline: reserved-flag pre-scan, two-phase global-flag parsing,
 * command-token parsing, env/config/default resolution, and constraint
 * validation. Mirrors Go doParse/extractGlobalFlags/parseCommand
 * (strictcli.go, parse.go) with Python _parse/_parse_global_flags/
 * _parse_command as the divergence ground truth.
 *
 * Internal contract: helpers throw ParseError; doParse converts them into
 * "parse-error" outcomes at the two sibling catch boundaries (global-flag
 * parsing without a command prefix, command parsing with the full
 * "app path command" prefix). Help/version/schema/mcp requests are outcome
 * variants, not exceptions; rendering them is help.ts/app-runner territory.
 */

import type { AppImpl, GroupImpl, RegisteredCommand } from "./app.js";
import { newStdinTracker, type StdinTracker } from "./atprefix.js";
import { resolveEnvValue } from "./env.js";
import {
	errBoolFlagNoValue,
	errBoolNegationNoValue,
	errConfigValueDuplicate,
	errConfigValueError,
	errFlagRequiresFlag,
	errFlagRequiresValue,
	errFlagSetInBothAndConfig,
	errFlagSetInBothCliAndConfig,
	errFlagsMustBeUsedTogether,
	errFlagValueError,
	errHermeticConfigMutuallyExclusive,
	errHermeticWithConfigCommands,
	errImpliesConflict,
	errMissingRequiredArgument,
	errMutuallyExclusive,
	errOneOfRequired,
	errUnexpectedArgument,
	errUnknownFlag,
	ParseError,
} from "./errors.js";
import {
	type AnyArg,
	type AnyFlag,
	type ConflictMode,
	elemSchemaOf,
	flagOpts,
	schemaKind,
} from "./factories.js";
import { resolveCommand } from "./routing.js";
import { SourcedStore, type SourceLabel } from "./sources.js";
import {
	appendListValue,
	coerceArgValue,
	coerceToScalar,
	findDuplicate,
	formatValueForError,
	parseDictValue,
	storeDictEntries,
	validateChoices,
} from "./values.js";

// --- Parameter naming ---

/** Converts a flag name like "dry-run" to its handler-args key "dry_run". */
export function flagParamName(flagName: string): string {
	return flagName.replace(/^-+/, "").replaceAll("-", "_");
}

// --- Config seam (Phase 5 fills; the default provider supplies no data) ---

export interface ConfigLoadResult {
	/** Param-name-keyed raw config values; null when no config file applies. */
	readonly data: Readonly<Record<string, unknown>> | null;
	/** Non-empty when the config file exists but cannot be parsed. */
	readonly parseErr?: string;
}

/**
 * Injectable config-values provider. Phase 5 implements file loading and
 * per-flag coercion; the parse pipeline owns precedence and conflict
 * semantics so they are already exact here.
 */
export interface ConfigProvider {
	load(runtimePathOverride: string | undefined): ConfigLoadResult;
	/** Coerces a raw config value to f's type; throws Error with the bare message. */
	coerce(f: AnyFlag, value: unknown): unknown;
}

export const emptyConfigProvider: ConfigProvider = {
	load: () => ({ data: null }),
	coerce: () => {
		throw new Error("internal: no config provider installed");
	},
};

/** Resolved per-parse config state threaded through the flag-resolution passes. */
interface ConfigContext {
	readonly data: Readonly<Record<string, unknown>> | null;
	readonly coerce: ConfigProvider["coerce"];
	readonly conflictMode: ConflictMode;
}

function coerceConfigValue(
	cfg: ConfigContext,
	f: AnyFlag,
	value: unknown,
): unknown {
	try {
		return cfg.coerce(f, value);
	} catch (e) {
		throw new ParseError(errConfigValueError(f.name, (e as Error).message));
	}
}

function effectiveConflictMode(cfg: ConfigContext, f: AnyFlag): string {
	return flagOpts(f).conflictMode ?? cfg.conflictMode;
}

/**
 * Conflict-mode equality (pinned by the siblings): scalars exact, plain lists
 * order-sensitive, unique flags order-insensitive multiset equality.
 */
export function valuesEqualForConflict(
	cliVal: unknown,
	configVal: unknown,
	f: AnyFlag,
): boolean {
	if (
		flagOpts(f).unique === true &&
		Array.isArray(cliVal) &&
		Array.isArray(configVal)
	) {
		return multisetEqual(cliVal, configVal);
	}
	return deepEqualValues(cliVal, configVal);
}

function deepEqualValues(a: unknown, b: unknown): boolean {
	if (Object.is(a, b)) {
		return true;
	}
	if (Array.isArray(a) && Array.isArray(b)) {
		return a.length === b.length && a.every((v, i) => deepEqualValues(v, b[i]));
	}
	if (a instanceof Map && b instanceof Map) {
		if (a.size !== b.size) {
			return false;
		}
		for (const [k, v] of a) {
			if (!b.has(k) || !deepEqualValues(v, b.get(k))) {
				return false;
			}
		}
		return true;
	}
	return false;
}

function multisetEqual(a: readonly unknown[], b: readonly unknown[]): boolean {
	if (a.length !== b.length) {
		return false;
	}
	// Keyed by type + rendered value, mirroring Go's "%T:%v" counting.
	const counts = new Map<string, number>();
	const keyOf = (v: unknown): string => `${typeof v}:${String(v)}`;
	for (const v of a) {
		counts.set(keyOf(v), (counts.get(keyOf(v)) ?? 0) + 1);
	}
	for (const v of b) {
		counts.set(keyOf(v), (counts.get(keyOf(v)) ?? 0) - 1);
	}
	for (const c of counts.values()) {
		if (c !== 0) {
			return false;
		}
	}
	return true;
}

// --- Flag token lookups ---

interface FlagLookups {
	readonly long: Map<string, AnyFlag>;
	readonly short: Map<string, AnyFlag>;
	readonly negation: Map<string, AnyFlag>;
}

function isNegatableBool(f: AnyFlag): boolean {
	return f.schema === "bool" && flagOpts(f).negatable !== false;
}

function addToLookups(lookups: FlagLookups, flags: readonly AnyFlag[]): void {
	for (const f of flags) {
		lookups.long.set(`--${f.name}`, f);
		const short = flagOpts(f).short;
		if (short !== undefined && short !== "") {
			lookups.short.set(`-${short}`, f);
		}
		if (isNegatableBool(f)) {
			lookups.negation.set(`--no-${f.name}`, f);
		}
	}
}

function newLookups(flags: readonly AnyFlag[]): FlagLookups {
	const lookups: FlagLookups = {
		long: new Map(),
		short: new Map(),
		negation: new Map(),
	};
	addToLookups(lookups, flags);
	return lookups;
}

// --- Raw CLI value parsing (shared by global and command token loops) ---

/**
 * Parses one raw CLI value for a non-bool flag and stores it into cliSet,
 * handling dict merge (duplicate keys are hard errors), list append with
 * unique enforcement, and scalar coercion with @-prefix resolution.
 */
function parseRawFlagValue(
	f: AnyFlag,
	raw: string,
	cliSet: Map<string, unknown>,
	tracker: StdinTracker,
): void {
	const kind = schemaKind(f.schema);
	const elem = elemSchemaOf(f.carrier);
	if (kind === "dict") {
		const entries = parseDictValue(f.name, raw, elem);
		let target = cliSet.get(f.name) as Map<string, unknown> | undefined;
		if (target === undefined) {
			target = new Map();
			cliSet.set(f.name, target);
		}
		storeDictEntries(target, entries, f.name);
		return;
	}
	const value = coerceToScalar(f.name, raw, elem, tracker);
	if (kind === "list") {
		let list = cliSet.get(f.name) as unknown[] | undefined;
		if (list === undefined) {
			list = [];
			cliSet.set(f.name, list);
		}
		appendListValue(list, value, flagOpts(f).unique === true, f.name);
		return;
	}
	cliSet.set(f.name, value);
}

// --- Env and config resolution passes ---

function resolveEnvForFlags(
	flags: readonly AnyFlag[],
	cliSet: Map<string, unknown>,
	envNames: Set<string>,
	tracker: StdinTracker,
): void {
	for (const f of flags) {
		if (cliSet.has(f.name)) {
			continue;
		}
		const envVar = flagOpts(f).env;
		if (envVar === undefined) {
			continue;
		}
		const envVal = process.env[envVar];
		if (envVal === undefined) {
			continue;
		}
		cliSet.set(f.name, resolveEnvValue(f, envVar, envVal, tracker));
		envNames.add(f.name);
	}
}

/**
 * Applies config values to flags not set by CLI or env; in conflict mode
 * "error" a diverging config+cli/env overlap is a hard error. The
 * existingSource callback names the side config collided with.
 */
function applyConfigToFlags(
	flags: readonly AnyFlag[],
	cliSet: Map<string, unknown>,
	configNames: Set<string>,
	cfg: ConfigContext,
	existingSource: (f: AnyFlag) => string,
): void {
	const data = cfg.data;
	if (data === null) {
		return;
	}
	for (const f of flags) {
		const param = flagParamName(f.name);
		if (!Object.hasOwn(data, param)) {
			continue;
		}
		if (cliSet.has(f.name)) {
			// Conflict ONLY when the values diverge; identical values agree.
			if (effectiveConflictMode(cfg, f) === "error") {
				const coerced = coerceConfigValue(cfg, f, data[param]);
				if (!valuesEqualForConflict(cliSet.get(f.name), coerced, f)) {
					throw new ParseError(
						errFlagSetInBothAndConfig(f.name, existingSource(f)),
					);
				}
			}
			continue; // cli-wins, or error mode with matching values
		}
		const coerced = coerceConfigValue(cfg, f, data[param]);
		if (flagOpts(f).unique === true && Array.isArray(coerced)) {
			const dup = findDuplicate(coerced);
			if (dup !== undefined) {
				throw new ParseError(
					errConfigValueDuplicate(f.name, formatValueForError(dup)),
				);
			}
		}
		cliSet.set(f.name, coerced);
		configNames.add(f.name);
	}
}

// --- Defaults ---

interface DefaultedValue {
	readonly value: unknown;
	readonly source: SourceLabel;
}

/**
 * Resolves the value of a flag that was not provided by CLI, env, or config.
 * Throws ParseError when the flag is required. prefix is "" for command flags
 * and "global " for global flags.
 *
 * Infra seam: RelativeToRoot flag defaults (resolved through app.infraRoots,
 * source label "infra") land with the infra subphase; until the marker type
 * exists, every declared default resolves with source "default".
 */
function applyFlagDefault(
	f: AnyFlag,
	mutexFlagNames: ReadonlySet<string> | null,
	prefix: string,
): DefaultedValue {
	const o = flagOpts(f);
	const kind = schemaKind(f.schema);
	if (kind === "dict") {
		const dflt = o.default;
		return {
			value: dflt instanceof Map ? new Map(dflt) : new Map<string, unknown>(),
			source: "default",
		};
	}
	if (kind === "list") {
		const dflt = o.default;
		return {
			value: Array.isArray(dflt) ? [...dflt] : [],
			source: "default",
		};
	}
	if (o.default !== undefined && o.default !== null) {
		return { value: o.default, source: "default" };
	}
	if (o.default === null) {
		// default: null -- explicitly optional; the value is "not passed".
		return { value: undefined, source: "default" };
	}
	if (mutexFlagNames?.has(f.name)) {
		// Mutex groups enforce their own required semantics.
		return { value: undefined, source: "default" };
	}
	// Inline message templates, mirroring the siblings' inline fmt/f-strings.
	if (f.schema === "bool" && isNegatableBool(f)) {
		throw new ParseError(
			`${prefix}flag '--${f.name}' must be passed as --${f.name} or --no-${f.name}`,
		);
	}
	if (f.schema === "bool") {
		throw new ParseError(
			`${prefix}flag '--${f.name}' must be passed as --${f.name}`,
		);
	}
	throw new ParseError(`${prefix}flag '--${f.name}' is required`);
}

// --- Command parsing ---

export interface ParsedCommand {
	readonly kwargs: Record<string, unknown>;
	/** Global flag values parsed from post-command tokens, param-name-keyed. */
	readonly postGlobalValues: Record<string, unknown>;
	/** Param-name -> source label for command flags and post-command globals. */
	readonly sources: Record<string, string>;
}

/**
 * Parses tokens against a resolved command's flags and args. Global flags are
 * also recognized in post-command tokens and returned separately so the
 * caller can merge them with pre-command globals. Throws ParseError.
 */
export function parseCommand(
	cmd: RegisteredCommand,
	tokens: readonly string[],
	globalFlags: readonly AnyFlag[],
	cfg: ConfigContext | null,
	tracker: StdinTracker,
	hermetic: boolean,
): ParsedCommand {
	if (cmd.def.kind !== "command") {
		throw new Error(
			"internal: parseCommand requires a non-passthrough command",
		);
	}
	const def = cmd.def;
	const lookups = newLookups(cmd.flags);
	addToLookups(lookups, globalFlags);
	const globalFlagNames = new Set(globalFlags.map((f) => f.name));

	const cliSet = new Map<string, unknown>();
	const positionals: string[] = [];

	let i = 0;
	let stopFlags = false;
	while (i < tokens.length) {
		const tok = tokens[i] as string;

		if (stopFlags || !tok.startsWith("-") || tok === "-") {
			positionals.push(tok);
			i++;
			continue;
		}

		if (tok === "--") {
			stopFlags = true;
			i++;
			continue;
		}

		// --flag=value form
		if (tok.startsWith("--") && tok.includes("=")) {
			const eqPos = tok.indexOf("=");
			const flagPart = tok.slice(0, eqPos);
			const valuePart = tok.slice(eqPos + 1);
			const f = lookups.long.get(flagPart);
			if (f !== undefined) {
				if (f.schema === "bool") {
					throw new ParseError(errBoolFlagNoValue(flagPart));
				}
				parseRawFlagValue(f, valuePart, cliSet, tracker);
			} else if (lookups.negation.has(flagPart)) {
				throw new ParseError(errBoolNegationNoValue(flagPart));
			} else {
				throw new ParseError(errUnknownFlag(flagPart));
			}
			i++;
			continue;
		}

		// --no-flag negation
		const negated = lookups.negation.get(tok);
		if (negated !== undefined) {
			cliSet.set(negated.name, false);
			i++;
			continue;
		}

		// --flag (long form without =)
		if (tok.startsWith("--")) {
			const f = lookups.long.get(tok);
			if (f === undefined) {
				throw new ParseError(errUnknownFlag(tok));
			}
			if (f.schema === "bool") {
				cliSet.set(f.name, true);
				i++;
			} else {
				if (i + 1 >= tokens.length) {
					throw new ParseError(errFlagRequiresValue(tok));
				}
				parseRawFlagValue(f, tokens[i + 1] as string, cliSet, tracker);
				i += 2;
			}
			continue;
		}

		// -x (short form)
		if (tok.length === 2) {
			const f = lookups.short.get(tok);
			if (f !== undefined) {
				if (f.schema === "bool") {
					cliSet.set(f.name, true);
					i++;
				} else {
					if (i + 1 >= tokens.length) {
						throw new ParseError(errFlagRequiresValue(tok));
					}
					parseRawFlagValue(f, tokens[i + 1] as string, cliSet, tracker);
					i += 2;
				}
				continue;
			}
		}

		// Token starts with "-" but matches no known flag; treat as a
		// positional arg (e.g. negative numbers like -7, -3.14).
		positionals.push(tok);
		i++;
	}

	const envNames = new Set<string>();
	const configNames = new Set<string>();

	if (!hermetic) {
		resolveEnvForFlags(cmd.flags, cliSet, envNames, tracker);
		if (cfg !== null) {
			applyConfigToFlags(cmd.flags, cliSet, configNames, cfg, (f) =>
				envNames.has(f.name) ? "env" : "cli",
			);
			// Config-conflict detection for GLOBAL flags parsed AFTER the command
			// name. Detection ONLY: config values for globals were already applied
			// during the pre-command pass. Globals reaching cliSet here are purely
			// CLI-parsed, so the divergence source is always "cli".
			if (cfg.data !== null) {
				for (const f of globalFlags) {
					if (!cliSet.has(f.name)) {
						continue;
					}
					const param = flagParamName(f.name);
					if (!Object.hasOwn(cfg.data, param)) {
						continue;
					}
					if (effectiveConflictMode(cfg, f) !== "error") {
						continue;
					}
					const coerced = coerceConfigValue(cfg, f, cfg.data[param]);
					if (!valuesEqualForConflict(cliSet.get(f.name), coerced, f)) {
						throw new ParseError(errFlagSetInBothCliAndConfig(f.name));
					}
				}
			}
		}
	}

	const store = new SourcedStore();
	for (const [k, v] of cliSet) {
		if (envNames.has(k)) {
			store.set(k, v, "env");
		} else if (configNames.has(k)) {
			store.set(k, v, "config");
		} else {
			store.set(k, v, "cli");
		}
	}

	return validateAndBuildKwargs(
		cmd,
		def.args,
		store,
		positionals,
		globalFlagNames,
	);
}

/**
 * Second half of command parsing: mutex enforcement, implies resolution,
 * dependency checks, defaults, choices, custom validation, positional-arg
 * resolution, and kwargs assembly, all on sourced values.
 */
function validateAndBuildKwargs(
	cmd: RegisteredCommand,
	args: readonly AnyArg[],
	store: SourcedStore,
	positionals: readonly string[],
	globalFlagNames: ReadonlySet<string>,
): ParsedCommand {
	if (cmd.def.kind !== "command") {
		throw new Error("internal: passthrough commands are not parsed");
	}
	const def = cmd.def;

	// Mutex constraints (before defaults). Only cli/env/config sources count.
	for (const mg of def.mutex) {
		const mgFlags = Object.values(mg.flags);
		const setFlags = mgFlags
			.filter((f) => store.isPresentForMutex(f.name))
			.map((f) => `--${f.name}`);
		if (setFlags.length > 1) {
			throw new ParseError(errMutuallyExclusive(setFlags.join(" and ")));
		}
		if (setFlags.length === 0) {
			throw new ParseError(
				errOneOfRequired(mgFlags.map((f) => `--${f.name}`).join(", ")),
			);
		}
	}

	// Implies resolution (before dependency checks, so implied values
	// participate in downstream coRequired/requires validation).
	for (const dep of def.dependencies) {
		if (dep.kind !== "implies") {
			continue;
		}
		if (!store.isPresentForDeps(dep.flag)) {
			continue;
		}
		if (store.has(dep.implies)) {
			if (store.get(dep.implies) !== dep.value) {
				const neg = dep.value ? "" : "no-";
				const explicitNeg = dep.value ? "no-" : "";
				throw new ParseError(
					errImpliesConflict(dep.flag, neg, dep.implies, explicitNeg),
				);
			}
		} else {
			store.set(dep.implies, dep.value, "implied");
		}
	}

	// Dependency constraints: cli, env, config, implied count; default does not.
	for (const dep of def.dependencies) {
		if (dep.kind === "co-required") {
			const present = dep.flags.filter((n) => store.isPresentForDeps(n));
			if (present.length > 0 && present.length < dep.flags.length) {
				throw new ParseError(
					errFlagsMustBeUsedTogether(dep.flags.map((n) => `--${n}`).join(", ")),
				);
			}
		} else if (dep.kind === "requires") {
			if (
				store.isPresentForDeps(dep.flag) &&
				!store.isPresentForDeps(dep.dependsOn)
			) {
				throw new ParseError(errFlagRequiresFlag(dep.flag, dep.dependsOn));
			}
		}
	}

	const mutexFlagNames = new Set<string>();
	for (const mg of def.mutex) {
		for (const f of Object.values(mg.flags)) {
			mutexFlagNames.add(f.name);
		}
	}

	// Defaults
	for (const f of cmd.flags) {
		if (store.has(f.name)) {
			continue;
		}
		const { value, source } = applyFlagDefault(f, mutexFlagNames, "");
		store.set(f.name, value, source);
	}

	// Choices
	for (const f of cmd.flags) {
		if (store.has(f.name)) {
			validateChoices(
				f.name,
				store.get(f.name),
				schemaKind(f.schema) === "list",
				flagOpts(f).choices,
				false,
			);
		}
	}

	// Custom validation. An undefined value means the flag was not passed
	// (default: null or an unset mutex flag) -- nothing to validate.
	for (const f of cmd.flags) {
		const validate = flagOpts(f).validate;
		if (validate === undefined || !store.has(f.name)) {
			continue;
		}
		const val = store.get(f.name);
		const check = (v: unknown): void => {
			try {
				validate(v as never);
			} catch (e) {
				throw new ParseError(errFlagValueError(f.name, (e as Error).message));
			}
		};
		if (schemaKind(f.schema) === "list") {
			if (Array.isArray(val)) {
				for (const v of val) {
					check(v);
				}
			}
		} else if (val !== undefined && val !== null) {
			check(val);
		}
	}

	// Positional args
	const argValues = new Map<string, unknown>();
	const lastArg =
		args.length > 0 ? (args[args.length - 1] as AnyArg) : undefined;
	const hasVariadic = lastArg?.opts.variadic === true;
	const fixedArgs = hasVariadic ? args.slice(0, -1) : args;
	fixedArgs.forEach((a, idx) => {
		if (idx < positionals.length) {
			argValues.set(
				a.name,
				coerceArgValue(a.name, positionals[idx] as string, a.schema),
			);
		} else if (a.opts.required !== false) {
			throw new ParseError(errMissingRequiredArgument(a.name));
		} else if (a.opts.default !== undefined) {
			argValues.set(a.name, a.opts.default);
		}
		// Optional arg with no default: key omitted (the handler-args type
		// marks it `?:`), matching Python's omitted kwarg.
	});
	if (hasVariadic && lastArg !== undefined) {
		const remaining = positionals.slice(fixedArgs.length);
		if (lastArg.opts.required !== false && remaining.length === 0) {
			throw new ParseError(errMissingRequiredArgument(lastArg.name));
		}
		argValues.set(
			lastArg.name,
			remaining.map((p) => coerceArgValue(lastArg.name, p, lastArg.schema)),
		);
	} else if (positionals.length > args.length) {
		throw new ParseError(
			errUnexpectedArgument(positionals[args.length] as string),
		);
	}

	// Arg choices (after type coercion)
	for (const a of args) {
		if (argValues.has(a.name)) {
			const opts = a.opts as { readonly choices?: readonly unknown[] };
			validateChoices(
				a.name,
				argValues.get(a.name),
				a.opts.variadic === true,
				opts.choices,
				true,
			);
		}
	}

	// kwargs (command flags and args only; doParse merges globals)
	const kwargs: Record<string, unknown> = {};
	for (const f of cmd.flags) {
		kwargs[flagParamName(f.name)] = store.get(f.name);
	}
	for (const a of args) {
		if (argValues.has(a.name)) {
			kwargs[a.name] = argValues.get(a.name);
		}
	}

	const postGlobalValues: Record<string, unknown> = {};
	for (const name of globalFlagNames) {
		if (store.has(name)) {
			postGlobalValues[flagParamName(name)] = store.get(name);
		}
	}

	const rawSources = store.sourceMap();
	const sources: Record<string, string> = {};
	for (const f of cmd.flags) {
		const s = rawSources.get(f.name);
		if (s !== undefined) {
			sources[flagParamName(f.name)] = s;
		}
	}
	// Globals parsed post-command emit their source label too (always "cli"
	// here; env/config for globals resolve in the pre-command pass). Without
	// this, `tool cmd --global X` would report source "default".
	for (const name of globalFlagNames) {
		const s = rawSources.get(name);
		if (s !== undefined) {
			sources[flagParamName(name)] = s;
		}
	}

	return { kwargs, postGlobalValues, sources };
}

// --- Global flag extraction (pre-command phase) ---

export interface ExtractedGlobals {
	/** Param-name-keyed resolved global flag values. */
	readonly values: Record<string, unknown>;
	/** Param-name -> source label. */
	readonly sources: Record<string, string>;
	/** Tokens from the first non-global token onward (command region). */
	readonly remaining: readonly string[];
}

/**
 * Scans argv for global flag tokens before the command name. Stops at the
 * first non-flag token (the command name), at "--" (kept in remaining), or at
 * an unknown flag-like token. Resolves env, config, defaults, and choices for
 * global flags. Throws ParseError.
 */
export function extractGlobalFlags(
	app: AppImpl,
	argv: readonly string[],
	hermetic: boolean,
	tracker: StdinTracker,
	cfg: ConfigContext | null,
): ExtractedGlobals {
	if (app.globalFlags.length === 0) {
		return { values: {}, sources: {}, remaining: argv };
	}
	const lookups = newLookups(app.globalFlags);
	const cliSet = new Map<string, unknown>();

	let remaining: readonly string[] | null = null;
	let i = 0;
	while (i < argv.length) {
		const tok = argv[i] as string;

		// -- stops global flag parsing; include it in remaining
		if (tok === "--") {
			remaining = argv.slice(i);
			break;
		}

		// --flag=value form
		if (tok.startsWith("--") && tok.includes("=")) {
			const eqPos = tok.indexOf("=");
			const flagPart = tok.slice(0, eqPos);
			const valuePart = tok.slice(eqPos + 1);
			const f = lookups.long.get(flagPart);
			if (f !== undefined) {
				if (f.schema === "bool") {
					throw new ParseError(errBoolFlagNoValue(flagPart));
				}
				parseRawFlagValue(f, valuePart, cliSet, tracker);
				i++;
				continue;
			}
			if (lookups.negation.has(flagPart)) {
				throw new ParseError(errBoolNegationNoValue(flagPart));
			}
			// Not a global flag -- this is the command region.
			remaining = argv.slice(i);
			break;
		}

		// --no-flag negation
		const negated = lookups.negation.get(tok);
		if (negated !== undefined) {
			cliSet.set(negated.name, false);
			i++;
			continue;
		}

		// --flag (long form)
		const longFlag = tok.startsWith("--") ? lookups.long.get(tok) : undefined;
		if (longFlag !== undefined) {
			if (longFlag.schema === "bool") {
				cliSet.set(longFlag.name, true);
				i++;
			} else {
				if (i + 1 >= argv.length) {
					throw new ParseError(errFlagRequiresValue(tok));
				}
				parseRawFlagValue(longFlag, argv[i + 1] as string, cliSet, tracker);
				i += 2;
			}
			continue;
		}

		// -x (short form)
		const shortFlag =
			tok.startsWith("-") && tok.length === 2
				? lookups.short.get(tok)
				: undefined;
		if (shortFlag !== undefined) {
			if (shortFlag.schema === "bool") {
				cliSet.set(shortFlag.name, true);
				i++;
			} else {
				if (i + 1 >= argv.length) {
					throw new ParseError(errFlagRequiresValue(tok));
				}
				parseRawFlagValue(shortFlag, argv[i + 1] as string, cliSet, tracker);
				i += 2;
			}
			continue;
		}

		// Not a global flag -- command name or unknown token.
		remaining = argv.slice(i);
		break;
	}
	if (remaining === null) {
		remaining = [];
	}

	const sources: Record<string, string> = {};
	for (const name of cliSet.keys()) {
		sources[flagParamName(name)] = "cli";
	}

	if (!hermetic) {
		const envNames = new Set<string>();
		resolveEnvForFlags(app.globalFlags, cliSet, envNames, tracker);
		for (const name of envNames) {
			sources[flagParamName(name)] = "env";
		}
		if (cfg !== null) {
			const configNames = new Set<string>();
			applyConfigToFlags(
				app.globalFlags,
				cliSet,
				configNames,
				cfg,
				(f) => sources[flagParamName(f.name)] ?? "cli",
			);
			for (const name of configNames) {
				sources[flagParamName(name)] = "config";
			}
		}
	}

	// Defaults for global flags not set anywhere
	for (const f of app.globalFlags) {
		if (cliSet.has(f.name)) {
			continue;
		}
		const { value, source } = applyFlagDefault(f, null, "global ");
		cliSet.set(f.name, value);
		sources[flagParamName(f.name)] = source;
	}

	// Choices for global flags
	for (const f of app.globalFlags) {
		if (cliSet.has(f.name)) {
			validateChoices(
				f.name,
				cliSet.get(f.name),
				schemaKind(f.schema) === "list",
				flagOpts(f).choices,
				false,
			);
		}
	}

	const values: Record<string, unknown> = {};
	for (const [name, v] of cliSet) {
		values[flagParamName(name)] = v;
	}
	return { values, sources, remaining };
}

// --- Reserved-flag pre-scan ---

export interface PreScanResult {
	readonly dumpSchema: boolean;
	readonly serveMcp: boolean;
	readonly hermetic: boolean;
	readonly configPath: string | undefined;
	readonly err: string | undefined;
	/** argv with --config/--config=value/--hermetic stripped out. */
	readonly cleanedArgv: readonly string[];
}

/**
 * Position-aware pre-scan for --dump-schema, --mcp, --config, and --hermetic
 * in the pre-command region only (before the first non-flag token, before
 * "--"). Known global flags and their values are skipped so a global-flag
 * value that looks like a command name does not end the region early.
 */
export function preScanReservedFlags(
	app: AppImpl,
	argv: readonly string[],
): PreScanResult {
	const knownFlags = new Map<string, boolean>(); // token -> takes a value
	for (const f of app.globalFlags) {
		const takesValue = f.schema !== "bool";
		knownFlags.set(`--${f.name}`, takesValue);
		const short = flagOpts(f).short;
		if (short !== undefined && short !== "") {
			knownFlags.set(`-${short}`, takesValue);
		}
		if (isNegatableBool(f)) {
			knownFlags.set(`--no-${f.name}`, false);
		}
	}

	let hermetic = false;
	let configPath: string | undefined;
	const excludeIndices = new Set<number>();
	const done = (err?: string): PreScanResult => {
		const cleanedArgv =
			excludeIndices.size > 0
				? argv.filter((_, j) => !excludeIndices.has(j))
				: argv;
		return {
			dumpSchema: false,
			serveMcp: false,
			hermetic,
			configPath,
			err,
			cleanedArgv,
		};
	};

	let i = 0;
	while (i < argv.length) {
		const tok = argv[i] as string;

		// -- terminates the pre-command region
		if (tok === "--") {
			break;
		}
		// Non-flag token = command name: stop scanning
		if (!tok.startsWith("-") || tok === "-") {
			break;
		}

		if (tok === "--dump-schema") {
			return { ...done(), dumpSchema: true };
		}
		if (tok === "--mcp") {
			return { ...done(), serveMcp: true };
		}
		if (tok === "--hermetic") {
			hermetic = true;
			excludeIndices.add(i);
			i++;
			continue;
		}
		if (tok.startsWith("--config=")) {
			if (!app.configEnabled) {
				return done(
					"--config is not available: this app does not use config files",
				);
			}
			const val = tok.slice("--config=".length);
			if (val === "") {
				return done(errFlagRequiresValue("--config"));
			}
			configPath = val;
			excludeIndices.add(i);
			i++;
			continue;
		}
		if (tok === "--config") {
			if (!app.configEnabled) {
				return done(
					"--config is not available: this app does not use config files",
				);
			}
			if (i + 1 >= argv.length) {
				return done(errFlagRequiresValue("--config"));
			}
			configPath = argv[i + 1] as string;
			excludeIndices.add(i);
			excludeIndices.add(i + 1);
			i += 2;
			continue;
		}

		// Known global flag with --flag=value form: skip
		if (tok.startsWith("--") && tok.includes("=")) {
			const flagPart = tok.slice(0, tok.indexOf("="));
			if (knownFlags.has(flagPart)) {
				i++;
				continue;
			}
			break; // unknown flag-like token before command name: stop
		}

		// Known global flag: skip it (and its value if non-bool)
		const takesValue = knownFlags.get(tok);
		if (takesValue !== undefined) {
			i += takesValue ? 2 : 1;
			continue;
		}

		break; // unknown flag-like token before command name: stop
	}

	return done();
}

// --- doParse ---

export type HelpTarget =
	| { readonly level: "app" }
	| {
			readonly level: "group";
			readonly group: GroupImpl;
			readonly path: readonly string[];
	  }
	| {
			readonly level: "command";
			readonly cmd: RegisteredCommand;
			readonly path: readonly string[];
	  };

export type ParseOutcome =
	| { readonly kind: "help"; readonly target: HelpTarget }
	| { readonly kind: "version"; readonly text: string }
	| { readonly kind: "dump-schema" }
	| { readonly kind: "mcp" }
	| {
			readonly kind: "parse-error";
			readonly message: string;
			readonly commandPrefix?: string;
	  }
	| {
			readonly kind: "command";
			readonly cmd: RegisteredCommand;
			readonly cmdPath: string;
			readonly kwargs: Record<string, unknown>;
			readonly globalKwargs: Record<string, unknown>;
			readonly sources: Record<string, string>;
	  }
	| {
			readonly kind: "passthrough";
			readonly cmd: RegisteredCommand;
			readonly cmdPath: string;
			readonly args: readonly string[];
			readonly globalKwargs: Record<string, unknown>;
	  };

export interface DoParseDeps {
	readonly config?: ConfigProvider;
}

/** Checks if --help or -h appears in tokens before any "--" separator. */
export function tokensContainHelp(tokens: readonly string[]): boolean {
	for (const tok of tokens) {
		if (tok === "--") {
			return false;
		}
		if (tok === "--help" || tok === "-h") {
			return true;
		}
	}
	return false;
}

function parseErrorOutcome(e: unknown, commandPrefix?: string): ParseOutcome {
	if (e instanceof ParseError) {
		return {
			kind: "parse-error",
			message: e.message,
			...(commandPrefix !== undefined ? { commandPrefix } : {}),
		};
	}
	throw e;
}

/**
 * Parses argv (without program name) into a ParseOutcome. Exactly one variant
 * applies: help, version, dump-schema, mcp, parse-error, command, or
 * passthrough.
 */
export function doParse(
	app: AppImpl,
	argv: readonly string[],
	deps?: DoParseDeps,
): ParseOutcome {
	// Fresh stdin tracking per parse invocation (@- is single-use).
	const tracker = newStdinTracker();

	// App-level --help/-h and --version/-v as the only token
	if (
		argv.length === 0 ||
		(argv.length === 1 && (argv[0] === "--help" || argv[0] === "-h"))
	) {
		return { kind: "help", target: { level: "app" } };
	}
	if (argv.length === 1 && (argv[0] === "--version" || argv[0] === "-v")) {
		return { kind: "version", text: `${app.name} ${app.version}` };
	}

	const pre = preScanReservedFlags(app, argv);
	if (pre.dumpSchema) {
		return { kind: "dump-schema" };
	}
	if (pre.serveMcp) {
		return { kind: "mcp" };
	}
	if (pre.err !== undefined) {
		return { kind: "parse-error", message: pre.err };
	}
	if (pre.hermetic && pre.configPath !== undefined) {
		return {
			kind: "parse-error",
			message: errHermeticConfigMutuallyExclusive(),
		};
	}

	// Config loading (Phase-5 seam). Hermetic skips it entirely.
	let cfg: ConfigContext | null = null;
	let configLoadErr: string | undefined;
	if (app.configEnabled && !pre.hermetic) {
		const provider = deps?.config ?? emptyConfigProvider;
		const loaded = provider.load(pre.configPath);
		if (loaded.parseErr !== undefined && loaded.parseErr !== "") {
			configLoadErr = loaded.parseErr;
			cfg = {
				data: {},
				coerce: provider.coerce.bind(provider),
				conflictMode: app.configConflictMode,
			};
		} else {
			cfg = {
				data: loaded.data,
				coerce: provider.coerce.bind(provider),
				conflictMode: app.configConflictMode,
			};
		}
	}

	// Global flags from cleaned argv (--config/--hermetic stripped)
	let globals: ExtractedGlobals;
	try {
		globals = extractGlobalFlags(
			app,
			pre.cleanedArgv,
			pre.hermetic,
			tracker,
			cfg,
		);
	} catch (e) {
		return parseErrorOutcome(e);
	}

	// If global flag parsing stopped at --, strip it before routing
	let rest = globals.remaining;
	if (rest.length > 0 && rest[0] === "--") {
		rest = rest.slice(1);
	}

	// After extracting globals, check for help/version again
	if (
		rest.length === 0 ||
		(rest.length === 1 && (rest[0] === "--help" || rest[0] === "-h"))
	) {
		return { kind: "help", target: { level: "app" } };
	}
	if (rest.length === 1 && (rest[0] === "--version" || rest[0] === "-v")) {
		return { kind: "version", text: `${app.name} ${app.version}` };
	}

	const route = resolveCommand(app, rest);
	if (route.err !== undefined) {
		return {
			kind: "parse-error",
			message: route.err,
			...(route.commandPrefix !== undefined
				? { commandPrefix: route.commandPrefix }
				: {}),
		};
	}
	if (route.helpAtGroup) {
		return {
			kind: "help",
			target: {
				level: "group",
				group: route.lastGroup as GroupImpl,
				path: route.path,
			},
		};
	}

	const cmd = route.cmd as RegisteredCommand;
	const cmdRest = route.rest;
	const path = route.path;
	const cmdPath = [...path, cmd.name].join(".");

	// Command-level --help anywhere in remaining tokens (before any "--")
	if (tokensContainHelp(cmdRest)) {
		return { kind: "help", target: { level: "command", cmd, path } };
	}

	// Config subcommand exemption (self-lock prevention): edit/path/set work
	// on broken configs; the full exemption behavior lands in Phase 5 with
	// the auto-registered config group.
	const isConfigSubcommand = path.length > 0 && path[0] === "config";
	if (pre.hermetic && isConfigSubcommand) {
		return { kind: "parse-error", message: errHermeticWithConfigCommands() };
	}
	if (configLoadErr !== undefined && !isConfigSubcommand) {
		return { kind: "parse-error", message: configLoadErr };
	}
	// Phase-5 seam: stash configLoadErr for `config show`, and validate
	// declared config fields for non-config subcommands.

	// Passthrough: skip all flag/arg parsing, forward raw args
	if (cmd.kind === "passthrough") {
		return {
			kind: "passthrough",
			cmd,
			cmdPath,
			args: cmdRest,
			globalKwargs: globals.values,
		};
	}

	let parsed: ParsedCommand;
	try {
		parsed = parseCommand(
			cmd,
			cmdRest,
			app.globalFlags,
			cfg,
			tracker,
			pre.hermetic,
		);
	} catch (e) {
		return parseErrorOutcome(e, [app.name, ...path, cmd.name].join(" "));
	}

	// Merge global values: post-command globals override pre-command ones
	const globalKwargs: Record<string, unknown> = {
		...globals.values,
		...parsed.postGlobalValues,
	};
	const kwargs: Record<string, unknown> = { ...parsed.kwargs, ...globalKwargs };

	// Merge global sources into command sources. For a global set
	// post-command, parseCommand already placed the correct (cli) source, so
	// the pre-command label (typically "default") must NOT overwrite it.
	const sources: Record<string, string> = { ...parsed.sources };
	for (const [k, v] of Object.entries(globals.sources)) {
		if (Object.hasOwn(parsed.postGlobalValues, k)) {
			continue; // post-command position wins
		}
		sources[k] = v;
	}

	return { kind: "command", cmd, cmdPath, kwargs, globalKwargs, sources };
}

// --- Parse-error surface ---

/**
 * Renders the exact two-line stderr surface for a parse error:
 * "error: <msg>\ntry '<prefix> --help'\n". The prefix is the routed command
 * prefix when available, else the app name.
 */
export function formatParseErrorOutput(
	app: AppImpl,
	message: string,
	commandPrefix?: string,
): string {
	const prefix =
		commandPrefix !== undefined && commandPrefix !== ""
			? commandPrefix
			: app.name;
	return `error: ${message}\ntry '${prefix} --help'\n`;
}
