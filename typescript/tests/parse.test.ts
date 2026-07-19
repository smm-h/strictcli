/**
 * Parse-pipeline tests. Expected outputs are derived from the conformance
 * suite (conformance/cases/*.json) -- each test names its source case where
 * one exists. The mini-runner below is the smallest seam over doParse:
 * argv in, exact stdout/stderr/exit out. The full run()/test() surface lands
 * in the next subphase.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { AppImpl, AppSpec } from "../src/app.js";
import type {
	AnyCommand,
	PassthroughArgs,
	PassthroughDef,
} from "../src/factories.js";
import { formatFloatCanonical } from "../src/float.js";
import {
	arg,
	coRequired,
	createApp,
	defineCommand,
	deprecated,
	flag,
	implies,
	mutexGroup,
	passthrough,
	requires,
	t,
} from "../src/index.js";
import {
	type ConfigProvider,
	type DoParseDeps,
	doParse,
	flagParamName,
	formatParseErrorOutput,
	type ParseOutcome,
	preScanReservedFlags,
	tokensContainHelp,
} from "../src/parse.js";

// --- Mini-runner seam ---

interface RunResult {
	readonly kind: ParseOutcome["kind"];
	readonly stdout: string;
	readonly stderr: string;
	readonly exitCode: number;
	readonly outcome: ParseOutcome;
}

/**
 * Runs the parse pipeline and, for command/passthrough outcomes, invokes the
 * handler. Handlers print by pushing onto the shared `out` array (joined with
 * newlines, mirroring conformance stdout comparison). Help outcomes are
 * represented structurally only -- help *rendering* is a later subphase.
 */
async function run(
	app: AppImpl,
	argv: readonly string[],
	out: readonly string[] = [],
	deps?: DoParseDeps,
): Promise<RunResult> {
	const outcome = doParse(app, argv, deps);
	const done = (
		stdout: string,
		stderr: string,
		exitCode: number,
	): RunResult => ({
		kind: outcome.kind,
		stdout,
		stderr,
		exitCode,
		outcome,
	});
	switch (outcome.kind) {
		case "help":
		case "dump-schema":
		case "mcp":
			return done("", "", 0);
		case "version":
			return done(outcome.text, "", 0);
		case "parse-error":
			return done(
				"",
				formatParseErrorOutput(app, outcome.message, outcome.commandPrefix),
				1,
			);
		case "passthrough": {
			const def = outcome.cmd.def as PassthroughDef<string>;
			const args: PassthroughArgs = {
				name: outcome.cmd.name,
				args: outcome.args,
				globals: outcome.globalKwargs,
			};
			const result = await def.handler(args, undefined);
			return done(out.join("\n"), "", typeof result === "number" ? result : 0);
		}
		case "command": {
			const def = outcome.cmd.def as AnyCommand;
			const result = await def.handler(outcome.kwargs as never, undefined);
			return done(out.join("\n"), "", typeof result === "number" ? result : 0);
		}
	}
}

/** Conformance handler-prints value formatting (ref_python.py semantics). */
function fmt(v: unknown): string {
	if (v === undefined || v === null) {
		return "None";
	}
	switch (typeof v) {
		case "boolean":
			return v ? "true" : "false";
		case "bigint":
			return v.toString();
		case "number":
			return formatFloatCanonical(v);
		case "string":
			return v;
		default:
			break;
	}
	if (Array.isArray(v)) {
		return v.map(fmt).join(",");
	}
	if (v instanceof Map) {
		return [...v.keys()]
			.sort()
			.map((k) => `${k}=${fmt(v.get(k))}`)
			.join(",");
	}
	return String(v);
}

function makeApp(spec?: Partial<AppSpec>): AppImpl {
	return createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		...spec,
	}) as AppImpl;
}

/** Expected two-line parse-error stderr surface. */
function errOut(msg: string, prefix = "myapp"): string {
	return `error: ${msg}\ntry '${prefix} --help'\n`;
}

async function withEnv<T>(
	vars: Record<string, string>,
	fn: () => Promise<T>,
): Promise<T> {
	const saved = new Map<string, string | undefined>();
	for (const [k, v] of Object.entries(vars)) {
		saved.set(k, process.env[k]);
		process.env[k] = v;
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

function fakeConfig(data: Record<string, unknown>): ConfigProvider {
	return {
		load: () => ({ data }),
		// Tests supply pre-typed values; Phase 5 adds real coercion.
		coerce: (_f, v) => v,
	};
}

// =========================================================================
// flags.json
// =========================================================================

test("flags: str flag with space and equals syntax", async () => {
	for (const argv of [
		["cmd", "--target", "foo"],
		["cmd", "--target=foo"],
	]) {
		const out: string[] = [];
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: { target: flag("target", t.str, { help: "the target" }) },
				handler: (a) => {
					out.push(`target=${fmt(a.target)}`);
				},
			}),
		);
		const r = await run(app, argv, out);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, "target=foo");
	}
});

function boolApp(out: string[], negatable?: false): AppImpl {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				verbose:
					negatable === false
						? flag("verbose", t.bool, {
								help: "be verbose",
								default: false,
								negatable: false,
							})
						: flag("verbose", t.bool, { help: "be verbose", default: false }),
			},
			handler: (a) => {
				out.push(`verbose=${fmt(a.verbose)}`);
			},
		}),
	);
	return app;
}

test("flags: bool present/absent/negation", async () => {
	const cases: readonly [string[], string][] = [
		[["cmd", "--verbose"], "verbose=true"],
		[["cmd"], "verbose=false"],
		[["cmd", "--no-verbose"], "verbose=false"],
	];
	for (const [argv, expected] of cases) {
		const out: string[] = [];
		const r = await run(boolApp(out), argv, out);
		assert.equal(r.exitCode, 0);
		assert.equal(r.stdout, expected);
	}
});

test("flags: short flags for bool and str", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				verbose: flag("verbose", t.bool, {
					help: "be verbose",
					short: "V",
					default: false,
				}),
				target: flag("target", t.str, {
					help: "the target",
					short: "t",
					default: "none",
				}),
			},
			handler: (a) => {
				out.push(`verbose=${fmt(a.verbose)} target=${fmt(a.target)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "-V", "-t", "foo"], out);
	assert.equal(r.stdout, "verbose=true target=foo");
});

test("flags: str flag default omitted/provided", async () => {
	for (const [argv, expected] of [
		[["cmd"], "format=text"],
		[["cmd", "--format", "json"], "format=json"],
	] as const) {
		const out: string[] = [];
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					format: flag("format", t.str, {
						help: "output format",
						default: "text",
					}),
				},
				handler: (a) => {
					out.push(`format=${fmt(a.format)}`);
				},
			}),
		);
		const r = await run(app, [...argv], out);
		assert.equal(r.stdout, expected);
	}
});

test("flags: required str flag missing produces exact error", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { target: flag("target", t.str, { help: "the target" }) },
			handler: () => undefined,
		}),
	);
	const r = await run(app, ["cmd"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, errOut("flag '--target' is required", "myapp cmd"));
});

test("flags: bool flag=value syntax is rejected", async () => {
	const out: string[] = [];
	const r = await run(boolApp(out), ["cmd", "--verbose=true"], out);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--verbose' is a boolean flag and does not take a value",
			"myapp cmd",
		),
	);
});

test("flags: negatable false rejects --no-flag as unknown", async () => {
	const out: string[] = [];
	const r = await run(boolApp(out, false), ["cmd", "--no-verbose"], out);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, errOut("unknown flag '--no-verbose'", "myapp cmd"));
});

test("flags: required bool must-be-passed messages", async () => {
	// required_bools.json shapes: negatable and non-negatable required bools.
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { watch: flag("watch", t.bool, { help: "watch mode" }) },
			handler: () => undefined,
		}),
	);
	const r = await run(app, ["cmd"]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--watch' must be passed as --watch or --no-watch",
			"myapp cmd",
		),
	);

	const app2 = makeApp();
	app2.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				watch: flag("watch", t.bool, { help: "watch mode", negatable: false }),
			},
			handler: () => undefined,
		}),
	);
	const r2 = await run(app2, ["cmd"]);
	assert.equal(
		r2.stderr,
		errOut("flag '--watch' must be passed as --watch", "myapp cmd"),
	);
});

// =========================================================================
// errors.json
// =========================================================================

test("errors: unknown flag (bare and equals form)", async () => {
	for (const argv of [
		["cmd", "--unknown"],
		["cmd", "--unknown=value"],
	]) {
		const out: string[] = [];
		const r = await run(boolApp(out), argv, out);
		assert.equal(r.exitCode, 1);
		assert.equal(r.stderr, errOut("unknown flag '--unknown'", "myapp cmd"));
	}
});

test("errors: unknown short flag treated as positional", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	const r = await run(app, ["cmd", "-x"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, errOut("unexpected argument '-x'", "myapp cmd"));
});

test("errors: extra positional arg", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	const r = await run(app, ["cmd", "surprise"]);
	assert.equal(r.stderr, errOut("unexpected argument 'surprise'", "myapp cmd"));
});

test("errors: flag requires a value", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { target: flag("target", t.str, { help: "the target" }) },
			handler: () => undefined,
		}),
	);
	const r = await run(app, ["cmd", "--target"]);
	assert.equal(
		r.stderr,
		errOut("flag '--target' requires a value", "myapp cmd"),
	);
});

test("errors: unknown command uses app-level try hint", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	const r = await run(app, ["unknown"]);
	assert.equal(r.exitCode, 1);
	assert.equal(r.stderr, errOut("unknown command 'unknown'"));
});

test("errors: bool negation with value is rejected", async () => {
	const out: string[] = [];
	const r = await run(boolApp(out), ["cmd", "--no-verbose=true"], out);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--no-verbose' is a boolean negation and does not take a value",
			"myapp cmd",
		),
	);
});

test("errors: str flag consumes flag-like next token as its value", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				target: flag("target", t.str, { help: "the target" }),
				verbose: flag("verbose", t.bool, {
					help: "be verbose",
					default: false,
				}),
			},
			handler: (a) => {
				out.push(`target=${fmt(a.target)} verbose=${fmt(a.verbose)}`);
			},
		}),
	);
	const r1 = await run(app, ["cmd", "--target", "--unknown"], out);
	assert.equal(r1.exitCode, 0);
	assert.equal(r1.stdout, "target=--unknown verbose=false");
	out.length = 0;
	const r2 = await run(app, ["cmd", "--target", "--verbose"], out);
	assert.equal(r2.stdout, "target=--verbose verbose=false");
});

// =========================================================================
// args.json / typed_args.json / variadic.json
// =========================================================================

test("args: single required arg and missing required arg", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("greet", {
			help: "say hello",
			args: [arg("name", t.str, { help: "who to greet" })],
			handler: (a) => {
				out.push(`hello ${fmt(a.name)}`);
			},
		}),
	);
	const r = await run(app, ["greet", "world"], out);
	assert.equal(r.stdout, "hello world");
	const r2 = await run(app, ["greet"], out);
	assert.equal(r2.exitCode, 1);
	assert.equal(
		r2.stderr,
		errOut("missing required argument 'name'", "myapp greet"),
	);
});

test("args: two positional args in order", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("copy", {
			help: "copy files",
			args: [
				arg("src", t.str, { help: "source file" }),
				arg("dst", t.str, { help: "destination file" }),
			],
			handler: (a) => {
				out.push(`${fmt(a.src)}->${fmt(a.dst)}`);
			},
		}),
	);
	const r = await run(app, ["copy", "a.txt", "b.txt"], out);
	assert.equal(r.stdout, "a.txt->b.txt");
});

test("args: optional arg with default, provided and omitted", async () => {
	for (const [argv, expected] of [
		[["cmd", "/tmp/foo"], "path=/tmp/foo"],
		[["cmd"], "path=."],
	] as const) {
		const out: string[] = [];
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				args: [
					arg("path", t.str, {
						help: "project dir",
						required: false,
						default: ".",
					}),
				],
				handler: (a) => {
					out.push(`path=${fmt(a.path)}`);
				},
			}),
		);
		const r = await run(app, [...argv], out);
		assert.equal(r.stdout, expected);
	}
});

test("args: required first, optional second with default", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [
				arg("src", t.str, { help: "source file" }),
				arg("dst", t.str, {
					help: "destination",
					required: false,
					default: "out",
				}),
			],
			handler: (a) => {
				out.push(`${fmt(a.src)}:${fmt(a.dst)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "input.txt"], out);
	assert.equal(r.stdout, "input.txt:out");
});

test("args: optional arg without default, omitted gives None", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("path", t.str, { help: "project dir", required: false })],
			handler: (a) => {
				out.push(`path=${fmt(a.path)}`);
			},
		}),
	);
	const r = await run(app, ["cmd"], out);
	assert.equal(r.stdout, "path=None");
});

test("args: double dash stops flag parsing", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				verbose: flag("verbose", t.bool, {
					help: "be verbose",
					default: false,
				}),
			},
			args: [arg("path", t.str, { help: "a path" })],
			handler: (a) => {
				out.push(`verbose=${fmt(a.verbose)} path=${fmt(a.path)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "--", "--not-a-flag"], out);
	assert.equal(r.stdout, "verbose=false path=--not-a-flag");
});

test("typed args: int/float/bool coercion and exact errors", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("count", t.int, { help: "how many" })],
			handler: (a) => {
				out.push(`count=${fmt(a.count)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "42"], out);
	assert.equal(r.stdout, "count=42");
	const r2 = await run(app, ["cmd", "abc"], out);
	assert.equal(
		r2.stderr,
		errOut("argument 'count': expected integer, got 'abc'", "myapp cmd"),
	);

	const out3: string[] = [];
	const app3 = makeApp();
	app3.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("flag", t.bool, { help: "a bool" })],
			handler: (a) => {
				out3.push(`flag=${fmt(a.flag)}`);
			},
		}),
	);
	assert.equal((await run(app3, ["cmd", "true"], out3)).stdout, "flag=true");
	const r4 = await run(app3, ["cmd", "maybe"], out3);
	assert.equal(
		r4.stderr,
		errOut("argument 'flag': expected boolean, got 'maybe'", "myapp cmd"),
	);

	const out5: string[] = [];
	const app5 = makeApp();
	app5.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("rate", t.float, { help: "the rate" })],
			handler: (a) => {
				out5.push(`rate=${fmt(a.rate)}`);
			},
		}),
	);
	assert.equal((await run(app5, ["cmd", "3.14"], out5)).stdout, "rate=3.14");
	const r6 = await run(app5, ["cmd", "xyz"], out5);
	assert.equal(
		r6.stderr,
		errOut("argument 'rate': expected float, got 'xyz'", "myapp cmd"),
	);
});

function variadicApp(out: string[], required: boolean): AppImpl {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [
				required
					? arg("files", t.str, { help: "files to process", variadic: true })
					: arg("files", t.str, {
							help: "files to process",
							variadic: true,
							required: false,
						}),
			],
			handler: (a) => {
				out.push(`files=${fmt(a.files)}`);
			},
		}),
	);
	return app;
}

test("variadic: collects values, required/optional zero-value behavior", async () => {
	const out: string[] = [];
	assert.equal(
		(await run(variadicApp(out, true), ["cmd", "a", "b", "c"], out)).stdout,
		"files=a,b,c",
	);
	const r = await run(variadicApp([], true), ["cmd"]);
	assert.equal(
		r.stderr,
		errOut("missing required argument 'files'", "myapp cmd"),
	);
	const out2: string[] = [];
	assert.equal(
		(await run(variadicApp(out2, false), ["cmd"], out2)).stdout,
		"files=",
	);
	const out3: string[] = [];
	assert.equal(
		(await run(variadicApp(out3, true), ["cmd", "--", "-a", "-b"], out3))
			.stdout,
		"files=-a,-b",
	);
});

test("variadic: with preceding required arg", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [
				arg("target", t.str, { help: "the target" }),
				arg("files", t.str, { help: "files", variadic: true }),
			],
			handler: (a) => {
				out.push(`target=${fmt(a.target)} files=${fmt(a.files)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "target", "f1", "f2"], out);
	assert.equal(r.stdout, "target=target files=f1,f2");
});

test("typed args: negative int after double dash", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("offset", t.int, { help: "the offset" })],
			handler: (a) => {
				out.push(`offset=${fmt(a.offset)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "--", "-5"], out);
	assert.equal(r.stdout, "offset=-5");
});

// =========================================================================
// nesting.json (routing through groups)
// =========================================================================

function nestedApp(out: string[]): AppImpl {
	const app = makeApp();
	const dns = app.group("dns", { help: "manage DNS" });
	const zone = dns.group("zone", { help: "manage zones" });
	zone.command(
		defineCommand("list", {
			help: "list all zones",
			handler: () => {
				out.push("listing zones");
			},
		}),
	);
	zone.command(
		defineCommand("create", {
			help: "create a zone",
			flags: { name: flag("name", t.str, { help: "zone name" }) },
			handler: (a) => {
				out.push(`created ${fmt(a.name)}`);
			},
		}),
	);
	return app;
}

test("nesting: group command dispatch and flags", async () => {
	const out: string[] = [];
	const app = makeApp();
	const config = app.group("config", { help: "manage configuration" });
	config.command(
		defineCommand("set", {
			help: "set a config value",
			flags: {
				key: flag("key", t.str, { help: "config key" }),
				value: flag("value", t.str, { help: "config value" }),
			},
			handler: (a) => {
				out.push(`${fmt(a.key)}=${fmt(a.value)}`);
			},
		}),
	);
	const r = await run(
		app,
		["config", "set", "--key", "name", "--value", "strictcli"],
		out,
	);
	assert.equal(r.stdout, "name=strictcli");
});

test("nesting: unknown group subcommand error includes path", async () => {
	const app = makeApp();
	const config = app.group("config", { help: "manage configuration" });
	config.command(
		defineCommand("show", { help: "display config", handler: () => undefined }),
	);
	const r = await run(app, ["config", "delete"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		errOut("unknown command 'delete' in 'config'", "myapp config"),
	);
});

test("nesting: 3-level dispatch, flags, and unknown command", async () => {
	const out: string[] = [];
	const app = nestedApp(out);
	assert.equal(
		(await run(app, ["dns", "zone", "list"], out)).stdout,
		"listing zones",
	);
	out.length = 0;
	assert.equal(
		(await run(app, ["dns", "zone", "create", "--name", "example.com"], out))
			.stdout,
		"created example.com",
	);
	const r = await run(app, ["dns", "zone", "delete"]);
	assert.equal(
		r.stderr,
		errOut("unknown command 'delete' in 'dns zone'", "myapp dns zone"),
	);
});

test("nesting: 4-level dispatch", async () => {
	const out: string[] = [];
	const app = makeApp();
	app
		.group("cloud", { help: "cloud operations" })
		.group("compute", { help: "compute resources" })
		.group("instance", { help: "manage instances" })
		.command(
			defineCommand("list", {
				help: "list instances",
				handler: () => {
					out.push("listing instances");
				},
			}),
		);
	const r = await run(app, ["cloud", "compute", "instance", "list"], out);
	assert.equal(r.stdout, "listing instances");
});

test("nesting: group with no subcommand or --help yields group help outcome", async () => {
	const app = nestedApp([]);
	for (const argv of [
		["dns", "zone"],
		["dns", "zone", "--help"],
		["dns", "zone", "-h"],
	]) {
		const r = await run(app, argv);
		assert.equal(r.kind, "help");
		assert.equal(r.exitCode, 0);
		const outcome = r.outcome as Extract<ParseOutcome, { kind: "help" }>;
		assert.equal(outcome.target.level, "group");
		if (outcome.target.level === "group") {
			assert.equal(outcome.target.group.name, "zone");
			assert.deepEqual(outcome.target.path, ["dns", "zone"]);
		}
	}
});

test("nesting: mixed groups and commands at same level", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("version", {
			help: "show version",
			handler: () => {
				out.push("1.0.0");
			},
		}),
	);
	const config = app.group("config", { help: "manage configuration" });
	config.command(
		defineCommand("show", {
			help: "display config",
			handler: () => {
				out.push("showing config");
			},
		}),
	);
	const remote = config.group("remote", { help: "manage remotes" });
	remote.command(
		defineCommand("list", {
			help: "list remotes",
			handler: () => {
				out.push("listing remotes");
			},
		}),
	);
	const r = await run(app, ["config", "remote", "list"], out);
	assert.equal(r.stdout, "listing remotes");
});

// =========================================================================
// global_flags.json
// =========================================================================

function globalApp(out: string[]): AppImpl {
	const app = makeApp({
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "enable verbose output",
				default: false,
			}),
			settings: flag("settings", t.str, {
				help: "settings path",
				default: "/etc/myapp",
			}),
		},
	});
	app.command(
		defineCommand("cmd", {
			help: "a command",
			handler: (_a, _ctx) => {
				out.push("ran");
			},
		}),
	);
	return app;
}

test("global_flags: bool before and after the command name", async () => {
	for (const argv of [
		["--verbose", "cmd"],
		["cmd", "--verbose"],
	]) {
		const out: string[] = [];
		const app = globalApp(out);
		const r = await run(app, argv, out);
		assert.equal(r.exitCode, 0);
		const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o.kwargs.verbose, true);
		assert.equal(o.globalKwargs.verbose, true);
	}
});

test("global_flags: negation, str value, defaults", async () => {
	const out: string[] = [];
	const app = globalApp(out);
	const r = await run(app, ["--no-verbose", "cmd"], out);
	const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o.kwargs.verbose, false);

	const r2 = await run(globalApp([]), ["--settings", "/tmp", "cmd"]);
	const o2 = r2.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o2.kwargs.settings, "/tmp");

	const r3 = await run(globalApp([]), ["cmd"]);
	const o3 = r3.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o3.kwargs.verbose, false);
	assert.equal(o3.kwargs.settings, "/etc/myapp");
});

test("global_flags: global int flag coerces to bigint", async () => {
	const out: string[] = [];
	const app = makeApp({
		flags: {
			port: flag("port", t.int, { help: "server port", default: 3000n }),
		},
	});
	app.command(
		defineCommand("cmd", {
			help: "a command",
			handler: (a) => {
				out.push(`port=${fmt((a as { port: bigint }).port)}`);
			},
		}),
	);
	const r = await run(app, ["--port", "8080", "cmd"], out);
	assert.equal(r.stdout, "port=8080");
});

test("global_flags: global flag from env var", async () => {
	await withEnv({ MYAPP_VERBOSE: "true" }, async () => {
		const app = makeApp({
			envPrefix: "MYAPP",
			flags: {
				verbose: flag("verbose", t.bool, {
					help: "enable verbose output",
					env: "MYAPP_VERBOSE",
					default: false,
				}),
			},
		});
		app.command(
			defineCommand("cmd", { help: "a command", handler: () => undefined }),
		);
		const r = await run(app, ["cmd"]);
		const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o.kwargs.verbose, true);
		assert.equal(o.sources.verbose, "env");
	});
});

test("global_flags: global and command flags together (conformance exact)", async () => {
	const out: string[] = [];
	const app = makeApp({
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "enable verbose output",
				default: false,
			}),
			settings: flag("settings", t.str, {
				help: "settings path",
				default: "/etc/myapp",
			}),
		},
	});
	app.command(
		defineCommand("deploy", {
			help: "deploy the app",
			flags: {
				force_deploy: flag("force-deploy", t.bool, {
					help: "force deploy",
					default: false,
				}),
			},
			handler: (a) => {
				const g = a as unknown as {
					verbose: boolean;
					settings: string;
					force_deploy: boolean;
				};
				out.push(
					`verbose=${fmt(g.verbose)} settings=${fmt(g.settings)} force-deploy=${fmt(g.force_deploy)}`,
				);
			},
		}),
	);
	const r = await run(
		app,
		["--verbose", "--settings", "/tmp/cfg", "deploy", "--force-deploy"],
		out,
	);
	assert.equal(r.stdout, "verbose=true settings=/tmp/cfg force-deploy=true");
});

// =========================================================================
// mutex.json / cross_feature.json
// =========================================================================

function mutexBoolApp(out: string[]): AppImpl {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			mutex: [
				mutexGroup({
					verbose: flag("verbose", t.bool, { help: "verbose output" }),
					quiet: flag("quiet", t.bool, { help: "quiet output" }),
				}),
			],
			handler: (a) => {
				const g = a as unknown as { verbose?: boolean; quiet?: boolean };
				out.push(`verbose=${fmt(g.verbose)} quiet=${fmt(g.quiet)}`);
			},
		}),
	);
	return app;
}

test("mutex: neither provided is exact one-of-required error", async () => {
	const r = await run(mutexBoolApp([]), ["cmd"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		errOut("one of --verbose, --quiet is required", "myapp cmd"),
	);
});

test("mutex: one provided is ok, unset member is None", async () => {
	const out: string[] = [];
	assert.equal(
		(await run(mutexBoolApp(out), ["cmd", "--verbose"], out)).stdout,
		"verbose=true quiet=None",
	);
	const out2: string[] = [];
	assert.equal(
		(await run(mutexBoolApp(out2), ["cmd", "--quiet"], out2)).stdout,
		"verbose=None quiet=true",
	);
});

test("mutex: both provided is exact mutually-exclusive error", async () => {
	const r = await run(mutexBoolApp([]), ["cmd", "--verbose", "--quiet"]);
	assert.equal(
		r.stderr,
		errOut("--verbose and --quiet are mutually exclusive", "myapp cmd"),
	);
});

function mutexStrApp(out: string[]): AppImpl {
	const app = makeApp();
	app.command(
		defineCommand("fetch", {
			help: "fetch data",
			mutex: [
				mutexGroup({
					file: flag("file", t.str, { help: "read from file", default: null }),
					url: flag("url", t.str, { help: "read from URL", default: null }),
				}),
			],
			handler: (a) => {
				const g = a as unknown as { file?: string; url?: string };
				out.push(`file=${fmt(g.file)} url=${fmt(g.url)}`);
			},
		}),
	);
	return app;
}

test("mutex: str flags with default null", async () => {
	const out: string[] = [];
	assert.equal(
		(await run(mutexStrApp(out), ["fetch", "--file", "data.txt"], out)).stdout,
		"file=data.txt url=None",
	);
	const r = await run(mutexStrApp([]), [
		"fetch",
		"--file",
		"data.txt",
		"--url",
		"http://example.com",
	]);
	assert.equal(
		r.stderr,
		errOut("--file and --url are mutually exclusive", "myapp fetch"),
	);
});

test("mutex: env-set members count as present (composition.json)", async () => {
	const mk = (out: string[]): AppImpl => {
		const app = makeApp({ envPrefix: "MYAPP" });
		app.command(
			defineCommand("cmd", {
				help: "a command",
				mutex: [
					mutexGroup({
						file: flag("file", t.str, {
							help: "read from file",
							default: null,
							env: "MYAPP_FILE",
						}),
						url: flag("url", t.str, {
							help: "read from URL",
							default: null,
							env: "MYAPP_URL",
						}),
					}),
				],
				handler: (a) => {
					const g = a as unknown as { file?: string; url?: string };
					out.push(`file=${fmt(g.file)} url=${fmt(g.url)}`);
				},
			}),
		);
		return app;
	};
	await withEnv({ MYAPP_FILE: "data.txt" }, async () => {
		const out: string[] = [];
		assert.equal(
			(await run(mk(out), ["cmd"], out)).stdout,
			"file=data.txt url=None",
		);
	});
	await withEnv(
		{ MYAPP_FILE: "data.txt", MYAPP_URL: "http://example.com" },
		async () => {
			const r = await run(mk([]), ["cmd"]);
			assert.equal(
				r.stderr,
				errOut("--file and --url are mutually exclusive", "myapp cmd"),
			);
		},
	);
});

// =========================================================================
// dependencies.json
// =========================================================================

function coRequiredApp(out: string[]): AppImpl {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				output: flag("output", t.str, { help: "output file", default: "none" }),
				format: flag("format", t.str, {
					help: "output format",
					default: "none",
				}),
			},
			dependencies: [coRequired(["output", "format"])],
			handler: (a) => {
				out.push(`output=${fmt(a.output)} format=${fmt(a.format)}`);
			},
		}),
	);
	return app;
}

test("dependencies: coRequired both/neither ok, one is exact error", async () => {
	const out: string[] = [];
	assert.equal(
		(
			await run(
				coRequiredApp(out),
				["cmd", "--output", "file.txt", "--format", "json"],
				out,
			)
		).stdout,
		"output=file.txt format=json",
	);
	assert.equal((await run(coRequiredApp([]), ["cmd"])).exitCode, 0);
	for (const argv of [
		["cmd", "--output", "file.txt"],
		["cmd", "--format", "json"],
	]) {
		const r = await run(coRequiredApp([]), argv);
		assert.equal(
			r.stderr,
			errOut("flags --output, --format must be used together", "myapp cmd"),
		);
	}
});

test("dependencies: requires enforcement", async () => {
	const mk = (_out: string[]): AppImpl => {
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					verbose: flag("verbose", t.bool, {
						help: "verbose output",
						default: false,
					}),
					output: flag("output", t.str, {
						help: "output file",
						default: "none",
					}),
				},
				dependencies: [requires({ flag: "verbose", dependsOn: "output" })],
				handler: () => undefined,
			}),
		);
		return app;
	};
	assert.equal(
		(await run(mk([]), ["cmd", "--verbose", "--output", "log.txt"])).exitCode,
		0,
	);
	assert.equal((await run(mk([]), ["cmd"])).exitCode, 0);
	assert.equal((await run(mk([]), ["cmd", "--output", "log.txt"])).exitCode, 0);
	const r = await run(mk([]), ["cmd", "--verbose"]);
	assert.equal(
		r.stderr,
		errOut("flag '--verbose' requires '--output'", "myapp cmd"),
	);
});

function impliesApp(out: string[], envPrefix?: string): AppImpl {
	const app = makeApp(envPrefix !== undefined ? { envPrefix } : {});
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				fast:
					envPrefix !== undefined
						? flag("fast", t.bool, {
								help: "fast mode",
								env: "MYAPP_FAST",
								default: false,
							})
						: flag("fast", t.bool, { help: "fast mode", default: false }),
				embeddings: flag("embeddings", t.bool, {
					help: "enable embeddings",
					default: true,
				}),
			},
			dependencies: [
				implies({ flag: "fast", implies: "embeddings", value: false }),
			],
			handler: (a) => {
				out.push(`fast=${fmt(a.fast)} embeddings=${fmt(a.embeddings)}`);
			},
		}),
	);
	return app;
}

test("dependencies: implies auto-set, default, conflict, agreement", async () => {
	const out: string[] = [];
	assert.equal(
		(await run(impliesApp(out), ["cmd", "--fast"], out)).stdout,
		"fast=true embeddings=false",
	);
	const out2: string[] = [];
	assert.equal(
		(await run(impliesApp(out2), ["cmd"], out2)).stdout,
		"fast=false embeddings=true",
	);
	const r = await run(impliesApp([]), ["cmd", "--fast", "--embeddings"]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--fast' implies '--no-embeddings', but '--embeddings' was explicitly provided",
			"myapp cmd",
		),
	);
	const out3: string[] = [];
	assert.equal(
		(await run(impliesApp(out3), ["cmd", "--fast", "--no-embeddings"], out3))
			.stdout,
		"fast=true embeddings=false",
	);
});

test("dependencies: implies env var trigger fires implication", async () => {
	await withEnv({ MYAPP_FAST: "true" }, async () => {
		const out: string[] = [];
		const r = await run(impliesApp(out, "MYAPP"), ["cmd"], out);
		assert.equal(r.stdout, "fast=true embeddings=false");
		const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o.sources.embeddings, "implied");
	});
});

// =========================================================================
// deprecated.json
// =========================================================================

test("deprecated: invoking a deprecated command prints message and exits 1", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("new-cmd", {
			help: "the replacement command",
			handler: () => {
				out.push("new");
			},
		}),
	);
	app.deprecate(deprecated("old-cmd", "use 'new-cmd' instead"));
	const r = await run(app, ["old-cmd"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		errOut("command 'old-cmd' is deprecated: use 'new-cmd' instead"),
	);
});

// =========================================================================
// basic.json / boundary.json (app-level help, version, edge tokens)
// =========================================================================

test("basic: --version and -v produce 'name version'", async () => {
	const app = makeApp({ version: "2.5.0" });
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	for (const argv of [["--version"], ["-v"]]) {
		const r = await run(app, argv);
		assert.equal(r.kind, "version");
		assert.equal(r.stdout, "myapp 2.5.0");
		assert.equal(r.exitCode, 0);
	}
});

test("basic: empty argv, --help, -h yield app help outcome", async () => {
	const app = makeApp();
	app.command(
		defineCommand("greet", { help: "say hello", handler: () => undefined }),
	);
	for (const argv of [[], ["--help"], ["-h"]]) {
		const r = await run(app, argv);
		assert.equal(r.kind, "help");
		const o = r.outcome as Extract<ParseOutcome, { kind: "help" }>;
		assert.equal(o.target.level, "app");
	}
});

test("boundary: only double dash shows app help", async () => {
	const app = makeApp();
	app.command(
		defineCommand("greet", { help: "say hello", handler: () => undefined }),
	);
	const r = await run(app, ["--"]);
	assert.equal(r.kind, "help");
});

test("boundary: unknown flag with no command is an unknown command", async () => {
	const app = makeApp();
	app.command(
		defineCommand("greet", { help: "say hello", handler: () => undefined }),
	);
	const r = await run(app, ["--unknown-flag"]);
	assert.equal(r.stderr, errOut("unknown command '--unknown-flag'"));
});

test("boundary: empty flag value, dash positional, bare cmd --", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { name: flag("name", t.str, { help: "the name" }) },
			handler: (a) => {
				out.push(`name=${fmt(a.name)}`);
			},
		}),
	);
	assert.equal((await run(app, ["cmd", "--name", ""], out)).stdout, "name=");

	const out2: string[] = [];
	const app2 = makeApp();
	app2.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("path", t.str, { help: "the path" })],
			handler: (a) => {
				out2.push(`path=${fmt(a.path)}`);
			},
		}),
	);
	assert.equal((await run(app2, ["cmd", "-"], out2)).stdout, "path=-");

	const out3: string[] = [];
	const app3 = makeApp();
	app3.command(
		defineCommand("cmd", {
			help: "a command",
			handler: () => {
				out3.push("ok");
			},
		}),
	);
	assert.equal((await run(app3, ["cmd", "--"], out3)).stdout, "ok");
});

test("boundary: int forms 007, +5, overflow, 12abc", async () => {
	const mk = (out: string[]): AppImpl => {
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: { port: flag("port", t.int, { help: "the port" }) },
				handler: (a) => {
					out.push(`port=${fmt(a.port)}`);
				},
			}),
		);
		return app;
	};
	const out: string[] = [];
	assert.equal(
		(await run(mk(out), ["cmd", "--port", "007"], out)).stdout,
		"port=7",
	);
	const out2: string[] = [];
	assert.equal(
		(await run(mk(out2), ["cmd", "--port", "+5"], out2)).stdout,
		"port=5",
	);
	assert.equal(
		(await run(mk([]), ["cmd", "--port", "99999999999999999999"])).stderr,
		errOut("--port: expected integer, got '99999999999999999999'", "myapp cmd"),
	);
	assert.equal(
		(await run(mk([]), ["cmd", "--port", "12abc"])).stderr,
		errOut("--port: expected integer, got '12abc'", "myapp cmd"),
	);
});

test("boundary: env var edge values", async () => {
	const mkBool = (): AppImpl => {
		const app = makeApp({ envPrefix: "MYAPP" });
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					verbose: flag("verbose", t.bool, {
						help: "be verbose",
						env: "MYAPP_VERBOSE",
						default: false,
					}),
				},
				handler: () => undefined,
			}),
		);
		return app;
	};
	await withEnv({ MYAPP_VERBOSE: "maybe" }, async () => {
		assert.equal(
			(await run(mkBool(), ["cmd"])).stderr,
			errOut(
				"invalid boolean value 'maybe' for env var 'MYAPP_VERBOSE' (flag '--verbose')",
				"myapp cmd",
			),
		);
	});
	await withEnv({ MYAPP_VERBOSE: "TRUE" }, async () => {
		const r = await run(mkBool(), ["cmd"]);
		const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o.kwargs.verbose, true);
	});

	const mkInt = (): AppImpl => {
		const app = makeApp({ envPrefix: "MYAPP" });
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					port: flag("port", t.int, {
						help: "the port",
						env: "MYAPP_PORT",
						default: 1n,
					}),
				},
				handler: () => undefined,
			}),
		);
		return app;
	};
	await withEnv({ MYAPP_PORT: " 42 " }, async () => {
		assert.equal(
			(await run(mkInt(), ["cmd"])).stderr,
			errOut(
				"--port: expected integer, got ' 42 ' (from env var 'MYAPP_PORT')",
				"myapp cmd",
			),
		);
	});

	// env value that looks like a flag stays a plain value
	const out: string[] = [];
	const app = makeApp({ envPrefix: "MYAPP" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				target: flag("target", t.str, {
					help: "the target",
					env: "MYAPP_TARGET",
					default: "x",
				}),
			},
			handler: (a) => {
				out.push(`target=${fmt(a.target)}`);
			},
		}),
	);
	await withEnv({ MYAPP_TARGET: "--foo" }, async () => {
		assert.equal((await run(app, ["cmd"], out)).stdout, "target=--foo");
	});
});

// =========================================================================
// env.json (precedence CLI > env > default)
// =========================================================================

test("env: str flag from env var; CLI overrides env", async () => {
	const mk = (out: string[]): AppImpl => {
		const app = makeApp({ envPrefix: "MYAPP" });
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					target: flag("target", t.str, {
						help: "the target",
						env: "MYAPP_TARGET",
						default: "default-target",
					}),
				},
				handler: (a) => {
					out.push(`target=${fmt(a.target)}`);
				},
			}),
		);
		return app;
	};
	await withEnv({ MYAPP_TARGET: "from-env" }, async () => {
		const out: string[] = [];
		assert.equal((await run(mk(out), ["cmd"], out)).stdout, "target=from-env");
		const out2: string[] = [];
		assert.equal(
			(await run(mk(out2), ["cmd", "--target", "from-cli"], out2)).stdout,
			"target=from-cli",
		);
	});
});

// =========================================================================
// repeatable.json / compound_types.json / env_separator.json
// =========================================================================

function tagsApp(
	out: string[],
	opts?: { choices?: readonly [string, ...string[]]; default?: string[] },
): AppImpl {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				tag: flag("tag", t.list(t.str), {
					help: "a tag",
					short: "t",
					...(opts?.choices !== undefined ? { choices: opts.choices } : {}),
					...(opts?.default !== undefined ? { default: opts.default } : {}),
				}),
			},
			handler: (a) => {
				out.push(`tags=${fmt(a.tag)}`);
			},
		}),
	);
	return app;
}

test("repeatable: occurrences accumulate; zero gives empty", async () => {
	const out: string[] = [];
	assert.equal(
		(
			await run(
				tagsApp(out),
				["cmd", "--tag", "alpha", "--tag", "beta", "--tag", "gamma"],
				out,
			)
		).stdout,
		"tags=alpha,beta,gamma",
	);
	const out2: string[] = [];
	assert.equal((await run(tagsApp(out2), ["cmd"], out2)).stdout, "tags=");
	const out3: string[] = [];
	assert.equal(
		(await run(tagsApp(out3), ["cmd", "--tag=alpha", "--tag=beta"], out3))
			.stdout,
		"tags=alpha,beta",
	);
	const out4: string[] = [];
	assert.equal(
		(await run(tagsApp(out4), ["cmd", "-t", "alpha", "-t", "beta"], out4))
			.stdout,
		"tags=alpha,beta",
	);
});

test("repeatable: int elements coerce; invalid element errors", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				ids: flag("ids", t.list(t.int), { help: "the ids" }),
			},
			handler: (a) => {
				out.push(`ids=${fmt(a.ids)}`);
			},
		}),
	);
	assert.equal(
		(await run(app, ["cmd", "--ids", "1", "--ids", "2", "--ids", "3"], out))
			.stdout,
		"ids=1,2,3",
	);
	const r = await run(app, ["cmd", "--ids", "abc"]);
	assert.equal(
		r.stderr,
		errOut("--ids: expected integer, got 'abc'", "myapp cmd"),
	);
});

test("repeatable: choices validated per element", async () => {
	const out: string[] = [];
	assert.equal(
		(
			await run(
				tagsApp(out, { choices: ["alpha", "beta"] }),
				["cmd", "--tag", "alpha", "--tag", "beta"],
				out,
			)
		).stdout,
		"tags=alpha,beta",
	);
	const r = await run(tagsApp([], { choices: ["alpha", "beta"] }), [
		"cmd",
		"--tag",
		"alpha",
		"--tag",
		"delta",
	]);
	assert.equal(
		r.stderr,
		errOut(
			"--tag: invalid value 'delta', must be one of: alpha, beta",
			"myapp cmd",
		),
	);
});

test("repeatable: default applied at runtime; CLI replaces (no merge)", async () => {
	const out: string[] = [];
	assert.equal(
		(await run(tagsApp(out, { default: ["x", "y"] }), ["cmd"], out)).stdout,
		"tags=x,y",
	);
	const out2: string[] = [];
	assert.equal(
		(
			await run(
				tagsApp(out2, { default: ["x", "y"] }),
				["cmd", "--tag", "z"],
				out2,
			)
		).stdout,
		"tags=z",
	);
});

test("dict: key=value entries, missing equals, duplicate key", async () => {
	const mk = (out: string[]): AppImpl => {
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					header: flag("header", t.dict(t.str), { help: "a header" }),
				},
				handler: (a) => {
					out.push(`headers=${fmt(a.header)}`);
				},
			}),
		);
		return app;
	};
	const out: string[] = [];
	assert.equal(
		(
			await run(
				mk(out),
				["cmd", "--header", "content-type=text/html", "--header", "b=2"],
				out,
			)
		).stdout,
		"headers=b=2,content-type=text/html",
	);
	assert.equal(
		(await run(mk([]), ["cmd", "--header", "no-equals-here"])).stderr,
		errOut(
			"--header: expected key=value or JSON, got 'no-equals-here'",
			"myapp cmd",
		),
	);
	assert.equal(
		(await run(mk([]), ["cmd", "--header", "a=1", "--header", "a=2"])).stderr,
		errOut("--header: duplicate key 'a'", "myapp cmd"),
	);
});

test("env_separator: split, escapes, unique and coercion errors", async () => {
	const mkTags = (out: string[], unique: boolean): AppImpl => {
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					tag: flag("tag", t.list(t.str), {
						help: "a tag",
						env: "TAGS",
						envSeparator: ",",
						prefixed: false,
						unique,
					}),
				},
				handler: (a) => {
					out.push(`tags=${fmt(a.tag)}`);
				},
			}),
		);
		return app;
	};
	await withEnv({ TAGS: "a,b,c" }, async () => {
		const out: string[] = [];
		assert.equal(
			(await run(mkTags(out, false), ["cmd"], out)).stdout,
			"tags=a,b,c",
		);
	});
	await withEnv({ TAGS: "a\\,b,c" }, async () => {
		const out: string[] = [];
		// Escaped separator joins the first two segments: elements "a,b" and "c".
		assert.equal(
			(await run(mkTags(out, false), ["cmd"], out)).stdout,
			"tags=a,b,c",
		);
	});
	await withEnv({ TAGS: "a,b,a" }, async () => {
		assert.equal(
			(await run(mkTags([], true), ["cmd"])).stderr,
			errOut("--tag: duplicate value 'a' (from env var 'TAGS')", "myapp cmd"),
		);
	});

	const mkCounts = (): AppImpl => {
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					count: flag("count", t.list(t.int), {
						help: "the counts",
						env: "COUNTS",
						envSeparator: ",",
						prefixed: false,
						unique: false,
					}),
				},
				handler: () => undefined,
			}),
		);
		return app;
	};
	await withEnv({ COUNTS: "1,abc,3" }, async () => {
		assert.equal(
			(await run(mkCounts(), ["cmd"])).stderr,
			errOut(
				"--count: expected integer, got 'abc' (from env var 'COUNTS')",
				"myapp cmd",
			),
		);
	});
});

// =========================================================================
// choices.json
// =========================================================================

test("choices: invalid str choice rejected with exact message", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				format: flag("format", t.str, {
					help: "output format",
					choices: ["text", "json"],
					default: "text",
				}),
			},
			handler: () => undefined,
		}),
	);
	const r = await run(app, ["cmd", "--format", "xml"]);
	assert.equal(
		r.stderr,
		errOut(
			"--format: invalid value 'xml', must be one of: text, json",
			"myapp cmd",
		),
	);
	assert.equal((await run(app, ["cmd", "--format", "json"])).exitCode, 0);
});

test("choices: optional arg with choices -- omitted ok, invalid rejected", async () => {
	const mk = (out: string[]): AppImpl => {
		const app = makeApp();
		app.command(
			defineCommand("cmd", {
				help: "a command",
				args: [
					arg("env", t.str, {
						help: "target env",
						required: false,
						choices: ["dev", "prod"],
					}),
				],
				handler: (a) => {
					out.push(`env=${fmt(a.env)}`);
				},
			}),
		);
		return app;
	};
	const out: string[] = [];
	assert.equal((await run(mk(out), ["cmd"], out)).stdout, "env=None");
	assert.equal(
		(await run(mk([]), ["cmd", "local"])).stderr,
		errOut(
			"argument 'env': invalid value 'local', must be one of: dev, prod",
			"myapp cmd",
		),
	);
});

test("choices: int arg choices format values without quotes-mismatch", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			args: [arg("level", t.int, { help: "the level", choices: [0n, 1n, 2n] })],
			handler: () => undefined,
		}),
	);
	const r = await run(app, ["cmd", "5"]);
	assert.equal(
		r.stderr,
		errOut(
			"argument 'level': invalid value '5', must be one of: 0, 1, 2",
			"myapp cmd",
		),
	);
});

test("choices: unset mutex flag with choices is not validated", async () => {
	const out: string[] = [];
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			mutex: [
				mutexGroup({
					format: flag("format", t.str, {
						help: "output format",
						default: null,
						choices: ["text", "json"],
					}),
					output: flag("output", t.str, { help: "output path", default: null }),
				}),
			],
			handler: (a) => {
				const g = a as unknown as { format?: string; output?: string };
				out.push(`format=${fmt(g.format)} output=${fmt(g.output)}`);
			},
		}),
	);
	const r = await run(app, ["cmd", "--output", "out.txt"], out);
	assert.equal(r.stdout, "format=None output=out.txt");
});

// =========================================================================
// Custom validate callbacks
// =========================================================================

test("validate: rejecting validator produces --flag: message", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				port: flag("port", t.int, {
					help: "the port",
					default: 1n,
					validate: (v) => {
						if (v > 65535n) {
							throw new Error("port must be <= 65535");
						}
					},
				}),
			},
			handler: () => undefined,
		}),
	);
	assert.equal((await run(app, ["cmd", "--port", "80"])).exitCode, 0);
	const r = await run(app, ["cmd", "--port", "70000"]);
	assert.equal(r.stderr, errOut("--port: port must be <= 65535", "myapp cmd"));
});

test("validate: list validator runs per element", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				tag: flag("tag", t.list(t.str), {
					help: "a tag",
					validate: (v) => {
						if (v.startsWith("x")) {
							throw new Error(`bad tag '${v}'`);
						}
					},
				}),
			},
			handler: () => undefined,
		}),
	);
	assert.equal((await run(app, ["cmd", "--tag", "ok"])).exitCode, 0);
	const r = await run(app, ["cmd", "--tag", "ok", "--tag", "xbad"]);
	assert.equal(r.stderr, errOut("--tag: bad tag 'xbad'", "myapp cmd"));
});

// =========================================================================
// passthrough.json
// =========================================================================

test("passthrough: receives raw args and pre-command globals", async () => {
	const out: string[] = [];
	const app = makeApp({
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "enable verbose output",
				default: false,
			}),
		},
	});
	app.command(
		passthrough("checkout", {
			help: "git checkout passthrough",
			handler: (a) => {
				out.push(`${a.name}:${a.args.join(",")}`);
				out.push(`verbose=${fmt(a.globals.verbose)}`);
			},
		}),
	);
	const r = await run(app, ["--verbose", "checkout", "-b", "feature"], out);
	assert.equal(r.exitCode, 0);
	assert.equal(r.stdout, "checkout:-b,feature\nverbose=true");
	const o = r.outcome as Extract<ParseOutcome, { kind: "passthrough" }>;
	assert.deepEqual(o.args, ["-b", "feature"]);
	assert.equal(o.cmdPath, "checkout");
});

// =========================================================================
// exit codes and command help recognition
// =========================================================================

test("handler numeric return becomes the exit code", async () => {
	const app = makeApp();
	app.command(
		defineCommand("fail", { help: "always fails", handler: () => 3 }),
	);
	const r = await run(app, ["fail"]);
	assert.equal(r.exitCode, 3);
});

test("help: --help/-h recognized anywhere in command tokens, but not after --", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: { target: flag("target", t.str, { help: "the target" }) },
			args: [arg("path", t.str, { help: "a path", required: false })],
			handler: () => undefined,
		}),
	);
	for (const argv of [
		["cmd", "--help"],
		["cmd", "-h"],
		["cmd", "--target", "x", "--help"],
	]) {
		const r = await run(app, argv);
		assert.equal(r.kind, "help");
		const o = r.outcome as Extract<ParseOutcome, { kind: "help" }>;
		assert.equal(o.target.level, "command");
	}
	// After -- the token is a literal positional, not a help request.
	const r = await run(app, ["cmd", "--target", "x", "--", "--help"]);
	assert.equal(r.kind, "command");
});

// =========================================================================
// hermetic.json + reserved-flag pre-scan
// =========================================================================

test("hermetic: env vars are ignored; source is 'default'", async () => {
	const out: string[] = [];
	const app = makeApp({ envPrefix: "MYAPP" });
	app.command(
		defineCommand("run", {
			help: "run it",
			flags: {
				level: flag("level", t.int, {
					help: "the level",
					env: "MYAPP_LEVEL",
					default: 0n,
				}),
			},
			handler: (a) => {
				out.push(`level=${fmt(a.level)}`);
			},
		}),
	);
	await withEnv({ MYAPP_LEVEL: "42" }, async () => {
		const r = await run(app, ["--hermetic", "run"], out);
		assert.equal(r.stdout, "level=0");
		const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o.sources.level, "default");
	});
});

test("hermetic: required flag missing errors even when env is set", async () => {
	const app = makeApp({ envPrefix: "MYAPP" });
	app.command(
		defineCommand("run", {
			help: "run it",
			flags: {
				name: flag("name", t.str, { help: "the name", env: "MYAPP_NAME" }),
			},
			handler: () => undefined,
		}),
	);
	await withEnv({ MYAPP_NAME: "test-value" }, async () => {
		const r = await run(app, ["--hermetic", "run"]);
		assert.equal(r.stderr, errOut("flag '--name' is required", "myapp run"));
	});
});

test("hermetic: --hermetic and --config are mutually exclusive", async () => {
	const app = makeApp({ config: true });
	app.command(
		defineCommand("run", { help: "run it", handler: () => undefined }),
	);
	const r = await run(app, [
		"--hermetic",
		"--config",
		"/tmp/nonexistent.json",
		"run",
	]);
	assert.equal(
		r.stderr,
		errOut("--hermetic and --config are mutually exclusive"),
	);
});

test("hermetic: --hermetic cannot be used with config commands", async () => {
	const app = makeApp({ config: true });
	const config = app.group("config", { help: "manage configuration" });
	config.command(
		defineCommand("show", { help: "display config", handler: () => undefined }),
	);
	const r = await run(app, ["--hermetic", "config", "show"]);
	assert.equal(
		r.stderr,
		errOut("--hermetic cannot be used with config commands"),
	);
});

test("prescan: --config on a non-config app is rejected", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	const r = await run(app, ["--config", "x.json", "cmd"]);
	assert.equal(
		r.stderr,
		errOut("--config is not available: this app does not use config files"),
	);
});

test("prescan: --config requires a value (bare and equals forms)", async () => {
	const app = makeApp({ config: true });
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	assert.equal(
		(await run(app, ["--config"])).stderr,
		errOut("flag '--config' requires a value"),
	);
	assert.equal(
		(await run(app, ["--config=", "cmd"])).stderr,
		errOut("flag '--config' requires a value"),
	);
});

test("prescan: --dump-schema and --mcp intercept in the pre-command region only", async () => {
	const app = makeApp();
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	assert.equal(doParse(app, ["--dump-schema"]).kind, "dump-schema");
	assert.equal(doParse(app, ["--mcp"]).kind, "mcp");
	// After the command token they are ordinary unknown flags.
	const r = await run(app, ["cmd", "--dump-schema"]);
	assert.equal(r.stderr, errOut("unknown flag '--dump-schema'", "myapp cmd"));
});

test("prescan: global flag value that looks like a command name is skipped", () => {
	const app = makeApp({
		flags: {
			settings: flag("settings", t.str, {
				help: "settings path",
				default: "/etc",
			}),
		},
	});
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	const pre = preScanReservedFlags(app as AppImpl, [
		"--settings",
		"cmd",
		"--hermetic",
		"cmd",
	]);
	assert.equal(pre.hermetic, true);
	assert.deepEqual(pre.cleanedArgv, ["--settings", "cmd", "cmd"]);
});

// =========================================================================
// provenance.json (source labels)
// =========================================================================

test("provenance: cli vs default; post- and pre-command global cli", async () => {
	const app = makeApp({
		flags: {
			settings: flag("settings", t.str, {
				help: "settings path",
				default: "/etc/myapp",
			}),
		},
	});
	app.command(
		defineCommand("run", {
			help: "run it",
			flags: {
				output: flag("output", t.str, { help: "output file", default: "none" }),
				level: flag("level", t.int, { help: "the level", default: 5n }),
			},
			handler: () => undefined,
		}),
	);
	const r = await run(app, ["run", "--output", "file.txt"]);
	const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o.sources.output, "cli");
	assert.equal(o.sources.level, "default");
	assert.equal(o.sources.settings, "default");

	const r2 = await run(app, ["run", "--settings", "from-cli"]);
	const o2 = r2.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o2.sources.settings, "cli");
	assert.equal(o2.kwargs.settings, "from-cli");

	const r3 = await run(app, ["--settings", "from-cli", "run"]);
	const o3 = r3.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o3.sources.settings, "cli");
});

test("provenance: env label; CLI overrides env with label cli", async () => {
	const app = makeApp();
	app.command(
		defineCommand("run", {
			help: "run it",
			flags: {
				level: flag("level", t.int, {
					help: "the level",
					env: "PROV_LEVEL",
					prefixed: false,
					default: 5n,
				}),
			},
			handler: () => undefined,
		}),
	);
	await withEnv({ PROV_LEVEL: "42" }, async () => {
		const r = await run(app, ["run"]);
		const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o.sources.level, "env");
		assert.equal(o.kwargs.level, 42n);
		const r2 = await run(app, ["run", "--level", "99"]);
		const o2 = r2.outcome as Extract<ParseOutcome, { kind: "command" }>;
		assert.equal(o2.sources.level, "cli");
	});
});

// =========================================================================
// Config seam (Phase-5 provider injection): precedence and conflicts
// =========================================================================

test("config: fills flags not set by CLI or env; CLI wins by default", async () => {
	const mk = (out: string[]): AppImpl => {
		const app = makeApp({ config: true });
		app.command(
			defineCommand("cmd", {
				help: "a command",
				flags: {
					mode: flag("mode", t.str, { help: "the mode", default: "normal" }),
				},
				handler: (a) => {
					out.push(`mode=${fmt(a.mode)}`);
				},
			}),
		);
		return app;
	};
	const deps: DoParseDeps = { config: fakeConfig({ mode: "from-config" }) };
	const out: string[] = [];
	const r = await run(mk(out), ["cmd"], out, deps);
	assert.equal(r.stdout, "mode=from-config");
	const o = r.outcome as Extract<ParseOutcome, { kind: "command" }>;
	assert.equal(o.sources.mode, "config");

	const out2: string[] = [];
	const r2 = await run(mk(out2), ["cmd", "--mode", "cli-val"], out2, deps);
	assert.equal(r2.stdout, "mode=cli-val");
});

test("config: conflict mode error rejects diverging cli+config", async () => {
	const app = makeApp({ config: true, configConflictMode: "error" });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				mode: flag("mode", t.str, { help: "the mode", default: "normal" }),
			},
			handler: () => undefined,
		}),
	);
	const deps: DoParseDeps = { config: fakeConfig({ mode: "config-val" }) };
	const r = await run(app, ["cmd", "--mode", "cli-val"], [], deps);
	assert.equal(
		r.stderr,
		errOut("flag 'mode' set in both cli and config; remove one", "myapp cmd"),
	);
	// Matching values are not a conflict.
	const r2 = await run(app, ["cmd", "--mode", "config-val"], [], deps);
	assert.equal(r2.exitCode, 0);
});

test("config: post-command global conflict detection (error mode)", async () => {
	const app = makeApp({
		config: true,
		configConflictMode: "error",
		flags: {
			settings: flag("settings", t.str, {
				help: "settings path",
				default: "/etc/myapp",
			}),
		},
	});
	app.command(
		defineCommand("cmd", { help: "a command", handler: () => undefined }),
	);
	const deps: DoParseDeps = { config: fakeConfig({ settings: "/cfg" }) };
	const r = await run(app, ["cmd", "--settings", "/other"], [], deps);
	assert.equal(
		r.stderr,
		errOut(
			"flag 'settings' set in both cli and config; remove one",
			"myapp cmd",
		),
	);
});

test("config: repeatable config value overrides default", async () => {
	const out: string[] = [];
	const app = makeApp({ config: true });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				tag: flag("tag", t.list(t.str), { help: "a tag", default: ["x", "y"] }),
			},
			handler: (a) => {
				out.push(`tags=${fmt(a.tag)}`);
			},
		}),
	);
	const deps: DoParseDeps = { config: fakeConfig({ tag: ["from-config"] }) };
	const r = await run(app, ["cmd"], out, deps);
	assert.equal(r.stdout, "tags=from-config");
});

test("config: hermetic skips config entirely", async () => {
	const out: string[] = [];
	const app = makeApp({ config: true });
	app.command(
		defineCommand("cmd", {
			help: "a command",
			flags: {
				mode: flag("mode", t.str, { help: "the mode", default: "normal" }),
			},
			handler: (a) => {
				out.push(`mode=${fmt(a.mode)}`);
			},
		}),
	);
	const deps: DoParseDeps = { config: fakeConfig({ mode: "from-config" }) };
	const r = await run(app, ["--hermetic", "cmd"], out, deps);
	assert.equal(r.stdout, "mode=normal");
});

// =========================================================================
// keyword-ish names and param mapping
// =========================================================================

test("flagParamName maps dashes to underscores (no Python keyword suffix)", () => {
	assert.equal(flagParamName("dry-run"), "dry_run");
	assert.equal(flagParamName("--dry-run"), "dry_run");
	assert.equal(flagParamName("global"), "global");
});

test("tokensContainHelp respects the -- separator", () => {
	assert.equal(tokensContainHelp(["--target", "x", "--help"]), true);
	assert.equal(tokensContainHelp(["-h"]), true);
	assert.equal(tokensContainHelp(["--", "--help"]), false);
	assert.equal(tokensContainHelp(["a", "b"]), false);
});
