#!/usr/bin/env python3
"""Mechanical sweep: declare forwarding on commands whose handler takes ``**kwargs``.

Guard v2 removed the blanket ``**kwargs`` exemption from handler-signature
validation: a var-keyword handler is a registration error unless the command
declares forwarding. This script finds ``@x.command(...)`` decorators applied to
a function with a ``**kwargs`` parameter and inserts

    forwarding=strictcli.Forwarding(reason="<reason>"),

immediately before the ``help=`` argument.

Passthrough registrations are skipped: a passthrough handler's signature is
deliberately unpoliced, so it never needs the declaration. Sites that already
declare ``forwarding=`` are skipped, so re-running is a no-op.

Usage:
    scripts/add_forwarding_declaration.py --reason "why" FILE [FILE ...]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def _insertions(source: str, reason: str, qualifier: str) -> list[tuple[int, int, str]]:
    tree = ast.parse(source)
    points: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.args.kwarg is None:
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not isinstance(func, ast.Attribute) or func.attr != "command":
                continue
            kw_names = {kw.arg for kw in dec.keywords}
            if "forwarding" in kw_names or "passthrough" in kw_names:
                continue
            help_kw = next((kw for kw in dec.keywords if kw.arg == "help"), None)
            if help_kw is None:
                raise SystemExit(
                    f"command registration without help= at line {dec.lineno}"
                )
            text = f'forwarding={qualifier}Forwarding(reason="{reason}"), '
            points.append((help_kw.lineno, help_kw.col_offset, text))
    return points


def rewrite(path: Path, reason: str, qualifier: str) -> int:
    source = path.read_text()
    points = _insertions(source, reason, qualifier)
    if not points:
        return 0
    lines = source.splitlines(keepends=True)
    for lineno, col, text in sorted(points, reverse=True):
        line = lines[lineno - 1]
        lines[lineno - 1] = line[:col] + text + line[col:]
    path.write_text("".join(lines))
    return len(points)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reason", required=True,
                        help="the mandatory forwarding reason string")
    parser.add_argument("--qualifier", default="strictcli.",
                        help='module qualifier for Forwarding (default "strictcli.")')
    parser.add_argument("files", nargs="+", type=Path)
    ns = parser.parse_args(argv)

    total = 0
    for path in ns.files:
        n = rewrite(path, ns.reason, ns.qualifier)
        if n:
            print(f"{path}: {n} registration(s)")
        total += n
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
