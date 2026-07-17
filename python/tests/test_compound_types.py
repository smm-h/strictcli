"""Tests for compound types: list[T] and dict[str, T] on flags and args."""

import json
import os
import pytest

import strictcli


# ---------------------------------------------------------------------------
# list[T] on flags
# ---------------------------------------------------------------------------


class TestListFlagRegistration:
    """Registration-time validation for list[T] flags."""

    def test_list_int_creates_repeatable_flag(self):
        """list[int] flag is internally repeatable with item_type=int."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="list of ids")
        def cmd(ctx, ids):
            pass

        cmd_obj = app._commands["cmd"]
        f = cmd_obj.flags[0]
        assert f.compound == "list"
        assert f.item_type is int
        assert f.repeatable is True
        assert f.type is int  # normalized to item type

    def test_list_str(self):
        """list[str] is a valid compound type."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("names", type=list[str], help="names")
        def cmd(ctx, names):
            pass

        cmd_obj = app._commands["cmd"]
        f = cmd_obj.flags[0]
        assert f.compound == "list"
        assert f.item_type is str

    def test_list_float(self):
        """list[float] is a valid compound type."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("values", type=list[float], help="values")
        def cmd(ctx, values):
            pass

        cmd_obj = app._commands["cmd"]
        f = cmd_obj.flags[0]
        assert f.compound == "list"
        assert f.item_type is float

    def test_list_bool_rejected(self):
        """list[bool] is not allowed (bool can't be repeatable)."""
        with pytest.raises(ValueError, match="list item type must be str, int, or float"):
            strictcli.Flag(name="items", type=list[bool], help="items")

    def test_bare_list_rejected(self):
        """Bare list without type argument is rejected."""
        with pytest.raises(ValueError, match="list type requires an item type"):
            strictcli.Flag(name="items", type=list, help="items")

    def test_list_with_explicit_repeatable_redundant(self):
        """list[int] + repeatable=True is allowed (redundant but not error)."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "ids", type=list[int], help="ids", repeatable=True, unique=False,
        )
        def cmd(ctx, ids):
            pass

        cmd_obj = app._commands["cmd"]
        f = cmd_obj.flags[0]
        assert f.compound == "list"
        assert f.repeatable is True

    def test_list_with_unique(self):
        """list[T] with unique=True works."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids", unique=True)
        def cmd(ctx, ids):
            pass

        cmd_obj = app._commands["cmd"]
        f = cmd_obj.flags[0]
        assert f.unique is True

    def test_list_default_is_empty_list(self):
        """Default for list[T] is []."""
        f = strictcli.Flag(name="ids", type=list[int], help="ids")
        assert f.default == []

    def test_list_explicit_default(self):
        """Explicit non-empty default for list[T]."""
        f = strictcli.Flag(
            name="ids", type=list[int], help="ids",
            default=[1, 2, 3],
        )
        assert f.default == [1, 2, 3]


class TestListFlagParsing:
    """CLI parsing for list[T] flags."""

    def test_list_int_multiple_values(self):
        """Multiple --flag val occurrences produce a list."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids")
        def cmd(ctx, ids):
            print(f"ids={ids!r}")

        r = app.test(["cmd", "--ids", "1", "--ids", "2", "--ids", "3"])
        assert r.exit_code == 0
        assert "ids=[1, 2, 3]" in r.stdout

    def test_list_str_multiple_values(self):
        """list[str] collects string values."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("tags", type=list[str], help="tags")
        def cmd(ctx, tags):
            print(f"tags={tags!r}")

        r = app.test(["cmd", "--tags", "a", "--tags", "b"])
        assert r.exit_code == 0
        assert "tags=['a', 'b']" in r.stdout

    def test_list_float_multiple_values(self):
        """list[float] coerces values to float."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("weights", type=list[float], help="weights")
        def cmd(ctx, weights):
            print(f"weights={weights!r}")

        r = app.test(["cmd", "--weights", "1.5", "--weights", "2.7"])
        assert r.exit_code == 0
        assert "weights=[1.5, 2.7]" in r.stdout

    def test_list_int_bad_value(self):
        """Invalid int in list[int] produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids")
        def cmd(ctx, ids):
            pass

        r = app.test(["cmd", "--ids", "abc"])
        assert r.exit_code == 1
        assert "--ids" in r.stderr

    def test_list_empty_when_omitted(self):
        """No occurrences produce an empty list."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids")
        def cmd(ctx, ids):
            print(f"ids={ids!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "ids=[]" in r.stdout

    def test_list_equals_form(self):
        """--flag=value form works for list flags."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids")
        def cmd(ctx, ids):
            print(f"ids={ids!r}")

        r = app.test(["cmd", "--ids=1", "--ids=2"])
        assert r.exit_code == 0
        assert "ids=[1, 2]" in r.stdout

    def test_list_unique_rejects_duplicates(self):
        """unique=True with list[int] rejects duplicate values."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids", unique=True)
        def cmd(ctx, ids):
            pass

        r = app.test(["cmd", "--ids", "1", "--ids", "1"])
        assert r.exit_code == 1
        assert "duplicate" in r.stderr

    def test_list_with_choices(self):
        """list[T] with choices validates each element."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "level", type=list[str], help="levels",
            choices=["debug", "info", "error"],
        )
        def cmd(ctx, level):
            print(f"level={level!r}")

        r = app.test(["cmd", "--level", "debug", "--level", "info"])
        assert r.exit_code == 0

        r2 = app.test(["cmd", "--level", "unknown"])
        assert r2.exit_code == 1
        assert "invalid value" in r2.stderr


class TestListFlagEnv:
    """Env var resolution for list[T] flags."""

    def test_list_env_with_separator(self):
        """list[T] with env + env_separator splits env value."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "ids", type=list[int], help="ids",
            env="TEST_IDS", env_separator=",",
        )
        def cmd(ctx, ids):
            print(f"ids={ids!r}")

        os.environ["TEST_IDS"] = "1,2,3"
        try:
            r = app.test(["cmd"])
            assert r.exit_code == 0
            assert "ids=[1, 2, 3]" in r.stdout
        finally:
            del os.environ["TEST_IDS"]


class TestListFlagCall:
    """app.call() with list[T] flags."""

    def test_call_with_native_list(self):
        """app.call() passes native Python lists directly."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")
        result = {}

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids")
        def cmd(ctx, ids):
            result["ids"] = ids

        app.call("cmd", ids=[1, 2, 3])
        assert result["ids"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# list[T] on args
# ---------------------------------------------------------------------------


class TestListArgRegistration:
    """Registration-time validation for list[T] args."""

    def test_list_arg_requires_variadic(self):
        """list[T] on args requires variadic=True."""
        with pytest.raises(ValueError, match="list type on args requires variadic=True"):
            strictcli.Arg(name="files", type=list[str], help="files")

    def test_list_arg_variadic_valid(self):
        """list[T] with variadic=True is valid."""
        a = strictcli.Arg(
            name="files", type=list[str], help="files", variadic=True,
        )
        assert a.compound == "list"
        assert a.item_type is str
        assert a.type is str  # normalized

    def test_list_arg_int(self):
        """list[int] variadic arg coerces values."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(
                name="nums", type=list[int], help="numbers", variadic=True,
            ),
        ])
        def cmd(ctx, nums):
            print(f"nums={nums!r}")

        r = app.test(["cmd", "1", "2", "3"])
        assert r.exit_code == 0
        assert "nums=[1, 2, 3]" in r.stdout

    def test_dict_on_args_rejected(self):
        """dict type on args is not supported."""
        with pytest.raises(ValueError, match="dict type is not supported on args"):
            strictcli.Arg(name="data", type=dict[str, str], help="data")


# ---------------------------------------------------------------------------
# dict[str, T] on flags
# ---------------------------------------------------------------------------


class TestDictFlagRegistration:
    """Registration-time validation for dict[str, T] flags."""

    def test_dict_str_str(self):
        """dict[str, str] creates a dict flag."""
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        assert f.compound == "dict"
        assert f.value_type is str
        assert f.type is str  # normalized to value type

    def test_dict_str_int(self):
        """dict[str, int] is valid."""
        f = strictcli.Flag(name="counts", type=dict[str, int], help="counts")
        assert f.compound == "dict"
        assert f.value_type is int

    def test_dict_str_float(self):
        """dict[str, float] is valid."""
        f = strictcli.Flag(name="weights", type=dict[str, float], help="weights")
        assert f.compound == "dict"
        assert f.value_type is float

    def test_dict_non_str_key_rejected(self):
        """dict with non-str key type is rejected."""
        with pytest.raises(ValueError, match="dict key type must be str"):
            strictcli.Flag(name="data", type=dict[int, str], help="data")

    def test_dict_bool_value_rejected(self):
        """dict[str, bool] is rejected."""
        with pytest.raises(ValueError, match="dict value type must be str, int, or float"):
            strictcli.Flag(name="flags", type=dict[str, bool], help="flags")

    def test_bare_dict_rejected(self):
        """Bare dict without type arguments is rejected."""
        with pytest.raises(ValueError, match="dict type requires type arguments"):
            strictcli.Flag(name="data", type=dict, help="data")

    def test_dict_with_repeatable_rejected(self):
        """dict type + repeatable=True is an error."""
        with pytest.raises(ValueError, match="dict type cannot be combined with repeatable"):
            strictcli.Flag(
                name="data", type=dict[str, str], help="data",
                repeatable=True, unique=False,
            )

    def test_dict_with_unique_rejected(self):
        """dict type + unique is an error."""
        with pytest.raises(ValueError, match="dict type cannot be combined with unique"):
            strictcli.Flag(
                name="data", type=dict[str, str], help="data",
                unique=True,
            )

    def test_dict_with_choices_rejected(self):
        """dict type + choices is an error."""
        with pytest.raises(ValueError, match="dict type cannot be combined with choices"):
            strictcli.Flag(
                name="data", type=dict[str, str], help="data",
                choices=["a", "b"],
            )

    def test_dict_with_env_separator_rejected(self):
        """dict type + env_separator is an error."""
        with pytest.raises(ValueError, match="dict type cannot use env_separator"):
            strictcli.Flag(
                name="data", type=dict[str, str], help="data",
                env="TEST_DATA", env_separator=",",
            )

    def test_dict_default_is_empty_dict(self):
        """Default for dict[str, T] is {}."""
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        assert f.default == {}

    def test_dict_explicit_default(self):
        """Explicit default for dict[str, T]."""
        f = strictcli.Flag(
            name="headers", type=dict[str, str], help="headers",
            default={"Accept": "json"},
        )
        assert f.default == {"Accept": "json"}

    def test_dict_invalid_default_type(self):
        """Non-dict default is rejected."""
        with pytest.raises(ValueError, match="dict flag default must be a dict"):
            strictcli.Flag(
                name="headers", type=dict[str, str], help="headers",
                default=["not", "a", "dict"],
            )

    def test_dict_empty_default_rejected(self):
        """Explicit empty dict default is rejected (redundant)."""
        with pytest.raises(ValueError, match="explicit empty default is redundant"):
            strictcli.Flag(
                name="headers", type=dict[str, str], help="headers",
                default={},
            )

    def test_dict_default_value_type_validated(self):
        """Dict default values must match the value type."""
        with pytest.raises(ValueError, match="is not of type int"):
            strictcli.Flag(
                name="counts", type=dict[str, int], help="counts",
                default={"a": "not_int"},
            )


class TestDictDisplayCanonicalSorted:
    """Dict flag values render as sorted key=value (Go parity)."""

    def test_format_dict_for_display_sorted(self):
        # Insertion order deliberately unsorted; output must be key-sorted.
        assert strictcli._format_dict_for_display(
            {"zebra": 3, "apple": 1, "mango": 2}
        ) == "apple=1, mango=2, zebra=3"

    def test_format_value_for_error_dict_sorted(self):
        assert strictcli._format_value_for_error(
            {"b": "y", "a": "x"}
        ) == "a=x, b=y"

    def test_format_default_for_help_dict_sorted(self):
        assert strictcli._format_default_for_help(
            {"b": 2, "a": 1}
        ) == "a=1, b=2"

    def test_dict_default_rendered_sorted_in_help(self):
        """A dict flag's default renders sorted key=value in command help."""
        app = strictcli.App(name="myapp", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "labels", type=dict[str, int], help="labels",
            default={"zebra": 3, "apple": 1, "mango": 2},
        )
        def cmd(ctx, labels):
            pass

        r = app.test(["cmd", "--help"])
        assert r.exit_code == 0
        assert "default: apple=1, mango=2, zebra=3" in r.stdout


class TestDictFlagParsing:
    """CLI parsing for dict[str, T] flags."""

    def test_dict_key_value_single(self):
        """Single --flag key=value stores one entry."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            print(f"headers={headers!r}")

        r = app.test(["cmd", "--headers", "Accept=json"])
        assert r.exit_code == 0
        assert "headers={'Accept': 'json'}" in r.stdout

    def test_dict_key_value_multiple(self):
        """Multiple --flag key=value occurrences build up a dict."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            # Sort for deterministic output
            print(f"headers={dict(sorted(headers.items()))!r}")

        r = app.test([
            "cmd",
            "--headers", "Accept=json",
            "--headers", "Content-Type=text",
        ])
        assert r.exit_code == 0
        assert "Accept" in r.stdout
        assert "Content-Type" in r.stdout

    def test_dict_int_values(self):
        """dict[str, int] coerces values to int."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("counts", type=dict[str, int], help="counts")
        def cmd(ctx, counts):
            print(f"counts={counts!r}")

        r = app.test(["cmd", "--counts", "a=1", "--counts", "b=2"])
        assert r.exit_code == 0
        assert "'a': 1" in r.stdout
        assert "'b': 2" in r.stdout

    def test_dict_float_values(self):
        """dict[str, float] coerces values to float."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("weights", type=dict[str, float], help="weights")
        def cmd(ctx, weights):
            print(f"weights={weights!r}")

        r = app.test(["cmd", "--weights", "a=1.5", "--weights", "b=2.7"])
        assert r.exit_code == 0
        assert "'a': 1.5" in r.stdout
        assert "'b': 2.7" in r.stdout

    def test_dict_bad_int_value(self):
        """Invalid int value in dict[str, int] produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("counts", type=dict[str, int], help="counts")
        def cmd(ctx, counts):
            pass

        r = app.test(["cmd", "--counts", "a=abc"])
        assert r.exit_code == 1
        assert "--counts" in r.stderr

    def test_dict_missing_equals(self):
        """Missing = in key=value produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            pass

        r = app.test(["cmd", "--headers", "noequals"])
        assert r.exit_code == 1
        assert "expected key=value or JSON" in r.stderr

    def test_dict_empty_key(self):
        """Empty key in =value produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            pass

        r = app.test(["cmd", "--headers", "=value"])
        assert r.exit_code == 1
        assert "empty key" in r.stderr

    def test_dict_duplicate_key(self):
        """Duplicate keys in --flag key=val are rejected."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            pass

        r = app.test(["cmd", "--headers", "a=1", "--headers", "a=2"])
        assert r.exit_code == 1
        assert "duplicate key" in r.stderr

    def test_dict_json_format(self):
        """JSON string starting with { is parsed as dict."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            print(f"headers={dict(sorted(headers.items()))!r}")

        r = app.test([
            "cmd", "--headers", '{"Accept": "json", "Content-Type": "text"}',
        ])
        assert r.exit_code == 0
        assert "Accept" in r.stdout
        assert "Content-Type" in r.stdout

    def test_dict_json_int_values(self):
        """JSON with int values coerced correctly."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("counts", type=dict[str, int], help="counts")
        def cmd(ctx, counts):
            print(f"counts={counts!r}")

        r = app.test(["cmd", "--counts", '{"a": 1, "b": 2}'])
        assert r.exit_code == 0
        assert "'a': 1" in r.stdout
        assert "'b': 2" in r.stdout

    def test_dict_json_type_mismatch(self):
        """JSON value type mismatch produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("counts", type=dict[str, int], help="counts")
        def cmd(ctx, counts):
            pass

        r = app.test(["cmd", "--counts", '{"a": "not_int"}'])
        assert r.exit_code == 1
        assert "must be an integer" in r.stderr

    def test_dict_json_invalid(self):
        """Invalid JSON produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            pass

        r = app.test(["cmd", "--headers", "{invalid json"])
        assert r.exit_code == 1
        assert "invalid JSON" in r.stderr

    def test_dict_json_not_object(self):
        """JSON array (not object) produces an error.

        Since JSON detection triggers on leading '{', an array starting
        with '[' is treated as a non-JSON string and fails key=value parsing.
        """
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            pass

        r = app.test(["cmd", "--headers", '["not", "an", "object"]'])
        assert r.exit_code == 1
        # Array doesn't start with '{' so it's treated as key=value
        assert "expected key=value or JSON" in r.stderr

    def test_dict_empty_when_omitted(self):
        """No occurrences produce an empty dict."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            print(f"headers={headers!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "headers={}" in r.stdout

    def test_dict_equals_form(self):
        """--flag=key=value form works (splits on first = for flag, rest is value)."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            print(f"headers={headers!r}")

        r = app.test(["cmd", "--headers=Accept=json"])
        assert r.exit_code == 0
        assert "'Accept': 'json'" in r.stdout

    def test_dict_value_with_equals(self):
        """Value containing = is preserved (split on first = only)."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("env", type=dict[str, str], help="env vars")
        def cmd(ctx, env):
            print(f"env={env!r}")

        r = app.test(["cmd", "--env", "FOO=bar=baz"])
        assert r.exit_code == 0
        assert "'FOO': 'bar=baz'" in r.stdout

    def test_dict_short_flag(self):
        """Dict flag with short form works."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "headers", short="H", type=dict[str, str], help="headers",
        )
        def cmd(ctx, headers):
            print(f"headers={headers!r}")

        r = app.test(["cmd", "-H", "Accept=json"])
        assert r.exit_code == 0
        assert "'Accept': 'json'" in r.stdout

    def test_dict_json_and_key_value_combined(self):
        """JSON and key=value can be mixed for the same dict flag."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            print(f"count={len(headers)}")

        r = app.test([
            "cmd",
            "--headers", '{"Accept": "json"}',
            "--headers", "Content-Type=text",
        ])
        assert r.exit_code == 0
        assert "count=2" in r.stdout

    def test_dict_json_duplicate_with_key_value(self):
        """Duplicate key between JSON and key=value is rejected."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            pass

        r = app.test([
            "cmd",
            "--headers", '{"Accept": "json"}',
            "--headers", "Accept=text",
        ])
        assert r.exit_code == 1
        assert "duplicate key" in r.stderr


class TestDictFlagEnv:
    """Env var resolution for dict[str, T] flags."""

    def test_dict_env_json(self):
        """Dict flags parse env vars as JSON objects."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "headers", type=dict[str, str], help="headers",
            env="TEST_HEADERS",
        )
        def cmd(ctx, headers):
            print(f"count={len(headers)}")

        os.environ["TEST_HEADERS"] = '{"Accept": "json", "Host": "example.com"}'
        try:
            r = app.test(["cmd"])
            assert r.exit_code == 0
            assert "count=2" in r.stdout
        finally:
            del os.environ["TEST_HEADERS"]

    def test_dict_env_invalid_json(self):
        """Invalid JSON in env var produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "headers", type=dict[str, str], help="headers",
            env="TEST_HEADERS",
        )
        def cmd(ctx, headers):
            pass

        os.environ["TEST_HEADERS"] = "not json"
        try:
            r = app.test(["cmd"])
            assert r.exit_code == 1
            assert "invalid JSON" in r.stderr
        finally:
            del os.environ["TEST_HEADERS"]

    def test_dict_env_not_object(self):
        """Non-object JSON in env var produces an error."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "headers", type=dict[str, str], help="headers",
            env="TEST_HEADERS",
        )
        def cmd(ctx, headers):
            pass

        os.environ["TEST_HEADERS"] = '"just a string"'
        try:
            r = app.test(["cmd"])
            assert r.exit_code == 1
            assert "must be a JSON object" in r.stderr
        finally:
            del os.environ["TEST_HEADERS"]

    def test_dict_cli_overrides_env(self):
        """CLI values override env var for dict flags."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "headers", type=dict[str, str], help="headers",
            env="TEST_HEADERS",
        )
        def cmd(ctx, headers):
            print(f"headers={headers!r}")

        os.environ["TEST_HEADERS"] = '{"Accept": "xml"}'
        try:
            r = app.test(["cmd", "--headers", "Accept=json"])
            assert r.exit_code == 0
            assert "'Accept': 'json'" in r.stdout
        finally:
            del os.environ["TEST_HEADERS"]


class TestDictFlagCall:
    """app.call() with dict[str, T] flags."""

    def test_call_with_native_dict(self):
        """app.call() passes native Python dicts directly."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")
        result = {}

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            result["headers"] = headers

        app.call("cmd", headers={"Accept": "json", "Host": "example.com"})
        assert result["headers"] == {"Accept": "json", "Host": "example.com"}

    def test_call_with_empty_dict(self):
        """app.call() with empty dict works."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")
        result = {}

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            result["headers"] = headers

        app.call("cmd", headers={})
        assert result["headers"] == {}


# ---------------------------------------------------------------------------
# Schema serialization
# ---------------------------------------------------------------------------


class TestCompoundTypeSchema:
    """Schema serialization for compound types."""

    def test_list_int_schema(self):
        """list[int] flag serializes as array type."""
        f = strictcli.Flag(name="ids", type=list[int], help="ids")
        from strictcli import _serialize_flag
        schema = _serialize_flag(f)
        assert schema["type"] == {
            "type": "array",
            "items": {"type": "int"},
        }

    def test_list_str_schema(self):
        """list[str] flag serializes with items.type=str."""
        f = strictcli.Flag(name="tags", type=list[str], help="tags")
        from strictcli import _serialize_flag
        schema = _serialize_flag(f)
        assert schema["type"] == {
            "type": "array",
            "items": {"type": "str"},
        }

    def test_dict_str_str_schema(self):
        """dict[str, str] serializes as object type."""
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        from strictcli import _serialize_flag
        schema = _serialize_flag(f)
        assert schema["type"] == {
            "type": "object",
            "additionalProperties": {"type": "str"},
        }

    def test_dict_str_int_schema(self):
        """dict[str, int] serializes with additionalProperties.type=int."""
        f = strictcli.Flag(name="counts", type=dict[str, int], help="counts")
        from strictcli import _serialize_flag
        schema = _serialize_flag(f)
        assert schema["type"] == {
            "type": "object",
            "additionalProperties": {"type": "int"},
        }

    def test_list_arg_schema(self):
        """list[T] arg serializes as array type."""
        a = strictcli.Arg(
            name="nums", type=list[int], help="numbers", variadic=True,
        )
        from strictcli import _serialize_arg
        schema = _serialize_arg(a)
        assert schema["type"] == {
            "type": "array",
            "items": {"type": "int"},
        }

    def test_scalar_flag_schema_unchanged(self):
        """Scalar flags still serialize as before."""
        f = strictcli.Flag(name="name", type=str, help="name")
        from strictcli import _serialize_flag
        schema = _serialize_flag(f)
        assert schema["type"] == "str"


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------


class TestCompoundTypeHelp:
    """Help text formatting for compound types."""

    def test_list_flag_spec(self):
        """list[T] flag shows correct type in spec."""
        from strictcli import _build_flag_spec
        f = strictcli.Flag(name="ids", type=list[int], help="ids")
        spec = _build_flag_spec(f)
        assert "<int>" in spec

    def test_dict_flag_spec(self):
        """dict[str, T] flag shows key=value format in spec."""
        from strictcli import _build_flag_spec
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        spec = _build_flag_spec(f)
        assert "<key=str>" in spec

    def test_list_flag_meta(self):
        """list[T] flag shows 'list' in metadata."""
        from strictcli import _build_flag_meta
        f = strictcli.Flag(name="ids", type=list[int], help="ids")
        meta = _build_flag_meta(f)
        assert "list" in meta

    def test_dict_flag_meta(self):
        """dict[str, T] flag shows 'dict' in metadata."""
        from strictcli import _build_flag_meta
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        meta = _build_flag_meta(f)
        assert "dict" in meta


# ---------------------------------------------------------------------------
# Config file
# ---------------------------------------------------------------------------


class TestDictFlagConfig:
    """Config file handling for dict flags."""

    def test_config_coerces_dict_value(self):
        """Config file with dict value is coerced correctly."""
        from strictcli import _coerce_config_value
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        result = _coerce_config_value({"Accept": "json"}, f)
        assert result == {"Accept": "json"}

    def test_config_rejects_non_dict(self):
        """Config file with non-dict for dict flag is rejected."""
        from strictcli import _coerce_config_value
        f = strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        with pytest.raises(ValueError, match="expected object"):
            _coerce_config_value(["not", "a", "dict"], f)

    def test_config_validates_value_types(self):
        """Config file dict values are type-checked."""
        from strictcli import _coerce_config_value
        f = strictcli.Flag(name="counts", type=dict[str, int], help="counts")
        with pytest.raises(ValueError, match="expected int"):
            _coerce_config_value({"a": "not_int"}, f)


# ---------------------------------------------------------------------------
# Global flags with compound types
# ---------------------------------------------------------------------------


class TestCompoundGlobalFlags:
    """Compound types on global flags."""

    def test_list_global_flag(self):
        """list[T] works as a global flag."""
        app = strictcli.App(
            name="test", version="1.0.0", help="test app",
            flags=[
                strictcli.Flag("tags", type=list[str], help="tags"),
            ],
        )

        @app.command("cmd", help="a command")
        def cmd(ctx, tags):
            print(f"tags={tags!r}")

        r = app.test(["--tags", "a", "--tags", "b", "cmd"])
        assert r.exit_code == 0
        assert "tags=['a', 'b']" in r.stdout

    def test_dict_global_flag(self):
        """dict[str, T] works as a global flag."""
        app = strictcli.App(
            name="test", version="1.0.0", help="test app",
            flags=[
                strictcli.Flag("meta", type=dict[str, str], help="metadata"),
            ],
        )

        @app.command("cmd", help="a command")
        def cmd(ctx, meta):
            print(f"meta={meta!r}")

        r = app.test(["--meta", "env=prod", "cmd"])
        assert r.exit_code == 0
        assert "'env': 'prod'" in r.stdout


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestCompoundEdgeCases:
    """Edge cases and interactions."""

    def test_list_and_dict_on_same_command(self):
        """A command can have both list[T] and dict[str, T] flags."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="ids")
        @strictcli.flag("meta", type=dict[str, str], help="metadata")
        def cmd(ctx, ids, meta):
            print(f"ids={ids!r} meta={meta!r}")

        r = app.test([
            "cmd",
            "--ids", "1", "--ids", "2",
            "--meta", "env=prod",
        ])
        assert r.exit_code == 0
        assert "ids=[1, 2]" in r.stdout
        assert "'env': 'prod'" in r.stdout

    def test_dict_with_validate(self):
        """Dict flag with custom validate receives the full dict."""
        def check_headers(d):
            if "Host" not in d:
                raise ValueError("Host header is required")

        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag(
            "headers", type=dict[str, str], help="headers",
            validate=check_headers,
        )
        def cmd(ctx, headers):
            print(f"ok")

        r = app.test(["cmd", "--headers", "Accept=json"])
        assert r.exit_code == 1
        assert "Host header is required" in r.stderr

        r2 = app.test(["cmd", "--headers", "Host=example.com"])
        assert r2.exit_code == 0

    def test_dict_json_with_equals_in_flag_form(self):
        """--flag='{json}' works (JSON starts at the right of first =)."""
        app = strictcli.App(name="test", version="1.0.0", help="test app")

        @app.command("cmd", help="a command")
        @strictcli.flag("headers", type=dict[str, str], help="headers")
        def cmd(ctx, headers):
            print(f"count={len(headers)}")

        r = app.test(["cmd", "--headers={'a': 'b'}".replace("'", '"')])
        assert r.exit_code == 0
        assert "count=1" in r.stdout
