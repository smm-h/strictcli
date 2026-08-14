/**
 * The delivered elected record: the tagged value a selector hands a handler,
 * plus the two helpers a handler uses to consume it (contract §24.1, §24.9).
 *
 * The record's own object form is FLAT -- `{ choice: "email", subject: "hi" }`
 * -- which is what makes `choice` and `value` reserved names inside every
 * scope (§24.7). The nesting-one-level-deeper alternative was refused because
 * it costs a level on every encoded value for a collision two reserved names
 * already close.
 */

import { errNoSourceInfo } from "./errors.js";

/**
 * Per-field provided-ness, carried on the record itself rather than in the
 * context's per-parse store.
 *
 * Two facts force that shape (§24.9). A scoped name is NOT unique
 * command-wide -- sibling scopes may reuse it -- so `ctx.provided("subject")`
 * has no single answer and must not invent one; a scoped flag is simply not
 * in the store, and asking for one raises the existing unknown-name error.
 * And the record's fields are USER-NAMED, so a `provided` method would occupy
 * a name a scope might want, which is why TypeScript spells it as a function
 * over the record.
 *
 * The property is a symbol and non-enumerable, so it never appears in
 * `Object.keys`, in JSON, or in a structural comparison of two records.
 */
const PROVIDED_FIELDS = Symbol.for("strictcli.electedProvidedFields");

/** The elected record as the framework builds it: a tag plus that choice's fields. */
export type ElectedRecord = Readonly<Record<string, unknown>>;

/**
 * Records which of an elected record's fields the INVOCATION caused, in
 * §23.6's own terms: `cli`, `env`, `config` and `implied` are provided;
 * `default` and `infra` are not. Package-internal -- the parser calls it once
 * per elected scope.
 */
export function attachProvidedFields(
	record: Record<string, unknown>,
	provided: ReadonlySet<string>,
): void {
	Object.defineProperty(record, PROVIDED_FIELDS, {
		value: new Set(provided),
		enumerable: false,
		writable: false,
		configurable: false,
	});
}

/**
 * Answers whether the invocation caused a field of an elected record, rather
 * than the declaration doing it (§23.6's predicate, evaluated inside the
 * scope). A name the record does not declare raises the same unknown-name
 * error `ctx.source` and `ctx.provided` already raise, rather than minting a
 * second vocabulary for one condition.
 *
 * @example
 * switch (args.via.choice) {
 *   case "email":
 *     if (provided(args.via, "subject")) { ... }
 * }
 */
export function provided(record: ElectedRecord, name: string): boolean {
	const key = name.replaceAll("-", "_");
	const fields = (record as Record<symbol, unknown>)[PROVIDED_FIELDS] as
		| Set<string>
		| undefined;
	if (fields === undefined || !Object.hasOwn(record, key)) {
		throw new Error(errNoSourceInfo(name));
	}
	return fields.has(key);
}

/**
 * Exhaustiveness helper for a `switch` over an elected record's `choice` tag.
 * A missing case makes the argument something other than `never`, so the
 * default branch fails to COMPILE (§24.12).
 *
 * @example
 * switch (args.via.choice) {
 *   case "email": return sendEmail(args.via);
 *   case "sms": return sendSms(args.via);
 *   default: return assertNever(args.via);
 * }
 */
export function assertNever(x: never): never {
	throw new Error(
		`unreachable: unhandled choice ${JSON.stringify(x)}: every choice of a selector must be handled`,
	);
}
