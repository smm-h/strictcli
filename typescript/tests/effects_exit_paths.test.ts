/**
 * The would-do log renders on every exit path out of a dry-mode dispatch, not
 * just the normal return (effects contract §3.1).
 *
 * app.run() writes to the real process streams, so these tests patch
 * process.stdout/stderr around it -- the same shape confirm.test.ts uses -- and
 * additionally survive a rejected run(), which is the whole point here.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	type App,
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
} from "../src/index.js";

const LOG =
	"DRY RUN — no changes were made. Would do:\n" +
	"  1. write: report.txt (2 bytes)\n";

interface RunCapture {
	stdout: string;
	stderr: string;
	exitCode: number;
	thrown: unknown;
}

/** Runs app.run(argv) against the real process streams, capturing both. */
async function captureRun(app: App, argv: string[]): Promise<RunCapture> {
	const out: string[] = [];
	const err: string[] = [];
	const realOut = process.stdout.write.bind(process.stdout);
	const realErr = process.stderr.write.bind(process.stderr);
	const patch =
		(sink: string[]) =>
		(chunk: string | Uint8Array): boolean => {
			sink.push(
				typeof chunk === "string" ? chunk : Buffer.from(chunk).toString(),
			);
			return true;
		};
	(process.stdout as unknown as { write: unknown }).write = patch(out);
	(process.stderr as unknown as { write: unknown }).write = patch(err);
	const savedExit = process.exitCode;
	let thrown: unknown;
	try {
		await app.run(argv);
	} catch (e) {
		thrown = e;
	} finally {
		(process.stdout as unknown as { write: unknown }).write = realOut;
		(process.stderr as unknown as { write: unknown }).write = realErr;
	}
	const exitCode = process.exitCode ?? 0;
	process.exitCode = savedExit;
	return {
		stdout: out.join(""),
		stderr: err.join(""),
		exitCode: Number(exitCode),
		thrown,
	};
}

/** One mutating command that records a write and then leaves via `tail`. */
function exitApp(tail: () => number): App {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	app.command(
		defineMutatingCommand("rel", {
			help: "h",
			handler: (_a, ctx) => {
				ctx.effects.write("report.txt", "ok");
				return tail();
			},
		}),
	);
	return app;
}

test("exit paths: a non-zero return still renders the log", async () => {
	const r = await captureRun(
		exitApp(() => 3),
		["--dry-run", "rel"],
	);
	assert.equal(r.stdout, LOG);
	assert.equal(r.stderr, "");
	assert.equal(r.exitCode, 3);
});

test("exit paths: a throwing handler still renders the log, marked incomplete", async () => {
	const app = exitApp(() => {
		throw new Error("kaboom");
	});
	const r = await captureRun(app, ["--dry-run", "rel"]);
	assert.equal(r.stdout, LOG);
	assert.equal(
		r.stderr,
		"error: dry-run preview ends at step 2: rel aborted — " +
			"the preview above may be incomplete\n",
	);
	// The throw continues untouched: nothing here swallows it.
	assert.equal((r.thrown as Error).message, "kaboom");
});

test("exit paths: a rejecting async handler is the same path", async () => {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	app.command(
		defineMutatingCommand("rel", {
			help: "h",
			handler: async (_a, ctx) => {
				ctx.effects.write("report.txt", "ok");
				await Promise.resolve();
				throw new Error("kaboom");
			},
		}),
	);
	const r = await captureRun(app, ["--dry-run", "rel"]);
	assert.equal(r.stdout, LOG);
	assert.match(r.stderr, /rel aborted/);
	assert.equal((r.thrown as Error).message, "kaboom");
});

test("exit paths: a bad handler return renders the log, marked incomplete", async () => {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	app.command(
		defineMutatingCommand("rel", {
			help: "h",
			handler: ((_a: unknown, ctx: { effects: { write: unknown } }) => {
				(ctx.effects.write as (p: string, c: string) => unknown)(
					"report.txt",
					"ok",
				);
				return ["not", "an", "outcome"];
			}) as never,
		}),
	);
	const r = await captureRun(app, ["--dry-run", "rel"]);
	assert.equal(r.stdout, LOG);
	assert.match(r.stderr, /rel aborted/);
	assert.match((r.thrown as Error).message, /command handler must return/);
});

test("exit paths: an aborted preview names the DOTTED command path", async () => {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	const grp = app.group("release", { help: "h" });
	grp.command(
		defineMutatingCommand("run", {
			help: "h",
			handler: () => {
				throw new Error("kaboom");
			},
		}),
	);
	const r = await captureRun(app, ["--dry-run", "release", "run"]);
	assert.equal(r.stdout, "DRY RUN — no changes were made. Would do:\n");
	assert.match(r.stderr, /release\.run aborted/);
});

test("exit paths: an aborted read_only preview is header with empty body", async () => {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	app.command(
		defineReadOnlyCommand("look", {
			help: "h",
			handler: () => {
				throw new Error("kaboom");
			},
		}),
	);
	const r = await captureRun(app, ["--dry-run", "look"]);
	assert.equal(r.stdout, "DRY RUN — no changes were made. Would do:\n");
	assert.match(r.stderr, /look aborted/);
});

test("exit paths: --quiet never suppresses the log and never moves the marker", async () => {
	const app = exitApp(() => {
		throw new Error("kaboom");
	});
	const r = await captureRun(app, ["--quiet", "--dry-run", "rel"]);
	assert.equal(r.stdout, LOG);
	assert.match(r.stderr, /rel aborted/);
});

test("exit paths: a live run has no log and no marker", async () => {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	app.command(
		defineReadOnlyCommand("look", {
			help: "h",
			handler: () => {
				throw new Error("kaboom");
			},
		}),
	);
	const r = await captureRun(app, ["look"]);
	assert.equal(r.stdout, "");
	assert.equal(r.stderr, "");
	assert.equal((r.thrown as Error).message, "kaboom");
});

test("exit paths: the truncation path keeps its own rendering and exit code", async () => {
	const app = createApp({ name: "t", version: "1.0.0", help: "h" });
	app.command(
		defineMutatingCommand("rel", {
			help: "h",
			handler: (_a, ctx) => {
				const u = ctx.effects.run(["git", "status"]);
				ctx.info(u.stdout); // extraction: truncates
				return 0;
			},
		}),
	);
	const r = await captureRun(app, ["--dry-run", "rel"]);
	assert.equal(
		r.stdout,
		"DRY RUN — no changes were made. Would do:\n  1. run: git status\n",
	);
	assert.equal(
		r.stderr,
		"error: dry-run preview ends at step 2: rel branched on unsettled " +
			"value «step 1 output» — cannot preview past this point\n",
	);
	assert.equal(r.exitCode, 1);
	assert.equal(r.thrown, undefined);
});
