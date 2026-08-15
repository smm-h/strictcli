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
import { coerceConfigValueForFlag, widenJsonIntegers } from "./config.js";
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
	errFlagRequired,
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
	requiredFlagForm,
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
import { firstProblem, type ParseProblem, STAGE } from "./scopeparse.js";
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
export function paramToFlagName(param: string): string {
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
 * the validation pipeline (Go coerceInvokeValue), and CHECKS it against the
 * declaration it was supplied against (contract §24.11, §23.4).
 *
 * "Pre-typed" has always meant ALREADY OF THE DECLARED TYPE, never exempt from
 * the declaration: a front door that does no parsing still has a declaration
 * saying what the value may be, and the closed-set half of it (`choices`) is
 * consulted on this path already. So the type half is consulted too, by the
 * check the config reader runs over an already-typed document -- a flat object
 * and a config document pose the identical question.
 *
 * `null` and `undefined` are legal for nothing. Optionality has ONE spelling
 * (§23.4): a flag that may be absent declares `optional` and is delivered
 * absent when its key is simply not there, so a null says nothing the
 * declaration cannot already say -- and on a required flag it would answer the
 * presence rule with a value the declaration forbids.
 *
 * Dict flags keep their own shape refusal, which is the one both this door and
 * Go's already print, and their entries are then checked like any others.
 */
function coerceInvokeValue(f: AnyFlag, value: unknown): unknown {
	let checked = value;
	if (schemaKind(f.schema) === "dict") {
		checked = Object.fromEntries(coerceInvokeDict(f, value));
	}
	try {
		return coerceConfigValueForFlag(widenJsonIntegers(checked), f);
	} catch (e) {
		throw new InvokeError(`--${f.name}: ${(e as Error).message}`);
	}
}

/**
 * The refusal one pre-typed value earns against its declaration, or undefined
 * when the declaration accepts it. It is the VALUE phase's own question
 * (§24.11 item 240), so the flat door asks it where that phase runs -- after
 * every election and scope decision, and before a presence problem is
 * reported -- rather than leaving it to the conversion's downstream call().
 */
export function preTypedValueRefusal(
	f: AnyFlag,
	value: unknown,
): string | undefined {
	try {
		coerceInvokeValue(f, value);
		return undefined;
	} catch (e) {
		return (e as Error).message;
	}
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
	// The key namespace here is the UNDERSCORED delivery-name space -- the
	// parameter name a handler receives, which is exactly what the flat schema
	// publishes (§24.11). A flag's dashed spelling is its command-line TOKEN,
	// and this door has no tokens, so a dashed key names nothing.
	const declaredByParam = new Map<string, string>();
	for (const name of [
		...flagByName.keys(),
		...selectorByName.keys(),
		...app.globalFlagNames,
	]) {
		declaredByParam.set(flagParamName(name), name);
	}
	// A key naming nothing this command declares is a fact about the object's
	// SHAPE, and shape is decided before every phase (§24.11, §24.3): an unknown
	// flag outranks every election, scope, value and presence problem on the
	// command line wherever it sits in argv, so an unknown key does the same
	// here. Checked in its own pass, ahead of the one that reads values, and the
	// supplied values are indexed by DECLARED name on the way through so every
	// pass below walks declarations rather than the caller's key order.
	const suppliedByFlagName = new Map<string, unknown>();
	for (const paramName of Object.keys(kwargs)) {
		const declared = declaredByParam.get(paramName);
		if (declared !== undefined) {
			suppliedByFlagName.set(declared, kwargs[paramName]);
			continue;
		}
		if (argNames.has(paramName)) {
			continue;
		}
		throw new InvokeError(
			errUnknownParameterForCommand(paramName, commandPath),
		);
	}

	// The phase order is the PARSER's, so it governs this door too (§24.3,
	// §18.24 item 243): every problem below is recorded with its stage and the
	// lowest one over the whole command decides, exactly as the flat door and
	// the command line select their refusal.
	const problems: ParseProblem[] = [];

	// Pass 1: every selector's election, command-wide and outermost first, with
	// the record facts that outrank an election recorded beside them. Walking
	// one selector to its END before starting the next decided every stage below
	// election for one selector before the next selector's record was looked at.
	const elections = new Map<AnyChoiceFlag, string>();
	for (const [name, sel] of selectorByName) {
		electFromRecord(
			sel,
			suppliedByFlagName.has(name),
			suppliedByFlagName.get(name),
			"",
			elections,
			problems,
		);
	}

	// Pass 2: the values, in DECLARATION order. An object has no order of its
	// own, so the order the caller happened to write its keys in decides
	// nothing (§21.4's reason, applied to this door). A selector whose election
	// never settled is skipped: its refusal is already recorded, and there is
	// no elected scope to read values from.
	const recordValue = (f: AnyFlag, value: unknown): void => {
		const refusal = preTypedValueRefusal(f, value);
		if (refusal !== undefined) {
			problems.push({ stage: STAGE.value, message: refusal });
			return;
		}
		store.set(f.name, coerceInvokeValue(f, value), "cli");
	};
	for (const d of def.allDecls) {
		const supplied = suppliedByFlagName.has(d.name);
		if (d.kind === "choice-flag") {
			const tag = elections.get(d);
			if (tag === undefined) {
				continue;
			}
			store.set(
				d.name,
				supplied
					? buildElectedRecord(
							d,
							suppliedByFlagName.get(d.name) as Record<string, unknown>,
							elections,
							app.infraRoots,
							problems,
						)
					: electDefaultRecord(d, tag, app.infraRoots),
				supplied ? "cli" : "default",
			);
			continue;
		}
		if (supplied) {
			recordValue(d, suppliedByFlagName.get(d.name));
		}
	}
	// An app-level global is a declaration like any other, so a value supplied
	// for one is checked like any other (§24.11).
	for (const gf of app.globalFlags) {
		if (suppliedByFlagName.has(gf.name)) {
			recordValue(gf, suppliedByFlagName.get(gf.name));
		}
	}
	const first = firstProblem(problems);
	if (first !== undefined) {
		throw new InvokeError(first.message);
	}

	// Positionals from kwargs in arg declaration order. They are handed to the
	// pipeline AS SUPPLIED: a positional arg is a declaration exactly as a flag
	// is, so the value supplied for one is checked against the type it declares
	// rather than stringified into a token the caller never wrote (§24.11).
	const positionals: unknown[] = [];
	for (const a of def.args) {
		if (!Object.hasOwn(kwargs, a.name)) {
			continue;
		}
		const val = kwargs[a.name];
		// A variadic arg is a SEQUENCE of positionals, so an array spreads into
		// one entry per element and each element is checked on its own; anything
		// else is the single element it looks like.
		if (a.opts.variadic === true && Array.isArray(val)) {
			positionals.push(...val);
		} else {
			positionals.push(val);
		}
	}

	let validated: Record<string, unknown>;
	let sources: Record<string, string>;
	try {
		const parsed = validateAndBuildKwargs(
			cmd,
			def.args,
			store,
			{ kind: "pre-typed", values: positionals },
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

/** The scope path one elected choice opens, as its refusals spell it. */
function electedScopePath(sel: AnyChoiceFlag, tag: string): string {
	return sel.electBy === "member-flags" ? `--${tag}` : `--${sel.name} ${tag}`;
}

/**
 * Pass 1 over one selector: which choice the record elects, plus the facts
 * about the record that outrank an election -- its own shape, the payload key
 * a payload-carrying member's election needs, and a key the elected scope
 * never declared. Nothing throws: each problem carries its stage and the
 * caller reports the lowest one over the WHOLE command (§24.3, §24.11).
 *
 * The walk descends into the elected choice's own selectors, outermost first,
 * so every election in the tree is settled before any value is read.
 */
function electFromRecord(
	sel: AnyChoiceFlag,
	supplied: boolean,
	value: unknown,
	path: string,
	elections: Map<AnyChoiceFlag, string>,
	problems: ParseProblem[],
): void {
	const suffix = errScopeSuffix(path);
	if (!supplied) {
		const o = sel.opts;
		if (o.presence === "default" && o.default !== undefined) {
			// A defaulted selection is COMPLETE by registration (§24.5), so
			// nothing under it can be missing and the walk stops here.
			elections.set(sel, o.default);
			return;
		}
		problems.push({
			stage: STAGE.presence,
			message:
				sel.electBy === "member-flags"
					? errOneOfRequired(memberList(sel), suffix)
					: `${errFlagRequired(sel.name, "value")}${suffix}`,
		});
		return;
	}
	if (typeof value !== "object" || value === null) {
		problems.push({
			stage: STAGE.shape,
			message: `flag '--${sel.name}': the elected value must be a record carrying its '${CHOICE_TAG_KEY}' tag`,
		});
		return;
	}
	const raw = value as Record<string, unknown>;
	const tag = raw[CHOICE_TAG_KEY];
	if (typeof tag !== "string" || !Object.hasOwn(sel.choices, tag)) {
		problems.push({
			stage: STAGE.shape,
			message: errFlagInvalidChoice(
				sel.name,
				String(tag),
				formatChoices(Object.keys(sel.choices)),
			),
		});
		return;
	}
	elections.set(sel, tag);
	const chosen = sel.choices[tag] as NonNullable<(typeof sel.choices)[string]>;
	const scope = electedScopePath(sel, tag);
	if (chosen.value !== undefined && !Object.hasOwn(raw, CHOICE_VALUE_KEY)) {
		// A member flag is elected by its own token and that token CARRIES the
		// payload, so a record electing one with no `value` is the command line's
		// own `--<member>` with nothing after it, and takes that sentence -- a
		// fact about the record's shape, which is why it outranks an election.
		// The ordinary required-flag message is refused for it: a member flag's
		// scope path stops at the scope that OWNS it (§12.13), so that message
		// would render the member as its own owner.
		problems.push({
			stage: STAGE.shape,
			message: errFlagRequiresValue(`--${tag}`),
		});
	}
	const declared = new Set<string>([
		CHOICE_TAG_KEY,
		CHOICE_VALUE_KEY,
		...Object.keys(chosen.flags),
	]);
	for (const key of Object.keys(raw)) {
		if (!declared.has(key)) {
			// A key the elected scope never declared is the scope question one
			// level down, and takes the stage a scope violation takes.
			problems.push({
				stage: STAGE.scope,
				message: `flag '--${key}' is only valid under '${scope}', but that scope does not declare it`,
			});
		}
	}
	for (const [key, sub] of Object.entries(chosen.flags)) {
		if (sub.kind === "choice-flag") {
			electFromRecord(
				sub,
				Object.hasOwn(raw, key),
				raw[key],
				scope,
				elections,
				problems,
			);
		}
	}
}

/**
 * Pass 2 over one selector: the record the handler receives, built from the
 * election pass 1 already settled. Every value is checked against the
 * declaration it was supplied against, a required sub-flag that nothing
 * supplied is refused, an optional one delivers absence as a PRESENT field,
 * and a defaulted one is filled from the declaration.
 *
 * Nothing throws: a value refusal and a scoped presence refusal each carry
 * their stage into the same list pass 1 wrote to, so the phases -- and not the
 * order this walk happens to reach them in -- decide which is reported.
 */
function buildElectedRecord(
	sel: AnyChoiceFlag,
	raw: Record<string, unknown>,
	elections: ReadonlyMap<AnyChoiceFlag, string>,
	infraRoots: ReadonlyMap<string, string>,
	problems: ParseProblem[],
): unknown {
	const tag = elections.get(sel) as string;
	const chosen = sel.choices[tag] as NonNullable<(typeof sel.choices)[string]>;
	const out: Record<string, unknown> = { [CHOICE_TAG_KEY]: tag };
	const provided = new Set<string>();
	const take = (f: AnyFlag, key: string, value: unknown): void => {
		const refusal = preTypedValueRefusal(f, value);
		if (refusal !== undefined) {
			problems.push({ stage: STAGE.value, message: refusal });
			return;
		}
		out[key] = coerceInvokeValue(f, value);
		provided.add(key);
	};
	if (chosen.value !== undefined) {
		// The member's payload is declared by its own flag -- named by the
		// member's own token and required once the member is elected (§24.4) --
		// so the value supplied for it is checked against that declaration.
		take(
			{
				kind: "flag",
				name: tag,
				schema: chosen.value.carrier.schema,
				carrier: chosen.value.carrier,
				opts: { help: chosen.value.help, presence: "required" },
			},
			CHOICE_VALUE_KEY,
			raw[CHOICE_VALUE_KEY],
		);
	}
	const path = electedScopePath(sel, tag);
	for (const [key, sub] of Object.entries(chosen.flags)) {
		if (sub.kind === "choice-flag") {
			const subTag = elections.get(sub);
			if (subTag === undefined) {
				continue;
			}
			if (Object.hasOwn(raw, key)) {
				out[key] = buildElectedRecord(
					sub,
					raw[key] as Record<string, unknown>,
					elections,
					infraRoots,
					problems,
				);
				provided.add(key);
			} else {
				out[key] = electDefaultRecord(sub, subTag, infraRoots);
			}
			continue;
		}
		if (Object.hasOwn(raw, key)) {
			take(sub, key, raw[key]);
			continue;
		}
		if (sub.opts.presence === "required") {
			// The ROOT sentence plus the scope suffix (§12.13): a required bool
			// inside a scope names the tokens that satisfy it exactly as it does at
			// root, and the suffix says where the requirement lives.
			problems.push({
				stage: STAGE.presence,
				message: `${errFlagRequired(sub.name, requiredFlagForm(sub))}${errScopeSuffix(path)}`,
			});
			continue;
		}
		// The declaration decides, exactly as it does on the argv path: a compound
		// default is copied and a RelativeToRoot marker resolves through the app's
		// declared infrastructure roots (§23, §24.6).
		out[key] = applyFlagDefaultForInvoke(sub, "", infraRoots).value;
	}
	attachProvidedFields(out, provided);
	return out;
}

/**
 * The record a selector's own `default` elects. A defaulted selection is
 * COMPLETE by registration (§24.5), so every sub-flag resolves from its own
 * declaration and nothing can be missing.
 */
function electDefaultRecord(
	sel: AnyChoiceFlag,
	choiceName: string,
	infraRoots: ReadonlyMap<string, string>,
): unknown {
	const chosen = sel.choices[choiceName];
	const out: Record<string, unknown> = { [CHOICE_TAG_KEY]: choiceName };
	for (const [key, sub] of Object.entries(chosen?.flags ?? {})) {
		if (sub.kind === "choice-flag") {
			out[key] =
				sub.opts.default === undefined
					? undefined
					: electDefaultRecord(sub, sub.opts.default, infraRoots);
			continue;
		}
		out[key] = applyFlagDefaultForInvoke(sub, "", infraRoots).value;
	}
	attachProvidedFields(out, new Set());
	return out;
}
