/**
 * NEGATIVE fixture: a selector's `default` naming a choice that does not
 * exist must not compile.
 *
 * The `default` member is typed `keyof C & string`, so the mistake is a
 * COMPILE error before it is a registration error (contract §24.12). The
 * registration guard still exists for a widened caller, and
 * tests/selector.test.ts asserts its bytes.
 *
 * Compiled by tests/negative_types.test.ts, which pins the error; it is
 * deliberately excluded from the main test build.
 */

import { choice, choiceFlag } from "../../src/index.js";

export const bad = choiceFlag(
	"via",
	{
		email: choice({ help: "deliver as an email message" }),
		sms: choice({ help: "deliver as a text message" }),
	},
	{ help: "delivery channel", presence: "default", default: "pigeon" },
);
