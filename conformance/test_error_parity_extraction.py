#!/usr/bin/env python3
"""Unit tests for check_error_parity.py's Python extraction surface.

The extractor decides what lands in the cross-language message catalog, so a
template it cannot see silently drops out of parity checking -- the one failure
mode that produces a false PASS.  These tests pin the two shapes it recognizes
(raised templates and `_msg_*` template functions), the truncation marker that
replaces the old trailing-space heuristic, and the effects-regime templates that
must never fall out again.

Runnable under pytest (auto-discovered) or standalone
(`python3 test_error_parity_extraction.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_error_parity as cep


def _py_sigs() -> dict[str, set[str]]:
    """{signature: {category, ...}} extracted from the real Python source."""
    sigs: dict[str, set[str]] = {}
    for category, raw in cep.extract_python_errors(cep.PY_SOURCE.read_text()):
        sigs.setdefault(cep.normalize_python(raw), set()).add(category)
    return sigs


# ---------------------------------------------------------------------------
# Truncation marking (replaces the old trailing-space heuristic)
# ---------------------------------------------------------------------------

def test_literal_run_cut_short_by_an_expression_is_truncated():
    text, truncated = cep._extract_string_literals(
        'f"commands cannot have " + ", ".join(parts)'
    )
    assert text == "commands cannot have "
    assert truncated is True
    assert cep.normalize_python(cep._truncation_marker(text, truncated)) == (
        "commands cannot have *"
    )


def test_complete_literal_ending_in_a_space_is_not_truncated():
    """The confirm prompt ends with a space BY DESIGN -- no phantom * for it."""
    text, truncated = cep._extract_string_literals(
        "f\"about to run mutating command '{name}'. Proceed? [y/N] \""
    )
    assert truncated is False
    assert cep.normalize_python(cep._truncation_marker(text, truncated)) == (
        "about to run mutating command *. Proceed? [y/N] "
    )


def test_confirm_prompt_signature_matches_its_go_counterpart():
    """The two normalizers must agree, or parity fails on a spelling artifact."""
    py_text, py_truncated = cep._extract_string_literals(
        "f\"about to run mutating command '{name}'. Proceed? [y/N] \""
    )
    py_sig = cep.normalize_python(cep._truncation_marker(py_text, py_truncated))
    go_sig = cep.normalize_go(
        "about to run mutating command '%s'. Proceed? [y/N] "
    )
    assert py_sig == go_sig


def test_literal_followed_by_another_argument_is_not_truncated():
    text, truncated = cep._extract_string_literals('"aborted", self._log')
    assert text == "aborted"
    assert truncated is False


# ---------------------------------------------------------------------------
# `_msg_*` template functions
# ---------------------------------------------------------------------------

_FAKE_SOURCE = '''\
def _msg_confirm_declined() -> str:
    return "aborted"


def _msg_dry_run_truncated(step: int, cmd: str) -> str:
    return (
        f"ends at step {step}: {cmd} branched "
        f"on an unsettled value"
    )


def _not_a_template() -> str:
    return "invisible"
'''


def test_msg_functions_are_extracted():
    found = dict(
        (raw, category)
        for category, raw in cep.extract_python_message_templates(_FAKE_SOURCE)
    )
    assert "aborted" in found
    assert (
        "ends at step {step}: {cmd} branched on an unsettled value" in found
    )


def test_non_msg_functions_are_not_extracted():
    raws = [raw for _, raw in cep.extract_python_message_templates(_FAKE_SOURCE)]
    assert "invisible" not in raws


def test_msg_function_body_is_bounded_at_the_next_top_level_def():
    """Without the bound, the return literal absorbs the rest of the file."""
    raws = [raw for _, raw in cep.extract_python_message_templates(_FAKE_SOURCE)]
    assert raws[0] == "aborted"  # not "aborted" + everything after it


def test_msg_function_category_split_matches_the_declared_set():
    for category, raw in cep.extract_python_message_templates(_FAKE_SOURCE):
        if raw == "aborted":
            assert category == "parse"  # _msg_confirm_declined
        elif raw.startswith("ends at step"):
            assert category == "parse"  # _msg_dry_run_truncated
    assert "_msg_confirm_prompt" in cep._PY_PARSE_TIME_MSG_FUNCS
    assert "_msg_dry_run_truncated" in cep._PY_PARSE_TIME_MSG_FUNCS


# ---------------------------------------------------------------------------
# Raised templates
# ---------------------------------------------------------------------------

def test_effect_failed_raises_are_extracted_as_parse_time():
    source = 'def f():\n    raise EffectFailed(f"boom {x}")\n'
    assert cep.extract_python_errors(source) == [("parse", "boom {x}")]


def test_value_error_raises_stay_registration_time():
    source = 'def f():\n    raise ValueError(f"bad {x}")\n'
    assert cep.extract_python_errors(source) == [("registration", "bad {x}")]


def test_type_error_raises_are_not_scanned():
    """SIGNATURE_STATUS rationales depend on this; a `_msg_*` is the way in."""
    source = 'def f():\n    raise TypeError(f"nope {x}")\n'
    assert cep.extract_python_errors(source) == []
    assert "TypeError" not in cep._PY_RAISED_TEMPLATE_TYPES


# ---------------------------------------------------------------------------
# The effects-regime templates, against the real source
# ---------------------------------------------------------------------------

_EFFECTS_TEMPLATES = {
    # Confirm protocol (effects contract §12.6)
    "about to run mutating command *. Proceed? [y/N] ": "parse",
    "error: stdin is not interactive; pass --yes to confirm": "parse",
    "aborted": "parse",
    # Truncation (§12.5)
    "error: dry-run preview ends at step *: * branched on unsettled value * "
    "— cannot preview past this point": "parse",
    # Effect failure (§12.8)
    "command *: effects.* failed: * exited *": "parse",
    "command *: effects.http failed: * * returned *": "parse",
    "command *: effects.* produced output that is not valid UTF-8": "parse",
    # Effect parameter type guards (TypeError-carried, so `_msg_*`-visible)
    "command *: effects.* argv must be a sequence of strings, not *":
        "registration",
    "command *: effects.* parameter * must be a string, a path, or a forwarded "
    "effect result; got *": "registration",
    "command *: effects.chmod parameter 'mode' must be an int, got *":
        "registration",
    "command *: effects.http parameter 'method' must be a string, got *":
        "registration",
    # Handle availability
    "ctx.effects is unavailable: this Context was constructed outside a "
    "command dispatch": "registration",
}


def test_every_effects_template_is_extracted_from_the_real_source():
    sigs = _py_sigs()
    missing = [s for s in _EFFECTS_TEMPLATES if s not in sigs]
    assert not missing, f"invisible to the parity extractor: {missing}"


def test_every_effects_template_lands_in_the_expected_category():
    sigs = _py_sigs()
    wrong = {
        s: sorted(sigs[s])
        for s, want in _EFFECTS_TEMPLATES.items()
        if s in sigs and want not in sigs[s]
    }
    assert not wrong, f"category drift: {wrong}"


def test_one_run_failure_template_covers_run_and_spawn():
    """§12.8 declares one template with `method` as a parameter, not two."""
    sigs = _py_sigs()
    assert "command *: effects.spawn failed: * exited *" not in sigs
    assert "command *: effects.* failed: * exited *" in sigs


if __name__ == "__main__":
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {_name}: {exc}")
    sys.exit(1 if failures else 0)
