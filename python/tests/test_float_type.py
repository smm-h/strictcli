"""Tests for type=float flag support."""

import pytest

import strictcli


def _make_app_with_float_flag(**flag_kwargs):
    """Helper: app with a single command that has one float flag."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", **flag_kwargs)
    def cmd(rate):
        print(f"rate={rate}")

    return app


def test_float_flag_parses():
    """Float flag with --rate 3.14 -> handler receives 3.14 as float."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "3.14"])
    assert r.exit_code == 0
    assert "rate=3.14" in r.stdout


def test_float_flag_value_is_float():
    """Float flag value is actually a float, not a string."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate")
    def cmd(rate):
        print(f"type={type(rate).__name__}")

    r = app.test(["cmd", "--rate", "3.14"])
    assert r.exit_code == 0
    assert "type=float" in r.stdout


def test_float_flag_with_default():
    """Float flag omitted uses default value."""
    app = _make_app_with_float_flag(default=1.5)
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "rate=1.5" in r.stdout


def test_float_flag_int_default():
    """Float flag accepts an int default (auto-coerced by Python)."""
    app = _make_app_with_float_flag(default=2)
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "rate=2" in r.stdout


def test_float_flag_from_env(monkeypatch):
    """Float flag value from env var is coerced to float."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", default=1.0, env="MYAPP_RATE")
    def cmd(rate):
        print(f"rate={rate} type={type(rate).__name__}")

    monkeypatch.setenv("MYAPP_RATE", "9.81")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "rate=9.81" in r.stdout
    assert "type=float" in r.stdout


def test_float_flag_bad_value():
    """Non-numeric value for float flag -> exit 1, stderr says expected float."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "abc"])
    assert r.exit_code == 1
    assert "expected float" in r.stderr
    assert "'abc'" in r.stderr


def test_float_flag_bad_env_value(monkeypatch):
    """Non-numeric env var for float flag -> exit 1, stderr says expected float."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", default=1.0, env="MYAPP_RATE")
    def cmd(rate):
        print(f"rate={rate}")

    monkeypatch.setenv("MYAPP_RATE", "abc")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "expected float" in r.stderr
    assert "'abc'" in r.stderr


def test_float_flag_required():
    """Float flag with no default and omitted -> exit 1, stderr says required."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "required" in r.stderr


def test_float_flag_equals_syntax():
    """Float flag with --rate=3.14 -> receives 3.14."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate=3.14"])
    assert r.exit_code == 0
    assert "rate=3.14" in r.stdout


def test_float_flag_negative_value():
    """Float flag with negative value --rate -2.5 -> receives -2.5."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate")
    def cmd(rate):
        print(f"rate={rate}")

    r = app.test(["cmd", "--rate", "-2.5"])
    assert r.exit_code == 0
    assert "rate=-2.5" in r.stdout


def test_float_flag_reject_nan():
    """NaN is rejected as a float value."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "nan"])
    assert r.exit_code == 1
    assert "NaN is not allowed" in r.stderr


def test_float_flag_reject_nan_case_insensitive():
    """NaN rejection is case-insensitive."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "NaN"])
    assert r.exit_code == 1
    assert "NaN is not allowed" in r.stderr


def test_float_flag_reject_inf():
    """Inf is rejected as a float value."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "inf"])
    assert r.exit_code == 1
    assert "Inf is not allowed" in r.stderr


def test_float_flag_reject_negative_inf():
    """-inf is rejected as a float value."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "-inf"])
    assert r.exit_code == 1
    assert "Inf is not allowed" in r.stderr


def test_float_flag_reject_whitespace():
    """Whitespace-padded values are rejected."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", " 3.14"])
    assert r.exit_code == 1
    assert "expected float" in r.stderr


def test_float_flag_reject_trailing_whitespace():
    """Trailing whitespace is rejected."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "3.14 "])
    assert r.exit_code == 1
    assert "expected float" in r.stderr


def test_float_flag_help_shows_float():
    """Float flag is shown as <float> in help output."""
    app = _make_app_with_float_flag(default=1.0)
    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "<float>" in r.stdout


def test_float_default_must_be_numeric():
    """Flag(type=float, default="3.14") raises ValueError at registration."""
    with pytest.raises(ValueError, match="float default"):
        strictcli.Flag(name="rate", type=float, help="the rate", default="3.14")


def test_float_flag_short_form():
    """Float flag via short flag -r 3.14 works."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", short="r", type=float, help="the rate")
    def cmd(rate):
        print(f"rate={rate}")

    r = app.test(["cmd", "-r", "3.14"])
    assert r.exit_code == 0
    assert "rate=3.14" in r.stdout


def test_float_flag_bad_value_equals_syntax():
    """Non-numeric value via equals syntax -> error."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate=abc"])
    assert r.exit_code == 1
    assert "expected float" in r.stderr


def test_float_flag_choices():
    """Float flag with choices validates correctly."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", choices=[0.5, 1.0, 2.0])
    def cmd(rate):
        print(f"rate={rate}")

    # Valid choice
    r = app.test(["cmd", "--rate", "1.0"])
    assert r.exit_code == 0
    assert "rate=1.0" in r.stdout

    # Invalid choice
    r = app.test(["cmd", "--rate", "3.0"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr


def test_float_flag_repeatable():
    """Float repeatable flag collects multiple values."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("weight", type=float, help="a weight", repeatable=True)
    def cmd(weight):
        print(f"weight={weight}")

    r = app.test(["cmd", "--weight", "1.5", "--weight", "2.5"])
    assert r.exit_code == 0
    assert "weight=[1.5, 2.5]" in r.stdout


def test_float_flag_integer_input():
    """Float flag accepts integer string input (e.g. '42' -> 42.0)."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "42"])
    assert r.exit_code == 0
    assert "rate=42.0" in r.stdout


def test_float_flag_scientific_notation():
    """Float flag accepts scientific notation (e.g. '1e-3')."""
    app = _make_app_with_float_flag()
    r = app.test(["cmd", "--rate", "1e-3"])
    assert r.exit_code == 0
    assert "rate=0.001" in r.stdout


def test_float_flag_nan_from_env_includes_env_suffix(monkeypatch):
    """NaN from env var includes '(from env var ...)' suffix in error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", default=1.0, env="MYAPP_RATE")
    def cmd(rate):
        print(f"rate={rate}")

    monkeypatch.setenv("MYAPP_RATE", "nan")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "NaN is not allowed" in r.stderr
    assert "(from env var 'MYAPP_RATE')" in r.stderr


def test_float_flag_inf_from_env_includes_env_suffix(monkeypatch):
    """Inf from env var includes '(from env var ...)' suffix in error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", default=1.0, env="MYAPP_RATE")
    def cmd(rate):
        print(f"rate={rate}")

    monkeypatch.setenv("MYAPP_RATE", "inf")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "Inf is not allowed" in r.stderr
    assert "(from env var 'MYAPP_RATE')" in r.stderr
