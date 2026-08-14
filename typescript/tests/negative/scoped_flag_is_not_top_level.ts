/**
 * NEGATIVE fixture: a scoped sub-flag must not be reachable as a top-level
 * handler argument, and a non-exhaustive switch must not compile.
 *
 * This is the structural fix §24.12 records for infer.ts's remaining
 * unsoundness: a scope's flags are unreachable except through the tag that
 * proves the scope was elected, so the handler-args type cannot lie about
 * them. §23.2 fixed the mutex-member case by declaration; this makes the
 * failure mode inexpressible.
 *
 * Compiled by tests/negative_types.test.ts, which pins the errors; it is
 * deliberately excluded from the main test build.
 */

import {
	assertNever,
	choice,
	choiceFlag,
	defineReadOnlyCommand,
	flag,
	t,
} from "../../src/index.js";

export const bad = defineReadOnlyCommand("send", {
	help: "h",
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
				sms: choice({ help: "sms" }),
			},
			{ help: "delivery channel", presence: "required" },
		),
	},
	handler: (args) => {
		// A sub-flag is never a top-level handler argument, at any depth.
		const leaked: string = args.subject;
		switch (args.via.choice) {
			case "email":
				return args.via.subject.length;
			// `sms` is deliberately unhandled: assertNever must refuse it.
			default:
				return assertNever(args.via) + leaked.length;
		}
	},
});
