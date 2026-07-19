/**
 * TOML parsing and comment-preserving single-key editing for the config
 * subsystem.
 *
 * Parsing strategy (the TOML 1.0 acceptance gate): smol-toml is the value
 * parser but accepts TOML 1.1, while the siblings' parsers (go-toml-edit,
 * Python tomllib) are TOML-1.0-native. Every parse therefore first validates
 * the raw text with toml-eslint-parser in "1.0" mode -- a full spec-compliant
 * TOML 1.0 parser -- which reliably rejects the six 1.1-only constructs
 * pinned in ts-port-spec.md (backslash-e / backslash-x escapes in basic
 * strings, newlines and trailing commas in inline tables, times and datetimes
 * without seconds). When the 1.0 parse fails but a 1.1 parse succeeds, the
 * failure is classified into the specific gate error; otherwise the document
 * is genuinely malformed and the 1.0 parser's own message (with position) is
 * reported. Only after the gate passes does smol-toml produce the value tree
 * (with { integersAsBigInt: true }, so TOML integers are bigint end-to-end).
 *
 * Editing strategy (the single-key splicer): `config set` must preserve
 * comments, key order, whitespace, and line endings byte-exactly for
 * everything except the target key -- the tomlkit behavior Python relies on,
 * and the go-toml-edit round-trip behavior Go relies on. The splicer locates
 * the target value's byte range via the toml-eslint-parser AST and performs
 * string surgery: replace the value token in place, append new keys at the
 * end of the owning table's key block, or create a new [table] header at the
 * end of the document (both siblings append missing tables at document end).
 * Every splice is verified by re-parsing both versions and asserting that
 * only the target key changed -- a mismatch is a hard internal error.
 */

import { parse as smolParse, TomlError } from "smol-toml";
import type { AST } from "toml-eslint-parser";
import { parseTOML, ParseError as TomlAstParseError } from "toml-eslint-parser";
import {
	errTomlBasicStringEscape,
	errTomlDatetimeMissingSeconds,
	errTomlInlineTableNewline,
	errTomlInlineTableTrailingComma,
	errTomlSpliceKeyNotFound,
	errTomlSpliceVerifyFailed,
	errTomlTimeMissingSeconds,
} from "./errors.js";
import { formatFloatCanonical } from "./float.js";

// --- Load failures ---

/**
 * A TOML document failed to parse (or failed the 1.0 gate). line/column are
 * 1-based when known; config.ts formats them into the sibling-shaped
 * "config file <path>: <msg> (line X, column Y)" surface.
 */
export class TomlLoadFailure extends Error {
	readonly line: number | undefined;
	readonly column: number | undefined;

	constructor(message: string, line?: number, column?: number) {
		super(message);
		this.name = "TomlLoadFailure";
		this.line = line;
		this.column = column;
	}
}

// --- The TOML 1.0 acceptance gate ---

/** Datetime-flavored TOMLValue kinds (toml-eslint-parser vocabulary). */
const DATETIME_KINDS: ReadonlySet<string> = new Set([
	"offset-date-time",
	"local-date-time",
	"local-date",
	"local-time",
]);

/**
 * Walks the 1.1 AST for a datetime value whose range covers `index`; used to
 * classify a seconds-less time/datetime rejected by the 1.0 parse. Returns
 * the node's kind, or undefined when no datetime covers the position.
 */
function datetimeKindAt(
	program: AST.TOMLProgram,
	index: number,
): string | undefined {
	let found: string | undefined;
	const visitValue = (node: AST.TOMLContentNode): void => {
		if (found !== undefined) {
			return;
		}
		if (node.type === "TOMLValue") {
			if (
				DATETIME_KINDS.has(node.kind) &&
				node.range[0] <= index &&
				index <= node.range[1]
			) {
				found = node.kind;
			}
			return;
		}
		if (node.type === "TOMLArray") {
			for (const el of node.elements) {
				visitValue(el);
			}
			return;
		}
		if (node.type === "TOMLInlineTable") {
			for (const kv of node.body) {
				visitValue(kv.value);
			}
		}
	};
	const top = program.body[0];
	if (top === undefined) {
		return undefined;
	}
	for (const node of top.body) {
		if (node.type === "TOMLKeyValue") {
			visitValue(node.value);
		} else {
			for (const kv of node.body) {
				visitValue(kv.value);
			}
		}
	}
	return found;
}

/**
 * Classifies a 1.0-mode parse failure on a document that parses cleanly as
 * TOML 1.1 -- i.e. one of the 1.1-only constructs -- into the specific gate
 * message. Falls back to the raw 1.0 parser message for any 1.1 construct
 * outside the pinned six (still a hard reject; the gate never lets 1.1
 * documents through).
 */
function classifyGateFailure(
	text: string,
	err: TomlAstParseError,
	program11: AST.TOMLProgram,
): string {
	const msg = err.message;
	if (msg.includes("escape sequence")) {
		const ch = text[err.index] ?? "?";
		return errTomlBasicStringEscape(ch);
	}
	if (msg.includes("newlines") && msg.includes("curly braces")) {
		return errTomlInlineTableNewline();
	}
	if (msg.includes("Trailing comma")) {
		return errTomlInlineTableTrailingComma();
	}
	const kind = datetimeKindAt(program11, err.index);
	if (kind === "local-time") {
		return errTomlTimeMissingSeconds();
	}
	if (kind !== undefined) {
		return errTomlDatetimeMissingSeconds();
	}
	return msg;
}

/**
 * Validates `text` as TOML 1.0, throwing TomlLoadFailure for malformed
 * documents and for TOML-1.1-only constructs. Returns the 1.0 AST for reuse.
 */
function gateToml10(text: string): AST.TOMLProgram {
	try {
		return parseTOML(text, { tomlVersion: "1.0" });
	} catch (e) {
		if (!(e instanceof TomlAstParseError)) {
			throw e;
		}
		// toml-eslint-parser columns are 0-based; report 1-based like tomllib.
		const line = e.lineNumber;
		const column = e.column + 1;
		let program11: AST.TOMLProgram | undefined;
		try {
			program11 = parseTOML(text, { tomlVersion: "1.1" });
		} catch {
			// Malformed under 1.1 too: a genuine syntax error, not a gate hit.
			throw new TomlLoadFailure(e.message, line, column);
		}
		throw new TomlLoadFailure(
			classifyGateFailure(text, e, program11),
			line,
			column,
		);
	}
}

/**
 * Parses a TOML config document: TOML 1.0 gate first, then smol-toml with
 * integersAsBigInt (ints are bigint, floats are number). Throws
 * TomlLoadFailure with 1-based position info on any failure.
 */
export function parseTomlConfig(text: string): Record<string, unknown> {
	gateToml10(text);
	try {
		return smolParse(text, { integersAsBigInt: true });
	} catch (e) {
		if (e instanceof TomlError) {
			// First line only: smol-toml appends a multi-line codeblock.
			const firstLine = e.message.split("\n", 1)[0] ?? e.message;
			throw new TomlLoadFailure(firstLine, e.line, e.column);
		}
		throw e;
	}
}

// --- Value rendering (canonical scalar formatting) ---

/**
 * Renders a value as a TOML value token, mirroring Python's
 * _toml_format_scalar: bools lowercase, ints (bigint) decimal, floats in SCF,
 * strings basic-quoted. Beyond Python's backslash/quote escaping, control
 * characters are escaped too (Python would emit invalid TOML for them; the
 * splicer's re-parse verification demands valid output). Arrays render as
 * "[a, b]"; Maps and plain objects render as inline tables with sorted keys
 * (the TS dict display rule; semantically identical to tomlkit's section
 * tables, and splice-verified).
 */
export function renderTomlValue(value: unknown): string {
	if (typeof value === "boolean") {
		return value ? "true" : "false";
	}
	if (typeof value === "bigint") {
		return value.toString();
	}
	if (typeof value === "number") {
		return formatFloatCanonical(value);
	}
	if (typeof value === "string") {
		return renderTomlString(value);
	}
	if (Array.isArray(value)) {
		return `[${value.map(renderTomlValue).join(", ")}]`;
	}
	if (value instanceof Map) {
		return renderInlineTable(
			[...(value as Map<unknown, unknown>).entries()].map(
				([k, v]): [string, unknown] => [String(k), v],
			),
		);
	}
	if (typeof value === "object" && value !== null) {
		return renderInlineTable(Object.entries(value));
	}
	// Python's fallback stringifies unknown values as a quoted string.
	return renderTomlString(String(value));
}

function renderInlineTable(entries: [string, unknown][]): string {
	const sorted = [...entries].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
	if (sorted.length === 0) {
		return "{}";
	}
	const parts = sorted.map(
		([k, v]) => `${renderTomlKeyPart(k)} = ${renderTomlValue(v)}`,
	);
	return `{ ${parts.join(", ")} }`;
}

function renderTomlString(s: string): string {
	let out = '"';
	for (const ch of s) {
		const code = ch.codePointAt(0) as number;
		if (ch === "\\" || ch === '"') {
			out += `\\${ch}`;
		} else if (ch === "\n") {
			out += "\\n";
		} else if (ch === "\r") {
			out += "\\r";
		} else if (ch === "\t") {
			out += "\\t";
		} else if (code < 0x20 || code === 0x7f) {
			out += `\\u${code.toString(16).toUpperCase().padStart(4, "0")}`;
		} else {
			out += ch;
		}
	}
	return `${out}"`;
}

const BARE_KEY_RE = /^[A-Za-z0-9_-]+$/;

/** Renders one key segment: bare when possible, basic-quoted otherwise. */
export function renderTomlKeyPart(part: string): string {
	return BARE_KEY_RE.test(part) ? part : renderTomlString(part);
}

// --- Deep tree equality (shared by splice verification and config.ts) ---

/**
 * Deep equality over config value trees: bigint/number/string/boolean
 * scalars, arrays, Maps, and plain objects (Maps and objects compare
 * interchangeably by entries). Non-plain objects (e.g. TomlDate) compare by
 * String() form.
 */
export function deepEqualTrees(a: unknown, b: unknown): boolean {
	if (Object.is(a, b)) {
		return true;
	}
	if (Array.isArray(a) && Array.isArray(b)) {
		return a.length === b.length && a.every((v, i) => deepEqualTrees(v, b[i]));
	}
	const aEntries = treeEntries(a);
	const bEntries = treeEntries(b);
	if (aEntries !== undefined && bEntries !== undefined) {
		if (aEntries.size !== bEntries.size) {
			return false;
		}
		for (const [k, v] of aEntries) {
			if (!bEntries.has(k) || !deepEqualTrees(v, bEntries.get(k))) {
				return false;
			}
		}
		return true;
	}
	if (
		typeof a === "object" &&
		a !== null &&
		typeof b === "object" &&
		b !== null
	) {
		// Non-plain objects (TomlDate and friends): canonical string form.
		return String(a) === String(b);
	}
	return false;
}

/** Entries view of a Map or plain object; undefined for everything else. */
function treeEntries(v: unknown): Map<string, unknown> | undefined {
	if (v instanceof Map) {
		return new Map(
			[...(v as Map<unknown, unknown>).entries()].map(([k, val]) => [
				String(k),
				val,
			]),
		);
	}
	if (
		typeof v === "object" &&
		v !== null &&
		!Array.isArray(v) &&
		(Object.getPrototypeOf(v) === Object.prototype ||
			Object.getPrototypeOf(v) === null)
	) {
		return new Map(Object.entries(v));
	}
	return undefined;
}

// --- AST navigation for the splicer ---

/** A key block that can own key-value pairs: the root, a [table], or an inline table. */
interface Container {
	/** Resolved dotted path of the container ([] for the root block). */
	readonly path: readonly string[];
	readonly kind: "root" | "table";
	readonly kvs: readonly AST.TOMLKeyValue[];
	/** The [table] node (absent for the root block). */
	readonly tableNode?: AST.TOMLTable;
}

function keySegments(key: AST.TOMLKey): string[] {
	return key.keys.map((k) =>
		k.type === "TOMLBare" ? k.name : String(k.value),
	);
}

function collectContainers(program: AST.TOMLProgram): {
	containers: Container[];
	firstTableStart: number | undefined;
} {
	const top = program.body[0];
	const rootKvs: AST.TOMLKeyValue[] = [];
	const containers: Container[] = [];
	let firstTableStart: number | undefined;
	if (top !== undefined) {
		for (const node of top.body) {
			if (node.type === "TOMLKeyValue") {
				rootKvs.push(node);
			} else {
				if (firstTableStart === undefined) {
					firstTableStart = node.range[0];
				}
				// Array-of-tables entries have numeric resolvedKey segments; the
				// config model never uses them, so they are unreachable targets.
				if (node.resolvedKey.every((s) => typeof s === "string")) {
					containers.push({
						path: node.resolvedKey as string[],
						kind: "table",
						kvs: node.body,
						tableNode: node,
					});
				}
			}
		}
	}
	containers.unshift({ path: [], kind: "root", kvs: rootKvs });
	return { containers, firstTableStart };
}

function pathsEqual(a: readonly string[], b: readonly string[]): boolean {
	return a.length === b.length && a.every((s, i) => s === b[i]);
}

function isPrefix(prefix: readonly string[], full: readonly string[]): boolean {
	return prefix.length <= full.length && prefix.every((s, i) => s === full[i]);
}

/** A located target: either a leaf value or the inline table that owns the rest of the path. */
interface Located {
	readonly kind: "leaf" | "inline-parent";
	/** For "leaf": the value node to replace. For "inline-parent": the inline table. */
	readonly node: AST.TOMLContentNode;
	/** The KeyValue that (transitively) owns the node, and its container. */
	readonly ownerKv: AST.TOMLKeyValue;
	readonly container: Container;
	/** For "inline-parent": remaining key segments to create inside it. */
	readonly remaining: readonly string[];
	/** For leaves inside inline tables: the chain of inline tables walked. */
	readonly inlineChain: readonly AST.TOMLInlineTable[];
	/** For leaves inside inline tables: the entry KeyValue inside the innermost table. */
	readonly inlineEntry?: AST.TOMLKeyValue;
}

/**
 * Finds the target path in the document: an exact leaf (value to replace or
 * delete), or the deepest inline table on the path (for insertion inside it).
 * Returns undefined when neither exists.
 */
function locate(
	containers: readonly Container[],
	parts: readonly string[],
): Located | undefined {
	let inlineParent: Located | undefined;
	for (const container of containers) {
		if (!isPrefix(container.path, parts)) {
			continue;
		}
		for (const kv of container.kvs) {
			const full = [...container.path, ...keySegments(kv.key)];
			if (pathsEqual(full, parts)) {
				return {
					kind: "leaf",
					node: kv.value,
					ownerKv: kv,
					container,
					remaining: [],
					inlineChain: [],
				};
			}
			if (isPrefix(full, parts) && kv.value.type === "TOMLInlineTable") {
				const walked = walkInline(
					kv.value,
					parts.slice(full.length),
					kv,
					container,
				);
				if (walked !== undefined) {
					if (walked.kind === "leaf") {
						return walked;
					}
					inlineParent = walked;
				}
			}
		}
	}
	return inlineParent;
}

/** Descends into an inline table looking for the remaining path segments. */
function walkInline(
	table: AST.TOMLInlineTable,
	remaining: readonly string[],
	ownerKv: AST.TOMLKeyValue,
	container: Container,
	chain: readonly AST.TOMLInlineTable[] = [],
): Located | undefined {
	const fullChain = [...chain, table];
	for (const kv of table.body) {
		const segs = keySegments(kv.key);
		if (pathsEqual(segs, remaining)) {
			return {
				kind: "leaf",
				node: kv.value,
				ownerKv,
				container,
				remaining: [],
				inlineChain: fullChain,
				inlineEntry: kv,
			};
		}
		if (isPrefix(segs, remaining) && kv.value.type === "TOMLInlineTable") {
			const walked = walkInline(
				kv.value,
				remaining.slice(segs.length),
				ownerKv,
				container,
				fullChain,
			);
			if (walked !== undefined) {
				return walked;
			}
		}
	}
	// Not found among entries: this table is the insertion parent.
	return {
		kind: "inline-parent",
		node: table,
		ownerKv,
		container,
		remaining,
		inlineChain: fullChain,
	};
}

// --- Line / EOL helpers ---

function eolOf(text: string): string {
	return text.includes("\r\n") ? "\r\n" : "\n";
}

/** Offset of the start of the line containing `index`. */
function lineStart(text: string, index: number): number {
	const nl = text.lastIndexOf("\n", index - 1);
	return nl === -1 ? 0 : nl + 1;
}

/** Offset just past the end of the line containing `index` (past the newline). */
function lineEnd(text: string, index: number): number {
	const nl = text.indexOf("\n", index);
	return nl === -1 ? text.length : nl + 1;
}

// --- Nested plain-object helpers (splice verification model) ---

function cloneTree(v: unknown): unknown {
	if (Array.isArray(v)) {
		return v.map(cloneTree);
	}
	const entries = treeEntries(v);
	if (entries !== undefined && !(v instanceof Map)) {
		const out: Record<string, unknown> = {};
		for (const [k, val] of entries) {
			out[k] = cloneTree(val);
		}
		return out;
	}
	if (v instanceof Map) {
		const out: Record<string, unknown> = {};
		for (const [k, val] of v as Map<unknown, unknown>) {
			out[String(k)] = cloneTree(val);
		}
		return out;
	}
	return v;
}

function nestedSetTree(
	data: Record<string, unknown>,
	parts: readonly string[],
	value: unknown,
): void {
	let current = data;
	for (const part of parts.slice(0, -1)) {
		const next = current[part];
		if (
			typeof next !== "object" ||
			next === null ||
			Array.isArray(next) ||
			next instanceof Map
		) {
			const created: Record<string, unknown> = {};
			current[part] = created;
			current = created;
		} else {
			current = next as Record<string, unknown>;
		}
	}
	current[parts[parts.length - 1] as string] = value;
}

function nestedDeleteTree(
	data: Record<string, unknown>,
	parts: readonly string[],
): boolean {
	const parents: [Record<string, unknown>, string][] = [];
	let current = data;
	for (const part of parts.slice(0, -1)) {
		const next = current[part];
		if (typeof next !== "object" || next === null || Array.isArray(next)) {
			return false;
		}
		parents.push([current, part]);
		current = next as Record<string, unknown>;
	}
	const last = parts[parts.length - 1] as string;
	if (!Object.hasOwn(current, last)) {
		return false;
	}
	delete current[last];
	for (let i = parents.length - 1; i >= 0; i--) {
		const [parent, key] = parents[i] as [Record<string, unknown>, string];
		const child = parent[key] as Record<string, unknown>;
		if (Object.keys(child).length === 0) {
			delete parent[key];
		}
	}
	return true;
}

// --- Splice verification ---

function verifySplice(
	oldText: string,
	newText: string,
	parts: readonly string[],
	op: { readonly set: unknown } | { readonly remove: true },
): void {
	const before =
		oldText.trim() === ""
			? {}
			: (cloneTree(parseTomlConfig(oldText)) as Record<string, unknown>);
	const after = parseTomlConfig(newText);
	if ("set" in op) {
		nestedSetTree(before, parts, cloneTree(op.set));
	} else {
		nestedDeleteTree(before, parts);
	}
	if (!deepEqualTrees(after, before)) {
		throw new Error(errTomlSpliceVerifyFailed(parts.join(".")));
	}
}

// --- The single-key splicer ---

/**
 * Sets `dottedKey` = `value` in the TOML document `text`, preserving all
 * other bytes exactly. Resolution order: replace an existing value token in
 * place (including inside inline tables); append `key = value` at the end of
 * the owning table's key block; append a dotted key when the parent exists
 * only implicitly via dotted keys; otherwise create a new [parent] header at
 * the end of the document (both siblings append missing tables at document
 * end). The result is verified by re-parsing both versions.
 */
export function tomlSetKey(
	text: string,
	dottedKey: string,
	value: unknown,
): string {
	const parts = dottedKey.split(".");
	const program = gateToml10(text);
	const { containers, firstTableStart } = collectContainers(program);
	const eol = eolOf(text);
	const rendered = renderTomlValue(value);
	const located = locate(containers, parts);

	let result: string;
	if (located?.kind === "leaf") {
		const [vs, ve] = located.node.range;
		result = text.slice(0, vs) + rendered + text.slice(ve);
	} else if (located?.kind === "inline-parent") {
		const table = located.node as AST.TOMLInlineTable;
		const keyStr = located.remaining.map(renderTomlKeyPart).join(".");
		const entry = `${keyStr} = ${rendered}`;
		const [ts, te] = table.range;
		if (table.body.length === 0) {
			result = `${text.slice(0, ts)}{ ${entry} }${text.slice(te)}`;
		} else {
			const lastKv = table.body[table.body.length - 1] as AST.TOMLKeyValue;
			const at = lastKv.range[1];
			result = `${text.slice(0, at)}, ${entry}${text.slice(at)}`;
		}
	} else {
		result = insertNewKey(
			text,
			containers,
			firstTableStart,
			parts,
			rendered,
			eol,
		);
	}
	verifySplice(text, result, parts, { set: value });
	return result;
}

/** Insertion path for a key that does not exist anywhere on its path. */
function insertNewKey(
	text: string,
	containers: readonly Container[],
	firstTableStart: number | undefined,
	parts: readonly string[],
	rendered: string,
	eol: string,
): string {
	const parent = parts.slice(0, -1);
	// Longest container whose path prefixes the parent path.
	let best: Container = containers[0] as Container; // root always present
	for (const c of containers) {
		if (isPrefix(c.path, parent) && c.path.length > best.path.length) {
			best = c;
		}
	}
	const rel = parts.slice(best.path.length);
	const relParent = rel.slice(0, -1);

	if (relParent.length === 0) {
		// Direct child of an existing key block.
		const line = `${renderTomlKeyPart(rel[0] as string)} = ${rendered}${eol}`;
		return insertLineInContainer(text, best, firstTableStart, line, eol);
	}

	// Parent path only exists implicitly via dotted keys in this container?
	const dottedConflict = best.kvs.some(
		(kv) => keySegments(kv.key)[0] === relParent[0],
	);
	if (dottedConflict) {
		// A [header] for the parent would redefine a dotted-key table; append a
		// dotted key-value in the same block instead.
		const line = `${rel.map(renderTomlKeyPart).join(".")} = ${rendered}${eol}`;
		return insertLineInContainer(text, best, firstTableStart, line, eol);
	}

	// Create a new [parent] header at the end of the document.
	const header = `[${parent.map(renderTomlKeyPart).join(".")}]`;
	const leaf = `${renderTomlKeyPart(parts[parts.length - 1] as string)} = ${rendered}`;
	let base = text;
	if (base !== "" && !base.endsWith("\n")) {
		base += eol;
	}
	const sep = base === "" ? "" : eol;
	return `${base}${sep}${header}${eol}${leaf}${eol}`;
}

/** Appends a `key = value` line at the end of a container's key block. */
function insertLineInContainer(
	text: string,
	container: Container,
	firstTableStart: number | undefined,
	line: string,
	eol: string,
): string {
	if (container.kvs.length > 0) {
		const lastKv = container.kvs[container.kvs.length - 1] as AST.TOMLKeyValue;
		const at = lineEnd(text, lastKv.range[1]);
		const head = text.slice(0, at);
		// A last line without a newline (EOF) gets terminated first.
		const terminator = head.endsWith("\n") ? "" : eol;
		return head + terminator + line + text.slice(at);
	}
	if (container.kind === "table" && container.tableNode !== undefined) {
		// Empty table: insert right after the header line.
		const at = lineEnd(text, container.tableNode.range[0]);
		let insert = line;
		if (!text.slice(0, at).endsWith("\n")) {
			insert = eol + line;
		}
		return text.slice(0, at) + insert + text.slice(at);
	}
	// Empty root block: before the first table header, else at end of document.
	if (firstTableStart !== undefined) {
		const at = lineStart(text, firstTableStart);
		return text.slice(0, at) + line + text.slice(at);
	}
	let base = text;
	if (base !== "" && !base.endsWith("\n")) {
		base += eol;
	}
	return base + line;
}

/**
 * Deletes `dottedKey` from the TOML document `text`, removing the key's whole
 * line (with any trailing comment, matching tomlkit) and pruning a [table]
 * header left with no keys. Entries inside inline tables are removed with
 * their separating comma; an inline table left empty is deleted with its own
 * key. Throws when the key is not present (callers check the parsed data
 * first). The result is verified by re-parsing both versions.
 */
export function tomlDeleteKey(text: string, dottedKey: string): string {
	const parts = dottedKey.split(".");
	const program = gateToml10(text);
	const { containers } = collectContainers(program);
	const located = locate(containers, parts);
	if (located === undefined || located.kind !== "leaf") {
		throw new Error(errTomlSpliceKeyNotFound(dottedKey));
	}

	let result: string;
	if (located.inlineEntry !== undefined) {
		result = deleteInlineEntry(text, located);
	} else {
		// Remove the key-value's whole line.
		const start = lineStart(text, located.ownerKv.range[0]);
		const end = lineEnd(text, located.ownerKv.range[1]);
		result = text.slice(0, start) + text.slice(end);
		// Prune the [table] header when the table has no keys left.
		if (
			located.container.kind === "table" &&
			located.container.kvs.length === 1 &&
			located.container.tableNode !== undefined
		) {
			const hs = lineStart(result, located.container.tableNode.range[0]);
			const he = lineEnd(result, located.container.tableNode.range[0]);
			result = result.slice(0, hs) + result.slice(he);
		}
	}
	verifySplice(text, result, parts, { remove: true });
	return result;
}

/** Removes one entry (with its comma) from the innermost inline table. */
function deleteInlineEntry(text: string, located: Located): string {
	const table = located.inlineChain[
		located.inlineChain.length - 1
	] as AST.TOMLInlineTable;
	const entry = located.inlineEntry as AST.TOMLKeyValue;
	if (table.body.length === 1) {
		// The inline table becomes empty: delete the owning key's whole line
		// (the tomlkit empty-container prune, one level).
		const start = lineStart(text, located.ownerKv.range[0]);
		const end = lineEnd(text, located.ownerKv.range[1]);
		return text.slice(0, start) + text.slice(end);
	}
	const idx = table.body.indexOf(entry);
	if (idx < table.body.length - 1) {
		const next = table.body[idx + 1] as AST.TOMLKeyValue;
		return text.slice(0, entry.range[0]) + text.slice(next.range[0]);
	}
	const prev = table.body[idx - 1] as AST.TOMLKeyValue;
	return text.slice(0, prev.range[1]) + text.slice(entry.range[1]);
}
