/**
 * Machine mode: the reserved --json flag and the payload API.
 *
 * Contract §19.1 (the flag and its delivery), §19.4 (the payload API) and
 * §7.1's 2026-08-13 amendment (the unconditional every-level name ban).
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	arg,
	createApp,
	defineReadOnlyCommand,
	flag,
	flagSet,
	mutexGroup,
	outcome,
	t,
} from "../src/index.js";

const RESERVED = /flag name 'json' is reserved by the framework/;

// --- the name ban: unconditional, at every level ---------------------------

test("json is reserved on a command flag", () => {
	assert.throws(
		() => flag("json", t.bool, { help: "h", default: false }),
		RESERVED,
	);
});

test("json is reserved on a flag-set flag", () => {
	assert.throws(
		() => flagSet("s", { json: flag("json", t.bool, { help: "h" }) }),
		RESERVED,
	);
});

test("json is reserved on a mutex-group flag", () => {
	assert.throws(
		() =>
			mutexGroup({
				json: flag("json", t.bool, { help: "h", default: false }),
				text: flag("text", t.bool, { help: "h", default: false }),
			}),
		RESERVED,
	);
});

test("json is reserved on an app global flag", () => {
	assert.throws(
		() =>
			createApp({
				name: "a",
				version: "1",
				help: "h",
				flags: { json: flag("json", t.bool, { help: "h", default: false }) },
			}),
		RESERVED,
	);
});

test("an arg named json is unaffected", () => {
	// The ban covers the flag surface only: an arg has no `--` spelling.
	assert.doesNotThrow(() => arg("json", t.str, { help: "a file named json" }));
});

// --- delivery: both argv regions, stripped, on the Context -----------------

function machineFlagApp() {
	const app = createApp({ name: "a", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			payloadSchema: {},
			handler: (_args, ctx) => {
				ctx.payload({ json: ctx.json });
				return outcome(0);
			},
		}),
	);
	return app;
}

test("--json is absent by default and the payload is not printed", async () => {
	const r = await machineFlagApp().test(["run"]);
	assert.equal(r.stdout, "");
	assert.deepEqual(r.data, { json: false });
});

test("--json is recognized before the command word", async () => {
	const r = await machineFlagApp().test(["--json", "run"]);
	assert.equal(r.stdout, '{"json":true}\n');
});

test("--json is recognized after the command word", async () => {
	const r = await machineFlagApp().test(["run", "--json"]);
	assert.equal(r.stdout, '{"json":true}\n');
});

test("--json never reaches the handler as a kwarg", async () => {
	const app = createApp({ name: "a", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			handler: (args) => {
				assert.equal(Object.hasOwn(args as object, "json"), false);
				return 0;
			},
		}),
	);
	assert.equal((await app.test(["run", "--json"])).exitCode, 0);
});

// --- the payload API -------------------------------------------------------

test("ctx.payload without a declared schema is a hard error", async () => {
	const app = createApp({ name: "a", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			handler: (_args, ctx) => {
				ctx.payload({ k: 1 });
				return outcome(0);
			},
		}),
	);
	await assert.rejects(() => app.test(["run"]), {
		message: 'command "run": ctx.payload requires a declared payload schema',
	});
});

test("ctx.payload twice in one dispatch is a hard error", async () => {
	const app = createApp({ name: "a", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			payloadSchema: {},
			handler: (_args, ctx) => {
				ctx.payload({ k: 1 });
				ctx.payload({ k: 2 });
				return outcome(0);
			},
		}),
	);
	await assert.rejects(() => app.test(["run"]), {
		message:
			'command "run": ctx.payload was already called (a dispatch carries at most one payload)',
	});
});

test("call() returns the payload the handler supplied", async () => {
	const app = createApp({ name: "a", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			payloadSchema: {},
			handler: (_args, ctx) => {
				ctx.payload(["a", "b"]);
				return outcome(0);
			},
		}),
	);
	assert.deepEqual(await app.call("run"), ["a", "b"]);
});

test("--quiet cannot reach the payload", async () => {
	const r = await machineFlagApp().test(["--quiet", "--json", "run"]);
	assert.equal(r.stdout, '{"json":true}\n');
});

test("payload escaping is plain UTF-8", async () => {
	const app = createApp({ name: "a", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run",
			payloadSchema: {},
			handler: (_args, ctx) => {
				ctx.payload({ text: "héllo <b>&</b> 日本語" });
				return outcome(0);
			},
		}),
	);
	const r = await app.test(["run", "--json"]);
	assert.equal(r.stdout, '{"text":"héllo <b>&</b> 日本語"}\n');
});
