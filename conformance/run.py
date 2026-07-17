#!/usr/bin/env python3
"""Conformance test runner for strictcli implementations.

Reads JSON test cases from conformance/cases/, generates reference apps,
invokes them as subprocesses, and compares the results against expectations.

Usage:
    python conformance/run.py --target python
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import jsonschema

# Resolve paths relative to this file
CONFORMANCE_DIR = Path(__file__).resolve().parent
CASES_DIR = CONFORMANCE_DIR / "cases"
SCHEMA_PATH = CONFORMANCE_DIR / "schema.json"
PROJECT_ROOT = CONFORMANCE_DIR.parent

# Go harness: single pre-built binary for all test cases
HARNESS_DIR = CONFORMANCE_DIR / "harness"
HARNESS_BINARY: str | None = None


def _ensure_harness() -> str:
    """Build the Go harness binary if not already built. Returns path to binary."""
    global HARNESS_BINARY
    if HARNESS_BINARY is not None:
        return HARNESS_BINARY

    binary = str(HARNESS_DIR / "harness")

    # Build the harness
    result = subprocess.run(
        ["go", "build", "-o", binary, "."],
        cwd=str(HARNESS_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"harness build failed:\n{result.stderr}")

    HARNESS_BINARY = binary
    return binary


def _cleanup_harness() -> None:
    """Remove the compiled harness binary."""
    global HARNESS_BINARY
    if HARNESS_BINARY and os.path.exists(HARNESS_BINARY):
        os.unlink(HARNESS_BINARY)
    HARNESS_BINARY = None


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


def _check_matches(actual: str, expected, stream_name: str) -> list[str]:
    """Check that actual matches expected regex pattern(s) via re.search."""
    errors = []
    if isinstance(expected, str):
        expected = [expected]
    for pat in expected:
        if not re.search(pat, actual):
            errors.append(f"  {stream_name} does not match pattern: {pat!r}")
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


# --- N-way target registry ---------------------------------------------------
#
# Each registered target is a self-contained descriptor that knows how to
# prepare a case (turn an app definition + argv into an executable command) and
# how to write the project marker file needed for --dump-schema. All target-
# specific code lives in these descriptors; the comparison and orchestration
# logic below is fully target-agnostic. Adding a future target (e.g. TypeScript)
# is one _register_target(...) call and zero changes anywhere else.


@dataclass
class Preparation:
    """The result of preparing a case for one target: a runnable command."""

    argv: list[str]
    extra_env: dict[str, str]
    cleanup_paths: list[str] = field(default_factory=list)


@dataclass
class Target:
    """A conformance target descriptor.

    prepare(app_def, case_argv) -> Preparation
        Builds the argv/env for running the case and lists temp files to unlink.
        May raise RuntimeError if the target's toolchain fails to build; callers
        translate that into a per-case failure.

    write_project_file(dir, app_name) -> None
        Writes the project marker file (e.g. go.mod / pyproject.toml) that
        --dump-schema needs in the working directory to determine project_id.
    """

    name: str
    prepare: Callable[[dict, list[str]], Preparation]
    write_project_file: Callable[[str, str], None]


TARGETS: dict[str, Target] = {}


def _register_target(target: Target) -> None:
    """Register a target descriptor. The insertion order is the reporting order."""
    TARGETS[target.name] = target


def _prepare_python(app_def: dict, case_argv: list[str]) -> Preparation:
    script = _generate_python_script(app_def)
    # Fix the sys.path to use an absolute path so the script works from any
    # directory (ref_python.py emits a __file__-relative path that only works
    # inside the conformance dir).
    python_dir = str(PROJECT_ROOT / "python")
    script = script.replace(
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))",
        f"sys.path.insert(0, {python_dir!r})",
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", prefix="strictcli_py_", delete=False
    ) as f:
        f.write(script)
        script_path = f.name
    return Preparation(
        argv=[sys.executable, script_path] + case_argv,
        extra_env={},
        cleanup_paths=[script_path],
    )


def _write_python_project_file(d: str, app_name: str) -> None:
    with open(os.path.join(d, "pyproject.toml"), "w") as f:
        f.write(f'[project]\nname = "{app_name}"\n')


def _prepare_go(app_def: dict, case_argv: list[str]) -> Preparation:
    binary = _ensure_harness()  # may raise RuntimeError; caller translates it
    # Write the app definition to a temp file for the harness to read.
    app_def_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="strictcli_def_", delete=False
    )
    json.dump(app_def, app_def_file, sort_keys=True)
    app_def_file.close()
    return Preparation(
        argv=[binary] + case_argv,
        extra_env={"CONFORMANCE_APP_DEF": app_def_file.name},
        cleanup_paths=[app_def_file.name],
    )


def _write_go_project_file(d: str, app_name: str) -> None:
    with open(os.path.join(d, "go.mod"), "w") as f:
        f.write(f"module {app_name}\n\ngo 1.21\n")


_register_target(Target("python", _prepare_python, _write_python_project_file))
_register_target(Target("go", _prepare_go, _write_go_project_file))


def _run_case(case: dict, target: str) -> tuple[bool, list[str], subprocess.CompletedProcess | None]:
    """Run a single test case. Returns (passed, error_messages, raw_result)."""
    errors = []
    raw_result = None

    # Handle config_content: write to a temp file and override config_path.
    # If argv contains "$CONFIG_PATH", substitute the temp path into argv
    # instead of setting config_path on the app def (for --config flag tests).
    config_tmp_path = None
    late_config_tmp_path = None
    app_def = case["app"]
    case_argv = case["argv"]
    if "config_content" in app_def:
        config_format = app_def.get("config_format", "json")
        ext = ".toml" if config_format == "toml" else ".json"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, prefix="strictcli_cfg_", delete=False
        ) as cfg_f:
            cfg_f.write(app_def["config_content"])
            config_tmp_path = cfg_f.name
        # Shallow copy so we don't mutate the original case
        app_def = dict(app_def)
        if any("$CONFIG_PATH" in arg for arg in case_argv):
            # Substitute $CONFIG_PATH in argv; don't set config_path on app
            case_argv = [
                arg.replace("$CONFIG_PATH", config_tmp_path)
                for arg in case_argv
            ]
        else:
            app_def["config_path"] = config_tmp_path

    # Handle config_content_late: create a temp path for the config file,
    # set config_path to it, but let the generated code write the content
    # AFTER app construction (between construction and app.run()).
    if "config_content_late" in app_def:
        config_format = app_def.get("config_format", "json")
        ext = ".toml" if config_format == "toml" else ".json"
        late_config_tmp_path = tempfile.mktemp(
            suffix=ext, prefix="strictcli_lcfg_",
        )
        # Shallow copy so we don't mutate the original case
        if app_def is case["app"]:
            app_def = dict(app_def)
        app_def["config_path"] = late_config_tmp_path
        # Keep config_content_late in app_def so generators can emit the write code

    descriptor = TARGETS.get(target)
    if descriptor is None:
        return False, [f"  unsupported target: {target}"], None
    try:
        prep = descriptor.prepare(app_def, case_argv)
    except RuntimeError as e:
        return False, [f"  harness build error: {e}"], None
    argv = prep.argv
    extra_env = prep.extra_env
    cleanup_paths = prep.cleanup_paths

    # --dump-schema needs the target's project marker file (go.mod / pyproject.toml)
    # in the CWD to determine project_id. Create a temp dir with the right file.
    proj_dir = None
    if "--dump-schema" in case_argv:
        proj_dir = tempfile.mkdtemp(prefix="strictcli_proj_")
        descriptor.write_project_file(proj_dir, app_def["name"])
        run_cwd = proj_dir
    else:
        run_cwd = str(CONFORMANCE_DIR)

    try:
        # Build environment: inherit current env, overlay test env and target extras
        env = os.environ.copy()
        test_env = case.get("env", {})
        env.update(test_env)
        env.update(extra_env)

        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=env,
            cwd=run_cwd,
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
        if "stdout_matches" in expect:
            errors.extend(
                _check_matches(result.stdout, expect["stdout_matches"], "stdout")
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
        if "stderr_matches" in expect:
            errors.extend(
                _check_matches(result.stderr, expect["stderr_matches"], "stderr")
            )

        # Check the seeded config file's content (after the run mutated it).
        cfg_assert_keys = (
            "config_file_contains",
            "config_file_not_contains",
            "config_file_matches",
        )
        if any(k in expect for k in cfg_assert_keys):
            cfg_path = config_tmp_path or late_config_tmp_path
            if cfg_path is None or not os.path.exists(cfg_path):
                errors.append(
                    "  config_file_* assertion requires a seeded config file "
                    "(config_content / config_content_late), but none was found"
                )
            else:
                with open(cfg_path, encoding="utf-8") as cf:
                    cfg_text = cf.read()
                if "config_file_contains" in expect:
                    errors.extend(
                        _check_contains(
                            cfg_text, expect["config_file_contains"], "config_file"
                        )
                    )
                if "config_file_not_contains" in expect:
                    errors.extend(
                        _check_not_contains(
                            cfg_text, expect["config_file_not_contains"], "config_file"
                        )
                    )
                if "config_file_matches" in expect:
                    errors.extend(
                        _check_matches(
                            cfg_text, expect["config_file_matches"], "config_file"
                        )
                    )

    except subprocess.TimeoutExpired:
        errors.append("  timed out after 10 seconds")
    except Exception as e:
        errors.append(f"  exception: {e}")
    finally:
        for cleanup_path in cleanup_paths:
            if cleanup_path is not None and os.path.exists(cleanup_path):
                os.unlink(cleanup_path)
        if config_tmp_path is not None:
            os.unlink(config_tmp_path)
        if late_config_tmp_path is not None and os.path.exists(late_config_tmp_path):
            os.unlink(late_config_tmp_path)
        if proj_dir is not None:
            shutil.rmtree(proj_dir, ignore_errors=True)

    return len(errors) == 0, errors, raw_result


def _normalize_temp_paths(s: str) -> str:
    """Replace temp directory paths with a placeholder so cross-target comparison ignores them."""
    tmpdir = re.escape(tempfile.gettempdir())
    return re.sub(
        tmpdir + r"/strictcli_[a-z]+_[a-zA-Z0-9_]+",
        "<TMPDIR>",
        s,
    )


def _stream_divergence(stream_name: str, values: dict[str, str]) -> list[str]:
    """Report N-way divergence for one stream.

    `values` maps target name -> normalized stream text. If all targets agree,
    returns []. Otherwise groups targets by identical output, identifies the odd
    one(s) out by majority (a unique largest group is the majority; every other
    target is odd), and emits a labeled diff. With no majority (e.g. two targets,
    or an even split) every distinct group is reported without an odd-one-out
    marker.
    """
    groups: dict[str, list[str]] = {}
    for tgt, val in values.items():
        groups.setdefault(val, []).append(tgt)
    if len(groups) == 1:
        return []

    sized = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_size = len(sized[0][1])
    majority_is_unique = sum(1 for _, tgts in sized if len(tgts) == top_size) == 1

    odd: list[str] = []
    if majority_is_unique:
        majority_targets = set(sized[0][1])
        odd = sorted(t for t in values if t not in majority_targets)

    header = f"  {stream_name} divergence"
    if odd:
        header += f" (odd one out: {', '.join(odd)})"
    header += ":"
    lines = [header]
    # Deterministic order: sort groups by their sorted target list.
    for val, tgts in sorted(groups.items(), key=lambda kv: sorted(kv[1])):
        label = ",".join(sorted(tgts))
        lines.append(f"    {label}: {val!r}")
    return lines


def _compare_outputs(
    results: dict[str, subprocess.CompletedProcess | None],
) -> list[str]:
    """N-way comparison of normalized stdout/stderr across all targets.

    `results` maps target name -> CompletedProcess (or None for a target that
    produced no result). Targets with no result are excluded. If fewer than two
    targets produced comparable output, returns [] (nothing to compare). On
    divergence, returns a labeled diff identifying the odd one(s) out.
    """
    warnings: list[str] = []
    present = {t: r for t, r in results.items() if r is not None}
    if len(present) < 2:
        return warnings

    stdout_vals = {
        t: _normalize_temp_paths(_normalize(r.stdout)) for t, r in present.items()
    }
    warnings.extend(_stream_divergence("stdout", stdout_vals))

    stderr_vals = {
        t: _normalize_temp_paths(_normalize(r.stderr)) for t, r in present.items()
    }
    warnings.extend(_stream_divergence("stderr", stderr_vals))

    return warnings


@dataclass
class ParityReport:
    """Aggregate outcome of an N-way parity run."""

    passed: int = 0
    parity_failures: int = 0
    output_divergences: int = 0
    consistent_failures: int = 0
    parity_failure_details: list[tuple[str, str]] = field(default_factory=list)
    divergence_details: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.passed + self.parity_failures + self.consistent_failures

    @property
    def exit_code(self) -> int:
        return 0 if self.parity_failures == 0 else 1


def _applicable_targets(case: dict, target_names: list[str]) -> list[str]:
    """Targets a case runs on: intersection of registered and declared targets.

    A case's `targets` key (if present) restricts it to those implementations;
    absent means all. Registration order is preserved.
    """
    declared = case.get("targets")
    if declared is None:
        return list(target_names)
    declared_set = set(declared)
    return [t for t in target_names if t in declared_set]


def _run_parity_mode(
    cases: list[tuple[str, dict]], target_names: list[str], verbose: bool
) -> ParityReport:
    """Run all cases against every applicable registered target and assert parity.

    For each case, runs the intersection of registered and case-declared targets
    and asserts their outputs are byte-identical. A case applicable to fewer than
    two targets is skipped (nothing to compare). Classification per case:

    - all targets pass their own assertions -> counted as passed; outputs are then
      compared N-way and any divergence is reported as a (non-fatal) warning.
    - all targets fail -> a consistent failure (not a parity break).
    - some pass and some fail -> a parity failure (fatal: sets a nonzero exit).
    """
    report = ParityReport()

    for filename, case in cases:
        name = case["name"]
        label = f"{filename}: {name}"

        applicable = _applicable_targets(case, target_names)
        if len(applicable) < 2:
            # Fewer than two targets run this case; parity is undefined.
            continue

        if verbose:
            print(f"  running: {label} ...", end=" ", flush=True)

        outcomes = {t: _run_case(case, t) for t in applicable}
        oks = {t: outcomes[t][0] for t in applicable}
        results = {t: outcomes[t][2] for t in applicable}

        if all(oks.values()):
            # All targets pass -- check output divergence.
            report.passed += 1
            div_warnings = _compare_outputs(results)
            if div_warnings:
                report.output_divergences += 1
                report.divergence_details.append((label, div_warnings))
                if verbose:
                    print("PASS (output divergence)")
            else:
                if verbose:
                    print("PASS")
        elif not any(oks.values()):
            # All targets fail -- consistent.
            report.consistent_failures += 1
            extra = ""
            codes = {
                t: (results[t].returncode if results[t] is not None else None)
                for t in applicable
            }
            if len(set(codes.values())) > 1:
                joined = ", ".join(f"{t}={codes[t]}" for t in applicable)
                extra = f" (exit codes differ: {joined})"
            if verbose:
                print(f"CONSISTENT FAIL{extra}")
        else:
            # Parity failure -- some targets pass, some fail.
            report.parity_failures += 1
            detail = ", ".join(
                f"{t}={'PASS' if oks[t] else 'FAIL'}" for t in applicable
            )
            report.parity_failure_details.append((label, detail))
            if verbose:
                print(f"PARITY FAIL ({detail})")

    # Print parity failures
    if report.parity_failure_details:
        print()
        print("PARITY FAILURES:")
        print("=" * 60)
        for label, detail in report.parity_failure_details:
            print(f"\n{label}")
            print(f"  {detail}")
        print()

    # Print output divergence warnings
    if report.divergence_details:
        print()
        print("OUTPUT DIVERGENCE WARNINGS:")
        print("=" * 60)
        for label, warnings in report.divergence_details:
            print(f"\n{label}")
            for w in warnings:
                print(w)
        print()

    # Cleanup
    _cleanup_harness()

    # Summary
    print(
        f"{report.passed}/{report.total} passed, {report.parity_failures} parity failures,"
        f" {report.output_divergences} output divergence warnings"
    )

    return report


def _run_single_mode(cases: list[tuple[str, dict]], target: str, verbose: bool) -> int:
    """Run all cases against a single target. Returns exit code."""
    passed = 0
    failed = 0
    failures = []

    for filename, case in cases:
        name = case["name"]
        label = f"{filename}: {name}"

        # Skip cases that declare a target restriction excluding this target.
        targets = case.get("targets")
        if targets is not None and target not in targets:
            continue

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
    _cleanup_harness()

    # Summary
    total = passed + failed
    print(f"{passed}/{total} passed, {failed} failed")

    return 0 if failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strictcli conformance tests")
    parser.add_argument(
        "--target",
        default=None,
        choices=list(TARGETS),
        help="Which implementation to test",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Test all registered targets, comparing results for parity",
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
        report = _run_parity_mode(cases, list(TARGETS), args.verbose)
        exit_code = report.exit_code
    else:
        exit_code = _run_single_mode(cases, args.target, args.verbose)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
