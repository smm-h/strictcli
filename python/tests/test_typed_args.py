"""Tests for typed positional args (type coercion, choices, invoke)."""

import pytest

import strictcli


# ---------------------------------------------------------------------------
# 2a: Arg type field registration
# ---------------------------------------------------------------------------


def test_arg_type_defaults_to_str():
    """Arg with no explicit type defaults to str."""
    a = strictcli.Arg(name="x", help="a value")
    assert a.type is str


def test_arg_type_int():
    """Arg can be declared with type=int."""
    a = strictcli.Arg(name="x", help="a value", type=int)
    assert a.type is int


def test_arg_type_float():
    """Arg can be declared with type=float."""
    a = strictcli.Arg(name="x", help="a value", type=float)
    assert a.type is float


def test_arg_type_bool():
    """Arg can be declared with type=bool."""
    a = strictcli.Arg(name="x", help="a value", type=bool)
    assert a.type is bool


def test_arg_invalid_type_raises():
    """Arg with unsupported type raises ValueError at registration."""
    with pytest.raises(ValueError, match="Arg.type must be str, bool, int, or float"):
        strictcli.Arg(name="x", help="a value", type=list)


def test_arg_int_default_type_validated():
    """type=int requires an int default."""
    with pytest.raises(ValueError, match="type=int requires an int default"):
        strictcli.Arg(name="x", help="a value", type=int, required=False, default="5")


def test_arg_float_default_type_validated():
    """type=float requires a float default."""
    with pytest.raises(ValueError, match="type=float requires a float default"):
        strictcli.Arg(name="x", help="a value", type=float, required=False, default="5.0")


def test_arg_bool_default_type_validated():
    """type=bool requires a bool default."""
    with pytest.raises(ValueError, match="type=bool requires a bool default"):
        strictcli.Arg(name="x", help="a value", type=bool, required=False, default="true")


def test_arg_int_default_rejects_bool():
    """type=int rejects bool as default (bool is subclass of int in Python)."""
    with pytest.raises(ValueError, match="type=int requires an int default"):
        strictcli.Arg(name="x", help="a value", type=int, required=False, default=True)


def test_arg_float_default_accepts_int():
    """type=float accepts int default (int is valid for float)."""
    a = strictcli.Arg(name="x", help="a value", type=float, required=False, default=5)
    assert a.default == 5


# ---------------------------------------------------------------------------
# 2b: Parse-time type coercion
# ---------------------------------------------------------------------------


def test_int_arg_valid():
    """Int arg parses valid integer string."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        print(f"count={count} type={type(count).__name__}")

    r = app.test(["cmd", "42"])
    assert r.exit_code == 0
    assert "count=42 type=int" in r.stdout


def test_int_arg_invalid():
    """Int arg rejects non-integer string."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        pass

    r = app.test(["cmd", "abc"])
    assert r.exit_code == 1
    assert "argument 'count': expected integer, got 'abc'" in r.stderr


def test_int_arg_rejects_float_string():
    """Int arg rejects float string."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        pass

    r = app.test(["cmd", "3.14"])
    assert r.exit_code == 1
    assert "expected integer" in r.stderr


def test_int_arg_negative():
    """Int arg handles negative values (after -- separator)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="offset", help="offset value", type=int)],
    )
    def cmd(ctx, offset):
        print(f"offset={offset} type={type(offset).__name__}")

    r = app.test(["cmd", "--", "-7"])
    assert r.exit_code == 0
    assert "offset=-7 type=int" in r.stdout


def test_float_arg_valid():
    """Float arg parses valid float string."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        print(f"ratio={ratio} type={type(ratio).__name__}")

    r = app.test(["cmd", "3.14"])
    assert r.exit_code == 0
    assert "ratio=3.14 type=float" in r.stdout


def test_float_arg_invalid():
    """Float arg rejects non-numeric string."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        pass

    r = app.test(["cmd", "abc"])
    assert r.exit_code == 1
    assert "argument 'ratio': expected float, got 'abc'" in r.stderr


def test_float_arg_rejects_nan():
    """Float arg rejects NaN."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        pass

    r = app.test(["cmd", "nan"])
    assert r.exit_code == 1
    assert "NaN is not allowed" in r.stderr


def test_float_arg_rejects_inf():
    """Float arg rejects Inf."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        pass

    r = app.test(["cmd", "inf"])
    assert r.exit_code == 1
    assert "Inf is not allowed" in r.stderr


def test_float_arg_integer_string():
    """Float arg accepts integer string (coerces to float)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        print(f"ratio={ratio} type={type(ratio).__name__}")

    r = app.test(["cmd", "5"])
    assert r.exit_code == 0
    assert "ratio=5.0 type=float" in r.stdout


def test_bool_arg_valid_true():
    """Bool arg parses valid true strings."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="flag", help="a flag", type=bool)],
    )
    def cmd(ctx, flag):
        print(f"flag={flag} type={type(flag).__name__}")

    for value in ("true", "True", "TRUE", "1", "yes", "Yes"):
        r = app.test(["cmd", value])
        assert r.exit_code == 0, f"Failed for {value}"
        assert "flag=True type=bool" in r.stdout, f"Failed for {value}"


def test_bool_arg_valid_false():
    """Bool arg parses valid false strings."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="flag", help="a flag", type=bool)],
    )
    def cmd(ctx, flag):
        print(f"flag={flag} type={type(flag).__name__}")

    for value in ("false", "False", "FALSE", "0", "no", "No"):
        r = app.test(["cmd", value])
        assert r.exit_code == 0, f"Failed for {value}"
        assert "flag=False type=bool" in r.stdout, f"Failed for {value}"


def test_bool_arg_invalid():
    """Bool arg rejects invalid strings."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="flag", help="a flag", type=bool)],
    )
    def cmd(ctx, flag):
        pass

    r = app.test(["cmd", "maybe"])
    assert r.exit_code == 1
    assert "argument 'flag': expected boolean, got 'maybe'" in r.stderr


def test_str_arg_backward_compat():
    """Existing str args work unchanged (no coercion)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="name", help="a name")],
    )
    def cmd(ctx, name):
        print(f"name={name} type={type(name).__name__}")

    r = app.test(["cmd", "hello"])
    assert r.exit_code == 0
    assert "name=hello type=str" in r.stdout


def test_str_arg_explicit_type():
    """Arg with explicit type=str behaves same as default."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="name", help="a name", type=str)],
    )
    def cmd(ctx, name):
        print(f"name={name} type={type(name).__name__}")

    r = app.test(["cmd", "hello"])
    assert r.exit_code == 0
    assert "name=hello type=str" in r.stdout


# ---------------------------------------------------------------------------
# 2b: Variadic typed args
# ---------------------------------------------------------------------------


def test_variadic_int_args():
    """Variadic arg with type=int parses multiple integers."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="numbers", help="numbers", type=int, variadic=True)],
    )
    def cmd(ctx, numbers):
        total = sum(numbers)
        types = [type(n).__name__ for n in numbers]
        print(f"sum={total} types={types}")

    r = app.test(["cmd", "1", "2", "3"])
    assert r.exit_code == 0
    assert "sum=6" in r.stdout
    assert "['int', 'int', 'int']" in r.stdout


def test_variadic_int_args_invalid():
    """Variadic int arg rejects non-integer in the list."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="numbers", help="numbers", type=int, variadic=True)],
    )
    def cmd(ctx, numbers):
        pass

    r = app.test(["cmd", "1", "abc", "3"])
    assert r.exit_code == 1
    assert "argument 'numbers': expected integer, got 'abc'" in r.stderr


def test_variadic_float_args():
    """Variadic arg with type=float parses multiple floats."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="values", help="values", type=float, variadic=True)],
    )
    def cmd(ctx, values):
        types = [type(v).__name__ for v in values]
        print(f"values={values} types={types}")

    r = app.test(["cmd", "1.5", "2.7"])
    assert r.exit_code == 0
    assert "types=['float', 'float']" in r.stdout


# ---------------------------------------------------------------------------
# 2c: Arg choices
# ---------------------------------------------------------------------------


def test_str_arg_choices_valid():
    """Str arg with choices accepts valid choice."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="color", help="pick a color", choices=["red", "blue", "green"])],
    )
    def cmd(ctx, color):
        print(f"color={color}")

    r = app.test(["cmd", "red"])
    assert r.exit_code == 0
    assert "color=red" in r.stdout


def test_str_arg_choices_invalid():
    """Str arg with choices rejects invalid choice."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="color", help="pick a color", choices=["red", "blue", "green"])],
    )
    def cmd(ctx, color):
        pass

    r = app.test(["cmd", "yellow"])
    assert r.exit_code == 1
    assert "argument 'color': invalid value 'yellow'" in r.stderr
    assert "must be one of: red, blue, green" in r.stderr


def test_int_arg_choices_valid():
    """Int arg with choices accepts valid choice."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="level", help="pick a level", type=int, choices=[1, 2, 3])],
    )
    def cmd(ctx, level):
        print(f"level={level} type={type(level).__name__}")

    r = app.test(["cmd", "2"])
    assert r.exit_code == 0
    assert "level=2 type=int" in r.stdout


def test_int_arg_choices_invalid():
    """Int arg with choices rejects invalid choice."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="level", help="pick a level", type=int, choices=[1, 2, 3])],
    )
    def cmd(ctx, level):
        pass

    r = app.test(["cmd", "5"])
    assert r.exit_code == 1
    assert "argument 'level': invalid value '5'" in r.stderr
    assert "must be one of: 1, 2, 3" in r.stderr


def test_choices_registration_type_mismatch():
    """Choices items must match the arg's type at registration."""
    with pytest.raises(ValueError, match="choice 'x' is not of type int"):
        strictcli.Arg(name="level", help="pick", type=int, choices=["x", "y"])


def test_choices_bool_incompatible():
    """Choices is incompatible with type=bool."""
    with pytest.raises(ValueError, match="choices is incompatible with type=bool"):
        strictcli.Arg(name="flag", help="pick", type=bool, choices=[True, False])


def test_choices_empty_list():
    """Empty choices list raises ValueError."""
    with pytest.raises(ValueError, match="choices must be a non-empty list"):
        strictcli.Arg(name="x", help="pick", choices=[])


def test_choices_default_must_be_in_choices():
    """Default value must be in choices if both are set."""
    with pytest.raises(ValueError, match="default .* is not in choices"):
        strictcli.Arg(
            name="x", help="pick", required=False,
            default="yellow", choices=["red", "blue"],
        )


def test_choices_default_valid():
    """Default value in choices is accepted."""
    a = strictcli.Arg(
        name="x", help="pick", required=False,
        default="red", choices=["red", "blue"],
    )
    assert a.default == "red"


def test_variadic_int_arg_choices():
    """Variadic int arg with choices validates each element."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(
            name="levels", help="pick levels", type=int,
            choices=[1, 2, 3], variadic=True,
        )],
    )
    def cmd(ctx, levels):
        print(f"levels={levels}")

    r = app.test(["cmd", "1", "3"])
    assert r.exit_code == 0
    assert "levels=[1, 3]" in r.stdout

    r = app.test(["cmd", "1", "5"])
    assert r.exit_code == 1
    assert "argument 'levels': invalid value '5'" in r.stderr


# ---------------------------------------------------------------------------
# 2d: Typed args via _invoke()
# ---------------------------------------------------------------------------


def test_invoke_int_arg():
    """_invoke passes int args through the string round-trip correctly."""
    captured = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        captured["count"] = count
        captured["type"] = type(count).__name__

    app._invoke("cmd", {"count": 42})
    assert captured["count"] == 42
    assert captured["type"] == "int"

    # Compare with CLI path
    captured.clear()
    app.test(["cmd", "42"])
    assert captured["count"] == 42
    assert captured["type"] == "int"


def test_invoke_float_arg():
    """_invoke passes float args through correctly."""
    captured = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        captured["ratio"] = ratio
        captured["type"] = type(ratio).__name__

    app._invoke("cmd", {"ratio": 3.14})
    assert captured["ratio"] == 3.14
    assert captured["type"] == "float"

    # Compare with CLI path
    captured.clear()
    app.test(["cmd", "3.14"])
    assert captured["ratio"] == 3.14
    assert captured["type"] == "float"


def test_invoke_bool_arg():
    """_invoke passes bool args through correctly."""
    captured = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="flag", help="a flag", type=bool)],
    )
    def cmd(ctx, flag):
        captured["flag"] = flag
        captured["type"] = type(flag).__name__

    app._invoke("cmd", {"flag": True})
    assert captured["flag"] is True
    assert captured["type"] == "bool"

    # Compare with CLI path
    captured.clear()
    app.test(["cmd", "true"])
    assert captured["flag"] is True
    assert captured["type"] == "bool"


def test_invoke_variadic_int_args():
    """_invoke handles variadic int args."""
    captured = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="numbers", help="numbers", type=int, variadic=True)],
    )
    def cmd(ctx, numbers):
        captured["numbers"] = numbers
        captured["sum"] = sum(numbers)

    app._invoke("cmd", {"numbers": [10, 20, 30]})
    assert captured["sum"] == 60
    assert all(isinstance(n, int) for n in captured["numbers"])

    # Compare with CLI path
    captured.clear()
    app.test(["cmd", "10", "20", "30"])
    assert captured["sum"] == 60
    assert all(isinstance(n, int) for n in captured["numbers"])


def test_invoke_str_arg_backward_compat():
    """_invoke with str args works unchanged."""
    captured = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="name", help="a name")],
    )
    def cmd(ctx, name):
        captured["name"] = name
        captured["type"] = type(name).__name__

    app._invoke("cmd", {"name": "hello"})
    assert captured["name"] == "hello"
    assert captured["type"] == "str"


def test_invoke_int_arg_with_choices():
    """_invoke validates choices for typed args."""
    captured = {}
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="level", help="pick a level", type=int, choices=[1, 2, 3])],
    )
    def cmd(ctx, level):
        captured["level"] = level

    app._invoke("cmd", {"level": 2})
    assert captured["level"] == 2

    with pytest.raises(Exception, match="invalid value '5'"):
        app._invoke("cmd", {"level": 5})


# ---------------------------------------------------------------------------
# Error message patterns (must match flag error patterns)
# ---------------------------------------------------------------------------


def test_int_arg_error_matches_flag_pattern():
    """Int arg error message follows the same pattern as flag int errors."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        pass

    r = app.test(["cmd", "xyz"])
    assert r.exit_code == 1
    # Flag pattern is: --flag-name: expected integer, got 'xyz'
    # Arg pattern is: argument 'count': expected integer, got 'xyz'
    assert "expected integer, got 'xyz'" in r.stderr


def test_float_arg_error_matches_flag_pattern():
    """Float arg error message follows the same pattern as flag float errors."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="ratio", help="a ratio", type=float)],
    )
    def cmd(ctx, ratio):
        pass

    r = app.test(["cmd", "xyz"])
    assert r.exit_code == 1
    # Flag pattern is: --flag-name: expected float, got 'xyz'
    # Arg pattern is: argument 'ratio': expected float, got 'xyz'
    assert "expected float, got 'xyz'" in r.stderr


def test_bool_arg_error_matches_flag_pattern():
    """Bool arg error message follows the same pattern as flag/env bool errors."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="flag", help="a flag", type=bool)],
    )
    def cmd(ctx, flag):
        pass

    r = app.test(["cmd", "xyz"])
    assert r.exit_code == 1
    # Bool pattern is: expected boolean, got 'xyz'
    assert "expected boolean, got 'xyz'" in r.stderr


# ---------------------------------------------------------------------------
# Help text display
# ---------------------------------------------------------------------------


def test_typed_arg_shows_type_in_help():
    """Non-str typed args show [type: X] in help text."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "[type: int]" in r.stdout


def test_str_arg_no_type_in_help():
    """Str args do NOT show [type: str] in help (it's the default)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="name", help="a name")],
    )
    def cmd(ctx, name):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "[type:" not in r.stdout


def test_choices_shown_in_help():
    """Arg choices shown in help text."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="color", help="pick a color", choices=["red", "blue"])],
    )
    def cmd(ctx, color):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "[choices: red, blue]" in r.stdout


# ---------------------------------------------------------------------------
# Decorator-based typed args
# ---------------------------------------------------------------------------


def test_decorator_int_arg():
    """@strictcli.arg decorator with type=int works."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.arg("count", help="a count", type=int)
    def cmd(ctx, count):
        print(f"count={count} type={type(count).__name__}")

    r = app.test(["cmd", "42"])
    assert r.exit_code == 0
    assert "count=42 type=int" in r.stdout


def test_decorator_arg_with_choices():
    """@strictcli.arg decorator with choices works."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.arg("color", help="pick a color", choices=["red", "blue"])
    def cmd(ctx, color):
        print(f"color={color}")

    r = app.test(["cmd", "red"])
    assert r.exit_code == 0
    assert "color=red" in r.stdout

    r = app.test(["cmd", "yellow"])
    assert r.exit_code == 1
    assert "invalid value 'yellow'" in r.stderr


# ---------------------------------------------------------------------------
# Mixed typed args and flags
# ---------------------------------------------------------------------------


def test_mixed_typed_arg_and_flags():
    """Typed arg works alongside regular flags."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    @strictcli.flag("verbose", type=bool, default=False, help="verbose output")
    def cmd(ctx, count, verbose):
        print(f"count={count} type={type(count).__name__} verbose={verbose}")

    r = app.test(["cmd", "--verbose", "42"])
    assert r.exit_code == 0
    assert "count=42 type=int" in r.stdout
    assert "verbose=True" in r.stdout


def test_int_arg_with_leading_whitespace():
    """Int arg rejects leading whitespace (strict parsing)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="count", help="a count", type=int)],
    )
    def cmd(ctx, count):
        pass

    r = app.test(["cmd", " 42"])
    assert r.exit_code == 1
    assert "expected integer" in r.stderr
