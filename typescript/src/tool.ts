/**
 * Tool export: descriptors for exposing CLI commands to tool-using LLM
 * agents, mirroring Go tool.go and Python _build_json_schema/as_tools. Python
 * is the divergence ground truth; the Go entry points are
 * buildJSONSchema/AsTools/JsonSchema.
 *
 * The JSON Schema builder maps the four scalar types to JSON Schema type
 * strings (str -> string, bool -> boolean, int -> integer, float -> number);
 * dict flags become "object" with additionalProperties, list flags and
 * variadic args become "array" with items. Int enum values stay bigint --
 * MCP serialization (jsonCompact) emits them as bare integer tokens.
 */

import type { AppImpl, GroupImpl, RegisteredCommand } from "./app.js";
import type { Effect } from "./effects.js";
import {
	errElectionOriginDefault,
	errElectionOriginSuffix,
	errFlagInvalidChoice,
	errFlagRequiresValue,
	errJsonSchemaIsGroup,
	errJsonSchemaRouteError,
	errMutexDeclineClause,
	errMutexRedundantNegation,
	errMutuallyExclusive,
	errOneOfRequired,
	errRouterCommandMustBeString,
	errScopeSuffix,
	errUnknownParameterForCommand,
	InvokeError,
} from "./errors.js";
import {
	type AnyChoiceFlag,
	type AnyCommand,
	type AnyDecl,
	type AnyFlag,
	flagOpts,
	memberList,
	type ScopeStep,
	scalarFragment,
	scopePath,
	valueSchemaFragment,
} from "./factories.js";
import {
	type CallOptions,
	commandClassification,
	markDeclarationElected,
	paramToFlagName,
	preTypedValueRefusal,
} from "./invoke.js";
import { flagParamName } from "./parse.js";
import { resolveCommand } from "./routing.js";
import {
	type Election,
	firstProblem,
	outOfScopeMessage,
	type ParseProblem,
	STAGE,
} from "./scopeparse.js";
import { formatChoices, formatValueForError } from "./values.js";

/**
 * A descriptor for exposing one CLI command to tool-using LLM agents.
 *
 * `effect` and `consequential` publish the effects-regime classification
 * BESIDE the argument schema (never inside it): a consumer rendering this tool
 * must be able to see that the command changes things and that calling it
 * requires stating consent. Same vocabulary as the schema dump: `effect` is
 * mandatory, `consequential` defaults to false.
 */
export interface Tool {
	readonly name: string;
	readonly description: string;
	readonly parameters: Record<string, unknown>;
	readonly effect: Effect;
	readonly consequential: boolean;
	readonly execute: (
		kwargs?: Record<string, unknown>,
		opts?: CallOptions,
	) => Promise<unknown>;
}

/**
 * Builds a JSON Schema parameters object for a command's flags and
 * positional args (Go buildJSONSchema / Python _build_json_schema).
 * Passthrough commands have no flags or args, so they yield the empty
 * object schema.
 */
export function buildJSONSchema(
	cmd: RegisteredCommand,
): Record<string, unknown> {
	const properties: Record<string, unknown> = {};
	const required: string[] = [];

	/**
	 * One ordinary flag's property, at root scope or any depth. The parameter
	 * schema is the SAME fragment the dump publishes (§25.13), so a tool
	 * schema's shape and a dumped one cannot disagree -- and an `enum` on an
	 * array-shaped parameter therefore sits inside `items`, describing the
	 * element, rather than at the property root, which would say the array
	 * itself must equal one of the choices.
	 */
	const flagProperty = (f: AnyFlag): Record<string, unknown> => ({
		...valueSchemaFragment(f),
		description: flagOpts(f).help,
	});

	/**
	 * The MCP projection is FLATTEN plus a description map (contract §24.11):
	 * every scoped flag contributes a top-level property, and NEVER appears in
	 * `required` -- its requiredness is conditional, and the schema has no
	 * vocabulary for that. A member-spelled selector projects IDENTICALLY to a
	 * token-spelled one: tokenization is a command-line fact and there are no
	 * tokens at this boundary, so a member's payload flattens under the
	 * member's own flag name, which the framework already guarantees unique
	 * command-wide.
	 */
	const flattenScope = (decls: readonly AnyDecl[]): void => {
		for (const d of decls) {
			if (d.kind === "flag") {
				properties[flagParamName(d.name)] = flagProperty(d);
				continue;
			}
			properties[flagParamName(d.name)] = {
				type: "string",
				enum: Object.keys(d.choices),
				description: d.opts.help,
			};
			for (const [choiceName, c] of Object.entries(d.choices)) {
				if (c.value !== undefined) {
					// The payload's OWN help documents the flattened property: the
					// property carries the value, not the election, so the choice's
					// help would describe something else entirely.
					properties[flagParamName(choiceName)] = {
						...scalarFragment(c.value.carrier.schema, undefined),
						description: c.value.help,
					};
				}
				flattenScope(Object.values(c.flags));
			}
		}
	};

	const rootDecls =
		cmd.def.kind === "command" ? (cmd.def as AnyCommand).allDecls : [];
	for (const d of rootDecls) {
		if (d.kind === "choice-flag") {
			// The selector's own property follows the ordinary rule: it appears in
			// `required` iff the selector declares `required` (§13's narrowing).
			if (d.opts.presence === "required") {
				required.push(flagParamName(d.name));
			}
			continue;
		}
		const o = flagOpts(d);
		// Requiredness comes from the DECLARED presence, flags and args alike
		// (contract §13's presence-round amendment). The hand-written derivation
		// this replaces excluded bools on the reasoning that "bool flags always
		// have a default", which §23 makes false by construction: a required
		// bool now appears here, as it already did in Python's projection.
		if (o.presence === "required") {
			required.push(flagParamName(d.name));
		}
	}
	flattenScope(rootDecls);

	const args = cmd.def.kind === "command" ? cmd.def.args : [];
	for (const a of args) {
		properties[a.name] = {
			...valueSchemaFragment(a),
			description: a.opts.help,
		};
		if (a.opts.presence === "required") {
			required.push(a.name);
		}
	}

	return {
		type: "object",
		properties,
		required,
		additionalProperties: false,
	};
}

/**
 * Produces the JSON Schema parameters object for a command path (Go
 * App.JsonSchema / Python app.json_schema). Throws InvokeError when the
 * path is invalid or resolves to a group.
 */
export function jsonSchemaForApp(
	app: AppImpl,
	commandPath: string,
): Record<string, unknown> {
	const route = resolveCommand(app, commandPath.split("."));
	if (route.err !== undefined) {
		throw new InvokeError(errJsonSchemaRouteError(route.err));
	}
	if (route.cmd === undefined) {
		throw new InvokeError(errJsonSchemaIsGroup(commandPath));
	}
	return buildJSONSchema(route.cmd);
}

/**
 * Collects non-hidden, non-interactive leaf commands as [dottedPath, cmd]
 * pairs in registration order: top-level commands first, then groups
 * (recursively; a hidden group hides its whole subtree). Shared by asTools
 * and the MCP tools/list handler.
 */
export function collectToolCommands(
	app: AppImpl,
): [string, RegisteredCommand][] {
	const out: [string, RegisteredCommand][] = [];
	for (const [name, cmd] of app.commands) {
		if (isToolEligible(cmd)) {
			out.push([name, cmd]);
		}
	}
	const walk = (group: GroupImpl, path: readonly string[]): void => {
		if (group.hidden) {
			return;
		}
		for (const [cmdName, cmd] of group.commands) {
			if (isToolEligible(cmd)) {
				out.push([[...path, cmdName].join("."), cmd]);
			}
		}
		for (const [subName, subGroup] of group.groups) {
			walk(subGroup, [...path, subName]);
		}
	};
	for (const [groupName, group] of app.groups) {
		walk(group, [groupName]);
	}
	return out;
}

function isToolEligible(cmd: RegisteredCommand): boolean {
	if (cmd.hidden) {
		return false;
	}
	return cmd.def.kind !== "command" || !cmd.def.interactive;
}

/**
 * Exports non-hidden, non-interactive leaf commands as Tool descriptors,
 * one per eligible command plus a trailing router tool. Each tool's execute
 * wraps app.call().
 */
export function asToolsForApp(app: AppImpl): Tool[] {
	const tools: Tool[] = [];
	const commandPaths: string[] = [];
	for (const [path, cmd] of collectToolCommands(app)) {
		tools.push(makeTool(app, path, cmd));
		commandPaths.push(path);
	}
	tools.push(makeRouterTool(app, commandPaths));
	return tools;
}

/**
 * The scope structure survives in the TOOL DESCRIPTION, appended as a
 * deterministic block so that an agent can read the constraint it cannot see
 * in the schema (contract §24.11):
 *
 *   Scoped parameters (enforced at call time):
 *     via=email: subject (required), recipient (required)
 *     via=sms: phone_number (required)
 *     visibility=user-facing type=feature: (no parameters)
 *
 * One line per scope, at every depth, in declaration order. The key is the
 * scope's path rendered as `<selector>=<choice>` segments joined by a single
 * space -- the machine-side spelling of §12.13's scope path, using the
 * PROPERTY names the schema publishes rather than the flags a CLI user types.
 *
 * The cost is stated rather than discovered: an agent cannot see the scope
 * rule before it calls; it learns by being refused. That is the least-bad of
 * the three options §24.11 records.
 */
export function scopeDescriptionBlock(cmd: RegisteredCommand): string {
	const decls =
		cmd.def.kind === "command" ? (cmd.def as AnyCommand).allDecls : [];
	const lines: string[] = [];
	const walk = (list: readonly AnyDecl[], prefix: readonly string[]): void => {
		for (const d of list) {
			if (d.kind !== "choice-flag") {
				continue;
			}
			for (const [choiceName, c] of Object.entries(d.choices)) {
				// The key is the scope's path in the PROPERTY names the schema
				// publishes: the selector is a property, and the choice is the
				// value its enum publishes -- so the choice name is not
				// underscored (§24.11).
				const path = [...prefix, `${flagParamName(d.name)}=${choiceName}`];
				const params: string[] = [];
				if (c.value !== undefined) {
					params.push(`${flagParamName(choiceName)} (required)`);
				}
				for (const sub of Object.values(c.flags)) {
					params.push(`${flagParamName(sub.name)} (${presenceClause(sub)})`);
				}
				lines.push(
					`  ${path.join(" ")}: ${params.length === 0 ? "(no parameters)" : params.join(", ")}`,
				);
				walk(Object.values(c.flags), path);
			}
		}
	};
	walk(decls, []);
	if (lines.length === 0) {
		return "";
	}
	return `\n\nScoped parameters (enforced at call time):\n${lines.join("\n")}`;
}

/** A scoped parameter's presence, as the description block spells it. */
function presenceClause(d: AnyDecl): string {
	const presence = d.opts.presence;
	if (presence !== "default") {
		return presence;
	}
	const dflt = (d.opts as { readonly default?: unknown }).default;
	return `default: ${formatValueForError(dflt)}`;
}

/**
 * Converts the FLAT machine form (§24.11's projection) into the elected
 * records `call()` takes, through the same election, scope and presence
 * machinery the argv path uses -- which is what makes the two front doors
 * agree by construction rather than by test.
 *
 * A wrong combination is refused here, at call time, with the SAME SENTENCE
 * the CLI parser gives. A command that declares no selector returns its
 * arguments unchanged, so this costs nothing where nothing is scoped.
 *
 * The passes are the parser's own, and they are COMMAND-WIDE rather than
 * per-selector (§24.3): every selector's election is resolved first, then
 * scope membership, then the records are built -- and each pass RECORDS its
 * problems instead of throwing, so the one reported is the lowest stage over
 * the whole command. Walking one selector to its end before starting the next
 * would report an earlier selector's missing election ahead of a later one's
 * double election, which is an answer no command line can produce.
 */
export function flatToCallKwargs(
	app: AppImpl,
	commandPath: string,
	cmd: RegisteredCommand,
	kwargs: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
	const decls =
		cmd.def.kind === "command" ? (cmd.def as AnyCommand).allDecls : [];
	if (!decls.some((d) => d.kind === "choice-flag")) {
		return { ...kwargs };
	}
	const problems: ParseProblem[] = [];
	const elections = new Map<AnyChoiceFlag, Election>();
	// Every property name a LIVE scope claims -- the flat counterpart of the
	// parser's liveNames. A live name is consumed by the build pass; anything
	// else is either out of scope or none of this function's business.
	const live = new Set<string>();
	// Every property name a scope owns, against the DECLARED name behind it and
	// the scope PATHS that own it -- the same ScopeStep paths the argv parser
	// carries. The refusal below is the CLI's sentence, so it names the flag the
	// way a user would type it, not the way the flat projection spells it.
	const scopedParams = new Map<
		string,
		{ readonly name: string; readonly owners: ScopeStep[][] }
	>();
	const ownedBy = (name: string, path: readonly ScopeStep[]): void => {
		const param = flagParamName(name);
		const entry = scopedParams.get(param) ?? { name, owners: [] };
		entry.owners.push([...path]);
		scopedParams.set(param, entry);
	};
	const collectScoped = (
		list: readonly AnyDecl[],
		path: readonly ScopeStep[],
	): void => {
		for (const d of list) {
			if (d.kind === "flag") {
				ownedBy(d.name, path);
				continue;
			}
			// A nested selector's own property belongs to the scope it sits in,
			// exactly as an ordinary flag's does -- supplied while a sibling scope is
			// elected, it takes the out-of-scope refusal rather than being read as a
			// name the command never declared. A ROOT selector owns no scope and is
			// consumed unconditionally, so it is not indexed here.
			if (path.length > 0) {
				ownedBy(d.name, path);
			}
			for (const [choiceName, c] of Object.entries(d.choices)) {
				const next: ScopeStep[] = [...path, { selector: d, choiceName }];
				// A member's own property flattens under the member's flag name, and
				// supplying it IS electing the member -- exactly as typing the
				// member's token is on the command line. So the property belongs to
				// the scope the SELECTOR sits in, never to the member's own scope:
				// naming the member's own election as its owner would say the flag is
				// only valid under itself (§24.11, §21.4).
				if (d.electBy === "member-flags") {
					ownedBy(choiceName, path);
				}
				collectScoped(Object.values(c.flags), next);
			}
		}
	};
	// Root-scope ordinary flags own no scope and are consumed unconditionally
	// below, so only the selectors open scopes worth indexing.
	collectScoped(
		decls.filter((d) => d.kind === "choice-flag"),
		[],
	);

	// --- Pass 0: the object's own shape ---
	//
	// A property no declaration mentions anywhere is a fact about the OBJECT,
	// settled before any election is read -- the flat counterpart of the token
	// scan refusing `--nope` before it interprets `--via` (§24.3's shape stage).
	// call() refuses the same key with the same sentence; recording it HERE is
	// what puts it ahead of every election, scope, value and presence problem,
	// exactly as the command line puts it there.
	//
	// The legal set is every DECLARED name, not every live one: a property whose
	// scope was not elected is declared, and gets the scope refusal that says so.
	const declaredParams = new Set<string>(scopedParams.keys());
	for (const d of decls) {
		declaredParams.add(flagParamName(d.name));
	}
	for (const a of (cmd.def as AnyCommand).args) {
		declaredParams.add(a.name);
	}
	for (const key of Object.keys(kwargs)) {
		if (
			declaredParams.has(key) ||
			app.globalFlagNames.has(paramToFlagName(key))
		) {
			continue;
		}
		problems.push({
			stage: STAGE.shape,
			message: errUnknownParameterForCommand(key, commandPath),
		});
	}

	// --- Pass 1: elections, over EVERY selector, outermost first ---

	/**
	 * A member-spelled selector's election, read out of the flat object. It is
	 * elected two ways at this boundary and they are one fact: the selector's
	 * own property naming the member, and the member's own property. Supplying
	 * the member's property IS electing it (§24.11's projection of §21.4), so
	 * two of them -- or one beside a selector property naming a different member
	 * -- is a DOUBLE election, which takes §21.4's mutual-exclusion sentence
	 * rather than a scope refusal.
	 *
	 * A payload-less member has no payload for its property to carry, so the
	 * property carries the election itself: `false` is the `--no-<name>` token,
	 * which DECLINES rather than choosing, and anything else elects.
	 */
	const electMembers = (
		sel: AnyChoiceFlag,
		named: unknown,
		suffix: string,
	): Election => {
		const elected: string[] = [];
		const declined: string[] = [];
		for (const [choiceName, c] of Object.entries(sel.choices)) {
			if (named === choiceName) {
				elected.push(choiceName);
				continue;
			}
			const param = flagParamName(choiceName);
			if (!Object.hasOwn(kwargs, param)) {
				continue;
			}
			if (c.value === undefined && kwargs[param] === false) {
				declined.push(choiceName);
				continue;
			}
			elected.push(choiceName);
		}
		const firstDeclined = declined[0];
		const clause =
			firstDeclined !== undefined ? errMutexDeclineClause(firstDeclined) : "";
		if (elected.length > 1) {
			problems.push({
				stage: STAGE.election,
				message: errMutuallyExclusive(
					elected.map((c) => `--${c}`).join(" and "),
				),
			});
			return { elected: undefined, origin: "" };
		}
		const sole = elected[0];
		if (sole !== undefined) {
			if (declined.length > 0) {
				problems.push({
					stage: STAGE.election,
					message: errMutexRedundantNegation(
						declined.map((c) => `--no-${c}`).join(" and "),
						sole,
						clause,
					),
				});
				return { elected: undefined, origin: "" };
			}
			return { elected: sole, origin: "" };
		}
		const o = sel.opts;
		if (o.presence === "default" && o.default !== undefined) {
			return { elected: o.default, origin: errElectionOriginDefault };
		}
		problems.push({
			stage: STAGE.presence,
			// Scope suffix, origin suffix, THEN the decline clause (§12.13) -- the
			// CLI parser's own composition, reused rather than restated.
			message: errOneOfRequired(memberList(sel), `${suffix}${clause}`),
		});
		return { elected: undefined, origin: "" };
	};

	/** A token-spelled selector's election: its own property names the choice. */
	const electToken = (
		sel: AnyChoiceFlag,
		named: unknown,
		suffix: string,
	): Election => {
		if (typeof named === "string") {
			return { elected: named, origin: "" };
		}
		const o = sel.opts;
		if (o.presence === "default" && o.default !== undefined) {
			return { elected: o.default, origin: errElectionOriginDefault };
		}
		problems.push({
			stage: STAGE.presence,
			message: `flag '--${sel.name}' is required${suffix}`,
		});
		return { elected: undefined, origin: "" };
	};

	/**
	 * The origin clause of the OUTERMOST non-command-line election on a path
	 * (§18.19 item 216), read out of the elections this pass has already
	 * settled. Empty when every election on the path was supplied by the caller.
	 */
	const electionOriginOn = (path: readonly ScopeStep[]): string => {
		for (const step of path) {
			const origin = elections.get(step.selector)?.origin ?? "";
			if (origin !== "") {
				return origin;
			}
		}
		return "";
	};

	const electOne = (
		sel: AnyChoiceFlag,
		path: readonly ScopeStep[],
	): Election => {
		const named = kwargs[flagParamName(sel.name)];
		if (typeof named === "string" && !Object.hasOwn(sel.choices, named)) {
			problems.push({
				// A selector property naming no declared choice is a fact about the
				// OBJECT, not about an election: there is nothing to elect from. It
				// therefore takes the shape stage, where it loses to an unknown key
				// recorded before it and beats every phase fact after it (§24.11).
				stage: STAGE.shape,
				message: errFlagInvalidChoice(
					sel.name,
					formatValueForError(named),
					formatChoices(Object.keys(sel.choices)),
				),
			});
			return { elected: undefined, origin: "" };
		}
		// The scope suffix and the origin suffix, in that order (§12.13), with a
		// decline clause after both -- the CLI parser's own composition.
		const suffix =
			errScopeSuffix(scopePath(path)) +
			errElectionOriginSuffix(electionOriginOn(path));
		return sel.electBy === "member-flags"
			? electMembers(sel, named, suffix)
			: electToken(sel, named, suffix);
	};

	/**
	 * One scope's elections, then the elected choice's own scope one level
	 * down. Every name the scope declares goes live whether it was supplied or
	 * not, exactly as the parser records them, so scope validation can tell an
	 * out-of-scope property from an undeclared one.
	 */
	const electScope = (
		list: readonly AnyDecl[],
		path: readonly ScopeStep[],
	): void => {
		for (const d of list) {
			live.add(flagParamName(d.name));
			if (d.kind !== "choice-flag") {
				continue;
			}
			if (d.electBy === "member-flags") {
				for (const choiceName of Object.keys(d.choices)) {
					live.add(flagParamName(choiceName));
				}
			}
			const election = electOne(d, path);
			elections.set(d, election);
			const chosen =
				election.elected === undefined
					? undefined
					: d.choices[election.elected];
			if (chosen === undefined) {
				continue;
			}
			electScope(Object.values(chosen.flags), [
				...path,
				{ selector: d, choiceName: election.elected as string },
			]);
		}
	};
	electScope(decls, []);

	// --- Pass 2: scope membership ---

	for (const key of Object.keys(kwargs)) {
		if (live.has(key)) {
			continue;
		}
		const scoped = scopedParams.get(key);
		if (scoped === undefined) {
			continue;
		}
		// The refusal is the CLI parser's own sentence, rendered by the CLI's own
		// renderer: one channel, one wording, whichever front door was used
		// (§24.11, §18.19 item 222).
		problems.push({
			stage: STAGE.scope,
			message: outOfScopeMessage(
				scoped.name,
				scoped.owners,
				scoped.owners[0] as ScopeStep[],
				(sel) => elections.get(sel),
			),
		});
	}

	// --- Pass 3: the records ---

	const buildRecord = (sel: AnyChoiceFlag, tag: string): unknown => {
		const chosen = sel.choices[tag];
		const record: Record<string, unknown> = { choice: tag };
		if (chosen === undefined) {
			return record;
		}
		if (chosen.value !== undefined) {
			const payloadKey = flagParamName(tag);
			if (Object.hasOwn(kwargs, payloadKey)) {
				record.value = kwargs[payloadKey];
				// The payload is declared by the member's own flag -- named by the
				// member's token and required once the member is elected (§24.4) --
				// so the value supplied for it is checked against that declaration.
				checkValue(
					{
						kind: "flag",
						name: tag,
						schema: chosen.value.carrier.schema,
						carrier: chosen.value.carrier,
						opts: { help: chosen.value.help, presence: "required" },
					},
					kwargs[payloadKey],
				);
			} else {
				// Electing a payload-carrying member while omitting the property that
				// carries its payload is the flat form of typing the member's token
				// with nothing after it, and takes that same sentence -- a fact about
				// the object's shape, which is why it outranks every election.
				problems.push({
					stage: STAGE.shape,
					message: errFlagRequiresValue(`--${tag}`),
				});
			}
		}
		for (const [subKey, sub] of Object.entries(chosen.flags)) {
			if (sub.kind === "choice-flag") {
				const subTag = elections.get(sub)?.elected;
				if (subTag !== undefined) {
					record[subKey] = buildRecord(sub, subTag);
				}
				continue;
			}
			const param = flagParamName(sub.name);
			if (Object.hasOwn(kwargs, param)) {
				record[subKey] = kwargs[param];
				checkValue(sub, kwargs[param]);
			}
		}
		return record;
	};

	/**
	 * The value phase, recorded rather than thrown (§24.11 item 240): a
	 * pre-typed value is checked against the declaration it was supplied
	 * against, and the check belongs to the phase a value refusal already sits
	 * in -- after every election and scope decision, and ahead of a presence
	 * problem, which is a stage the conversion can also record. Asking it here
	 * rather than downstream in call() is what lets the stage table decide
	 * between the two.
	 */
	function checkValue(f: AnyFlag, value: unknown): void {
		const refusal = preTypedValueRefusal(f, value);
		if (refusal !== undefined) {
			problems.push({ stage: STAGE.value, message: refusal });
		}
	}

	const out: Record<string, unknown> = {};
	for (const d of decls) {
		const param = flagParamName(d.name);
		if (d.kind === "choice-flag") {
			const election = elections.get(d);
			const tag = election?.elected;
			if (tag !== undefined) {
				const record = buildRecord(d, tag) as Record<string, unknown>;
				// A selection the caller elected nothing of is the DECLARATION's, and
				// materializing it here must not turn it into the call's: the record
				// is built because a sibling key may have to ride in it, so it carries
				// the mark that keeps `ctx.source` and `ctx.provided` answering
				// `default`/false for the election, exactly as the command line and
				// the record door answer for the same declaration (§23.6, §24.5). A
				// field the caller DID supply is delivered and follows the record
				// door's own rule, which labels every field it delivers the
				// declaration's (§18.26 item 253).
				if (election?.origin === errElectionOriginDefault) {
					markDeclarationElected(record);
				}
				out[param] = record;
			}
			continue;
		}
		if (Object.hasOwn(kwargs, param)) {
			out[param] = kwargs[param];
			checkValue(d, kwargs[param]);
		}
	}
	// An app-level global is a declaration like any other, so a value supplied
	// for one is checked in the same phase (§24.11).
	for (const gf of app.globalFlags) {
		const param = flagParamName(gf.name);
		if (Object.hasOwn(kwargs, param)) {
			checkValue(gf, kwargs[param]);
		}
	}
	// Everything no scope claims passes through untouched: positional args,
	// global flags, and the undeclared names call() itself refuses.
	for (const [key, value] of Object.entries(kwargs)) {
		if (live.has(key) || scopedParams.has(key)) {
			continue;
		}
		out[key] = value;
	}
	const first = firstProblem(problems);
	if (first !== undefined) {
		throw new InvokeError(first.message);
	}
	return out;
}

function makeTool(
	app: AppImpl,
	commandPath: string,
	cmd: RegisteredCommand,
): Tool {
	return {
		name: commandPath,
		description: `${cmd.help}${scopeDescriptionBlock(cmd)}`,
		parameters: buildJSONSchema(cmd),
		...commandClassification(cmd),
		// async so a conversion refusal reaches the caller as a REJECTED
		// promise, exactly as an invocation error does: a tool's execute is a
		// promise-returning contract, and a synchronous throw would escape it.
		execute: async (kwargs = {}, opts = {}) =>
			app.call(
				commandPath,
				flatToCallKwargs(app, commandPath, cmd, kwargs),
				opts,
			),
	};
}

/** Builds the router tool that lists and dispatches to per-command tools. */
function makeRouterTool(app: AppImpl, commandPaths: readonly string[]): Tool {
	const paths = [...commandPaths];
	const parameters: Record<string, unknown> = {
		type: "object",
		properties: {
			command: {
				type: "string",
				description: "Command to execute (dot-separated path)",
				enum: [...paths],
			},
		},
		required: ["command"],
		additionalProperties: false,
	};
	// The router can reach a mutating command, so it classifies as mutating. It
	// is NOT itself consequential: the routed command's own requirement is
	// checked when the call reaches it, and the router forwards the caller's
	// consent unchanged. Marking the router consequential would demand consent
	// for routing to a read_only command, which confirms nothing.
	return {
		name: app.name,
		description: `Route to ${app.name} commands`,
		parameters,
		effect: "mutating",
		consequential: false,
		execute: async (kwargs = {}, opts = {}) => {
			if (!Object.hasOwn(kwargs, "command")) {
				// No command specified -- return the list of available commands.
				return [...paths];
			}
			const cmdPath = kwargs.command;
			if (typeof cmdPath !== "string") {
				throw new InvokeError(errRouterCommandMustBeString());
			}
			const fwd: Record<string, unknown> = { ...kwargs };
			delete fwd.command;
			return app.call(cmdPath, fwd, opts);
		},
	};
}
