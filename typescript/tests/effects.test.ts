/**
 * The ctx.effects handle: the eight methods, the would-do log, Unsettled
 * carriers and the runtime seal, grants, observes, and the call-time
 * enforcement the contract pins.
 *
 * Byte-level expectations mirror the Python reference implementation
 * (python/strictcli/__init__.py and python/tests/test_effects.py).
 */

import { strict as assert } from "node:assert";
import {
	existsSync,
	mkdtempSync,
	readFileSync,
	statSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { AppImpl } from "../src/app.js";
import {
	type App,
	type AppSpec,
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
	type MutatingContext,
	type ReadOnlyContext,
} from "../src/index.js";

const HEADER = "DRY RUN — no changes were made. Would do:\n";

function tmp(): string {
	return mkdtempSync(join(tmpdir(), "sc-effects-"));
}

/** An app with one mutating command whose handler is the test body. */
function mutApp(
	handler: (ctx: MutatingContext) => number | undefined,
	spec: Partial<AppSpec> = {},
): App {
	const app = createApp({
		name: "t",
		version: "1.0.0",
		help: "h",
		...spec,
	});
	app.command(
		defineMutatingCommand("go", {
			help: "do the thing",
			handler: (_a, ctx) => handler(ctx),
		}),
	);
	return app;
}

/** An app with one read_only command whose handler is the test body. */
function roApp(
	handler: (ctx: ReadOnlyContext) => number | undefined,
	spec: Partial<AppSpec> = {},
): App {
	const app = createApp({ name: "t", version: "1.0.0", help: "h", ...spec });
	app.command(
		defineReadOnlyCommand("look", {
			help: "look at the thing",
			handler: (_a, ctx) => handler(ctx),
		}),
	);
	return app;
}

function log(app: App): Record<string, unknown>[] {
	return (app as unknown as AppImpl).effectLog();
}

// --- The would-do log format (§3.2) ---

test("effects: every verb renders its pinned detail", async () => {
	const app = mutApp((ctx) => {
		ctx.effects.run(["git", "tag", "v1"]);
		ctx.effects.spawn(["notify", "-x"]);
		ctx.effects.write("VERSION", "1.2.3");
		ctx.effects.mkdir("build");
		ctx.effects.remove("stale");
		ctx.effects.rename("a", "b");
		ctx.effects.chmod("run.sh", 0o755);
		ctx.effects.http("POST", "https://example.test/x");
		return 0;
	});
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(
		r.stdout,
		`${HEADER}` +
			"  1. run: git tag v1\n" +
			"  2. spawn: notify -x\n" +
			"  3. write: VERSION (5 bytes)\n" +
			"  4. mkdir: build\n" +
			"  5. remove: stale\n" +
			"  6. rename: a -> b\n" +
			"  7. chmod: run.sh 0755\n" +
			"  8. net: POST https://example.test/x\n",
	);
});

test("effects: the grant suffix precedes the conditional suffix", async () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineMutatingCommand("go", {
			help: "h",
			grants: [
				{ name: "push", reason: "engine owns refs", kind: "proc_mutate" },
			],
			handler: (_a, ctx) => {
				ctx.effects.run(["git", "push"], {
					grant: "push",
					skipIfCurrent: "remote:origin",
				});
				return 0;
			},
		}),
	);
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(
		r.stdout,
		`${HEADER}  1. run: git push (granted: push — engine owns refs)` +
			" [unless resource 'remote:origin' already current]\n",
	);
});

test("effects: --quiet never suppresses the would-do log", async () => {
	const app = mutApp((ctx) => {
		ctx.info("chatty");
		ctx.effects.mkdir("d");
		return 0;
	});
	const r = await app.test(["--quiet", "--dry-run", "go"]);
	assert.ok(!r.stdout.includes("chatty"));
	assert.equal(r.stdout, `${HEADER}  1. mkdir: d\n`);
});

// --- Carriers: forwarding, extraction, the seal ---

test("effects: a forwarded carrier renders its brand inline", async () => {
	const app = mutApp((ctx) => {
		const built = ctx.effects.run(["make"]);
		ctx.effects.run(["upload", built]);
		ctx.effects.write("out", built);
		return 0;
	});
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(
		r.stdout,
		`${HEADER}` +
			"  1. run: make\n" +
			"  2. run: upload «step 1 output»\n" +
			"  3. write: out («step 1 output»)\n",
	);
});

test("effects: forwarding does not consume the carrier", async () => {
	const app = mutApp((ctx) => {
		const built = ctx.effects.run(["make"]);
		ctx.effects.run(["a", built]);
		ctx.effects.run(["b", built]);
		return 0;
	});
	const r = await app.test(["--dry-run", "go"]);
	assert.ok(r.stdout.includes("  2. run: a «step 1 output»\n"));
	assert.ok(r.stdout.includes("  3. run: b «step 1 output»\n"));
});

test("effects: reading a member of a carrier truncates", async () => {
	const app = mutApp((ctx) => {
		const built = ctx.effects.run(["make"]);
		ctx.info(built.stdout);
		return 0;
	});
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stdout, `${HEADER}  1. run: make\n`);
	assert.equal(
		r.stderr,
		"error: dry-run preview ends at step 2: go branched on unsettled value " +
			"«step 1 output» — cannot preview past this point\n",
	);
});

test("effects: a handler that SWALLOWS the truncation still fails closed", async () => {
	const app = mutApp((ctx) => {
		const built = ctx.effects.run(["make"]);
		try {
			// The TS ceiling Python does not have: DryRunTruncated is an ordinary
			// Error here, so `catch` can see it. The dispatch site consults the
			// log's truncation record after the handler returns.
			ctx.info(built.stdout);
		} catch {
			// deliberately swallowed
		}
		return 0;
	});
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /dry-run preview ends at step 2/);
});

test("effects: the Proxy's three exemptions do not detonate", async () => {
	const seen: string[] = [];
	const app = mutApp((ctx) => {
		const built = ctx.effects.run(["make"]) as unknown as object;
		// Symbol.toStringTag and the Node inspect symbol are exempt.
		seen.push(Object.prototype.toString.call(built));
		const inspect = (built as Record<symbol, unknown>)[
			Symbol.for("nodejs.util.inspect.custom")
		] as () => string;
		seen.push(inspect());
		return 0;
	});
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(r.exitCode, 0);
	assert.deepEqual(seen, ["[object Unsettled]", "Unsettled(«step 1 output»)"]);
});

test("effects: toString and valueOf are NOT exempt", async () => {
	for (const member of ["toString", "valueOf"]) {
		const app = mutApp((ctx) => {
			const built = ctx.effects.run(["make"]) as unknown as Record<
				string,
				unknown
			>;
			void built[member];
			return 0;
		});
		const r = await app.test(["--dry-run", "go"]);
		assert.equal(r.exitCode, 1, member);
		assert.match(r.stderr, /cannot preview past this point/);
	}
});

// --- Void results are never forwardable (§2.5.5) ---

test("effects: forwarding a void result is a call-time error in dry mode", async () => {
	const app = mutApp((ctx) => {
		const nothing = ctx.effects.mkdir("d") as unknown as string;
		ctx.effects.run(["use", nothing]);
		return 0;
	});
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message:
			"command \"go\": effects.run parameter 'argv[1]' does not accept an unsettled value",
	});
});

test("effects: forwarding a Spawned is a call-time error", async () => {
	const app = mutApp((ctx) => {
		const child = ctx.effects.spawn(["sleep", "0"]);
		ctx.effects.run(["use", child as unknown as string]);
		return 0;
	});
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message:
			"command \"go\": effects.run parameter 'argv[1]' does not accept an unsettled value",
	});
});

test("effects: a carrier in an EXCLUDED parameter is rejected", async () => {
	const cases: [string, (ctx: MutatingContext, c: unknown) => void][] = [
		["cwd", (ctx, c) => ctx.effects.run(["x"], { cwd: c as string })],
		["env", (ctx, c) => ctx.effects.run(["x"], { env: { K: c as string } })],
		["resource", (ctx, c) => ctx.effects.mkdir("d", { resource: c as string })],
		[
			"headers",
			(ctx, c) =>
				ctx.effects.http("GET", "https://x.test", {
					headers: { A: c as string },
				}),
		],
		["method", (ctx, c) => ctx.effects.http(c as string, "https://x.test")],
	];
	for (const [param, body] of cases) {
		const app = mutApp((ctx) => {
			const built = ctx.effects.run(["make"]);
			body(ctx, built);
			return 0;
		});
		await assert.rejects(
			app.test(["--dry-run", "go"]),
			(e: Error) =>
				e.message.includes(`parameter '${param}' does not accept`) ||
				e.message.includes("does not accept an unsettled value"),
			param,
		);
	}
});

// --- Inapplicable options are a call-time hard error (§2.5.2) ---

test("effects: an option a method does not accept is a call-time error", async () => {
	const app = mutApp((ctx) => {
		(ctx.effects.mkdir as unknown as (p: string, o: object) => void)("d", {
			stream: true,
		});
		return 0;
	});
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message: "command \"go\": effects.mkdir does not accept option 'stream'",
	});
});

test("effects: the option name is reported in canonical snake_case", async () => {
	const app = mutApp((ctx) => {
		(ctx.effects.http as unknown as (m: string, u: string, o: object) => void)(
			"GET",
			"https://x.test",
			{ stream: true },
		);
		return 0;
	});
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message: "command \"go\": effects.http does not accept option 'stream'",
	});
});

test("effects: Spawned.wait accepts check and nothing else", async () => {
	const app = mutApp((ctx) => {
		const child = ctx.effects.spawn([process.execPath, "-e", ""]);
		(child.wait as unknown as (o: object) => void)({ cwd: "/tmp" });
		return 0;
	});
	await assert.rejects(app.test(["go"]), {
		message: "command \"go\": effects.spawn does not accept option 'cwd'",
	});
});

// --- Read-only enforcement (§9.1) ---

test("effects: every mutating member is refused in a read_only command", async () => {
	const bodies: [string, (ctx: ReadOnlyContext) => void][] = [
		["write", (c) => (c as unknown as MutatingContext).effects.write("p", "x")],
		["mkdir", (c) => (c as unknown as MutatingContext).effects.mkdir("p")],
		["remove", (c) => (c as unknown as MutatingContext).effects.remove("p")],
		[
			"rename",
			(c) => (c as unknown as MutatingContext).effects.rename("a", "b"),
		],
		[
			"chmod",
			(c) => (c as unknown as MutatingContext).effects.chmod("p", 0o644),
		],
		[
			"http",
			(c) =>
				(c as unknown as MutatingContext).effects.http("GET", "https://x.test"),
		],
		["spawn", (c) => (c as unknown as MutatingContext).effects.spawn(["x"])],
	];
	for (const [method, body] of bodies) {
		const app = roApp((ctx) => {
			body(ctx);
			return 0;
		});
		await assert.rejects(app.test(["look"]), {
			message: `command "look" is classified read_only; effects.${method} is a mutating operation`,
		});
	}
});

test("effects: a non-allowlisted run is refused in a read_only command", async () => {
	const app = roApp((ctx) => {
		ctx.effects.run(["rm", "-rf", "/"]);
		return 0;
	});
	await assert.rejects(app.test(["look"]), {
		message:
			'command "look" is classified read_only; effects.run argv rm -rf / is not on the app\'s proc_observe_allowlist',
	});
});

// --- Observes (§6.2) ---

test("effects: an allowlisted observe executes and is never logged", async () => {
	const app = mutApp(
		(ctx) => {
			const head = ctx.effects.run([
				process.execPath,
				"-e",
				"process.stdout.write('abc\\n')",
			]);
			ctx.info(`head=${head.stdout}`);
			ctx.effects.mkdir("d");
			return 0;
		},
		{ procObserveAllowlist: [[process.execPath, "-e"]] },
	);
	const r = await app.test(["--dry-run", "go"]);
	assert.ok(r.stdout.startsWith("head=abc\n"));
	assert.equal(r.stdout.slice("head=abc\n".length), `${HEADER}  1. mkdir: d\n`);
	assert.equal(log(app).length, 1);
});

test("effects: a POST-mutation observe yields a stale carrier", async () => {
	const app = mutApp(
		(ctx) => {
			ctx.effects.mkdir("d");
			const stale = ctx.effects.run([process.execPath, "-e", "0"]);
			ctx.info(stale.stdout);
			return 0;
		},
		{ procObserveAllowlist: [[process.execPath, "-e"]] },
	);
	const r = await app.test(["--dry-run", "go"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		"error: dry-run preview ends at step 2: go branched on unsettled value " +
			`«stale: ${process.execPath} -e 0» — cannot preview past this point\n`,
	);
});

test("effects: allowlist matching is element-wise prefix equality only", async () => {
	const app = roApp(
		(ctx) => {
			// A prefix of the allowlisted prefix does not match.
			ctx.effects.run([process.execPath]);
			return 0;
		},
		{ procObserveAllowlist: [[process.execPath, "-e"]] },
	);
	await assert.rejects(
		app.test(["look"]),
		/is not on the app's proc_observe_allowlist/,
	);
});

test("effects: a grant on an observe is a call-time error", async () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		procObserveAllowlist: [["git", "status"]],
	});
	app.command(
		defineMutatingCommand("go", {
			help: "h",
			grants: [{ name: "peek", reason: "why not", kind: "proc_mutate" }],
			handler: (_a, ctx) => {
				ctx.effects.run(["git", "status"], { grant: "peek" });
				return 0;
			},
		}),
	);
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message:
			"command \"go\": grant 'peek' cannot be used on an observe (an allowlisted effects.run changes nothing)",
	});
});

// --- Grants (§6.1) ---

test("effects: an undeclared grant is a call-time error", async () => {
	const app = mutApp((ctx) => {
		ctx.effects.mkdir("d", { grant: "nope" });
		return 0;
	});
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message: "command \"go\": grant 'nope' is not declared on this command",
	});
});

test("effects: a grant used for the wrong kind is a call-time error", async () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineMutatingCommand("go", {
			help: "h",
			grants: [{ name: "push", reason: "refs", kind: "proc_mutate" }],
			handler: (_a, ctx) => {
				ctx.effects.mkdir("d", { grant: "push" });
				return 0;
			},
		}),
	);
	await assert.rejects(app.test(["--dry-run", "go"]), {
		message:
			"command \"go\": grant 'push' is declared for kind proc_mutate but was used for a file_write effect",
	});
});

// --- Conditional annotations are preview-only (§5.2) ---

test("effects: skipIfCurrent is inert in real mode", async () => {
	const dir = tmp();
	const app = mutApp((ctx) => {
		ctx.effects.mkdir(join(dir, "made"), {
			resource: "dir:made",
			skipIfCurrent: "dir:made",
		});
		return 0;
	});
	const r = await app.test(["go"]);
	assert.equal(r.exitCode, 0);
	// The declaration did not skip anything: the effect executed.
	assert.ok(existsSync(join(dir, "made")));
	assert.deepEqual(log(app), [
		{
			seq: 1,
			kind: "file_write",
			verb: "mkdir",
			detail: join(dir, "made"),
			recorded: false,
			resource: "dir:made",
			skip_if_current: "dir:made",
		},
	]);
});

// --- Live mode really performs, and the log records it ---

test("effects: live mode performs the five path effects", async () => {
	const dir = tmp();
	const app = mutApp((ctx) => {
		ctx.effects.mkdir(join(dir, "sub"));
		ctx.effects.write(join(dir, "sub", "a.txt"), "hello");
		ctx.effects.rename(join(dir, "sub", "a.txt"), join(dir, "sub", "b.txt"));
		ctx.effects.chmod(join(dir, "sub", "b.txt"), 0o600);
		ctx.effects.remove(join(dir, "sub", "missing"));
		return 0;
	});
	const r = await app.test(["go"]);
	assert.equal(r.exitCode, 0);
	assert.equal(readFileSync(join(dir, "sub", "b.txt"), "utf8"), "hello");
	assert.equal(statSync(join(dir, "sub", "b.txt")).mode & 0o777, 0o600);
	// A live run populates the structured log too, with recorded: false.
	assert.equal(log(app).length, 5);
	for (const rec of log(app)) {
		assert.equal(rec.recorded, false);
	}
	// The would-do log is dry mode's output and does not exist in live mode.
	assert.equal(r.stdout, "");
});

test("effects: remove is recursive and tolerates a missing path", async () => {
	const dir = tmp();
	writeFileSync(join(dir, "f"), "x");
	const app = mutApp((ctx) => {
		ctx.effects.mkdir(join(dir, "tree", "deep"));
		ctx.effects.remove(join(dir, "tree"));
		ctx.effects.remove(join(dir, "never-existed"));
		return 0;
	});
	assert.equal((await app.test(["go"])).exitCode, 0);
	assert.ok(!existsSync(join(dir, "tree")));
});

test("effects: run captures utf-8 output with one trailing newline removed", async () => {
	let captured = "";
	const app = mutApp((ctx) => {
		const r = ctx.effects.run([
			process.execPath,
			"-e",
			"process.stdout.write('line\\n')",
		]);
		captured = r.stdout;
		return 0;
	});
	await app.test(["go"]);
	assert.equal(captured, "line");
});

test("effects: a nonzero exit is an error, and check:false opts out", async () => {
	const failing = [process.execPath, "-e", "process.exit(3)"];
	const app = mutApp((ctx) => {
		ctx.effects.run(failing);
		return 0;
	});
	await assert.rejects(app.test(["go"]), {
		name: "EffectFailed",
		message: `command "go": effects.run failed: ${failing.join(" ")} exited 3`,
	});

	let code = -1;
	const opted = mutApp((ctx) => {
		code = ctx.effects.run(failing, { check: false }).exitCode;
		return 0;
	});
	assert.equal((await opted.test(["go"])).exitCode, 0);
	assert.equal(code, 3);
});

test("effects: env merges OVER the inherited environment", async () => {
	let out = "";
	const app = mutApp((ctx) => {
		out = ctx.effects.run(
			[
				process.execPath,
				"-e",
				"process.stdout.write(String(process.env.PATH !== undefined) + ':' + process.env.SC_EXTRA)",
			],
			{ env: { SC_EXTRA: "yes" } },
		).stdout;
		return 0;
	});
	await app.test(["go"]);
	assert.equal(out, "true:yes");
});

test("effects: invalid UTF-8 on a captured stream fails the call", async () => {
	const app = mutApp((ctx) => {
		ctx.effects.run([
			process.execPath,
			"-e",
			"process.stdout.write(Buffer.from([0xff, 0xfe]))",
		]);
		return 0;
	});
	await assert.rejects(app.test(["go"]), {
		name: "EffectFailed",
		message:
			'command "go": effects.run produced output that is not valid UTF-8',
	});
});

test("effects: spawn starts a real child and wait carries its exit code", async () => {
	let pid = 0;
	let code = -1;
	const app = mutApp((ctx) => {
		const child = ctx.effects.spawn([
			process.execPath,
			"-e",
			"process.exit(7)",
		]);
		pid = child.pid;
		code = child.wait({ check: false }).exitCode;
		return 0;
	});
	assert.equal((await app.test(["go"])).exitCode, 0);
	assert.ok(pid > 0);
	assert.equal(code, 7);
});

test("effects: Spawned.wait defaults to check:true", async () => {
	const app = mutApp((ctx) => {
		ctx.effects.spawn([process.execPath, "-e", "process.exit(2)"]).wait();
		return 0;
	});
	await assert.rejects(app.test(["go"]), {
		name: "EffectFailed",
		message: /effects\.spawn failed: .* exited 2/,
	});
});

// --- The seal is armed at every dispatch site (§15) ---

test("effects: ctx.effects is armed on the run() path", async () => {
	const app = mutApp((ctx) => {
		ctx.effects.mkdir("d");
		return 0;
	});
	// run() writes to the real process streams; --dry-run keeps it hermetic.
	await app.run(["--dry-run", "--yes", "go"]);
	assert.equal(process.exitCode, 0);
	process.exitCode = 0;
	assert.equal(log(app).length, 1);
});

test("effects: ctx.effects is armed on the call() path", async () => {
	const dir = tmp();
	const app = mutApp((ctx) => {
		ctx.effects.mkdir(join(dir, "viaCall"));
		return 0;
	});
	await app.call("go");
	assert.ok(existsSync(join(dir, "viaCall")));
	assert.equal(log(app).length, 1);
});

test("effects: ctx.effects is armed on the passthrough call() path", async () => {
	const dir = tmp();
	const app = createApp({ name: "t", version: "1", help: "h" });
	const { mutatingPassthrough } = await import("../src/index.js");
	app.command(
		mutatingPassthrough("exec", {
			help: "h",
			handler: (_a, ctx) => {
				ctx.effects.mkdir(join(dir, "viaPassthrough"));
				return 0;
			},
		}),
	);
	await app.call("exec", { _args: [] });
	assert.ok(existsSync(join(dir, "viaPassthrough")));
	assert.equal(log(app).length, 1);
});

test("effects: a Context built outside a dispatch has no effects handle", async () => {
	const { Context } = await import("../src/index.js");
	const ctx = new Context({ write: () => {} }, { write: () => {} }, {}, null);
	assert.throws(() => ctx.effects, {
		message:
			"ctx.effects is unavailable: this Context was constructed outside a command dispatch",
	});
});

// --- --dry-run is not reachable programmatically (§8.4) ---

test("effects: call() runs live -- --dry-run is not reachable there", async () => {
	const dir = tmp();
	const app = mutApp((ctx) => {
		assert.equal(ctx.dryRun, false);
		ctx.effects.write(join(dir, "live.txt"), "x");
		return 0;
	});
	await app.call("go");
	assert.equal(readFileSync(join(dir, "live.txt"), "utf8"), "x");
});

// --- The reserved quartet on the Context (§7.2, §7.4) ---

test("effects: the quartet reaches the Context and never the handler args", async () => {
	let seen: Record<string, unknown> = {};
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("look", {
			help: "h",
			handler: (args, ctx) => {
				seen = {
					args: Object.keys(args as object),
					dryRun: ctx.dryRun,
					yes: ctx.yes,
					quiet: ctx.quiet,
					verbose: ctx.verbose,
				};
				return 0;
			},
		}),
	);
	await app.test(["--dry-run", "--yes", "--quiet", "--verbose", "look"]);
	assert.deepEqual(seen, {
		args: [],
		dryRun: true,
		yes: true,
		quiet: true,
		verbose: true,
	});
});

test("effects: --quiet dominates --verbose in the gating table", async () => {
	const rows: [string[], string[]][] = [
		[[], ["i", "w", "e"]],
		[["--verbose"], ["i", "d", "w", "e"]],
		[["--quiet"], ["w", "e"]],
		[
			["--quiet", "--verbose"],
			["w", "e"],
		],
	];
	for (const [flags, expected] of rows) {
		const app = roApp((ctx) => {
			ctx.info("i");
			ctx.debug("d");
			ctx.warn("w");
			ctx.error("e");
			return 0;
		});
		const r = await app.test([...flags, "look"]);
		const seen = `${r.stdout}${r.stderr}`.split("\n").filter((s) => s !== "");
		assert.deepEqual(seen, expected, flags.join(" "));
	}
});

// --- Framework-blessed CACHE_WRITEs (§9.2) ---

test("effects: a coverage shard is a CACHE_WRITE that executes even in dry mode", async () => {
	const dir = tmp();
	const cwd = process.cwd();
	process.chdir(dir);
	try {
		const app = createApp({
			name: "t",
			version: "1",
			help: "h",
			testCoverage: true,
		});
		app.command(defineReadOnlyCommand("look", { help: "h", handler: () => 0 }));
		const r = await app.test(["--dry-run", "look"]);
		const records = log(app);
		assert.equal(records.length, 1);
		assert.equal(records[0]?.kind, "cache_write");
		assert.equal(records[0]?.verb, "cache");
		// It EXECUTED (recorded: false) even though the run was a dry run...
		assert.equal(records[0]?.recorded, false);
		assert.ok(existsSync(String(records[0]?.detail)));
		// ...and it is never written to the would-do log.
		assert.equal(r.stdout, HEADER);
	} finally {
		process.chdir(cwd);
	}
});

test("effects: a CACHE_WRITE never trips read-only enforcement", async () => {
	const dir = tmp();
	const cwd = process.cwd();
	process.chdir(dir);
	try {
		const app = createApp({
			name: "t",
			version: "1",
			help: "h",
			testCoverage: true,
		});
		app.command(defineReadOnlyCommand("look", { help: "h", handler: () => 0 }));
		// A read_only command whose dispatch writes a coverage shard: no error.
		assert.equal((await app.test(["look"])).exitCode, 0);
	} finally {
		process.chdir(cwd);
	}
});
