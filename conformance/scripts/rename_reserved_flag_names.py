#!/usr/bin/env python3
"""Rename conformance-case flags that collide with the reserved quartet.

`dry-run`, `yes`, `quiet` and `verbose` are reserved framework flag names
(effects contract §7.1) and the ban is unconditional at every level -- command
flags, flag-set flags, mutex-group flags and app global flags alike. Cases that
predate the ban used `verbose`, `quiet` and `dry-run` as ordinary bool flags,
which now hard-error at registration and would take the whole case with them.

Renaming preserves each case's actual subject (env parsing, mutex grammar,
dependency wiring, provenance, ...); the four ban cases are authored separately
in `cases/reserved_global_flags.json`.

The replacements are the SAME LENGTH as the names they replace, which is not
cosmetic: several cases assert column-aligned help output verbatim, and a
shorter name would silently shift every expected `Flags:` block.

The replacement is textual and whole-file on purpose. A case's expected stdout,
stderr and env-var names live in the same file as its flag declaration, so one
pass keeps declaration and expectation in lockstep -- including derived
spellings (`--no-verbose`, `MYAPP_VERBOSE`, `{verbose}` template refs).

    python scripts/rename_reserved_flag_names.py
"""

from __future__ import annotations

import sys
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"

# (old, new) textual substitutions, applied only to the listed files. `quiet`
# and `dry-run` are scoped because their letter sequences appear in unrelated
# prose elsewhere; `verbose` is distinctive enough to run corpus-wide.
SUBSTITUTIONS: list[tuple[str, str, list[str] | None]] = [
    ("verbose", "chatter", None),
    ("Verbose", "Chatter", None),
    ("VERBOSE", "CHATTER", None),
    ("quiet", "muted", ["mutex.json", "passthrough.json"]),
    ("QUIET", "MUTED", ["mutex.json", "passthrough.json"]),
    ("dry-run", "preview", ["help.json"]),
    ("dry_run", "preview", ["help.json"]),
]


def main() -> int:
    changed = 0
    for path in sorted(CASES_DIR.glob("*.json")):
        text = original = path.read_text()
        for old, new, files in SUBSTITUTIONS:
            if files is not None and path.name not in files:
                continue
            text = text.replace(old, new)
        if text != original:
            path.write_text(text)
            print(f"{path.name}: rewritten")
            changed += 1
    print(f"total: {changed} file(s) rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
