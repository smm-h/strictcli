#!/usr/bin/env python3
"""Differential argv fuzzer for strictcli conformance.

Generates random argv sequences and runs them against every registered
implementation (Python, Go, TypeScript) of the same app definition, then
compares their results N-way. A divergence is any disagreement in exit code, or
in stdout when all implementations exit 0; the odd-one-out is identified by
majority. Divergences are recorded and minimized.

Execution reuses run.py's target machinery: the Python reference script is
generated via ref_python codegen, while Go and TypeScript run through the same
runtime harnesses run.py uses (the `conformance/harness` binary and
`conformance/harness_ts/main.js`, both reading the app definition from the
CONFORMANCE_APP_DEF env var). Harnesses are built once per run.

Usage:
    python conformance/fuzz.py --iterations 1000
    python conformance/fuzz.py --iterations 100 --seed 42
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time

# Reuse run.py's target descriptors, harness builds, and N-way divergence
# reporting rather than duplicating any of it here.
from run import (
    CONFORMANCE_DIR,
    TARGETS,
    _ensure_harness,
    _ensure_ts_harness,
    _normalize,
    _normalize_temp_paths,
    _stream_divergence,
)

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
            "effect": "read_only",
            "flags": [
                {
                    "name": "name",
                    "type": "str",
                    "help": "a name",
                    "presence": "default",
                    "default": "world",
                },
                {
                    "name": "chatter",
                    "type": "bool",
                    "help": "chatter output",
                    "presence": "optional",
                },
            ],
            "handler_prints": "run name={name} chatter={chatter}",
        },
    ],
}

COMPLEX_APP: dict = {
    "name": "fuzzapp",
    "version": "2.0.0",
    "help": "a complex app for fuzzing",
    "global_flags": [
        {
            "name": "chatter",
            "type": "bool",
            "help": "chatter output",
            "presence": "optional",
        },
    ],
    "commands": [
        {
            "name": "raw",
            "help": "passthrough command",
            "effect": "read_only",
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
                    "effect": "read_only",
                    "flags": [
                        {
                            "name": "target",
                            "type": "str",
                            "help": "deploy target",
                            "presence": "required",
                            "choices_str": ["prod", "staging"],
                        },
                        {
                            "name": "count",
                            "type": "int",
                            "help": "number of migrations",
                            "presence": "default",
                            "default": 1,
                        },
                        {
                            "name": "pretend",
                            "type": "bool",
                            "help": "pretend mode",
                            "presence": "optional",
                        },
                    ],
                    "args": [
                        {
                            "name": "path",
                            "help": "migration path",
                            "presence": "required",
                        },
                    ],
                    "handler_prints": "migrate target={target} count={count} pretend={pretend} path={path} chatter={chatter}",
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
# Execution (through run.py's runtime-harness target machinery)
# ---------------------------------------------------------------------------

TIMEOUT = 5

# Result of running one target: (exit_code, stdout, stderr). Exit code -1 means
# the run timed out.
RunResult = tuple[int, str, str]


def _run(target: str, app_def: dict, argv: list[str]) -> RunResult:
    """Run one implementation of `app_def` with `argv`. Returns (exit, out, err).

    Uses run.py's target descriptor to prepare the command (Python: ref_python
    codegen; Go/TypeScript: the runtime harness reading CONFORMANCE_APP_DEF).
    """
    prep = TARGETS[target].prepare(app_def, argv)
    env = os.environ.copy()
    env.update(prep.extra_env)
    try:
        result = subprocess.run(
            prep.argv,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONFORMANCE_DIR),
            timeout=TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    finally:
        for path in prep.cleanup_paths:
            if path is not None and os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# Divergence detection (N-way, odd-one-out by majority)
# ---------------------------------------------------------------------------


def _check_divergence(results: dict[str, RunResult]) -> str | None:
    """Return a description of the N-way divergence, or None if all agree.

    Compares exit codes across all targets; when every target exits 0, also
    compares normalized stdout. Uses run.py's _stream_divergence to identify the
    odd one(s) out by majority. A trailing per-target detail block aids
    reproduction.
    """
    exit_lines = _stream_divergence(
        "exit_code", {t: str(r[0]) for t, r in results.items()}
    )
    stdout_lines: list[str] = []
    if all(r[0] == 0 for r in results.values()):
        stdout_lines = _stream_divergence(
            "stdout",
            {t: _normalize_temp_paths(_normalize(r[1])) for t, r in results.items()},
        )
    if not exit_lines and not stdout_lines:
        return None

    lines = exit_lines + stdout_lines
    lines.append("  per-target detail:")
    for t in sorted(results):
        exit_code, stdout, stderr = results[t]
        lines.append(
            f"    {t}: exit={exit_code} "
            f"stdout={stdout.rstrip()!r} stderr={stderr.rstrip()!r}"
        )
    return "\n".join(lines)


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
    argv: list[str],
    target_names: list[str],
) -> list[str]:
    """Remove tokens one at a time, keeping the smallest argv that still diverges."""
    best = list(argv)

    changed = True
    while changed:
        changed = False
        for i in range(len(best)):
            candidate = best[:i] + best[i + 1:]
            results = {t: _run(t, app_def, candidate) for t in target_names}
            if _check_divergence(results):
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

    target_names = list(TARGETS)
    print(f"Targets: {', '.join(target_names)}")

    # Build the runtime harnesses once for the whole run (Python needs none).
    print("Building Go harness...", flush=True)
    _ensure_harness()
    print("Building TypeScript dist...", flush=True)
    _ensure_ts_harness()
    print()

    divergences: list[dict] = []
    generators = {
        "simple": _gen_argv_simple,
        "complex": _gen_argv_complex,
    }

    total = 0
    for label, app_def in APP_DEFS:
        gen = generators[label]
        print(f"--- Fuzzing '{label}' app ({iterations} iterations) ---")

        for i in range(1, iterations + 1):
            argv = gen(rng)
            results = {t: _run(t, app_def, argv) for t in target_names}

            desc = _check_divergence(results)
            if desc is not None:
                # Minimize
                minimal = _minimize(app_def, argv, target_names)
                # Re-run minimal to get fresh description
                min_results = {t: _run(t, app_def, minimal) for t in target_names}
                min_desc = _check_divergence(min_results) or desc

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
