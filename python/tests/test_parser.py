"""Tests for argument parsing."""

import strictcli


def _make_app_with_str_flag(**flag_kwargs):
    """Helper: app with a single command that has one str flag."""
    # Presence is mandatory (contract §23); these helpers declare the plain
    # required case unless the caller states its own.
    if "default" not in flag_kwargs and "presence" not in flag_kwargs:
        flag_kwargs["presence"] = "required"
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("target", type=str, help="the target", **flag_kwargs)
    def cmd(ctx, target):
        print(f"target={target}")

    return app


def _make_app_with_bool_flag():
    """Helper: app with a single command that has one bool flag."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("loud", type=bool, default=False, help="be loud")
    def cmd(ctx, loud):
        print(f"loud={loud}")

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
    r = app.test(["cmd", "--loud"])
    assert r.exit_code == 0
    assert "loud=True" in r.stdout


def test_bool_flag_absent():
    """Bool flag absent means default (False)."""
    app = _make_app_with_bool_flag()
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "loud=False" in r.stdout


def test_no_flag_negation():
    """--no-flag negation sets False."""
    app = _make_app_with_bool_flag()
    r = app.test(["cmd", "--no-loud"])
    assert r.exit_code == 0
    assert "loud=False" in r.stdout


def test_short_flag_bool():
    """Short flag -x for a bool flag."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("loud", short="v", type=bool, default=False, help="be loud")
    def cmd(ctx, loud):
        print(f"loud={loud}")

    r = app.test(["cmd", "-v"])
    assert r.exit_code == 0
    assert "loud=True" in r.stdout


def test_short_flag_with_value():
    """Short flag -x value for a str flag."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("target", short="t", type=str, help="the target", presence="required")
    def cmd(ctx, target):
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
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", args=[strictcli.Arg(name="path", help="a path", presence="required")])
    @strictcli.flag("loud", type=bool, default=False, help="be loud")
    def cmd(ctx, loud, path):
        print(f"loud={loud} path={path}")

    r = app.test(["cmd", "--", "--not-a-flag"])
    assert r.exit_code == 0
    assert "path=--not-a-flag" in r.stdout
    assert "loud=False" in r.stdout


def test_positional_args_in_order():
    """Positional args matched in order."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(name="src", help="source", presence="required"), strictcli.Arg(name="dst", help="dest", presence="required")],
    )
    def cmd(ctx, src, dst):
        print(f"src={src} dst={dst}")

    r = app.test(["cmd", "a.txt", "b.txt"])
    assert r.exit_code == 0
    assert "src=a.txt" in r.stdout
    assert "dst=b.txt" in r.stdout


def test_missing_required_positional_arg():
    """Missing required positional arg raises error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", args=[strictcli.Arg(name="path", help="a path", presence="required")])
    def cmd(ctx, path):
        pass

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "missing required argument" in r.stderr


def test_extra_positional_arg():
    """Extra positional arg raises error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    def cmd(ctx):
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


def test_str_flag_value_starting_with_hyphen():
    """Str flag accepts a value that starts with a hyphen (e.g. --offset -5)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("offset", short="o", type=str, help="the offset", presence="required")
    def cmd(ctx, offset):
        print(f"offset={offset}")

    # Long flag form
    r = app.test(["cmd", "--offset", "-5"])
    assert r.exit_code == 0
    assert "offset=-5" in r.stdout

    # Short flag form
    r = app.test(["cmd", "-o", "-5"])
    assert r.exit_code == 0
    assert "offset=-5" in r.stdout


# ---------------------------------------------------------------------------
# Parse-problem precedence: structure before value
#
# The rule is normative for EVERY command, not only for one that declares a
# selector: an unknown flag, an unknown choice and a scope violation are facts
# about the command line's shape, and shape is decided before any token's text
# is interpreted as a value. A command line carrying both kinds of problem
# therefore reports the same error whatever the order of the two tokens.
# ---------------------------------------------------------------------------


def _precedence_app():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("count", type=int, help="how many", presence="optional")
    @strictcli.flag("ratio", type=float, help="the ratio", presence="optional")
    @strictcli.flag(
        "mode", type=str, help="the mode", presence="optional",
        choices=[strictcli.Choice("fast"), strictcli.Choice("slow")],
    )
    def cmd(ctx, count, ratio, mode):
        print("ok")

    return app


def test_an_unknown_flag_outranks_a_value_that_will_not_coerce():
    r = _precedence_app().test(["cmd", "--count", "abc", "--unknown"])
    assert r.exit_code == 1
    assert "error: unknown flag '--unknown'\n" in r.stderr


def test_the_same_holds_when_the_bad_value_comes_second():
    r = _precedence_app().test(["cmd", "--unknown", "--count", "abc"])
    assert r.exit_code == 1
    assert "error: unknown flag '--unknown'\n" in r.stderr


def test_an_unknown_flag_outranks_a_float_that_will_not_coerce():
    r = _precedence_app().test(["cmd", "--ratio", "nope", "--unknown"])
    assert r.exit_code == 1
    assert "error: unknown flag '--unknown'\n" in r.stderr


def test_an_unknown_flag_outranks_an_invalid_choice():
    r = _precedence_app().test(["cmd", "--mode", "sideways", "--unknown"])
    assert r.exit_code == 1
    assert "error: unknown flag '--unknown'\n" in r.stderr


def test_a_value_problem_alone_still_reports_itself():
    """Precedence orders problems; it never suppresses one."""
    r = _precedence_app().test(["cmd", "--count", "abc"])
    assert r.exit_code == 1
    assert "error: --count: expected integer, got 'abc'\n" in r.stderr


def test_value_problems_are_reported_in_argv_order_among_themselves():
    r = _precedence_app().test(["cmd", "--count", "abc", "--ratio", "nope"])
    assert r.exit_code == 1
    assert "error: --count: expected integer, got 'abc'\n" in r.stderr

    r = _precedence_app().test(["cmd", "--ratio", "nope", "--count", "abc"])
    assert r.exit_code == 1
    assert "--ratio" in r.stderr


def test_a_missing_value_is_structural_and_outranks_a_bad_value():
    """`--flag` with nothing after it is a token-consumption fact, decided in
    the scan; it is reported ahead of a value that will not coerce."""
    r = _precedence_app().test(["cmd", "--count", "abc", "--ratio"])
    assert r.exit_code == 1
    assert "error: flag '--ratio' requires a value\n" in r.stderr
