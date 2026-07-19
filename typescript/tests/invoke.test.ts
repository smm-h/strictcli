/**
 * app.call() tests: programmatic invocation semantics, InvokeError messages,
 * and passthrough _args handling. Mirrors go/strictcli/invoke_test.go and
 * python/tests/test_call.py / test_invoke.py (Python is the divergence
 * ground truth for return values: a bare void return yields undefined).
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	arg,
	coRequired,
	createApp,
	defineCommand,
	flag,
	InvokeError,
	implies,
	mutexGroup,
	outcome,
	passthrough,
	t,
} from "../src/index.js";

function buildApp() {
	return createApp({ name: "myapp", version: "1.0.0", help: "test app" });
}

// --- Return-value semantics ---

test("call: handler returning an integer yields that integer", async () => {
	const app = buildApp();
	app.command(defineCommand("run", { help: "run", handler: () => 42 }));
	assert.equal(await app.call("run"), 42);
});

test("call: handler returning nothing yields undefined (Python None)", async () => {
	const app = buildApp();
	app.command(defineCommand("run", { help: "run", handler: () => undefined }));
	assert.equal(await app.call("run"), undefined);
});

test("call: outcome data is returned as-is", async () => {
	const app = buildApp();
	app.command(
		defineCommand("status", {
			help: "get status",
			handler: () => outcome(0, { healthy: true, uptime: 3600n }),
		}),
	);
	assert.deepEqual(await app.call("status"), { healthy: true, uptime: 3600n });
});

test("call: data-less outcome yields its exit code", async () => {
	const app = buildApp();
	app.command(defineCommand("run", { help: "run", handler: () => outcome(3) }));
	assert.equal(await app.call("run"), 3);
});

// --- Kwargs, defaults, and provenance ---

test("call: pre-typed flag values reach the handler; defaults fill gaps", async () => {
	const app = buildApp();
	let captured: { name: string; count: bigint } | undefined;
	app.command(
		defineCommand("greet", {
			help: "say hello",
			flags: {
				name: flag("name", t.str, { help: "who to greet" }),
				count: flag("count", t.int, { help: "times", default: 2n }),
			},
			handler: (args) => {
				captured = { name: args.name, count: args.count };
				return 0;
			},
		}),
	);
	assert.equal(await app.call("greet", { name: "world" }), 0);
	assert.deepEqual(captured, { name: "world", count: 2n });
});

test("call: dashed flag names use underscored kwargs keys", async () => {
	const app = buildApp();
	let seen: boolean | undefined;
	app.command(
		defineCommand("deploy", {
			help: "deploy",
			flags: {
				dry_run: flag("dry-run", t.bool, { help: "dry run", default: false }),
			},
			handler: (args) => {
				seen = args.dry_run;
				return 0;
			},
		}),
	);
	await app.call("deploy", { dry_run: true });
	assert.equal(seen, true);
});

test("call: provided kwargs report source cli; defaults report default", async () => {
	const app = buildApp();
	const sources: Record<string, string> = {};
	app.command(
		defineCommand("greet", {
			help: "say hello",
			flags: {
				name: flag("name", t.str, { help: "who" }),
				count: flag("count", t.int, { help: "times", default: 1n }),
			},
			handler: (_args, ctx) => {
				sources.name = ctx.source("name");
				sources.count = ctx.source("count");
				return 0;
			},
		}),
	);
	await app.call("greet", { name: "x" });
	assert.deepEqual(sources, { name: "cli", count: "default" });
});

test("call: global flags accept kwargs and fall back to defaults", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			verbose: flag("verbose", t.bool, { help: "verbose", default: false }),
			region: flag("region", t.str, { help: "region", default: "eu" }),
		},
	});
	let captured: Record<string, unknown> | undefined;
	app.command(
		defineCommand("run", {
			help: "run",
			handler: (args) => {
				captured = args as Record<string, unknown>;
				return 0;
			},
		}),
	);
	await app.call("run", { verbose: true });
	assert.equal(captured?.verbose, true);
	assert.equal(captured?.region, "eu");
});

test("call: dict flag accepts a Map or a plain object (converted to Map)", async () => {
	const app = buildApp();
	let seen: Map<string, string> | undefined;
	app.command(
		defineCommand("tag", {
			help: "tag",
			flags: {
				labels: flag("labels", t.dict(t.str), {
					help: "labels",
				}),
			},
			handler: (args) => {
				seen = args.labels;
				return 0;
			},
		}),
	);
	await app.call("tag", { labels: { a: "1", b: "2" } });
	assert.deepEqual(
		seen,
		new Map([
			["a", "1"],
			["b", "2"],
		]),
	);
	await app.call("tag", { labels: new Map([["k", "v"]]) });
	assert.deepEqual(seen, new Map([["k", "v"]]));
});

test("call: dict flag rejects non-map values with the Go-templated message", async () => {
	const app = buildApp();
	app.command(
		defineCommand("tag", {
			help: "tag",
			flags: {
				labels: flag("labels", t.dict(t.str), { help: "labels" }),
			},
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("tag", { labels: ["not", "a", "map"] }), {
		name: "InvokeError",
		message: 'dict flag "labels": expected map type, got Array',
	});
});

// --- Positional args ---

test("call: positional args are passed by declared name", async () => {
	const app = buildApp();
	let seen: string | undefined;
	app.command(
		defineCommand("deploy", {
			help: "deploy",
			args: [arg("target", t.str, { help: "target" })],
			handler: (args) => {
				seen = args.target;
				return 0;
			},
		}),
	);
	await app.call("deploy", { target: "prod" });
	assert.equal(seen, "prod");
});

test("call: variadic args take an array and re-coerce elements", async () => {
	const app = buildApp();
	let seen: readonly bigint[] | undefined;
	app.command(
		defineCommand("sum", {
			help: "sum",
			args: [arg("nums", t.int, { help: "numbers", variadic: true })],
			handler: (args) => {
				seen = args.nums;
				return 0;
			},
		}),
	);
	await app.call("sum", { nums: [1n, 2n, 3n] });
	assert.deepEqual(seen, [1n, 2n, 3n]);
});

test("call: missing required positional arg raises InvokeError", async () => {
	const app = buildApp();
	app.command(
		defineCommand("deploy", {
			help: "deploy",
			args: [arg("target", t.str, { help: "target" })],
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("deploy"), {
		name: "InvokeError",
		message: "missing required argument 'target'",
	});
});

// --- Error cases ---

test("call: unknown command raises InvokeError", async () => {
	const app = buildApp();
	app.command(defineCommand("greet", { help: "hi", handler: () => 0 }));
	await assert.rejects(app.call("nonexistent"), {
		name: "InvokeError",
		message: "unknown command 'nonexistent'",
	});
});

test("call: group path raises InvokeError (Python message)", async () => {
	const app = buildApp();
	const db = app.group("db", { help: "database commands" });
	db.command(defineCommand("migrate", { help: "migrate", handler: () => 0 }));
	await assert.rejects(app.call("db"), {
		name: "InvokeError",
		message: "'db' is a group, not a command",
	});
});

test("call: unknown parameter raises InvokeError with the command path", async () => {
	const app = buildApp();
	app.command(
		defineCommand("greet", {
			help: "hi",
			flags: { name: flag("name", t.str, { help: "who" }) },
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("greet", { name: "x", bogus: "y" }), {
		name: "InvokeError",
		message: 'unknown parameter "bogus" for command "greet"',
	});
});

test("call: missing required flag raises InvokeError", async () => {
	const app = buildApp();
	app.command(
		defineCommand("greet", {
			help: "hi",
			flags: { name: flag("name", t.str, { help: "who" }) },
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("greet"), {
		name: "InvokeError",
		message: "flag '--name' is required",
	});
});

test("call: mutex violations raise InvokeError", async () => {
	const build = () => {
		const app = buildApp();
		app.command(
			defineCommand("fetch", {
				help: "fetch",
				mutex: [
					mutexGroup({
						url: flag("url", t.str, { help: "url" }),
						file: flag("file", t.str, { help: "file" }),
					}),
				],
				handler: () => 0,
			}),
		);
		return app;
	};
	await assert.rejects(build().call("fetch", { url: "u", file: "f" }), {
		name: "InvokeError",
		message: "--url and --file are mutually exclusive",
	});
	await assert.rejects(build().call("fetch"), {
		name: "InvokeError",
		message: "one of --url, --file is required",
	});
});

test("call: dependency violations raise InvokeError", async () => {
	const app = buildApp();
	app.command(
		defineCommand("sync", {
			help: "sync",
			flags: {
				user: flag("user", t.str, { help: "user", default: null }),
				pass: flag("pass", t.str, { help: "pass", default: null }),
			},
			dependencies: [coRequired(["user", "pass"])],
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("sync", { user: "alice" }), {
		name: "InvokeError",
		message: "flags --user, --pass must be used together",
	});
});

test("call: implies dependency injects the implied value", async () => {
	const app = buildApp();
	let seen: { watch?: boolean; follow?: boolean } = {};
	app.command(
		defineCommand("logs", {
			help: "logs",
			flags: {
				watch: flag("watch", t.bool, { help: "watch", default: false }),
				follow: flag("follow", t.bool, { help: "follow", default: false }),
			},
			dependencies: [
				implies({ flag: "watch", implies: "follow", value: true }),
			],
			handler: (args, ctx) => {
				seen = { watch: args.watch, follow: args.follow };
				assert.equal(ctx.source("follow"), "implied");
				return 0;
			},
		}),
	);
	await app.call("logs", { watch: true });
	assert.deepEqual(seen, { watch: true, follow: true });
});

test("call: choices are validated on pre-typed values", async () => {
	const app = buildApp();
	app.command(
		defineCommand("paint", {
			help: "paint",
			flags: {
				color: flag("color", t.str, {
					help: "color",
					choices: ["red", "blue"],
				}),
			},
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("paint", { color: "green" }), InvokeError);
});

test("call: InvokeError is a distinct public Error subclass", () => {
	const e = new InvokeError("boom");
	assert.ok(e instanceof Error);
	assert.equal(e.name, "InvokeError");
	assert.equal(e.message, "boom");
});

// --- Nested groups ---

test("call: dot-separated paths resolve nested group commands", async () => {
	const app = buildApp();
	const dns = app.group("dns", { help: "dns" });
	const zone = dns.group("zone", { help: "zones" });
	zone.command(
		defineCommand("create", {
			help: "create zone",
			flags: { name: flag("name", t.str, { help: "zone name" }) },
			handler: (args) => outcome(0, { created: args.name }),
		}),
	);
	assert.deepEqual(await app.call("dns.zone.create", { name: "example.org" }), {
		created: "example.org",
	});
});

// --- Passthrough ---

test("call: passthrough forwards _args, name, and global values", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			verbose: flag("verbose", t.bool, { help: "verbose", default: false }),
		},
	});
	let captured:
		| {
				name: string;
				args: readonly string[];
				globals: Record<string, unknown>;
		  }
		| undefined;
	app.command(
		passthrough("exec", {
			help: "execute command",
			handler: (pa) => {
				captured = {
					name: pa.name,
					args: pa.args,
					globals: { ...pa.globals },
				};
				return 0;
			},
		}),
	);
	assert.equal(
		await app.call("exec", { _args: ["ls", "-la", "/tmp"], verbose: true }),
		0,
	);
	assert.deepEqual(captured, {
		name: "exec",
		args: ["ls", "-la", "/tmp"],
		globals: { verbose: true },
	});
});

test("call: passthrough omitted _args defaults to an empty list", async () => {
	const app = buildApp();
	let seen: readonly string[] | undefined;
	app.command(
		passthrough("exec", {
			help: "execute command",
			handler: (pa) => {
				seen = pa.args;
				return 0;
			},
		}),
	);
	await app.call("exec");
	assert.deepEqual(seen, []);
});

test("call: passthrough _args must be a string array", async () => {
	const app = buildApp();
	app.command(
		passthrough("exec", { help: "execute command", handler: () => 0 }),
	);
	await assert.rejects(app.call("exec", { _args: [1, 2] }), {
		name: "InvokeError",
		message: "passthrough command: _args must be []string",
	});
	await assert.rejects(app.call("exec", { _args: "ls" }), {
		name: "InvokeError",
		message: "passthrough command: _args must be []string",
	});
});

test("call: passthrough rejects unknown kwargs", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			verbose: flag("verbose", t.bool, { help: "verbose", default: false }),
		},
	});
	app.command(
		passthrough("exec", { help: "execute command", handler: () => 0 }),
	);
	await assert.rejects(
		app.call("exec", { _args: ["ls"], verbose: true, bogus_flag: "x" }),
		{
			name: "InvokeError",
			message: 'unknown parameter "bogus_flag" for passthrough command "exec"',
		},
	);
});

test("call: passthrough missing required global flag raises InvokeError", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			token: flag("token", t.str, { help: "auth token" }),
			verbose: flag("verbose", t.bool, { help: "verbose", default: false }),
		},
	});
	app.command(
		passthrough("exec", { help: "execute command", handler: () => 0 }),
	);
	await assert.rejects(app.call("exec", { _args: ["ls"], verbose: true }), {
		name: "InvokeError",
		message: "global flag '--token' is required",
	});
});

test("call: passthrough missing required bool global names both forms", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			force_run: flag("force-run", t.bool, { help: "force operation" }),
		},
	});
	app.command(
		passthrough("exec", { help: "execute command", handler: () => 0 }),
	);
	await assert.rejects(app.call("exec", { _args: ["ls"] }), {
		name: "InvokeError",
		message:
			"global flag '--force-run' must be passed as --force-run or --no-force-run",
	});
});

// --- Handler exceptions propagate unchanged ---

test("call: handler exceptions propagate (not wrapped in InvokeError)", async () => {
	const app = buildApp();
	app.command(
		defineCommand("fail", {
			help: "always fails",
			handler: () => {
				throw new RangeError("something broke");
			},
		}),
	);
	await assert.rejects(app.call("fail"), RangeError);
});
