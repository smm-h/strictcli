/**
 * Schema dump (--dump-schema): builds the machine-readable schema dict and
 * writes .strictcli/schema.json. Parity sources: go/strictcli/schema.go (all)
 * and Python _serialize_flag/_dump_schema_core/_write_schema. Key order and
 * omission rules follow Python (the divergence ground truth); Go sorts JSON
 * map keys on marshal, so it pins content, not order.
 *
 * TS model deltas (documented divergences):
 * - Flag/arg types are the exact ten TS carrier schema strings (str, bool,
 *   int, float, list[str|int|float], dict[str,str|int|float]). Go spells
 *   compounds list[str]/dict[str]; Python emits JSON-schema-ish objects for
 *   compounds. The TS schema string IS the declaration surface.
 * - "repeatable" is never emitted: list carriers are the only repeatable
 *   flags, and the list[...] type string already conveys it (Python's
 *   compound-list rule -- it omits repeatable for list[T] flags too).
 * - Empty list/dict defaults are omitted (Python's compound rule); explicit
 *   empty defaults are banned at registration anyway.
 * - project_id comes from package.json "name" (the ecosystem analog of
 *   Python's pyproject.toml [project].name and Go's go.mod module path).
 *
 * Machine-channel number convention: bigint values are bare integer tokens;
 * float values are SCF tokens (SCF strings are valid JSON numbers, and Python
 * json.dumps floats via repr == SCF, so the bytes match the Python sibling).
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { AppImpl, GroupImpl, RegisteredCommand } from "./app.js";
import type { ConfigFieldRt } from "./config.js";
import {
	errCannotDetermineProjectIDNoName,
	errCannotDetermineProjectIDNoPackageJson,
	errCannotDetermineProjectIDReadError,
	errSchemaMismatch,
} from "./errors.js";
import {
	type AnyArg,
	type AnyCommand,
	type AnyFlag,
	flagOpts,
	schemaKind,
} from "./factories.js";
import { formatFloatCanonical } from "./float.js";
import { type InfraRootPath, isInfraRootPath } from "./infra.js";

// --- JSON writer (2-space indent, bigint/float machine-channel tokens) ---

/**
 * Serializes a schema value as pretty JSON with 2-space indentation,
 * mirroring Python json.dumps(schema, indent=2): ": " key separator, one
 * item per line, empty containers as {} / []. BigInt values become bare
 * integer tokens and floats become SCF tokens (JSON.stringify can emit
 * neither), which is why this is a custom writer. Plain objects keep
 * insertion order; Maps are emitted with sorted keys (the TS dict display
 * convention). No trailing newline -- the file writer appends it.
 */
export function schemaJson(value: unknown, indent = 0): string {
	const pad = "  ".repeat(indent);
	const inner = "  ".repeat(indent + 1);
	if (value === null || value === undefined) {
		return "null";
	}
	switch (typeof value) {
		case "bigint":
			return value.toString();
		case "number":
			return formatFloatCanonical(value);
		case "boolean":
			return value ? "true" : "false";
		case "string":
			return JSON.stringify(value);
		case "object": {
			if (Array.isArray(value)) {
				if (value.length === 0) {
					return "[]";
				}
				const items = value.map((el) => inner + schemaJson(el, indent + 1));
				return `[\n${items.join(",\n")}\n${pad}]`;
			}
			const entries =
				value instanceof Map
					? [...(value as Map<unknown, unknown>).entries()]
							.map(([k, v]): [string, unknown] => [String(k), v])
							.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
					: Object.entries(value).filter(([, v]) => v !== undefined);
			if (entries.length === 0) {
				return "{}";
			}
			const items = entries.map(
				([k, v]) =>
					`${inner}${JSON.stringify(k)}: ${schemaJson(v, indent + 1)}`,
			);
			return `{\n${items.join(",\n")}\n${pad}}`;
		}
		default:
			// function/symbol cannot appear in schema dicts.
			throw new Error(
				`internal: unserializable schema value of type ${typeof value}`,
			);
	}
}

// --- Serializers (field order matches Python's insertion order) ---

/**
 * Serializes a RelativeToRoot marker machine-stably: only the declared env
 * var and path parts, never a resolved machine-specific path. Identical
 * shape across all implementations (Go serializeDefault / Python
 * _serialize_marker).
 */
function serializeMarker(m: InfraRootPath): Record<string, unknown> {
	return {
		relative_to_root: {
			env_var: m.envVar,
			parts: [...m.parts],
		},
	};
}

/** Serializes a Flag. Fields matching the schema defaults are omitted. */
function serializeFlag(f: AnyFlag): Record<string, unknown> {
	const o = flagOpts(f);
	const kind = schemaKind(f.schema);
	const d: Record<string, unknown> = {
		name: f.name,
		type: f.schema,
		help: o.help,
	};
	if (o.short !== undefined) {
		d.short = o.short;
	}
	// default: markers first (machine-stable shape), then per-kind rules.
	// Absent and explicit-null defaults are both omitted (defaults.flag says
	// default: null); empty list/dict defaults are omitted (Python's
	// compound-list/dict rule).
	const dflt = o.default;
	if (isInfraRootPath(dflt)) {
		d.default = serializeMarker(dflt);
	} else if (kind === "list") {
		if (Array.isArray(dflt) && dflt.length > 0) {
			d.default = [...dflt];
		}
	} else if (kind === "dict") {
		if (dflt instanceof Map && dflt.size > 0) {
			d.default = dflt;
		}
	} else if (dflt !== undefined && dflt !== null) {
		d.default = dflt;
	}
	if (o.env !== undefined) {
		d.env = o.env;
	}
	if (o.choices !== undefined) {
		d.choices = [...o.choices];
	}
	// repeatable: never emitted (see the module comment).
	if (o.unique === true) {
		d.unique = true;
	}
	// conflict_mode: serialized only when explicitly set (omitted when
	// inheriting the app default). Additive; schema_version stays 1, so
	// consumers must treat absence as "inherit the app config_conflict_mode".
	if (o.conflictMode !== undefined) {
		d.conflict_mode = o.conflictMode;
	}
	if (o.envSeparator !== undefined) {
		d.env_separator = o.envSeparator;
	}
	// negatable: bool flags always emit it (default nil covers non-bools).
	if (f.schema === "bool") {
		d.negatable = o.negatable !== false;
	}
	// hidden: always false in the current impl, so always omitted.
	return d;
}

/** Serializes an Arg. Fields matching the schema defaults are omitted. */
function serializeArg(a: AnyArg): Record<string, unknown> {
	const o = a.opts;
	const d: Record<string, unknown> = {
		name: a.name,
		help: o.help,
	};
	if (a.schema !== "str") {
		d.type = a.schema;
	}
	if (o.required === false) {
		d.required = false;
	}
	if (o.default !== undefined) {
		d.default = o.default;
	}
	if (o.variadic === true) {
		d.variadic = true;
	}
	const choices = (o as { choices?: readonly unknown[] }).choices;
	if (choices !== undefined) {
		d.choices = [...choices];
	}
	return d;
}

/** Builds the constraints array from a command's mutex groups and dependencies. */
function serializeConstraints(def: AnyCommand): Record<string, unknown>[] {
	const constraints: Record<string, unknown>[] = [];
	for (const mg of def.mutex) {
		constraints.push({
			type: "mutex",
			flags: Object.values(mg.flags).map((f) => f.name),
		});
	}
	for (const dep of def.dependencies) {
		switch (dep.kind) {
			case "co-required":
				constraints.push({ type: "co_required", flags: [...dep.flags] });
				break;
			case "requires":
				constraints.push({
					type: "requires",
					flag: dep.flag,
					depends_on: dep.dependsOn,
				});
				break;
			case "implies":
				constraints.push({
					type: "implies",
					flag: dep.flag,
					implies: dep.implies,
					value: dep.value,
				});
				break;
		}
	}
	return constraints;
}

/** Serializes a registered command (regular or passthrough). */
function serializeCommand(rc: RegisteredCommand): Record<string, unknown> {
	const d: Record<string, unknown> = {
		name: rc.name,
		help: rc.help,
	};
	if (rc.kind === "passthrough") {
		d.passthrough = true;
	}
	if (rc.flags.length > 0) {
		d.flags = rc.flags.map(serializeFlag);
	}
	if (rc.kind === "command") {
		const def = rc.def as AnyCommand;
		if (def.args.length > 0) {
			d.args = def.args.map(serializeArg);
		}
	}
	// tags: merged (own + inherited group) tags, already deduped and sorted.
	if (rc.tags.length > 0) {
		d.tags = [...rc.tags];
	}
	if (rc.kind === "command") {
		const def = rc.def as AnyCommand;
		const constraints = serializeConstraints(def);
		if (constraints.length > 0) {
			d.constraints = constraints;
		}
		if (rc.hidden) {
			d.hidden = true;
		}
		if (def.interactive) {
			d.interactive = true;
		}
		if (rc.configFields.length > 0) {
			d.config_fields = [...rc.configFields];
		}
	} else if (rc.hidden) {
		d.hidden = true;
	}
	return d;
}

/** Serializes a Group (recursive). Own tags only, not accumulated. */
function serializeGroup(grp: GroupImpl): Record<string, unknown> {
	const d: Record<string, unknown> = {
		name: grp.name,
		help: grp.help,
	};
	if (grp.commands.size > 0) {
		const commands: Record<string, unknown> = {};
		for (const [name, cmd] of grp.commands) {
			commands[name] = serializeCommand(cmd);
		}
		d.commands = commands;
	}
	if (grp.groups.size > 0) {
		const groups: Record<string, unknown> = {};
		for (const [name, sub] of grp.groups) {
			groups[name] = serializeGroup(sub);
		}
		d.groups = groups;
	}
	if (grp.deprecated.size > 0) {
		d.deprecated = Object.fromEntries(grp.deprecated);
	}
	if (grp.tags.length > 0) {
		d.tags = [...grp.tags].sort();
	}
	if (grp.hidden) {
		d.hidden = true;
	}
	return d;
}

/**
 * Returns the canonical defaults object for the schema. Consumers use this
 * to reconstruct omitted fields.
 */
function buildSchemaDefaults(): Record<string, unknown> {
	return {
		schema_version: 1n,
		app: {
			env_prefix: null,
			config: false,
			global_flags: [],
			commands: {},
			groups: {},
			deprecated: {},
			tag_contracts: {},
		},
		flag: {
			short: null,
			default: null,
			env: null,
			choices: null,
			repeatable: false,
			unique: false,
			env_separator: null,
			negatable: null,
			hidden: false,
		},
		arg: {
			type: "str",
			required: true,
			default: null,
			variadic: false,
			choices: null,
		},
		command: {
			passthrough: false,
			flags: [],
			args: [],
			tags: [],
			constraints: [],
			hidden: false,
			interactive: false,
		},
		group: {
			commands: {},
			groups: {},
			deprecated: {},
			tags: [],
			hidden: false,
		},
	};
}

// --- Core schema production (CWD-free) ---

/** Records which commands (space-joined paths) bind each config field. */
function collectConfigFieldBindings(app: AppImpl): Map<string, string[]> {
	const bindings = new Map<string, string[]>();
	for (const name of app.configFields.keys()) {
		bindings.set(name, []);
	}
	const collect = (
		commands: ReadonlyMap<string, RegisteredCommand>,
		path: readonly string[],
	): void => {
		for (const cmd of commands.values()) {
			const cmdPath = [...path, cmd.name].join(" ");
			for (const cfName of cmd.configFields) {
				bindings.get(cfName)?.push(cmdPath);
			}
		}
	};
	const collectGroup = (grp: GroupImpl, path: readonly string[]): void => {
		const groupPath = [...path, grp.name];
		collect(grp.commands, groupPath);
		for (const sub of grp.groups.values()) {
			collectGroup(sub, groupPath);
		}
	};
	collect(app.commands, []);
	for (const grp of app.groups.values()) {
		collectGroup(grp, []);
	}
	return bindings;
}

/** Serializes one declared config field entry. */
function serializeConfigField(
	cf: ConfigFieldRt,
	boundCommands: readonly string[],
): Record<string, unknown> {
	const entry: Record<string, unknown> = {
		type: cf.schema,
		help: cf.help,
		required: cf.required,
	};
	if (cf.hasDefault) {
		entry.default = cf.default;
	}
	if (boundCommands.length > 0) {
		entry.bound_commands = [...boundCommands];
	}
	return entry;
}

/**
 * Builds the full schema dict, excluding project_id.
 *
 * This is the CWD-free, filesystem-free core of schema production. It reads
 * only the in-memory App; project_id is the only field that requires reading
 * package.json from the CWD, so it is added later by the file-writer path.
 * Fields matching their defaults are omitted; see buildSchemaDefaults().
 */
export function dumpSchemaCore(app: AppImpl): Record<string, unknown> {
	const schema: Record<string, unknown> = {
		schema_version: 1n,
		defaults: buildSchemaDefaults(),
		name: app.name,
		version: app.version,
		help: app.help,
	};
	if (app.envPrefix !== undefined) {
		schema.env_prefix = app.envPrefix;
	}
	if (app.configEnabled) {
		schema.config = true;
	}
	if (app.globalFlags.length > 0) {
		schema.global_flags = app.globalFlags.map(serializeFlag);
	}
	if (app.commands.size > 0) {
		const commands: Record<string, unknown> = {};
		for (const [name, cmd] of app.commands) {
			commands[name] = serializeCommand(cmd);
		}
		schema.commands = commands;
	}
	if (app.groups.size > 0) {
		const groups: Record<string, unknown> = {};
		for (const [name, grp] of app.groups) {
			groups[name] = serializeGroup(grp);
		}
		schema.groups = groups;
	}
	if (app.deprecated.size > 0) {
		schema.deprecated = Object.fromEntries(app.deprecated);
	}
	if (app.tagContracts.size > 0) {
		schema.tag_contracts = Object.fromEntries(app.tagContracts);
	}
	// checks: only present when checks are enabled. Provider-sourced checks
	// (registerCheckProvider) are deliberately EXCLUDED: providers materialize
	// lazily per-cwd at check-run time, so they are not part of the static,
	// committed schema. The schema describes the declared surface, not the
	// dynamically-materialized one.
	if (app.checks.enabled) {
		const checksMap: Record<string, unknown> = {};
		for (const [name, def] of app.checks.defs) {
			if (app.checks.providerSourcedNames.has(name)) {
				continue;
			}
			const entry: Record<string, unknown> = {
				tags: [...def.tags],
				severity: def.severity,
				fast: def.fast,
				pure: def.pure,
				needs_network: def.needsNetwork,
				depends_on: [...def.dependsOn],
			};
			if (def.scope !== "") {
				entry.scope = def.scope;
			}
			checksMap[name] = entry;
		}
		schema.checks = checksMap;
	}
	if (app.configFields.size > 0) {
		const bindings = collectConfigFieldBindings(app);
		const cfSchema: Record<string, unknown> = {};
		for (const [name, cf] of app.configFields) {
			cfSchema[name] = serializeConfigField(cf, bindings.get(name) ?? []);
		}
		schema.config_fields = cfSchema;
	}
	// infra: only present when roots or handshake vars are declared. Resolved
	// root values are intentionally EXCLUDED -- the schema must be
	// machine-stable (not machine-specific). Only the declared env var and
	// default path (both stable declarations) are emitted for roots.
	if (app.infraRootDefaults.size > 0 || app.handshakeEnvs.size > 0) {
		const infra: Record<string, unknown> = {};
		if (app.infraRootDefaults.size > 0) {
			infra.roots = [...app.infraRootDefaults].map(([envVar, dflt]) => ({
				env_var: envVar,
				default: dflt,
			}));
		}
		if (app.handshakeEnvs.size > 0) {
			infra.handshakes = [...app.handshakeEnvs].map(([envVar, helpText]) => ({
				env_var: envVar,
				help: helpText,
			}));
		}
		schema.infra = infra;
	}
	return schema;
}

// --- project_id and the file-writer path (CWD-dependent) ---

/** Reads the project name from package.json in the current working directory. */
function readProjectId(): string {
	let raw: string;
	try {
		raw = readFileSync("package.json", "utf8");
	} catch {
		throw new Error(errCannotDetermineProjectIDNoPackageJson());
	}
	let parsed: unknown;
	try {
		parsed = JSON.parse(raw);
	} catch (e) {
		throw new Error(errCannotDetermineProjectIDReadError((e as Error).message));
	}
	const name =
		typeof parsed === "object" && parsed !== null
			? (parsed as { name?: unknown }).name
			: undefined;
	if (typeof name !== "string" || name === "") {
		throw new Error(errCannotDetermineProjectIDNoName());
	}
	return name;
}

/**
 * Produces the full schema dict including project_id (reads the CWD).
 * project_id is inserted immediately after defaults so the on-disk layout is
 * stable and byte-identical to the core dict once project_id is removed
 * (Python's _dump_schema layout).
 */
function dumpSchema(app: AppImpl): Record<string, unknown> {
	const core = dumpSchemaCore(app);
	const projectId = readProjectId();
	const result: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(core)) {
		result[key] = value;
		if (key === "defaults") {
			result.project_id = projectId;
		}
	}
	return result;
}

/**
 * Verifies that an existing schema file belongs to the same project. Throws
 * on mismatch. Silently passes on: missing file, unreadable file, JSON
 * without a project_id field, non-string project_id, or matching project_id.
 */
function checkSchemaProjectId(filePath: string, newProjectId: string): void {
	let raw: string;
	try {
		raw = readFileSync(filePath, "utf8");
	} catch {
		return;
	}
	let existing: unknown;
	try {
		existing = JSON.parse(raw);
	} catch {
		return;
	}
	if (typeof existing !== "object" || existing === null) {
		return;
	}
	const existingId = (existing as { project_id?: unknown }).project_id;
	if (typeof existingId !== "string") {
		return;
	}
	if (existingId !== newProjectId) {
		throw new Error(errSchemaMismatch(existingId, newProjectId));
	}
}

/**
 * Writes the schema to .strictcli/schema.json (2-space indent, trailing
 * newline) in the current working directory and returns the absolute path.
 */
export function writeSchema(app: AppImpl): string {
	const schema = dumpSchema(app);
	const dirPath = join(".", ".strictcli");
	mkdirSync(dirPath, { recursive: true });
	const filePath = join(dirPath, "schema.json");
	checkSchemaProjectId(filePath, schema.project_id as string);
	writeFileSync(filePath, `${schemaJson(schema)}\n`);
	return resolve(filePath);
}
