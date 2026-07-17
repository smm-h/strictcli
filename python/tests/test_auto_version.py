"""Tests for the required App.version field (no auto-detection)."""

import pytest

import strictcli


def test_explicit_version_still_works():
    """App with an explicit version string uses it as-is."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    assert app.version == "1.0.0"


def test_missing_version_is_registration_error():
    """App without a version raises a clear registration-time error."""
    with pytest.raises(ValueError, match=r"App\.version must be a non-empty string"):
        strictcli.App(name="mytool", help="test app")


def test_empty_version_is_registration_error():
    """App with an empty/whitespace version raises a registration-time error."""
    with pytest.raises(ValueError, match=r"App\.version must be a non-empty string"):
        strictcli.App(name="mytool", version="   ", help="test app")


def test_version_output_with_explicit_version():
    """--version shows the explicit version string."""
    app = strictcli.App(name="myapp", version="5.6.7", help="test app")

    @app.command("noop", help="does nothing")
    def noop(ctx):
        pass

    r = app.test(["--version"])
    assert r.exit_code == 0
    assert "myapp 5.6.7" in r.stdout


def test_help_shows_explicit_version():
    """Help output includes the explicit version."""
    app = strictcli.App(name="mytool", version="3.2.1", help="a great tool")

    @app.command("noop", help="does nothing")
    def noop(ctx):
        pass

    r = app.test([])
    assert r.exit_code == 0
    assert "mytool v3.2.1" in r.stdout
