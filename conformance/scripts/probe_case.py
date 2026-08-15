#!/usr/bin/env python3
"""Run one case definition against every target and print what each produced.

The corpus is written against pinned bytes, and the fastest honest way to learn
those bytes is to run the state rather than to guess it. This drives the same
`run.py` machinery the suite uses -- the Python reference script, the Go harness
binary and the TypeScript harness -- and prints each target's exit status,
stdout and stderr verbatim, without asserting anything.

    python scripts/probe_case.py <case-file.json> [--index N] [--name SUBSTR]

The case file is an ordinary corpus file (an array of cases). Anything the
runner's own `expect` block would have checked is ignored here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run as runner  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case_file")
    ap.add_argument("--index", type=int, default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--target", default=None)
    args = ap.parse_args()

    cases = json.loads(Path(args.case_file).read_text())
    selected = list(enumerate(cases))
    if args.index is not None:
        selected = [(args.index, cases[args.index])]
    if args.name is not None:
        selected = [(i, c) for i, c in selected if args.name in c["name"]]

    targets = [args.target] if args.target else list(runner.TARGETS)

    for i, case in selected:
        print("=" * 70)
        print(f"[{i}] {case['name']}")
        for target in targets:
            if case.get("targets") and target not in case["targets"]:
                continue
            ok, errors, result = runner._run_case(case, target)
            print(f"--- {target}: ok={ok} exit={None if result is None else result.returncode}")
            if result is not None:
                print(f"  stdout: {result.stdout!r}")
                print(f"  stderr: {result.stderr!r}")
            for e in errors:
                print(f"  ! {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
