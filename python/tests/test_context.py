"""Tests for Context class and Context injection into handlers."""

import io
import json

import pytest

import strictcli
from strictcli import Context


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


class TestContextOutputRouting:
    """Context.info/warn/debug/error route to correct streams."""

    def test_info_writes_to_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        ctx = Context(stdout=stdout, stderr=stderr)
        ctx.info("hello")
        assert stdout.getvalue() == "hello\n"
        assert stderr.getvalue() == ""

    def test_warn_writes_to_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        ctx = Context(stdout=stdout, stderr=stderr)
        ctx.warn("careful")
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == "careful\n"

    def test_debug_writes_to_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        ctx = Context(stdout=stdout, stderr=stderr)
        ctx.debug("trace")
        assert stdout.getvalue() == "trace\n"
        assert stderr.getvalue() == ""

    def test_error_writes_to_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        ctx = Context(stdout=stdout, stderr=stderr)
        ctx.error("fail")
        assert stdout.getvalue() == ""
        assert stderr.getvalue() == "fail\n"


class TestContextEmit:
    """Emit writes JSON to stdout and stores data."""

    def test_emit_writes_json_to_stdout(self):
        stdout = io.StringIO()
        ctx = Context(stdout=stdout)
        ctx.emit({"key": "value"})
        assert stdout.getvalue() == '{"key": "value"}\n'

    def test_emit_stores_data(self):
        ctx = Context(stdout=io.StringIO())
        data = {"count": 42}
        ctx.emit(data)
        assert ctx._emit_data == {"count": 42}
        assert ctx._emit_called is True

    def test_emit_none_is_valid(self):
        """None is valid emit data -- sentinel distinguishes 'not called' from 'called with None'."""
        stdout = io.StringIO()
        ctx = Context(stdout=stdout)
        ctx.emit(None)
        assert ctx._emit_data is None
        assert ctx._emit_called is True
        assert stdout.getvalue() == "null\n"

    def test_emit_called_twice_raises(self):
        ctx = Context(stdout=io.StringIO())
        ctx.emit("first")
        with pytest.raises(RuntimeError, match="emit called more than once"):
            ctx.emit("second")

    def test_emit_list(self):
        stdout = io.StringIO()
        ctx = Context(stdout=stdout)
        ctx.emit([1, 2, 3])
        assert json.loads(stdout.getvalue()) == [1, 2, 3]

    def test_emit_string(self):
        stdout = io.StringIO()
        ctx = Context(stdout=stdout)
        ctx.emit("hello")
        assert json.loads(stdout.getvalue()) == "hello"

    def test_emit_not_called_sentinel(self):
        """Before emit is called, _emit_data is the sentinel, not None."""
        ctx = Context(stdout=io.StringIO())
        assert ctx._emit_called is False
        from strictcli import _MissingSentinel
        assert isinstance(ctx._emit_data, _MissingSentinel)


class TestContextInjection:
    """Handler with `ctx: Context` first param receives a Context."""

    def test_handler_receives_context(self):
        app = _build_app()
        captured = {}

        @app.command("greet", help="greet someone")
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(ctx: Context, name):
            captured["ctx"] = ctx
            captured["name"] = name
            ctx.info(f"Hello, {name}!")

        result = app.test(["greet", "--name", "Alice"])
        assert result.exit_code == 0
        assert isinstance(captured["ctx"], Context)
        assert captured["name"] == "Alice"
        assert "Hello, Alice!" in result.stdout

    def test_handler_without_context_works_as_before(self):
        app = _build_app()
        captured = {}

        @app.command("greet", help="greet someone")
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(name):
            captured["name"] = name
            print(f"Hello, {name}!")

        result = app.test(["greet", "--name", "Bob"])
        assert result.exit_code == 0
        assert captured["name"] == "Bob"
        assert "Hello, Bob!" in result.stdout

    def test_context_handler_with_no_flags(self):
        app = _build_app()
        captured = {}

        @app.command("ping", help="ping")
        def ping(ctx: Context):
            captured["ctx"] = ctx
            ctx.info("pong")

        result = app.test(["ping"])
        assert result.exit_code == 0
        assert isinstance(captured["ctx"], Context)
        assert "pong" in result.stdout


class TestContextWithTest:
    """test() on Context-aware handler captures Context output."""

    def test_context_info_captured_in_stdout(self):
        app = _build_app()

        @app.command("say", help="say something")
        @strictcli.flag("msg", type=str, help="message")
        def say(ctx: Context, msg):
            ctx.info(msg)

        result = app.test(["say", "--msg", "hello"])
        assert result.exit_code == 0
        assert result.stdout == "hello\n"

    def test_context_warn_captured_in_stderr(self):
        app = _build_app()

        @app.command("warn-me", help="warn")
        def warn_me(ctx: Context):
            ctx.warn("danger")

        result = app.test(["warn-me"])
        assert result.exit_code == 0
        assert result.stderr == "danger\n"

    def test_context_emit_captured_in_test(self):
        app = _build_app()

        @app.command("data", help="return data")
        def data(ctx: Context):
            ctx.emit({"result": 42})

        result = app.test(["data"])
        assert result.exit_code == 0
        assert result.data == {"result": 42}
        assert json.loads(result.stdout) == {"result": 42}

    def test_context_emit_none_captured(self):
        app = _build_app()

        @app.command("empty", help="emit None")
        def empty(ctx: Context):
            ctx.emit(None)

        result = app.test(["empty"])
        assert result.exit_code == 0
        assert result.data is None
        assert result.stdout == "null\n"


class TestContextWithCall:
    """call() on Context-aware handler with emit returns emit'd data."""

    def test_call_returns_emitted_data(self):
        app = _build_app()

        @app.command("compute", help="compute something")
        @strictcli.flag("x", type=int, help="value")
        def compute(ctx: Context, x):
            ctx.emit({"squared": x * x})

        result = app.call("compute", x=5)
        assert result == {"squared": 25}

    def test_call_returns_handler_return_when_no_emit(self):
        app = _build_app()

        @app.command("compute", help="compute")
        @strictcli.flag("x", type=int, help="value")
        def compute(ctx: Context, x):
            return x * 2

        result = app.call("compute", x=5)
        assert result == 10

    def test_call_prefers_emit_over_return_value(self):
        """When handler both emits and returns, emit takes precedence."""
        app = _build_app()

        @app.command("both", help="both emit and return")
        def both(ctx: Context):
            ctx.emit({"from": "emit"})
            return {"from": "return"}

        result = app.call("both")
        assert result == {"from": "emit"}

    def test_call_without_context_works_as_before(self):
        app = _build_app()

        @app.command("add", help="add")
        @strictcli.flag("a", type=int, help="first")
        @strictcli.flag("b", type=int, help="second")
        def add(a, b):
            return a + b

        result = app.call("add", a=3, b=4)
        assert result == 7


class TestContextRegistration:
    """needs_context is set at registration time."""

    def test_needs_context_true_for_context_handler(self):
        app = _build_app()

        @app.command("cmd", help="test")
        def cmd(ctx: Context):
            pass

        # Access the registered command
        registered = app._commands["cmd"]
        assert registered.needs_context is True

    def test_needs_context_false_for_regular_handler(self):
        app = _build_app()

        @app.command("cmd", help="test")
        def cmd():
            pass

        registered = app._commands["cmd"]
        assert registered.needs_context is False

    def test_context_param_must_be_first(self):
        """Context annotation on non-first param is treated as extra parameter error."""
        app = _build_app()
        with pytest.raises(ValueError, match="extra parameter"):
            @app.command("bad", help="test")
            @strictcli.flag("x", type=int, help="value")
            def bad(x, ctx: Context):
                pass

    def test_context_handler_with_multiple_flags(self):
        app = _build_app()
        captured = {}

        @app.command("multi", help="multi-flag test")
        @strictcli.flag("name", type=str, help="name")
        @strictcli.flag("count", type=int, help="count")
        @strictcli.flag("verbose", type=bool, default=False, help="verbose")
        def multi(ctx: Context, name, count, verbose):
            captured.update(name=name, count=count, verbose=verbose)
            ctx.info(f"{name}: {count}")

        result = app.test(["multi", "--name", "test", "--count", "3"])
        assert result.exit_code == 0
        assert captured["name"] == "test"
        assert captured["count"] == 3
        assert captured["verbose"] is False
        assert "test: 3" in result.stdout


class TestContextWithGroups:
    """Context injection works with nested groups."""

    def test_context_in_grouped_command(self):
        app = _build_app()
        grp = app.group("svc", help="service commands")
        captured = {}

        @grp.command("status", help="show status")
        def status(ctx: Context):
            captured["ctx"] = ctx
            ctx.info("running")

        result = app.test(["svc", "status"])
        assert result.exit_code == 0
        assert isinstance(captured["ctx"], Context)
        assert "running" in result.stdout


class TestContextWithInvoke:
    """_invoke() handles Context injection."""

    def test_invoke_with_context_handler(self):
        app = _build_app()
        captured = {}

        @app.command("cmd", help="test")
        @strictcli.flag("x", type=int, help="value")
        def cmd(ctx: Context, x):
            captured["x"] = x
            ctx.emit({"doubled": x * 2})

        result = app._invoke("cmd", {"x": 3})
        assert result == {"doubled": 6}
        assert captured["x"] == 3

    def test_invoke_without_context_handler(self):
        app = _build_app()
        captured = {}

        @app.command("cmd", help="test")
        @strictcli.flag("x", type=int, help="value")
        def cmd(x):
            captured["x"] = x
            return x + 1

        result = app._invoke("cmd", {"x": 3})
        assert result == 4
