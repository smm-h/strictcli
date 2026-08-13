"""Claimed rendering: ctx.effects.recorded() / render_log() (contract §19.7).

Calling recorded() claims the render; render_log() produces byte-identical
bytes wherever the handler puts them; a claim that never rendered is
re-rendered at the seam; and in machine mode render_log() is a no-op.
"""

import json

import strictcli as sc

LOG = (
    "DRY RUN — no changes were made. Would do:\n"
    "  1. mkdir: build\n"
    "  2. write: VERSION (5 bytes)\n"
)


def _app():
    return sc.App(name="app", version="1.0.0", help="app")


def _build(app, *, claim=False, render=False, prints=True):
    @app.command("build", help="build", effect="mutating")
    def _build_handler(ctx):
        ctx.effects.mkdir("build")
        ctx.effects.write("VERSION", "1.2.3")
        if claim:
            ctx.effects.recorded()
        if render:
            ctx.effects.render_log()
        if prints:
            print("summary")
        return 0

    return app


class TestOrdering:
    def test_unclaimed_the_framework_renders_after_the_handler(self):
        r = _build(_app()).test(["--dry-run", "build"])
        assert r.stdout == "summary\n" + LOG

    def test_render_log_puts_the_identical_bytes_first(self):
        r = _build(_app(), render=True).test(["--dry-run", "build"])
        assert r.stdout == LOG + "summary\n"
        assert r.stderr == ""

    def test_a_rendered_log_is_not_repeated_at_the_seam(self):
        r = _build(_app(), render=True, prints=False).test(["--dry-run", "build"])
        assert r.stdout == LOG


class TestTheClaimNeverRemovesTheRender:
    def test_claimed_but_never_rendered_is_re_rendered_at_the_seam(self):
        r = _build(_app(), claim=True).test(["--dry-run", "build"])
        assert r.stdout == "summary\n" + LOG

    # A claim that survives an UNWIND is pinned end-to-end by the
    # claimed_rendering conformance case: test() re-raises, so the captured
    # streams never reach a Result here.

class TestRecordedReturnsTheRecords:
    def test_the_shape_is_the_structured_record(self):
        app = _app()
        seen = {}

        @app.command("build", help="build", effect="mutating")
        def _build_handler(ctx):
            ctx.effects.mkdir("build")
            seen["records"] = ctx.effects.recorded()
            return 0

        app.test(["--dry-run", "build"])
        assert seen["records"] == [
            {
                "seq": 1,
                "kind": "file_write",
                "verb": "mkdir",
                "detail": "build",
                "recorded": True,
            }
        ]


class TestModes:
    def test_render_log_emits_nothing_outside_dry_mode(self):
        # No effects at all: a live run must PERFORM anything it records, and
        # this case is about render_log() staying silent, not about writing.
        app = _app()

        @app.command("build", help="build", effect="mutating")
        def _build_handler(ctx):
            ctx.effects.render_log()
            print("summary")
            return 0

        r = app.test(["build"])
        assert r.stdout == "summary\n"
        assert r.stderr == ""

    def test_render_log_renders_the_bare_header_in_a_dry_run_with_no_effects(self):
        app = _app()

        @app.command("build", help="build", effect="mutating")
        def _build_handler(ctx):
            ctx.effects.render_log()
            print("summary")
            return 0

        r = app.test(["--dry-run", "build"])
        assert r.stdout == "DRY RUN — no changes were made. Would do:\nsummary\n"

    def test_render_log_is_a_no_op_in_machine_mode(self):
        r = _build(_app(), render=True, prints=False).test(
            ["--json", "--dry-run", "build"]
        )
        env = json.loads(r.stdout)
        assert "DRY RUN" not in r.stdout
        assert [rec["verb"] for rec in env["preview"]] == ["mkdir", "write"]
        assert r.stderr == ""
