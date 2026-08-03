"""Tests for the framework-owned reserved flag quartet.

Covers the unconditional name ban (--dry-run/--yes/--quiet/--verbose), the
position-aware pre-scan extraction, Context delivery, and the --quiet/--verbose
output gating table.
"""

import pytest

import strictcli

QUARTET = ["dry-run", "yes", "quiet", "verbose"]
BAN_MESSAGE = "is reserved by the framework (dry-run, yes, quiet, verbose)"


class TestReservedNameBan:
    """The ban is unconditional and applies at every level."""

    @pytest.mark.parametrize("name", QUARTET)
    def test_banned_on_a_bare_flag(self, name):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(name=name, type=bool, default=False, help="nope")
        assert str(exc.value) == (
            f"flag name '{name}' is reserved by the framework "
            f"(dry-run, yes, quiet, verbose)"
        )

    @pytest.mark.parametrize("name", QUARTET)
    def test_banned_as_a_global_flag(self, name):
        with pytest.raises(ValueError, match=BAN_MESSAGE.replace("(", r"\(").replace(")", r"\)")):
            strictcli.App(
                name="app", version="1.0.0", help="app",
                flags=[strictcli.Flag(name=name, type=bool, default=False, help="nope")],
            )

    @pytest.mark.parametrize("name", QUARTET)
    def test_banned_as_a_command_flag(self, name):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("run", effect="read_only", forwarding=strictcli.Forwarding(reason="test handler absorbs global flag values"), help="run")
            @strictcli.flag(name, type=bool, default=False, help="nope")
            def _run(ctx, **kw):
                return 0
        assert BAN_MESSAGE in str(exc.value)

    @pytest.mark.parametrize("name", QUARTET)
    def test_banned_in_a_flag_set(self, name):
        with pytest.raises(ValueError) as exc:
            strictcli.FlagSet(flags=[
                strictcli.Flag(name=name, type=bool, default=False, help="nope"),
            ])
        assert BAN_MESSAGE in str(exc.value)

    @pytest.mark.parametrize("name", QUARTET)
    def test_banned_in_a_mutex_group(self, name):
        with pytest.raises(ValueError) as exc:
            strictcli.MutexGroup(flags=[
                strictcli.Flag(name=name, type=bool, default=False, help="nope"),
                strictcli.Flag(name="other", type=bool, default=False, help="other"),
            ])
        assert BAN_MESSAGE in str(exc.value)

    def test_short_names_are_unaffected(self):
        """The ban covers long flag names only."""
        f = strictcli.Flag(name="loud", short="q", type=bool, default=False, help="loud")
        assert f.short == "q"

    def test_arg_names_are_unaffected(self):
        """A positional arg has no `--` spelling, so the ban does not apply."""
        a = strictcli.Arg(name="verbose", help="a positional named verbose")
        assert a.name == "verbose"


def _quartet_app():
    app = strictcli.App(name="app", version="1.0.0", help="app")

    @app.command("run", effect="read_only", help="run")
    def _run(ctx):
        return strictcli.outcome(data={
            "dry_run": ctx.dry_run,
            "yes": ctx.yes,
            "quiet": ctx.quiet,
            "verbose": ctx.verbose,
        })

    return app


class TestDelivery:
    """The quartet is delivered on the Context, never as handler kwargs."""

    def test_defaults_all_false(self):
        r = _quartet_app().test(["run"])
        assert r.exit_code == 0
        assert r.data == {"dry_run": False, "yes": False, "quiet": False, "verbose": False}

    @pytest.mark.parametrize("token,key", [
        ("--dry-run", "dry_run"),
        ("--yes", "yes"),
        ("--quiet", "quiet"),
        ("--verbose", "verbose"),
    ])
    def test_each_flag_reaches_the_context(self, token, key):
        r = _quartet_app().test([token, "run"])
        assert r.exit_code == 0
        assert r.data[key] is True
        for other in ("dry_run", "yes", "quiet", "verbose"):
            if other != key:
                assert r.data[other] is False

    def test_all_four_together(self):
        r = _quartet_app().test(["--dry-run", "--yes", "--quiet", "--verbose", "run"])
        assert r.exit_code == 0
        assert r.data == {"dry_run": True, "yes": True, "quiet": True, "verbose": True}

    def test_not_passed_as_handler_kwargs(self):
        """A handler that names no quartet parameter still dispatches."""
        app = strictcli.App(name="app", version="1.0.0", help="app")
        seen = {}

        @app.command("run", effect="read_only", help="run")
        def _run(ctx):
            seen["ok"] = True
            return 0

        r = app.test(["--dry-run", "--quiet", "run"])
        assert r.exit_code == 0
        assert seen == {"ok": True}

    def test_pre_scan_is_position_aware(self):
        """The quartet is extracted from the pre-command region only, which is
        what keeps a passthrough command's args opaque to the framework."""
        app = _quartet_app()
        r = app.test(["run", "--dry-run"])
        assert r.exit_code == 1
        assert "unknown flag '--dry-run'" in r.stderr

    def test_passthrough_args_stay_opaque(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        seen = {}

        def _pt(ctx, name, args, globals):
            seen["args"] = args
            return 0

        @app.command("exec", effect="read_only", help="exec",
                     passthrough=strictcli.Passthrough(handler=_pt))
        def _exec(ctx, **kw):
            return 0

        r = app.test(["exec", "--quiet", "--verbose"])
        assert r.exit_code == 0
        assert seen["args"] == ["--quiet", "--verbose"]


class TestGating:
    """The --quiet/--verbose gating table (quiet dominates verbose)."""

    def _run(self, argv):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", effect="read_only", help="run")
        def _r(ctx):
            ctx.debug("D")
            ctx.info("I")
            ctx.warn("W")
            ctx.error("E")
            return 0

        return app.test(argv)

    def test_default_hides_debug_only(self):
        r = self._run(["run"])
        assert r.stdout == "I\n"
        assert r.stderr == "W\nE\n"

    def test_verbose_shows_debug(self):
        r = self._run(["--verbose", "run"])
        assert r.stdout == "D\nI\n"
        assert r.stderr == "W\nE\n"

    def test_quiet_hides_info_and_debug(self):
        r = self._run(["--quiet", "run"])
        assert r.stdout == ""
        assert r.stderr == "W\nE\n"

    def test_quiet_dominates_verbose(self):
        r = self._run(["--quiet", "--verbose", "run"])
        assert r.stdout == ""
        assert r.stderr == "W\nE\n"

    def test_quiet_never_suppresses_structured_data(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", effect="read_only", help="run")
        def _r(ctx):
            return strictcli.outcome(data={"k": 1})

        r = app.test(["--quiet", "run"])
        assert r.data == {"k": 1}
        assert '{"k":1}' in r.stdout

    def test_quiet_never_suppresses_parse_errors(self):
        app = _quartet_app()
        r = app.test(["--quiet", "nope"])
        assert r.exit_code == 1
        assert "unknown command" in r.stderr
