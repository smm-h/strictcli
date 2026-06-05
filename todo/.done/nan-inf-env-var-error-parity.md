# NaN/Inf error messages drop env var suffix in Python

## Problem

When a float flag receives NaN or Inf via an environment variable, Go includes the env var source in the error message but Python does not:

- Go: `--rate: NaN is not allowed (from env var 'MYAPP_RATE')`
- Python: `--rate: NaN is not allowed`

For all other float parse errors via env vars (e.g., `MYAPP_RATE=abc`), both produce matching messages with the env var suffix. The divergence is specific to NaN/Inf.

## Root cause

In Python's `_float_parse_error`, when the message is "NaN is not allowed" or "Inf is not allowed", the function returns the message without appending the env var suffix. Go's error path appends the env suffix uniformly to all float parse errors.

## Conformance gap

The conformance tests in `conformance/cases/float_type.json` only test NaN/Inf via CLI flags, not via environment variables. The env-var NaN/Inf path is untested in the cross-language conformance suite.

The `check_error_parity.py` file has a known-divergence entry for the general env var error wrapper pattern, but the NaN/Inf case is a specific instance where Python doesn't just format differently — it drops the env var information entirely.

## What's needed

- Fix the Python `_float_parse_error` function to include the env var suffix for NaN/Inf errors
- Add conformance test cases for NaN/Inf via environment variables
- Verify the fix makes both languages produce identical output
