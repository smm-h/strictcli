/**
 * Connection-env primitive tests: app-level declaration, lazy read, hermetic
 * suppression, check-side access (ConnectionEnvReader), registration-time
 * enforcement, and precedence (cli > env). Parity with the Go and Python
 * connection-env tests.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { CheckContext, ConnectionEnvReader } from "../src/index.js";
import { createApp, defineCommand, flag, t } from "../src/index.js";
import { dumpSchemaCore } from "../src/schema.js";

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

function connApp() {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "conn" },
	});
	app.command(
		defineCommand("run", {
			help: "run it",
			flags: {
				dsn: flag("dsn", t.str, {
					help: "connection string",
					default: null,
					connectionUrl: true,
					connectionEnv: "DATABASE_URL",
				}),
			},
			handler: (args, ctx) => {
				ctx.info(`${ctx.source("dsn")}:${args.dsn}`);
				return 0;
			},
		}),
	);
	return app;
}

// --- Declaration + help + schema ---

test("connection: help renders the suppressed-by-hermetic line", async () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "Postgres connection string" },
	});
	app.command(defineCommand("run", { help: "run it", handler: () => 0 }));
	const r = await app.test(["--help"]);
	assert.ok(r.stdout.includes("Infrastructure:"));
	assert.ok(
		r.stdout.includes(
			"connection URL, suppressed by --hermetic (Postgres connection string)",
		),
		r.stdout,
	);
});

test("connection: schema dump lists connections", () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "Postgres connection string" },
	});
	const schema = dumpSchemaCore(app as never) as {
		infra: { connections: unknown[] };
	};
	assert.deepEqual(schema.infra.connections, [
		{ env_var: "DATABASE_URL", help: "Postgres connection string" },
	]);
});

// --- Lazy read + precedence (cli > env) + hermetic ---

test("connection: lazy read from env, source is 'env'", async () => {
	await withEnv({ DATABASE_URL: "postgres://from-env/db" }, async () => {
		const r = await connApp().test(["run"]);
		assert.equal(r.exitCode, 0, r.stderr);
		assert.equal(r.stdout, "env:postgres://from-env/db\n");
	});
});

test("connection: CLI beats env, source is 'cli'", async () => {
	await withEnv({ DATABASE_URL: "postgres://from-env/db" }, async () => {
		const r = await connApp().test(["run", "--dsn", "postgres://from-cli/db"]);
		assert.equal(r.exitCode, 0, r.stderr);
		assert.equal(r.stdout, "cli:postgres://from-cli/db\n");
	});
});

test("connection: hermetic suppresses the env read", async () => {
	await withEnv({ DATABASE_URL: "postgres://from-env/db" }, async () => {
		const r = await connApp().test(["--hermetic", "run"]);
		assert.equal(r.exitCode, 0, r.stderr);
		assert.ok(!r.stdout.includes("env:postgres://from-env/db"), r.stdout);
	});
});

// --- Handler-side infraValue / connectionEnvValue ---

test("connection: infraValue and connectionEnvValue resolve live", async () => {
	await withEnv({ DATABASE_URL: "postgres://live/db" }, async () => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			connectionEnv: { DATABASE_URL: "conn" },
		});
		app.command(
			defineCommand("run", {
				help: "run",
				handler: (_args, ctx) => {
					const [cv, cs] = ctx.connectionEnvValue("DATABASE_URL");
					const [iv, is] = ctx.infraValue("DATABASE_URL");
					ctx.info(`${cv}:${cs}:${iv}:${is}`);
					return 0;
				},
			}),
		);
		const r = await app.test(["run"]);
		assert.equal(r.stdout, "postgres://live/db:true:postgres://live/db:true\n");
	});
});

test("connection: hermetic makes connectionEnvValue absent", async () => {
	await withEnv({ DATABASE_URL: "postgres://live/db" }, async () => {
		const app = createApp({
			name: "myapp",
			version: "1.0.0",
			help: "t",
			connectionEnv: { DATABASE_URL: "conn" },
		});
		app.command(
			defineCommand("run", {
				help: "run",
				handler: (_args, ctx) => {
					const [cv, cs] = ctx.connectionEnvValue("DATABASE_URL");
					ctx.info(`${cv}:${cs}`);
					return 0;
				},
			}),
		);
		const r = await app.test(["--hermetic", "run"]);
		assert.equal(r.stdout, "undefined:false\n");
	});
});

// --- Check-side access via ConnectionEnvReader ---

function connCheckApp() {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "conn" },
		checksEmbed: `app = "myapp"
[checks.db-reachable]
tags = ["db"]
severity = "error"
fast = true
pure = false
needs_network = true
depends_on = []
`,
	});
	app.errorCheck("db-reachable", (ctx, r) => {
		const [dsn, present] = (
			ctx as unknown as ConnectionEnvReader
		).connectionEnvValue("DATABASE_URL");
		if (!present) {
			return r.skipped("DATABASE_URL absent (hermetic or unset)");
		}
		r.note(`dsn=${dsn}`);
		return r.passed("connection env visible");
	});
	const ctx: CheckContext = { projectRoot: "." };
	app.setCheckContext(() => ctx);
	return app;
}

test("connection: check reads the connection env", async () => {
	await withEnv({ DATABASE_URL: "postgres://check/db" }, async () => {
		const r = await connCheckApp().test(["check", "--tag", "db", "--verbose"]);
		assert.ok(r.stdout.includes("dsn=postgres://check/db"), r.stdout);
		assert.ok(r.stdout.includes("PASS"), r.stdout);
	});
});

test("connection: check skips under hermetic", async () => {
	await withEnv({ DATABASE_URL: "postgres://check/db" }, async () => {
		const r = await connCheckApp().test(["--hermetic", "check", "--tag", "db"]);
		assert.ok(r.stdout.includes("SKIP"), r.stdout);
		assert.ok(!r.stdout.includes("dsn="), r.stdout);
	});
});

// --- Registration-time enforcement ---

test("connection: URL-class flag with no binding is a registration error", () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "conn" },
	});
	assert.throws(
		() =>
			app.command(
				defineCommand("run", {
					help: "run",
					flags: {
						dsn: flag("dsn", t.str, {
							help: "dsn",
							default: null,
							connectionUrl: true,
						}),
					},
					handler: () => 0,
				}),
			),
		/must bind to a declared connection env/,
	);
});

test("connection: binding to an undeclared connection env is a registration error", () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "conn" },
	});
	assert.throws(
		() =>
			app.command(
				defineCommand("run", {
					help: "run",
					flags: {
						dsn: flag("dsn", t.str, {
							help: "dsn",
							default: null,
							connectionUrl: true,
							connectionEnv: "OTHER_URL",
						}),
					},
					handler: () => 0,
				}),
			),
		/undeclared connection env/,
	);
});

test("connection: binding without the URL marker is a registration error", () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "conn" },
	});
	assert.throws(
		() =>
			app.command(
				defineCommand("run", {
					help: "run",
					flags: {
						dsn: flag("dsn", t.str, {
							help: "dsn",
							default: null,
							connectionEnv: "DATABASE_URL",
						}),
					},
					handler: () => 0,
				}),
			),
		/requires the flag to be marked as a connection-URL flag/,
	);
});

test("connection: binding plus per-flag env is a registration error", () => {
	const app = createApp({
		name: "myapp",
		version: "1.0.0",
		help: "t",
		connectionEnv: { DATABASE_URL: "conn" },
	});
	assert.throws(
		() =>
			app.command(
				defineCommand("run", {
					help: "run",
					flags: {
						dsn: flag("dsn", t.str, {
							help: "dsn",
							default: null,
							env: "SOMETHING_ELSE",
							connectionUrl: true,
							connectionEnv: "DATABASE_URL",
						}),
					},
					handler: () => 0,
				}),
			),
		/cannot be combined with a per-flag env var/,
	);
});

test("connection: empty help is a registration error", () => {
	assert.throws(
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				connectionEnv: { DATABASE_URL: "" },
			}),
		/help must be a non-empty string/,
	);
});

test("connection: colliding with a root is a registration error", () => {
	assert.throws(
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				infraRoot: { SHARED: "/var/lib" },
				connectionEnv: { SHARED: "conn" },
			}),
		/already declared as an infra root/,
	);
});

test("connection: colliding with a handshake is a registration error", () => {
	assert.throws(
		() =>
			createApp({
				name: "myapp",
				version: "1.0.0",
				help: "t",
				handshakeEnv: { SHARED: "handshake" },
				connectionEnv: { SHARED: "conn" },
			}),
		/already declared as a handshake env var/,
	);
});
