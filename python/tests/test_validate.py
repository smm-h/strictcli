"""Tests for Flag(validate=func) support."""

import strictcli


def _positive_int(value):
    if value <= 0:
        raise ValueError("must be a positive integer")


def _make_app_with_validate(**flag_kwargs):
    """Helper: app with a single command that has one flag with validate."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("port", type=int, help="the port", **flag_kwargs)
    def cmd(ctx, port):
        print(f"port={port}")

    return app


def test_passing_validation():
    """A value that passes validation is accepted."""
    app = _make_app_with_validate(validate=_positive_int)
    r = app.test(["cmd", "--port", "8080"])
    assert r.exit_code == 0
    assert "port=8080" in r.stdout


def test_failing_validation():
    """A value that fails validation is rejected with the ValueError message."""
    app = _make_app_with_validate(validate=_positive_int)
    r = app.test(["cmd", "--port", "-1"])
    assert r.exit_code == 1
    assert "--port" in r.stderr
    assert "must be a positive integer" in r.stderr


def test_validate_runs_on_env_var(monkeypatch):
    """Validation runs on values sourced from env vars."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "port", type=int, help="the port",
        env="MYAPP_PORT", validate=_positive_int,
    )
    def cmd(ctx, port):
        print(f"port={port}")

    monkeypatch.setenv("MYAPP_PORT", "0")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--port" in r.stderr
    assert "must be a positive integer" in r.stderr


def test_validate_runs_on_default():
    """Validation runs on default values."""
    app = _make_app_with_validate(default=-5, validate=_positive_int)
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--port" in r.stderr
    assert "must be a positive integer" in r.stderr


def test_validate_receives_coerced_int():
    """Validator receives the coerced int value, not a string."""
    received = []

    def capture(value):
        received.append(value)

    app = _make_app_with_validate(validate=capture)
    r = app.test(["cmd", "--port", "42"])
    assert r.exit_code == 0
    assert len(received) == 1
    assert received[0] == 42
    assert isinstance(received[0], int)


def test_validate_runs_after_choices():
    """When both choices and validate are set, choices are checked first."""
    call_log = []

    def tracking_validator(value):
        call_log.append(value)

    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "port", type=int, help="the port",
        choices=[80, 443], validate=tracking_validator,
    )
    def cmd(ctx, port):
        print(f"port={port}")

    # Value not in choices -- should fail at choices check, validator never called
    r = app.test(["cmd", "--port", "9090"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr
    assert len(call_log) == 0


def test_validate_none_is_noop():
    """When validate is None (default), behavior is unchanged."""
    app = _make_app_with_validate(validate=None)
    r = app.test(["cmd", "--port", "8080"])
    assert r.exit_code == 0
    assert "port=8080" in r.stdout


def test_validate_with_str_flag():
    """Validate works on str-type flags too."""
    def no_spaces(value):
        if " " in value:
            raise ValueError("must not contain spaces")

    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("name", help="the name", validate=no_spaces)
    def cmd(ctx, name):
        print(f"name={name}")

    r = app.test(["cmd", "--name", "hello world"])
    assert r.exit_code == 1
    assert "--name" in r.stderr
    assert "must not contain spaces" in r.stderr

    r = app.test(["cmd", "--name", "hello"])
    assert r.exit_code == 0
    assert "name=hello" in r.stdout
