/**
 * NEGATIVE fixture: an update's names, its property floor and its write mode
 * are COMPILE errors in TypeScript (contract §27.8).
 *
 * `properties` is typed `readonly [K, ...K[]]` where `K` is the key union of
 * the command's own declared names, so the floor of one AND every name are
 * checked by the compiler: a property naming a flag the command does not
 * declare does not compile, and `errUpdateNameUnknown` stays reachable only
 * through a widened or JSON-shaped caller, which is the treatment §12.13 item
 * 213 established. `writeMode` is the literal union `"sparse" |
 * "full_replace"`, so a typo is a compile error rather than a registration one.
 *
 * A payoff that reaches one language is a PRO, not a con; these are
 * TypeScript's, beside Go's own two-parameter Properties floor.
 *
 * Compiled by tests/negative_types.test.ts, which pins the errors; it is
 * deliberately excluded from the main test build.
 */

import { defineMutatingCommand, flag, t } from "../../src/index.js";

const content = flag("content", t.str, {
	help: "record content",
	presence: "optional",
});

export const unknownProperty = defineMutatingCommand("update-record", {
	help: "change one DNS record in place",
	updateOf: {
		resource: "dns-record",
		writeMode: "sparse",
		properties: ["contnet"],
	},
	flags: { content },
	handler: () => 0,
});

export const emptyProperties = defineMutatingCommand("update-record", {
	help: "change one DNS record in place",
	updateOf: {
		resource: "dns-record",
		writeMode: "sparse",
		properties: [],
	},
	flags: { content },
	handler: () => 0,
});

export const badWriteMode = defineMutatingCommand("update-record", {
	help: "change one DNS record in place",
	updateOf: {
		resource: "dns-record",
		writeMode: "patch",
		properties: ["content"],
	},
	flags: { content },
	handler: () => 0,
});
