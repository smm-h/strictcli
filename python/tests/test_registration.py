"""Tests for command registration and validation."""

import pytest

import strictcli


def test_register_command_with_flags_and_args():
    """Register a command successfully with flags and args."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("greet", help="say hello", args=[strictcli.Arg(name="name", help="who to greet")])
    @strictcli.flag("loud", type=bool, default=False, help="shout it")
    def greet(name, loud):
        pass

    assert "greet" in app._commands
    cmd = app._commands["greet"]
    assert cmd.name == "greet"
    assert len(cmd.flags) == 1
    assert cmd.flags[0].name == "loud"
    assert len(cmd.args) == 1
    assert cmd.args[0].name == "name"


def test_missing_help_on_command():
    """Missing help on command raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="missing help text"):

        @app.command("bad", help="")
        def bad():
            pass


def test_missing_help_on_flag():
    """Missing help on flag raises ValueError."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        strictcli.Flag(name="oops", type=str, help="")


def test_missing_help_on_arg():
    """Missing help on arg raises ValueError."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        strictcli.Arg(name="oops", help="")


def test_handler_missing_param():
    """Handler signature mismatch (missing param) raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="handler missing parameter"):

        @app.command("cmd", help="a command")
        @strictcli.flag("verbose", type=bool, default=False, help="be verbose")
        def cmd():
            pass


def test_handler_extra_param():
    """Handler has extra param raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="handler has extra parameter"):

        @app.command("cmd", help="a command")
        def cmd(extra):
            pass


def test_duplicate_flag_name():
    """Duplicate flag name raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="duplicate flag name"):

        @app.command("cmd", help="a command")
        @strictcli.flag("verbose", type=bool, default=False, help="be verbose")
        @strictcli.flag("verbose", type=bool, default=False, help="also verbose")
        def cmd(verbose):
            pass


def test_env_prefix_without_prefix():
    """Env var without correct prefix raises ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")
    with pytest.raises(ValueError, match='must start with "MYAPP_'):

        @app.command("cmd", help="a command")
        @strictcli.flag("target", type=str, help="target", default="x", env="WRONG_TARGET")
        def cmd(target):
            pass


def test_env_prefix_with_prefixed_false():
    """prefixed=False bypasses env prefix check."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "target", type=str, help="target", default="x", env="SPECIAL_TARGET", prefixed=False
    )
    def cmd(target):
        pass

    assert app._commands["cmd"].flags[0].env == "SPECIAL_TARGET"


def test_env_prefix_correct():
    """Correct env prefix passes validation."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag("target", type=str, help="target", default="x", env="MYAPP_TARGET")
    def cmd(target):
        pass

    assert app._commands["cmd"].flags[0].env == "MYAPP_TARGET"


def test_flag_set_merging():
    """Command inherits flag set flags."""
    verbose_flag_set = strictcli.FlagSet(
        name="verbose", flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")]
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", flag_sets=[verbose_flag_set])
    def cmd(verbose):
        pass

    assert len(app._commands["cmd"].flags) == 1
    assert app._commands["cmd"].flags[0].name == "verbose"


def test_group_registration():
    """group.command works to register a command in a group."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")

    @grp.command("show", help="show config")
    def show():
        pass

    assert "show" in grp.commands
    assert grp.commands["show"].name == "show"


def test_group_env_prefix_propagation():
    """Group commands get validated with app's env_prefix."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")
    grp = app.group("config", help="config commands")

    with pytest.raises(ValueError, match='must start with "MYAPP_'):

        @grp.command("show", help="show config")
        @strictcli.flag("path", type=str, help="path", default="/etc", env="BAD_PATH")
        def show(path):
            pass
