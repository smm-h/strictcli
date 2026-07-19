/**
 * Test-coverage instrumentation tests: shard files written by test(), the
 * canonical manifest, and the built-in cli-test-coverage provider check.
 *
 * Each test chdirs into a fresh temp directory because the shard dir
 * (.strictcli/coverage/) and manifest are cwd-relative, mirroring the
 * siblings. Expectations derive from conformance/cases/test_coverage.json
 * and go/strictcli/coverage.go / Python _test_coverage_provider.
 */

import { strict as assert } from "node:assert";
import { existsSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { CheckContext } from "../src/index.js";
import { type App, createApp, defineCommand } from "../src/index.js";

const CTX: CheckContext = { projectRoot: "." };

async function inTempDir<T>(fn: (dir: string) => Promise<T>): Promise<T> {
	const oldCwd = process.cwd();
	const dir = mkdtempSync(join(tmpdir(), "strictcli-coverage-"));
	process.chdir(dir);
	try {
		return await fn(dir);
	} finally {
		process.chdir(oldCwd);
	}
}

/** The three-command mirror app from conformance test_coverage.json. */
function coverageApp(): App {
	const app = createApp({
		name: "testapp",
		version: "1.0.0",
		help: "test",
		testCoverage: true,
	});
	for (const [name, help, prints] of [
		["deploy", "deploy the app", "deployed"],
		["status", "show status", "ok"],
		["build", "build the app", "built"],
	] as const) {
		app.command(
			defineCommand(name, {
				help,
				handler: (_args, ctx) => {
					ctx.info(prints);
					return 0;
				},
			}),
		);
	}
	app.setCheckContext(() => CTX);
	return app;
}

test("testCoverage creates the shard dir eagerly and shards on test()", async () => {
	await inTempDir(async () => {
		const app = coverageApp();
		assert.ok(existsSync(join(".strictcli", "coverage")));

		await app.test(["deploy"]);
		await app.test(["deploy"]);
		const shards = readdirSync(join(".strictcli", "coverage"));
		assert.equal(shards.length, 1);
		const shard = shards[0] as string;
		assert.match(shard, new RegExp(`^${process.pid}-\\d+\\.jsonl$`));
		assert.equal(
			readFileSync(join(".strictcli", "coverage", shard), "utf8"),
			'{"command":"deploy"}\n{"command":"deploy"}\n',
		);
	});
});

test("partial coverage fails naming every uncovered command, sorted", async () => {
	await inTempDir(async () => {
		const app = coverageApp();
		await app.test(["deploy"]);
		const result = await app.test(["check", "--all"]);
		assert.equal(result.exitCode, 1);
		assert.equal(
			result.stdout,
			"FAIL  cli-test-coverage    2 command(s) with zero test coverage\n" +
				"        [error] no test coverage for command: build\n" +
				"        [error] no test coverage for command: status\n",
		);
	});
});

test("full coverage passes and writes the canonical sorted manifest", async () => {
	await inTempDir(async () => {
		const app = coverageApp();
		await app.test(["deploy"]);
		await app.test(["status"]);
		await app.test(["build"]);
		const result = await app.test(["check", "--all"]);
		assert.equal(result.exitCode, 0);
		assert.equal(
			result.stdout,
			"PASS  cli-test-coverage    all 3 commands have test coverage\n",
		);
		// Manifest: sorted covered commands, 2-space indent, trailing newline.
		// Running `check --all` via test() records "check" itself too.
		assert.equal(
			readFileSync(join(".strictcli", "test-coverage.json"), "utf8"),
			'[\n  "build",\n  "check",\n  "deploy",\n  "status"\n]\n',
		);
	});
});

test("no shard data fails with the stale-manifest problem", async () => {
	await inTempDir(async () => {
		const app = coverageApp();
		// Run the check via the programmatic API so no shard is written first.
		const { results, exitCode } = await app.runChecks(CTX, {
			nameGlob: "cli-test-coverage",
		});
		assert.equal(exitCode, 1);
		const r = results[0];
		assert.ok(r !== undefined);
		assert.equal(r.status, "fail");
		assert.equal(
			r.message,
			"no coverage data: .strictcli/coverage/ contains no shard files",
		);
		assert.deepEqual(
			r.problems.map((p) => ({ ...p })),
			[{ severity: "error", text: "stale or empty manifest" }],
		);
	});
});

test("group commands are covered by their dotted path", async () => {
	await inTempDir(async () => {
		const app = createApp({
			name: "testapp",
			version: "1.0.0",
			help: "test",
			testCoverage: true,
		});
		const infra = app.group("infra", { help: "infra commands" });
		infra.command(
			defineCommand("deploy", {
				help: "deploy infra",
				handler: () => 0,
			}),
		);
		app.setCheckContext(() => CTX);

		await app.test(["infra", "deploy"]);
		const shards = readdirSync(join(".strictcli", "coverage"));
		const shard = shards[0] as string;
		assert.equal(
			readFileSync(join(".strictcli", "coverage", shard), "utf8"),
			'{"command":"infra.deploy"}\n',
		);
		const result = await app.test(["check", "--all"]);
		assert.equal(result.exitCode, 0);
		assert.match(result.stdout, /all 1 commands have test coverage/);
	});
});

test("the injected check command is excluded from the coverage surface", async () => {
	await inTempDir(async () => {
		// An app with zero user commands: the surface minus "check" is empty,
		// so even a lone check run (which shards "check" itself) passes.
		const app = createApp({
			name: "empty",
			version: "1.0.0",
			help: "test",
			testCoverage: true,
		});
		app.setCheckContext(() => CTX);
		const result = await app.test(["check", "--all"]);
		assert.equal(result.exitCode, 0);
		assert.match(result.stdout, /all 0 commands have test coverage/);
	});
});

test("shards merge across multiple files in the coverage dir", async () => {
	await inTempDir(async () => {
		const app = coverageApp();
		await app.test(["deploy"]);
		// Simulate a second process shard by writing another file directly.
		const { writeFileSync } = await import("node:fs");
		writeFileSync(
			join(".strictcli", "coverage", "99999-0.jsonl"),
			'{"command":"status"}\n{"command":"build"}\n',
		);
		const result = await app.test(["check", "--all"]);
		assert.equal(result.exitCode, 0);
		assert.match(result.stdout, /all 3 commands have test coverage/);
	});
});

test("run() does not record coverage (test-only instrumentation)", async () => {
	await inTempDir(async () => {
		const app = coverageApp();
		await app.run(["deploy"]);
		process.exitCode = 0; // reset the exit code run() set
		assert.deepEqual(readdirSync(join(".strictcli", "coverage")), []);
	});
});
