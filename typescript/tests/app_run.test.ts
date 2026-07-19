/**
 * run()/test() dispatch tests: the execution surface completed in this
 * subphase (async handlers, result interpretation, data emission, capture
 * mechanics, tag-contract enforcement). Byte expectations follow the Python
 * implementation (the divergence ground truth); e2e.test.ts pins the
 * conformance scenarios.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { Context } from "../src/context.js";
import {
	createApp,
	defineCommand,
	flag,
	outcome,
	passthrough,
	t,
} from "../src/index.js";

test("test: result surface is stdout/stderr/exitCode with optional data", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			handler: (_args, ctx) => {
				ctx.info("out-line");
				ctx.warn("err-line");
				return 3;
			},
		}),
	);
	const r = await app.test(["run"]);
	assert.deepEqual(r, {
		stdout: "out-line\n",
		stderr: "err-line\n",
		exitCode: 3,
	});
	assert.equal("data" in r, false);
});

test("test: captures console.log output from handlers", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			handler: () => {
				console.log("via console");
				return 0;
			},
		}),
	);
	const r = await app.test(["run"]);
	assert.equal(r.stdout, "via console\n");
});

test("test: async handlers are awaited", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			handler: async (_args, ctx) => {
				await new Promise((resolve) => setTimeout(resolve, 5));
				ctx.info("after-await");
				return outcome(2, { done: true });
			},
		}),
	);
	const r = await app.test(["run"]);
	assert.equal(r.stdout, 'after-await\n{"done":true}\n');
	assert.equal(r.exitCode, 2);
	assert.deepEqual(r.data, { done: true });
});

test("test: outcome data prints one compact JSON line with BigInt tokens", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			flags: { count: flag("count", t.int, { help: "count", default: 7n }) },
			handler: (args) => outcome(0, { count: args.count, name: "x" }),
		}),
	);
	const r = await app.test(["run", "--count", "9007199254740993"]);
	assert.equal(r.stdout, '{"count":9007199254740993,"name":"x"}\n');
	assert.deepEqual(r.data, { count: 9007199254740993n, name: "x" });
});

test("test: bad handler returns are hard errors (propagate to the caller)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			handler: () => ["not-an-outcome"] as never,
		}),
	);
	// Python's test() lets the TypeError propagate (only SystemExit is
	// caught); the TS surface matches. Also covers "a returned Promise
	// resolving to a bad value" -- run/test await before interpreting.
	await assert.rejects(() => app.test(["run"]), {
		name: "TypeError",
		message:
			"command handler must return number (exit code), undefined (exit 0), or strictcli.outcome(...); got Array",
	});
	const asyncBad = createApp({ name: "myapp", version: "1.0.0", help: "h" });
	asyncBad.command(
		defineCommand("run", {
			help: "run",
			handler: async () => "nope" as never,
		}),
	);
	await assert.rejects(() => asyncBad.test(["run"]), {
		name: "TypeError",
		message:
			"command handler must return number (exit code), undefined (exit 0), or strictcli.outcome(...); got string",
	});
	// The console patches must be restored after the throw.
	const probe = await app.test(["--version"]);
	assert.equal(probe.stdout, "myapp 1.0.0\n");
});

test("test: passthrough handlers flow through the result contract", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		passthrough("exec", {
			help: "exec",
			handler: (pt, ctx: Context) => {
				ctx.info(`${pt.name}:${pt.args.join(",")}`);
				return outcome(4, { forwarded: pt.args.length });
			},
		}),
	);
	const r = await app.test(["exec", "-x", "y"]);
	assert.equal(r.stdout, 'exec:-x,y\n{"forwarded":2}\n');
	assert.equal(r.exitCode, 4);
	assert.deepEqual(r.data, { forwarded: 2 });
});

test("test: ctx.source works during dispatch", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			flags: {
				dry_run: flag("dry-run", t.bool, { help: "dry", default: true }),
			},
			handler: (_args, ctx) => {
				ctx.info(`cli=${ctx.source("dry-run")}`);
				return 0;
			},
		}),
	);
	assert.equal((await app.test(["run", "--dry-run"])).stdout, "cli=cli\n");
	assert.equal((await app.test(["run"])).stdout, "cli=default\n");
});

test("test: --mcp reports the Python in-process message", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(defineCommand("run", { help: "run", handler: () => 0 }));
	const r = await app.test(["--mcp"]);
	assert.equal(r.stderr, "error: --mcp requires interactive stdin/stdout\n");
	assert.equal(r.exitCode, 1);
});

test("test: tag-contract violations abort dispatch with error", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("greet", { help: "greet", tags: ["json"], handler: () => 0 }),
	);
	app.tagContract("json", "json");
	const r = await app.test(["greet"]);
	// Pinned by conformance command_tags.json ("tag contract violated").
	assert.equal(
		r.stderr,
		'error: command "greet": tag "json" requires flag "--json"\n',
	);
	assert.equal(r.exitCode, 1);
});

test("test: tag contracts satisfied by command or global flags pass", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			json: flag("json", t.bool, { help: "json output", default: false }),
		},
	});
	app.command(
		defineCommand("greet", {
			help: "greet",
			tags: ["json"],
			handler: (_args, ctx) => {
				ctx.info("hello");
				return 0;
			},
		}),
	);
	app.tagContract("json", "json");
	const r = await app.test(["greet"]);
	assert.equal(r.stdout, "hello\n");
	assert.equal(r.exitCode, 0);
});

test("test: tag contracts are enforced recursively; passthrough exempt", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	const grp = app.group("tools", { help: "tools" });
	grp.command(
		defineCommand("lint", { help: "lint", tags: ["json"], handler: () => 0 }),
	);
	app.tagContract("json", "json");
	const r = await app.test(["tools", "lint"]);
	assert.equal(
		r.stderr,
		'error: command "lint": tag "json" requires flag "--json"\n',
	);
	assert.equal(r.exitCode, 1);

	const ptApp = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
	});
	ptApp.command(
		passthrough("raw", { help: "raw", tags: ["json"], handler: () => 0 }),
	);
	ptApp.tagContract("json", "json");
	assert.equal((await ptApp.test(["raw"])).exitCode, 0);
});

test("run: writes to process streams and sets process.exitCode", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("run", {
			help: "run",
			handler: (_args, ctx) => {
				ctx.info("hello-from-run");
				return outcome(5, { via: "run" });
			},
		}),
	);
	// Capture the real process streams the same way test() does, to observe
	// what run() writes without spawning a child process.
	const chunks: string[] = [];
	const orig = process.stdout.write.bind(process.stdout);
	const origExitCode = process.exitCode;
	process.stdout.write = ((chunk: string | Uint8Array): boolean => {
		chunks.push(
			typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk),
		);
		return true;
	}) as typeof process.stdout.write;
	try {
		await app.run(["run"]);
	} finally {
		process.stdout.write = orig;
	}
	assert.equal(chunks.join(""), 'hello-from-run\n{"via":"run"}\n');
	assert.equal(process.exitCode, 5);
	process.exitCode = origExitCode;
});

test("run: defaults argv to process.argv.slice(2)", async () => {
	const app = createApp({ name: "myapp", version: "9.9.9", help: "test app" });
	app.command(defineCommand("run", { help: "run", handler: () => 0 }));
	const origArgv = process.argv;
	const chunks: string[] = [];
	const orig = process.stdout.write.bind(process.stdout);
	const origExitCode = process.exitCode;
	process.argv = [origArgv[0] as string, "myapp", "--version"];
	process.stdout.write = ((chunk: string | Uint8Array): boolean => {
		chunks.push(
			typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk),
		);
		return true;
	}) as typeof process.stdout.write;
	try {
		await app.run();
	} finally {
		process.stdout.write = orig;
		process.argv = origArgv;
	}
	assert.equal(chunks.join(""), "myapp 9.9.9\n");
	assert.equal(process.exitCode, 0);
	process.exitCode = origExitCode;
});
