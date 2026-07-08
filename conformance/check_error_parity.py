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
GO_CHECK = PROJECT_ROOT / "go" / "strictcli" / "check.go"
GO_CHECK_RUNNER = PROJECT_ROOT / "go" / "strictcli" / "check_runner.go"
GO_CHECK_PUBLIC = PROJECT_ROOT / "go" / "strictcli" / "check_public.go"
GO_TAGDSL = PROJECT_ROOT / "go" / "strictcli" / "tagdsl.go"
GO_CONFIG = PROJECT_ROOT / "go" / "strictcli" / "config.go"
GO_ROUTING = PROJECT_ROOT / "go" / "strictcli" / "routing.go"
GO_INVOKE = PROJECT_ROOT / "go" / "strictcli" / "invoke.go"
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
    # Python raises ValueError for invalid type; Go uses typed constructors.
    # Covers both the 3-type form (str/bool/int) and 4-type form (str/bool/int/float).
    'Flag.type must be str, bool, or int, got *':
        "Go uses typed constructors (StringFlag/BoolFlag/IntFlag/FloatFlag), no runtime type check",
    'Flag.type must be str, bool, int, or float, got *':
        "Go uses typed constructors (StringFlag/BoolFlag/IntFlag/FloatFlag), no runtime type check",
    # Python validates default type for int/float flags; Go checks differently
    'Flag *: type=int requires an int default, got *':
        "Go validates via typed assertion with %T format verb",
    'Flag *: type=float requires a float default, got *':
        "Go validates via typed assertion with %T format verb (float64)",
    # Python validates choices element types generically
    'Flag *: choice * is not of type *':
        "Go validates choices with type-specific messages (str/int/float)",
    # _strict_int internal errors -- surfaced through 'expected integer' at parse level
    'invalid literal for int() with base 10: *':
        "Python internal ValueError from _strict_int, surfaces as 'expected integer'",
    'integer out of range':
        "Python internal ValueError from _strict_int, surfaces as 'expected integer'",
    # _strict_float internal errors -- surfaced through _float_parse_error wrapper
    'invalid literal for float(): *':
        "Python internal ValueError from _strict_float, surfaces as 'expected float'",
    'NaN is not allowed':
        "Python internal ValueError from _strict_float, wrapped with flag prefix at call site",
    'Inf is not allowed':
        "Python internal ValueError from _strict_float, wrapped with flag prefix at call site",
    # Python _require_non_empty_str uses generic {class_name}.{field_name} pattern
    '*.* must be a non-empty string':
        "Python uses generic _require_non_empty_str; Go has entity-specific messages",
    # Python Command.__post_init__ calls _require_non_empty_str
    'Command.help must be a non-empty string':
        "Python dataclass __post_init__; Go uses 'missing help text' message",
    # Python uses {self.choices!r} which normalizes to * (no brackets);
    # Go uses [%s] which normalizes to [*]. Same runtime output; different
    # signature due to format string structure.
    'Flag *: default * is not in choices *':
        "Python f-string normalizes without brackets; Go counterpart is 'Flag *: default * is not in choices [*]'",
    # Python validates CheckResult fields at construction; Go uses typed struct
    'CheckResult.message must be a non-empty string':
        "Go uses typed struct fields; no runtime validation needed",
    'CheckResult.status must be one of "pass", "fail", "warn", "skip", got *':
        "Go uses typed struct fields; no runtime validation needed",
    # Python validates Implies.value type at registration; Go uses typed bool field
    'command *: Implies value must be a bool, got *':
        "Go Implies struct has typed bool Value field; no runtime type check needed",
    # Python tag DSL uses tuple-based AST with runtime dispatch; Go uses typed interfaces
    'tag expression: unknown AST node *':
        "Python uses tuple-based AST with string dispatch; Go uses typed interfaces",
    # Python uses !r (single quotes), Go uses %q (double quotes) for config_format value
    'App.config_format must be "json" or "toml", got *':
        "Go uses fmt.Fprintf+os.Exit with %q quoting; Python uses ValueError with !r quoting",
    # Python uses field names (checks_path/checks_embed); Go uses option function names
    'cannot use both checks_path and checks_embed':
        "Go uses option function names (WithChecks/WithChecksEmbed); Python uses field names (checks_path/checks_embed)",
    # Python uses the field name (App.config_conflict_mode); Go uses the
    # option function name (WithConfigConflictMode). Same validation, same
    # runtime effect; the entity name differs by API-surface convention.
    'App.config_conflict_mode must be "cli-wins" or "error", got *':
        "Go counterpart is 'WithConfigConflictMode: mode must be ...' (option function name)",
    # Python validates unique as bool at registration; Go uses typed bool field
    'Flag *: unique must be True or False':
        "Go uses typed bool field for Unique; no runtime type check needed",
    # Python validates repeatable default element types generically
    'Flag *: default element * is not of type *':
        "Go validates default elements with type-specific messages (str/int/float)",
    # --- Compound type structural differences ---
    # Python uses generic {context}: patterns for compound type validation
    # (Flag/Arg prefix merged into context); Go uses typed constructors with
    # entity-specific messages (ListOf, DictOf, separate Arg vs Flag paths).
    '*: dict key type must be str, got *':
        "Python generic {context}: pattern; Go uses DictOf typed constructor",
    '*: dict type requires type arguments (e.g., dict[str, int]), got bare dict':
        "Python generic {context}: pattern; Go uses DictOf typed constructor",
    '*: dict type takes exactly two type arguments, got *':
        "Python generic {context}: pattern; Go uses DictOf typed constructor",
    '*: dict value type must be str, int, or float, got *':
        "Python generic {context}: pattern; Go uses DictOf typed constructor",
    '*: list item type must be str, int, or float, got *':
        "Python generic {context}: pattern; Go uses ListOf typed constructor",
    '*: list type requires an item type (e.g., list[int]), got bare list':
        "Python generic {context}: pattern; Go uses ListOf typed constructor",
    '*: list type takes exactly one type argument, got *':
        "Python generic {context}: pattern; Go uses ListOf typed constructor",
    '*: type must be str, bool, int, float, list[T], or dict[str, T], got *':
        "Python generic {context}: pattern; Go uses separate typed constructors",
    # Python has typed {context} validation for Flag compound type checks
    'Flag *: * is not of type float':
        "Python generic {context} pattern; Go uses typed constructors with separate messages",
    'Flag *: * is not of type int':
        "Python generic {context} pattern; Go uses typed constructors with separate messages",
    'Flag *: * is not of type str':
        "Python generic {context} pattern; Go uses typed constructors with separate messages",
    # --- Dict/list parse-time messages ---
    # Python dict flag parsing uses JSON-based key=value and JSON object parsing.
    # Go handles dict parsing differently with type-specific coercion in parse.go.
    '--*: JSON key must be a string, got *':
        "Python dict flag JSON parsing; Go handles via typed coercion in parse.go",
    '--*: JSON value for key * must be a number, got *':
        "Python dict flag JSON value validation; Go handles via typed coercion",
    '--*: JSON value for key * must be a string, got *':
        "Python dict flag JSON value validation; Go handles via typed coercion",
    '--*: JSON value for key * must be an integer, got *':
        "Python dict flag JSON value validation; Go handles via typed coercion",
    '--*: JSON value must be an object, got *':
        "Python dict flag JSON object validation; Go handles via typed coercion",
    '--*: duplicate key *':
        "Python dict flag duplicate key detection; Go handles via map overwrite",
    '--*: empty key in *':
        "Python dict flag empty key validation; Go handles differently",
    '--*: env var * must be a JSON object, got *':
        "Python dict flag env var validation; Go handles via typed coercion",
    '--*: expected key=value or JSON, got *':
        "Python dict flag format validation; Go handles via typed coercion",
    '--*: invalid JSON in env var *: *':
        "Python dict flag JSON parse error; Go handles via typed coercion",
    '--*: invalid JSON: *':
        "Python dict flag JSON parse error; Go handles via typed coercion",
    '--*: unsupported value type *':
        "Python dict flag unsupported type; Go handles via typed constructors",
    '--*: value for key *: *':
        "Python dict flag per-key value error; Go handles via typed coercion",
    # --- Arg compound type messages ---
    # Python uses same compound type validation for Arg as for Flag;
    # Go has separate Arg-specific messages with different wording.
    'Arg *: choice * is not of type *':
        "Go validates Arg choices with type-specific messages (str/int/float)",
    'Arg *: default * is not in choices *':
        "Python f-string normalizes without brackets; Go counterpart uses [%s]",
    'Arg *: dict type is not supported on args':
        "Go uses 'positional arguments' wording instead of 'args'",
    'Arg *: list item type must be str, int, or float, got *':
        "Python includes 'got' clause; Go omits it",
    'Arg *: list type on args requires variadic=True':
        "Go uses lowercase variadic=true; Python uses variadic=True",
    'Arg *: list type requires an item type (e.g., list[int]), got bare list':
        "Python includes full example; Go has different wording",
    'Arg *: list type takes exactly one type argument, got *':
        "Python generic pattern; Go has different wording",
    # --- Flag compound type Python-only messages ---
    # Python validates flag compound types with wording that doesn't match Go.
    'Flag *: dict default key * must be a string':
        "Python validates dict default keys; Go uses typed map[string]interface{} assertion",
    'Flag *: dict flag default must be a dict':
        "Python uses 'dict'; Go uses 'map[string]interface{}'",
    'Flag *: dict type cannot be combined with choices':
        "Go uses 'choices is incompatible with compound types (list/dict)'",
    'Flag *: dict type cannot be combined with repeatable=True':
        "Go forbids compound+repeatable differently; no direct counterpart",
    'Flag *: dict type cannot be combined with unique':
        "Go forbids compound+unique differently; no direct counterpart",
    'Flag *: dict type cannot use env_separator (env vars are parsed as JSON)':
        "Go validates list/env interaction differently; no direct counterpart",
    'Flag.type must be str, bool, int, float, list[T], or dict[str, T], got *':
        "Go uses typed constructors (ListOf/DictOf); no runtime type check needed",
    # --- Typed arg parse-time messages ---
    # Python's typed arg parsing produces 'argument' prefixed messages;
    # Go uses different wording ('expected X, got Y' at parse level).
    'argument *: *':
        "Python generic 'argument' prefix wrapper; Go produces typed errors at parse level",
    'argument *: expected float, got *':
        "Python typed arg float parsing; Go handles at parse level with different prefix",
    # --- Required-bool prefix structural difference ---
    # Go's applyFlagDefault uses a prefix parameter ("%sflag '--%s' ...") that
    # produces one format string per error type. The extractor sees "%sflag"
    # which normalizes to "*flag" -- a single Go signature covers both command
    # and global flags. Python uses separate literal messages for "flag" and
    # "global flag" prefixes. Same errors at runtime; signature mismatch due
    # to Go parameterized prefix vs Python literal prefix.
    "flag '--*' is required":
        "Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    "flag '--*' must be passed as --*":
        "Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    "flag '--*' must be passed as --* or --no-*":
        "Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    "global flag '--*' is required":
        "Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    "global flag '--*' must be passed as --*":
        "Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    "global flag '--*' must be passed as --* or --no-*":
        "Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
}

# Go-only: errors that have no Python counterpart by design
GO_ONLY_EXCLUSIONS: dict[str, str] = {
    # Go has type-specific choice validation messages that Python covers generically
    'Flag *: choice * is not of type str':
        "Go type-specific choice validation (Python uses generic pattern)",
    'Flag *: choice * is not of type int':
        "Go type-specific choice validation (Python uses generic pattern)",
    'Flag *: choice * is not of type float':
        "Go type-specific choice validation (Python uses generic pattern)",
    # Go validates int/float default type with %T; Python uses __name__
    'Flag *: type=int requires an int default, got *':
        "Go uses %T format verb; Python uses type(x).__name__",
    'Flag *: type=float requires a float64 default, got *':
        "Go uses 'float64' type name; Python uses 'float'",
    # Go has type-specific default element validation messages that Python covers generically
    'Flag *: default element * is not of type str':
        "Go type-specific default element validation (Python uses generic pattern)",
    'Flag *: default element * is not of type int':
        "Go type-specific default element validation (Python uses generic pattern)",
    'Flag *: default element * is not of type float':
        "Go type-specific default element validation (Python uses generic pattern)",
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
    # Go uses [%s] which normalizes to [*]; Python counterpart normalizes
    # without brackets. Same runtime output; different signature form.
    'Flag *: default * is not in choices [*]':
        "Go fmt.Sprintf normalizes with brackets; Python counterpart is 'Flag *: default * is not in choices *'",
    # Go has additional cycle detection messages from expansion phase and Kahn fallback
    'check dependency cycle detected involving *':
        "Go expansion-phase cycle detection; Python only reports cycles via path format",
    'check dependency cycle detected':
        "Go Kahn fallback when cycle path not found; Python always finds cycle path",
    # Go path.Match can return an error for invalid glob patterns
    'invalid glob pattern *: *':
        "Go-specific path.Match error; Python fnmatch never errors on patterns",
    # Go wraps float env var errors with a generic suffix pattern
    '* (from env var *)':
        "Go generic env var error wrapper; Python embeds env var in specific messages",
    # Go uses option function names (WithChecks/WithChecksEmbed); Python uses field names
    'cannot use both WithChecks and WithChecksEmbed':
        "Go uses option function names (WithChecks/WithChecksEmbed); Python uses field names (checks_path/checks_embed)",
    # Go uses the option function name (WithConfigConflictMode); Python uses
    # the field name (App.config_conflict_mode). Same validation.
    'WithConfigConflictMode: mode must be "cli-wins" or "error", got *':
        "Python counterpart is 'App.config_conflict_mode must be ...' (field name)",
    # Go has a plain-string return for non-whole float->int coercion in config;
    # Python covers this generically via 'expected integer, got *'
    'expected integer, got float':
        "Go plain-string return in coerceConfigScalarLong; Python generic 'expected integer, got *'",
    # --- Compound type Go-only messages ---
    # Go uses typed constructors (ListOf, DictOf) and entity-specific messages
    # that don't exist in Python's generic {context}: pattern approach.
    'Arg *: choice * is not of type float':
        "Go type-specific Arg choice validation (Python uses generic pattern)",
    'Arg *: choice * is not of type int':
        "Go type-specific Arg choice validation (Python uses generic pattern)",
    'Arg *: choice * is not of type str':
        "Go type-specific Arg choice validation (Python uses generic pattern)",
    'Arg *: choices is incompatible with list type':
        "Go Arg-specific compound type restriction; Python validates differently",
    'Arg *: default * is not in choices [*]':
        "Go fmt.Sprintf with brackets; Python counterpart normalizes without brackets",
    'Arg *: dict type is not supported on positional arguments':
        "Go uses 'positional arguments' wording; Python uses 'args'",
    'Arg *: list item type must be str, int, or float':
        "Go omits 'got' clause; Python includes it",
    'Arg *: list type requires variadic=true':
        "Go uses lowercase variadic=true; Python uses variadic=True",
    'DictOf: value type must be str, int, or float, got *':
        "Go typed constructor validation; Python uses generic {context}: pattern",
    'Flag *: choices is incompatible with compound types (list/dict)':
        "Go Flag-specific compound type restriction; Python validates differently",
    'Flag *: default element *: *':
        "Go type-specific default element validation (Python uses generic pattern)",
    'Flag *: default value for key *: *':
        "Go type-specific dict default validation; Python validates generically",
    'Flag *: dict flag default must be a map[string]interface{}':
        "Go typed assertion for dict default; Python uses isinstance check",
    'Flag *: explicit empty default is redundant for list flags, omit the default':
        "Go-specific list flag default validation; Python handles differently",
    'Flag *: list flag default must be a []interface{}':
        "Go typed assertion for list default; Python uses isinstance check",
    'ListOf: item type must be str, int, or float, got *':
        "Go typed constructor validation; Python uses generic {context}: pattern",
    # --- Config field Go-only messages ---
    # Go has separate config field help text validation messages;
    # Python uses generic _require_non_empty_str producing '*.* must be...'
    'config field *: help text is required':
        "Go entity-specific; Python generic '*.* must be a non-empty string'",
    'framework field *: help text is required':
        "Go entity-specific; Python generic '*.* must be a non-empty string'",
    'framework field *: invalid name, must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)':
        "Go has separate framework field validation; Python uses ConfigField.__post_init__",
    # --- Config field validation short-name errors ---
    # coerceConfigScalarShort produces these without prefix; the caller
    # (validateBoundConfigFields) wraps them with 'config field "X": ...'
    # Python produces the wrapped form directly via _check_config_field_type.
    'expected bool, got *':
        "Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    'expected int, got *':
        "Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    'expected int, got float':
        "Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    'expected str, got *':
        "Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    'expected array for list flag, got *':
        "Go coerceConfigValue for ListType flags; Python uses 'repeatable flag'",
    # --- Invoke/routing Go-only messages ---
    'no command specified':
        "Go routing returns error; Python shows help when no command given",
    'passthrough command: _args must be []string':
        "Go typed system requires []string assertion; Python uses duck typing",
    'dict flag *: expected map type, got *':
        "Go invoke coerceInvokeDict; Python uses isinstance with different message",
    # --- List flag env separator ---
    '--*: list flag with env requires env_separator':
        "Go-specific list/env interaction validation; Python handles differently",
}

# Dead code: errors present in both implementations but unreachable at runtime.
# These are excluded from coverage checks (no conformance test can trigger them).
DEAD_CODE_EXCLUSIONS: dict[str, str] = {
    # Both Python and Go validate Flag.help in the Flag constructor before
    # the command-level loop that checks flag help. The command-level check
    # is unreachable dead code.
    'command *: flag * missing help text':
        "Flag constructors validate help before command-level check can fire",
}

# Coverage-deferred: parse-time errors that exist in both implementations but
# require conformance test infrastructure not yet built (e.g., config file
# fixtures, multi-flag interaction scenarios). These are temporarily excluded
# from coverage checks but remain parity-checked.
COVERAGE_DEFERRED_EXCLUSIONS: dict[str, str] = {
    # Config value coercion errors require writing a config file fixture
    '--*: config value error: *':
        "Needs config file fixture support in conformance framework",
    '--*: config value error: duplicate value *':
        "Needs config file fixture support in conformance framework",
    # Implies conflict requires specific flag interaction setup
    "flag '--*' implies '--**', but '--**' was explicitly provided":
        "Needs Implies dependency test case in conformance framework",
    # @-prefix stdin and edge-case errors that require infrastructure not
    # available in the conformance subprocess framework
    '--*: cannot read stdin':
        "Requires stdin piping to subprocess, not supported in conformance runner",
    '--*: stdin (@-) can only be used once per invocation':
        "Requires stdin piping to subprocess, not supported in conformance runner",
    '--*: file exceeds 1 MB limit':
        "Requires a >1MB fixture file, impractical for conformance suite",
    '--*: cannot read file: *':
        "Requires a file with restricted permissions, platform-dependent",
    # Invoke API errors (programmatic call, not CLI argv)
    'unknown parameter * for command *':
        "Invoke API error; needs programmatic call conformance test infrastructure",
    'unknown parameter * for passthrough command *':
        "Invoke API error; needs programmatic call conformance test infrastructure",
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

    # The argument must BEGIN with a string literal (optionally f-prefixed).
    # Otherwise it is a variable expression (e.g., raise _ParseError(err) or
    # raise _ParseError(pre_scan["err"])) whose embedded string literals are
    # subscript keys, not error message text.
    if not text or text[0] not in ('"', "'", "f") or (
        text[0] == "f" and (len(text) < 2 or text[1] not in ('"', "'"))
    ):
        return None

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

def extract_go_errors(
    strictcli_src: str,
    parse_src: str,
    check_src: str,
    check_runner_src: str,
    check_public_src: str,
    tagdsl_src: str,
    config_src: str,
    routing_src: str,
    invoke_src: str,
) -> list[tuple[str, str]]:
    """Extract (category, format_string) pairs from Go source.

    Categories: 'registration' for panic(), 'parse' for error string returns.
    """
    results: list[tuple[str, str]] = []

    # --- Registration errors from strictcli.go and config.go (panics) ---

    # panic(fmt.Sprintf("...", args)) -- allow whitespace/newlines before the quote
    panic_sprintf = re.compile(
        r'panic\(fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in panic_sprintf.finditer(strictcli_src):
        results.append(("registration", m.group(1)))
    for m in panic_sprintf.finditer(config_src):
        results.append(("registration", m.group(1)))

    # panic("...")
    panic_plain = re.compile(
        r'panic\("((?:[^"\\]|\\.)*)"\)',
    )
    for m in panic_plain.finditer(strictcli_src):
        results.append(("registration", m.group(1)))
    for m in panic_plain.finditer(config_src):
        results.append(("registration", m.group(1)))

    # --- Registration errors from strictcli.go (violations append pattern) ---
    # violations = append(violations, fmt.Sprintf("...", args))
    violations_sprintf = re.compile(
        r'append\(violations,\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in violations_sprintf.finditer(strictcli_src):
        results.append(("registration", m.group(1)))

    # --- Parse errors from parse.go ---
    # return nil, ..., fmt.Sprintf("...", args) with two or more leading
    # nils. Arity-agnostic: parse helpers have grown extra return values
    # over time (e.g., provenance sources added a fourth return), so match
    # any run of two-plus nils rather than a fixed arity.
    parse_sprintf_3 = re.compile(
        r'return\s+(?:nil,\s*){2,}fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_sprintf_3.finditer(parse_src):
        results.append(("parse", m.group(1)))

    # return "", fmt.Sprintf("...", args) -- resolveAtPrefix helper
    parse_sprintf_str_err = re.compile(
        r'return\s+"",\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_sprintf_str_err.finditer(parse_src):
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

    # parseErr: "..." -- plain string literals (e.g., hermetic mode errors)
    parse_err_plain = re.compile(
        r'parseErr:\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_err_plain.finditer(strictcli_src):
        results.append(("parse", m.group(1)))

    # return nil, fmt.Sprintf("...", args) -- parseGlobalFlagValue
    parse_sprintf_2 = re.compile(
        r'return\s+nil,\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_sprintf_2.finditer(strictcli_src):
        results.append(("parse", m.group(1)))

    # --- Registration errors from check.go (fmt.Errorf for TOML validation) ---
    errorf_pat = re.compile(
        r'fmt\.Errorf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in errorf_pat.finditer(check_src):
        results.append(("registration", m.group(1)))

    # --- Registration errors from check_runner.go (fmt.Errorf for cycle detection) ---
    for m in errorf_pat.finditer(check_runner_src):
        results.append(("registration", m.group(1)))

    # --- Registration errors from check_public.go (fmt.Errorf for public API) ---
    for m in errorf_pat.finditer(check_public_src):
        # Skip pure format-string wrappers like fmt.Errorf("%s", errMsg)
        # that just re-wrap an existing error message without adding content.
        if m.group(1) == "%s":
            continue
        results.append(("registration", m.group(1)))

    # --- Registration errors from tagdsl.go (fmt.Errorf for tag expression parsing) ---
    for m in errorf_pat.finditer(tagdsl_src):
        results.append(("registration", m.group(1)))

    # --- Single-return parse errors from parse.go (storeValue helper) ---
    # return fmt.Sprintf("...", args) -- storeValue duplicate detection
    parse_sprintf_1 = re.compile(
        r'return\s+fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in parse_sprintf_1.finditer(parse_src):
        fmt_str = m.group(1)
        # Skip formatValueForError's fallback (not an error message)
        if fmt_str == "%v":
            continue
        results.append(("parse", fmt_str))

    # --- Single-return parse errors from strictcli.go (storeValue in extractGlobalFlags) ---
    for m in parse_sprintf_1.finditer(strictcli_src):
        fmt_str = m.group(1)
        if fmt_str == "%v":
            continue
        # Skip registration errors (already captured by panic patterns)
        # and the checks_declared error (already captured)
        if fmt_str.startswith("checks declared"):
            continue
        # Skip tag contract error -- Python equivalent uses return (not raise),
        # so it's also not extracted. Parity is maintained by conformance cases.
        if 'tag %q requires flag' in fmt_str:
            continue
        results.append(("parse", fmt_str))

    # --- Config value coercion errors from config.go (fmt.Sprintf in return) ---
    # return nil, fmt.Sprintf("...", args) -- coerceConfigValue
    for m in parse_sprintf_2.finditer(config_src):
        results.append(("registration", m.group(1)))

    # --- Config value coercion errors from config.go (plain string in return) ---
    # return nil, "..." -- coerceConfigValue/coerceConfigScalar
    config_plain_err = re.compile(
        r'return\s+nil,\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in config_plain_err.finditer(config_src):
        fmt_str = m.group(1)
        # Skip provenance source labels like `return nil, "default"` --
        # (value, source) tuple returns, not error messages. Real error
        # messages always contain a space.
        if " " not in fmt_str:
            continue
        results.append(("registration", fmt_str))

    # --- Parse errors from routing.go (struct literal err field) ---
    # err: fmt.Sprintf("...", args) and err: "..."
    struct_err_sprintf = re.compile(
        r'err:\s*fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
    )
    struct_err_plain = re.compile(
        r'err:\s*"((?:[^"\\]|\\.)*)"',
    )
    for m in struct_err_sprintf.finditer(routing_src):
        results.append(("parse", m.group(1)))
    for m in struct_err_plain.finditer(routing_src):
        results.append(("parse", m.group(1)))

    # --- Parse errors from invoke.go (struct literal err field and returns) ---
    for m in struct_err_sprintf.finditer(invoke_src):
        results.append(("parse", m.group(1)))
    for m in struct_err_plain.finditer(invoke_src):
        fmt_str = m.group(1)
        # Skip partial strings that are continued with + concatenation
        # (e.g., "no command resolved from path: " + commandPath)
        if fmt_str.endswith(": "):
            continue
        results.append(("parse", fmt_str))
    # return nil, fmt.Sprintf("...", args) -- coerceInvokeDict
    for m in parse_sprintf_2.finditer(invoke_src):
        results.append(("registration", m.group(1)))

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

    First unescapes Go string escapes (\\\" -> \", \\n -> newline, etc.).
    Then replaces %s, %d, %v, %q, %T with *.
    %q produces a Go-quoted string (with surrounding double quotes), so we
    treat it like * rather than "*".
    Then normalizes quoted placeholders: '*' becomes *.
    """
    # Unescape Go string literal escape sequences
    sig = fmt_str.replace('\\"', '"')
    sig = sig.replace('\\n', '\n')
    sig = sig.replace('\\t', '\t')
    sig = sig.replace('\\\\', '\\')
    sig = re.sub(r"%[sdvqT]", "*", sig)
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
    go_check_source = GO_CHECK.read_text()
    go_check_runner_source = GO_CHECK_RUNNER.read_text()
    go_check_public_source = GO_CHECK_PUBLIC.read_text()
    go_tagdsl_source = GO_TAGDSL.read_text()
    go_config_source = GO_CONFIG.read_text()
    go_routing_source = GO_ROUTING.read_text()
    go_invoke_source = GO_INVOKE.read_text()

    # Extract raw error patterns
    py_raw = extract_python_errors(py_source)
    go_raw = extract_go_errors(
        go_strictcli_source, go_parse_source,
        go_check_source, go_check_runner_source,
        go_check_public_source, go_tagdsl_source,
        go_config_source, go_routing_source,
        go_invoke_source,
    )

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
    # Only parse-time errors (category='parse') can be tested through the
    # conformance framework which exercises CLI behavior (argv -> stderr).
    # Registration-time errors (panics in Go, ValueError in Python during
    # app setup) are tested by each implementation's own unit tests.
    test_assertions = extract_test_stderr(CASES_DIR)

    # Build set of parse-time signatures only
    parse_sigs: set[str] = set()
    for sig, origins in py_sigs.items():
        if any(cat == "parse" for cat, _ in origins):
            parse_sigs.add(sig)
    for sig, origins in go_sigs.items():
        if any(cat == "parse" for cat, _ in origins):
            parse_sigs.add(sig)

    # Exclude signatures that are in exclusion lists
    excluded_sigs = (
        set(PY_ONLY_EXCLUSIONS.keys())
        | set(GO_ONLY_EXCLUSIONS.keys())
        | set(DEAD_CODE_EXCLUSIONS.keys())
        | set(COVERAGE_DEFERRED_EXCLUSIONS.keys())
    )

    uncovered: list[str] = []
    for sig in sorted(parse_sigs - excluded_sigs):
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
    all_sigs = set(py_sigs.keys()) | set(go_sigs.keys())
    matched = set(py_sigs.keys()) & set(go_sigs.keys())
    py_excl = len([s for s in py_only if s in PY_ONLY_EXCLUSIONS])
    go_excl = len([s for s in go_only if s in GO_ONLY_EXCLUSIONS])
    coverable = parse_sigs - excluded_sigs
    covered_count = len(coverable - set(uncovered))

    dead_excl = len([s for s in all_sigs if s in DEAD_CODE_EXCLUSIONS])
    deferred_excl = len([s for s in parse_sigs if s in COVERAGE_DEFERRED_EXCLUSIONS])

    print("Error parity check passed.")
    print(f"  Matched signatures: {len(matched)}")
    print(f"  Python-only (excluded): {py_excl}")
    print(f"  Go-only (excluded): {go_excl}")
    print(f"  Dead code (excluded): {dead_excl}")
    print(f"  Coverage deferred: {deferred_excl}")
    print(f"  Parse-time coverage: {covered_count}/{len(coverable)} signatures covered")
    print(f"  Total signatures: {len(all_sigs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
