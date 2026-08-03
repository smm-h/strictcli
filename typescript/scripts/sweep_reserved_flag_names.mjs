#!/usr/bin/env node
/**
 * Mechanical sweep for the effects regime's reserved flag quartet.
 *
 * `dry-run`, `yes`, `quiet` and `verbose` are now reserved framework flag
 * names, banned UNCONDITIONALLY at every level. The test suite used three of
 * them as ordinary example flags throughout, so every such declaration -- and
 * every argv token, handler key, help expectation and schema expectation that
 * referenced it -- has to be renamed.
 *
 * The replacements are deliberately the SAME LENGTH as the names they replace,
 * because the help renderer pads flag columns to the longest name in a block: a
 * shorter substitute would silently reflow captured help expectations and turn
 * a mechanical rename into a semantic edit.
 *
 * `yes` is not swept: no test declares it as a flag, and it appears in the
 * bool env-string vocabulary ("1|true|yes"), which must not change.
 *
 * Committed rather than run inline so the transformation is reviewable and
 * repeatable.
 *
 * Usage: node scripts/sweep_reserved_flag_names.mjs <file>...
 */

import { readFileSync, writeFileSync } from "node:fs";

/** [reserved name, same-length replacement] in dashed and underscored forms. */
const RENAMES = [
	[/\bverbose\b/g, "chatter"],
	[/\bVerbose\b/g, "Chatter"],
	[/\bquiet\b/g, "muted"],
	[/\bdry-run\b/g, "sim-run"],
	[/\bdry_run\b/g, "sim_run"],
	[/\bdryRun\b/g, "simRun"],
];

let changed = 0;
for (const path of process.argv.slice(2)) {
	const before = readFileSync(path, "utf8");
	let after = before;
	for (const [pattern, replacement] of RENAMES) {
		after = after.replace(pattern, replacement);
	}
	if (after !== before) {
		writeFileSync(path, after);
		changed++;
		process.stdout.write(`rewrote ${path}\n`);
	}
}
process.stdout.write(`${changed} file(s) rewritten\n`);
