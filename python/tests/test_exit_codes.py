"""Tests for handler return value as exit code."""

import sys

import strictcli


def _make_app(handler):
    """Build a minimal app with a single command wired to the given handler."""
    app = strictcli.App(name="testapp", version="0.1.0", help="test app")
    app.command("run", help="run handler")(handler)
    return app


def test_handler_returns_zero():
    def handler():
        return 0

    result = _make_app(handler).test(["run"])
    assert result.exit_code == 0


def test_handler_returns_one():
    def handler():
        return 1

    result = _make_app(handler).test(["run"])
    assert result.exit_code == 1


def test_handler_returns_42():
    def handler():
        return 42

    result = _make_app(handler).test(["run"])
    assert result.exit_code == 42


def test_handler_returns_none():
    """Backward compat: None is treated as exit code 0."""

    def handler():
        pass  # implicitly returns None

    result = _make_app(handler).test(["run"])
    assert result.exit_code == 0


def test_handler_calls_sys_exit():
    """sys.exit() in handler still works as before."""

    def handler():
        sys.exit(2)

    result = _make_app(handler).test(["run"])
    assert result.exit_code == 2
