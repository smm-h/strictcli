#!/usr/bin/env python3
"""Standalone smoke test for the TypeScript conformance harness.

Runs a small set of representative conformance cases through BOTH the Go
harness (conformance/harness/) and the TS harness (conformance/harness_ts/
main.js) and compares stdout, stderr, and exit code byte-for-byte. This is a
harness-vs-harness parity spot check, independent of run.py's expectation
matching -- the Go harness output is the oracle.

Prerequisites: `go` on PATH, `node` >= 22 on PATH, and a built TS dist
(cd typescript && npm run build).

Usage: python conformance/harness_ts/smoke_test.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFORMANCE_DIR = HERE.parent
CASES_DIR = CONFORMANCE_DIR / "cases"
GO_HARNESS_DIR = CONFORMANCE_DIR / "harness"

# Representative slice of the vocabulary: (case file, case name).
SMOKE_CASES = [
    # basic dispatch + version + unknown command error
    ("basic.json", "basic: dispatch to command"),
    ("basic.json", "basic: unknown command error"),
    ("basic.json", "basic: --version flag"),
    # flags: types, defaults, short forms, bool rendering
    ("flags.json", None),  # None = every case in the file
    # checks: embedded TOML, severities, reporters, notes
    ("checks.json", "checks: list with 2 checks shows names and tags"),
    ("checks.json", "checks: all passing exits 0"),
    ("checks.json", "checks: one failing exits 1"),
    # passthrough: raw args + global flag lines
    ("passthrough.json", "passthrough: receives raw args"),
    ("passthrough.json", "passthrough: with global flags"),
    # registration errors: "error: <msg>" stderr contract
    ("registration_errors.json", "registration: duplicate flag names"),
    ("registration_errors.json", "registration: empty app help"),
    # compound types, dependencies, nesting, providers: full-vocabulary spread
    ("compound_types.json", None),
    ("dependencies.json", None),
    ("nesting.json", None),
    ("providers.json", None),
    ("repeatable.json", None),
    ("variadic.json", None),
    ("outcome_contract.json", None),
]


def build_go_harness() -> str:
    binary = GO_HARNESS_DIR / "smoke_harness"
    result = subprocess.run(
        ["go", "build", "-o", str(binary), "."],
        cwd=GO_HARNESS_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"go harness build failed:\n{result.stderr}")
    return str(binary)


def load_cases() -> list[dict]:
    selected = []
    for filename, case_name in SMOKE_CASES:
        cases = json.loads((CASES_DIR / filename).read_text())
        if case_name is None:
            selected.extend(cases)
            continue
        matches = [c for c in cases if c["name"] == case_name]
        if not matches:
            raise RuntimeError(f"case not found: {filename}: {case_name}")
        selected.extend(matches)
    return selected


def run_harness(cmd: list[str], app_def: dict, argv: list[str], case_env: dict) -> tuple[str, str, int]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(app_def, f)
        def_path = f.name
    env = os.environ.copy()
    env.update(case_env)
    env["CONFORMANCE_APP_DEF"] = def_path
    try:
        result = subprocess.run(
            cmd + argv,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONFORMANCE_DIR),
            timeout=30,
        )
        return result.stdout, result.stderr, result.returncode
    finally:
        os.unlink(def_path)


def satisfies_expect(expect: dict, stdout: str, stderr: str, code: int) -> bool:
    """Minimal expectation matcher for the divergent-wording fallback.

    Only the keys that gate stream content and exit code are checked;
    config_file_* assertions are run.py's business and irrelevant to a
    harness-vs-harness comparison.
    """
    import re

    if code != expect["exit_code"]:
        return False
    checks = [
        ("stdout_equals", lambda v: stdout.rstrip("\n") == v),
        ("stdout_contains", lambda v: v in stdout),
        ("stdout_not_contains", lambda v: v not in stdout),
        ("stdout_matches", lambda v: re.search(v, stdout) is not None),
        ("stderr_equals", lambda v: stderr.rstrip("\n") == v),
        ("stderr_contains", lambda v: v in stderr),
        ("stderr_not_contains", lambda v: v not in stderr),
    ]
    for key, check in checks:
        if key in expect and not check(expect[key]):
            return False
    return True


def main() -> int:
    go_binary = build_go_harness()
    cases = load_cases()
    failures = 0
    divergent = 0
    for case in cases:
        targets = case.get("targets")
        if targets is not None and "go" not in targets:
            continue  # the oracle harness cannot run this case
        name = case["name"]
        app_def = case["app"]
        argv = case["argv"]
        case_env = case.get("env", {})
        go_out, go_err, go_code = run_harness(
            [go_binary], app_def, argv, case_env
        )
        ts_out, ts_err, ts_code = run_harness(
            ["node", str(HERE / "main.js")], app_def, argv, case_env
        )
        problems = []
        if ts_out != go_out:
            problems.append(f"  stdout: go={go_out!r} ts={ts_out!r}")
        if ts_err != go_err:
            problems.append(f"  stderr: go={go_err!r} ts={ts_err!r}")
        if ts_code != go_code:
            problems.append(f"  exit: go={go_code} ts={ts_code}")
        if not problems:
            print(f"ok   {name}")
            continue
        # Byte divergence: accept when both harnesses independently satisfy
        # the case's own expectation (pinned per-language message wording,
        # e.g. NewErrorCheckSpec vs errorCheckSpec vs error_check_spec).
        expect = case["expect"]
        if satisfies_expect(expect, go_out, go_err, go_code) and satisfies_expect(
            expect, ts_out, ts_err, ts_code
        ):
            divergent += 1
            print(f"ok   {name} (divergent wording; both satisfy expectation)")
            continue
        failures += 1
        print(f"FAIL {name}")
        for p in problems:
            print(p)
    os.unlink(go_binary)
    print(
        f"\n{len(cases)} cases, {failures} failures, "
        f"{divergent} accepted wording divergences"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
