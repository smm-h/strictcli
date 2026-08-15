/**
 * MCP server tests: serveMcp(), the --mcp reserved flag, and the JSON-RPC
 * 2.0 protocol surface. Mirrors python/tests/test_mcp.py's pinned set
 * exactly (dotted tool names, Go-canon error strings: "Parse error",
 * "Method not found: <m>", the three -32602 parameter messages).
 */

import { strict as assert } from "node:assert";
import { PassThrough, Readable } from "node:stream";
import { test } from "node:test";
import type { App } from "../src/app.js";
import {
	choice,
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
	flag,
	memberChoiceFlag,
	outcome,
	t,
} from "../src/index.js";
import { MCP_CONTINUATION_TTL_SECONDS, McpContinuation } from "../src/mcp.js";

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

/**
 * The metadata every modern-era request carries (protocol 2026-07-28). The
 * helpers below splice it into any request that does not bring its own, so a
 * test that is not about the metadata itself reads as it always did.
 */
const MODERN_META: Record<string, unknown> = {
	"io.modelcontextprotocol/protocolVersion": "2026-07-28",
	"io.modelcontextprotocol/clientCapabilities": {},
};

/** Returns `req` with the modern request metadata spliced in. */
function asModern(req: unknown): unknown {
	if (typeof req !== "object" || req === null) {
		return req;
	}
	const obj = req as Record<string, unknown>;
	if (obj.method === "initialize" || !Object.hasOwn(obj, "method")) {
		return req;
	}
	const params = { ...((obj.params ?? {}) as Record<string, unknown>) };
	if (Object.hasOwn(params, "_meta")) {
		return req;
	}
	params._meta = { ...MODERN_META };
	return { ...obj, params };
}

/** Sends modern-era JSON-RPC requests and returns the parsed responses. */
async function sendRequests(
	app: App,
	...requests: unknown[]
): Promise<Record<string, unknown>[]> {
	return sendRequestsRaw(app, ...requests.map(asModern));
}

/** Sends JSON-RPC requests exactly as written -- no metadata is spliced in. */
async function sendRequestsRaw(
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

/** Sends one request as written and asserts exactly one response came back. */
async function sendOneRaw(
	app: App,
	request: unknown,
): Promise<Record<string, unknown>> {
	const responses = await sendRequestsRaw(app, request);
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
	assert.equal(result.protocolVersion, "2025-11-25");
	assert.deepEqual(result.capabilities, {
		tools: {},
		experimental: { "dev.smmh.strictcli/consequential-confirmation": {} },
	});
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
			flags: {
				target: flag("target", t.str, {
					help: "deploy target",
					presence: "required",
				}),
			},
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
				target: flag("target", t.str, {
					help: "deploy target",
					presence: "required",
				}),
				count: flag("count", t.int, {
					help: "instance count",
					presence: "default",
					default: 1n,
				}),
				chatter: flag("chatter", t.bool, {
					help: "chatter mode",
					presence: "default",
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
			payloadSchema: {},
			help: "get info",
			handler: (_args, ctx) => {
				ctx.payload({ version: "1.0.0", status: "ok" });
				return outcome(0);
			},
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
			payloadSchema: {},
			help: "deploy",
			flags: {
				target: flag("target", t.str, {
					help: "deploy target",
					presence: "required",
				}),
				count: flag("count", t.int, {
					help: "instance count",
					presence: "default",
					default: 1n,
				}),
			},
			handler: (args, ctx) => {
				captured.target = args.target;
				captured.count = args.count;
				ctx.payload({ deployed: args.target, count: args.count });
				return outcome(0);
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
	// A pre-typed value is checked against its declaration (§24.11, §18.23 item
	// 240), and JSON has no bigint, so the integer token arrives as the declared
	// int carrier's own representation rather than as the `number` JSON.parse
	// produced -- what the handler receives is what its type says it receives.
	assert.equal(captured.count, 3n);
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
			payloadSchema: {},
			help: "run migrations",
			flags: {
				sim_run: flag("sim-run", t.bool, {
					help: "dry run mode",
					presence: "default",
					default: false,
				}),
			},
			handler: (args, ctx) => {
				ctx.payload({ migrated: true, sim_run: args.sim_run });
				return outcome(0);
			},
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
			flags: {
				target: flag("target", t.str, {
					help: "deploy target",
					presence: "required",
				}),
			},
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

test("mcp: a double member election surfaces as isError content", async () => {
	// Supplying a member's payload property elects that member, so a payload
	// beside a selector property naming a DIFFERENT member is a double election
	// (§24.11, §21.4). It is a call the server ran and refused, which is the
	// invocation-error channel -- never a -32602 protocol error.
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("launch", {
			help: "launch",
			flags: {
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one profile",
							value: { carrier: t.str, help: "profile name" },
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to launch", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	const resp = await sendOne(app, {
		jsonrpc: "2.0",
		id: 17,
		method: "tools/call",
		params: {
			name: "launch",
			arguments: { target: "all-profiles", profile: "work" },
		},
	});
	assert.equal("error" in resp, false);
	assert.equal(resultOf(resp).isError, true);
	const content = contentOf(resp);
	assert.equal(content.length, 1);
	assert.equal(
		content[0]?.text,
		"--profile and --all-profiles are mutually exclusive",
	);
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
			payloadSchema: {},
			help: "does nothing",
			handler: (_args, ctx) => {
				ctx.payload("ok");
				return outcome(0);
			},
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
			payloadSchema: {},
			help: "greet someone",
			flags: {
				name: flag("name", t.str, {
					help: "person to greet",
					presence: "required",
				}),
			},
			handler: (args, ctx) => {
				captured.name = args.name;
				ctx.payload({ greeting: `hello ${args.name}` });
				return outcome(0);
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
			payloadSchema: {},
			help: "upload a file",
			flags: {
				bucket: flag("bucket", t.str, {
					help: "target bucket",
					presence: "required",
				}),
			},
			handler: (args, ctx) => {
				ctx.payload({ uploaded_to: args.bucket });
				return outcome(0);
			},
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
			payloadSchema: {},
			help: "always succeeds",
			handler: (_args, ctx) => {
				ctx.payload("success");
				return outcome(0);
			},
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
			payloadSchema: {},
			help: "look at things",
			handler: (_args, ctx) => {
				ctx.payload({ looked: true });
				return outcome(0);
			},
		}),
	);
	app.command(
		defineMutatingCommand("release", {
			payloadSchema: {},
			help: "release things",
			consequential: true,
			handler: (_args, ctx) => {
				ctx.payload({ released: true });
				return outcome(0);
			},
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
	// These clients declare no capabilities at all, so the modern answer is the
	// capability error rather than the seam's refusal, which is only reachable
	// from the legacy era now.
	const resp = await sendOne(consentApp(), callRequest({ name: "release" }));
	assert.equal(errorOf(resp).code, -32021);
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
	assert.equal(errorOf(resp).code, -32021);
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
	// The consent never registered, so the command was still unconfirmed and
	// the call never reached it.
	assert.equal(errorOf(resp).code, -32021);
});

// ---------------------------------------------------------------------------
// The modern era (protocol 2026-07-28)
// ---------------------------------------------------------------------------

/** The modern metadata block with per-test overrides applied. */
function metaWith(overrides: Record<string, unknown>): Record<string, unknown> {
	return { ...MODERN_META, ...overrides };
}

function modernApp(): App {
	const app = buildApp();
	app.command(
		defineReadOnlyCommand("status", {
			help: "show status",
			handler: () => outcome(0),
		}),
	);
	return app;
}

test("mcp: server/discover advertises versions, capabilities and identity", async () => {
	const resp = await sendOne(modernApp(), {
		jsonrpc: "2.0",
		id: 1,
		method: "server/discover",
		params: {},
	});
	const result = resultOf(resp);
	assert.equal(result.resultType, "complete");
	assert.deepEqual(result.supportedVersions, ["2026-07-28"]);
	assert.equal(result.instructions, "test app");
	assert.equal(result.ttlMs, 3600000);
	assert.equal(result.cacheScope, "public");
	assert.deepEqual(
		(result._meta as Record<string, unknown>)[
			"io.modelcontextprotocol/serverInfo"
		],
		{ name: "myapp", version: "1.0.0" },
	);
});

test("mcp: server/discover declares the confirmation feature by name", async () => {
	const resp = await sendOne(modernApp(), {
		jsonrpc: "2.0",
		id: 1,
		method: "server/discover",
		params: {},
	});
	const caps = resultOf(resp).capabilities as Record<string, unknown>;
	assert.deepEqual(caps.extensions, {
		"dev.smmh.strictcli/consequential-confirmation": {},
	});
});

test("mcp: modern results carry their result type", async () => {
	const app = modernApp();
	const list = await sendOne(app, {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {},
	});
	assert.equal(resultOf(list).resultType, "complete");
	assert.equal(resultOf(list).ttlMs, 3600000);
	assert.equal(resultOf(list).cacheScope, "public");

	const call = await sendOne(app, {
		jsonrpc: "2.0",
		id: 2,
		method: "tools/call",
		params: { name: "status", arguments: {} },
	});
	assert.equal(resultOf(call).resultType, "complete");
});

test("mcp: a request without the protocol metadata is refused", async () => {
	const resp = await sendOneRaw(modernApp(), {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {},
	});
	assert.equal(errorOf(resp).code, -32602);
	assert.equal(
		errorOf(resp).message,
		"missing required request metadata: _meta['io.modelcontextprotocol/protocolVersion']",
	);
});

test("mcp: the request metadata is validated key by key", async () => {
	const cases: [Record<string, unknown>, string][] = [
		[{ _meta: [] }, "parameter '_meta' must be an object"],
		[
			{
				_meta: metaWith({
					"io.modelcontextprotocol/protocolVersion": 2026,
				}),
			},
			"_meta['io.modelcontextprotocol/protocolVersion'] must be a string",
		],
		[
			{ _meta: { "io.modelcontextprotocol/protocolVersion": "2026-07-28" } },
			"missing required request metadata: _meta['io.modelcontextprotocol/clientCapabilities']",
		],
		[
			{
				_meta: metaWith({
					"io.modelcontextprotocol/clientCapabilities": "yes",
				}),
			},
			"_meta['io.modelcontextprotocol/clientCapabilities'] must be an object",
		],
		[
			{
				_meta: metaWith({
					"io.modelcontextprotocol/clientInfo": "ExampleClient",
				}),
			},
			"_meta['io.modelcontextprotocol/clientInfo'] must be an object",
		],
		[
			{ _meta: metaWith({ "-bad./key": 1 }) },
			"invalid _meta key name: '-bad./key'",
		],
		[
			{ _meta: metaWith({ "io.modelcontextprotocol/whatever": 1 }) },
			"unrecognized reserved _meta key: 'io.modelcontextprotocol/whatever'",
		],
	];
	for (const [params, message] of cases) {
		const resp = await sendOneRaw(modernApp(), {
			jsonrpc: "2.0",
			id: 1,
			method: "tools/list",
			params,
		});
		assert.equal(errorOf(resp).code, -32602);
		assert.equal(errorOf(resp).message, message);
	}
});

/*
 * The same request names the same key in every implementation.
 *
 * Go sorts the key set before validating because its map iteration is
 * randomized (§22.2); Python and TypeScript read a document's own order, which
 * is a different key whenever a request carries more than one offending key.
 * Sorted is what §22.2 documents, so all three sort.
 */
test("mcp: more than one offending _meta key names the first in sorted order", async () => {
	const cases: [Record<string, unknown>, string][] = [
		[{ "z!bad": 1, "a!bad": 1 }, "invalid _meta key name: 'a!bad'"],
		// The lexically first offender is named whichever rule it breaks.
		[
			{ "z!bad": 1, "io.mcp/whatever": 1 },
			"unrecognized reserved _meta key: 'io.mcp/whatever'",
		],
	];
	for (const [extra, message] of cases) {
		const resp = await sendOneRaw(modernApp(), {
			jsonrpc: "2.0",
			id: 1,
			method: "tools/list",
			params: { _meta: metaWith(extra) },
		});
		assert.equal(errorOf(resp).message, message);
	}
});

test("mcp: vendor and optional metadata keys are accepted", async () => {
	const resp = await sendOneRaw(modernApp(), {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {
			_meta: metaWith({
				"com.example.mcp/thing": 1,
				traceparent: "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01",
				progressToken: 7,
				"io.modelcontextprotocol/clientInfo": {
					name: "ExampleClient",
					version: "1.0.0",
				},
				"io.modelcontextprotocol/logLevel": "debug",
			}),
		},
	});
	assert.equal(resultOf(resp).resultType, "complete");
});

test("mcp: an unsupported protocol version is refused with the supported list", async () => {
	const resp = await sendOneRaw(modernApp(), {
		jsonrpc: "2.0",
		id: 1,
		method: "tools/list",
		params: {
			_meta: metaWith({
				"io.modelcontextprotocol/protocolVersion": "1900-01-01",
			}),
		},
	});
	assert.equal(errorOf(resp).code, -32022);
	assert.equal(errorOf(resp).message, "Unsupported protocol version");
	assert.deepEqual(errorOf(resp).data, {
		supported: ["2026-07-28"],
		requested: "1900-01-01",
	});
});

test("mcp: an unknown modern method is method-not-found", async () => {
	const resp = await sendOne(modernApp(), {
		jsonrpc: "2.0",
		id: 1,
		method: "resources/list",
		params: {},
	});
	assert.equal(errorOf(resp).code, -32601);
	assert.equal(errorOf(resp).message, "Method not found: resources/list");
});

test("mcp: initialize selects the legacy era for later requests", async () => {
	const responses = await sendRequestsRaw(
		modernApp(),
		{ jsonrpc: "2.0", id: 1, method: "initialize", params: {} },
		{ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} },
		{
			jsonrpc: "2.0",
			id: 3,
			method: "tools/list",
			params: { _meta: { ...MODERN_META } },
		},
		{ jsonrpc: "2.0", id: 4, method: "server/discover", params: {} },
	);
	assert.equal(
		resultOf(responses[0] as Record<string, unknown>).protocolVersion,
		"2025-11-25",
	);
	const legacyList = resultOf(responses[1] as Record<string, unknown>);
	assert.equal(Object.hasOwn(legacyList, "resultType"), false);
	assert.equal(Object.hasOwn(legacyList, "ttlMs"), false);
	assert.equal(
		resultOf(responses[2] as Record<string, unknown>).resultType,
		"complete",
	);
	assert.equal(errorOf(responses[3] as Record<string, unknown>).code, -32601);
});

// ---------------------------------------------------------------------------
// The confirmation round-trip and its continuation state
// ---------------------------------------------------------------------------

/**
 * Drives a live MCP session in which a request may depend on an earlier reply.
 *
 * The continuation key and its spent-id set live in the server process, so a
 * round-trip has to be driven through ONE serveMcp call: a second call is a
 * second server, and its state is deliberately worthless to the first.
 */
async function serveSession(
	app: App,
	...steps: ((seen: Record<string, unknown>[]) => unknown)[]
): Promise<Record<string, unknown>[]> {
	const stream = new PassThrough();
	const responses: Record<string, unknown>[] = [];
	let arrived: (() => void) | undefined;
	const serving = app.serveMcp({
		input: stream,
		output: {
			write: (chunk) => {
				for (const line of chunk.split("\n")) {
					if (line.trim() !== "") {
						responses.push(JSON.parse(line) as Record<string, unknown>);
					}
				}
				arrived?.();
			},
		},
	});
	for (const step of steps) {
		const reply = new Promise<void>((resolve) => {
			arrived = resolve;
		});
		stream.write(`${JSON.stringify(step(responses))}\n`);
		await reply;
	}
	stream.end();
	await serving;
	return responses;
}

/** A client that can render a form elicitation. */
function elicitingMeta(): Record<string, unknown> {
	return {
		"io.modelcontextprotocol/protocolVersion": "2026-07-28",
		"io.modelcontextprotocol/clientCapabilities": { elicitation: { form: {} } },
		"io.modelcontextprotocol/clientInfo": { name: "cli", version: "1.0.0" },
	};
}

function confirmingApp(): App {
	const app = buildApp();
	app.command(
		defineMutatingCommand("release", {
			help: "release it",
			consequential: true,
			handler: () => outcome(0),
		}),
	);
	app.command(
		defineReadOnlyCommand("look", { help: "look around", handler: () => 0 }),
	);
	return app;
}

function toolCall(id: unknown, params: Record<string, unknown>): unknown {
	if (!Object.hasOwn(params, "_meta")) {
		params._meta = elicitingMeta();
	}
	return { jsonrpc: "2.0", id, method: "tools/call", params };
}

function acceptance(proceed: boolean): Record<string, unknown> {
	return {
		"consequential-confirmation": {
			action: "accept",
			content: { proceed },
		},
	};
}

function stateOf(resp: Record<string, unknown>): string {
	return resultOf(resp).requestState as string;
}

/** Asks, then answers: the two halves of one confirmation. */
async function driveConfirmation(
	app: App,
	answers: Record<string, unknown>,
): Promise<Record<string, unknown>[]> {
	return serveSession(
		app,
		() => toolCall(1, { name: "release", arguments: {} }),
		(seen) =>
			toolCall(2, {
				name: "release",
				arguments: {},
				requestState: stateOf(seen[0] as Record<string, unknown>),
				inputResponses: answers,
			}),
	);
}

test("mcp: an unconsented consequential call asks for confirmation", async () => {
	const resp = await sendOneRaw(
		confirmingApp(),
		toolCall(1, { name: "release", arguments: {} }),
	);
	const result = resultOf(resp);
	assert.equal(result.resultType, "input_required");
	const requests = result.inputRequests as Record<string, unknown>;
	const request = requests["consequential-confirmation"] as Record<
		string,
		unknown
	>;
	assert.equal(request.method, "elicitation/create");
	const params = request.params as Record<string, unknown>;
	assert.equal(params.mode, "form");
	assert.equal(
		params.message,
		"about to run consequential command 'release'. Proceed?",
	);
	assert.equal(typeof result.requestState, "string");
	assert.notEqual(result.requestState, "");
});

test("mcp: a retry carrying acceptance proceeds", async () => {
	const responses = await driveConfirmation(confirmingApp(), acceptance(true));
	const result = resultOf(responses[1] as Record<string, unknown>);
	assert.equal(result.resultType, "complete");
	assert.equal(Object.hasOwn(result, "isError"), false);
});

test("mcp: a declined or cancelled confirmation aborts", async () => {
	for (const action of ["decline", "cancel"]) {
		const responses = await driveConfirmation(confirmingApp(), {
			"consequential-confirmation": { action },
		});
		const result = resultOf(responses[1] as Record<string, unknown>);
		assert.equal(result.isError, true);
		assert.equal((result.content as { text: string }[])[0]?.text, "aborted");
	}
});

test("mcp: an acceptance that says no aborts", async () => {
	const responses = await driveConfirmation(confirmingApp(), acceptance(false));
	assert.equal(resultOf(responses[1] as Record<string, unknown>).isError, true);
});

test("mcp: a missing answer asks again with fresh state", async () => {
	const responses = await driveConfirmation(confirmingApp(), {});
	const second = resultOf(responses[1] as Record<string, unknown>);
	assert.equal(second.resultType, "input_required");
	assert.notEqual(
		second.requestState,
		stateOf(responses[0] as Record<string, unknown>),
	);
});

test("mcp: a read-only tool is never asked about", async () => {
	const resp = await sendOneRaw(
		confirmingApp(),
		toolCall(1, { name: "look", arguments: {} }),
	);
	assert.equal(resultOf(resp).resultType, "complete");
});

test("mcp: a client without elicitation gets the capability error", async () => {
	// The revision forbids sending an input request the client never said it
	// could fulfil, and assigns the code for saying so.
	const resp = await sendOneRaw(
		confirmingApp(),
		toolCall(1, {
			name: "release",
			arguments: {},
			_meta: { ...MODERN_META },
		}),
	);
	const error = errorOf(resp);
	assert.equal(error.code, -32021);
	assert.equal(
		error.message,
		"Server requires the elicitation capability for this request",
	);
	assert.deepEqual(error.data, {
		requiredCapabilities: { elicitation: { form: {} } },
	});
});

test("mcp: a url-only client gets the capability error", async () => {
	const resp = await sendOneRaw(
		confirmingApp(),
		toolCall(1, {
			name: "release",
			arguments: {},
			_meta: metaWith({
				"io.modelcontextprotocol/clientCapabilities": {
					elicitation: { url: {} },
				},
			}),
		}),
	);
	assert.equal(errorOf(resp).code, -32021);
});

test("mcp: a stated consent needs no declared capability", async () => {
	const resp = await sendOneRaw(
		confirmingApp(),
		toolCall(1, {
			name: "release",
			arguments: {},
			approve_consequential: true,
			_meta: { ...MODERN_META },
		}),
	);
	const result = resultOf(resp);
	assert.equal(result.resultType, "complete");
	assert.equal(Object.hasOwn(result, "isError"), false);
});

// ---------------------------------------------------------------------------
// The legacy era's confirmation (contract §22.7)
// ---------------------------------------------------------------------------

/**
 * Like serveSession, but each step declares whether a reply is expected before
 * the next line goes out: the legacy exchange holds a request open while it
 * waits for an answer, so some lines have to be sent without reading first.
 */
async function serveScript(
	app: App,
	...steps: {
		build: (seen: Record<string, unknown>[]) => unknown;
		reply: boolean;
	}[]
): Promise<Record<string, unknown>[]> {
	const stream = new PassThrough();
	const responses: Record<string, unknown>[] = [];
	let arrived: (() => void) | undefined;
	const serving = app.serveMcp({
		input: stream,
		output: {
			write: (chunk) => {
				for (const line of chunk.split("\n")) {
					if (line.trim() !== "") {
						responses.push(JSON.parse(line) as Record<string, unknown>);
					}
				}
				arrived?.();
			},
		},
	});
	for (const step of steps) {
		const reply = new Promise<void>((resolve) => {
			arrived = resolve;
		});
		stream.write(`${JSON.stringify(step.build(responses))}\n`);
		if (step.reply) {
			await reply;
		}
	}
	stream.end();
	await serving;
	return responses;
}

/** The legacy opener: in that era the handshake IS the client's declaration. */
function handshakeRequest(elicitation: boolean): unknown {
	return {
		jsonrpc: "2.0",
		id: 1,
		method: "initialize",
		params: {
			capabilities: elicitation ? { elicitation: { form: {} } } : {},
			clientInfo: { name: "cli", version: "1.0.0" },
		},
	};
}

/** A legacy tools/call: no per-request metadata, because that era has none. */
function legacyCall(
	id: unknown,
	name: string,
	params: Record<string, unknown> = {},
): unknown {
	return {
		jsonrpc: "2.0",
		id,
		method: "tools/call",
		params: { name, arguments: {}, ...params },
	};
}

/** Answers the elicitation the server just sent, echoing its id. */
function answerElicitation(
	seen: Record<string, unknown>[],
	result: unknown,
): unknown {
	const ask = seen[seen.length - 1] as Record<string, unknown>;
	return { jsonrpc: "2.0", id: ask.id, result };
}

test("mcp: a legacy consequential call is asked over a server request", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => handshakeRequest(true),
		() => legacyCall(2, "release"),
		(seen) =>
			answerElicitation(seen, { action: "accept", content: { proceed: true } }),
	);
	const ask = responses[1] as Record<string, unknown>;
	assert.equal(ask.method, "elicitation/create");
	const params = ask.params as Record<string, unknown>;
	assert.equal(params.mode, "form");
	assert.equal(
		params.message,
		"about to run consequential command 'release'. Proceed?",
	);
	// The correlation id IS the continuation blob: one mint-and-verify path, two
	// delivery vehicles.
	assert.equal(typeof ask.id, "string");
	assert.ok((ask.id as string).includes("."));
	const result = resultOf(responses[2] as Record<string, unknown>);
	assert.equal(Object.hasOwn(result, "isError"), false);
	assert.equal(Object.hasOwn(result, "resultType"), false);
	// The command ran: its outcome, not an abort.
	assert.equal((result.content as { text: string }[])[0]?.text, "0");
});

test("mcp: in the legacy era anything but an acceptance aborts", async () => {
	const answers: unknown[] = [
		{ action: "decline" },
		{ action: "cancel" },
		{ action: "accept", content: { proceed: false } },
		{ action: "accept" },
		"not an elicitation result",
	];
	for (const answer of answers) {
		const responses = await serveSession(
			confirmingApp(),
			() => handshakeRequest(true),
			() => legacyCall(2, "release"),
			(seen) => answerElicitation(seen, answer),
		);
		const result = resultOf(responses[2] as Record<string, unknown>);
		assert.equal(result.isError, true);
		assert.equal((result.content as { text: string }[])[0]?.text, "aborted");
	}
});

test("mcp: a legacy error response aborts", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => handshakeRequest(true),
		() => legacyCall(2, "release"),
		(seen) => {
			const ask = seen[seen.length - 1] as Record<string, unknown>;
			return {
				jsonrpc: "2.0",
				id: ask.id,
				error: { code: -32601, message: "Method not found" },
			};
		},
	);
	assert.equal(resultOf(responses[2] as Record<string, unknown>).isError, true);
});

test("mcp: a legacy answer under an id the server never minted confirms nothing", async () => {
	const responses = await serveScript(
		confirmingApp(),
		{ build: () => handshakeRequest(true), reply: true },
		{ build: () => legacyCall(2, "release"), reply: true },
		{
			build: () => ({
				jsonrpc: "2.0",
				id: "not-the-blob",
				result: { action: "accept", content: { proceed: true } },
			}),
			reply: false,
		},
	);
	// The stray response is discarded; the stream then ends without an answer,
	// which aborts.
	const result = resultOf(responses[2] as Record<string, unknown>);
	assert.equal(result.isError, true);
	assert.equal((result.content as { text: string }[])[0]?.text, "aborted");
});

test("mcp: a legacy client that cannot be asked gets the seam's refusal", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => handshakeRequest(false),
		() => legacyCall(2, "release"),
	);
	const result = resultOf(responses[1] as Record<string, unknown>);
	assert.equal(result.isError, true);
	assert.equal(
		(result.content as { text: string }[])[0]?.text,
		"command 'release' is consequential: the call must carry confirmation",
	);
});

test("mcp: legacy read-only and consented calls are never asked about", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => handshakeRequest(true),
		() => legacyCall(2, "look"),
		() => legacyCall(3, "release", { approve_consequential: true }),
	);
	for (const resp of responses.slice(1)) {
		assert.equal(
			Object.hasOwn(resultOf(resp as Record<string, unknown>), "isError"),
			false,
		);
	}
});

/**
 * Fails unless the modern replay of a spent blob was refused as already used
 * rather than running the command.
 */
function assertReplayRefused(resp: Record<string, unknown>): void {
	assert.ok(
		Object.hasOwn(resp, "error"),
		`the aborted blob was replayed and ran the command: ${JSON.stringify(resp)}`,
	);
	assert.equal(errorOf(resp).message, "requestState has already been used");
}

/** The modern replay of the blob the server put on the wire as an elicitation id. */
function replayAskedBlob(seen: Record<string, unknown>[]): unknown {
	const ask = seen.filter((r) => r.method === "elicitation/create").pop() as
		| Record<string, unknown>
		| undefined;
	return toolCall(3, {
		name: "release",
		arguments: {},
		requestState: ask?.id,
		inputResponses: acceptance(true),
	});
}

/*
 * Every legacy exit spends the blob -- an abort is not a free replay.
 *
 * The blob binds the same principal and the same request digest the modern era
 * mints, and stays live for five minutes. An exchange that ended without
 * consuming it therefore hands the client a `requestState` it can answer
 * itself, on the modern path, for the very call it just aborted.
 */
test("mcp: a legacy exchange aborted by an error response consumes its state", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => handshakeRequest(true),
		() => legacyCall(2, "release"),
		(seen) => {
			const ask = seen[seen.length - 1] as Record<string, unknown>;
			return {
				jsonrpc: "2.0",
				id: ask.id,
				error: { code: -32601, message: "Method not found" },
			};
		},
		replayAskedBlob,
	);
	assert.equal(resultOf(responses[2] as Record<string, unknown>).isError, true);
	assertReplayRefused(responses[3] as Record<string, unknown>);
});

test("mcp: a legacy exchange refused by its answer consumes its state", async () => {
	// The exits that always consumed still do, after the reordering.
	for (const answer of [
		{ action: "decline" },
		{ action: "cancel" },
		{ action: "accept", content: { proceed: false } },
	]) {
		const responses = await serveSession(
			confirmingApp(),
			() => handshakeRequest(true),
			() => legacyCall(2, "release"),
			(seen) => answerElicitation(seen, answer),
			replayAskedBlob,
		);
		assert.equal(
			resultOf(responses[2] as Record<string, unknown>).isError,
			true,
		);
		assertReplayRefused(responses[3] as Record<string, unknown>);
	}
});

test("mcp: a legacy exchange that ends unanswered consumes its state", async () => {
	const responses = await serveScript(
		confirmingApp(),
		{ build: () => handshakeRequest(true), reply: true },
		{ build: () => legacyCall(2, "release"), reply: true },
		// Held while the server waits; the stream then ends without an answer,
		// which aborts, and the held request is served afterwards.
		{ build: replayAskedBlob, reply: false },
	);
	assert.equal(resultOf(responses[2] as Record<string, unknown>).isError, true);
	assertReplayRefused(responses[3] as Record<string, unknown>);
});

test("mcp: legacy traffic arriving mid-exchange is held, not dropped", async () => {
	const responses = await serveScript(
		confirmingApp(),
		{ build: () => handshakeRequest(true), reply: true },
		{ build: () => legacyCall(2, "release"), reply: true },
		{
			// Sent while the server is waiting for the answer.
			build: () => ({ jsonrpc: "2.0", id: 3, method: "tools/list" }),
			reply: false,
		},
		{
			build: (seen) => {
				const ask = seen[1] as Record<string, unknown>;
				return {
					jsonrpc: "2.0",
					id: ask.id,
					result: { action: "accept", content: { proceed: true } },
				};
			},
			reply: false,
		},
	);
	assert.equal(
		(responses[1] as Record<string, unknown>).method,
		"elicitation/create",
	);
	assert.equal((responses[2] as Record<string, unknown>).id, 2);
	// Served after the call it interrupted, never dropped.
	assert.equal((responses[3] as Record<string, unknown>).id, 3);
});

test("mcp: a modern call is still asked the modern way after a handshake", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => handshakeRequest(true),
		() => toolCall(2, { name: "release", arguments: {} }),
	);
	assert.equal(
		resultOf(responses[1] as Record<string, unknown>).resultType,
		"input_required",
	);
});

test("mcp: a tampered continuation is refused", async () => {
	const responses = await serveSession(
		confirmingApp(),
		() => toolCall(1, { name: "release", arguments: {} }),
		(seen) => {
			// The FIRST character: base64 decoders ignore the trailing bits of
			// a final character that does not fill a byte, so changing the last
			// character of the blob can decode to the identical bytes.
			const state = stateOf(seen[0] as Record<string, unknown>);
			const broken = `${state.startsWith("A") ? "B" : "A"}${state.slice(1)}`;
			return toolCall(2, {
				name: "release",
				arguments: {},
				requestState: broken,
				inputResponses: acceptance(true),
			});
		},
	);
	const err = errorOf(responses[1] as Record<string, unknown>);
	assert.equal(err.code, -32602);
	assert.equal(err.message, "requestState failed verification");
});

test("mcp: a continuation is single use", async () => {
	const retry =
		(id: number) =>
		(seen: Record<string, unknown>[]): unknown =>
			toolCall(id, {
				name: "release",
				arguments: {},
				requestState: stateOf(seen[0] as Record<string, unknown>),
				inputResponses: acceptance(true),
			});
	const responses = await serveSession(
		confirmingApp(),
		() => toolCall(1, { name: "release", arguments: {} }),
		retry(2),
		retry(3),
	);
	assert.equal(
		resultOf(responses[1] as Record<string, unknown>).resultType,
		"complete",
	);
	assert.equal(
		errorOf(responses[2] as Record<string, unknown>).message,
		"requestState has already been used",
	);
});

test("mcp: a continuation does not travel to another request or client", async () => {
	const other = await serveSession(
		confirmingApp(),
		() => toolCall(1, { name: "release", arguments: {} }),
		(seen) =>
			toolCall(2, {
				name: "release",
				arguments: { unexpected: 1 },
				requestState: stateOf(seen[0] as Record<string, unknown>),
				inputResponses: acceptance(true),
			}),
	);
	assert.equal(
		errorOf(other[1] as Record<string, unknown>).message,
		"requestState does not match this request",
	);

	const elsewhere = await serveSession(
		confirmingApp(),
		() => toolCall(1, { name: "release", arguments: {} }),
		(seen) => {
			const meta = elicitingMeta();
			meta["io.modelcontextprotocol/clientInfo"] = {
				name: "someone-else",
				version: "1.0.0",
			};
			return toolCall(2, {
				_meta: meta,
				name: "release",
				arguments: {},
				requestState: stateOf(seen[0] as Record<string, unknown>),
				inputResponses: acceptance(true),
			});
		},
	);
	assert.equal(
		errorOf(elsewhere[1] as Record<string, unknown>).message,
		"requestState was issued to a different client",
	);
});

test("mcp: an answer without its continuation is refused", async () => {
	const resp = await sendOneRaw(
		confirmingApp(),
		toolCall(1, {
			name: "release",
			arguments: {},
			inputResponses: acceptance(true),
		}),
	);
	assert.equal(
		errorOf(resp).message,
		"parameter 'inputResponses' requires the requestState it was issued with",
	);
});

test("mcp: a malformed answer is a protocol error", async () => {
	const responses = await driveConfirmation(confirmingApp(), {
		"consequential-confirmation": { action: "shrug" },
	});
	assert.equal(
		errorOf(responses[1] as Record<string, unknown>).message,
		"inputResponses['consequential-confirmation'] is not an elicitation result",
	);
});

/*
 * §22.4's blob is unpadded base64url and no other spelling of it.
 *
 * Left to themselves the three languages' decoders disagree: Python's accepts
 * padding and Node's ignores anything outside the alphabet, while Go's refuses
 * both -- and all three ignore a newline or the trailing bits of a final
 * character that does not fill a byte. The blob is attacker-controlled input,
 * so the spelling is checked before any decoder sees it, identically
 * everywhere.
 */
test("mcp: a continuation accepts only canonical unpadded base64url", () => {
	const alphabet =
		"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
	const continuation = new McpContinuation();
	const now = 1000000;
	const good = continuation.mint("cli/1.0.0", "digest", now);
	const [head, mac] = good.split(".") as [string, string];
	// The same data bits with a flipped ignored trailing bit: a lax decoder
	// yields the identical MAC bytes and accepts the blob.
	const noisy =
		mac.slice(0, -1) +
		alphabet[alphabet.indexOf(mac[mac.length - 1] as string) ^ 1];
	for (const spelling of [
		`${good}=`, // padding
		`${good}*`, // outside the alphabet
		`${head.slice(0, 5)}\n${head.slice(5)}.${mac}`, // a newline a decoder may skip
		`${head}.${noisy}`, // non-canonical trailing bits
	]) {
		assert.equal(
			continuation.verify(spelling, "cli/1.0.0", "digest", now),
			"requestState failed verification",
			`accepted a non-canonical spelling: ${spelling}`,
		);
	}
	// The canonical spelling still verifies, and is consumed doing so.
	assert.equal(
		continuation.verify(good, "cli/1.0.0", "digest", now),
		undefined,
	);
});

test("mcp: a continuation expires, and is worthless to another process", () => {
	// No clock reaches the wire, so expiry is driven at the mint.
	const continuation = new McpContinuation();
	const now = 1000000;
	const state = continuation.mint("cli/1.0.0", "digest", now);
	assert.equal(
		continuation.verify(
			state,
			"cli/1.0.0",
			"digest",
			now + MCP_CONTINUATION_TTL_SECONDS - 1,
		),
		undefined,
	);
	const fresh = continuation.mint("cli/1.0.0", "digest", now);
	assert.equal(
		continuation.verify(
			fresh,
			"cli/1.0.0",
			"digest",
			now + MCP_CONTINUATION_TTL_SECONDS + 1,
		),
		"requestState has expired",
	);

	const other = new McpContinuation();
	assert.equal(
		other.verify(state, "cli/1.0.0", "digest", now),
		"requestState failed verification",
	);
});
