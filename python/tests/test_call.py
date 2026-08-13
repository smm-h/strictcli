"""Tests for App.call(), App.acall(), and Outcome-based handler returns."""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

import pytest
from conftest import payload

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


class TestCallReturnsInt:
    """Handler returning int: call() returns int, test().data is None."""

    def test_call_returns_int(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            return 42

        assert app.call("run") == 42

    def test_test_data_is_none_for_int_return(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            return 42

        result = app.test(["run"])
        assert result.data is None
        assert result.exit_code == 42

    def test_test_data_is_none_for_zero(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            return 0

        result = app.test(["run"])
        assert result.data is None
        assert result.exit_code == 0


class TestCallReturnsNone:
    """Handler returning None: call() returns None, test().data is None."""

    def test_call_returns_none(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        assert app.call("run") is None

    def test_test_data_is_none(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        result = app.test(["run"])
        assert result.data is None
        assert result.exit_code == 0


class TestCallReturnsDict:
    """Handler returning outcome(data=dict): call() returns dict, test().data is dict."""

    def test_call_returns_dict(self):
        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload({"healthy": True, "uptime": 3600})
            return strictcli.outcome()

        result = app.call("status")
        assert result == {"healthy": True, "uptime": 3600}

    def test_test_data_is_dict(self):
        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload({"healthy": True, "uptime": 3600})
            return strictcli.outcome()

        result = app.test(["status"])
        assert result.data == {"healthy": True, "uptime": 3600}
        assert result.exit_code == 0

    def test_call_with_flags(self):
        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        @strictcli.flag("loud", type=bool, default=False, help="include details")
        def status(ctx, loud):
            data = {"healthy": True}
            if loud:
                data["details"] = "all systems operational"
            ctx.payload(data)
            return strictcli.outcome()

        result = app.call("status", loud=True)
        assert result == {"healthy": True, "details": "all systems operational"}


class TestCallReturnsList:
    """Handler returning outcome(data=list): call() returns list."""

    def test_call_returns_list(self):
        app = _build_app()

        @app.command("list-users", effect="read_only", help="list users", payload_schema={})
        def list_users(ctx):
            ctx.payload(["alice", "bob", "charlie"])
            return strictcli.outcome()

        result = app.call("list-users")
        assert result == ["alice", "bob", "charlie"]

    def test_test_data_is_list(self):
        app = _build_app()

        @app.command("list-users", effect="read_only", help="list users", payload_schema={})
        def list_users(ctx):
            ctx.payload(["alice", "bob", "charlie"])
            return strictcli.outcome()

        result = app.test(["list-users"])
        assert result.data == ["alice", "bob", "charlie"]
        assert result.exit_code == 0


class TestCallRejectsNonJSONPayloads:
    """A payload must be a JSON value (contract §19.5).

    A dataclass instance is not one, and no schema can describe it, so
    ``ctx.payload`` refuses it at the call rather than letting the serializer
    invent a shape for it. The declaration and the emitted document are the
    same artifact; a value the declaration cannot describe has no place in it.
    """

    def test_call_rejects_a_dataclass(self):
        @dataclass
        class Status:
            healthy: bool
            uptime: int

        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload(Status(healthy=True, uptime=3600))
            return strictcli.outcome()

        with pytest.raises(RuntimeError) as e:
            app.call("status")
        assert str(e.value) == (
            'command "status": payload does not satisfy the declared schema '
            "at payload: the value is not representable in JSON"
        )

    def test_test_rejects_a_dataclass(self):
        @dataclass
        class Status:
            healthy: bool
            uptime: int

        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload(Status(healthy=True, uptime=3600))
            return strictcli.outcome()

        with pytest.raises(RuntimeError, match="not representable in JSON"):
            app.test(["status"])

    def test_a_dict_of_the_same_fields_is_accepted(self):
        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload({"healthy": True, "uptime": 3600})
            return strictcli.outcome()

        assert app.call("status") == {"healthy": True, "uptime": 3600}


class TestCallReturnsString:
    """Handler returning outcome(data=str): call() returns string."""

    def test_call_returns_string(self):
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet", payload_schema={})
        def greet(ctx):
            ctx.payload("hello world")
            return strictcli.outcome()

        result = app.call("greet")
        assert result == "hello world"

    def test_test_data_is_string(self):
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet", payload_schema={})
        def greet(ctx):
            ctx.payload("hello world")
            return strictcli.outcome()

        result = app.test(["greet"])
        assert result.data == "hello world"
        assert result.exit_code == 0


class TestCallErrorCases:
    """call() raises InvokeError (not SystemExit) for errors."""

    def test_unknown_command(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown command 'nonexistent'"):
            app.call("nonexistent")

    def test_missing_required_flag(self):
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet")
        @strictcli.flag("name", type=str, help="name")
        def greet(ctx, name):
            pass

        with pytest.raises(strictcli.InvokeError, match="flag '--name' is required"):
            app.call("greet")

    def test_missing_required_arg(self):
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target")],
        )
        def deploy(ctx, target):
            pass

        with pytest.raises(strictcli.InvokeError, match="missing required argument 'target'"):
            app.call("deploy")

    def test_unknown_kwarg(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown parameter 'bogus'"):
            app.call("run", bogus="value")

    def test_mutex_violation(self):
        app = _build_app()

        @app.command(
            "fmt", effect="read_only", help="format",
            mutex=[strictcli.MutexGroup(
                flags=[
                    strictcli.Flag(name="as-json", type=bool, default=False, help="JSON output"),
                    strictcli.Flag(name="yaml", type=bool, default=False, help="YAML output"),
                ],
            )],
        )
        def fmt(ctx, as_json, yaml):
            pass

        with pytest.raises(strictcli.InvokeError, match="mutually exclusive"):
            app.call("fmt", as_json=True, yaml=True)

    def test_group_path_raises(self):
        """Calling a group (not a command) raises InvokeError."""
        app = _build_app()
        grp = app.group("config", help="config management")

        @grp.command("show", effect="read_only", help="show config")
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

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError) as exc_info:
            app.call("nonexistent")
        assert exc_info.value.__cause__ is not None

    def test_bad_return_type_raises(self):
        """A raw structured return (not via outcome()) is a hard error."""
        app = _build_app()

        @app.command("bad", effect="read_only", help="bad")
        def bad(ctx):
            return {"nope": True}

        with pytest.raises(TypeError, match="strictcli.outcome"):
            app.call("bad")


class TestRunWithStructuredData:
    """The machine payload is JSON-printed to stdout in machine mode.

    Outside machine mode the payload is captured by ``test()`` and printed
    nowhere at all (contract §19.4), so every case here passes ``--json``.
    """

    def test_prints_json_for_dict(self):
        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload({"healthy": True, "count": 5})
            return strictcli.outcome()

        result = app.test(["status", "--json"])
        assert result.exit_code == 0
        assert result.data == {"healthy": True, "count": 5}
        assert payload(result) == {"healthy": True, "count": 5}

    def test_prints_json_for_list(self):
        app = _build_app()

        @app.command("list-items", effect="read_only", help="list items", payload_schema={})
        def list_items(ctx):
            ctx.payload([1, 2, 3])
            return strictcli.outcome()

        result = app.test(["list-items", "--json"])
        assert result.exit_code == 0
        assert result.data == [1, 2, 3]
        assert payload(result) == [1, 2, 3]

    def test_a_dataclass_is_refused_instead_of_stringified(self):
        """A dataclass payload fails at the call (contract §19.5).

        The serializer used to fall back to ``str()`` here, which shipped a
        JSON string where a consumer expected an object. Emission-time
        validation replaces that with a refusal.
        """
        @dataclass
        class Status:
            healthy: bool
            uptime: int

        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload(Status(healthy=True, uptime=3600))
            return strictcli.outcome()

        with pytest.raises(RuntimeError, match="not representable in JSON"):
            app.test(["status", "--json"])

    def test_a_nested_non_serializable_value_is_refused_by_path(self):
        """The refusal names the exact node that cannot be emitted."""
        app = _build_app()

        @app.command("info", effect="read_only", help="get info", payload_schema={})
        def info(ctx):
            ctx.payload({
                "timestamp": datetime(2025, 1, 15, 10, 30, 0),
                "path": PurePosixPath("/usr/local/bin"),
                "count": 42,
            })
            return strictcli.outcome()

        with pytest.raises(RuntimeError) as e:
            app.test(["info", "--json"])
        # Sorted traversal reaches "path" before "timestamp".
        assert str(e.value) == (
            'command "info": payload does not satisfy the declared schema at '
            'payload["path"]: the value is not representable in JSON'
        )

    def test_an_isoformat_string_is_the_way_to_carry_a_timestamp(self):
        app = _build_app()

        @app.command("info", effect="read_only", help="get info", payload_schema={})
        def info(ctx):
            ctx.payload({
                "timestamp": datetime(2025, 1, 15, 10, 30, 0).isoformat(),
                "path": str(PurePosixPath("/usr/local/bin")),
                "count": 42,
            })
            return strictcli.outcome()

        result = app.test(["info", "--json"])
        parsed = payload(result)
        assert parsed["timestamp"] == "2025-01-15T10:30:00"
        assert parsed["path"] == "/usr/local/bin"
        assert parsed["count"] == 42

    def test_string_return_serializes_to_json_string(self):
        """String data produces a JSON string on stdout."""
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet", payload_schema={})
        def greet(ctx):
            ctx.payload("hello world")
            return strictcli.outcome()

        result = app.test(["greet", "--json"])
        assert payload(result) == "hello world"


class TestAcall:
    """acall() returns same result as call()."""

    def test_acall_returns_dict(self):
        app = _build_app()

        @app.command("status", effect="read_only", help="get status", payload_schema={})
        def status(ctx):
            ctx.payload({"healthy": True})
            return strictcli.outcome()

        result = asyncio.run(app.acall("status"))
        assert result == {"healthy": True}

    def test_acall_returns_int(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            return 42

        result = asyncio.run(app.acall("run"))
        assert result == 42

    def test_acall_returns_none(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        result = asyncio.run(app.acall("run"))
        assert result is None

    def test_acall_raises_invoke_error(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown command 'nonexistent'"):
            asyncio.run(app.acall("nonexistent"))

    def test_acall_with_kwargs(self):
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet", payload_schema={})
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(ctx, name):
            ctx.payload({"greeting": f"hello {name}"})
            return strictcli.outcome()

        result = asyncio.run(app.acall("greet", name="Alice"))
        assert result == {"greeting": "hello Alice"}


class TestBackwardCompat:
    """test() behavior for int/None-returning handlers."""

    def test_int_return_sets_exit_code(self):
        app = _build_app()

        @app.command("fail", effect="read_only", help="fail")
        def fail(ctx):
            return 1

        result = app.test(["fail"])
        assert result.exit_code == 1
        assert result.data is None

    def test_none_return_exit_code_zero(self):
        app = _build_app()

        @app.command("ok", effect="read_only", help="ok")
        def ok(ctx):
            pass

        result = app.test(["ok"])
        assert result.exit_code == 0
        assert result.data is None

    def test_handler_prints_to_stdout(self):
        """Handler print() still captured in result.stdout."""
        app = _build_app()

        @app.command("hello", effect="read_only", help="hello", payload_schema={})
        def hello(ctx):
            print("hello world")
            ctx.payload({"done": True})
            return strictcli.outcome()

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

        @app.command("greet", effect="read_only", help="greet", payload_schema={})
        @strictcli.flag("name", type=str, help="name")
        def greet(ctx, name):
            ctx.payload({"greeting": f"hello {name}"})
            return strictcli.outcome()

        result = app.test(["greet"])  # missing required --name
        assert result.exit_code == 1
        assert result.data is None


class TestCallNestedCommands:
    """call() resolves dot-separated paths for nested commands."""

    def test_group_command(self):
        app = _build_app()
        grp = app.group("config", help="config management")

        @grp.command("show", effect="read_only", help="show config", payload_schema={})
        def show(ctx):
            ctx.payload({"key": "value"})
            return strictcli.outcome()

        result = app.call("config.show")
        assert result == {"key": "value"}

    def test_deeply_nested_command(self):
        app = _build_app()
        g1 = app.group("infra", help="infrastructure")
        g2 = g1.group("dns", help="DNS management")

        @g2.command("list", effect="read_only", help="list DNS records", payload_schema={})
        def list_records(ctx):
            ctx.payload(["a.example.com", "b.example.com"])
            return strictcli.outcome()

        result = app.call("infra.dns.list")
        assert result == ["a.example.com", "b.example.com"]
