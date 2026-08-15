/**
 * Programmatic invocation: app.call(commandPath, kwargs) runs a command
 * in-process with pre-typed values, bypassing CLI parsing and env resolution.
 * It also skips config loading and stdin handling. Mirrors Go invoke.go with
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
import {
	Context,
	contextPayload,
	NO_RESERVED_FLAGS,
	type ReservedFlags,
	type Writer,
} from "./context.js";
import type { Effect } from "./effects.js";
import { attachProvidedFields } from "./elected.js";
import {
	errCallConsequentialUnconsented,
	errCallPathIsGroup,
	errDictFlagExpectedMapType,
	errFlagInvalidChoice,
	errFlagRequiresValue,
	errOneOfRequired,
	errPassthroughArgsNotStringSlice,
	errScopeSuffix,
	errUnknownParameterForCommand,
	errUnknownParameterForPassthroughCommand,
	InvokeError,
	ParseError,
} from "./errors.js";
import {
	type AnyChoiceFlag,
	type AnyCommand,
	type AnyFlag,
	CHOICE_TAG_KEY,
	CHOICE_VALUE_KEY,
	memberList,
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
import { formatChoices } from "./values.js";

/** Sinks for invoke contexts: structured data flows back through the Outcome. */
const discard: Writer = { write: () => {} };

/**
 * Per-call state that is NOT a handler kwarg. TS takes it as a trailing
 * options object -- the idiomatic counterpart of Python's keyword-only
 * argument and Go's variadic CallOption.
 */
export interface CallOptions {
	/**
	 * The caller's explicit consent, the programmatic counterpart of the CLI's
	 * --approve-consequential. A command that declares itself consequential is
	 * refused without it; read-only and plain mutating commands are
	 * unaffected.
	 */
	readonly approveConsequential?: boolean;
}

/**
 * Reads a registered command's effects-regime classification (schema.ts
 * serializeCommand reads the same two carrier fields). Shared by the invoke
 * consent check and the tool/MCP descriptors.
 */
export function commandClassification(cmd: RegisteredCommand): {
	readonly effect: Effect;
	readonly consequential: boolean;
} {
	const carrier = cmd.def as {
		readonly effect: Effect;
		readonly consequential?: boolean;
	};
	return {
		effect: carrier.effect,
		consequential: carrier.consequential === true,
	};
}

function isConsequential(cmd: RegisteredCommand): boolean {
	return commandClassification(cmd).consequential;
}

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
		return applyFlagDefault(f, prefix, infraRoots);
	} catch (e) {
		if (e instanceof ParseError) {
			throw new InvokeError(e.message);
		}
		throw e;
	}
}

/**
 * Interprets the handler's (awaited) return for call():
 * - a payload supplied through ctx.payload -> the payload (contract §19.4)
 * - bare undefined -> undefined (Python's None; Go handlers cannot express it)
 * - otherwise -> the exit code
 */
function interpretForCall(result: unknown, ctx: Context): unknown {
	const interpreted = interpretHandlerReturn(result);
	const supplied = contextPayload(ctx);
	if (supplied.set) {
		return supplied.value;
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
	opts: CallOptions = {},
): Promise<unknown> {
	const approveConsequential = opts.approveConsequential === true;
	// The caller's declaration is delivered to the handler on the Context, so a
	// handler (or an audit record) can see how the run was consented to.
	const reserved: ReservedFlags = {
		...NO_RESERVED_FLAGS,
		approveConsequential,
	};
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

	// The consent check (contract §8.5). There is no terminal here, so the
	// confirm protocol's PROMPT cannot fire -- the caller must have said so in
	// the call. Checked before anything is dispatched or recorded.
	if (isConsequential(cmd) && !approveConsequential) {
		throw new InvokeError(errCallConsequentialUnconsented(commandPath));
	}

	// Start a new dispatch BEFORE coverage recording so pre-handler
	// CACHE_WRITEs land in this dispatch's effect log.
	app.beginDispatch();
	// Record test-coverage hit (command-level only).
	if (app.testCoverage) {
		recordCoverage(app, commandPath);
	}

	if (cmd.kind === "passthrough") {
		return invokePassthrough(app, cmd, commandPath, kwargs, reserved);
	}
	const def = cmd.def as AnyCommand;

	// Reverse mapping: flag name (with dashes) -> flag definition.
	const flagByName = new Map<string, AnyFlag>();
	for (const f of cmd.flags) {
		flagByName.set(f.name, f);
	}
	const argNames = new Set(def.args.map((a) => a.name));

	// Selectors declared at command level, by dash name. `call()` takes the
	// ELECTED RECORD, pre-typed (contract §24.11): the programmatic front
	// door's contract is unchanged -- pre-typed values, no parsing -- so the
	// value for a selector is the same record a handler receives.
	const selectorByName = new Map<string, AnyChoiceFlag>();
	for (const d of def.allDecls) {
		if (d.kind === "choice-flag") {
			selectorByName.set(d.name, d);
		}
	}

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
		const sel = selectorByName.get(flagName);
		if (sel !== undefined) {
			try {
				store.set(flagName, validateElectedRecord(sel, value), "cli");
			} catch (e) {
				throw new InvokeError((e as Error).message);
			}
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
	// A selector with no kwarg elects from its declaration, exactly as the
	// argv path's election phase does: its default, or the required refusal.
	for (const [name, sel] of selectorByName) {
		if (store.has(name)) {
			continue;
		}
		if (sel.opts.presence === "default" && sel.opts.default !== undefined) {
			store.set(name, electDefaultRecord(sel, sel.opts.default), "default");
			continue;
		}
		throw new InvokeError(
			sel.electBy === "member-flags"
				? errOneOfRequired(memberList(sel), "")
				: `flag '--${name}' is required`,
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
			[...selectorByName.keys()],
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
	//
	// Programmatic dispatch never PROMPTS and never emits the non-TTY error:
	// the requirement is honoured by the consent check above instead.
	// --dry-run is likewise not reachable here (argv parsing is bypassed
	// entirely), so the effects handle is armed in live mode -- but it IS
	// armed, because the seal is mandatory at every ctx-construction site.
	const ctx = new Context(
		discard,
		discard,
		sources,
		buildInfraAccess(
			app.infraRoots,
			app.handshakeEnvs,
			app.connectionEnvs,
			false,
		),
		reserved,
		app.armEffects(cmd, commandPath, false, reserved),
		cmd.name,
		def.payloadSchema ?? null,
	);
	const result = await def.handler(validated as never, ctx);
	return interpretForCall(result, ctx);
}

async function invokePassthrough(
	app: AppImpl,
	cmd: RegisteredCommand,
	commandPath: string,
	kwargs: Readonly<Record<string, unknown>>,
	reserved: ReservedFlags,
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
		buildInfraAccess(
			app.infraRoots,
			app.handshakeEnvs,
			app.connectionEnvs,
			false,
		),
		reserved,
		app.armEffects(cmd, commandPath, false, reserved),
		cmd.name,
		(cmd.def as PassthroughDef<string>).payloadSchema ?? null,
	);
	const def = cmd.def as PassthroughDef<string>;
	const result = await def.handler({ name: cmd.name, args, globals }, ctx);
	return interpretForCall(result, ctx);
}

// --- Elected records on the programmatic front door (contract §24.11) ---

/**
 * Validates one pre-typed elected record against its selector's declaration:
 * the tag names a declared choice, every required sub-flag is present, an
 * optional one delivers absence as a PRESENT field, and a defaulted one is
 * filled from the declaration. Unknown fields are refused -- a key the scope
 * never declared is the same mistake an unknown parameter is one level up.
 */
function validateElectedRecord(sel: AnyChoiceFlag, value: unknown): unknown {
	if (typeof value !== "object" || value === null) {
		throw new Error(
			`flag '--${sel.name}': the elected value must be a record carrying its '${CHOICE_TAG_KEY}' tag`,
		);
	}
	const raw = value as Record<string, unknown>;
	const tag = raw[CHOICE_TAG_KEY];
	if (typeof tag !== "string" || !Object.hasOwn(sel.choices, tag)) {
		throw new Error(
			errFlagInvalidChoice(
				sel.name,
				String(tag),
				formatChoices(Object.keys(sel.choices)),
			),
		);
	}
	const chosen = sel.choices[tag] as NonNullable<(typeof sel.choices)[string]>;
	const out: Record<string, unknown> = { [CHOICE_TAG_KEY]: tag };
	const provided = new Set<string>();
	if (chosen.value !== undefined) {
		if (!Object.hasOwn(raw, CHOICE_VALUE_KEY)) {
			// A member flag is elected by its own token and that token CARRIES the
			// payload, so a record electing one with no `value` is the command
			// line's own `--<member>` with nothing after it, and takes that
			// sentence. The ordinary required-flag message is refused for it: a
			// member flag's scope path stops at the scope that OWNS it (§12.13), so
			// that message would render the member as its own owner.
			throw new Error(errFlagRequiresValue(`--${tag}`));
		}
		out[CHOICE_VALUE_KEY] = raw[CHOICE_VALUE_KEY];
		provided.add(CHOICE_VALUE_KEY);
	}
	const path =
		sel.electBy === "member-flags" ? `--${tag}` : `--${sel.name} ${tag}`;
	const declared = new Set<string>([CHOICE_TAG_KEY, CHOICE_VALUE_KEY]);
	for (const [key, sub] of Object.entries(chosen.flags)) {
		declared.add(key);
		if (sub.kind === "choice-flag") {
			if (Object.hasOwn(raw, key)) {
				out[key] = validateElectedRecord(sub, raw[key]);
				provided.add(key);
			} else if (
				sub.opts.presence === "default" &&
				sub.opts.default !== undefined
			) {
				out[key] = electDefaultRecord(sub, sub.opts.default);
			} else {
				throw new Error(
					sub.electBy === "member-flags"
						? `${errOneOfRequired(memberList(sub), "")}${errScopeSuffix(path)}`
						: `flag '--${sub.name}' is required${errScopeSuffix(path)}`,
				);
			}
			continue;
		}
		if (Object.hasOwn(raw, key)) {
			out[key] = coerceInvokeValue(sub, raw[key]);
			provided.add(key);
			continue;
		}
		if (sub.opts.presence === "required") {
			throw new Error(
				`flag '--${sub.name}' is required${errScopeSuffix(path)}`,
			);
		}
		out[key] = sub.opts.presence === "default" ? sub.opts.default : undefined;
	}
	for (const key of Object.keys(raw)) {
		if (!declared.has(key)) {
			throw new Error(
				`flag '--${key}' is only valid under '${path}', but that scope does not declare it`,
			);
		}
	}
	attachProvidedFields(out, provided);
	return out;
}

/**
 * The record a selector's own `default` elects. A defaulted selection is
 * COMPLETE by registration (§24.5), so every sub-flag resolves from its own
 * declaration and nothing can be missing.
 */
function electDefaultRecord(sel: AnyChoiceFlag, choiceName: string): unknown {
	const chosen = sel.choices[choiceName];
	const out: Record<string, unknown> = { [CHOICE_TAG_KEY]: choiceName };
	for (const [key, sub] of Object.entries(chosen?.flags ?? {})) {
		if (sub.kind === "choice-flag") {
			out[key] =
				sub.opts.default === undefined
					? undefined
					: electDefaultRecord(sub, sub.opts.default);
			continue;
		}
		out[key] = sub.opts.presence === "default" ? sub.opts.default : undefined;
	}
	attachProvidedFields(out, new Set());
	return out;
}
