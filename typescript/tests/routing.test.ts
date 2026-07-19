import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { AppImpl } from "../src/app.js";
import { createApp, defineCommand, deprecated } from "../src/index.js";
import { resolveCommand } from "../src/routing.js";

function makeApp(): AppImpl {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
	}) as AppImpl;
	app.command(
		defineCommand("run", { help: "run something", handler: () => undefined }),
	);
	app.deprecate(deprecated("old-run", "use 'run' instead"));
	const dns = app.group("dns", { help: "manage DNS" });
	const zone = dns.group("zone", { help: "manage zones" });
	zone.command(
		defineCommand("list", { help: "list all zones", handler: () => undefined }),
	);
	zone.deprecate(deprecated("dump", "use 'list' instead"));
	return app;
}

test("routing: root command with remaining tokens", () => {
	const r = resolveCommand(makeApp(), ["run", "--x", "y"]);
	assert.equal(r.cmd?.name, "run");
	assert.deepEqual(r.rest, ["--x", "y"]);
	assert.deepEqual(r.path, []);
	assert.equal(r.err, undefined);
});

test("routing: nested command consumes the group path", () => {
	const r = resolveCommand(makeApp(), ["dns", "zone", "list", "extra"]);
	assert.equal(r.cmd?.name, "list");
	assert.deepEqual(r.path, ["dns", "zone"]);
	assert.deepEqual(r.rest, ["extra"]);
	assert.equal(r.lastGroup?.name, "zone");
});

test("routing: unknown command at root and inside groups", () => {
	const r = resolveCommand(makeApp(), ["deploy"]);
	assert.equal(r.err, "unknown command 'deploy'");
	assert.equal(r.commandPrefix, undefined);

	const r2 = resolveCommand(makeApp(), ["dns", "zone", "delete"]);
	assert.equal(r2.err, "unknown command 'delete' in 'dns zone'");
	assert.equal(r2.commandPrefix, "myapp dns zone");
});

test("routing: deprecated commands error at any depth", () => {
	const r = resolveCommand(makeApp(), ["old-run"]);
	assert.equal(r.err, "command 'old-run' is deprecated: use 'run' instead");

	const r2 = resolveCommand(makeApp(), ["dns", "zone", "dump"]);
	assert.equal(r2.err, "command 'dump' is deprecated: use 'list' instead");
});

test("routing: bare group and group --help request group help", () => {
	for (const segments of [["dns"], ["dns", "--help"], ["dns", "-h"]]) {
		const r = resolveCommand(makeApp(), segments);
		assert.equal(r.helpAtGroup, true);
		assert.equal(r.lastGroup?.name, "dns");
		assert.deepEqual(r.path, ["dns"]);
	}
	const r2 = resolveCommand(makeApp(), ["dns", "zone"]);
	assert.equal(r2.helpAtGroup, true);
	assert.equal(r2.lastGroup?.name, "zone");
});

test("routing: --help right after a group wins even with trailing tokens (Python semantics)", () => {
	const r = resolveCommand(makeApp(), ["dns", "--help", "extra"]);
	assert.equal(r.helpAtGroup, true);
	assert.equal(r.lastGroup?.name, "dns");
});
