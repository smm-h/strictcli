/**
 * Help rendering tests, byte-pinned against the conformance suite: every
 * expected string below is a `stdout_equals` value from conformance/cases/
 * (help.json, nesting.json, env.json, choices.json, int_type.json,
 * repeatable.json, mutex.json, global_flags.json, flag_sets.json,
 * passthrough.json) plus a trailing newline, or -- for app-level sections
 * with no conformance stdout_equals case (Deprecated / Global flags /
 * Infrastructure) -- the exact stdout captured from the Python
 * implementation's app.test() (see scripts noted inline).
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	arg,
	createApp,
	defineCommand,
	deprecated,
	flag,
	flagSet,
	mutexGroup,
	passthrough,
	t,
} from "../src/index.js";

const ok = () => undefined;

test("help: app help shows version and commands (help.json)", async () => {
	const app = createApp({
		name: "myapp",
		version: "3.0.0",
		help: "my cool app",
	});
	app.command(defineCommand("run", { help: "run something", handler: ok }));
	app.command(defineCommand("test", { help: "run tests", handler: ok }));
	const r = await app.test([]);
	assert.equal(
		r.stdout,
		"myapp v3.0.0 -- my cool app\n\nCommands:\n  run     run something\n  test    run tests\n\nUse 'myapp <command> --help' for more information.\n",
	);
	assert.equal(r.stderr, "");
	assert.equal(r.exitCode, 0);
});

test("help: command help shows flags and args (help.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("deploy", {
			help: "deploy the app",
			args: [arg("target", t.str, { help: "deploy target" })],
			flags: {
				dry_run: flag("dry-run", t.bool, {
					help: "preview changes",
					default: false,
				}),
			},
			handler: ok,
		}),
	);
	const r = await app.test(["deploy", "--help"]);
	assert.equal(
		r.stdout,
		"myapp deploy -- deploy the app\n\nArguments:\n  target    deploy target\n\nFlags:\n  --dry-run, --no-dry-run    preview changes [default: false]\n",
	);
	assert.equal(r.exitCode, 0);
});

test("help: command help via -h shows only the header (help.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(defineCommand("deploy", { help: "deploy the app", handler: ok }));
	const r = await app.test(["deploy", "-h"]);
	assert.equal(r.stdout, "myapp deploy -- deploy the app\n");
});

test("help: str flag shows <str> and default (help.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				output: flag("output", t.str, {
					help: "output path",
					default: "out.txt",
				}),
			},
			handler: ok,
		}),
	);
	const r = await app.test(["cmd", "--help"]);
	assert.equal(
		r.stdout,
		"myapp cmd -- a command\n\nFlags:\n  --output <str>    output path [default: out.txt]\n",
	);
});

test("help: required flag shown as [required] (help.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { target: flag("target", t.str, { help: "the target" }) },
			handler: ok,
		}),
	);
	const r = await app.test(["cmd", "--help"]);
	assert.equal(
		r.stdout,
		"myapp cmd -- a command\n\nFlags:\n  --target <str>    the target [required]\n",
	);
});

test("help: explicitly-optional flag shows [optional] (Go Default(nil) fix)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				target: flag("target", t.str, { help: "the target", default: null }),
			},
			handler: ok,
		}),
	);
	const r = await app.test(["cmd", "--help"]);
	assert.equal(
		r.stdout,
		"myapp cmd -- a command\n\nFlags:\n  --target <str>    the target [optional]\n",
	);
});

test("help: app help shows groups (help.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	const grp = app.group("config", { help: "manage configuration" });
	grp.command(defineCommand("show", { help: "display config", handler: ok }));
	const r = await app.test([]);
	assert.equal(
		r.stdout,
		"myapp v1.0.0 -- test app\n\nGroups:\n  config    manage configuration\n\nUse 'myapp <command> --help' for more information.\n",
	);
});

test("help: optional arg shows default / [optional] (help.json)", async () => {
	const withDefault = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
	});
	withDefault.command(
		defineCommand("cmd", {
			help: "a command",
			args: [
				arg("path", t.str, {
					help: "project dir",
					required: false,
					default: ".",
				}),
			],
			handler: ok,
		}),
	);
	assert.equal(
		(await withDefault.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nArguments:\n  path    project dir [default: .]\n",
	);

	const noDefault = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
	});
	noDefault.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("path", t.str, { help: "project dir", required: false })],
			handler: ok,
		}),
	);
	assert.equal(
		(await noDefault.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nArguments:\n  path    project dir [optional]\n",
	);
});

test("help: env var and choices metadata (env.json, choices.json)", async () => {
	const envApp = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		envPrefix: "MYAPP",
	});
	envApp.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				target: flag("target", t.str, {
					help: "the target",
					default: "x",
					env: "MYAPP_TARGET",
				}),
			},
			handler: ok,
		}),
	);
	assert.equal(
		(await envApp.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --target <str>    the target [env: MYAPP_TARGET] [default: x]\n",
	);

	const choicesApp = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
	});
	choicesApp.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				format: flag("format", t.str, {
					help: "output format",
					choices: ["text", "json"],
					default: "text",
				}),
			},
			handler: ok,
		}),
	);
	assert.equal(
		(await choicesApp.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --format <str>    output format [choices: text, json] [default: text]\n",
	);
});

test("help: int flag shows <int> (int_type.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				port: flag("port", t.int, { help: "the port", default: 8000n }),
			},
			handler: ok,
		}),
	);
	assert.equal(
		(await app.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --port <int>    the port [default: 8000]\n",
	);
});

test("help: repeatable list flags show [repeatable] (repeatable.json)", async () => {
	const bare = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	bare.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				tag: flag("tag", t.list(t.str), { help: "a tag", repeatable: true }),
			},
			handler: ok,
		}),
	);
	assert.equal(
		(await bare.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --tag <str>    a tag [repeatable]\n",
	);

	const withDefault = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
	});
	withDefault.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				tag: flag("tag", t.list(t.str), {
					help: "a tag",
					repeatable: true,
					default: ["x", "y"],
				}),
			},
			handler: ok,
		}),
	);
	assert.equal(
		(await withDefault.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --tag <str>    a tag [repeatable] [default: x, y]\n",
	);
});

test("help: mutex groups render their own section (mutex.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				name: flag("name", t.str, { help: "your name", default: "anon" }),
			},
			mutex: [
				mutexGroup({
					verbose: flag("verbose", t.bool, { help: "verbose output" }),
					quiet: flag("quiet", t.bool, { help: "quiet output" }),
				}),
			],
			handler: ok,
		}),
	);
	assert.equal(
		(await app.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --name <str>    your name [default: anon]\n\nFlags (mutually exclusive):\n  --verbose, --no-verbose    verbose output [required]\n  --quiet, --no-quiet        quiet output [required]\n",
	);
});

test("help: global flags in command help (global_flags.json)", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "enable verbose output",
				default: false,
			}),
		},
	});
	app.command(defineCommand("cmd", { help: "a command", handler: ok }));
	assert.equal(
		(await app.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nGlobal flags:\n  --verbose, --no-verbose    enable verbose output [default: false]\n",
	);
});

test("help: nested command help shows the group prefix (nesting.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	const grp = app.group("config", { help: "manage configuration" });
	grp.command(
		defineCommand("set", {
			help: "set a config value",
			flags: {
				key: flag("key", t.str, { help: "config key" }),
				value: flag("value", t.str, { help: "config value" }),
			},
			handler: ok,
		}),
	);
	assert.equal(
		(await app.test(["config", "set", "--help"])).stdout,
		"myapp config set -- set a config value\n\nFlags:\n  --key <str>      config key [required]\n  --value <str>    config value [required]\n",
	);
});

test("help: 3-level nesting (nesting.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	const dns = app.group("dns", { help: "manage DNS" });
	dns.command(
		defineCommand("status", { help: "show DNS status", handler: ok }),
	);
	const zone = dns.group("zone", { help: "manage zones" });
	zone.command(defineCommand("list", { help: "list all zones", handler: ok }));
	zone.command(
		defineCommand("create", {
			help: "create a zone",
			flags: { name: flag("name", t.str, { help: "zone name" }) },
			handler: ok,
		}),
	);

	assert.equal(
		(await app.test(["dns", "--help"])).stdout,
		"myapp dns -- manage DNS\n\nCommands:\n  status    show DNS status\n\nGroups:\n  zone    manage zones\n\nUse 'myapp dns <command> --help' for more information.\n",
	);
	assert.equal(
		(await app.test(["dns", "zone", "--help"])).stdout,
		"myapp dns zone -- manage zones\n\nCommands:\n  list      list all zones\n  create    create a zone\n\nUse 'myapp dns zone <command> --help' for more information.\n",
	);
	assert.equal(
		(await app.test(["dns", "zone", "create", "--help"])).stdout,
		"myapp dns zone create -- create a zone\n\nFlags:\n  --name <str>    zone name [required]\n",
	);
});

test("help: group help lists subcommands (nesting.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	const grp = app.group("config", { help: "manage configuration" });
	grp.command(defineCommand("show", { help: "display config", handler: ok }));
	grp.command(
		defineCommand("set", { help: "set a config value", handler: ok }),
	);
	const expected =
		"myapp config -- manage configuration\n\nCommands:\n  show    display config\n  set     set a config value\n\nUse 'myapp config <command> --help' for more information.\n";
	assert.equal((await app.test(["config", "--help"])).stdout, expected);
	// A bare group token also renders group help.
	assert.equal((await app.test(["config"])).stdout, expected);
});

test("help: passthrough command help is header-only (passthrough.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		passthrough("checkout", {
			help: "checkout a branch",
			handler: () => 0,
		}),
	);
	assert.equal(
		(await app.test(["checkout", "--help"])).stdout,
		"myapp checkout -- checkout a branch\n",
	);
	// Passthrough commands appear in the app-level Commands section.
	app.command(passthrough("status", { help: "show status", handler: () => 0 }));
	assert.equal(
		(await app.test([])).stdout,
		"myapp v1.0.0 -- test app\n\nCommands:\n  checkout    checkout a branch\n  status      show status\n\nUse 'myapp <command> --help' for more information.\n",
	);
});

test("help: flag-set flags render in the Flags section (flag_sets.json)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flagSets: [
				flagSet("diagnostics", {
					debug: flag("debug", t.bool, {
						help: "enable debug mode",
						default: false,
					}),
				}),
			],
			handler: ok,
		}),
	);
	assert.equal(
		(await app.test(["cmd", "--help"])).stdout,
		"myapp cmd -- a command\n\nFlags:\n  --debug, --no-debug    enable debug mode [default: false]\n",
	);
});

// App-level sections with no conformance stdout_equals case: expected bytes
// captured by running the Python implementation's app.test() over mirror apps
// (scratchpad capture_help.py, 2026-07-19; Python is the divergence oracle).

test("help: app help shows the Deprecated section (Python-captured)", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineCommand("new-cmd", { help: "the replacement command", handler: ok }),
	);
	app.deprecate(deprecated("old-cmd", "use 'new-cmd' instead"));
	assert.equal(
		(await app.test([])).stdout,
		"myapp v1.0.0 -- test app\n\nCommands:\n  new-cmd    the replacement command\n\nDeprecated:\n  old-cmd    use 'new-cmd' instead\n\nUse 'myapp <command> --help' for more information.\n",
	);
});

test("help: app help shows Global flags without meta (Python-captured)", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "enable verbose output",
				default: false,
				short: "V",
			}),
		},
	});
	app.command(defineCommand("cmd", { help: "a command", handler: ok }));
	assert.equal(
		(await app.test([])).stdout,
		"myapp v1.0.0 -- test app\n\nCommands:\n  cmd    a command\n\nGlobal flags:\n  --verbose, -V    enable verbose output\n\nUse 'myapp <command> --help' for more information.\n",
	);
});

test("help: app help shows the Infrastructure section (Python-captured)", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		infraRoot: { MYAPP_ROOT: "~/.myapp" },
		handshakeEnv: { MYAPP_ORCHESTRATED: "set by the orchestrator" },
	});
	app.command(defineCommand("cmd", { help: "a command", handler: ok }));
	assert.equal(
		(await app.test([])).stdout,
		"myapp v1.0.0 -- test app\n\nCommands:\n  cmd    a command\n\nInfrastructure:\n  (location/handshake env vars; not suppressed by --hermetic)\n  MYAPP_ROOT            root (default: ~/.myapp)\n  MYAPP_ORCHESTRATED    set by the orchestrator\n\nUse 'myapp <command> --help' for more information.\n",
	);
});
