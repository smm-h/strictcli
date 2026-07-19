/**
 * Runner tests: DAG order with dependency pull-in, cycle detection, the
 * dependency-failure cascade, warn/skip non-cascade, the purity partition,
 * durationMs timing, and the programmatic app.runChecks surface.
 *
 * GROUND TRUTH: byte-level expectations captured on 2026-07-19 from the
 * Python implementation (scratchpad pychecks.py / pychecks2.py) and
 * cross-checked against conformance/cases/checks.json + check_purity.json.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import { setTimeout as sleep } from "node:timers/promises";
import type { CheckContext } from "../src/index.js";
import { type App, createApp } from "../src/index.js";

const CTX: CheckContext = { projectRoot: "." };

function checkBody(
	severity: "error" | "warn",
	extra: Record<string, string> = {},
): string {
	const lines = [
		'tags = ["release"]',
		`severity = "${severity}"`,
		"fast = true",
		"pure = true",
		"needs_network = false",
		extra.depends_on !== undefined
			? `depends_on = ${extra.depends_on}`
			: "depends_on = []",
	];
	return `${lines.join("\n")}\n`;
}

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

test("dry-run: Kahn order, dependency annotation, purity annotation", async () => {
	const result = await mirrorApp().test(["check", "--all", "--dry-run"]);
	assert.equal(result.exitCode, 0);
	assert.equal(
		result.stdout,
		"Would run 4 checks:\n" +
			"  1. compile [impure]\n" +
			"  2. format [pure]\n" +
			"  3. lint [pure]\n" +
			"  4. deploy-gate (depends on: compile, lint) [impure]\n",
	);
});

test("cascade: dependency FAIL skips dependents with exact skip message", async () => {
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
});

test("cascade: warn dependency satisfies the dependent (no cascade)", async () => {
	const toml = `app = "t"\n[checks.compile]\n${checkBody("error")}\n[checks.lint]\n${checkBody("error", { depends_on: '["compile"]' })}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("compile", (_c, r) => {
		r.warn("compiled with warnings");
		return r.found("compiled with warnings");
	});
	app.errorCheck("lint", (_c, r) => r.passed("lint ok"));
	app.setCheckContext(() => CTX);
	const result = await app.test(["check", "--all"]);
	assert.equal(result.exitCode, 1); // warn still exits nonzero
	assert.match(result.stdout, /WARN {2}compile/);
	assert.match(result.stdout, /PASS {2}lint/);
	assert.doesNotMatch(result.stdout, /SKIP/);
});

test("cascade: explicit SKIP is not a failure, dependents still run", async () => {
	const toml = `app = "t"\n[checks.compile]\n${checkBody("error")}\n[checks.lint]\n${checkBody("error", { depends_on: '["compile"]' })}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("compile", (_c, r) => r.skipped("not applicable"));
	app.errorCheck("lint", (_c, r) => r.passed("lint ok"));
	app.setCheckContext(() => CTX);
	const result = await app.test(["check", "--all"]);
	assert.equal(result.exitCode, 0);
	assert.match(result.stdout, /SKIP {2}compile/);
	assert.match(result.stdout, /PASS {2}lint/);
});

test("cascade: multi-level chain, mid-chain failure cascades transitively", async () => {
	const toml = `app = "t"\n[checks.check-a]\n${checkBody("error")}\n[checks.check-b]\n${checkBody("error", { depends_on: '["check-a"]' })}\n[checks.check-c]\n${checkBody("error", { depends_on: '["check-b"]' })}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("check-a", (_c, r) => r.passed("a passed"));
	app.errorCheck("check-b", (_c, r) => {
		r.error("b failed");
		return r.found("b failed");
	});
	app.errorCheck("check-c", (_c, r) => r.passed("c passed"));
	app.setCheckContext(() => CTX);
	const result = await app.test(["check", "--all"]);
	assert.equal(result.exitCode, 1);
	assert.match(result.stdout, /PASS {2}check-a/);
	assert.match(result.stdout, /FAIL {2}check-b/);
	assert.match(
		result.stdout,
		/SKIP {2}check-c {4}skipped: dependency "check-b" failed/,
	);
});

test("cycle detection: exact Python cycle-path bytes", async () => {
	const toml = `app = "t"\n[checks.a]\n${checkBody("error", { depends_on: '["b"]' })}\n[checks.b]\n${checkBody("error", { depends_on: '["a"]' })}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("a", (_c, r) => r.passed("ok"));
	app.errorCheck("b", (_c, r) => r.passed("ok"));
	app.setCheckContext(() => CTX);
	await assert.rejects(app.test(["check", "--all"]), {
		message: "check dependency cycle: a -> b -> a",
	});
	await assert.rejects(app.runChecks(CTX, { runAll: true }), {
		message: "check dependency cycle: a -> b -> a",
	});
});

test("filtered-dep pull-in: selecting only the dependent runs the dependency too", async () => {
	const toml = `app = "t"\n[checks.compile]\n${checkBody("error")}\n[checks.lint]\n${checkBody("error", { depends_on: '["compile"]' })}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("compile", (_c, r) => r.passed("compiled ok"));
	app.errorCheck("lint", (_c, r) => r.passed("lint ok"));
	app.setCheckContext(() => CTX);
	const result = await app.test(["check", "--name", "lint"]);
	assert.equal(result.exitCode, 0);
	assert.equal(
		result.stdout,
		"PASS  compile    compiled ok\nPASS  lint       lint ok\n",
	);
});

test("non-minted outcome is a hard error (belt-and-braces)", async () => {
	const toml = `app = "t"\n[checks.a]\n${checkBody("error")}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	// Force an untyped bad return through the typed surface.
	app.errorCheck(
		"a",
		(() => 42) as unknown as Parameters<typeof app.errorCheck>[1],
	);
	app.setCheckContext(() => CTX);
	await assert.rejects(app.test(["check", "--all"]), {
		message:
			'check "a" returned an outcome not minted by its reporter; use reporter methods (Passed/Skipped/Found)',
	});
});

test("durationMs: integer wall-clock around the impl only; cascade-skips carry 0", async () => {
	const toml = `app = "t"\n[checks.slow]\n${checkBody("error")}\n[checks.dep]\n${checkBody("error", { depends_on: '["slow"]' })}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("slow", async (_c, r) => {
		await sleep(15);
		r.error("bad");
		return r.found("slow failed");
	});
	app.errorCheck("dep", (_c, r) => r.passed("never runs"));
	app.setCheckContext(() => CTX);
	const { results, exitCode } = await app.runChecks(CTX, { runAll: true });
	assert.equal(exitCode, 1);
	assert.equal(results.length, 2);
	const slow = results[0];
	const dep = results[1];
	assert.ok(slow !== undefined && dep !== undefined);
	assert.equal(slow.name, "slow");
	assert.ok(Number.isInteger(slow.durationMs));
	assert.ok(slow.durationMs >= 10, `durationMs=${slow.durationMs}`);
	assert.equal(dep.name, "dep");
	assert.equal(dep.status, "skip");
	assert.equal(dep.durationMs, 0);
});

// --- Programmatic runChecks surface ---

test("runChecks: not enabled is a hard error", async () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	await assert.rejects(app.runChecks(CTX), {
		message: "checks are not enabled on this App",
	});
});

test("runChecks: empty selection returns empty results and exit 0", async () => {
	const toml = `app = "t"\n[checks.a]\n${checkBody("error")}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("a", (_c, r) => r.passed("ok"));
	const out = await app.runChecks(CTX);
	assert.deepEqual(out.results, []);
	assert.deepEqual(out.impureListed, []);
	assert.equal(out.exitCode, 0);
});

test("runChecks: result accessors and ignoreWarnings", async () => {
	const toml = `app = "t"\n[checks.a]\n${checkBody("warn")}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.warnCheck("a", (_c, r) => {
		r.warn("minor issues");
		r.note("checked stuff");
		return r.found("minor issues");
	});
	const strict = await app.runChecks(CTX, { runAll: true });
	assert.equal(strict.exitCode, 1);
	const r = strict.results[0];
	assert.ok(r !== undefined);
	assert.equal(r.name, "a");
	assert.equal(r.status, "warn");
	assert.equal(r.message, "minor issues");
	assert.deepEqual(
		r.problems.map((p) => ({ ...p })),
		[{ severity: "warn", text: "minor issues" }],
	);
	assert.deepEqual([...r.notes], ["checked stuff"]);
	assert.equal(r.gated(), false);
	assert.equal(r.warned(), true);

	const lenient = await app.runChecks(CTX, {
		runAll: true,
		ignoreWarnings: true,
	});
	assert.equal(lenient.exitCode, 0);
});

test("runChecks: tag/glob filters intersect", async () => {
	const toml = `app = "t"
[checks.check-alpha]
tags = ["x"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-beta]
tags = ["x"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-gamma]
tags = ["y"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	app.errorCheck("check-alpha", (_c, r) => r.passed("alpha passed"));
	app.errorCheck("check-beta", (_c, r) => r.passed("beta passed"));
	app.errorCheck("check-gamma", (_c, r) => r.passed("gamma passed"));
	const out = await app.runChecks(CTX, {
		tagExpr: "x",
		nameGlob: "check-a*",
	});
	assert.deepEqual(
		out.results.map((r) => r.name),
		["check-alpha"],
	);
	assert.equal(out.exitCode, 0);
});

test("runChecks: purity partition lists impure checks and their dependents", async () => {
	const toml = `app = "t"
[checks.pure-a]
tags = ["x"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.impure-b]
tags = ["x"]
severity = "error"
fast = true
pure = false
needs_network = false
depends_on = []

[checks.net-c]
tags = ["x"]
severity = "error"
fast = true
pure = true
needs_network = true
depends_on = []

[checks.pure-d]
tags = ["x"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["impure-b"]
`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	const ran: string[] = [];
	for (const name of ["pure-a", "impure-b", "net-c", "pure-d"]) {
		app.errorCheck(name, (_c, r) => {
			ran.push(name);
			return r.passed(`${name} ok`);
		});
	}
	const out = await app.runChecks(CTX, { runAll: true, pureOnly: true });
	// Only the pure, network-free check with no listed dependencies executes;
	// pure-d joins the listing because its dependency impure-b was listed.
	assert.deepEqual(ran, ["pure-a"]);
	assert.deepEqual(
		out.results.map((r) => r.name),
		["pure-a"],
	);
	assert.deepEqual(out.impureListed, ["impure-b", "net-c", "pure-d"]);
	assert.equal(out.exitCode, 0);
});

test("runChecks: unregistered declared check is a thrown error", async () => {
	const toml = `app = "t"\n[checks.a]\n${checkBody("error")}`;
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: toml,
	});
	await assert.rejects(app.runChecks(CTX, { runAll: true }), {
		message: "checks declared in checks.toml but not registered: a",
	});
});
