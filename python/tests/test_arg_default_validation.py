"""Registration-time validation of arg defaults.

str args must reject non-string defaults, and a variadic arg must refuse a
default declaration entirely (contract §23.3).
"""

import pytest

import strictcli


def test_arg_str_default_type_validated():
    """type=str requires a str default."""
    with pytest.raises(ValueError, match="type=str requires a str default"):
        strictcli.Arg(name="x", help="a value", default=42)


def test_arg_str_default_rejects_bool():
    """type=str rejects a bool default."""
    with pytest.raises(ValueError, match="type=str requires a str default"):
        strictcli.Arg(name="x", help="a value", default=True)


def test_variadic_list_arg_cannot_declare_a_default():
    """A variadic arg always delivers a list, so a default is refused (§23.3)."""
    with pytest.raises(ValueError) as exc:
        strictcli.Arg(
            name="items", help="the items", type=list[str],
            variadic=True, default=["a", "b"],
        )
    assert str(exc.value) == (
        'Arg "items": a variadic arg cannot declare default=: it always '
        'delivers a list, so declare presence="required" for at least one '
        'value or presence="optional" for possibly none'
    )


def test_variadic_scalar_arg_cannot_declare_a_default():
    """The same refusal on a plain variadic arg, whatever the default's shape."""
    with pytest.raises(ValueError) as exc:
        strictcli.Arg(name="items", help="the items", variadic=True, default="a")
    assert str(exc.value) == (
        'Arg "items": a variadic arg cannot declare default=: it always '
        'delivers a list, so declare presence="required" for at least one '
        'value or presence="optional" for possibly none'
    )


def test_variadic_list_arg_declares_required_or_optional():
    """The two legal declarations for a variadic arg."""
    req = strictcli.Arg(
        name="items", help="the items", type=list[str],
        variadic=True, presence="required",
    )
    assert req.presence == "required"
    opt = strictcli.Arg(
        name="items", help="the items", type=list[str],
        variadic=True, presence="optional",
    )
    assert opt.presence == "optional"
