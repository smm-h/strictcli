import { strict as assert } from "node:assert";
import { test } from "node:test";
import { SourcedStore, type SourceLabel } from "../src/sources.js";

const ALL_LABELS: readonly SourceLabel[] = [
	"cli",
	"env",
	"config",
	"default",
	"implied",
	"infra",
];

test("sources: set/get/has round-trip, including undefined values", () => {
	const s = new SourcedStore();
	s.set("file", undefined, "default");
	assert.equal(s.has("file"), true);
	assert.equal(s.get("file"), undefined);
	assert.equal(s.getEntry("file")?.source, "default");
	assert.equal(s.has("missing"), false);
	assert.equal(s.getEntry("missing"), undefined);

	s.set("port", 8080n, "cli");
	assert.equal(s.get("port"), 8080n);
	// Last write wins, including the source.
	s.set("port", 9090n, "env");
	assert.deepEqual(s.getEntry("port"), { value: 9090n, source: "env" });
});

test("sources: mutex presence counts only cli, env, and config", () => {
	const s = new SourcedStore();
	for (const label of ALL_LABELS) {
		s.set(label, true, label);
	}
	assert.equal(s.isPresentForMutex("cli"), true);
	assert.equal(s.isPresentForMutex("env"), true);
	assert.equal(s.isPresentForMutex("config"), true);
	assert.equal(s.isPresentForMutex("default"), false);
	assert.equal(s.isPresentForMutex("implied"), false);
	assert.equal(s.isPresentForMutex("infra"), false);
	assert.equal(s.isPresentForMutex("missing"), false);
});

test("sources: deps presence counts everything except default", () => {
	const s = new SourcedStore();
	for (const label of ALL_LABELS) {
		s.set(label, true, label);
	}
	assert.equal(s.isPresentForDeps("cli"), true);
	assert.equal(s.isPresentForDeps("env"), true);
	assert.equal(s.isPresentForDeps("config"), true);
	assert.equal(s.isPresentForDeps("default"), false);
	assert.equal(s.isPresentForDeps("implied"), true);
	assert.equal(s.isPresentForDeps("infra"), true);
	assert.equal(s.isPresentForDeps("missing"), false);
});

test("sources: sourceMap exposes the exact label strings", () => {
	const s = new SourcedStore();
	s.set("a", 1n, "cli");
	s.set("b", "x", "implied");
	s.set("c", true, "infra");
	assert.deepEqual(
		s.sourceMap(),
		new Map([
			["a", "cli"],
			["b", "implied"],
			["c", "infra"],
		]),
	);
});
