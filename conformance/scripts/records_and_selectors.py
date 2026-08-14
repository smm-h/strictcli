#!/usr/bin/env python3
"""Migrate the case corpus to record-shaped `choices_<T>` entries.

One-time migration (contract §24.2): the bare-value `choices=` entry is
deleted, so every case's `choices_str` / `choices_int` / `choices_float` list
becomes a list of `{"value": ...}` records. Help is never added here -- an
entry that declared none still declares none, which is what keeps §24.10's
one-line rendering the default.

Mutex groups are NOT touched by this script: each surviving group is a
declaration whose replacement is a member-spelled selector with different
delivery, so those case files are migrated by hand.
"""
from __future__ import annotations

import json
import pathlib
import sys

CASES = pathlib.Path(__file__).resolve().parent.parent / "cases"
KEYS = ("choices_str", "choices_int", "choices_float")


def convert(node: object) -> bool:
    """Rewrite every bare choices list under `node`. Returns True if changed."""
    changed = False
    if isinstance(node, dict):
        for key in KEYS:
            entries = node.get(key)
            if isinstance(entries, list) and any(
                not isinstance(e, dict) for e in entries
            ):
                node[key] = [
                    e if isinstance(e, dict) else {"value": e} for e in entries
                ]
                changed = True
        for value in node.values():
            changed |= convert(value)
    elif isinstance(node, list):
        for item in node:
            changed |= convert(item)
    return changed


def main(argv: list[str]) -> int:
    targets = [CASES / name for name in argv] if argv else sorted(CASES.glob("*.json"))
    for path in targets:
        doc = json.loads(path.read_text())
        if convert(doc):
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
            print(f"rewrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
