/**
 * app.call() tests: programmatic invocation semantics, InvokeError messages,
 * and passthrough _args handling. Mirrors go/strictcli/invoke_test.go and
 * python/tests/test_call.py / test_invoke.py (Python is the divergence
 * ground truth for return values: a bare void return yields undefined).
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	allOrNone,
	arg,
	choice,
	createApp,
	defineReadOnlyCommand,
	flag,
	InvokeError,
	implies,
	memberChoiceFlag,
	outcome,
	readOnlyPassthrough,
	t,
} from "../src/index.js";

function buildApp() {
	return createApp({ name: "myapp", version: "1.0.0", help: "test app" });
}

// --- Return-value semantics ---

test("call: handler returning an integer yields that integer", async () => {
	const app = buildApp();
	app.command(defineReadOnlyCommand("run", { help: "run", handler: () => 42 }));
	assert.equal(await app.call("run"), 42);
});

test("call: handler returning nothing yields undefined (Python None)", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("run", { help: "run", handler: () => undefined }),
	);
	assert.equal(await app.call("run"), undefined);
});

test("call: outcome data is returned as-is", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("status", {
			payloadSchema: {},
			help: "get status",
			handler: (_args, ctx) => {
				ctx.payload({ healthy: true, uptime: 3600n });
				return outcome(0);
			},
		}),
	);
	assert.deepEqual(await app.call("status"), { healthy: true, uptime: 3600n });
});

test("call: data-less outcome yields its exit code", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("run", { help: "run", handler: () => outcome(3) }),
	);
	assert.equal(await app.call("run"), 3);
});

// --- Kwargs, defaults, and provenance ---

test("call: pre-typed flag values reach the handler; defaults fill gaps", async () => {
	const app = buildApp();
	let captured: { name: string; count: bigint } | undefined;
	app.command(
		defineReadOnlyCommand("greet", {
			help: "say hello",
			flags: {
				name: flag("name", t.str, {
					help: "who to greet",
					presence: "required",
				}),
				count: flag("count", t.int, {
					help: "times",
					presence: "default",
					default: 2n,
				}),
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
		defineReadOnlyCommand("deploy", {
			help: "deploy",
			flags: {
				sim_run: flag("sim-run", t.bool, {
					help: "dry run",
					presence: "default",
					default: false,
				}),
			},
			handler: (args) => {
				seen = args.sim_run;
				return 0;
			},
		}),
	);
	await app.call("deploy", { sim_run: true });
	assert.equal(seen, true);
});

test("call: provided kwargs report source cli; defaults report default", async () => {
	const app = buildApp();
	const sources: Record<string, string> = {};
	app.command(
		defineReadOnlyCommand("greet", {
			help: "say hello",
			flags: {
				name: flag("name", t.str, { help: "who", presence: "required" }),
				count: flag("count", t.int, {
					help: "times",
					presence: "default",
					default: 1n,
				}),
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
			chatter: flag("chatter", t.bool, {
				help: "chatter",
				presence: "default",
				default: false,
			}),
			region: flag("region", t.str, {
				help: "region",
				presence: "default",
				default: "eu",
			}),
		},
	});
	let captured: Record<string, unknown> | undefined;
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			handler: (args) => {
				captured = args as Record<string, unknown>;
				return 0;
			},
		}),
	);
	await app.call("run", { chatter: true });
	assert.equal(captured?.chatter, true);
	assert.equal(captured?.region, "eu");
});

test("call: dict flag accepts a Map or a plain object (converted to Map)", async () => {
	const app = buildApp();
	let seen: Map<string, string> | undefined;
	app.command(
		defineReadOnlyCommand("tag", {
			help: "tag",
			flags: {
				labels: flag("labels", t.dict(t.str), {
					help: "labels",
					presence: "default",
					default: new Map(),
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
		defineReadOnlyCommand("tag", {
			help: "tag",
			flags: {
				labels: flag("labels", t.dict(t.str), {
					help: "labels",
					presence: "default",
					default: new Map(),
				}),
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
		defineReadOnlyCommand("deploy", {
			help: "deploy",
			args: [arg("target", t.str, { help: "target", presence: "required" })],
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
		defineReadOnlyCommand("sum", {
			help: "sum",
			args: [
				arg("nums", t.int, {
					help: "numbers",
					variadic: true,
					presence: "required",
				}),
			],
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
		defineReadOnlyCommand("deploy", {
			help: "deploy",
			args: [arg("target", t.str, { help: "target", presence: "required" })],
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("deploy"), {
		name: "InvokeError",
		message: "missing required argument 'target'",
	});
});

test("call: an omitted optional arg arrives as a present key holding absence", async () => {
	// The presence declaration reaches the programmatic path too (§23.3): the
	// key is delivered, holding undefined, rather than being omitted.
	const app = buildApp();
	let seen: Record<string, unknown> | undefined;
	app.command(
		defineReadOnlyCommand("copy", {
			help: "copy",
			args: [
				arg("src", t.str, { help: "source", presence: "required" }),
				arg("dest", t.str, { help: "destination", presence: "optional" }),
			],
			flags: {
				mode: flag("mode", t.str, { help: "mode", presence: "optional" }),
				tag: flag("tag", t.list(t.str), { help: "tags", presence: "optional" }),
			},
			handler: (args) => {
				seen = args as Record<string, unknown>;
				return 0;
			},
		}),
	);
	await app.call("copy", { src: "a" });
	assert.ok(seen);
	assert.ok("dest" in seen);
	assert.equal(seen.dest, undefined);
	assert.equal(seen.mode, undefined);
	// Not the empty list the framework used to invent for a compound flag.
	assert.equal(seen.tag, undefined);
});

// --- Error cases ---

test("call: unknown command raises InvokeError", async () => {
	const app = buildApp();
	app.command(defineReadOnlyCommand("greet", { help: "hi", handler: () => 0 }));
	await assert.rejects(app.call("nonexistent"), {
		name: "InvokeError",
		message: "unknown command 'nonexistent'",
	});
});

test("call: group path raises InvokeError (Python message)", async () => {
	const app = buildApp();
	const db = app.group("db", { help: "database commands" });
	db.command(
		defineReadOnlyCommand("migrate", { help: "migrate", handler: () => 0 }),
	);
	await assert.rejects(app.call("db"), {
		name: "InvokeError",
		message: "'db' is a group, not a command",
	});
});

test("call: unknown parameter raises InvokeError with the command path", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("greet", {
			help: "hi",
			flags: {
				name: flag("name", t.str, { help: "who", presence: "required" }),
			},
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
		defineReadOnlyCommand("greet", {
			help: "hi",
			flags: {
				name: flag("name", t.str, { help: "who", presence: "required" }),
			},
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("greet"), {
		name: "InvokeError",
		message: "flag '--name' is required",
	});
});

test("call: a bad elected record raises InvokeError", async () => {
	const build = () => {
		const app = buildApp();
		app.command(
			defineReadOnlyCommand("fetch", {
				help: "fetch",
				flags: {
					source: memberChoiceFlag(
						"source",
						{
							url: choice({
								help: "url",
								value: { carrier: t.str, help: "the URL to read" },
							}),
							file: choice({
								help: "file",
								value: { carrier: t.str, help: "path to the file" },
							}),
						},
						{ help: "where to read from", presence: "required" },
					),
				},
				handler: () => 0,
			}),
		);
		return app;
	};
	// call() takes the ELECTED RECORD, pre-typed (§24.11): there is no flat
	// combination to be wrong about, so what a bad call gets wrong is the
	// record itself.
	await assert.rejects(build().call("fetch", { source: { choice: "both" } }), {
		name: "InvokeError",
		message: "--source: invalid value 'both', must be one of: url, file",
	});
	await assert.rejects(build().call("fetch"), {
		name: "InvokeError",
		message: "one of --url, --file is required",
	});
	// A member flag is elected by its own token and that token CARRIES the
	// payload, so a record electing one with no `value` is `--url` typed with
	// nothing after it -- and takes that sentence, never a presence refusal
	// naming the member as its own owner (§24.11).
	await assert.rejects(build().call("fetch", { source: { choice: "url" } }), {
		name: "InvokeError",
		message: "flag '--url' requires a value",
	});
	assert.equal(
		await build().call("fetch", { source: { choice: "url", value: "u" } }),
		0,
	);
});

test("call: a selector with no kwarg elects from its declaration", async () => {
	// The programmatic path takes the elected record; a selector nobody named
	// elects its declared default, or refuses exactly as the argv path does.
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				scope: memberChoiceFlag(
					"scope",
					{
						profile: choice({
							help: "a profile",
							value: { carrier: t.str, help: "profile name" },
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "which profiles", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("run", {}), {
		name: "InvokeError",
		message: "one of --profile, --all-profiles is required",
	});
	assert.equal(await app.call("run", { scope: { choice: "all-profiles" } }), 0);
});

test("call: dependency violations raise InvokeError", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("sync", {
			help: "sync",
			flags: {
				user: flag("user", t.str, { help: "user", presence: "optional" }),
				pass: flag("pass", t.str, { help: "pass", presence: "optional" }),
			},
			constraints: [
				allOrNone({
					name: "creds",
					members: [{ name: "user" }, { name: "pass" }],
				}),
			],
			handler: () => 0,
		}),
	);
	await assert.rejects(app.call("sync", { user: "alice" }), {
		name: "InvokeError",
		message: 'constraint "creds": --user, --pass must be used together',
	});
});

test("call: implies dependency injects the implied value", async () => {
	const app = buildApp();
	let seen: { watch?: boolean; follow?: boolean } = {};
	app.command(
		defineReadOnlyCommand("logs", {
			help: "logs",
			flags: {
				watch: flag("watch", t.bool, {
					help: "watch",
					presence: "default",
					default: false,
				}),
				follow: flag("follow", t.bool, {
					help: "follow",
					presence: "default",
					default: false,
				}),
			},
			constraints: [
				implies({
					name: "watch-follow",
					flag: "watch",
					implies: "follow",
					value: true,
				}),
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
		defineReadOnlyCommand("paint", {
			help: "paint",
			flags: {
				color: flag("color", t.str, {
					help: "color",
					choices: [{ value: "red" }, { value: "blue" }],
					presence: "required",
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
		defineReadOnlyCommand("create", {
			payloadSchema: {},
			help: "create zone",
			flags: {
				name: flag("name", t.str, { help: "zone name", presence: "required" }),
			},
			handler: (args, ctx) => {
				ctx.payload({ created: args.name });
				return outcome(0);
			},
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
			chatter: flag("chatter", t.bool, {
				help: "chatter",
				presence: "default",
				default: false,
			}),
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
		readOnlyPassthrough("exec", {
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
		await app.call("exec", { _args: ["ls", "-la", "/tmp"], chatter: true }),
		0,
	);
	assert.deepEqual(captured, {
		name: "exec",
		args: ["ls", "-la", "/tmp"],
		globals: { chatter: true },
	});
});

test("call: passthrough omitted _args defaults to an empty list", async () => {
	const app = buildApp();
	let seen: readonly string[] | undefined;
	app.command(
		readOnlyPassthrough("exec", {
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
		readOnlyPassthrough("exec", { help: "execute command", handler: () => 0 }),
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
			chatter: flag("chatter", t.bool, {
				help: "chatter",
				presence: "default",
				default: false,
			}),
		},
	});
	app.command(
		readOnlyPassthrough("exec", { help: "execute command", handler: () => 0 }),
	);
	await assert.rejects(
		app.call("exec", { _args: ["ls"], chatter: true, bogus_flag: "x" }),
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
			token: flag("token", t.str, { help: "auth token", presence: "required" }),
			chatter: flag("chatter", t.bool, {
				help: "chatter",
				presence: "default",
				default: false,
			}),
		},
	});
	app.command(
		readOnlyPassthrough("exec", { help: "execute command", handler: () => 0 }),
	);
	await assert.rejects(app.call("exec", { _args: ["ls"], chatter: true }), {
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
			force_run: flag("force-run", t.bool, {
				help: "force operation",
				presence: "required",
			}),
		},
	});
	app.command(
		readOnlyPassthrough("exec", { help: "execute command", handler: () => 0 }),
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
		defineReadOnlyCommand("fail", {
			help: "always fails",
			handler: () => {
				throw new RangeError("something broke");
			},
		}),
	);
	await assert.rejects(app.call("fail"), RangeError);
});

// --- Pre-typed values are checked against the declaration (§24.11, §23.4) ---

/**
 * "Pre-typed" means ALREADY OF THE DECLARED TYPE, never exempt from the
 * declaration. This door parses nothing, but the declaration still says what
 * the value may be -- and it is the same question a config document poses, so
 * it takes the same check and the same sentences.
 */
function typedApp(captured?: Record<string, unknown>) {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			trace_id: flag("trace-id", t.str, { help: "id", presence: "optional" }),
		},
	});
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			flags: {
				name: flag("name", t.str, { help: "a name", presence: "optional" }),
				count: flag("count", t.int, { help: "a count", presence: "optional" }),
				weight: flag("weight", t.float, {
					help: "a weight",
					presence: "optional",
				}),
				tags: flag("tags", t.list(t.str), {
					help: "tags",
					presence: "default",
					default: [],
				}),
				labels: flag("labels", t.dict(t.str), {
					help: "labels",
					presence: "default",
					default: new Map(),
				}),
			},
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, {
						name: args.name,
						count: args.count,
						weight: args.weight,
						tags: args.tags,
						labels: args.labels,
					});
				}
				return 0;
			},
		}),
	);
	return app;
}

async function refusal(kwargs: Record<string, unknown>): Promise<string> {
	try {
		await typedApp().call("run", kwargs);
	} catch (e) {
		return (e as Error).message;
	}
	throw new Error("expected a refusal");
}

test("call: a wrong-typed pre-typed value is refused, never delivered", async () => {
	assert.equal(await refusal({ name: 7n }), "--name: expected string, got int");
	assert.equal(
		await refusal({ count: "7" }),
		"--count: expected integer, got str",
	);
	assert.equal(
		await refusal({ count: 1.5 }),
		"--count: expected integer, got float",
	);
	assert.equal(
		await refusal({ weight: "1.5" }),
		"--weight: expected float, got str",
	);
	// A compound is checked entry by entry, exactly as a config document is.
	assert.equal(
		await refusal({ tags: ["a", 2n] }),
		"--tags: element 1: expected str, got int",
	);
	assert.equal(
		await refusal({ labels: { a: "1", b: 2n } }),
		"--labels: key 'b': expected str, got int",
	);
	// The dict flag's own SHAPE refusal is unchanged.
	assert.equal(
		await refusal({ labels: ["not", "a", "map"] }),
		'dict flag "labels": expected map type, got Array',
	);
	// An app-level global is a declaration like any other.
	assert.equal(
		await refusal({ trace_id: 7n }),
		"--trace-id: expected string, got int",
	);
});

test("call: null is a legal value for nothing, whatever the presence", async () => {
	// Optionality has ONE spelling: an optional flag is delivered absent when
	// its key is absent, so a null says nothing the declaration cannot say --
	// and on a required flag it would answer the presence rule with a value the
	// declaration forbids (§23.4).
	assert.equal(
		await refusal({ name: null }),
		"--name: expected string, got null",
	);
	assert.equal(
		await refusal({ count: null }),
		"--count: expected integer, got null",
	);
	assert.equal(
		await refusal({ name: undefined }),
		"--name: expected string, got null",
	);
});

test("call: an unknown parameter is refused before any value problem", async () => {
	// Shape before phase, at the record front door too (§24.11): a key naming
	// nothing the command declares outranks a wrong-typed value beside it,
	// whichever key the caller wrote first.
	assert.equal(
		await refusal({ name: null, nope: 1 }),
		'unknown parameter "nope" for command "run"',
	);
	assert.equal(
		await refusal({ nope: 1, name: null }),
		'unknown parameter "nope" for command "run"',
	);
});

test("call: an integer supplied as a JSON number arrives as the declared int", async () => {
	// JSON has no bigint. The value is converted INTO the declared type, which
	// is what makes the handler's parameter type true of what it holds.
	const captured: Record<string, unknown> = {};
	await typedApp(captured).call("run", { count: 3, weight: 2, name: "x" });
	assert.equal(captured.count, 3n);
	assert.equal(captured.weight, 2);
	assert.equal(captured.name, "x");
});
