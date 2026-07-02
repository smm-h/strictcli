"""Registration-time validation of arg defaults.

str args must reject non-string defaults, and list (variadic) args must
validate their default as a list with correctly-typed elements.
"""

import pytest

import strictcli


def test_arg_str_default_type_validated():
    """type=str requires a str default."""
    with pytest.raises(ValueError, match="type=str requires a str default"):
        strictcli.Arg(name="x", help="a value", required=False, default=42)


def test_arg_str_default_rejects_bool():
    """type=str rejects a bool default."""
    with pytest.raises(ValueError, match="type=str requires a str default"):
        strictcli.Arg(name="x", help="a value", required=False, default=True)


def test_arg_list_default_must_be_list():
    """A list arg default must be a list."""
    with pytest.raises(ValueError, match="list arg default must be a list"):
        strictcli.Arg(
            name="items", help="the items", type=list[str],
            variadic=True, required=False, default="nope",
        )


def test_arg_list_default_empty_rejected():
    """An explicit empty list default is redundant and rejected."""
    with pytest.raises(
        ValueError,
        match="explicit empty default is redundant for list args",
    ):
        strictcli.Arg(
            name="items", help="the items", type=list[str],
            variadic=True, required=False, default=[],
        )


def test_arg_list_default_element_type_validated():
    """Element types of a list arg default are validated."""
    with pytest.raises(ValueError, match="default element 1 is not of type str"):
        strictcli.Arg(
            name="items", help="the items", type=list[str],
            variadic=True, required=False, default=["a", 2],
        )


def test_arg_list_default_int_element_type_validated():
    """Element types of an int list arg default are validated."""
    with pytest.raises(ValueError, match="default element 0 is not of type int"):
        strictcli.Arg(
            name="nums", help="the numbers", type=list[int],
            variadic=True, required=False, default=["1"],
        )


def test_arg_list_default_valid_str():
    """A well-typed list default is accepted."""
    a = strictcli.Arg(
        name="items", help="the items", type=list[str],
        variadic=True, required=False, default=["a", "b"],
    )
    assert a.default == ["a", "b"]


def test_arg_list_default_float_coerces_int():
    """Int elements in a float list default are coerced to float."""
    a = strictcli.Arg(
        name="ratios", help="the ratios", type=list[float],
        variadic=True, required=False, default=[1, 2.5],
    )
    assert a.default == [1.0, 2.5]
    assert isinstance(a.default[0], float)
