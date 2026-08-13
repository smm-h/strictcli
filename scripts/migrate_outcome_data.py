#!/usr/bin/env python3
"""One-shot migration: outcome(data=...) -> ctx.payload(...) + payload_schema.

Rewrites `return strictcli.outcome(data=X)` / `return sc.outcome(exit_code=N,
data=X)` into a `ctx.payload(X)` call followed by the exit-code-only outcome,
and adds `payload_schema={}` to the command decorator of every function whose
body then calls ctx.payload. Run once per file; idempotent enough to re-run.

Usage: migrate_outcome_data.py FILE [FILE ...]
"""
from __future__ import annotations

import ast
import re
import sys


def _match_paren(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    while i < len(text):
        c = text[i]
        if c in "\"'":
            quote = c
            triple = text[i:i + 3] in ('"""', "'''")
            if triple:
                end = text.find(text[i:i + 3], i + 3)
                i = (end + 3) if end != -1 else len(text)
                continue
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("unbalanced")


CALL_RE = re.compile(r"(?P<pre>\breturn\s+)(?P<mod>\w+)\.outcome\(")


def rewrite_calls(src: str) -> str:
    out = src
    while True:
        changed = False
        for m in CALL_RE.finditer(out):
            open_idx = m.end() - 1
            close_idx = _match_paren(out, open_idx)
            args = out[open_idx + 1:close_idx]
            if "data=" not in args:
                continue
            # split top-level args
            parts = []
            depth = 0
            cur = ""
            i = 0
            while i < len(args):
                c = args[i]
                if c in "\"'":
                    quote = c
                    cur += c
                    i += 1
                    while i < len(args):
                        cur += args[i]
                        if args[i] == "\\":
                            cur += args[i + 1]
                            i += 2
                            continue
                        if args[i] == quote:
                            i += 1
                            break
                        i += 1
                    continue
                if c in "([{":
                    depth += 1
                elif c in ")]}":
                    depth -= 1
                if c == "," and depth == 0:
                    parts.append(cur)
                    cur = ""
                    i += 1
                    continue
                cur += c
                i += 1
            if cur.strip():
                parts.append(cur)
            data_expr = None
            keep = []
            for p in parts:
                ps = p.strip()
                if ps.startswith("data="):
                    data_expr = ps[len("data="):].strip()
                else:
                    keep.append(ps)
            if data_expr is None:
                continue
            line_start = out.rfind("\n", 0, m.start()) + 1
            indent = out[line_start:m.start()]
            mod = m.group("mod")
            rest = ", ".join(keep)
            replacement = (
                f"{indent}ctx.payload({data_expr})\n"
                f"{indent}return {mod}.outcome({rest})"
            )
            out = out[:line_start] + replacement + out[close_idx + 1:]
            changed = True
            break
        if not changed:
            return out


DECOR_RE = re.compile(r"\.command\(|\.group\(")


def add_payload_schema(src: str) -> str:
    tree = ast.parse(src)
    lines = src.split("\n")
    inserts = []  # (lineno of decorator call start, col of '(' )

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            body_src = ast.get_source_segment(src, node) or ""
            if "ctx.payload(" not in body_src:
                self.generic_visit(node)
                return
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                if isinstance(func, ast.Attribute) and func.attr == "command":
                    if any(
                        kw.arg == "payload_schema" for kw in dec.keywords
                    ):
                        continue
                    inserts.append((dec.lineno, dec.col_offset, dec))
            self.generic_visit(node)

    V().visit(tree)
    # insert as a trailing keyword before the decorator call's closing paren
    for lineno, col, dec in sorted(inserts, key=lambda t: -t[0]):
        # find the '(' after the decorator func
        start = sum(len(l) + 1 for l in lines[:lineno - 1]) + col
        open_idx = src.index("(", start)
        close_idx = _match_paren(src, open_idx)
        src = src[:close_idx] + ", payload_schema={}" + src[close_idx:]
        lines = src.split("\n")
    return src


def main() -> int:
    for path in sys.argv[1:]:
        src = open(path).read()
        new = rewrite_calls(src)
        if new != src:
            new = add_payload_schema(new)
        if new != src:
            open(path, "w").write(new)
            print(f"migrated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
