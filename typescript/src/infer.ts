/**
 * Handler-args inference: computes the precise args object type a handler
 * receives from a command's keyed flag map and ordered arg tuple.
 *
 * Optionality mirrors the runtime kwargs contract of the siblings:
 * - flags: scalar with `default: null` (explicitly optional) -> true `?:` key;
 *   everything else (required, defaulted, list, dict) -> always-present key.
 * - args: `required: false` with no default -> true `?:` key (the siblings
 *   omit the kwarg entirely); variadic -> always-present array.
 */

import type { AnyArg, AnyCommand, AnyFlag, FlagMap } from "./factories.js";
import type { DictSchema, ListSchema } from "./types.js";

/** Flattens an intersection into a single object type (homomorphic, keeps `?:`). */
type Prettify<T> = { [K in keyof T]: T[K] };

/** A flag key is optional iff the flag is scalar and declared with `default: null`. */
type FlagKeyIsOptional<D extends AnyFlag> = D["schema"] extends
	| ListSchema
	| DictSchema
	? false
	: D["opts"] extends { readonly default: null }
		? true
		: false;

type FlagValue<D extends AnyFlag> = NonNullable<D["_out"]>;

// -readonly: const type parameters mark the flag map's properties readonly,
// and homomorphic mapped types would otherwise propagate that into the
// handler-args type.
type RequiredFlagKeys<F extends FlagMap> = {
	-readonly [K in keyof F as FlagKeyIsOptional<F[K]> extends true
		? never
		: K]: FlagValue<F[K]>;
};

type OptionalFlagKeys<F extends FlagMap> = {
	-readonly [K in keyof F as FlagKeyIsOptional<F[K]> extends true
		? K
		: never]?: FlagValue<F[K]>;
};

/** An arg key is optional iff non-variadic, `required: false`, and no default. */
type ArgKeyIsOptional<D extends AnyArg> = D["opts"] extends {
	readonly variadic: true;
}
	? false
	: D["opts"] extends { readonly required: false }
		? "default" extends keyof D["opts"]
			? false
			: true
		: false;

type ArgValue<D extends AnyArg> = D["opts"] extends { readonly variadic: true }
	? NonNullable<D["_out"]>[]
	: NonNullable<D["_out"]>;

type RequiredArgKeys<A extends readonly AnyArg[]> = {
	[D in A[number] as ArgKeyIsOptional<D> extends true
		? never
		: D["name"]]: ArgValue<D>;
};

type OptionalArgKeys<A extends readonly AnyArg[]> = {
	[D in A[number] as ArgKeyIsOptional<D> extends true
		? D["name"]
		: never]?: ArgValue<D>;
};

export type InferHandlerArgs<
	F extends FlagMap,
	A extends readonly AnyArg[],
> = Prettify<
	RequiredFlagKeys<F> &
		OptionalFlagKeys<F> &
		RequiredArgKeys<A> &
		OptionalArgKeys<A>
>;

/** Handler-args type of a command carrier produced by defineCommand. */
export type InferHandler<C extends AnyCommand> = InferHandlerArgs<
	C["flags"],
	C["args"]
>;
