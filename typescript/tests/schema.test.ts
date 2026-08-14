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
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { deprecated } from "../src/factories.js";
import {
	type App,
	arg,
	coRequired,
	createApp,
	defineReadOnlyCommand,
	flag,
	flagSet,
	implies,
	mutexGroup,
	readOnlyPassthrough,
	relativeToRoot,
	requires,
	t,
} from "../src/index.js";
import { schemaJson } from "../src/schema.js";

const EXPECTED_JSON = `{
  "schema_version": 1,
  "defaults": {
    "schema_version": 1,
    "app": {
      "env_prefix": null,
      "config": false,
      "global_flags": [],
      "commands": {},
      "groups": {},
      "deprecated": {},
      "tag_contracts": {}
    },
    "flag": {
      "short": null,
      "default": null,
      "env": null,
      "choices": null,
      "repeatable": false,
      "unique": false,
      "env_separator": null,
      "negatable": null,
      "hidden": false
    },
    "arg": {
      "type": "str",
      "default": null,
      "variadic": false,
      "choices": null
    },
    "command": {
      "passthrough": false,
      "flags": [],
      "args": [],
      "tags": [],
      "constraints": [],
      "hidden": false,
      "interactive": false
    },
    "group": {
      "commands": {},
      "groups": {},
      "deprecated": {},
      "tags": [],
      "hidden": false
    }
  },
  "name": "richapp",
  "version": "2.5.0",
  "help": "A comprehensive schema app",
  "env_prefix": "RICH",
  "config": true,
  "global_flags": [
    {
      "name": "chatter",
      "type": "bool",
      "help": "Enable chatter output",
      "short": "V",
      "presence": "default",
      "default": false,
      "negatable": true
    },
    {
      "name": "log-level",
      "type": "str",
      "help": "Logging level",
      "presence": "default",
      "default": "info",
      "env": "RICH_LOG_LEVEL",
      "choices": [
        "debug",
        "info",
        "warn",
        "error"
      ]
    },
    {
      "name": "state-file",
      "type": "str",
      "help": "State file relative to the infra root",
      "presence": "default",
      "default": {
        "relative_to_root": {
          "env_var": "RICH_HOME",
          "parts": [
            "state",
            "app.db"
          ]
        }
      }
    }
  ],
  "commands": {
    "check": {
      "name": "check",
      "help": "Run project checks registered via the check framework and report results",
      "effect": "read_only",
      "payload_schema": {
        "type": "array",
        "items": {
          "type": "object"
        }
      },
      "flags": [
        {
          "name": "all",
          "type": "bool",
          "help": "Run every registered check regardless of tag or name filters",
          "presence": "default",
          "default": false,
          "negatable": true
        },
        {
          "name": "tag",
          "type": "str",
          "help": "Tag DSL expression to select checks (e.g. 'changelog & !quality')",
          "presence": "default",
          "default": ""
        },
        {
          "name": "name",
          "type": "str",
          "help": "Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*')",
          "presence": "default",
          "default": ""
        },
        {
          "name": "list",
          "type": "bool",
          "help": "List all registered checks with their tags and exit without running",
          "presence": "default",
          "default": false,
          "negatable": true
        },
        {
          "name": "ignore-warnings",
          "type": "bool",
          "help": "Treat warn-severity results as passing so they do not cause nonzero exit",
          "presence": "default",
          "default": false,
          "negatable": true
        }
      ],
      "forwarding": {
        "reason": "framework-internal: absorbs app-defined global flag values"
      }
    },
    "types": {
      "name": "types",
      "help": "Test all flag types",
      "effect": "read_only",
      "flags": [
        {
          "name": "name",
          "type": "str",
          "help": "A string flag",
          "presence": "default",
          "default": "world"
        },
        {
          "name": "count",
          "type": "int",
          "help": "An integer flag",
          "presence": "default",
          "default": 42
        },
        {
          "name": "big",
          "type": "int",
          "help": "A big integer flag",
          "presence": "default",
          "default": 9007199254740993
        },
        {
          "name": "ratio",
          "type": "float",
          "help": "A float flag",
          "presence": "default",
          "default": 3.14
        },
        {
          "name": "sim-run",
          "type": "bool",
          "help": "Dry run mode",
          "presence": "required",
          "negatable": true
        },
        {
          "name": "cache-file",
          "type": "str",
          "help": "Cache file relative to the infra root",
          "presence": "default",
          "default": {
            "relative_to_root": {
              "env_var": "RICH_HOME",
              "parts": [
                "cache.bin"
              ]
            }
          }
        }
      ],
      "args": [
        {
          "name": "target",
          "help": "Target to process",
          "presence": "required"
        }
      ]
    },
    "multi": {
      "name": "multi",
      "help": "Test list and dict flags",
      "effect": "read_only",
      "flags": [
        {
          "name": "tag",
          "type": "list[str]",
          "help": "Tags to apply",
          "presence": "default",
          "default": [],
          "env": "RICH_TAGS",
          "unique": true,
          "env_separator": ","
        },
        {
          "name": "port",
          "type": "list[int]",
          "help": "Ports to open",
          "presence": "default",
          "default": [
            80,
            443
          ]
        },
        {
          "name": "matrix",
          "type": "dict[str,int]",
          "help": "Named weights",
          "presence": "default",
          "default": {
            "alpha": 1,
            "beta": 2
          }
        }
      ]
    },
    "output": {
      "name": "output",
      "help": "Test mutex flags",
      "effect": "read_only",
      "flags": [
        {
          "name": "as-json",
          "type": "bool",
          "help": "JSON output",
          "presence": "optional",
          "negatable": true
        },
        {
          "name": "yaml",
          "type": "bool",
          "help": "YAML output",
          "presence": "optional",
          "negatable": true
        },
        {
          "name": "text",
          "type": "bool",
          "help": "Text output",
          "presence": "optional",
          "negatable": true
        }
      ],
      "constraints": [
        {
          "type": "mutex",
          "flags": [
            "as-json",
            "yaml",
            "text"
          ]
        }
      ]
    },
    "deploy": {
      "name": "deploy",
      "help": "Test dependencies",
      "effect": "read_only",
      "flags": [
        {
          "name": "host",
          "type": "str",
          "help": "Deploy host",
          "presence": "optional"
        },
        {
          "name": "port-num",
          "type": "int",
          "help": "Deploy port",
          "presence": "optional"
        },
        {
          "name": "ssl",
          "type": "bool",
          "help": "Use SSL",
          "presence": "required",
          "negatable": true
        },
        {
          "name": "cert",
          "type": "str",
          "help": "SSL certificate path",
          "presence": "optional"
        }
      ],
      "constraints": [
        {
          "type": "co_required",
          "flags": [
            "host",
            "port-num"
          ]
        },
        {
          "type": "requires",
          "flag": "cert",
          "depends_on": "ssl"
        }
      ]
    },
    "notify": {
      "name": "notify",
      "help": "Test implies dependency",
      "effect": "read_only",
      "flags": [
        {
          "name": "email",
          "type": "bool",
          "help": "Send email notification",
          "presence": "required",
          "negatable": true
        },
        {
          "name": "alert",
          "type": "bool",
          "help": "Enable alerts",
          "presence": "required",
          "negatable": true
        }
      ],
      "constraints": [
        {
          "type": "implies",
          "flag": "email",
          "implies": "alert",
          "value": true
        }
      ]
    },
    "query": {
      "name": "query",
      "help": "Test flag sets",
      "effect": "read_only",
      "flags": [
        {
          "name": "page",
          "type": "int",
          "help": "Page number",
          "presence": "default",
          "default": 1
        },
        {
          "name": "per-page",
          "type": "int",
          "help": "Items per page",
          "presence": "default",
          "default": 20
        }
      ]
    },
    "files": {
      "name": "files",
      "help": "Test args",
      "effect": "read_only",
      "args": [
        {
          "name": "src",
          "help": "Source directory",
          "presence": "required"
        },
        {
          "name": "mode",
          "help": "Copy mode",
          "presence": "default",
          "default": "fast"
        },
        {
          "name": "extra",
          "help": "Extra files",
          "presence": "optional",
          "variadic": true
        }
      ]
    },
    "exec": {
      "name": "exec",
      "help": "Execute a command",
      "effect": "read_only",
      "passthrough": true
    },
    "lint": {
      "name": "lint",
      "help": "Run linters",
      "effect": "read_only",
      "tags": [
        "ci",
        "quality"
      ]
    },
    "level": {
      "name": "level",
      "help": "Test int/float choices",
      "effect": "read_only",
      "flags": [
        {
          "name": "priority",
          "type": "int",
          "help": "Priority level",
          "presence": "default",
          "default": 3,
          "choices": [
            1,
            2,
            3,
            4,
            5
          ]
        },
        {
          "name": "threshold",
          "type": "float",
          "help": "Threshold value",
          "presence": "default",
          "default": 0.5,
          "choices": [
            0.1,
            0.5,
            0.9
          ]
        }
      ]
    },
    "info": {
      "name": "info",
      "help": "Show info",
      "effect": "read_only",
      "flags": [
        {
          "name": "format",
          "type": "str",
          "help": "Output format",
          "short": "f",
          "presence": "default",
          "default": "table"
        },
        {
          "name": "color-off",
          "type": "bool",
          "help": "Disable colors",
          "presence": "default",
          "default": false,
          "negatable": false
        },
        {
          "name": "strict-mode",
          "type": "bool",
          "help": "Strict mode",
          "presence": "default",
          "default": false,
          "conflict_mode": "error",
          "negatable": true
        }
      ]
    },
    "secret": {
      "name": "secret",
      "help": "Hidden maintenance command",
      "effect": "read_only",
      "hidden": true
    },
    "shell": {
      "name": "shell",
      "help": "Interactive shell",
      "effect": "read_only",
      "interactive": true
    },
    "serve": {
      "name": "serve",
      "help": "Start the server",
      "effect": "read_only",
      "config_fields": [
        "api.key",
        "listen_port"
      ]
    }
  },
  "groups": {
    "config": {
      "name": "config",
      "help": "Manage persistent configuration values stored in the config file",
      "commands": {
        "path": {
          "name": "path",
          "help": "Print the absolute path to this application's config file and nothing else, so the value can be piped straight into another command. The path is $XDG_CONFIG_HOME/<app>/config.<toml|json> (falling back to ~/.config), or the explicit override the application was built with. Printing it does not create the file, and reports the same path whether or not one exists yet.",
          "effect": "read_only",
          "forwarding": {
            "reason": "framework-internal: absorbs app-defined global flag values"
          }
        },
        "show": {
          "name": "show",
          "help": "Show every flag and config field with its effective value and where that value came from, resolved through the precedence chain environment variable, then config file, then declared default. Declared infrastructure roots, handshake and connection environment variables are listed too. Choose --plain for an aligned human-readable table; the framework-owned --json yields the same information as a machine-readable object carrying each entry's type, default and help text.",
          "effect": "read_only",
          "payload_schema": {
            "type": "object"
          },
          "flags": [
            {
              "name": "plain",
              "type": "bool",
              "help": "Display config values in a human-readable table format",
              "presence": "default",
              "default": false,
              "negatable": true
            }
          ],
          "forwarding": {
            "reason": "framework-internal: absorbs app-defined global flag values"
          }
        },
        "set": {
          "name": "set",
          "help": "Write a persistent value into the config file so it overrides a flag's declared default on every later run. The value is coerced to the flag's own type and rejected if it does not fit: repeatable flags take a comma-separated list (backslash-escape a literal comma) and are checked for duplicates, dict flags take a JSON object. Use --default to drop a key back to its default, and --clear to empty a repeatable flag.",
          "effect": "mutating",
          "flags": [
            {
              "name": "clear",
              "type": "bool",
              "help": "Clear a repeatable flag by setting its value to an empty list",
              "presence": "default",
              "default": false,
              "negatable": true
            },
            {
              "name": "default",
              "type": "bool",
              "help": "Reset a key to its default value by removing it from the config file",
              "presence": "default",
              "default": false,
              "negatable": true
            }
          ],
          "args": [
            {
              "name": "key",
              "help": "The config key to set, matching a registered flag name",
              "presence": "required"
            },
            {
              "name": "value",
              "help": "Value to set (comma-separated for repeatable flags, use backslash to escape commas)",
              "presence": "optional"
            }
          ],
          "forwarding": {
            "reason": "framework-internal: absorbs app-defined global flag values"
          }
        },
        "edit": {
          "name": "edit",
          "help": "Open this application's config file in the editor named by $EDITOR, falling back to vi. The parent directory and an empty config file are created first if they do not exist, so the editor always opens something. Launching the editor counts as a mutation: under --dry-run the command records the editor invocation and opens nothing.",
          "effect": "mutating",
          "interactive": true,
          "forwarding": {
            "reason": "framework-internal: absorbs app-defined global flag values"
          }
        },
        "init": {
          "name": "init",
          "help": "Create a starter config file listing every flag and config field the application declares, each commented with its help text, type and default value, so the file documents itself. The format follows whichever of TOML or JSON the application was built for. Refuses with an error if a config file already exists rather than overwriting it; the created path is printed on success.",
          "effect": "mutating",
          "forwarding": {
            "reason": "framework-internal: absorbs app-defined global flag values"
          }
        }
      }
    },
    "db": {
      "name": "db",
      "help": "Database operations",
      "commands": {
        "migrate": {
          "name": "migrate",
          "help": "Run migrations",
          "effect": "read_only",
          "flags": [
            {
              "name": "steps",
              "type": "int",
              "help": "Migration steps",
              "presence": "optional"
            }
          ],
          "tags": [
            "infra"
          ],
          "config_fields": [
            "listen_port"
          ]
        },
        "seed": {
          "name": "seed",
          "help": "Seed database",
          "effect": "read_only",
          "tags": [
            "infra"
          ]
        }
      },
      "groups": {
        "cache": {
          "name": "cache",
          "help": "Cache operations",
          "commands": {
            "clear": {
              "name": "clear",
              "help": "Clear cache",
              "effect": "read_only",
              "tags": [
                "infra"
              ]
            },
            "stats": {
              "name": "stats",
              "help": "Show cache stats",
              "effect": "read_only",
              "flags": [
                {
                  "name": "detailed",
                  "type": "bool",
                  "help": "Show detailed stats",
                  "presence": "required",
                  "negatable": true
                }
              ],
              "tags": [
                "infra"
              ]
            }
          }
        }
      },
      "deprecated": {
        "reset": "Use 'db migrate --steps -1' instead"
      },
      "tags": [
        "infra"
      ]
    }
  },
  "deprecated": {
    "old-cmd": "Use 'new-cmd' instead"
  },
  "tag_contracts": {
    "quality": "chatter"
  },
  "checks": {
    "lint-clean": {
      "tags": [
        "quality"
      ],
      "severity": "error",
      "fast": true,
      "pure": true,
      "needs_network": false,
      "depends_on": []
    },
    "db-ping": {
      "tags": [
        "infra"
      ],
      "severity": "warn",
      "fast": false,
      "pure": false,
      "needs_network": true,
      "depends_on": [
        "lint-clean"
      ],
      "scope": "db"
    }
  },
  "config_fields": {
    "api.key": {
      "type": "str",
      "help": "API key for the service",
      "required": true,
      "bound_commands": [
        "serve"
      ]
    },
    "listen_port": {
      "type": "int",
      "help": "Port to listen on",
      "required": false,
      "default": 8080,
      "bound_commands": [
        "serve",
        "db migrate"
      ]
    },
    "debug": {
      "type": "bool",
      "help": "Enable debug mode",
      "required": false,
      "default": false
    }
  },
  "infra": {
    "roots": [
      {
        "env_var": "RICH_HOME",
        "default": "/var/lib/richapp"
      }
    ],
    "handshakes": [
      {
        "env_var": "RICH_SESSION",
        "help": "Session token from the invoking process"
      }
    ]
  }
}`;

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
export function buildRichApp(): App {
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
			chatter: flag("chatter", t.bool, {
				help: "Enable chatter output",
				short: "V",
				presence: "default",
				default: false,
			}),
			log_level: flag("log-level", t.str, {
				help: "Logging level",
				presence: "default",
				default: "info",
				env: "RICH_LOG_LEVEL",
				choices: ["debug", "info", "warn", "error"],
			}),
			state_file: flag("state-file", t.str, {
				help: "State file relative to the infra root",
				presence: "default",
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
		defineReadOnlyCommand("types", {
			help: "Test all flag types",
			flags: {
				name: flag("name", t.str, {
					help: "A string flag",
					presence: "default",
					default: "world",
				}),
				count: flag("count", t.int, {
					help: "An integer flag",
					presence: "default",
					default: 42n,
				}),
				big: flag("big", t.int, {
					help: "A big integer flag",
					presence: "default",
					default: 9007199254740993n,
				}),
				ratio: flag("ratio", t.float, {
					help: "A float flag",
					presence: "default",
					default: 3.14,
				}),
				sim_run: flag("sim-run", t.bool, {
					help: "Dry run mode",
					presence: "required",
				}),
				cache_file: flag("cache-file", t.str, {
					help: "Cache file relative to the infra root",
					presence: "default",
					default: relativeToRoot("RICH_HOME", "cache.bin"),
				}),
			},
			args: [
				arg("target", t.str, {
					help: "Target to process",
					presence: "required",
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("multi", {
			help: "Test list and dict flags",
			flags: {
				tag: flag("tag", t.list(t.str), {
					help: "Tags to apply",
					unique: true,
					env: "RICH_TAGS",
					envSeparator: ",",
					presence: "default",
					default: [],
				}),
				port: flag("port", t.list(t.int), {
					help: "Ports to open",
					unique: false,
					presence: "default",
					default: [80n, 443n],
				}),
				// Insertion order beta-then-alpha; the schema must sort dict keys.
				matrix: flag("matrix", t.dict(t.int), {
					help: "Named weights",
					presence: "default",
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
		defineReadOnlyCommand("output", {
			help: "Test mutex flags",
			mutex: [
				mutexGroup({
					as_json: flag("as-json", t.bool, {
						help: "JSON output",
						presence: "optional",
					}),
					yaml: flag("yaml", t.bool, {
						help: "YAML output",
						presence: "optional",
					}),
					text: flag("text", t.bool, {
						help: "Text output",
						presence: "optional",
					}),
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("deploy", {
			help: "Test dependencies",
			flags: {
				host: flag("host", t.str, {
					help: "Deploy host",
					presence: "optional",
				}),
				port_num: flag("port-num", t.int, {
					help: "Deploy port",
					presence: "optional",
				}),
				ssl: flag("ssl", t.bool, { help: "Use SSL", presence: "required" }),
				cert: flag("cert", t.str, {
					help: "SSL certificate path",
					presence: "optional",
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
		defineReadOnlyCommand("notify", {
			help: "Test implies dependency",
			flags: {
				email: flag("email", t.bool, {
					help: "Send email notification",
					presence: "required",
				}),
				alert: flag("alert", t.bool, {
					help: "Enable alerts",
					presence: "required",
				}),
			},
			dependencies: [implies({ flag: "email", implies: "alert", value: true })],
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("query", {
			help: "Test flag sets",
			flagSets: [
				flagSet("pagination", {
					page: flag("page", t.int, {
						help: "Page number",
						presence: "default",
						default: 1n,
					}),
					per_page: flag("per-page", t.int, {
						help: "Items per page",
						presence: "default",
						default: 20n,
					}),
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("files", {
			help: "Test args",
			args: [
				arg("src", t.str, { help: "Source directory", presence: "required" }),
				arg("mode", t.str, {
					help: "Copy mode",
					presence: "default",
					default: "fast",
				}),
				arg("extra", t.str, {
					help: "Extra files",
					presence: "optional",
					variadic: true,
				}),
			],
			handler: () => 0,
		}),
	);

	app.command(
		readOnlyPassthrough("exec", {
			help: "Execute a command",
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("lint", {
			help: "Run linters",
			tags: ["quality", "ci"],
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("level", {
			help: "Test int/float choices",
			flags: {
				priority: flag("priority", t.int, {
					help: "Priority level",
					choices: [1n, 2n, 3n, 4n, 5n],
					presence: "default",
					default: 3n,
				}),
				threshold: flag("threshold", t.float, {
					help: "Threshold value",
					choices: [0.1, 0.5, 0.9],
					presence: "default",
					default: 0.5,
				}),
			},
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("info", {
			help: "Show info",
			flags: {
				format: flag("format", t.str, {
					help: "Output format",
					short: "f",
					presence: "default",
					default: "table",
				}),
				color_off: flag("color-off", t.bool, {
					help: "Disable colors",
					negatable: false,
					presence: "default",
					default: false,
				}),
				strict_mode: flag("strict-mode", t.bool, {
					help: "Strict mode",
					conflictMode: "error",
					presence: "default",
					default: false,
				}),
			},
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("secret", {
			help: "Hidden maintenance command",
			hidden: true,
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("shell", {
			help: "Interactive shell",
			interactive: true,
			handler: () => 0,
		}),
	);

	app.command(
		defineReadOnlyCommand("serve", {
			help: "Start the server",
			configFields: ["api.key", "listen_port"],
			handler: () => 0,
		}),
	);

	app.deprecate(deprecated("old-cmd", "Use 'new-cmd' instead"));
	app.tagContract("quality", "chatter");

	const db = app.group("db", { help: "Database operations", tags: ["infra"] });
	db.command(
		defineReadOnlyCommand("migrate", {
			help: "Run migrations",
			flags: {
				steps: flag("steps", t.int, {
					help: "Migration steps",
					presence: "optional",
				}),
			},
			configFields: ["listen_port"],
			handler: () => 0,
		}),
	);
	db.command(
		defineReadOnlyCommand("seed", { help: "Seed database", handler: () => 0 }),
	);
	db.deprecate(deprecated("reset", "Use 'db migrate --steps -1' instead"));

	const cache = db.group("cache", { help: "Cache operations" });
	cache.command(
		defineReadOnlyCommand("clear", { help: "Clear cache", handler: () => 0 }),
	);
	cache.command(
		defineReadOnlyCommand("stats", {
			help: "Show cache stats",
			flags: {
				detailed: flag("detailed", t.bool, {
					help: "Show detailed stats",
					presence: "required",
				}),
			},
			handler: () => 0,
		}),
	);

	return app;
}

function buildMinimalApp(): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("greet", { help: "say hello", handler: () => 0 }),
	);
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

// Contract §23.7: `default` is emitted exactly when presence is "default", and
// then ALWAYS -- including for the empty collections, which used to be the
// framework's own silent value and had nothing to announce. The Python and Go
// suites pin the same pair on their own dumps.
test("empty-collection defaults are emitted, not omitted", () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "t" });
	app.command(
		defineReadOnlyCommand("cmd", {
			help: "a command",
			flags: {
				tag: flag("tag", t.list(t.str), {
					help: "tags",
					presence: "default",
					default: [],
				}),
				header: flag("header", t.dict(t.str), {
					help: "headers",
					presence: "default",
					default: new Map(),
				}),
			},
			handler: () => 0,
		}),
	);
	const dumped = JSON.parse(schemaJson(app.dumpSchemaDict())) as {
		commands: {
			cmd: { flags: { name: string; presence: string; default: unknown }[] };
		};
	};
	const byName = (name: string) => {
		const f = dumped.commands.cmd.flags.find((e) => e.name === name);
		assert.ok(f, `flag ${name} missing from the dump`);
		return f;
	};
	assert.equal(byName("tag").presence, "default");
	assert.deepEqual(byName("tag").default, []);
	assert.equal(byName("header").presence, "default");
	assert.deepEqual(byName("header").default, {});
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

// --- The declared --dump-schema location ---

test("--dump-schema writes the declared relative path, not the default", async () => {
	await withTempCwd(async (dir) => {
		writeFileSync("package.json", '{"name": "myapp"}\n');
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "test app",
			schemaPath: join("build", "cli-schema.json"),
		});
		app.command(
			defineReadOnlyCommand("greet", { help: "say hello", handler: () => 0 }),
		);
		const res = await app.test(["--dump-schema"]);
		assert.equal(res.exitCode, 0);
		const want = join(dir, "build", "cli-schema.json");
		assert.equal(res.stdout, `${want}\n`);
		assert.ok(existsSync(want));
		assert.ok(!existsSync(join(dir, ".strictcli")));
	});
});

test("--dump-schema writes a declared relativeToRoot() location", async () => {
	await withTempCwd(async (dir) => {
		writeFileSync("package.json", '{"name": "myapp"}\n');
		const root = join(dir, "root");
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "test app",
			infraRoot: { MYAPP_HOME: root },
			schemaPath: relativeToRoot("MYAPP_HOME", "schema.json"),
		});
		app.command(
			defineReadOnlyCommand("greet", { help: "say hello", handler: () => 0 }),
		);
		assert.equal((await app.test(["--dump-schema"])).exitCode, 0);
		assert.ok(existsSync(join(root, "schema.json")));
	});
});

test("the default --dump-schema location is anchored at construction", async () => {
	await withTempCwd(async (dir) => {
		writeFileSync("package.json", '{"name": "myapp"}\n');
		const app = buildMinimalApp();
		const elsewhere = mkdtempSync(join(tmpdir(), "strictcli-elsewhere-"));
		// project_id is read from the cwd at dump time -- a separate cwd
		// dependency this test is not about, so both directories carry one.
		writeFileSync(join(elsewhere, "package.json"), '{"name": "myapp"}\n');
		const back = process.cwd();
		process.chdir(elsewhere);
		try {
			assert.equal((await app.test(["--dump-schema"])).exitCode, 0);
		} finally {
			process.chdir(back);
		}
		assert.ok(existsSync(join(dir, ".strictcli", "schema.json")));
		assert.ok(!existsSync(join(elsewhere, ".strictcli")));
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

// --- The presence key (contract §13's presence-round amendment) ---

test("schema: presence is on every flag and arg entry, always", () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("cmd", {
			help: "a command",
			args: [
				arg("src", t.str, { help: "source", presence: "required" }),
				arg("dest", t.str, { help: "destination", presence: "optional" }),
				arg("mode", t.str, {
					help: "mode",
					presence: "default",
					default: "fast",
				}),
			],
			flags: {
				target: flag("target", t.str, {
					help: "the target",
					presence: "required",
				}),
				host: flag("host", t.str, { help: "the host", presence: "optional" }),
				tag: flag("tag", t.list(t.str), {
					help: "tags",
					presence: "default",
					default: [],
				}),
				meta: flag("meta", t.dict(t.int), {
					help: "metadata",
					presence: "default",
					default: new Map(),
				}),
				label: flag("label", t.str, {
					help: "a label",
					presence: "default",
					default: "",
				}),
				chatter: flag("chatter", t.bool, {
					help: "chatter",
					presence: "default",
					default: false,
				}),
			},
			handler: () => 0,
		}),
	);
	const dict = app.dumpSchemaDict() as Record<string, unknown> & {
		commands: Record<string, unknown>;
	};
	const cmd = dict.commands.cmd as {
		flags: Record<string, unknown>[];
		args: Record<string, unknown>[];
	};
	const byName = new Map(cmd.flags.map((f) => [f.name as string, f]));
	assert.equal(byName.get("target")?.presence, "required");
	assert.ok(!("default" in (byName.get("target") ?? {})));
	assert.equal(byName.get("host")?.presence, "optional");
	assert.ok(!("default" in (byName.get("host") ?? {})));
	// A declared default is emitted ALWAYS, whatever the value: [], {}, "",
	// false and 0 are declarations rather than the absence of one.
	assert.deepEqual(byName.get("tag")?.default, []);
	assert.deepEqual(byName.get("meta")?.default, new Map());
	assert.equal(byName.get("label")?.default, "");
	assert.equal(byName.get("chatter")?.default, false);

	const args = new Map(cmd.args.map((a) => [a.name as string, a]));
	assert.equal(args.get("src")?.presence, "required");
	assert.equal(args.get("dest")?.presence, "optional");
	assert.equal(args.get("mode")?.presence, "default");
	assert.equal(args.get("mode")?.default, "fast");
	// The arg entry's `required` key is deleted, here and in the defaults block.
	for (const a of cmd.args) {
		assert.ok(!("required" in a));
	}
	const defaults = dict.defaults as { arg: Record<string, unknown> };
	assert.ok(!("required" in defaults.arg));
});
