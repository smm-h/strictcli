#!/usr/bin/env python3
"""Error parity check for strictcli conformance.

Extracts error message patterns from both the Python and Go implementations,
normalizes them to a common signature form, and verifies:
  1. Every Python error has a Go counterpart (and vice versa).
  2. Every error signature is covered by at least one conformance test case.

Exit 0 if all checks pass, exit 1 with a diff report otherwise.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFORMANCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFORMANCE_DIR.parent
PY_SOURCE = PROJECT_ROOT / "python" / "strictcli" / "__init__.py"
GO_STRICTCLI = PROJECT_ROOT / "go" / "strictcli" / "strictcli.go"
GO_PARSE = PROJECT_ROOT / "go" / "strictcli" / "parse.go"
CASES_DIR = CONFORMANCE_DIR / "cases"

# ---------------------------------------------------------------------------
# Known exclusions -- errors that intentionally exist in only one impl
# or whose signature form differs in ways normalization cannot reconcile.
# ---------------------------------------------------------------------------

# Python-only: errors that have no Go counterpart by design
PY_ONLY_EXCLUSIONS: dict[str, str] = {
    # Python validates handler signatures at registration time; Go uses
    # map[string]interface{} so there is no parameter-level mismatch to catch.
    'command *: handler missing parameter * for flag *':
        "Go uses map[string]interface{} kwargs, no handler signature validation",
    'command *: handler missing parameter * for arg *':
        "Go uses map[string]interface{} kwargs, no handler signature validation",
    'command *: handler has extra parameter * not matching any flag or arg':
        "Go uses map[string]interface{} kwargs, no handler signature validation",
    # Python raises ValueError for invalid type; Go uses typed constructors
    'Flag.type must be str, bool, or int, got *':
        "Go uses typed constructors (StringFlag/BoolFlag/IntFlag), no runtime type check",
    # Python validates default type for int flags; Go checks differently
    'Flag *: type=int requires an int default, got *':
        "Go validates via typed assertion with %T format verb",
    # Python validates choices element types generically
    'Flag *: choice * is not of type *':
        "Go validates choices with type-specific messages (str/int)",
    # _strict_int internal errors -- surfaced through 'expected integer' at parse level
    'invalid literal for int() with base 10: *':
        "Python internal ValueError from _strict_int, surfaces as 'expected integer'",
    'integer out of range':
        "Python internal ValueError from _strict_int, surfaces as 'expected integer'",
    # Python _require_non_empty_str uses generic {class_name}.{field_name} pattern
    '*.* must be a non-empty string':
        "Python uses generic _require_non_empty_str; Go has entity-specific messages",
    # Python Command.__post_init__ calls _require_non_empty_str
    'Command.help must be a non-empty string':
        "Python dataclass __post_init__; Go uses 'missing help text' message",
}

# Go-only: errors that have no Python counterpart by design
GO_ONLY_EXCLUSIONS: dict[str, str] = {
    # Go has type-specific choice validation messages that Python covers generically
    'Flag *: choice * is not of type str':
        "Go type-specific choice validation (Python uses generic pattern)",
    'Flag *: choice * is not of type int':
        "Go type-specific choice validation (Python uses generic pattern)",
    # Go validates int default type with %T; Python uses __name__
    'Flag *: type=int requires an int default, got *':
        "Go uses %T format verb; Python uses type(x).__name__",
    # Go has entity-specific help validation messages; Python uses generic
    # _require_non_empty_str producing '{class_name}.{field_name} must be...'
    'App.help must be a non-empty string':
        "Go entity-specific; Python generic '*.* must be a non-empty string'",
    'Arg.help must be a non-empty string':
        "Go entity-specific; Python generic '*.* must be a non-empty string'",
    'Flag.help must be a non-empty string':
        "Go entity-specific; Python generic '*.* must be a non-empty string'",
    'Group.help must be a non-empty string':
        "Go entity-specific; Python generic '*.* must be a non-empty string'",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_raise_arg(source: str, pos: int) -> str | None:
    """Given a position right after 'raise ExcType(', extract the argument.

    Uses parenthesis counting to find the matching ')'.
    Returns the content between the parens (exclusive).
    """
    depth = 1
    i = pos
    while i < len(source) and depth > 0:
        ch = source[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch in ('"', "'"):
            # Skip over string literals
            quote = ch
            i += 1
            while i < len(source) and source[i] != quote:
                if source[i] == "\\":
                    i += 1  # skip escaped char
                i += 1
        i += 1
    if depth == 0:
        return source[pos : i - 1]
    return None


def _extract_string_literals(arg_text: str) -> str | None:
    """Extract and concatenate all string literal pieces from a raise argument.

    Handles: f"...", f'...', "...", '...' and implicit concatenation.
    Returns the combined template string, or None if no strings found.
    """
    parts: list[str] = []
    is_fstring = False
    i = 0
    text = arg_text.strip()

    while i < len(text):
        # Skip whitespace and newlines
        if text[i] in " \t\n\r":
            i += 1
            continue

        # Check for f-string prefix
        if text[i] == "f" and i + 1 < len(text) and text[i + 1] in ('"', "'"):
            is_fstring = True
            i += 1
            # Fall through to string extraction below

        if text[i] in ('"', "'"):
            quote = text[i]
            i += 1
            part = []
            while i < len(text) and text[i] != quote:
                if text[i] == "\\":
                    part.append(text[i + 1])
                    i += 2
                else:
                    part.append(text[i])
                    i += 1
            if i < len(text):
                i += 1  # skip closing quote
            parts.append("".join(part))
            continue

        # Skip anything else (e.g., the + operator between string parts,
        # or expressions like ", ".join(...))
        # If we hit a non-string expression, stop -- the rest is code, not literal
        if parts:
            break
        i += 1

    if not parts:
        return None
    return "".join(parts)


# ---------------------------------------------------------------------------
# 1. Extract error patterns from Python source
# ---------------------------------------------------------------------------

def extract_python_errors(source: str) -> list[tuple[str, str]]:
    """Extract (category, format_string) pairs from Python source.

    Categories: 'parse' for _ParseError, 'registration' for ValueError.
    """
    results: list[tuple[str, str]] = []

    # Find all raise _ParseError(...) and raise ValueError(...)
    pattern = re.compile(r'raise\s+(_ParseError|ValueError)\(')
    for m in pattern.finditer(source):
        exc_type = m.group(1)
        category = "parse" if exc_type == "_ParseError" else "registration"
        arg_start = m.end()
        arg_text = _extract_raise_arg(source, arg_start)
        if arg_text is None:
            continue
        fmt_str = _extract_string_literals(arg_text)
        if fmt_str is None:
            continue
        results.append((category, fmt_str))

    return results


# ---------------------------------------------------------------------------
# 2. Extract error patterns from Go source
# ---------------------------------------------------------------------------

def extract_go_errors(strictcli_src: str, parse_src: str) -> list[tuple[str, str]]:
    """Extract (category, format_string) pairs from Go source.

    Categories: 'registration' for panic(), 'parse' for error string returns.
    """
    results: list[tuple[str, str]] = []

    # --- Registration errors from strictcli.go ---

    # panic(fmt.Sprintf("...", args)) -- allow whitespace/newlines before the quote
    panic_sprintf = re.compile(
        r'panic\(fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in panic_sprintf.finditer(strictcli_src):
        results.append(("registration", m.group(1)))

    # panic("...")
    panic_plain = re.compile(
        r'panic\("((?:[^"\\]|\\.)*)"\)',
    )
    for m in panic_plain.finditer(strictcli_src):
        results.append(("registration", m.group(1)))

    # --- Parse errors from parse.go ---
    # return nil, nil, fmt.Sprintf("...", args)
    parse_sprintf_3 = re.compile(
        r'return\s+nil,\s*nil,\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_sprintf_3.finditer(parse_src):
        results.append(("parse", m.group(1)))

    # --- Parse errors from strictcli.go (extractGlobalFlags and doParse) ---
    for m in parse_sprintf_3.finditer(strictcli_src):
        results.append(("parse", m.group(1)))

    # parseErr: fmt.Sprintf("...", args)
    parse_err_sprintf = re.compile(
        r'parseErr:\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_err_sprintf.finditer(strictcli_src):
        results.append(("parse", m.group(1)))

    # return nil, fmt.Sprintf("...", args) -- parseGlobalFlagValue
    parse_sprintf_2 = re.compile(
        r'return\s+nil,\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_sprintf_2.finditer(strictcli_src):
        results.append(("parse", m.group(1)))

    return results


# ---------------------------------------------------------------------------
# 3. Normalize to common signatures
# ---------------------------------------------------------------------------

def normalize_python(fmt_str: str) -> str:
    """Normalize a Python f-string template to a signature.

    Replaces {anything} (including {x!r}, {x!s}) with *.
    Then normalizes quoted placeholders: '*' and "*" become *.
    If the string ends with a trailing space (indicating truncated
    concatenation with a dynamic part), append * to represent it.
    """
    sig = re.sub(r"\{[^}]*\}", "*", fmt_str)
    # Normalize quoted * placeholders
    sig = re.sub(r"""['"](\*)['""]""", r"\1", sig)
    sig = re.sub(r"""['"](\*)['"']""", r"\1", sig)
    # Trailing space indicates truncated string concatenation (e.g., f"..." + expr)
    if sig.endswith(" "):
        sig = sig + "*"
    return sig


def normalize_go(fmt_str: str) -> str:
    """Normalize a Go fmt.Sprintf format string to a signature.

    Replaces %s, %d, %v, %q, %T with *.
    %q produces a Go-quoted string (with surrounding double quotes), so we
    treat it like * rather than "*".
    Then normalizes quoted placeholders: '*' becomes *.
    """
    sig = re.sub(r"%[sdvqT]", "*", fmt_str)
    # Normalize surrounding quotes on placeholders: '*' -> *
    sig = re.sub(r"'(\*)'", r"\1", sig)
    return sig


def deduplicate_signatures(
    items: list[tuple[str, str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """Deduplicate by signature, keeping track of origins.

    Input: list of (category, raw_pattern, signature)
    Returns: {signature: [(category, raw_pattern), ...]}
    """
    result: dict[str, list[tuple[str, str]]] = {}
    for cat, raw, sig in items:
        if sig not in result:
            result[sig] = []
        entry = (cat, raw)
        if entry not in result[sig]:
            result[sig].append(entry)
    return result


# ---------------------------------------------------------------------------
# 4. Check test coverage
# ---------------------------------------------------------------------------

def extract_test_stderr(cases_dir: Path) -> list[str]:
    """Extract all stderr assertion strings from conformance test cases."""
    assertions: list[str] = []
    for json_file in sorted(cases_dir.glob("*.json")):
        cases = json.loads(json_file.read_text())
        for case in cases:
            expect = case.get("expect", {})
            if "stderr_equals" in expect:
                assertions.append(expect["stderr_equals"])
            if "stderr_contains" in expect:
                val = expect["stderr_contains"]
                if isinstance(val, str):
                    assertions.append(val)
                elif isinstance(val, list):
                    assertions.extend(val)
    return assertions


def signature_matches_assertion(sig: str, assertion: str) -> bool:
    """Check if a signature could match a concrete stderr assertion.

    Converts the signature to a regex where * matches any non-empty substring,
    then checks if the assertion contains a match.
    """
    parts = sig.split("*")
    escaped = [re.escape(p) for p in parts]
    pattern = ".+?".join(escaped)
    try:
        return bool(re.search(pattern, assertion))
    except re.error:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    py_source = PY_SOURCE.read_text()
    go_strictcli_source = GO_STRICTCLI.read_text()
    go_parse_source = GO_PARSE.read_text()

    # Extract raw error patterns
    py_raw = extract_python_errors(py_source)
    go_raw = extract_go_errors(go_strictcli_source, go_parse_source)

    # Normalize to signatures
    py_items = [(cat, raw, normalize_python(raw)) for cat, raw in py_raw]
    go_items = [(cat, raw, normalize_go(raw)) for cat, raw in go_raw]

    py_sigs = deduplicate_signatures(py_items)
    go_sigs = deduplicate_signatures(go_items)

    all_errors: list[str] = []

    # --- Check 1: Python signatures not in Go ---
    py_only = set(py_sigs.keys()) - set(go_sigs.keys())
    for sig in sorted(py_only):
        if sig in PY_ONLY_EXCLUSIONS:
            continue
        origins = py_sigs[sig]
        raw_examples = ", ".join(repr(raw) for _, raw in origins[:2])
        all_errors.append(
            f"Python-only error (no Go match): {sig!r} "
            f"(from: {raw_examples})"
        )

    # --- Check 2: Go signatures not in Python ---
    go_only = set(go_sigs.keys()) - set(py_sigs.keys())
    for sig in sorted(go_only):
        if sig in GO_ONLY_EXCLUSIONS:
            continue
        origins = go_sigs[sig]
        raw_examples = ", ".join(repr(raw) for _, raw in origins[:2])
        all_errors.append(
            f"Go-only error (no Python match): {sig!r} "
            f"(from: {raw_examples})"
        )

    # --- Check 3: Test coverage ---
    test_assertions = extract_test_stderr(CASES_DIR)
    all_sigs = set(py_sigs.keys()) | set(go_sigs.keys())

    # Exclude signatures that are in the exclusion lists (one-impl-only by design)
    excluded_sigs = set(PY_ONLY_EXCLUSIONS.keys()) | set(GO_ONLY_EXCLUSIONS.keys())

    uncovered: list[str] = []
    for sig in sorted(all_sigs - excluded_sigs):
        covered = any(
            signature_matches_assertion(sig, assertion)
            for assertion in test_assertions
        )
        if not covered:
            uncovered.append(sig)

    for sig in uncovered:
        sources = []
        if sig in py_sigs:
            sources.append("Python")
        if sig in go_sigs:
            sources.append("Go")
        all_errors.append(
            f"Uncovered error signature: {sig!r} "
            f"(in: {', '.join(sources)})"
        )

    if all_errors:
        print(f"Error parity check FAILED ({len(all_errors)} issue(s)):\n")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    # Summary on success
    matched = set(py_sigs.keys()) & set(go_sigs.keys())
    py_excl = len([s for s in py_only if s in PY_ONLY_EXCLUSIONS])
    go_excl = len([s for s in go_only if s in GO_ONLY_EXCLUSIONS])
    covered_count = len(all_sigs - excluded_sigs - set(uncovered))

    print("Error parity check passed.")
    print(f"  Matched signatures: {len(matched)}")
    print(f"  Python-only (excluded): {py_excl}")
    print(f"  Go-only (excluded): {go_excl}")
    print(f"  Test coverage: {covered_count}/{len(all_sigs - excluded_sigs)} signatures covered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
