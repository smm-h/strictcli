"""Tests for Arg default value support."""

import pytest

import strictcli


def test_optional_arg_with_default_value_provided():
    """Optional arg with default, value provided -> uses provided value."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="path", help="project directory", default=".")],
    )
    def cmd(ctx, path):
        print(f"path={path}")

    r = app.test(["cmd", "/tmp/foo"])
    assert r.exit_code == 0
    assert "path=/tmp/foo" in r.stdout


def test_optional_arg_with_default_value_omitted():
    """Optional arg with default, value omitted -> uses default."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="path", help="project directory", default=".")],
    )
    def cmd(ctx, path):
        print(f"path={path}")

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "path=." in r.stdout


def test_optional_arg_without_default_omitted():
    """Optional arg without default, value omitted -> omitted from kwargs (backward compat)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="path", help="project directory", presence="optional")],
    )
    def cmd(ctx, path=None):
        print(f"path={path}")

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "path=None" in r.stdout


def test_required_arg_with_default_raises():
    """Required arg with default -> the two-declared presence error.

    The old `required arg cannot have a default` message is deleted: the
    two-declared error says the same thing for every pair and names both
    spellings (contract §12.12).
    """
    with pytest.raises(ValueError) as exc:
        strictcli.Arg(
            name="path", help="project directory",
            presence="required", default=".",
        )
    assert str(exc.value) == (
        'Arg "path": presence is declared twice: presence="required" and '
        "default=. cannot be combined; declare exactly one"
    )


def test_default_shown_in_help():
    """Default value shown in help output for optional args."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="path", help="project directory", default=".")],
    )
    def cmd(ctx, path):
        print(f"path={path}")

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "path" in r.stdout
    assert "[default: .]" in r.stdout


def test_optional_arg_without_default_shows_optional_in_help():
    """Optional arg without default shows [optional] in help, not [default: ...]."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="path", help="project directory", presence="optional")],
    )
    def cmd(ctx, path=None):
        print(f"path={path}")

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "[optional]" in r.stdout
    assert "[default:" not in r.stdout


def test_multiple_args_first_required_second_optional_with_default():
    """Multiple args: first required, second optional with default."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[
            strictcli.Arg(name="src", help="source file", presence="required"),
            strictcli.Arg(name="dst", help="destination", default="out"),
        ],
    )
    def cmd(ctx, src, dst):
        print(f"src={src} dst={dst}")

    # Both provided
    r = app.test(["cmd", "input.txt", "output.txt"])
    assert r.exit_code == 0
    assert "src=input.txt" in r.stdout
    assert "dst=output.txt" in r.stdout

    # Only required provided, optional gets default
    r = app.test(["cmd", "input.txt"])
    assert r.exit_code == 0
    assert "src=input.txt" in r.stdout
    assert "dst=out" in r.stdout


def test_handler_receives_default_when_arg_omitted():
    """Handler receives the default value as a kwarg when the arg is omitted."""
    received = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="path", help="project directory", default=".")],
    )
    def cmd(ctx, path):
        received["path"] = path

    app.test(["cmd"])
    assert received["path"] == "."


def test_arg_decorator_with_default():
    """The arg() decorator passes default through to Arg."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.arg("path", help="project directory", default=".")
    def cmd(ctx, path):
        print(f"path={path}")

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "path=." in r.stdout


def test_arg_decorator_required_with_default_raises():
    """The arg() decorator with presence="required" and a default raises."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError) as exc:

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.arg(
            "path", help="project directory", presence="required", default=".",
        )
        def cmd(ctx, path):
            pass

    assert str(exc.value) == (
        'Arg "path": presence is declared twice: presence="required" and '
        "default=. cannot be combined; declare exactly one"
    )
