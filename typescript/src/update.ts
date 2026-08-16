/**
 * The update-command construct after registration (contract §27).
 *
 * An update command declares ONE record -- the resource it changes, the write
 * mode it changes it under, the declarations that name WHICH instance, and the
 * declarations that name WHAT changes -- and the framework derives from it the
 * at-least-one-property rule (§27.4), the write set and its two renderings
 * (§27.5), the clear vocabulary's delivery (§27.6), the schema encoding (§27.9)
 * and the MCP projection (§27.10).
 *
 * Registration lives in factories.ts, which owns the declaration guards and
 * §27.11's order; everything AFTER registration lives here, so the five
 * consumers -- the parse pipeline, the would-do log, the envelope, the dumped
 * schema and the MCP projection -- read one evaluation and one rendering
 * rather than five.
 *
 * Absence resolving to a VALUE is banned; absence BOUNDING SCOPE is what a
 * sparse update is (§27.13). The three properties that keep the second half
 * legitimate are enforced here rather than promised: the write set is derived
 * from ONE predicate (§23.6's provided, no source filter), it is never empty,
 * and it is never invisible.
 */

import { errUpdateNoProperty, ParseError } from "./errors.js";
import type { AnyCommand, AnyFlag, UpdateOf, WriteMode } from "./factories.js";
import { flagOpts, flagParamName } from "./factories.js";
import type { SourcedStore } from "./sources.js";

/**
 * The two parentheticals the write set's human line carries: a function of the
 * write mode alone, and always present in both segment shapes (§27.5).
 */
const WRITE_MODE_PAREN: Readonly<Record<WriteMode, string>> = {
	sparse: "(other properties unchanged)",
	full_replace: "(other properties are re-sent as read)",
};

/**
 * The two clauses the MCP description block's last line opens with -- the
 * human log's two parentheticals in the same words (§27.10).
 */
const WRITE_MODE_CLAUSE: Readonly<Record<WriteMode, string>> = {
	sparse: "left unchanged",
	full_replace: "re-sent as read",
};

/** The envelope's `writes` member, with its key order pinned (§27.5). */
export interface WritesEnvelope {
	readonly resource: string;
	readonly write_mode: string;
	readonly written: readonly string[];
	readonly cleared: readonly string[];
	readonly resent: readonly string[];
	readonly untouched: readonly string[];
}

/**
 * One invocation's answer to an update declaration: the ordered pair of the
 * properties it writes and the properties it clears, plus the two readings of
 * "the rest". Computed at parse time from §27.4's predicate and rendered
 * wherever a run reports what it does.
 */
export class UpdateState {
	readonly written: string[] = [];
	readonly cleared: string[] = [];
	readonly resent: string[] = [];
	readonly untouched: string[] = [];

	constructor(readonly decl: UpdateOf) {}

	/**
	 * The trailing parenthetical: a function of the write mode alone, and
	 * always present in both segment shapes.
	 */
	private paren(): string {
		return WRITE_MODE_PAREN[this.decl.writeMode];
	}

	/**
	 * The would-do log's unnumbered write-set line (§27.5), without the
	 * two-space indent the log adds.
	 *
	 * Two segments, `writes:` first, separated by `"; "`, with an empty segment
	 * omitted entirely -- §27.4's rule guarantees at least one survives, so the
	 * line is never empty and never has to say that it is. Names are the
	 * properties' DECLARED names without the `--` prefix: the log is the human
	 * surface, where the reader knows a declaration by the name they type, and
	 * the write set is data, which is why the token's prefix comes off.
	 */
	logLine(): string {
		const segments: string[] = [];
		if (this.written.length > 0) {
			segments.push(`writes: ${this.written.join(", ")}`);
		}
		if (this.cleared.length > 0) {
			segments.push(`clears: ${this.cleared.join(", ")}`);
		}
		return `${segments.join("; ")} ${this.paren()}`;
	}

	/**
	 * The machine rendering (§19.2's amendment, §27.5).
	 *
	 * The four arrays hold UNDERSCORED parameter names in declaration order and
	 * partition the declared property set exactly: every property appears in
	 * exactly one of them. `resent` and `untouched` are the two readings of
	 * "the rest", and exactly one of them is ever non-empty.
	 */
	envelopeMember(): WritesEnvelope {
		return {
			resource: this.decl.resource,
			write_mode: this.decl.writeMode,
			written: this.written.map(flagParamName),
			cleared: this.cleared.map(flagParamName),
			resent: this.resent.map(flagParamName),
			untouched: this.untouched.map(flagParamName),
		};
	}
}

/**
 * Every declared property as a CLI token, unquoted and joined by ", " in
 * declaration order (§12.16's list rule).
 */
function renderPropertyTokens(names: readonly string[]): string {
	return names.map((n) => `--${n}`).join(", ");
}

/**
 * Enforces the at-least-one-property rule and computes the write set (§27.4,
 * §27.5). Returns null on a command that declares no update.
 *
 * A property is provided exactly when §23.6's predicate says so, and there is
 * no source filter: a value from env, from config or injected by an `implies`
 * is a provision. A negated bool property is a provision too -- inside an
 * update command `--no-proxied` WRITES false -- and so is an unset, clearing
 * being writing.
 */
export function evaluateUpdate(
	def: AnyCommand,
	store: SourcedStore,
	unsets: ReadonlySet<string>,
): UpdateState | null {
	const d = def.updateOf;
	if (d === undefined) {
		return null;
	}
	const st = new UpdateState(d);
	for (const name of d.properties as readonly string[]) {
		if (unsets.has(name)) {
			st.cleared.push(name);
		} else if (store.isPresentForDeps(name)) {
			st.written.push(name);
		} else if (d.writeMode === "full_replace") {
			// A full-replace write touches every property, so nothing is
			// untouched: the rest is read back and re-sent.
			st.resent.push(name);
		} else {
			st.untouched.push(name);
		}
	}
	if (st.written.length === 0 && st.cleared.length === 0) {
		throw new ParseError(
			errUpdateNoProperty(
				d.resource,
				renderPropertyTokens(d.properties as readonly string[]),
			),
		);
	}
	return st;
}

// --- The MCP projection (§27.10) ---

/**
 * The at-least-one-property rule as one `required` branch per property, in
 * declaration order.
 *
 * Its fidelity is EXACT: the rule IS provision at this door -- a supplied key
 * is a provided property, a null is a supplied key and a clear, a false is a
 * supplied key and a write -- so `required` states the whole rule with nothing
 * left over.
 */
export function updateAnyOfBranches(
	def: AnyCommand,
): Record<string, unknown>[] {
	const d = def.updateOf;
	if (d === undefined) {
		return [];
	}
	return (d.properties as readonly string[]).map((name) => ({
		required: [flagParamName(name)],
	}));
}

/**
 * The tool description's update block (§27.10), in the shape §24.11's scope
 * block and §26.12's constraint block already established: appended after both
 * when they exist and separated from them by a blank line.
 *
 * Members render in PROPERTY names, like every other member in this block: the
 * caller writes keys, not argv.
 */
export function updateDescriptionBlock(def: AnyCommand): string {
	const d = def.updateOf;
	if (d === undefined) {
		return "";
	}
	const props = d.properties as readonly string[];
	const lines: string[] = [];
	// The `identifies:` line is omitted when the resource declares no identity
	// members.
	const identity = (d.identity ?? []) as readonly string[];
	if (identity.length > 0) {
		lines.push(`  identifies: ${identity.map(flagParamName).join(", ")}`);
	}
	lines.push(
		`  writes: ${props.map(flagParamName).join(", ")} -- at least one is required`,
	);
	let last = `  a property that is not supplied is ${WRITE_MODE_CLAUSE[d.writeMode]}`;
	// The `; null clears <list>` clause appears only when at least one property
	// is nullable, naming them in declaration order.
	const byName = new Map(def.allDecls.map((x) => [x.name, x]));
	const nullable = props.filter(
		(name) => flagOpts(byName.get(name) as AnyFlag).nullable === true,
	);
	if (nullable.length > 0) {
		last += `; null clears ${nullable.map(flagParamName).join(", ")}`;
	}
	lines.push(last);
	return `\n\nUpdate of "${d.resource}" (write mode: ${d.writeMode}):\n${lines.join("\n")}`;
}

// --- The schema encoding (§27.9) ---

/**
 * Publishes the declaration COMPLETELY rather than indicatively: a consumer
 * reconstructs the rule without re-reading the declaration.
 *
 * Names are published in the DECLARED spelling, matching the flag entry's own
 * `name`; the underscored spelling belongs to the machine doors. All three
 * keys are always present, `identity` as `[]` when the resource has none.
 */
export function serializeUpdateOf(d: UpdateOf): Record<string, unknown> {
	return {
		resource: d.resource,
		identity: [...((d.identity ?? []) as readonly string[])],
		properties: [...(d.properties as readonly string[])],
	};
}
