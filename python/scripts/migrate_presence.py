#!/usr/bin/env python3
"""Migrate flag declarations to the mandatory three-way presence declaration.

Contract §23 makes `presence="required"` / `presence="optional"` / `default=<value>`
mandatory on every flag, so a declaration that states none of the three stops
registering. This script rewrites the declarations that stated nothing, choosing
the spelling that preserves the behaviour they had before the round:

- a scalar flag with no default was required               -> presence="required"
- a repeatable / list[T] flag was silently forced to []    -> default=[]
- a dict[str, T] flag was silently forced to {}            -> default={}

Calls that already declare `presence=`, already declare `default=`, or forward
`**kwargs` are reported and left alone: the first two need nothing, and the third
cannot be decided from the call site.

Usage:
    python scripts/migrate_presence.py --report  <files...>
    python scripts/migrate_presence.py --write   <files...>
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

FLAG_CALLEES = {"flag", "Flag"}
ARG_CALLEES = {"arg", "Arg"}


def _callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _line_starts(data: bytes) -> list[int]:
    starts = [0]
    for i, b in enumerate(data):
        if b == 0x0A:
            starts.append(i + 1)
    return starts


def _offset(starts: list[int], lineno: int, col: int) -> int:
    return starts[lineno - 1] + col


def _is_dict_flag(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "type":
            src = ast.dump(kw.value)
            if "dict" in src.lower():
                return True
    return False


def _is_repeatable_flag(node: ast.Call) -> bool:
    for kw in node.keywords:
        if kw.arg == "repeatable" and isinstance(kw.value, ast.Constant):
            if kw.value.value is True:
                return True
        if kw.arg == "type":
            v = kw.value
            if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name):
                if v.value.id == "list":
                    return True
            if isinstance(v, ast.Name) and v.id == "list":
                return True
    return False


def _kw_span(starts: list[int], kw: ast.keyword) -> tuple[int, int]:
    return (
        _offset(starts, kw.lineno, kw.col_offset),
        _offset(starts, kw.value.end_lineno, kw.value.end_col_offset),
    )


def _drop_span(data: bytes, start: int, end: int) -> tuple[int, int]:
    """Widen a keyword's span to swallow one neighbouring comma separator."""
    j = end
    while j < len(data) and data[j : j + 1].isspace():
        j += 1
    if data[j : j + 1] == b",":
        j += 1
        while j < len(data) and data[j : j + 1] in (b" ", b"\t"):
            j += 1
        return start, j
    i = start
    while i > 0 and data[i - 1 : i].isspace():
        i -= 1
    if data[i - 1 : i] == b",":
        i -= 1
    return i, end


def plan(path: Path) -> tuple[list[tuple[int, int, str]], list[str]]:
    data = path.read_bytes()
    tree = ast.parse(data.decode("utf-8"), filename=str(path))
    starts = _line_starts(data)
    edits: list[tuple[int, int, str]] = []
    notes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _callee_name(node)
        if callee in ARG_CALLEES:
            kwnames = {kw.arg for kw in node.keywords}
            if None in kwnames or "presence" in kwnames:
                continue
            req_kw = next(
                (kw for kw in node.keywords if kw.arg == "required"), None,
            )
            has_default = "default" in kwnames
            if req_kw is None:
                if has_default:
                    continue
                tail = node.keywords[-1] if node.keywords else None
                last = tail.value if tail is not None else node.args[-1]
                pos = _offset(starts, last.end_lineno, last.end_col_offset)
                edits.append((pos, pos, ', presence="required"'))
                continue
            start, end = _kw_span(starts, req_kw)
            value = getattr(req_kw.value, "value", None)
            if has_default:
                # `required=False` plus a default spelled one fact across two
                # fields; the default is now the whole declaration.
                s, e = _drop_span(data, start, end)
                edits.append((s, e, ""))
            elif value is True:
                edits.append((start, end, 'presence="required"'))
            else:
                edits.append((start, end, 'presence="optional"'))
            continue
        if callee not in FLAG_CALLEES:
            continue
        kwnames = {kw.arg for kw in node.keywords}
        if None in kwnames:
            notes.append(f"{path}:{node.lineno}: **kwargs forwarding -- skipped")
            continue
        if "presence" in kwnames:
            continue
        if "default" in kwnames:
            for kw in node.keywords:
                if kw.arg == "default" and isinstance(kw.value, ast.Constant):
                    if kw.value.value is None:
                        # `default=None` never declared optionality; it is what
                        # the sites meant, so it becomes the one spelling of it.
                        start, end = _kw_span(starts, kw)
                        edits.append((start, end, 'presence="optional"'))
            continue
        if _is_dict_flag(node):
            addition = "default={}"
        elif _is_repeatable_flag(node):
            addition = "default=[]"
        else:
            addition = 'presence="required"'
        tail = node.keywords[-1] if node.keywords else None
        last = tail.value if tail is not None else (
            node.args[-1] if node.args else None
        )
        if last is None:
            notes.append(f"{path}:{node.lineno}: no arguments -- skipped")
            continue
        pos = _offset(starts, last.end_lineno, last.end_col_offset)
        edits.append((pos, pos, f", {addition}"))
    return edits, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("files", nargs="+")
    ns = ap.parse_args()
    total = 0
    for name in ns.files:
        path = Path(name)
        edits, notes = plan(path)
        for note in notes:
            print(note)
        if not edits:
            continue
        total += len(edits)
        print(f"{path}: {len(edits)} declaration(s)")
        if not ns.write:
            continue
        data = path.read_bytes()
        for start, end, text in sorted(edits, reverse=True):
            data = data[:start] + text.encode("utf-8") + data[end:]
        path.write_bytes(data)
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
