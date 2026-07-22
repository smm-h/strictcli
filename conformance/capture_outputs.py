#!/usr/bin/env python3
"""Capture exact outputs from conformance test cases.

Runs each test case against a target implementation, captures stdout/stderr,
and optionally updates the JSON test files to use exact matching where appropriate.

Usage:
    python conformance/capture_outputs.py --target python
    python conformance/capture_outputs.py --target python --update
    python conformance/capture_outputs.py --target python --compare-with go
    python conformance/capture_outputs.py --target typescript --compare-with go
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure we can import sibling modules
CONFORMANCE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CONFORMANCE_DIR))

from run import (
    _generate_python_script,
    _normalize,
    _run_case,
    CASES_DIR,
    TARGETS,
)


def _capture_all(target: str) -> list[dict]:
    """Run every test case and capture outputs.

    Returns a list of dicts with keys:
        file, name, exit_code, stdout, stderr, expected_exit_code
    """
    results = []
    for json_file in sorted(CASES_DIR.glob("*.json")):
        with open(json_file) as f:
            cases = json.load(f)
        for case in cases:
            _ok, _errors, raw = _run_case(case, target)
            entry = {
                "file": json_file.name,
                "name": case["name"],
                "expected_exit_code": case["expect"]["exit_code"],
                "actual_exit_code": raw.returncode if raw else None,
                "stdout": _normalize(raw.stdout) if raw else "",
                "stderr": _normalize(raw.stderr) if raw else "",
                "expect": case["expect"],
            }
            results.append(entry)
    return results


def _should_convert_stdout(expect: dict, actual_stdout: str) -> bool:
    """Decide whether to convert stdout_contains to stdout_equals."""
    if "stdout_equals" in expect:
        return False  # already exact
    if "stdout_contains" not in expect:
        return False

    contains = expect["stdout_contains"]
    normalized_actual = _normalize(actual_stdout)

    if isinstance(contains, str):
        # Convert if the contains value IS the complete output
        return normalized_actual == contains
    elif isinstance(contains, list):
        # Convert if all items together make up the complete output
        # (only when there's a single item that equals the full output)
        if len(contains) == 1 and normalized_actual == contains[0]:
            return True
        # For multi-item lists, the contains values are fragments;
        # convert only if all the fragments together equal the output
        # (very unlikely, so we skip this case and do full capture instead)
        return False
    return False


def _should_convert_stderr(expect: dict, actual_stderr: str) -> bool:
    """Decide whether to convert stderr_contains to stderr_equals."""
    if "stderr_equals" in expect:
        return False  # already exact
    if "stderr_contains" not in expect:
        return False

    contains = expect["stderr_contains"]
    normalized_actual = _normalize(actual_stderr)

    if isinstance(contains, str):
        return normalized_actual == contains
    elif isinstance(contains, list):
        if len(contains) == 1 and normalized_actual == contains[0]:
            return True
        return False
    return False


def _add_stdout_equals(expect: dict, actual_stdout: str) -> bool:
    """Add stdout_equals for tests that have stdout_contains as substring checks.

    Returns True if stdout_equals was added (test had stdout_contains that was
    a proper substring of the actual output).
    """
    if "stdout_equals" in expect:
        return False
    if "stdout_contains" not in expect:
        return False

    normalized_actual = _normalize(actual_stdout)
    if not normalized_actual:
        return False

    contains = expect["stdout_contains"]
    if isinstance(contains, str):
        # Already handled by _should_convert_stdout if exact match;
        # here we add stdout_equals alongside stdout_contains
        if contains in normalized_actual and contains != normalized_actual:
            expect["stdout_equals"] = normalized_actual
            return True
    elif isinstance(contains, list):
        # All fragments must be substrings; add the exact output
        all_present = all(s in normalized_actual for s in contains)
        if all_present:
            expect["stdout_equals"] = normalized_actual
            return True

    return False


def _add_stderr_equals(expect: dict, actual_stderr: str) -> bool:
    """Add stderr_equals for tests that have stderr_contains as substring checks."""
    if "stderr_equals" in expect:
        return False
    if "stderr_contains" not in expect:
        return False

    normalized_actual = _normalize(actual_stderr)
    if not normalized_actual:
        return False

    contains = expect["stderr_contains"]
    if isinstance(contains, str):
        if contains in normalized_actual and contains != normalized_actual:
            expect["stderr_equals"] = normalized_actual
            return True
    elif isinstance(contains, list):
        all_present = all(s in normalized_actual for s in contains)
        if all_present:
            expect["stderr_equals"] = normalized_actual
            return True

    return False


def update_test_files(results: list[dict], mode: str = "convert") -> dict:
    """Update test JSON files based on captured outputs.

    mode="convert": Replace stdout_contains with stdout_equals where contains == full output.
    mode="add": Add stdout_equals alongside existing stdout_contains (for substring cases).

    Returns stats dict.
    """
    # Group results by file
    by_file: dict[str, list[dict]] = {}
    for r in results:
        by_file.setdefault(r["file"], []).append(r)

    stats = {
        "stdout_converted": 0,
        "stderr_converted": 0,
        "stdout_added": 0,
        "stderr_added": 0,
        "files_modified": 0,
    }

    for filename, file_results in by_file.items():
        filepath = CASES_DIR / filename
        with open(filepath) as f:
            cases = json.load(f)

        modified = False
        for case, result in zip(cases, file_results):
            assert case["name"] == result["name"], (
                f"Mismatch: {case['name']} vs {result['name']}"
            )

            # Skip if actual exit code doesn't match expected
            if result["actual_exit_code"] != result["expected_exit_code"]:
                continue

            expect = case["expect"]

            if mode == "convert":
                # Convert stdout_contains -> stdout_equals
                if _should_convert_stdout(expect, result["stdout"]):
                    old_val = expect.pop("stdout_contains")
                    expect["stdout_equals"] = _normalize(result["stdout"])
                    stats["stdout_converted"] += 1
                    modified = True

                # Convert stderr_contains -> stderr_equals
                if _should_convert_stderr(expect, result["stderr"]):
                    old_val = expect.pop("stderr_contains")
                    expect["stderr_equals"] = _normalize(result["stderr"])
                    stats["stderr_converted"] += 1
                    modified = True

            elif mode == "add":
                # Add stdout_equals alongside stdout_contains
                if _add_stdout_equals(expect, result["stdout"]):
                    stats["stdout_added"] += 1
                    modified = True

                # Add stderr_equals alongside stderr_contains
                if _add_stderr_equals(expect, result["stderr"]):
                    stats["stderr_added"] += 1
                    modified = True

        if modified:
            stats["files_modified"] += 1
            with open(filepath, "w") as f:
                json.dump(cases, f, indent=2)
                f.write("\n")

    return stats


def compare_targets(results_a: list[dict], results_b: list[dict], label_a: str, label_b: str) -> int:
    """Compare outputs between two targets. Returns number of divergences."""
    divergences = 0
    for ra, rb in zip(results_a, results_b):
        assert ra["name"] == rb["name"]
        if ra["stdout"] != rb["stdout"]:
            print(f"STDOUT DIVERGENCE: {ra['name']}")
            print(f"  {label_a}: {ra['stdout']!r}")
            print(f"  {label_b}: {rb['stdout']!r}")
            divergences += 1
        if ra["stderr"] != rb["stderr"]:
            print(f"STDERR DIVERGENCE: {ra['name']}")
            print(f"  {label_a}: {ra['stderr']!r}")
            print(f"  {label_b}: {rb['stderr']!r}")
            divergences += 1
    return divergences


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture conformance test outputs")
    parser.add_argument(
        "--target",
        required=True,
        choices=list(TARGETS),
        help="Target implementation to capture from",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update JSON files: convert contains to equals where output matches exactly",
    )
    parser.add_argument(
        "--add",
        action="store_true",
        help="Update JSON files: add equals alongside contains for all passing tests",
    )
    parser.add_argument(
        "--compare-with",
        choices=list(TARGETS),
        help="Also run against this target and compare outputs",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Dump captured outputs to stdout as JSON",
    )
    args = parser.parse_args()

    print(f"Capturing outputs from {args.target}...", file=sys.stderr)
    results = _capture_all(args.target)
    print(f"Captured {len(results)} test cases.", file=sys.stderr)

    if args.dump:
        # Print captured outputs
        for r in results:
            print(json.dumps({
                "file": r["file"],
                "name": r["name"],
                "exit_code": r["actual_exit_code"],
                "stdout": r["stdout"],
                "stderr": r["stderr"],
            }))

    if args.compare_with:
        print(f"\nCapturing outputs from {args.compare_with}...", file=sys.stderr)
        results_b = _capture_all(args.compare_with)
        divs = compare_targets(results, results_b, args.target, args.compare_with)
        print(f"\n{divs} divergence(s) found.", file=sys.stderr)

    if args.update:
        stats = update_test_files(results, mode="convert")
        print(f"\nConversion stats:", file=sys.stderr)
        print(f"  stdout_contains -> stdout_equals: {stats['stdout_converted']}", file=sys.stderr)
        print(f"  stderr_contains -> stderr_equals: {stats['stderr_converted']}", file=sys.stderr)
        print(f"  Files modified: {stats['files_modified']}", file=sys.stderr)

    if args.add:
        stats = update_test_files(results, mode="add")
        print(f"\nAddition stats:", file=sys.stderr)
        print(f"  stdout_equals added: {stats['stdout_added']}", file=sys.stderr)
        print(f"  stderr_equals added: {stats['stderr_added']}", file=sys.stderr)
        print(f"  Files modified: {stats['files_modified']}", file=sys.stderr)


if __name__ == "__main__":
    main()
