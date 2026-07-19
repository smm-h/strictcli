/**
 * Tool export tests: jsonSchema(), asTools(), Tool shape, and the router
 * tool. Mirrors python/tests/test_tool_export.py (dotted tool names) with
 * go/strictcli/tool_test.go as the schema-shape cross-check.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	arg,
	createApp,
	defineCommand,
	flag,
	outcome,
	t,
} from "../src/index.js";

function buildApp() {
	return createApp({ name: "myapp", version: "1.0.0", help: "test app" });
}

type Schema = Record<string, Record<string, unknown>> & Record<string, unknown>;

function props(schema: Record<string, unknown>): Record<string, Schema> {
	return schema.properties as Record<string, Schema>;
}

// --- jsonSchema: basic types ---

test("jsonSchema: scalar types map to string/integer/number/boolean", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "multi-type command",
			flags: {
				name: flag("name", t.str, { help: "string flag" }),
				count: flag("count", t.int, { help: "integer flag" }),
				factor: flag("factor", t.float, { help: "number flag" }),
				verbose: flag("verbose", t.bool, {
					help: "boolean flag",
					default: false,
				}),
			},
			handler: () => 0,
		}),
	);
	const schema = app.jsonSchema("cmd");
	assert.equal(schema.type, "object");
	assert.equal(schema.additionalProperties, false);
	const p = props(schema);
	assert.equal(p.name?.type, "string");
	assert.equal(p.count?.type, "integer");
	assert.equal(p.factor?.type, "number");
	assert.equal(p.verbose?.type, "boolean");
});

test("jsonSchema: list and dict flags become array/object", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "compound command",
			flags: {
				nums: flag("nums", t.list(t.int), { help: "int list" }),
				labels: flag("labels", t.dict(t.str), { help: "labels" }),
			},
			handler: () => 0,
		}),
	);
	const p = props(app.jsonSchema("cmd"));
	assert.deepEqual(p.nums, {
		type: "array",
		items: { type: "integer" },
		description: "int list",
	});
	assert.deepEqual(p.labels, {
		type: "object",
		additionalProperties: { type: "string" },
		description: "labels",
	});
});

// --- jsonSchema: required rules ---

test("jsonSchema: required covers only scalar non-bool flags without defaults", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				name: flag("name", t.str, { help: "required name" }),
				greeting: flag("greeting", t.str, {
					help: "optional",
					default: "hello",
				}),
				nickname: flag("nickname", t.str, {
					help: "explicitly optional",
					default: null,
				}),
				verbose: flag("verbose", t.bool, { help: "bool", default: false }),
				items: flag("items", t.list(t.str), { help: "list" }),
				labels: flag("labels", t.dict(t.str), { help: "dict" }),
			},
			handler: () => 0,
		}),
	);
	assert.deepEqual(app.jsonSchema("cmd").required, ["name"]);
});

test("jsonSchema: required args are listed; optional args are not", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [
				arg("target", t.str, { help: "target" }),
				arg("extra", t.str, { help: "extra", required: false }),
			],
			handler: () => 0,
		}),
	);
	const schema = app.jsonSchema("cmd");
	assert.deepEqual(schema.required, ["target"]);
	const p = props(schema);
	assert.equal(p.target?.type, "string");
	assert.equal(p.extra?.type, "string");
});

test("jsonSchema: variadic args become arrays with typed items", () => {
	const app = buildApp();
	app.command(
		defineCommand("sum", {
			help: "sum",
			args: [arg("nums", t.int, { help: "numbers", variadic: true })],
			handler: () => 0,
		}),
	);
	const p = props(app.jsonSchema("sum"));
	assert.deepEqual(p.nums, {
		type: "array",
		items: { type: "integer" },
		description: "numbers",
	});
});

// --- jsonSchema: choices and descriptions ---

test("jsonSchema: choices become enum (bigint for int flags)", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				color: flag("color", t.str, {
					help: "color",
					choices: ["red", "blue"],
				}),
				level: flag("level", t.int, { help: "level", choices: [1n, 2n] }),
			},
			args: [arg("mode", t.str, { help: "mode", choices: ["fast", "slow"] })],
			handler: () => 0,
		}),
	);
	const p = props(app.jsonSchema("cmd"));
	assert.deepEqual(p.color?.enum, ["red", "blue"]);
	assert.deepEqual(p.level?.enum, [1n, 2n]);
	assert.deepEqual(p.mode?.enum, ["fast", "slow"]);
	assert.equal("enum" in (p.color ?? {}), true);
});

test("jsonSchema: no choices means no enum key; help becomes description", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { name: flag("name", t.str, { help: "a name" }) },
			args: [arg("target", t.str, { help: "the target" })],
			handler: () => 0,
		}),
	);
	const p = props(app.jsonSchema("cmd"));
	assert.equal("enum" in (p.name ?? {}), false);
	assert.equal(p.name?.description, "a name");
	assert.equal(p.target?.description, "the target");
});

test("jsonSchema: dashed flag names use underscored property keys", () => {
	const app = buildApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				dry_run: flag("dry-run", t.bool, { help: "dry run", default: false }),
			},
			handler: () => 0,
		}),
	);
	const p = props(app.jsonSchema("cmd"));
	assert.ok(p.dry_run);
	assert.equal("dry-run" in p, false);
});

// --- jsonSchema: paths and errors ---

test("jsonSchema: resolves group and nested-group command paths", () => {
	const app = buildApp();
	const cloud = app.group("cloud", { help: "cloud" });
	const storage = cloud.group("storage", { help: "storage" });
	storage.command(
		defineCommand("upload", {
			help: "upload",
			flags: { bucket: flag("bucket", t.str, { help: "bucket" }) },
			handler: () => 0,
		}),
	);
	const p = props(app.jsonSchema("cloud.storage.upload"));
	assert.equal(p.bucket?.type, "string");
});

test("jsonSchema: unknown command and group paths throw InvokeError", () => {
	const app = buildApp();
	const db = app.group("db", { help: "database" });
	db.command(defineCommand("migrate", { help: "migrate", handler: () => 0 }));
	assert.throws(() => app.jsonSchema("nope"), {
		name: "InvokeError",
		message: "JsonSchema: unknown command 'nope'",
	});
	assert.throws(() => app.jsonSchema("db"), {
		name: "InvokeError",
		message: "JsonSchema: 'db' is a group, not a command",
	});
});

// --- asTools ---

function toolFixture() {
	const app = buildApp();
	app.command(
		defineCommand("deploy", {
			help: "deploy the app",
			flags: { target: flag("target", t.str, { help: "deploy target" }) },
			handler: (args) => outcome(0, { deployed: args.target }),
		}),
	);
	app.command(
		defineCommand("secret", { help: "hidden", hidden: true, handler: () => 0 }),
	);
	app.command(
		defineCommand("wizard", {
			help: "interactive wizard",
			interactive: true,
			handler: () => 0,
		}),
	);
	const db = app.group("db", { help: "database commands" });
	db.command(
		defineCommand("migrate", { help: "run migrations", handler: () => 0 }),
	);
	const ghost = app.group("ghost", { help: "hidden group", hidden: true });
	ghost.command(defineCommand("boo", { help: "boo", handler: () => 0 }));
	return app;
}

test("asTools: eligible commands in order, then the router tool last", () => {
	const app = toolFixture();
	const tools = app.asTools();
	assert.deepEqual(
		tools.map((tl) => tl.name),
		["deploy", "db.migrate", "myapp"],
	);
});

test("asTools: tool shape carries description, parameters, and execute", async () => {
	const app = toolFixture();
	const deploy = app.asTools()[0];
	assert.ok(deploy);
	assert.equal(deploy.name, "deploy");
	assert.equal(deploy.description, "deploy the app");
	assert.deepEqual(deploy.parameters, app.jsonSchema("deploy"));
	assert.equal(typeof deploy.execute, "function");
	assert.deepEqual(await deploy.execute({ target: "prod" }), {
		deployed: "prod",
	});
});

test("asTools: execute rejects with InvokeError on bad kwargs", async () => {
	const app = toolFixture();
	const deploy = app.asTools()[0];
	assert.ok(deploy);
	await assert.rejects(deploy.execute({}), {
		name: "InvokeError",
		message: "flag '--target' is required",
	});
});

test("asTools: router tool describes and dispatches commands", async () => {
	const app = toolFixture();
	const tools = app.asTools();
	const router = tools[tools.length - 1];
	assert.ok(router);
	assert.equal(router.name, "myapp");
	assert.equal(router.description, "Route to myapp commands");
	assert.deepEqual(router.parameters, {
		type: "object",
		properties: {
			command: {
				type: "string",
				description: "Command to execute (dot-separated path)",
				enum: ["deploy", "db.migrate"],
			},
		},
		required: ["command"],
		additionalProperties: false,
	});
	// No command: lists the available command paths.
	assert.deepEqual(await router.execute(), ["deploy", "db.migrate"]);
	// Dispatch strips the command key and forwards the rest.
	assert.deepEqual(
		await router.execute({ command: "deploy", target: "prod" }),
		{ deployed: "prod" },
	);
});

test("asTools: router rejects non-string and unknown commands", async () => {
	const app = toolFixture();
	const tools = app.asTools();
	const router = tools[tools.length - 1];
	assert.ok(router);
	await assert.rejects(router.execute({ command: 42 }), {
		name: "InvokeError",
		message: "command must be a string",
	});
	await assert.rejects(router.execute({ command: "nonexistent" }), {
		name: "InvokeError",
		message: "unknown command 'nonexistent'",
	});
});

test("asTools: app with no commands yields only the router tool", () => {
	const app = buildApp();
	const tools = app.asTools();
	assert.equal(tools.length, 1);
	assert.equal(tools[0]?.name, "myapp");
	const cmdProp = props(tools[0]?.parameters as Record<string, unknown>);
	assert.deepEqual(cmdProp.command?.enum, []);
});
