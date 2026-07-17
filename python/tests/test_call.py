"""Tests for App.call(), App.acall(), and Outcome-based handler returns."""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

import pytest

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


class TestCallReturnsInt:
    """Handler returning int: call() returns int, test().data is None."""

    def test_call_returns_int(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            return 42

        assert app.call("run") == 42

    def test_test_data_is_none_for_int_return(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            return 42

        result = app.test(["run"])
        assert result.data is None
        assert result.exit_code == 42

    def test_test_data_is_none_for_zero(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            return 0

        result = app.test(["run"])
        assert result.data is None
        assert result.exit_code == 0


class TestCallReturnsNone:
    """Handler returning None: call() returns None, test().data is None."""

    def test_call_returns_none(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        assert app.call("run") is None

    def test_test_data_is_none(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        result = app.test(["run"])
        assert result.data is None
        assert result.exit_code == 0


class TestCallReturnsDict:
    """Handler returning outcome(data=dict): call() returns dict, test().data is dict."""

    def test_call_returns_dict(self):
        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data={"healthy": True, "uptime": 3600})

        result = app.call("status")
        assert result == {"healthy": True, "uptime": 3600}

    def test_test_data_is_dict(self):
        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data={"healthy": True, "uptime": 3600})

        result = app.test(["status"])
        assert result.data == {"healthy": True, "uptime": 3600}
        assert result.exit_code == 0

    def test_call_with_flags(self):
        app = _build_app()

        @app.command("status", help="get status")
        @strictcli.flag("verbose", type=bool, default=False, help="include details")
        def status(ctx, verbose):
            data = {"healthy": True}
            if verbose:
                data["details"] = "all systems operational"
            return strictcli.outcome(data=data)

        result = app.call("status", verbose=True)
        assert result == {"healthy": True, "details": "all systems operational"}


class TestCallReturnsList:
    """Handler returning outcome(data=list): call() returns list."""

    def test_call_returns_list(self):
        app = _build_app()

        @app.command("list-users", help="list users")
        def list_users(ctx):
            return strictcli.outcome(data=["alice", "bob", "charlie"])

        result = app.call("list-users")
        assert result == ["alice", "bob", "charlie"]

    def test_test_data_is_list(self):
        app = _build_app()

        @app.command("list-users", help="list users")
        def list_users(ctx):
            return strictcli.outcome(data=["alice", "bob", "charlie"])

        result = app.test(["list-users"])
        assert result.data == ["alice", "bob", "charlie"]
        assert result.exit_code == 0


class TestCallReturnsDataclass:
    """Handler returning outcome(data=dataclass): call() returns dataclass."""

    def test_call_returns_dataclass(self):
        @dataclass
        class Status:
            healthy: bool
            uptime: int

        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data=Status(healthy=True, uptime=3600))

        result = app.call("status")
        assert isinstance(result, Status)
        assert result.healthy is True
        assert result.uptime == 3600

    def test_test_data_is_dataclass(self):
        @dataclass
        class Status:
            healthy: bool
            uptime: int

        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data=Status(healthy=True, uptime=3600))

        result = app.test(["status"])
        assert isinstance(result.data, Status)
        assert result.data.healthy is True
        assert result.data.uptime == 3600
        assert result.exit_code == 0


class TestCallReturnsString:
    """Handler returning outcome(data=str): call() returns string."""

    def test_call_returns_string(self):
        app = _build_app()

        @app.command("greet", help="greet")
        def greet(ctx):
            return strictcli.outcome(data="hello world")

        result = app.call("greet")
        assert result == "hello world"

    def test_test_data_is_string(self):
        app = _build_app()

        @app.command("greet", help="greet")
        def greet(ctx):
            return strictcli.outcome(data="hello world")

        result = app.test(["greet"])
        assert result.data == "hello world"
        assert result.exit_code == 0


class TestCallErrorCases:
    """call() raises InvokeError (not SystemExit) for errors."""

    def test_unknown_command(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown command 'nonexistent'"):
            app.call("nonexistent")

    def test_missing_required_flag(self):
        app = _build_app()

        @app.command("greet", help="greet")
        @strictcli.flag("name", type=str, help="name")
        def greet(ctx, name):
            pass

        with pytest.raises(strictcli.InvokeError, match="flag '--name' is required"):
            app.call("greet")

    def test_missing_required_arg(self):
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target")],
        )
        def deploy(ctx, target):
            pass

        with pytest.raises(strictcli.InvokeError, match="missing required argument 'target'"):
            app.call("deploy")

    def test_unknown_kwarg(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown parameter 'bogus'"):
            app.call("run", bogus="value")

    def test_mutex_violation(self):
        app = _build_app()

        @app.command(
            "fmt", help="format",
            mutex=[strictcli.MutexGroup(
                flags=[
                    strictcli.Flag(name="json", type=bool, default=False, help="JSON output"),
                    strictcli.Flag(name="yaml", type=bool, default=False, help="YAML output"),
                ],
            )],
        )
        def fmt(ctx, json, yaml):
            pass

        with pytest.raises(strictcli.InvokeError, match="mutually exclusive"):
            app.call("fmt", json=True, yaml=True)

    def test_group_path_raises(self):
        """Calling a group (not a command) raises InvokeError."""
        app = _build_app()
        grp = app.group("config", help="config management")

        @grp.command("show", help="show config")
        def show(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="is a group, not a command"):
            app.call("config")

    def test_invoke_error_is_not_system_exit(self):
        """InvokeError is not a subclass of SystemExit."""
        assert not issubclass(strictcli.InvokeError, SystemExit)

    def test_invoke_error_chains_from_parse_error(self):
        """InvokeError.__cause__ is the original _ParseError."""
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError) as exc_info:
            app.call("nonexistent")
        assert exc_info.value.__cause__ is not None

    def test_bad_return_type_raises(self):
        """A raw structured return (not via outcome()) is a hard error."""
        app = _build_app()

        @app.command("bad", help="bad")
        def bad(ctx):
            return {"nope": True}

        with pytest.raises(TypeError, match="strictcli.outcome"):
            app.call("bad")


class TestRunWithStructuredData:
    """Outcome data is JSON-printed to stdout by the framework."""

    def test_prints_json_for_dict(self):
        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data={"healthy": True, "count": 5})

        result = app.test(["status"])
        assert result.exit_code == 0
        assert result.data == {"healthy": True, "count": 5}
        assert json.loads(result.stdout) == {"healthy": True, "count": 5}

    def test_prints_json_for_list(self):
        app = _build_app()

        @app.command("list-items", help="list items")
        def list_items(ctx):
            return strictcli.outcome(data=[1, 2, 3])

        result = app.test(["list-items"])
        assert result.exit_code == 0
        assert result.data == [1, 2, 3]
        assert json.loads(result.stdout) == [1, 2, 3]

    def test_dataclass_serializes_via_default_str(self):
        """Dataclass data serializes to stdout via json.dumps(default=str)."""
        @dataclass
        class Status:
            healthy: bool
            uptime: int

        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data=Status(healthy=True, uptime=3600))

        result = app.test(["status"])
        parsed = json.loads(result.stdout)
        # default=str converts the dataclass to its str() repr
        assert isinstance(parsed, str)
        assert "healthy=True" in parsed
        assert "uptime=3600" in parsed

    def test_nested_non_serializable_uses_default_str(self):
        """Non-serializable values nested in data use default=str on stdout."""
        app = _build_app()

        @app.command("info", help="get info")
        def info(ctx):
            return strictcli.outcome(data={
                "timestamp": datetime(2025, 1, 15, 10, 30, 0),
                "path": PurePosixPath("/usr/local/bin"),
                "count": 42,
            })

        result = app.test(["info"])
        parsed = json.loads(result.stdout)
        assert parsed["timestamp"] == "2025-01-15 10:30:00"
        assert parsed["path"] == "/usr/local/bin"
        assert parsed["count"] == 42

    def test_string_return_serializes_to_json_string(self):
        """String data produces a JSON string on stdout."""
        app = _build_app()

        @app.command("greet", help="greet")
        def greet(ctx):
            return strictcli.outcome(data="hello world")

        result = app.test(["greet"])
        assert json.loads(result.stdout) == "hello world"


class TestAcall:
    """acall() returns same result as call()."""

    def test_acall_returns_dict(self):
        app = _build_app()

        @app.command("status", help="get status")
        def status(ctx):
            return strictcli.outcome(data={"healthy": True})

        result = asyncio.run(app.acall("status"))
        assert result == {"healthy": True}

    def test_acall_returns_int(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            return 42

        result = asyncio.run(app.acall("run"))
        assert result == 42

    def test_acall_returns_none(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        result = asyncio.run(app.acall("run"))
        assert result is None

    def test_acall_raises_invoke_error(self):
        app = _build_app()

        @app.command("run", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown command 'nonexistent'"):
            asyncio.run(app.acall("nonexistent"))

    def test_acall_with_kwargs(self):
        app = _build_app()

        @app.command("greet", help="greet")
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(ctx, name):
            return strictcli.outcome(data={"greeting": f"hello {name}"})

        result = asyncio.run(app.acall("greet", name="Alice"))
        assert result == {"greeting": "hello Alice"}


class TestBackwardCompat:
    """test() behavior for int/None-returning handlers."""

    def test_int_return_sets_exit_code(self):
        app = _build_app()

        @app.command("fail", help="fail")
        def fail(ctx):
            return 1

        result = app.test(["fail"])
        assert result.exit_code == 1
        assert result.data is None

    def test_none_return_exit_code_zero(self):
        app = _build_app()

        @app.command("ok", help="ok")
        def ok(ctx):
            pass

        result = app.test(["ok"])
        assert result.exit_code == 0
        assert result.data is None

    def test_handler_prints_to_stdout(self):
        """Handler print() still captured in result.stdout."""
        app = _build_app()

        @app.command("hello", help="hello")
        def hello(ctx):
            print("hello world")
            return strictcli.outcome(data={"done": True})

        result = app.test(["hello"])
        assert "hello world" in result.stdout
        assert result.data == {"done": True}
        assert result.exit_code == 0

    def test_result_default_data_is_none(self):
        """Result() without data argument defaults to None."""
        r = strictcli.Result(stdout="", stderr="", exit_code=0)
        assert r.data is None

    def test_error_result_data_is_none(self):
        """On parse errors, data remains None."""
        app = _build_app()

        @app.command("greet", help="greet")
        @strictcli.flag("name", type=str, help="name")
        def greet(ctx, name):
            return strictcli.outcome(data={"greeting": f"hello {name}"})

        result = app.test(["greet"])  # missing required --name
        assert result.exit_code == 1
        assert result.data is None


class TestCallNestedCommands:
    """call() resolves dot-separated paths for nested commands."""

    def test_group_command(self):
        app = _build_app()
        grp = app.group("config", help="config management")

        @grp.command("show", help="show config")
        def show(ctx):
            return strictcli.outcome(data={"key": "value"})

        result = app.call("config.show")
        assert result == {"key": "value"}

    def test_deeply_nested_command(self):
        app = _build_app()
        g1 = app.group("infra", help="infrastructure")
        g2 = g1.group("dns", help="DNS management")

        @g2.command("list", help="list DNS records")
        def list_records(ctx):
            return strictcli.outcome(data=["a.example.com", "b.example.com"])

        result = app.call("infra.dns.list")
        assert result == ["a.example.com", "b.example.com"]
