# Integer overflow: Python arbitrary precision vs Go fixed-size int

## Problem

Python accepts arbitrarily large integers for int-typed flags (e.g., `99999999999999999999`). Go rejects them because `strconv.Atoi` fails when the value exceeds the platform's `int` range (typically int64: -2^63 to 2^63-1).

## Impact

Found by differential fuzzing (`conformance/fuzz.py`). Any user passing very large integers gets different behavior between implementations.

## Options

1. **Python enforces int64 range.** After parsing with `int()`, check that the value fits in `[-2^63, 2^63-1]`. Raise a parse error if not. Simple, makes both implementations agree. Trade-off: Python users lose the ability to use large ints.
2. **Go uses big.Int.** Overkill for a CLI framework.
3. **Document as a known language difference.** Both implementations correctly parse what their language supports. Add a note in docs. Trade-off: behavioral divergence remains.

Option 1 is the most correct for cross-language conformance.

## Affected files

- `python/strictcli/__init__.py` (`_strict_int` helper, int parsing in `_parse_global_flags` and `_parse_command`)

## Effort

Low. Add a range check after `int()` in the `_strict_int` helper.
