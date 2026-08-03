"""Tests for the framework-owned confirm protocol."""

import io
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


def _app(effect="mutating", passthrough=False):
    app = sc.App(name="app", version="1.0.0", help="app")
    if passthrough:
        def _pt(ctx, name, args, globals):
            print("ran")
            return 0

        @app.command("deploy", help="deploy", effect=effect,
                     passthrough=sc.Passthrough(handler=_pt))
        def _d(ctx, **kw):
            return 0
    else:
        @app.command("deploy", help="deploy", effect=effect)
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
        assert out.err == "about to run mutating command 'deploy'. Proceed? [y/N] "

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
            "about to run mutating command 'deploy'. Proceed? [y/N] aborted\n"
        )

    def test_prompt_names_the_dotted_command_path(self, monkeypatch, capsys):
        app = sc.App(name="app", version="1.0.0", help="app")
        grp = app.group("release", help="release")

        @grp.command("run", help="run", effect="mutating")
        def _run_cmd(ctx):
            return 0

        code = _run(app, ["release", "run"], FakeStdin("y\n"), monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == (
            "about to run mutating command 'release.run'. Proceed? [y/N] "
        )


class TestNonInteractive:
    def test_non_tty_is_a_hard_error(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="y\n", tty=False)
        code = _run(_app(), ["deploy"], stdin, monkeypatch)
        assert code == 1
        out = capsys.readouterr()
        assert "ran" not in out.out
        assert out.err == "error: stdin is not interactive; pass --yes to confirm\n"
        assert stdin.read_count == 0

    def test_non_tty_with_yes_proceeds(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="", tty=False)
        code = _run(_app(), ["--yes", "deploy"], stdin, monkeypatch)
        assert code == 0
        out = capsys.readouterr()
        assert "ran" in out.out
        assert out.err == ""


class TestWhenItDoesNotFire:
    def test_yes_skips_the_prompt(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(), ["--yes", "deploy"], stdin, monkeypatch)
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
        code = _run(_app(effect="read_only"), ["deploy"], stdin, monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == ""

    def test_test_dispatch_never_prompts(self, monkeypatch):
        """Programmatic dispatch behaves as if --yes were passed."""
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="n\n", tty=False))
        r = _app().test(["deploy"])
        assert r.exit_code == 0
        assert "ran" in r.stdout

    def test_call_dispatch_never_prompts(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", FakeStdin(answer="n\n", tty=False))
        _app().call("deploy")


class TestPassthroughIsNotExempt:
    def test_mutating_passthrough_prompts(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(passthrough=True), ["deploy", "--anything"], stdin, monkeypatch)
        assert code == 1
        out = capsys.readouterr()
        assert "ran" not in out.out
        assert out.err.startswith("about to run mutating command 'deploy'.")

    def test_yes_skips_the_passthrough_prompt(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=True)
        code = _run(_app(passthrough=True), ["--yes", "deploy", "-x"], stdin, monkeypatch)
        assert code == 0
        assert "ran" in capsys.readouterr().out

    def test_read_only_passthrough_never_prompts(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="n\n", tty=False)
        code = _run(_app(effect="read_only", passthrough=True), ["deploy"],
                    stdin, monkeypatch)
        assert code == 0
        assert capsys.readouterr().err == ""


class TestNoBypass:
    def test_there_is_no_no_confirm_flag(self, monkeypatch, capsys):
        stdin = FakeStdin(answer="y\n", tty=True)
        monkeypatch.setattr(sys, "argv", ["app", "--no-confirm", "deploy"])
        monkeypatch.setattr(sys, "stdin", stdin)
        with pytest.raises(SystemExit) as exc:
            _app().run()
        assert exc.value.code == 1
        assert "unknown" in capsys.readouterr().err.lower()
