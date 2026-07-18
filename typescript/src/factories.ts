/**
 * Declaration factories: flag/arg descriptors, dependency descriptors, and
 * command carriers. `const` type parameters preserve literal names and exact
 * option object types without `as const` at call sites.
 *
 * Option sets and registration-error messages are verified against the
 * Python Flag/Arg dataclasses and the Go Flag/Arg option functions; only the
 * checks that are purely local to a single declaration run here -- cross-flag
 * validation is the registration layer's job (later subphase).
 */

import type { InferHandlerArgs } from "./infer.js";
import type {
	Carrier,
	Context,
	DictSchema,
	HandlerReturn,
	ListSchema,
	ScalarSchema,
	Schema,
} from "./types.js";

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

export function flag<
	const N extends string,
	Out,
	S extends Schema,
	const O extends FlagOpts<Out, S>,
>(name: N, carrier: Carrier<Out, S>, opts: O): FlagDef<N, Out, S, O> {
	if (typeof opts.help !== "string" || opts.help.trim() === "") {
		throw new Error("Flag.help must be a non-empty string");
	}
	if (name === "force") {
		throw new Error(
			"flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'",
		);
	}
	if (name.startsWith("no-")) {
		throw new Error(
			`flag '${name}': names starting with 'no-' are reserved for the negation system; use a positive name instead`,
		);
	}
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

export function arg<
	const N extends string,
	Out,
	S extends ScalarSchema,
	const O extends ArgOpts<Out, S>,
>(name: N, carrier: Carrier<Out, S>, opts: O): ArgDef<N, Out, S, O> {
	if (typeof opts.help !== "string" || opts.help.trim() === "") {
		throw new Error("Arg.help must be a non-empty string");
	}
	// required defaults to true; the type system steers toward valid shapes but
	// cannot excess-property-check generic constraints, so enforce here too.
	if (opts.required !== false && "default" in opts) {
		throw new Error("required arg cannot have a default");
	}
	return { kind: "arg", name, schema: carrier.schema, carrier, opts };
}

// --- Dependency and flag-set descriptors ---

export interface FlagSet<N extends string, F extends FlagMap> {
	readonly kind: "flag-set";
	readonly name: N;
	readonly flags: F;
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

export type Handler<F extends FlagMap, A extends readonly AnyArg[]> = (
	args: InferHandlerArgs<F, A>,
	ctx: Context,
) => HandlerReturn | Promise<HandlerReturn>;

export interface CommandDef<
	N extends string,
	F extends FlagMap,
	A extends readonly AnyArg[],
> {
	readonly kind: "command";
	readonly name: N;
	readonly help: string;
	readonly flags: F;
	readonly args: A;
	readonly handler: Handler<F, A>;
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
	readonly handler: (
		args: never,
		ctx: Context,
	) => HandlerReturn | Promise<HandlerReturn>;
	readonly tags: readonly string[];
	readonly hidden: boolean;
	readonly interactive: boolean;
	readonly configFields: readonly string[];
}

export interface CommandSpec<F extends FlagMap, A extends readonly AnyArg[]> {
	readonly help: string;
	readonly flags?: F;
	readonly args?: A;
	readonly handler: Handler<F, A>;
	readonly tags?: readonly string[];
	readonly hidden?: boolean;
	readonly interactive?: boolean;
	readonly configFields?: readonly string[];
}

const TAG_RE = /^[a-z][a-z0-9-]*$/;

function validateTags(tags: readonly string[]): void {
	for (const tag of tags) {
		if (!TAG_RE.test(tag)) {
			throw new Error(`invalid tag name "${tag}": must match [a-z][a-z0-9-]*`);
		}
	}
}

export function defineCommand<
	const N extends string,
	const F extends FlagMap = Record<never, never>,
	const A extends readonly AnyArg[] = readonly [],
>(name: N, spec: CommandSpec<F, A>): CommandDef<N, F, A> {
	if (typeof spec.help !== "string" || spec.help.trim() === "") {
		throw new Error("Command.help must be a non-empty string");
	}
	// The empty fallbacks are safe: F/A only default when flags/args are absent.
	const flags = spec.flags ?? ({} as F);
	const args = spec.args ?? ([] as unknown as A);
	for (const [key, f] of Object.entries(flags)) {
		const expected = f.name.replaceAll("-", "_");
		if (key !== expected) {
			throw new Error(
				`command "${name}": flags key '${key}' must be the underscore form of flag '${f.name}' ('${expected}')`,
			);
		}
	}
	const tags = spec.tags ?? [];
	validateTags(tags);
	return {
		kind: "command",
		name,
		help: spec.help,
		flags,
		args,
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
		throw new Error("Command.help must be a non-empty string");
	}
	const tags = spec.tags ?? [];
	validateTags(tags);
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
		throw new Error("deprecated command name must be a non-empty string");
	}
	if (typeof message !== "string" || message.trim() === "") {
		throw new Error(`deprecated command "${name}": message must not be empty`);
	}
	return { kind: "deprecated", name, message };
}
