import { strict as assert } from "node:assert";
import { test } from "node:test";
import { Context, type Writer } from "../src/context.js";

function sink(): { chunks: string[]; writer: Writer } {
	const chunks: string[] = [];
	return { chunks, writer: { write: (s: string) => chunks.push(s) } };
}

test("context: info/debug write to stdout, warn/error to stderr", () => {
	const out = sink();
	const err = sink();
	const ctx = new Context(out.writer, err.writer, {}, null);
	ctx.info("i");
	ctx.debug("d");
	ctx.warn("w");
	ctx.error("e");
	assert.deepEqual(out.chunks, ["i\n", "d\n"]);
	assert.deepEqual(err.chunks, ["w\n", "e\n"]);
});

test("context: source accepts underscored and dashed names", () => {
	const out = sink();
	const ctx = new Context(out.writer, out.writer, { dry_run: "cli" }, null);
	assert.equal(ctx.source("dry_run"), "cli");
	assert.equal(ctx.source("dry-run"), "cli");
});

test("context: source tries the underscore form first", () => {
	const out = sink();
	// A pathological map with both spellings: the underscore form wins,
	// mirroring the siblings' lookup order.
	const ctx = new Context(
		out.writer,
		out.writer,
		{ dry_run: "env", "dry-run": "cli" },
		null,
	);
	assert.equal(ctx.source("dry-run"), "env");
});

test("context: source throws the sibling message for unknown flags", () => {
	const out = sink();
	const ctx = new Context(out.writer, out.writer, {}, null);
	assert.throws(() => ctx.source("nope"), {
		message: 'no source info for flag "nope"',
	});
});

test("context: infraValue throws not-declared without infra wiring", () => {
	const out = sink();
	const ctx = new Context(out.writer, out.writer, {}, null);
	assert.throws(() => ctx.infraValue("MYTOOL_ROOT"), {
		message:
			'InfraValue: "MYTOOL_ROOT" is not a declared infra root or handshake env var',
	});
});

test("context: infraValue resolves declared roots and live handshakes", () => {
	const out = sink();
	const ctx = new Context(
		out.writer,
		out.writer,
		{},
		{
			roots: new Map([["MYTOOL_ROOT", "/resolved/root"]]),
			handshakes: new Set(["MYTOOL_HANDSHAKE"]),
		},
	);
	assert.deepEqual(ctx.infraValue("MYTOOL_ROOT"), ["/resolved/root", true]);
	// Handshake read is LIVE from the environment.
	delete process.env.MYTOOL_HANDSHAKE;
	assert.deepEqual(ctx.infraValue("MYTOOL_HANDSHAKE"), [undefined, false]);
	process.env.MYTOOL_HANDSHAKE = "1";
	try {
		assert.deepEqual(ctx.infraValue("MYTOOL_HANDSHAKE"), ["1", true]);
	} finally {
		delete process.env.MYTOOL_HANDSHAKE;
	}
	assert.throws(() => ctx.infraValue("OTHER"), {
		message:
			'InfraValue: "OTHER" is not a declared infra root or handshake env var',
	});
});
