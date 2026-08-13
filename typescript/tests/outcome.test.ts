import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	interpretHandlerReturn,
	isOutcome,
	jsonCompact,
	outcome,
} from "../src/outcome.js";

// --- Branding ---

test("outcome: factory mints, forged shapes are rejected", () => {
	const o = outcome(3);
	assert.equal(isOutcome(o), true);
	// Structural clones are NOT outcomes -- only the factory mints.
	assert.equal(isOutcome({ exitCode: 3 }), false);
	assert.equal(isOutcome({ ...o }), false);
	assert.equal(isOutcome(null), false);
	assert.equal(isOutcome(3), false);
});

test("outcome: defaults to exit 0 and is frozen", () => {
	const o = outcome();
	assert.equal(o.exitCode, 0);
	assert.equal(Object.isFrozen(o), true);
});

test("outcome: non-integer exit codes are hard errors", () => {
	assert.throws(() => outcome(1.5), {
		name: "TypeError",
		message:
			"strictcli.outcome: exit_code must be an integer number; got non-integer number",
	});
	assert.throws(() => outcome("0" as never), {
		name: "TypeError",
		message:
			"strictcli.outcome: exit_code must be an integer number; got string",
	});
});

// --- interpretHandlerReturn: permitted returns ---

test("interpretHandlerReturn: undefined means exit 0", () => {
	assert.deepEqual(interpretHandlerReturn(undefined), { exitCode: 0 });
});

test("interpretHandlerReturn: integer numbers are exit codes", () => {
	assert.deepEqual(interpretHandlerReturn(3), { exitCode: 3 });
	assert.equal(interpretHandlerReturn(0).exitCode, 0);
	assert.equal(interpretHandlerReturn(-1).exitCode, -1);
});

test("interpretHandlerReturn: outcome carries the exit code", () => {
	assert.deepEqual(interpretHandlerReturn(outcome(2)), { exitCode: 2 });
	assert.deepEqual(interpretHandlerReturn(outcome(3)), { exitCode: 3 });
});

// --- interpretHandlerReturn: hard errors ---

function rejectsReturn(value: unknown, got: string): void {
	assert.throws(() => interpretHandlerReturn(value), {
		name: "TypeError",
		message:
			"command handler must return number (exit code), undefined (exit 0), " +
			`or strictcli.outcome(...); got ${got}`,
	});
}

test("interpretHandlerReturn: anything else is a hard error", () => {
	// The static message prefix is pinned by conformance
	// outcome_contract.json ("outcome: bad handler return is a hard error"):
	// stderr must contain "command handler must return".
	rejectsReturn("ok", "string");
	rejectsReturn(true, "boolean");
	rejectsReturn(null, "null");
	rejectsReturn(1.5, "non-integer number");
	rejectsReturn(Number.NaN, "non-integer number");
	rejectsReturn(3n, "bigint");
	rejectsReturn(["not-an-outcome"], "Array");
	rejectsReturn({ exitCode: 0 }, "Object");
	rejectsReturn(new Map(), "Map");
	rejectsReturn(() => 0, "function");
});

// --- jsonCompact ---

test("jsonCompact: compact separators, byte-identical to the siblings", () => {
	// Pinned by outcome_contract.json data-only case.
	assert.equal(
		jsonCompact({ count: 3, name: "strictcli" }),
		'{"count":3,"name":"strictcli"}',
	);
});

test("jsonCompact: BigInt values serialize as bare integer tokens", () => {
	assert.equal(jsonCompact(9007199254740993n), "9007199254740993");
	assert.equal(
		jsonCompact({ big: 123456789012345678901234567890n }),
		'{"big":123456789012345678901234567890}',
	);
	assert.equal(jsonCompact([1n, -2n]), "[1,-2]");
});

test("jsonCompact: Maps become objects with sorted keys", () => {
	const m = new Map<string, unknown>([
		["zeta", 1n],
		["alpha", "x"],
	]);
	assert.equal(jsonCompact(m), '{"alpha":"x","zeta":1}');
});

test("jsonCompact: plain objects keep insertion order", () => {
	assert.equal(jsonCompact({ b: 1, a: 2 }), '{"b":1,"a":2}');
});

test("jsonCompact: JSON.stringify semantics for edge values", () => {
	// undefined-valued properties are skipped; undefined array elements
	// become null (matching JSON.stringify).
	assert.equal(jsonCompact({ a: undefined, b: 1 }), '{"b":1}');
	assert.equal(jsonCompact([undefined, 1]), "[null,1]");
	assert.equal(jsonCompact(null), "null");
	assert.equal(jsonCompact("s"), '"s"');
	assert.equal(jsonCompact(true), "true");
	assert.equal(jsonCompact(1.5), "1.5");
	assert.equal(
		jsonCompact({ nested: { list: [1n, "two"] } }),
		'{"nested":{"list":[1,"two"]}}',
	);
});
