"""Tests for Flag(repeatable=True) support."""

import pytest

import strictcli


def _make_app_with_repeatable(**flag_kwargs):
    """Helper: app with a single command that has one repeatable flag."""
    flag_kwargs.setdefault("unique", False)
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("record", help="a record", repeatable=True, **flag_kwargs)
    def cmd(record):
        print(f"record={record!r}")

    return app


def test_single_occurrence():
    """A single occurrence produces a list with one element."""
    app = _make_app_with_repeatable()
    r = app.test(["cmd", "--record", "alpha"])
    assert r.exit_code == 0
    assert "record=['alpha']" in r.stdout


def test_multiple_occurrences():
    """Multiple occurrences produce a list with all elements in order."""
    app = _make_app_with_repeatable()
    r = app.test(["cmd", "--record", "alpha", "--record", "beta", "--record", "gamma"])
    assert r.exit_code == 0
    assert "record=['alpha', 'beta', 'gamma']" in r.stdout


def test_zero_occurrences():
    """No occurrences produce an empty list (the default)."""
    app = _make_app_with_repeatable()
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "record=[]" in r.stdout


def test_repeatable_with_type_int():
    """Repeatable with type=int coerces each value to int."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("port", type=int, help="a port", repeatable=True, unique=False)
    def cmd(port):
        print(f"port={port!r}")

    r = app.test(["cmd", "--port", "80", "--port", "443"])
    assert r.exit_code == 0
    assert "port=[80, 443]" in r.stdout


def test_repeatable_with_choices_valid():
    """Repeatable with choices: each valid value is accepted."""
    app = _make_app_with_repeatable(choices=["alpha", "beta", "gamma"])
    r = app.test(["cmd", "--record", "alpha", "--record", "gamma"])
    assert r.exit_code == 0
    assert "record=['alpha', 'gamma']" in r.stdout


def test_repeatable_with_choices_invalid():
    """Repeatable with choices: an invalid value in any occurrence is rejected."""
    app = _make_app_with_repeatable(choices=["alpha", "beta", "gamma"])
    r = app.test(["cmd", "--record", "alpha", "--record", "delta"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr
    assert "'delta'" in r.stderr
    assert "alpha" in r.stderr


def test_repeatable_bad_int_value():
    """Repeatable with type=int: a non-integer value produces an error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("port", type=int, help="a port", repeatable=True, unique=False)
    def cmd(port):
        print(f"port={port!r}")

    r = app.test(["cmd", "--port", "80", "--port", "abc"])
    assert r.exit_code == 1
    assert "expected integer" in r.stderr
    assert "'abc'" in r.stderr


def test_repeatable_with_bool_raises():
    """repeatable=True with type=bool raises ValueError at registration."""
    with pytest.raises(ValueError, match="repeatable is incompatible with type=bool"):
        strictcli.Flag(
            name="verbose", type=bool, help="be verbose", repeatable=True,
        )


def test_unique_requires_repeatable():
    """unique=True on a non-repeatable flag raises ValueError."""
    with pytest.raises(ValueError, match='unique requires repeatable=True'):
        strictcli.Flag(
            name="tag", type=str, help="a tag", unique=True,
        )


def test_unique_false_requires_repeatable():
    """unique=False on a non-repeatable flag raises ValueError."""
    with pytest.raises(ValueError, match='unique requires repeatable=True'):
        strictcli.Flag(
            name="tag", type=str, help="a tag", unique=False,
        )


def test_repeatable_requires_explicit_unique():
    """repeatable=True without unique raises ValueError."""
    with pytest.raises(
        ValueError,
        match='repeatable requires explicit unique',
    ):
        strictcli.Flag(
            name="tag", type=str, help="a tag", repeatable=True,
        )


def test_repeatable_shown_in_help():
    """Repeatable is shown in help output."""
    app = _make_app_with_repeatable()
    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "repeatable" in r.stdout


def test_repeatable_with_env_var(monkeypatch):
    """An env var value for a repeatable flag becomes a single-element list."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "record", help="a record", repeatable=True, unique=False,
        env="MYAPP_RECORD", env_separator=",",
    )
    def cmd(record):
        print(f"record={record!r}")

    monkeypatch.setenv("MYAPP_RECORD", "fromenv")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "record=['fromenv']" in r.stdout


def test_repeatable_with_equals_syntax():
    """Repeatable with --flag=value syntax."""
    app = _make_app_with_repeatable()
    r = app.test(["cmd", "--record=alpha", "--record=beta"])
    assert r.exit_code == 0
    assert "record=['alpha', 'beta']" in r.stdout


def test_repeatable_with_short_flag():
    """Repeatable with short flag syntax."""
    app = _make_app_with_repeatable(short="r")
    r = app.test(["cmd", "-r", "alpha", "-r", "beta"])
    assert r.exit_code == 0
    assert "record=['alpha', 'beta']" in r.stdout


def test_repeatable_with_validate():
    """Repeatable with validate: each element is validated individually."""
    def no_spaces(value):
        if " " in value:
            raise ValueError("must not contain spaces")

    app = _make_app_with_repeatable(validate=no_spaces)
    r = app.test(["cmd", "--record", "good", "--record", "has space"])
    assert r.exit_code == 1
    assert "--record" in r.stderr
    assert "must not contain spaces" in r.stderr


def test_repeatable_validate_all_pass():
    """Repeatable with validate: all valid elements pass."""
    def no_spaces(value):
        if " " in value:
            raise ValueError("must not contain spaces")

    app = _make_app_with_repeatable(validate=no_spaces)
    r = app.test(["cmd", "--record", "alpha", "--record", "beta"])
    assert r.exit_code == 0
    assert "record=['alpha', 'beta']" in r.stdout


def test_repeatable_env_var_with_type_int(monkeypatch):
    """An env var for a repeatable int flag produces a single-element int list."""
    app = strictcli.App(name="test", version="1.0.0", help="test app", env_prefix="MYAPP")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "port", type=int, help="a port", repeatable=True, unique=False,
        env="MYAPP_PORT", env_separator=",",
    )
    def cmd(port):
        print(f"port={port!r}")

    monkeypatch.setenv("MYAPP_PORT", "8080")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "port=[8080]" in r.stdout


def test_env_separator_requires_repeatable():
    """env_separator on a non-repeatable flag raises ValueError."""
    with pytest.raises(ValueError, match='env_separator requires repeatable=True'):
        strictcli.Flag(
            name="tag", type=str, help="a tag",
            env="MYAPP_TAG", env_separator=",",
        )


def test_env_separator_requires_env():
    """env_separator without env raises ValueError."""
    with pytest.raises(ValueError, match='env_separator requires env'):
        strictcli.Flag(
            name="tag", type=str, help="a tag",
            repeatable=True, unique=False, env_separator=",",
        )


def test_repeatable_env_requires_separator():
    """repeatable flag with env but no env_separator raises ValueError."""
    with pytest.raises(
        ValueError,
        match='repeatable flag with env requires env_separator',
    ):
        strictcli.Flag(
            name="tag", type=str, help="a tag",
            repeatable=True, unique=False, env="MYAPP_TAG",
        )


def test_env_separator_must_be_single_char():
    """env_separator must be exactly one character."""
    with pytest.raises(ValueError, match='env_separator must be a single character'):
        strictcli.Flag(
            name="tag", type=str, help="a tag",
            repeatable=True, unique=False, env="MYAPP_TAG", env_separator="::",
        )


def test_env_separator_cannot_be_backslash():
    """env_separator cannot be a backslash."""
    with pytest.raises(ValueError, match='env_separator cannot be a backslash'):
        strictcli.Flag(
            name="tag", type=str, help="a tag",
            repeatable=True, unique=False, env="MYAPP_TAG", env_separator="\\",
        )
