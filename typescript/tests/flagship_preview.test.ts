/** The three flagship preview shapes, asserted byte-for-byte. */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { AppImpl } from "../src/app.js";
import { buildApp } from "./flagship_app.js";

/** The test-only structured effect log of the most recent dispatch. */
function effectLog(
	app: ReturnType<typeof buildApp>,
): Record<string, unknown>[] {
	return (app as unknown as AppImpl).effectLog();
}

// --- (a) A multi-step preview with forwarding and inline brands ---

test("flagship: the preview is complete and byte-exact", async () => {
	const app = buildApp();
	const r = await app.test(["--dry-run", "release", "run", "1.2.3"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		r.stdout,
		"DRY RUN — no changes were made. Would do:\n" +
			"  1. run: make build VERSION=1.2.3\n" +
			"  2. write: CHANGELOG.md («step 1 output»)\n" +
			"  3. run: git tag v1.2.3\n" +
			"  4. run: git push origin v1.2.3" +
			" (granted: push — release engine owns remote refs)\n" +
			"  5. net: POST https://api.github.test/repos/o/r/releases" +
			" [unless resource 'gh-release:v1.2.3' already current]\n" +
			"  6. run: gh release view «step 5 output»\n" +
			"  7. spawn: notify --release v1.2.3\n",
	);
	assert.equal(r.stderr, "");
});

test("flagship: nothing was executed", async () => {
	const app = buildApp();
	await app.test(["--dry-run", "release", "run", "1.2.3"]);
	const { existsSync } = await import("node:fs");
	assert.ok(!existsSync("CHANGELOG.md.should-not-exist"));
	// The write target itself would be the repo's own CHANGELOG-like path; the
	// structured log proves the effect was recorded rather than performed.
	for (const rec of effectLog(app)) {
		assert.equal(rec.recorded, true, JSON.stringify(rec));
	}
});

test("flagship: the structured log carries the declared metadata", async () => {
	const app = buildApp();
	await app.test(["--dry-run", "release", "run", "1.2.3"]);
	assert.deepEqual(effectLog(app), [
		{
			seq: 1,
			kind: "proc_mutate",
			verb: "run",
			detail: "make build VERSION=1.2.3",
			recorded: true,
			resource: "artifact:1.2.3",
		},
		{
			seq: 2,
			kind: "file_write",
			verb: "write",
			detail: "CHANGELOG.md («step 1 output»)",
			recorded: true,
		},
		{
			seq: 3,
			kind: "proc_mutate",
			verb: "run",
			detail: "git tag v1.2.3",
			recorded: true,
			resource: "tag:v1.2.3",
		},
		{
			seq: 4,
			kind: "proc_mutate",
			verb: "run",
			detail: "git push origin v1.2.3",
			recorded: true,
			resource: "remote:origin",
			grant: "push",
		},
		{
			seq: 5,
			kind: "net_mutate",
			verb: "net",
			detail: "POST https://api.github.test/repos/o/r/releases",
			recorded: true,
			resource: "gh-release:v1.2.3",
			skip_if_current: "gh-release:v1.2.3",
		},
		{
			seq: 6,
			kind: "proc_mutate",
			verb: "run",
			detail: "gh release view «step 5 output»",
			recorded: true,
		},
		{
			seq: 7,
			kind: "proc_spawn",
			verb: "spawn",
			detail: "notify --release v1.2.3",
			recorded: true,
		},
	]);
});

test("flagship: a write forwarding an unsettled carrier carries no byte count", async () => {
	const app = buildApp();
	await app.test(["--dry-run", "release", "run", "1.2.3"]);
	const write = effectLog(app).find((r) => r.verb === "write");
	// Absent and explicit-null are equivalent: nothing produced those bytes and
	// the framework will not invent a count.
	assert.ok(write !== undefined);
	assert.equal(write.bytes, undefined);
});

test("flagship: the pre-mutation observe is never logged", async () => {
	const app = buildApp();
	const r = await app.test(["--dry-run", "release", "run", "1.2.3"]);
	// The observe ran for real and its result was branched on, but a read is not
	// a change: it appears in neither the rendered nor the structured log.
	assert.ok(!r.stdout.includes("process.stdout.write"));
	for (const rec of effectLog(app)) {
		assert.ok(!String(rec.detail).includes("process.stdout.write"));
	}
});

// --- (b) Branching on an unsettled value stops the preview ---

test("flagship: truncation is byte-exact", async () => {
	const app = buildApp();
	const r = await app.test(["--dry-run", "release", "verify"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stdout,
		"DRY RUN — no changes were made. Would do:\n" +
			"  1. run: git tag v9\n" +
			"  2. run: git describe --tags\n",
	);
	assert.equal(
		r.stderr,
		"error: dry-run preview ends at step 3: release.verify branched on " +
			"unsettled value «step 2 output» — cannot preview past this point\n",
	);
});

test("flagship: the unreachable step was never recorded", async () => {
	const app = buildApp();
	await app.test(["--dry-run", "release", "verify"]);
	assert.equal(effectLog(app).length, 2);
});

// --- (c) A read_only command gets real values and an empty would-do body ---

test("flagship: read_only observes return bare values in live mode", async () => {
	const r = await buildApp().test(["status"]);
	assert.equal(r.exitCode, 0);
	assert.deepEqual(r.data, { head: "a1b2c3d", clean: true, exit_code: 0 });
});

test("flagship: read_only observes return bare values in dry mode too", async () => {
	const r = await buildApp().test(["--dry-run", "status"]);
	assert.equal(r.exitCode, 0);
	assert.deepEqual(r.data, { head: "a1b2c3d", clean: true, exit_code: 0 });
});

test("flagship: a read_only dry run's would-do body is empty", async () => {
	const r = await buildApp().test(["--dry-run", "status"]);
	assert.ok(r.stdout.endsWith("DRY RUN — no changes were made. Would do:\n"));
});

test("flagship: a read_only dry run records no effects", async () => {
	const app = buildApp();
	await app.test(["--dry-run", "status"]);
	assert.deepEqual(effectLog(app), []);
});

test("flagship: --quiet hides ctx.info but never the would-do header", async () => {
	const r = await buildApp().test(["--quiet", "--dry-run", "status"]);
	assert.ok(!r.stdout.includes("head: a1b2c3d"));
	assert.ok(r.stdout.includes("DRY RUN — no changes were made. Would do:"));
});

// --- Classification is visible in the schema ---

test("flagship: the schema carries the regime declarations", () => {
	const schema = buildApp().dumpSchemaDict();
	const commands = schema.commands as Record<string, Record<string, unknown>>;
	assert.equal(commands.status?.effect, "read_only");
	const groups = schema.groups as Record<string, Record<string, unknown>>;
	const rel = (groups.release as Record<string, unknown>).commands as Record<
		string,
		Record<string, unknown>
	>;
	assert.equal(rel.run?.effect, "mutating");
	assert.deepEqual(rel.run?.grants, [
		{
			name: "push",
			reason: "release engine owns remote refs",
			kind: "proc_mutate",
		},
	]);
	assert.equal(rel.verify?.effect, "mutating");
	assert.deepEqual(schema.proc_observe_allowlist, [[process.execPath, "-e"]]);
});
