"""Tests for shared utility functions."""

import strictcli


# --- _split_escaped ---


class TestSplitEscaped:
    def test_basic_split(self):
        assert strictcli._split_escaped("a,b,c", ",") == ["a", "b", "c"]

    def test_escaped_sep(self):
        assert strictcli._split_escaped("a\\,b,c", ",") == ["a,b", "c"]

    def test_empty_string(self):
        assert strictcli._split_escaped("", ",") == [""]

    def test_sep_only(self):
        assert strictcli._split_escaped(",", ",") == ["", ""]

    def test_single_value(self):
        assert strictcli._split_escaped("a", ",") == ["a"]

    def test_escaped_backslash(self):
        assert strictcli._split_escaped("a\\\\", ",") == ["a\\\\"]

    def test_escaped_backslash_then_sep(self):
        assert strictcli._split_escaped("a\\\\,b", ",") == ["a\\\\", "b"]

    def test_trailing_backslash(self):
        assert strictcli._split_escaped("a\\", ",") == ["a\\\\"]

    def test_multiple_escaped_seps(self):
        assert strictcli._split_escaped("a\\,b\\,c", ",") == ["a,b,c"]

    def test_different_separator(self):
        assert strictcli._split_escaped("a:b:c", ":") == ["a", "b", "c"]

    def test_escaped_different_separator(self):
        assert strictcli._split_escaped("a\\:b:c", ":") == ["a:b", "c"]


# --- _find_duplicate ---


class TestFindDuplicate:
    def test_no_duplicates(self):
        assert strictcli._find_duplicate([1, 2, 3]) is None

    def test_has_duplicate(self):
        assert strictcli._find_duplicate([1, 2, 2, 3]) == 2

    def test_first_duplicate_returned(self):
        assert strictcli._find_duplicate([1, 2, 3, 2, 1]) == 2

    def test_empty_list(self):
        assert strictcli._find_duplicate([]) is None

    def test_single_element(self):
        assert strictcli._find_duplicate([1]) is None

    def test_string_duplicates(self):
        assert strictcli._find_duplicate(["a", "b", "a"]) == "a"

    def test_all_same(self):
        assert strictcli._find_duplicate([5, 5, 5]) == 5


# --- _format_value_for_error ---


class TestFormatValueForError:
    def test_string(self):
        assert strictcli._format_value_for_error("hello") == "hello"

    def test_int(self):
        assert strictcli._format_value_for_error(3) == "3"

    def test_float_whole(self):
        assert strictcli._format_value_for_error(3.0) == "3.0"

    def test_float_fractional(self):
        assert strictcli._format_value_for_error(3.5) == "3.5"

    def test_bool_true(self):
        assert strictcli._format_value_for_error(True) == "true"

    def test_bool_false(self):
        assert strictcli._format_value_for_error(False) == "false"

    def test_negative_int(self):
        assert strictcli._format_value_for_error(-7) == "-7"

    def test_negative_float(self):
        assert strictcli._format_value_for_error(-3.14) == "-3.14"

    def test_zero_float(self):
        assert strictcli._format_value_for_error(0.0) == "0.0"


# --- _config_typename ---


class TestConfigTypename:
    def test_str(self):
        assert strictcli._config_typename("hello") == "str"

    def test_bool(self):
        assert strictcli._config_typename(True) == "bool"

    def test_int(self):
        assert strictcli._config_typename(42) == "int"

    def test_float(self):
        assert strictcli._config_typename(3.14) == "float"

    def test_none(self):
        assert strictcli._config_typename(None) == "null"

    def test_list(self):
        assert strictcli._config_typename([1, 2, 3]) == "array"

    def test_bool_before_int(self):
        """bool is a subclass of int in Python; must check bool first."""
        assert strictcli._config_typename(False) == "bool"
