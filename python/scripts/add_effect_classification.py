#!/usr/bin/env python3
"""Mechanical sweep: add the mandatory ``effect=`` classification to command
registrations that lack it.

The effects regime makes ``effect="read_only" | "mutating"`` mandatory on every
command. This script rewrites ``.command(...)`` call sites that do not already
declare it, inserting the keyword immediately before the (always present,
always keyword-passed) ``help=`` argument so the result stays readable:

    @app.command("deploy", effect="read_only", help="deploy the app")

Only ``.command(...)`` attribute calls are touched; ``.group(...)``,
``.deprecate(...)`` and everything else are left alone. Files are rewritten in
place. Re-running is a no-op (sites that already declare ``effect=`` are
skipped).

Usage:
    scripts/add_effect_classification.py [--effect read_only] FILE [FILE ...]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def _insertions(source: str, effect: str) -> list[tuple[int, int, str]]:
    """Return (lineno, col_offset, text) insertion points, one per call site."""
    tree = ast.parse(source)
    points: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "command":
            continue
        kw_names = {kw.arg for kw in node.keywords}
        if "effect" in kw_names:
            continue
        help_kw = next((kw for kw in node.keywords if kw.arg == "help"), None)
        if help_kw is None:
            raise SystemExit(
                f"command registration without help= at line {node.lineno}; "
                "insertion anchor missing"
            )
        points.append((help_kw.lineno, help_kw.col_offset, f'effect="{effect}", '))
    return points


def rewrite(path: Path, effect: str) -> int:
    source = path.read_text()
    points = _insertions(source, effect)
    if not points:
        return 0
    lines = source.splitlines(keepends=True)
    # Apply bottom-up so earlier offsets stay valid.
    for lineno, col, text in sorted(points, reverse=True):
        line = lines[lineno - 1]
        lines[lineno - 1] = line[:col] + text + line[col:]
    path.write_text("".join(lines))
    return len(points)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effect", default="read_only",
                        choices=["read_only", "mutating"],
                        help="classification to insert (default: read_only)")
    parser.add_argument("files", nargs="+", type=Path)
    ns = parser.parse_args(argv)

    total = 0
    for path in ns.files:
        n = rewrite(path, ns.effect)
        if n:
            print(f"{path}: {n} registration(s)")
        total += n
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
