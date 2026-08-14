/**
 * Handler-args inference: computes the precise args object type a handler
 * receives from a command's keyed declaration map and ordered arg tuple.
 *
 * Optionality follows the DECLARED presence (contract §23.2), for flags and
 * args alike:
 * - flags: `presence: "optional"` -> true `?:` key, for every carrier
 *   including compounds; `required` and `default` -> always-present key.
 * - args: `presence: "optional"` on a non-variadic arg -> true `?:` key (the
 *   runtime object carries the property holding `undefined`, §23.3); variadic
 *   -> always-present array, since a variadic always delivers a list.
 *
 * A SELECTOR delivers one tagged value under its own key: an exact
 * discriminated union with one member per declared choice, each carrying the
 * literal choice name under `choice` plus that choice's own scope inferred by
 * the same machinery, so nesting recurses for free (§24.1, §24.12):
 *
 *   choiceFlag("via", { email: choice({ help, flags: { subject: ... } }),
 *                       sms:   choice({ help, flags: { phone_number: ... } }) },
 *              { help, presence: "required" })
 *
 *   args.via: { choice: "email"; subject: string }
 *           | { choice: "sms";   phone_number: string }
 *
 * and a `switch (args.via.choice)` missing a case fails to compile at the
 * `assertNever` line. Nothing above is written by the declaring code.
 *
 * The soundness rule this module exists to hold: a key's optionality follows
 * the DECLARED presence, and a sub-flag NEVER becomes a top-level key. That
 * second half is the structural fix for the unsoundness this module carried
 * in its mutex-group form -- mutex members were intersected into the
 * top-level args as always-present, non-nullable keys while the parser handed
 * them `undefined`. A scope's flags are reachable only through the tag that
 * proves the scope was elected, so the failure mode is inexpressible rather
 * than merely fixed by declaration (§23.2, §24.12).
 */

import type {
	AnyArg,
	AnyChoiceFlag,
	AnyCommand,
	AnyDecl,
	AnyFlag,
	ChoiceMap,
	FlagMap,
} from "./factories.js";

/** Flattens an intersection into a single object type (homomorphic, keeps `?:`). */
type Prettify<T> = { [K in keyof T]: T[K] };

/**
 * A key is optional iff its declaration says `presence: "optional"`. A
 * selector can never be optional (§24.5), so this reads uniformly over both
 * declaration kinds.
 */
type KeyIsOptional<D extends AnyDecl> = D["opts"] extends {
	readonly presence: "optional";
}
	? true
	: false;

/**
 * A member-spelled choice may carry a payload on its own electing token
 * (`--profile work`), delivered under the reserved name `value`. `unknown` is
 * the identity under intersection, so a payload-less choice contributes
 * nothing at all.
 */
type ChoiceValuePart<C> = C extends {
	readonly value: { readonly _out?: infer V };
}
	? { value: NonNullable<V> }
	: unknown;

/**
 * The tagged union a selector delivers: one member per declared choice,
 * carrying the literal choice name under `choice`, that choice's payload if
 * it has one, and that choice's own scope.
 */
export type Elected<C extends ChoiceMap> = {
	[K in keyof C & string]: Prettify<
		{ readonly choice: K } & ChoiceValuePart<C[K]> &
			InferScopeArgs<C[K]["flags"]>
	>;
}[keyof C & string];

/**
 * The value one declaration delivers. The `kind` discriminant is what keeps
 * this from guessing: a selector is matched by its literal kind, never by the
 * shape of its options.
 */
type Delivered<D extends AnyDecl> = D extends { readonly kind: "choice-flag" }
	? Elected<D["choices"]>
	: D extends AnyFlag
		? NonNullable<D["_out"]>
		: never;

// -readonly: const type parameters mark the declaration map's properties
// readonly, and homomorphic mapped types would otherwise propagate that into
// the handler-args type.
type RequiredFlagKeys<F extends FlagMap> = {
	-readonly [K in keyof F as KeyIsOptional<F[K]> extends true
		? never
		: K]: Delivered<F[K]>;
};

type OptionalFlagKeys<F extends FlagMap> = {
	-readonly [K in keyof F as KeyIsOptional<F[K]> extends true
		? K
		: never]?: Delivered<F[K]>;
};

/** The complete args object one scope contributes (a choice's own flags). */
export type InferScopeArgs<F extends FlagMap> = Prettify<
	RequiredFlagKeys<F> & OptionalFlagKeys<F>
>;

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
 * Computes the handler args type from a declaration map and arg tuple. Flags
 * and non-variadic args declaring `presence: "optional"` become optional keys.
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
 * Args contributed by an array of flag-carrying descriptors (flag sets):
 * each descriptor's declaration map is inferred independently, then all are
 * intersected.
 */
type FlagCarrierArgs<T extends readonly { readonly flags: FlagMap }[]> =
	UnionToIntersection<
		T[number] extends { readonly flags: infer FM extends FlagMap }
			? InferHandlerArgs<FM, readonly []>
			: never
	>;

/**
 * The complete args object a handler receives: direct declarations,
 * positional args, plus every flag contributed by flag sets. The empty case
 * short-circuits to InferHandlerArgs so the type stays identical (not merely
 * mutually assignable) to the plain flags/args inference.
 */
export type HandlerArgs<
	F extends FlagMap,
	A extends readonly AnyArg[],
	FS extends readonly { readonly flags: FlagMap }[],
> = [FS] extends [readonly []]
	? InferHandlerArgs<F, A>
	: Prettify<InferHandlerArgs<F, A> & FlagCarrierArgs<FS>>;

/**
 * Handler-args type of a command carrier produced by defineCommand. Derived
 * from the stored handler's parameter type so flag-set flags are included.
 */
export type InferHandler<C extends AnyCommand> = Parameters<C["handler"]>[0];

/** The elected-value type of one selector declaration, for handler helpers. */
export type ElectedOf<D extends AnyChoiceFlag> = Elected<D["choices"]>;

/** The elected-value type of one named choice, for per-choice helper functions. */
export type ChoiceOf<
	D extends AnyChoiceFlag,
	K extends keyof D["choices"] & string,
> = Extract<Elected<D["choices"]>, { readonly choice: K }>;
