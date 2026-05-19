"""Tests for auto-version detection from package metadata."""

from unittest.mock import patch

import strictcli


def test_explicit_version_still_works():
    """App with an explicit version string uses it as-is."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    assert app.version == "1.0.0"


def test_version_none_non_installed_package():
    """App with version=None and a non-installed package gets 'unknown'."""
    app = strictcli.App(name="not-a-real-package-xyz", help="test app")
    assert app.version == "unknown"


def test_version_none_auto_detects_installed_package():
    """App with version=None picks up version from importlib.metadata."""
    with patch("importlib.metadata.version", return_value="2.3.4"):
        app = strictcli.App(name="my-package", help="test app")
    assert app.version == "2.3.4"


def test_version_output_with_explicit_version():
    """--version shows the explicit version string."""
    app = strictcli.App(name="myapp", version="5.6.7", help="test app")

    @app.command("noop", help="does nothing")
    def noop():
        pass

    r = app.test(["--version"])
    assert r.exit_code == 0
    assert "myapp 5.6.7" in r.stdout


def test_version_output_with_auto_detected_version():
    """--version shows the auto-detected version from package metadata."""
    with patch("importlib.metadata.version", return_value="9.8.7"):
        app = strictcli.App(name="my-tool", help="test app")

    @app.command("noop", help="does nothing")
    def noop():
        pass

    r = app.test(["--version"])
    assert r.exit_code == 0
    assert "my-tool 9.8.7" in r.stdout


def test_version_output_with_unknown_fallback():
    """--version shows 'unknown' when package is not installed."""
    app = strictcli.App(name="not-installed-pkg-abc", help="test app")

    @app.command("noop", help="does nothing")
    def noop():
        pass

    r = app.test(["--version"])
    assert r.exit_code == 0
    assert "not-installed-pkg-abc unknown" in r.stdout


def test_help_shows_auto_detected_version():
    """Help output includes the auto-detected version."""
    with patch("importlib.metadata.version", return_value="3.2.1"):
        app = strictcli.App(name="mytool", help="a great tool")

    @app.command("noop", help="does nothing")
    def noop():
        pass

    r = app.test([])
    assert r.exit_code == 0
    assert "mytool v3.2.1" in r.stdout
