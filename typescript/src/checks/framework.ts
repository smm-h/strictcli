/**
 * Check framework core: sealed outcomes, reporters, definitions, checks.toml
 * parsing, and the registration/double-entry machinery.
 *
 * Parity sources: go/strictcli/check.go (structure and templates) with
 * python/strictcli/__init__.py (~1145-1283, ~2312-2600, ~3025-3100) as the
 * divergence ground truth. The scope field is PARSE-ONLY (matching Go): it is
 * carried on definitions and emitted in schema/list output, but never
 * consulted at run time -- there is no scope adapter and no SkipCheck in TS.
 */

import {
	errCannotRegisterCheckNotDeclared,
	errCannotRegisterCheckNotEnabled,
	errCheckDuplicateRegistration,
	errCheckOutcomeDirectConstruction,
	errCheckSeverityMismatch,
	errChecksTomlAppNotString,
	errChecksTomlBoolFieldInvalid,
	errChecksTomlCheckMustBeTable,
	errChecksTomlChecksMustBeTable,
	errChecksTomlDependsOnEntriesMustBeStrings,
	errChecksTomlDependsOnMustBeStrings,
	errChecksTomlDependsOnUnknown,
	errChecksTomlInvalidCheckName,
	errChecksTomlMissingApp,
	errChecksTomlMissingField,
	errChecksTomlParse,
	errChecksTomlScopeMustBeString,
	errChecksTomlSeverityInvalid,
	errChecksTomlTagsEntriesMustBeStrings,
	errChecksTomlTagsMustBeStrings,
	errChecksTomlUnknownField,
	errChecksTomlUnknownTopLevelKey,
	errDuplicateCheckDef,
	errFoundNoProblems,
	errNoteTextEmpty,
	errOutcomeMessageEmpty,
	errPassedWithProblems,
	errProblemTextEmpty,
	errSkippedWithProblems,
	errSkipReasonEmpty,
	errUnknownCheckOutcomeKind,
	RegistrationError,
} from "../errors.js";
import { parseTomlConfig, TomlLoadFailure } from "../toml.js";
import type { CheckSpec } from "./provider.js";

// --- Public contract types ---

/** Minimal interface that tool-specific check contexts must satisfy. */
export interface CheckContext {
	readonly projectRoot: string;
}

export type CheckSeverity = "error" | "warn";

/** A single minted finding: text plus severity ("error" or "warn"). */
export interface CheckProblem {
	readonly severity: CheckSeverity;
	readonly text: string;
}

// Module-private mint token: a CheckOutcome can be constructed only by code
// that holds this token (the reporters and the runner's internal skip mint).
// This is the seal that makes forging an outcome directly impossible.
const MINT_TOKEN = Symbol("strictcli.checks.mint");

/**
 * The ceiling-typed result of a check implementation. Sealed by construction:
 * a valid outcome is obtained ONLY through reporter methods
 * (passed/skipped/found) or the runner's internal skip mint, both of which
 * pass the module-private mint token. Direct construction throws.
 */
export class CheckOutcome {
	readonly kind: "passed" | "skipped" | "found";
	readonly message: string;
	readonly problems: readonly CheckProblem[];
	/**
	 * Informational, verdict-inert channel: notes are recorded unconditionally
	 * on ANY outcome (including a pass) via reporter.note. They are PROVABLY
	 * inert -- excluded from status derivation, gating, problem ordering, and
	 * exit codes. They surface only under --verbose and in JSON.
	 */
	readonly notes: readonly string[];

	constructor(
		token: symbol,
		kind: "passed" | "skipped" | "found",
		message: string,
		problems: readonly CheckProblem[],
		notes: readonly string[],
	) {
		if (token !== MINT_TOKEN) {
			throw new Error(errCheckOutcomeDirectConstruction());
		}
		this.kind = kind;
		this.message = message;
		this.problems = problems;
		this.notes = notes;
	}
}

/** Runner-internal mint for cascade-skip outcomes (not part of the public API). */
export function mintSkip(message: string): CheckOutcome {
	return new CheckOutcome(MINT_TOKEN, "skipped", message, [], []);
}

/**
 * Problems grouped by severity: all error-severity problems first, then all
 * warn-severity problems. Insertion order is preserved within each group.
 */
export function orderedProblems(o: CheckOutcome): readonly CheckProblem[] {
	const errs = o.problems.filter((p) => p.severity === "error");
	const warns = o.problems.filter((p) => p.severity === "warn");
	return [...errs, ...warns];
}

/**
 * Maps a minted CheckOutcome to a display/verdict label. found + any
 * error-severity problem => "fail"; found + only warns => "warn";
 * passed => "pass"; skipped => "skip".
 */
export function deriveStatus(o: CheckOutcome): CheckStatus {
	switch (o.kind) {
		case "passed":
			return "pass";
		case "skipped":
			return "skip";
		case "found":
			return o.problems.some((p) => p.severity === "error") ? "fail" : "warn";
		default:
			// Defensive: outcomes are only ever minted with one of the three
			// kinds above (mirrors the Go panic / Python ValueError).
			throw new Error(errUnknownCheckOutcomeKind(o.kind));
	}
}

export type CheckStatus = "pass" | "fail" | "warn" | "skip";

// --- Reporters ---

function requireNonEmptyText(text: string, template: () => string): void {
	if (typeof text !== "string" || text.trim() === "") {
		throw new Error(template());
	}
}

/**
 * Shared problem accumulator and minting surface for both reporters. Holds
 * note/warn/passed/skipped/found. Error-minting lives ONLY on ErrorReporter,
 * so WarnReporter structurally lacks it (calling .error on a WarnReporter is
 * a type error and a runtime TypeError).
 */
class ReporterCore {
	protected readonly problems: CheckProblem[] = [];
	// Notes accumulate informational messages recorded via note(). They are
	// carried onto the minted outcome but never influence status, gating, or
	// exit codes -- a verdict-inert reporting channel.
	protected readonly notes: string[] = [];

	/**
	 * Records an informational note. Non-empty text required. Notes are
	 * allowed on EVERY outcome, including a pass -- they never trigger the
	 * problems-present errors that passed()/skipped() enforce.
	 */
	note(text: string): void {
		requireNonEmptyText(text, errNoteTextEmpty);
		this.notes.push(text);
	}

	/** Mints a warn-severity problem. Non-empty text required. */
	warn(text: string): void {
		requireNonEmptyText(text, errProblemTextEmpty);
		this.problems.push({ severity: "warn", text });
	}

	/** Finalizes a terminal PASS. Errors if any problems were reported. */
	passed(message: string): CheckOutcome {
		requireNonEmptyText(message, errOutcomeMessageEmpty);
		if (this.problems.length > 0) {
			throw new Error(errPassedWithProblems());
		}
		return new CheckOutcome(MINT_TOKEN, "passed", message, [], [...this.notes]);
	}

	/** Finalizes a terminal SKIP. Errors if any problems were reported. */
	skipped(reason: string): CheckOutcome {
		requireNonEmptyText(reason, errSkipReasonEmpty);
		if (this.problems.length > 0) {
			throw new Error(errSkippedWithProblems());
		}
		return new CheckOutcome(MINT_TOKEN, "skipped", reason, [], [...this.notes]);
	}

	/**
	 * Finalizes an outcome carrying the accumulated problems. Errors when no
	 * problems were accumulated (nothing found means pass -- say so explicitly
	 * with passed()).
	 */
	found(message: string): CheckOutcome {
		requireNonEmptyText(message, errOutcomeMessageEmpty);
		if (this.problems.length === 0) {
			throw new Error(errFoundNoProblems());
		}
		return new CheckOutcome(
			MINT_TOKEN,
			"found",
			message,
			[...this.problems],
			[...this.notes],
		);
	}
}

/**
 * Reporter handed to warn-severity check impls. It can mint warn-severity
 * problems and terminal outcomes but structurally LACKS error-minting: there
 * is no error method in its surface, so a warn check cannot produce an
 * error-severity problem and can never cascade.
 */
export class WarnReporter extends ReporterCore {}

/**
 * Reporter handed to error-severity check impls. Everything WarnReporter has
 * PLUS error() (mints an error-severity problem).
 */
export class ErrorReporter extends ReporterCore {
	/** Mints an error-severity problem. Non-empty text required. */
	error(text: string): void {
		requireNonEmptyText(text, errProblemTextEmpty);
		this.problems.push({ severity: "error", text });
	}
}

// --- Run results ---

/**
 * A named check outcome returned by app.runChecks(). The verdict is derived
 * from the minted outcome; the runner's exit/cascade logic and the formatters
 * all consume these same accessors (one source of truth).
 */
export class CheckRunResult {
	constructor(
		readonly name: string,
		readonly outcome: CheckOutcome,
		/**
		 * Wall-clock time in integer milliseconds spent inside the check impl.
		 * Captured around the impl call only; checks that never execute
		 * (cascade-skipped) carry 0. Purely informational -- never affects
		 * status or exit codes.
		 */
		readonly durationMs: number = 0,
	) {}

	/** Derived label: "pass", "fail", "warn", or "skip". */
	get status(): CheckStatus {
		return deriveStatus(this.outcome);
	}

	get message(): string {
		return this.outcome.message;
	}

	get problems(): readonly CheckProblem[] {
		return this.outcome.problems;
	}

	get notes(): readonly string[] {
		return this.outcome.notes;
	}

	/** Whether the outcome carries an error-severity problem (derived FAIL). */
	gated(): boolean {
		return this.status === "fail";
	}

	/** Whether the outcome carries only warn-severity problems (derived WARN). */
	warned(): boolean {
		return this.status === "warn";
	}
}

// --- Definitions and registry state ---

/** A check impl wrapped with its reporter, installed at registration time. */
export type CheckImpl = (
	ctx: CheckContext,
) => CheckOutcome | Promise<CheckOutcome>;

/** Internal definition of a single check loaded from checks.toml. */
export interface CheckDef {
	readonly name: string;
	readonly tags: readonly string[];
	readonly severity: CheckSeverity;
	readonly fast: boolean;
	readonly pure: boolean;
	readonly needsNetwork: boolean;
	readonly dependsOn: readonly string[];
	/** Optional, defaults to "". Parse-only: carried but never consulted at run time. */
	readonly scope: string;
	impl: CheckImpl | undefined;
	implForm: CheckSeverity | "";
}

/** Per-app check-system state, held by AppImpl. */
export interface ChecksState {
	enabled: boolean;
	readonly defs: Map<string, CheckDef>;
	contextFactory: (() => CheckContext) | undefined;
	// Check-provider hook state. Providers populate the registry lazily at
	// the first registry read (materialization), memoized per cwd.
	readonly providers: Array<() => readonly CheckSpec[] | undefined>;
	readonly providerSourcedNames: Set<string>;
	providerMaterializedCwd: string | undefined;
}

export function newChecksState(): ChecksState {
	return {
		enabled: false,
		defs: new Map(),
		contextFactory: undefined,
		providers: [],
		providerSourcedNames: new Set(),
		providerMaterializedCwd: undefined,
	};
}

/**
 * Single internal insertion point for check definitions. Rejects duplicate
 * names as a hard error. TOML loading and provider materialization both
 * route through here.
 */
export function addCheckDef(state: ChecksState, def: CheckDef): void {
	if (state.defs.has(def.name)) {
		throw new RegistrationError(errDuplicateCheckDef(def.name));
	}
	state.defs.set(def.name, def);
}

/** Check names in sorted order, for deterministic listing. */
export function sortedCheckNames(state: ChecksState): string[] {
	return [...state.defs.keys()].sort();
}

/**
 * Single registration chokepoint shared by app.errorCheck and app.warnCheck.
 * Enforces the double-entry contract (declared vs registered) and
 * cross-checks the registration FORM against the TOML-declared severity so
 * that app.errorCheck on a severity="warn" definition is a hard error.
 */
export function registerCheckImpl(
	state: ChecksState,
	name: string,
	form: CheckSeverity,
	run: CheckImpl,
): void {
	if (!state.enabled) {
		throw new RegistrationError(errCannotRegisterCheckNotEnabled(name));
	}
	const def = state.defs.get(name);
	if (def === undefined) {
		throw new RegistrationError(errCannotRegisterCheckNotDeclared(name));
	}
	if (def.impl !== undefined) {
		throw new RegistrationError(errCheckDuplicateRegistration(name));
	}
	if (def.severity !== form) {
		const used = form === "error" ? "app.errorCheck" : "app.warnCheck";
		const want = form === "error" ? "app.warnCheck" : "app.errorCheck";
		throw new RegistrationError(
			errCheckSeverityMismatch(name, def.severity, used, want),
		);
	}
	def.impl = run;
	def.implForm = form;
}

/**
 * Validates that all declared checks have registered implementations.
 * Returns an error message listing unregistered checks, or undefined.
 * (Inline string in both siblings, so it stays inline here too.)
 */
export function validateCheckRegistrations(
	state: ChecksState,
): string | undefined {
	if (!state.enabled) {
		return undefined;
	}
	const missing = [...state.defs.values()]
		.filter((def) => def.impl === undefined)
		.map((def) => def.name)
		.sort();
	if (missing.length === 0) {
		return undefined;
	}
	return `checks declared in checks.toml but not registered: ${missing.join(", ")}`;
}

// --- checks.toml parsing ---

/** Validates identifier names (check names, tag names). */
export const CHECK_IDENTIFIER_RE = /^[a-z][a-z0-9-]*$/;

/** Allowed fields in a check definition table. */
const KNOWN_CHECK_FIELDS: ReadonlySet<string> = new Set([
	"tags",
	"severity",
	"fast",
	"pure",
	"needs_network",
	"depends_on",
	"scope",
]);

/** Required fields, checked for presence in sorted order (Python parity). */
const REQUIRED_CHECK_FIELDS: readonly string[] = [
	"depends_on",
	"fast",
	"needs_network",
	"pure",
	"severity",
	"tags",
];

export interface ParsedChecksToml {
	readonly appName: string;
	readonly defs: Map<string, CheckDef>;
	/** Check names in [checks] declaration order. */
	readonly order: readonly string[];
}

/** A TOML table value: a plain decoded object (not an array/date/scalar). */
function isTomlTable(v: unknown): v is Record<string, unknown> {
	return (
		typeof v === "object" &&
		v !== null &&
		!Array.isArray(v) &&
		!(v instanceof Date)
	);
}

/**
 * Python-compatible type name for a decoded TOML value (matches Go's
 * tomlTypeName / Python's type(val).__name__ for cross-language parity).
 */
function tomlTypeName(v: unknown): string {
	if (typeof v === "boolean") {
		return "bool";
	}
	if (typeof v === "bigint") {
		return "int";
	}
	if (typeof v === "number") {
		return "float";
	}
	if (typeof v === "string") {
		return "str";
	}
	if (Array.isArray(v)) {
		return "list";
	}
	if (v instanceof Date) {
		return "datetime";
	}
	if (v === null || v === undefined) {
		return "NoneType";
	}
	return "dict";
}

/** Display form for a "severity" slot: strings verbatim, others stringified. */
function severityDisplay(v: unknown): string {
	return typeof v === "string" ? v : String(v);
}

/**
 * Parses and validates checks TOML text, returning the app name, validated
 * check definitions, and names in declaration order. Throws
 * RegistrationError (the ValueError analog) on any schema violation or
 * invalid TOML. Validation order follows Python (_parse_checks_toml).
 */
export function parseChecksToml(text: string): ParsedChecksToml {
	let parsed: Record<string, unknown>;
	try {
		parsed = parseTomlConfig(text);
	} catch (e) {
		if (e instanceof TomlLoadFailure) {
			const pos =
				e.line !== undefined ? ` (at line ${e.line}, column ${e.column})` : "";
			throw new RegistrationError(errChecksTomlParse(`${e.message}${pos}`));
		}
		throw e;
	}

	// Only "app" and [checks] are allowed at the top level.
	for (const key of Object.keys(parsed)) {
		if (key !== "app" && key !== "checks") {
			throw new RegistrationError(errChecksTomlUnknownTopLevelKey(key));
		}
	}

	// Required "app" field.
	if (!Object.hasOwn(parsed, "app")) {
		throw new RegistrationError(errChecksTomlMissingApp());
	}
	const appRaw = parsed.app;
	if (typeof appRaw !== "string" || appRaw === "") {
		throw new RegistrationError(errChecksTomlAppNotString());
	}
	const appName = appRaw;

	// A file with just app = "x" is valid -- the [checks] section is optional.
	if (!Object.hasOwn(parsed, "checks")) {
		return { appName, defs: new Map(), order: [] };
	}
	const checksRaw = parsed.checks;
	if (!isTomlTable(checksRaw)) {
		throw new RegistrationError(errChecksTomlChecksMustBeTable());
	}

	const defs = new Map<string, CheckDef>();
	const order: string[] = [];

	for (const [name, fieldsRaw] of Object.entries(checksRaw)) {
		if (!CHECK_IDENTIFIER_RE.test(name)) {
			throw new RegistrationError(errChecksTomlInvalidCheckName(name));
		}
		if (!isTomlTable(fieldsRaw)) {
			throw new RegistrationError(errChecksTomlCheckMustBeTable(name));
		}
		const fields = fieldsRaw;

		// Unknown fields: report the alphabetically-first one (Python parity).
		const unknown = Object.keys(fields)
			.filter((f) => !KNOWN_CHECK_FIELDS.has(f))
			.sort();
		if (unknown.length > 0) {
			throw new RegistrationError(
				errChecksTomlUnknownField(name, unknown[0] as string),
			);
		}

		// Required fields, presence checked in sorted order (Python parity).
		for (const req of REQUIRED_CHECK_FIELDS) {
			if (!Object.hasOwn(fields, req)) {
				throw new RegistrationError(errChecksTomlMissingField(name, req));
			}
		}

		// tags: list of non-empty strings (may be empty).
		const tagsRaw = fields.tags;
		if (!Array.isArray(tagsRaw)) {
			throw new RegistrationError(errChecksTomlTagsMustBeStrings(name));
		}
		const tags: string[] = [];
		for (const tag of tagsRaw) {
			if (typeof tag !== "string" || tag.trim() === "") {
				throw new RegistrationError(
					errChecksTomlTagsEntriesMustBeStrings(name),
				);
			}
			tags.push(tag);
		}

		// severity: "error" or "warn".
		const severityRaw = fields.severity;
		if (severityRaw !== "error" && severityRaw !== "warn") {
			throw new RegistrationError(
				errChecksTomlSeverityInvalid(name, severityDisplay(severityRaw)),
			);
		}

		// fast / pure / needs_network: booleans.
		const bools: Record<string, boolean> = {};
		for (const boolField of ["fast", "pure", "needs_network"]) {
			const raw = fields[boolField];
			if (typeof raw !== "boolean") {
				throw new RegistrationError(
					errChecksTomlBoolFieldInvalid(name, boolField, tomlTypeName(raw)),
				);
			}
			bools[boolField] = raw;
		}

		// depends_on: list of strings (may be empty).
		const dependsOnRaw = fields.depends_on;
		if (!Array.isArray(dependsOnRaw)) {
			throw new RegistrationError(errChecksTomlDependsOnMustBeStrings(name));
		}
		const dependsOn: string[] = [];
		for (const dep of dependsOnRaw) {
			if (typeof dep !== "string") {
				throw new RegistrationError(
					errChecksTomlDependsOnEntriesMustBeStrings(name),
				);
			}
			dependsOn.push(dep);
		}

		// scope: optional string, defaults to "" (parse-only field).
		let scope = "";
		if (Object.hasOwn(fields, "scope")) {
			const scopeRaw = fields.scope;
			if (typeof scopeRaw !== "string") {
				throw new RegistrationError(
					errChecksTomlScopeMustBeString(name, tomlTypeName(scopeRaw)),
				);
			}
			scope = scopeRaw;
		}

		defs.set(name, {
			name,
			tags,
			severity: severityRaw,
			fast: bools.fast as boolean,
			pure: bools.pure as boolean,
			needsNetwork: bools.needs_network as boolean,
			dependsOn,
			scope,
			impl: undefined,
			implForm: "",
		});
		order.push(name);
	}

	// Cross-validate depends_on references.
	for (const name of order) {
		const def = defs.get(name) as CheckDef;
		for (const dep of def.dependsOn) {
			if (!defs.has(dep)) {
				throw new RegistrationError(errChecksTomlDependsOnUnknown(name, dep));
			}
		}
	}

	return { appName, defs, order };
}
