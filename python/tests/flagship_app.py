"""A permanent fixture app demonstrating the three flagship preview shapes.

This is the reference the effects regime is judged against:

(a) ``release run``  -- a complete multi-step data-flow preview: a real value
    from a pre-mutation observe, carriers forwarded into later effects with
    their brands rendered inline, a grant suffix, and a conditional suffix.
(b) ``release verify`` -- honest truncation: the handler branches on a value it
    cannot know, so the preview stops with the pinned error instead of
    inventing one.
(c) ``status`` -- a read_only command: observes return bare, real values in
    both modes, and the would-do body is always empty.

The observes use a Python one-liner rather than ``git rev-parse`` so the
fixture is hermetic (no repository, no git binary), but the shape is exactly
the ratified idempotency idiom: branch on an allowlisted observe, which returns
a real value even in dry mode.
"""

import sys

import strictcli as sc

# Stands in for `git rev-parse HEAD`: an allowlisted observe.
OBSERVE_PREFIX = [sys.executable, "-c"]
HEAD_ARGV = [sys.executable, "-c", "print('a1b2c3d')"]
DIRTY_ARGV = [sys.executable, "-c", "print('')"]


def build_app() -> sc.App:
    app = sc.App(
        name="ship",
        version="1.0.0",
        help="A release tool demonstrating the effects regime",
        proc_observe_allowlist=[OBSERVE_PREFIX],
    )

    @app.command("status", help="Show what a release would start from",
                 effect="read_only", payload_schema={})
    def status(ctx):
        # An observe returns a real value here in BOTH modes: read_only
        # commands never record anything, so nothing is ever unsettled.
        head = ctx.effects.run(HEAD_ARGV)
        dirty = ctx.effects.run(DIRTY_ARGV, check=False)
        ctx.info(f"head: {head.stdout}")
        ctx.payload({
            "head": head.stdout,
            "clean": dirty.stdout == "",
            "exit_code": head.exit_code,
        })
        return sc.outcome()

    release = app.group("release", help="Release commands")

    @release.command(
        "run",
        help="Cut a release",
        effect="mutating",
        grants=[sc.Grant("push", "release engine owns remote refs", sc.PROC_MUTATE)],
        args=[sc.Arg(name="version", help="The version to release")],
    )
    def release_run(ctx, version):
        # Real-mode idempotency lives in the handler and branches on an
        # allowlisted observe -- a real value, so the preview walks straight
        # through the `if` instead of truncating.
        head = ctx.effects.run(HEAD_ARGV, check=False)
        if head.exit_code != 0:
            ctx.error("cannot determine HEAD")
            return 1

        artifact = ctx.effects.run(["make", "build", f"VERSION={version}"],
                                   resource=f"artifact:{version}")
        # Forwarding the carrier as CONTENT: there is no byte count to report,
        # so the brand renders in its place.
        ctx.effects.write("CHANGELOG.md", artifact)
        ctx.effects.run(["git", "tag", f"v{version}"],
                        resource=f"tag:v{version}")
        ctx.effects.run(["git", "push", "origin", f"v{version}"],
                        grant="push", resource="remote:origin")
        created = ctx.effects.http(
            "POST", "https://api.github.test/repos/o/r/releases",
            resource=f"gh-release:v{version}",
            skip_if_current=f"gh-release:v{version}",
        )
        # Forwarding the http carrier into a later argv.
        ctx.effects.run(["gh", "release", "view", created])
        ctx.effects.spawn(["notify", "--release", f"v{version}"])
        return 0

    @release.command("verify", help="Verify the last release", effect="mutating")
    def release_verify(ctx):
        ctx.effects.run(["git", "tag", "v9"])
        described = ctx.effects.run(["git", "describe", "--tags"])
        # Branching on a value nothing produced: the preview ends here.
        if described.exit_code == 0:
            ctx.effects.run(["echo", "unreachable"])
        return 0

    return app
