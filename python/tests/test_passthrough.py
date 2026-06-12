"""Tests for passthrough command support."""

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


def _make_passthrough_handler(capture: dict):
    """Create a passthrough handler that records its call args."""
    def handler(name, args, globals):
        capture["name"] = name
        capture["args"] = args
        capture["globals"] = globals
        return capture.get("return_code", 0)
    return handler


class TestPassthroughReceivesRawArgs:
    def test_flag_like_tokens_passed_through(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec", "--verbose", "-n", "3", "file.txt"])
        assert result.exit_code == 0
        assert capture["name"] == "exec"
        assert capture["args"] == ["--verbose", "-n", "3", "file.txt"]


class TestPassthroughNoArgs:
    def test_empty_args(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec"])
        assert result.exit_code == 0
        assert capture["name"] == "exec"
        assert capture["args"] == []


class TestPassthroughWithGlobalFlags:
    def test_global_flags_passed_to_handler(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app(
            flags=[strictcli.Flag(name="debug", type=bool, help="enable debug")]
        )

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["--debug", "exec", "--some-flag", "value"])
        assert result.exit_code == 0
        assert capture["globals"] == {"debug": True}
        assert capture["args"] == ["--some-flag", "value"]

    def test_global_flags_default_values(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app(
            flags=[strictcli.Flag(name="debug", type=bool, help="enable debug")]
        )

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec", "arg1"])
        assert result.exit_code == 0
        assert capture["globals"] == {"debug": False}


class TestPassthroughExitCode:
    def test_handler_returns_exit_code(self):
        capture = {"return_code": 42}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec", "arg1"])
        assert result.exit_code == 42

    def test_handler_returns_zero(self):
        capture = {"return_code": 0}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec"])
        assert result.exit_code == 0


class TestPassthroughInAppHelp:
    def test_listed_as_command(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="run external tool", passthrough=pt)
        def exec_cmd():
            pass

        @app.command("status", help="show status")
        def status():
            pass

        result = app.test(["--help"])
        assert "exec" in result.stdout
        assert "run external tool" in result.stdout
        assert "status" in result.stdout


class TestPassthroughCommandHelp:
    def test_shows_help_no_flags(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="run external tool", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec", "--help"])
        assert "myapp exec -- run external tool" in result.stdout
        # No flags or arguments sections
        assert "Flags:" not in result.stdout
        assert "Arguments:" not in result.stdout


class TestPassthroughWithFlagsRaisesValueError:
    def test_decorator_flags(self):
        pt = strictcli.Passthrough(handler=lambda n, a, g: 0)
        app = _build_app()
        try:
            @app.command("exec", help="run", passthrough=pt)
            @strictcli.flag("verbose", type=bool, help="verbose output")
            def exec_cmd(verbose):
                pass
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "passthrough" in str(e)
            assert "flags" in str(e)


class TestPassthroughWithArgsRaisesValueError:
    def test_explicit_args(self):
        pt = strictcli.Passthrough(handler=lambda n, a, g: 0)
        app = _build_app()
        try:
            @app.command(
                "exec", help="run", passthrough=pt,
                args=[strictcli.Arg(name="target", help="target")],
            )
            def exec_cmd(target):
                pass
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "passthrough" in str(e)
            assert "args" in str(e)

    def test_decorator_args(self):
        pt = strictcli.Passthrough(handler=lambda n, a, g: 0)
        app = _build_app()
        try:
            @app.command("exec", help="run", passthrough=pt)
            @strictcli.arg("target", help="target")
            def exec_cmd(target):
                pass
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "passthrough" in str(e)
            assert "args" in str(e)


class TestPassthroughWithFlagSetsRaisesValueError:
    def test_flag_sets(self):
        pt = strictcli.Passthrough(handler=lambda n, a, g: 0)
        flag_set = strictcli.FlagSet(
            name="auth",
            flags=[strictcli.Flag(name="token", type=str, help="token", default="")],
        )
        app = _build_app()
        try:
            @app.command("exec", help="run", passthrough=pt, flag_sets=[flag_set])
            def exec_cmd(token):
                pass
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "passthrough" in str(e)
            assert "flag sets" in str(e)


class TestPassthroughWithMutexRaisesValueError:
    def test_mutex(self):
        pt = strictcli.Passthrough(handler=lambda n, a, g: 0)
        mg = strictcli.MutexGroup(flags=[
            strictcli.Flag(name="json", type=bool, help="json output"),
            strictcli.Flag(name="yaml", type=bool, help="yaml output"),
        ])
        app = _build_app()
        try:
            @app.command("exec", help="run", passthrough=pt, mutex=[mg])
            def exec_cmd(json, yaml):
                pass
            assert False, "should have raised ValueError"
        except ValueError as e:
            assert "passthrough" in str(e)
            assert "mutex" in str(e)


class TestMultiplePassthroughSameHandler:
    def test_same_passthrough_object(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        @app.command("run", help="run something", passthrough=pt)
        def run_cmd():
            pass

        result = app.test(["exec", "a", "b"])
        assert capture["name"] == "exec"
        assert capture["args"] == ["a", "b"]

        result = app.test(["run", "x"])
        assert capture["name"] == "run"
        assert capture["args"] == ["x"]


class TestPassthroughNonzeroExitCode:
    def test_nonzero_propagated(self):
        capture = {"return_code": 7}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec", "arg1"])
        assert result.exit_code == 7

    def test_one_propagated(self):
        capture = {"return_code": 1}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec"])
        assert result.exit_code == 1


class TestPassthroughDoubleDash:
    def test_double_dash_passed_through(self):
        capture = {}
        pt = strictcli.Passthrough(handler=_make_passthrough_handler(capture))
        app = _build_app()

        @app.command("exec", help="execute something", passthrough=pt)
        def exec_cmd():
            pass

        result = app.test(["exec", "--", "--flag", "value"])
        assert result.exit_code == 0
        assert capture["args"] == ["--", "--flag", "value"]
