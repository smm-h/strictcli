/**
 * Claimed rendering: ctx.effects.recorded() / renderLog() (contract §19.7).
 *
 * Calling recorded() claims the render; renderLog() produces byte-identical
 * bytes wherever the handler puts them; a claim that never rendered is
 * re-rendered at the seam; and in machine mode renderLog() is a no-op.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { type App, createApp, defineMutatingCommand } from "../src/index.js";
import { envelope } from "./envelope_helpers.js";

const LOG =
	"DRY RUN — no changes were made. Would do:\n" +
	"  1. mkdir: build\n" +
	"  2. write: VERSION (5 bytes)\n";

function buildApp(opts: {
	claim?: boolean;
	render?: boolean;
	prints?: boolean;
}): App {
	const app = createApp({ name: "app", version: "1.0.0", help: "app" });
	app.command(
		defineMutatingCommand("build", {
			help: "build",
			handler: (_args, ctx) => {
				ctx.effects.mkdir("build");
				ctx.effects.write("VERSION", "1.2.3");
				if (opts.claim === true) {
					ctx.effects.recorded();
				}
				if (opts.render === true) {
					ctx.effects.renderLog();
				}
				if (opts.prints === true) {
					ctx.info("summary");
				}
				return 0;
			},
		}),
	);
	return app;
}

test("claimed rendering: unclaimed, the framework renders after the handler", async () => {
	const r = await buildApp({ prints: true }).test(["--dry-run", "build"]);
	assert.equal(r.stdout, `summary\n${LOG}`);
});

test("claimed rendering: renderLog puts the identical bytes first", async () => {
	const r = await buildApp({ render: true, prints: true }).test([
		"--dry-run",
		"build",
	]);
	assert.equal(r.stdout, `${LOG}summary\n`);
	assert.equal(r.stderr, "");
});

test("claimed rendering: a rendered log is not repeated at the seam", async () => {
	const r = await buildApp({ render: true }).test(["--dry-run", "build"]);
	assert.equal(r.stdout, LOG);
});

test("claimed rendering: claimed but never rendered is re-rendered at the seam", async () => {
	const r = await buildApp({ claim: true, prints: true }).test([
		"--dry-run",
		"build",
	]);
	assert.equal(r.stdout, `summary\n${LOG}`);
});

test("claimed rendering: recorded() returns the structured records", async () => {
	const app = createApp({ name: "app", version: "1.0.0", help: "app" });
	let seen: Record<string, unknown>[] = [];
	app.command(
		defineMutatingCommand("build", {
			help: "build",
			handler: (_args, ctx) => {
				ctx.effects.mkdir("build");
				seen = ctx.effects.recorded();
				return 0;
			},
		}),
	);
	await app.test(["--dry-run", "build"]);
	assert.deepEqual(seen, [
		{
			seq: 1,
			kind: "file_write",
			verb: "mkdir",
			detail: "build",
			recorded: true,
		},
	]);
});

/**
 * Records nothing at all: a live run must PERFORM whatever it records, and the
 * two cases below are about renderLog's own output.
 */
function effectlessApp(): App {
	const app = createApp({ name: "app", version: "1.0.0", help: "app" });
	app.command(
		defineMutatingCommand("build", {
			help: "build",
			handler: (_args, ctx) => {
				ctx.effects.renderLog();
				ctx.info("summary");
				return 0;
			},
		}),
	);
	return app;
}

test("claimed rendering: renderLog emits nothing outside dry mode", async () => {
	const r = await effectlessApp().test(["build"]);
	assert.equal(r.stdout, "summary\n");
	assert.equal(r.stderr, "");
});

test("claimed rendering: renderLog renders the bare header with no effects", async () => {
	const r = await effectlessApp().test(["--dry-run", "build"]);
	assert.equal(
		r.stdout,
		"DRY RUN — no changes were made. Would do:\nsummary\n",
	);
});

test("claimed rendering: renderLog is a no-op in machine mode", async () => {
	const r = await buildApp({ render: true }).test([
		"--json",
		"--dry-run",
		"build",
	]);
	assert.equal(r.stdout.includes("DRY RUN"), false);
	assert.deepEqual(
		(envelope(r.stdout).preview as Record<string, unknown>[]).map(
			(rec) => rec.verb,
		),
		["mkdir", "write"],
	);
	assert.equal(r.stderr, "");
});
