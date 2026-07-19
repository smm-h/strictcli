/**
 * Schema dump tests (src/schema.ts).
 *
 * EXPECTED_JSON below was derived by running the PYTHON implementation's
 * --dump-schema on a byte-equivalent mirror app (Python is the divergence
 * ground truth) and normalizing the known TS model deltas:
 *  - compound flag types become the TS carrier schema strings ("list[str]",
 *    "list[int]", "dict[str,int]" instead of Python's JSON-schema objects),
 *  - dict flag defaults are emitted with sorted keys (the TS Map display
 *    convention; the mirror declared {"beta": 2, "alpha": 1}),
 *  - project_id is stripped (the written file adds it back from
 *    package.json).
 * Everything else -- key order, omission rules, the defaults block, the
 * auto-registered check command and config group, checks/config_fields/infra
 * sections, SCF float tokens, and bare integer tokens -- is byte-derived
 * from the Python output.
 */

import { strict as assert } from "node:assert";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { deprecated } from "../src/factories.js";
import {
	type App,
	arg,
	coRequired,
	createApp,
	defineCommand,
	flag,
	flagSet,
	implies,
	mutexGroup,
	passthrough,
	relativeToRoot,
	requires,
	t,
} from "../src/index.js";
import { schemaJson } from "../src/schema.js";

const EXPECTED_JSON = `{"schema_version":1,"defaults":{"schema_version":1,"app":{"env_prefix":null,"config":false,"global_flags":[],"commands":{},"groups":{},"deprecated":{},"tag_contracts":{}},"flag":{"short":null,"default":null,"env":null,"choices":null,"repeatable":false,"unique":false,"env_separator":null,"negatable":null,"hidden":false},"arg":{"type":"str","required":true,"default":null,"variadic":false,"choices":null},"command":{"passthrough":false,"flags":[],"args":[],"tags":[],"constraints":[],"hidden":false,"interactive":false},"group":{"commands":{},"groups":{},"deprecated":{},"tags":[],"hidden":false}},"name":"richapp","version":"2.5.0","help":"A comprehensive schema app","env_prefix":"RICH","config":true,"global_flags":[{"name":"verbose","type":"bool","help":"Enable verbose output","short":"V","default":false,"negatable":true},{"name":"log-level","type":"str","help":"Logging level","default":"info","env":"RICH_LOG_LEVEL","choices":["debug","info","warn","error"]},{"name":"state-file","type":"str","help":"State file relative to the infra root","default":{"relative_to_root":{"env_var":"RICH_HOME","parts":["state","app.db"]}}}],"commands":{"check":{"name":"check","help":"Run project checks registered via the check framework and report results","flags":[{"name":"all","type":"bool","help":"Run every registered check regardless of tag or name filters","default":false,"negatable":true},{"name":"tag","type":"str","help":"Tag DSL expression to select checks (e.g. 'changelog & !quality')","default":""},{"name":"name","type":"str","help":"Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*')","default":""},{"name":"list","type":"bool","help":"List all registered checks with their tags and exit without running","default":false,"negatable":true},{"name":"json","type":"bool","help":"Output check results as machine-readable JSON instead of human text","default":false,"negatable":true},{"name":"ignore-warnings","type":"bool","help":"Treat warn-severity results as passing so they do not cause nonzero exit","default":false,"negatable":true},{"name":"dry-run","type":"bool","help":"Show which checks would run based on current filters without executing them","default":false,"negatable":true}]},"types":{"name":"types","help":"Test all flag types","flags":[{"name":"name","type":"str","help":"A string flag","default":"world"},{"name":"count","type":"int","help":"An integer flag","default":42},{"name":"big","type":"int","help":"A big integer flag","default":9007199254740993},{"name":"ratio","type":"float","help":"A float flag","default":3.14},{"name":"dry-run","type":"bool","help":"Dry run mode","negatable":true},{"name":"cache-file","type":"str","help":"Cache file relative to the infra root","default":{"relative_to_root":{"env_var":"RICH_HOME","parts":["cache.bin"]}}}],"args":[{"name":"target","help":"Target to process"}]},"multi":{"name":"multi","help":"Test list and dict flags","flags":[{"name":"tag","type":"list[str]","help":"Tags to apply","env":"RICH_TAGS","unique":true,"env_separator":","},{"name":"port","type":"list[int]","help":"Ports to open","default":[80,443]},{"name":"matrix","type":"dict[str,int]","help":"Named weights","default":{"alpha":1,"beta":2}}]},"output":{"name":"output","help":"Test mutex flags","flags":[{"name":"json","type":"bool","help":"JSON output","negatable":true},{"name":"yaml","type":"bool","help":"YAML output","negatable":true},{"name":"text","type":"bool","help":"Text output","negatable":true}],"constraints":[{"type":"mutex","flags":["json","yaml","text"]}]},"deploy":{"name":"deploy","help":"Test dependencies","flags":[{"name":"host","type":"str","help":"Deploy host"},{"name":"port-num","type":"int","help":"Deploy port"},{"name":"ssl","type":"bool","help":"Use SSL","negatable":true},{"name":"cert","type":"str","help":"SSL certificate path"}],"constraints":[{"type":"co_required","flags":["host","port-num"]},{"type":"requires","flag":"cert","depends_on":"ssl"}]},"notify":{"name":"notify","help":"Test implies dependency","flags":[{"name":"email","type":"bool","help":"Send email notification","negatable":true},{"name":"alert","type":"bool","help":"Enable alerts","negatable":true}],"constraints":[{"type":"implies","flag":"email","implies":"alert","value":true}]},"query":{"name":"query","help":"Test flag sets","flags":[{"name":"page","type":"int","help":"Page number","default":1},{"name":"per-page","type":"int","help":"Items per page","default":20}]},"files":{"name":"files","help":"Test args","args":[{"name":"src","help":"Source directory"},{"name":"mode","help":"Copy mode","required":false,"default":"fast"},{"name":"extra","help":"Extra files","required":false,"variadic":true}]},"exec":{"name":"exec","help":"Execute a command","passthrough":true},"lint":{"name":"lint","help":"Run linters","tags":["ci","quality"]},"level":{"name":"level","help":"Test int/float choices","flags":[{"name":"priority","type":"int","help":"Priority level","default":3,"choices":[1,2,3,4,5]},{"name":"threshold","type":"float","help":"Threshold value","default":0.5,"choices":[0.1,0.5,0.9]}]},"info":{"name":"info","help":"Show info","flags":[{"name":"format","type":"str","help":"Output format","short":"f","default":"table"},{"name":"color-off","type":"bool","help":"Disable colors","default":false,"negatable":false},{"name":"strict-mode","type":"bool","help":"Strict mode","default":false,"conflict_mode":"error","negatable":true}]},"secret":{"name":"secret","help":"Hidden maintenance command","hidden":true},"shell":{"name":"shell","help":"Interactive shell","interactive":true},"serve":{"name":"serve","help":"Start the server","config_fields":["api.key","listen_port"]}},"groups":{"config":{"name":"config","help":"Manage persistent configuration values stored in the config file","commands":{"path":{"name":"path","help":"Print the absolute path to the config file for this application"},"show":{"name":"show","help":"Show all config values with their sources (config file, env, or default)","flags":[{"name":"plain","type":"bool","help":"Display config values in a human-readable table format","default":false,"negatable":true},{"name":"json","type":"bool","help":"Display config values as a JSON object with source metadata","default":false,"negatable":true}],"constraints":[{"type":"mutex","flags":["plain","json"]}]},"set":{"name":"set","help":"Set a persistent config value that overrides the default for a flag","flags":[{"name":"clear","type":"bool","help":"Clear a repeatable flag by setting its value to an empty list","default":false,"negatable":true},{"name":"default","type":"bool","help":"Reset a key to its default value by removing it from the config file","default":false,"negatable":true}],"args":[{"name":"key","help":"The config key to set, matching a registered flag name"},{"name":"value","help":"Value to set (comma-separated for repeatable flags, use backslash to escape commas)","required":false}]},"edit":{"name":"edit","help":"Open the config file for manual editing in $EDITOR (creates if missing)","interactive":true},"init":{"name":"init","help":"Generate a template config file with documented fields and defaults"}}},"db":{"name":"db","help":"Database operations","commands":{"migrate":{"name":"migrate","help":"Run migrations","flags":[{"name":"steps","type":"int","help":"Migration steps"}],"tags":["infra"],"config_fields":["listen_port"]},"seed":{"name":"seed","help":"Seed database","tags":["infra"]}},"groups":{"cache":{"name":"cache","help":"Cache operations","commands":{"clear":{"name":"clear","help":"Clear cache","tags":["infra"]},"stats":{"name":"stats","help":"Show cache stats","flags":[{"name":"detailed","type":"bool","help":"Show detailed stats","negatable":true}],"tags":["infra"]}}}},"deprecated":{"reset":"Use 'db migrate --steps -1' instead"},"tags":["infra"]}},"deprecated":{"old-cmd":"Use 'new-cmd' instead"},"tag_contracts":{"quality":"verbose"},"checks":{"lint-clean":{"tags":["quality"],"severity":"error","fast":true,"pure":true,"needs_network":false,"depends_on":[]},"db-ping":{"tags":["infra"],"severity":"warn","fast":false,"pure":false,"needs_network":true,"depends_on":["lint-clean"],"scope":"db"}},"config_fields":{"api.key":{"type":"str","help":"API key for the service","required":true,"bound_commands":["serve"]},"listen_port":{"type":"int","help":"Port to listen on","required":false,"default":8080,"bound_commands":["serve","db migrate"]},"debug":{"type":"bool","help":"Enable debug mode","required":false,"default":false}},"infra":{"roots":[{"env_var":"RICH_HOME","default":"/var/lib/richapp"}],"handshakes":[{"env_var":"RICH_SESSION","help":"Session token from the invoking process"}]}}`;

const CHECKS_TOML = `app = "richapp"

[checks.lint-clean]
tags = ["quality"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.db-ping]
tags = ["infra"]
severity = "warn"
fast = false
pure = false
needs_network = true
depends_on = ["lint-clean"]
scope = "db"
`;

/** Builds the TS rich app; registration order mirrors the Python mirror app. */
function buildRichApp(): App {
	const app = createApp({
		name: "richapp",
		version: "2.5.0",
		help: "A comprehensive schema app",
		envPrefix: "RICH",
		config: true,
		infraRoot: { RICH_HOME: "/var/lib/richapp" },
		handshakeEnv: { RICH_SESSION: "Session token from the invoking process" },
		checksEmbed: CHECKS_TOML,
		flags: {
			verbose: flag("verbose", t.bool, {
				help: "Enable verbose output",
				short: "V",
				default: false,
			}),
			log_level: flag("log-level", t.str, {
				help: "Logging level",
				default: "info",
				env: "RICH_LOG_LEVEL",
				choices: ["debug", "info", "warn", "error"],
			}),
			state_file: flag("state-file", t.str, {
				help: "State file relative to the infra root",
				default: relativeToRoot("RICH_HOME", "state", "app.db"),
			}),
		},
	});

	app.configField("api.key", { type: t.str, help: "API key for the service" });
	app.configField("listen_port", {
		type: t.int,
		help: "Port to listen on",
		default: 8080n,
	});
	app.configField("debug", {
		type: t.bool,
		help: "Enable debug mode",
		default: false,
	});

	app.errorCheck("lint-clean", (_ctx, r) => r.passed("clean"));
	app.warnCheck("db-ping", (_ctx, r) => r.passed("pong"));

	app.command(
		defineCommand("types", {
			help: "Test all flag types",
			flags: {
				name: flag("name", t.str, {
					help: "A string flag",
					default: "world",
				}),
				count: flag("count", t.int, {
					help: "An integer flag",
					default: 42n,
				}),
				big: flag("big", t.int, {
					help: "A big integer flag",
					default: 9007199254740993n,
				}),
				ratio: flag("ratio", t.float, {
					help: "A float flag",
					default: 3.14,
				}),
				dry_run: flag("dry-run", t.bool, { help: "Dry run mode" }),
				cache_file: flag("cache-file", t.str, {
					help: "Cache file relative to the infra root",
					default: relativeToRoot("RICH_HOME", "cache.bin"),
				}),
			},
			args: [arg("target", t.str, { help: "Target to process" })],
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("multi", {
			help: "Test list and dict flags",
			flags: {
				tag: flag("tag", t.list(t.str), {
					help: "Tags to apply",
					unique: true,
					env: "RICH_TAGS",
					envSeparator: ",",
				}),
				port: flag("port", t.list(t.int), {
					help: "Ports to open",
					unique: false,
					default: [80n, 443n],
				}),
				// Insertion order beta-then-alpha; the schema must sort dict keys.
				matrix: flag("matrix", t.dict(t.int), {
					help: "Named weights",
					default: new Map([
						["beta", 2n],
						["alpha", 1n],
					]),
				}),
			},
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("output", {
			help: "Test mutex flags",
			mutex: [
				mutexGroup({
					json: flag("json", t.bool, { help: "JSON output" }),
					yaml: flag("yaml", t.bool, { help: "YAML output" }),
					text: flag("text", t.bool, { help: "Text output" }),
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("deploy", {
			help: "Test dependencies",
			flags: {
				host: flag("host", t.str, { help: "Deploy host", default: null }),
				port_num: flag("port-num", t.int, {
					help: "Deploy port",
					default: null,
				}),
				ssl: flag("ssl", t.bool, { help: "Use SSL" }),
				cert: flag("cert", t.str, {
					help: "SSL certificate path",
					default: null,
				}),
			},
			dependencies: [
				coRequired(["host", "port-num"]),
				requires({ flag: "cert", dependsOn: "ssl" }),
			],
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("notify", {
			help: "Test implies dependency",
			flags: {
				email: flag("email", t.bool, { help: "Send email notification" }),
				alert: flag("alert", t.bool, { help: "Enable alerts" }),
			},
			dependencies: [implies({ flag: "email", implies: "alert", value: true })],
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("query", {
			help: "Test flag sets",
			flagSets: [
				flagSet("pagination", {
					page: flag("page", t.int, { help: "Page number", default: 1n }),
					per_page: flag("per-page", t.int, {
						help: "Items per page",
						default: 20n,
					}),
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("files", {
			help: "Test args",
			args: [
				arg("src", t.str, { help: "Source directory" }),
				arg("mode", t.str, {
					help: "Copy mode",
					required: false,
					default: "fast",
				}),
				arg("extra", t.str, {
					help: "Extra files",
					required: false,
					variadic: true,
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		passthrough("exec", { help: "Execute a command", handler: () => 0 }),
	);

	app.command(
		defineCommand("lint", {
			help: "Run linters",
			tags: ["quality", "ci"],
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("level", {
			help: "Test int/float choices",
			flags: {
				priority: flag("priority", t.int, {
					help: "Priority level",
					choices: [1n, 2n, 3n, 4n, 5n],
					default: 3n,
				}),
				threshold: flag("threshold", t.float, {
					help: "Threshold value",
					choices: [0.1, 0.5, 0.9],
					default: 0.5,
				}),
			},
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("info", {
			help: "Show info",
			flags: {
				format: flag("format", t.str, {
					help: "Output format",
					short: "f",
					default: "table",
				}),
				color_off: flag("color-off", t.bool, {
					help: "Disable colors",
					negatable: false,
					default: false,
				}),
				strict_mode: flag("strict-mode", t.bool, {
					help: "Strict mode",
					conflictMode: "error",
					default: false,
				}),
			},
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("secret", {
			help: "Hidden maintenance command",
			hidden: true,
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("shell", {
			help: "Interactive shell",
			interactive: true,
			handler: () => 0,
		}),
	);

	app.command(
		defineCommand("serve", {
			help: "Start the server",
			configFields: ["api.key", "listen_port"],
			handler: () => 0,
		}),
	);

	app.deprecate(deprecated("old-cmd", "Use 'new-cmd' instead"));
	app.tagContract("quality", "verbose");

	const db = app.group("db", { help: "Database operations", tags: ["infra"] });
	db.command(
		defineCommand("migrate", {
			help: "Run migrations",
			flags: {
				steps: flag("steps", t.int, {
					help: "Migration steps",
					default: null,
				}),
			},
			configFields: ["listen_port"],
			handler: () => 0,
		}),
	);
	db.command(
		defineCommand("seed", { help: "Seed database", handler: () => 0 }),
	);
	db.deprecate(deprecated("reset", "Use 'db migrate --steps -1' instead"));

	const cache = db.group("cache", { help: "Cache operations" });
	cache.command(
		defineCommand("clear", { help: "Clear cache", handler: () => 0 }),
	);
	cache.command(
		defineCommand("stats", {
			help: "Show cache stats",
			flags: {
				detailed: flag("detailed", t.bool, { help: "Show detailed stats" }),
			},
			handler: () => 0,
		}),
	);

	return app;
}

function buildMinimalApp(): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(defineCommand("greet", { help: "say hello", handler: () => 0 }));
	return app;
}

/** Runs fn with cwd switched to a fresh temp dir; restores cwd afterwards. */
async function withTempCwd<T>(fn: (dir: string) => Promise<T>): Promise<T> {
	const oldCwd = process.cwd();
	process.chdir(mkdtempSync(join(tmpdir(), "strictcli-schema-")));
	try {
		// process.cwd() (not the mkdtemp result) so symlinked tmpdirs compare
		// equal to paths produced by resolve().
		return await fn(process.cwd());
	} finally {
		process.chdir(oldCwd);
	}
}

// --- Rich-app structural equality ---

test("--dump-schema writes the expected rich-app schema file", async () => {
	await withTempCwd(async (dir) => {
		writeFileSync("package.json", '{"name": "richapp"}\n');
		const res = await buildRichApp().test(["--dump-schema"]);
		assert.equal(res.stderr, "");
		assert.equal(res.exitCode, 0);
		const schemaPath = join(dir, ".strictcli", "schema.json");
		assert.equal(res.stdout, `${schemaPath}\n`);

		const raw = readFileSync(schemaPath, "utf8");
		// Exact sibling formatting: 2-space indent, ": " separator, trailing \n.
		assert.ok(raw.startsWith('{\n  "schema_version": 1,\n  "defaults": {\n'));
		assert.ok(raw.endsWith("\n"));
		assert.ok(!raw.endsWith("\n\n"));
		// BigInt defaults are bare integer tokens, precise beyond 2^53.
		assert.ok(raw.includes('"default": 9007199254740993'));
		// Float defaults are SCF tokens (valid JSON numbers).
		assert.ok(raw.includes('"default": 3.14'));

		const parsed = JSON.parse(raw) as Record<string, unknown>;
		assert.equal(parsed.project_id, "richapp");
		// project_id sits immediately after defaults (Python layout).
		assert.deepEqual(Object.keys(parsed).slice(0, 5), [
			"schema_version",
			"defaults",
			"project_id",
			"name",
			"version",
		]);
		delete parsed.project_id;
		assert.deepEqual(parsed, JSON.parse(EXPECTED_JSON));
	});
});

test("dumpSchemaDict is CWD-free, has no project_id, and matches the file content", () => {
	const dict = buildRichApp().dumpSchemaDict();
	assert.ok(!("project_id" in dict));
	// Integer schema values are bigint (BigInt int64 end-to-end).
	assert.equal(dict.schema_version, 1n);
	assert.deepEqual(JSON.parse(schemaJson(dict)), JSON.parse(EXPECTED_JSON));
});

// --- Conformance case behaviors (cases/dump_schema.json) ---

test("--dump-schema exits 0 and prints the absolute schema path", async () => {
	await withTempCwd(async (dir) => {
		writeFileSync("package.json", '{"name": "myapp"}\n');
		const res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 0);
		assert.ok(res.stdout.includes(".strictcli/schema.json"));
		assert.ok(res.stdout.startsWith("/"));
		assert.equal(res.stdout, `${join(dir, ".strictcli", "schema.json")}\n`);
	});
});

// --- project_id-change guard on existing schema files ---

test("existing schema with a different project_id blocks the dump", async () => {
	await withTempCwd(async () => {
		writeFileSync("package.json", '{"name": "myapp"}\n');
		mkdirSync(".strictcli");
		const stale = '{"project_id": "other-proj"}\n';
		writeFileSync(join(".strictcli", "schema.json"), stale);
		const res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 1);
		assert.equal(
			res.stderr,
			"error: Schema mismatch: existing schema belongs to project " +
				"'other-proj', not 'myapp'. Run from the correct project directory.\n",
		);
		// The guard fires before the write: the stale file is untouched.
		assert.equal(
			readFileSync(join(".strictcli", "schema.json"), "utf8"),
			stale,
		);
	});
});

test("guard passes silently on unparseable, id-less, and matching existing schemas", async () => {
	await withTempCwd(async () => {
		writeFileSync("package.json", '{"name": "myapp"}\n');
		mkdirSync(".strictcli");
		const schemaPath = join(".strictcli", "schema.json");

		// Unparseable JSON: overwritten without complaint.
		writeFileSync(schemaPath, "not json{");
		let res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 0);

		// Valid JSON without project_id: overwritten without complaint.
		writeFileSync(schemaPath, '{"name": "whatever"}\n');
		res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 0);

		// Matching project_id (the file just written): re-dump succeeds.
		res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 0);
		const parsed = JSON.parse(readFileSync(schemaPath, "utf8")) as {
			project_id: string;
		};
		assert.equal(parsed.project_id, "myapp");
	});
});

// --- project_id derivation errors (package.json) ---

test("missing package.json is a hard error", async () => {
	await withTempCwd(async () => {
		const res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 1);
		assert.equal(
			res.stderr,
			"error: Cannot determine project_id: package.json not found\n",
		);
	});
});

test("unparseable package.json is a read error", async () => {
	await withTempCwd(async () => {
		writeFileSync("package.json", "{broken");
		const res = await buildMinimalApp().test(["--dump-schema"]);
		assert.equal(res.exitCode, 1);
		assert.ok(
			res.stderr.startsWith(
				"error: Cannot determine project_id: error reading package.json: ",
			),
		);
	});
});

test("package.json without a usable name field is a hard error", async () => {
	await withTempCwd(async () => {
		for (const content of ["{}", '{"name": ""}', '{"name": 42}']) {
			writeFileSync("package.json", content);
			const res = await buildMinimalApp().test(["--dump-schema"]);
			assert.equal(res.exitCode, 1);
			assert.equal(
				res.stderr,
				"error: Cannot determine project_id: no name field in package.json\n",
			);
		}
	});
});
