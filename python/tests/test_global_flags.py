"""Tests for app-level global flags."""

import pytest

import strictcli


def _make_app_with_global_verbose():
    """Helper: app with a global --verbose flag and a simple command."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="enable verbose output")],
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="build target", default="all")
    def run(target, verbose):
        if verbose:
            print(f"verbose: running {target}")
        else:
            print(f"running {target}")

    return app


def test_global_bool_flag_before_command():
    """Global bool flag before the command name is parsed."""
    app = _make_app_with_global_verbose()
    r = app.test(["--verbose", "run"])
    assert r.exit_code == 0
    assert "verbose: running all" in r.stdout


def test_global_bool_flag_not_provided():
    """Global bool flag defaults to False when not provided."""
    app = _make_app_with_global_verbose()
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "running all" in r.stdout
    assert "verbose" not in r.stdout


def test_global_str_flag_with_value():
    """Global str flag with a value is parsed correctly."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="settings", type=str, help="settings file path", default="default.toml")],
    )

    @app.command("run", help="run something")
    def run(settings):
        print(f"settings={settings}")

    r = app.test(["--settings", "custom.toml", "run"])
    assert r.exit_code == 0
    assert "settings=custom.toml" in r.stdout


def test_global_int_flag_with_value():
    """Global int flag with a value is parsed correctly."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="jobs", type=int, help="parallel jobs", default=1)],
    )

    @app.command("build", help="build something")
    def build(jobs):
        print(f"jobs={jobs}")

    r = app.test(["--jobs", "4", "build"])
    assert r.exit_code == 0
    assert "jobs=4" in r.stdout


def test_global_flag_default():
    """Global flag uses default when not provided on CLI."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="settings", type=str, help="settings path", default="app.toml")],
    )

    @app.command("run", help="run")
    def run(settings):
        print(f"settings={settings}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "settings=app.toml" in r.stdout


def test_global_flag_from_env(monkeypatch):
    """Global flag resolved from environment variable."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="token", type=str, help="auth token", env="MYAPP_TOKEN", default="")],
    )

    @app.command("run", help="run")
    def run(token):
        print(f"token={token}")

    monkeypatch.setenv("MYAPP_TOKEN", "secret123")
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "token=secret123" in r.stdout


def test_global_flag_cli_overrides_env(monkeypatch):
    """CLI value for global flag takes precedence over env var."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="token", type=str, help="auth token", env="MYAPP_TOKEN", default="")],
    )

    @app.command("run", help="run")
    def run(token):
        print(f"token={token}")

    monkeypatch.setenv("MYAPP_TOKEN", "from-env")
    r = app.test(["--token", "from-cli", "run"])
    assert r.exit_code == 0
    assert "token=from-cli" in r.stdout


def test_global_flag_appears_in_command_help():
    """Global flags appear in the help output for every command."""
    app = _make_app_with_global_verbose()
    r = app.test(["run", "--help"])
    assert r.exit_code == 0
    assert "Global flags:" in r.stdout
    assert "--verbose" in r.stdout


def test_global_and_command_flags_together():
    """Global flags and command flags work together."""
    app = _make_app_with_global_verbose()
    r = app.test(["--verbose", "run", "--target", "web"])
    assert r.exit_code == 0
    assert "verbose: running web" in r.stdout


def test_collision_between_global_and_command_flag():
    """Collision between global and command flag raises ValueError at registration."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")],
    )

    with pytest.raises(ValueError, match="collides with a global flag"):

        @app.command("run", help="run something")
        @strictcli.flag("verbose", type=bool, default=False, help="also verbose")
        def run(verbose):
            pass


def test_global_flag_with_double_dash_separator():
    """-- stops global flag parsing; remaining tokens go to command."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")],
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="build target", default="all")
    def run(target, verbose):
        print(f"verbose={verbose} target={target}")

    # -- stops global flag parsing, so --verbose is not consumed as global
    # The command parser sees: -- run --target web
    # But "-- run" means run is a positional, not a command name... actually
    # the remaining tokens include -- so command routing sees "--" first.
    # Let's test: --verbose before --, then command after --
    r = app.test(["--verbose", "--", "run", "--target", "web"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout
    assert "target=web" in r.stdout


def test_global_flag_negation():
    """--no-verbose negation works for global bool flags."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, help="verbose output", default=True)],
    )

    @app.command("run", help="run something")
    def run(verbose):
        print(f"verbose={verbose}")

    r = app.test(["--no-verbose", "run"])
    assert r.exit_code == 0
    assert "verbose=False" in r.stdout


def test_global_flag_short_form():
    """Global flag with short form works."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", short="V", type=bool, default=False, help="verbose output")],
    )

    @app.command("run", help="run something")
    def run(verbose):
        print(f"verbose={verbose}")

    r = app.test(["-V", "run"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


def test_global_flag_with_group():
    """Global flags work with group commands."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")],
    )

    grp = app.group("config", help="manage config")

    @grp.command("show", help="show config")
    def show(verbose):
        print(f"verbose={verbose}")

    r = app.test(["--verbose", "config", "show"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


def test_global_flag_with_group_and_command_flags():
    """Global flags + group command flags work together."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")],
    )

    grp = app.group("config", help="manage config")

    @grp.command("set", help="set a value")
    @strictcli.flag("key", type=str, help="config key")
    @strictcli.flag("value", type=str, help="config value")
    def set_(key, value, verbose):
        if verbose:
            print(f"verbose: setting {key}={value}")
        else:
            print(f"setting {key}={value}")

    r = app.test(["--verbose", "config", "set", "--key", "name", "--value", "test"])
    assert r.exit_code == 0
    assert "verbose: setting name=test" in r.stdout


def test_global_flag_collision_in_group():
    """Collision between global and group command flag raises ValueError."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")],
    )

    grp = app.group("config", help="manage config")

    with pytest.raises(ValueError, match="collides with a global flag"):

        @grp.command("show", help="show config")
        @strictcli.flag("verbose", type=bool, default=False, help="also verbose")
        def show(verbose):
            pass


def test_global_flag_equals_form():
    """Global str flag with --flag=value syntax."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[strictcli.Flag(name="settings", type=str, help="settings path", default="default.toml")],
    )

    @app.command("run", help="run")
    def run(settings):
        print(f"settings={settings}")

    r = app.test(["--settings=custom.toml", "run"])
    assert r.exit_code == 0
    assert "settings=custom.toml" in r.stdout


def test_multiple_global_flags():
    """Multiple global flags parsed together."""
    app = strictcli.App(
        name="myapp",
        version="1.0.0",
        help="test app",
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="settings", type=str, help="settings path", default="default.toml"),
        ],
    )

    @app.command("run", help="run")
    def run(verbose, settings):
        print(f"verbose={verbose} settings={settings}")

    r = app.test(["--verbose", "--settings", "custom.toml", "run"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout
    assert "settings=custom.toml" in r.stdout


def test_no_global_flags_works():
    """App without global flags works as before."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", help="run something")
    def run():
        print("running")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "running" in r.stdout
