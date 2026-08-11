/**
 * MCP server tests: serveMcp(), the --mcp reserved flag, and the JSON-RPC
 * 2.0 protocol surface. Mirrors python/tests/test_mcp.py's pinned set
 * exactly (dotted tool names, Go-canon error strings: "Parse error",
 * "Method not found: <m>", the three -32602 parameter messages).
 */

import { strict as assert } from "node:assert";
import { Readable } from "node:stream";
import { test } from "node:test";
import type { App } from "../src/app.js";
import {
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
	flag,
	outcome,
	t,
} from "../src/index.js";

function buildApp(spec: Record<string, unknown> = {}): App {
	return createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		...spec,
	});
}

/** Serves raw input text and returns the parsed response lines. */
async function serveRaw(
	app: App,
	text: string,
): Promise<Record<string, unknown>[]> {
	const chunks: string[] = [];
	await app.serveMcp({
		input: Readable.from(text),
		output: { write: (s) => chunks.push(s) },
	});
	return chunks
		.join("")
		.split("\n")
		.filter((line) => line.trim() !== "")
		.map((line) => JSON.parse(line) as Record<string, unknown>);
}

/** Sends JSON-RPC requests and returns the parsed responses. */
async function sendRequests(
	app: App,
	...requests: unknown[]
): Promise<Record<string, unknown>[]> {
	const text = `${requests.map((r) => JSON.stringify(r)).join("\n")}\n`;
	return serveRaw(app, text);
}

/** Sends one request and asserts exactly one response came back. */
async function sendOne(
	app: App,
	request: unknown,
): Promise<Record<string, unknown>> {
	const responses = await sendRequests(app, request);
	assert.equal(responses.length, 1);
	return responses[0] as Record<string, unknown>;
}

function resultOf(resp: Record<string, unknown>): Record<string, unknown> {
	return resp.result as Record<string, unknown>;
}

function errorOf(resp: Record<string, unknown>): Record<string, unknown> {
	return resp.error as Record<string, unknown>;
}

function contentOf(
	resp: Record<string, unknown>,
): { type: string; text: string }[] {
	return resultOf(resp).content as { type: string; text: string }[];
}

function toolsOf(resp: Record<string, unknown>): Record<string, unknown>[] {
	return resultOf(resp).tools as Record<string, unknown>[];
}

function addNoopCommand(app: App): void {
	app.command(
		defineReadOnlyCommand("cmd", { help: "a command", handler: () => 0 }),
	);
}

// --- initialize ---

test("mcp: initialize returns protocol info and server info", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "initialize",
		params: {},
	});
	assert.equal(resp.jsonrpc, "2.0");
	assert.equal(resp.id, 1);
	const result = resultOf(resp);
	assert.equal(result.protocolVersion, "2024-11-05");
	assert.deepEqual(result.capabilities, { tools: {} });
	assert.deepEqual(result.serverInfo, { name: "myapp", version: "1.0.0" });
});

test("mcp: initialize preserves a string id", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: "abc-123",
		method: "initialize",
		params: {},
	});
	assert.equal(resp.id, "abc-123");
});

test("mcp: initialize reflects the app name and version", async () => {
	const app = createApp({ name: "mytool", version: "2.5.0", help: "my tool" });
	app.command(
		defineReadOnlyCommand("run", { help: "run something", handler: () => 0 }),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "initialize",
		params: {},
	});
	assert.deepEqual(resultOf(resp).serverInfo, {
		name: "mytool",
		version: "2.5.0",
	});
});

// --- tools/list ---

test("mcp: tools/list returns a definition for a single command", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("deploy", {
			help: "deploy the app",
			flags: { target: flag("target", t.str, { help: "deploy target" }) },
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 2,
		method: "tools/list",
		params: {},
	});
	const tools = toolsOf(resp);
	assert.equal(tools.length, 1);
	const tool = tools[0] as Record<string, unknown>;
	assert.equal(tool.name, "deploy");
	assert.equal(tool.description, "deploy the app");
	const inputSchema = tool.inputSchema as Record<string, unknown>;
	assert.equal(inputSchema.type, "object");
	assert.ok(
		Object.hasOwn(inputSchema.properties as Record<string, unknown>, "target"),
	);
});

test("mcp: tools/list covers multiple commands", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("deploy", {
			help: "deploy the app",
			handler: () => 0,
		}),
	);
	app.command(
		defineReadOnlyCommand("status", { help: "show status", handler: () => 0 }),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 3,
		method: "tools/list",
		params: {},
	});
	const names = toolsOf(resp).map((tl) => tl.name);
	assert.ok(names.includes("deploy"));
	assert.ok(names.includes("status"));
});

test("mcp: tools/list uses dotted names for grouped commands", async () => {
	const app = buildApp();
	const grp = app.group("db", { help: "database commands" });
	grp.command(
		defineReadOnlyCommand("migrate", {
			help: "run migrations",
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 4,
		method: "tools/list",
		params: {},
	});
	assert.ok(
		toolsOf(resp)
			.map((tl) => tl.name)
			.includes("db.migrate"),
	);
});

test("mcp: tools/list excludes hidden commands", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("visible", {
			help: "visible command",
			handler: () => 0,
		}),
	);
	app.command(
		defineReadOnlyCommand("secret", {
			help: "hidden command",
			hidden: true,
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 5,
		method: "tools/list",
		params: {},
	});
	const names = toolsOf(resp).map((tl) => tl.name);
	assert.ok(names.includes("visible"));
	assert.equal(names.includes("secret"), false);
});

test("mcp: tools/list excludes interactive commands", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("batch", {
			help: "batch operation",
			handler: () => 0,
		}),
	);
	app.command(
		defineReadOnlyCommand("wizard", {
			help: "interactive wizard",
			interactive: true,
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 6,
		method: "tools/list",
		params: {},
	});
	const names = toolsOf(resp).map((tl) => tl.name);
	assert.ok(names.includes("batch"));
	assert.equal(names.includes("wizard"), false);
});

test("mcp: tools/list inputSchema matches jsonSchema()", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("deploy", {
			help: "deploy the app",
			flags: {
				target: flag("target", t.str, { help: "deploy target" }),
				count: flag("count", t.int, { help: "instance count", default: 1n }),
				chatter: flag("chatter", t.bool, {
					help: "chatter mode",
					default: false,
				}),
			},
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 7,
		method: "tools/list",
		params: {},
	});
	const tool = toolsOf(resp)[0] as Record<string, unknown>;
	// The response was JSON round-tripped; the schema here is all-string, so
	// the comparison is exact.
	assert.deepEqual(tool.inputSchema, app.jsonSchema("deploy"));
});

// --- tools/call ---

test("mcp: tools/call returns outcome data as JSON text", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("info", {
			help: "get info",
			handler: () => outcome(0, { version: "1.0.0", status: "ok" }),
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 10,
		method: "tools/call",
		params: { name: "info", arguments: {} },
	});
	const content = contentOf(resp);
	assert.equal(content.length, 1);
	assert.equal(content[0]?.type, "text");
	assert.deepEqual(JSON.parse(content[0]?.text as string), {
		version: "1.0.0",
		status: "ok",
	});
});

test("mcp: tools/call passes arguments through to the handler", async () => {
	const captured: Record<string, unknown> = {};
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("deploy", {
			help: "deploy",
			flags: {
				target: flag("target", t.str, { help: "deploy target" }),
				count: flag("count", t.int, { help: "instance count", default: 1n }),
			},
			handler: (args) => {
				captured.target = args.target;
				captured.count = args.count;
				return outcome(0, { deployed: args.target, count: args.count });
			},
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 11,
		method: "tools/call",
		params: { name: "deploy", arguments: { target: "prod", count: 3 } },
	});
	assert.equal(captured.target, "prod");
	// Pre-typed invoke values pass through as-is (Go parity): a JSON number
	// stays a number, it is not converted to bigint.
	assert.equal(captured.count, 3);
	assert.deepEqual(JSON.parse(contentOf(resp)[0]?.text as string), {
		deployed: "prod",
		count: 3,
	});
});

test("mcp: tools/call serializes a void handler return as null", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("noop", {
			help: "does nothing",
			handler: () => undefined,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 12,
		method: "tools/call",
		params: { name: "noop", arguments: {} },
	});
	assert.equal(JSON.parse(contentOf(resp)[0]?.text as string), null);
});

test("mcp: tools/call serializes an integer handler return", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("count", { help: "count things", handler: () => 42 }),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 13,
		method: "tools/call",
		params: { name: "count", arguments: {} },
	});
	assert.equal(JSON.parse(contentOf(resp)[0]?.text as string), 42);
});

test("mcp: tools/call resolves dotted grouped-command names", async () => {
	const app = buildApp();
	const grp = app.group("db", { help: "database commands" });
	grp.command(
		defineReadOnlyCommand("migrate", {
			help: "run migrations",
			flags: {
				sim_run: flag("sim-run", t.bool, {
					help: "dry run mode",
					default: false,
				}),
			},
			handler: (args) => outcome(0, { migrated: true, sim_run: args.sim_run }),
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 14,
		method: "tools/call",
		params: { name: "db.migrate", arguments: { sim_run: true } },
	});
	assert.deepEqual(JSON.parse(contentOf(resp)[0]?.text as string), {
		migrated: true,
		sim_run: true,
	});
});

test("mcp: unknown tool surfaces as isError content, not -32602", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 15,
		method: "tools/call",
		params: { name: "nonexistent", arguments: {} },
	});
	assert.equal("error" in resp, false);
	assert.equal(resultOf(resp).isError, true);
	const content = contentOf(resp);
	assert.equal(content.length, 1);
	assert.equal(content[0]?.type, "text");
	assert.equal(content[0]?.text, "unknown command 'nonexistent'");
});

test("mcp: missing required flag surfaces as isError content", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("deploy", {
			help: "deploy",
			flags: { target: flag("target", t.str, { help: "deploy target" }) },
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 16,
		method: "tools/call",
		params: { name: "deploy", arguments: {} },
	});
	assert.equal(resultOf(resp).isError, true);
	const content = contentOf(resp);
	assert.equal(content.length, 1);
	assert.equal(content[0]?.type, "text");
	assert.equal(content[0]?.text, "flag '--target' is required");
});

test("mcp: tools/call without name is -32602", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 17,
		method: "tools/call",
		params: { arguments: {} },
	});
	assert.equal(errorOf(resp).code, -32602);
	assert.equal(errorOf(resp).message, "missing required parameter: name");
});

test("mcp: tools/call with non-string name is -32602", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 19,
		method: "tools/call",
		params: { name: 42, arguments: {} },
	});
	assert.equal(errorOf(resp).code, -32602);
	assert.equal(errorOf(resp).message, "parameter 'name' must be a string");
});

test("mcp: tools/call with non-object arguments is -32602", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 20,
		method: "tools/call",
		params: { name: "cmd", arguments: ["not", "an", "object"] },
	});
	assert.equal(errorOf(resp).code, -32602);
	assert.equal(
		errorOf(resp).message,
		"parameter 'arguments' must be an object",
	);
});

test("mcp: omitted arguments key defaults to an empty object", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("noop", {
			help: "does nothing",
			handler: () => outcome(0, "ok"),
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 18,
		method: "tools/call",
		params: { name: "noop" },
	});
	assert.equal(JSON.parse(contentOf(resp)[0]?.text as string), "ok");
});

// --- Notifications ---

test("mcp: notifications (no id) produce no response", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const responses = await sendRequests(app, {
		jsonrpc: "2.0",
		method: "notifications/initialized",
	});
	assert.deepEqual(responses, []);
});

test("mcp: notifications are consumed silently between requests", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const responses = await sendRequests(
		app,
		{ jsonrpc: "2.0", method: "notifications/initialized" },
		{ jsonrpc: "2.0", id: 1, method: "initialize", params: {} },
	);
	assert.equal(responses.length, 1);
	assert.equal(responses[0]?.id, 1);
});

// --- Protocol errors ---

test("mcp: malformed JSON is -32700 Parse error with null id", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const responses = await serveRaw(app, "not valid json\n");
	assert.equal(responses.length, 1);
	const resp = responses[0] as Record<string, unknown>;
	assert.equal(errorOf(resp).code, -32700);
	// Go-parity: message casing is "Parse error".
	assert.equal(errorOf(resp).message, "Parse error");
	assert.equal(resp.id, null);
});

test("mcp: unknown method is -32601 Method not found", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 99,
		method: "bogus/method",
		params: {},
	});
	assert.equal(errorOf(resp).code, -32601);
	// Go-parity: message casing is "Method not found".
	assert.equal(errorOf(resp).message, "Method not found: bogus/method");
});

test("mcp: a non-object JSON line is -32700 Parse error (Go parity)", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const responses = await serveRaw(app, "[1, 2, 3]\n");
	assert.equal(responses.length, 1);
	const resp = responses[0] as Record<string, unknown>;
	assert.equal(errorOf(resp).code, -32700);
	assert.equal(errorOf(resp).message, "Parse error");
});

test("mcp: blank lines are silently skipped", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const req = JSON.stringify({
		jsonrpc: "2.0",
		id: 1,
		method: "initialize",
		params: {},
	});
	const responses = await serveRaw(app, `\n\n${req}\n\n`);
	assert.equal(responses.length, 1);
	assert.equal(responses[0]?.id, 1);
});

// --- Multi-request conversation ---

test("mcp: full conversation: initialize, notification, list, call", async () => {
	const captured: Record<string, unknown> = {};
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("greet", {
			help: "greet someone",
			flags: { name: flag("name", t.str, { help: "person to greet" }) },
			handler: (args) => {
				captured.name = args.name;
				return outcome(0, { greeting: `hello ${args.name}` });
			},
		}),
	);
	const responses = await sendRequests(
		app,
		{ jsonrpc: "2.0", id: 1, method: "initialize", params: {} },
		{ jsonrpc: "2.0", method: "notifications/initialized" },
		{ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} },
		{
			jsonrpc: "2.0",
			id: 3,
			method: "tools/call",
			params: { name: "greet", arguments: { name: "Alice" } },
		},
	);
	assert.equal(responses.length, 3);

	assert.equal(responses[0]?.id, 1);
	assert.deepEqual(
		resultOf(responses[0] as Record<string, unknown>).serverInfo,
		{ name: "myapp", version: "1.0.0" },
	);

	assert.equal(responses[1]?.id, 2);
	const tools = toolsOf(responses[1] as Record<string, unknown>);
	assert.equal(tools.length, 1);
	assert.equal(tools[0]?.name, "greet");

	assert.equal(responses[2]?.id, 3);
	assert.deepEqual(
		JSON.parse(
			contentOf(responses[2] as Record<string, unknown>)[0]?.text as string,
		),
		{ greeting: "hello Alice" },
	);
	assert.equal(captured.name, "Alice");
});

// --- --mcp flag interception ---

test("mcp: test(['--mcp']) errors with the interactive-stdin message", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const result = await app.test(["--mcp"]);
	assert.equal(result.exitCode, 1);
	assert.equal(
		result.stderr,
		"error: --mcp requires interactive stdin/stdout\n",
	);
});

test("mcp: --mcp is intercepted anywhere in argv", async () => {
	const app = buildApp();
	addNoopCommand(app);
	const result = await app.test(["cmd", "--mcp"]);
	assert.equal(result.exitCode, 1);
	assert.ok(result.stderr.includes("--mcp"));
});

// --- Edge cases ---

test("mcp: deeply nested commands list and call by dotted path", async () => {
	const app = buildApp();
	const grp1 = app.group("cloud", { help: "cloud commands" });
	const grp2 = grp1.group("storage", { help: "storage commands" });
	grp2.command(
		defineReadOnlyCommand("upload", {
			help: "upload a file",
			flags: { bucket: flag("bucket", t.str, { help: "target bucket" }) },
			handler: (args) => outcome(0, { uploaded_to: args.bucket }),
		}),
	);

	const listResp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {},
	});
	assert.ok(
		toolsOf(listResp)
			.map((tl) => tl.name)
			.includes("cloud.storage.upload"),
	);

	const callResp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 2,
		method: "tools/call",
		params: {
			name: "cloud.storage.upload",
			arguments: { bucket: "my-bucket" },
		},
	});
	assert.deepEqual(JSON.parse(contentOf(callResp)[0]?.text as string), {
		uploaded_to: "my-bucket",
	});
});

test("mcp: a throwing handler returns isError content", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("fail", {
			help: "always fails",
			handler: () => {
				throw new Error("something broke");
			},
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/call",
		params: { name: "fail", arguments: {} },
	});
	assert.equal(resultOf(resp).isError, true);
	assert.ok(contentOf(resp)[0]?.text.includes("something broke"));
});

test("mcp: non-interactive config subcommands are exposed", async () => {
	const app = buildApp({ config: true });
	app.command(
		defineReadOnlyCommand("run", { help: "run the app", handler: () => 0 }),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {},
	});
	const names = toolsOf(resp).map((tl) => tl.name);
	assert.ok(names.includes("config.show"));
	assert.ok(names.includes("config.set"));
	assert.ok(names.includes("config.path"));
	assert.ok(names.includes("config.init"));
	// config.edit is interactive and must be excluded.
	assert.equal(names.includes("config.edit"), false);
});

test("mcp: successful calls carry no isError key", async () => {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("ok", {
			help: "always succeeds",
			handler: () => outcome(0, "success"),
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/call",
		params: { name: "ok", arguments: {} },
	});
	assert.equal("isError" in resultOf(resp), false);
});

// --- effects classification and programmatic consent over MCP ---

function consentApp(): App {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("look", {
			help: "look at things",
			handler: () => outcome(0, { looked: true }),
		}),
	);
	app.command(
		defineMutatingCommand("release", {
			help: "release things",
			consequential: true,
			handler: () => outcome(0, { released: true }),
		}),
	);
	return app;
}

async function toolDefs(
	app: App,
): Promise<Map<string, Record<string, unknown>>> {
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {},
	});
	return new Map(toolsOf(resp).map((def) => [def.name as string, def]));
}

function callRequest(params: Record<string, unknown>): unknown {
	return { jsonrpc: "2.0", id: 1, method: "tools/call", params };
}

test("mcp: tools/list publishes effect and consequential", async () => {
	const defs = await toolDefs(consentApp());
	assert.equal(defs.get("look")?.effect, "read_only");
	assert.equal(defs.get("release")?.effect, "mutating");
	assert.equal(defs.get("release")?.consequential, true);
	// Absence means "not consequential", exactly as in the schema dump.
	assert.equal(Object.hasOwn(defs.get("look") ?? {}, "consequential"), false);
});

test("mcp: the classification is not in inputSchema", async () => {
	const defs = await toolDefs(consentApp());
	const schema = defs.get("release")?.inputSchema as Record<string, unknown>;
	const properties = schema.properties as Record<string, unknown>;
	for (const banned of ["effect", "consequential", "approve_consequential"]) {
		assert.equal(Object.hasOwn(properties, banned), false);
	}
});

test("mcp: tools/call refuses a consequential tool without consent", async () => {
	const resp = await sendOne(consentApp(), callRequest({ name: "release" }));
	assert.equal(resultOf(resp).isError, true);
	assert.equal(
		contentOf(resp)[0]?.text,
		"command 'release' is consequential: pass approve_consequential to confirm",
	);
});

test("mcp: tools/call proceeds with explicit consent", async () => {
	const resp = await sendOne(
		consentApp(),
		callRequest({ name: "release", approve_consequential: true }),
	);
	assert.equal(Object.hasOwn(resultOf(resp), "isError"), false);
	assert.equal(contentOf(resp)[0]?.text, '{"released":true}');
});

test("mcp: an explicit false consent is refused", async () => {
	const resp = await sendOne(
		consentApp(),
		callRequest({ name: "release", approve_consequential: false }),
	);
	assert.equal(resultOf(resp).isError, true);
});

test("mcp: a read_only tool needs no consent", async () => {
	const resp = await sendOne(consentApp(), callRequest({ name: "look" }));
	assert.equal(Object.hasOwn(resultOf(resp), "isError"), false);
});

test("mcp: a non-boolean consent is a protocol error", async () => {
	const resp = await sendOne(
		consentApp(),
		callRequest({ name: "release", approve_consequential: "yes" }),
	);
	assert.equal(errorOf(resp).code, -32602);
	assert.equal(
		errorOf(resp).message,
		"parameter 'approve_consequential' must be a boolean",
	);
});

test("mcp: consent inside arguments does not consent", async () => {
	// The command's argument namespace is not a consent channel: no command
	// can declare the reserved name, so it surfaces as an unknown parameter.
	const resp = await sendOne(
		consentApp(),
		callRequest({
			name: "release",
			arguments: { approve_consequential: true },
		}),
	);
	assert.equal(resultOf(resp).isError, true);
});
