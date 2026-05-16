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

# Resolve paths relative to this file
CONFORMANCE_DIR = Path(__file__).resolve().parent
CASES_DIR = CONFORMANCE_DIR / "cases"
PROJECT_ROOT = CONFORMANCE_DIR.parent
GO_PKG_DIR = PROJECT_ROOT / "go"

# Cache directory for compiled Go binaries (keyed by app-def hash)
GO_BUILD_CACHE: dict[str, str] = {}


def _load_cases() -> list[tuple[str, dict]]:
    """Load all test cases from JSON files. Returns (filename, case) pairs."""
    cases = []
    for json_file in sorted(CASES_DIR.glob("*.json")):
        with open(json_file) as f:
            data = json.load(f)
        for case in data:
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
    build_dir = tempfile.mkdtemp(prefix="strictcli_go_", dir=str(CONFORMANCE_DIR))
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


def _run_case(case: dict, target: str) -> tuple[bool, list[str]]:
    """Run a single test case. Returns (passed, error_messages)."""
    errors = []

    if target == "python":
        script = _generate_python_script(case["app"])
        # Write script to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir=str(CONFORMANCE_DIR), delete=False
        ) as f:
            f.write(script)
            script_path = f.name
        argv = [sys.executable, script_path] + case["argv"]
        cleanup_path = script_path
    elif target == "go":
        try:
            binary = _build_go_binary(case["app"])
        except RuntimeError as e:
            return False, [f"  build error: {e}"]
        argv = [binary] + case["argv"]
        cleanup_path = None  # binary lives in cache, cleaned up at exit
    else:
        return False, [f"  unsupported target: {target}"]

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
            timeout=10,
        )

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

    return len(errors) == 0, errors


def _cleanup_go_cache() -> None:
    """Remove all temporary Go build directories."""
    for binary_path in GO_BUILD_CACHE.values():
        build_dir = os.path.dirname(binary_path)
        shutil.rmtree(build_dir, ignore_errors=True)
    GO_BUILD_CACHE.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strictcli conformance tests")
    parser.add_argument(
        "--target",
        required=True,
        choices=["python", "go"],
        help="Which implementation to test",
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

    cases = _load_cases()
    if not cases:
        print("No test cases found!")
        sys.exit(1)

    if args.filter:
        cases = [(f, c) for f, c in cases if args.filter in c["name"]]
        if not cases:
            print(f"No test cases match filter: {args.filter!r}")
            sys.exit(1)

    passed = 0
    failed = 0
    failures = []

    for filename, case in cases:
        name = case["name"]
        label = f"{filename}: {name}"

        if args.verbose:
            print(f"  running: {label} ...", end=" ", flush=True)

        ok, errors = _run_case(case, args.target)

        if ok:
            passed += 1
            if args.verbose:
                print("PASS")
        else:
            failed += 1
            failures.append((label, errors))
            if args.verbose:
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

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
