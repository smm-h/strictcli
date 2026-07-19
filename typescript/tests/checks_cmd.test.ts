/**
 * Check command surface tests: the 8 flags, list/dry-run/help/no-match
 * branches, text and JSON formatters (including --verbose notes, durations,
 * and the count summary), and scope emission in list JSON.
 *
 * GROUND TRUTH: byte-level expectations were captured on 2026-07-19 by
 * running the Python implementation over the same mirror app (scratchpad
 * pychecks.py); durations are normalized before comparison since they are
 * wall-clock. Cross-checked against conformance/cases/checks.json +
 * check_notes.json + check_purity.json.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { CheckContext } from "../src/index.js";
import {
	type App,
	createApp,
	flag,
	formatCheckResults,
	formatCheckResultsJSON,
	t,
} from "../src/index.js";

const CTX: CheckContext = { projectRoot: "." };

/** The 4-check mirror app used to capture the Python ground-truth bytes. */
function mirrorApp(): App {
	const toml = `app = "testapp"
[checks.lint]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.format]
tags = ["dev", "quality"]
severity = "warn"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.compile]
tags = ["release"]
severity = "error"
fast = false
pure = false
needs_network = false
depends_on = []

[checks.deploy-gate]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = true
depends_on = ["compile", "lint"]
scope = "changelog"
`;
	const app = createApp({
		name: "testapp",
		version: "1.0.0",
		help: "test",
		checksEmbed: toml,
	});
	app.errorCheck("lint", (_c, r) => {
		r.note("scanned 5 files");
		return r.passed("all good");
	});
	app.warnCheck("format", (_c, r) => {
		r.warn("style issue A");
		return r.found("style issues");
	});
	app.errorCheck("compile", (_c, r) => {
		r.error("compile failed hard");
		r.warn("also a warning");
		return r.found("compile failed");
	});
	app.errorCheck("deploy-gate", (_c, r) => r.passed("gate ok"));
	app.setCheckContext(() => CTX);
	return app;
}

/** Replaces wall-clock "(Nms)" durations with "(0ms)" for byte comparison. */
function zeroDurations(s: string): string {
	return s.replaceAll(/\((\d+)ms\)/g, "(0ms)");
}

test("check --list: aligned human table sorted by name", async () => {
	const result = await mirrorApp().test(["check", "--list"]);
	assert.equal(result.exitCode, 0);
	assert.equal(
		result.stdout,
		"NAME          TAGS           SEVERITY\n" +
			"compile       release        error\n" +
			"deploy-gate   release        error\n" +
			"format        dev, quality   warn\n" +
			"lint          release        error\n",
	);
});

test("check --list --json: compact entries, scope only when non-empty", async () => {
	const result = await mirrorApp().test(["check", "--list", "--json"]);
	assert.equal(result.exitCode, 0);
	assert.equal(
		result.stdout,
		'[{"name":"compile","tags":["release"],"severity":"error"},' +
			'{"name":"deploy-gate","tags":["release"],"severity":"error","scope":"changelog"},' +
			'{"name":"format","tags":["dev","quality"],"severity":"warn"},' +
			'{"name":"lint","tags":["release"],"severity":"error"}]\n',
	);
});

test("check --list on an app-only checks.toml prints No checks defined.", async () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: 'app = "t"\n',
	});
	const result = await app.test(["check", "--list"]);
	assert.equal(result.exitCode, 0);
	assert.equal(result.stdout, "No checks defined.\n");
});

test("check --all: grouped problems (errors before warns), cascade skip", async () => {
	const result = await mirrorApp().test(["check", "--all"]);
	assert.equal(result.exitCode, 1);
	assert.equal(
		result.stdout,
		"FAIL  compile        compile failed\n" +
			"        [error] compile failed hard\n" +
			"        [warn] also a warning\n" +
			"WARN  format         style issues\n" +
			"        [warn] style issue A\n" +
			"PASS  lint           all good\n" +
			'SKIP  deploy-gate    skipped: dependency "compile" failed\n',
	);
	// Notes stay hidden without --verbose, even on failing checks.
	assert.doesNotMatch(result.stdout, /\[note\]/);
});

test("check --all --verbose: durations, notes, and count summary", async () => {
	const result = await mirrorApp().test(["check", "--all", "--verbose"]);
	assert.equal(result.exitCode, 1);
	assert.match(result.stdout, /\(\d+ms\)/);
	assert.equal(
		zeroDurations(result.stdout),
		"FAIL  compile        compile failed (0ms)\n" +
			"        [error] compile failed hard\n" +
			"        [warn] also a warning\n" +
			"WARN  format         style issues (0ms)\n" +
			"        [warn] style issue A\n" +
			"PASS  lint           all good (0ms)\n" +
			"        [note] scanned 5 files\n" +
			'SKIP  deploy-gate    skipped: dependency "compile" failed (0ms)\n' +
			"\n" +
			"1 passed / 1 failed / 1 warned / 1 skipped\n",
	);
});

test("check --all --json: notes and duration_ms always present", async () => {
	const result = await mirrorApp().test(["check", "--all", "--json"]);
	assert.equal(result.exitCode, 1);
	assert.equal(
		result.stdout.replaceAll(/"duration_ms":\d+/g, '"duration_ms":0'),
		'[{"name":"compile","status":"fail","message":"compile failed","problems":[{"severity":"error","text":"compile failed hard"},{"severity":"warn","text":"also a warning"}],"notes":[],"duration_ms":0},' +
			'{"name":"format","status":"warn","message":"style issues","problems":[{"severity":"warn","text":"style issue A"}],"notes":[],"duration_ms":0},' +
			'{"name":"lint","status":"pass","message":"all good","problems":[],"notes":["scanned 5 files"],"duration_ms":0},' +
			'{"name":"deploy-gate","status":"skip","message":"skipped: dependency \\"compile\\" failed","problems":[],"notes":[],"duration_ms":0}]\n',
	);
});

test("check --tag: DSL filtering; --name: glob filtering", async () => {
	const byTag = await mirrorApp().test(["check", "--tag", "dev & quality"]);
	assert.equal(byTag.exitCode, 1);
	assert.match(byTag.stdout, /WARN {2}format/);
	assert.doesNotMatch(byTag.stdout, /lint/);

	const byName = await mirrorApp().test(["check", "--name", "lin*"]);
	assert.equal(byName.exitCode, 0);
	assert.equal(byName.stdout, "PASS  lint    all good\n");
});

test("check with non-matching filter prints the no-match message", async () => {
	const result = await mirrorApp().test(["check", "--tag", "nonexistent"]);
	assert.equal(result.exitCode, 0);
	assert.equal(result.stdout, "No checks matched the given filters.\n");
});

test("check --ignore-warnings: warn-only run exits 0, WARN still shown", async () => {
	const toml =
		'app = "t"\n[checks.lint]\ntags = ["x"]\nseverity = "error"\nfast = true\npure = true\nneeds_network = false\ndepends_on = []\n';
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("lint", (_c, r) => {
		r.warn("minor issues");
		return r.found("minor issues");
	});
	app.setCheckContext(() => CTX);
	const strict = await app.test(["check", "--all"]);
	assert.equal(strict.exitCode, 1);
	assert.match(strict.stdout, /WARN/);
	const lenient = await app.test(["check", "--all", "--ignore-warnings"]);
	assert.equal(lenient.exitCode, 0);
	assert.match(lenient.stdout, /WARN/);
});

test("check with no flags shows the command help (Python branch order)", async () => {
	const expectedHelp =
		"testapp check -- Run project checks registered via the check framework and report results\n" +
		"\n" +
		"Flags:\n" +
		"  --all, --no-all                            Run every registered check regardless of tag or name filters [default: false]\n" +
		"  --tag <str>                                Tag DSL expression to select checks (e.g. 'changelog & !quality') [default: ]\n" +
		"  --name <str>                               Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*') [default: ]\n" +
		"  --list, --no-list                          List all registered checks with their tags and exit without running [default: false]\n" +
		"  --json, --no-json                          Output check results as machine-readable JSON instead of human text [default: false]\n" +
		"  --ignore-warnings, --no-ignore-warnings    Treat warn-severity results as passing so they do not cause nonzero exit [default: false]\n" +
		"  --verbose, --no-verbose                    Show per-check notes and durations (including on passing checks) plus a trailing pass/fail/warn/skip count summary [default: false]\n" +
		"  --dry-run, --no-dry-run                    Show which checks would run based on current filters without executing them [default: false]\n";
	const bare = await mirrorApp().test(["check"]);
	assert.equal(bare.exitCode, 0);
	assert.equal(bare.stdout, expectedHelp);
	// --dry-run without a filter is NOT a filter: still the help branch.
	const dry = await mirrorApp().test(["check", "--dry-run"]);
	assert.equal(dry.exitCode, 0);
	assert.equal(dry.stdout, expectedHelp);
});

test("check --dry-run with a non-matching filter prints no-match, not a plan", async () => {
	const result = await mirrorApp().test([
		"check",
		"--tag",
		"nonexistent",
		"--dry-run",
	]);
	assert.equal(result.exitCode, 0);
	assert.equal(result.stdout, "No checks matched the given filters.\n");
});

test("check --dry-run: singular noun for a single check", async () => {
	const result = await mirrorApp().test([
		"check",
		"--name",
		"lint",
		"--dry-run",
	]);
	assert.equal(result.exitCode, 0);
	assert.equal(result.stdout, "Would run 1 check:\n  1. lint [pure]\n");
});

test("dry-run purity annotations: pure=false and needs_network=true are impure", async () => {
	const toml = `app = "t"
[checks.deploy]
tags = ["release"]
severity = "error"
fast = false
pure = false
needs_network = false
depends_on = []

[checks.fetch]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = true
depends_on = []
`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("deploy", (_c, r) => r.passed("deployed"));
	app.errorCheck("fetch", (_c, r) => r.passed("fetched"));
	app.setCheckContext(() => CTX);
	const result = await app.test(["check", "--all", "--dry-run"]);
	assert.equal(result.exitCode, 0);
	assert.equal(
		result.stdout,
		"Would run 2 checks:\n  1. deploy [impure]\n  2. fetch [impure]\n",
	);
});

test("check run without a context factory is a stderr error, exit 1", async () => {
	const toml =
		'app = "t"\n[checks.a]\ntags = ["x"]\nseverity = "error"\nfast = true\npure = true\nneeds_network = false\ndepends_on = []\n';
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("a", (_c, r) => r.passed("ok"));
	const result = await app.test(["check", "--all"]);
	assert.equal(result.exitCode, 1);
	assert.equal(result.stdout, "");
	assert.equal(
		result.stderr,
		"error: no check context configured. Call app.setCheckContext(factory) before running.\n",
	);
});

test("malformed tag expression propagates out of test() (Python ValueError parity)", async () => {
	await assert.rejects(mirrorApp().test(["check", "--tag", "x &"]), {
		message: "tag expression: unexpected end of expression at position 3",
	});
});

test("check command is absent when checks are never enabled", async () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	const result = await app.test(["check", "--all"]);
	assert.equal(result.exitCode, 1);
	assert.match(result.stderr, /unknown command 'check'/);
	const help = await app.test(["--help"]);
	assert.doesNotMatch(help.stdout, /\bcheck\b/);
});

test("check command appears in app help when checks are enabled", async () => {
	const help = await mirrorApp().test(["--help"]);
	assert.match(
		help.stdout,
		/check +Run project checks registered via the check framework and report results/,
	);
});

test("scoped checks run normally (scope is parse-only, matching Go)", async () => {
	const toml =
		'app = "t"\n[checks.scoped-check]\ntags = ["release"]\nseverity = "error"\nfast = true\npure = true\nneeds_network = false\ndepends_on = []\nscope = "changelog"\n';
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("scoped-check", (_c, r) => r.passed("scoped check ok"));
	app.setCheckContext(() => CTX);
	const result = await app.test(["check", "--all"]);
	assert.equal(result.exitCode, 0);
	assert.equal(result.stdout, "PASS  scoped-check    scoped check ok\n");

	const listed = await app.test(["check", "--list", "--json"]);
	assert.match(listed.stdout, /"scope":"changelog"/);
});

test("a global flag colliding with a check flag is dropped from the command", async () => {
	const toml =
		'app = "g"\n[checks.a]\ntags = ["x"]\nseverity = "error"\nfast = true\npure = true\nneeds_network = false\ndepends_on = []\n';
	const app = createApp({
		name: "g",
		version: "1",
		help: "h",
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "Global verbosity toggle",
				default: false,
			}),
		},
		checksEmbed: toml,
	});
	app.errorCheck("a", (_c, r) => r.passed("ok"));
	app.setCheckContext(() => CTX);
	// The global --verbose value flows into the handler kwargs.
	const quiet = await app.test(["check", "--all"]);
	assert.equal(quiet.exitCode, 0);
	assert.doesNotMatch(quiet.stdout, /passed \//);
	const verbose = await app.test(["--verbose", "check", "--all"]);
	assert.equal(verbose.exitCode, 0);
	assert.match(verbose.stdout, /1 passed \/ 0 failed \/ 0 warned \/ 0 skipped/);
});

// --- Formatter functions (public surface) ---

test("formatCheckResults returns empty string for no results", () => {
	assert.equal(formatCheckResults([], false), "");
	assert.equal(formatCheckResults([], true), "");
});

test("formatCheckResultsJSON serializes empty results as []", () => {
	assert.equal(formatCheckResultsJSON([]), "[]");
});
