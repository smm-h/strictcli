/**
 * Declaration factories: flag/arg descriptors, dependency descriptors, and
 * command carriers. `const` type parameters preserve literal names and exact
 * option object types without `as const` at call sites.
 *
 * Validation runs at construction time, mirroring the siblings (Go
 * validateFlagConfig / Python Flag.__post_init__ run when the flag value is
 * built, and buildAndValidateCommand runs at registration). Messages are
 * byte-identical to the siblings; where Go and Python disagree, the Python
 * implementation is the captured ground truth (see tests/registration.test.ts).
 * App-context checks (global-flag collisions, env prefixes) live in app.ts.
 */

import {
	errArgBoolDefaultTypeMismatch,
	errArgChoicesEmpty,
	errArgChoicesIncompatibleBool,
	errArgChoiceTypeMismatch,
	errArgFloatDefaultTypeMismatch,
	errArgHelpEmpty,
	errArgIntDefaultTypeMismatch,
	errArgStrDefaultTypeMismatch,
	errCommandAtMostOneVariadic,
	errCommandCoRequiredDuplicate,
	errCommandCoRequiredMinFlags,
	errCommandCoRequiredUnknownFlag,
	errCommandDuplicateArg,
	errCommandDuplicateFlag,
	errCommandFlagInMultipleMutex,
	errCommandImpliesSameFlag,
	errCommandImpliesTargetNotBool,
	errCommandImpliesTriggerNotBool,
	errCommandImpliesUnknownFlag,
	errCommandMissingHelp,
	errCommandMutexMinFlags,
	errCommandRequiresSameFlag,
	errCommandRequiresUnknownFlag,
	errCommandVariadicMustBeLast,
	errDeprecatedMessageEmpty,
	errDeprecatedNameEmpty,
	errFlagChoicesEmpty,
	errFlagChoicesIncompatibleBool,
	errFlagChoiceTypeMismatch,
	errFlagDefaultElementTypeMismatch,
	errFlagEnvSeparatorBackslash,
	errFlagEnvSeparatorRequiresEnv,
	errFlagEnvSeparatorRequiresRepeatable,
	errFlagEnvSeparatorSingleChar,
	errFlagExplicitEmptyDefaultRedundantDict,
	errFlagExplicitEmptyDefaultRedundantList,
	errFlagFloatDefaultTypeMismatch,
	errFlagForceReserved,
	errFlagHelpEmpty,
	errFlagIntDefaultTypeMismatch,
	errFlagNoPrefixReserved,
	errFlagRepeatableEnvRequiresSeparator,
	errFlagRepeatableIncompatibleBool,
	errFlagUniqueRequiresRepeatable,
	errInvalidTagName,
	errRequiredArgCannotHaveDefault,
	RegistrationError,
} from "./errors.js";
import type { HandlerArgs } from "./infer.js";
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
export type ElementOf<Out> = Out extends readonly (infer E)[] ? E : Out;

export type ConflictMode = "cli-wins" | "error";

/**
 * Per-carrier option surface. Inapplicable options are `never`-typed so they
 * cannot be provided at all: negatable is bool-only; choices exclude bool and
 * dict; envSeparator/repeatable/unique are list-only (list carriers are the
 * only repeatable flags in TS -- scalar `repeatable: true` does not exist).
 */
export type FlagOpts<Out, S extends Schema> = {
	readonly help: string;
	readonly short?: string;
	readonly env?: string;
	readonly prefixed?: boolean;
	readonly conflictMode?: ConflictMode;
	/** Throw an Error to reject; list validators receive each element. */
	readonly validate?: (value: ElementOf<Out>) => void;
	/**
	 * `null` declares an explicitly-optional scalar flag (the Go `Default(nil)`
	 * / conformance `"default": null` shape). Absent default = required.
	 */
	readonly default?: Out | null;
	readonly negatable?: S extends "bool" ? boolean : never;
	readonly choices?: S extends "bool" | DictSchema
		? never
		: readonly [ElementOf<Out>, ...ElementOf<Out>[]];
	readonly envSeparator?: S extends ListSchema ? string : never;
	readonly repeatable?: S extends ListSchema ? true : never;
	readonly unique?: S extends ListSchema ? boolean : never;
};

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
	readonly opts: { readonly help: string; readonly default?: unknown };
	readonly _out?: unknown;
}

/**
 * Runtime view of a flag's options. The generic option surface narrows
 * inapplicable options to `never` per carrier; validation reads them
 * uniformly through this widened shape.
 */
export interface FlagOptsView {
	readonly help: string;
	readonly short?: string;
	readonly env?: string;
	readonly prefixed?: boolean;
	readonly conflictMode?: string;
	readonly validate?: (value: never) => void;
	readonly default?: unknown;
	readonly negatable?: boolean;
	readonly choices?: readonly unknown[];
	readonly envSeparator?: string;
	readonly repeatable?: boolean;
	readonly unique?: boolean;
}

/** Widened options of a flag descriptor, for runtime validation and parsing. */
export function flagOpts(f: AnyFlag): FlagOptsView {
	return f.opts as FlagOptsView;
}

function schemaKind(schema: Schema): "scalar" | "list" | "dict" {
	if (schema.startsWith("list[")) {
		return "list";
	}
	if (schema.startsWith("dict[")) {
		return "dict";
	}
	return "scalar";
}

/** Element schema of a carrier: the item/value schema for compounds, the schema itself for scalars. */
function elemSchemaOf(carrier: Carrier<unknown, Schema>): ScalarSchema {
	return (carrier.elem?.schema ?? carrier.schema) as ScalarSchema;
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
	if (name === "force") {
		throw new RegistrationError(errFlagForceReserved());
	}
	if (name.startsWith("no-")) {
		throw new RegistrationError(errFlagNoPrefixReserved(name));
	}
	const kind = schemaKind(carrier.schema);
	const elem = elemSchemaOf(carrier);
	if (kind === "dict") {
		if (o.repeatable !== undefined) {
			throw new RegistrationError(
				`Flag "${name}": dict type cannot be combined with repeatable=True`,
			);
		}
		if (o.unique !== undefined) {
			throw new RegistrationError(
				`Flag "${name}": dict type cannot be combined with unique`,
			);
		}
		if (o.choices !== undefined) {
			throw new RegistrationError(
				`Flag "${name}": dict type cannot be combined with choices`,
			);
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
			`Flag "${name}": conflict_mode must be "cli-wins" or "error", got ${pyRepr(o.conflictMode)}`,
		);
	}
	if (kind === "dict") {
		if (o.envSeparator !== undefined) {
			throw new RegistrationError(
				`Flag "${name}": dict type cannot use env_separator (env vars are parsed as JSON)`,
			);
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
		for (const c of o.choices) {
			if (!matchesScalar(elem, c)) {
				throw new RegistrationError(
					errFlagChoiceTypeMismatch(name, pyRepr(c), elem),
				);
			}
		}
	}
	const dflt = o.default;
	if (kind === "dict" && dflt !== undefined && dflt !== null) {
		if (!(dflt instanceof Map)) {
			throw new RegistrationError(
				`Flag "${name}": dict flag default must be a Map`,
			);
		}
		if (dflt.size === 0) {
			throw new RegistrationError(
				errFlagExplicitEmptyDefaultRedundantDict(name),
			);
		}
		for (const [k, v] of dflt as Map<unknown, unknown>) {
			if (typeof k !== "string") {
				throw new RegistrationError(
					`Flag "${name}": dict default key ${pyRepr(k)} must be a string`,
				);
			}
			if (!matchesScalar(elem, v)) {
				throw new RegistrationError(
					`Flag "${name}": dict default value for key ${pyRepr(k)} is not of type ${elem}`,
				);
			}
		}
	} else if (kind === "list" && dflt !== undefined && dflt !== null) {
		if (!Array.isArray(dflt)) {
			throw new RegistrationError(
				`Flag "${name}": list flag default must be an array`,
			);
		}
		if (dflt.length === 0) {
			throw new RegistrationError(
				errFlagExplicitEmptyDefaultRedundantList(name),
			);
		}
		for (const [i, el] of (dflt as unknown[]).entries()) {
			if (!matchesScalar(elem, el)) {
				throw new RegistrationError(
					errFlagDefaultElementTypeMismatch(name, i, elem),
				);
			}
		}
	} else if (kind === "scalar" && dflt !== undefined && dflt !== null) {
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
	if (
		kind === "scalar" &&
		o.choices !== undefined &&
		dflt !== undefined &&
		dflt !== null &&
		!(o.choices as readonly unknown[]).includes(dflt)
	) {
		throw new RegistrationError(
			`Flag "${name}": default ${pyRepr(dflt)} is not in choices [${(
				o.choices as readonly unknown[]
			)
				.map(pyRepr)
				.join(", ")}]`,
		);
	}
}

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

type ArgChoices<Out, S extends ScalarSchema> = S extends "bool"
	? never
	: readonly [Out, ...Out[]];

/**
 * Args take scalar carriers only; a variadic arg collects Out[] (the list-arg
 * shape from the siblings is expressed as scalar carrier + `variadic: true`).
 * `default` is only meaningful with `required: false` (required is the arg
 * default, matching the siblings).
 */
export type ArgOpts<Out, S extends ScalarSchema> =
	| {
			readonly help: string;
			readonly variadic: true;
			readonly required?: boolean;
			readonly choices?: ArgChoices<Out, S>;
	  }
	| {
			readonly help: string;
			readonly variadic?: false;
			readonly required?: true;
			readonly choices?: ArgChoices<Out, S>;
	  }
	| {
			readonly help: string;
			readonly variadic?: false;
			readonly required: false;
			readonly default?: Out;
			readonly choices?: ArgChoices<Out, S>;
	  };

export interface ArgDef<
	N extends string,
	Out,
	S extends ScalarSchema,
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
	readonly schema: ScalarSchema;
	readonly carrier: Carrier<unknown, ScalarSchema>;
	readonly opts: {
		readonly help: string;
		readonly required?: boolean;
		readonly variadic?: boolean;
		readonly default?: unknown;
	};
	readonly _out?: unknown;
}

/** Runtime view of an arg's options (see FlagOptsView). */
export interface ArgOptsView {
	readonly help: string;
	readonly required?: boolean;
	readonly variadic?: boolean;
	readonly default?: unknown;
	readonly choices?: readonly unknown[];
}

export function arg<
	const N extends string,
	Out,
	S extends ScalarSchema,
	const O extends ArgOpts<Out, S>,
>(name: N, carrier: Carrier<Out, S>, opts: O): ArgDef<N, Out, S, O> {
	const o = opts as ArgOptsView;
	if (typeof o.help !== "string" || o.help.trim() === "") {
		throw new RegistrationError(errArgHelpEmpty());
	}
	// required defaults to true; the type system steers toward valid shapes but
	// cannot excess-property-check generic constraints, so enforce here too.
	if (o.required !== false && "default" in o) {
		throw new RegistrationError(errRequiredArgCannotHaveDefault());
	}
	const kind = schemaKind(carrier.schema);
	if (kind === "dict") {
		throw new RegistrationError(
			`Arg "${name}": dict type is not supported on args`,
		);
	}
	if (kind === "list") {
		if (o.variadic !== true) {
			throw new RegistrationError(
				`Arg "${name}": list type on args requires variadic=True`,
			);
		}
		// TS-only: variadic args are declared with the ELEMENT carrier plus
		// variadic: true; a list carrier here is an inexpressible shape.
		throw new RegistrationError(
			`Arg "${name}": variadic args take a scalar element type, not a list type`,
		);
	}
	if (o.choices !== undefined) {
		if (carrier.schema === "bool") {
			throw new RegistrationError(errArgChoicesIncompatibleBool(name));
		}
		if (!Array.isArray(o.choices) || o.choices.length === 0) {
			throw new RegistrationError(errArgChoicesEmpty(name));
		}
		for (const c of o.choices) {
			if (!matchesScalar(carrier.schema, c)) {
				throw new RegistrationError(
					errArgChoiceTypeMismatch(name, pyRepr(c), carrier.schema),
				);
			}
		}
	}
	const dflt = o.default;
	if (
		dflt !== undefined &&
		dflt !== null &&
		!matchesScalar(carrier.schema, dflt)
	) {
		const got = pyTypeName(dflt);
		switch (carrier.schema) {
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
		dflt !== null &&
		!(o.choices as readonly unknown[]).includes(dflt)
	) {
		throw new RegistrationError(
			`Arg "${name}": default ${pyRepr(dflt)} is not in choices [${(
				o.choices as readonly unknown[]
			)
				.map(pyRepr)
				.join(", ")}]`,
		);
	}
	return { kind: "arg", name, schema: carrier.schema, carrier, opts };
}

// --- Dependency and flag-set descriptors ---

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

export function flagSet<const N extends string, const F extends FlagMap>(
	name: N,
	flags: F,
): FlagSet<N, F> {
	return { kind: "flag-set", name, flags };
}

export interface MutexGroup<F extends FlagMap> {
	readonly kind: "mutex-group";
	readonly flags: F;
}

/** Structural supertype of every MutexGroup instantiation. */
export interface AnyMutexGroup {
	readonly kind: "mutex-group";
	readonly flags: FlagMap;
}

export function mutexGroup<const F extends FlagMap>(flags: F): MutexGroup<F> {
	return { kind: "mutex-group", flags };
}

export interface CoRequired {
	readonly kind: "co-required";
	/** Flag names (dash form), matching the sibling CoRequired shape. */
	readonly flags: readonly string[];
}

export function coRequired(flags: readonly string[]): CoRequired {
	return { kind: "co-required", flags };
}

export interface Requires {
	readonly kind: "requires";
	readonly flag: string;
	readonly dependsOn: string;
}

export function requires(spec: {
	readonly flag: string;
	readonly dependsOn: string;
}): Requires {
	return { kind: "requires", flag: spec.flag, dependsOn: spec.dependsOn };
}

export interface Implies {
	readonly kind: "implies";
	readonly flag: string;
	readonly implies: string;
	readonly value: boolean;
}

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

export type Dependency = CoRequired | Requires | Implies;

// --- Command carriers ---

/**
 * Flags are a keyed map: the map key IS the handler key, so underscore keys
 * come free (no dash-to-underscore type machinery). defineCommand verifies at
 * runtime that each key is the underscore form of its flag's name.
 */
export type FlagMap = Readonly<Record<string, AnyFlag>>;

export type Handler<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
	M extends readonly AnyMutexGroup[] = readonly [],
> = (
	args: HandlerArgs<F, A, FS, M>,
	ctx: Context,
) => HandlerReturn | Promise<HandlerReturn>;

export interface CommandDef<
	N extends string,
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
	M extends readonly AnyMutexGroup[] = readonly [],
> {
	readonly kind: "command";
	readonly name: N;
	readonly help: string;
	readonly flags: F;
	readonly args: A;
	readonly flagSets: FS;
	readonly mutex: M;
	readonly dependencies: readonly Dependency[];
	/** Merged flag list (flags, then flag-set flags, then mutex flags), in declaration order. */
	readonly allFlags: readonly AnyFlag[];
	readonly handler: Handler<F, A, FS, M>;
	// Typed but unwired until later subphases.
	readonly tags: readonly string[];
	readonly hidden: boolean;
	readonly interactive: boolean;
	readonly configFields: readonly string[];
}

/** Structural supertype of every CommandDef instantiation. */
export interface AnyCommand {
	readonly kind: "command";
	readonly name: string;
	readonly help: string;
	readonly flags: FlagMap;
	readonly args: readonly AnyArg[];
	readonly flagSets: readonly AnyFlagSet[];
	readonly mutex: readonly AnyMutexGroup[];
	readonly dependencies: readonly Dependency[];
	readonly allFlags: readonly AnyFlag[];
	readonly handler: (
		args: never,
		ctx: Context,
	) => HandlerReturn | Promise<HandlerReturn>;
	readonly tags: readonly string[];
	readonly hidden: boolean;
	readonly interactive: boolean;
	readonly configFields: readonly string[];
}

export interface CommandSpec<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly AnyFlagSet[] = readonly [],
	M extends readonly AnyMutexGroup[] = readonly [],
> {
	readonly help: string;
	readonly flags?: F;
	readonly args?: A;
	readonly flagSets?: FS;
	readonly mutex?: M;
	readonly dependencies?: readonly Dependency[];
	readonly handler: Handler<F, A, FS, M>;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
	readonly interactive?: boolean;
	readonly configFields?: readonly string[];
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

export function defineCommand<
	const N extends string,
	const F extends FlagMap = Record<never, never>,
	const A extends readonly AnyArg[] = readonly [],
	const FS extends readonly AnyFlagSet[] = readonly [],
	const M extends readonly AnyMutexGroup[] = readonly [],
>(name: N, spec: CommandSpec<F, A, FS, M>): CommandDef<N, F, A, FS, M> {
	if (typeof spec.help !== "string" || spec.help.trim() === "") {
		throw new RegistrationError(errCommandMissingHelp(name));
	}
	// The empty fallbacks are safe: the type params only default when the
	// corresponding spec properties are absent.
	const flags = spec.flags ?? ({} as F);
	const args = spec.args ?? ([] as unknown as A);
	const flagSets = spec.flagSets ?? ([] as unknown as FS);
	const mutex = spec.mutex ?? ([] as unknown as M);
	const dependencies = spec.dependencies ?? [];

	validateFlagMapKeys(name, flags);
	for (const fs of flagSets) {
		validateFlagMapKeys(name, fs.flags);
	}
	const mutexFlagNames = new Set<string>();
	for (const mg of mutex) {
		validateFlagMapKeys(name, mg.flags);
		const mgFlags = Object.values(mg.flags);
		if (mgFlags.length < 2) {
			throw new RegistrationError(
				errCommandMutexMinFlags(name, mgFlags.length),
			);
		}
		for (const f of mgFlags) {
			if (mutexFlagNames.has(f.name)) {
				throw new RegistrationError(
					errCommandFlagInMultipleMutex(name, f.name),
				);
			}
			mutexFlagNames.add(f.name);
		}
	}

	const allFlags: AnyFlag[] = [
		...Object.values(flags),
		...flagSets.flatMap((fs) => Object.values(fs.flags)),
		...mutex.flatMap((mg) => Object.values(mg.flags)),
	];
	const seenFlagNames = new Set<string>();
	for (const f of allFlags) {
		if (seenFlagNames.has(f.name)) {
			throw new RegistrationError(errCommandDuplicateFlag(name, f.name));
		}
		seenFlagNames.add(f.name);
	}

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
	// references are reported before same-flag violations).
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
						`command "${name}": Implies value must be a bool, got '${pyTypeName(dep.value)}'`,
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
		flags,
		args,
		flagSets,
		mutex,
		dependencies,
		allFlags,
		handler: spec.handler,
		tags,
		hidden: spec.hidden ?? false,
		interactive: spec.interactive ?? false,
		configFields: spec.configFields ?? [],
	};
}

// --- Passthrough and deprecated command carriers ---

export interface PassthroughArgs {
	readonly name: string;
	readonly args: readonly string[];
	readonly globals: Readonly<Record<string, unknown>>;
}

export type PassthroughHandler = (
	args: PassthroughArgs,
	ctx: Context,
) => HandlerReturn | Promise<HandlerReturn>;

export interface PassthroughDef<N extends string> {
	readonly kind: "passthrough";
	readonly name: N;
	readonly help: string;
	readonly handler: PassthroughHandler;
	readonly tags: readonly string[];
	readonly hidden: boolean;
}

export function passthrough<const N extends string>(
	name: N,
	spec: {
		readonly help: string;
		readonly handler: PassthroughHandler;
		readonly tags?: readonly string[];
		readonly hidden?: boolean;
	},
): PassthroughDef<N> {
	if (typeof spec.help !== "string" || spec.help.trim() === "") {
		throw new RegistrationError(errCommandMissingHelp(name));
	}
	const tags = validateAndDedupTags(spec.tags ?? []);
	return {
		kind: "passthrough",
		name,
		help: spec.help,
		handler: spec.handler,
		tags,
		hidden: spec.hidden ?? false,
	};
}

export interface DeprecatedDef<N extends string> {
	readonly kind: "deprecated";
	readonly name: N;
	readonly message: string;
}

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
