#!/usr/bin/env python3
"""Declare the mandatory presence fact on every case flag and every case arg.

The presence declaration (effects contract §23) makes every flag and every
positional arg state exactly one of three facts at registration: `required`,
`optional`, or a `default` value. Cases written before the round declared none
of them, so every one of them now fails registration with
`presence is undeclared`. This codemod writes the fact each declaration already
had, derived from the pre-round semantics rather than guessed:

| Pre-round shape | Written presence | Why |
|---|---|---|
| `default_relative_to_root` | `default` | the RelativeToRoot marker IS a default declaration (§23.5's infra row) |
| `default: null` | `optional` (key dropped) | Go's `Default(nil)` / TS's `default: null` delivered a real not-provided; §23.1 refuses the value-shaped spelling and redirects to this one |
| `default: <value>` | `default` | unchanged fact, now stated |
| a mutex member with no default | `optional` | §23.4 deletes the parse-time member exemption; the member's own declaration is what says it may be absent, and §23.5's mutex row makes `required` a registration error there |
| anything else | `required` | all three implementations required a flag that declared no default, so this is the fact the case already exercised |

Args take the same treatment through the deleted `required` key: `required:
false` becomes `optional` (or `default` when a default sits beside it), and
`required: true`/absent becomes `required`.

Two shapes this codemod deliberately does NOT reason about, because they are
semantic rather than mechanical and are hand-reviewed after it runs:

- a compound (list/dict/repeatable) flag with no declared default, which used
  to get the framework's silent `[]`/`{}` and now must declare one when the
  case asserts empty-collection delivery (§23.5's compound rows);
- a case that omits a flag from its argv and asserts something other than the
  required error, which wants `optional` rather than the `required` written
  here.

Idempotent: a declaration that already carries `presence` is left alone.

    python scripts/declare_presence.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def _with_presence(decl: dict, presence: str) -> dict:
    """Return decl with `presence` inserted directly after `help`."""
    out: dict = {}
    for key, value in decl.items():
        if key == "default" and presence == "optional":
            # The null-valued default is not a spelling of optionality (§23.1):
            # the key goes, and `presence: "optional"` replaces it.
            continue
        if key == "required":
            # The arg-side `required` key is deleted, not kept beside presence.
            continue
        out[key] = value
        if key == "help":
            out["presence"] = presence
    if "presence" not in out:
        out["presence"] = presence
    return out


def _flag_presence(flag: dict, *, mutex_member: bool) -> str:
    if "default_relative_to_root" in flag:
        return "default"
    if "default" in flag:
        return "optional" if flag["default"] is None else "default"
    return "optional" if mutex_member else "required"


def _arg_presence(arg: dict) -> str:
    if "default" in arg:
        return "optional" if arg["default"] is None else "default"
    if arg.get("required", True) is False:
        return "optional"
    return "required"


def _migrate_flags(flags: list, *, mutex_member: bool) -> tuple[list, int]:
    changed = 0
    out = []
    for flag in flags:
        if "presence" in flag:
            out.append(flag)
            continue
        out.append(_with_presence(flag, _flag_presence(flag, mutex_member=mutex_member)))
        changed += 1
    return out, changed


def _migrate_command(cmd: dict) -> int:
    changed = 0
    if "flags" in cmd:
        cmd["flags"], n = _migrate_flags(cmd["flags"], mutex_member=False)
        changed += n
    for flag_set in cmd.get("flag_sets", []) or []:
        flag_set["flags"], n = _migrate_flags(flag_set["flags"], mutex_member=False)
        changed += n
    for group in cmd.get("mutex", []) or []:
        group["flags"], n = _migrate_flags(group["flags"], mutex_member=True)
        changed += n
    if "args" in cmd:
        out = []
        for arg in cmd["args"]:
            if "presence" in arg:
                out.append(arg)
                continue
            out.append(_with_presence(arg, _arg_presence(arg)))
            changed += 1
        cmd["args"] = out
    return changed


def _migrate_container(node: dict) -> int:
    """Walk an app or group entry, migrating every command it reaches."""
    changed = 0
    for cmd in node.get("commands", []) or []:
        changed += _migrate_command(cmd)
    for group in node.get("groups", []) or []:
        changed += _migrate_container(group)
    return changed


def migrate(path: Path, *, write: bool) -> int:
    cases = json.loads(path.read_text())
    changed = 0
    for case in cases:
        app = case.get("app", {})
        if "global_flags" in app:
            app["global_flags"], n = _migrate_flags(app["global_flags"], mutex_member=False)
            changed += n
        changed += _migrate_container(app)
    if changed and write:
        path.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    total = 0
    for path in sorted(CASES_DIR.glob("*.json")):
        n = migrate(path, write=not args.check)
        if n:
            total += n
            print(f"{path.name}: {n} declaration(s)")
    verb = "would declare" if args.check else "declared"
    print(f"{verb} presence on {total} declaration(s)")
    if args.check and total:
        sys.exit(1)


if __name__ == "__main__":
    main()
