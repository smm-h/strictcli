import { strict as assert } from "node:assert";
import { homedir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { AppImpl } from "../src/app.js";
import {
	arg,
	coRequired,
	createApp,
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

// Expected messages are the captured Python implementation ground truth (the
// divergence oracle); most are byte-identical to the Go catalog as well.
function rejects(fn: () => unknown, message: string): void {
	assert.throws(fn, { name: "RegistrationError", message });
}

// Bypass the type layer to exercise runtime guards the way an untyped JS
// caller could (never is assignable to every parameter type).
function loose(v: unknown): never {
	return v as never;
}

// --- Flag validation ---

test("flag: help, force ban, no- prefix ban", () => {
	rejects(
		() => flag("target", t.str, { help: "  " }),
		"Flag.help must be a non-empty string",
	);
	rejects(
		() => flag("force", t.str, { help: "h" }),
		"flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'",
	);
	rejects(
		() => flag("no-frame", t.bool, { help: "h", default: true }),
		"flag 'no-frame': names starting with 'no-' are reserved for the negation system; use a positive name instead",
	);
});

test("flag: dict carriers reject repeatable, unique, choices, envSeparator", () => {
	rejects(
		() => flag("meta", t.dict(t.int), loose({ help: "h", repeatable: true })),
		'Flag "meta": dict type cannot be combined with repeatable=True',
	);
	rejects(
		() => flag("meta", t.dict(t.int), loose({ help: "h", unique: true })),
		'Flag "meta": dict type cannot be combined with unique',
	);
	rejects(
		() => flag("meta", t.dict(t.int), loose({ help: "h", choices: [1n] })),
		'Flag "meta": dict type cannot be combined with choices',
	);
	rejects(
		() => flag("meta", t.dict(t.int), loose({ help: "h", envSeparator: "," })),
		'Flag "meta": dict type cannot use env_separator (env vars are parsed as JSON)',
	);
});

test("flag: repeatable constraint web", () => {
	rejects(
		() =>
			flag(
				"verbose",
				t.bool,
				loose({ help: "h", default: false, repeatable: true }),
			),
		'Flag "verbose": repeatable is incompatible with type=bool',
	);
	// TS-only: scalar repeatable flags do not exist -- list carriers ARE the
	// repeatable flags (no sibling analog for this inexpressible state).
	rejects(
		() => flag("tag", t.str, loose({ help: "h", repeatable: true })),
		'Flag "tag": repeatable requires a list type',
	);
	rejects(
		() => flag("tag", t.str, loose({ help: "h", unique: true })),
		'Flag "tag": unique requires repeatable=True',
	);
});

test("flag: envSeparator constraint web", () => {
	rejects(
		() => flag("tag", t.str, loose({ help: "h", envSeparator: "," })),
		'Flag "tag": env_separator requires repeatable=True',
	);
	rejects(
		() => flag("tag", t.list(t.str), { help: "h", envSeparator: "," }),
		'Flag "tag": env_separator requires env',
	);
	rejects(
		() => flag("tag", t.list(t.str), { help: "h", env: "TAGS" }),
		'Flag "tag": repeatable flag with env requires env_separator',
	);
	rejects(
		() =>
			flag("tag", t.list(t.str), {
				help: "h",
				env: "TAGS",
				envSeparator: ",,",
			}),
		'Flag "tag": env_separator must be a single character',
	);
	rejects(
		() =>
			flag("tag", t.list(t.str), {
				help: "h",
				env: "TAGS",
				envSeparator: "\\",
			}),
		'Flag "tag": env_separator cannot be a backslash',
	);
	// Positive: the full valid combination.
	const ok = flag("tag", t.list(t.str), {
		help: "h",
		env: "TAGS",
		envSeparator: ",",
		unique: true,
	});
	assert.equal(ok.schema, "list[str]");
});

test("flag: conflictMode must be cli-wins or error", () => {
	rejects(
		() => flag("target", t.str, loose({ help: "h", conflictMode: "merge" })),
		'Flag "target": conflict_mode must be "cli-wins" or "error", got \'merge\'',
	);
	assert.equal(
		flag("target", t.str, { help: "h", conflictMode: "error" }).opts
			.conflictMode,
		"error",
	);
});

test("flag: choices validation", () => {
	rejects(
		() =>
			flag(
				"verbose",
				t.bool,
				loose({ help: "h", default: false, choices: [true] }),
			),
		'Flag "verbose": choices is incompatible with type=bool',
	);
	rejects(
		() => flag("fmt", t.str, loose({ help: "h", choices: [] })),
		'Flag "fmt": choices must be a non-empty list',
	);
	rejects(
		() => flag("fmt", t.str, loose({ help: "h", choices: ["a", 5n] })),
		'Flag "fmt": choice 5 is not of type str',
	);
	rejects(
		() => flag("lvl", t.int, loose({ help: "h", choices: [1n, "x"] })),
		"Flag \"lvl\": choice 'x' is not of type int",
	);
	rejects(
		() => flag("ratio", t.float, loose({ help: "h", choices: [1.5, 2n] })),
		'Flag "ratio": choice 2 is not of type float',
	);
	// Python parity: choices on LIST flags are allowed and validate elements
	// against the item type (Go rejects; Python is the divergence oracle).
	const ok = flag("tag", t.list(t.str), { help: "h", choices: ["a", "b"] });
	assert.deepEqual(ok.opts.choices, ["a", "b"]);
	rejects(
		() => flag("tag", t.list(t.int), loose({ help: "h", choices: [1n, "x"] })),
		"Flag \"tag\": choice 'x' is not of type int",
	);
});

test("flag: scalar default type checks (int and float only, like siblings)", () => {
	rejects(
		() => flag("count", t.int, loose({ help: "h", default: 5 })),
		"Flag \"count\": type=int requires an int default, got 'float'",
	);
	rejects(
		() => flag("count", t.int, loose({ help: "h", default: "x" })),
		"Flag \"count\": type=int requires an int default, got 'str'",
	);
	rejects(
		() => flag("ratio", t.float, loose({ help: "h", default: 5n })),
		"Flag \"ratio\": type=float requires a float default, got 'int'",
	);
	rejects(
		() => flag("ratio", t.float, loose({ help: "h", default: "x" })),
		"Flag \"ratio\": type=float requires a float default, got 'str'",
	);
});

test("flag: dict default shape checks", () => {
	rejects(
		() => flag("meta", t.dict(t.int), loose({ help: "h", default: [1n] })),
		'Flag "meta": dict flag default must be a Map',
	);
	rejects(
		() => flag("meta", t.dict(t.int), { help: "h", default: new Map() }),
		'Flag "meta": explicit empty default is redundant for dict flags, omit the default',
	);
	rejects(
		() =>
			flag(
				"meta",
				t.dict(t.int),
				loose({ help: "h", default: new Map([["a", "x"]]) }),
			),
		"Flag \"meta\": dict default value for key 'a' is not of type int",
	);
	rejects(
		() =>
			flag(
				"meta",
				t.dict(t.int),
				loose({ help: "h", default: new Map([[5n, 1n]]) }),
			),
		'Flag "meta": dict default key 5 must be a string',
	);
	const ok = flag("meta", t.dict(t.int), {
		help: "h",
		default: new Map([["a", 1n]]),
	});
	assert.equal(ok.schema, "dict[str,int]");
});

test("flag: list default shape checks", () => {
	rejects(
		() => flag("tag", t.list(t.str), loose({ help: "h", default: "x" })),
		'Flag "tag": list flag default must be an array',
	);
	rejects(
		() => flag("tag", t.list(t.str), { help: "h", default: [] }),
		'Flag "tag": explicit empty default is redundant for list flags, omit the default',
	);
	rejects(
		() => flag("tag", t.list(t.str), loose({ help: "h", default: ["a", 5n] })),
		'Flag "tag": default element 1 is not of type str',
	);
	rejects(
		() => flag("lvl", t.list(t.int), loose({ help: "h", default: [1n, 2] })),
		'Flag "lvl": default element 1 is not of type int',
	);
	const ok = flag("tag", t.list(t.str), { help: "h", default: ["a"] });
	assert.deepEqual(ok.opts.default, ["a"]);
});

test("flag: default must be in choices (Python repr formatting)", () => {
	rejects(
		() =>
			flag("fmt", t.str, {
				help: "h",
				choices: ["text", "json"],
				default: "xml",
			}),
		"Flag \"fmt\": default 'xml' is not in choices ['text', 'json']",
	);
	rejects(
		() => flag("lvl", t.int, { help: "h", choices: [1n, 2n], default: 5n }),
		'Flag "lvl": default 5 is not in choices [1, 2]',
	);
	const ok = flag("fmt", t.str, {
		help: "h",
		choices: ["text", "json"],
		default: "text",
	});
	assert.equal(ok.opts.default, "text");
});

// --- Arg validation ---

test("arg: help and required-default", () => {
	rejects(
		() => arg("src", t.str, { help: " " }),
		"Arg.help must be a non-empty string",
	);
	rejects(
		() => arg("src", t.str, loose({ help: "h", default: "x" })),
		"required arg cannot have a default",
	);
});

test("arg: compound carriers are rejected", () => {
	rejects(
		() => arg("v", loose(t.dict(t.int)), { help: "h" }),
		'Arg "v": dict type is not supported on args',
	);
	rejects(
		() => arg("v", loose(t.list(t.int)), { help: "h" }),
		'Arg "v": list type on args requires variadic=True',
	);
	// TS-only: variadic args take the element carrier, never a list carrier.
	rejects(
		() => arg("v", loose(t.list(t.int)), { help: "h", variadic: true }),
		'Arg "v": variadic args take a scalar element type, not a list type',
	);
});

test("arg: choices validation", () => {
	rejects(
		() => arg("v", t.bool, loose({ help: "h", choices: [true] })),
		'Arg "v": choices is incompatible with type=bool',
	);
	rejects(
		() => arg("v", t.str, loose({ help: "h", choices: [] })),
		'Arg "v": choices must be a non-empty list',
	);
	rejects(
		() => arg("v", t.str, loose({ help: "h", choices: ["a", 5n] })),
		'Arg "v": choice 5 is not of type str',
	);
	// Variadic args may declare choices (validated per element at parse time).
	const ok = arg("v", t.str, {
		help: "h",
		variadic: true,
		choices: ["a", "b"],
	});
	assert.deepEqual(ok.opts.choices, ["a", "b"]);
});

test("arg: default type checks for all four types", () => {
	rejects(
		() => arg("v", t.str, loose({ help: "h", required: false, default: 5n })),
		"Arg \"v\": type=str requires a str default, got 'int'",
	);
	rejects(
		() => arg("v", t.int, loose({ help: "h", required: false, default: "x" })),
		"Arg \"v\": type=int requires an int default, got 'str'",
	);
	rejects(
		() =>
			arg("v", t.float, loose({ help: "h", required: false, default: "x" })),
		"Arg \"v\": type=float requires a float default, got 'str'",
	);
	rejects(
		() => arg("v", t.bool, loose({ help: "h", required: false, default: 5n })),
		"Arg \"v\": type=bool requires a bool default, got 'int'",
	);
});

test("arg: default must be in choices (Python repr formatting)", () => {
	rejects(
		() =>
			arg("v", t.str, {
				help: "h",
				required: false,
				choices: ["a", "b"],
				default: "c",
			}),
		"Arg \"v\": default 'c' is not in choices ['a', 'b']",
	);
	rejects(
		() =>
			arg("v", t.int, {
				help: "h",
				required: false,
				choices: [1n, 2n],
				default: 5n,
			}),
		'Arg "v": default 5 is not in choices [1, 2]',
	);
});

// --- defineCommand validation ---

const strFlag = (name: string) => flag(name, t.str, { help: "h" });
const boolFlag = (name: string) =>
	flag(name, t.bool, { help: "h", default: false });

test("command: missing help", () => {
	rejects(
		() => defineCommand("x", { help: " ", handler: () => 0 }),
		'command "x": missing help text',
	);
	rejects(
		() => passthrough("x", { help: " ", handler: () => 0 }),
		'command "x": missing help text',
	);
});

test("command: flag-map keys must be underscore forms (flags, flagSets, mutex)", () => {
	rejects(
		() =>
			defineCommand("build", {
				help: "h",
				flags: {
					dryRun: flag("dry-run", t.bool, { help: "h", default: false }),
				},
				handler: () => 0,
			}),
		"command \"build\": flags key 'dryRun' must be the underscore form of flag 'dry-run' ('dry_run')",
	);
	rejects(
		() =>
			defineCommand("build", {
				help: "h",
				flagSets: [flagSet("fs", loose({ wrong: strFlag("right") }))],
				handler: () => 0,
			}),
		"command \"build\": flags key 'wrong' must be the underscore form of flag 'right' ('right')",
	);
	rejects(
		() =>
			defineCommand("build", {
				help: "h",
				mutex: [
					mutexGroup(loose({ wrong: strFlag("right"), b: strFlag("b") })),
				],
				handler: () => 0,
			}),
		"command \"build\": flags key 'wrong' must be the underscore form of flag 'right' ('right')",
	);
});

test("command: mutex groups need at least 2 flags and no overlap", () => {
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				mutex: [mutexGroup({ a: strFlag("a") })],
				handler: () => 0,
			}),
		'command "cmd": mutex group must have at least 2 flags, got 1',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				mutex: [
					mutexGroup({ a: strFlag("a"), b: strFlag("b") }),
					mutexGroup({ a: strFlag("a"), c: strFlag("c") }),
				],
				handler: () => 0,
			}),
		'command "cmd": flag "a" appears in multiple mutex groups',
	);
});

test("command: duplicate flag and arg names", () => {
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: strFlag("a") },
				flagSets: [flagSet("fs", { a: strFlag("a") })],
				handler: () => 0,
			}),
		'command "cmd": duplicate flag name "a"',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				args: [arg("x", t.str, { help: "h" }), arg("x", t.str, { help: "h" })],
				handler: () => 0,
			}),
		'command "cmd": duplicate arg name "x"',
	);
});

test("command: variadic arg constraints", () => {
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				args: [
					arg("x", t.str, { help: "h", variadic: true }),
					arg("y", t.str, { help: "h", variadic: true }),
				],
				handler: () => 0,
			}),
		'command "cmd": at most one variadic arg is allowed',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				args: [
					arg("x", t.str, { help: "h", variadic: true }),
					arg("y", t.str, { help: "h" }),
				],
				handler: () => 0,
			}),
		'command "cmd": variadic arg "x" must be the last arg',
	);
});

test("command: CoRequired reference validation", () => {
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				dependencies: [coRequired(["a"])],
				handler: () => 0,
			}),
		'command "cmd": CoRequired must have at least 2 flags, got 1',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: strFlag("a") },
				dependencies: [coRequired(["a", "b"])],
				handler: () => 0,
			}),
		'command "cmd": CoRequired references unknown flag "b"',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: strFlag("a"), b: strFlag("b") },
				dependencies: [coRequired(["a", "b", "a"])],
				handler: () => 0,
			}),
		'command "cmd": CoRequired has duplicate flag "a"',
	);
});

test("command: Requires reference validation (unknown reported before same-flag)", () => {
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				dependencies: [requires({ flag: "a", dependsOn: "a" })],
				handler: () => 0,
			}),
		'command "cmd": Requires references unknown flag "a"',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: strFlag("a") },
				dependencies: [requires({ flag: "a", dependsOn: "a" })],
				handler: () => 0,
			}),
		'command "cmd": Requires flag and depends_on cannot be the same ("a")',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: strFlag("a") },
				dependencies: [requires({ flag: "a", dependsOn: "b" })],
				handler: () => 0,
			}),
		'command "cmd": Requires references unknown flag "b"',
	);
});

test("command: Implies reference validation", () => {
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				dependencies: [implies({ flag: "a", implies: "b", value: true })],
				handler: () => 0,
			}),
		'command "cmd": Implies references unknown flag "a"',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: boolFlag("a") },
				dependencies: [implies({ flag: "a", implies: "a", value: true })],
				handler: () => 0,
			}),
		'command "cmd": Implies flag and implies cannot be the same ("a")',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: strFlag("a"), b: boolFlag("b") },
				dependencies: [implies({ flag: "a", implies: "b", value: true })],
				handler: () => 0,
			}),
		'command "cmd": Implies trigger flag "a" must be a bool flag',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: boolFlag("a"), b: strFlag("b") },
				dependencies: [implies({ flag: "a", implies: "b", value: true })],
				handler: () => 0,
			}),
		'command "cmd": Implies target flag "b" must be a bool flag',
	);
	rejects(
		() =>
			defineCommand("cmd", {
				help: "h",
				flags: { a: boolFlag("a"), b: boolFlag("b") },
				dependencies: [implies(loose({ flag: "a", implies: "b", value: 5n }))],
				handler: () => 0,
			}),
		"command \"cmd\": Implies value must be a bool, got 'int'",
	);
});

test("command: tag name validation and dedup", () => {
	rejects(
		() => defineCommand("cmd", { help: "h", tags: ["Bad"], handler: () => 0 }),
		'invalid tag name "Bad": must match [a-z][a-z0-9-]*',
	);
	const cmd = defineCommand("cmd", {
		help: "h",
		tags: ["b", "a", "b"],
		handler: () => 0,
	});
	assert.deepEqual(cmd.tags, ["b", "a"]);
});

// --- createApp validation ---

function makeApp(extra?: Partial<Parameters<typeof createApp>[0]>): AppImpl {
	return createApp({
		name: "myapp",
		version: "1.0.0",
		help: "my cool app",
		...extra,
	}) as AppImpl;
}

test("createApp: version and help are required non-empty", () => {
	rejects(
		() => createApp({ name: "myapp", version: " ", help: "h" }),
		"App.version must be a non-empty string",
	);
	rejects(
		() => createApp(loose({ name: "myapp", help: "h" })),
		"App.version must be a non-empty string",
	);
	rejects(
		() => createApp({ name: "myapp", version: "1.0.0", help: " " }),
		"App.help must be a non-empty string",
	);
});

test("createApp: all eight reserved global flag names are rejected", () => {
	for (const name of [
		"help",
		"h",
		"version",
		"v",
		"dump-schema",
		"mcp",
		"config",
		"hermetic",
	]) {
		const key = name.replaceAll("-", "_");
		rejects(
			() => makeApp({ flags: { [key]: strFlag(name) } }),
			`global flag name "${name}" is reserved`,
		);
	}
});

test("createApp: reserved global short flags are rejected", () => {
	rejects(
		() =>
			makeApp({
				flags: {
					quiet: flag("quiet", t.bool, {
						help: "h",
						short: "v",
						default: false,
					}),
				},
			}),
		'global short flag "v" is reserved',
	);
});

test("createApp: global flag map keys must be underscore forms", () => {
	rejects(
		() =>
			makeApp({
				flags: {
					dryRun: flag("dry-run", t.bool, { help: "h", default: false }),
				},
			}),
		"App.flags key 'dryRun' must be the underscore form of flag 'dry-run' ('dry_run')",
	);
});

test("createApp: handshake env var validation", () => {
	rejects(
		() => makeApp({ handshakeEnv: { MY_VAR: "  " } }),
		'handshake env var "MY_VAR": help must be a non-empty string',
	);
	rejects(
		() =>
			makeApp({
				infraRoot: { MY_ROOT: "~/x" },
				handshakeEnv: { MY_ROOT: "hello" },
			}),
		'handshake env var "MY_ROOT" is already declared as an infra root',
	);
});

test("createApp: infra roots resolve eagerly (env override, tilde expansion)", () => {
	process.env.STRICTCLI_TS_REG_TEST_ROOT = "~/from-env";
	try {
		const app = makeApp({
			infraRoot: {
				STRICTCLI_TS_REG_TEST_ROOT: "/unused-default",
				STRICTCLI_TS_REG_TEST_OTHER: "~/other-root",
			},
		});
		assert.equal(
			app.infraRoots.get("STRICTCLI_TS_REG_TEST_ROOT"),
			join(homedir(), "from-env"),
		);
		assert.equal(app.infraRootFromEnv.get("STRICTCLI_TS_REG_TEST_ROOT"), true);
		assert.equal(
			app.infraRoots.get("STRICTCLI_TS_REG_TEST_OTHER"),
			join(homedir(), "other-root"),
		);
		assert.equal(
			app.infraRootFromEnv.get("STRICTCLI_TS_REG_TEST_OTHER"),
			false,
		);
		assert.equal(
			app.infraRootDefaults.get("STRICTCLI_TS_REG_TEST_ROOT"),
			"/unused-default",
		);
	} finally {
		delete process.env.STRICTCLI_TS_REG_TEST_ROOT;
	}
});

// --- App-level registration ---

test("app.command: command flags may not collide with global flags", () => {
	const app = makeApp({ flags: { verbose: boolFlag("verbose") } });
	rejects(
		() =>
			app.command(
				defineCommand("cmd", {
					help: "h",
					flags: { verbose: boolFlag("verbose") },
					handler: () => 0,
				}),
			),
		'command "cmd": flag "verbose" collides with a global flag',
	);
});

test("app.command: env prefix enforcement", () => {
	const app = makeApp({ envPrefix: "MYAPP" });
	rejects(
		() =>
			app.command(
				defineCommand("cmd", {
					help: "h",
					flags: { target: flag("target", t.str, { help: "h", env: "TGT" }) },
					handler: () => 0,
				}),
			),
		'command "cmd": env var "TGT" for flag "target" must start with "MYAPP_" (or set prefixed=false)',
	);
	// prefixed: false opts out; a conforming prefix passes.
	app.command(
		defineCommand("ok", {
			help: "h",
			flags: {
				target: flag("target", t.str, {
					help: "h",
					env: "TGT",
					prefixed: false,
				}),
				output: flag("output", t.str, { help: "h", env: "MYAPP_OUTPUT" }),
			},
			handler: () => 0,
		}),
	);
	assert.ok(app.commands.has("ok"));
});

test("app: registration order is preserved (commands, groups, global flags)", () => {
	const app = makeApp({
		flags: { zeta: strFlag("zeta"), alpha: strFlag("alpha") },
	});
	app.command(defineCommand("bravo", { help: "h", handler: () => 0 }));
	app.command(defineCommand("alpha", { help: "h", handler: () => 0 }));
	app.command(passthrough("zulu", { help: "h", handler: () => 0 }));
	app.group("mike", { help: "h" });
	app.group("kilo", { help: "h" });
	assert.deepEqual([...app.commands.keys()], ["bravo", "alpha", "zulu"]);
	assert.deepEqual([...app.groups.keys()], ["mike", "kilo"]);
	assert.deepEqual(
		app.globalFlags.map((f) => f.name),
		["zeta", "alpha"],
	);
});

test("app: top-level re-registration overwrites in place (sibling parity)", () => {
	const app = makeApp();
	app.command(defineCommand("cmd", { help: "first", handler: () => 0 }));
	app.command(defineCommand("other", { help: "h", handler: () => 0 }));
	app.command(defineCommand("cmd", { help: "second", handler: () => 0 }));
	assert.deepEqual([...app.commands.keys()], ["cmd", "other"]);
	assert.equal(app.commands.get("cmd")?.help, "second");
});

test("app.command: merged flag order is flags, then flag sets, then mutex", () => {
	const app = makeApp();
	app.command(
		defineCommand("deploy", {
			help: "h",
			flags: { region: strFlag("region") },
			flagSets: [flagSet("common", { verbose: boolFlag("verbose") })],
			mutex: [
				mutexGroup({
					from_file: flag("from-file", t.str, { help: "h", default: null }),
					from_url: flag("from-url", t.str, { help: "h", default: null }),
				}),
			],
			handler: () => 0,
		}),
	);
	const reg = app.commands.get("deploy");
	assert.ok(reg);
	assert.deepEqual(
		reg.flags.map((f) => f.name),
		["region", "verbose", "from-file", "from-url"],
	);
});

// --- Groups ---

test("group: help and tag validation", () => {
	const app = makeApp();
	rejects(
		() => app.group("dns", { help: " " }),
		"Group.help must be a non-empty string",
	);
	rejects(
		() => app.group("dns", { help: "h", tags: ["Bad"] }),
		'invalid tag name "Bad": must match [a-z][a-z0-9-]*',
	);
});

test("group: nested collision checks", () => {
	const app = makeApp();
	const dns = app.group("dns", { help: "DNS tools" });
	dns.group("zone", { help: "Zone tools" });
	rejects(
		() => dns.group("zone", { help: "again" }),
		'group "zone" is already registered',
	);
	rejects(
		() => dns.command(defineCommand("zone", { help: "h", handler: () => 0 })),
		'command "zone" collides with an existing group',
	);
	dns.command(defineCommand("list", { help: "h", handler: () => 0 }));
	rejects(
		() => dns.group("list", { help: "h" }),
		'group "list" collides with an existing command',
	);
});

test("group: arbitrary nesting depth with sorted tag accumulation", () => {
	const app = makeApp();
	const dns = app.group("dns", { help: "DNS", tags: ["net"] });
	const zone = dns.group("zone", {
		help: "Zones",
		tags: ["zone-ops", "alpha"],
	});
	const record = zone.group("record", { help: "Records" });
	record.command(
		defineCommand("create", { help: "h", tags: ["beta"], handler: () => 0 }),
	);
	const dnsImpl = app.groups.get("dns");
	assert.ok(dnsImpl);
	const zoneImpl = dnsImpl.groups.get("zone");
	assert.ok(zoneImpl);
	const recordImpl = zoneImpl.groups.get("record");
	assert.ok(recordImpl);
	assert.deepEqual(recordImpl.accumulatedTags, ["alpha", "net", "zone-ops"]);
	assert.deepEqual(recordImpl.commands.get("create")?.tags, [
		"alpha",
		"beta",
		"net",
		"zone-ops",
	]);
});

test("group: hidden and tags are stored", () => {
	const app = makeApp();
	const g = app.group("internal", {
		help: "h",
		hidden: true,
		tags: ["b", "a"],
	});
	assert.equal(g.hidden, true);
	assert.deepEqual(g.tags, ["b", "a"]);
});

// --- Deprecated commands ---

test("deprecated: factory validates name and message", () => {
	rejects(
		() => deprecated(" ", "use other"),
		"deprecated command name must be a non-empty string",
	);
	rejects(
		() => deprecated("old-cmd", "  "),
		'deprecated command "old-cmd": message must not be empty',
	);
});

test("deprecate: collision checks at app and group level", () => {
	const app = makeApp();
	app.command(defineCommand("cmd", { help: "h", handler: () => 0 }));
	app.group("grp", { help: "h" });
	rejects(
		() => app.deprecate(deprecated("cmd", "use other")),
		'deprecated command "cmd" collides with an existing command',
	);
	rejects(
		() => app.deprecate(deprecated("grp", "use other")),
		'deprecated command "grp" collides with an existing group',
	);
	app.deprecate(deprecated("old-cmd", "use 'cmd' instead"));
	rejects(
		() => app.deprecate(deprecated("old-cmd", "again")),
		'deprecated command "old-cmd" is already registered',
	);
	assert.equal(app.deprecated.get("old-cmd"), "use 'cmd' instead");

	const grp = app.groups.get("grp");
	assert.ok(grp);
	grp.command(defineCommand("sub", { help: "h", handler: () => 0 }));
	rejects(
		() => grp.deprecate(deprecated("sub", "gone")),
		'deprecated command "sub" collides with an existing command',
	);
	grp.deprecate(deprecated("old-sub", "gone"));
	assert.equal(grp.deprecated.get("old-sub"), "gone");
});

// --- Tag contracts ---

test("tagContract: validates the tag name and stores the contract", () => {
	const app = makeApp();
	rejects(
		() => app.tagContract("Bad", "dry-run"),
		'invalid tag name "Bad": must match [a-z][a-z0-9-]*',
	);
	app.tagContract("release", "dry-run");
	assert.equal(app.tagContracts.get("release"), "dry-run");
});

// --- Integration: inference flows through app.command(defineCommand(...)) ---

type Equals<A, B> =
	(<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
		? true
		: false;
type Assert<T extends true> = T;

const deployCmd = defineCommand("deploy", {
	help: "Deploy the service",
	flags: {
		region: flag("region", t.str, {
			help: "Region",
			choices: ["eu", "us"],
			default: "eu",
		}),
		replicas: flag("replicas", t.int, { help: "Replica count" }),
	},
	flagSets: [
		flagSet("common", {
			verbose: flag("verbose", t.bool, { help: "Verbose", default: false }),
		}),
	],
	mutex: [
		mutexGroup({
			from_file: flag("from-file", t.str, { help: "From file", default: null }),
			from_url: flag("from-url", t.str, { help: "From URL", default: null }),
		}),
	],
	args: [arg("service", t.str, { help: "Service name" })],
	dependencies: [requires({ flag: "from-file", dependsOn: "region" })],
	handler: (args) => {
		type _Args = Assert<
			Equals<
				typeof args,
				{
					region: string;
					replicas: bigint;
					verbose: boolean;
					from_file?: string;
					from_url?: string;
					service: string;
				}
			>
		>;
		return args.verbose ? Number(args.replicas) : 0;
	},
});

test("integration: precisely-typed command registers with derived data intact", () => {
	const app = makeApp();
	app.command(deployCmd);
	const reg = app.commands.get("deploy");
	assert.ok(reg);
	assert.equal(reg.kind, "command");
	assert.deepEqual(
		reg.flags.map((f) => f.name),
		["region", "replicas", "verbose", "from-file", "from-url"],
	);
	assert.deepEqual(reg.tags, []);
});

// --- Type-level negative cases ---
// Never-invoked closures: only the compile errors are under test.

void [
	// @ts-expect-error version is a required createApp field
	() => createApp({ name: "x", help: "h" }),
	// @ts-expect-error help is a required createApp field
	() => createApp({ name: "x", version: "1.0.0" }),
	(app: ReturnType<typeof createApp>) =>
		// @ts-expect-error deprecated carriers register via app.deprecate, not app.command
		app.command(deprecated("old", "gone")),
	// @ts-expect-error repeatable is not available on scalar carriers
	() => flag("tag", t.str, { help: "h", repeatable: true }),
	() =>
		// @ts-expect-error configFormat is a closed union
		createApp({ name: "x", version: "1.0.0", help: "h", configFormat: "yaml" }),
];
