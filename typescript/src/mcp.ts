/**
 * MCP (Model Context Protocol) server: a line-delimited JSON-RPC 2.0 loop
 * over stdin/stdout handling initialize, tools/list, and tools/call.
 * Triggered by the reserved --mcp global flag (position-aware pre-scan in
 * parse.ts); test() rejects it with the interactive-stdin message instead.
 *
 * Parity: Go mcp.go supplies the canonical error strings ("Parse error",
 * "Method not found: <m>", the three -32602 messages); Python
 * _run_mcp_server is the ground truth for behavior where the siblings
 * diverge -- tool names are dotted command paths (Python), not
 * underscore-mangled (Go), and a non-object JSON line is a -32700 parse
 * error exactly like malformed JSON.
 */

import { createInterface } from "node:readline";
import type { AppImpl } from "./app.js";
import type { Writer } from "./context.js";
import { jsonCompact } from "./outcome.js";
import { buildJSONSchema, collectToolCommands } from "./tool.js";

/** Optional stream overrides for serveMcp (defaults: process stdin/stdout). */
export interface McpIO {
	readonly input?: NodeJS.ReadableStream;
	readonly output?: Writer;
}

// JSON-RPC error codes.
const MCP_ERR_PARSE = -32700;
const MCP_ERR_METHOD_NOT_FOUND = -32601;
const MCP_ERR_INVALID_PARAMS = -32602;

type JsonObject = Record<string, unknown>;

function isPlainObject(v: unknown): v is JsonObject {
	return typeof v === "object" && v !== null && !Array.isArray(v);
}

function jsonrpcError(
	reqId: unknown,
	code: number,
	message: string,
): JsonObject {
	return { jsonrpc: "2.0", id: reqId ?? null, error: { code, message } };
}

function jsonrpcResult(reqId: unknown, result: unknown): JsonObject {
	return { jsonrpc: "2.0", id: reqId ?? null, result };
}

/** Tool-result error content (isError), NOT a JSON-RPC protocol error. */
function toolErrorResult(reqId: unknown, text: string): JsonObject {
	return jsonrpcResult(reqId, {
		content: [{ type: "text", text }],
		isError: true,
	});
}

function handleInitialize(app: AppImpl, reqId: unknown): JsonObject {
	return jsonrpcResult(reqId, {
		protocolVersion: "2024-11-05",
		capabilities: { tools: {} },
		serverInfo: { name: app.name, version: app.version },
	});
}

function handleToolsList(app: AppImpl, reqId: unknown): JsonObject {
	const tools = collectToolCommands(app).map(([dottedPath, cmd]) => ({
		name: dottedPath,
		description: cmd.help,
		inputSchema: buildJSONSchema(cmd),
	}));
	return jsonrpcResult(reqId, { tools });
}

async function handleToolsCall(
	app: AppImpl,
	reqId: unknown,
	params: JsonObject,
): Promise<JsonObject> {
	if (!Object.hasOwn(params, "name")) {
		return jsonrpcError(
			reqId,
			MCP_ERR_INVALID_PARAMS,
			"missing required parameter: name",
		);
	}
	const toolName = params.name;
	if (typeof toolName !== "string") {
		return jsonrpcError(
			reqId,
			MCP_ERR_INVALID_PARAMS,
			"parameter 'name' must be a string",
		);
	}

	// Unknown tools are NOT a -32602 protocol error: the name is passed to
	// app.call(), whose invocation error surfaces as isError content below.
	let callArgs: JsonObject = {};
	if (Object.hasOwn(params, "arguments")) {
		const argsVal = params.arguments;
		if (!isPlainObject(argsVal)) {
			return jsonrpcError(
				reqId,
				MCP_ERR_INVALID_PARAMS,
				"parameter 'arguments' must be an object",
			);
		}
		callArgs = argsVal;
	}

	let result: unknown;
	try {
		result = await app.call(toolName, callArgs);
	} catch (e) {
		return toolErrorResult(reqId, e instanceof Error ? e.message : String(e));
	}

	// jsonCompact serializes undefined as "null" (Python json.dumps(None))
	// and BigInt values as bare integer tokens.
	return jsonrpcResult(reqId, {
		content: [{ type: "text", text: jsonCompact(result) }],
	});
}

/**
 * Runs the MCP JSON-RPC 2.0 server loop: one JSON object per line in, one
 * JSON object per line out, until input is exhausted (EOF). Notifications
 * (no "id" key) get no response; blank lines are skipped.
 */
export async function serveMcp(app: AppImpl, io: McpIO = {}): Promise<void> {
	const input = io.input ?? process.stdin;
	const output = io.output ?? process.stdout;
	const write = (resp: JsonObject): void => {
		output.write(`${jsonCompact(resp)}\n`);
	};

	const rl = createInterface({ input, crlfDelay: Infinity });
	for await (const line of rl) {
		if (line.trim() === "") {
			continue;
		}

		let msg: unknown;
		try {
			msg = JSON.parse(line);
		} catch {
			write(jsonrpcError(null, MCP_ERR_PARSE, "Parse error"));
			continue;
		}
		// A non-object JSON value is a parse error, matching Go (which
		// unmarshals directly into a struct).
		if (!isPlainObject(msg)) {
			write(jsonrpcError(null, MCP_ERR_PARSE, "Parse error"));
			continue;
		}

		// Notifications have no "id" key -- consume silently, no response.
		if (!Object.hasOwn(msg, "id")) {
			continue;
		}
		const reqId = msg.id;
		const method = Object.hasOwn(msg, "method") ? msg.method : "";
		const params = isPlainObject(msg.params) ? msg.params : {};

		let resp: JsonObject;
		if (method === "initialize") {
			resp = handleInitialize(app, reqId);
		} else if (method === "tools/list") {
			resp = handleToolsList(app, reqId);
		} else if (method === "tools/call") {
			resp = await handleToolsCall(app, reqId, params);
		} else {
			resp = jsonrpcError(
				reqId,
				MCP_ERR_METHOD_NOT_FOUND,
				`Method not found: ${String(method)}`,
			);
		}
		write(resp);
	}
}
