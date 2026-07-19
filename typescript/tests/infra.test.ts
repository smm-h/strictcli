/**
 * Infrastructure env-var tests: eager root resolution, live handshake reads,
 * the relativeToRoot() marker (branding, defaults, provenance, registration
 * validation), hermetic immunity, and the help "Infrastructure:" section.
 * Byte expectations were captured from the Go implementation (help section)
 * and the Python implementation (marker repr, registration errors) -- the
 * unit-level pins for conformance/cases/infra_env.json and the relevant
 * hermetic.json semantics.
 */

import { strict as assert } from "node:assert";
import { homedir } from "node:os";
import { test } from "node:test";
import { createApp, defineCommand, flag, t } from "../src/index.js";
import {
	buildInfraAccess,
	expandTilde,
	isInfraRootPath,
	relativeToRoot,
	resolveInfraRootPath,
	validateFlagInfraMarker,
} from "../src/infra.js";

async function withEnv<T>(
	vars: Record<string, string | undefined>,
	fn: () => Promise<T> | T,
): Promise<T> {
	const saved = new Map<string, string | undefined>();
	for (const [k, v] of Object.entries(vars)) {
		saved.set(k, process.env[k]);
		if (v === undefined) {
			delete process.env[k];
		} else {
			process.env[k] = v;
		}
	}
	try {
		return await fn();
	} finally {
		for (const [k, v] of saved) {
			if (v === undefined) {
				delete process.env[k];
			} else {
				process.env[k] = v;
			}
		}
	}
}

// --- Marker factory ---

test("infra: relativeToRoot mints a branded, frozen marker", () => {
	const m = relativeToRoot("MYAPP_HOME", "db.sqlite");
	assert.equal(isInfraRootPath(m), true);
	assert.equal(m.envVar, "MYAPP_HOME");
	assert.deepEqual([...m.parts], ["db.sqlite"]);
	assert.equal(Object.isFrozen(m), true);
	// Hand-forged structural copies are never recognized (mint set, no shape
	// detection -- the outcome() branding pattern).
	assert.equal(
		isInfraRootPath({ envVar: "MYAPP_HOME", parts: ["db.sqlite"] }),
		false,
	);
	assert.equal(isInfraRootPath(null), false);
	assert.equal(isInfraRootPath("MYAPP_HOME"), false);
});

test("infra: marker toString is the Python repr, including the empty-parts quirk", () => {
	// Captured from Python: repr(RelativeToRoot('E')) keeps the trailing ", ".
	assert.equal(String(relativeToRoot("E")), "RelativeToRoot('E', )");
	assert.equal(
		String(relativeToRoot("E", "a", "b")),
		"RelativeToRoot('E', 'a', 'b')",
	);
});

// --- Helpers ---

test("infra: expandTilde expands ~ and ~/ only", () => {
	assert.equal(expandTilde("~"), homedir());
	assert.equal(expandTilde("~/data"), `${homedir()}/data`);
	assert.equal(expandTilde("/opt/data"), "/opt/data");
	assert.equal(expandTilde("x~y"), "x~y");
});

test("infra: resolveInfraRootPath joins parts and rejects undeclared roots", () => {
	const roots = new Map([["MYAPP_HOME", "/opt/data"]]);
	assert.equal(
		resolveInfraRootPath(relativeToRoot("MYAPP_HOME", "db.sqlite"), roots),
		"/opt/data/db.sqlite",
	);
	assert.equal(
		resolveInfraRootPath(relativeToRoot("MYAPP_HOME"), roots),
		"/opt/data",
	);
	assert.throws(() => resolveInfraRootPath(relativeToRoot("NOPE"), roots), {
		message:
			'RelativeToRoot references undeclared infra root "NOPE"; declare it as an infra root',
	});
});

test("infra: buildInfraAccess snapshots roots and handshake names, null when empty", () => {
	assert.equal(buildInfraAccess(new Map(), new Map()), null);
	const access = buildInfraAccess(
		new Map([["ROOT", "/r"]]),
		new Map([["HS", "help text"]]),
	);
	assert.notEqual(access, null);
	assert.deepEqual([...(access?.roots ?? new Map())], [["ROOT", "/r"]]);
	assert.deepEqual([...(access?.handshakes ?? new Set())], ["HS"]);
});

// --- Eager root resolution at construction ---

function infraApp() {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "Test infra root resolution",
		infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
	});
	app.command(
		defineCommand("run", {
			help: "Run it",
			flags: {
				db: flag("db", t.str, {
					help: "Database path",
					default: relativeToRoot("MYAPP_HOME", "db.sqlite"),
				}),
			},
			handler: (args, ctx) => {
				ctx.info(`${ctx.source("db")}:${args.db}`);
				return 0;
			},
		}),
	);
	return app;
}

test("infra: root resolves from the env var at construction, not at parse", async () => {
	const app = await withEnv({ MYAPP_HOME: "/opt/data" }, () => infraApp());
	// Construction captured the value; a later env change must not matter.
	await withEnv({ MYAPP_HOME: "/changed/later" }, async () => {
		const r = await app.test(["run"]);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "infra:/opt/data/db.sqlite\n");
	});
});

test("infra: root env value gets ~ expanded", async () => {
	const app = await withEnv({ MYAPP_HOME: "~/data" }, () => infraApp());
	const r = await app.test(["run"]);
	assert.equal(r.stdout, `infra:${homedir()}/data/db.sqlite\n`);
});

test("infra: default path gets ~ expanded when the env var is unset", async () => {
	const app = await withEnv({ SCRATCH_HOME_X: undefined }, () =>
		createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			infraRoot: { SCRATCH_HOME_X: "~/scratch" },
		}),
	);
	app.command(
		defineCommand("show", {
			help: "show",
			handler: (_args, ctx) => {
				const [value, isSet] = ctx.infraValue("SCRATCH_HOME_X");
				ctx.info(`${value}:${isSet}`);
				return 0;
			},
		}),
	);
	const r = await app.test(["show"]);
	assert.equal(r.stdout, `${homedir()}/scratch:true\n`);
});

// --- The four infra_env.json conformance cases, at unit level ---

test("infra_env case: flag default resolves through root (env set), source is 'infra'", async () => {
	await withEnv({ MYAPP_HOME: "/opt/data" }, async () => {
		const r = await infraApp().test(["run"]);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "infra:/opt/data/db.sqlite\n");
	});
});

test("infra_env case: root unset -> declared default resolves, source is 'infra'", async () => {
	await withEnv({ MYAPP_HOME: undefined }, async () => {
		const r = await infraApp().test(["run"]);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "infra:/var/lib/myapp/db.sqlite\n");
	});
});

test("infra_env case: hermetic still resolves the marker (root has no argv dependency)", async () => {
	await withEnv({ MYAPP_HOME: "/opt/data" }, async () => {
		const r = await infraApp().test(["--hermetic", "run"]);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "infra:/opt/data/db.sqlite\n");
	});
});

test("infra_env case: CLI value overrides the marker default, source is 'cli'", async () => {
	await withEnv({ MYAPP_HOME: "/opt/data" }, async () => {
		const r = await infraApp().test(["run", "--db", "/tmp/custom.db"]);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "cli:/tmp/custom.db\n");
	});
});

// --- Hermetic interplay with per-flag env vars (hermetic.json semantics) ---

test("infra: hermetic suppresses the flag's env var but not the marker default", async () => {
	const build = () => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
		});
		app.command(
			defineCommand("run", {
				help: "run",
				flags: {
					db: flag("db", t.str, {
						help: "db",
						env: "MYAPP_DB",
						default: relativeToRoot("MYAPP_HOME", "db.sqlite"),
					}),
				},
				handler: (args, ctx) => {
					ctx.info(`${ctx.source("db")}:${args.db}`);
					return 0;
				},
			}),
		);
		return app;
	};
	await withEnv(
		{ MYAPP_HOME: "/opt/data", MYAPP_DB: "/from/env.db" },
		async () => {
			const plain = await build().test(["run"]);
			assert.equal(plain.stdout, "env:/from/env.db\n");
			const hermetic = await build().test(["--hermetic", "run"]);
			assert.equal(hermetic.stdout, "infra:/opt/data/db.sqlite\n");
		},
	);
});

// --- Global-flag marker defaults ---

test("infra: global flag marker default resolves with source 'infra'", async () => {
	const app = await withEnv({ MYAPP_HOME: undefined }, () => {
		const a = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
			flags: {
				state_dir: flag("state-dir", t.str, {
					help: "State directory",
					default: relativeToRoot("MYAPP_HOME", "state"),
				}),
			},
		});
		a.command(
			defineCommand("run", {
				help: "run",
				handler: (args, ctx) => {
					const globals = args as Record<string, unknown>;
					ctx.info(`${ctx.source("state-dir")}:${globals.state_dir}`);
					return 0;
				},
			}),
		);
		return a;
	});
	const byDefault = await app.test(["run"]);
	assert.equal(byDefault.stdout, "infra:/var/lib/myapp/state\n");
	const byCli = await app.test(["--state-dir", "/x", "run"]);
	assert.equal(byCli.stdout, "cli:/x\n");
});

// --- Handshake env vars ---

test("infra: handshake values are read live, roots stay captured", async () => {
	const app = await withEnv(
		{ MYAPP_HOME: "/opt/data", MYAPP_ORCHESTRATED: undefined },
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
				handshakeEnv: { MYAPP_ORCHESTRATED: "set by the orchestrator" },
			}),
	);
	app.command(
		defineCommand("show", {
			help: "show",
			handler: (_args, ctx) => {
				const [hs, hsSet] = ctx.infraValue("MYAPP_ORCHESTRATED");
				const [root, rootSet] = ctx.infraValue("MYAPP_HOME");
				ctx.info(`hs=${hs},${hsSet} root=${root},${rootSet}`);
				return 0;
			},
		}),
	);
	// Unset at call time -> [undefined, false], even though the app was
	// constructed while other vars were set.
	await withEnv({ MYAPP_ORCHESTRATED: undefined }, async () => {
		const r = await app.test(["show"]);
		assert.equal(r.stdout, "hs=undefined,false root=/opt/data,true\n");
	});
	// Set at call time -> live value; the root remains the captured one.
	await withEnv(
		{ MYAPP_ORCHESTRATED: "1", MYAPP_HOME: "/changed" },
		async () => {
			const r = await app.test(["show"]);
			assert.equal(r.stdout, "hs=1,true root=/opt/data,true\n");
		},
	);
});

test("infra: infraValue on an undeclared var throws the sibling message", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
	});
	app.command(
		defineCommand("show", {
			help: "show",
			handler: (_args, ctx) => {
				try {
					ctx.infraValue("OTHER");
				} catch (e) {
					ctx.info((e as Error).message);
				}
				return 0;
			},
		}),
	);
	const r = await app.test(["show"]);
	assert.equal(
		r.stdout,
		'InfraValue: "OTHER" is not a declared infra root or handshake env var\n',
	);
});

// --- Registration-time validation ---

test("infra: handshake help must be a non-empty string", () => {
	assert.throws(
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				handshakeEnv: { MYAPP_ORCHESTRATED: "   " },
			}),
		{
			message:
				'handshake env var "MYAPP_ORCHESTRATED": help must be a non-empty string',
		},
	);
});

test("infra: handshake var colliding with a declared root is rejected", () => {
	assert.throws(
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
				handshakeEnv: { MYAPP_HOME: "also a handshake" },
			}),
		{
			message:
				'handshake env var "MYAPP_HOME" is already declared as an infra root',
		},
	);
});

test("infra: global flag marker referencing an undeclared root is a hard error", () => {
	assert.throws(
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				flags: {
					db: flag("db", t.str, {
						help: "db",
						default: relativeToRoot("NOPE", "db.sqlite"),
					}),
				},
			}),
		{
			message:
				'flag "db": RelativeToRoot references undeclared infra root "NOPE"; declare it as an infra root',
		},
	);
});

test("infra: command flag marker referencing an undeclared root is a hard error", () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "t" });
	const cmd = defineCommand("run", {
		help: "run",
		flags: {
			db: flag("db", t.str, {
				help: "db",
				default: relativeToRoot("NOPE"),
			}),
		},
		handler: () => 0,
	});
	// Python's command-scoped message (the divergence ground truth).
	assert.throws(() => app.command(cmd), {
		message:
			'command "run": flag "db": RelativeToRoot references undeclared infra root "NOPE"; declare it as an infra root',
	});
});

test("infra: group-nested command flag markers are validated too", () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "t" });
	const grp = app.group("db", { help: "db group" });
	assert.throws(
		() =>
			grp.command(
				defineCommand("init", {
					help: "init",
					flags: {
						path: flag("path", t.str, {
							help: "path",
							default: relativeToRoot("NOPE"),
						}),
					},
					handler: () => 0,
				}),
			),
		{
			message:
				'command "init": flag "path": RelativeToRoot references undeclared infra root "NOPE"; declare it as an infra root',
		},
	);
});

test("infra: declared markers register cleanly at every level", () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		infraRoot: { MYAPP_HOME: "/var/lib/myapp" },
		flags: {
			state_dir: flag("state-dir", t.str, {
				help: "state",
				default: relativeToRoot("MYAPP_HOME", "state"),
			}),
		},
	});
	const grp = app.group("db", { help: "db group" });
	grp.command(
		defineCommand("init", {
			help: "init",
			flags: {
				path: flag("path", t.str, {
					help: "path",
					default: relativeToRoot("MYAPP_HOME", "db.sqlite"),
				}),
			},
			handler: () => 0,
		}),
	);
});

test("infra: validateFlagInfraMarker ignores non-marker defaults", () => {
	const roots = new Map<string, string>();
	validateFlagInfraMarker(
		flag("plain", t.str, { help: "p", default: "x" }),
		roots,
	);
	validateFlagInfraMarker(
		flag("opt", t.str, { help: "o", default: null }),
		roots,
	);
	validateFlagInfraMarker(flag("req", t.str, { help: "r" }), roots);
});

test("infra: marker on an int flag is rejected like Python (type mismatch)", () => {
	assert.throws(
		() =>
			flag("n", t.int, {
				help: "n",
				default: relativeToRoot("MYAPP_HOME"),
			}),
		{
			message: `Flag "n": type=int requires an int default, got 'RelativeToRoot'`,
		},
	);
});

test("infra: marker default vs choices renders the Python repr", () => {
	// Captured from Python: the marker repr (with the trailing ", " for empty
	// parts) lands inside the choices-mismatch message.
	assert.throws(
		() =>
			flag("c", t.str, {
				help: "c",
				choices: ["a", "b"],
				default: relativeToRoot("MYAPP_HOME"),
			}),
		{
			message: `Flag "c": default RelativeToRoot('MYAPP_HOME', ) is not in choices ['a', 'b']`,
		},
	);
});

// --- Help rendering ---

test("infra: app help renders the Infrastructure section (Go byte parity)", async () => {
	// Byte-captured from the Go implementation. SCRATCH_HOME_X is set in the
	// environment to prove help shows the DECLARED default, not the resolved
	// value, and that the annotation line documents hermetic immunity.
	const app = await withEnv({ SCRATCH_HOME_X: "/opt/data" }, () => {
		const a = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "Test infra help",
			infraRoot: {
				MYAPP_HOME: "/var/lib/myapp",
				SCRATCH_HOME_X: "~/scratch",
			},
			handshakeEnv: { MYAPP_ORCHESTRATED: "set by the orchestrator" },
		});
		a.command(defineCommand("run", { help: "Run it", handler: () => 0 }));
		return a;
	});
	const r = await app.test(["--help"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		r.stdout,
		"myapp v1.0.0 -- Test infra help\n" +
			"\n" +
			"Commands:\n" +
			"  run    Run it\n" +
			"\n" +
			"Infrastructure:\n" +
			"  (location/handshake env vars; not suppressed by --hermetic)\n" +
			"  MYAPP_HOME            root (default: /var/lib/myapp)\n" +
			"  SCRATCH_HOME_X        root (default: ~/scratch)\n" +
			"  MYAPP_ORCHESTRATED    set by the orchestrator\n" +
			"\n" +
			"Use 'myapp <command> --help' for more information.\n",
	);
});

test("infra: command help renders the marker default as the Python repr", async () => {
	const app = await withEnv({ MYAPP_HOME: undefined }, () => infraApp());
	const r = await app.test(["run", "--help"]);
	assert.equal(r.exitCode, 0);
	// Byte-captured from the Python implementation.
	assert.equal(
		r.stdout,
		"myapp run -- Run it\n" +
			"\n" +
			"Flags:\n" +
			"  --db <str>    Database path [default: RelativeToRoot('MYAPP_HOME', 'db.sqlite')]\n",
	);
});
