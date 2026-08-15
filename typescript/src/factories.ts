/**
 * Declaration factories: flag and arg descriptors, dependency descriptors,
 * and command carriers, all built through `const`-typed option objects. The
 * `const` type parameters preserve literal names and exact option-object
 * types without `as const` at call sites.
 *
 * Validation runs at construction time, mirroring the siblings (Go
 * validateFlagConfig / Python Flag.__post_init__ run when the flag value is
 * built, and buildAndValidateCommand runs at registration). Messages are
 * byte-identical to the siblings; where Go and Python disagree, the Python
 * implementation is the captured ground truth (see tests/registration.test.ts).
 * App-context checks (global-flag collisions, env prefixes) live in app.ts.
 */

import type { MutatingContext, ReadOnlyContext } from "./context.js";
import {
	type Effect,
	type Forwarding,
	type Grant,
	isGrantableKind,
} from "./effects.js";
import {
	errArgBoolDefaultTypeMismatch,
	errArgChoiceMagnitude,
	errArgChoicesEmpty,
	errArgChoicesEntryNotRecord,
	errArgChoicesIncompatibleBool,
	errArgChoiceTypeMismatch,
	errArgDefaultNullNotOptional,
	errArgDefaultValueMissing,
	errArgDictTypeNotSupportedOnArgs,
	errArgFloatDefaultTypeMismatch,
	errArgHelpEmpty,
	errArgIntDefaultTypeMismatch,
	errArgListTypeOnArgsRequiresVariadicTrue,
	errArgNameConsentReserved,
	errArgPresenceDeclaredTwice,
	errArgPresenceUndeclared,
	errArgStrDefaultTypeMismatch,
	errArgVariadicDefault,
	errChoiceDuplicateName,
	errChoiceHelpEmpty,
	errChoicesEntryNotRecord,
	errCoElectableNameReuse,
	errCommandAtMostOneVariadic,
	errCommandCoRequiredDuplicate,
	errCommandCoRequiredMinFlags,
	errCommandCoRequiredUnknownFlag,
	errCommandDryRunReasonMissing,
	errCommandDryRunReasonWithoutDeclaration,
	errCommandDuplicateArg,
	errCommandDuplicateFlag,
	errCommandImpliesSameFlag,
	errCommandImpliesTargetNotBool,
	errCommandImpliesTriggerNotBool,
	errCommandImpliesUnknownFlag,
	errCommandImpliesValueMustBeBool,
	errCommandMissingHelp,
	errCommandReadOnlyConsequential,
	errCommandReadOnlyDryRunUnsupported,
	errCommandRequiresSameFlag,
	errCommandRequiresUnknownFlag,
	errCommandVariadicMustBeLast,
	errConstraintReferencesScopedFlag,
	errDeprecatedMessageEmpty,
	errDeprecatedNameEmpty,
	errFlagChoiceMagnitude,
	errFlagChoicesEmpty,
	errFlagChoicesIncompatibleBool,
	errFlagChoiceTypeMismatch,
	errFlagConflictModeBad,
	errFlagDefaultElementTypeMismatch,
	errFlagDefaultNullNotOptional,
	errFlagDefaultValueMissing,
	errFlagDictCannotCombineChoices,
	errFlagDictCannotCombineRepeatable,
	errFlagDictCannotCombineUnique,
	errFlagDictCannotUseEnvSeparator,
	errFlagDictDefaultKeyMustBeString,
	errFlagEnvSeparatorBackslash,
	errFlagEnvSeparatorRequiresEnv,
	errFlagEnvSeparatorRequiresRepeatable,
	errFlagEnvSeparatorSingleChar,
	errFlagFloatDefaultTypeMismatch,
	errFlagForceReserved,
	errFlagHelpEmpty,
	errFlagIntDefaultTypeMismatch,
	errFlagNameConsentReserved,
	errFlagNameJsonReserved,
	errFlagNameReservedByFramework,
	errFlagNameYesBanned,
	errFlagNoPrefixReserved,
	errFlagPresenceDeclaredTwice,
	errFlagPresenceUndeclared,
	errFlagRepeatableEnvRequiresSeparator,
	errFlagRepeatableIncompatibleBool,
	errFlagUniqueRequiresRepeatable,
	errForwardingReasonEmpty,
	errGrantDuplicate,
	errGrantKindInvalid,
	errGrantNameInvalid,
	errGrantReasonEmpty,
	errInvalidTagName,
	errMemberDefaultCarriesValue,
	errMemberFlagPresence,
	errMemberSelectorShort,
	errPayloadSchemaInvalid,
	errScopedNameChoiceReserved,
	errScopedNameCollidesRoot,
	errScopedNameCollidesSelector,
	errScopedNameValueReserved,
	errScopedPositional,
	errSelectorDefaultIncomplete,
	errSelectorDefaultUnknownChoice,
	errSelectorNoChoices,
	errSelectorOptional,
	errShortCollidesAcrossScopes,
	errShortOnAmbiguousElection,
	errShortShapeMismatch,
	errSiblingScopeShapeMismatch,
	errTokenChoiceCarriesPayload,
	PRESENCE_SPELLING_OPTIONAL,
	PRESENCE_SPELLING_REQUIRED,
	presenceSpellingDefault,
	RegistrationError,
} from "./errors.js";
import type { HandlerArgs } from "./infer.js";
import { type InfraRootPath, isInfraRootPath } from "./infra.js";
import { validatePayloadSchemaLiteral } from "./payload_schema.js";
import type {
	Carrier,
	Context,
	DictSchema,
	ElemSchema,
	HandlerReturn,
	ListSchema,
	ScalarSchema,
	Schema,
} from "./types.js";
import { formatChoices, formatValueForError } from "./values.js";

// --- Python-parity value formatting for registration errors ---

/**
 * Python repr() for the value kinds that appear in registration errors.
 * bigint is the TS int type (repr like a Python int); number is the TS float
 * type (integral values render with a trailing .0, like a Python float).
 */
export function pyRepr(v: unknown): string {
	switch (typeof v) {
		case "string":
			if (v.includes("'") && !v.includes('"')) {
				return `"${v.replaceAll("\\", "\\\\")}"`;
			}
			return `'${v.replaceAll("\\", "\\\\").replaceAll("'", "\\'")}'`;
		case "bigint":
			return v.toString();
		case "number":
			return Number.isInteger(v) ? `${v}.0` : String(v);
		case "boolean":
			return v ? "True" : "False";
		default:
			return String(v);
	}
}

/** strictcli type name of a runtime value (str/bool/int/float vocabulary). */
export function pyTypeName(v: unknown): string {
	if (isInfraRootPath(v)) {
		// Python type(...).__name__ of the marker class.
		return "RelativeToRoot";
	}
	switch (typeof v) {
		case "string":
			return "str";
		case "boolean":
			return "bool";
		case "bigint":
			return "int";
		case "number":
			return "float";
		default:
			return typeof v;
	}
}

function matchesScalar(schema: ScalarSchema | ElemSchema, v: unknown): boolean {
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

// --- Flags ---

/** For list carriers, the element type; for scalars and dicts, the value itself. */
/** Extracts the element type from a list output type, or returns the type itself for scalars/dicts. */
export type ElementOf<Out> = Out extends readonly (infer E)[] ? E : Out;

/** How to resolve a flag set in both CLI args and config: "cli-wins" keeps the CLI value, "error" rejects the conflict. */
export type ConflictMode = "cli-wins" | "error";

/**
 * The three-way presence declaration every flag and every arg carries
 * (contract §23.1). Exactly one of the three facts is declared, always
 * explicitly: nothing about presence is inferred from the shape of another
 * declaration.
 */
export type Presence = "required" | "optional" | "default";

/**
 * One entry of a value flag's (or arg's) `choices` list: a value with
 * OPTIONAL help (contract §24.2, §24.12's value-flag record row).
 *
 * The bare-value entry (`choices: ["head", "branches"]`) is DELETED. An entry
 * that may carry help and an entry that carries none would otherwise be two
 * spellings of one fact, which is §23's one-spelling-per-fact rule applied one
 * surface over. Help is optional -- that is what keeps §24.10's one-line
 * rendering reachable -- and, when supplied, must be non-empty like every
 * other help string in the framework.
 */
export interface ChoiceRecord<V> {
	readonly value: V;
	readonly help?: string;
}

/** Runtime view of one `choices` entry (see FlagOptsView). */
export interface ChoiceRecordView {
	readonly value: unknown;
	readonly help?: string;
}

/** The declared values of a `choices` list, in declaration order. */
export function choiceValues(
	choices: readonly ChoiceRecordView[],
): readonly unknown[] {
	return choices.map((c) => c.value);
}

/** True when any entry of a `choices` list carries help (§24.10's block rule). */
export function anyChoiceHasHelp(
	choices: readonly ChoiceRecordView[],
): boolean {
	return choices.some((c) => c.help !== undefined);
}

/**
 * Validates a `choices` list's entry SHAPE (contract §24.2). Every entry is a
 * record; a bare value is refused with the redirect §12.13 pins, and a help
 * string that is present but empty is refused like every other help string.
 * Shared by the flag and arg surfaces.
 */
function validateChoiceRecords(
	entries: readonly unknown[],
	entryNotRecord: (i: number) => string,
	helpEmpty: () => string,
): void {
	entries.forEach((entry, i) => {
		if (
			typeof entry !== "object" ||
			entry === null ||
			!Object.hasOwn(entry, "value")
		) {
			throw new RegistrationError(entryNotRecord(i));
		}
		const help = (entry as ChoiceRecordView).help;
		if (
			help !== undefined &&
			(typeof help !== "string" || help.trim() === "")
		) {
			throw new RegistrationError(helpEmpty());
		}
	});
}

/**
 * §12.14's guard, over one declaration's resolved choice values.
 *
 * An `int` choice is a `bigint` here, so the comparison is a bigint one: the
 * magnitude test is `> 2^53`, never `>=` -- 2^53 itself round-trips through a
 * double exactly. A `float` choice is a `number` and is deliberately exempt
 * (§12.14): the canonical float form round-trips to the identical double.
 */
const CHOICE_MAX_MAGNITUDE = 2n ** 53n;

function validateChoiceMagnitudes(
	values: readonly unknown[],
	magnitude: (v: string) => string,
): void {
	for (const value of values) {
		if (typeof value !== "bigint") {
			continue;
		}
		if (value > CHOICE_MAX_MAGNITUDE || value < -CHOICE_MAX_MAGNITUDE) {
			throw new RegistrationError(magnitude(String(value)));
		}
	}
}

/**
 * The options every flag carries whatever its presence declaration is.
 * Inapplicable options are `never`-typed so they cannot be provided at all:
 * negatable is bool-only; choices exclude bool and dict;
 * envSeparator/repeatable/unique are list-only (list carriers are the only
 * repeatable flags in TS -- scalar `repeatable: true` does not exist).
 */
interface FlagCommonOpts<Out, S extends Schema> {
	readonly help: string;
	readonly short?: string;
	readonly env?: string;
	readonly prefixed?: boolean;
	readonly conflictMode?: ConflictMode;
	/** Throw an Error to reject; list validators receive each element. */
	readonly validate?: (value: ElementOf<Out>) => void;
	readonly negatable?: S extends "bool" ? boolean : never;
	readonly choices?: S extends "bool" | DictSchema
		? never
		: readonly [
				ChoiceRecord<ElementOf<Out>>,
				...ChoiceRecord<ElementOf<Out>>[],
			];
	readonly envSeparator?: S extends ListSchema ? string : never;
	readonly repeatable?: S extends ListSchema ? true : never;
	readonly unique?: S extends ListSchema ? boolean : never;
	/**
	 * Marks a connection-URL (URL-class) flag. A URL-class flag MUST bind to a
	 * declared connection env (connectionEnv), enforced at registration. The
	 * binding is hermetic-suppressed, lazily read, no default; the CLI token
	 * wins over the env (source "cli" vs "env").
	 */
	readonly connectionUrl?: boolean;
	/** The declared connection env (createApp connectionEnv) this flag binds to. */
	readonly connectionEnv?: string;
}

/**
 * Per-carrier option surface, a discriminated union on `presence` (contract
 * §23.2) mirroring the three-shape union ArgOpts has carried since the port.
 *
 * - `presence: "required"` -- a value must be supplied, by CLI, env, config or
 *   an implication.
 * - `presence: "optional"` -- absence is legal and is delivered AS absence
 *   (`undefined`), for every carrier including bools (real tri-state) and
 *   compounds (no silent `[]` / `{}`).
 * - `presence: "default"` -- the framework supplies the declared value when
 *   nothing else does. The `default` member is mandatory here and illegal
 *   anywhere else; a relativeToRoot() marker resolves through a declared infra
 *   root when defaults are applied at parse time (source label "infra").
 *
 * `default: null` does not type-check and is refused at registration too, with
 * a redirect to `presence: "optional"` -- a widened option object can reach the
 * factory at runtime with a `null` the compiler never saw.
 */
export type FlagOpts<Out, S extends Schema> =
	| (FlagCommonOpts<Out, S> & {
			readonly presence: "required";
			/** Never declared here: a required flag has no value of its own. */
			readonly default?: never;
	  })
	| (FlagCommonOpts<Out, S> & {
			readonly presence: "optional";
			/** Never declared here -- `default: null` is not optionality (§23.1). */
			readonly default?: never;
	  })
	| (FlagCommonOpts<Out, S> & {
			readonly presence: "default";
			readonly default: Out | InfraRootPath;
	  });

/** A fully typed flag descriptor produced by the flag() factory. */
export interface FlagDef<
	N extends string,
	Out,
	S extends Schema,
	O extends FlagOpts<Out, S>,
> {
	readonly kind: "flag";
	readonly name: N;
	readonly schema: S;
	readonly carrier: Carrier<Out, S>;
	readonly opts: O;
	/** Phantom output type; never present at runtime. */
	readonly _out?: Out;
}

/**
 * Structural supertype of every FlagDef instantiation. Deliberately loose on
 * `opts` (exact option types vary per flag) so concrete defs assign without
 * variance traps.
 */
export interface AnyFlag {
	readonly kind: "flag";
	readonly name: string;
	readonly schema: Schema;
	readonly carrier: Carrier<unknown, Schema>;
	readonly opts: {
		readonly help: string;
		readonly short?: string;
		readonly env?: string;
		readonly presence: Presence;
		readonly default?: unknown;
	};
	readonly _out?: unknown;
}

/**
 * Runtime view of a flag's options. The generic option surface narrows
 * inapplicable options to `never` per carrier; validation reads them
 * uniformly through this widened shape.
 */
export interface FlagOptsView {
	readonly help: string;
	/** The declared presence; always one of the three after registration. */
	readonly presence: Presence;
	readonly short?: string;
	readonly env?: string;
	readonly prefixed?: boolean;
	readonly conflictMode?: string;
	readonly validate?: (value: never) => void;
	readonly default?: unknown;
	readonly negatable?: boolean;
	readonly choices?: readonly ChoiceRecordView[];
	readonly envSeparator?: string;
	readonly repeatable?: boolean;
	readonly unique?: boolean;
	/** Marks a connection-URL (URL-class) flag; must bind to a connection env. */
	readonly connectionUrl?: boolean;
	/** The declared connection env (createApp connectionEnv) this flag binds to. */
	readonly connectionEnv?: string;
}

/** Widened options of a flag descriptor, for runtime validation and parsing. */
export function flagOpts(f: AnyFlag): FlagOptsView {
	return f.opts as FlagOptsView;
}

/** Structural kind of a schema string (also used by env.ts/parse-side modules). */
export function schemaKind(schema: Schema): "scalar" | "list" | "dict" {
	if (schema.startsWith("list[")) {
		return "list";
	}
	if (schema.startsWith("dict[")) {
		return "dict";
	}
	return "scalar";
}

/** Element schema of a carrier: the item/value schema for compounds, the schema itself for scalars. */
export function elemSchemaOf(carrier: Carrier<unknown, Schema>): ScalarSchema {
	return (carrier.elem?.schema ?? carrier.schema) as ScalarSchema;
}

/** The carrier's four scalars under JSON Schema's own type names (§25.2). */
export const JSON_SCHEMA_TYPES: Readonly<Record<ScalarSchema, string>> = {
	str: "string",
	bool: "boolean",
	int: "integer",
	float: "number",
};

/** One scalar row of §25.2's fragment table, with its `enum` if any. */
export function scalarFragment(
	elem: ScalarSchema,
	values: readonly unknown[] | undefined,
): Record<string, unknown> {
	const frag: Record<string, unknown> = { type: JSON_SCHEMA_TYPES[elem] };
	if (values !== undefined) {
		frag.enum = [...values];
	}
	return frag;
}

/**
 * The JSON Schema fragment describing the value a declaration delivers: a real
 * fragment from the closed four-keyword subset (`type`, `items`,
 * `additionalProperties`, `enum`) with JSON Schema's own type names, emitted in
 * that key order (contract §25.2).
 *
 * ARITY IS VALUE SHAPE (§25.3): a list carrier and a variadic arg publish the
 * identical array fragment, which is what makes the deleted `repeatable` key a
 * second spelling of a fact the shape already carries.
 *
 * An optional declaration emits the plain type: there is no `null` in any
 * fragment and no type list, because presence is the sole authority on absence
 * and a nullable fragment would be a second statement about it.
 *
 * The same function feeds the MCP projection, so a tool schema's parameter
 * shape and the dumped one cannot disagree (§25.13).
 */
export function valueSchemaFragment(
	decl: AnyFlag | AnyArg,
): Record<string, unknown> {
	if (decl.kind === "arg") {
		const values = argChoiceValues(decl);
		const elem = elemSchemaOf(decl.carrier);
		return decl.opts.variadic === true || schemaKind(decl.schema) === "list"
			? { type: "array", items: scalarFragment(elem, values) }
			: scalarFragment(elem, values);
	}
	const kind = schemaKind(decl.schema);
	const elem = elemSchemaOf(decl.carrier);
	if (kind === "dict") {
		// A JSON object's keys are strings by definition, so the value type is a
		// complete description -- there is no `propertyNames` in the subset and
		// none is needed. A dict flag is refused choices at registration.
		return {
			type: "object",
			additionalProperties: { type: JSON_SCHEMA_TYPES[elem] },
		};
	}
	const declared = flagOpts(decl).choices;
	const values = declared === undefined ? undefined : choiceValues(declared);
	return kind === "list"
		? { type: "array", items: scalarFragment(elem, values) }
		: scalarFragment(elem, values);
}

/** An arg's declared choice values, or undefined when it declares none. */
export function argChoiceValues(a: AnyArg): readonly unknown[] | undefined {
	const declared = (a.opts as ArgOptsView).choices;
	return declared === undefined ? undefined : choiceValues(declared);
}

/**
 * The four flag names the effects regime reserves for the framework. The ban is
 * UNCONDITIONAL and applies at every level -- command flags, flag-set flags,
 * scoped sub-flags and app global flags -- because the framework extracts
 * them in the position-aware pre-scan and delivers them on the Context.
 *
 * Declared here rather than in app.ts so factories.ts can enforce the ban
 * without importing app.ts (which imports this module); app.ts folds this set
 * into its own RESERVED_GLOBAL_FLAG_NAMES.
 *
 * The four have NO short forms, so short-flag names are unaffected.
 */
export const RESERVED_FRAMEWORK_FLAG_NAMES: ReadonlySet<string> = new Set([
	"dry-run",
	"approve-consequential",
	"quiet",
	"verbose",
]);

/**
 * Names the framework refuses outright without owning a flag of that name.
 *
 * `yes` is here because --approve-consequential replaced --yes (contract
 * §7.1) and a private --yes would restate it in a spelling that IS muscle
 * memory -- exactly what the rename removed.
 */
export const BANNED_FLAG_NAMES: ReadonlySet<string> = new Set(["yes"]);

/**
 * The machine-mode flag name, reserved on the SAME unconditional every-level
 * tier as the quartet (contract §7.1's 2026-08-13 amendment). It is NOT a
 * fifth member of the quartet -- the four are the effects regime's own flags
 * and are named as a set throughout the contract -- so it carries its own
 * reserved-name message and its own pre-scan token entry.
 */
export const RESERVED_MACHINE_FLAG_NAME = "json";

/**
 * The programmatic consent PARAMETER name, reserved on both the flag surface
 * and the arg surface at every level.
 *
 * TS kwargs are an options object, so a parameter of this name cannot shadow
 * `CallOptions.approveConsequential` the way Python's keyword-only consent
 * parameter would -- but the name is framework vocabulary in every
 * implementation (app.call, Tool.execute, the MCP tools/call param), and a
 * command must mean the same thing on every channel and in every language.
 * RESERVED_FRAMEWORK_FLAG_NAMES covers the FLAG spelling
 * `approve-consequential`; this covers the underscore spelling the parameter
 * surface uses, and it is the one reserved name that reaches positional args.
 */
export const RESERVED_CONSENT_PARAM_NAME = "approve_consequential";

/** The four presence messages of one surface (flags or args). */
interface PresenceErrors {
	undeclared(name: string): string;
	declaredTwice(name: string, first: string, second: string): string;
	nullNotOptional(name: string): string;
	defaultValueMissing(name: string): string;
}

const FLAG_PRESENCE_ERRORS: PresenceErrors = {
	undeclared: errFlagPresenceUndeclared,
	declaredTwice: errFlagPresenceDeclaredTwice,
	nullNotOptional: errFlagDefaultNullNotOptional,
	defaultValueMissing: errFlagDefaultValueMissing,
};

const ARG_PRESENCE_ERRORS: PresenceErrors = {
	undeclared: errArgPresenceUndeclared,
	declaredTwice: errArgPresenceDeclaredTwice,
	nullNotOptional: errArgDefaultNullNotOptional,
	defaultValueMissing: errArgDefaultValueMissing,
};

/**
 * Resolves the declared presence at registration time (contract §23.1,
 * §12.12). The type system already refuses a `default` outside the
 * `"default"` member, but the check is enforced at runtime too: a widened
 * option object -- a conformance harness, a plain-JS consumer, an `as`
 * assertion -- reaches the factory with shapes the compiler never saw.
 *
 * Zero declared and two declared are both hard errors, and a null-valued
 * default is refused as well: it is not a spelling of optionality.
 *
 * The count check runs FIRST (§12.12's implementation-sweep box, ledger item
 * 154): `presence: "required"` or `presence: "optional"` written beside
 * `default: null` is a combination error naming both spellings, and the
 * null-default redirect is reserved for the null default written as the sole
 * declaration -- which here means either `default: null` alone or the
 * two-part `presence: "default"` carrying it. Only an untyped or JSON-driven
 * caller can reach the paired form at all (`default?: never` on the
 * required/optional members refuses it at compile time), but the runtime check
 * follows the ruling regardless.
 */
function resolvePresence(
	name: string,
	o: { readonly presence?: unknown; readonly default?: unknown },
	errs: PresenceErrors,
): Presence {
	const dflt = o.default;
	const declared = o.presence;
	if (
		(declared === "required" || declared === "optional") &&
		dflt !== undefined
	) {
		// Canonical order (required, optional, default) regardless of the order
		// they were written in, so the line is deterministic. A null default
		// reaches here too, and names the spelling that was actually written.
		throw new RegistrationError(
			errs.declaredTwice(
				name,
				declared === "required"
					? PRESENCE_SPELLING_REQUIRED
					: PRESENCE_SPELLING_OPTIONAL,
				presenceSpellingDefault(formatValueForError(dflt)),
			),
		);
	}
	if (dflt === null) {
		throw new RegistrationError(errs.nullNotOptional(name));
	}
	if (
		declared !== "required" &&
		declared !== "optional" &&
		declared !== "default"
	) {
		throw new RegistrationError(errs.undeclared(name));
	}
	if (declared === "default") {
		if (dflt === undefined) {
			throw new RegistrationError(errs.defaultValueMissing(name));
		}
		return "default";
	}
	return declared;
}

/**
 * Every flag-name ban, in one place so it re-runs at EVERY depth: on a command
 * flag, on a flag-set flag, on a selector's own name, on a member-spelled
 * choice name (which IS a flag name), and on a sub-flag declared three scopes
 * down. A ban enforced only against a flat root list is the scoped-selector
 * construct's most likely correctness defect (contract §24.7), so the bans
 * live behind one function rather than inline in one caller.
 */
function validateFlagName(name: string): void {
	if (name === "force") {
		throw new RegistrationError(errFlagForceReserved());
	}
	if (RESERVED_FRAMEWORK_FLAG_NAMES.has(name)) {
		throw new RegistrationError(errFlagNameReservedByFramework(name));
	}
	// The machine-mode flag, on the same unconditional tier (§7.1's amendment).
	if (name === RESERVED_MACHINE_FLAG_NAME) {
		throw new RegistrationError(errFlagNameJsonReserved());
	}
	// The consent parameter name, reserved on the flag surface too.
	if (name === RESERVED_CONSENT_PARAM_NAME) {
		throw new RegistrationError(errFlagNameConsentReserved());
	}
	if (BANNED_FLAG_NAMES.has(name)) {
		throw new RegistrationError(errFlagNameYesBanned());
	}
	if (name.startsWith("no-")) {
		throw new RegistrationError(errFlagNoPrefixReserved(name));
	}
}

// Mirrors Python Flag.__post_init__ (the divergence ground truth), with the
// TS carrier model: list carriers ARE the repeatable flags, dict carriers are
// Map-backed, int is bigint, float is number.
function validateFlagConfig(
	name: string,
	carrier: Carrier<unknown, Schema>,
	o: FlagOptsView,
): void {
	if (typeof o.help !== "string" || o.help.trim() === "") {
		throw new RegistrationError(errFlagHelpEmpty());
	}
	validateFlagName(name);
	const presence = resolvePresence(name, o, FLAG_PRESENCE_ERRORS);
	const kind = schemaKind(carrier.schema);
	const elem = elemSchemaOf(carrier);
	if (kind === "dict") {
		if (o.repeatable !== undefined) {
			throw new RegistrationError(errFlagDictCannotCombineRepeatable(name));
		}
		if (o.unique !== undefined) {
			throw new RegistrationError(errFlagDictCannotCombineUnique(name));
		}
		if (o.choices !== undefined) {
			throw new RegistrationError(errFlagDictCannotCombineChoices(name));
		}
	}
	if (kind === "scalar" && o.repeatable !== undefined) {
		if (carrier.schema === "bool") {
			throw new RegistrationError(errFlagRepeatableIncompatibleBool(name));
		}
		// TS-only: scalar repeatable flags do not exist -- a list carrier IS the
		// repeatable flag. No sibling message maps to this inexpressible state.
		throw new RegistrationError(
			`Flag "${name}": repeatable requires a list type`,
		);
	}
	if (kind === "scalar" && o.unique !== undefined) {
		throw new RegistrationError(errFlagUniqueRequiresRepeatable(name));
	}
	if (
		o.conflictMode !== undefined &&
		o.conflictMode !== "cli-wins" &&
		o.conflictMode !== "error"
	) {
		throw new RegistrationError(
			errFlagConflictModeBad(name, pyRepr(o.conflictMode)),
		);
	}
	if (kind === "dict") {
		if (o.envSeparator !== undefined) {
			throw new RegistrationError(errFlagDictCannotUseEnvSeparator(name));
		}
	} else {
		if (o.envSeparator !== undefined && kind !== "list") {
			throw new RegistrationError(errFlagEnvSeparatorRequiresRepeatable(name));
		}
		if (o.envSeparator !== undefined && o.env === undefined) {
			throw new RegistrationError(errFlagEnvSeparatorRequiresEnv(name));
		}
		if (
			kind === "list" &&
			o.env !== undefined &&
			o.envSeparator === undefined
		) {
			throw new RegistrationError(errFlagRepeatableEnvRequiresSeparator(name));
		}
	}
	if (o.envSeparator !== undefined && o.envSeparator.length !== 1) {
		throw new RegistrationError(errFlagEnvSeparatorSingleChar(name));
	}
	if (o.envSeparator === "\\") {
		throw new RegistrationError(errFlagEnvSeparatorBackslash(name));
	}
	if (kind !== "dict" && o.choices !== undefined) {
		if (elem === "bool") {
			throw new RegistrationError(errFlagChoicesIncompatibleBool(name));
		}
		if (!Array.isArray(o.choices) || o.choices.length === 0) {
			throw new RegistrationError(errFlagChoicesEmpty(name));
		}
		validateChoiceRecords(
			o.choices,
			(i) => errChoicesEntryNotRecord(name, i),
			() => errFlagHelpEmpty(),
		);
		for (const c of choiceValues(o.choices)) {
			if (!matchesScalar(elem, c)) {
				throw new RegistrationError(
					errFlagChoiceTypeMismatch(name, pyRepr(c), elem),
				);
			}
		}
		validateChoiceMagnitudes(choiceValues(o.choices), (v) =>
			errFlagChoiceMagnitude(name, v),
		);
	}
	// Every default check below runs only for a `presence: "default"`
	// declaration: an optional or required flag HAS no value to check, and an
	// empty collection is now a declaration rather than the framework's own
	// silent fallback (contract §23.5, §12.12's deleted templates).
	const dflt = presence === "default" ? o.default : undefined;
	if (kind === "dict" && dflt !== undefined) {
		if (!(dflt instanceof Map)) {
			throw new RegistrationError(
				`Flag "${name}": dict flag default must be a Map`,
			);
		}
		for (const [k, v] of dflt as Map<unknown, unknown>) {
			if (typeof k !== "string") {
				throw new RegistrationError(
					errFlagDictDefaultKeyMustBeString(name, pyRepr(k)),
				);
			}
			if (!matchesScalar(elem, v)) {
				throw new RegistrationError(
					`Flag "${name}": dict default value for key ${pyRepr(k)} is not of type ${elem}`,
				);
			}
		}
	} else if (kind === "list" && dflt !== undefined) {
		if (!Array.isArray(dflt)) {
			throw new RegistrationError(
				`Flag "${name}": list flag default must be an array`,
			);
		}
		for (const [i, el] of (dflt as unknown[]).entries()) {
			if (!matchesScalar(elem, el)) {
				throw new RegistrationError(
					errFlagDefaultElementTypeMismatch(name, i, elem),
				);
			}
		}
	} else if (kind === "scalar" && dflt !== undefined) {
		if (carrier.schema === "int" && typeof dflt !== "bigint") {
			throw new RegistrationError(
				errFlagIntDefaultTypeMismatch(name, pyTypeName(dflt)),
			);
		}
		if (carrier.schema === "float" && typeof dflt !== "number") {
			throw new RegistrationError(
				errFlagFloatDefaultTypeMismatch(name, pyTypeName(dflt)),
			);
		}
	}
	// The default-in-choices check applies to declared VALUES only, never to
	// absence: an optional flag declares no value, so there is nothing to match
	// against choices (§23.5's whole-table note).
	if (
		kind === "scalar" &&
		o.choices !== undefined &&
		dflt !== undefined &&
		!choiceValues(o.choices).includes(dflt)
	) {
		throw new RegistrationError(
			`Flag "${name}": default ${pyRepr(dflt)} is not in choices [${choiceValues(
				o.choices,
			)
				.map(pyRepr)
				.join(", ")}]`,
		);
	}
}

/**
 * Creates a flag descriptor for use in defineCommand(). Validates the flag
 * configuration at construction time (presence, help text, default type,
 * choices, etc.).
 */
export function flag<
	const N extends string,
	Out,
	S extends Schema,
	const O extends FlagOpts<Out, S>,
>(name: N, carrier: Carrier<Out, S>, opts: O): FlagDef<N, Out, S, O> {
	validateFlagConfig(
		name,
		carrier as Carrier<unknown, Schema>,
		opts as FlagOptsView,
	);
	return { kind: "flag", name, schema: carrier.schema, carrier, opts };
}

// --- Args ---

/**
 * The carriers a positional arg accepts: the scalars, plus the list carriers a
 * VARIADIC arg may be spelled with (§25.4). A dict carrier is refused at the
 * type level and at registration -- no implementation has ever accepted one.
 */
export type ArgSchema = ScalarSchema | ListSchema;

type ArgChoices<Out, S extends ArgSchema> = S extends "bool"
	? never
	: readonly [ChoiceRecord<ElementOf<Out>>, ...ChoiceRecord<ElementOf<Out>>[]];

/**
 * Args take scalar carriers only; a variadic arg collects Out[] (the list-arg
 * shape from the siblings is expressed as scalar carrier + `variadic: true`).
 *
 * The same three-way presence declaration flags carry (contract §23.3),
 * expressed through the same discriminated union: `required?: boolean` is
 * DELETED, not retained beside it. A variadic arg always delivers a list, so
 * `required` means at least one value and `optional` means possibly none;
 * `presence: "default"` on a variadic arg is a registration error.
 */
export type ArgOpts<Out, S extends ArgSchema> =
	| {
			readonly help: string;
			readonly presence: "required";
			/** Never declared here: a required arg has no value of its own. */
			readonly default?: never;
			readonly variadic?: boolean;
			readonly choices?: ArgChoices<Out, S>;
	  }
	| {
			readonly help: string;
			readonly presence: "optional";
			/** Never declared here -- `default: null` is not optionality (§23.1). */
			readonly default?: never;
			readonly variadic?: boolean;
			readonly choices?: ArgChoices<Out, S>;
	  }
	| {
			readonly help: string;
			readonly presence: "default";
			readonly default: Out;
			readonly variadic?: false;
			readonly choices?: ArgChoices<Out, S>;
	  };

/** A fully typed positional argument descriptor produced by the arg() factory. */
export interface ArgDef<
	N extends string,
	Out,
	S extends ArgSchema,
	O extends ArgOpts<Out, S>,
> {
	readonly kind: "arg";
	readonly name: N;
	readonly schema: S;
	readonly carrier: Carrier<Out, S>;
	readonly opts: O;
	/** Phantom output type; never present at runtime. */
	readonly _out?: Out;
}

/** Structural supertype of every ArgDef instantiation. */
export interface AnyArg {
	readonly kind: "arg";
	readonly name: string;
	/**
	 * A scalar carrier, or -- on a VARIADIC arg only -- a list carrier: the two
	 * spellings register, deliver and publish identically (§25.4).
	 */
	readonly schema: Schema;
	readonly carrier: Carrier<unknown, Schema>;
	readonly opts: {
		readonly help: string;
		readonly presence: Presence;
		readonly variadic?: boolean;
		readonly default?: unknown;
	};
	readonly _out?: unknown;
}

/** Runtime view of an arg's options (see FlagOptsView). */
export interface ArgOptsView {
	readonly help: string;
	/** The declared presence; always one of the three after registration. */
	readonly presence: Presence;
	readonly variadic?: boolean;
	readonly default?: unknown;
	readonly choices?: readonly ChoiceRecordView[];
}

/**
 * Creates a positional argument descriptor for use in defineCommand(). Args
 * take scalar carriers only; variadic args (variadic: true) collect an array.
 */
export function arg<
	const N extends string,
	Out,
	S extends ArgSchema,
	const O extends ArgOpts<Out, S>,
>(name: N, carrier: Carrier<Out, S>, opts: O): ArgDef<N, Out, S, O> {
	const o = opts as ArgOptsView;
	if (typeof o.help !== "string" || o.help.trim() === "") {
		throw new RegistrationError(errArgHelpEmpty());
	}
	// The consent parameter name is the one reserved name that reaches the
	// positional-arg surface.
	if (name === RESERVED_CONSENT_PARAM_NAME) {
		throw new RegistrationError(errArgNameConsentReserved());
	}
	const presence = resolvePresence(name, o, ARG_PRESENCE_ERRORS);
	// A variadic arg always delivers a list, so the empty case is `optional`,
	// spelled once (§23.3).
	if (presence === "default" && o.variadic === true) {
		throw new RegistrationError(errArgVariadicDefault(name));
	}
	const kind = schemaKind(carrier.schema);
	if (kind === "dict") {
		throw new RegistrationError(errArgDictTypeNotSupportedOnArgs(name));
	}
	// A variadic arg takes either spelling: the element carrier plus
	// `variadic: true` (the idiomatic one), or the list carrier the siblings
	// spell it with. Both deliver the same array and publish the same fragment
	// (§25.4); a list carrier on a NON-variadic arg is still refused, because
	// only a variadic arg delivers a list.
	if (kind === "list" && o.variadic !== true) {
		throw new RegistrationError(errArgListTypeOnArgsRequiresVariadicTrue(name));
	}
	const elem = elemSchemaOf(carrier as Carrier<unknown, Schema>);
	if (o.choices !== undefined) {
		if (elem === "bool") {
			throw new RegistrationError(errArgChoicesIncompatibleBool(name));
		}
		if (!Array.isArray(o.choices) || o.choices.length === 0) {
			throw new RegistrationError(errArgChoicesEmpty(name));
		}
		validateChoiceRecords(
			o.choices,
			(i) => errArgChoicesEntryNotRecord(name, i),
			() => errArgHelpEmpty(),
		);
		for (const c of choiceValues(o.choices)) {
			if (!matchesScalar(elem, c)) {
				throw new RegistrationError(
					errArgChoiceTypeMismatch(name, pyRepr(c), elem),
				);
			}
		}
		validateChoiceMagnitudes(choiceValues(o.choices), (v) =>
			errArgChoiceMagnitude(name, v),
		);
	}
	// As on flags, the value checks below apply to a declared value only.
	const dflt = presence === "default" ? o.default : undefined;
	if (dflt !== undefined && !matchesScalar(elem, dflt)) {
		const got = pyTypeName(dflt);
		switch (elem) {
			case "str":
				throw new RegistrationError(errArgStrDefaultTypeMismatch(name, got));
			case "int":
				throw new RegistrationError(errArgIntDefaultTypeMismatch(name, got));
			case "float":
				throw new RegistrationError(errArgFloatDefaultTypeMismatch(name, got));
			case "bool":
				throw new RegistrationError(errArgBoolDefaultTypeMismatch(name, got));
		}
	}
	if (
		o.choices !== undefined &&
		dflt !== undefined &&
		!choiceValues(o.choices).includes(dflt)
	) {
		throw new RegistrationError(
			`Arg "${name}": default ${pyRepr(dflt)} is not in choices [${choiceValues(
				o.choices,
			)
				.map(pyRepr)
				.join(", ")}]`,
		);
	}
	return { kind: "arg", name, schema: carrier.schema, carrier, opts };
}

// --- Dependency and flag-set descriptors ---

/** A named group of flags that can be shared across multiple commands. */
export interface FlagSet<N extends string, F extends FlagMap> {
	readonly kind: "flag-set";
	readonly name: N;
	readonly flags: F;
}

/** Structural supertype of every FlagSet instantiation. */
export interface AnyFlagSet {
	readonly kind: "flag-set";
	readonly name: string;
	readonly flags: FlagMap;
}

/** Creates a named flag set for sharing flags across commands. */
export function flagSet<const N extends string, const F extends FlagMap>(
	name: N,
	flags: F,
): FlagSet<N, F> {
	return { kind: "flag-set", name, flags };
}

// `MutexGroup` is DELETED (contract §21's supersession box, §24.4, §24.14).
// The exactly-one family left the constraint system entirely: every
// exactly-one shape is a selector -- member-spelled where the alternatives are
// their own flags (`memberChoiceFlag`), token-spelled where they are values of
// one flag (`choiceFlag`). There is no shim, no alias and no deprecation
// period, and no `ExactlyOne` constructor or cardinality parameter may
// reintroduce one.

/** Constraint: the listed flags must all be provided together or all be absent. */
export interface CoRequired {
	readonly kind: "co-required";
	/** Flag names (dash form), matching the sibling CoRequired shape. */
	readonly flags: readonly string[];
}

/** Creates a co-required constraint: all listed flags must appear together. */
export function coRequired(flags: readonly string[]): CoRequired {
	return { kind: "co-required", flags };
}

/** Constraint: when `flag` is provided, `dependsOn` must also be provided. */
export interface Requires {
	readonly kind: "requires";
	readonly flag: string;
	readonly dependsOn: string;
}

/** Creates a one-way dependency: `flag` requires `dependsOn` to also be set. */
export function requires(spec: {
	readonly flag: string;
	readonly dependsOn: string;
}): Requires {
	return { kind: "requires", flag: spec.flag, dependsOn: spec.dependsOn };
}

/** Constraint: when `flag` is provided, `implies` is automatically set to `value`. Both must be bool flags. */
export interface Implies {
	readonly kind: "implies";
	readonly flag: string;
	readonly implies: string;
	readonly value: boolean;
}

/** Creates an implication: when `flag` is set, auto-sets `implies` to `value`. Both must be bool flags. */
export function implies(spec: {
	readonly flag: string;
	readonly implies: string;
	readonly value: boolean;
}): Implies {
	return {
		kind: "implies",
		flag: spec.flag,
		implies: spec.implies,
		value: spec.value,
	};
}

/** Union of all inter-flag dependency constraint types. */
export type Dependency = CoRequired | Requires | Implies;

// --- Command carriers ---

/**
 * Flags are a keyed map: the map key IS the handler key, so underscore keys
 * come free (no dash-to-underscore type machinery). defineCommand verifies at
 * runtime that each key is the underscore form of its flag's name.
 */
/** A keyed map of declarations: the key is the underscore form of the name (also the handler arg key). */
export type FlagMap = Readonly<Record<string, AnyDecl>>;

/**
 * A keyed map of ORDINARY flags only. App-level global flags take this rather
 * than `FlagMap`: a global flag is resolved by the pre-command scan, before
 * any command's declaration is consulted, so there is no command whose scopes
 * an election could open (contract §24.3's pre-scan note).
 */
export type GlobalFlagMap = Readonly<Record<string, AnyFlag>>;

// --- The scoped-selector construct (contract §24) ---

/**
 * Everything that can sit in a flag map: an ordinary flag, or a SELECTOR --
 * a flag that elects exactly one of its declared choices, each of which owns
 * the flags that exist only while it is elected (contract §24.1).
 */
export type AnyDecl = AnyFlag | AnyChoiceFlag;

/** The discriminant key every elected record carries; reserved in every scope. */
export const CHOICE_TAG_KEY = "choice";
/** The key a member-spelled choice's own payload is delivered under. */
export const CHOICE_VALUE_KEY = "value";

/** One choice of a selector: mandatory help plus the scope it owns. */
export interface ChoiceDef<F extends FlagMap> {
	readonly kind: "choice";
	readonly help: string;
	readonly flags: F;
}

/**
 * A member-spelled choice's own payload: the carrier that types it plus the
 * help that documents it. Help is MANDATORY here for the same reason it is
 * mandatory on a flag -- the payload is a separate documented thing from the
 * choice that carries it, and §25.6's `value` entry publishes its own
 * `{type, help}` pair. The choice's help says what electing it means; the
 * payload's help says what the value it takes is.
 */
type ChoicePayload<Out> = {
	readonly carrier: Carrier<Out, ScalarSchema>;
	readonly help: string;
};

/**
 * A choice that carries a payload of its own, delivered under the reserved
 * name `value`. Only member spelling can carry one: a token-spelled choice is
 * named by the token itself and has nowhere to put a payload (§24.4).
 */
export interface ValueChoiceDef<Out, F extends FlagMap> {
	readonly kind: "choice";
	readonly help: string;
	readonly flags: F;
	readonly value: ChoicePayload<Out>;
}

/** Structural supertype of every choice descriptor. */
export interface AnyChoice {
	readonly kind: "choice";
	readonly help: string;
	readonly flags: FlagMap;
	readonly value?: ChoicePayload<unknown>;
}

/** A selector's choice map: the choice name (as typed) to the choice it declares. */
export type ChoiceMap = Readonly<Record<string, AnyChoice>>;

/**
 * Declares one choice of a selector. `flags` is the scope it owns -- omitted
 * for a choice that owns none, which is the degenerate case that makes this
 * construct subsume a plain constrained value with per-choice documentation.
 * `value` declares the payload a member-spelled choice's own token carries:
 * its carrier and its own help, the same pair `flag()` takes for an ordinary
 * flag's type and documentation.
 */
export function choice<const F extends FlagMap = Record<never, never>>(spec: {
	readonly help: string;
	readonly flags?: F;
}): ChoiceDef<F>;
export function choice<
	Out,
	const F extends FlagMap = Record<never, never>,
>(spec: {
	readonly help: string;
	readonly value: ChoicePayload<Out>;
	readonly flags?: F;
}): ValueChoiceDef<Out, F>;
export function choice(spec: {
	readonly help: string;
	readonly value?: ChoicePayload<unknown>;
	readonly flags?: FlagMap;
}): AnyChoice {
	const flags = spec.flags ?? {};
	return spec.value === undefined
		? { kind: "choice", help: spec.help, flags }
		: { kind: "choice", help: spec.help, flags, value: spec.value };
}

/**
 * Selector options. Presence is `required` or a `default` and NOTHING else:
 * `optional` has no union member at all, because an absent selection is a
 * choice nobody named and the answer is to name it (§24.5, ruling B2). A
 * widened caller that reaches the factory with one anyway is refused at
 * registration with the redirect §12.13 pins.
 *
 * The `default` member is typed `keyof C & string`, so a default naming a
 * choice that does not exist is a COMPILE error before it is a registration
 * error.
 */
interface ChoiceFlagCommonOpts {
	readonly help: string;
	readonly short?: string;
	readonly env?: string;
	readonly prefixed?: boolean;
	readonly conflictMode?: ConflictMode;
}

export type ChoiceFlagOpts<C extends ChoiceMap> =
	| (ChoiceFlagCommonOpts & {
			readonly presence: "required";
			/** Never declared here: a required selector has no election of its own. */
			readonly default?: never;
	  })
	| (ChoiceFlagCommonOpts & {
			readonly presence: "default";
			readonly default: keyof C & string;
	  });

/**
 * How a choice is elected on the command line (§24.12's own two strings,
 * which are also what the dumped schema publishes):
 *
 * - `selector-token`: one flag names the choice -- `--via email`.
 * - `member-flags`: each choice is spelled as its own flag -- `--profile work`
 *   elects the `profile` choice carrying "work", `--all-profiles` elects a
 *   payload-less one. The selector's own name is never typed; it is the
 *   handler key and the noun help and errors use.
 *
 * The spelling is the FACTORY's name (the defineReadOnlyCommand /
 * defineMutatingCommand precedent), so there is no option to forget and no
 * inference. Delivery is identical for both: only tokenization differs.
 */
export type ElectBy = "selector-token" | "member-flags";

/** A fully typed selector descriptor produced by the twin selector factories. */
export interface ChoiceFlagDef<
	N extends string,
	C extends ChoiceMap,
	O extends ChoiceFlagOpts<C>,
> {
	readonly kind: "choice-flag";
	readonly electBy: ElectBy;
	readonly name: N;
	readonly choices: C;
	readonly opts: O;
}

/** Structural supertype of every ChoiceFlagDef instantiation. */
export interface AnyChoiceFlag {
	readonly kind: "choice-flag";
	readonly electBy: ElectBy;
	readonly name: string;
	readonly choices: ChoiceMap;
	readonly opts: {
		readonly help: string;
		readonly short?: string;
		readonly env?: string;
		readonly prefixed?: boolean;
		readonly conflictMode?: ConflictMode;
		readonly presence: Presence;
		readonly default?: string;
	};
}

/** Converts a flag name like "dry-run" to its handler-args key "dry_run". */
export function flagParamName(flagName: string): string {
	return flagName.replace(/^-+/, "").replaceAll("-", "_");
}

/** Narrows a declaration to a selector. */
export function isChoiceFlag(d: AnyDecl): d is AnyChoiceFlag {
	return d.kind === "choice-flag";
}

/**
 * A choice map whose keys are not literal -- `{[someVariable]: choice(...)}`
 * -- silently degrades the delivered tag to `string`, which makes the switch
 * have nothing to be exhaustive over and makes `assertNever` accept anything.
 * Since silence is the failure mode, the constraint turns it into a compile
 * error naming itself (§24.12).
 */
type RequireLiteralChoiceKeys<C> = string extends keyof C
	? { readonly __choice_keys_must_be_literal: never }
	: unknown;

/**
 * Declares a TOKEN-spelled selector: `--via email` names the choice, and each
 * choice owns the flags that exist only while it is elected.
 *
 * The choice map sits where a carrier sits on `flag()`: `flag(name, t.str,
 * opts)` says "this flag's type is t.str", and `choiceFlag(name, choices,
 * opts)` says "this flag's type is this set of choices" -- for a selector, the
 * choices ARE the type.
 */
export function choiceFlag<
	const N extends string,
	const C extends ChoiceMap,
	const O extends ChoiceFlagOpts<C>,
>(
	name: N,
	choices: C & RequireLiteralChoiceKeys<C>,
	opts: O,
): ChoiceFlagDef<N, C, O> {
	return buildChoiceFlag("selector-token", name, choices, opts);
}

/**
 * Declares the same construct spelled as its own member flags: `--profile
 * work` elects the `profile` choice with the payload "work", `--all-profiles`
 * elects a payload-less one, and the selector's own name is never typed.
 *
 * This is the shape that subsumes the deleted `MutexGroup` (§21's box): it
 * reproduces that construct's error sentences byte-for-byte and its `--no-x`
 * decline semantics, and adds what a group could not express -- a member that
 * owns a scope, and a member that carries its payload in the alternative that
 * owns it.
 */
export function memberChoiceFlag<
	const N extends string,
	const C extends ChoiceMap,
	const O extends ChoiceFlagOpts<C>,
>(
	name: N,
	choices: C & RequireLiteralChoiceKeys<C>,
	opts: O,
): ChoiceFlagDef<N, C, O> {
	return buildChoiceFlag("member-flags", name, choices, opts);
}

/** Widened options of a selector descriptor, for runtime validation. */
interface ChoiceFlagOptsView {
	readonly help?: unknown;
	readonly short?: unknown;
	readonly env?: unknown;
	readonly presence?: unknown;
	readonly default?: unknown;
}

/**
 * The one place a selector's own declaration is validated. Command-context
 * checks that need to see sibling declarations (root collisions, co-electable
 * name reuse, shorts across scopes) run in buildCommandDef.
 */
function buildChoiceFlag<
	const N extends string,
	const C extends ChoiceMap,
	const O extends ChoiceFlagOpts<C>,
>(electBy: ElectBy, name: N, choices: C, opts: O): ChoiceFlagDef<N, C, O> {
	const o = opts as ChoiceFlagOptsView;
	if (typeof o.help !== "string" || o.help.trim() === "") {
		throw new RegistrationError(errFlagHelpEmpty());
	}
	// Every name ban re-runs on a selector's own name exactly as it does on an
	// ordinary flag's: a ban enforced only against a flat root list is this
	// construct's most likely correctness defect (§24.7).
	validateFlagName(name);
	// `optional` is refused with the redirect that names the remedy. The type
	// union has no `"optional"` member, so only a widened caller reaches this.
	if (o.presence === "optional") {
		throw new RegistrationError(errSelectorOptional(name));
	}
	if (o.presence !== "required" && o.presence !== "default") {
		throw new RegistrationError(errFlagPresenceUndeclared(name));
	}
	if (o.presence === "default" && o.default === undefined) {
		throw new RegistrationError(errFlagDefaultValueMissing(name));
	}
	const entries = Object.entries(choices);
	if (entries.length < 2) {
		throw new RegistrationError(errSelectorNoChoices(name));
	}
	const seenChoiceNames = new Set<string>();
	for (const [choiceName, c] of entries) {
		if (seenChoiceNames.has(choiceName)) {
			throw new RegistrationError(errChoiceDuplicateName(name, choiceName));
		}
		seenChoiceNames.add(choiceName);
		if (typeof c?.help !== "string" || c.help.trim() === "") {
			throw new RegistrationError(errChoiceHelpEmpty(name, choiceName));
		}
		// A payload rides the electing token, and a token-spelled choice's
		// electing token IS its name -- there is nowhere to put one (§24.4).
		if (electBy === "selector-token" && c.value !== undefined) {
			throw new RegistrationError(
				errTokenChoiceCarriesPayload(name, choiceName),
			);
		}
		if (electBy === "member-flags") {
			// A member's choice name IS a flag name and inherits every flag-name
			// rule, including the bans (§24.7).
			validateFlagName(choiceName);
			// TypeScript's spelling has no per-member presence slot: electing the
			// member supplies its payload, so the rule holds by construction. A
			// widened caller writing one anyway is refused (§12.13).
			const declaredPresence = (c as { readonly presence?: unknown }).presence;
			if (declaredPresence !== undefined && declaredPresence !== "required") {
				throw new RegistrationError(errMemberFlagPresence(name, choiceName));
			}
		}
		validateScopeContents(name, choiceName, c.flags);
	}
	// A member-spelled selector is never typed, so it cannot carry a short.
	if (electBy === "member-flags" && o.short !== undefined) {
		throw new RegistrationError(errMemberSelectorShort(name));
	}
	if (o.presence === "default") {
		validateSelectorDefault(name, electBy, choices, o.default as string);
	}
	validateSiblingScopeShapes(name, choices);
	return { kind: "choice-flag", electBy, name, choices, opts };
}

/**
 * A defaulted selection is COMPLETE: a choice plus every field its scope
 * needs, so a defaulted selection with an unsatisfied required sub-flag
 * cannot exist (§24.5). Electing a choice on the command line never borrows
 * the default's values, so this is the only place completeness is checkable.
 */
function validateSelectorDefault(
	name: string,
	electBy: ElectBy,
	choices: ChoiceMap,
	dflt: string,
): void {
	const spelling = presenceSpellingDefault(formatValueForError(dflt));
	const elected = choices[dflt];
	if (elected === undefined) {
		throw new RegistrationError(
			errSelectorDefaultUnknownChoice(
				name,
				spelling,
				formatChoices(Object.keys(choices)),
			),
		);
	}
	// A value-carrying member's value is supplied by the token that elects it,
	// and a default has no token (§24.5).
	if (electBy === "member-flags" && elected.value !== undefined) {
		throw new RegistrationError(
			errMemberDefaultCarriesValue(name, spelling, dflt),
		);
	}
	for (const sub of Object.values(elected.flags)) {
		if (sub.opts.presence === "required") {
			throw new RegistrationError(
				errSelectorDefaultIncomplete(name, spelling, dflt, sub.name),
			);
		}
	}
}

/**
 * The checks one choice's own scope answers: the two reserved names, the
 * scoped-positional ban, and the collision with the selector's own name.
 * Recurses through nested selectors, so every rule holds at every depth.
 */
function validateScopeContents(
	selector: string,
	choiceName: string,
	flags: FlagMap,
): void {
	for (const decl of Object.values(flags)) {
		// A positional's meaning would depend on an election that may be typed
		// after it. The typed surface cannot express one; a widened caller can.
		if ((decl as { readonly kind?: string }).kind === "arg") {
			throw new RegistrationError(errScopedPositional(choiceName, selector));
		}
		if (decl.name === CHOICE_TAG_KEY) {
			throw new RegistrationError(
				errScopedNameChoiceReserved(choiceName, selector),
			);
		}
		if (decl.name === CHOICE_VALUE_KEY) {
			throw new RegistrationError(
				errScopedNameValueReserved(choiceName, selector),
			);
		}
		if (decl.name === selector) {
			throw new RegistrationError(
				errScopedNameCollidesSelector(choiceName, selector, decl.name),
			);
		}
	}
}

/**
 * The value shape of one surface name: its type and its arity together
 * (§25.3's word for the pair). Tokenizing `--x` cannot wait for an election,
 * so two sibling scopes declaring one name must agree on it (§24.7).
 */
function valueShapeOf(s: SurfaceName): string {
	return s.takesValue ? s.shape : `${s.shape}/flag`;
}

/**
 * Sibling scopes may reuse a flag name only with an identical value shape.
 * Two choices of one selector can never be elected together, so the name is
 * unambiguous at delivery -- but tokenization precedes election.
 */
function validateSiblingScopeShapes(name: string, choices: ChoiceMap): void {
	const seen = new Map<string, { shape: string; choice: string }>();
	for (const [choiceName, c] of Object.entries(choices)) {
		for (const s of scopeSurfaceNames(c.flags)) {
			const prior = seen.get(s.name);
			if (prior === undefined) {
				seen.set(s.name, { shape: valueShapeOf(s), choice: choiceName });
				continue;
			}
			if (prior.choice === choiceName) {
				continue;
			}
			if (prior.shape !== valueShapeOf(s)) {
				throw new RegistrationError(
					errSiblingScopeShapeMismatch(name, s.name, prior.choice, choiceName),
				);
			}
		}
	}
}

/** One surface name typed on the command line, and what it tokenizes as. */
export interface SurfaceName {
	/** The dash name, without leading dashes. */
	readonly name: string;
	/** Whether the token consumes the following argv element. */
	readonly takesValue: boolean;
	/** The declared value shape, for the sibling-reuse rule. */
	readonly shape: string;
	/** For member spelling, the choice this name elects. */
	readonly elects?: string;
	/** The declaration the name belongs to. */
	readonly decl: AnyDecl;
}

/**
 * The names one declaration puts on the command line. A token-spelled
 * selector puts its own name there; a member-spelled one puts one name per
 * choice instead, and never its own.
 */
export function surfaceNames(decl: AnyDecl): SurfaceName[] {
	if (decl.kind === "flag") {
		return [
			{
				name: decl.name,
				takesValue: decl.schema !== "bool",
				shape: decl.schema,
				decl,
			},
		];
	}
	if (decl.electBy === "selector-token") {
		return [{ name: decl.name, takesValue: true, shape: "choice", decl }];
	}
	return Object.entries(decl.choices).map(([choiceName, c]) => ({
		name: choiceName,
		takesValue: c.value !== undefined,
		shape: c.value === undefined ? "bool" : c.value.carrier.schema,
		elects: choiceName,
		decl,
	}));
}

/** Every surface name declared anywhere inside a scope subtree, in declaration order. */
function scopeSurfaceNames(flags: FlagMap): SurfaceName[] {
	const out: SurfaceName[] = [];
	for (const decl of Object.values(flags)) {
		out.push(...surfaceNames(decl));
		if (decl.kind === "choice-flag") {
			for (const c of Object.values(decl.choices)) {
				out.push(...scopeSurfaceNames(c.flags));
			}
		}
	}
	return out;
}

/** One election on a scope path: a selector plus the choice it elected. */
export interface ScopeStep {
	readonly selector: AnyChoiceFlag;
	readonly choiceName: string;
}

/**
 * One segment of the pinned scope-path format (§12.13): a token-spelled
 * segment is `--<selector> <choice>`, a member-spelled one is `--<choice>`
 * (the member's own flag, which is the only token a reader ever types).
 */
export function scopeSegment(
	selector: AnyChoiceFlag,
	choiceName: string,
): string {
	return selector.electBy === "member-flags"
		? `--${choiceName}`
		: `--${selector.name} ${choiceName}`;
}

/**
 * The pinned scope-path rendering: one segment per election on the path,
 * outermost first, joined by a single space. Empty at root scope. Callers
 * wrap it in single quotes wherever a template names one.
 */
export function scopePath(path: readonly ScopeStep[]): string {
	return path.map((s) => scopeSegment(s.selector, s.choiceName)).join(" ");
}

/** The member list a member-spelled selector offers, unquoted and comma-joined. */
export function memberList(sel: AnyChoiceFlag): string {
	return Object.keys(sel.choices)
		.map((c) => `--${c}`)
		.join(", ");
}

/** One entry of the flat index every scoped surface name resolves through. */
export interface ScopeIndexEntry {
	readonly decl: AnyDecl;
	readonly path: readonly ScopeStep[];
	readonly takesValue: boolean;
	/** Set when the name is a member-spelled election (`--all-profiles`). */
	readonly elects?: string;
}

/**
 * Every surface name in one declaration tree, by dash name. One name can map
 * to several entries: two sibling choices may each declare `--subject`, since
 * they can never be elected at once.
 */
export type ScopeIndex = ReadonlyMap<string, readonly ScopeIndexEntry[]>;

/** Builds the whole-tree surface-name index for a declaration list. */
export function buildScopeIndex(decls: readonly AnyDecl[]): ScopeIndex {
	const index = new Map<string, ScopeIndexEntry[]>();
	const walk = (list: readonly AnyDecl[], path: readonly ScopeStep[]): void => {
		for (const decl of list) {
			for (const s of surfaceNames(decl)) {
				const entries = index.get(s.name) ?? [];
				entries.push(
					s.elects === undefined
						? { decl, path, takesValue: s.takesValue }
						: { decl, path, takesValue: s.takesValue, elects: s.elects },
				);
				index.set(s.name, entries);
			}
			if (decl.kind === "choice-flag") {
				for (const [choiceName, c] of Object.entries(decl.choices)) {
					walk(Object.values(c.flags), [
						...path,
						{ selector: decl, choiceName },
					]);
				}
			}
		}
	};
	walk(decls, []);
	return index;
}

/**
 * Two scopes are simultaneously electable unless some selector on both paths
 * elected DIFFERENT choices -- which is exactly when the two can never be
 * live at once. The rule is written against *simultaneously electable* rather
 * than against *sibling* deliberately: it is the formulation that still holds
 * if multi-elect is ever adopted (§24.13).
 */
function simultaneouslyElectable(
	a: readonly ScopeStep[],
	b: readonly ScopeStep[],
): boolean {
	for (const sa of a) {
		for (const sb of b) {
			if (sa.selector === sb.selector && sa.choiceName !== sb.choiceName) {
				return false;
			}
		}
	}
	return true;
}

/**
 * The whole-tree registration checks a single selector cannot answer on its
 * own, because each of them needs to see a sibling declaration: a scoped name
 * colliding with a command-level flag, a name or a short reused by two scopes
 * that can be elected at the same time (§24.7).
 */
function validateDeclTree(
	cmdName: string,
	decls: readonly AnyDecl[],
	rootNames: ReadonlySet<string>,
): void {
	const index = buildScopeIndex(decls);
	for (const [name, entries] of index) {
		// A scoped flag may not reuse a command-level flag's name: it could
		// never be reached. Checked across every entry BEFORE the pair scan, so
		// the collision is named as itself rather than as a name two scopes
		// happen to share.
		if (rootNames.has(name)) {
			const scoped = entries.find((e) => e.path.length > 0);
			if (scoped !== undefined) {
				const last = scoped.path[scoped.path.length - 1] as ScopeStep;
				throw new RegistrationError(
					errScopedNameCollidesRoot(last.choiceName, last.selector.name, name),
				);
			}
		}
		for (let i = 0; i < entries.length; i++) {
			const a = entries[i] as ScopeIndexEntry;
			for (let j = i + 1; j < entries.length; j++) {
				const b = entries[j] as ScopeIndexEntry;
				if (!simultaneouslyElectable(a.path, b.path)) {
					continue;
				}
				throw new RegistrationError(
					errCoElectableNameReuse(
						cmdName,
						name,
						scopePath(a.path),
						scopePath(b.path),
					),
				);
			}
		}
	}
	// Shorts are claimed across every simultaneously live scope; sibling
	// scopes may reuse one. Only pairs involving a scoped declaration are
	// checked here -- a root-level short collision is pre-existing surface
	// this round does not touch.
	const shorts = new Map<
		string,
		{ name: string; path: readonly ScopeStep[] }[]
	>();
	for (const entries of index.values()) {
		for (const e of entries) {
			// A member-spelled election's short belongs to its own choice flag,
			// which cannot carry one at all (§24.4).
			if (e.elects !== undefined) {
				continue;
			}
			const short = e.decl.opts.short;
			if (typeof short !== "string" || short === "") {
				continue;
			}
			const claims = shorts.get(short) ?? [];
			if (!claims.some((c) => c.name === e.decl.name)) {
				claims.push({ name: e.decl.name, path: e.path });
			}
			shorts.set(short, claims);
		}
	}
	for (const [short, claims] of shorts) {
		for (let i = 0; i < claims.length; i++) {
			for (let j = i + 1; j < claims.length; j++) {
				const a = claims[i] as { name: string; path: readonly ScopeStep[] };
				const b = claims[j] as { name: string; path: readonly ScopeStep[] };
				if (a.path.length === 0 && b.path.length === 0) {
					continue;
				}
				if (!simultaneouslyElectable(a.path, b.path)) {
					continue;
				}
				throw new RegistrationError(
					errShortCollidesAcrossScopes(cmdName, short, a.name, b.name),
				);
			}
		}
	}
	validateSiblingScopeShorts(cmdName, decls);
}

/** One token a declaration puts on the command line, for the short-claim table. */
interface DeclSite {
	readonly name: string;
	/** An `election` site is read BEFORE any election has happened. */
	readonly kind: "flag" | "election";
	readonly shape: string;
	readonly short: string | undefined;
}

/**
 * Every token reachable below a selector, in declaration order -- which is
 * what makes the two guards below cover MEMBER scopes as well as the choices
 * of a token-spelled selector. A table built only from token-spelled
 * selectors' choices leaves exactly that hazard open (§12.13, §18.19 item 221).
 *
 * Root-level ordinary flags are not sites: a root short colliding with a
 * scoped one is `errShortCollidesAcrossScopes`'s condition, checked above.
 */
function collectDeclSites(
	decls: readonly AnyDecl[],
	scoped: boolean,
	out: DeclSite[],
): void {
	for (const decl of decls) {
		if (decl.kind === "flag") {
			if (scoped) {
				const s = surfaceNames(decl)[0] as SurfaceName;
				out.push({
					name: decl.name,
					kind: "flag",
					shape: valueShapeOf(s),
					short: flagOpts(decl).short,
				});
			}
			continue;
		}
		for (const s of surfaceNames(decl)) {
			// A member-spelled election's token belongs to its own choice flag,
			// which cannot carry a short at all, and TypeScript's member payload
			// has no short slot -- so a member site claims none.
			out.push({
				name: s.name,
				kind: "election",
				shape: valueShapeOf(s),
				short: s.elects === undefined ? decl.opts.short : undefined,
			});
		}
		for (const c of Object.values(decl.choices)) {
			collectDeclSites(Object.values(c.flags), true, out);
		}
	}
}

/**
 * The two sibling-scope short rules (§18.19 item 221). Sibling scopes may
 * reuse a short -- they can never be live together -- but the binding is
 * resolved AFTER the elections, so the token must consume argv identically
 * whatever the election decides, and it may never be the token that elects.
 */
function validateSiblingScopeShorts(
	cmdName: string,
	decls: readonly AnyDecl[],
): void {
	const sites: DeclSite[] = [];
	collectDeclSites(decls, false, sites);
	const byName = new Map<string, DeclSite[]>();
	for (const site of sites) {
		const entries = byName.get(site.name) ?? [];
		entries.push(site);
		byName.set(site.name, entries);
	}
	// short -> the distinct NAMES claiming it, in declaration order. One name
	// declared by two sibling scopes is the sibling-NAME rule's business, not
	// this one's.
	const claims = new Map<string, string[]>();
	for (const site of sites) {
		if (site.short === undefined || site.short === "") {
			continue;
		}
		const names = claims.get(site.short) ?? [];
		if (!names.includes(site.name)) {
			names.push(site.name);
		}
		claims.set(site.short, names);
	}
	for (const [short, names] of claims) {
		if (names.length < 2) {
			continue;
		}
		const shapes = new Set<string>();
		for (const name of names) {
			for (const site of byName.get(name) ?? []) {
				if (site.kind !== "flag") {
					throw new RegistrationError(
						errShortOnAmbiguousElection(cmdName, short, name),
					);
				}
				shapes.add(site.shape);
			}
		}
		if (shapes.size > 1) {
			throw new RegistrationError(
				errShortShapeMismatch(
					cmdName,
					short,
					names[0] as string,
					names[1] as string,
				),
			);
		}
	}
}

/**
 * Every name declared inside SOME scope, mapped to the rendered scope path it
 * lives under -- the lookup the constraint families consult before reporting
 * an operand as unknown (§24.8).
 */
function scopedFlagPathMap(
	decls: readonly AnyDecl[],
): ReadonlyMap<string, string> {
	const out = new Map<string, string>();
	for (const [name, entries] of buildScopeIndex(decls)) {
		const scoped = entries.find((e) => e.path.length > 0);
		if (scoped !== undefined && !out.has(name)) {
			out.set(name, scopePath(scoped.path));
		}
	}
	return out;
}

/** Every ordinary flag declared anywhere inside a declaration tree. */
export function allScopedFlags(decls: readonly AnyDecl[]): AnyFlag[] {
	const out: AnyFlag[] = [];
	for (const decl of decls) {
		if (decl.kind === "flag") {
			out.push(decl);
			continue;
		}
		for (const c of Object.values(decl.choices)) {
			out.push(...allScopedFlags(Object.values(c.flags)));
		}
	}
	return out;
}

/**
 * A command handler function receiving typed args and a Context.
 *
 * `C` is the classification-narrowed context type: `defineReadOnlyCommand`
 * binds it to ReadOnlyContext (whose `effects` exposes only `run`), and
 * `defineMutatingCommand` to the full MutatingContext. A `.write()` inside a
 * read-only command is therefore a COMPILE error, on top of the runtime seal
 * every implementation carries regardless (plain-JS consumers bypass the type
 * system entirely).
 */
export type Handler<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
	C = MutatingContext,
> = (
	args: HandlerArgs<F, A, FS>,
	ctx: C,
) => HandlerReturn | Promise<HandlerReturn>;

/** A fully validated command descriptor produced by the twin factories. */
export interface CommandDef<
	N extends string,
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
	C = MutatingContext,
> {
	readonly kind: "command";
	readonly name: N;
	readonly help: string;
	/** Mandatory classification. There is no default and no inference. */
	readonly effect: Effect;
	/**
	 * Declared per-command (contract §8.1) and NOT mandatory -- absence means
	 * "not consequential". It is a property of the COMMAND, deliberately not
	 * named after the framework's reaction to it, so other behaviours can hang
	 * off it later. Today the framework prompts for exactly these commands.
	 */
	readonly consequential: boolean;
	/**
	 * Declared per-command; the default `true` is the regime's baseline (a
	 * mutating command records rather than executes under --dry-run). A command
	 * that declares it false is saying a preview of it would LIE -- its effects
	 * escape the effects handle, or its later steps read state the recorded
	 * ones would have written -- so the framework refuses --dry-run for it at
	 * parse time rather than rendering a preview nobody can trust.
	 */
	readonly dryRunSupported: boolean;
	/** Mandatory when dryRunSupported is false; shown in help and the refusal. */
	readonly dryRunUnsupportedReason: string | undefined;
	/**
	 * The command's machine payload contract (contract §19.5): an inline JSON
	 * Schema literal, registered as written. Absence means the command cannot
	 * produce a payload -- ctx.payload is then a call-time hard error. The
	 * literal is stored opaquely at this round; validating a payload against it
	 * is a later item.
	 */
	readonly payloadSchema: Readonly<Record<string, unknown>> | undefined;
	/**
	 * Declares that this command's stdout IS the artifact (contract §19.6).
	 * In machine mode stdout carries the command's own document byte-exactly
	 * and the envelope moves to stderr with the diagnostics it carries.
	 * Outside machine mode the declaration changes nothing at all.
	 */
	readonly ownsStdout: boolean;
	readonly flags: F;
	readonly args: A;
	readonly flagSets: FS;
	readonly dependencies: readonly Dependency[];
	/**
	 * Merged ROOT-LEVEL declaration list (own flags, then flag-set flags), in
	 * declaration order. A selector appears here as one entry; the flags its
	 * choices own are reachable only through it (contract §24.1).
	 */
	readonly allDecls: readonly AnyDecl[];
	/** The root-level ORDINARY flags of allDecls, in declaration order. */
	readonly allFlags: readonly AnyFlag[];
	readonly handler: Handler<F, A, FS, C>;
	readonly tags: readonly string[];
	readonly hidden: boolean;
	readonly interactive: boolean;
	readonly configFields: readonly string[];
	/** Per-effect-kind authorizations with mandatory human reasons. */
	readonly grants: readonly Grant[];
	/** Declared forwarding (inert in TS beyond the schema emission). */
	readonly forwarding: Forwarding | undefined;
}

/** Structural supertype of every CommandDef instantiation. */
export interface AnyCommand {
	readonly kind: "command";
	readonly name: string;
	readonly help: string;
	readonly effect: Effect;
	readonly consequential: boolean;
	readonly dryRunSupported: boolean;
	readonly dryRunUnsupportedReason: string | undefined;
	readonly payloadSchema: Readonly<Record<string, unknown>> | undefined;
	/**
	 * Declares that this command's stdout IS the artifact (contract §19.6).
	 * In machine mode stdout carries the command's own document byte-exactly
	 * and the envelope moves to stderr with the diagnostics it carries.
	 * Outside machine mode the declaration changes nothing at all.
	 */
	readonly ownsStdout: boolean;
	readonly flags: FlagMap;
	readonly args: readonly AnyArg[];
	readonly flagSets: readonly AnyFlagSet[];
	readonly dependencies: readonly Dependency[];
	readonly allDecls: readonly AnyDecl[];
	readonly allFlags: readonly AnyFlag[];
	readonly handler: (
		args: never,
		ctx: Context,
	) => HandlerReturn | Promise<HandlerReturn>;
	readonly tags: readonly string[];
	readonly hidden: boolean;
	readonly interactive: boolean;
	readonly configFields: readonly string[];
	readonly grants: readonly Grant[];
	readonly forwarding: Forwarding | undefined;
}

/**
 * Configuration passed to defineReadOnlyCommand(). Identical to
 * MutatingCommandSpec except for the context type the handler's `ctx`
 * parameter is narrowed to (§2.4).
 */
export interface ReadOnlyCommandSpec<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
> {
	readonly help: string;
	readonly flags?: F;
	readonly args?: A;
	readonly flagSets?: FS;
	readonly dependencies?: readonly Dependency[];
	readonly handler: Handler<F, A, FS, ReadOnlyContext>;
	/**
	 * Declaring this on a read_only command is a registration-time hard error:
	 * a command that changes nothing has nothing to confirm. The member exists
	 * on this spec so that error is reachable rather than silently dropped.
	 */
	readonly consequential?: boolean;
	/**
	 * Declaring this false on a read_only command is a registration-time hard
	 * error: a command that changes nothing has no effects a preview could
	 * misrepresent. The member exists on this spec so that error is reachable
	 * rather than silently dropped.
	 */
	readonly dryRunSupported?: boolean;
	readonly dryRunUnsupportedReason?: string;
	/**
	 * The command's machine payload contract (contract §19.5): the inline JSON
	 * Schema literal a payload supplied through ctx.payload is registered
	 * against. A command that declares none cannot produce a payload.
	 */
	readonly payloadSchema?: Readonly<Record<string, unknown>>;
	/**
	 * Declares that this command's stdout IS the artifact (contract §19.6):
	 * in machine mode stdout carries the command's own document byte-exactly
	 * and the envelope moves to stderr. Outside machine mode it changes
	 * nothing.
	 */
	readonly ownsStdout?: boolean;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
	readonly interactive?: boolean;
	readonly configFields?: readonly string[];
	readonly grants?: readonly Grant[];
	readonly forwarding?: Forwarding;
}

/** Configuration passed to defineMutatingCommand(). */
export interface MutatingCommandSpec<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
> {
	readonly help: string;
	readonly flags?: F;
	readonly args?: A;
	readonly flagSets?: FS;
	readonly dependencies?: readonly Dependency[];
	readonly handler: Handler<F, A, FS, MutatingContext>;
	/**
	 * Declares that this command's effects are worth interrupting someone for.
	 * It is the ONLY thing that makes the framework prompt (§8.1): a plain
	 * mutating command never does.
	 */
	readonly consequential?: boolean;
	/**
	 * Declares that --dry-run is refused for this command, with a mandatory
	 * `dryRunUnsupportedReason`. Declare it when a preview would LIE: when the
	 * command's effects escape the effects handle, or when its later steps read
	 * state its earlier (recorded, therefore un-performed) steps would have
	 * written. Absence means the regime's baseline, where effects are recorded
	 * rather than executed.
	 */
	readonly dryRunSupported?: boolean;
	/** Mandatory when dryRunSupported is false; shown in help and the refusal. */
	readonly dryRunUnsupportedReason?: string;
	/**
	 * The command's machine payload contract (contract §19.5): the inline JSON
	 * Schema literal a payload supplied through ctx.payload is registered
	 * against. A command that declares none cannot produce a payload.
	 */
	readonly payloadSchema?: Readonly<Record<string, unknown>>;
	/**
	 * Declares that this command's stdout IS the artifact (contract §19.6):
	 * in machine mode stdout carries the command's own document byte-exactly
	 * and the envelope moves to stderr. Outside machine mode it changes
	 * nothing.
	 */
	readonly ownsStdout?: boolean;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
	readonly interactive?: boolean;
	readonly configFields?: readonly string[];
	readonly grants?: readonly Grant[];
	readonly forwarding?: Forwarding;
}

const GRANT_NAME_RE = /^[a-z][a-z0-9-]*$/;

/** Validates a command's grant declarations at registration time. */
export function validateGrants(
	cmdName: string,
	grants: readonly Grant[] | undefined,
): readonly Grant[] {
	const resolved: Grant[] = [];
	const seen = new Set<string>();
	for (const g of grants ?? []) {
		if (typeof g !== "object" || g === null) {
			throw new RegistrationError(
				`command "${cmdName}": grants must be grant objects, got ${typeof g}`,
			);
		}
		if (typeof g.name !== "string" || !GRANT_NAME_RE.test(g.name)) {
			throw new RegistrationError(errGrantNameInvalid(cmdName, String(g.name)));
		}
		if (seen.has(g.name)) {
			throw new RegistrationError(errGrantDuplicate(cmdName, g.name));
		}
		if (typeof g.reason !== "string" || g.reason.trim() === "") {
			throw new RegistrationError(errGrantReasonEmpty(cmdName, g.name));
		}
		if (!isGrantableKind(g.kind)) {
			throw new RegistrationError(
				errGrantKindInvalid(cmdName, g.name, String(g.kind)),
			);
		}
		seen.add(g.name);
		resolved.push(g);
	}
	return resolved;
}

/**
 * The three registration-time guards on the dry-run declaration, shared by the
 * ordinary and passthrough builders so both surfaces reject the same shapes
 * with the same messages.
 */
export function validateDryRunDeclaration(
	cmdName: string,
	effect: Effect,
	dryRunSupported: boolean | undefined,
	dryRunUnsupportedReason: string | undefined,
): void {
	const hasReason =
		typeof dryRunUnsupportedReason === "string" &&
		dryRunUnsupportedReason.trim() !== "";
	if (dryRunSupported === false) {
		if (effect === "read_only") {
			throw new RegistrationError(errCommandReadOnlyDryRunUnsupported(cmdName));
		}
		if (!hasReason) {
			throw new RegistrationError(errCommandDryRunReasonMissing(cmdName));
		}
	} else if (dryRunUnsupportedReason !== undefined) {
		throw new RegistrationError(
			errCommandDryRunReasonWithoutDeclaration(cmdName),
		);
	}
}

/**
 * Validates a declared payload schema at registration time (contract §19.5).
 *
 * The literal is validated as written over the closed subset: an unknown
 * keyword anywhere is a hard error, which is what keeps the subset closed by
 * construction. Shared by the ordinary and passthrough builders so both
 * surfaces reject the same shapes with the same messages.
 */
export function validatePayloadSchemaDeclaration(
	cmdName: string,
	payloadSchema: Readonly<Record<string, unknown>> | undefined,
): void {
	if (payloadSchema === undefined) {
		return;
	}
	const found = validatePayloadSchemaLiteral(payloadSchema);
	if (found !== null) {
		throw new RegistrationError(
			errPayloadSchemaInvalid(cmdName, found.path, found.detail),
		);
	}
}

/** Validates a declared-forwarding declaration at registration time. */
export function validateForwarding(
	cmdName: string,
	forwarding: Forwarding | undefined,
): Forwarding | undefined {
	if (forwarding === undefined) {
		return undefined;
	}
	if (
		typeof forwarding.reason !== "string" ||
		forwarding.reason.trim() === ""
	) {
		throw new RegistrationError(errForwardingReasonEmpty(cmdName));
	}
	return forwarding;
}

const TAG_RE = /^[a-z][a-z0-9-]*$/;

/** Validates tag names and removes duplicates, preserving order. */
export function validateAndDedupTags(
	tags: readonly string[],
): readonly string[] {
	const result: string[] = [];
	for (const tag of tags) {
		if (!TAG_RE.test(tag)) {
			throw new RegistrationError(errInvalidTagName(tag));
		}
		if (!result.includes(tag)) {
			result.push(tag);
		}
	}
	return result;
}

function validateFlagMapKeys(cmdName: string, flags: FlagMap): void {
	for (const [key, f] of Object.entries(flags)) {
		const expected = f.name.replaceAll("-", "_");
		if (key !== expected) {
			throw new RegistrationError(
				`command "${cmdName}": flags key '${key}' must be the underscore form of flag '${f.name}' ('${expected}')`,
			);
		}
	}
}

/**
 * The shared body of the twin factories. `effect` is not a spec key: it is
 * spliced in by whichever factory was called, which is what makes
 * classification mandatory and inference impossible.
 */
function buildCommandDef<
	N extends string,
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[],
	C,
>(
	name: N,
	spec: ReadOnlyCommandSpec<F, A, FS> | MutatingCommandSpec<F, A, FS>,
	effect: Effect,
): CommandDef<N, F, A, FS, C> {
	if (typeof spec.help !== "string" || spec.help.trim() === "") {
		throw new RegistrationError(errCommandMissingHelp(name));
	}
	// A read_only command cannot be consequential: it changes nothing, so
	// there is nothing to interrupt anyone for (contract §8.1).
	if (spec.consequential === true && effect === "read_only") {
		throw new RegistrationError(errCommandReadOnlyConsequential(name));
	}
	validateDryRunDeclaration(
		name,
		effect,
		spec.dryRunSupported,
		spec.dryRunUnsupportedReason,
	);
	validatePayloadSchemaDeclaration(name, spec.payloadSchema);
	// The empty fallbacks are safe: the type params only default when the
	// corresponding spec properties are absent.
	const flags = spec.flags ?? ({} as F);
	const args = spec.args ?? ([] as unknown as A);
	const flagSets = spec.flagSets ?? ([] as unknown as FS);
	const dependencies = spec.dependencies ?? [];

	validateFlagMapKeys(name, flags);
	for (const fs of flagSets) {
		validateFlagMapKeys(name, fs.flags);
	}

	const allDecls: AnyDecl[] = [
		...Object.values(flags),
		...flagSets.flatMap((fs) => Object.values(fs.flags)),
	];
	const allFlags: AnyFlag[] = allDecls.filter(
		(d): d is AnyFlag => d.kind === "flag",
	);
	const seenFlagNames = new Set<string>();
	for (const d of allDecls) {
		if (seenFlagNames.has(d.name)) {
			throw new RegistrationError(errCommandDuplicateFlag(name, d.name));
		}
		seenFlagNames.add(d.name);
	}
	// Every token declared at ROOT, which under member spelling includes each
	// member's own name: electing a member IS the election, so a member token
	// opens no scope of its own and sits beside the command-level flags rather
	// than under them (§18.19 item 223). Two of them naming one token is the
	// plain duplicate-flag error -- the co-electable template one level down
	// could only state it with two empty scope paths, which says nothing.
	const seenRootTokens = new Set<string>();
	for (const d of allDecls) {
		for (const s of surfaceNames(d)) {
			if (seenRootTokens.has(s.name)) {
				throw new RegistrationError(errCommandDuplicateFlag(name, s.name));
			}
			seenRootTokens.add(s.name);
		}
	}
	// The whole declaration TREE: root collisions, simultaneously-electable
	// name and short reuse, and the scoped keys of every nested scope
	// (contract §24.7).
	validateDeclTree(name, allDecls, seenFlagNames);
	// A constraint naming a scoped flag is a registration error: the scope
	// already IS the constraint (§24.8).
	const scopedFlagPaths = scopedFlagPathMap(allDecls);

	const seenArgNames = new Set<string>();
	for (const a of args) {
		if (seenArgNames.has(a.name)) {
			throw new RegistrationError(errCommandDuplicateArg(name, a.name));
		}
		seenArgNames.add(a.name);
	}
	const variadicCount = args.filter((a) => a.opts.variadic === true).length;
	if (variadicCount > 1) {
		throw new RegistrationError(errCommandAtMostOneVariadic(name));
	}
	args.forEach((a, i) => {
		if (a.opts.variadic === true && i !== args.length - 1) {
			throw new RegistrationError(errCommandVariadicMustBeLast(name, a.name));
		}
	});

	// Dependency reference validation, in the Python check order (unknown
	// references are reported before same-flag violations). A SCOPED operand
	// is refused before either: the scope already is the constraint, and it
	// would otherwise report as an unknown flag, which is the wrong diagnosis
	// (§24.8).
	const refuseScopedOperand = (family: string, flagName: string): void => {
		const path = scopedFlagPaths.get(flagName);
		if (path !== undefined) {
			throw new RegistrationError(
				errConstraintReferencesScopedFlag(name, family, flagName, path),
			);
		}
	};
	for (const dep of dependencies) {
		switch (dep.kind) {
			case "co-required": {
				if (dep.flags.length < 2) {
					throw new RegistrationError(
						errCommandCoRequiredMinFlags(name, dep.flags.length),
					);
				}
				const seenDep = new Set<string>();
				for (const flagName of dep.flags) {
					refuseScopedOperand("CoRequired", flagName);
					if (!seenFlagNames.has(flagName)) {
						throw new RegistrationError(
							errCommandCoRequiredUnknownFlag(name, flagName),
						);
					}
					if (seenDep.has(flagName)) {
						throw new RegistrationError(
							errCommandCoRequiredDuplicate(name, flagName),
						);
					}
					seenDep.add(flagName);
				}
				break;
			}
			case "requires": {
				refuseScopedOperand("Requires", dep.flag);
				refuseScopedOperand("Requires", dep.dependsOn);
				if (!seenFlagNames.has(dep.flag)) {
					throw new RegistrationError(
						errCommandRequiresUnknownFlag(name, dep.flag),
					);
				}
				if (!seenFlagNames.has(dep.dependsOn)) {
					throw new RegistrationError(
						errCommandRequiresUnknownFlag(name, dep.dependsOn),
					);
				}
				if (dep.flag === dep.dependsOn) {
					throw new RegistrationError(
						errCommandRequiresSameFlag(name, dep.flag),
					);
				}
				break;
			}
			case "implies": {
				refuseScopedOperand("Implies", dep.flag);
				refuseScopedOperand("Implies", dep.implies);
				if (!seenFlagNames.has(dep.flag)) {
					throw new RegistrationError(
						errCommandImpliesUnknownFlag(name, dep.flag),
					);
				}
				if (!seenFlagNames.has(dep.implies)) {
					throw new RegistrationError(
						errCommandImpliesUnknownFlag(name, dep.implies),
					);
				}
				if (dep.flag === dep.implies) {
					throw new RegistrationError(
						errCommandImpliesSameFlag(name, dep.flag),
					);
				}
				const trigger = allFlags.find((f) => f.name === dep.flag);
				const target = allFlags.find((f) => f.name === dep.implies);
				if (trigger?.schema !== "bool") {
					throw new RegistrationError(
						errCommandImpliesTriggerNotBool(name, dep.flag),
					);
				}
				if (target?.schema !== "bool") {
					throw new RegistrationError(
						errCommandImpliesTargetNotBool(name, dep.implies),
					);
				}
				if (typeof dep.value !== "boolean") {
					throw new RegistrationError(
						errCommandImpliesValueMustBeBool(name, pyTypeName(dep.value)),
					);
				}
				break;
			}
		}
	}

	const tags = validateAndDedupTags(spec.tags ?? []);
	return {
		kind: "command",
		name,
		help: spec.help,
		effect,
		consequential: spec.consequential ?? false,
		dryRunSupported: spec.dryRunSupported ?? true,
		dryRunUnsupportedReason: spec.dryRunUnsupportedReason,
		payloadSchema: spec.payloadSchema,
		ownsStdout: spec.ownsStdout ?? false,
		flags,
		args,
		flagSets,
		dependencies,
		allDecls,
		allFlags,
		handler: spec.handler as Handler<F, A, FS, C>,
		tags,
		hidden: spec.hidden ?? false,
		interactive: spec.interactive ?? false,
		configFields: spec.configFields ?? [],
		grants: validateGrants(name, spec.grants),
		forwarding: validateForwarding(name, spec.forwarding),
	};
}

/**
 * Creates a `read_only` command descriptor with typed flags (ordinary or
 * scoped selectors), args, flag sets and dependencies. Validates all
 * constraints at construction time.
 *
 * A read_only command never prompts (§8) and cannot be declared consequential;
 * calling any mutating member of the effects handle is a hard error at call
 * time. Its handler's `ctx` is narrowed to ReadOnlyContext, so
 * `ctx.effects.write(...)` does not compile.
 */
export function defineReadOnlyCommand<
	const N extends string,
	const F extends FlagMap = Record<never, never>,
	const A extends readonly AnyArg[] = readonly [],
	const FS extends readonly AnyFlagSet[] = readonly [],
>(
	name: N,
	spec: ReadOnlyCommandSpec<F, A, FS>,
): CommandDef<N, F, A, FS, ReadOnlyContext> {
	return buildCommandDef<N, F, A, FS, ReadOnlyContext>(name, spec, "read_only");
}

/**
 * Creates a `mutating` command descriptor with typed flags (ordinary or
 * scoped selectors), args, flag sets and dependencies. Validates all
 * constraints at construction time.
 *
 * A mutating command participates in dry mode and may call every member of the
 * effects handle. It does NOT prompt unless it also declares
 * `consequential: true` (§8.1).
 */
export function defineMutatingCommand<
	const N extends string,
	const F extends FlagMap = Record<never, never>,
	const A extends readonly AnyArg[] = readonly [],
	const FS extends readonly AnyFlagSet[] = readonly [],
>(
	name: N,
	spec: MutatingCommandSpec<F, A, FS>,
): CommandDef<N, F, A, FS, MutatingContext> {
	return buildCommandDef<N, F, A, FS, MutatingContext>(name, spec, "mutating");
}

// --- Passthrough and deprecated command carriers ---

/** Arguments passed to a passthrough command handler: the command name, raw args, and global flag values. */
export interface PassthroughArgs {
	readonly name: string;
	readonly args: readonly string[];
	readonly globals: Readonly<Record<string, unknown>>;
}

/** Handler function for passthrough commands (receives raw args, no parsing). */
export type PassthroughHandler<C = MutatingContext> = (
	args: PassthroughArgs,
	ctx: C,
) => HandlerReturn | Promise<HandlerReturn>;

/** A passthrough command descriptor produced by the passthrough twins. */
export interface PassthroughDef<N extends string, C = MutatingContext> {
	readonly kind: "passthrough";
	readonly name: N;
	readonly help: string;
	/** Mandatory classification, exactly as on an ordinary command. */
	readonly effect: Effect;
	/** Declared exactly as on an ordinary command (contract §8.1). */
	readonly consequential: boolean;
	/** Declared exactly as on an ordinary command. */
	readonly dryRunSupported: boolean;
	readonly dryRunUnsupportedReason: string | undefined;
	/** Declared exactly as on an ordinary command (contract §19.5). */
	readonly payloadSchema: Readonly<Record<string, unknown>> | undefined;
	/**
	 * Declares that this command's stdout IS the artifact (contract §19.6).
	 * In machine mode stdout carries the command's own document byte-exactly
	 * and the envelope moves to stderr with the diagnostics it carries.
	 * Outside machine mode the declaration changes nothing at all.
	 */
	readonly ownsStdout: boolean;
	readonly handler: PassthroughHandler<C>;
	readonly tags: readonly string[];
	readonly hidden: boolean;
	readonly grants: readonly Grant[];
}

/** The options object both passthrough twins take. */
interface PassthroughSpec<C> {
	readonly help: string;
	readonly handler: PassthroughHandler<C>;
	readonly consequential?: boolean;
	readonly dryRunSupported?: boolean;
	readonly dryRunUnsupportedReason?: string;
	readonly payloadSchema?: Readonly<Record<string, unknown>>;
	/**
	 * Declares that this command's stdout IS the artifact (contract §19.6):
	 * in machine mode stdout carries the command's own document byte-exactly
	 * and the envelope moves to stderr. Outside machine mode it changes
	 * nothing.
	 */
	readonly ownsStdout?: boolean;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
	readonly grants?: readonly Grant[];
}

function buildPassthroughDef<N extends string, C>(
	name: N,
	spec: PassthroughSpec<C>,
	effect: Effect,
): PassthroughDef<N, C> {
	if (typeof spec.help !== "string" || spec.help.trim() === "") {
		throw new RegistrationError(errCommandMissingHelp(name));
	}
	if (spec.consequential === true && effect === "read_only") {
		throw new RegistrationError(errCommandReadOnlyConsequential(name));
	}
	validateDryRunDeclaration(
		name,
		effect,
		spec.dryRunSupported,
		spec.dryRunUnsupportedReason,
	);
	validatePayloadSchemaDeclaration(name, spec.payloadSchema);
	const tags = validateAndDedupTags(spec.tags ?? []);
	return {
		kind: "passthrough",
		name,
		help: spec.help,
		effect,
		consequential: spec.consequential ?? false,
		dryRunSupported: spec.dryRunSupported ?? true,
		dryRunUnsupportedReason: spec.dryRunUnsupportedReason,
		payloadSchema: spec.payloadSchema,
		ownsStdout: spec.ownsStdout ?? false,
		handler: spec.handler,
		tags,
		hidden: spec.hidden ?? false,
		grants: validateGrants(name, spec.grants),
	};
}

/**
 * Creates a `read_only` passthrough command that bypasses all flag/arg
 * parsing. The handler receives the raw argument list and global flag values,
 * and never prompts. It cannot be declared consequential.
 */
export function readOnlyPassthrough<const N extends string>(
	name: N,
	spec: PassthroughSpec<ReadOnlyContext>,
): PassthroughDef<N, ReadOnlyContext> {
	return buildPassthroughDef(name, spec, "read_only");
}

/**
 * Creates a `mutating` passthrough command that bypasses all flag/arg parsing.
 *
 * A mutating passthrough is NOT exempt from the confirm protocol when it
 * declares `consequential: true`: that its args are opaque to the framework is
 * a reason to confirm, not a reason to skip -- the framework knows less about
 * what is about to happen, not more.
 */
export function mutatingPassthrough<const N extends string>(
	name: N,
	spec: PassthroughSpec<MutatingContext>,
): PassthroughDef<N, MutatingContext> {
	return buildPassthroughDef(name, spec, "mutating");
}

/** A deprecated command descriptor produced by the deprecated() factory. */
export interface DeprecatedDef<N extends string> {
	readonly kind: "deprecated";
	readonly name: N;
	readonly message: string;
}

/** Creates a deprecated command entry that prints a message to stderr and exits 1 when invoked. */
export function deprecated<const N extends string>(
	name: N,
	message: string,
): DeprecatedDef<N> {
	if (typeof name !== "string" || name.trim() === "") {
		throw new RegistrationError(errDeprecatedNameEmpty());
	}
	if (typeof message !== "string" || message.trim() === "") {
		throw new RegistrationError(errDeprecatedMessageEmpty(name));
	}
	return { kind: "deprecated", name, message };
}
