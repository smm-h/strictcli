#!/usr/bin/env node
/**
 * Generates src/version.ts from package.json.
 *
 * package.json is the single source of truth for the package version. Before
 * this script existed, `VERSION` was a hand-written literal in src/index.ts and
 * a test pinned that literal, so the published constant drifted (it said
 * 0.31.0 while the package shipped 0.35.0) and the test kept the lie in place.
 *
 * Wiring: `prebuild` runs this before every `tsc`, and `prepack` runs
 * `npm run build`, so a packed tarball always carries the version its
 * package.json declares. src/version.ts is a build artifact (gitignored, like
 * dist/) -- it is never edited or committed, and tests/index.test.ts asserts
 * that VERSION and package.json agree.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const PKG = fileURLToPath(new URL("../package.json", import.meta.url));
const OUT = fileURLToPath(new URL("../src/version.ts", import.meta.url));

const pkg = JSON.parse(readFileSync(PKG, "utf8"));
const version = pkg.version;
if (typeof version !== "string" || version.length === 0) {
	throw new Error(`${PKG} declares no string "version" field`);
}
if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)*$/.test(version)) {
	throw new Error(`${PKG} version ${JSON.stringify(version)} is not semver`);
}

const contents = `/**
 * GENERATED FILE -- do not edit, and do not commit.
 *
 * Written by scripts/gen-version.mjs from package.json on every build (the
 * \`prebuild\` npm hook, which \`prepack\` inherits through \`npm run build\`).
 * package.json is the single source of truth for the package version.
 */

/** The current version of the strictcli TypeScript package. */
export const VERSION = ${JSON.stringify(version)};
`;

let existing;
try {
	existing = readFileSync(OUT, "utf8");
} catch {
	existing = undefined;
}
if (existing !== contents) {
	writeFileSync(OUT, contents);
	process.stdout.write(`gen-version: src/version.ts -> ${version}\n`);
}
