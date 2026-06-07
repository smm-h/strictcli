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


def test_env_separator_shown_in_help():
    """Help text shows [env: MY_TAGS (sep: ,)] for repeatable flag with env_separator."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tags", help="tags to apply", repeatable=True, unique=False,
        env="MY_TAGS", env_separator=",",
    )
    def cmd(tags):
        print(f"tags={tags!r}")

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "[env: MY_TAGS (sep: ,)]" in r.stdout


# --- Env separator parsing tests ---


def test_env_separator_splits_value(monkeypatch):
    """TAGS=a,b,c with env_separator=',' produces ['a', 'b', 'c']."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=False,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "a,b,c")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "tag=['a', 'b', 'c']" in r.stdout


def test_env_separator_escaped_separator(monkeypatch):
    r"""TAGS=a\,b,c produces ['a,b', 'c'] (escaped separator)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=False,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "a\\,b,c")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "tag=['a,b', 'c']" in r.stdout


def test_env_separator_single_value(monkeypatch):
    """TAGS=a with env_separator=',' produces ['a'] (no separator in value)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=False,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "a")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "tag=['a']" in r.stdout


def test_env_separator_int_coercion(monkeypatch):
    """COUNTS=1,2,3 with int type and env_separator=',' produces [1, 2, 3]."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "count", type=int, help="a count", repeatable=True, unique=False,
        env="COUNTS", env_separator=",",
    )
    def cmd(count):
        print(f"count={count!r}")

    monkeypatch.setenv("COUNTS", "1,2,3")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "count=[1, 2, 3]" in r.stdout


def test_env_separator_int_coercion_error(monkeypatch):
    """COUNTS=1,abc,3 with int type produces per-element coercion error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "count", type=int, help="a count", repeatable=True, unique=False,
        env="COUNTS", env_separator=",",
    )
    def cmd(count):
        print(f"count={count!r}")

    monkeypatch.setenv("COUNTS", "1,abc,3")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--count: expected integer, got 'abc' (from env var 'COUNTS')" in r.stderr


def test_env_separator_unique_duplicate_error(monkeypatch):
    """TAGS=a,b,a with unique=True produces duplicate error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=True,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "a,b,a")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--tag: duplicate value 'a' (from env var 'TAGS')" in r.stderr


def test_env_separator_unique_no_duplicate(monkeypatch):
    """TAGS=a,b,c with unique=True succeeds when all values are distinct."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=True,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "a,b,c")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "tag=['a', 'b', 'c']" in r.stdout


def test_env_separator_cli_overrides_env(monkeypatch):
    """CLI value completely replaces env (first source wins, no merging)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=False,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "x,y,z")
    r = app.test(["cmd", "--tag", "from-cli"])
    assert r.exit_code == 0
    assert "tag=['from-cli']" in r.stdout


def test_env_separator_colon_separator(monkeypatch):
    """Test with env_separator=':' to verify it's not hardcoded to comma."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "path", help="a path", repeatable=True, unique=False,
        env="PATHS", env_separator=":",
    )
    def cmd(path):
        print(f"path={path!r}")

    monkeypatch.setenv("PATHS", "/usr/bin:/usr/local/bin:/home/user/bin")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "path=['/usr/bin', '/usr/local/bin', '/home/user/bin']" in r.stdout


def test_env_separator_at_prefix_per_element(monkeypatch, tmp_path):
    """String flag: TAGS=@file.txt,b resolves @file.txt per-element."""
    content_file = tmp_path / "file.txt"
    content_file.write_text("from-file")

    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "tag", help="a tag", repeatable=True, unique=False,
        env="TAGS", env_separator=",",
    )
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", f"@{content_file},b")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "tag=['from-file', 'b']" in r.stdout


def test_env_separator_global_flag(monkeypatch):
    """Env separator on global repeatable flag splits correctly."""
    app = strictcli.App(
        name="test", version="1.0.0", help="test app",
        flags=[
            strictcli.Flag(
                name="tag", type=str, help="a tag", repeatable=True,
                unique=False, env="TAGS", env_separator=",",
            ),
        ],
    )

    @app.command("cmd", help="a command")
    def cmd(tag):
        print(f"tag={tag!r}")

    monkeypatch.setenv("TAGS", "a,b,c")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "tag=['a', 'b', 'c']" in r.stdout


def test_env_separator_float_coercion(monkeypatch):
    """RATES=1.5,2.5,3.5 with float type and env_separator=',' produces [1.5, 2.5, 3.5]."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "rate", type=float, help="a rate", repeatable=True, unique=False,
        env="RATES", env_separator=",",
    )
    def cmd(rate):
        print(f"rate={rate!r}")

    monkeypatch.setenv("RATES", "1.5,2.5,3.5")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "rate=[1.5, 2.5, 3.5]" in r.stdout


def test_env_separator_float_coercion_error(monkeypatch):
    """RATES=1.5,abc with float type produces per-element coercion error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "rate", type=float, help="a rate", repeatable=True, unique=False,
        env="RATES", env_separator=",",
    )
    def cmd(rate):
        print(f"rate={rate!r}")

    monkeypatch.setenv("RATES", "1.5,abc")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--rate: expected float, got 'abc' (from env var 'RATES')" in r.stderr


def test_env_separator_float_nan_error(monkeypatch):
    """RATES=1.5,NaN with float type produces NaN error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag(
        "rate", type=float, help="a rate", repeatable=True, unique=False,
        env="RATES", env_separator=",",
    )
    def cmd(rate):
        print(f"rate={rate!r}")

    monkeypatch.setenv("RATES", "1.5,NaN")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--rate: NaN is not allowed (from env var 'RATES')" in r.stderr


# --- Repeatable flag default validation ---


def test_repeatable_default_must_be_list():
    """Repeatable flag with non-list default raises ValueError."""
    with pytest.raises(ValueError, match='Flag "record": repeatable flag default must be a list'):
        _make_app_with_repeatable(type=str, default="not a list")


def test_repeatable_default_empty_list_error():
    """Repeatable flag with explicit default=[] raises ValueError."""
    with pytest.raises(
        ValueError,
        match='Flag "record": explicit empty default is redundant for repeatable flags, omit the default',
    ):
        _make_app_with_repeatable(type=str, default=[])


def test_repeatable_default_wrong_element_type_str():
    """Repeatable str flag with default=[1] raises ValueError at element 0."""
    with pytest.raises(ValueError, match='Flag "record": default element 0 is not of type str'):
        _make_app_with_repeatable(type=str, default=[1])


def test_repeatable_default_wrong_element_type_int():
    """Repeatable int flag with default=["x"] raises ValueError."""
    with pytest.raises(ValueError, match='Flag "record": default element 0 is not of type int'):
        _make_app_with_repeatable(type=int, default=["x"])


def test_repeatable_default_int_coerced_to_float():
    """Repeatable float flag with default=[1, 2] coerces to [1.0, 2.0]."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("val", type=float, help="a value", repeatable=True, unique=False,
                    default=[1, 2])
    def cmd(val):
        print(f"val={val!r}")

    # The flag object should have coerced defaults
    flag_obj = app._commands["cmd"].flags[0]
    assert flag_obj.default == [1.0, 2.0]
    assert all(isinstance(x, float) for x in flag_obj.default)


def test_repeatable_default_valid():
    """Repeatable flag with valid non-empty default succeeds."""
    app = _make_app_with_repeatable(type=str, default=["a", "b"])
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "record=['a', 'b']" in r.stdout
