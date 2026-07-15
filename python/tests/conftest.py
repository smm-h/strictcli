"""Shared test helpers for the check-outcome tests.

The minter helpers exercise the real reporter minting path (the only way to
obtain a ``_CheckOutcome``) so behavioral tests can express expected outcomes
concisely. ``fail_outcome``/``warn_outcome`` mint one problem per extra arg (or
a single problem from the message when none are given).
"""

from strictcli import ErrorReporter, _CheckOutcome


def pass_outcome(message: str) -> _CheckOutcome:
    return ErrorReporter().passed(message)


def skip_outcome(reason: str) -> _CheckOutcome:
    return ErrorReporter().skipped(reason)


def fail_outcome(message: str, *problems: str) -> _CheckOutcome:
    r = ErrorReporter()
    if not problems:
        r.error(message)
    for p in problems:
        r.error(p)
    return r.found(message)


def warn_outcome(message: str, *problems: str) -> _CheckOutcome:
    r = ErrorReporter()
    if not problems:
        r.warn(message)
    for p in problems:
        r.warn(p)
    return r.found(message)
