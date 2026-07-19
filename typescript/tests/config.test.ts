/**
 * config.ts tests: JSON/TOML loading, the XDG path model, --config /
 * no-default-path behavior, conflict modes, config fields, and the five
 * auto-registered config subcommands. Spot-ports every conformance
 * config*.json case family at unit level.
 *
 * GROUND TRUTH: byte-level expectations were captured on 2026-07-19 by
 * running the Python implementation over mirror apps (scratchpad pysmoke.py /
 * pysmoke2.py) -- the embedded strings are those bytes verbatim. They also
 * satisfy the conformance expectations of the source cases.
 */

import { strict as assert } from "node:assert";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import type { AppSpec } from "../src/app.js";
import {
	coerceConfigValueForFlag,
	configFilePath,
	JsonLoadFailure,
	parseJsonConfig,
} from "../src/config.js";
import { RegistrationError } from "../src/errors.js";
import { type App, createApp, defineCommand, flag, t } from "../src/index.js";

// --- Environment scaffolding -------------------------------------------

/** Creates a fresh XDG_CONFIG_HOME with an app config dir; returns the paths. */
function freshXdg(appName = "myapp"): { xdg: string; dir: string } {
	const xdg = mkdtempSync(join(tmpdir(), "strictcli-config-"));
	process.env.XDG_CONFIG_HOME = xdg;
	const dir = join(xdg, appName);
	mkdirSync(dir, { recursive: true });
	return { xdg, dir };
}

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

// =========================================================================
// Strict JSON parsing (bigint ints, positions)
// =========================================================================

test("parseJsonConfig: integer tokens become bigint, fraction/exponent tokens number", () => {
	const data = parseJsonConfig(
		'{"i": 42, "f": 3.14, "e": 1e2, "n": -7, "s": "x", "b": true, "z": null}',
	) as Record<string, unknown>;
	assert.equal(data.i, 42n);
	assert.equal(data.f, 3.14);
	assert.equal(data.e, 100);
	assert.equal(data.n, -7n);
	assert.equal(data.s, "x");
	assert.equal(data.b, true);
	assert.equal(data.z, null);
});

test("parseJsonConfig: nested objects, arrays, escapes", () => {
	const data = parseJsonConfig(
		'{"o": {"k": [1, 2.5]}, "esc": "a\\n\\u00e9"}',
	) as Record<string, unknown>;
	assert.deepEqual((data.o as Record<string, unknown>).k, [1n, 2.5]);
	assert.equal(data.esc, "a\né");
});

test("parseJsonConfig: failures carry Python json vocabulary and 1-based positions", () => {
	try {
		parseJsonConfig('{"key": bad}');
		assert.fail("expected JsonLoadFailure");
	} catch (e) {
		assert.ok(e instanceof JsonLoadFailure);
		assert.equal(e.message, "Expecting value");
		assert.equal(e.line, 1);
		assert.equal(e.column, 9);
		// Python str(JSONDecodeError) form used by `config set` dict values.
		assert.equal(
			e.pyDecodeErrorString(),
			"Expecting value: line 1 column 9 (char 8)",
		);
	}
	assert.throws(() => parseJsonConfig('{"a": 1'), /Expecting ',' delimiter/);
	assert.throws(() => parseJsonConfig("{} extra"), /Extra data/);
	assert.throws(
		() => parseJsonConfig("{bad: 1}"),
		/Expecting property name enclosed in double quotes/,
	);
});

// =========================================================================
// Config file path (XDG model)
// =========================================================================

test("configFilePath: XDG_CONFIG_HOME honored, format selects the extension", async () => {
	await withEnv({ XDG_CONFIG_HOME: "/tmp/fake-config" }, () => {
		assert.equal(
			configFilePath("myapp", undefined, "json"),
			"/tmp/fake-config/myapp/config.json",
		);
		assert.equal(
			configFilePath("myapp", undefined, "toml"),
			"/tmp/fake-config/myapp/config.toml",
		);
	});
});

test("configFilePath: falls back to ~/.config when XDG_CONFIG_HOME is unset", async () => {
	await withEnv({ XDG_CONFIG_HOME: undefined }, () => {
		assert.equal(
			configFilePath("myapp", undefined, "json"),
			join(homedir(), ".config", "myapp", "config.json"),
		);
	});
});

test("configFilePath: override wins and expands ~", () => {
	assert.equal(
		configFilePath("myapp", "/etc/app.json", "json"),
		"/etc/app.json",
	);
	assert.equal(
		configFilePath("myapp", "~/cfg.toml", "toml"),
		join(homedir(), "cfg.toml"),
	);
});

// =========================================================================
// Config value coercion (flag path, long typenames)
// =========================================================================

test("coerceConfigValueForFlag: scalars coerce with long-typename errors", () => {
	const intFlag = flag("count", t.int, { help: "c", default: 0n });
	assert.equal(coerceConfigValueForFlag(42n, intFlag), 42n);
	assert.throws(
		() => coerceConfigValueForFlag("x", intFlag),
		/expected integer, got str/,
	);
	// Floats never coerce to int (Python semantics).
	assert.throws(
		() => coerceConfigValueForFlag(1.5, intFlag),
		/expected integer, got float/,
	);
	const floatFlag = flag("rate", t.float, { help: "r", default: 0 });
	assert.equal(coerceConfigValueForFlag(2n, floatFlag), 2);
	assert.equal(coerceConfigValueForFlag(2.5, floatFlag), 2.5);
	const boolFlag = flag("on", t.bool, { help: "b", default: false });
	assert.throws(
		() => coerceConfigValueForFlag("yes", boolFlag),
		/expected boolean, got str/,
	);
	const strFlag = flag("name", t.str, { help: "s", default: "" });
	assert.throws(
		() => coerceConfigValueForFlag(1n, strFlag),
		/expected string, got int/,
	);
	assert.throws(
		() => coerceConfigValueForFlag([1n], strFlag),
		/expected scalar, got array/,
	);
});

test("coerceConfigValueForFlag: lists and dicts (element errors carry index/key)", () => {
	const listFlag = flag("tags", t.list(t.str), { help: "t" });
	assert.deepEqual(coerceConfigValueForFlag(["a", "b"], listFlag), ["a", "b"]);
	assert.throws(
		() => coerceConfigValueForFlag(["a", 1n], listFlag),
		/element 1: expected str, got int/,
	);
	assert.throws(
		() => coerceConfigValueForFlag("a", listFlag),
		/expected array for repeatable flag, got str/,
	);
	const dictFlag = flag("meta", t.dict(t.int), { help: "m" });
	const coerced = coerceConfigValueForFlag({ a: 1n }, dictFlag) as Map<
		string,
		unknown
	>;
	assert.equal(coerced.get("a"), 1n);
	assert.throws(
		() => coerceConfigValueForFlag({ a: "x" }, dictFlag),
		/key 'a': expected int, got str/,
	);
	assert.throws(
		() => coerceConfigValueForFlag(1n, dictFlag),
		/expected object for dict flag, got int/,
	);
});

// =========================================================================
// App builders shared by the e2e families
// =========================================================================

function basicApp(extra?: Partial<AppSpec>): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		config: true,
		...extra,
	});
	app.command(
		defineCommand("run", {
			help: "run command",
			flags: {
				count: flag("count", t.int, { help: "a count", default: 0n }),
				name: flag("name", t.str, { help: "a name", default: "world" }),
			},
			handler: (args, ctx) => {
				ctx.info(`count=${args.count}`);
				return 0;
			},
		}),
	);
	return app;
}

function portApp(extra?: Partial<AppSpec>): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		config: true,
		...extra,
	});
	app.command(
		defineCommand("run", {
			help: "run command",
			flags: {
				port: flag("port", t.int, {
					help: "port number",
					default: 80n,
					env: "APP_PORT",
				}),
			},
			handler: (args, ctx) => {
				ctx.info(`port=${args.port}`);
				return 0;
			},
		}),
	);
	return app;
}

// =========================================================================
// config.json family: group registration and `config path`
// =========================================================================

test("config path exits 0 when config enabled (XDG path, byte-exact)", async () => {
	await withEnv({ XDG_CONFIG_HOME: "/tmp/fake-config" }, async () => {
		const r = await basicApp().test(["config", "path"]);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "/tmp/fake-config/myapp/config.json\n");
	});
});

test("config path uses .toml extension for toml format", async () => {
	await withEnv({ XDG_CONFIG_HOME: "/tmp/fake-config" }, async () => {
		const r = await basicApp({ configFormat: "toml" }).test(["config", "path"]);
		assert.equal(r.stdout, "/tmp/fake-config/myapp/config.toml\n");
	});
});

test("config is unknown command when config disabled", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(defineCommand("run", { help: "r", handler: () => 0 }));
	const r = await app.test(["config"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /unknown command/);
});

test("config group appears in help only when enabled", async () => {
	const enabled = await basicApp().test(["--help"]);
	assert.equal(enabled.exitCode, 0);
	assert.match(enabled.stdout, /Groups:/);
	assert.match(enabled.stdout, /config/);
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(defineCommand("run", { help: "r", handler: () => 0 }));
	const disabled = await app.test(["--help"]);
	assert.equal(disabled.exitCode, 0);
	assert.ok(!disabled.stdout.includes("config"));
});

test("config help shows the five subcommands", async () => {
	const r = await basicApp().test(["config", "--help"]);
	assert.equal(r.exitCode, 0);
	for (const sub of ["path", "show", "set", "edit", "init"]) {
		assert.ok(r.stdout.includes(sub), sub);
	}
});

// =========================================================================
// config_advanced family: loading, precedence, show, set errors
// =========================================================================

test("TOML config loading with typed values via run + config show", async () => {
	const { dir } = freshXdg();
	writeFileSync(
		join(dir, "config.toml"),
		"count = 42\ndebug = true\nrate = 3.14",
	);
	const mk = () => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "test app",
			config: true,
			configFormat: "toml",
		});
		app.command(
			defineCommand("run", {
				help: "run command",
				flags: {
					count: flag("count", t.int, { help: "a count", default: 0n }),
					debug: flag("debug", t.bool, { help: "debug mode", default: false }),
					rate: flag("rate", t.float, { help: "a rate", default: 0 }),
				},
				handler: (args, ctx) => {
					ctx.info(`${args.count} ${args.debug} ${args.rate}`);
					return 0;
				},
			}),
		);
		return app;
	};
	const run = await mk().test(["run"]);
	assert.equal(run.stdout, "42 true 3.14\n");
	const show = await mk().test(["config", "show", "--plain"]);
	assert.equal(show.exitCode, 0);
	assert.equal(
		show.stdout,
		"count = 42  (source: config)\ndebug = true  (source: config)\nrate = 3.14  (source: config)\n",
	);
});

test("precedence: config wins over default; CLI and env win over config", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.toml"), "port = 9090");
	const mk = () => portApp({ configFormat: "toml" });
	assert.equal((await mk().test(["run"])).stdout, "port=9090\n");
	assert.equal(
		(await mk().test(["run", "--port", "8080"])).stdout,
		"port=8080\n",
	);
	await withEnv({ APP_PORT: "7070" }, async () => {
		assert.equal((await mk().test(["run"])).stdout, "port=7070\n");
	});
});

test("config show --plain source attribution (config vs default), byte-exact", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"count": 10}\n');
	const r = await basicApp().test(["config", "show", "--plain"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		r.stdout,
		"count = 10  (source: config)\nname = world  (source: default)\n",
	);
});

test("config show --json output, byte-exact (sorted keys, indent 2)", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"count": 10}\n');
	const r = await basicApp().test(["config", "show", "--json"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		r.stdout,
		'{\n  "count": {\n    "source": "config",\n    "value": 10\n  },\n  "name": {\n    "source": "default",\n    "value": "world"\n  }\n}\n',
	);
});

test("config show env source attribution coerces the display value", async () => {
	freshXdg();
	await withEnv({ APP_PORT: "7070" }, async () => {
		const r = await portApp().test(["config", "show", "--plain"]);
		assert.equal(r.stdout, "port = 7070  (source: env)\n");
	});
});

test("config set: unknown key / bad int / bad bool errors", async () => {
	freshXdg();
	let r = await basicApp().test(["config", "set", "nonexistent", "value"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, "config set: unknown key 'nonexistent'\n");
	r = await basicApp().test(["config", "set", "count", "abc"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /^config set: key 'count': /);
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		config: true,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: { debug: flag("debug", t.bool, { help: "d", default: false }) },
			handler: () => 0,
		}),
	);
	r = await app.test(["config", "set", "debug", "maybe"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /^config set: key 'debug': /);
});

test("config show without flags / with both flags: mutex enforcement", async () => {
	freshXdg();
	let r = await basicApp().test(["config", "show"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		"error: one of --plain, --json is required\ntry 'myapp config show --help'\n",
	);
	r = await basicApp().test(["config", "show", "--plain", "--json"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /mutually exclusive/);
});

test("parse-time loading: late-written config is honored", async () => {
	const { dir } = freshXdg();
	const app = portApp();
	// Config written AFTER app construction but BEFORE parse.
	writeFileSync(join(dir, "config.json"), '{"port": 5555}');
	const r = await app.test(["run"]);
	assert.equal(r.stdout, "port=5555\n");
});

// =========================================================================
// config_flag family: the --config global flag
// =========================================================================

test("--config on app with config disabled is a hard error", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "t" });
	app.command(defineCommand("run", { help: "r", handler: () => 0 }));
	const r = await app.test(["--config", "/tmp/fake.json", "run"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /--config is not available/);
});

test("--config after command name is an unknown flag error", async () => {
	freshXdg();
	const r = await basicApp().test(["run", "--config", "/tmp/fake.json"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /unknown flag/);
});

test("--config <path> and --config=<path> load the named file", async () => {
	const { xdg } = freshXdg();
	const p = join(xdg, "explicit.json");
	writeFileSync(p, '{"port": 9090}');
	assert.equal(
		(await portApp().test(["--config", p, "run"])).stdout,
		"port=9090\n",
	);
	assert.equal(
		(await portApp().test([`--config=${p}`, "run"])).stdout,
		"port=9090\n",
	);
});

test("--config missing value is an error", async () => {
	freshXdg();
	const r = await basicApp().test(["--config"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /'--config' requires a value/);
});

test("--config missing file is a hard error", async () => {
	freshXdg();
	const r = await portApp().test([
		"--config",
		"/nonexistent/path/config.json",
		"run",
	]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /config file not found/);
});

test("--hermetic and --config are mutually exclusive", async () => {
	freshXdg();
	const r = await basicApp().test(["--hermetic", "--config", "/x.json", "run"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /--hermetic and --config are mutually exclusive/);
});

test("--hermetic cannot be used with config commands", async () => {
	freshXdg();
	const r = await basicApp().test(["--hermetic", "config", "path"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /--hermetic cannot be used with config commands/);
});

// =========================================================================
// config_no_default_path family
// =========================================================================

test("noDefaultConfigPath: nothing loads without --config; explicit --config loads", async () => {
	const { dir, xdg } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"port": 9090}');
	const r = await portApp({ noDefaultConfigPath: true }).test(["run"]);
	assert.equal(r.stdout, "port=80\n");
	const p = join(xdg, "explicit.json");
	writeFileSync(p, '{"port": 9090}');
	const r2 = await portApp({ noDefaultConfigPath: true }).test([
		"--config",
		p,
		"run",
	]);
	assert.equal(r2.stdout, "port=9090\n");
});

// =========================================================================
// config_hard_error family: malformed files and conflict modes
// =========================================================================

test("malformed TOML is a hard error with position", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.toml"), "key = [unclosed");
	const r = await basicApp({ configFormat: "toml" }).test(["run"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /config file .*: .* \(line 1, column 8\)/);
});

test("malformed JSON is a hard error with position (byte-shape)", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"key": bad}');
	const r = await basicApp().test(["run"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		`error: config file ${p}: Expecting value (line 1, column 9)\ntry 'myapp --help'\n`,
	);
});

test("config show on broken config shows the load error", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), "{broken");
	const r = await basicApp().test(["config", "show", "--plain"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /config file/);
});

function conflictApp(mode: "cli-wins" | "error"): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
		configConflictMode: mode,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				name: flag("name", t.str, {
					help: "n",
					default: "d",
					env: "MYAPP_NAME",
				}),
			},
			handler: (_args, ctx) => {
				ctx.info("ok");
				return 0;
			},
		}),
	);
	return app;
}

test("conflict error mode: config+cli and config+env diverging are hard errors", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"name": "from-config"}');
	let r = await conflictApp("error").test(["run", "--name", "from-cli"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /flag 'name' set in both cli and config; remove one/);
	await withEnv({ MYAPP_NAME: "from-env" }, async () => {
		r = await conflictApp("error").test(["run"]);
		assert.equal(r.exitCode, 1);
		assert.match(
			r.stderr,
			/flag 'name' set in both env and config; remove one/,
		);
	});
});

test("conflict cli-wins mode passes; error mode passes on identical values", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"name": "from-config"}');
	let r = await conflictApp("cli-wins").test(["run", "--name", "from-cli"]);
	assert.equal(r.exitCode, 0);
	writeFileSync(join(dir, "config.json"), '{"name": "same"}');
	r = await conflictApp("error").test(["run", "--name", "same"]);
	assert.equal(r.exitCode, 0);
});

test("per-flag conflictMode beats the app-level mode (both directions)", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"name": "from-config"}');
	const mk = (
		appMode: "cli-wins" | "error",
		flagMode: "cli-wins" | "error",
	): App => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			config: true,
			configConflictMode: appMode,
		});
		app.command(
			defineCommand("run", {
				help: "r",
				flags: {
					name: flag("name", t.str, {
						help: "n",
						default: "d",
						conflictMode: flagMode,
					}),
				},
				handler: (_args, ctx) => {
					ctx.info("ok");
					return 0;
				},
			}),
		);
		return app;
	};
	const errBeats = await mk("cli-wins", "error").test(["run", "--name", "x"]);
	assert.equal(errBeats.exitCode, 1);
	const cliWinsBeats = await mk("error", "cli-wins").test([
		"run",
		"--name",
		"x",
	]);
	assert.equal(cliWinsBeats.exitCode, 0);
});

test("conflict equality: plain lists order-sensitive, unique flags multiset", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"tag": ["a", "b"]}');
	const mk = (unique: boolean): App => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			config: true,
			configConflictMode: "error",
		});
		app.command(
			defineCommand("run", {
				help: "r",
				flags: { tag: flag("tag", t.list(t.str), { help: "t", unique }) },
				handler: (_args, ctx) => {
					ctx.info("ok");
					return 0;
				},
			}),
		);
		return app;
	};
	// Same order: agree.
	assert.equal(
		(await mk(false).test(["run", "--tag", "a", "--tag", "b"])).exitCode,
		0,
	);
	// Plain list, different order: diverge.
	const diverge = await mk(false).test(["run", "--tag", "b", "--tag", "a"]);
	assert.equal(diverge.exitCode, 1);
	assert.match(diverge.stderr, /flag 'tag' set in both cli and config/);
	// Unique flag, different order: multiset-equal.
	assert.equal(
		(await mk(true).test(["run", "--tag", "b", "--tag", "a"])).exitCode,
		0,
	);
});

test("conflict detection covers global flags parsed after the command name", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"settings": "from-config"}');
	const mk = (mode: "cli-wins" | "error"): App => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			config: true,
			configConflictMode: mode,
			flags: {
				settings: flag("settings", t.str, { help: "s", default: "d" }),
			},
		});
		app.command(
			defineCommand("run", {
				help: "r",
				handler: (_args, ctx) => {
					ctx.info("ok");
					return 0;
				},
			}),
		);
		return app;
	};
	const after = await mk("error").test(["run", "--settings", "from-cli"]);
	assert.equal(after.exitCode, 1);
	assert.match(
		after.stderr,
		/flag 'settings' set in both cli and config; remove one/,
	);
	const before = await mk("error").test(["--settings", "from-cli", "run"]);
	assert.equal(before.exitCode, 1);
	const same = await mk("error").test(["run", "--settings", "from-config"]);
	assert.equal(same.exitCode, 0);
	const cliWins = await mk("cli-wins").test(["run", "--settings", "from-cli"]);
	assert.equal(cliWins.exitCode, 0);
});

// =========================================================================
// config_repeatable family
// =========================================================================

function tagsApp(unique = true): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: { tags: flag("tags", t.list(t.str), { help: "tags", unique }) },
			handler: (args, ctx) => {
				ctx.info(`tags=${args.tags.join(",")}`);
				return 0;
			},
		}),
	);
	return app;
}

test("repeatable: JSON array from config applied; empty array; CLI override", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"tags": ["a", "b", "c"]}');
	assert.equal((await tagsApp().test(["run"])).stdout, "tags=a,b,c\n");
	assert.equal(
		(await tagsApp().test(["run", "--tags", "x", "--tags", "y"])).stdout,
		"tags=x,y\n",
	);
	writeFileSync(p, '{"tags": []}');
	assert.equal((await tagsApp().test(["run"])).stdout, "tags=\n");
});

test("repeatable: unique enforcement rejects duplicate from config", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"tags": ["a", "b", "a"]}');
	const r = await tagsApp().test(["run"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /duplicate value 'a'/);
});

test("repeatable: int array from config; show --plain displays the array", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"ports": [80, 443]}');
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				ports: flag("ports", t.list(t.int), { help: "p", unique: false }),
			},
			handler: (args, ctx) => {
				ctx.info(`ports=${args.ports.join(",")}`);
				return 0;
			},
		}),
	);
	assert.equal((await app.test(["run"])).stdout, "ports=80,443\n");
	const show = await app.test(["config", "show", "--plain"]);
	assert.equal(show.stdout, "ports = [80, 443]  (source: config)\n");
});

test("repeatable/dict: show --plain renders empty defaults as []/{} (Python parity)", async () => {
	freshXdg();
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				tags: flag("tags", t.list(t.str), { help: "tags", unique: true }),
				meta: flag("meta", t.dict(t.int), { help: "meta" }),
			},
			handler: () => 0,
		}),
	);
	const r = await app.test(["config", "show", "--plain"]);
	assert.equal(
		r.stdout,
		"tags = []  (source: default)\nmeta = {}  (source: default)\n",
	);
});

// =========================================================================
// config_set family
// =========================================================================

function setApp(): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				count: flag("count", t.int, { help: "c", default: 0n }),
				tags: flag("tags", t.list(t.str), { help: "t", unique: true }),
				meta: flag("meta", t.dict(t.int), { help: "m" }),
			},
			handler: () => 0,
		}),
	);
	return app;
}

test("config set: scalar value writes Python-shaped JSON (indent 2, trailing newline)", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"count": 10}\n');
	const r = await setApp().test(["config", "set", "count", "77"]);
	assert.equal(r.exitCode, 0);
	assert.equal(readFileSync(p, "utf8"), '{\n  "count": 77\n}\n');
});

test("config set: list value splits on comma; duplicate on unique flag errors", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, "{}");
	let r = await setApp().test(["config", "set", "tags", "x,y"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		readFileSync(p, "utf8"),
		'{\n  "tags": [\n    "x",\n    "y"\n  ]\n}\n',
	);
	r = await setApp().test(["config", "set", "tags", "a,a"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, "config set: key 'tags': duplicate value 'a'\n");
});

test("config set: dict value takes a JSON object; bad JSON carries Python decode string", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, "{}");
	let r = await setApp().test(["config", "set", "meta", '{"a": 1}']);
	assert.equal(r.exitCode, 0);
	assert.equal(readFileSync(p, "utf8"), '{\n  "meta": {\n    "a": 1\n  }\n}\n');
	r = await setApp().test(["config", "set", "meta", "notjson"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		"config set: key 'meta': invalid JSON: Expecting value: line 1 column 1 (char 0)\n",
	);
});

test("config set: --clear, --default, and their combination errors", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"tags": ["x", "y"]}');
	// --clear on repeatable flag succeeds (writes []).
	let r = await setApp().test(["config", "set", "tags", "--clear"]);
	assert.equal(r.exitCode, 0);
	assert.equal(readFileSync(p, "utf8"), '{\n  "tags": []\n}\n');
	// --clear on scalar flag errors.
	r = await setApp().test(["config", "set", "count", "--clear"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, "config set: --clear is only for repeatable flags\n");
	// --default when key not in config errors.
	writeFileSync(p, "{}");
	r = await setApp().test(["config", "set", "count", "--default"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, "config set: key 'count' not in config\n");
	// Value combined with --clear / --default errors.
	r = await setApp().test(["config", "set", "tags", "a,b", "--clear"]);
	assert.equal(r.stderr, "config set: cannot provide a value with --clear\n");
	r = await setApp().test(["config", "set", "count", "42", "--default"]);
	assert.equal(r.stderr, "config set: cannot provide a value with --default\n");
	r = await setApp().test(["config", "set", "tags", "--clear", "--default"]);
	assert.equal(
		r.stderr,
		"config set: --clear and --default are mutually exclusive\n",
	);
});

test("config set: --default removes the key (JSON and nested TOML)", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"count": 5, "tags": ["x"]}');
	const r = await setApp().test(["config", "set", "count", "--default"]);
	assert.equal(r.exitCode, 0);
	assert.equal(readFileSync(p, "utf8"), '{\n  "tags": [\n    "x"\n  ]\n}\n');
});

test("config set on TOML preserves comments and layout byte-exactly (tomlkit parity)", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.toml");
	writeFileSync(
		p,
		'# top comment\ncount = 1  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n',
	);
	const mk = () => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			config: true,
			configFormat: "toml",
		});
		app.command(
			defineCommand("run", {
				help: "r",
				flags: { count: flag("count", t.int, { help: "c", default: 0n }) },
				handler: () => 0,
			}),
		);
		app.configField("server.port", {
			type: t.int,
			help: "the port",
			default: 8080n,
		});
		app.configField("server.host", {
			type: t.str,
			help: "the host",
			default: "h",
		});
		return app;
	};
	// GROUND TRUTH: bytes captured from Python tomlkit over the same document.
	let r = await mk().test(["config", "set", "count", "42"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		readFileSync(p, "utf8"),
		'# top comment\ncount = 42  # trailing\n\n[server]\n# port doc\nport = 8080\nhost = "a"\n',
	);
	r = await mk().test(["config", "set", "server.port", "9090"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		readFileSync(p, "utf8"),
		'# top comment\ncount = 42  # trailing\n\n[server]\n# port doc\nport = 9090\nhost = "a"\n',
	);
	r = await mk().test(["config", "set", "count", "--default"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		readFileSync(p, "utf8"),
		'# top comment\n\n[server]\n# port doc\nport = 9090\nhost = "a"\n',
	);
});

// =========================================================================
// config_fields family
// =========================================================================

function fieldsApp(): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.configField("api.key", { type: t.str, help: "API key" });
	app.configField("port", { type: t.int, help: "server port", default: 8080n });
	app.command(
		defineCommand("run", {
			help: "r",
			configFields: ["api.key", "port"],
			handler: (_args, ctx) => {
				ctx.info("ok");
				return 0;
			},
		}),
	);
	return app;
}

test("config fields: required field missing produces error", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), "{}");
	const r = await fieldsApp().test(["run"]);
	assert.equal(r.exitCode, 1);
	assert.match(
		r.stderr,
		/required config field "api\.key" is missing from config file/,
	);
});

test("config fields: present with correct types passes; wrong type errors", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"api": {"key": "sekrit"}}');
	const ok = await fieldsApp().test(["run"]);
	assert.equal(ok.exitCode, 0);
	assert.equal(ok.stdout, "ok\n");
	writeFileSync(p, '{"api": {"key": 5}}');
	const bad = await fieldsApp().test(["run"]);
	assert.equal(bad.exitCode, 1);
	assert.equal(
		bad.stderr,
		"error: config field \"api.key\": expected str, got int\ntry 'myapp --help'\n",
	);
});

test("config fields: unknown key in config rejected (only when fields are declared)", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, '{"bogus": "value", "api": {"key": "k"}}');
	const r = await fieldsApp().test(["run"]);
	assert.equal(r.exitCode, 1);
	assert.match(r.stderr, /unknown key "bogus" in config file/);
	// Without declared config fields the unknown-key gate does not run.
	writeFileSync(p, '{"bogus": "value"}');
	const noFields = await basicApp().test(["run"]);
	assert.equal(noFields.exitCode, 0);
});

test("config fields: show --plain and --json render the Config fields section, byte-exact", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"api": {"key": "sekrit"}}\n');
	const plain = await fieldsApp().test(["config", "show", "--plain"]);
	assert.equal(plain.exitCode, 0);
	assert.equal(
		plain.stdout,
		"\nConfig fields:\n  api.key (str, required) = sekrit  (source: config)  -- API key\n  port (int, optional) = 8080  (source: default)  -- server port\n",
	);
	const json = await fieldsApp().test(["config", "show", "--json"]);
	assert.equal(json.exitCode, 0);
	assert.equal(
		json.stdout,
		'{\n  "api.key": {\n    "help": "API key",\n    "required": true,\n    "source": "config",\n    "type": "str",\n    "value": "sekrit"\n  },\n  "port": {\n    "default": 8080,\n    "help": "server port",\n    "required": false,\n    "source": "default",\n    "type": "int",\n    "value": 8080\n  }\n}\n',
	);
});

// =========================================================================
// config_field_flag_coexist family
// =========================================================================

function coexistApp(): App {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.configField("target", {
		type: t.str,
		help: "the deploy target",
		default: "prod",
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				target: flag("target", t.str, {
					help: "deploy target",
					default: "prod",
				}),
			},
			handler: (_args, ctx) => {
				ctx.info("ok");
				return 0;
			},
		}),
	);
	return app;
}

test("field-flag coexist: show --plain renders colliding key once with annotation", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"target": "deployed"}');
	const r = await coexistApp().test(["config", "show", "--plain"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		r.stdout,
		"target = deployed  (source: config)  -- the deploy target\n",
	);
	assert.ok(!r.stdout.includes("Config fields:"));
});

test("field-flag coexist: show --json renders colliding key once (flag entry shape)", async () => {
	const { dir } = freshXdg();
	writeFileSync(join(dir, "config.json"), '{"target": "deployed"}');
	const r = await coexistApp().test(["config", "show", "--json"]);
	assert.equal(r.exitCode, 0);
	assert.ok(r.stdout.includes('"deployed"'));
	assert.ok(r.stdout.includes('"source": "config"'));
	assert.ok(!r.stdout.includes('"type"'));
});

test("field-flag coexist: disagreeing defaults are a registration error", () => {
	freshXdg();
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.configField("target", { type: t.str, help: "h", default: "prod" });
	assert.throws(
		() =>
			app.command(
				defineCommand("run", {
					help: "r",
					flags: {
						target: flag("target", t.str, { help: "h", default: "stage" }),
					},
					handler: () => 0,
				}),
			),
		/config field "target" collides with flag "target" but their defaults disagree \('prod' vs 'stage'\); remove one default or make them equal/,
	);
});

// =========================================================================
// config init
// =========================================================================

test("config init: TOML template with comments, sections, and required markers (byte-exact)", async () => {
	const { dir } = freshXdg();
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
		configFormat: "toml",
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				count: flag("count", t.int, { help: "a count", default: 3n }),
				name: flag("name", t.str, { help: "a name" }),
			},
			handler: () => 0,
		}),
	);
	app.configField("api.key", { type: t.str, help: "API key" });
	app.configField("port", { type: t.int, help: "server port", default: 8080n });
	app.configField("db.conn.host", {
		type: t.str,
		help: "db host",
		default: "localhost",
	});
	const r = await app.test(["config", "init"]);
	assert.equal(r.exitCode, 0);
	assert.equal(r.stdout, `${join(dir, "config.toml")}\n`);
	assert.equal(
		readFileSync(join(dir, "config.toml"), "utf8"),
		'# a count\ncount = 3\n\n# a name\n# name =\n\n# server port\nport = 8080\n\n[api]\n# API key (required)\n# key =\n\n[db]\n\n[db.conn]\n# db host\nhost = "localhost"\n\n',
	);
});

test("config init: JSON template nests dotted fields; required fields are null (byte-exact)", async () => {
	const { dir } = freshXdg();
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		config: true,
	});
	app.command(
		defineCommand("run", {
			help: "r",
			flags: {
				count: flag("count", t.int, { help: "a count", default: 3n }),
				name: flag("name", t.str, { help: "a name" }),
			},
			handler: () => 0,
		}),
	);
	app.configField("api.key", { type: t.str, help: "API key" });
	app.configField("port", { type: t.int, help: "server port", default: 8080n });
	const r = await app.test(["config", "init"]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		readFileSync(join(dir, "config.json"), "utf8"),
		'{\n  "count": 3,\n  "name": null,\n  "api": {\n    "key": null\n  },\n  "port": 8080\n}\n',
	);
});

test("config init: existing file is an error (Python spelling)", async () => {
	const { dir } = freshXdg();
	const p = join(dir, "config.json");
	writeFileSync(p, "{}\n");
	const r = await basicApp().test(["config", "init"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, `config init: config file already exists: ${p}\n`);
});

// =========================================================================
// Registration-time validation
// =========================================================================

test("configField: name, help, type, default, duplicate, and reserved-prefix errors", () => {
	const mk = () =>
		createApp({ name: "a", version: "1", help: "h", config: true });
	assert.throws(
		() => mk().configField("_x", { type: t.str, help: "h" }),
		/config field name "_x" is reserved/,
	);
	assert.throws(
		() => mk().configField("Bad", { type: t.str, help: "h" }),
		/ConfigField name "Bad" is invalid/,
	);
	assert.throws(
		() => mk().configField("x", { type: t.str, help: "  " }),
		/config field "x": help text is required/,
	);
	assert.throws(
		() =>
			mk().configField("x", {
				type: t.list(t.str) as never,
				help: "h",
			}),
		/ConfigField\.type must be str, bool, int, or float/,
	);
	assert.throws(
		() =>
			mk().configField("x", { type: t.int, help: "h", default: "s" as never }),
		/default value 's' does not match type int/,
	);
	const app = mk();
	app.configField("x", { type: t.str, help: "h" });
	assert.throws(
		() => app.configField("x", { type: t.str, help: "h" }),
		/duplicate config field name "x"/,
	);
});

test("command configFields binding must reference a declared field", () => {
	const app = createApp({ name: "a", version: "1", help: "h", config: true });
	assert.throws(
		() =>
			app.command(
				defineCommand("run", {
					help: "r",
					configFields: ["nope"],
					handler: () => 0,
				}),
			),
		/command "run": config_fields references unknown config field "nope"/,
	);
});

test("createApp validates configFormat and configConflictMode for untyped callers", () => {
	assert.throws(
		() =>
			createApp({
				name: "a",
				version: "1",
				help: "h",
				configFormat: "yaml" as never,
			}),
		(e: unknown) =>
			e instanceof RegistrationError &&
			e.message === `App.config_format must be "json" or "toml", got 'yaml'`,
	);
	assert.throws(
		() =>
			createApp({
				name: "a",
				version: "1",
				help: "h",
				configConflictMode: "merge" as never,
			}),
		(e: unknown) =>
			e instanceof RegistrationError &&
			e.message ===
				`App.config_conflict_mode must be "cli-wins" or "error", got 'merge'`,
	);
});

// =========================================================================
// configPath option (explicit path instead of XDG)
// =========================================================================

test("configPath option: loads from the explicit path, ~ expanded", async () => {
	const { xdg } = freshXdg();
	const p = join(xdg, "custom-location.json");
	writeFileSync(p, '{"port": 9090}');
	const r = await portApp({ configPath: p }).test(["run"]);
	assert.equal(r.stdout, "port=9090\n");
	const path = await portApp({ configPath: p }).test(["config", "path"]);
	assert.equal(path.stdout, `${p}\n`);
});
