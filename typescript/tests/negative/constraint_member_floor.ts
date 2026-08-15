/**
 * NEGATIVE fixture: the two-member floor and the `when` vocabulary are
 * COMPILE errors in TypeScript (contract §26.6).
 *
 * `members` is typed `readonly [ConstraintMember, ConstraintMember,
 * ...ConstraintMember[]]`, so a one-member constraint cannot be written by an
 * ordinary caller -- `errConstraintMinMembers` stays reachable only through a
 * widened or JSON-shaped caller, which is the treatment §12.13 item 213
 * established. `when` is the literal union `"present" | "true" | "non_empty"`,
 * so a typo is a compile error rather than a registration one.
 *
 * A payoff that reaches one language is a PRO, not a con; these two are
 * TypeScript's, beside Go's own two-named-members floor.
 *
 * Compiled by tests/negative_types.test.ts, which pins the errors; it is
 * deliberately excluded from the main test build.
 */

import { allOrNone, atLeastOne } from "../../src/index.js";

export const tooFewMembers = allOrNone({
	name: "author-name",
	members: [{ name: "old-name" }],
});

export const badWhen = atLeastOne({
	name: "purge-selection",
	members: [{ name: "targets", when: "nonempty" }, { name: "all" }],
});
