/**
 * Handler-args inference: computes the precise args object type a handler
 * receives from a command's keyed flag map and ordered arg tuple.
 *
 * Optionality follows the DECLARED presence (contract §23.2), for flags and
 * args alike:
 * - flags: `presence: "optional"` -> true `?:` key, for every carrier
 *   including compounds; `required` and `default` -> always-present key.
 * - args: `presence: "optional"` on a non-variadic arg -> true `?:` key (the
 *   runtime object carries the property holding `undefined`, §23.3); variadic
 *   -> always-present array, since a variadic always delivers a list.
 *
 * Reading the declaration is what fixes the unsoundness this module carried:
 * a mutex member declared without a default used to be typed as an
 * always-present, non-nullable key while the parser handed it `undefined`
 * through the exemption §23.4 deletes.
 */

import type { AnyArg, AnyCommand, AnyFlag, FlagMap } from "./factories.js";

/** Flattens an intersection into a single object type (homomorphic, keeps `?:`). */
type Prettify<T> = { [K in keyof T]: T[K] };

/** A flag key is optional iff the flag declares `presence: "optional"`. */
type FlagKeyIsOptional<D extends AnyFlag> = D["opts"] extends {
	readonly presence: "optional";
}
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

/** An arg key is optional iff it is non-variadic and declares `presence: "optional"`. */
type ArgKeyIsOptional<D extends AnyArg> = D["opts"] extends {
	readonly variadic: true;
}
	? false
	: D["opts"] extends { readonly presence: "optional" }
		? true
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

/**
 * Computes the handler args type from a flag map and arg tuple. Flags and
 * non-variadic args declaring `presence: "optional"` become optional keys.
 */
export type InferHandlerArgs<
	F extends FlagMap,
	A extends readonly AnyArg[],
> = Prettify<
	RequiredFlagKeys<F> &
		OptionalFlagKeys<F> &
		RequiredArgKeys<A> &
		OptionalArgKeys<A>
>;

// The [U] extends [never] guard keeps the empty case at `unknown` (identity
// under intersection); the naked distribution would collapse it to `never`.
type UnionToIntersection<U> = [U] extends [never]
	? unknown
	: (U extends unknown ? (x: U) => void : never) extends (x: infer I) => void
		? I
		: never;

/**
 * Args contributed by an array of flag-carrying descriptors (flag sets or
 * mutex groups): each descriptor's flag map is inferred independently, then
 * all are intersected.
 */
type FlagCarrierArgs<T extends readonly { readonly flags: FlagMap }[]> =
	UnionToIntersection<
		T[number] extends { readonly flags: infer FM extends FlagMap }
			? InferHandlerArgs<FM, readonly []>
			: never
	>;

/**
 * The complete args object a handler receives: direct flags, positional args,
 * plus every flag contributed by flag sets and mutex groups. The empty case
 * short-circuits to InferHandlerArgs so the type stays identical (not merely
 * mutually assignable) to the plain flags/args inference.
 */
export type HandlerArgs<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly { readonly flags: FlagMap }[],
	M extends readonly { readonly flags: FlagMap }[],
> = [FS, M] extends [readonly [], readonly []]
	? InferHandlerArgs<F, A>
	: Prettify<InferHandlerArgs<F, A> & FlagCarrierArgs<FS> & FlagCarrierArgs<M>>;

/**
 * Handler-args type of a command carrier produced by defineCommand. Derived
 * from the stored handler's parameter type so flag-set and mutex flags are
 * included.
 */
export type InferHandler<C extends AnyCommand> = Parameters<C["handler"]>[0];
