"""Tests for Flag(choices=[...]) support."""

import pytest

import strictcli


def _make_app_with_choices(**flag_kwargs):
    """Helper: app with a single command that has one flag with choices."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("format", help="output format", **flag_kwargs)
    def cmd(format):
        print(f"format={format}")

    return app


def test_valid_choice_accepted():
    """A value that is in the choices list is accepted."""
    app = _make_app_with_choices(choices=["text", "json"])
    r = app.test(["cmd", "--format", "json"])
    assert r.exit_code == 0
    assert "format=json" in r.stdout


def test_invalid_choice_rejected():
    """A value not in choices is rejected with an error listing valid options."""
    app = _make_app_with_choices(choices=["text", "json"])
    r = app.test(["cmd", "--format", "xml"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr
    assert "'xml'" in r.stderr
    assert "text" in r.stderr
    assert "json" in r.stderr


def test_choices_shown_in_help():
    """Choices are displayed in the help output."""
    app = _make_app_with_choices(choices=["text", "json"], default="text")
    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "choices: text, json" in r.stdout


def test_choices_with_int_type():
    """Choices work with type=int."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("port", type=int, help="the port", choices=[80, 443, 8080])
    def cmd(port):
        print(f"port={port}")

    r = app.test(["cmd", "--port", "443"])
    assert r.exit_code == 0
    assert "port=443" in r.stdout


def test_invalid_int_choice_rejected():
    """An int value not in choices is rejected."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("port", type=int, help="the port", choices=[80, 443, 8080])
    def cmd(port):
        print(f"port={port}")

    r = app.test(["cmd", "--port", "9090"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr
    assert "9090" in r.stderr
    assert "80" in r.stderr
    assert "443" in r.stderr
    assert "8080" in r.stderr


def test_choices_with_env_var_valid(monkeypatch):
    """A valid env var value that is in choices is accepted."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "format", help="output format", choices=["text", "json"],
        default="text", env="MYAPP_FORMAT",
    )
    def cmd(format):
        print(f"format={format}")

    monkeypatch.setenv("MYAPP_FORMAT", "json")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "format=json" in r.stdout


def test_choices_with_env_var_invalid(monkeypatch):
    """An env var value not in choices is rejected."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "format", help="output format", choices=["text", "json"],
        default="text", env="MYAPP_FORMAT",
    )
    def cmd(format):
        print(f"format={format}")

    monkeypatch.setenv("MYAPP_FORMAT", "xml")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr
    assert "'xml'" in r.stderr


def test_default_must_be_in_choices():
    """A default value not in the choices list raises ValueError at registration."""
    with pytest.raises(ValueError, match="default.*not in choices"):
        strictcli.Flag(
            name="format", type=str, help="output format",
            choices=["text", "json"], default="xml",
        )


def test_choices_with_bool_raises():
    """choices with type=bool raises ValueError at registration."""
    with pytest.raises(ValueError, match="incompatible with type=bool"):
        strictcli.Flag(
            name="verbose", type=bool, help="be verbose",
            choices=[True, False],
        )


def test_empty_choices_raises():
    """An empty choices list raises ValueError at registration."""
    with pytest.raises(ValueError, match="non-empty list"):
        strictcli.Flag(
            name="format", type=str, help="output format",
            choices=[],
        )
