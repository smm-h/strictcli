/**
 * The constraint system (contract §26): the two co-occurrence families
 * resolved against their command, rendered for every surface that publishes
 * them, and evaluated at parse time.
 *
 * Registration lives in factories.ts (it owns the declaration guards and the
 * §26.8 order); everything AFTER registration lives here, so the four
 * consumers -- the parse pipeline, help, the dumped schema and the MCP
 * projection -- read one resolution and one rendering rather than four.
 */

import type {
	AllOrNone,
	AnyCommand,
	AtLeastOne,
	Constraint,
	Implies,
	Requires,
	When,
} from "./factories.js";
import { flagParamName } from "./factories.js";

/** A member's RESOLVED kind (§26.2), published verbatim by the schema. */
export type MemberKind = "flag" | "arg" | "constraint";

/**
 * A member after resolution. `when` is present on a flag or arg member --
 * always, defaulted to `present` -- and absent on a constraint member, which
 * has no election of its own (§26.3).
 */
export interface ResolvedMember {
	readonly kind: MemberKind;
	readonly name: string;
	readonly when: When | undefined;
}

/** A co-occurrence constraint with its members resolved. */
export interface ResolvedCoOccurrence {
	readonly kind: "at-least-one" | "all-or-none";
	readonly name: string;
	readonly members: readonly ResolvedMember[];
}

/** Every constraint of a command, in declaration order, resolved. */
export type ResolvedConstraint = ResolvedCoOccurrence | Requires | Implies;

/** True for the two families that carry members and may be nested. */
export function isCoOccurrenceResolved(
	c: ResolvedConstraint,
): c is ResolvedCoOccurrence {
	return c.kind === "at-least-one" || c.kind === "all-or-none";
}

/**
 * Resolves every member name of every constraint against the command's flags,
 * args and other constraints. Registration already proved the set legal, so
 * this never refuses -- it only publishes what the lookup found, which is
 * what lets a consumer reconstruct the rule without re-reading the
 * declaration (§26.11).
 */
export function resolveConstraints(
	def: AnyCommand,
): readonly ResolvedConstraint[] {
	const declNames = new Set(def.allDecls.map((d) => d.name));
	const argNames = new Set(def.args.map((a) => a.name));
	const out: ResolvedConstraint[] = [];
	for (const c of def.constraints) {
		if (c.kind !== "at-least-one" && c.kind !== "all-or-none") {
			out.push(c);
			continue;
		}
		out.push({
			kind: c.kind,
			name: c.name,
			members: c.members.map((m) => {
				const kind: MemberKind = declNames.has(m.name)
					? "flag"
					: argNames.has(m.name)
						? "arg"
						: "constraint";
				return {
					kind,
					name: m.name,
					// Always emitted on a flag or arg member, never on a constraint
					// member: a defaulted `when` that could be omitted is an erasure
					// (§25.7's amendment).
					when: kind === "constraint" ? undefined : (m.when ?? "present"),
				};
			}),
		});
	}
	return out;
}

/** Name -> resolved constraint, for the nesting walks below. */
export function constraintIndex(
	resolved: readonly ResolvedConstraint[],
): ReadonlyMap<string, ResolvedConstraint> {
	return new Map(resolved.map((c) => [c.name, c]));
}

// --- Rendering (§12.15's member rule) ---

/**
 * How a member's name is spelled in a sentence.
 *
 * - `cli` -- the command-line token (`--old-name`, bare `targets`), which is
 *   what a parse error and the help block use, help being the command-line
 *   surface;
 * - `property` -- the schema's property name (underscored), which is what the
 *   MCP description block uses, the caller there writing keys rather than
 *   argv (§26.12).
 */
export type MemberStyle = "cli" | "property";

/** The connector a family joins its own operands with, inside a parent's line. */
function connectorOf(kind: ResolvedCoOccurrence["kind"]): string {
	return kind === "all-or-none" ? " with " : " or ";
}

/**
 * One member, rendered STRUCTURALLY rather than nominally: a nested member
 * renders its own operands in parentheses and never its name. The
 * constraint's name identifies the rule that failed and appears once, in the
 * prefix; a member list names tokens the reader can act on (§12.15).
 */
export function renderMember(
	m: ResolvedMember,
	index: ReadonlyMap<string, ResolvedConstraint>,
	style: MemberStyle,
): string {
	if (m.kind === "flag") {
		return style === "cli" ? `--${m.name}` : flagParamName(m.name);
	}
	if (m.kind === "arg") {
		return m.name;
	}
	const nested = index.get(m.name);
	if (nested === undefined || !isCoOccurrenceResolved(nested)) {
		return m.name;
	}
	const inner = nested.members
		.map((sub) => renderMember(sub, index, style))
		.join(connectorOf(nested.kind));
	return `(${inner})`;
}

/** A member LIST: unquoted, joined by `, `, in declaration order (§12.15). */
export function renderMembers(
	members: readonly ResolvedMember[],
	index: ReadonlyMap<string, ResolvedConstraint>,
	style: MemberStyle,
): string {
	return members.map((m) => renderMember(m, index, style)).join(", ");
}

/**
 * The per-family sentence the HELP block renders, in CLI tokens because help
 * is the command-line surface (§26.10). `implies` renders `--no-<implies>`
 * when the declared value is false -- the negation spelling its own violation
 * sentence already uses; no `=true` spelling is invented.
 */
export function helpSentence(
	c: ResolvedConstraint,
	index: ReadonlyMap<string, ResolvedConstraint>,
): string {
	switch (c.kind) {
		case "at-least-one":
			return `at least one of ${renderMembers(c.members, index, "cli")}`;
		case "all-or-none":
			return `all or none of ${renderMembers(c.members, index, "cli")}`;
		case "requires":
			return `--${c.flag} requires --${c.dependsOn}`;
		default:
			return `--${c.flag} implies --${c.value ? "" : "no-"}${c.implies}`;
	}
}

/**
 * The per-family sentence the MCP description block renders, in PROPERTY
 * names -- the caller there writes keys, not argv (§26.12). The two
 * co-occurrence families take the pinned `<family> of: <members>` form.
 */
export function mcpSentence(
	c: ResolvedConstraint,
	index: ReadonlyMap<string, ResolvedConstraint>,
): string {
	switch (c.kind) {
		case "at-least-one":
			return `at least one of: ${renderMembers(c.members, index, "property")}`;
		case "all-or-none":
			return `all or none of: ${renderMembers(c.members, index, "property")}`;
		case "requires":
			return `${flagParamName(c.flag)} requires ${flagParamName(c.dependsOn)}`;
		default:
			return `${flagParamName(c.flag)} implies ${flagParamName(c.implies)} = ${c.value}`;
	}
}

// --- Evaluation (§26.4) ---

/** Answers whether one flag or arg member's election selector fires. */
export type EngagementProbe = (m: ResolvedMember) => boolean;

/**
 * A flag or arg member is engaged iff its `when` selector fires; a nested
 * constraint member is engaged iff at least one of ITS members is. Engagement
 * propagates upward; satisfaction does not (§26.4).
 */
export function isEngaged(
	m: ResolvedMember,
	index: ReadonlyMap<string, ResolvedConstraint>,
	probe: EngagementProbe,
): boolean {
	if (m.kind !== "constraint") {
		return probe(m);
	}
	const nested = index.get(m.name);
	if (nested === undefined || !isCoOccurrenceResolved(nested)) {
		return false;
	}
	return nested.members.some((sub) => isEngaged(sub, index, probe));
}

/** The declaration surface's own union, re-exported for the consumers. */
export type { AllOrNone, AtLeastOne, Constraint };
