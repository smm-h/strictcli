"""Tests for the framework-owned confirm protocol.

The protocol fires for commands that DECLARE THEMSELVES consequential, never
for a plain ``mutating`` command. Classification answers "should a dry run
record rather than execute?"; ``consequential`` answers "are these effects
worth interrupting someone for?".
"""

import asyncio
import sys

import pytest

import strictcli as sc


class FakeStdin:
    """A stdin stand-in with controllable TTY-ness and a scripted answer."""

    def __init__(self, answer="", tty=True):
        self._answer = answer
        self._tty = tty
        self.read_count = 0

    def isatty(self):
        return self._tty

    def readline(self):
        self.read_count += 1
        return self._answer


def _app(effect="mutating", passthrough=False, consequential=True):
    app = sc.App(name="app", version="1.0.0", help="app")
    if passthrough:
        def _pt(ctx, name, args, globals):
            print("ran")
            return 0

        @app.command("deploy", help="deploy", effect=effect,
                     consequential=consequential,
                     passthrough=sc.Passthrough(handler=_pt))
        def _d(ctx, **kw):
            return 0
    else:
        @app.command("deploy", help="deploy", effect=effect,
                     consequential=consequential)
        def _deploy(ctx):
            print("ran")
            return 0

    return app


def _run(app, argv, stdin, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app"] + argv)
    monkeypatch.setattr(sys, "stdin", stdin)
    with pytest.raises(SystemExit) as exc:
        app.run()
    return exc.value.code


class TestPrompt:
    @pytest.mark.parametrize("answer", ["y\n", "Y\n", "y", "Y"])
    def test_accepting_answers_proceed(self, answer, monkeypatch, capsys):
        stdin = FakeStdin(answer=answer, tty=True)
        code = _run(_app(), ["deploy"], stdin, monkeypatch)
        assert code == 0
        out = capsys.readouterr()
        assert "ran" in out.out
        assert out.err == (
            "about to run consequential command 'deploy'. Proceed? [y/N] "
        )

    @pytest.mark.parametrize("answer", ["y\r\n", "Y\r\n", "y\r", "Y\r"])
    def test_a_crlf_terminated_answer_proceeds(self, answer, monkeypatch,
                                               capsys):
        """A human at a Windows console types the same 'y' (§8.2).

        Their terminal terminates the line CRLF, and a stdin stream that does
        not translate newlines hands the framework a trailing carriage return.
        Declining there would refuse an answer the human plainly gave.
        """
        stdin = FakeStdin(answer=answer, tty=True)
        code = _run(_app(), ["deploy"], stdin, monkeypatch)
        assert code == 0
        assert "ran" in capsys.readouterr().out

    @pytest.mark.parametrize("answer", ["n\n", "\n", "", "yes\n", "Yes\n", "no\n", "  y\n",
                                        "y\r\r\n", "\r\ry\n", "y\n\n"])
    def test_everything_else_declines(self, answer, monkeypatch, capsys):
        stdin = FakeStdin(answer=answer, tty=True)
        code = _run(_app(), ["deploy"], stdin, monkeypatch)
        assert code == 1
        out = capsys.readouterr()
        assert "ran" not in out.out
        assert out.err == (
            "about to run consequential command 'deploy'. "
            "Proceed? [y/N] aborted\n"
        )

    def test_prompt_names_the_dotted_command_path(self, monkeypatch, capsys):
        app = sc.App(name="app", version="1.0.0", help="app")
        grp = app.group("release", help="release")

        @grp.command("run", help="run", effect="mutating", consequential=True)
        def _run_cmd(ctx):
            return 0

        code = _run(app, ["release", "run"], FakeStdin("y\n"), monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == (
            "about to run consequential command 'release.run'. Proceed? [y/N] "
        )


class TestNonInteractive:
    def test_non_tty_is_a_hard_error(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="y\n", tty=False)
        code = _run(_app(), ["deploy"], stdin, monkeypatch)
        assert code == 1
        out = capsys.readouterr()
        assert "ran" not in out.out
        assert out.err == (
            "error: stdin is not interactive; a consequential command must be "
            "confirmed at a terminal\n"
        )
        assert stdin.read_count == 0

    def test_non_tty_with_approval_proceeds(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="", tty=False)
        code = _run(_app(), ["--approve-consequential", "deploy"], stdin,
                    monkeypatch)
        assert code == 0
        out = capsys.readouterr()
        assert "ran" in out.out
        assert out.err == ""


class TestWhenItDoesNotFire:
    def test_a_mutating_command_that_is_not_consequential_never_prompts(
            self, monkeypatch, capsys):
        """The headline of the redesign: `mutating` alone never prompts.

        Two thirds of the commands in a real fleet classify `mutating`; the
        genuinely dangerous ones are a small fraction of that. Inferring the
        prompt from classification made the guardrail noise.
        """
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(consequential=False), ["deploy"], stdin, monkeypatch)
        assert code == 0
        assert stdin.read_count == 0
        out = capsys.readouterr()
        assert "ran" in out.out
        assert out.err == ""

    def test_a_mutating_non_consequential_command_runs_without_a_tty(
            self, monkeypatch, capsys):
        stdin = FakeStdin(answer="", tty=False)
        code = _run(_app(consequential=False), ["deploy"], stdin, monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == ""

    def test_approve_consequential_skips_the_prompt(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(), ["--approve-consequential", "deploy"], stdin,
                    monkeypatch)
        assert code == 0
        assert stdin.read_count == 0
        assert capsys.readouterr().err == ""

    def test_approve_consequential_is_recognized_after_the_command_name(
            self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(), ["deploy", "--approve-consequential"], stdin,
                    monkeypatch)
        assert code == 0
        assert stdin.read_count == 0
        assert capsys.readouterr().err == ""

    def test_dry_run_skips_the_prompt(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(), ["--dry-run", "deploy"], stdin, monkeypatch)
        assert code == 0
        assert stdin.read_count == 0
        out = capsys.readouterr()
        assert out.err == ""
        assert "DRY RUN — no changes were made. Would do:" in out.out

    def test_read_only_never_prompts(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=False)
        code = _run(_app(effect="read_only", consequential=False), ["deploy"],
                    stdin, monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == ""

    def test_test_dispatch_never_prompts(self, monkeypatch):
        """Programmatic dispatch behaves as if --approve-consequential were passed."""
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="n\n", tty=False))
        r = _app().test(["deploy"])
        assert r.exit_code == 0
        assert "ran" in r.stdout

    def test_call_dispatch_never_prompts(self, monkeypatch):
        """call() never reads stdin -- consent is stated in the call itself."""
        stdin = FakeStdin(answer="n\n", tty=False)
        monkeypatch.setattr(sys, "stdin", stdin)
        _app().call("deploy", approve_consequential=True)
        assert stdin.read_count == 0


class TestCallConsent:
    """The programmatic channel honours the requirement without prompting."""

    def test_unconsented_call_is_refused(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="y\n", tty=False))
        with pytest.raises(sc.InvokeError) as exc:
            _app().call("deploy")
        assert str(exc.value) == (
            "command 'deploy' is consequential: the call must carry "
            "confirmation"
        )

    def test_consented_call_proceeds(self, capsys):
        assert _app().call("deploy", approve_consequential=True) == 0
        assert "ran" in capsys.readouterr().out

    def test_unconsented_passthrough_call_is_refused(self):
        with pytest.raises(sc.InvokeError) as exc:
            _app(passthrough=True).call("deploy", _args=["-x"])
        assert "is consequential" in str(exc.value)

    def test_consented_passthrough_call_proceeds(self, capsys):
        app = _app(passthrough=True)
        assert app.call(
            "deploy", approve_consequential=True, _args=["-x"],
        ) == 0
        assert "ran" in capsys.readouterr().out

    def test_a_plain_mutating_call_needs_no_consent(self, capsys):
        assert _app(consequential=False).call("deploy") == 0
        assert "ran" in capsys.readouterr().out

    def test_a_read_only_call_needs_no_consent(self, capsys):
        app = _app(effect="read_only", consequential=False)
        assert app.call("deploy") == 0
        assert "ran" in capsys.readouterr().out

    def test_consent_reaches_the_handler(self):
        app = sc.App(name="app", version="1.0.0", help="app")
        seen = {}

        @app.command("deploy", help="deploy", effect="mutating",
                     consequential=True)
        def _deploy(ctx):
            seen["approved"] = ctx.approve_consequential
            return 0

        app.call("deploy", approve_consequential=True)
        assert seen == {"approved": True}

    def test_acall_refuses_and_proceeds_like_call(self):
        with pytest.raises(sc.InvokeError):
            asyncio.run(_app().acall("deploy"))
        assert asyncio.run(
            _app().acall("deploy", approve_consequential=True)
        ) == 0


class TestPassthroughIsNotExempt:
    def test_consequential_passthrough_prompts(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(passthrough=True), ["deploy", "--anything"], stdin,
                    monkeypatch)
        assert code == 1
        out = capsys.readouterr()
        assert "ran" not in out.out
        assert out.err.startswith("about to run consequential command 'deploy'.")

    def test_approval_skips_the_passthrough_prompt(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(passthrough=True),
                    ["--approve-consequential", "deploy", "-x"], stdin,
                    monkeypatch)
        assert code == 0
        assert "ran" in capsys.readouterr().out

    def test_a_mutating_passthrough_that_is_not_consequential_never_prompts(
            self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=False)
        code = _run(_app(passthrough=True, consequential=False), ["deploy"],
                    stdin, monkeypatch)
        assert code == 0
        assert "ran" in capsys.readouterr().out

    def test_read_only_passthrough_never_prompts(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=False)
        code = _run(_app(effect="read_only", passthrough=True,
                         consequential=False),
                    ["deploy"], stdin, monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == ""


class TestDeclaration:
    def test_read_only_cannot_be_consequential(self):
        app = sc.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("cmd", help="c", effect="read_only",
                         consequential=True)
            def _c(ctx):
                return 0
        assert str(exc.value) == (
            'command "cmd": a read_only command cannot be consequential '
            '(a command that changes nothing has nothing to confirm)'
        )

    def test_read_only_passthrough_cannot_be_consequential(self):
        app = sc.App(name="app", version="1.0.0", help="app")

        def _pt(ctx, name, args, globals):
            return 0

        with pytest.raises(ValueError) as exc:
            @app.command("cmd", help="c", effect="read_only",
                         consequential=True,
                         passthrough=sc.Passthrough(handler=_pt))
            def _c(ctx, **kw):
                return 0
        assert "cannot be consequential" in str(exc.value)

    def test_consequential_is_not_mandatory(self):
        """Unlike classification, absence simply means "not consequential"."""
        app = sc.App(name="app", version="1.0.0", help="app")

        @app.command("cmd", help="c", effect="mutating")
        def _c(ctx):
            return 0

        assert app._commands["cmd"].consequential is False

    def test_consequential_is_emitted_in_the_schema(self):
        app = sc.App(name="app", version="1.0.0", help="app")

        @app.command("plain", help="c", effect="mutating")
        def _p(ctx):
            return 0

        @app.command("grave", help="c", effect="mutating", consequential=True)
        def _g(ctx):
            return 0

        cmds = app.dump_schema_dict()["commands"]
        assert "consequential" not in cmds["plain"]
        assert cmds["grave"]["consequential"] is True


class TestReservedNames:
    def test_approve_consequential_is_a_reserved_flag_name(self):
        with pytest.raises(ValueError) as exc:
            sc.Flag(name="approve-consequential", type=bool, help="no")
        assert str(exc.value) == (
            "flag name 'approve-consequential' is reserved by the framework "
            "(dry-run, approve-consequential, quiet, verbose)"
        )

    def test_approve_consequential_is_a_reserved_flag_param_name(self):
        """The underscore spelling is the programmatic consent parameter.

        A flag of that name would reach the handler as the same kwarg
        `call()` reserves for consent, so it is refused at registration.
        """
        with pytest.raises(ValueError) as exc:
            sc.Flag(name="approve_consequential", type=bool, help="no")
        assert str(exc.value) == (
            "flag name 'approve_consequential' is reserved by the framework: "
            "it names the programmatic consent parameter"
        )

    def test_approve_consequential_is_a_reserved_arg_name(self):
        """A positional arg of that name is swallowed by call()'s keyword-only
        consent parameter while MCP still reaches it -- two channels
        disagreeing about the same command. Refused at registration."""
        with pytest.raises(ValueError) as exc:
            sc.Arg(name="approve_consequential", help="no")
        assert str(exc.value) == (
            "arg name 'approve_consequential' is reserved by the framework: "
            "it names the programmatic consent parameter"
        )

    def test_other_arg_names_are_unaffected(self):
        """Only the consent parameter is reserved on the arg surface: the
        quartet's own names stay legal as positionals."""
        assert sc.Arg(name="verbose", help="a positional").name == "verbose"
        assert sc.Arg(name="approve", help="a positional").name == "approve"

    def test_reserved_consent_name_is_rejected_through_the_command_decorator(self):
        app = sc.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("cmd", help="c", effect="read_only",
                         args=[sc.Arg(name="approve_consequential", help="x")])
            def _c(ctx, approve_consequential):
                return 0
        assert "reserved by the framework" in str(exc.value)

    def test_yes_stays_banned(self):
        """`yes` owns no framework flag, but a private --yes would restate
        --approve-consequential in a spelling that IS muscle memory."""
        with pytest.raises(ValueError) as exc:
            sc.Flag(name="yes", type=bool, help="no")
        assert str(exc.value) == (
            "flag name 'yes' is banned by the framework: "
            "the confirmation skip is --approve-consequential"
        )

    def test_yes_is_no_longer_a_framework_token(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="y\n", tty=True)
        monkeypatch.setattr(sys, "argv", ["app", "--yes", "deploy"])
        monkeypatch.setattr(sys, "stdin", stdin)
        with pytest.raises(SystemExit) as exc:
            _app().run()
        assert exc.value.code == 1
        assert "unknown" in capsys.readouterr().err.lower()


class TestContextAccessor:
    def test_ctx_exposes_approve_consequential(self):
        app = sc.App(name="app", version="1.0.0", help="app")
        seen = {}

        @app.command("cmd", help="c", effect="mutating", consequential=True)
        def _c(ctx):
            seen["v"] = ctx.approve_consequential
            return 0

        app.test(["--approve-consequential", "cmd"])
        assert seen["v"] is True
        app.test(["cmd"])
        assert seen["v"] is False


class TestNoBypass:
    def test_there_is_no_no_confirm_flag(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="y\n", tty=True)
        monkeypatch.setattr(sys, "argv", ["app", "--no-confirm", "deploy"])
        monkeypatch.setattr(sys, "stdin", stdin)
        with pytest.raises(SystemExit) as exc:
            _app().run()
        assert exc.value.code == 1
        assert "unknown" in capsys.readouterr().err.lower()


class FakeConfirmIO:
    """A ConfirmIO stand-in: controllable interactivity and a scripted answer."""

    def __init__(self, answer="", interactive=True):
        self._answer = answer
        self._interactive = interactive
        self.read_count = 0

    def is_interactive(self):
        return self._interactive

    def read_line(self):
        self.read_count += 1
        return self._answer


class TestConfirmIOSeam:
    """The test-only seam that swaps the protocol's stdin side.

    It changes WHERE the answer comes from, never WHETHER the protocol runs --
    the twins are Go's App.SetConfirmIO and TypeScript's setConfirmIO, and the
    conformance suite drives all three through it so the interactive branch is
    reachable from a subprocess whose stdin is a pipe.
    """

    def test_seam_supplies_the_answer_without_touching_stdin(
        self, monkeypatch, capsys
    ):
        app = _app()
        io = FakeConfirmIO(answer="y\n", interactive=True)
        app._set_confirm_io(io)
        # sys.stdin is deliberately a NON-interactive stand-in: if the protocol
        # consulted it, this run would take the non-interactive error branch.
        monkeypatch.setattr(sys, "argv", ["app", "deploy"])
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="n\n", tty=False))
        with pytest.raises(SystemExit) as exc:
            app.run()
        assert exc.value.code == 0
        assert "ran" in capsys.readouterr().out
        assert io.read_count == 1

    def test_seam_declines_like_the_real_reader(self, monkeypatch, capsys):
        app = _app()
        app._set_confirm_io(FakeConfirmIO(answer="n\n", interactive=True))
        monkeypatch.setattr(sys, "argv", ["app", "deploy"])
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="y\n", tty=True))
        with pytest.raises(SystemExit) as exc:
            app.run()
        assert exc.value.code == 1
        assert "aborted" in capsys.readouterr().err

    def test_seam_non_interactive_is_the_hard_error(self, monkeypatch, capsys):
        app = _app()
        app._set_confirm_io(FakeConfirmIO(answer="y\n", interactive=False))
        monkeypatch.setattr(sys, "argv", ["app", "deploy"])
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="y\n", tty=True))
        with pytest.raises(SystemExit) as exc:
            app.run()
        assert exc.value.code == 1
        assert "stdin is not interactive" in capsys.readouterr().err

    def test_none_restores_the_real_reader(self, monkeypatch, capsys):
        app = _app()
        app._set_confirm_io(FakeConfirmIO(answer="n\n", interactive=True))
        app._set_confirm_io(None)
        monkeypatch.setattr(sys, "argv", ["app", "deploy"])
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="y\n", tty=True))
        with pytest.raises(SystemExit) as exc:
            app.run()
        assert exc.value.code == 0
        assert "ran" in capsys.readouterr().out

    def test_the_seam_is_not_a_bypass(self, monkeypatch, capsys):
        # An installed seam still runs the whole protocol: an empty answer
        # declines exactly as it would from a real terminal.
        app = _app()
        app._set_confirm_io(FakeConfirmIO(answer="", interactive=True))
        monkeypatch.setattr(sys, "argv", ["app", "deploy"])
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="y\n", tty=True))
        with pytest.raises(SystemExit) as exc:
            app.run()
        assert exc.value.code == 1
        assert "aborted" in capsys.readouterr().err
