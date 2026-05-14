"""Tests for environment variable support."""

import strictcli


def _make_env_app(prefixed=True):
    """Helper: app with a str flag backed by an env var."""
    prefix = "MYAPP" if prefixed else None
    env_name = "MYAPP_TARGET" if prefixed else "SPECIAL"
    flag_prefixed = prefixed

    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix=prefix)

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "target",
        type=str,
        help="the target",
        default="fallback",
        env=env_name,
        prefixed=flag_prefixed,
    )
    def cmd(target):
        print(f"target={target}")

    return app, env_name


def test_flag_value_from_env(monkeypatch):
    """Flag value comes from env var when not on CLI."""
    app, env_name = _make_env_app()
    monkeypatch.setenv(env_name, "from-env")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "target=from-env" in r.stdout


def test_cli_overrides_env(monkeypatch):
    """CLI flag overrides env var."""
    app, env_name = _make_env_app()
    monkeypatch.setenv(env_name, "from-env")
    r = app.test(["cmd", "--target", "from-cli"])
    assert r.exit_code == 0
    assert "target=from-cli" in r.stdout


def _make_bool_env_app():
    """Helper: app with a bool flag backed by an env var."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag("verbose", type=bool, help="be verbose", env="MYAPP_VERBOSE")
    def cmd(verbose):
        print(f"verbose={verbose}")

    return app


def test_bool_env_true_values(monkeypatch):
    """Bool env var 'true', '1', 'yes' all resolve to True."""
    for val in ("true", "1", "yes", "True", "YES"):
        app = _make_bool_env_app()
        monkeypatch.setenv("MYAPP_VERBOSE", val)
        r = app.test(["cmd"])
        assert r.exit_code == 0, f"failed for env value {val!r}: {r.stderr}"
        assert "verbose=True" in r.stdout, f"failed for env value {val!r}"


def test_bool_env_false_values(monkeypatch):
    """Bool env var 'false', '0', 'no' all resolve to False."""
    for val in ("false", "0", "no", "False", "NO"):
        app = _make_bool_env_app()
        monkeypatch.setenv("MYAPP_VERBOSE", val)
        r = app.test(["cmd"])
        assert r.exit_code == 0, f"failed for env value {val!r}: {r.stderr}"
        assert "verbose=False" in r.stdout, f"failed for env value {val!r}"


def test_bool_env_invalid(monkeypatch):
    """Invalid bool env var raises error."""
    app = _make_bool_env_app()
    monkeypatch.setenv("MYAPP_VERBOSE", "maybe")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "invalid boolean value" in r.stderr


def test_env_var_prefixed_false(monkeypatch):
    """Env var with prefixed=False works without prefix validation."""
    app, env_name = _make_env_app(prefixed=False)
    assert env_name == "SPECIAL"
    monkeypatch.setenv("SPECIAL", "works")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "target=works" in r.stdout
