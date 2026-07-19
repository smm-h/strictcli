/**
 * The auto-registered `check` command plus the human/JSON result formatters.
 *
 * Parity sources: go/strictcli/check_cmd.go and check_public.go (formatters)
 * with Python _register_check_command / _check_list_mode /
 * _check_dry_run_mode / format_check_results (~3419-3517, ~7092-7212) as the
 * divergence ground truth for the branch order (list -> help-when-unfiltered
 * -> no-match -> dry-run -> run) and the inline output strings.
 *
 * Errors raised below the handler (tag DSL, cycles, provider
 * materialization) propagate out of run()/test(), mirroring Python where
 * they surface as ValueError to the caller.
 */

import type { AppImpl } from "../app.js";
import type { Context } from "../context.js";
import {
	type AnyCommand,
	type AnyFlag,
	defineCommand,
	flag,
} from "../factories.js";
import { formatCommandHelp } from "../help.js";
import { t } from "../types.js";
import type {
	CheckDef,
	CheckRunResult,
	CheckStatus,
	ChecksState,
} from "./framework.js";
import { orderedProblems, sortedCheckNames } from "./framework.js";
import { materializeCheckProviders } from "./provider.js";
import {
	checkIsPure,
	filterChecks,
	resolveCheckOrder,
	runOrderedChecks,
} from "./runner.js";

/**
 * Turns on the check system exactly once: flips enabled and registers the
 * auto-generated `check` command a single time. Idempotent -- calling it
 * again is a no-op, which prevents double-registration. The command is
 * absent (hidden) entirely when checks are never enabled.
 */
export function enableChecks(app: AppImpl): void {
	if (app.checks.enabled) {
		return;
	}
	app.checks.enabled = true;
	registerCheckCommand(app);
}

/** Registers the auto-generated `check` command (called from enableChecks). */
function registerCheckCommand(app: AppImpl): void {
	const candidates: AnyFlag[] = [
		flag("all", t.bool, {
			help: "Run every registered check regardless of tag or name filters",
			default: false,
		}),
		flag("tag", t.str, {
			help: "Tag DSL expression to select checks (e.g. 'changelog & !quality')",
			default: "",
		}),
		flag("name", t.str, {
			help: "Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*')",
			default: "",
		}),
		flag("list", t.bool, {
			help: "List all registered checks with their tags and exit without running",
			default: false,
		}),
		flag("json", t.bool, {
			help: "Output check results as machine-readable JSON instead of human text",
			default: false,
		}),
		flag("ignore-warnings", t.bool, {
			help: "Treat warn-severity results as passing so they do not cause nonzero exit",
			default: false,
		}),
		flag("verbose", t.bool, {
			help: "Show per-check notes and durations (including on passing checks) plus a trailing pass/fail/warn/skip count summary",
			default: false,
		}),
		flag("dry-run", t.bool, {
			help: "Show which checks would run based on current filters without executing them",
			default: false,
		}),
	];
	// Candidates colliding with global flags are dropped -- the handler
	// receives the global flag's value for that key instead (Python parity).
	const flags: Record<string, AnyFlag> = {};
	for (const f of candidates) {
		if (!app.globalFlagNames.has(f.name)) {
			flags[f.name.replaceAll("-", "_")] = f;
		}
	}

	const def = defineCommand("check", {
		help: "Run project checks registered via the check framework and report results",
		flags,
		handler: (args, ctx) =>
			checkHandler(app, args as Record<string, unknown>, ctx),
	}) as AnyCommand;

	app.commands.set("check", {
		kind: "command",
		name: "check",
		help: def.help,
		def,
		flags: def.allFlags,
		tags: [],
		hidden: false,
		configFields: [],
	});
}

async function checkHandler(
	app: AppImpl,
	kwargs: Record<string, unknown>,
	ctx: Context,
): Promise<number> {
	// Materialize provider-sourced checks before any registry read (covers
	// the list, dry-run, and execution branches below).
	materializeCheckProviders(app.checks);

	const runAll = kwargs.all === true;
	const listMode = kwargs.list === true;
	const jsonOut = kwargs.json === true;
	const ignoreWarnings = kwargs.ignore_warnings === true;
	const verbose = kwargs.verbose === true;
	const dryRun = kwargs.dry_run === true;
	// Treat empty strings as "not provided".
	const tagRaw = typeof kwargs.tag === "string" ? kwargs.tag : "";
	const nameRaw = typeof kwargs.name === "string" ? kwargs.name : "";
	const tagExpr = tagRaw !== "" ? tagRaw : undefined;
	const nameGlob = nameRaw !== "" ? nameRaw : undefined;

	if (listMode) {
		checkListMode(app.checks, jsonOut, ctx);
		return 0;
	}

	const hasFilter = runAll || tagExpr !== undefined || nameGlob !== undefined;
	if (!hasFilter) {
		// No flags: show help for the check command.
		const cmd = app.commands.get("check");
		if (cmd !== undefined) {
			ctx.info(formatCommandHelp(app, cmd, ""));
		}
		return 0;
	}

	const selected = filterChecks(app.checks.defs, tagExpr, nameGlob, runAll);
	if (selected.size === 0) {
		ctx.info("No checks matched the given filters.");
		return 0;
	}
	const order = resolveCheckOrder(app.checks.defs, selected);

	if (dryRun) {
		checkDryRunMode(app.checks.defs, order, ctx);
		return 0;
	}

	// Execution mode: need a context.
	if (app.checks.contextFactory === undefined) {
		ctx.error(
			"error: no check context configured. " +
				"Call app.setCheckContext(factory) before running.",
		);
		return 1;
	}
	const context = app.checks.contextFactory();
	// The check command executes all selected checks; the purity partition is
	// an API-only mode (runChecks pureOnly), so nothing is ever listed here.
	const { results, exitCode } = await runOrderedChecks(
		app.checks.defs,
		order,
		context,
		ignoreWarnings,
		false,
	);

	if (jsonOut) {
		ctx.info(formatCheckResultsJSON(results));
	} else {
		const output = formatCheckResults(results, verbose);
		if (output !== "") {
			ctx.info(output);
		}
	}
	return exitCode;
}

/** The --list mode: check listing in human or JSON format. */
function checkListMode(
	state: ChecksState,
	jsonMode: boolean,
	ctx: Context,
): void {
	const names = sortedCheckNames(state);
	const sortedDefs = names.map((n) => state.defs.get(n) as CheckDef);

	if (jsonMode) {
		const items = sortedDefs.map((def) => ({
			name: def.name,
			tags: def.tags,
			severity: def.severity,
			// Scope is emitted only when non-empty (omitempty parity).
			...(def.scope !== "" ? { scope: def.scope } : {}),
		}));
		ctx.info(JSON.stringify(items));
		return;
	}

	if (sortedDefs.length === 0) {
		ctx.info("No checks defined.");
		return;
	}

	let nameWidth = "NAME".length;
	let tagsWidth = "TAGS".length;
	for (const def of sortedDefs) {
		nameWidth = Math.max(nameWidth, def.name.length);
		tagsWidth = Math.max(tagsWidth, def.tags.join(", ").length);
	}
	const lines = [
		`${"NAME".padEnd(nameWidth)}   ${"TAGS".padEnd(tagsWidth)}   SEVERITY`,
	];
	for (const def of sortedDefs) {
		const tagsStr = def.tags.join(", ");
		lines.push(
			`${def.name.padEnd(nameWidth)}   ${tagsStr.padEnd(tagsWidth)}   ${def.severity}`,
		);
	}
	ctx.info(lines.join("\n"));
}

/** The --dry-run mode: prints the execution plan without running checks. */
function checkDryRunMode(
	defs: ReadonlyMap<string, CheckDef>,
	order: readonly string[],
	ctx: Context,
): void {
	const noun = order.length === 1 ? "check" : "checks";
	const lines = [`Would run ${order.length} ${noun}:`];
	const inOrder = new Set(order);
	order.forEach((name, i) => {
		const def = defs.get(name) as CheckDef;
		const purity = checkIsPure(def) ? "pure" : "impure";
		const deps = def.dependsOn.filter((d) => inOrder.has(d));
		if (deps.length > 0) {
			lines.push(
				`  ${i + 1}. ${name} (depends on: ${deps.join(", ")}) [${purity}]`,
			);
		} else {
			lines.push(`  ${i + 1}. ${name} [${purity}]`);
		}
	});
	ctx.info(lines.join("\n"));
}

const STATUS_LABELS: Readonly<Record<CheckStatus, string>> = {
	pass: "PASS",
	fail: "FAIL",
	warn: "WARN",
	skip: "SKIP",
};

/**
 * Formats check results as a human-readable aligned string. Shows the
 * derived status label, name, and message, with minted problems listed under
 * the check row grouped by severity (error problems first, then warns), each
 * tagged with its severity. Problems appear for fail/warn/skip outcomes or
 * when verbose. Notes are verdict-inert and surface ONLY under verbose, on
 * every outcome including a pass; verbose also appends per-check durations
 * ("(<n>ms)") and a trailing count summary. No trailing newline.
 */
export function formatCheckResults(
	results: readonly CheckRunResult[],
	verbose = false,
): string {
	if (results.length === 0) {
		return "";
	}

	let nameWidth = 0;
	for (const r of results) {
		nameWidth = Math.max(nameWidth, r.name.length);
	}

	const lines: string[] = [];
	const counts: Record<CheckStatus, number> = {
		pass: 0,
		fail: 0,
		warn: 0,
		skip: 0,
	};

	for (const r of results) {
		const status = r.status;
		counts[status]++;
		let row = `${STATUS_LABELS[status]}  ${r.name.padEnd(nameWidth)}    ${r.message}`;
		if (verbose) {
			row += ` (${r.durationMs}ms)`;
		}
		lines.push(row);

		const showProblems =
			verbose || status === "fail" || status === "warn" || status === "skip";
		if (showProblems) {
			for (const p of orderedProblems(r.outcome)) {
				lines.push(`        [${p.severity}] ${p.text}`);
			}
		}
		if (verbose) {
			for (const n of r.notes) {
				lines.push(`        [note] ${n}`);
			}
		}
	}

	if (verbose) {
		lines.push("");
		lines.push(
			`${counts.pass} passed / ${counts.fail} failed / ` +
				`${counts.warn} warned / ${counts.skip} skipped`,
		);
	}

	return lines.join("\n");
}

/**
 * Formats check results as a compact JSON array string. Each entry carries
 * the derived status plus the minted problems (each with its severity and
 * text); problems and notes serialize as [] when empty, and duration_ms is
 * always present. No trailing newline.
 */
export function formatCheckResultsJSON(
	results: readonly CheckRunResult[],
): string {
	const items = results.map((r) => ({
		name: r.name,
		status: r.status,
		message: r.message,
		problems: r.problems.map((p) => ({ severity: p.severity, text: p.text })),
		notes: [...r.notes],
		duration_ms: r.durationMs,
	}));
	return JSON.stringify(items);
}
