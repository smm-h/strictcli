/**
 * NEGATIVE fixture: a COMPUTED choice key must not compile.
 *
 * Object-literal keys are literal types by default, so the delivered value is
 * an exact discriminated union with no annotation anywhere. A computed key
 * would silently degrade the tag to `string` and make `assertNever` accept
 * anything -- since silence is the failure mode, the choice map is constrained
 * to literal keys and a computed one is a compile error naming itself
 * (contract §24.12).
 *
 * Compiled by tests/negative_types.test.ts, which pins the error; it is
 * deliberately excluded from the main test build.
 */

import { choice, choiceFlag } from "../../src/index.js";

declare const computed: string;

export const bad = choiceFlag(
	"via",
	{
		[computed]: choice({ help: "deliver as an email message" }),
		sms: choice({ help: "deliver as a text message" }),
	},
	{ help: "delivery channel", presence: "required" },
);
