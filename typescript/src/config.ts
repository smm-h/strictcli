/**
 * Config subsystem: file loading (JSON + TOML), value coercion, config
 * fields, the --config/XDG path model, and the five auto-registered
 * `config` subcommands (show/set/path/edit/init).
 *
 * Parity sources: go/strictcli/config.go and the Python config sections;
 * where they diverge, Python is the ground truth (per the port convention),
 * pinned by conformance/cases/config*.json. Subcommand output strings that
 * are inline fmt/f-strings in BOTH siblings stay inline here too (the
 * values.ts precedent); genuinely new templates (TOML 1.0 gate, app-level
 * config option validation) live in errors.ts.
 *
 * Value model: config ints are bigint end-to-end (JSON int tokens and TOML
 * integers), floats are number, dict-flag values coerce to Map. The JSON
 * loader is a small strict parser (not JSON.parse) because the sibling
 * behavior needs two things V8 cannot give: the int/float distinction from
 * the source token, and 1-based line/column error positions for the
 * "config file <path>: <msg> (line X, column Y)" surface.
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { AppImpl, RegisteredCommand } from "./app.js";
import { GroupImpl } from "./app.js";
import type { Context } from "./context.js";
import {
	errConfigDictKeyTypeMismatch,
	errConfigElementTypeMismatch,
	errConfigExpectedArrayForRepeatableFlag,
	errConfigExpectedBooleanGot,
	errConfigExpectedIntegerGot,
	errConfigExpectedObjectForDictFlag,
	errConfigExpectedScalarGotArray,
	errConfigExpectedStringGot,
	errConfigFieldConflictsFramework,
	errConfigFieldDefaultMismatch,
	errConfigFieldFlagDefaultDisagree,
	errConfigFieldHelpRequired,
	errConfigFieldNameInvalid,
	errConfigFieldNameReserved,
	errConfigFieldTypeBad,
	errDuplicateConfigField,
	errDuplicateFrameworkField,
	errExpectedBoolGot,
	errExpectedFloatGot,
	errExpectedIntGot,
	errExpectedStrGot,
	errFrameworkFieldConflictsUser,
	errFrameworkFieldHelpRequired,
	errFrameworkFieldMustStartUnderscore,
	errFrameworkFieldNameInvalid,
	RegistrationError,
} from "./errors.js";
import {
	type AnyCommand,
	type AnyFlag,
	arg,
	defineCommand,
	elemSchemaOf,
	flag,
	flagOpts,
	mutexGroup,
	pyRepr,
	schemaKind,
} from "./factories.js";
import { formatFloatCanonical } from "./float.js";
import { expandTilde, isInfraRootPath } from "./infra.js";
import type { ConfigLoadResult, ConfigProvider } from "./parse.js";
import { flagParamName } from "./parse.js";
import {
	deepEqualTrees,
	parseTomlConfig,
	renderTomlValue,
	TomlLoadFailure,
	tomlDeleteKey,
	tomlSetKey,
} from "./toml.js";
import type { Carrier, ScalarSchema } from "./types.js";
import { t } from "./types.js";
import {
	findDuplicate,
	formatValueForError,
	parseBoolStrict,
	parseFloatStrictValue,
	parseIntStrict,
	splitEscaped,
} from "./values.js";

// --- Strict JSON parsing (positions + bigint ints) ---

/** A JSON config document failed to parse. line/column are 1-based; offset is 0-based. */
export class JsonLoadFailure extends Error {
	readonly line: number;
	readonly column: number;
	readonly offset: number;

	constructor(message: string, line: number, column: number, offset: number) {
		super(message);
		this.name = "JsonLoadFailure";
		this.line = line;
		this.column = column;
		this.offset = offset;
	}

	/** Python str(JSONDecodeError) form: "msg: line L column C (char N)". */
	pyDecodeErrorString(): string {
		return `${this.message}: line ${this.line} column ${this.column} (char ${this.offset})`;
	}
}

const JSON_WS = new Set([" ", "\t", "\n", "\r"]);
const JSON_NUMBER_RE = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/;

/** 1-based (line, column) of a character offset, matching Python's math. */
function textPosition(text: string, offset: number): [number, number] {
	let line = 1;
	let last = -1;
	for (let i = 0; i < offset && i < text.length; i++) {
		if (text[i] === "\n") {
			line++;
			last = i;
		}
	}
	return [line, offset - last];
}

/**
 * Minimal strict JSON parser: objects become null-prototype records
 * (insertion order preserved, no prototype pollution), integer tokens become
 * bigint, fraction/exponent tokens become number. Error messages use the
 * Python json vocabulary ("Expecting value", ...), since Python is the
 * message ground truth and V8's messages carry no reliable position.
 */
export function parseJsonConfig(text: string): unknown {
	let i = 0;

	const fail = (msg: string, at = i): never => {
		const [line, column] = textPosition(text, at);
		throw new JsonLoadFailure(msg, line, column, at);
	};

	const skipWs = (): void => {
		while (i < text.length && JSON_WS.has(text[i] as string)) {
			i++;
		}
	};

	const parseString = (): string => {
		const start = i;
		i++; // opening quote
		let out = "";
		for (;;) {
			if (i >= text.length) {
				fail("Unterminated string starting at", start);
			}
			const ch = text[i] as string;
			if (ch === '"') {
				i++;
				return out;
			}
			if (ch === "\\") {
				const esc = text[i + 1];
				switch (esc) {
					case '"':
					case "\\":
					case "/":
						out += esc;
						i += 2;
						break;
					case "b":
						out += "\b";
						i += 2;
						break;
					case "f":
						out += "\f";
						i += 2;
						break;
					case "n":
						out += "\n";
						i += 2;
						break;
					case "r":
						out += "\r";
						i += 2;
						break;
					case "t":
						out += "\t";
						i += 2;
						break;
					case "u": {
						const hex = text.slice(i + 2, i + 6);
						if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
							fail("Invalid \\uXXXX escape", i);
						}
						out += String.fromCharCode(Number.parseInt(hex, 16));
						i += 6;
						break;
					}
					default:
						fail("Invalid \\escape", i);
				}
				continue;
			}
			if ((ch.codePointAt(0) as number) < 0x20) {
				fail("Invalid control character at", i);
			}
			out += ch;
			i++;
		}
	};

	const parseValue = (): unknown => {
		if (i >= text.length) {
			fail("Expecting value");
		}
		const ch = text[i] as string;
		if (ch === "{") {
			i++;
			skipWs();
			const obj: Record<string, unknown> = Object.create(null);
			if (text[i] === "}") {
				i++;
				return obj;
			}
			for (;;) {
				if (text[i] !== '"') {
					fail("Expecting property name enclosed in double quotes");
				}
				const key = parseString();
				skipWs();
				if (text[i] !== ":") {
					fail("Expecting ':' delimiter");
				}
				i++;
				skipWs();
				obj[key] = parseValue();
				skipWs();
				if (text[i] === ",") {
					i++;
					skipWs();
					continue;
				}
				if (text[i] === "}") {
					i++;
					return obj;
				}
				fail("Expecting ',' delimiter");
			}
		}
		if (ch === "[") {
			i++;
			skipWs();
			const arr: unknown[] = [];
			if (text[i] === "]") {
				i++;
				return arr;
			}
			for (;;) {
				arr.push(parseValue());
				skipWs();
				if (text[i] === ",") {
					i++;
					skipWs();
					continue;
				}
				if (text[i] === "]") {
					i++;
					return arr;
				}
				fail("Expecting ',' delimiter");
			}
		}
		if (ch === '"') {
			return parseString();
		}
		if (ch === "-" || (ch >= "0" && ch <= "9")) {
			const m = JSON_NUMBER_RE.exec(text.slice(i));
			if (m === null) {
				fail("Expecting value");
			}
			const tok = (m as RegExpExecArray)[0];
			i += tok.length;
			return /[.eE]/.test(tok) ? Number(tok) : BigInt(tok);
		}
		if (text.startsWith("true", i)) {
			i += 4;
			return true;
		}
		if (text.startsWith("false", i)) {
			i += 5;
			return false;
		}
		if (text.startsWith("null", i)) {
			i += 4;
			return null;
		}
		fail("Expecting value");
		return undefined; // unreachable
	};

	skipWs();
	const value = parseValue();
	skipWs();
	if (i < text.length) {
		fail("Extra data");
	}
	return value;
}

// --- Nested plain-object helpers (dot-separated config keys) ---

function isRecord(v: unknown): v is Record<string, unknown> {
	return (
		typeof v === "object" &&
		v !== null &&
		!Array.isArray(v) &&
		!(v instanceof Map) &&
		!(v instanceof Date)
	);
}

/** Looks up a dot-separated key; ok=false when any segment is missing/non-map. */
export function nestedGet(
	data: Record<string, unknown>,
	dottedKey: string,
): { readonly ok: boolean; readonly value: unknown } {
	const parts = dottedKey.split(".");
	let current: unknown = data;
	for (const part of parts.slice(0, -1)) {
		if (!isRecord(current) || !Object.hasOwn(current, part)) {
			return { ok: false, value: undefined };
		}
		current = current[part];
	}
	const last = parts[parts.length - 1] as string;
	if (!isRecord(current) || !Object.hasOwn(current, last)) {
		return { ok: false, value: undefined };
	}
	return { ok: true, value: current[last] };
}

/** Sets a dot-separated key, creating (or replacing non-map) intermediates. */
export function nestedSet(
	data: Record<string, unknown>,
	dottedKey: string,
	value: unknown,
): void {
	const parts = dottedKey.split(".");
	let current = data;
	for (const part of parts.slice(0, -1)) {
		const next = current[part];
		if (isRecord(next)) {
			current = next;
		} else {
			const created: Record<string, unknown> = Object.create(null);
			current[part] = created;
			current = created;
		}
	}
	current[parts[parts.length - 1] as string] = value;
}

/** Deletes a dot-separated key, pruning now-empty intermediate maps. */
export function nestedDelete(
	data: Record<string, unknown>,
	dottedKey: string,
): boolean {
	const parts = dottedKey.split(".");
	const parents: [Record<string, unknown>, string][] = [];
	let current = data;
	for (const part of parts.slice(0, -1)) {
		const next = current[part];
		if (!isRecord(next)) {
			return false;
		}
		parents.push([current, part]);
		current = next;
	}
	const last = parts[parts.length - 1] as string;
	if (!Object.hasOwn(current, last)) {
		return false;
	}
	delete current[last];
	for (let i = parents.length - 1; i >= 0; i--) {
		const [parent, key] = parents[i] as [Record<string, unknown>, string];
		const child = parent[key] as Record<string, unknown>;
		if (Object.keys(child).length === 0) {
			delete parent[key];
		}
	}
	return true;
}

/** Flattens a nested record to dot-separated leaf key paths. */
export function collectNestedKeys(
	data: Record<string, unknown>,
	prefix = "",
): string[] {
	const keys: string[] = [];
	for (const [k, v] of Object.entries(data)) {
		const fullKey = prefix === "" ? k : `${prefix}.${k}`;
		if (isRecord(v)) {
			keys.push(...collectNestedKeys(v, fullKey));
		} else {
			keys.push(fullKey);
		}
	}
	return keys;
}

// --- Config file path and loading ---

/**
 * The config file path for an app: the override (with ~ expanded, Python
 * behavior) when present, else $XDG_CONFIG_HOME/<name>/config.<ext> with
 * ~/.config as the XDG fallback.
 */
export function configFilePath(
	appName: string,
	override: string | undefined,
	format: string,
): string {
	if (override !== undefined && override !== "") {
		return expandTilde(override);
	}
	const configHome = process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config");
	const ext = format === "toml" ? "toml" : "json";
	return join(configHome, appName, `config.${ext}`);
}

export interface ConfigFileResult {
	readonly data: Record<string, unknown>;
	/** Non-empty when the file exists but is malformed (with position info). */
	readonly parseErr?: string;
}

/**
 * Loads the config file. Missing file with isRuntimeFlag (the user passed
 * --config) is a hard error; missing file otherwise is soft (empty data).
 * Malformed files are always hard errors with 1-based position info.
 */
export function loadConfigFile(
	appName: string,
	override: string | undefined,
	format: string,
	isRuntimeFlag: boolean,
): ConfigFileResult {
	const path = configFilePath(appName, override, format);
	let text: string;
	try {
		text = readFileSync(path, "utf8");
	} catch {
		if (isRuntimeFlag) {
			return { data: {}, parseErr: `config file not found: ${path}` };
		}
		return { data: {} };
	}
	if (format === "toml") {
		try {
			return { data: parseTomlConfig(text) };
		} catch (e) {
			if (e instanceof TomlLoadFailure) {
				const pos =
					e.line !== undefined ? ` (line ${e.line}, column ${e.column})` : "";
				return {
					data: {},
					parseErr: `config file ${path}: ${e.message}${pos}`,
				};
			}
			throw e;
		}
	}
	let parsed: unknown;
	try {
		parsed = parseJsonConfig(text);
	} catch (e) {
		if (e instanceof JsonLoadFailure) {
			return {
				data: {},
				parseErr: `config file ${path}: ${e.message} (line ${e.line}, column ${e.column})`,
			};
		}
		throw e;
	}
	if (!isRecord(parsed)) {
		// The Go side hard-errors here (cannot unmarshal into a map); Python
		// tolerates it and misbehaves later. Hard error, with position 1:1.
		return {
			data: {},
			parseErr: `config file ${path}: expected object, got ${configTypename(parsed)} (line 1, column 1)`,
		};
	}
	return { data: parsed };
}

// --- Type names and coercion ---

/** Python _config_typename vocabulary for config-decoded values. */
export function configTypename(v: unknown): string {
	if (typeof v === "boolean") {
		return "bool";
	}
	if (typeof v === "bigint") {
		return "int";
	}
	if (typeof v === "number") {
		return "float";
	}
	if (typeof v === "string") {
		return "str";
	}
	if (v === null || v === undefined) {
		return "null";
	}
	if (Array.isArray(v)) {
		return "array";
	}
	if (isRecord(v) || v instanceof Map) {
		return "object";
	}
	const ctor = (v as { constructor?: { name?: string } }).constructor?.name;
	return ctor !== undefined && ctor !== "" ? ctor : typeof v;
}

/**
 * Coerces one config value to a scalar schema with the long type-name
 * vocabulary ("expected boolean/integer/string/float"), the flag coercion
 * path. Throws a plain Error with the bare message.
 */
function coerceConfigScalarLong(value: unknown, schema: ScalarSchema): unknown {
	switch (schema) {
		case "bool":
			if (typeof value === "boolean") {
				return value;
			}
			throw new Error(errConfigExpectedBooleanGot(configTypename(value)));
		case "int":
			if (typeof value === "bigint") {
				return value;
			}
			// Floats never coerce to int (Python semantics; Go accepts integral
			// floats, Python is the divergence ground truth).
			throw new Error(errConfigExpectedIntegerGot(configTypename(value)));
		case "float":
			if (typeof value === "bigint") {
				return Number(value);
			}
			if (typeof value === "number") {
				return value;
			}
			throw new Error(errExpectedFloatGot(configTypename(value)));
		case "str":
			if (typeof value === "string") {
				return value;
			}
			throw new Error(errConfigExpectedStringGot(configTypename(value)));
	}
}

/**
 * Coerces a config value to a flag's type: dict flags take objects (-> Map),
 * list flags take arrays, scalars take scalars. Throws a plain Error with the
 * bare message; parse.ts wraps it as "--flag: config value error: <msg>".
 */
export function coerceConfigValueForFlag(value: unknown, f: AnyFlag): unknown {
	const kind = schemaKind(f.schema);
	const elem = elemSchemaOf(f.carrier);
	if (kind === "dict") {
		if (!isRecord(value)) {
			throw new Error(
				errConfigExpectedObjectForDictFlag(configTypename(value)),
			);
		}
		const result = new Map<string, unknown>();
		for (const [k, v] of Object.entries(value)) {
			try {
				result.set(k, coerceConfigScalarLong(v, elem));
			} catch {
				throw new Error(
					errConfigDictKeyTypeMismatch(k, elem, configTypename(v)),
				);
			}
		}
		return result;
	}
	if (Array.isArray(value)) {
		if (kind !== "list") {
			throw new Error(errConfigExpectedScalarGotArray());
		}
		const result: unknown[] = [];
		for (const [i, el] of value.entries()) {
			try {
				result.push(coerceConfigScalarLong(el, elem));
			} catch {
				throw new Error(
					errConfigElementTypeMismatch(i, elem, configTypename(el)),
				);
			}
		}
		return result;
	}
	if (kind === "list") {
		throw new Error(
			errConfigExpectedArrayForRepeatableFlag(configTypename(value)),
		);
	}
	return coerceConfigScalarLong(value, f.schema as ScalarSchema);
}

// --- Config fields ---

export interface ConfigFieldSpec<Out = unknown> {
	readonly type: Carrier<Out, ScalarSchema>;
	readonly help: string;
	readonly default?: Out;
}

/** Runtime record of a declared config field. */
export interface ConfigFieldRt {
	readonly name: string;
	readonly schema: ScalarSchema;
	readonly help: string;
	readonly default: unknown;
	readonly hasDefault: boolean;
	/** Computed: no default means required. */
	readonly required: boolean;
}

const CONFIG_FIELD_NAME_RE = /^_?[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$/;
const SCALAR_SCHEMAS: ReadonlySet<string> = new Set([
	"str",
	"bool",
	"int",
	"float",
]);

function matchesScalarSchema(schema: ScalarSchema, v: unknown): boolean {
	switch (schema) {
		case "str":
			return typeof v === "string";
		case "bool":
			return typeof v === "boolean";
		case "int":
			return typeof v === "bigint";
		case "float":
			return typeof v === "number";
	}
}

/**
 * Registration-time agreement check for a flag colliding with a config field
 * (a validation-only coexistence): explicit defaults on both sides must be
 * equal. A flag default of undefined/null means "no default".
 */
export function checkFlagConfigFieldDefault(
	flagName: string,
	flagDefault: unknown,
	cf: ConfigFieldRt,
): void {
	const flagHas = flagDefault !== undefined && flagDefault !== null;
	if (flagHas && cf.hasDefault && !deepEqualTrees(flagDefault, cf.default)) {
		throw new RegistrationError(
			errConfigFieldFlagDefaultDisagree(
				cf.name,
				flagName,
				pyRepr(cf.default),
				pyRepr(flagDefault),
			),
		);
	}
}

/** Declares a typed config file field on the app (App.configField delegate). */
export function registerConfigField(
	app: AppImpl,
	name: string,
	spec: ConfigFieldSpec,
): void {
	// Python check order: reserved prefix, duplicates, framework conflicts,
	// then the ConfigField construction checks (help, type, name, default).
	if (name.startsWith("_")) {
		throw new RegistrationError(errConfigFieldNameReserved(name));
	}
	if (app.configFields.has(name)) {
		throw new RegistrationError(errDuplicateConfigField(name));
	}
	if (app.frameworkFields.has(name)) {
		throw new RegistrationError(errConfigFieldConflictsFramework(name));
	}
	if (typeof spec.help !== "string" || spec.help.trim() === "") {
		throw new RegistrationError(errConfigFieldHelpRequired(name));
	}
	const schema = (spec.type as { schema?: unknown } | undefined)?.schema;
	if (typeof schema !== "string" || !SCALAR_SCHEMAS.has(schema)) {
		throw new RegistrationError(errConfigFieldTypeBad(String(schema)));
	}
	if (!CONFIG_FIELD_NAME_RE.test(name)) {
		throw new RegistrationError(errConfigFieldNameInvalid(name));
	}
	const hasDefault = "default" in spec;
	if (
		hasDefault &&
		!matchesScalarSchema(schema as ScalarSchema, spec.default)
	) {
		throw new RegistrationError(
			errConfigFieldDefaultMismatch(name, pyRepr(spec.default), schema),
		);
	}
	const cf: ConfigFieldRt = {
		name,
		schema: schema as ScalarSchema,
		help: spec.help,
		default: spec.default,
		hasDefault,
		required: !hasDefault,
	};
	// A config field colliding with an existing flag's param name annotates
	// the flag; their defaults must agree. Flags registered after this field
	// are checked from the command-registration side instead.
	for (const f of collectAllFlags(app)) {
		if (flagParamName(f.name) === name) {
			checkFlagConfigFieldDefault(f.name, flagOpts(f).default, cf);
		}
	}
	app.configFields.set(name, cf);
}

/**
 * Declares an internal framework config field (underscore-prefixed names,
 * never exposed to users). Framework fields are always required-shaped (no
 * default) and exist for key-recognition only.
 */
export function registerFrameworkField(
	app: AppImpl,
	name: string,
	type: Carrier<unknown, ScalarSchema>,
	help: string,
): void {
	if (!name.startsWith("_")) {
		throw new RegistrationError(errFrameworkFieldMustStartUnderscore(name));
	}
	if (!CONFIG_FIELD_NAME_RE.test(name)) {
		throw new RegistrationError(errFrameworkFieldNameInvalid(name));
	}
	if (typeof help !== "string" || help.trim() === "") {
		throw new RegistrationError(errFrameworkFieldHelpRequired(name));
	}
	const schema = (type as { schema?: unknown } | undefined)?.schema;
	if (typeof schema !== "string" || !SCALAR_SCHEMAS.has(schema)) {
		throw new RegistrationError(errConfigFieldTypeBad(String(schema)));
	}
	if (app.frameworkFields.has(name)) {
		throw new RegistrationError(errDuplicateFrameworkField(name));
	}
	if (app.configFields.has(name)) {
		throw new RegistrationError(errFrameworkFieldConflictsUser(name));
	}
	app.frameworkFields.set(name, {
		name,
		schema: schema as ScalarSchema,
		help,
		default: undefined,
		hasDefault: false,
		required: true,
	});
}

/** Short-type-name check of a config file value against a field's declared type. */
function checkConfigFieldType(
	cf: ConfigFieldRt,
	value: unknown,
): string | undefined {
	const got = configTypename(value);
	switch (cf.schema) {
		case "bool":
			if (typeof value !== "boolean") {
				return errExpectedBoolGot(got);
			}
			break;
		case "int":
			if (typeof value !== "bigint") {
				return errExpectedIntGot(got);
			}
			break;
		case "float":
			if (typeof value !== "bigint" && typeof value !== "number") {
				return errExpectedFloatGot(got);
			}
			break;
		case "str":
			if (typeof value !== "string") {
				return errExpectedStrGot(got);
			}
			break;
	}
	return undefined;
}

/**
 * Parse-time config-field validation (Python step 2.5): every bound required
 * field must exist with the declared type, and every key in the config file
 * must be known (a flag param name, config field, or framework field).
 * Returns an error message, or undefined when all checks pass.
 */
export function validateConfigFieldsForCommand(
	app: AppImpl,
	cmdConfigFields: readonly string[],
	data: Readonly<Record<string, unknown>>,
): string | undefined {
	for (const fieldName of cmdConfigFields) {
		const cf = app.configFields.get(fieldName);
		if (cf === undefined) {
			// Defensive: bindings are validated at registration.
			return `config field "${fieldName}" is not registered`;
		}
		const found = nestedGet(data as Record<string, unknown>, fieldName);
		if (!found.ok) {
			if (cf.required) {
				return `required config field "${fieldName}" is missing from config file`;
			}
			continue;
		}
		const err = checkConfigFieldType(cf, found.value);
		if (err !== undefined) {
			return `config field "${fieldName}": ${err}`;
		}
	}
	const knownKeys = new Set<string>();
	for (const f of collectAllFlags(app)) {
		knownKeys.add(flagParamName(f.name));
	}
	for (const name of app.configFields.keys()) {
		knownKeys.add(name);
	}
	for (const name of app.frameworkFields.keys()) {
		knownKeys.add(name);
	}
	for (const key of collectNestedKeys(data as Record<string, unknown>)) {
		if (!knownKeys.has(key)) {
			return `unknown key "${key}" in config file`;
		}
	}
	return undefined;
}

// --- Flag collection and colliding fields ---

/**
 * All flags visible to the config system: global flags plus every command's
 * flags across all groups (first occurrence per name wins), skipping the
 * auto-generated config group itself.
 */
export function collectAllFlags(app: AppImpl): AnyFlag[] {
	const flags: AnyFlag[] = [...app.globalFlags];
	const seen = new Set<string>(flags.map((f) => f.name));
	const addFrom = (commands: ReadonlyMap<string, RegisteredCommand>): void => {
		for (const cmd of commands.values()) {
			for (const f of cmd.flags) {
				if (!seen.has(f.name)) {
					flags.push(f);
					seen.add(f.name);
				}
			}
		}
	};
	addFrom(app.commands);
	const walkGroup = (grp: GroupImpl): void => {
		addFrom(grp.commands);
		for (const sub of grp.groups.values()) {
			walkGroup(sub);
		}
	};
	for (const [name, grp] of app.groups) {
		if (name === "config") {
			continue; // the auto-generated config group
		}
		walkGroup(grp);
	}
	return flags;
}

/**
 * Config fields whose name equals a flag's param name, keyed by that name.
 * Such fields are validation-only: they annotate the colliding flag and
 * render once (on the flag), not as a separate config key.
 */
export function collidingConfigFields(
	app: AppImpl,
): Map<string, ConfigFieldRt> {
	const result = new Map<string, ConfigFieldRt>();
	if (app.configFields.size === 0) {
		return result;
	}
	const flagParams = new Set(
		collectAllFlags(app).map((f) => flagParamName(f.name)),
	);
	for (const [name, cf] of app.configFields) {
		if (flagParams.has(name)) {
			result.set(name, cf);
		}
	}
	return result;
}

// --- Display formatting ---

/** Python json string escaping (ensure_ascii=True). */
function pyJsonString(s: string): string {
	let out = '"';
	for (const ch of s) {
		const code = ch.codePointAt(0) as number;
		if (ch === '"' || ch === "\\") {
			out += `\\${ch}`;
		} else if (ch === "\n") {
			out += "\\n";
		} else if (ch === "\r") {
			out += "\\r";
		} else if (ch === "\t") {
			out += "\\t";
		} else if (ch === "\b") {
			out += "\\b";
		} else if (ch === "\f") {
			out += "\\f";
		} else if (code < 0x20 || code > 0x7e) {
			if (code > 0xffff) {
				// Astral plane: UTF-16 surrogate pair, like Python's json.
				for (let k = 0; k < ch.length; k++) {
					out += `\\u${ch.charCodeAt(k).toString(16).padStart(4, "0")}`;
				}
			} else {
				out += `\\u${code.toString(16).padStart(4, "0")}`;
			}
		} else {
			out += ch;
		}
	}
	return `${out}"`;
}

/**
 * Python-json.dumps-shaped serialization: ", "/": " separators (or indented
 * layout), bigint as bare integer tokens, floats in SCF, Maps as objects with
 * sorted keys (the TS dict display rule), plain objects in insertion order
 * unless sortKeys.
 */
export function jsonDumpsPy(
	value: unknown,
	indent?: number,
	sortKeys = false,
): string {
	const pad = (level: number): string =>
		indent === undefined ? "" : " ".repeat(indent * level);
	const dump = (v: unknown, level: number): string => {
		if (v === null || v === undefined) {
			return "null";
		}
		switch (typeof v) {
			case "boolean":
				return v ? "true" : "false";
			case "bigint":
				return v.toString();
			case "number":
				return formatFloatCanonical(v);
			case "string":
				return pyJsonString(v);
			default:
				break;
		}
		if (Array.isArray(v)) {
			if (v.length === 0) {
				return "[]";
			}
			const items = v.map((el) => dump(el, level + 1));
			if (indent === undefined) {
				return `[${items.join(", ")}]`;
			}
			return `[\n${items.map((s) => pad(level + 1) + s).join(",\n")}\n${pad(level)}]`;
		}
		let entries: [string, unknown][];
		if (v instanceof Map) {
			entries = [...(v as Map<unknown, unknown>).entries()]
				.map(([k, val]): [string, unknown] => [String(k), val])
				.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
		} else if (isRecord(v)) {
			entries = Object.entries(v);
			if (sortKeys) {
				entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
			}
		} else {
			return pyJsonString(String(v));
		}
		if (entries.length === 0) {
			return "{}";
		}
		const items = entries.map(
			([k, val]) => `${pyJsonString(k)}: ${dump(val, level + 1)}` as const,
		);
		if (indent === undefined) {
			return `{${items.join(", ")}}`;
		}
		return `{\n${items.map((s) => pad(level + 1) + s).join(",\n")}\n${pad(level)}}`;
	};
	return dump(value, 0);
}

/** Formats a config value for `config show` output (Python _format_config_value). */
export function formatConfigValue(v: unknown): string {
	if (v === null || v === undefined) {
		return "<nil>";
	}
	if (v instanceof Map || Array.isArray(v) || isRecord(v)) {
		return jsonDumpsPy(v);
	}
	if (typeof v === "boolean") {
		return v ? "true" : "false";
	}
	if (typeof v === "number") {
		return formatFloatCanonical(v);
	}
	if (typeof v === "bigint") {
		return v.toString();
	}
	if (typeof v === "string") {
		return v;
	}
	return String(v);
}

/**
 * Effective value and source for a flag in the `config show` context.
 * Precedence: env > config > default. "cli" is structurally impossible here
 * (config show is a subcommand; the app's own flags were never passed).
 */
export function resolveFlagShowSource(
	f: AnyFlag,
	configData: Readonly<Record<string, unknown>>,
): [value: unknown, source: string] {
	const envVar = flagOpts(f).env;
	if (envVar !== undefined) {
		const envVal = process.env[envVar];
		if (envVal !== undefined) {
			// Coerce for display; on failure show the raw string (the parse-time
			// error path handles actual errors). Python keys the coercion on
			// f.type, which is the ELEMENT type for repeatable flags and `dict`
			// (no scalar branch) for dict flags -- so dict flags stay raw.
			const elem = elemSchemaOf(f.carrier);
			try {
				if (f.schema === "bool") {
					return [parseBoolStrict(envVal), "env"];
				}
				if (schemaKind(f.schema) !== "dict") {
					if (elem === "int") {
						return [parseIntStrict(envVal), "env"];
					}
					if (elem === "float") {
						return [parseFloatStrictValue(envVal), "env"];
					}
				}
			} catch {
				return [envVal, "env"];
			}
			return [envVal, "env"];
		}
	}
	const param = flagParamName(f.name);
	if (Object.hasOwn(configData, param)) {
		return [configData[param], "config"];
	}
	// Python Flag normalizes absent list/dict defaults to []/{} at
	// construction, so config show renders them as empty containers.
	const dflt = flagOpts(f).default;
	const kind = schemaKind(f.schema);
	if (kind === "dict") {
		return [dflt instanceof Map ? dflt : new Map(), "default"];
	}
	if (kind === "list") {
		return [Array.isArray(dflt) ? dflt : [], "default"];
	}
	if (dflt !== undefined && dflt !== null) {
		return [dflt, "default"];
	}
	return [undefined, "default"];
}

// --- Template generation (config init) ---

/** Renders a flag/field default as a TOML token, Python-repr-ing markers. */
function renderTemplateTomlValue(v: unknown): string {
	if (isInfraRootPath(v)) {
		return renderTomlValue(String(v));
	}
	return renderTomlValue(v);
}

/**
 * A flag's default for template rendering: list/dict flags normalize an
 * absent default to []/{} (Python Flag construction does this normalization).
 */
function normalizeFlagTemplateDefault(f: AnyFlag): unknown {
	const dflt = flagOpts(f).default;
	const kind = schemaKind(f.schema);
	if (kind === "dict") {
		return dflt instanceof Map ? dflt : new Map<string, unknown>();
	}
	if (kind === "list") {
		return Array.isArray(dflt) ? dflt : [];
	}
	return dflt;
}

/** TOML template with comments (Python _generate_config_template_toml). */
export function generateTomlTemplate(app: AppImpl): string {
	const lines: string[] = [];
	const flags = collectAllFlags(app);
	const colliding = collidingConfigFields(app);

	for (const f of flags) {
		const param = flagParamName(f.name);
		let comment = `# ${f.opts.help}`;
		const cfCollide = colliding.get(param);
		if (cfCollide !== undefined) {
			comment += ` -- ${cfCollide.help}`;
		}
		lines.push(comment);
		const dflt = normalizeFlagTemplateDefault(f);
		if (dflt !== undefined && dflt !== null) {
			lines.push(`${param} = ${renderTemplateTomlValue(dflt)}`);
		} else {
			lines.push(`# ${param} =`);
		}
		lines.push("");
	}

	const topLevel: ConfigFieldRt[] = [];
	const sections = new Map<string, ConfigFieldRt[]>();
	for (const [name, cf] of app.configFields) {
		if (colliding.has(name)) {
			continue; // rendered once, on the flag line above
		}
		const parts = name.split(".");
		if (parts.length === 1) {
			topLevel.push(cf);
		} else {
			const section = parts[0] as string;
			const list = sections.get(section);
			if (list === undefined) {
				sections.set(section, [cf]);
			} else {
				list.push(cf);
			}
		}
	}

	for (const cf of topLevel) {
		const req = cf.required ? " (required)" : "";
		lines.push(`# ${cf.help}${req}`);
		if (!cf.required) {
			lines.push(`${cf.name} = ${renderTemplateTomlValue(cf.default)}`);
		} else {
			lines.push(`# ${cf.name} =`);
		}
		lines.push("");
	}

	for (const [section, fields] of sections) {
		lines.push(`[${section}]`);
		for (const cf of fields) {
			const subKey = cf.name.split(".").slice(1).join(".");
			const deeperParts = subKey.split(".");
			const req = cf.required ? " (required)" : "";
			if (deeperParts.length > 1) {
				const subSection = `${section}.${deeperParts[0]}`;
				const leafKey = deeperParts.slice(1).join(".");
				lines.push("");
				lines.push(`[${subSection}]`);
				lines.push(`# ${cf.help}${req}`);
				if (!cf.required) {
					lines.push(`${leafKey} = ${renderTemplateTomlValue(cf.default)}`);
				} else {
					lines.push(`# ${leafKey} =`);
				}
			} else {
				lines.push(`# ${cf.help}${req}`);
				if (!cf.required) {
					lines.push(`${subKey} = ${renderTemplateTomlValue(cf.default)}`);
				} else {
					lines.push(`# ${subKey} =`);
				}
			}
		}
		lines.push("");
	}

	return lines.length > 0 ? `${lines.join("\n")}\n` : "";
}

/** JSON template (Python _generate_config_template_json). */
export function generateJsonTemplate(app: AppImpl): string {
	const data: Record<string, unknown> = Object.create(null);
	const flags = collectAllFlags(app);
	const colliding = collidingConfigFields(app);

	for (const f of flags) {
		const param = flagParamName(f.name);
		const dflt = normalizeFlagTemplateDefault(f);
		data[param] =
			dflt === undefined || dflt === null
				? null
				: isInfraRootPath(dflt)
					? String(dflt)
					: dflt;
	}
	for (const [name, cf] of app.configFields) {
		if (colliding.has(name)) {
			continue;
		}
		nestedSet(data, name, cf.required ? null : cf.default);
	}
	return `${jsonDumpsPy(data, 2)}\n`;
}

// --- Config file mutation (config set) ---

function readFileOrEmpty(path: string): string {
	try {
		return readFileSync(path, "utf8");
	} catch {
		return "";
	}
}

/**
 * Persists `key` = `value`: the TOML path uses the comment-preserving
 * splicer on the file bytes; JSON re-serializes the in-memory data (already
 * mutated). Returns the handler exit code.
 */
function writeConfigSet(
	app: AppImpl,
	data: Record<string, unknown>,
	path: string,
	key: string,
	value: unknown,
	ctx: Context,
): number {
	nestedSet(data, key, value);
	if (app.configFormat === "toml") {
		const text = readFileOrEmpty(path);
		let newText: string;
		try {
			newText = tomlSetKey(text, key, value);
		} catch (e) {
			ctx.error(`error: cannot update config: ${(e as Error).message}`);
			return 1;
		}
		writeFileSync(path, newText);
		return 0;
	}
	writeFileSync(path, `${jsonDumpsPy(data, 2)}\n`);
	return 0;
}

/**
 * Removes `key` and persists. Returns "absent" when the key was not in the
 * loaded data, otherwise the handler exit code.
 */
function writeConfigUnset(
	app: AppImpl,
	data: Record<string, unknown>,
	path: string,
	key: string,
	ctx: Context,
): number | "absent" {
	if (!nestedDelete(data, key)) {
		return "absent";
	}
	if (app.configFormat === "toml") {
		const text = readFileOrEmpty(path);
		let newText: string;
		try {
			newText = tomlDeleteKey(text, key);
		} catch (e) {
			ctx.error(`error: cannot update config: ${(e as Error).message}`);
			return 1;
		}
		writeFileSync(path, newText);
		return 0;
	}
	writeFileSync(path, `${jsonDumpsPy(data, 2)}\n`);
	return 0;
}

// --- config set handlers ---

interface ConfigSetArgs {
	readonly key: string;
	readonly value?: string;
	readonly clear: boolean;
	readonly default: boolean;
}

/** `config set` for a config field (Python _config_set_field). */
function configSetField(
	app: AppImpl,
	key: string,
	value: string | undefined,
	cf: ConfigFieldRt,
	data: Record<string, unknown>,
	path: string,
	useClear: boolean,
	useDefault: boolean,
	ctx: Context,
): number {
	const hasValue = value !== undefined;
	if (useClear) {
		ctx.error("config set: --clear is only for repeatable flags");
		return 1;
	}
	if (hasValue && useDefault) {
		ctx.error("config set: cannot provide a value with --default");
		return 1;
	}
	if (!hasValue && !useDefault) {
		ctx.error("config set: provide a value or --default");
		return 1;
	}
	if (useDefault) {
		const r = writeConfigUnset(app, data, path, key, ctx);
		if (r === "absent") {
			ctx.error(`config set: key '${key}' not in config`);
			return 1;
		}
		return r;
	}
	let typed: unknown;
	try {
		typed = coerceSetScalar(value as string, cf.schema);
	} catch (e) {
		ctx.error(`config set: key '${key}': ${(e as Error).message}`);
		return 1;
	}
	return writeConfigSet(app, data, path, key, typed, ctx);
}

/** Strict string-to-scalar coercion for config set values. */
function coerceSetScalar(raw: string, schema: ScalarSchema): unknown {
	switch (schema) {
		case "bool":
			return parseBoolStrict(raw);
		case "int":
			return parseIntStrict(raw);
		case "float":
			// parseFloatStrictValue already produces the sibling messages:
			// NaN/Inf pass through, everything else is "expected float, got '.'".
			return parseFloatStrictValue(raw);
		case "str":
			return raw;
	}
}

/** `config set` for a registered flag (the main path). */
function configSetFlag(
	app: AppImpl,
	key: string,
	value: string | undefined,
	f: AnyFlag,
	data: Record<string, unknown>,
	path: string,
	useClear: boolean,
	useDefault: boolean,
	ctx: Context,
): number {
	const hasValue = value !== undefined;
	if (useClear && useDefault) {
		ctx.error("config set: --clear and --default are mutually exclusive");
		return 1;
	}
	if (hasValue && useClear) {
		ctx.error("config set: cannot provide a value with --clear");
		return 1;
	}
	if (hasValue && useDefault) {
		ctx.error("config set: cannot provide a value with --default");
		return 1;
	}
	if (!hasValue && !useClear && !useDefault) {
		ctx.error("config set: provide a value, --clear, or --default");
		return 1;
	}

	const kind = schemaKind(f.schema);
	const elem = elemSchemaOf(f.carrier);

	if (useClear) {
		let cleared: unknown;
		if (kind === "dict") {
			cleared = Object.create(null) as Record<string, unknown>;
		} else if (kind === "list") {
			cleared = [];
		} else {
			ctx.error("config set: --clear is only for repeatable flags");
			return 1;
		}
		return writeConfigSet(app, data, path, key, cleared, ctx);
	}

	if (useDefault) {
		const r = writeConfigUnset(app, data, path, key, ctx);
		if (r === "absent") {
			ctx.error(`config set: key '${key}' not in config`);
			return 1;
		}
		return r;
	}

	let typed: unknown;
	if (kind === "dict") {
		// Dict flags take a JSON object value (Python semantics).
		let parsed: unknown;
		try {
			parsed = parseJsonConfig(value as string);
		} catch (e) {
			const detail =
				e instanceof JsonLoadFailure
					? e.pyDecodeErrorString()
					: (e as Error).message;
			ctx.error(`config set: key '${key}': invalid JSON: ${detail}`);
			return 1;
		}
		if (!isRecord(parsed)) {
			ctx.error(`config set: key '${key}': expected JSON object`);
			return 1;
		}
		const typedDict: Record<string, unknown> = Object.create(null);
		for (const [dk, dv] of Object.entries(parsed)) {
			try {
				typedDict[dk] = coerceConfigScalarLong(dv, elem);
			} catch (e) {
				ctx.error(
					`config set: key '${key}': value for '${dk}': ${(e as Error).message}`,
				);
				return 1;
			}
		}
		typed = typedDict;
	} else if (kind === "list") {
		const parts = splitEscaped(value as string, ",");
		const coerced: unknown[] = [];
		for (const p of parts) {
			try {
				coerced.push(coerceSetScalar(p, elem));
			} catch (e) {
				ctx.error(`config set: key '${key}': ${(e as Error).message}`);
				return 1;
			}
		}
		if (flagOpts(f).unique === true) {
			const dup = findDuplicate(coerced);
			if (dup !== undefined) {
				ctx.error(
					`config set: key '${key}': duplicate value '${formatValueForError(dup)}'`,
				);
				return 1;
			}
		}
		typed = coerced;
	} else {
		try {
			typed = coerceSetScalar(value as string, f.schema as ScalarSchema);
		} catch (e) {
			ctx.error(`config set: key '${key}': ${(e as Error).message}`);
			return 1;
		}
	}

	return writeConfigSet(app, data, path, key, typed, ctx);
}

// --- config show handler ---

function configShowHandler(
	app: AppImpl,
	useJson: boolean,
	ctx: Context,
): number {
	if (app.configParseErr !== undefined) {
		ctx.error(`error: ${app.configParseErr}`);
		return 1;
	}
	const configData = (app.configData ?? {}) as Record<string, unknown>;
	const allFlags = collectAllFlags(app);
	const colliding = collidingConfigFields(app);

	if (useJson) {
		const result: Record<string, unknown> = Object.create(null);
		for (const f of allFlags) {
			const param = flagParamName(f.name);
			const [value, source] = resolveFlagShowSource(f, configData);
			result[param] = { value: value ?? null, source };
		}
		for (const [cfName, cf] of app.configFields) {
			if (colliding.has(cfName)) {
				continue; // validation-only: rendered once, on the flag entry
			}
			const found = nestedGet(configData, cfName);
			let value: unknown;
			let source: string;
			if (found.ok) {
				value = found.value;
				source = "config";
			} else if (cf.hasDefault) {
				value = cf.default;
				source = "default";
			} else {
				value = null;
				source = "not set";
			}
			const entry: Record<string, unknown> = {
				value: value ?? null,
				source,
				type: cf.schema,
				required: cf.required,
				help: cf.help,
			};
			if (cf.hasDefault) {
				entry.default = cf.default;
			}
			result[cfName] = entry;
		}
		if (app.infraRoots.size > 0 || app.handshakeEnvs.size > 0) {
			const infra: Record<string, unknown> = Object.create(null);
			for (const [ev, resolved] of app.infraRoots) {
				infra[ev] = {
					kind: "root",
					source: app.infraRootFromEnv.get(ev) === true ? "env" : "default",
					resolved,
				};
			}
			for (const [ev, helpText] of app.handshakeEnvs) {
				const live = process.env[ev];
				const entry: Record<string, unknown> = {
					kind: "handshake",
					set: live !== undefined,
					help: helpText,
				};
				if (live !== undefined) {
					entry.value = live;
				}
				infra[ev] = entry;
			}
			result.__infrastructure__ = infra;
		}
		ctx.info(jsonDumpsPy(result, 2, true));
		return 0;
	}

	// --plain
	for (const f of allFlags) {
		const param = flagParamName(f.name);
		const [value, source] = resolveFlagShowSource(f, configData);
		let line = `${param} = ${formatConfigValue(value)}  (source: ${source})`;
		const cfCollide = colliding.get(param);
		if (cfCollide !== undefined) {
			line += `  -- ${cfCollide.help}`;
		}
		ctx.info(line);
	}
	const nonColliding = [...app.configFields.entries()].filter(
		([name]) => !colliding.has(name),
	);
	if (nonColliding.length > 0) {
		ctx.info("");
		ctx.info("Config fields:");
		for (const [cfName, cf] of nonColliding) {
			const found = nestedGet(configData, cfName);
			let value: unknown;
			let source: string;
			if (found.ok) {
				value = found.value;
				source = "config";
			} else if (cf.hasDefault) {
				value = cf.default;
				source = "default";
			} else {
				value = undefined;
				source = "not set";
			}
			const reqStr = cf.required ? "required" : "optional";
			ctx.info(
				`  ${cfName} (${cf.schema}, ${reqStr}) = ${formatConfigValue(value)}  (source: ${source})  -- ${cf.help}`,
			);
		}
	}
	if (app.infraRoots.size > 0 || app.handshakeEnvs.size > 0) {
		ctx.info("");
		ctx.info("Infrastructure:");
		for (const [ev, resolved] of app.infraRoots) {
			const src = app.infraRootFromEnv.get(ev) === true ? "env-set" : "default";
			ctx.info(`  ${ev} (root) = ${resolved}  (source: ${src})`);
		}
		for (const [ev, helpText] of app.handshakeEnvs) {
			const live = process.env[ev];
			if (live !== undefined) {
				ctx.info(`  ${ev} (handshake) = ${live}  (set)  -- ${helpText}`);
			} else {
				ctx.info(`  ${ev} (handshake) = <unset>  -- ${helpText}`);
			}
		}
	}
	return 0;
}

// --- The auto-registered config group ---

/**
 * Registers the `config` command group (path/show/set/edit/init) on the app.
 * Commands are installed directly (bypassing the app-context collision
 * checks), mirroring Python's direct Command construction -- user global
 * flags named e.g. "json" must not collide with config subcommand flags.
 */
export function registerConfigGroup(app: AppImpl): void {
	const grp = new GroupImpl(
		"config",
		"Manage persistent configuration values stored in the config file",
		[],
		[],
		false,
		app,
	);
	app.groups.set("config", grp);

	const install = (def: AnyCommand): void => {
		grp.commands.set(def.name, {
			kind: "command",
			name: def.name,
			help: def.help,
			def,
			flags: def.allFlags,
			tags: [],
			hidden: false,
			configFields: [],
		});
	};

	install(
		defineCommand("path", {
			help: "Print the absolute path to the config file for this application",
			handler: (_args, ctx) => {
				ctx.info(
					configFilePath(app.name, app.configPathOverride, app.configFormat),
				);
				return 0;
			},
		}) as AnyCommand,
	);

	install(
		defineCommand("show", {
			help: "Show all config values with their sources (config file, env, or default)",
			mutex: [
				mutexGroup({
					plain: flag("plain", t.bool, {
						help: "Display config values in a human-readable table format",
						default: false,
					}),
					json: flag("json", t.bool, {
						help: "Display config values as a JSON object with source metadata",
						default: false,
					}),
				}),
			],
			handler: (args, ctx) => configShowHandler(app, args.json, ctx),
		}) as AnyCommand,
	);

	install(
		defineCommand("set", {
			help: "Set a persistent config value that overrides the default for a flag",
			args: [
				arg("key", t.str, {
					help: "The config key to set, matching a registered flag name",
				}),
				arg("value", t.str, {
					help: "Value to set (comma-separated for repeatable flags, use backslash to escape commas)",
					required: false,
				}),
			],
			flags: {
				clear: flag("clear", t.bool, {
					help: "Clear a repeatable flag by setting its value to an empty list",
					default: false,
				}),
				default: flag("default", t.bool, {
					help: "Reset a key to its default value by removing it from the config file",
					default: false,
				}),
			},
			handler: (args, ctx) => configSetDispatch(app, args, ctx),
		}) as AnyCommand,
	);

	install(
		defineCommand("edit", {
			help: "Open the config file for manual editing in $EDITOR (creates if missing)",
			interactive: true,
			handler: (_args, ctx) => {
				const path = configFilePath(
					app.name,
					app.configPathOverride,
					app.configFormat,
				);
				mkdirSync(dirname(path), { recursive: true });
				if (!existsSync(path)) {
					writeFileSync(path, app.configFormat === "toml" ? "" : "{}\n");
				}
				const editor = process.env.EDITOR || "vi";
				const res = spawnSync(editor, [path], { stdio: "inherit" });
				if (res.error !== undefined) {
					ctx.error(`error: editor failed: ${res.error.message}`);
					return 1;
				}
				if (res.status !== 0) {
					ctx.error(`error: editor failed: exit status ${res.status}`);
					return 1;
				}
				return 0;
			},
		}) as AnyCommand,
	);

	install(
		defineCommand("init", {
			help: "Generate a template config file with documented fields and defaults",
			handler: (_args, ctx) => {
				const path = configFilePath(
					app.name,
					app.configPathOverride,
					app.configFormat,
				);
				if (existsSync(path)) {
					ctx.error(`config init: config file already exists: ${path}`);
					return 1;
				}
				mkdirSync(dirname(path), { recursive: true });
				const content =
					app.configFormat === "toml"
						? generateTomlTemplate(app)
						: generateJsonTemplate(app);
				writeFileSync(path, content);
				ctx.info(path);
				return 0;
			},
		}) as AnyCommand,
	);
}

function configSetDispatch(
	app: AppImpl,
	args: ConfigSetArgs,
	ctx: Context,
): number {
	const key = args.key;
	const path = configFilePath(
		app.name,
		app.configPathOverride,
		app.configFormat,
	);
	mkdirSync(dirname(path), { recursive: true });
	// The data loaded at parse time (Python uses _config_data the same way).
	const existing = (app.configData ?? {}) as Record<string, unknown>;

	const allFlags = collectAllFlags(app);
	const matchedFlag = allFlags.find((f) => flagParamName(f.name) === key);
	const matchedField =
		matchedFlag === undefined ? app.configFields.get(key) : undefined;
	if (matchedFlag === undefined && matchedField === undefined) {
		ctx.error(`config set: unknown key '${key}'`);
		return 1;
	}
	if (matchedField !== undefined) {
		return configSetField(
			app,
			key,
			args.value,
			matchedField,
			existing,
			path,
			args.clear,
			args.default,
			ctx,
		);
	}
	return configSetFlag(
		app,
		key,
		args.value,
		matchedFlag as AnyFlag,
		existing,
		path,
		args.clear,
		args.default,
		ctx,
	);
}

// --- The parse-pipeline config provider ---

/**
 * The ConfigProvider installed by app.dispatch: loads the config file per
 * parse (recording data and parse errors on the app for the config
 * subcommands), coerces raw config values to flag types, and runs the
 * step-2.5 config-field validation.
 */
export function makeConfigProvider(app: AppImpl): ConfigProvider {
	return {
		load(runtimePathOverride: string | undefined): ConfigLoadResult {
			app.configParseErr = undefined;
			// no-default-config-path: without an explicit --config, nothing loads.
			if (app.noDefaultConfigPath && runtimePathOverride === undefined) {
				app.configData = {};
				return { data: {} };
			}
			const override = runtimePathOverride ?? app.configPathOverride;
			const result = loadConfigFile(
				app.name,
				override,
				app.configFormat,
				runtimePathOverride !== undefined,
			);
			if (result.parseErr !== undefined) {
				app.configData = {};
				app.configParseErr = result.parseErr;
				return { data: {}, parseErr: result.parseErr };
			}
			app.configData = result.data;
			return { data: result.data };
		},
		coerce(f: AnyFlag, value: unknown): unknown {
			return coerceConfigValueForFlag(value, f);
		},
		validateFields(
			cmdConfigFields: readonly string[],
			data: Readonly<Record<string, unknown>>,
		): string | undefined {
			// Python gates step 2.5 on the app having declared config fields.
			if (app.configFields.size === 0) {
				return undefined;
			}
			return validateConfigFieldsForCommand(app, cmdConfigFields, data);
		},
	};
}
