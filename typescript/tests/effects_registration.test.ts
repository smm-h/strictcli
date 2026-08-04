/**
 * Registration-time enforcement of the effects regime: the reserved flag
 * quartet's unconditional name ban, mandatory classification through the twin
 * factories, grant and forwarding declarations, and the framework-internal
 * marker's module verification.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	type AppImpl,
	createApp,
	defineFrameworkCommand,
	FRAMEWORK_INTERNAL_FORWARDING_REASON,
	markFrameworkHandler,
} from "../src/app.js";
import { RegistrationError } from "../src/errors.js";
import type { AnyCommand } from "../src/factories.js";
import {
	arg,
	defineMutatingCommand,
	defineReadOnlyCommand,
	deprecated,
	flag,
	flagSet,
	mutatingPassthrough,
	mutexGroup,
	readOnlyPassthrough,
	t,
} from "../src/index.js";

const RESERVED = ["dry-run", "approve-consequential", "quiet", "verbose"];

function reservedMessage(name: string): string {
	return `flag name '${name}' is reserved by the framework (dry-run, approve-consequential, quiet, verbose)`;
}

// `yes` owns no framework flag any more, but it stays banned so nobody
// reintroduces a private --yes meaning the same thing (§12.1).
const YES_BAN_MESSAGE =
	"flag name 'yes' is banned by the framework: the confirmation skip is --approve-consequential";

// --- §7.1 the unconditional name ban ---

test("reserved quartet: flag() refuses each reserved name", () => {
	for (const name of RESERVED) {
		assert.throws(() => flag(name, t.bool, { help: "h", default: false }), {
			name: "RegistrationError",
			message: reservedMessage(name),
		});
	}
});

test("reserved names: `yes` is banned outright", () => {
	assert.throws(() => flag("yes", t.bool, { help: "h", default: false }), {
		name: "RegistrationError",
		message: YES_BAN_MESSAGE,
	});
	assert.throws(
		() =>
			createApp({
				name: "t",
				version: "1",
				help: "h",
				flags: { yes: flag("yes", t.bool, { help: "h", default: false }) },
			}),
		{ message: YES_BAN_MESSAGE },
	);
});

test("reserved quartet: the ban applies at every level, not just globals", () => {
	// Command flags, flag-set flags and mutex-group flags all go through the
	// same flag() factory, so the ban is unconditional by construction.
	for (const name of RESERVED) {
		assert.throws(() => flag(name, t.bool, { help: "h", default: false }));
	}
	// A flag set and a mutex group cannot even be built with one.
	assert.throws(() =>
		flagSet("common", {
			quiet: flag("quiet", t.bool, { help: "h", default: false }),
		}),
	);
	assert.throws(() =>
		mutexGroup({
			yes: flag("yes", t.bool, { help: "h", default: false }),
			no_thanks: flag("no-thanks", t.bool, { help: "h", default: false }),
		}),
	);
});

test("reserved quartet: the global-flag path carries the same message", () => {
	// flag() bans the name first, so the global path is reached only by an
	// untyped caller forging a descriptor.
	const forged = {
		kind: "flag" as const,
		name: "verbose",
		schema: "bool" as const,
		carrier: t.bool,
		opts: { help: "h", default: false },
	};
	assert.throws(
		() =>
			createApp({
				name: "t",
				version: "1",
				help: "h",
				flags: { verbose: forged },
			}),
		{ message: reservedMessage("verbose") },
	);
});

test("reserved quartet: --output is explicitly NOT reserved", () => {
	assert.doesNotThrow(() =>
		flag("output", t.str, { help: "where to write", default: "-" }),
	);
});

test("reserved quartet: short names are unaffected by the ban", () => {
	assert.doesNotThrow(() =>
		flag("quietly", t.bool, { help: "h", short: "q", default: false }),
	);
});

test("reserved quartet: arg names are unaffected (an arg has no -- spelling)", () => {
	assert.doesNotThrow(() => arg("verbose", t.str, { help: "h" }));
});

// --- §1.1 mandatory classification ---

test("classification: the twin factories splice in the effect", () => {
	assert.equal(
		defineReadOnlyCommand("a", { help: "h", handler: () => 0 }).effect,
		"read_only",
	);
	assert.equal(
		defineMutatingCommand("b", { help: "h", handler: () => 0 }).effect,
		"mutating",
	);
	assert.equal(
		readOnlyPassthrough("c", { help: "h", handler: () => 0 }).effect,
		"read_only",
	);
	assert.equal(
		mutatingPassthrough("d", { help: "h", handler: () => 0 }).effect,
		"mutating",
	);
});

test("classification: a carrier with no effect is a registration error", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	const forged = {
		...defineReadOnlyCommand("x", { help: "h", handler: () => 0 }),
		effect: undefined,
	} as unknown as AnyCommand;
	assert.throws(() => app.command(forged), {
		name: "RegistrationError",
		message:
			'command "x": effect classification is required (effect="read_only" or effect="mutating")',
	});
});

test("classification: an invalid effect is a registration error", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	const forged = {
		...defineReadOnlyCommand("x", { help: "h", handler: () => 0 }),
		effect: "maybe",
	} as unknown as AnyCommand;
	assert.throws(() => app.command(forged), {
		name: "RegistrationError",
		message:
			'command "x": invalid effect "maybe": must be "read_only" or "mutating"',
	});
});

test("classification: deprecated commands are exempt, and carrying one errors", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	// The exempt path: no effect, no error.
	assert.doesNotThrow(() => app.deprecate(deprecated("old", "gone")));
	const forged = {
		...deprecated("older", "gone"),
		effect: "read_only",
	} as unknown as ReturnType<typeof deprecated>;
	assert.throws(() => app.deprecate(forged), {
		name: "RegistrationError",
		message:
			'deprecated command "older": effect classification does not apply (a deprecated command has no handler)',
	});
});

test("classification: deprecated entries stay out of the command schema", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.deprecate(deprecated("old", "gone"));
	const schema = app.dumpSchemaDict();
	assert.deepEqual(schema.deprecated, { old: "gone" });
	assert.equal(schema.commands, undefined);
});

// --- §6.1 grant declarations ---

test("grants: names must match [a-z][a-z0-9-]*", () => {
	assert.throws(
		() =>
			defineMutatingCommand("go", {
				help: "h",
				grants: [{ name: "Push", reason: "r", kind: "proc_mutate" }],
				handler: () => 0,
			}),
		{
			message:
				"command \"go\": invalid grant name 'Push': must match [a-z][a-z0-9-]*",
		},
	);
});

test("grants: duplicate names are rejected", () => {
	assert.throws(
		() =>
			defineMutatingCommand("go", {
				help: "h",
				grants: [
					{ name: "push", reason: "r", kind: "proc_mutate" },
					{ name: "push", reason: "r2", kind: "net_mutate" },
				],
				handler: () => 0,
			}),
		{ message: "command \"go\": duplicate grant 'push'" },
	);
});

test("grants: the reason is mandatory and non-empty", () => {
	assert.throws(
		() =>
			defineMutatingCommand("go", {
				help: "h",
				grants: [{ name: "push", reason: "  ", kind: "proc_mutate" }],
				handler: () => 0,
			}),
		{
			message: "command \"go\": grant 'push' reason must be a non-empty string",
		},
	);
});

test("grants: the kind must be one of the four grantable kinds", () => {
	assert.throws(
		() =>
			defineMutatingCommand("go", {
				help: "h",
				grants: [
					{
						name: "push",
						reason: "r",
						kind: "cache_write" as never,
					},
				],
				handler: () => 0,
			}),
		{
			message:
				"command \"go\": grant 'push' has invalid kind 'cache_write': must be one of proc_mutate, proc_spawn, file_write, net_mutate",
		},
	);
});

test("grants: a passthrough may declare them too", () => {
	const def = mutatingPassthrough("exec", {
		help: "h",
		grants: [
			{ name: "run-any", reason: "opaque by design", kind: "proc_mutate" },
		],
		handler: () => 0,
	});
	assert.equal(def.grants.length, 1);
});

// --- §10.2 declared forwarding ---

test("forwarding: the reason is mandatory and non-empty", () => {
	assert.throws(
		() =>
			defineReadOnlyCommand("go", {
				help: "h",
				forwarding: { reason: "" },
				handler: () => 0,
			}),
		{ message: 'command "go": forwarding reason must be a non-empty string' },
	);
});

test("forwarding: a declared reason reaches the schema", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	app.command(
		defineReadOnlyCommand("wrap", {
			help: "h",
			forwarding: { reason: "wraps another CLI" },
			handler: () => 0,
		}),
	);
	const commands = app.dumpSchemaDict().commands as Record<
		string,
		Record<string, unknown>
	>;
	assert.deepEqual(commands.wrap?.forwarding, { reason: "wraps another CLI" });
});

// --- §10.4 the framework-internal marker and its module verification ---

test("framework-internal: the six auto-registered commands declare forwarding", () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		config: true,
		checksEmbed: 'app = "t"\n',
	});
	const schema = app.dumpSchemaDict();
	const commands = schema.commands as Record<string, Record<string, unknown>>;
	assert.deepEqual(commands.check?.forwarding, {
		reason: FRAMEWORK_INTERNAL_FORWARDING_REASON,
	});
	const groups = schema.groups as Record<string, Record<string, unknown>>;
	const cfg = (groups.config as Record<string, unknown>).commands as Record<
		string,
		Record<string, unknown>
	>;
	for (const name of ["path", "show", "set", "edit", "init"]) {
		assert.deepEqual(
			cfg[name]?.forwarding,
			{ reason: FRAMEWORK_INTERNAL_FORWARDING_REASON },
			name,
		);
	}
});

test("framework-internal: the five config subcommands carry §9.2's classifications", () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		config: true,
	});
	const groups = app.dumpSchemaDict().groups as Record<
		string,
		Record<string, unknown>
	>;
	const cfg = (groups.config as Record<string, unknown>).commands as Record<
		string,
		Record<string, unknown>
	>;
	assert.equal(cfg.show?.effect, "read_only");
	assert.equal(cfg.path?.effect, "read_only");
	assert.equal(cfg.set?.effect, "mutating");
	assert.equal(cfg.init?.effect, "mutating");
	assert.equal(cfg.edit?.effect, "mutating");
});

test("framework-internal: `check` classifies read_only", () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: 'app = "t"\n',
	});
	const commands = app.dumpSchemaDict().commands as Record<
		string,
		Record<string, unknown>
	>;
	assert.equal(commands.check?.effect, "read_only");
});

test("framework-internal: the marker is not emitted in the schema", () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		checksEmbed: 'app = "t"\n',
	});
	const commands = app.dumpSchemaDict().commands as Record<
		string,
		Record<string, unknown>
	>;
	assert.ok(!("frameworkInternal" in (commands.check as object)));
});

test("framework-internal: a FOREIGN handler carrying the marker fails registration", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	// defineFrameworkCommand is package-internal, but a consumer reaching it by
	// any route -- monkey-patching, prototype tampering, reflection -- gets a
	// carrier whose handler is NOT in the framework WeakSet.
	const foreign = defineFrameworkCommand("sneaky", "mutating", {
		help: "h",
		handler: (() => 0) as never,
	});
	assert.throws(() => app.command(foreign), {
		name: "RegistrationError",
		message:
			'command "sneaky": handler is marked framework-internal but is not defined in the strictcli module',
	});
});

test("framework-internal: a marked handler registers cleanly", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	const ours = defineFrameworkCommand("blessed", "read_only", {
		help: "h",
		handler: markFrameworkHandler(() => 0) as never,
	});
	assert.doesNotThrow(() => app.command(ours));
});

test("framework-internal: verification keys on identity, not on the name", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	const blessed = markFrameworkHandler(function checkHandler() {
		return 0;
	});
	// A DIFFERENT function with the same `name` is not the blessed identity.
	const impostor = { checkHandler: () => 0 }.checkHandler;
	assert.equal(impostor.name, blessed.name);
	assert.throws(
		() =>
			app.command(
				defineFrameworkCommand("x", "read_only", {
					help: "h",
					handler: impostor as never,
				}),
			),
		{ message: /is not defined in the strictcli module/ },
	);
});

test("framework-internal: the marker is unreachable from the public spec", () => {
	// There is no `frameworkInternal` key in any options object: passing one
	// through the public factory is dropped, so the carrier is unmarked and the
	// verification never fires.
	const def = defineReadOnlyCommand("x", {
		help: "h",
		handler: () => 0,
		...({ frameworkInternal: true } as object),
	} as never);
	assert.ok(!("frameworkInternal" in (def as object)));
});

// --- §7.5 check-command subsumption ---

test("check subsumption: the app-level allowlist reaches the schema", () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		procObserveAllowlist: [
			["git", "status"],
			["gh", "release", "view"],
		],
	});
	assert.deepEqual(app.dumpSchemaDict().proc_observe_allowlist, [
		["git", "status"],
		["gh", "release", "view"],
	]);
});

test("check subsumption: an empty allowlist is omitted from the schema", () => {
	const app = createApp({ name: "t", version: "1", help: "h" });
	assert.ok(!("proc_observe_allowlist" in app.dumpSchemaDict()));
});

test("allowlist: entries must be non-empty lists of strings", () => {
	assert.throws(
		() =>
			createApp({
				name: "t",
				version: "1",
				help: "h",
				procObserveAllowlist: [[]],
			}),
		{ message: "proc_observe_allowlist entries must not be empty" },
	);
	assert.throws(
		() =>
			createApp({
				name: "t",
				version: "1",
				help: "h",
				procObserveAllowlist: [[1 as never]],
			}),
		{
			message:
				"proc_observe_allowlist entries must be lists of strings, got number",
		},
	);
});

// --- The single validated registration path (§10.4) ---

test("registration: framework commands go through the same validated path", () => {
	const app = createApp({
		name: "t",
		version: "1",
		help: "h",
		config: true,
		checksEmbed: 'app = "t"\n',
	}) as unknown as AppImpl;
	// Every registered command -- consumer or framework -- lands in the same
	// RegisteredCommand map with a classified carrier.
	const cmd = app.commands.get("check");
	assert.ok(cmd !== undefined);
	assert.equal((cmd.def as AnyCommand).effect, "read_only");
	const cfg = app.groups.get("config");
	assert.ok(cfg !== undefined);
	for (const [, rc] of cfg.commands) {
		assert.ok(
			["read_only", "mutating"].includes((rc.def as AnyCommand).effect),
		);
	}
});

test("registration: RegistrationError is the thrown type for every ban", () => {
	assert.throws(
		() => flag("quiet", t.bool, { help: "h", default: false }),
		RegistrationError,
	);
});
