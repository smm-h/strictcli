"""Tests for two-level nesting (groups with subcommands)."""

import strictcli


def _make_group_app():
    """Helper: app with a group containing subcommands."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")
    grp = app.group("config", help="manage configuration")

    @grp.command("show", help="display current config")
    def show():
        print("showing config")

    @grp.command("set", help="set a config value")
    @strictcli.flag("key", type=str, help="config key")
    @strictcli.flag("value", type=str, help="config value")
    def set_(key, value):
        print(f"set {key}={value}")

    return app


def test_group_command_dispatch():
    """app.test(['group', 'sub']) dispatches to subcommand."""
    app = _make_group_app()
    r = app.test(["config", "show"])
    assert r.exit_code == 0
    assert "showing config" in r.stdout


def test_group_command_with_flags():
    """Group subcommand with flags works."""
    app = _make_group_app()
    r = app.test(["config", "set", "--key", "name", "--value", "strictcli"])
    assert r.exit_code == 0
    assert "set name=strictcli" in r.stdout


def test_unknown_group_subcommand():
    """Unknown group subcommand raises error."""
    app = _make_group_app()
    r = app.test(["config", "delete"])
    assert r.exit_code == 1
    assert "unknown command" in r.stderr


def test_group_help_shows_subcommands():
    """Group help shows subcommands."""
    app = _make_group_app()
    r = app.test(["config", "--help"])
    assert r.exit_code == 0
    assert "show" in r.stdout
    assert "set" in r.stdout
    assert "display current config" in r.stdout
    assert "set a config value" in r.stdout


def test_nested_command_help_shows_group_prefix():
    """Nested command help shows group prefix in usage line."""
    app = _make_group_app()
    r = app.test(["config", "set", "--help"])
    assert r.exit_code == 0
    # The help should show "myapp config set" not just "myapp set"
    assert "config set" in r.stdout
