/**
 * Programmatic invocation: app.call(commandPath, kwargs) runs a command
 * in-process with pre-typed values, bypassing CLI parsing, env var
 * resolution, config loading, and stdin handling. Mirrors Go invoke.go with
 * Python _invoke/call as the divergence ground truth where the two differ
 * (group-path message, undefined-return value).
 *
 * commandPath uses dot-separated segments ("deploy", "dns.zone.create").
 * kwargs keys use underscored parameter names ("dry_run", not "--dry-run").
 * Passthrough commands take the raw argument list under the special "_args"
 * key. Failures throw InvokeError (errors.ts) instead of printing to stderr.
 */

import type { AppImpl, RegisteredCommand } from "./app.js";
import { recordCoverage } from "./checks/coverage.js";
import { validateCheckRegistrations } from "./checks/framework.js";
import { Context, type Writer } from "./context.js";
import {
	errCallPathIsGroup,
	errDictFlagExpectedMapType,
	errPassthroughArgsNotStringSlice,
	errUnknownParameterForCommand,
	errUnknownParameterForPassthroughCommand,
	InvokeError,
	ParseError,
} from "./errors.js";
import {
	type AnyCommand,
	type AnyFlag,
	type PassthroughDef,
	schemaKind,
} from "./factories.js";
import { buildInfraAccess } from "./infra.js";
import { interpretHandlerReturn } from "./outcome.js";
import {
	applyFlagDefault,
	flagParamName,
	validateAndBuildKwargs,
} from "./parse.js";
import { resolveCommand } from "./routing.js";
import { SourcedStore } from "./sources.js";

/** Sinks for invoke contexts: structured data flows back through the Outcome. */
const discard: Writer = { write: () => {} };

/** Converts a parameter name like "dry_run" back to a flag name "dry-run". */
function paramToFlagName(param: string): string {
	return param.replaceAll("_", "-");
}

/** Runtime type name for the dict-coercion error (TS vocabulary; Go %T slot). */
function invokeTypeName(v: unknown): string {
	if (v === null) {
		return "null";
	}
	if (Array.isArray(v)) {
		return "Array";
	}
	if (typeof v === "object") {
		const ctor = (v as { constructor?: { name?: string } }).constructor?.name;
		return ctor !== undefined && ctor !== "" ? ctor : "object";
	}
	return typeof v;
}

/**
 * Converts a caller-provided value to the internal representation expected by
 * the validation pipeline (Go coerceInvokeValue). Dict flags accept a Map
 * (passed through) or a plain object (converted to a Map); anything else is
 * an InvokeError. Lists and scalars pass through as-is -- values are
 * pre-typed by the caller.
 */
function coerceInvokeValue(f: AnyFlag, value: unknown): unknown {
	if (schemaKind(f.schema) === "dict") {
		return coerceInvokeDict(f, value);
	}
	return value;
}

function coerceInvokeDict(f: AnyFlag, value: unknown): Map<string, unknown> {
	if (value instanceof Map) {
		return value as Map<string, unknown>;
	}
	if (typeof value === "object" && value !== null && !Array.isArray(value)) {
		return new Map(Object.entries(value));
	}
	throw new InvokeError(
		errDictFlagExpectedMapType(f.name, invokeTypeName(value)),
	);
}

/** Wraps applyFlagDefault, converting its ParseError into an InvokeError. */
function applyFlagDefaultForInvoke(
	f: AnyFlag,
	prefix: string,
	infraRoots: ReadonlyMap<string, string>,
): { value: unknown; source: string } {
	try {
		return applyFlagDefault(f, null, prefix, infraRoots);
	} catch (e) {
		if (e instanceof ParseError) {
			throw new InvokeError(e.message);
		}
		throw e;
	}
}

/**
 * Interprets the handler's (awaited) return for call():
 * - outcome with data -> the data
 * - bare undefined -> undefined (Python's None; Go handlers cannot express it)
 * - otherwise -> the exit code (integer returns and data-less outcomes)
 */
function interpretForCall(result: unknown): unknown {
	const interpreted = interpretHandlerReturn(result);
	if (interpreted.hasData) {
		return interpreted.data;
	}
	if (result === undefined) {
		return undefined;
	}
	return interpreted.exitCode;
}

/** Stringifies one positional-arg kwarg for the shared coercion pipeline. */
function positionalString(v: unknown): string {
	return String(v);
}

/**
 * The implementation behind App.call(). Resolves the command, populates a
 * SourcedStore from kwargs (marked "cli" so mutex/dependency checks see
 * them), runs the shared validation pipeline, and awaits the handler.
 */
export async function invokeApp(
	app: AppImpl,
	commandPath: string,
	kwargs: Readonly<Record<string, unknown>>,
): Promise<unknown> {
	// Validate registrations (Go invoke: check registrations + tag contracts).
	const checkErr = validateCheckRegistrations(app.checks);
	if (checkErr !== undefined) {
		throw new InvokeError(checkErr);
	}
	const tagErr = app.validateTagContracts();
	if (tagErr !== undefined) {
		throw new InvokeError(tagErr);
	}

	const route = resolveCommand(app, commandPath.split("."));
	if (route.err !== undefined) {
		throw new InvokeError(route.err);
	}
	if (route.cmd === undefined) {
		throw new InvokeError(errCallPathIsGroup(commandPath));
	}
	const cmd = route.cmd;

	// Record test-coverage hit (command-level only).
	if (app.testCoverage) {
		recordCoverage(app, commandPath);
	}

	if (cmd.kind === "passthrough") {
		return invokePassthrough(app, cmd, commandPath, kwargs);
	}
	const def = cmd.def as AnyCommand;

	// Reverse mapping: flag name (with dashes) -> flag definition.
	const flagByName = new Map<string, AnyFlag>();
	for (const f of cmd.flags) {
		flagByName.set(f.name, f);
	}
	const argNames = new Set(def.args.map((a) => a.name));

	// Populate the sourced store from kwargs, mapping param names back to
	// flag names. Provided kwargs are marked "cli"; absent flags get their
	// defaults inside validateAndBuildKwargs.
	const store = new SourcedStore();
	for (const [paramName, value] of Object.entries(kwargs)) {
		const flagName = paramToFlagName(paramName);
		const f = flagByName.get(flagName);
		if (f !== undefined) {
			store.set(flagName, coerceInvokeValue(f, value), "cli");
			continue;
		}
		if (app.globalFlagNames.has(flagName)) {
			store.set(flagName, value, "cli");
			continue;
		}
		if (argNames.has(paramName)) {
			continue; // handled below in arg declaration order
		}
		throw new InvokeError(
			errUnknownParameterForCommand(paramName, commandPath),
		);
	}

	// Positionals from kwargs in arg declaration order; the shared pipeline
	// re-coerces them from strings, exactly like CLI tokens.
	const positionals: string[] = [];
	for (const a of def.args) {
		if (!Object.hasOwn(kwargs, a.name)) {
			continue;
		}
		const val = kwargs[a.name];
		if (a.opts.variadic === true && Array.isArray(val)) {
			for (const item of val) {
				positionals.push(positionalString(item));
			}
		} else {
			positionals.push(positionalString(val));
		}
	}

	let validated: Record<string, unknown>;
	let sources: Record<string, string>;
	try {
		const parsed = validateAndBuildKwargs(
			cmd,
			def.args,
			store,
			positionals,
			app.globalFlagNames,
			app.infraRoots,
		);
		validated = { ...parsed.kwargs, ...parsed.postGlobalValues };
		sources = { ...parsed.sources };
	} catch (e) {
		if (e instanceof ParseError) {
			throw new InvokeError(e.message);
		}
		throw e;
	}

	// Apply global flag defaults for globals not provided in kwargs.
	for (const gf of app.globalFlags) {
		const param = flagParamName(gf.name);
		if (Object.hasOwn(validated, param)) {
			continue;
		}
		const { value, source } = applyFlagDefaultForInvoke(
			gf,
			"global ",
			app.infraRoots,
		);
		validated[param] = value;
		sources[param] = source;
	}

	// Stdout/stderr are discarded for invoke (Go io.Discard): structured data
	// flows back through the return value, not the streams.
	const ctx = new Context(
		discard,
		discard,
		sources,
		buildInfraAccess(app.infraRoots, app.handshakeEnvs),
	);
	const result = await def.handler(validated as never, ctx);
	return interpretForCall(result);
}

async function invokePassthrough(
	app: AppImpl,
	cmd: RegisteredCommand,
	commandPath: string,
	kwargs: Readonly<Record<string, unknown>>,
): Promise<unknown> {
	let args: readonly string[] = [];
	if (Object.hasOwn(kwargs, "_args")) {
		const rawArgs = kwargs._args;
		if (
			!Array.isArray(rawArgs) ||
			!rawArgs.every((a) => typeof a === "string")
		) {
			throw new InvokeError(errPassthroughArgsNotStringSlice());
		}
		args = rawArgs;
	}

	const globalParamNames = new Set(
		app.globalFlags.map((gf) => flagParamName(gf.name)),
	);
	for (const key of Object.keys(kwargs)) {
		if (key === "_args") {
			continue;
		}
		if (!globalParamNames.has(key)) {
			throw new InvokeError(
				errUnknownParameterForPassthroughCommand(key, commandPath),
			);
		}
	}

	const globals: Record<string, unknown> = {};
	for (const gf of app.globalFlags) {
		const param = flagParamName(gf.name);
		if (Object.hasOwn(kwargs, param)) {
			globals[param] = kwargs[param];
		} else {
			globals[param] = applyFlagDefaultForInvoke(
				gf,
				"global ",
				app.infraRoots,
			).value;
		}
	}

	const ctx = new Context(
		discard,
		discard,
		{},
		buildInfraAccess(app.infraRoots, app.handshakeEnvs),
	);
	const def = cmd.def as PassthroughDef<string>;
	const result = await def.handler({ name: cmd.name, args, globals }, ctx);
	return interpretForCall(result);
}
