"""Tests for the strictcli canonical float format (SCF).

The canon:
1. Shortest decimal string that round-trips to the identical IEEE-754 double.
2. Integer-valued floats in fixed notation always carry a trailing ``.0``.
3. ``-0.0`` is preserved as ``-0.0``.
4. Fixed notation for ``|x|`` in ``[1e-6, 1e21)``; scientific outside. Zero is
   always fixed.
5. Scientific: lowercase ``e``, explicit sign, no zero-padding (``1e+21``,
   ``1e-7``, ``1.5e+300``).
6. The ``.0`` rule lives only in the fixed branch, never scientific.
"""

import math
import struct

import pytest

import strictcli

# (value, canonical) — the full battery from the SCF spec.
BATTERY = [
    (1.0, "1.0"),
    (-1.0, "-1.0"),
    (0.5, "0.5"),
    (-0.0, "-0.0"),
    (0.0, "0.0"),
    (100.0, "100.0"),
    (1e15, "1000000000000000.0"),
    (1e16, "10000000000000000.0"),
    (1e20, "100000000000000000000.0"),
    (1e21, "1e+21"),
    (1e-4, "0.0001"),
    (1e-5, "0.00001"),
    (1e-7, "1e-7"),
    (0.1, "0.1"),
    (9007199254740992.0, "9007199254740992.0"),  # 2**53
    (1.5e300, "1.5e+300"),
]


@pytest.mark.parametrize("value,expected", BATTERY)
def test_battery(value, expected):
    assert strictcli._format_float_canonical(value) == expected


def test_negative_zero_preserved():
    assert strictcli._format_float_canonical(-0.0) == "-0.0"
    assert strictcli._format_float_canonical(0.0) == "0.0"


def test_fixed_boundaries():
    # 1e-6 is the inclusive lower edge of the fixed range.
    assert strictcli._format_float_canonical(1e-6) == "0.000001"
    # Just under 1e-6 goes scientific.
    assert strictcli._format_float_canonical(9e-7) == "9e-7"
    # 1e21 is the exclusive upper edge -> scientific.
    assert strictcli._format_float_canonical(1e21) == "1e+21"
    # Just under 1e21 stays fixed with the trailing .0.
    assert strictcli._format_float_canonical(1e20) == "100000000000000000000.0"


def test_scientific_has_no_zero_padding_and_explicit_sign():
    assert strictcli._format_float_canonical(1e-7) == "1e-7"
    assert strictcli._format_float_canonical(1e21) == "1e+21"
    assert strictcli._format_float_canonical(-1.5e300) == "-1.5e+300"
    assert strictcli._format_float_canonical(1e100) == "1e+100"


def test_no_dot_zero_in_scientific_branch():
    # Rule 6: the .0 suffix is a fixed-branch-only rule.
    assert "e" in strictcli._format_float_canonical(1e21)
    assert strictcli._format_float_canonical(1e21) == "1e+21"


def test_format_value_for_error_uses_canonical():
    # An integer-valued float above the fixed range still renders fixed with .0.
    assert strictcli._format_value_for_error(1e16) == "10000000000000000.0"
    assert strictcli._format_value_for_error(1e-7) == "1e-7"
    # Non-float behavior is unchanged.
    assert strictcli._format_value_for_error(3) == "3"
    assert strictcli._format_value_for_error("x") == "x"
    assert strictcli._format_value_for_error(True) == "true"


def _bits(x: float) -> bytes:
    return struct.pack("<d", x)


def test_roundtrip_property():
    """float(format(x)) must reproduce the identical double for finite x.

    Draws random 64-bit patterns (covering subnormals, tiny/huge magnitudes,
    and negative zero) and asserts bit-for-bit round-trip identity.
    """
    import random

    rng = random.Random(0xC0FFEE)
    checked = 0
    for _ in range(100_000):
        bits = rng.getrandbits(64)
        x = struct.unpack("<d", struct.pack("<Q", bits))[0]
        if math.isnan(x) or math.isinf(x):
            continue
        s = strictcli._format_float_canonical(x)
        y = float(s)
        assert _bits(x) == _bits(y), f"round-trip failed for {x!r}: {s!r}"
        checked += 1
    assert checked > 50_000  # sanity: we actually exercised many finite doubles


def test_roundtrip_targeted_extremes():
    """Explicit subnormal and extreme-magnitude doubles round-trip identically."""
    extremes = [
        5e-324,            # smallest positive subnormal
        2.2250738585072014e-308,  # smallest positive normal
        1.7976931348623157e308,   # largest finite
        -5e-324,
        -1.7976931348623157e308,
        1e-300,
        1e300,
        -0.0,
    ]
    for x in extremes:
        s = strictcli._format_float_canonical(x)
        assert _bits(float(s)) == _bits(x), f"round-trip failed for {x!r}: {s!r}"


def test_toml_config_set_writes_canonical_float(tmp_path):
    """config set writes floats to TOML in canonical form.

    The conformance harness only observes stdout/stderr, so the TOML write
    path is pinned here: set a divergent float, then read the .toml file and
    assert the canonical spelling was written (not Python's ``str`` form).
    """
    config_file = tmp_path / "config.toml"

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_format="toml",
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    @strictcli.flag("big", type=float, help="a big rate", default=0.0)
    @strictcli.flag("tiny", type=float, help="a tiny rate", default=0.0)
    def run(ctx, big, tiny):
        pass

    r = app.test(["config", "set", "big", "1e16"])
    assert r.exit_code == 0
    r = app.test(["config", "set", "tiny", "1e-7"])
    assert r.exit_code == 0

    text = config_file.read_text()
    assert "big = 10000000000000000.0" in text
    assert "tiny = 1e-7" in text
    # The non-canonical Python str() spellings must not appear.
    assert "1e+16" not in text
    assert "1e-07" not in text


def test_toml_scalar_float_is_canonical():
    assert strictcli._toml_format_scalar(1e16) == "10000000000000000.0"
    assert strictcli._toml_format_scalar(1e-7) == "1e-7"
    # Ints are unaffected.
    assert strictcli._toml_format_scalar(42) == "42"


def test_config_value_float_is_canonical():
    assert strictcli._format_config_value(1e16) == "10000000000000000.0"
    assert strictcli._format_config_value(1e-7) == "1e-7"
    assert strictcli._format_config_value(3.14) == "3.14"


def test_config_show_plain_renders_canonical(tmp_path):
    """config show --plain surfaces config floats in canonical form."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("big = 10000000000000000.0\ntiny = 0.0000001\n")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_format="toml",
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    @strictcli.flag("big", type=float, help="a big rate", default=0.0)
    @strictcli.flag("tiny", type=float, help="a tiny rate", default=0.0)
    def run(ctx, big, tiny):
        pass

    r = app.test(["config", "show", "--plain"])
    assert r.exit_code == 0
    assert "big = 10000000000000000.0" in r.stdout
    assert "tiny = 1e-7" in r.stdout
    assert "1e+16" not in r.stdout


def test_help_float_default_is_canonical():
    """Help text renders float defaults in canonical form."""
    app = strictcli.App(name="testapp", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("big", type=float, help="a big rate", default=1e16)
    @strictcli.flag("tiny", type=float, help="a tiny rate", default=1e-7)
    def cmd(ctx, big, tiny):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "default: 10000000000000000.0" in r.stdout
    assert "default: 1e-7" in r.stdout
    assert "default: 1e+16" not in r.stdout


def test_choices_error_echoes_canonical():
    """An invalid float choice echoes the attempted value canonically."""
    app = strictcli.App(name="testapp", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="the rate", choices=[1.5, 2.5])
    def cmd(ctx, rate):
        pass

    r = app.test(["cmd", "--rate", "1e16"])
    assert r.exit_code == 1
    assert "invalid value '10000000000000000.0'" in r.stderr
    assert "1e+16" not in r.stderr
