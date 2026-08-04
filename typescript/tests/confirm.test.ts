/**
 * The framework-owned confirm protocol (§8), byte-exact.
 *
 * The protocol fires for commands that DECLARE THEMSELVES consequential, never
 * for a plain `mutating` command.
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
			consequential: true,
			handler: () => {
				record.push("ran");
				return 0;
			},
		}),
	);
	app.command(
		defineMutatingCommand("build", {
			help: "h",
			handler: () => {
				record.push("built");
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
			"about to run consequential command 'deploy'. Proceed? [y/N] ",
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
	// A human at a Windows console types the same 'y'; their terminal terminates
	// the line CRLF and stdin hands us the carriage return (§8.2).
	for (const answer of ["y\r", "Y\r"]) {
		const ran: string[] = [];
		setConfirmIO(io(answer));
		try {
			await captureRun(ranApp(ran), ["deploy"]);
			assert.deepEqual(ran, ["ran"], JSON.stringify(answer));
		} finally {
			setConfirmIO(null);
		}
	}
	for (const answer of ["", "yes", "n", "N", "Yes", " y", "y\r\r", "\ry"]) {
		const ran: string[] = [];
		setConfirmIO(io(answer));
		try {
			const r = await captureRun(ranApp(ran), ["deploy"]);
			assert.deepEqual(ran, [], JSON.stringify(answer));
			assert.equal(r.exitCode, 1);
			assert.equal(
				r.stderr,
				"about to run consequential command 'deploy'. Proceed? [y/N] aborted\n",
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
			"error: stdin is not interactive; pass --approve-consequential to confirm\n",
		);
		assert.equal(r.exitCode, 1);
		assert.deepEqual(ran, []);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: --approve-consequential skips the prompt", async () => {
	const ran: string[] = [];
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(ranApp(ran), [
			"--approve-consequential",
			"deploy",
		]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["ran"]);
	} finally {
		setConfirmIO(null);
	}
});

// The headline of the redesign: `mutating` alone never prompts. Two thirds of
// the commands in a real fleet classify mutating; the genuinely dangerous ones
// are a small fraction of that.
test("confirm: never fires for a mutating command that is not consequential", async () => {
	const ran: string[] = [];
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(ranApp(ran), ["build"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["built"]);
		assert.equal(r.exitCode, 0);
	} finally {
		setConfirmIO(null);
	}
});

// `yes` owns no framework flag any more.
test("confirm: --yes is no longer a recognized token", async () => {
	const r = await ranApp([]).test(["build", "--yes"]);
	assert.equal(r.exitCode, 1);
	assert.ok(r.stderr.includes("--yes"), r.stderr);
});

test("confirm: a read_only command cannot be declared consequential", () => {
	assert.throws(
		() =>
			defineReadOnlyCommand("look", {
				help: "h",
				consequential: true,
				handler: () => 0,
			}),
		(e: Error) =>
			e.message ===
			'command "look": a read_only command cannot be consequential (a command that changes nothing has nothing to confirm)',
	);
	assert.throws(
		() =>
			readOnlyPassthrough("show", {
				help: "h",
				consequential: true,
				handler: () => 0,
			}),
		(e: Error) => e.message.includes("cannot be consequential"),
	);
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

test("confirm: a CONSEQUENTIAL passthrough is not exempt", async () => {
	const ran: string[] = [];
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		mutatingPassthrough("exec", {
			help: "h",
			consequential: true,
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
			"about to run consequential command 'exec'. Proceed? [y/N] aborted\n",
		);
		assert.deepEqual(ran, []);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: a mutating passthrough that is not consequential never prompts", async () => {
	const ran: string[] = [];
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		mutatingPassthrough("thru", {
			help: "h",
			handler: () => {
				ran.push("ran");
				return 0;
			},
		}),
	);
	setConfirmIO(io("n", /* interactive */ false));
	try {
		const r = await captureRun(app, ["thru", "--anything"]);
		assert.equal(r.stderr, "");
		assert.deepEqual(ran, ["ran"]);
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
		defineMutatingCommand("run", {
			help: "h",
			consequential: true,
			handler: () => 0,
		}),
	);
	setConfirmIO(io("n"));
	try {
		const r = await captureRun(app, ["release", "run"]);
		assert.ok(
			r.stderr.startsWith(
				"about to run consequential command 'release.run'. Proceed? [y/N] ",
			),
			r.stderr,
		);
	} finally {
		setConfirmIO(null);
	}
});

test("confirm: the programmatic paths behave as if --approve-consequential were passed", async () => {
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

test("confirm: ctx.approveConsequential reflects the actual flag, not the dispatch path", async () => {
	const seen: boolean[] = [];
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineMutatingCommand("deploy", {
			help: "h",
			consequential: true,
			handler: (_a, ctx) => {
				seen.push(ctx.approveConsequential);
				return 0;
			},
		}),
	);
	// Prompt suppression is a property of the dispatch path; the flag value is
	// reported honestly.
	await app.test(["deploy"]);
	await app.test(["--approve-consequential", "deploy"]);
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
