import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { VERSION } from "../src/index.js";

/**
 * package.json is the single source of truth for the package version; VERSION
 * is generated from it by scripts/gen-version.mjs on every build (the
 * `prebuild` hook, which `prepack` inherits). This test asserts the agreement
 * rather than pinning a literal -- a pinned literal is what let the published
 * constant say 0.31.0 while the package shipped 0.35.0.
 */
function packageVersion(): string {
	const raw = readFileSync(
		new URL("../../package.json", import.meta.url),
		"utf8",
	);
	const pkg = JSON.parse(raw) as { version?: unknown };
	assert.equal(
		typeof pkg.version,
		"string",
		"package.json must declare a string version",
	);
	return pkg.version as string;
}

test("VERSION agrees with the package.json version", () => {
	assert.equal(VERSION, packageVersion());
});
