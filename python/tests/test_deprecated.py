"""Tests for deprecated command support."""

import pytest

import strictcli


def _make_app():
    """Create a test app with a normal command and a deprecated command."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("run", help="run something")
    def run():
        return 0

    app.deprecate("old-run", message="use 'run' instead")
    return app


def test_invoke_deprecated_command():
    """Invoking a deprecated command exits 1 with deprecation message on stderr."""
    app = _make_app()
    result = app.test(["old-run"])
    assert result.exit_code == 1
    assert "command 'old-run' is deprecated: use 'run' instead" in result.stderr


def test_app_help_shows_deprecated_section():
    """App help includes a 'Deprecated:' section listing deprecated commands."""
    app = _make_app()
    result = app.test(["--help"])
    assert result.exit_code == 0
    assert "Deprecated:" in result.stdout
    assert "old-run" in result.stdout
    assert "use 'run' instead" in result.stdout


def test_group_help_shows_deprecated_section():
    """Group help includes a 'Deprecated:' section for deprecated subcommands."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")

    @grp.command("show", help="show config")
    def show():
        return 0

    grp.deprecate("dump", message="use 'show' instead")

    result = app.test(["config", "--help"])
    assert result.exit_code == 0
    assert "Deprecated:" in result.stdout
    assert "dump" in result.stdout
    assert "use 'show' instead" in result.stdout


def test_invoke_deprecated_group_subcommand():
    """Invoking a deprecated subcommand in a group exits 1 with message."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")

    @grp.command("show", help="show config")
    def show():
        return 0

    grp.deprecate("dump", message="use 'show' instead")

    result = app.test(["config", "dump"])
    assert result.exit_code == 1
    assert "command 'dump' is deprecated: use 'show' instead" in result.stderr


def test_normal_and_deprecated_coexist():
    """Normal commands work fine alongside deprecated ones."""
    app = _make_app()

    # Normal command works
    result = app.test(["run"])
    assert result.exit_code == 0
    assert result.stderr == ""

    # Deprecated command fails with message
    result = app.test(["old-run"])
    assert result.exit_code == 1
    assert "deprecated" in result.stderr


def test_registration_error_duplicate_with_command():
    """Registering a deprecated command that collides with an existing command raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("run", help="run something")
    def run():
        return 0

    with pytest.raises(ValueError, match='collides with an existing command'):
        app.deprecate("run", message="use something else")


def test_registration_error_duplicate_with_group():
    """Registering a deprecated command that collides with an existing group raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    app.group("config", help="config commands")

    with pytest.raises(ValueError, match='collides with an existing group'):
        app.deprecate("config", message="use something else")


def test_registration_error_duplicate_deprecated():
    """Registering the same deprecated command twice raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    app.deprecate("old-cmd", message="removed")

    with pytest.raises(ValueError, match='already registered'):
        app.deprecate("old-cmd", message="also removed")


def test_registration_error_empty_message():
    """Empty message raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="message must not be empty"):
        app.deprecate("old-cmd", message="")


def test_registration_error_empty_name():
    """Empty name raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="deprecated command name must be a non-empty string"):
        app.deprecate("", message="removed")


def test_group_registration_error_duplicate_with_command():
    """Registering a deprecated subcommand that collides with an existing command raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")

    @grp.command("show", help="show config")
    def show():
        return 0

    with pytest.raises(ValueError, match='collides with an existing command'):
        grp.deprecate("show", message="removed")


def test_group_registration_error_duplicate_deprecated():
    """Registering the same deprecated subcommand twice raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")
    grp.deprecate("old-show", message="removed")

    with pytest.raises(ValueError, match='already registered'):
        grp.deprecate("old-show", message="also removed")


def test_group_registration_error_empty_message():
    """Empty message on group deprecated command raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")

    with pytest.raises(ValueError, match="message must not be empty"):
        grp.deprecate("old-show", message="")
