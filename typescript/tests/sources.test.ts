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

test("sources: mutex election counts only cli (contract §21.3)", () => {
	const s = new SourcedStore();
	for (const label of ALL_LABELS) {
		s.set(label, true, label);
	}
	assert.equal(s.isCli("cli"), true);
	assert.equal(s.isCli("env"), false);
	assert.equal(s.isCli("config"), false);
	assert.equal(s.isCli("default"), false);
	assert.equal(s.isCli("implied"), false);
	assert.equal(s.isCli("infra"), false);
	assert.equal(s.isCli("missing"), false);

	assert.equal(s.isEnvOrConfig("env"), true);
	assert.equal(s.isEnvOrConfig("config"), true);
	assert.equal(s.isEnvOrConfig("cli"), false);
	assert.equal(s.isEnvOrConfig("default"), false);
	assert.equal(s.isEnvOrConfig("missing"), false);

	s.delete("env");
	assert.equal(s.has("env"), false);
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
