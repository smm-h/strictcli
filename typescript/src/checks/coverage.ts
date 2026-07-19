/**
 * CLI test-coverage instrumentation: per-process shard files recording which
 * commands app.test() exercised, plus the built-in cli-test-coverage check
 * provider that merges shards into the canonical manifest and compares the
 * result against the app's full command surface.
 *
 * Parity sources: go/strictcli/coverage.go with Python _record_coverage /
 * _collect_all_command_paths / _test_coverage_provider (~2801-2934) as the
 * divergence ground truth.
 */

import {
	appendFileSync,
	existsSync,
	mkdirSync,
	readdirSync,
	readFileSync,
	writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import type { AppImpl, GroupImpl } from "../app.js";
import {
	errTestCoverageCannotCreateDir,
	RegistrationError,
} from "../errors.js";
import type { CheckSpec } from "./provider.js";
import { errorCheckSpec } from "./provider.js";

const COVERAGE_DIR = join(".strictcli", "coverage");
const MANIFEST_PATH = join(".strictcli", "test-coverage.json");

/**
 * Enables test-coverage instrumentation on an app: computes the per-process
 * shard path template, creates the shard directory eagerly (a failure here
 * is a hard construction error), and registers the built-in
 * cli-test-coverage provider.
 */
export function initTestCoverage(app: AppImpl): void {
	app.coverageShardPath = join(COVERAGE_DIR, `${process.pid}-{n}.jsonl`);
	try {
		mkdirSync(COVERAGE_DIR, { recursive: true });
	} catch (e) {
		throw new RegistrationError(
			errTestCoverageCannotCreateDir((e as Error).message),
		);
	}
	app.registerCheckProvider(testCoverageProvider(app));
}

/**
 * Appends a coverage record for the resolved command path. Each test()
 * invocation writes one JSONL line to a per-process shard file.
 */
export function recordCoverage(app: AppImpl, cmdPath: string): void {
	if (!app.testCoverage || app.coverageShardPath === undefined) {
		return;
	}
	const path = app.coverageShardPath.replace(
		"{n}",
		String(app.coverageCounter),
	);
	mkdirSync(dirname(path), { recursive: true });
	appendFileSync(path, `${JSON.stringify({ command: cmdPath })}\n`);
}

/**
 * Enumerates all non-deprecated leaf command paths as dot-separated strings
 * (e.g. "deploy", "infra.deploy").
 */
export function collectAllCommandPaths(app: AppImpl): Set<string> {
	const paths = new Set<string>();
	for (const name of app.commands.keys()) {
		paths.add(name);
	}
	const walkGroup = (grp: GroupImpl, prefix: readonly string[]): void => {
		for (const cmdName of grp.commands.keys()) {
			paths.add([...prefix, cmdName].join("."));
		}
		for (const [subName, subGrp] of grp.groups) {
			walkGroup(subGrp, [...prefix, subName]);
		}
	};
	for (const [groupName, grp] of app.groups) {
		walkGroup(grp, [groupName]);
	}
	return paths;
}

/**
 * The built-in check provider for cli-test-coverage, auto-registered when
 * the app enables testCoverage. Merges per-process shard files into the
 * canonical sorted manifest and hard-FAILs listing every command with zero
 * coverage (excluding the framework-injected check command).
 */
export function testCoverageProvider(app: AppImpl): () => CheckSpec[] {
	return () => [
		errorCheckSpec({
			name: "cli-test-coverage",
			tags: ["test"],
			fast: true,
			pure: true,
			needsNetwork: false,
			dependsOn: [],
			impl: (_ctx, reporter) => {
				// Merge shards.
				const covered = new Set<string>();
				if (existsSync(COVERAGE_DIR)) {
					for (const fname of readdirSync(COVERAGE_DIR)) {
						if (!fname.endsWith(".jsonl")) {
							continue;
						}
						const content = readFileSync(join(COVERAGE_DIR, fname), "utf8");
						for (const rawLine of content.split("\n")) {
							const line = rawLine.trim();
							if (line === "") {
								continue;
							}
							const entry = JSON.parse(line) as Record<string, unknown>;
							if (typeof entry.command === "string") {
								covered.add(entry.command);
							}
						}
					}
				}

				if (covered.size === 0) {
					reporter.error("stale or empty manifest");
					return reporter.found(
						"no coverage data: .strictcli/coverage/ contains no shard files",
					);
				}

				// Write the canonical manifest (sorted, 2-space indent, trailing
				// newline).
				const manifest = [...covered].sort();
				writeFileSync(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`);

				// Compare against the command surface (exclude the
				// framework-injected check command -- it is not a user command).
				const allCommands = collectAllCommandPaths(app);
				allCommands.delete("check");
				const uncovered = [...allCommands]
					.filter((cmd) => !covered.has(cmd))
					.sort();

				if (uncovered.length > 0) {
					for (const cmd of uncovered) {
						reporter.error(`no test coverage for command: ${cmd}`);
					}
					return reporter.found(
						`${uncovered.length} command(s) with zero test coverage`,
					);
				}
				return reporter.passed(
					`all ${allCommands.size} commands have test coverage`,
				);
			},
		}),
	];
}
