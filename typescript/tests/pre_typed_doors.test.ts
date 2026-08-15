/**
 * The two programmatic front doors and the phases they run (contract §24.11,
 * §24.3, §23.4). Mirrors go/strictcli/flat_pre_typed_test.go.
 *
 *   - A positional arg is a declaration exactly as a flag is: a value supplied
 *     for one is CHECKED against the type it declares and never stringified
 *     into a token the caller did not write.
 *   - Both doors are one parser. `call()` takes the elected record and the flat
 *     machine form takes the choice name and the scoped keys, but the phases
 *     are the parser's: every selector's election is settled command-wide, then
 *     scope, then values, then presence, with the lowest stage over the whole
 *     command deciding what is reported -- so the two doors answer the same
 *     states with the same sentence.
 *   - A required bool inside a scope takes the ROOT sentence plus the scope
 *     suffix: the suffix says where the requirement lives and follows a
 *     complete sentence (§12.13).
 *   - The key namespace is the underscored parameter one both doors publish, so
 *     a dash-spelled key names nothing the command declares.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
	type App,
	arg,
	choice,
	choiceFlag,
	createApp,
	defineReadOnlyCommand,
	flag,
	memberChoiceFlag,
	type Tool,
	t,
} from "../src/index.js";

function errOut(msg: string, prefix = "myapp"): string {
	return `error: ${msg}\ntry '${prefix} --help'\n`;
}

/** The refusal one call produced, or a failure when the call was accepted. */
async function refusal(p: Promise<unknown>): Promise<string> {
	try {
		await p;
	} catch (e) {
		return (e as Error).message;
	}
	throw new Error("the call was accepted; want a refusal");
}

function toolFor(app: App, name: string): Tool {
	const found = app.asTools().find((tool) => tool.name === name);
	assert.ok(found, `no tool named ${name}`);
	return found;
}

// --- Positional args are declarations too (§24.11, no stringification) ---

/**
 * One command of each positional shape: two fixed args of different types, and
 * (in variadicApp) a variadic one whose elements are checked one by one.
 */
function argApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			args: [
				arg("target", t.str, { help: "what to run", presence: "required" }),
				arg("amount", t.int, { help: "how many", presence: "optional" }),
			],
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, { target: args.target, amount: args.amount });
				}
				return 0;
			},
		}),
	);
	return app;
}

function variadicApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			args: [
				arg("nums", t.int, {
					help: "some numbers",
					presence: "optional",
					variadic: true,
				}),
			],
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, { nums: args.nums });
				}
				return 0;
			},
		}),
	);
	return app;
}

test("call: a positional arg is checked against its declaration", async () => {
	assert.equal(
		await refusal(argApp().call("run", { target: 5 })),
		"argument 'target': expected string, got int",
	);
	assert.equal(
		await refusal(argApp().call("run", { target: null })),
		"argument 'target': expected string, got null",
	);
	assert.equal(
		await refusal(argApp().call("run", { target: "t", amount: "7" })),
		"argument 'amount': expected integer, got str",
	);
	assert.equal(
		await refusal(argApp().call("run", { target: "t", amount: true })),
		"argument 'amount': expected integer, got bool",
	);
	assert.equal(
		await refusal(argApp().call("run", { target: "t", amount: 1.5 })),
		"argument 'amount': expected integer, got float",
	);
});

test("call: a positional arg takes the declared type, absent stays absent", async () => {
	const captured: Record<string, unknown> = {};
	await argApp(captured).call("run", { target: "t", amount: 3 });
	assert.equal(captured.target, "t");
	// JSON has no bigint: the integer is converted INTO the declared type.
	assert.equal(captured.amount, 3n);

	const bare: Record<string, unknown> = {};
	await argApp(bare).call("run", { target: "t" });
	assert.ok("amount" in bare);
	assert.equal(bare.amount, undefined);
});

test("call: a variadic arg checks every element it was given", async () => {
	assert.equal(
		await refusal(variadicApp().call("run", { nums: [1, "2"] })),
		"argument 'nums': expected integer, got str",
	);
	const captured: Record<string, unknown> = {};
	await variadicApp(captured).call("run", { nums: [1, 2] });
	assert.deepEqual(captured.nums, [1n, 2n]);
});

test("call: a missing required flag still outranks a positional refusal", async () => {
	// The command line refuses in that order too: an arg token is coerced after
	// every flag has resolved from its own declaration.
	const build = (): App => {
		const app = createApp({ name: "myapp", version: "1.0.0", help: "app" });
		app.command(
			defineReadOnlyCommand("run", {
				help: "run it",
				flags: {
					need: flag("need", t.str, { help: "needed", presence: "required" }),
				},
				args: [arg("count", t.int, { help: "how many", presence: "required" })],
				handler: () => 0,
			}),
		);
		return app;
	};
	assert.equal(
		(await build().test(["run", "nope"])).stderr,
		errOut("flag '--need' is required", "myapp run"),
	);
	assert.equal(
		await refusal(build().call("run", { count: "nope" })),
		"flag '--need' is required",
	);
});

// --- The record door stages its phases command-wide (§18.22 item 232) ---

/**
 * Two selectors, so one selector's record can carry a problem while the other
 * is left unelected -- the state that tells the phases apart. `mode` is
 * declared first, which is what decides ties within one stage.
 */
function twoSelectorApp(): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				mode: memberChoiceFlag(
					"mode",
					{
						fast: choice({ help: "quickly" }),
						slow: choice({ help: "safely" }),
					},
					{ help: "how to run", presence: "required" },
				),
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one named profile",
							value: { carrier: t.str, help: "the profile name" },
							flags: {
								depth: flag("depth", t.int, {
									help: "how deep",
									presence: "optional",
								}),
							},
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to run", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	return app;
}

const missingModeElection = "one of --fast, --slow is required";

test("call: a value refusal outranks a missing election, at both doors", async () => {
	// The pre-typed value check IS the value phase (§24.11 item 240), and
	// presence is the phase after it, so a wrong-typed payload or scoped value
	// is what a caller hears -- the command line answers the same way, where a
	// bad scoped token beats an election that never happened.
	const badPayload = "--profile: expected string, got int";
	const badScoped = "--depth: expected integer, got str";
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				target: { choice: "profile", value: 123 },
			}),
		),
		badPayload,
	);
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				target: { choice: "profile", value: "work", depth: "deep" },
			}),
		),
		badScoped,
	);
	// The flat door answers the same states identically -- one parser, two
	// spellings of the same object.
	assert.equal(
		await refusal(toolFor(twoSelectorApp(), "run").execute({ profile: 123 })),
		badPayload,
	);
	assert.equal(
		await refusal(
			toolFor(twoSelectorApp(), "run").execute({
				profile: "work",
				depth: "deep",
			}),
		),
		badScoped,
	);
	// And with nothing to refuse, the missing election is what is left.
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				target: { choice: "profile", value: "work" },
			}),
		),
		missingModeElection,
	);
	assert.equal(
		await refusal(
			toolFor(twoSelectorApp(), "run").execute({ profile: "work" }),
		),
		missingModeElection,
	);
});

test("call: a record's shape outranks every phase fact beside it", async () => {
	// An invalid tag is a fact about the record, not an election: there is
	// nothing to elect from.
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				mode: { choice: "nope" },
				target: { choice: "profile", value: 123 },
			}),
		),
		"--mode: invalid value 'nope', must be one of: fast, slow",
	);
	// Electing a payload-carrying member with no `value` is the member's own
	// token with nothing after it, and outranks the missing election beside it.
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", { target: { choice: "profile" } }),
		),
		"flag '--profile' requires a value",
	);
	// A key the elected scope never declared is the scope question one level
	// down, which also outranks a missing election.
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				target: { choice: "profile", value: "work", bogus: 1 },
			}),
		),
		"flag '--bogus' is only valid under '--profile', but that scope does not declare it",
	);
	// A value that is not a record at all cannot carry a tag.
	assert.equal(
		await refusal(twoSelectorApp().call("run", { target: "profile" })),
		"flag '--target': the elected value must be a record carrying its 'choice' tag",
	);
});

/**
 * A token-spelled selector declared BEFORE a member-spelled one, so the first
 * selector's record can carry a problem of each stage while the second's names
 * an undeclared choice -- the election refusal that must be heard over all of
 * them.
 */
function stagedSelectorApp(): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "an email message",
							flags: {
								retries: flag("retries", t.int, {
									help: "how many",
									presence: "required",
								}),
							},
						}),
						sms: choice({
							help: "a text message",
							flags: {
								phone_number: flag("phone-number", t.str, {
									help: "the destination",
									presence: "required",
								}),
							},
						}),
					},
					{ help: "delivery channel", presence: "required" },
				),
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one named profile",
							value: { carrier: t.str, help: "the profile name" },
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to run", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	return app;
}

test("call: a later selector's election beats every stage below it", async () => {
	// The stage table decides across the WHOLE command, so the second
	// selector's election refusal is heard over a value, a presence and a scope
	// problem in the first selector's record alike.
	const badTag = { choice: "other" };
	const want =
		"--target: invalid value 'other', must be one of: profile, all-profiles";
	assert.equal(
		await refusal(
			stagedSelectorApp().call("run", {
				via: { choice: "email", retries: "nope" },
				target: badTag,
			}),
		),
		want,
	);
	assert.equal(
		await refusal(
			stagedSelectorApp().call("run", {
				via: { choice: "email" },
				target: badTag,
			}),
		),
		want,
	);
	assert.equal(
		await refusal(
			stagedSelectorApp().call("run", {
				via: { choice: "email", retries: 1, phone_number: "x" },
				target: badTag,
			}),
		),
		want,
	);
});

test("call: the value sweep runs in declaration order, not key order", async () => {
	// An object has no order of its own, so the order the caller happened to
	// write its keys in decides nothing: `mode` is declared first, so its
	// record's problem is the one reported either way.
	const bad = {
		mode: { choice: "nope" },
		target: { choice: "profile", value: 123 },
	};
	const want = "--mode: invalid value 'nope', must be one of: fast, slow";
	assert.equal(await refusal(twoSelectorApp().call("run", bad)), want);
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				target: bad.target,
				mode: bad.mode,
			}),
		),
		want,
	);
});

test("call: two missing elections report the outermost declared one", async () => {
	assert.equal(
		await refusal(twoSelectorApp().call("run", {})),
		missingModeElection,
	);
	assert.equal(
		(await twoSelectorApp().test(["run"])).stderr,
		errOut(missingModeElection, "myapp run"),
	);
});

// --- A required bool inside a scope (§12.13, §18.23 item 239) ---

function scopedBoolApp(): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				strict: flag("strict", t.bool, {
					help: "fail hard",
					presence: "required",
				}),
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "an email message",
							flags: {
								verify: flag("verify", t.bool, {
									help: "verify the address",
									presence: "required",
								}),
							},
						}),
						sms: choice({ help: "a text message" }),
					},
					{ help: "delivery channel", presence: "required", env: "MYAPP_VIA" },
				),
			},
			handler: () => 0,
		}),
	);
	return app;
}

const scopedBoolWant =
	"flag '--verify' must be passed as --verify or --no-verify under '--via email'";

test("scope: a required negatable bool takes the root sentence plus the suffix", async () => {
	assert.equal(
		(await scopedBoolApp().test(["run", "--strict", "--via", "email"])).stderr,
		errOut(scopedBoolWant, "myapp run"),
	);
	// The root sentence the suffix is appended to, on its own.
	assert.equal(
		(await scopedBoolApp().test(["run", "--via", "email", "--verify"])).stderr,
		errOut(
			"flag '--strict' must be passed as --strict or --no-strict",
			"myapp run",
		),
	);
	// Both programmatic doors render the same composition.
	assert.equal(
		await refusal(
			scopedBoolApp().call("run", { strict: true, via: { choice: "email" } }),
		),
		scopedBoolWant,
	);
	assert.equal(
		await refusal(
			toolFor(scopedBoolApp(), "run").execute({ strict: true, via: "email" }),
		),
		scopedBoolWant,
	);
});

test("scope: the origin clause follows the scope suffix on that sentence", async () => {
	// §12.13's composition, unchanged by the sentence it now attaches to: the
	// scope suffix names where the requirement lives, then the origin names the
	// ambient election that put it there.
	process.env.MYAPP_VIA = "email";
	try {
		assert.equal(
			(await scopedBoolApp().test(["run", "--strict"])).stderr,
			errOut(
				`${scopedBoolWant} (elected from env var 'MYAPP_VIA')`,
				"myapp run",
			),
		);
	} finally {
		delete process.env.MYAPP_VIA;
	}
});

test("scope: a non-negatable required bool names the one token it has", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "an email message",
							flags: {
								verify: flag("verify", t.bool, {
									help: "verify the address",
									presence: "required",
									negatable: false,
								}),
							},
						}),
						sms: choice({ help: "a text message" }),
					},
					{ help: "delivery channel", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	assert.equal(
		(await app.test(["run", "--via", "email"])).stderr,
		errOut(
			"flag '--verify' must be passed as --verify under '--via email'",
			"myapp run",
		),
	);
});

// --- A dash-spelled key names nothing, at either door (§24.11) ---

/**
 * The key namespace at both programmatic doors is the underscored DELIVERY-name
 * space -- the parameter name a handler receives, which is exactly what the
 * flat schema publishes. A flag's dashed spelling is its command-line TOKEN,
 * and neither door has tokens, so a dashed key is refused rather than accepted
 * under a second spelling or silently dropped.
 */
function dashKeyApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				keep_going: flag("keep-going", t.str, {
					help: "carry on",
					presence: "optional",
				}),
				via: choiceFlag(
					"via",
					{
						sms: choice({
							help: "a text message",
							flags: {
								phone_number: flag("phone-number", t.str, {
									help: "the destination",
									presence: "required",
								}),
							},
						}),
						none: choice({ help: "no delivery" }),
					},
					{ help: "delivery channel", presence: "default", default: "none" },
				),
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one named profile",
							value: { carrier: t.str, help: "the profile name" },
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to run", presence: "required" },
				),
			},
			args: [
				arg("target_name", t.str, { help: "a name", presence: "optional" }),
			],
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, {
						keep_going: args.keep_going,
						target_name: args.target_name,
					});
				}
				return 0;
			},
		}),
	);
	return app;
}

test("flat: a dash-spelled key is an unknown parameter, never a silent drop", async () => {
	const run = (kwargs: Record<string, unknown>): Promise<unknown> =>
		toolFor(dashKeyApp(), "run").execute({ all_profiles: true, ...kwargs });
	assert.equal(
		await refusal(run({ "keep-going": "yes" })),
		'unknown parameter "keep-going" for command "run"',
	);
	assert.equal(
		await refusal(run({ "phone-number": "555" })),
		'unknown parameter "phone-number" for command "run"',
	);
	assert.equal(
		await refusal(run({ "target-name": "x" })),
		'unknown parameter "target-name" for command "run"',
	);
	// A member's own property, electing and declining alike.
	assert.equal(
		await refusal(
			toolFor(dashKeyApp(), "run").execute({ "all-profiles": true }),
		),
		'unknown parameter "all-profiles" for command "run"',
	);
	assert.equal(
		await refusal(
			toolFor(dashKeyApp(), "run").execute({
				target: "profile",
				profile: "work",
				"all-profiles": false,
			}),
		),
		'unknown parameter "all-profiles" for command "run"',
	);
});

test("call: the record door refuses a dash-spelled key too", async () => {
	// One implementation's two doors disagreeing about one key is the same
	// defect as two implementations disagreeing.
	assert.equal(
		await refusal(
			dashKeyApp().call("run", {
				"keep-going": "yes",
				target: { choice: "all-profiles" },
			}),
		),
		'unknown parameter "keep-going" for command "run"',
	);
	const captured: Record<string, unknown> = {};
	assert.equal(
		await dashKeyApp(captured).call("run", {
			keep_going: "yes",
			target: { choice: "all-profiles" },
		}),
		0,
	);
	assert.equal(captured.keep_going, "yes");
});

test("flat: the underscored spelling is the one the schema publishes", async () => {
	const captured: Record<string, unknown> = {};
	const app = dashKeyApp(captured);
	const run = toolFor(app, "run");
	assert.deepEqual(
		Object.keys(
			(run.parameters as { properties: Record<string, unknown> }).properties,
		).sort(),
		// A payload-less member publishes no property of its own (§18.21 item
		// 231): the selector's own property is what elects it.
		["keep_going", "phone_number", "profile", "target", "target_name", "via"],
	);
	assert.equal(
		await run.execute({
			all_profiles: true,
			keep_going: "yes",
			target_name: "x",
		}),
		0,
	);
	assert.equal(captured.keep_going, "yes");
	assert.equal(captured.target_name, "x");
});
