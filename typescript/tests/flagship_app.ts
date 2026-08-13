/**
 * A permanent fixture app demonstrating the three flagship preview shapes.
 *
 * This is the reference the effects regime is judged against:
 *
 * (a) `release run`    -- a complete multi-step data-flow preview: a real value
 *     from a pre-mutation observe, carriers forwarded into later effects with
 *     their brands rendered inline, a grant suffix, and a conditional suffix.
 * (b) `release verify` -- honest truncation: the handler branches on a value it
 *     cannot know, so the preview stops with the pinned error instead of
 *     inventing one.
 * (c) `status`         -- a read_only command: observes return bare, real values
 *     in both modes, and the would-do body is always empty.
 *
 * The observes use a Node one-liner rather than `git rev-parse` so the fixture
 * is hermetic (no repository, no git binary), but the shape is exactly the
 * ratified idempotency idiom: branch on an allowlisted observe, which returns a
 * real value even in dry mode.
 */

import {
	type App,
	arg,
	createApp,
	defineMutatingCommand,
	defineReadOnlyCommand,
	outcome,
	t,
} from "../src/index.js";

/** Stands in for `git rev-parse HEAD`: an allowlisted observe. */
export const OBSERVE_PREFIX = [process.execPath, "-e"];
export const HEAD_ARGV = [
	process.execPath,
	"-e",
	"process.stdout.write('a1b2c3d\\n')",
];
export const DIRTY_ARGV = [
	process.execPath,
	"-e",
	"process.stdout.write('\\n')",
];

export function buildApp(): App {
	const app = createApp({
		name: "ship",
		version: "1.0.0",
		help: "A release tool demonstrating the effects regime",
		procObserveAllowlist: [OBSERVE_PREFIX],
	});

	app.command(
		defineReadOnlyCommand("status", {
			payloadSchema: {},
			help: "Show what a release would start from",
			handler: (_args, ctx) => {
				// An observe returns a real value here in BOTH modes: read_only
				// commands never record anything, so nothing is ever unsettled.
				const head = ctx.effects.run(HEAD_ARGV);
				const dirty = ctx.effects.run(DIRTY_ARGV, { check: false });
				ctx.info(`head: ${head.stdout}`);
				ctx.payload({
					head: head.stdout,
					clean: dirty.stdout === "",
					exit_code: head.exitCode,
				});
				return outcome(0);
			},
		}),
	);

	const release = app.group("release", { help: "Release commands" });

	release.command(
		defineMutatingCommand("run", {
			help: "Cut a release",
			grants: [
				{
					name: "push",
					reason: "release engine owns remote refs",
					kind: "proc_mutate",
				},
			],
			args: [arg("version", t.str, { help: "The version to release" })],
			handler: (args, ctx) => {
				// Real-mode idempotency lives in the handler and branches on an
				// allowlisted observe -- a real value, so the preview walks straight
				// through the `if` instead of truncating.
				const head = ctx.effects.run(HEAD_ARGV, { check: false });
				if (head.exitCode !== 0) {
					ctx.error("cannot determine HEAD");
					return 1;
				}

				const version = args.version;
				const artifact = ctx.effects.run(
					["make", "build", `VERSION=${version}`],
					{ resource: `artifact:${version}` },
				);
				// Forwarding the carrier as CONTENT: there is no byte count to
				// report, so the brand renders in its place.
				ctx.effects.write("CHANGELOG.md", artifact);
				ctx.effects.run(["git", "tag", `v${version}`], {
					resource: `tag:v${version}`,
				});
				ctx.effects.run(["git", "push", "origin", `v${version}`], {
					grant: "push",
					resource: "remote:origin",
				});
				const created = ctx.effects.http(
					"POST",
					"https://api.github.test/repos/o/r/releases",
					{
						resource: `gh-release:v${version}`,
						skipIfCurrent: `gh-release:v${version}`,
					},
				);
				// Forwarding the http carrier into a later argv.
				ctx.effects.run(["gh", "release", "view", created]);
				ctx.effects.spawn(["notify", "--release", `v${version}`]);
				return 0;
			},
		}),
	);

	release.command(
		defineMutatingCommand("verify", {
			help: "Verify the last release",
			handler: (_args, ctx) => {
				ctx.effects.run(["git", "tag", "v9"]);
				const described = ctx.effects.run(["git", "describe", "--tags"]);
				// Branching on a value nothing produced: the preview ends here.
				if (described.exitCode === 0) {
					ctx.effects.run(["echo", "unreachable"]);
				}
				return 0;
			},
		}),
	);

	return app;
}
