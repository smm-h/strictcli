#!/usr/bin/env python3
"""Unit tests for the N-way target registry in run.py.

These exercise the target-agnostic parity machinery WITHOUT shelling out to the
real python/go targets: a fake in-process target is registered into the registry
and `_run_case` is stubbed to return synthetic outcomes. This proves that adding
a target is purely a registry operation and that N-way odd-one-out reporting
works for more than two targets.

Runnable under pytest (auto-discovered) or standalone (`python3 test_run_registry.py`).
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Build a synthetic CompletedProcess for comparison tests."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


@contextmanager
def _fake_target(name: str):
    """Register a throwaway target into the registry, then remove it."""
    def _prepare(app_def, case_argv):  # pragma: no cover - never called (stubbed)
        raise AssertionError("fake target prepare should be stubbed via _run_case")

    def _write(d, app_name):  # pragma: no cover
        pass

    run._register_target(run.Target(name, _prepare, _write))
    try:
        yield
    finally:
        run.TARGETS.pop(name, None)


@contextmanager
def _stub_run_case(outcomes: dict[str, tuple[bool, list, object]]):
    """Stub run._run_case to return per-target synthetic outcomes.

    `outcomes` maps target name -> (ok, errors, CompletedProcess|None).
    """
    original = run._run_case

    def _fake(case, target):
        return outcomes[target]

    run._run_case = _fake
    try:
        yield
    finally:
        run._run_case = original


# --- Registry basics ---------------------------------------------------------


def test_default_registry_has_python_and_go():
    assert set(run.TARGETS) >= {"python", "go"}
    assert isinstance(run.TARGETS["python"], run.Target)
    assert isinstance(run.TARGETS["go"], run.Target)


def test_register_and_unregister_target():
    assert "ts" not in run.TARGETS
    with _fake_target("ts"):
        assert "ts" in run.TARGETS
        assert list(run.TARGETS)[-1] == "ts"  # insertion order preserved
    assert "ts" not in run.TARGETS


# --- N-way output comparison -------------------------------------------------


def test_compare_all_agree_no_warnings():
    results = {
        "python": _proc(stdout="hello"),
        "go": _proc(stdout="hello"),
        "ts": _proc(stdout="hello"),
    }
    assert run._compare_outputs(results) == []


def test_compare_three_way_odd_one_out():
    # python & go agree; ts is the odd one out on stdout.
    results = {
        "python": _proc(stdout="hello"),
        "go": _proc(stdout="hello"),
        "ts": _proc(stdout="HELLO"),
    }
    warnings = run._compare_outputs(results)
    text = "\n".join(warnings)
    assert "stdout divergence (odd one out: ts):" in text
    assert "go,python: 'hello'" in text
    assert "ts: 'HELLO'" in text
    # stderr all empty -> no stderr divergence line
    assert "stderr divergence" not in text


def test_compare_two_way_no_majority_reports_both_labeled():
    results = {
        "python": _proc(stderr="py-error"),
        "go": _proc(stderr="go-error"),
    }
    warnings = run._compare_outputs(results)
    text = "\n".join(warnings)
    # No unique majority with two distinct targets -> no odd-one-out marker.
    assert "stderr divergence:" in text
    assert "odd one out" not in text
    assert "go: 'go-error'" in text
    assert "python: 'py-error'" in text


def test_compare_fewer_than_two_present_is_noop():
    assert run._compare_outputs({"python": _proc(stdout="x"), "go": None}) == []


# --- Acknowledged divergence --------------------------------------------------


def _ack(streams: dict[str, list[str]]):
    return {"reason": "test reason", "streams": streams}


def test_acknowledged_target_excluded_from_stream_comparison():
    # go's stderr genuinely differs but is acknowledged; python & ts still match.
    results = {
        "python": _proc(stderr="shared error"),
        "go": _proc(stderr="go-specific error"),
        "ts": _proc(stderr="shared error"),
    }
    assert run._compare_outputs(results, _ack({"stderr": ["go"]})) == []


def test_acknowledgment_is_per_stream_not_global():
    # go acknowledged on stderr only; its stdout divergence still warns.
    results = {
        "python": _proc(stdout="hello", stderr="shared"),
        "go": _proc(stdout="HELLO", stderr="go-specific"),
        "ts": _proc(stdout="hello", stderr="shared"),
    }
    warnings = run._compare_outputs(results, _ack({"stderr": ["go"]}))
    text = "\n".join(warnings)
    assert "stdout divergence (odd one out: go):" in text
    assert "stderr" not in text


def test_unacknowledged_targets_still_compared():
    # go acknowledged, but python & ts diverge from each other -> warn.
    results = {
        "python": _proc(stderr="py error"),
        "go": _proc(stderr="go error"),
        "ts": _proc(stderr="ts error"),
    }
    warnings = run._compare_outputs(results, _ack({"stderr": ["go"]}))
    text = "\n".join(warnings)
    assert "stderr divergence" in text
    assert "py error" in text and "ts error" in text
    assert "go error" not in text


def test_stale_acknowledgment_is_reported():
    # Acknowledged target's output matches every other target -> stale.
    results = {
        "python": _proc(stderr="same"),
        "go": _proc(stderr="same"),
        "ts": _proc(stderr="same"),
    }
    warnings = run._compare_outputs(results, _ack({"stderr": ["go"]}))
    text = "\n".join(warnings)
    assert "stale acknowledged divergence" in text
    assert "'go'" in text


def test_validate_acknowledgment_rejects_inapplicable_target():
    case = {
        "name": "x",
        "targets": ["python", "go"],
        "acknowledged_divergence": _ack({"stderr": ["ts"]}),
    }
    errors = run._validate_acknowledged_divergence(case, ["python", "go"])
    assert len(errors) == 1
    assert "not applicable" in errors[0]


def test_validate_acknowledgment_requires_a_baseline_target():
    case = {
        "name": "x",
        "acknowledged_divergence": _ack({"stderr": ["python", "go"]}),
    }
    errors = run._validate_acknowledged_divergence(case, ["python", "go"])
    assert len(errors) == 1
    assert "baseline" in errors[0]


def test_validate_acknowledgment_absent_is_noop():
    assert run._validate_acknowledged_divergence({"name": "x"}, ["python", "go"]) == []


# --- Target scoping ----------------------------------------------------------


def test_applicable_targets_intersection():
    names = ["python", "go", "ts"]
    assert run._applicable_targets({}, names) == ["python", "go", "ts"]
    assert run._applicable_targets({"targets": ["python", "go"]}, names) == [
        "python",
        "go",
    ]
    assert run._applicable_targets({"targets": ["python"]}, names) == ["python"]


# --- N-way parity mode with a fake registered target -------------------------


def test_parity_mode_reports_divergence_with_fake_target():
    case = {"name": "synthetic", "targets": ["python", "go", "ts"]}
    cases = [("fake.json", case)]
    outcomes = {
        "python": (True, [], _proc(stdout="ok")),
        "go": (True, [], _proc(stdout="ok")),
        "ts": (True, [], _proc(stdout="DIFFERENT")),  # passes own assertions, diverges
    }
    with _fake_target("ts"), _stub_run_case(outcomes):
        report = run._run_parity_mode(cases, ["python", "go", "ts"], verbose=False)

    assert report.passed == 1
    assert report.parity_failures == 0
    assert report.output_divergences == 1
    label, warnings = report.divergence_details[0]
    assert "synthetic" in label
    assert "odd one out: ts" in "\n".join(warnings)


def test_parity_mode_flags_odd_target_failure_as_parity_break():
    case = {"name": "synthetic", "targets": ["python", "go", "ts"]}
    cases = [("fake.json", case)]
    outcomes = {
        "python": (True, [], _proc(stdout="ok")),
        "go": (True, [], _proc(stdout="ok")),
        "ts": (False, ["  boom"], _proc(stdout="ok", returncode=1)),
    }
    with _fake_target("ts"), _stub_run_case(outcomes):
        report = run._run_parity_mode(cases, ["python", "go", "ts"], verbose=False)

    assert report.parity_failures == 1
    assert report.passed == 0
    label, detail = report.parity_failure_details[0]
    assert "ts=FAIL" in detail
    assert "python=PASS" in detail
    assert report.exit_code == 1


def test_parity_mode_all_fail_is_consistent_not_parity_break():
    case = {"name": "synthetic", "targets": ["python", "go", "ts"]}
    cases = [("fake.json", case)]
    outcomes = {
        "python": (False, ["x"], _proc(returncode=1)),
        "go": (False, ["x"], _proc(returncode=1)),
        "ts": (False, ["x"], _proc(returncode=1)),
    }
    with _fake_target("ts"), _stub_run_case(outcomes):
        report = run._run_parity_mode(cases, ["python", "go", "ts"], verbose=False)

    assert report.consistent_failures == 1
    assert report.parity_failures == 0
    assert report.exit_code == 0


def test_parity_mode_skips_single_target_case():
    # A case scoped to one registered target has nothing to compare -> skipped.
    case = {"name": "py-only", "targets": ["python"]}
    cases = [("fake.json", case)]
    outcomes = {"python": (True, [], _proc(stdout="ok"))}
    with _stub_run_case(outcomes):
        report = run._run_parity_mode(cases, ["python", "go"], verbose=False)

    assert report.total == 0
    assert report.exit_code == 0


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
