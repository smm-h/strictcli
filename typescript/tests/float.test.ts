import { strict as assert } from "node:assert";
import { test } from "node:test";
import { formatFloatCanonical } from "../src/float.js";

// The 15-value SCF battery from ts-port-spec.md.
const battery: readonly [number, string][] = [
	[1.0, "1.0"],
	[-1.0, "-1.0"],
	[0.5, "0.5"],
	[-0.0, "-0.0"],
	[100.0, "100.0"],
	[1e15, "1000000000000000.0"],
	[1e16, "10000000000000000.0"],
	[1e20, "100000000000000000000.0"],
	[1e21, "1e+21"],
	[1e-4, "0.0001"],
	[1e-5, "0.00001"],
	[1e-7, "1e-7"],
	[0.1, "0.1"],
	[9007199254740992, "9007199254740992.0"],
	[1.5e300, "1.5e+300"],
];

test("SCF battery from ts-port-spec.md", () => {
	for (const [input, expected] of battery) {
		assert.equal(formatFloatCanonical(input), expected, `input ${input}`);
	}
});

test("zero carve-out distinguishes -0.0 from 0.0", () => {
	assert.equal(formatFloatCanonical(0), "0.0");
	assert.equal(formatFloatCanonical(-0), "-0.0");
});

/** The adjacent double on the given side of x, via bit-level step. */
function nextAfter(x: number, direction: -1n | 1n): number {
	const dv = new DataView(new ArrayBuffer(8));
	dv.setFloat64(0, x);
	dv.setBigUint64(0, dv.getBigUint64(0) + direction);
	return dv.getFloat64(0);
}

test("band boundaries: fixed inside [1e-6, 1e21), scientific outside", () => {
	assert.equal(formatFloatCanonical(1e-6), "0.000001");
	assert.equal(
		formatFloatCanonical(nextAfter(1e-6, -1n)),
		"9.999999999999997e-7",
	);
	assert.equal(
		formatFloatCanonical(nextAfter(1e21, -1n)),
		"999999999999999900000.0",
	);
	assert.equal(formatFloatCanonical(1e21), "1e+21");
});

test("scientific spelling: lowercase e, explicit sign, no exponent padding", () => {
	assert.equal(formatFloatCanonical(5e-324), "5e-324");
	assert.equal(formatFloatCanonical(1e-323), "1e-323");
	assert.equal(formatFloatCanonical(-1.5e300), "-1.5e+300");
});

test("non-finite input is an internal hard error", () => {
	assert.throws(() => formatFloatCanonical(Number.NaN), {
		message: "internal: formatFloatCanonical on non-finite NaN",
	});
	assert.throws(() => formatFloatCanonical(Number.POSITIVE_INFINITY), {
		message: "internal: formatFloatCanonical on non-finite Infinity",
	});
	assert.throws(() => formatFloatCanonical(Number.NEGATIVE_INFINITY), {
		message: "internal: formatFloatCanonical on non-finite -Infinity",
	});
});
