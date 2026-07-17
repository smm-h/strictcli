"""Tests for command-specific help suggestions in parse error messages."""

import strictcli


def _make_app():
    """Helper: app with a command that has a required flag."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("stream", help="stream data")
    @strictcli.flag("target", type=str, help="the target")
    def stream(ctx, target):
        print(f"target={target}")

    return app


def _make_group_app():
    """Helper: app with a nested group command that has a required flag."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")
    grp = app.group("config", help="manage configuration")

    @grp.command("set", help="set a value")
    @strictcli.flag("key", type=str, help="config key")
    def set_(ctx, key):
        print(f"key={key}")

    return app


def test_missing_required_arg_suggests_subcommand_help():
    """Missing required flag on subcommand suggests 'myapp stream --help'."""
    app = _make_app()
    r = app.test(["stream"])
    assert r.exit_code == 1
    assert "try 'myapp stream --help'" in r.stderr


def test_unknown_flag_suggests_subcommand_help():
    """Unknown flag on subcommand suggests 'myapp stream --help'."""
    app = _make_app()
    r = app.test(["stream", "--bogus"])
    assert r.exit_code == 1
    assert "try 'myapp stream --help'" in r.stderr


def test_unknown_toplevel_command_suggests_app_help():
    """Unknown top-level command suggests 'myapp --help' (no command_prefix)."""
    app = _make_app()
    r = app.test(["nonexistent"])
    assert r.exit_code == 1
    assert "try 'myapp --help'" in r.stderr


def test_nested_group_missing_arg_suggests_full_path():
    """Missing required flag in group command suggests 'myapp config set --help'."""
    app = _make_group_app()
    r = app.test(["config", "set"])
    assert r.exit_code == 1
    assert "try 'myapp config set --help'" in r.stderr
