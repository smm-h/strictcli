import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { Carrier, DictSchema, Schema } from "../src/index.js";
import { flag, t } from "../src/index.js";

// Exact type equality via the conditional-generic-signature trick (see
// ts-port-spec.md, "Equals type-assertion technique").
type Equals<A, B> =
	(<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
		? true
		: false;
type Assert<T extends true> = T;

// --- Runtime: schema strings are byte-exact (no space after the comma) ---

test("scalar schema strings are exact", () => {
	assert.equal(t.str.schema, "str");
	assert.equal(t.bool.schema, "bool");
	assert.equal(t.int.schema, "int");
	assert.equal(t.float.schema, "float");
});

test("list schema strings are exact", () => {
	assert.equal(t.list(t.str).schema, "list[str]");
	assert.equal(t.list(t.int).schema, "list[int]");
	assert.equal(t.list(t.float).schema, "list[float]");
});

test("dict schema strings are exact", () => {
	assert.equal(t.dict(t.str).schema, "dict[str,str]");
	assert.equal(t.dict(t.int).schema, "dict[str,int]");
	assert.equal(t.dict(t.float).schema, "dict[str,float]");
});

test("compound carriers refuse whole-value parsing", () => {
	assert.throws(() => t.list(t.str).parse("x"), {
		message:
			"internal: compound carriers are parsed element-wise via their elem carrier",
	});
});

// --- Type-level: schema literals and value types computed by one generic ---

const listInt = t.list(t.int);
const dictFloat = t.dict(t.float);

export type _ListIntSchema = Assert<
	Equals<(typeof listInt)["schema"], "list[int]">
>;
export type _ListIntOut = Assert<
	Equals<NonNullable<(typeof listInt)["_out"]>, bigint[]>
>;
export type _DictFloatSchema = Assert<
	Equals<(typeof dictFloat)["schema"], "dict[str,float]">
>;
export type _DictFloatOut = Assert<
	Equals<NonNullable<(typeof dictFloat)["_out"]>, Map<string, number>>
>;
export type _IntIsBigint = Assert<
	Equals<NonNullable<(typeof t.int)["_out"]>, bigint>
>;

// The ten schema strings form a closed union.
export type _SchemaCount = Assert<
	Equals<
		Schema,
		| "str"
		| "bool"
		| "int"
		| "float"
		| "list[str]"
		| "list[int]"
		| "list[float]"
		| "dict[str,str]"
		| "dict[str,int]"
		| "dict[str,float]"
	>
>;

// --- Wrong-declaration cases: compilation of @ts-expect-error IS the assertion ---

// @ts-expect-error bool is not a valid list element type
t.list(t.bool);

// @ts-expect-error bool is not a valid dict value type
t.dict(t.bool);

// @ts-expect-error dict schema strings have no space after the comma
const _badDictSchema: DictSchema = "dict[str, int]";

// @ts-expect-error hand-forged object literals are not branded carriers
const _forged: Carrier<string, "str"> = {
	schema: "str",
	parse: (r: string) => r,
};

// @ts-expect-error a forged carrier cannot be passed to flag()
flag("target", { schema: "str", parse: (r: string) => r }, { help: "x" });
