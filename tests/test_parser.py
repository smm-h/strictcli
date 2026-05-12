"""Tests for argument parsing."""

import excli


def _make_app_with_str_flag(**flag_kwargs):
    """Helper: app with a single command that has one str flag."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @excli.flag("target", type=str, help="the target", **flag_kwargs)
    def cmd(target):
        print(f"target={target}")

    return app


def _make_app_with_bool_flag():
    """Helper: app with a single command that has one bool flag."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @excli.flag("verbose", type=bool, help="be verbose")
    def cmd(verbose):
        print(f"verbose={verbose}")

    return app


def test_str_flag_space():
    """Str flag with --flag value (space-separated)."""
    app = _make_app_with_str_flag()
    r = app.test(["cmd", "--target", "foo"])
    assert r.exit_code == 0
    assert "target=foo" in r.stdout


def test_str_flag_equals():
    """Str flag with --flag=value form."""
    app = _make_app_with_str_flag()
    r = app.test(["cmd", "--target=bar"])
    assert r.exit_code == 0
    assert "target=bar" in r.stdout


def test_bool_flag_present():
    """Bool flag present means True."""
    app = _make_app_with_bool_flag()
    r = app.test(["cmd", "--verbose"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


def test_bool_flag_absent():
    """Bool flag absent means default (False)."""
    app = _make_app_with_bool_flag()
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "verbose=False" in r.stdout


def test_no_flag_negation():
    """--no-flag negation sets False."""
    app = _make_app_with_bool_flag()
    r = app.test(["cmd", "--no-verbose"])
    assert r.exit_code == 0
    assert "verbose=False" in r.stdout


def test_short_flag_bool():
    """Short flag -x for a bool flag."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @excli.flag("verbose", short="v", type=bool, help="be verbose")
    def cmd(verbose):
        print(f"verbose={verbose}")

    r = app.test(["cmd", "-v"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


def test_short_flag_with_value():
    """Short flag -x value for a str flag."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @excli.flag("target", short="t", type=str, help="the target")
    def cmd(target):
        print(f"target={target}")

    r = app.test(["cmd", "-t", "foo"])
    assert r.exit_code == 0
    assert "target=foo" in r.stdout


def test_unknown_flag_error():
    """Unknown flag raises error (exit_code=1)."""
    app = _make_app_with_bool_flag()
    r = app.test(["cmd", "--unknown"])
    assert r.exit_code == 1
    assert "unknown flag" in r.stderr


def test_missing_required_str_flag():
    """Missing required str flag raises error."""
    app = _make_app_with_str_flag()
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "required" in r.stderr


def test_double_dash_separator():
    """-- separator stops flag parsing; remaining tokens become positional."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", args=[excli.Arg(name="path", help="a path")])
    @excli.flag("verbose", type=bool, help="be verbose")
    def cmd(verbose, path):
        print(f"verbose={verbose} path={path}")

    r = app.test(["cmd", "--", "--not-a-flag"])
    assert r.exit_code == 0
    assert "path=--not-a-flag" in r.stdout
    assert "verbose=False" in r.stdout


def test_positional_args_in_order():
    """Positional args matched in order."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[excli.Arg(name="src", help="source"), excli.Arg(name="dst", help="dest")],
    )
    def cmd(src, dst):
        print(f"src={src} dst={dst}")

    r = app.test(["cmd", "a.txt", "b.txt"])
    assert r.exit_code == 0
    assert "src=a.txt" in r.stdout
    assert "dst=b.txt" in r.stdout


def test_missing_required_positional_arg():
    """Missing required positional arg raises error."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", args=[excli.Arg(name="path", help="a path")])
    def cmd(path):
        pass

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "missing required argument" in r.stderr


def test_extra_positional_arg():
    """Extra positional arg raises error."""
    app = excli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    def cmd():
        pass

    r = app.test(["cmd", "surprise"])
    assert r.exit_code == 1
    assert "unexpected argument" in r.stderr


def test_required_str_flag_via_equals():
    """Required str flag provided via --flag=value works."""
    app = _make_app_with_str_flag()
    r = app.test(["cmd", "--target=hello"])
    assert r.exit_code == 0
    assert "target=hello" in r.stdout
