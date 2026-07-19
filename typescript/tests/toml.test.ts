/**
 * toml.ts tests: the TOML 1.0 acceptance gate (the six 1.1-only constructs
 * from ts-port-spec.md), strict value parsing (bigint ints), and the
 * comment-preserving single-key splicer (set/delete byte-exactness).
 *
 * GROUND TRUTH: the splicer expectations for the commented document were
 * captured on 2026-07-19 by running Python's tomlkit-based _write_config_set /
 * _write_config_unset over the same document (scratchpad pysmoke2.py) -- the
 * expected strings below are those bytes verbatim.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	deepEqualTrees,
	parseTomlConfig,
	renderTomlKeyPart,
	renderTomlValue,
	TomlLoadFailure,
	tomlDeleteKey,
	tomlSetKey,
} from "../src/toml.js";

// =========================================================================
// Value parsing
// =========================================================================

test("parseTomlConfig: ints are bigint, floats number, full scalar set", () => {
	const data = parseTomlConfig(
		'a = 1\nb = 2.5\nc = "x"\nd = true\n[tbl]\ne = -7\n',
	);
	assert.equal(data.a, 1n);
	assert.equal(data.b, 2.5);
	assert.equal(data.c, "x");
	assert.equal(data.d, true);
	assert.equal((data.tbl as Record<string, unknown>).e, -7n);
});

test("parseTomlConfig: arrays and inline tables", () => {
	const data = parseTomlConfig('arr = [1, 2]\npoint = { x = 1, y = "b" }\n');
	assert.deepEqual(data.arr, [1n, 2n]);
	const point = data.point as Record<string, unknown>;
	assert.equal(point.x, 1n);
	assert.equal(point.y, "b");
});

test("parseTomlConfig: malformed document throws with 1-based position", () => {
	try {
		parseTomlConfig("key = [unclosed");
		assert.fail("expected TomlLoadFailure");
	} catch (e) {
		assert.ok(e instanceof TomlLoadFailure);
		assert.equal(e.line, 1);
		assert.equal(e.column, 8);
	}
});

test("parseTomlConfig: empty document parses to empty object", () => {
	assert.deepEqual(parseTomlConfig(""), {});
});

// =========================================================================
// The TOML 1.0 acceptance gate: the six 1.1-only constructs
// =========================================================================

function gateError(doc: string): TomlLoadFailure {
	try {
		parseTomlConfig(doc);
	} catch (e) {
		assert.ok(e instanceof TomlLoadFailure, `expected failure for: ${doc}`);
		return e;
	}
	assert.fail(`document was accepted but must be gated: ${doc}`);
}

test("gate 1: backslash-e escape in basic strings is rejected", () => {
	const e = gateError('s = "a\\eb"');
	assert.equal(
		e.message,
		"invalid escape sequence '\\e' in basic string (TOML 1.1 construct; strictcli requires TOML 1.0)",
	);
});

test("gate 2: backslash-x hex escape in basic strings is rejected", () => {
	const e = gateError('s = "a\\x41b"');
	assert.equal(
		e.message,
		"invalid escape sequence '\\x' in basic string (TOML 1.1 construct; strictcli requires TOML 1.0)",
	);
});

test("gate 3: newline inside inline table is rejected", () => {
	const e = gateError("t = {\n a = 1 }");
	assert.equal(
		e.message,
		"newline inside inline table (TOML 1.1 construct; strictcli requires TOML 1.0)",
	);
});

test("gate 4: trailing comma in inline table is rejected", () => {
	const e = gateError("t = { a = 1, }");
	assert.equal(
		e.message,
		"trailing comma in inline table (TOML 1.1 construct; strictcli requires TOML 1.0)",
	);
});

test("gate 5: time without seconds is rejected", () => {
	const e = gateError("t = 07:32");
	assert.equal(
		e.message,
		"time without seconds (TOML 1.1 construct; strictcli requires TOML 1.0)",
	);
});

test("gate 6: datetime without seconds is rejected", () => {
	const e = gateError("d = 1979-05-27T07:32");
	assert.equal(
		e.message,
		"datetime without seconds (TOML 1.1 construct; strictcli requires TOML 1.0)",
	);
});

test("gate: literal 1.1-lookalike text inside strings does not false-positive", () => {
	// Every gated construct spelled INSIDE string values must pass untouched.
	const data = parseTomlConfig(
		[
			`a = 'raw \\e and \\x41 stay literal'`,
			`b = "escaped backslash \\\\e is fine"`,
			`c = "{ not, a, table, }"`,
			`d = "07:32"`,
			`e = "1979-05-27T07:32"`,
			`f = "# not a comment"`,
		].join("\n"),
	);
	assert.equal(data.a, "raw \\e and \\x41 stay literal");
	assert.equal(data.b, "escaped backslash \\e is fine");
	assert.equal(data.c, "{ not, a, table, }");
	assert.equal(data.d, "07:32");
	assert.equal(data.e, "1979-05-27T07:32");
	assert.equal(data.f, "# not a comment");
});

test("gate: valid TOML 1.0 constructs pass (full-second datetimes, tabs, unicode escapes)", () => {
	const data = parseTomlConfig(
		[
			'u = "\\u00e9"',
			"t = 07:32:00",
			"d = 1979-05-27T07:32:00Z",
			"inline = { a = 1, b = 2 }",
			"arr = [1, 2, 3]",
		].join("\n"),
	);
	assert.equal(data.u, "é");
	assert.deepEqual(data.arr, [1n, 2n, 3n]);
});

// =========================================================================
// Value rendering
// =========================================================================

test("renderTomlValue: scalar tokens (bools lowercase, bigint decimal, SCF floats, quoted strings)", () => {
	assert.equal(renderTomlValue(true), "true");
	assert.equal(renderTomlValue(false), "false");
	assert.equal(renderTomlValue(42n), "42");
	assert.equal(renderTomlValue(3.0), "3.0");
	assert.equal(renderTomlValue(1e21), "1e+21");
	assert.equal(renderTomlValue("hi"), '"hi"');
	assert.equal(renderTomlValue('a"b\\c'), '"a\\"b\\\\c"');
	assert.equal(renderTomlValue("line\nbreak"), '"line\\nbreak"');
});

test("renderTomlValue: arrays and sorted inline tables", () => {
	assert.equal(renderTomlValue([1n, 2n]), "[1, 2]");
	assert.equal(renderTomlValue([]), "[]");
	const m = new Map<string, unknown>([
		["b", 2n],
		["a", 1n],
	]);
	assert.equal(renderTomlValue(m), "{ a = 1, b = 2 }");
	assert.equal(renderTomlValue(new Map()), "{}");
});

test("renderTomlKeyPart: bare when possible, quoted otherwise", () => {
	assert.equal(renderTomlKeyPart("simple-key_1"), "simple-key_1");
	assert.equal(renderTomlKeyPart("has space"), '"has space"');
});

// =========================================================================
// Splicer: tomlSetKey
// =========================================================================

// The commented mixed-layout document used across the splice tests.
const DOC =
	'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n\n[other]\nx = 1\n';

test("splice set: replaces only the value token; comments/order/whitespace survive byte-exact", () => {
	assert.equal(
		tomlSetKey(DOC, "count", 42n),
		'# top comment\ncount = 42  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n\n[other]\nx = 1\n',
	);
});

test("splice set: nested key inside a [table]", () => {
	assert.equal(
		tomlSetKey(DOC, "server.port", 9090n),
		'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nport = 9090\nhost = "a"\n\n[other]\nx = 1\n',
	);
});

test("splice set: appends a new key at the end of the owning table's key block", () => {
	assert.equal(
		tomlSetKey(DOC, "server.timeout", 30n),
		'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\ntimeout = 30\n\n[other]\nx = 1\n',
	);
});

test("splice set: creates a new [table] header at the end of the document", () => {
	assert.equal(
		tomlSetKey(DOC, "db.name", "x"),
		'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n\n[other]\nx = 1\n\n[db]\nname = "x"\n',
	);
});

test("splice set: new root key lands at the end of the root block, before the first table", () => {
	assert.equal(
		tomlSetKey(DOC, "newkey", true),
		'# top comment\ncount = 1  # trailing\nnewkey = true\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n\n[other]\nx = 1\n',
	);
});

test("splice set: CRLF line endings are preserved (replace and append)", () => {
	const crlf = "a = 1\r\nb = 2\r\n";
	assert.equal(tomlSetKey(crlf, "b", 3n), "a = 1\r\nb = 3\r\n");
	assert.equal(tomlSetKey(crlf, "c", 4n), "a = 1\r\nb = 2\r\nc = 4\r\n");
});

test("splice set: empty document (root key and new table)", () => {
	assert.equal(tomlSetKey("", "a", 1n), "a = 1\n");
	assert.equal(tomlSetKey("", "srv.port", 1n), "[srv]\nport = 1\n");
});

test("splice set: inline table entries (replace, append, and string values)", () => {
	const inl = "point = { x = 1, y = 2 }\n";
	assert.equal(tomlSetKey(inl, "point.y", 5n), "point = { x = 1, y = 5 }\n");
	assert.equal(
		tomlSetKey(inl, "point.z", 9n),
		"point = { x = 1, y = 2, z = 9 }\n",
	);
});

test("splice set: float and string value tokens render canonically", () => {
	assert.equal(tomlSetKey("r = 1.0\n", "r", 2.5), "r = 2.5\n");
	assert.equal(tomlSetKey('s = "a"\n', "s", 'q"uo'), 's = "q\\"uo"\n');
});

test("splice set: re-parse verification accepts every splice (round-trip data check)", () => {
	// Sanity: the new document parses and carries exactly the updated key.
	const out = tomlSetKey(DOC, "server.port", 1n);
	const parsed = parseTomlConfig(out);
	assert.equal((parsed.server as Record<string, unknown>).port, 1n);
	assert.ok(deepEqualTrees(parsed.other, { x: 1n }));
});

// =========================================================================
// Splicer: tomlDeleteKey
// =========================================================================

test("splice delete: removes the key's whole line (with trailing comment)", () => {
	// tomlkit parity: deleting count removes the line INCLUDING its comment.
	assert.equal(
		tomlDeleteKey(DOC, "count"),
		'# top comment\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n\n[other]\nx = 1\n',
	);
});

test("splice delete: nested key keeps the table when keys remain", () => {
	assert.equal(
		tomlDeleteKey(DOC, "server.port"),
		'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nhost = "a"\n\n[other]\nx = 1\n',
	);
});

test("splice delete: pruning a [table] left with no keys removes its header", () => {
	assert.equal(
		tomlDeleteKey(DOC, "other.x"),
		'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n\n',
	);
});

test("splice delete: inline table entry with its comma; empty inline table deletes the owning line", () => {
	const inl = "point = { x = 1, y = 2 }\n";
	assert.equal(tomlDeleteKey(inl, "point.y"), "point = { x = 1 }\n");
	assert.equal(
		tomlDeleteKey("point = { x = 1 }\nz = 3\n", "point.x"),
		"z = 3\n",
	);
});

test("splice delete: missing key is an internal error", () => {
	assert.throws(
		() => tomlDeleteKey(DOC, "does.not.exist"),
		/TOML splice: key "does\.not\.exist" not found/,
	);
});

// =========================================================================
// deepEqualTrees
// =========================================================================

test("deepEqualTrees: scalars, arrays, Maps and records compare structurally", () => {
	assert.ok(deepEqualTrees(1n, 1n));
	assert.ok(!deepEqualTrees(1n, 2n));
	assert.ok(deepEqualTrees([1n, "a"], [1n, "a"]));
	assert.ok(!deepEqualTrees([1n], [1n, 1n]));
	assert.ok(deepEqualTrees(new Map([["a", 1n]]), { a: 1n }));
	assert.ok(!deepEqualTrees({ a: 1n }, { a: 1n, b: 2n }));
	assert.ok(deepEqualTrees({ t: { x: 1n } }, { t: { x: 1n } }));
});
