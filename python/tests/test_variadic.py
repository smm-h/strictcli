"""Tests for variadic positional args."""

import pytest

import strictcli


def test_variadic_collects_multiple_values():
    """Variadic arg collects all remaining positionals into a list."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="files", help="input files", variadic=True)],
    )
    def cmd(files):
        print(f"files={files}")

    r = app.test(["cmd", "a.txt", "b.txt", "c.txt"])
    assert r.exit_code == 0
    assert "files=['a.txt', 'b.txt', 'c.txt']" in r.stdout


def test_variadic_collects_single_value():
    """Variadic arg with a single positional produces a one-element list."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="files", help="input files", variadic=True)],
    )
    def cmd(files):
        print(f"files={files}")

    r = app.test(["cmd", "only.txt"])
    assert r.exit_code == 0
    assert "files=['only.txt']" in r.stdout


def test_variadic_required_zero_values_error():
    """Variadic arg with required=True and zero values -> error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="files", help="input files", variadic=True)],
    )
    def cmd(files):
        pass

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "missing required argument 'files'" in r.stderr


def test_variadic_optional_zero_values_empty_list():
    """Variadic arg with required=False and zero values -> empty list."""
    received = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="files", help="input files", required=False, variadic=True)],
    )
    def cmd(files):
        received["files"] = files

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert received["files"] == []


def test_variadic_after_double_dash():
    """Tokens after -- are treated as positionals even if flag-like."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="args", help="arguments", variadic=True)],
    )
    def cmd(args):
        print(f"args={args}")

    r = app.test(["cmd", "--", "--flag", "-x", "value"])
    assert r.exit_code == 0
    assert "args=['--flag', '-x', 'value']" in r.stdout


def test_variadic_with_preceding_required_arg():
    """Variadic arg after a required fixed arg."""
    received = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[
            strictcli.Arg(name="src", help="source directory"),
            strictcli.Arg(name="files", help="files to copy", variadic=True),
        ],
    )
    def cmd(src, files):
        received["src"] = src
        received["files"] = files

    r = app.test(["cmd", "/src", "a.txt", "b.txt"])
    assert r.exit_code == 0
    assert received["src"] == "/src"
    assert received["files"] == ["a.txt", "b.txt"]


def test_variadic_shown_in_help():
    """Variadic arg shown as 'name...' in help output."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="files", help="input files", variadic=True)],
    )
    def cmd(files):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "files..." in r.stdout


def test_multiple_variadic_args_registration_error():
    """Multiple variadic args -> ValueError at registration."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="at most one variadic arg"):

        @app.command(
            "cmd",
            help="a command",
            args=[
                strictcli.Arg(name="a", help="first", variadic=True),
                strictcli.Arg(name="b", help="second", variadic=True),
            ],
        )
        def cmd(a, b):
            pass


def test_variadic_not_last_arg_registration_error():
    """Variadic arg not in last position -> ValueError at registration."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match='variadic arg "files" must be the last arg'):

        @app.command(
            "cmd",
            help="a command",
            args=[
                strictcli.Arg(name="files", help="input files", variadic=True),
                strictcli.Arg(name="dest", help="destination"),
            ],
        )
        def cmd(files, dest):
            pass


def test_variadic_required_with_default_registration_error():
    """Variadic + required=True + default -> ValueError (required+default already caught)."""
    with pytest.raises(ValueError, match="required arg cannot have a default"):
        strictcli.Arg(name="files", help="input files", required=True, default=["x"], variadic=True)


def test_handler_receives_list_type():
    """Handler receives a list object for variadic args."""
    received = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="items", help="items", variadic=True)],
    )
    def cmd(items):
        received["items"] = items

    app.test(["cmd", "x", "y"])
    assert isinstance(received["items"], list)
    assert received["items"] == ["x", "y"]
