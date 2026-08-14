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
	errFlagInvalidChoice,
	errFlagOutOfScope,
	errJsonSchemaIsGroup,
	errJsonSchemaRouteError,
	errOneOfRequired,
	errRouterCommandMustBeString,
	errScopeWhyElected,
	errScopeWhyNotProvided,
	InvokeError,
} from "./errors.js";
import {
	type AnyChoiceFlag,
	type AnyCommand,
	type AnyDecl,
	type AnyFlag,
	choiceValues,
	elemSchemaOf,
	flagOpts,
	memberList,
	schemaKind,
} from "./factories.js";
import { type CallOptions, commandClassification } from "./invoke.js";
import { flagParamName } from "./parse.js";
import { resolveCommand } from "./routing.js";
import type { ScalarSchema } from "./types.js";
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

/** Scalar schema -> JSON Schema type string. */
const JSON_SCHEMA_TYPES: Readonly<Record<ScalarSchema, string>> = {
	str: "string",
	bool: "boolean",
	int: "integer",
	float: "number",
};

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

	/** One ordinary flag's property, at root scope or any depth. */
	const flagProperty = (f: AnyFlag): Record<string, unknown> => {
		const prop: Record<string, unknown> = {};
		const kind = schemaKind(f.schema);
		if (kind === "dict") {
			prop.type = "object";
			prop.additionalProperties = {
				type: JSON_SCHEMA_TYPES[elemSchemaOf(f.carrier)],
			};
		} else if (kind === "list") {
			prop.type = "array";
			prop.items = { type: JSON_SCHEMA_TYPES[elemSchemaOf(f.carrier)] };
		} else {
			prop.type = JSON_SCHEMA_TYPES[f.schema as ScalarSchema];
		}
		const o = flagOpts(f);
		if (o.choices !== undefined) {
			prop.enum = [...choiceValues(o.choices)];
		}
		prop.description = o.help;
		return prop;
	};

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
					properties[flagParamName(choiceName)] = {
						type: JSON_SCHEMA_TYPES[c.value.schema],
						description: c.help,
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
		const prop: Record<string, unknown> = {};
		if (a.opts.variadic === true) {
			prop.type = "array";
			prop.items = { type: JSON_SCHEMA_TYPES[a.schema] };
		} else {
			prop.type = JSON_SCHEMA_TYPES[a.schema];
		}
		const opts = a.opts as {
			readonly choices?: readonly { readonly value: unknown }[];
		};
		if (opts.choices !== undefined) {
			prop.enum = [...choiceValues(opts.choices)];
		}
		prop.description = a.opts.help;
		properties[a.name] = prop;

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
 */
export function flatToCallKwargs(
	cmd: RegisteredCommand,
	kwargs: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
	const decls =
		cmd.def.kind === "command" ? (cmd.def as AnyCommand).allDecls : [];
	if (!decls.some((d) => d.kind === "choice-flag")) {
		return { ...kwargs };
	}
	const out: Record<string, unknown> = {};
	const consumed = new Set<string>();
	const scopedParams = new Map<string, string[]>();
	const collectScoped = (
		list: readonly AnyDecl[],
		path: readonly string[],
	): void => {
		for (const d of list) {
			if (d.kind === "flag") {
				const owners = scopedParams.get(flagParamName(d.name)) ?? [];
				owners.push(path.join(" "));
				scopedParams.set(flagParamName(d.name), owners);
				continue;
			}
			for (const [choiceName, c] of Object.entries(d.choices)) {
				const next = [...path, `${flagParamName(d.name)}=${choiceName}`];
				if (c.value !== undefined) {
					const owners = scopedParams.get(flagParamName(choiceName)) ?? [];
					owners.push(next.join(" "));
					scopedParams.set(flagParamName(choiceName), owners);
				}
				collectScoped(Object.values(c.flags), next);
			}
		}
	};
	for (const d of decls) {
		if (d.kind === "choice-flag") {
			for (const [choiceName, c] of Object.entries(d.choices)) {
				const base = [`${flagParamName(d.name)}=${flagParamName(choiceName)}`];
				if (c.value !== undefined) {
					const owners = scopedParams.get(flagParamName(choiceName)) ?? [];
					owners.push(base.join(" "));
					scopedParams.set(flagParamName(choiceName), owners);
				}
				collectScoped(Object.values(c.flags), base);
			}
		}
	}

	const elected = new Map<string, string>();
	const buildRecord = (sel: AnyChoiceFlag): unknown => {
		const key = flagParamName(sel.name);
		const named = kwargs[key];
		consumed.add(key);
		const tag =
			typeof named === "string"
				? named
				: sel.opts.presence === "default"
					? sel.opts.default
					: undefined;
		if (tag === undefined) {
			throw new InvokeError(
				sel.electBy === "member-flags"
					? errOneOfRequired(memberList(sel), "")
					: `flag '--${sel.name}' is required`,
			);
		}
		const chosen = sel.choices[tag];
		if (chosen === undefined) {
			throw new InvokeError(
				errFlagInvalidChoice(
					sel.name,
					String(tag),
					formatChoices(Object.keys(sel.choices)),
				),
			);
		}
		elected.set(flagParamName(sel.name), tag);
		const record: Record<string, unknown> = { choice: tag };
		if (chosen.value !== undefined) {
			const payloadKey = flagParamName(tag);
			consumed.add(payloadKey);
			if (Object.hasOwn(kwargs, payloadKey)) {
				record.value = kwargs[payloadKey];
			}
		}
		for (const [subKey, sub] of Object.entries(chosen.flags)) {
			if (sub.kind === "choice-flag") {
				record[subKey] = buildRecord(sub);
				continue;
			}
			const param = flagParamName(sub.name);
			consumed.add(param);
			if (Object.hasOwn(kwargs, param)) {
				record[subKey] = kwargs[param];
			}
		}
		return record;
	};

	for (const d of decls) {
		if (d.kind === "choice-flag") {
			out[flagParamName(d.name)] = buildRecord(d);
			continue;
		}
		const param = flagParamName(d.name);
		consumed.add(param);
		if (Object.hasOwn(kwargs, param)) {
			out[param] = kwargs[param];
		}
	}
	for (const [key, value] of Object.entries(kwargs)) {
		if (consumed.has(key)) {
			continue;
		}
		const owners = scopedParams.get(key);
		if (owners === undefined) {
			out[key] = value;
			continue;
		}
		// The same `<why>` clause the CLI parser gives, in the machine
		// spelling: the first owner's outermost unsatisfied election.
		throw new InvokeError(
			errFlagOutOfScope(
				key,
				owners.map((o) => `'${o}'`).join(" or "),
				whyNotLive(owners[0] as string, elected),
			),
		);
	}
	return out;
}

/**
 * The out-of-scope `<why>` clause at the machine boundary: the first segment
 * of the owner's path whose election did not happen, named the way §12.13's
 * three clauses name it.
 */
function whyNotLive(
	owner: string,
	elected: ReadonlyMap<string, string>,
): string {
	const satisfied: string[] = [];
	for (const segment of owner.split(" ")) {
		const [selectorName, choiceName] = segment.split("=");
		const actual = elected.get(selectorName as string);
		if (actual === choiceName) {
			satisfied.push(segment);
			continue;
		}
		if (actual === undefined) {
			return errScopeWhyNotProvided(selectorName as string);
		}
		return errScopeWhyElected(
			[...satisfied, `${selectorName}=${actual}`].join(" "),
			"",
		);
	}
	return errScopeWhyNotProvided(owner);
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
			app.call(commandPath, flatToCallKwargs(cmd, kwargs), opts),
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
