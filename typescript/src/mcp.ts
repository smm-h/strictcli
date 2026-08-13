/**
 * MCP (Model Context Protocol) server: a line-delimited JSON-RPC 2.0 loop
 * over stdin/stdout handling initialize, tools/list, and tools/call.
 * Triggered by the reserved --mcp global flag (position-aware pre-scan in
 * parse.ts); test() rejects it with the interactive-stdin message instead.
 *
 * Parity: Go mcp.go supplies the canonical error strings ("Parse error",
 * "Method not found: <m>", the three -32602 messages); Python
 * _run_mcp_server is the ground truth for behavior where the siblings once
 * diverged -- a tool name is the dotted command path (Go's underscore
 * mangling and its guessing reverse lookup are deleted), and a non-object
 * JSON line is a -32700 parse error exactly like malformed JSON.
 */

import { createInterface } from "node:readline";
import type { AppImpl } from "./app.js";
import type { Writer } from "./context.js";
import { commandClassification } from "./invoke.js";
import { jsonCompact } from "./outcome.js";
import { buildJSONSchema, collectToolCommands } from "./tool.js";

/** Optional stream overrides for serveMcp (defaults: process stdin/stdout). */
export interface McpIO {
	readonly input?: NodeJS.ReadableStream;
	readonly output?: Writer;
}

// JSON-RPC and MCP error codes. -32020 (HeaderMismatch) belongs to the HTTP
// transport, which this server does not speak; -32021
// (MissingRequiredClientCapability) is fired by the confirmation round-trip.
const MCP_ERR_PARSE = -32700;
const MCP_ERR_METHOD_NOT_FOUND = -32601;
const MCP_ERR_INVALID_PARAMS = -32602;
const MCP_ERR_UNSUPPORTED_PROTOCOL_VERSION = -32022;

// The server speaks two eras (effects contract §22):
//
//   MODERN (2026-07-28) -- stateless. There is no handshake: every request
//   carries its protocol version and the client's capabilities in `_meta`,
//   every result carries a `resultType`, and `server/discover` advertises the
//   supported versions, the capabilities and the server identity that the
//   handshake used to carry.
//
//   LEGACY (2024-11-05) -- the `initialize` handshake. It is selected by an
//   `initialize` request and scoped to this process, which is exactly the
//   dual-era rule the modern revision specifies for a server serving both.
//
// A request that carries neither the modern metadata nor a preceding
// `initialize` is malformed and is refused. Nothing is inferred.
export const MCP_PROTOCOL_VERSION = "2026-07-28";
const MCP_LEGACY_PROTOCOL_VERSION = "2024-11-05";

// The reserved `_meta` keys of the modern revision.
export const MCP_META_PROTOCOL_VERSION =
	"io.modelcontextprotocol/protocolVersion";
export const MCP_META_CLIENT_CAPABILITIES =
	"io.modelcontextprotocol/clientCapabilities";
const MCP_META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo";
const MCP_META_SERVER_INFO = "io.modelcontextprotocol/serverInfo";
const MCP_META_LOG_LEVEL = "io.modelcontextprotocol/logLevel";
const MCP_META_SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId";

// A key under a prefix the protocol reserves for itself is either one this
// revision defines or one this server does not speak; the second is refused
// rather than ignored.
const MCP_RECOGNIZED_RESERVED_META_KEYS = new Set([
	MCP_META_PROTOCOL_VERSION,
	MCP_META_CLIENT_CAPABILITIES,
	MCP_META_CLIENT_INFO,
	MCP_META_LOG_LEVEL,
	MCP_META_SUBSCRIPTION_ID,
]);

// The named feature the server declares (campaign decision 26). A NAME, never a
// version number: a new name appears only if the confirmation dance changes
// incompatibly.
const MCP_FEATURE_CONSEQUENTIAL_CONFIRMATION =
	"dev.smmh.strictcli/consequential-confirmation";

// Cacheability of the list surfaces. The tool list is derived from the app's
// static command registration, so it cannot vary per client (public) and cannot
// change while the process runs.
const MCP_CACHE_TTL_MS = 3600000;
const MCP_CACHE_SCOPE = "public";

const MCP_META_PREFIX_LABEL_RE = /^[A-Za-z](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/;
const MCP_META_NAME_RE = /^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/;

type JsonObject = Record<string, unknown>;

function isPlainObject(v: unknown): v is JsonObject {
	return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * True when `key` matches the protocol's `_meta` key-name grammar: an optional
 * dot-separated prefix, a slash, and a name. The name may be empty; when it is
 * not, it begins and ends alphanumeric and may carry hyphens, underscores and
 * dots in between.
 */
function metaKeyValid(key: string): boolean {
	const parts = key.split("/");
	let name: string;
	if (parts.length === 1) {
		name = parts[0] as string;
	} else if (parts.length === 2) {
		for (const label of (parts[0] as string).split(".")) {
			if (!MCP_META_PREFIX_LABEL_RE.test(label)) {
				return false;
			}
		}
		name = parts[1] as string;
	} else {
		return false;
	}
	return name === "" || MCP_META_NAME_RE.test(name);
}

/**
 * True when `key` sits under a prefix the protocol reserves for itself: any
 * prefix whose SECOND label is `modelcontextprotocol` or `mcp`. So
 * `io.modelcontextprotocol/` and `com.mcp.tools/` are reserved and
 * `com.example.mcp/` is not.
 */
function metaKeyReserved(key: string): boolean {
	const parts = key.split("/");
	if (parts.length !== 2) {
		return false;
	}
	const labels = (parts[0] as string).split(".");
	return (
		labels.length >= 2 &&
		(labels[1] === "modelcontextprotocol" || labels[1] === "mcp")
	);
}

/**
 * Validate one request's `_meta` block; return the refusal, or undefined.
 * Called only once the block is known to carry the protocol version, which is
 * what selects the modern era in the first place.
 */
function validateMeta(meta: JsonObject): string | undefined {
	for (const key of Object.keys(meta)) {
		if (!metaKeyValid(key)) {
			return `invalid _meta key name: '${key}'`;
		}
		if (metaKeyReserved(key) && !MCP_RECOGNIZED_RESERVED_META_KEYS.has(key)) {
			return `unrecognized reserved _meta key: '${key}'`;
		}
	}
	if (typeof meta[MCP_META_PROTOCOL_VERSION] !== "string") {
		return `_meta['${MCP_META_PROTOCOL_VERSION}'] must be a string`;
	}
	if (!Object.hasOwn(meta, MCP_META_CLIENT_CAPABILITIES)) {
		return `missing required request metadata: _meta['${MCP_META_CLIENT_CAPABILITIES}']`;
	}
	if (!isPlainObject(meta[MCP_META_CLIENT_CAPABILITIES])) {
		return `_meta['${MCP_META_CLIENT_CAPABILITIES}'] must be an object`;
	}
	if (
		Object.hasOwn(meta, MCP_META_CLIENT_INFO) &&
		!isPlainObject(meta[MCP_META_CLIENT_INFO])
	) {
		return `_meta['${MCP_META_CLIENT_INFO}'] must be an object`;
	}
	return undefined;
}

function jsonrpcError(
	reqId: unknown,
	code: number,
	message: string,
	data?: unknown,
): JsonObject {
	const error: JsonObject = { code, message };
	if (data !== undefined) {
		error.data = data;
	}
	return { jsonrpc: "2.0", id: reqId ?? null, error };
}

function jsonrpcResult(reqId: unknown, result: unknown): JsonObject {
	return { jsonrpc: "2.0", id: reqId ?? null, result };
}

/** The identity every modern result carries in its own `_meta`. */
function serverInfoMeta(app: AppImpl): JsonObject {
	return {
		[MCP_META_SERVER_INFO]: { name: app.name, version: app.version },
	};
}

/** Wrap a modern result body: `resultType` in front, server identity behind. */
function completeResult(
	app: AppImpl,
	reqId: unknown,
	body: JsonObject,
): JsonObject {
	return jsonrpcResult(reqId, {
		resultType: "complete",
		...body,
		_meta: serverInfoMeta(app),
	});
}

/** A tool result -- the one place the two eras' shapes differ. */
function toolResult(
	app: AppImpl,
	reqId: unknown,
	text: string,
	modern: boolean,
	isError = false,
): JsonObject {
	const body: JsonObject = { content: [{ type: "text", text }] };
	if (isError) {
		body.isError = true;
	}
	return modern ? completeResult(app, reqId, body) : jsonrpcResult(reqId, body);
}

/**
 * The legacy-era `initialize` handshake, which also selects that era.
 *
 * The modern revision has no handshake; this method is what a legacy client
 * opens with, and answering it is what puts this process into legacy semantics
 * for every later request that carries no modern metadata.
 */
function handleInitialize(app: AppImpl, reqId: unknown): JsonObject {
	return jsonrpcResult(reqId, {
		protocolVersion: MCP_LEGACY_PROTOCOL_VERSION,
		capabilities: { tools: {} },
		serverInfo: { name: app.name, version: app.version },
	});
}

/**
 * `server/discover` -- the modern era's mandatory discovery call. It replaces
 * the handshake: supported versions, capabilities and identity in one request.
 * The declared feature is a NAME rather than a version number, so a client
 * learns that this server runs the confirmation dance without having to infer
 * it from a revision date.
 */
function handleDiscover(app: AppImpl, reqId: unknown): JsonObject {
	return completeResult(app, reqId, {
		supportedVersions: [MCP_PROTOCOL_VERSION],
		capabilities: {
			tools: {},
			extensions: { [MCP_FEATURE_CONSEQUENTIAL_CONFIRMATION]: {} },
		},
		instructions: app.help,
		ttlMs: MCP_CACHE_TTL_MS,
		cacheScope: MCP_CACHE_SCOPE,
	});
}

function handleToolsList(
	app: AppImpl,
	reqId: unknown,
	modern: boolean,
): JsonObject {
	// The classification sits BESIDE inputSchema, never inside it: it describes
	// the tool, not an argument the caller passes. Same emission rule as the
	// schema dump -- `effect` always, `consequential` only when true (absence
	// means "not consequential").
	const tools = collectToolCommands(app).map(([dottedPath, cmd]) => {
		const { effect, consequential } = commandClassification(cmd);
		const def: JsonObject = {
			name: dottedPath,
			description: cmd.help,
			effect,
			inputSchema: buildJSONSchema(cmd),
		};
		if (consequential) {
			def.consequential = true;
		}
		return def;
	});
	if (!modern) {
		return jsonrpcResult(reqId, { tools });
	}
	return completeResult(app, reqId, {
		tools,
		ttlMs: MCP_CACHE_TTL_MS,
		cacheScope: MCP_CACHE_SCOPE,
	});
}

async function handleToolsCall(
	app: AppImpl,
	reqId: unknown,
	params: JsonObject,
	modern: boolean,
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

	// Consent is a top-level param, a sibling of `name` and `arguments` --
	// never a member of `arguments`, which is the command's own argument
	// namespace and is published with additionalProperties: false. There is no
	// server-side default: absent means "not consented", and a consequential
	// tool is then refused.
	const consentVal = Object.hasOwn(params, "approve_consequential")
		? params.approve_consequential
		: false;
	if (typeof consentVal !== "boolean") {
		return jsonrpcError(
			reqId,
			MCP_ERR_INVALID_PARAMS,
			"parameter 'approve_consequential' must be a boolean",
		);
	}

	let result: unknown;
	try {
		result = await app.call(toolName, callArgs, {
			approveConsequential: consentVal,
		});
	} catch (e) {
		return toolResult(
			app,
			reqId,
			e instanceof Error ? e.message : String(e),
			modern,
			true,
		);
	}

	// jsonCompact serializes undefined as "null" (Python json.dumps(None))
	// and BigInt values as bare integer tokens.
	return toolResult(app, reqId, jsonCompact(result), modern);
}

/** Dispatch one modern-era request: metadata, then version, then method. */
async function dispatchModern(
	app: AppImpl,
	reqId: unknown,
	method: string,
	params: JsonObject,
	meta: JsonObject,
): Promise<JsonObject> {
	const invalid = validateMeta(meta);
	if (invalid !== undefined) {
		return jsonrpcError(reqId, MCP_ERR_INVALID_PARAMS, invalid);
	}
	const version = meta[MCP_META_PROTOCOL_VERSION];
	if (version !== MCP_PROTOCOL_VERSION) {
		return jsonrpcError(
			reqId,
			MCP_ERR_UNSUPPORTED_PROTOCOL_VERSION,
			"Unsupported protocol version",
			{ supported: [MCP_PROTOCOL_VERSION], requested: version },
		);
	}
	if (method === "server/discover") {
		return handleDiscover(app, reqId);
	}
	if (method === "tools/list") {
		return handleToolsList(app, reqId, true);
	}
	if (method === "tools/call") {
		return await handleToolsCall(app, reqId, params, true);
	}
	return jsonrpcError(
		reqId,
		MCP_ERR_METHOD_NOT_FOUND,
		`Method not found: ${method}`,
	);
}

/** Dispatch one legacy-era request, unchanged from the handshake revision. */
async function dispatchLegacy(
	app: AppImpl,
	reqId: unknown,
	method: string,
	params: JsonObject,
): Promise<JsonObject> {
	if (method === "tools/list") {
		return handleToolsList(app, reqId, false);
	}
	if (method === "tools/call") {
		return await handleToolsCall(app, reqId, params, false);
	}
	return jsonrpcError(
		reqId,
		MCP_ERR_METHOD_NOT_FOUND,
		`Method not found: ${method}`,
	);
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

	// The one piece of connection state a dual-era server is allowed: an
	// `initialize` request selects legacy semantics for this process. Modern
	// requests carry everything they need and never consult it.
	let legacyEra = false;

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
			legacyEra = true;
			resp = handleInitialize(app, reqId);
		} else {
			const metaVal = params._meta;
			const present = Object.hasOwn(params, "_meta");
			if (present && !isPlainObject(metaVal)) {
				resp = jsonrpcError(
					reqId,
					MCP_ERR_INVALID_PARAMS,
					"parameter '_meta' must be an object",
				);
			} else if (
				isPlainObject(metaVal) &&
				Object.hasOwn(metaVal, MCP_META_PROTOCOL_VERSION)
			) {
				resp = await dispatchModern(
					app,
					reqId,
					String(method),
					params,
					metaVal,
				);
			} else if (legacyEra) {
				resp = await dispatchLegacy(app, reqId, String(method), params);
			} else {
				resp = jsonrpcError(
					reqId,
					MCP_ERR_INVALID_PARAMS,
					`missing required request metadata: _meta['${MCP_META_PROTOCOL_VERSION}']`,
				);
			}
		}
		write(resp);
	}
}
