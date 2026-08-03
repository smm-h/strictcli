/**
 * The framework-owned confirm protocol (§8), byte-exact.
 *
 * The stdin side is driven through the package-internal setConfirmIO seam (the
 * TS analog of Python's tests monkeypatching sys.stdin): it changes WHERE the
 * answer comes from, never WHETHER the protocol runs.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { type ConfirmIO, setConfirmIO } from "../src/confirm.js";
import type { Writer } from "../src/context.js";
import {
	type App,
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
	mutatingPassthrough,
	readOnlyPassthrough,
} from "../src/index.js";

/** Captures the real process streams for the duration of an app.run(). */
async function captureRun(
	app: App,
	argv: string[],
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
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
	try {
		await app.run(argv);
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
	};
}

function io(answer: string | null, interactive = true): ConfirmIO {
	return {
		isInteractive: () => interactive,
		readLine: () => answer ?? "",
	};
}

function ranApp(record: string[]): App {
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineMutatingCommand("deploy", {
			help: "h",
			handler: () => {
				record.push("ran");
				return 0;
			},
		}),
	);
	app.command(
		defineReadOnlyCommand("look", {
			help: "h",
			handler: () => {
				record.push("looked");
				return 0;
			},
		}),
	);
	return app;
}

test("confirm: the prompt is byte-exact and 'y' proceeds", async () => {
	const ran: string[] = [];
	setConfirmIO(io("y"));
	try {
		const r = await captureRun(ranApp(ran), ["deploy"]);
		assert.equal(
			r.stderr,
			"about to run mutating command 'deploy'. Proceed? [y/N] ",
		);
		assert.deepEqual(ran, ["ran"]);
		assert.equal(r.exitCode, 0);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: exactly 'y' or 'Y' proceeds; everything else declines", async () => {
	for (const answer of ["y", "Y"]) {
		const ran: string[] = [];
		setConfirmIO(io(answer));
		try {
			await captureRun(ranApp(ran), ["deploy"]);
			assert.deepEqual(ran, ["ran"], answer);
		} finally {
			setConfirmIO(null);
		}
	}
	for (const answer of ["", "yes", "n", "N", "Yes", " y"]) {
		const ran: string[] = [];
		setConfirmIO(io(answer));
		try {
			const r = await captureRun(ranApp(ran), ["deploy"]);
			assert.deepEqual(ran, [], JSON.stringify(answer));
			assert.equal(r.exitCode, 1);
			assert.equal(
				r.stderr,
				"about to run mutating command 'deploy'. Proceed? [y/N] aborted\n",
			);
		} finally {
			setConfirmIO(null);
		}
	}
});

test("confirm: a non-interactive stdin errors instead of prompting", async () => {
	const ran: string[] = [];
	setConfirmIO(io("y", /* interactive */ false));
	try {
		const r = await captureRun(ranApp(ran), ["deploy"]);
		assert.equal(
			r.stderr,
			"error: stdin is not interactive; pass --yes to confirm\n",
		);
		assert.equal(r.exitCode, 1);
		assert.deepEqual(ran, []);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: --yes skips the prompt", async () => {
	const ran: string[] = [];
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(ranApp(ran), ["--yes", "deploy"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["ran"]);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: --dry-run skips the prompt", async () => {
	const ran: string[] = [];
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(ranApp(ran), ["--dry-run", "deploy"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["ran"]);
		assert.ok(r.stdout.includes("DRY RUN — no changes were made. Would do:"));
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: never fires for a read_only command", async () => {
	const ran: string[] = [];
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(ranApp(ran), ["look"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["looked"]);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: a MUTATING passthrough is not exempt", async () => {
	const ran: string[] = [];
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		mutatingPassthrough("exec", {
			help: "h",
			handler: () => {
				ran.push("ran");
				return 0;
			},
		}),
	);
	setConfirmIO(io("n"));
	try {
		const r = await captureRun(app, ["exec", "--anything"]);
		assert.equal(
			r.stderr,
			"about to run mutating command 'exec'. Proceed? [y/N] aborted\n",
		);
		assert.deepEqual(ran, []);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: a READ-ONLY passthrough never prompts", async () => {
	const ran: string[] = [];
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		readOnlyPassthrough("show", {
			help: "h",
			handler: () => {
				ran.push("ran");
				return 0;
			},
		}),
	);
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(app, ["show", "--anything"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["ran"]);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: the prompt names the DOTTED command path", async () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	const release = app.group("release", { help: "h" });
	release.command(
		defineMutatingCommand("run", { help: "h", handler: () => 0 }),
	);
	setConfirmIO(io("n"));
	try {
		const r = await captureRun(app, ["release", "run"]);
		assert.ok(
			r.stderr.startsWith(
				"about to run mutating command 'release.run'. Proceed? [y/N] ",
			),
			r.stderr,
		);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: the programmatic paths behave as if --yes were passed", async () => {
	const ran: string[] = [];
	setConfirmIO(io("n", /* interactive */ false));
	try {
		// test(): never prompts, never emits the non-TTY error.
		const r = await ranApp(ran).test(["deploy"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["ran"]);
		// call(): likewise.
		ran.length = 0;
		await ranApp(ran).call("deploy");
		assert.deepEqual(ran, ["ran"]);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: ctx.yes reflects the actual flag, not the dispatch path", async () => {
	const seen: boolean[] = [];
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineMutatingCommand("deploy", {
			help: "h",
			handler: (_a, ctx) => {
				seen.push(ctx.yes);
				return 0;
			},
		}),
	);
	// Prompt suppression is a property of the dispatch path; the flag value is
	// reported honestly.
	await app.test(["deploy"]);
	await app.test(["--yes", "deploy"]);
	assert.deepEqual(seen, [false, true]);
});

test("confirm: setConfirmIO is package-internal (never re-exported)", async () => {
	const api = (await import("../src/index.js")) as unknown as Record<
		string,
		unknown
	>;
	assert.equal(api.setConfirmIO, undefined);
	// A Writer is all the protocol needs from the caller's side.
	const sink: Writer = { write: () => {} };
	assert.equal(typeof sink.write, "function");
});
