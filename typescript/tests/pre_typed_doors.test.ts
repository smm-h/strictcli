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
	provided,
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
	// A key the elected scope never declared names nothing the command declares,
	// one level down: the flat door's own unknown-parameter sentence with
	// §12.13's scope suffix saying where (§24.11 item 246).
	assert.equal(
		await refusal(
			twoSelectorApp().call("run", {
				target: { choice: "profile", value: "work", bogus: 1 },
			}),
		),
		`unknown parameter "bogus" for command "run" under '--profile'`,
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
	// selector's election refusal is heard over a value and a presence problem
	// in the first selector's record alike.
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
	// A key naming a flag a SIBLING scope declares is not a scope fact inside a
	// record: the record's namespace is the elected scope's own, so the key
	// names nothing at all -- a SHAPE fact, which outranks the second
	// selector's election refusal rather than losing to it (§24.11 item 246).
	assert.equal(
		await refusal(
			stagedSelectorApp().call("run", {
				via: { choice: "email", retries: 1, phone_number: "x" },
				target: badTag,
			}),
		),
		`unknown parameter "phone_number" for command "run" under '--via email'`,
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

// --- A key inside an elected record (§24.11 item 246, §24.3) ---

/**
 * A record's key namespace is the ELECTED CHOICE'S OWN SCOPE: the tag key, the
 * payload key where the choice carries one, and the parameters that scope
 * declares at that level. A key outside that set names nothing the command
 * declares, which is a fact about the object's SHAPE -- reported ahead of every
 * election, scope, value and presence problem the same call contains, exactly
 * as the flat door's own unknown key is.
 *
 * The sentence is the flat door's with §12.13's scope suffix on it, at every
 * depth. The out-of-scope template is refused for this state: it names a flag
 * the command DECLARES against the scopes that own it, and a key naming nothing
 * anywhere has no other side to name.
 */
function recordDepthApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				count: flag("count", t.int, { help: "how many", presence: "optional" }),
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
								format: choiceFlag(
									"format",
									{
										plain: choice({ help: "plain text" }),
										rich: choice({
											help: "rich text",
											flags: {
												width: flag("width", t.int, {
													help: "columns",
													presence: "required",
												}),
											},
										}),
									},
									{
										help: "the body format",
										presence: "default",
										default: "plain",
									},
								),
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
				mode: memberChoiceFlag(
					"mode",
					{
						profile: choice({
							help: "one named profile",
							value: { carrier: t.str, help: "the profile name" },
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to act on", presence: "required" },
				),
			},
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, args);
				}
				return 0;
			},
		}),
	);
	return app;
}

const allProfiles = { choice: "all-profiles" };

test("call: an unknown key inside a record is refused at the shape stage", async () => {
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				mode: allProfiles,
				via: { choice: "email", retries: 1, bogus: 2 },
			}),
		),
		`unknown parameter "bogus" for command "run" under '--via email'`,
	);
	// A key naming a flag a SIBLING choice declares names nothing this scope
	// declares either: the namespace is the elected scope's own.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				mode: allProfiles,
				via: { choice: "email", retries: 1, phone_number: "x" },
			}),
		),
		`unknown parameter "phone_number" for command "run" under '--via email'`,
	);
	// The same fact one level further down carries the WHOLE path.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				mode: allProfiles,
				via: {
					choice: "email",
					retries: 1,
					format: { choice: "rich", width: 5, bogus: 2 },
				},
			}),
		),
		`unknown parameter "bogus" for command "run" under '--via email --format rich'`,
	);
	// A member-spelled scope renders its own token in the suffix, and its
	// payload key is declared.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				via: { choice: "email", retries: 1 },
				mode: { choice: "profile", value: "work", bogus: 1 },
			}),
		),
		`unknown parameter "bogus" for command "run" under '--profile'`,
	);
});

test("call: a record's unknown key outranks every phase beside it", async () => {
	const want = `unknown parameter "bogus" for command "run" under '--via email'`;
	// Beside a second selector electing nothing (presence).
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				via: { choice: "email", retries: 1, bogus: 2 },
			}),
		),
		want,
	);
	// Beside a value refusal at root and inside the same record.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				count: "nope",
				mode: allProfiles,
				via: { choice: "email", retries: "nope", bogus: 2 },
			}),
		),
		want,
	);
	// Beside a missing required flag in the same scope (presence).
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				mode: allProfiles,
				via: { choice: "email", bogus: 2 },
			}),
		),
		want,
	);
	// Beside a payload-carrying member elected with no `value` -- also a shape
	// fact, and recorded after the key that names nothing.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				via: { choice: "email", retries: 1 },
				mode: { choice: "profile", bogus: 1 },
			}),
		),
		`unknown parameter "bogus" for command "run" under '--profile'`,
	);
});

test("call: a nested scope's parameters belong in the nested record", async () => {
	// The namespace is per LEVEL, so a nested scope's flag written in the OUTER
	// record names nothing that record's scope declares.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				mode: allProfiles,
				via: { choice: "email", retries: 1, format: "rich", width: 80 },
			}),
		),
		`unknown parameter "width" for command "run" under '--via email'`,
	);
	// Electing the nested choice inside its own record leaves its required flag
	// missing rather than misread -- with the whole path in the suffix, exactly
	// as the command line renders it.
	assert.equal(
		await refusal(
			recordDepthApp().call("run", {
				mode: allProfiles,
				via: { choice: "email", retries: 1, format: { choice: "rich" } },
			}),
		),
		"flag '--width' is required under '--via email --format rich'",
	);
	assert.equal(
		(
			await recordDepthApp().test([
				"run",
				"--all-profiles",
				"--via",
				"email",
				"--retries",
				"1",
				"--format",
				"rich",
			])
		).stderr,
		errOut(
			"flag '--width' is required under '--via email --format rich'",
			"myapp run",
		),
	);
	// And a nested choice that requires nothing is elected and delivered.
	const captured: Record<string, unknown> = {};
	assert.equal(
		await recordDepthApp(captured).call("run", {
			mode: allProfiles,
			via: { choice: "email", retries: 1, format: { choice: "plain" } },
		}),
		0,
	);
	assert.deepEqual(captured.via, {
		choice: "email",
		retries: 1n,
		format: { choice: "plain" },
	});
});

test("flat: a declared flag out of scope keeps §12.13's own sentence", async () => {
	// The record's unknown key is not the flat door's scope violation: the same
	// parameter supplied at the flat door's TOP LEVEL is a flag the command
	// declares, in a scope that does not own it, and keeps the sentence that
	// names both sides.
	assert.equal(
		await refusal(
			toolFor(recordDepthApp(), "run").execute({
				all_profiles: true,
				via: "email",
				retries: 1,
				phone_number: "x",
			}),
		),
		"flag '--phone-number' is only valid under '--via sms', but '--via email' was elected",
	);
});

// --- A pre-typed positional binds to the arg its KEY names (§24.11 item 248) ---

/**
 * A kwargs object has no order of its own (§21.4), so the key is the binding
 * and an omitted key is the absence presence answers. Reading the supplied
 * subset densely would hand a value the caller wrote under one name to whatever
 * arg the omissions left in that slot, and then refuse it in the name of an arg
 * nobody supplied.
 *
 * `label` is declared FIRST and optional, `count` second and required, so a
 * call supplying only `count` is exactly the state position-binding gets wrong.
 */
function keyedArgsApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {},
			args: [
				arg("label", t.str, { help: "a label", presence: "optional" }),
				arg("count", t.int, { help: "how many", presence: "required" }),
			],
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, args);
				}
				return 0;
			},
		}),
	);
	return app;
}

function variadicArgsApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {},
			args: [
				arg("label", t.str, { help: "a label", presence: "optional" }),
				arg("rest", t.int, {
					help: "the rest",
					presence: "optional",
					variadic: true,
				}),
			],
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, args);
				}
				return 0;
			},
		}),
	);
	return app;
}

test("call: a positional binds to the arg its key names", async () => {
	const captured: Record<string, unknown> = {};
	assert.equal(await keyedArgsApp(captured).call("run", { count: 2 }), 0);
	// The value the caller wrote under `count` is `count`'s, and the arg
	// declared before it is delivered ABSENT rather than handed that value.
	assert.equal(captured.count, 2n);
	assert.ok("label" in captured);
	assert.equal(captured.label, undefined);
	const both: Record<string, unknown> = {};
	assert.equal(
		await keyedArgsApp(both).call("run", { count: 2, label: "x" }),
		0,
	);
	assert.equal(both.label, "x");
	assert.equal(both.count, 2n);
});

test("call: an omitted positional key is the absence presence answers", async () => {
	// A required arg nobody named keeps the argv path's own sentence, whatever
	// the supplied subset would have filled its slot with.
	assert.equal(
		await refusal(keyedArgsApp().call("run", { label: "x" })),
		"missing required argument 'count'",
	);
	assert.equal(
		await refusal(keyedArgsApp().call("run", {})),
		"missing required argument 'count'",
	);
	// A refusal names the arg the KEY names, never the one a dense read would
	// have reached.
	assert.equal(
		await refusal(keyedArgsApp().call("run", { count: "nope" })),
		"argument 'count': expected integer, got str",
	);
	assert.equal(
		await refusal(keyedArgsApp().call("run", { label: 5, count: 2 })),
		"argument 'label': expected string, got int",
	);
});

test("call: a defaulted positional takes its default when its key is absent", async () => {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	const captured: Record<string, unknown> = {};
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {},
			args: [
				arg("label", t.str, {
					help: "a label",
					presence: "default",
					default: "d",
				}),
				arg("count", t.int, { help: "how many", presence: "required" }),
			],
			handler: (args) => {
				Object.assign(captured, args);
				return 0;
			},
		}),
	);
	assert.equal(await app.call("run", { count: 2 }), 0);
	assert.equal(captured.label, "d");
	assert.equal(captured.count, 2n);
});

test("call: a variadic positional is a sequence under its own key", async () => {
	const captured: Record<string, unknown> = {};
	assert.equal(
		await variadicArgsApp(captured).call("run", { rest: [1, 2, 3] }),
		0,
	);
	assert.deepEqual(captured.rest, [1n, 2n, 3n]);
	assert.equal(captured.label, undefined);
	// Anything but an array is the single element it looks like.
	const single: Record<string, unknown> = {};
	assert.equal(await variadicArgsApp(single).call("run", { rest: 7 }), 0);
	assert.deepEqual(single.rest, [7n]);
	// An absent key delivers no elements, and the arg declared before it keeps
	// the value its own key named.
	const omitted: Record<string, unknown> = {};
	assert.equal(await variadicArgsApp(omitted).call("run", { label: "x" }), 0);
	assert.deepEqual(omitted.rest, []);
	assert.equal(omitted.label, "x");
	// Each element is checked on its own, under the arg's own name.
	assert.equal(
		await refusal(variadicArgsApp().call("run", { rest: [1, "nope"] })),
		"argument 'rest': expected integer, got str",
	);
});

test("flat: the machine door binds positionals by key too", async () => {
	// The flat door hands its object to call(), so the binding is the same one
	// -- one parser, two spellings.
	const captured: Record<string, unknown> = {};
	assert.equal(
		await toolFor(keyedArgsApp(captured), "run").execute({ count: 2 }),
		0,
	);
	assert.equal(captured.count, 2n);
	assert.equal(captured.label, undefined);
	assert.equal(
		await refusal(toolFor(keyedArgsApp(), "run").execute({ label: "x" })),
		"missing required argument 'count'",
	);
});

// =========================================================================
// The record door's own two pins (§18.26 items 252 and 253)
// =========================================================================

/**
 * One selector whose elected scope declares every presence: an optional field,
 * a required one, and a defaulted one. `store` is what tells absence-by-key
 * from absence-by-value, and `depth` is the required field an explicit nothing
 * must never satisfy.
 */
function presencesApp(captured?: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("send", {
			help: "send it",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "an email message",
							flags: {
								subject: flag("subject", t.str, {
									help: "the subject",
									presence: "optional",
								}),
								recipient: flag("recipient", t.str, {
									help: "to whom",
									presence: "required",
								}),
								store: flag("store", t.str, {
									help: "where the copy goes",
									presence: "default",
									default: "outbox",
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
			},
			handler: (args) => {
				if (captured !== undefined) {
					Object.assign(captured, { via: args.via });
				}
				return 0;
			},
		}),
	);
	return app;
}

/**
 * A top-level optional flag, so the same explicit nothing can be asked at the
 * flat boundary, where key omission is the spelling absence already has.
 */
function flatOptionalApp(): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				subject: flag("subject", t.str, {
					help: "the subject",
					presence: "optional",
				}),
			},
			handler: () => 0,
		}),
	);
	return app;
}

test("call: an explicit nothing on an optional scoped field IS absence", async () => {
	// The record door is the one place absence has no spelling of its own: a
	// scope is an object, and `{subject: undefined}` is exactly how a caller
	// writes an optional property that is not set. So an explicit nothing
	// delivers §23.4's own delivery -- a PRESENT key holding nothing (§18.26
	// item 252).
	for (const nothing of [undefined, null]) {
		const captured: Record<string, unknown> = {};
		assert.equal(
			await presencesApp(captured).call("send", {
				via: { choice: "email", subject: nothing, recipient: "a@b.test" },
			}),
			0,
		);
		const rec = captured.via as Record<string, unknown>;
		assert.ok("subject" in rec);
		assert.equal(rec.subject, undefined);
		// Omitting the key delivers the identical record, which is the point:
		// one fact, and now one delivery.
		const omitted: Record<string, unknown> = {};
		await presencesApp(omitted).call("send", {
			via: { choice: "email", recipient: "a@b.test" },
		});
		assert.deepEqual(rec, omitted.via);
	}
});

test("call: an explicit nothing is refused for every other presence", async () => {
	// Item 240's line narrows to the optional declaration and to nothing else:
	// a required field is not satisfied by a null, and a defaulted one is not
	// reset to its declaration by one.
	assert.equal(
		await refusal(
			presencesApp().call("send", {
				via: { choice: "email", recipient: null },
			}),
		),
		"--recipient: expected string, got null",
	);
	assert.equal(
		await refusal(
			presencesApp().call("send", {
				via: { choice: "email", recipient: undefined },
			}),
		),
		"--recipient: expected string, got null",
	);
	assert.equal(
		await refusal(
			presencesApp().call("send", {
				via: { choice: "email", recipient: "a@b.test", store: null },
			}),
		),
		"--store: expected string, got null",
	);
});

test("call: the flat boundary refuses an explicit nothing, unchanged", async () => {
	// Absence has a spelling of its own here -- the caller omits the key -- so a
	// null would be a SECOND spelling of one fact (§24.11 item 240, unnarrowed).
	assert.equal(
		await refusal(flatOptionalApp().call("run", { subject: null })),
		"--subject: expected string, got null",
	);
	assert.equal(
		await refusal(flatOptionalApp().call("run", { subject: undefined })),
		"--subject: expected string, got null",
	);
	// And the flat MACHINE form spells a scoped field flat, so it is the same
	// boundary one level down.
	assert.equal(
		await refusal(
			toolFor(presencesApp(), "send").execute({
				via: "email",
				recipient: "a@b.test",
				subject: null,
			}),
		),
		"--subject: expected string, got null",
	);
});

test("call: every field a record supplies reports the declaration (§18.26 item 253)", async () => {
	// The supplied-versus-declared distinction is not decidable at every
	// implementation's record door, and one accessor answering three ways for
	// one call is the divergence parity forbids: the door that can answer least
	// decides what the shared answer is. So `provided()` over a caller-supplied
	// record answers false for every field, and the limitation is written down
	// rather than papered over with a value comparison.
	const captured: Record<string, unknown> = {};
	await presencesApp(captured).call("send", {
		via: { choice: "email", subject: "hi", recipient: "a@b.test" },
	});
	const rec = captured.via as Record<string, unknown>;
	assert.equal(provided(rec, "subject"), false);
	assert.equal(provided(rec, "recipient"), false);
	// A field the caller did not supply was already the declaration's.
	assert.equal(provided(rec, "store"), false);
	// The flat machine form converts into that record, so it answers the same.
	const flat: Record<string, unknown> = {};
	await toolFor(presencesApp(flat), "send").execute({
		via: "email",
		subject: "hi",
		recipient: "a@b.test",
	});
	assert.equal(provided(flat.via as Record<string, unknown>, "subject"), false);
	// An unknown name still raises the existing error rather than answering.
	assert.throws(() => provided(rec, "nonesuch"), {
		message: 'no source info for flag "nonesuch"',
	});
});

test("call: the command line still answers provided() with what it caused", async () => {
	// The pin is the RECORD door's alone: a command line names its own tokens,
	// so §23.6's predicate is decidable there and keeps its answer.
	const captured: Record<string, unknown> = {};
	await presencesApp(captured).test([
		"send",
		"--via",
		"email",
		"--subject",
		"hi",
		"--recipient",
		"a@b.test",
	]);
	const rec = captured.via as Record<string, unknown>;
	assert.equal(provided(rec, "subject"), true);
	assert.equal(provided(rec, "recipient"), true);
	assert.equal(provided(rec, "store"), false);
});

// =========================================================================
// A selection the caller elected NOTHING of is the declaration's (§23.6,
// §24.5, §18.26 item 253)
// =========================================================================

/**
 * A selector carrying a default selection, so every door can be asked the same
 * question: who caused this record? `captured` takes the selector's own source
 * and the record, so the answer is read at the accessor rather than inferred.
 */
function defaultedSelectionApp(captured: Record<string, unknown>): App {
	const app = createApp({ name: "myapp", version: "1.0.0", help: "test app" });
	app.command(
		defineReadOnlyCommand("send", {
			help: "send it",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "an email message",
							flags: {
								subject: flag("subject", t.str, {
									help: "the subject",
									presence: "default",
									default: "hi",
								}),
							},
						}),
						sms: choice({
							help: "a text message",
							flags: {
								phone_number: flag("phone-number", t.str, {
									help: "the destination",
									presence: "optional",
								}),
							},
						}),
					},
					{ help: "delivery channel", presence: "default", default: "email" },
				),
			},
			handler: (args, ctx) => {
				Object.assign(captured, {
					via: args.via,
					source: ctx.source("via"),
					provided: ctx.provided("via"),
				});
				return 0;
			},
		}),
	);
	return app;
}

test("flat: a selection the caller contributed nothing to is the declaration's", async () => {
	// The election came from the declaration, so the selector's source is
	// `default` and `provided()` is false -- the same answer the command line
	// and the record door give for the same declaration (§23.6, §24.5).
	const flat: Record<string, unknown> = {};
	assert.equal(
		await toolFor(defaultedSelectionApp(flat), "send").execute({}),
		0,
	);
	assert.equal(flat.source, "default");
	assert.equal(flat.provided, false);
	assert.deepEqual(flat.via, { choice: "email", subject: "hi" });

	const argv: Record<string, unknown> = {};
	await defaultedSelectionApp(argv).test(["send"]);
	assert.equal(argv.source, "default");
	assert.equal(argv.provided, false);

	const record: Record<string, unknown> = {};
	await defaultedSelectionApp(record).call("send", {});
	assert.equal(record.source, "default");
	assert.equal(record.provided, false);
});

test("flat: a sibling key beside a defaulted election is delivered, election unchanged", async () => {
	// The caller supplied a field of the elected scope and elected nothing: the
	// election stays the declaration's, and the field is delivered exactly as
	// the command line delivers it under a defaulted election. The field itself
	// follows the record door's rule -- every field that door delivers reports
	// the declaration (§18.26 item 253).
	const flat: Record<string, unknown> = {};
	assert.equal(
		await toolFor(defaultedSelectionApp(flat), "send").execute({
			subject: "yo",
		}),
		0,
	);
	assert.equal(flat.source, "default");
	assert.equal(flat.provided, false);
	assert.deepEqual(flat.via, { choice: "email", subject: "yo" });
	assert.equal(provided(flat.via as Record<string, unknown>, "subject"), false);

	// The command line answers the same about the election, and delivers the
	// same value for the flag the invocation did name.
	const argv: Record<string, unknown> = {};
	await defaultedSelectionApp(argv).test(["send", "--subject", "yo"]);
	assert.equal(argv.source, "default");
	assert.deepEqual(argv.via, { choice: "email", subject: "yo" });
});

test("flat: an election the caller DID make still reports the call", async () => {
	// The pin is about a record nothing was contributed to; a caller who named
	// the choice caused the value, and `provided()` says so.
	const flat: Record<string, unknown> = {};
	await toolFor(defaultedSelectionApp(flat), "send").execute({ via: "email" });
	assert.equal(flat.source, "cli");
	assert.equal(flat.provided, true);
});
