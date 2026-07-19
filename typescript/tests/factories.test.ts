import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	arg,
	coRequired,
	defineCommand,
	deprecated,
	flag,
	flagSet,
	implies,
	mutexGroup,
	passthrough,
	requires,
	t,
} from "../src/index.js";

// --- Runtime: descriptor shapes ---

test("flag captures name, schema, and opts", () => {
	const f = flag("dry-run", t.bool, { help: "Dry run", default: true });
	assert.equal(f.kind, "flag");
	assert.equal(f.name, "dry-run");
	assert.equal(f.schema, "bool");
	assert.equal(f.opts.help, "Dry run");
	assert.equal(f.opts.default, true);
});

test("flag registration errors match sibling messages", () => {
	assert.throws(() => flag("target", t.str, { help: "" }), {
		message: "Flag.help must be a non-empty string",
	});
	assert.throws(() => flag("target", t.str, { help: "   " }), {
		message: "Flag.help must be a non-empty string",
	});
	assert.throws(() => flag("force", t.str, { help: "x" }), {
		message:
			"flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'",
	});
	assert.throws(() => flag("no-frame", t.bool, { help: "x", default: true }), {
		message:
			"flag 'no-frame': names starting with 'no-' are reserved for the negation system; use a positive name instead",
	});
});

test("arg registration errors match sibling messages", () => {
	assert.throws(() => arg("src", t.str, { help: "" }), {
		message: "Arg.help must be a non-empty string",
	});
	// The type system cannot excess-property-check generic constraints (spike
	// finding), so a stray default on a required arg is a runtime error.
	assert.throws(() => arg("src", t.str, { help: "Source", default: "x" }), {
		message: "required arg cannot have a default",
	});
	assert.throws(
		() => arg("src", t.str, { help: "Source", required: true, default: "x" }),
		{ message: "required arg cannot have a default" },
	);
});

test("dependency descriptors carry sibling field shapes", () => {
	const cr = coRequired(["user", "password"]);
	assert.deepEqual(cr, { kind: "co-required", flags: ["user", "password"] });

	const rq = requires({ flag: "password", dependsOn: "user" });
	assert.deepEqual(rq, {
		kind: "requires",
		flag: "password",
		dependsOn: "user",
	});

	const im = implies({ flag: "debug", implies: "verbose", value: true });
	assert.deepEqual(im, {
		kind: "implies",
		flag: "debug",
		implies: "verbose",
		value: true,
	});
});

test("flagSet and mutexGroup hold keyed flag maps", () => {
	const common = flagSet("common", {
		verbose: flag("verbose", t.bool, { help: "Verbose", default: false }),
	});
	assert.equal(common.kind, "flag-set");
	assert.equal(common.name, "common");
	assert.equal(common.flags.verbose.name, "verbose");

	const mg = mutexGroup({
		file: flag("file", t.str, { help: "From file", default: null }),
		url: flag("url", t.str, { help: "From URL", default: null }),
	});
	assert.equal(mg.kind, "mutex-group");
	assert.equal(mg.flags.file.schema, "str");
});

test("defineCommand validates help, tags, and flag-map keys", () => {
	assert.throws(() => defineCommand("x", { help: " ", handler: () => 0 }), {
		message: 'command "x": missing help text',
	});
	assert.throws(
		() => defineCommand("x", { help: "h", tags: ["Bad"], handler: () => 0 }),
		{ message: 'invalid tag name "Bad": must match [a-z][a-z0-9-]*' },
	);
	assert.throws(
		() =>
			defineCommand("build", {
				help: "h",
				flags: {
					dryRun: flag("dry-run", t.bool, { help: "h", default: false }),
				},
				handler: () => 0,
			}),
		{
			message:
				"command \"build\": flags key 'dryRun' must be the underscore form of flag 'dry-run' ('dry_run')",
		},
	);
});

test("passthrough and deprecated carriers", () => {
	const pt = passthrough("checkout", {
		help: "Forward to git checkout",
		handler: (args) => (args.args.length > 0 ? 0 : 1),
	});
	assert.equal(pt.kind, "passthrough");
	assert.equal(pt.name, "checkout");
	assert.equal(pt.hidden, false);

	const dep = deprecated("old-cmd", "use 'new-cmd' instead");
	assert.deepEqual(dep, {
		kind: "deprecated",
		name: "old-cmd",
		message: "use 'new-cmd' instead",
	});
	assert.throws(() => deprecated("old-cmd", "  "), {
		message: 'deprecated command "old-cmd": message must not be empty',
	});
});

// --- Type-level: per-carrier option typing ---
// Each case is wrapped in a never-invoked closure: the runtime validators now
// also reject these shapes, and only the compile error is under test here.

void [
	// @ts-expect-error int flags take bigint defaults, not number
	() => flag("count", t.int, { help: "h", default: 5 }),
	// @ts-expect-error list defaults are element arrays, not scalars
	() => flag("tag", t.list(t.str), { help: "h", default: "x" }),
	// @ts-expect-error choices are incompatible with bool flags
	() => flag("verbose", t.bool, { help: "h", default: false, choices: [true] }),
	// @ts-expect-error negatable is only meaningful for bool flags
	() => flag("target", t.str, { help: "h", negatable: false }),
	// @ts-expect-error unique requires a list carrier
	() => flag("target", t.str, { help: "h", unique: true }),
	// @ts-expect-error dict flags cannot use envSeparator (env vars are JSON)
	() => flag("meta", t.dict(t.int), { help: "h", envSeparator: "," }),
	// @ts-expect-error dict carriers are not allowed on args
	() => arg("values", t.dict(t.int), { help: "h" }),
	// @ts-expect-error list args are expressed as scalar carrier + variadic: true
	() => arg("values", t.list(t.float), { help: "h" }),
	// @ts-expect-error choices elements must match the carrier's value type
	() => flag("level", t.int, { help: "h", choices: [1, 2] }),
];
