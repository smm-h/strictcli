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
	errJsonSchemaIsGroup,
	errJsonSchemaRouteError,
	errRouterCommandMustBeString,
	InvokeError,
} from "./errors.js";
import { elemSchemaOf, flagOpts, schemaKind } from "./factories.js";
import { type CallOptions, commandClassification } from "./invoke.js";
import { flagParamName } from "./parse.js";
import { resolveCommand } from "./routing.js";
import type { ScalarSchema } from "./types.js";

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

	for (const f of cmd.flags) {
		const paramName = flagParamName(f.name);
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
			prop.enum = [...o.choices];
		}
		prop.description = o.help;
		properties[paramName] = prop;

		// Requiredness comes from the DECLARED presence, flags and args alike
		// (contract §13's presence-round amendment). The hand-written derivation
		// this replaces excluded bools on the reasoning that "bool flags always
		// have a default", which §23 makes false by construction: a required
		// bool now appears here, as it already did in Python's projection.
		if (o.presence === "required") {
			required.push(paramName);
		}
	}

	const args = cmd.def.kind === "command" ? cmd.def.args : [];
	for (const a of args) {
		const prop: Record<string, unknown> = {};
		if (a.opts.variadic === true) {
			prop.type = "array";
			prop.items = { type: JSON_SCHEMA_TYPES[a.schema] };
		} else {
			prop.type = JSON_SCHEMA_TYPES[a.schema];
		}
		const opts = a.opts as { readonly choices?: readonly unknown[] };
		if (opts.choices !== undefined) {
			prop.enum = [...opts.choices];
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

function makeTool(
	app: AppImpl,
	commandPath: string,
	cmd: RegisteredCommand,
): Tool {
	return {
		name: commandPath,
		description: cmd.help,
		parameters: buildJSONSchema(cmd),
		...commandClassification(cmd),
		execute: (kwargs = {}, opts = {}) => app.call(commandPath, kwargs, opts),
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
