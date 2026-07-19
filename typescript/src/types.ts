/**
 * Type foundation: nominally-branded carriers pairing a phantom output type
 * with a literal schema string. Productionizes Solution 10 from the verified
 * spike (see ts-port-spec.md, "Type-machinery reference").
 */

import {
	parseBoolStrict,
	parseFloatStrictValue,
	parseIntStrict,
} from "./values.js";

// --- Schema string unions (closed set of ten) ---

export type ScalarSchema = "str" | "bool" | "int" | "float";
/** Element schemas for list items and dict values -- bool is deliberately excluded. */
export type ElemSchema = "str" | "int" | "float";
export type ListSchema = `list[${ElemSchema}]`;
/** Dict keys are always str. No space after the comma. */
export type DictSchema = `dict[str,${ElemSchema}]`;
export type Schema = ScalarSchema | ListSchema | DictSchema;

// --- Carrier ---

// Phantom-only nominal brand: never set at runtime. It exists so hand-forged
// object literals cannot masquerade as carriers at the type level.
declare const CarrierBrand: unique symbol;

/**
 * A carrier pairs a phantom output type with a literal schema string and the
 * runtime parse function. The schema string and the output type are computed
 * by one generic per constructor, so they cannot drift.
 */
export interface Carrier<Out, S extends Schema> {
	readonly [CarrierBrand]: true;
	/** Phantom output type; never present at runtime. */
	readonly _out?: Out;
	readonly schema: S;
	readonly parse: (raw: string) => Out;
	/** Element carrier for list/dict carriers; absent on scalar carriers. */
	readonly elem?: Carrier<unknown, ElemSchema>;
}

// The brand is phantom-only, so no object literal satisfies the interface
// directly -- the double cast is the single sanctioned construction site.
function mkScalar<Out, S extends ScalarSchema>(
	schema: S,
	parse: (raw: string) => Out,
): Carrier<Out, S> {
	return { schema, parse } as unknown as Carrier<Out, S>;
}

// Compound carriers are parsed element-wise by the parser (a raw CLI token is
// one element occurrence, never a whole list/dict), so a whole-value parse on
// the compound carrier itself would be silent nonsense. Hard error instead.
function compoundParse(): never {
	throw new Error(
		"internal: compound carriers are parsed element-wise via their elem carrier",
	);
}

export const t = {
	// Scalar parse bodies are the strict parity parsers from values.ts: int
	// strictness (no whitespace, 64-bit signed bounds), float NaN/Inf
	// rejection, bool env-string rules. They throw ParseError with the bare
	// (context-free) sibling messages; callers add flag/arg context.
	str: mkScalar<string, "str">("str", (raw) => raw),
	bool: mkScalar<boolean, "bool">("bool", parseBoolStrict),
	int: mkScalar<bigint, "int">("int", parseIntStrict),
	float: mkScalar<number, "float">("float", parseFloatStrictValue),
	// ONE generic each: output type and schema string both derive from the
	// element carrier's type parameters, so they cannot drift.
	list<Out, S extends ElemSchema>(
		elem: Carrier<Out, S>,
	): Carrier<Out[], `list[${S}]`> {
		return {
			schema: `list[${elem.schema}]`,
			parse: compoundParse,
			elem,
		} as unknown as Carrier<Out[], `list[${S}]`>;
	},
	dict<Out, S extends ElemSchema>(
		elem: Carrier<Out, S>,
	): Carrier<Map<string, Out>, `dict[str,${S}]`> {
		return {
			schema: `dict[str,${elem.schema}]`,
			parse: compoundParse,
			elem,
		} as unknown as Carrier<Map<string, Out>, `dict[str,${S}]`>;
	},
};

// --- Handler result contract (placeholders wired up by later subphases) ---

// Phantom brand; outcome.ts (later subphase) provides the constructor and the
// runtime brand so invoke.ts can hard-error on any other return value.
declare const OutcomeBrand: unique symbol;

/** Branded marker for structured handler outcomes (see outcome.ts, later subphase). */
export interface Outcome {
	readonly [OutcomeBrand]: true;
}

/** Placeholder until context.ts lands (later subphase). */
export type Context = unknown;

/** Strict result contract: a handler returns a number, undefined, or outcome(...). */
export type HandlerResult = number | undefined | Outcome;

/** What a handler function may return (void covers handlers with no return statement). */
// biome-ignore lint/suspicious/noConfusingVoidType: replacing void with undefined would reject handlers that have no return statement (their return type infers as void, which is not assignable to undefined)
export type HandlerReturn = HandlerResult | void;
