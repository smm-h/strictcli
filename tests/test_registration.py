"""Tests for command registration and validation."""

import pytest

import excli


def test_register_command_with_flags_and_args():
    """Register a command successfully with flags and args."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("greet", help="say hello", args=[excli.Arg(name="name", help="who to greet")])
    @excli.flag("loud", type=bool, help="shout it")
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
    app = excli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="missing help text"):

        @app.command("bad", help="")
        def bad():
            pass


def test_missing_help_on_flag():
    """Missing help on flag raises ValueError."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        excli.Flag(name="oops", type=str, help="")


def test_missing_help_on_arg():
    """Missing help on arg raises ValueError."""
    with pytest.raises(ValueError, match="must be a non-empty string"):
        excli.Arg(name="oops", help="")


def test_handler_missing_param():
    """Handler signature mismatch (missing param) raises ValueError."""
    app = excli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="handler missing parameter"):

        @app.command("cmd", help="a command")
        @excli.flag("verbose", type=bool, help="be verbose")
        def cmd():
            pass


def test_handler_extra_param():
    """Handler has extra param raises ValueError."""
    app = excli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="handler has extra parameter"):

        @app.command("cmd", help="a command")
        def cmd(extra):
            pass


def test_duplicate_flag_name():
    """Duplicate flag name raises ValueError."""
    app = excli.App(name="test", version="1.0.0", help="test app")
    with pytest.raises(ValueError, match="duplicate flag name"):

        @app.command("cmd", help="a command")
        @excli.flag("verbose", type=bool, help="be verbose")
        @excli.flag("verbose", type=bool, help="also verbose")
        def cmd(verbose):
            pass


def test_env_prefix_without_prefix():
    """Env var without correct prefix raises ValueError."""
    app = excli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")
    with pytest.raises(ValueError, match="must start with 'MYAPP_'"):

        @app.command("cmd", help="a command")
        @excli.flag("target", type=str, help="target", default="x", env="WRONG_TARGET")
        def cmd(target):
            pass


def test_env_prefix_with_prefixed_false():
    """prefixed=False bypasses env prefix check."""
    app = excli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @excli.flag(
        "target", type=str, help="target", default="x", env="SPECIAL_TARGET", prefixed=False
    )
    def cmd(target):
        pass

    assert app._commands["cmd"].flags[0].env == "SPECIAL_TARGET"


def test_env_prefix_correct():
    """Correct env prefix passes validation."""
    app = excli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @excli.flag("target", type=str, help="target", default="x", env="MYAPP_TARGET")
    def cmd(target):
        pass

    assert app._commands["cmd"].flags[0].env == "MYAPP_TARGET"


def test_tag_merging():
    """Command inherits tag flags."""
    verbose_tag = excli.Tag(
        name="verbose", flags=[excli.Flag(name="verbose", type=bool, help="verbose output")]
    )
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", tags=[verbose_tag])
    def cmd(verbose):
        pass

    assert len(app._commands["cmd"].flags) == 1
    assert app._commands["cmd"].flags[0].name == "verbose"


def test_group_registration():
    """group.command works to register a command in a group."""
    app = excli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="config commands")

    @grp.command("show", help="show config")
    def show():
        pass

    assert "show" in grp.commands
    assert grp.commands["show"].name == "show"


def test_group_env_prefix_propagation():
    """Group commands get validated with app's env_prefix."""
    app = excli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")
    grp = app.group("config", help="config commands")

    with pytest.raises(ValueError, match="must start with 'MYAPP_'"):

        @grp.command("show", help="show config")
        @excli.flag("path", type=str, help="path", default="/etc", env="BAD_PATH")
        def show(path):
            pass
