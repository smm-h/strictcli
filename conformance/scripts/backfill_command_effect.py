#!/usr/bin/env python3
"""Backfill the mandatory `effect` classification on conformance case commands.

Command classification is mandatory (effects contract §1.1), so every
non-deprecated command entry in `cases/*.json` must carry `effect`. Deprecated
entries are classification-exempt and must NOT carry it.

The default this script writes is `read_only`, and that is the correct default
for a backfill rather than a convenience: a `mutating` command is subject to the
confirm protocol (§8), which on the non-TTY subprocess the conformance runner
spawns would turn every pre-existing case into
`error: stdin is not interactive; pass --yes to confirm`. The generated handlers
issue no effects, so read-only enforcement (§9.1) never fires on them either.

Idempotent: entries that already declare `effect` are left alone. Re-run it
after adding case files that forgot the field.

    python scripts/backfill_command_effect.py [--effect read_only|mutating]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def _walk_commands(container: dict):
    """Yield every command entry reachable from an app or group definition."""
    for cmd in container.get("commands", []) or []:
        yield cmd
    for group in container.get("groups", []) or []:
        yield from _walk_commands(group)


def backfill(path: Path, effect: str) -> int:
    cases = json.loads(path.read_text())
    added = 0
    for case in cases:
        for cmd in _walk_commands(case.get("app", {})):
            if cmd.get("deprecated") is True:
                # Classification-exempt (§1.1); passing one is a hard error.
                cmd.pop("effect", None)
                continue
            if "effect" in cmd:
                continue
            # Insert right after `help` so the serialized order reads naturally.
            rebuilt = {}
            for key, value in cmd.items():
                rebuilt[key] = value
                if key == "help":
                    rebuilt["effect"] = effect
            if "effect" not in rebuilt:
                rebuilt["effect"] = effect
            cmd.clear()
            cmd.update(rebuilt)
            added += 1
    if added:
        path.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--effect",
        choices=["read_only", "mutating"],
        default="read_only",
        help="classification to write on entries that lack one",
    )
    args = ap.parse_args()

    total = 0
    for path in sorted(CASES_DIR.glob("*.json")):
        added = backfill(path, args.effect)
        if added:
            print(f"{path.name}: +{added}")
        total += added
    print(f"total: {total} command entries classified {args.effect!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
