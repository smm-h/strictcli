"""Tests for the flag set system."""

import strictcli


def test_flag_set_with_single_flag():
    """FlagSet with single flag applied to command."""
    verbose_flag_set = strictcli.FlagSet(
        name="verbose",
        flags=[strictcli.Flag(name="verbose", type=bool, help="verbose output")],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", flag_sets=[verbose_flag_set])
    def cmd(verbose):
        print(f"verbose={verbose}")

    r = app.test(["cmd", "--verbose"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


def test_flag_set_with_multiple_flags():
    """FlagSet with multiple flags applied to command."""
    output_flag_set = strictcli.FlagSet(
        name="output",
        flags=[
            strictcli.Flag(name="format", type=str, help="output format", default="text"),
            strictcli.Flag(name="color", type=bool, help="use color"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", flag_sets=[output_flag_set])
    def cmd(format, color):
        print(f"format={format} color={color}")

    r = app.test(["cmd", "--format", "json", "--color"])
    assert r.exit_code == 0
    assert "format=json" in r.stdout
    assert "color=True" in r.stdout


def test_flag_set_flags_in_command_flags():
    """FlagSet flags appear in command's flags list."""
    flag_set = strictcli.FlagSet(
        name="debug",
        flags=[strictcli.Flag(name="debug", type=bool, help="enable debug mode")],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", flag_sets=[flag_set])
    def cmd(debug):
        pass

    assert len(app._commands["cmd"].flags) == 1
    assert app._commands["cmd"].flags[0].name == "debug"


def test_flag_set_flags_in_help():
    """FlagSet flags shown in help output."""
    flag_set = strictcli.FlagSet(
        name="debug",
        flags=[strictcli.Flag(name="debug", type=bool, help="enable debug mode")],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", flag_sets=[flag_set])
    def cmd(debug):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "--debug" in r.stdout
    assert "enable debug mode" in r.stdout


def test_flag_set_flag_values_parsed():
    """FlagSet flag values parsed correctly through the full pipeline."""
    auth_flag_set = strictcli.FlagSet(
        name="auth",
        flags=[
            strictcli.Flag(name="token", type=str, help="auth token", default="none"),
            strictcli.Flag(name="insecure", type=bool, help="skip TLS verification"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("deploy", help="deploy the app", flag_sets=[auth_flag_set])
    def deploy(token, insecure):
        print(f"token={token} insecure={insecure}")

    # Test with all flag set flags provided
    r = app.test(["deploy", "--token", "abc123", "--insecure"])
    assert r.exit_code == 0
    assert "token=abc123" in r.stdout
    assert "insecure=True" in r.stdout

    # Test with defaults
    r = app.test(["deploy"])
    assert r.exit_code == 0
    assert "token=none" in r.stdout
    assert "insecure=False" in r.stdout
