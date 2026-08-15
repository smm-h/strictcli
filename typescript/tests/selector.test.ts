/**
 * The scoped-selector construct (effects contract §24) and its message family
 * (§12.13).
 *
 * Every template below is asserted BYTE-EXACT at runtime. Compile-time typing
 * never exempts a runtime check: a widened caller, a plain-JS consumer and the
 * conformance harness all reach the same factories through JSON, so each
 * registration guard is exercised through `loose()` where the type system
 * would otherwise refuse the declaration outright.
 */

import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { App, AppSpec } from "../src/app.js";
import { createApp } from "../src/app.js";
import * as errors from "../src/errors.js";
import {
	arg,
	choice,
	choiceFlag,
	coRequired,
	defineReadOnlyCommand,
	flag,
	implies,
	memberChoiceFlag,
	provided,
	requires,
	t,
} from "../src/index.js";

function makeApp(spec?: Partial<AppSpec>): App {
	return createApp({
		name: "myapp",
		version: "1.0.0",
		help: "test app",
		...spec,
	});
}

/** Expected two-line parse-error stderr surface. */
function errOut(msg: string, prefix = "myapp"): string {
	return `error: ${msg}\ntry '${prefix} --help'\n`;
}

/**
 * Widens an option/choice literal past the type system. Every registration
 * guard here has a compile-time twin, and the runtime check is what a
 * JSON-driven caller meets.
 */
function loose(v: unknown): never {
	return v as never;
}

function rejects(fn: () => unknown, message: string): void {
	assert.throws(fn, (e: unknown) => {
		assert.equal((e as Error).message, message);
		return true;
	});
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

// =========================================================================
// The notify example (§24's own): election, scopes, delivery
// =========================================================================

function notifyApp(spec?: Partial<AppSpec>): App {
	const app = makeApp(spec);
	app.command(
		defineReadOnlyCommand("send", {
			help: "send one notification through exactly one channel",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "deliver the notification as an email message",
							flags: {
								subject: flag("subject", t.str, {
									help: "subject line of the message",
									presence: "required",
								}),
								recipient: flag("recipient", t.str, {
									help: "destination email address",
									presence: "optional",
								}),
							},
						}),
						sms: choice({
							help: "deliver the notification as a text message",
							flags: {
								phone_number: flag("phone-number", t.str, {
									help: "destination number in E.164 form",
									presence: "required",
									env: "MYAPP_PHONE",
								}),
							},
						}),
					},
					{ help: "delivery channel", short: "v", presence: "required" },
				),
			},
			handler: (a, ctx) => {
				switch (a.via.choice) {
					case "email":
						ctx.info(
							`email subject=${a.via.subject} recipient=${a.via.recipient ?? "None"} ` +
								`recipientProvided=${provided(a.via, "recipient")}`,
						);
						break;
					case "sms":
						ctx.info(`sms number=${a.via.phone_number}`);
						break;
				}
				return 0;
			},
		}),
	);
	return app;
}

test("selector: an elected choice delivers one tagged record with its own fields", async () => {
	const r = await notifyApp().test([
		"send",
		"--via",
		"email",
		"--subject",
		"hi",
	]);
	assert.equal(r.exitCode, 0);
	assert.equal(
		r.stdout,
		"email subject=hi recipient=None recipientProvided=false\n",
	);
});

test("selector: parsing is order-independent", async () => {
	const a = await notifyApp().test([
		"send",
		"--subject",
		"hi",
		"--via",
		"email",
	]);
	const b = await notifyApp().test([
		"send",
		"--via",
		"email",
		"--subject",
		"hi",
	]);
	assert.equal(a.stdout, b.stdout);
	assert.equal(a.exitCode, 0);
});

test("selector: a flag of another choice's scope is a distinct parse error", async () => {
	// The round's central error, and deliberately NOT "unknown flag": the flag
	// is declared, it is simply not in the elected scope (§12.13).
	const r = await notifyApp().test(["send", "--via", "sms", "--subject", "hi"]);
	assert.equal(r.exitCode, 1);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--subject' is only valid under '--via email', but '--via sms' was elected",
			"myapp send",
		),
	);
});

test("selector: the scope error outranks the missing required sub-flag it causes", async () => {
	// election -> scope -> value -> presence. The spelling mistake is reported
	// before its consequence (§24.3).
	const r = await notifyApp().test(["send", "--via", "sms", "--subject", "hi"]);
	assert.match(r.stderr, /--subject/);
	assert.doesNotMatch(r.stderr, /phone-number/);
});

test("selector: a scoped flag supplied with no election blames the election", async () => {
	const r = await notifyApp().test(["send", "--subject", "hi"]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--subject' is only valid under '--via email', but '--via' was not provided",
			"myapp send",
		),
	);
});

test("selector: nothing typed at all is the ordinary required-flag error", async () => {
	// Both statements are true; the precedence rule picks the one that names a
	// token the reader typed -- and here there is none (§24.3).
	const r = await notifyApp().test(["send"]);
	assert.equal(r.stderr, errOut("flag '--via' is required", "myapp send"));
});

test("selector: a required sub-flag of the elected scope names its scope", async () => {
	const r = await notifyApp().test(["send", "--via", "email"]);
	assert.equal(
		r.stderr,
		errOut("flag '--subject' is required under '--via email'", "myapp send"),
	);
});

test("selector: a value naming no choice reuses the invalid-choice sentence", async () => {
	const r = await notifyApp().test(["send", "--via", "pigeon"]);
	assert.equal(
		r.stderr,
		errOut(
			"--via: invalid value 'pigeon', must be one of: email, sms",
			"myapp send",
		),
	);
});

test("selector: elected more than once names both values in command-line order", async () => {
	const r = await notifyApp().test(["send", "--via", "email", "--via", "sms"]);
	assert.equal(
		r.stderr,
		errOut("--via: elected more than once, as 'email' and 'sms'", "myapp send"),
	);
});

test("selector: a short elects exactly as the long form does", async () => {
	const r = await notifyApp().test(["send", "-v", "email", "--subject", "hi"]);
	assert.equal(r.exitCode, 0);
});

test("selector: provided() answers for the record's own fields", async () => {
	const r = await notifyApp().test([
		"send",
		"--via",
		"email",
		"--subject",
		"hi",
		"--recipient",
		"a@b.test",
	]);
	assert.match(r.stdout, /recipientProvided=true/);
});

test("selector: provided() raises the existing unknown-name error", async () => {
	const app = makeApp();
	let seen: unknown;
	app.command(
		defineReadOnlyCommand("send", {
			help: "send",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({ help: "email" }),
						sms: choice({ help: "sms" }),
					},
					{ help: "channel", presence: "required" },
				),
			},
			handler: (a) => {
				try {
					provided(a.via, "nonesuch");
				} catch (e) {
					seen = e;
				}
				return 0;
			},
		}),
	);
	await app.test(["send", "--via", "email"]);
	assert.equal((seen as Error).message, 'no source info for flag "nonesuch"');
});

test("selector: ctx.source and ctx.provided answer for the selector's own key", async () => {
	const app = makeApp();
	const seen: string[] = [];
	app.command(
		defineReadOnlyCommand("send", {
			help: "send",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({ help: "email" }),
						sms: choice({ help: "sms" }),
					},
					{ help: "channel", presence: "default", default: "sms" },
				),
			},
			handler: (_a, ctx) => {
				seen.push(`${ctx.source("via")}/${ctx.provided("via")}`);
				return 0;
			},
		}),
	);
	await app.test(["send", "--via", "email"]);
	await app.test(["send"]);
	// True when the invocation elected, false when the declaration's default
	// did -- §23.6 unchanged (§24.5).
	assert.deepEqual(seen, ["cli/true", "default/false"]);
});

// =========================================================================
// Recursion, and the outermost-unsatisfied-election blame rule
// =========================================================================

function nestedApp(): App {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("add", {
			help: "add an entry",
			flags: {
				visibility: choiceFlag(
					"visibility",
					{
						"user-facing": choice({
							help: "shown to users",
							flags: {
								type: choiceFlag(
									"type",
									{
										feature: choice({
											help: "a feature",
											flags: {
												headline: flag("headline", t.str, {
													help: "the headline",
													presence: "required",
												}),
											},
										}),
										fix: choice({ help: "a fix" }),
									},
									{ help: "entry type", presence: "required" },
								),
							},
						}),
						internal: choice({ help: "not shown to users" }),
					},
					{ help: "who sees it", presence: "required" },
				),
			},
			handler: (a, ctx) => {
				if (a.visibility.choice === "user-facing") {
					ctx.info(
						a.visibility.type.choice === "feature"
							? `feature ${a.visibility.type.headline}`
							: "fix",
					);
				} else {
					ctx.info("internal");
				}
				return 0;
			},
		}),
	);
	return app;
}

test("recursion: a selector inside a scope elects and delivers", async () => {
	const r = await nestedApp().test([
		"add",
		"--visibility",
		"user-facing",
		"--type",
		"feature",
		"--headline",
		"it works",
	]);
	assert.equal(r.exitCode, 0);
	assert.equal(r.stdout, "feature it works\n");
});

test("recursion: the OUTERMOST unsatisfied election is blamed", async () => {
	// A flag two levels down whose outer election is the one that failed
	// blames the outer election, because that is the token the reader would
	// have to change (§24.3, §12.13).
	const r = await nestedApp().test([
		"add",
		"--visibility",
		"internal",
		"--headline",
		"x",
	]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--headline' is only valid under '--visibility user-facing --type feature', " +
				"but '--visibility internal' was elected",
			"myapp add",
		),
	);
});

test("recursion: a required sub-flag two levels down names the whole scope path", async () => {
	const r = await nestedApp().test([
		"add",
		"--visibility",
		"user-facing",
		"--type",
		"feature",
	]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--headline' is required under '--visibility user-facing --type feature'",
			"myapp add",
		),
	);
});

test("recursion: a required nested selector names its own scope", async () => {
	const r = await nestedApp().test(["add", "--visibility", "user-facing"]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--type' is required under '--visibility user-facing'",
			"myapp add",
		),
	);
});

// =========================================================================
// Sources, ambient elections, and conditional bindings (§24.6)
// =========================================================================

test("sources: a token-spelled selector elects from an env var, and says so", async () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("send", {
			help: "send",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "email",
							flags: {
								subject: flag("subject", t.str, {
									help: "subject",
									presence: "required",
								}),
							},
						}),
						sms: choice({
							help: "sms",
							flags: {
								phone_number: flag("phone-number", t.str, {
									help: "number",
									presence: "required",
								}),
							},
						}),
					},
					{ help: "channel", presence: "required", env: "NOTIFY_VIA" },
				),
			},
			handler: () => 0,
		}),
	);
	await withEnv({ NOTIFY_VIA: "sms" }, async () => {
		// An election from a non-CLI source names itself in every message it
		// causes: the refusal would otherwise blame a command line that does
		// not contain the cause (§24.6).
		const r = await app.test(["send"]);
		assert.equal(
			r.stderr,
			errOut(
				"flag '--phone-number' is required under '--via sms' (elected from env var 'NOTIFY_VIA')",
				"myapp send",
			),
		);
		// The out-of-scope clause carries the same origin.
		const r2 = await app.test(["send", "--subject", "hi"]);
		assert.equal(
			r2.stderr,
			errOut(
				"flag '--subject' is only valid under '--via email', but '--via sms' was elected from env var 'NOTIFY_VIA'",
				"myapp send",
			),
		);
	});
});

test("sources: a default election produces the ' by default' origin", async () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("send", {
			help: "send",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "email",
							flags: {
								subject: flag("subject", t.str, {
									help: "subject",
									presence: "optional",
								}),
							},
						}),
						sms: choice({ help: "sms" }),
					},
					{ help: "channel", presence: "default", default: "sms" },
				),
			},
			handler: () => 0,
		}),
	);
	const r = await app.test(["send", "--subject", "hi"]);
	assert.equal(
		r.stderr,
		errOut(
			"flag '--subject' is only valid under '--via email', but '--via sms' was elected by default",
			"myapp send",
		),
	);
});

test("sources: a scoped env binding is consulted when its scope is elected", async () => {
	const out = await withEnv({ MYAPP_PHONE: "+15550100" }, async () =>
		notifyApp().test(["send", "--via", "sms"]),
	);
	assert.equal(out.exitCode, 0);
	assert.equal(out.stdout, "sms number=+15550100\n");
});

test("sources: a skipped binding is named under --verbose, and only there", async () => {
	// A binding whose scope was not elected is a conditional binding by
	// declaration: never consulted, never an error, and always surfaced
	// (§24.6). One line per binding, in declaration order.
	await withEnv({ MYAPP_PHONE: "+15550100" }, async () => {
		const quiet = await notifyApp().test([
			"send",
			"--via",
			"email",
			"--subject",
			"hi",
		]);
		assert.doesNotMatch(quiet.stdout, /not consulted/);
		const loud = await notifyApp().test([
			"send",
			"--verbose",
			"--via",
			"email",
			"--subject",
			"hi",
		]);
		assert.match(
			loud.stdout,
			/not consulted: env var 'MYAPP_PHONE' binds flag '--phone-number' under '--via sms', which was not elected/,
		);
	});
});

// =========================================================================
// Member spelling (§24.4)
// =========================================================================

test("member spelling: a member may own a scope, which a group could not express", async () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("launch", {
			help: "launch",
			flags: {
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one profile",
							value: { carrier: t.str, help: "profile name" },
							flags: {
								create_missing: flag("create-missing", t.bool, {
									help: "create it when absent",
									presence: "default",
									default: false,
								}),
							},
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to launch", presence: "required" },
				),
			},
			handler: (a, ctx) => {
				ctx.info(
					a.target.choice === "profile"
						? `profile=${a.target.value} create=${a.target.create_missing}`
						: "all",
				);
				return 0;
			},
		}),
	);
	assert.equal(
		(await app.test(["launch", "--profile", "work", "--create-missing"]))
			.stdout,
		"profile=work create=true\n",
	);
	// `--all-profiles --create-missing` is a SCOPE error, where a mutex group
	// could only leave the second silently ignored (§24.4).
	assert.equal(
		(await app.test(["launch", "--all-profiles", "--create-missing"])).stderr,
		errOut(
			"flag '--create-missing' is only valid under '--profile', but '--all-profiles' was elected",
			"myapp launch",
		),
	);
});

test("member spelling: a member-spelled selector may default to a payload-less member", async () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("launch", {
			help: "launch",
			flags: {
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one profile",
							value: { carrier: t.str, help: "profile name" },
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{
						help: "what to launch",
						presence: "default",
						default: "all-profiles",
					},
				),
			},
			handler: (a, ctx) => {
				ctx.info(a.target.choice);
				return 0;
			},
		}),
	);
	assert.equal((await app.test(["launch"])).stdout, "all-profiles\n");
});

// =========================================================================
// Registration guards (§12.13), byte-exact
// =========================================================================

const twoChoices = {
	email: choice({ help: "email" }),
	sms: choice({ help: "sms" }),
};

test("guard: a selector cannot declare optional", () => {
	rejects(
		() =>
			choiceFlag("via", twoChoices, loose({ help: "h", presence: "optional" })),
		'Flag "via": a choice flag cannot declare presence: "optional": an absent selection is a choice nobody named, so name it as a choice of its own',
	);
});

test("guard: a selector must declare at least two choices", () => {
	rejects(
		() =>
			choiceFlag("via", loose({ email: choice({ help: "email" }) }), {
				help: "h",
				presence: "required",
			}),
		'Flag "via": a choice flag must declare at least two choices',
	);
});

test("guard: a choice's help is mandatory", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				loose({
					email: choice(loose({ help: " " })),
					sms: choice({ help: "sms" }),
				}),
				{ help: "h", presence: "required" },
			),
		'Choice "email" of "via": help text is required',
	);
});

test("guard: a default naming no declared choice", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				twoChoices,
				loose({ help: "h", presence: "default", default: "pigeon" }),
			),
		'Flag "via": presence: "default" with default: pigeon names no declared choice: must be one of: email, sms',
	);
});

test("guard: a defaulted selection must be complete", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							subject: flag("subject", t.str, {
								help: "subject",
								presence: "required",
							}),
						},
					}),
					sms: choice({ help: "sms" }),
				},
				{ help: "h", presence: "default", default: "email" },
			),
		'Flag "via": presence: "default" with default: email elects choice "email", whose scope declares the required flag \'--subject\': a defaulted selection must be complete with nothing typed',
	);
});

test("guard: a member-spelled default may only elect a payload-less member", () => {
	rejects(
		() =>
			memberChoiceFlag(
				"target",
				{
					profile: choice({
						help: "one profile",
						value: { carrier: t.str, help: "profile name" },
					}),
					"all-profiles": choice({ help: "every profile" }),
				},
				{ help: "h", presence: "default", default: "profile" },
			),
		'Flag "target": presence: "default" with default: profile elects choice "profile", whose flag carries a value nothing supplies: only a payload-less member can be a default',
	);
});

test("guard: a member-spelled selector cannot carry a short", () => {
	rejects(
		() =>
			memberChoiceFlag("target", twoChoices, {
				help: "h",
				short: "t",
				presence: "required",
			}),
		'Flag "target": a member-spelled choice flag is never typed, so it cannot carry a short: declare the short on a member',
	);
});

test("guard: a token-spelled choice cannot carry a payload", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						value: { carrier: t.str, help: "the address to deliver to" },
					}),
					sms: choice({ help: "sms" }),
				},
				{ help: "h", presence: "required" },
			),
		'Choice "email" of "via": a token-spelled choice cannot carry a payload: the token names the choice, and a choice that carries its own value belongs to a member-spelled choice flag, declared with memberChoiceFlag(...)',
	);
});

test("guard: the two reserved names inside every scope", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							choice: flag("choice", t.str, {
								help: "h",
								presence: "optional",
							}),
						},
					}),
					sms: choice({ help: "sms" }),
				},
				{ help: "h", presence: "required" },
			),
		'Choice "email" of "via": flag name \'choice\' is reserved by the framework: it tags the delivered record',
	);
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							value: flag("value", t.str, { help: "h", presence: "optional" }),
						},
					}),
					sms: choice({ help: "sms" }),
				},
				{ help: "h", presence: "required" },
			),
		'Choice "email" of "via": flag name \'value\' is reserved by the framework: it carries a member-spelled choice\'s own payload',
	);
});

test("guard: a scoped flag may not reuse the selector's own name", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							via: flag("via", t.str, { help: "h", presence: "optional" }),
						},
					}),
					sms: choice({ help: "sms" }),
				},
				{ help: "h", presence: "required" },
			),
		'Choice "email" of "via": flag \'--via\' collides with the choice flag\'s own name',
	);
});

test("guard: a scoped flag may not reuse a command-level flag's name", () => {
	rejects(
		() =>
			defineReadOnlyCommand("send", {
				help: "h",
				flags: {
					subject: flag("subject", t.str, { help: "h", presence: "optional" }),
					via: choiceFlag(
						"via",
						{
							email: choice({
								help: "email",
								flags: {
									subject: flag("subject", t.str, {
										help: "h",
										presence: "optional",
									}),
								},
							}),
							sms: choice({ help: "sms" }),
						},
						{ help: "h", presence: "required" },
					),
				},
				handler: () => 0,
			}),
		'Choice "email" of "via": flag \'--subject\' collides with a command-level flag of the same name: the scoped one could never be reached',
	);
});

test("guard: sibling scopes may reuse a name only with an identical value shape", () => {
	// Same shape is legal: the two can never be elected together.
	assert.doesNotThrow(() =>
		choiceFlag(
			"via",
			{
				email: choice({
					help: "email",
					flags: { to: flag("to", t.str, { help: "h", presence: "optional" }) },
				}),
				sms: choice({
					help: "sms",
					flags: { to: flag("to", t.str, { help: "h", presence: "optional" }) },
				}),
			},
			{ help: "h", presence: "required" },
		),
	);
	// A differing shape is not: tokenizing '--to' cannot wait for an election.
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							to: flag("to", t.str, { help: "h", presence: "optional" }),
						},
					}),
					sms: choice({
						help: "sms",
						flags: {
							to: flag("to", t.bool, { help: "h", presence: "optional" }),
						},
					}),
				},
				{ help: "h", presence: "required" },
			),
		'Flag "via": flag \'--to\' is declared by choices "email" and "sms" with different value shapes: sibling scopes may reuse a name only with an identical type and arity, because tokenizing \'--to\' cannot wait for an election',
	);
});

test("guard: an arity-only sibling mismatch takes the same widened message", () => {
	// §18.18 item 208: one condition, one message. A repeatable declaration
	// beside a scalar one is a value-shape mismatch, not a second template.
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							to: flag("to", t.list(t.str), {
								help: "h",
								presence: "optional",
							}),
						},
					}),
					sms: choice({
						help: "sms",
						flags: {
							to: flag("to", t.str, { help: "h", presence: "optional" }),
						},
					}),
				},
				{ help: "h", presence: "required" },
			),
		'Flag "via": flag \'--to\' is declared by choices "email" and "sms" with different value shapes: sibling scopes may reuse a name only with an identical type and arity, because tokenizing \'--to\' cannot wait for an election',
	);
});

test("guard: a short is claimed across every simultaneously live scope", () => {
	rejects(
		() =>
			defineReadOnlyCommand("send", {
				help: "h",
				flags: {
					subject: flag("subject", t.str, {
						help: "h",
						short: "s",
						presence: "optional",
					}),
					via: choiceFlag(
						"via",
						{
							email: choice({
								help: "email",
								flags: {
									sender: flag("sender", t.str, {
										help: "h",
										short: "s",
										presence: "optional",
									}),
								},
							}),
							sms: choice({ help: "sms" }),
						},
						{ help: "h", presence: "required" },
					),
				},
				handler: () => 0,
			}),
		"command \"send\": short '-s' is claimed by '--subject' and '--sender', which can be elected at the same time",
	);
});

/**
 * The two short-reuse guards (§12.13, §18.19 item 221). §24.7 permits sibling
 * scopes to reuse a short and says nothing more, which left two states with a
 * rule and no message. Both are `command "<name>": ` messages, because the
 * claimants live in different scopes and neither owns the collision.
 */
test("guard: sibling scopes may reuse a short when the two tokenize alike", () => {
	// Legal: the token consumes argv identically whatever the election decides.
	defineReadOnlyCommand("send", {
		help: "h",
		flags: {
			via: choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							subject: flag("subject", t.str, {
								help: "h",
								short: "s",
								presence: "optional",
							}),
						},
					}),
					sms: choice({
						help: "sms",
						flags: {
							sender: flag("sender", t.str, {
								help: "h",
								short: "s",
								presence: "optional",
							}),
						},
					}),
				},
				{ help: "h", presence: "required" },
			),
		},
		handler: () => 0,
	});
});

test("guard: a short reused by sibling scopes must tokenize identically", () => {
	rejects(
		() =>
			defineReadOnlyCommand("send", {
				help: "h",
				flags: {
					via: choiceFlag(
						"via",
						{
							email: choice({
								help: "email",
								flags: {
									subject: flag("subject", t.str, {
										help: "h",
										short: "s",
										presence: "optional",
									}),
								},
							}),
							sms: choice({
								help: "sms",
								flags: {
									silent: flag("silent", t.bool, {
										help: "h",
										short: "s",
										presence: "optional",
									}),
								},
							}),
						},
						{ help: "h", presence: "required" },
					),
				},
				handler: () => 0,
			}),
		"command \"send\": short '-s' is claimed by '--subject' and '--silent' with different value shapes: sibling scopes may reuse a short only with an identical type and arity, because tokenizing '-s' cannot wait for an election",
	);
});

test("guard: a short reused by sibling scopes may not name an election", () => {
	// Which name a reused short binds to resolves AFTER the elections, and an
	// election token has to be readable before any election has happened.
	rejects(
		() =>
			defineReadOnlyCommand("send", {
				help: "h",
				flags: {
					via: choiceFlag(
						"via",
						{
							email: choice({
								help: "email",
								flags: {
									subject: flag("subject", t.str, {
										help: "h",
										short: "s",
										presence: "optional",
									}),
								},
							}),
							webhook: choice({
								help: "webhook",
								flags: {
									scheme: choiceFlag(
										"scheme",
										{
											http: choice({ help: "plain" }),
											https: choice({ help: "tls" }),
										},
										{ help: "h", short: "s", presence: "required" },
									),
								},
							}),
						},
						{ help: "h", presence: "required" },
					),
				},
				handler: () => 0,
			}),
		"command \"send\": short '-s' is reused by sibling scopes and also claimed by '--scheme', which elects: an election token is read before any election has happened, so its short cannot be shared",
	);
});

test("guard: the short-claim table walks member scopes too", () => {
	// Two sibling MEMBER scopes are covered by the same words: the guards are
	// stated over scopes, never over the choices of a token-spelled selector,
	// which is what closes the member-scope hazard.
	rejects(
		() =>
			defineReadOnlyCommand("run", {
				help: "h",
				flags: {
					target: memberChoiceFlag(
						"target",
						{
							profile: choice({
								help: "one profile",
								value: { carrier: t.str, help: "profile name" },
								flags: {
									subject: flag("subject", t.str, {
										help: "h",
										short: "s",
										presence: "optional",
									}),
								},
							}),
							all_profiles: choice({
								help: "every profile",
								flags: {
									silent: flag("silent", t.bool, {
										help: "h",
										short: "s",
										presence: "optional",
									}),
								},
							}),
						},
						{ help: "h", presence: "required" },
					),
				},
				handler: () => 0,
			}),
		"command \"run\": short '-s' is claimed by '--subject' and '--silent' with different value shapes: sibling scopes may reuse a short only with an identical type and arity, because tokenizing '-s' cannot wait for an election",
	);
});

test("guard: a positional arg cannot be declared inside a choice scope", () => {
	rejects(
		() =>
			choiceFlag(
				"via",
				loose({
					email: choice(
						loose({
							help: "email",
							flags: {
								target: arg("target", t.str, {
									help: "h",
									presence: "required",
								}),
							},
						}),
					),
					sms: choice({ help: "sms" }),
				}),
				{ help: "h", presence: "required" },
			),
		'Choice "email" of "via": positional args cannot be declared inside a choice scope: a positional\'s meaning would depend on an election that may be typed after it',
	);
});

test("guard: every name ban re-runs at every depth", () => {
	// A ban enforced only against a flat root list is this construct's most
	// likely correctness defect, so it is checked as a requirement (§24.7).
	rejects(
		() =>
			choiceFlag(
				"via",
				{
					email: choice({
						help: "email",
						flags: {
							dry_run: flag("dry-run", t.bool, {
								help: "h",
								presence: "optional",
							}),
						},
					}),
					sms: choice({ help: "sms" }),
				},
				{ help: "h", presence: "required" },
			),
		"flag name 'dry-run' is reserved by the framework (dry-run, approve-consequential, quiet, verbose)",
	);
	rejects(
		() => choiceFlag("force", twoChoices, { help: "h", presence: "required" }),
		"flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'",
	);
});

test("guard: a constraint naming a scoped flag is a registration error", () => {
	const cmd = (dependency: ReturnType<typeof requires>) =>
		defineReadOnlyCommand("send", {
			help: "h",
			flags: {
				loud: flag("loud", t.bool, {
					help: "h",
					presence: "default",
					default: false,
				}),
				via: choiceFlag(
					"via",
					{
						email: choice({
							help: "email",
							flags: {
								subject: flag("subject", t.str, {
									help: "h",
									presence: "optional",
								}),
							},
						}),
						sms: choice({ help: "sms" }),
					},
					{ help: "h", presence: "required" },
				),
			},
			dependencies: [dependency],
			handler: () => 0,
		});
	rejects(
		() => cmd(requires({ flag: "subject", dependsOn: "loud" })),
		"command \"send\": Requires references 'subject', which is declared under '--via email': dependency constraints operate at root scope only",
	);
	rejects(
		() => cmd(loose(coRequired(["subject", "loud"]))),
		"command \"send\": CoRequired references 'subject', which is declared under '--via email': dependency constraints operate at root scope only",
	);
	rejects(
		() =>
			cmd(loose(implies({ flag: "subject", implies: "loud", value: true }))),
		"command \"send\": Implies references 'subject', which is declared under '--via email': dependency constraints operate at root scope only",
	);
});

// =========================================================================
// The value-flag record, and the deleted bare entry (§24.2)
// =========================================================================

test("choices: a bare entry is refused with the record redirect", () => {
	rejects(
		() =>
			flag(
				"mode",
				t.str,
				loose({ help: "h", choices: ["a", "b"], presence: "required" }),
			),
		'Flag "mode": choices entry 0 is a bare value: declare it as { value: <value>, help: "..." }',
	);
	rejects(
		() =>
			arg(
				"mode",
				t.str,
				loose({ help: "h", choices: ["a"], presence: "required" }),
			),
		'Arg "mode": choices entry 0 is a bare value: declare it as { value: <value>, help: "..." }',
	);
});

test("choices: an entry's help is optional, and non-empty when supplied", () => {
	assert.doesNotThrow(() =>
		flag("mode", t.str, {
			help: "h",
			choices: [{ value: "a", help: "the a mode" }, { value: "b" }],
			presence: "required",
		}),
	);
	rejects(
		() =>
			flag(
				"mode",
				t.str,
				loose({
					help: "h",
					choices: [{ value: "a", help: " " }],
					presence: "required",
				}),
			),
		"Flag.help must be a non-empty string",
	);
});

// =========================================================================
// Help rendering (§24.10)
// =========================================================================

test("help: a token-spelled selector renders an indented block", async () => {
	const r = await notifyApp().test(["send", "--help"]);
	assert.equal(
		r.stdout,
		[
			"myapp send -- send one notification through exactly one channel",
			"",
			"Flags:",
			"  --via, -v <choice>          delivery channel [required]",
			"    email                     deliver the notification as an email message",
			"      --subject <str>         subject line of the message [required]",
			"      --recipient <str>       destination email address [optional]",
			"    sms                       deliver the notification as a text message",
			"      --phone-number <str>    destination number in E.164 form [env: MYAPP_PHONE] [required]",
			"",
		].join("\n"),
	);
});

/**
 * A defaulted selector's presence part is its COMPLETE elected value (§24.5,
 * §18.19 item 215): the choice, then its own scalar fields in declaration
 * order. Go and TypeScript read the values off the named choice's declared
 * scope defaults, which completeness is what makes the same values Python
 * reads off its default instance.
 */
function defaultedApp(scope: "fields" | "empty" | "nested"): App {
	const app = makeApp();
	const webhook =
		scope === "fields"
			? choice({
					help: "post the notification to a URL",
					flags: {
						url: flag("url", t.str, {
							help: "the endpoint",
							presence: "default",
							default: "https://example.test/hook",
						}),
						retries: flag("retries", t.int, {
							help: "how many times to retry",
							presence: "default",
							default: 5n,
						}),
						// An optional field supplies no value, and `null` is not a
						// declarable default, so it is omitted from the rendering.
						tag: flag("tag", t.str, {
							help: "an optional tag",
							presence: "optional",
						}),
					},
				})
			: scope === "nested"
				? choice({
						help: "post the notification to a URL",
						flags: {
							url: flag("url", t.str, {
								help: "the endpoint",
								presence: "default",
								default: "https://example.test/hook",
							}),
							auth: choiceFlag(
								"auth",
								{
									none: choice({ help: "no authentication" }),
									token: choice({ help: "a bearer token" }),
								},
								{
									help: "how to authenticate",
									presence: "default",
									default: "none",
								},
							),
						},
					})
				: choice({ help: "post the notification to a URL" });
	app.command(
		defineReadOnlyCommand("send", {
			help: "send one notification",
			flags: {
				via: choiceFlag(
					"via",
					{
						webhook,
						shout: choice({ help: "deliver by shouting" }),
					},
					{ help: "delivery channel", presence: "default", default: "webhook" },
				),
			},
			handler: () => 0,
		}),
	);
	return app;
}

test("help: a defaulted selector renders its complete elected value", async () => {
	const r = await defaultedApp("fields").test(["send", "--help"]);
	assert.ok(
		r.stdout.includes(
			"delivery channel [default: webhook (url=https://example.test/hook, retries=5)]",
		),
		r.stdout,
	);
});

test("help: a defaulted selector with an empty scope renders the choice alone", async () => {
	const r = await defaultedApp("empty").test(["send", "--help"]);
	assert.ok(
		r.stdout.includes("delivery channel [default: webhook]\n"),
		r.stdout,
	);
	assert.ok(!r.stdout.includes("[default: webhook ("), r.stdout);
});

test("help: a nested selector in a defaulted scope states its own default", async () => {
	// It is not expanded into the parenthesized list: it opens its own line in
	// the block, where its own presence part states its own default.
	const r = await defaultedApp("nested").test(["send", "--help"]);
	assert.ok(
		r.stdout.includes(
			"delivery channel [default: webhook (url=https://example.test/hook)]",
		),
		r.stdout,
	);
	assert.ok(r.stdout.includes("how to authenticate [default: none]"), r.stdout);
});

test("help: a value flag keeps the one-line form until an entry carries help", async () => {
	const mk = (withHelp: boolean): App => {
		const app = makeApp();
		app.command(
			defineReadOnlyCommand("cmd", {
				help: "a command",
				flags: {
					mode: flag("mode", t.str, {
						help: "the mode",
						choices: withHelp
							? [
									{ value: "fast", help: "go fast" },
									{ value: "slow", help: "go slow" },
								]
							: [{ value: "fast" }, { value: "slow" }],
						presence: "required",
					}),
				},
				handler: () => 0,
			}),
		);
		return app;
	};
	assert.equal(
		(await mk(false).test(["cmd", "--help"])).stdout,
		[
			"myapp cmd -- a command",
			"",
			"Flags:",
			"  --mode <str>    the mode [choices: fast, slow] [required]",
			"",
		].join("\n"),
	);
	assert.equal(
		(await mk(true).test(["cmd", "--help"])).stdout,
		[
			"myapp cmd -- a command",
			"",
			"Flags:",
			"  --mode <str>    the mode [required]",
			"    fast          go fast",
			"    slow          go slow",
			"",
		].join("\n"),
	);
});

/**
 * §24.10's block rule is content-keyed, never surface-keyed (§18.19 item 218):
 * a positional arg whose `choices` entries carry help renders the same block a
 * flag's do, inside the `Arguments:` section and against that section's own
 * alignment column.
 */
function argChoicesApp(withHelp: boolean): App {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("add", {
			help: "add an entry",
			args: [
				arg("kind", t.str, {
					help: "the kind of entry",
					presence: "required",
					choices: withHelp
						? [
								{ value: "feature", help: "a user-facing feature" },
								{ value: "fix", help: "a user-facing fix" },
							]
						: [{ value: "feature" }, { value: "fix" }],
				}),
			],
			handler: () => 0,
		}),
	);
	return app;
}

test("help: a positional arg with helped choices renders an indented block", async () => {
	assert.equal(
		(await argChoicesApp(true).test(["add", "--help"])).stdout,
		[
			"myapp add -- add an entry",
			"",
			"Arguments:",
			"  kind         the kind of entry [required]",
			"    feature    a user-facing feature",
			"    fix        a user-facing fix",
			"",
		].join("\n"),
	);
});

test("help: an arg whose entries carry no help keeps the one-line form", async () => {
	assert.equal(
		(await argChoicesApp(false).test(["add", "--help"])).stdout,
		[
			"myapp add -- add an entry",
			"",
			"Arguments:",
			"  kind    the kind of entry [choices: feature, fix] [required]",
			"",
		].join("\n"),
	);
});

test("help: an arg block entry with no help renders the value alone", async () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("add", {
			help: "add an entry",
			args: [
				arg("kind", t.str, {
					help: "the kind of entry",
					presence: "required",
					choices: [
						{ value: "feature", help: "a user-facing feature" },
						{ value: "fix" },
					],
				}),
			],
			handler: () => 0,
		}),
	);
	assert.equal(
		(await app.test(["add", "--help"])).stdout,
		[
			"myapp add -- add an entry",
			"",
			"Arguments:",
			"  kind         the kind of entry [required]",
			"    feature    a user-facing feature",
			"    fix",
			"",
		].join("\n"),
	);
});

// =========================================================================
// Schema, MCP and the machine boundary (§24.11)
// =========================================================================

test("mcp: the projection flattens, and a scoped flag is never required", () => {
	const app = notifyApp();
	const schema = app.jsonSchema("send") as {
		properties: Record<string, { type?: string; enum?: unknown[] }>;
		required: string[];
	};
	assert.deepEqual(schema.properties.via, {
		type: "string",
		enum: ["email", "sms"],
		description: "delivery channel",
	});
	assert.equal(schema.properties.subject?.type, "string");
	assert.equal(schema.properties.phone_number?.type, "string");
	// The selector's own property follows the ordinary rule; every scoped flag
	// is excluded from `required`, because its requiredness is conditional.
	assert.deepEqual(schema.required, ["via"]);
});

test("mcp: a member's flattened property is described by the payload's own help", () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "operate on one named profile",
							value: { carrier: t.str, help: "profile name" },
						}),
						"all-profiles": choice({ help: "operate on every profile" }),
					},
					{ help: "which profiles to operate on", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	const schema = app.jsonSchema("run") as {
		properties: Record<string, { type?: string; description?: string }>;
	};
	// The property carries the VALUE, so the payload's help describes it; the
	// selector's own property carries the election and takes the selector's.
	assert.deepEqual(schema.properties.profile, {
		type: "string",
		description: "profile name",
	});
	assert.equal(
		schema.properties.target?.description,
		"which profiles to operate on",
	);
});

test("mcp: the scope structure rides the tool description", () => {
	const tools = notifyApp().asTools();
	const send = tools.find((t2) => t2.name === "send");
	assert.ok(send);
	assert.equal(
		send.description,
		[
			"send one notification through exactly one channel",
			"",
			"Scoped parameters (enforced at call time):",
			"  via=email: subject (required), recipient (optional)",
			"  via=sms: phone_number (required)",
		].join("\n"),
	);
});

test("mcp: an empty scope renders (no parameters), at every depth", () => {
	const tools = nestedApp().asTools();
	const add = tools.find((t2) => t2.name === "add");
	assert.ok(add);
	assert.equal(
		add.description,
		[
			"add an entry",
			"",
			"Scoped parameters (enforced at call time):",
			"  visibility=user-facing: type (required)",
			"  visibility=user-facing type=feature: headline (required)",
			"  visibility=user-facing type=fix: (no parameters)",
			"  visibility=internal: (no parameters)",
		].join("\n"),
	);
});

test("mcp: a wrong combination is refused at call time with the CLI's sentence", async () => {
	const tools = notifyApp().asTools();
	const send = tools.find((t2) => t2.name === "send");
	assert.ok(send);
	assert.equal(await send.execute({ via: "email", subject: "hi" }), 0);
	await assert.rejects(send.execute({ via: "sms", subject: "hi" }), {
		message:
			"flag '--subject' is only valid under 'via=email', but 'via=sms' was elected",
	});
});

// =========================================================================
// The catalogue's own bytes
// =========================================================================

test("templates: the scope path, suffix and origin clauses compose as pinned", () => {
	assert.equal(errors.errScopeSuffix(""), "");
	assert.equal(errors.errScopeSuffix("--via email"), " under '--via email'");
	assert.equal(errors.errElectionOriginSuffix(""), "");
	assert.equal(
		errors.errElectionOriginSuffix(errors.errElectionOriginEnv("NOTIFY_VIA")),
		" (elected from env var 'NOTIFY_VIA')",
	);
	assert.equal(
		errors.errElectionOriginSuffix(errors.errElectionOriginConfig("via")),
		" (elected from config key 'via')",
	);
	assert.equal(
		errors.errElectionOriginSuffix(errors.errElectionOriginDefault),
		" (elected by default)",
	);
	assert.equal(
		errors.errFlagOutOfScope(
			"x",
			"'--mode a' or '--mode b'",
			"'--mode c' was elected",
		),
		"flag '--x' is only valid under '--mode a' or '--mode b', but '--mode c' was elected",
	);
	assert.equal(
		errors.errScopeWhyNoMemberElected("--profile, --all-profiles"),
		"none of --profile, --all-profiles was elected",
	);
	assert.equal(
		errors.errAmbientBindingSkippedConfig(
			"phone_number",
			"phone-number",
			"--via sms",
		),
		"not consulted: config key 'phone_number' binds flag '--phone-number' under '--via sms', which was not elected",
	);
	assert.equal(
		errors.errChoiceDuplicateName("via", "email"),
		'Flag "via": choice "email" is declared twice',
	);
});

test("member spelling: an out-of-scope flag under an unelected member names no token", () => {
	// The member-spelled twin of the "was not provided" clause: it cannot name
	// a selector token, because none is ever typed (§12.13).
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("launch", {
			help: "launch",
			flags: {
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "one profile",
							value: { carrier: t.str, help: "profile name" },
							flags: {
								create_missing: flag("create-missing", t.bool, {
									help: "create it when absent",
									presence: "default",
									default: false,
								}),
							},
						}),
						"all-profiles": choice({ help: "every profile" }),
					},
					{ help: "what to launch", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	return app.test(["launch", "--create-missing"]).then((r) => {
		assert.equal(
			r.stderr,
			errOut(
				"flag '--create-missing' is only valid under '--profile', but none of --profile, --all-profiles was elected",
				"myapp launch",
			),
		);
	});
});

test("sources: a skipped CONFIG binding is named under --verbose too", async () => {
	const app = makeApp({ config: false });
	app.command(
		defineReadOnlyCommand("send", {
			help: "send",
			flags: {
				via: choiceFlag(
					"via",
					{
						email: choice({ help: "email" }),
						sms: choice({
							help: "sms",
							flags: {
								phone_number: flag("phone-number", t.str, {
									help: "number",
									presence: "optional",
									env: "MYAPP_PHONE",
								}),
							},
						}),
					},
					{ help: "channel", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	await withEnv({ MYAPP_PHONE: "+15550100" }, async () => {
		const r = await app.test(["send", "--verbose", "--via", "email"]);
		assert.equal(r.exitCode, 0);
		assert.equal(
			r.stdout,
			"not consulted: env var 'MYAPP_PHONE' binds flag '--phone-number' under '--via sms', which was not elected\n",
		);
	});
});

// =========================================================================
// §12.14 -- an int choice beyond ±2^53 is a registration error
// =========================================================================

const MAGNITUDE_CLAUSE =
	"the number's magnitude exceeds 2^53 (declare a big identifier as a string)";

test("guard: an int choice beyond 2^53 is refused on a flag", () => {
	rejects(
		() =>
			flag("id", t.int, {
				help: "the id",
				presence: "required",
				choices: [{ value: 1n }, { value: 9007199254740993n }],
			}),
		`Flag "id": choice 9007199254740993: ${MAGNITUDE_CLAUSE}`,
	);
});

test("guard: an int choice beyond 2^53 is refused on an arg", () => {
	rejects(
		() =>
			arg("id", t.int, {
				help: "the id",
				presence: "required",
				choices: [{ value: 1n }, { value: 9007199254740993n }],
			}),
		`Arg "id": choice 9007199254740993: ${MAGNITUDE_CLAUSE}`,
	);
});

test("guard: the negative side is refused and renders its sign", () => {
	rejects(
		() =>
			flag("id", t.int, {
				help: "the id",
				presence: "required",
				choices: [{ value: -9007199254740993n }],
			}),
		`Flag "id": choice -9007199254740993: ${MAGNITUDE_CLAUSE}`,
	);
});

test("guard: exactly 2^53 registers", () => {
	// The guard is `exceeds`, not `reaches`: 2^53 itself round-trips through a
	// double exactly.
	flag("id", t.int, {
		help: "the id",
		presence: "required",
		choices: [{ value: 9007199254740992n }, { value: -9007199254740992n }],
	});
	arg("id", t.int, {
		help: "the id",
		presence: "required",
		choices: [{ value: 9007199254740992n }],
	});
});

test("guard: a float choice of the same magnitude is exempt", () => {
	// The canonical float form is by construction the shortest string that
	// round-trips to the identical double, so nothing is lost there.
	flag("ratio", t.float, {
		help: "the ratio",
		presence: "required",
		choices: [{ value: 1e300 }, { value: 0.5 }],
	});
});

test("guard: a list carrier's int choices are covered too", () => {
	// The guard runs over a declaration's resolved choice VALUES, whatever
	// arity the carrier publishes them at.
	rejects(
		() =>
			flag("ids", t.list(t.int), {
				help: "the ids",
				presence: "required",
				choices: [{ value: 9007199254740993n }],
			}),
		`Flag "ids": choice 9007199254740993: ${MAGNITUDE_CLAUSE}`,
	);
});

// =========================================================================
// The selector encoding (§25.6)
// =========================================================================

/** The `flags` array of a one-command app's dumped command entry. */
function dumpedFlags(app: App): Record<string, unknown>[] {
	const dict = (
		app as unknown as { dumpSchemaDict: () => Record<string, unknown> }
	).dumpSchemaDict();
	const commands = dict.commands as Record<string, Record<string, unknown>>;
	const first = Object.values(commands)[0] as Record<string, unknown>;
	return first.flags as Record<string, unknown>[];
}

test("schema: a token-spelled selector publishes its choices, scopes and spelling", () => {
	const entry = dumpedFlags(notifyApp())[0] as Record<string, unknown>;
	// A selector has NO value_schema, and its absence IS the declaration: a
	// variant is inexpressible in the closed four-keyword subset, and the
	// presence of `elect_by` is what tells a reader which shape it holds.
	assert.ok(!("value_schema" in entry));
	assert.deepEqual(Object.keys(entry), [
		"name",
		"help",
		"short",
		"presence",
		"choices",
		"elect_by",
	]);
	assert.deepEqual(entry, {
		name: "via",
		help: "delivery channel",
		short: "v",
		presence: "required",
		choices: [
			{
				name: "email",
				help: "deliver the notification as an email message",
				flags: [
					{
						name: "subject",
						help: "subject line of the message",
						value_schema: { type: "string" },
						presence: "required",
					},
					{
						name: "recipient",
						help: "destination email address",
						value_schema: { type: "string" },
						presence: "optional",
					},
				],
			},
			{
				name: "sms",
				help: "deliver the notification as a text message",
				flags: [
					{
						name: "phone-number",
						help: "destination number in E.164 form",
						value_schema: { type: "string" },
						presence: "required",
						env: "MYAPP_PHONE",
					},
				],
			},
		],
		elect_by: "selector-token",
	});
});

test("schema: a member-spelled choice's payload is the first scope entry", () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("run", {
			help: "run it",
			flags: {
				target: memberChoiceFlag(
					"target",
					{
						profile: choice({
							help: "operate on one named profile",
							value: { carrier: t.str, help: "profile name" },
							flags: {
								create_missing: flag("create-missing", t.bool, {
									help: "create the profile when absent",
									presence: "default",
									default: false,
								}),
							},
						}),
						all_profiles: choice({ help: "operate on every profile" }),
					},
					{ help: "which profiles to operate on", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	const entry = dumpedFlags(app)[0] as Record<string, unknown>;
	// The payload is supplied by electing the member, and required-once-elected
	// is exactly what a member flag's presence means. A payload-less member has
	// no `value` entry, and an empty scope omits `flags` entirely. The `value`
	// entry's help is the PAYLOAD's own, never the choice's: the choice's help
	// says what electing it means, the payload's what the value is (§25.6).
	assert.deepEqual(entry.choices, [
		{
			name: "profile",
			help: "operate on one named profile",
			flags: [
				{
					name: "value",
					help: "profile name",
					value_schema: { type: "string" },
					presence: "required",
				},
				{
					name: "create-missing",
					help: "create the profile when absent",
					value_schema: { type: "boolean" },
					presence: "default",
					default: false,
					negatable: true,
				},
			],
		},
		{ name: "all_profiles", help: "operate on every profile" },
	]);
	assert.equal(entry.elect_by, "member-flags");
});

test("schema: a nested selector is an ordinary entry inside a flags array", () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("add", {
			help: "add an entry",
			flags: {
				visibility: choiceFlag(
					"visibility",
					{
						"user-facing": choice({
							help: "a change users read about",
							flags: {
								type: choiceFlag(
									"type",
									{
										feature: choice({ help: "a user-facing feature" }),
										fix: choice({ help: "a user-facing fix" }),
									},
									{ help: "the kind of change", presence: "required" },
								),
							},
						}),
						internal: choice({ help: "a change nobody upgrades for" }),
					},
					{ help: "who the entry is for", presence: "required" },
				),
			},
			handler: () => 0,
		}),
	);
	const entry = dumpedFlags(app)[0] as Record<string, unknown>;
	const outer = (entry.choices as Record<string, unknown>[])[0] as Record<
		string,
		unknown
	>;
	const nested = (outer.flags as Record<string, unknown>[])[0] as Record<
		string,
		unknown
	>;
	// Recursion is free: a nested selector is a full flag entry carrying its
	// own `choices` and `elect_by`, to any depth.
	assert.equal(nested.name, "type");
	assert.equal(nested.elect_by, "selector-token");
	assert.ok(!("value_schema" in nested));
	assert.deepEqual(nested.choices, [
		{ name: "feature", help: "a user-facing feature" },
		{ name: "fix", help: "a user-facing fix" },
	]);
});

test("schema: a defaulted selector publishes the flat map", () => {
	const app = makeApp();
	app.command(
		defineReadOnlyCommand("send", {
			help: "send it",
			flags: {
				via: choiceFlag(
					"via",
					{
						webhook: choice({
							help: "post to a URL",
							flags: {
								url: flag("url", t.str, {
									help: "the endpoint",
									presence: "default",
									default: "https://example.test/hook",
								}),
								retries: flag("retries", t.int, {
									help: "attempts",
									presence: "default",
									default: 3n,
								}),
								tag: flag("tag", t.str, {
									help: "a tag",
									presence: "optional",
								}),
							},
						}),
						shout: choice({ help: "shout it" }),
					},
					{ help: "delivery channel", presence: "default", default: "webhook" },
				),
			},
			handler: () => 0,
		}),
	);
	const entry = dumpedFlags(app)[0] as Record<string, unknown>;
	// The choice's name under the reserved key `choice`, then each field that
	// HAS a value, in declaration order. A field with no value is omitted,
	// which is unambiguous because `null` is not a declarable default anywhere.
	assert.deepEqual(entry.default, {
		choice: "webhook",
		url: "https://example.test/hook",
		retries: 3n,
	});
});
