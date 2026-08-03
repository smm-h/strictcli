#!/usr/bin/env node
/**
 * Mechanical sweep for the effects regime's breaking registration change.
 *
 * `defineCommand` and `passthrough` are REMOVED from the TS surface: the twin
 * factories `defineReadOnlyCommand`/`defineMutatingCommand` and
 * `readOnlyPassthrough`/`mutatingPassthrough` are the only mint, because
 * classification is mandatory and has no default.
 *
 * Every registration in the test suite therefore has to be reclassified. The
 * overwhelming majority of the suite exercises parsing, help rendering, routing
 * and schema shape -- none of which touches the effects handle -- so the sweep
 * rewrites them to the read-only twin, which is the conservative choice (a
 * read-only command cannot reach a mutating effect at all). The handful of
 * registrations that genuinely need `mutating` are reclassified by hand
 * afterwards.
 *
 * Committed rather than run inline so the transformation is reviewable and
 * repeatable.
 *
 * Usage: node scripts/sweep_twin_factories.mjs <file>...
 */

import { readFileSync, writeFileSync } from "node:fs";

/** Ordered rewrite rules. Each is [pattern, replacement]. */
const RULES = [
	// Call sites and namespace-qualified references.
	[/(?<![A-Za-z0-9_$.])defineCommand(?=[({<]|,|\s*}|\s*from)/g, "defineReadOnlyCommand"],
	[/\bapi\.defineCommand\b/g, "api.defineReadOnlyCommand"],
	[/(?<![A-Za-z0-9_$.])passthrough\(/g, "readOnlyPassthrough("],
	[/\bapi\.passthrough\b/g, "api.readOnlyPassthrough"],
	// Import specifiers (bare, on their own line in a multi-line import list).
	[/^(\s*)defineCommand,$/gm, "$1defineReadOnlyCommand,"],
	[/^(\s*)passthrough,$/gm, "$1readOnlyPassthrough,"],
];

let changed = 0;
for (const path of process.argv.slice(2)) {
	const before = readFileSync(path, "utf8");
	let after = before;
	for (const [pattern, replacement] of RULES) {
		after = after.replace(pattern, replacement);
	}
	if (after !== before) {
		writeFileSync(path, after);
		changed++;
		process.stdout.write(`rewrote ${path}\n`);
	}
}
process.stdout.write(`${changed} file(s) rewritten\n`);
