#!/usr/bin/env python3
"""Conformance test runner for strictcli implementations.

Reads JSON test cases from conformance/cases/, generates reference apps,
invokes them as subprocesses, and compares the results against expectations.

Usage:
    python conformance/run.py --target python
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import jsonschema

# Resolve paths relative to this file
CONFORMANCE_DIR = Path(__file__).resolve().parent
CASES_DIR = CONFORMANCE_DIR / "cases"
SCHEMA_PATH = CONFORMANCE_DIR / "schema.json"
PROJECT_ROOT = CONFORMANCE_DIR.parent
GO_PKG_DIR = PROJECT_ROOT / "go"

# Cache directory for compiled Go binaries (keyed by app-def hash)
GO_BUILD_CACHE: dict[str, str] = {}


def _load_schema() -> tuple[dict, dict]:
    """Load the conformance schema and return (full_schema, test_case_schema).

    The test_case_schema is the $defs/test_case definition with a local $defs
    copy so $ref pointers resolve correctly when validating individual cases.
    """
    with open(SCHEMA_PATH) as f:
        full_schema = json.load(f)
    # Build a standalone schema for a single test_case that carries all $defs
    test_case_schema = dict(full_schema["$defs"]["test_case"])
    test_case_schema["$defs"] = full_schema["$defs"]
    return full_schema, test_case_schema


def _load_cases() -> list[tuple[str, dict]]:
    """Load all test cases from JSON files. Returns (filename, case) pairs.

    Validates each non-exempt case against schema.json. Exits on first failure.
    """
    _, test_case_schema = _load_schema()
    cases = []
    for json_file in sorted(CASES_DIR.glob("*.json")):
        with open(json_file) as f:
            data = json.load(f)
        for case in data:
            if not case.get("skip_schema_validation", False):
                try:
                    jsonschema.validate(instance=case, schema=test_case_schema)
                except jsonschema.ValidationError as e:
                    print(
                        f"Schema validation failed for case "
                        f"{case.get('name', '<unnamed>')!r} in {json_file.name}:",
                        file=sys.stderr,
                    )
                    print(f"  {e.message}", file=sys.stderr)
                    sys.exit(1)
            cases.append((json_file.name, case))
    return cases


def _generate_python_script(app_def: dict) -> str:
    """Generate a Python script from an app definition."""
    from ref_python import generate
    return generate(app_def)


def _generate_go_source(app_def: dict) -> str:
    """Generate a Go main.go from an app definition."""
    from ref_go import generate
    return generate(app_def)


def _build_go_binary(app_def: dict) -> str:
    """Build a Go binary from an app definition, with caching.

    Returns the path to the compiled binary.
    """
    # Cache key: hash of the canonical JSON app definition
    cache_key = hashlib.sha256(
        json.dumps(app_def, sort_keys=True).encode()
    ).hexdigest()[:16]

    if cache_key in GO_BUILD_CACHE:
        return GO_BUILD_CACHE[cache_key]

    source = _generate_go_source(app_def)

    # Create a temp directory with go.mod and main.go
    build_dir = tempfile.mkdtemp(prefix="strictcli_go_")
    main_go = os.path.join(build_dir, "main.go")
    go_mod = os.path.join(build_dir, "go.mod")
    binary = os.path.join(build_dir, "app")

    with open(main_go, "w") as f:
        f.write(source)

    go_mod_content = (
        "module conformance_test\n\n"
        "go 1.23\n\n"
        "require github.com/smm-h/strictcli/go v0.0.0\n\n"
        f"replace github.com/smm-h/strictcli/go => {GO_PKG_DIR}\n"
    )
    with open(go_mod, "w") as f:
        f.write(go_mod_content)

    # Resolve transitive dependencies
    tidy_result = subprocess.run(
        ["go", "mod", "tidy"],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if tidy_result.returncode != 0:
        raise RuntimeError(
            f"go mod tidy failed:\n{tidy_result.stderr}\n\n--- main.go ---\n{source}"
        )

    # Build
    result = subprocess.run(
        ["go", "build", "-o", binary, "."],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        # Include generated source in error for debugging
        raise RuntimeError(
            f"go build failed:\n{result.stderr}\n\n--- main.go ---\n{source}"
        )

    GO_BUILD_CACHE[cache_key] = binary
    return binary


def _normalize(s: str) -> str:
    """Normalize a string for comparison (strip trailing whitespace per line, strip trailing newline)."""
    return "\n".join(line.rstrip() for line in s.rstrip("\n").split("\n"))


def _check_contains(actual: str, expected, stream_name: str) -> list[str]:
    """Check that actual contains expected substring(s). Returns list of error messages."""
    errors = []
    if isinstance(expected, str):
        expected = [expected]
    for s in expected:
        if s not in actual:
            errors.append(f"  {stream_name} does not contain: {s!r}")
            errors.append(f"  actual {stream_name}: {actual!r}")
    return errors


def _check_not_contains(actual: str, expected, stream_name: str) -> list[str]:
    """Check that actual does NOT contain the specified substring(s)."""
    errors = []
    if isinstance(expected, str):
        expected = [expected]
    for s in expected:
        if s in actual:
            errors.append(f"  {stream_name} should NOT contain: {s!r}")
            errors.append(f"  actual {stream_name}: {actual!r}")
    return errors


def _check_equals(actual: str, expected: str, stream_name: str) -> list[str]:
    """Check exact match. Returns list of error messages."""
    errors = []
    actual_norm = _normalize(actual)
    expected_norm = _normalize(expected)
    if actual_norm != expected_norm:
        errors.append(f"  {stream_name} mismatch:")
        errors.append(f"    expected: {expected_norm!r}")
        errors.append(f"    actual:   {actual_norm!r}")
    return errors


def _run_case(case: dict, target: str) -> tuple[bool, list[str], subprocess.CompletedProcess | None]:
    """Run a single test case. Returns (passed, error_messages, raw_result)."""
    errors = []
    raw_result = None

    if target == "python":
        script = _generate_python_script(case["app"])
        # Fix the sys.path to use an absolute path so the script works from
        # any directory (it's generated with a __file__-relative path by
        # ref_python.py which only works inside the conformance dir).
        python_dir = str(PROJECT_ROOT / "python")
        script = script.replace(
            "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))",
            f"sys.path.insert(0, {python_dir!r})",
        )
        # Write script to temp file (in system temp dir, not the project tree)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="strictcli_py_", delete=False
        ) as f:
            f.write(script)
            script_path = f.name
        argv = [sys.executable, script_path] + case["argv"]
        cleanup_path = script_path
    elif target == "go":
        try:
            binary = _build_go_binary(case["app"])
        except RuntimeError as e:
            return False, [f"  build error: {e}"], None
        argv = [binary] + case["argv"]
        cleanup_path = None  # binary lives in cache, cleaned up at exit
    else:
        return False, [f"  unsupported target: {target}"], None

    try:
        # Build environment: inherit current env, overlay test env
        env = os.environ.copy()
        test_env = case.get("env", {})
        env.update(test_env)

        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONFORMANCE_DIR),
            timeout=10,
        )
        raw_result = result

        # Check exit code
        expect = case["expect"]
        if result.returncode != expect["exit_code"]:
            errors.append(
                f"  exit_code: expected {expect['exit_code']}, got {result.returncode}"
            )
            if result.stderr:
                errors.append(f"  stderr: {result.stderr.rstrip()!r}")
            if result.stdout:
                errors.append(f"  stdout: {result.stdout.rstrip()!r}")

        # Check stdout
        if "stdout_contains" in expect:
            errors.extend(
                _check_contains(result.stdout, expect["stdout_contains"], "stdout")
            )
        if "stdout_equals" in expect:
            errors.extend(
                _check_equals(result.stdout, expect["stdout_equals"], "stdout")
            )
        if "stdout_not_contains" in expect:
            errors.extend(
                _check_not_contains(result.stdout, expect["stdout_not_contains"], "stdout")
            )

        # Check stderr
        if "stderr_contains" in expect:
            errors.extend(
                _check_contains(result.stderr, expect["stderr_contains"], "stderr")
            )
        if "stderr_equals" in expect:
            errors.extend(
                _check_equals(result.stderr, expect["stderr_equals"], "stderr")
            )
        if "stderr_not_contains" in expect:
            errors.extend(
                _check_not_contains(result.stderr, expect["stderr_not_contains"], "stderr")
            )

    except subprocess.TimeoutExpired:
        errors.append("  timed out after 10 seconds")
    except Exception as e:
        errors.append(f"  exception: {e}")
    finally:
        if cleanup_path is not None:
            os.unlink(cleanup_path)

    return len(errors) == 0, errors, raw_result


def _cleanup_go_cache() -> None:
    """Remove all temporary Go build directories."""
    for binary_path in GO_BUILD_CACHE.values():
        build_dir = os.path.dirname(binary_path)
        shutil.rmtree(build_dir, ignore_errors=True)
    GO_BUILD_CACHE.clear()


def _compare_outputs(
    py_result: subprocess.CompletedProcess | None,
    go_result: subprocess.CompletedProcess | None,
) -> list[str]:
    """Compare normalized stdout/stderr between two targets. Returns warnings."""
    warnings = []
    if py_result is None or go_result is None:
        return warnings

    py_stdout = _normalize(py_result.stdout)
    go_stdout = _normalize(go_result.stdout)
    if py_stdout != go_stdout:
        warnings.append("  stdout divergence:")
        warnings.append(f"    python: {py_stdout!r}")
        warnings.append(f"    go:     {go_stdout!r}")

    py_stderr = _normalize(py_result.stderr)
    go_stderr = _normalize(go_result.stderr)
    if py_stderr != go_stderr:
        warnings.append("  stderr divergence:")
        warnings.append(f"    python: {py_stderr!r}")
        warnings.append(f"    go:     {go_stderr!r}")

    return warnings


def _run_both_mode(cases: list[tuple[str, dict]], verbose: bool) -> int:
    """Run all cases against both python and go, comparing results.

    Returns exit code (0 = no parity failures, 1 = parity failures exist).
    """
    passed = 0
    parity_failures = 0
    output_divergences = 0
    consistent_failures = 0
    parity_failure_details: list[tuple[str, str]] = []
    divergence_details: list[tuple[str, list[str]]] = []

    for filename, case in cases:
        name = case["name"]
        label = f"{filename}: {name}"

        if verbose:
            print(f"  running: {label} ...", end=" ", flush=True)

        py_ok, py_errors, py_result = _run_case(case, "python")
        go_ok, go_errors, go_result = _run_case(case, "go")

        if py_ok and go_ok:
            # Both pass -- check output divergence
            passed += 1
            div_warnings = _compare_outputs(py_result, go_result)
            if div_warnings:
                output_divergences += 1
                divergence_details.append((label, div_warnings))
                if verbose:
                    print("PASS (output divergence)")
            else:
                if verbose:
                    print("PASS")
        elif not py_ok and not go_ok:
            # Both fail -- consistent
            consistent_failures += 1
            extra = ""
            if (
                py_result is not None
                and go_result is not None
                and py_result.returncode != go_result.returncode
            ):
                extra = (
                    f" (exit codes differ: python={py_result.returncode},"
                    f" go={go_result.returncode})"
                )
            if verbose:
                print(f"CONSISTENT FAIL{extra}")
        else:
            # Parity failure -- one passes, one fails
            parity_failures += 1
            py_status = "PASS" if py_ok else "FAIL"
            go_status = "PASS" if go_ok else "FAIL"
            detail = f"python={py_status}, go={go_status}"
            parity_failure_details.append((label, detail))
            if verbose:
                print(f"PARITY FAIL ({detail})")

    # Print parity failures
    if parity_failure_details:
        print()
        print("PARITY FAILURES:")
        print("=" * 60)
        for label, detail in parity_failure_details:
            print(f"\n{label}")
            print(f"  {detail}")
        print()

    # Print output divergence warnings
    if divergence_details:
        print()
        print("OUTPUT DIVERGENCE WARNINGS:")
        print("=" * 60)
        for label, warnings in divergence_details:
            print(f"\n{label}")
            for w in warnings:
                print(w)
        print()

    # Cleanup
    _cleanup_go_cache()

    # Summary
    total = passed + parity_failures + consistent_failures
    print(
        f"{passed}/{total} passed, {parity_failures} parity failures,"
        f" {output_divergences} output divergence warnings"
    )

    return 0 if parity_failures == 0 else 1


def _run_single_mode(cases: list[tuple[str, dict]], target: str, verbose: bool) -> int:
    """Run all cases against a single target. Returns exit code."""
    passed = 0
    failed = 0
    failures = []

    for filename, case in cases:
        name = case["name"]
        label = f"{filename}: {name}"

        if verbose:
            print(f"  running: {label} ...", end=" ", flush=True)

        ok, errors, _result = _run_case(case, target)

        if ok:
            passed += 1
            if verbose:
                print("PASS")
        else:
            failed += 1
            failures.append((label, errors))
            if verbose:
                print("FAIL")

    # Print failures
    if failures:
        print()
        print("FAILURES:")
        print("=" * 60)
        for label, errors in failures:
            print(f"\n{label}")
            for e in errors:
                print(e)
        print()

    # Cleanup
    _cleanup_go_cache()

    # Summary
    total = passed + failed
    print(f"{passed}/{total} passed, {failed} failed")

    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strictcli conformance tests")
    parser.add_argument(
        "--target",
        default=None,
        choices=["python", "go"],
        help="Which implementation to test",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Test both python and go, comparing results for parity",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Only run cases whose name contains this substring",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each test case name as it runs",
    )
    args = parser.parse_args()

    # Validate: exactly one of --target or --both
    if args.both and args.target is not None:
        print("error: --both and --target are mutually exclusive", file=sys.stderr)
        sys.exit(2)
    if not args.both and args.target is None:
        print("error: one of --target or --both is required", file=sys.stderr)
        sys.exit(2)

    cases = _load_cases()
    if not cases:
        print("No test cases found!")
        sys.exit(1)

    if args.filter:
        cases = [(f, c) for f, c in cases if args.filter in c["name"]]
        if not cases:
            print(f"No test cases match filter: {args.filter!r}")
            sys.exit(1)

    if args.both:
        exit_code = _run_both_mode(cases, args.verbose)
    else:
        exit_code = _run_single_mode(cases, args.target, args.verbose)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
