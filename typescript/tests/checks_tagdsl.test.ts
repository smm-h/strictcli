/**
 * Tag DSL tests: operator semantics, precedence (! > & > ^ > | > -),
 * parentheses, and byte-offset error positions.
 *
 * GROUND TRUTH: error bytes captured on 2026-07-19 from the Python
 * implementation (_tagdsl_*); semantics cross-checked against
 * go/strictcli/tagdsl.go.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { globToRegExp } from "../src/checks/runner.js";
import { matchTagExpr } from "../src/checks/tagdsl.js";

function m(expr: string, tags: readonly string[]): boolean {
	return matchTagExpr(expr, new Set(tags));
}

test("tagdsl: identifiers and simple operators", () => {
	assert.equal(m("a", ["a"]), true);
	assert.equal(m("a", ["b"]), false);
	assert.equal(m("!a", ["a"]), false);
	assert.equal(m("!a", []), true);
	assert.equal(m("a & b", ["a", "b"]), true);
	assert.equal(m("a & b", ["a"]), false);
	assert.equal(m("a | b", ["b"]), true);
	assert.equal(m("a | b", []), false);
	assert.equal(m("a ^ b", ["a"]), true);
	assert.equal(m("a ^ b", ["a", "b"]), false);
	assert.equal(m("a - b", ["a"]), true);
	assert.equal(m("a - b", ["a", "b"]), false);
});

test("tagdsl: identifier names may contain digits and hyphens", () => {
	assert.equal(m("pre-push", ["pre-push"]), true);
	assert.equal(m("t2", ["t2"]), true);
	// A hyphen continuing an identifier is part of the name, not DIFF.
	assert.equal(m("a-b", ["a"]), false);
	assert.equal(m("a-b", ["a-b"]), true);
	// Whitespace separates: now it IS a - b.
	assert.equal(m("a - b", ["a"]), true);
});

test("tagdsl: precedence tightest-first NOT, AND, XOR, OR, DIFF", () => {
	// a | b & c == a | (b & c)
	assert.equal(m("a | b & c", ["b"]), false);
	assert.equal(m("a | b & c", ["b", "c"]), true);
	assert.equal(m("a | b & c", ["a"]), true);
	// !a & b == (!a) & b
	assert.equal(m("!a & b", ["b"]), true);
	assert.equal(m("!a & b", ["a", "b"]), false);
	// a ^ b | c == (a ^ b) | c
	assert.equal(m("a ^ b | c", ["a", "b", "c"]), true);
	assert.equal(m("a ^ b | c", ["a", "b"]), false);
	// a - b | c == a - (b | c)
	assert.equal(m("a - b | c", ["a", "c"]), false);
	assert.equal(m("a - b | c", ["a"]), true);
	// Conformance example: (release | changelog) & !slow
	assert.equal(m("(release | changelog) & !slow", ["changelog"]), true);
	assert.equal(m("(release | changelog) & !slow", ["release", "slow"]), false);
});

test("tagdsl: parentheses override precedence", () => {
	assert.equal(m("(a | b) & c", ["a"]), false);
	assert.equal(m("(a | b) & c", ["a", "c"]), true);
	assert.equal(m("!(a & b)", ["a"]), true);
	assert.equal(m("!(a & b)", ["a", "b"]), false);
	assert.equal(m("(a - b) | c", ["c"]), true);
});

test("tagdsl: double negation and chained operators", () => {
	assert.equal(m("!!a", ["a"]), true);
	assert.equal(m("a & b & c", ["a", "b", "c"]), true);
	assert.equal(m("a & b & c", ["a", "b"]), false);
	assert.equal(m("a - b - c", ["a", "c"]), false);
});

test("tagdsl: error bytes and positions", () => {
	assert.throws(() => m("9bad", []), {
		message: 'tag expression: unexpected character "9" at position 0',
	});
	assert.throws(() => m("x &", []), {
		message: "tag expression: unexpected end of expression at position 3",
	});
	assert.throws(() => m("(a", []), {
		message: 'tag expression: expected ")" at position 2',
	});
	assert.throws(() => m("a b", []), {
		message: 'tag expression: unexpected token "b" at position 2',
	});
	assert.throws(() => m(")", []), {
		message: 'tag expression: unexpected token ")" at position 0',
	});
	assert.throws(() => m("", []), {
		message: "tag expression: empty expression",
	});
	assert.throws(() => m("   ", []), {
		message: "tag expression: empty expression",
	});
	// Uppercase is not a valid identifier start.
	assert.throws(() => m("Bad", []), {
		message: 'tag expression: unexpected character "B" at position 0',
	});
});

// --- Name globs (fnmatch semantics; Python is the divergence ground truth) ---

test("glob: fnmatch star, question mark, and character classes", () => {
	assert.equal(globToRegExp("lin*").test("lint"), true);
	assert.equal(globToRegExp("lin*").test("format"), false);
	assert.equal(globToRegExp("*coverage*").test("cli-test-coverage"), true);
	assert.equal(globToRegExp("hash-*").test("hash-resolution"), true);
	assert.equal(globToRegExp("?int").test("lint"), true);
	assert.equal(globToRegExp("?int").test("mint"), true);
	assert.equal(globToRegExp("?int").test("print"), false);
	assert.equal(globToRegExp("[lm]int").test("lint"), true);
	assert.equal(globToRegExp("[lm]int").test("pint"), false);
	assert.equal(globToRegExp("[!l]int").test("mint"), true);
	assert.equal(globToRegExp("[!l]int").test("lint"), false);
	// Unterminated "[" is a literal (fnmatch never errors).
	assert.equal(globToRegExp("a[b").test("a[b"), true);
	// Exact names match themselves; regex metacharacters are escaped.
	assert.equal(globToRegExp("a.b").test("a.b"), true);
	assert.equal(globToRegExp("a.b").test("axb"), false);
});
