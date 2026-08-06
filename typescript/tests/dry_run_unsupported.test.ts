/**
 * The `dryRunSupported: false` command declaration.
 *
 * Covers the three registration-time guards (read_only prohibition, mandatory
 * reason, orphan reason), the parse-time refusal on both the app.test() and the
 * real app.run() argv path, `--help` precedence over the refusal, the `Dry run:`
 * help section, and the emit-when-declared schema pair.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	type App,
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
	mutatingPassthrough,
	readOnlyPassthrough,
} from "../src/index.js";

const REASON =
	"the engine re-reads what its earlier steps wrote, so a preview lies";

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

function fixture(): App {
	const app = createApp({ name: "app", version: "1.0.0", help: "app" });
	app.command(
		defineMutatingCommand("run", {
			help: "run the release",
			dryRunSupported: false,
			dryRunUnsupportedReason: REASON,
			handler: (_args, ctx) => {
				ctx.info("ran");
				return 0;
			},
		}),
	);
	app.command(
		defineMutatingCommand("plan", {
			help: "plan the release",
			handler: (_args, ctx) => {
				ctx.info("planned");
				return 0;
			},
		}),
	);
	const rel = app.group("rel", { help: "release group" });
	rel.command(
		defineMutatingCommand("run", {
			help: "run the release",
			dryRunSupported: false,
			dryRunUnsupportedReason: REASON,
			handler: () => 0,
		}),
	);
	app.command(
		mutatingPassthrough("wrap", {
			help: "forward to a child",
			dryRunSupported: false,
			dryRunUnsupportedReason: REASON,
			handler: (_args, ctx) => {
				ctx.info("wrapped");
				return 0;
			},
		}),
	);
	return app;
}

// --- registration validation ---

test("dry-run: declaring it false on a read_only command is a hard error", () => {
	assert.throws(
		() =>
			defineReadOnlyCommand("show", {
				help: "h",
				dryRunSupported: false,
				dryRunUnsupportedReason: REASON,
				handler: () => 0,
			}),
		{
			name: "RegistrationError",
			message:
				'command "show": a read_only command cannot declare dry_run_supported=false (a command that changes nothing has no effects a preview could misrepresent)',
		},
	);
});

test("dry-run: the read_only prohibition covers passthrough carriers", () => {
	assert.throws(
		() =>
			readOnlyPassthrough("show", {
				help: "h",
				dryRunSupported: false,
				dryRunUnsupportedReason: REASON,
				handler: () => 0,
			}),
		{ name: "RegistrationError" },
	);
});

test("dry-run: the reason is mandatory and non-empty", () => {
	for (const reason of [undefined, "", "   "]) {
		assert.throws(
			() =>
				defineMutatingCommand("run", {
					help: "h",
					dryRunSupported: false,
					...(reason === undefined ? {} : { dryRunUnsupportedReason: reason }),
					handler: () => 0,
				}),
			{
				name: "RegistrationError",
				message:
					'command "run": dry_run_supported=false requires a non-empty dry_run_unsupported_reason (say what a preview cannot honestly show)',
			},
		);
	}
});

test("dry-run: a reason without the declaration is a hard error", () => {
	assert.throws(
		() =>
			defineMutatingCommand("run", {
				help: "h",
				dryRunUnsupportedReason: REASON,
				handler: () => 0,
			}),
		{
			name: "RegistrationError",
			message:
				'command "run": dry_run_unsupported_reason requires dry_run_supported=false (there is nothing to explain while dry run is supported)',
		},
	);
});

test("dry-run: support is the undeclared baseline", () => {
	const def = defineMutatingCommand("plan", { help: "h", handler: () => 0 });
	assert.equal(def.dryRunSupported, true);
	assert.equal(def.dryRunUnsupportedReason, undefined);
	const refusing = defineMutatingCommand("run", {
		help: "h",
		dryRunSupported: false,
		dryRunUnsupportedReason: REASON,
		handler: () => 0,
	});
	assert.equal(refusing.dryRunSupported, false);
	assert.equal(refusing.dryRunUnsupportedReason, REASON);
});

// --- parse-time refusal (app.test() path) ---

test("dry-run: the refusal fires from either flag position", async () => {
	for (const argv of [
		["--dry-run", "run"],
		["run", "--dry-run"],
	]) {
		const r = await fixture().test(argv);
		assert.equal(r.exitCode, 1);
		assert.equal(
			r.stderr,
			`error: --dry-run is not supported by command 'run': ${REASON}\ntry 'app --help'\n`,
		);
		assert.equal(r.stdout, "");
	}
});

test("dry-run: the refusal names the dotted path inside a group", async () => {
	const r = await fixture().test(["rel", "run", "--dry-run"]);
	assert.equal(r.exitCode, 1);
	assert.ok(
		r.stderr.includes(
			`error: --dry-run is not supported by command 'rel.run': ${REASON}`,
		),
		r.stderr,
	);
});

test("dry-run: the refusal applies to a passthrough command", async () => {
	// Pre-command position only: after a passthrough command's name the quartet
	// belongs to the child process and is never scanned.
	const r = await fixture().test(["--dry-run", "wrap"]);
	assert.equal(r.exitCode, 1);
	assert.ok(
		r.stderr.includes("--dry-run is not supported by command 'wrap'"),
		r.stderr,
	);
});

test("dry-run: the passthrough asymmetry leaves a trailing flag to the child", async () => {
	const r = await fixture().test(["wrap", "--dry-run"]);
	assert.equal(r.exitCode, 0);
	assert.ok(r.stdout.includes("wrapped"), r.stdout);
});

test("dry-run: a bare -- terminates the scan", async () => {
	// After `--` the token is positional data, not the quartet: the command
	// takes no positionals, so it fails as an unexpected argument rather than as
	// a dry-run refusal.
	const r = await fixture().test(["run", "--", "--dry-run"]);
	assert.ok(
		r.stderr.startsWith("error: unexpected argument '--dry-run'"),
		r.stderr,
	);
	assert.ok(!r.stderr.includes("is not supported by command"), r.stderr);
});

test("dry-run: a supporting command still previews", async () => {
	const r = await fixture().test(["plan", "--dry-run"]);
	assert.equal(r.exitCode, 0);
	assert.ok(r.stdout.includes("planned"), r.stdout);
});

test("dry-run: without the flag the refusing command runs", async () => {
	const r = await fixture().test(["run"]);
	assert.equal(r.exitCode, 0);
	assert.ok(r.stdout.includes("ran"), r.stdout);
});

// --- parse-time refusal (real app.run() path) ---

test("dry-run: the refusal fires on the real argv path", async () => {
	const r = await captureRun(fixture(), ["run", "--dry-run"]);
	assert.equal(r.exitCode, 1);
	assert.ok(
		r.stderr.includes(
			`error: --dry-run is not supported by command 'run': ${REASON}`,
		),
		r.stderr,
	);
	assert.ok(!r.stdout.includes("ran"), r.stdout);
});

// --- --help precedence ---

test("dry-run: --help beats the refusal", async () => {
	for (const argv of [
		["run", "--dry-run", "--help"],
		["run", "--help", "--dry-run"],
		["--dry-run", "run", "-h"],
	]) {
		const r = await fixture().test(argv);
		assert.equal(r.exitCode, 0);
		assert.ok(r.stdout.startsWith("app run -- run the release"), r.stdout);
		assert.ok(!r.stderr.includes("is not supported by command"), r.stderr);
	}
});

// --- help rendering ---

test("dry-run: the help section is byte-exact", async () => {
	const r = await fixture().test(["run", "--help"]);
	assert.equal(
		r.stdout,
		`app run -- run the release\n\nDry run:\n  --dry-run is not supported: ${REASON}\n`,
	);
});

test("dry-run: the help section renders for a passthrough command", async () => {
	const r = await fixture().test(["wrap", "--help"]);
	assert.equal(
		r.stdout,
		`app wrap -- forward to a child\n\nDry run:\n  --dry-run is not supported: ${REASON}\n`,
	);
});

test("dry-run: no help section on a supporting command", async () => {
	const r = await fixture().test(["plan", "--help"]);
	assert.ok(!r.stdout.includes("Dry run:"), r.stdout);
});

// --- schema emission ---

test("dry-run: the schema pair is emitted only when declared", () => {
	const commands = fixture().dumpSchemaDict().commands as Record<
		string,
		Record<string, unknown>
	>;
	assert.equal(commands.run?.dry_run_supported, false);
	assert.equal(commands.run?.dry_run_unsupported_reason, REASON);
	assert.ok(!("dry_run_supported" in (commands.plan ?? {})));
	assert.ok(!("dry_run_unsupported_reason" in (commands.plan ?? {})));
});
