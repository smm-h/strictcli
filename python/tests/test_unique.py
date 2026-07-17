"""Tests for Flag(unique=True) enforcement, help text, and schema."""

import strictcli


def _make_app_with_unique_flag(**flag_kwargs):
    """Helper: app with a single command that has one unique repeatable flag."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("tag", help="a tag", repeatable=True, unique=True, **flag_kwargs)
    def cmd(ctx, tag):
        print(f"tag={tag!r}")

    return app


def test_unique_duplicate_error():
    """--tag a --tag a on unique flag produces error."""
    app = _make_app_with_unique_flag()
    r = app.test(["cmd", "--tag", "a", "--tag", "a"])
    assert r.exit_code == 1
    assert "--tag: duplicate value 'a'" in r.stderr


def test_unique_distinct_values():
    """--tag a --tag b on unique flag succeeds."""
    app = _make_app_with_unique_flag()
    r = app.test(["cmd", "--tag", "a", "--tag", "b"])
    assert r.exit_code == 0
    assert "tag=['a', 'b']" in r.stdout


def test_unique_int_dedup():
    """--count 1 --count 1 on unique int flag produces error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("count", type=int, help="a count", repeatable=True, unique=True)
    def cmd(ctx, count):
        print(f"count={count!r}")

    r = app.test(["cmd", "--count", "1", "--count", "1"])
    assert r.exit_code == 1
    assert "--count: duplicate value '1'" in r.stderr


def test_unique_global_flag_duplicate():
    """Unique enforcement on global repeatable flags."""
    app = strictcli.App(
        name="test",
        version="1.0.0",
        help="test app",
        flags=[
            strictcli.Flag(
                name="tag", type=str, help="a tag", repeatable=True, unique=True,
            ),
        ],
    )

    @app.command("cmd", help="a command")
    def cmd(ctx, tag):
        print(f"tag={tag!r}")

    r = app.test(["--tag", "a", "--tag", "a", "cmd"])
    assert r.exit_code == 1
    assert "--tag: duplicate value 'a'" in r.stderr


def test_unique_help_text():
    """Help output contains [unique] after [repeatable]."""
    app = _make_app_with_unique_flag()
    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    stdout = r.stdout
    # [repeatable] must come before [unique]
    rep_idx = stdout.index("[repeatable]")
    uniq_idx = stdout.index("[unique]")
    assert rep_idx < uniq_idx


def test_unique_false_not_in_help():
    """unique=False does not show [unique] in help."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("tag", help="a tag", repeatable=True, unique=False)
    def cmd(ctx, tag):
        print(f"tag={tag!r}")

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "[unique]" not in r.stdout
    assert "[repeatable]" in r.stdout


def test_unique_duplicate_with_equals_syntax():
    """--tag=a --tag=a on unique flag produces error."""
    app = _make_app_with_unique_flag()
    r = app.test(["cmd", "--tag=a", "--tag=a"])
    assert r.exit_code == 1
    assert "--tag: duplicate value 'a'" in r.stderr


def test_unique_float_dedup():
    """Duplicate float values on unique flag produce error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("val", type=float, help="a value", repeatable=True, unique=True)
    def cmd(ctx, val):
        print(f"val={val!r}")

    r = app.test(["cmd", "--val", "1.5", "--val", "1.5"])
    assert r.exit_code == 1
    assert "--val: duplicate value '1.5'" in r.stderr
