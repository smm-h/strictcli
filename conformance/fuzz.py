#!/usr/bin/env python3
"""Differential argv fuzzer for strictcli conformance.

Generates random argv sequences and runs them against both Python and Go
implementations of the same app definition. Divergences (different exit codes,
or different stdout when both exit 0) are recorded and minimized.

Usage:
    python conformance/fuzz.py --iterations 1000
    python conformance/fuzz.py --iterations 100 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CONFORMANCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFORMANCE_DIR.parent
GO_PKG_DIR = PROJECT_ROOT / "go"

# ---------------------------------------------------------------------------
# App definitions
# ---------------------------------------------------------------------------

SIMPLE_APP: dict = {
    "name": "fuzzapp",
    "version": "1.0.0",
    "help": "a simple app for fuzzing",
    "commands": [
        {
            "name": "run",
            "help": "run something",
            "flags": [
                {
                    "name": "name",
                    "type": "str",
                    "help": "a name",
                    "default": "world",
                },
                {
                    "name": "verbose",
                    "type": "bool",
                    "help": "verbose output",
                },
            ],
            "handler_prints": "run name={name} verbose={verbose}",
        },
    ],
}

COMPLEX_APP: dict = {
    "name": "fuzzapp",
    "version": "2.0.0",
    "help": "a complex app for fuzzing",
    "global_flags": [
        {
            "name": "verbose",
            "type": "bool",
            "help": "verbose output",
        },
    ],
    "commands": [
        {
            "name": "raw",
            "help": "passthrough command",
            "passthrough": True,
            "passthrough_handler_prints": "{name}:{args}",
        },
    ],
    "groups": [
        {
            "name": "db",
            "help": "database operations",
            "commands": [
                {
                    "name": "migrate",
                    "help": "run migrations",
                    "flags": [
                        {
                            "name": "target",
                            "type": "str",
                            "help": "deploy target",
                            "choices_str": ["prod", "staging"],
                        },
                        {
                            "name": "count",
                            "type": "int",
                            "help": "number of migrations",
                            "default": 1,
                        },
                        {
                            "name": "dry-run",
                            "type": "bool",
                            "help": "dry run mode",
                        },
                    ],
                    "args": [
                        {
                            "name": "path",
                            "help": "migration path",
                            "required": True,
                        },
                    ],
                    "handler_prints": "migrate target={target} count={count} dry-run={dry-run} path={path} verbose={verbose}",
                },
            ],
        },
    ],
}

APP_DEFS: list[tuple[str, dict]] = [
    ("simple", SIMPLE_APP),
    ("complex", COMPLEX_APP),
]

# ---------------------------------------------------------------------------
# Code generation (reused from run.py infrastructure)
# ---------------------------------------------------------------------------


def _generate_python_script(app_def: dict) -> str:
    from ref_python import generate
    return generate(app_def)


def _generate_go_source(app_def: dict) -> str:
    from ref_go import generate
    return generate(app_def)


# ---------------------------------------------------------------------------
# Go binary cache (keyed by app-def hash)
# ---------------------------------------------------------------------------

_GO_BUILD_CACHE: dict[str, str] = {}


def _build_go_binary(app_def: dict) -> str:
    cache_key = hashlib.sha256(
        json.dumps(app_def, sort_keys=True).encode()
    ).hexdigest()[:16]

    if cache_key in _GO_BUILD_CACHE:
        return _GO_BUILD_CACHE[cache_key]

    source = _generate_go_source(app_def)
    build_dir = tempfile.mkdtemp(prefix="strictcli_fuzz_go_", dir=str(CONFORMANCE_DIR))
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

    result = subprocess.run(
        ["go", "build", "-o", binary, "."],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"go build failed:\n{result.stderr}\n\n--- main.go ---\n{source}")

    _GO_BUILD_CACHE[cache_key] = binary
    return binary


def _cleanup_go_cache() -> None:
    for binary_path in _GO_BUILD_CACHE.values():
        build_dir = os.path.dirname(binary_path)
        shutil.rmtree(build_dir, ignore_errors=True)
    _GO_BUILD_CACHE.clear()


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------

TIMEOUT = 5


def _normalize(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.rstrip("\n").split("\n"))


def _run_python(app_def: dict, argv: list[str]) -> tuple[int, str, str]:
    """Run the Python implementation. Returns (exit_code, stdout, stderr).

    Exit code -1 means timeout.
    """
    script = _generate_python_script(app_def)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=str(CONFORMANCE_DIR), delete=False
    ) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, script_path] + argv,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    finally:
        os.unlink(script_path)


def _run_go(binary: str, argv: list[str]) -> tuple[int, str, str]:
    """Run the Go implementation. Returns (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            [binary] + argv,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------


def _check_divergence(
    py_exit: int, py_stdout: str, py_stderr: str,
    go_exit: int, go_stdout: str, go_stderr: str,
) -> str | None:
    """Return a description of the divergence, or None if outputs agree."""
    if py_exit != go_exit:
        return (
            f"exit code: python={py_exit} go={go_exit}\n"
            f"  py stdout: {py_stdout.rstrip()!r}\n"
            f"  py stderr: {py_stderr.rstrip()!r}\n"
            f"  go stdout: {go_stdout.rstrip()!r}\n"
            f"  go stderr: {go_stderr.rstrip()!r}"
        )
    if py_exit == 0 and go_exit == 0:
        py_norm = _normalize(py_stdout)
        go_norm = _normalize(go_stdout)
        if py_norm != go_norm:
            return (
                f"stdout mismatch (both exit 0):\n"
                f"  python: {py_norm!r}\n"
                f"  go:     {go_norm!r}"
            )
    return None


# ---------------------------------------------------------------------------
# Argv generation
# ---------------------------------------------------------------------------

# Tokens used across all strategies
_GARBAGE = [
    "", " ", "foo", "bar", "baz", "123", "-", "---", "--=val",
    "--unknown", "-x", "-xyz", "true", "false", "null", "0", "-1",
    "a b", "a=b", "--", "'quoted'", '"double"',
]


def _gen_argv_simple(rng: random.Random) -> list[str]:
    """Generate a random argv for the simple app."""
    tokens: list[str] = []
    strategy = rng.choice([
        "valid_basic", "valid_flags", "garbage", "help_interspersed",
        "mixed", "empty", "double_dash", "flag_styles",
    ])

    if strategy == "valid_basic":
        tokens.append("run")
        if rng.random() < 0.5:
            tokens.extend(["--name", rng.choice(["alice", "bob", ""])])
        if rng.random() < 0.5:
            tokens.append("--verbose")

    elif strategy == "valid_flags":
        tokens.append("run")
        # Random flag styles
        for _ in range(rng.randint(0, 4)):
            flag = rng.choice(["--name", "--verbose"])
            if flag == "--name":
                style = rng.choice(["space", "equals"])
                val = rng.choice(["alice", "bob", "", "123", "true"])
                if style == "equals":
                    tokens.append(f"--name={val}")
                else:
                    tokens.extend(["--name", val])
            else:
                tokens.append("--verbose")

    elif strategy == "garbage":
        n = rng.randint(0, 6)
        for _ in range(n):
            tokens.append(rng.choice(_GARBAGE))

    elif strategy == "help_interspersed":
        parts = ["run", "--name", "val", "--verbose"]
        rng.shuffle(parts)
        pos = rng.randint(0, len(parts))
        flag = rng.choice(["--help", "-h", "--version", "-v"])
        parts.insert(pos, flag)
        tokens = parts

    elif strategy == "mixed":
        tokens.append(rng.choice(["run", "unknown", "db", ""]))
        for _ in range(rng.randint(0, 5)):
            tokens.append(rng.choice(
                ["--name", "val", "--verbose", "--unknown", "-x", "extra", "--"]
            ))

    elif strategy == "empty":
        pass  # empty argv

    elif strategy == "double_dash":
        tokens.append("run")
        if rng.random() < 0.5:
            tokens.extend(["--name", "val"])
        tokens.append("--")
        for _ in range(rng.randint(0, 3)):
            tokens.append(rng.choice(["--name", "extra", "--verbose", "pos"]))

    elif strategy == "flag_styles":
        tokens.append("run")
        # Mix of --flag=val, --flag val, repeated flags, wrong types
        for _ in range(rng.randint(1, 5)):
            pick = rng.choice(["name_eq", "name_sp", "verbose", "dup_verbose", "bad_bool"])
            if pick == "name_eq":
                tokens.append(f"--name={rng.choice(['a', 'b', ''])}")
            elif pick == "name_sp":
                tokens.extend(["--name", rng.choice(["a", "b", ""])])
            elif pick == "verbose":
                tokens.append("--verbose")
            elif pick == "dup_verbose":
                tokens.extend(["--verbose", "--verbose"])
            elif pick == "bad_bool":
                tokens.extend(["--verbose", "notabool"])

    return tokens


def _gen_argv_complex(rng: random.Random) -> list[str]:
    """Generate a random argv for the complex app."""
    tokens: list[str] = []
    strategy = rng.choice([
        "valid_migrate", "valid_raw", "garbage", "help_interspersed",
        "mixed", "empty", "double_dash", "missing_required",
        "choices_invalid", "int_flag_bad",
    ])

    if strategy == "valid_migrate":
        tokens.extend(["db", "migrate"])
        if rng.random() < 0.7:
            target = rng.choice(["prod", "staging"])
            if rng.random() < 0.5:
                tokens.extend(["--target", target])
            else:
                tokens.append(f"--target={target}")
        if rng.random() < 0.5:
            count = rng.choice(["1", "5", "0", "-1", "abc"])
            if rng.random() < 0.5:
                tokens.extend(["--count", count])
            else:
                tokens.append(f"--count={count}")
        if rng.random() < 0.4:
            tokens.append("--dry-run")
        if rng.random() < 0.3:
            tokens.append("--verbose")
        # path arg (required) -- sometimes omit to test error
        if rng.random() < 0.8:
            tokens.append(rng.choice(["./migrations", "/tmp/m", "path with space"]))

    elif strategy == "valid_raw":
        tokens.append("raw")
        for _ in range(rng.randint(0, 5)):
            tokens.append(rng.choice(["--some-flag", "val", "-x", "pos", "--", "--verbose"]))

    elif strategy == "garbage":
        n = rng.randint(0, 6)
        for _ in range(n):
            tokens.append(rng.choice(_GARBAGE))

    elif strategy == "help_interspersed":
        base = rng.choice([
            ["db", "migrate", "--target", "prod", "./m"],
            ["raw", "extra"],
            ["db"],
            [],
        ])
        pos = rng.randint(0, len(base))
        flag = rng.choice(["--help", "-h", "--version", "-v"])
        base.insert(pos, flag)
        tokens = base

    elif strategy == "mixed":
        first = rng.choice(["db", "raw", "unknown", "migrate", ""])
        tokens.append(first)
        if first == "db":
            tokens.append(rng.choice(["migrate", "unknown", "--help", ""]))
        for _ in range(rng.randint(0, 4)):
            tokens.append(rng.choice([
                "--target", "prod", "staging", "--count", "3", "--dry-run",
                "--verbose", "--unknown", "-x", "extra", "--",
            ]))

    elif strategy == "empty":
        pass

    elif strategy == "double_dash":
        tokens.extend(["db", "migrate", "--target", "prod"])
        tokens.append("--")
        for _ in range(rng.randint(0, 3)):
            tokens.append(rng.choice(["--count", "extra", "pos"]))

    elif strategy == "missing_required":
        tokens.extend(["db", "migrate"])
        # Omit --target (required via choices) and/or path arg
        if rng.random() < 0.5:
            tokens.extend(["--count", str(rng.randint(1, 10))])
        if rng.random() < 0.3:
            tokens.append("--dry-run")

    elif strategy == "choices_invalid":
        tokens.extend(["db", "migrate"])
        bad_target = rng.choice(["dev", "local", "production", "PROD", ""])
        if rng.random() < 0.5:
            tokens.extend(["--target", bad_target])
        else:
            tokens.append(f"--target={bad_target}")
        tokens.append("./m")

    elif strategy == "int_flag_bad":
        tokens.extend(["db", "migrate", "--target", "prod"])
        bad_int = rng.choice(["abc", "1.5", "", "true", "99999999999999999999"])
        if rng.random() < 0.5:
            tokens.extend(["--count", bad_int])
        else:
            tokens.append(f"--count={bad_int}")
        tokens.append("./m")

    return tokens


# ---------------------------------------------------------------------------
# Minimization
# ---------------------------------------------------------------------------


def _minimize(
    app_def: dict,
    go_binary: str,
    argv: list[str],
) -> list[str]:
    """Remove tokens one at a time, keeping the smallest argv that still diverges."""
    best = list(argv)

    changed = True
    while changed:
        changed = False
        for i in range(len(best)):
            candidate = best[:i] + best[i + 1:]
            py_exit, py_stdout, py_stderr = _run_python(app_def, candidate)
            go_exit, go_stdout, go_stderr = _run_go(go_binary, candidate)
            if _check_divergence(py_exit, py_stdout, py_stderr, go_exit, go_stdout, go_stderr):
                best = candidate
                changed = True
                break  # restart from beginning with shorter list

    return best


# ---------------------------------------------------------------------------
# Main fuzzing loop
# ---------------------------------------------------------------------------


def fuzz(iterations: int, seed: int | None) -> list[dict]:
    """Run the fuzzer. Returns a list of divergence records."""
    if seed is None:
        seed = int(time.time() * 1000) % (2**32)
    print(f"Seed: {seed}")
    print(f"Iterations: {iterations} ({iterations} per app definition)")

    rng = random.Random(seed)

    # Pre-build Go binaries for both app definitions
    go_binaries: dict[str, str] = {}
    for label, app_def in APP_DEFS:
        print(f"Building Go binary for '{label}' app...", flush=True)
        go_binaries[label] = _build_go_binary(app_def)
    print()

    divergences: list[dict] = []
    generators = {
        "simple": _gen_argv_simple,
        "complex": _gen_argv_complex,
    }

    total = 0
    for label, app_def in APP_DEFS:
        go_binary = go_binaries[label]
        gen = generators[label]
        print(f"--- Fuzzing '{label}' app ({iterations} iterations) ---")

        for i in range(1, iterations + 1):
            argv = gen(rng)
            py_exit, py_stdout, py_stderr = _run_python(app_def, argv)
            go_exit, go_stdout, go_stderr = _run_go(go_binary, argv)

            desc = _check_divergence(py_exit, py_stdout, py_stderr, go_exit, go_stdout, go_stderr)
            if desc is not None:
                # Minimize
                minimal = _minimize(app_def, go_binary, argv)
                # Re-run minimal to get fresh description
                py2_exit, py2_stdout, py2_stderr = _run_python(app_def, minimal)
                go2_exit, go2_stdout, go2_stderr = _run_go(go_binary, minimal)
                min_desc = _check_divergence(
                    py2_exit, py2_stdout, py2_stderr, go2_exit, go2_stdout, go2_stderr
                ) or desc

                record = {
                    "app": label,
                    "seed": seed,
                    "iteration": i,
                    "original_argv": argv,
                    "minimal_argv": minimal,
                    "description": min_desc,
                }
                divergences.append(record)
                print(f"  [{i}/{iterations}] DIVERGENCE: argv={argv}")
                print(f"             minimal: {minimal}")
                print(f"             {min_desc.splitlines()[0]}")

            if i % 100 == 0:
                print(f"  [{i}/{iterations}] {len(divergences)} divergence(s) so far", flush=True)

            total += 1

        print()

    # Final report
    print("=" * 60)
    print(f"Total iterations: {total}")
    print(f"Divergences found: {len(divergences)}")

    if divergences:
        # Deduplicate by minimal argv
        seen: set[str] = set()
        unique: list[dict] = []
        for d in divergences:
            key = f"{d['app']}:{d['minimal_argv']}"
            if key not in seen:
                seen.add(key)
                unique.append(d)

        print(f"Unique minimal reproducers: {len(unique)}")
        print()
        for j, d in enumerate(unique, 1):
            print(f"Reproducer {j} ({d['app']} app):")
            print(f"  argv: {d['minimal_argv']}")
            for line in d["description"].splitlines():
                print(f"  {line}")
            print()
    else:
        print("No divergences found.")

    _cleanup_go_cache()
    return divergences


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Differential argv fuzzer for strictcli"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        required=True,
        help="Number of random inputs per app definition",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    divergences = fuzz(args.iterations, args.seed)
    sys.exit(1 if divergences else 0)


if __name__ == "__main__":
    main()
