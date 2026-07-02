"""Tests for help output formatting."""

import strictcli


def _make_full_app():
    """Helper: app with commands, a group, and flags."""
    app = strictcli.App(name="myapp", version="2.0.0", help="a great app")

    @app.command("init", help="initialize the project")
    @strictcli.flag("force-overwrite", type=bool, default=False, help="overwrite existing files")
    def init(force_overwrite):
        pass

    @app.command(
        "build",
        help="build the project",
        args=[strictcli.Arg(name="target", help="build target")],
    )
    @strictcli.flag("output", short="o", type=str, help="output directory", default="dist")
    def build(target, output):
        pass

    grp = app.group("config", help="manage configuration")

    @grp.command("show", help="show current config")
    def show():
        pass

    @grp.command("set", help="set a config value")
    @strictcli.flag("key", type=str, help="config key")
    def set_(key):
        pass

    return app


def test_app_level_help_shows_commands_and_groups():
    """App-level help shows commands and groups."""
    app = _make_full_app()
    r = app.test([])
    assert r.exit_code == 0
    assert "Commands:" in r.stdout
    assert "init" in r.stdout
    assert "build" in r.stdout
    assert "Groups:" in r.stdout
    assert "config" in r.stdout


def test_app_level_help_skips_empty_sections():
    """App-level help skips empty sections when no commands or groups."""
    app = strictcli.App(name="empty", version="0.0.1", help="empty app")

    @app.command("only", help="the only command")
    def only():
        pass

    r = app.test([])
    assert r.exit_code == 0
    assert "Commands:" in r.stdout
    assert "Groups:" not in r.stdout


def test_group_level_help():
    """Group-level help shows group commands."""
    app = _make_full_app()
    r = app.test(["config", "--help"])
    assert r.exit_code == 0
    assert "config" in r.stdout
    assert "show" in r.stdout
    assert "set" in r.stdout
    assert "manage configuration" in r.stdout


def test_command_level_help_shows_flags():
    """Command-level help shows flags with metadata."""
    app = _make_full_app()
    r = app.test(["build", "--help"])
    assert r.exit_code == 0
    assert "--output" in r.stdout
    assert "-o" in r.stdout
    assert "<str>" in r.stdout
    assert "default: dist" in r.stdout


def test_command_level_help_shows_args():
    """Command-level help shows positional arguments."""
    app = _make_full_app()
    r = app.test(["build", "--help"])
    assert r.exit_code == 0
    assert "Arguments:" in r.stdout
    assert "target" in r.stdout
    assert "build target" in r.stdout


def test_version_output():
    """--version output shows name and version."""
    app = _make_full_app()
    r = app.test(["--version"])
    assert r.exit_code == 0
    assert "myapp 2.0.0" in r.stdout


def test_help_at_app_level_via_empty_argv():
    """--help at app level via app.test([])."""
    app = _make_full_app()
    r = app.test([])
    assert r.exit_code == 0
    assert "myapp v2.0.0" in r.stdout
    assert "a great app" in r.stdout


def test_help_at_command_level():
    """--help at command level via app.test(['cmd', '--help'])."""
    app = _make_full_app()
    r = app.test(["init", "--help"])
    assert r.exit_code == 0
    assert "init" in r.stdout
    assert "initialize the project" in r.stdout
    assert "--force-overwrite" in r.stdout


def test_help_at_group_level():
    """--help at group level via app.test(['grp', '--help'])."""
    app = _make_full_app()
    r = app.test(["config", "--help"])
    assert r.exit_code == 0
    assert "config" in r.stdout
    assert "manage configuration" in r.stdout


def test_help_after_flags():
    """--help recognized after other flags, not just as the sole token."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("verbose", type=bool, default=False, help="enable verbose output")
    def cmd(verbose):
        pass

    r = app.test(["cmd", "--verbose", "--help"])
    assert r.exit_code == 0
    assert "cmd" in r.stdout
    assert "--verbose" in r.stdout


def test_help_not_after_separator():
    """--help after -- is a literal argument, not a help request."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="items", help="items to process", variadic=True)],
    )
    def cmd(items):
        print(",".join(items))

    r = app.test(["cmd", "--", "--help"])
    assert r.exit_code == 0
    assert "--help" in r.stdout  # printed as a literal arg value
    assert "Flags:" not in r.stdout  # not showing help text
