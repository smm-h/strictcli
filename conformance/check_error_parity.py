#!/usr/bin/env python3
"""Error parity check for strictcli conformance.

Extracts error message patterns from N implementations (currently Python and
Go), normalizes them to a common signature form, and verifies:
  1. Every signature extracted from any implementation is accounted for in all
     others (present or excluded with rationale).
  2. Every parse-time error signature is covered by at least one conformance
     test case.

The comparison is N-way symmetric: each implementation's extracted messages
form a multiset keyed by normalized signature.  Adding a new target requires
an explicit status answer for every signature that differs.

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
GO_CHECK_PROVIDER = PROJECT_ROOT / "go" / "strictcli" / "check_provider.go"
GO_TAGDSL = PROJECT_ROOT / "go" / "strictcli" / "tagdsl.go"
GO_CONFIG = PROJECT_ROOT / "go" / "strictcli" / "config.go"
GO_ROUTING = PROJECT_ROOT / "go" / "strictcli" / "routing.go"
GO_INVOKE = PROJECT_ROOT / "go" / "strictcli" / "invoke.go"
GO_ERRORS = PROJECT_ROOT / "go" / "strictcli" / "errors.go"
CASES_DIR = CONFORMANCE_DIR / "cases"

# ---------------------------------------------------------------------------
# Implementation registry
# ---------------------------------------------------------------------------

IMPLEMENTATIONS = ("python", "go")

# ---------------------------------------------------------------------------
# Unified signature status manifest
#
# Shape: {signature: {impl_name: status_string}}
#
# Status strings:
#   "excluded:<rationale>"         -- not present in this impl, by design
#   "dead_code:<rationale>"        -- present but unreachable at runtime
#   "coverage_deferred:<rationale>" -- present but coverage deferred
#
# Signatures NOT listed here are expected to be present in ALL
# implementations.  Signatures listed here need a status for every
# implementation where the default ("present and coverable") does not hold.
# ---------------------------------------------------------------------------

SIGNATURE_STATUS: dict[str, dict[str, str]] = {
    # =======================================================================
    # Python-present, Go-excluded
    # =======================================================================

    # -- Handler signature validation (Python only) --
    'command *: handler missing parameter * for flag *': {
        "go": "excluded:Go uses map[string]interface{} kwargs, no handler signature validation",
    },
    'command *: handler missing parameter * for arg *': {
        "go": "excluded:Go uses map[string]interface{} kwargs, no handler signature validation",
    },
    'command *: handler has extra parameter * not matching any flag or arg': {
        "go": "excluded:Go uses map[string]interface{} kwargs, no handler signature validation",
    },

    # -- Python default type validation --
    'Flag *: choice * is not of type *': {
        "go": "excluded:Go validates choices with type-specific messages (str/int/float)",
    },

    # -- Python internal float errors --
    'invalid literal for float(): *': {
        "go": "excluded:Python internal ValueError from _strict_float, surfaces as 'expected float'",
    },
    'NaN is not allowed': {
        "go": "excluded:Python internal ValueError from _strict_float, wrapped with flag prefix at call site",
    },
    'Inf is not allowed': {
        "go": "excluded:Python internal ValueError from _strict_float, wrapped with flag prefix at call site",
    },

    # -- Python generic _require_non_empty_str --
    '*.* must be a non-empty string': {
        "go": "excluded:Python uses generic _require_non_empty_str; Go has entity-specific messages",
    },

    # -- SkipCheck (Python-only scope adapter) --
    'SkipCheck.reason must be a non-empty string': {
        "go": "excluded:Python-only scope-adapter skip directive; Go has no scope adapter",
    },

    # -- Check provider validation (Python dynamic, Go static) --
    'check provider must be callable': {
        "go": "excluded:Go RegisterCheckProvider takes a typed func value; no callable check needed",
    },
    'check provider must return a list of CheckSpec, got *': {
        "go": "excluded:Go provider return type is []CheckSpec (statically typed); no runtime check",
    },
    'check provider returned a non-CheckSpec value: *': {
        "go": "excluded:Go provider elements are CheckSpec (statically typed); no runtime check",
    },

    # -- Python f-string vs Go fmt.Sprintf bracket differences --
    'Flag *: default * is not in choices *': {
        "go": "excluded:Python f-string normalizes without brackets; Go counterpart is 'Flag *: default * is not in choices [*]'",
    },

    # -- Python Implies value type validation --
    'command *: Implies value must be a bool, got *': {
        "go": "excluded:Go Implies struct has typed bool Value field; no runtime type check needed",
    },

    # -- Python tag DSL --
    'tag expression: unknown AST node *': {
        "go": "excluded:Python uses tuple-based AST with string dispatch; Go uses typed interfaces",
    },

    # -- Python config format validation --
    'App.config_format must be "json" or "toml", got *': {
        "go": "excluded:Go uses fmt.Fprintf+os.Exit with %q quoting; Python uses ValueError with !r quoting",
    },

    # -- Python field name vs Go option function name --
    'cannot use both checks_path and checks_embed': {
        "go": "excluded:Go uses option function names (WithChecks/WithChecksEmbed); Python uses field names (checks_path/checks_embed)",
    },
    'App.config_conflict_mode must be "cli-wins" or "error", got *': {
        "go": "excluded:Go counterpart is 'WithConfigConflictMode: mode must be ...' (option function name)",
    },
    'Flag *: conflict_mode must be "cli-wins" or "error", got *': {
        "go": "excluded:Go counterpart is 'ConflictMode: mode must be ...' (option function name)",
    },

    # -- Python unique bool validation --
    'Flag *: unique must be True or False': {
        "go": "excluded:Go uses typed bool field for Unique; no runtime type check needed",
    },

    # -- Python repeatable default element validation --
    'Flag *: default element * is not of type *': {
        "go": "excluded:Go validates default elements with type-specific messages (str/int/float)",
    },

    # -- Compound type structural differences --
    '*: dict key type must be str, got *': {
        "go": "excluded:Python generic {context}: pattern; Go uses DictOf typed constructor",
    },
    '*: dict type requires type arguments (e.g., dict[str, int]), got bare dict': {
        "go": "excluded:Python generic {context}: pattern; Go uses DictOf typed constructor",
    },
    '*: dict type takes exactly two type arguments, got *': {
        "go": "excluded:Python generic {context}: pattern; Go uses DictOf typed constructor",
    },
    '*: dict value type must be str, int, or float, got *': {
        "go": "excluded:Python generic {context}: pattern; Go uses DictOf typed constructor",
    },
    '*: list item type must be str, int, or float, got *': {
        "go": "excluded:Python generic {context}: pattern; Go uses ListOf typed constructor",
    },
    '*: list type requires an item type (e.g., list[int]), got bare list': {
        "go": "excluded:Python generic {context}: pattern; Go uses ListOf typed constructor",
    },
    '*: list type takes exactly one type argument, got *': {
        "go": "excluded:Python generic {context}: pattern; Go uses ListOf typed constructor",
    },
    '*: type must be str, bool, int, float, list[T], or dict[str, T], got *': {
        "go": "excluded:Python generic {context}: pattern; Go uses separate typed constructors",
    },

    # -- Python compound type validation (Flag context) --
    'Flag *: * is not of type float': {
        "go": "excluded:Python generic {context} pattern; Go uses typed constructors with separate messages",
    },
    'Flag *: * is not of type int': {
        "go": "excluded:Python generic {context} pattern; Go uses typed constructors with separate messages",
    },
    'Flag *: * is not of type str': {
        "go": "excluded:Python generic {context} pattern; Go uses typed constructors with separate messages",
    },

    # -- Dict/list parse-time messages (Python JSON-based) --
    '--*: JSON key must be a string, got *': {
        "go": "excluded:Python dict flag JSON parsing; Go handles via typed coercion in parse.go",
    },
    '--*: JSON value for key * must be a number, got *': {
        "go": "excluded:Python dict flag JSON value validation; Go handles via typed coercion",
    },
    '--*: JSON value for key * must be a string, got *': {
        "go": "excluded:Python dict flag JSON value validation; Go handles via typed coercion",
    },
    '--*: JSON value for key * must be an integer, got *': {
        "go": "excluded:Python dict flag JSON value validation; Go handles via typed coercion",
    },
    '--*: JSON value must be an object, got *': {
        "go": "excluded:Python dict flag JSON object validation; Go handles via typed coercion",
    },
    '--*: duplicate key *': {
        "go": "excluded:Python dict flag duplicate key detection; Go handles via map overwrite",
    },
    '--*: empty key in *': {
        "go": "excluded:Python dict flag empty key validation; Go handles differently",
    },
    '--*: env var * must be a JSON object, got *': {
        "go": "excluded:Python dict flag env var validation; Go handles via typed coercion",
    },
    '--*: expected key=value or JSON, got *': {
        "go": "excluded:Python dict flag format validation; Go handles via typed coercion",
    },
    '--*: invalid JSON in env var *: *': {
        "go": "excluded:Python dict flag JSON parse error; Go handles via typed coercion",
    },
    '--*: invalid JSON: *': {
        "go": "excluded:Python dict flag JSON parse error; Go handles via typed coercion",
    },
    '--*: unsupported value type *': {
        "go": "excluded:Python dict flag unsupported type; Go handles via typed constructors",
    },
    '--*: value for key *: *': {
        "go": "excluded:Python dict flag per-key value error; Go handles via typed coercion",
    },

    # -- Arg compound type messages (Python wording) --
    'Arg *: choice * is not of type *': {
        "go": "excluded:Go validates Arg choices with type-specific messages (str/int/float)",
    },
    'Arg *: default * is not in choices *': {
        "go": "excluded:Python f-string normalizes without brackets; Go counterpart uses [%s]",
    },
    'Arg *: dict type is not supported on args': {
        "go": "excluded:Go uses 'positional arguments' wording instead of 'args'",
    },
    'Arg *: list item type must be str, int, or float, got *': {
        "go": "excluded:Python includes 'got' clause; Go omits it",
    },
    'Arg *: list type on args requires variadic=True': {
        "go": "excluded:Go uses lowercase variadic=true; Python uses variadic=True",
    },
    'Arg *: list type requires an item type (e.g., list[int]), got bare list': {
        "go": "excluded:Python includes full example; Go has different wording",
    },
    'Arg *: list type takes exactly one type argument, got *': {
        "go": "excluded:Python generic pattern; Go has different wording",
    },

    # -- Flag compound type Python-only messages --
    'Flag *: dict default key * must be a string': {
        "go": "excluded:Python validates dict default keys; Go uses typed map[string]interface{} assertion",
    },
    'Flag *: dict flag default must be a dict': {
        "go": "excluded:Python uses 'dict'; Go uses 'map[string]interface{}'",
    },
    'Flag *: dict type cannot be combined with choices': {
        "go": "excluded:Go uses 'choices is incompatible with compound types (list/dict)'",
    },
    'Flag *: dict type cannot be combined with repeatable=True': {
        "go": "excluded:Go forbids compound+repeatable differently; no direct counterpart",
    },
    'Flag *: dict type cannot be combined with unique': {
        "go": "excluded:Go forbids compound+unique differently; no direct counterpart",
    },
    'Flag *: dict type cannot use env_separator (env vars are parsed as JSON)': {
        "go": "excluded:Go validates list/env interaction differently; no direct counterpart",
    },
    'Flag.type must be str, bool, int, float, list[T], or dict[str, T], got *': {
        "go": "excluded:Go uses typed constructors (ListOf/DictOf); no runtime type check needed",
    },

    # -- Typed arg parse-time messages --
    'argument *: *': {
        "go": "excluded:Python generic 'argument' prefix wrapper; Go produces typed errors at parse level",
    },
    'argument *: expected float, got *': {
        "go": "excluded:Python typed arg float parsing; Go handles at parse level with different prefix",
    },

    # -- Required-bool prefix structural difference --
    "flag '--*' is required": {
        "go": "excluded:Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    },
    "flag '--*' must be passed as --*": {
        "go": "excluded:Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    },
    "flag '--*' must be passed as --* or --no-*": {
        "go": "excluded:Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    },
    "global flag '--*' is required": {
        "go": "excluded:Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    },
    "global flag '--*' must be passed as --*": {
        "go": "excluded:Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    },
    "global flag '--*' must be passed as --* or --no-*": {
        "go": "excluded:Go uses parameterized prefix in applyFlagDefault; signature is '*flag --*...'",
    },

    # -- InfraEnv structural / extraction asymmetries --
    'RelativeToRoot references undeclared infra root *; declare it as an infra root': {
        "go": "excluded:Go counterpart is an aligned fmt.Errorf in resolveInfraRootPath, not in the extracted registration set",
    },
    'command *: flag *: RelativeToRoot references undeclared infra root *; declare it as an infra root': {
        "go": "excluded:Go has no command-context flag-marker validation; it validates per-flag at registration",
    },

    # =======================================================================
    # Go-present, Python-excluded
    # =======================================================================

    # -- Go type-specific choice validation --
    'Flag *: choice * is not of type str': {
        "python": "excluded:Go type-specific choice validation (Python uses generic pattern)",
    },
    'Flag *: choice * is not of type int': {
        "python": "excluded:Go type-specific choice validation (Python uses generic pattern)",
    },
    'Flag *: choice * is not of type float': {
        "python": "excluded:Go type-specific choice validation (Python uses generic pattern)",
    },

    # -- Go type-specific default element validation --
    'Flag *: default element * is not of type str': {
        "python": "excluded:Go type-specific default element validation (Python uses generic pattern)",
    },
    'Flag *: default element * is not of type int': {
        "python": "excluded:Go type-specific default element validation (Python uses generic pattern)",
    },
    'Flag *: default element * is not of type float': {
        "python": "excluded:Go type-specific default element validation (Python uses generic pattern)",
    },

    # -- Go entity-specific help validation --
    'App.help must be a non-empty string': {
        "python": "excluded:Go entity-specific; Python generic '*.* must be a non-empty string'",
    },
    'Arg.help must be a non-empty string': {
        "python": "excluded:Go entity-specific; Python generic '*.* must be a non-empty string'",
    },
    'Flag.help must be a non-empty string': {
        "python": "excluded:Go entity-specific; Python generic '*.* must be a non-empty string'",
    },
    'Group.help must be a non-empty string': {
        "python": "excluded:Go entity-specific; Python generic '*.* must be a non-empty string'",
    },

    # -- Go bracket-formatted choices --
    'Flag *: default * is not in choices [*]': {
        "python": "excluded:Go fmt.Sprintf normalizes with brackets; Python counterpart is 'Flag *: default * is not in choices *'",
    },

    # -- Go cycle detection --
    'check dependency cycle detected involving *': {
        "python": "excluded:Go expansion-phase cycle detection; Python only reports cycles via path format",
    },
    'check dependency cycle detected': {
        "python": "excluded:Go Kahn fallback when cycle path not found; Python always finds cycle path",
    },

    # -- Go path.Match error --
    'invalid glob pattern *: *': {
        "python": "excluded:Go-specific path.Match error; Python fnmatch never errors on patterns",
    },

    # -- Go env var error wrapper --
    '* (from env var *)': {
        "python": "excluded:Go generic env var error wrapper; Python embeds env var in specific messages",
    },

    # -- Go option function names --
    'cannot use both WithChecks and WithChecksEmbed': {
        "python": "excluded:Go uses option function names (WithChecks/WithChecksEmbed); Python uses field names (checks_path/checks_embed)",
    },
    'WithConfigConflictMode: mode must be "cli-wins" or "error", got *': {
        "python": "excluded:Python counterpart is 'App.config_conflict_mode must be ...' (field name)",
    },
    'ConflictMode: mode must be "cli-wins" or "error", got *': {
        "python": "excluded:Python counterpart is 'Flag ...: conflict_mode must be ...' (flag kwarg name)",
    },

    # -- Go config coercion --
    'expected integer, got float': {
        "python": "excluded:Go plain-string return in coerceConfigScalarLong; Python generic 'expected integer, got *'",
    },

    # -- Go compound type messages --
    'Arg *: choice * is not of type float': {
        "python": "excluded:Go type-specific Arg choice validation (Python uses generic pattern)",
    },
    'Arg *: choice * is not of type int': {
        "python": "excluded:Go type-specific Arg choice validation (Python uses generic pattern)",
    },
    'Arg *: choice * is not of type str': {
        "python": "excluded:Go type-specific Arg choice validation (Python uses generic pattern)",
    },
    'Arg *: choices is incompatible with list type': {
        "python": "excluded:Go Arg-specific compound type restriction; Python validates differently",
    },
    'Arg *: default * is not in choices [*]': {
        "python": "excluded:Go fmt.Sprintf with brackets; Python counterpart normalizes without brackets",
    },
    'Arg *: dict type is not supported on positional arguments': {
        "python": "excluded:Go uses 'positional arguments' wording; Python uses 'args'",
    },
    'Arg *: list item type must be str, int, or float': {
        "python": "excluded:Go omits 'got' clause; Python includes it",
    },
    'Arg *: list type requires variadic=true': {
        "python": "excluded:Go uses lowercase variadic=true; Python uses variadic=True",
    },
    'DictOf: value type must be str, int, or float, got *': {
        "python": "excluded:Go typed constructor validation; Python uses generic {context}: pattern",
    },
    'Flag *: choices is incompatible with compound types (list/dict)': {
        "python": "excluded:Go Flag-specific compound type restriction; Python validates differently",
    },
    'Flag *: default element *: *': {
        "python": "excluded:Go type-specific default element validation (Python uses generic pattern)",
    },
    'Flag *: default value for key *: *': {
        "python": "excluded:Go type-specific dict default validation; Python validates generically",
    },
    'Flag *: dict flag default must be a map[string]interface{}': {
        "python": "excluded:Go typed assertion for dict default; Python uses isinstance check",
    },
    'Flag *: explicit empty default is redundant for list flags, omit the default': {
        "python": "excluded:Go-specific list flag default validation; Python handles differently",
    },
    'Flag *: list flag default must be a []interface{}': {
        "python": "excluded:Go typed assertion for list default; Python uses isinstance check",
    },
    'ListOf: item type must be str, int, or float, got *': {
        "python": "excluded:Go typed constructor validation; Python uses generic {context}: pattern",
    },

    # -- Go config field help validation --
    'config field *: help text is required': {
        "python": "excluded:Go entity-specific; Python generic '*.* must be a non-empty string'",
    },
    'framework field *: help text is required': {
        "python": "excluded:Go entity-specific; Python generic '*.* must be a non-empty string'",
    },
    'framework field *: invalid name, must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)': {
        "python": "excluded:Go has separate framework field validation; Python uses ConfigField.__post_init__",
    },

    # -- Go config coercion short-name errors --
    'expected bool, got *': {
        "python": "excluded:Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    },
    'expected int, got *': {
        "python": "excluded:Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    },
    'expected int, got float': {
        "python": "excluded:Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    },
    'expected str, got *': {
        "python": "excluded:Go coerceConfigScalarShort raw return; Python wraps with 'config field' prefix",
    },
    'expected array for list flag, got *': {
        "python": "excluded:Go coerceConfigValue for ListType flags; Python uses 'repeatable flag'",
    },

    # -- Go invoke/routing errors --
    'no command specified': {
        "python": "excluded:Go routing returns error; Python shows help when no command given",
    },
    'passthrough command: _args must be []string': {
        "python": "excluded:Go typed system requires []string assertion; Python uses duck typing",
    },
    'dict flag *: expected map type, got *': {
        "python": "excluded:Go invoke coerceInvokeDict; Python uses isinstance with different message",
    },

    # -- Go list flag env separator --
    '--*: list flag with env requires env_separator': {
        "python": "excluded:Go-specific list/env interaction validation; Python handles differently",
    },

    # -- Go InfraEnv structural asymmetries --
    'duplicate infra root env var *': {
        "python": "excluded:Python infra_root is a dict keyed by env var; duplicates are impossible by construction",
    },
    'duplicate handshake env var *': {
        "python": "excluded:Python handshake_env is a dict keyed by env var; duplicates are impossible by construction",
    },

    # -- Go schema.go errors (go.mod project_id, schema mismatch) --
    'Cannot determine project_id: go.mod not found': {
        "python": "excluded:Go schema uses go.mod for project_id; Python uses pyproject.toml/setup.py",
    },
    'Cannot determine project_id: error reading go.mod: %w': {
        "python": "excluded:Go schema uses go.mod for project_id; Python uses pyproject.toml/setup.py",
    },
    'Cannot determine project_id: no module directive in go.mod': {
        "python": "excluded:Go schema uses go.mod for project_id; Python uses pyproject.toml/setup.py",
    },
    "Schema mismatch: existing schema belongs to project *, not *. Run from the correct project directory.": {
        "python": "excluded:Go schema project_id validation; Python equivalent validates differently",
    },

    # -- Go outcome.go errors (typed generics Get/GetOpt) --
    'strictcli.Get: no such key *': {
        "python": "excluded:Go typed generic helper; Python uses kwargs[key] directly",
    },
    'strictcli.Get: key * is nil (not provided); use GetOpt for optional values': {
        "python": "excluded:Go typed generic helper; Python uses kwargs[key] directly",
    },
    'strictcli.Get: key * has dynamic type *, want *': {
        "python": "excluded:Go typed generic helper; Python is dynamically typed",
    },
    'strictcli.GetOpt: no such key *': {
        "python": "excluded:Go typed generic helper; Python uses kwargs.get(key) directly",
    },
    'strictcli.GetOpt: key * has dynamic type *, want *': {
        "python": "excluded:Go typed generic helper; Python is dynamically typed",
    },

    # -- Go context.go errors (InfraValue, Source) --
    'InfraValue: * is not a declared infra root or handshake env var': {
        "python": "excluded:Go Context.InfraValue panic; Python equivalent raises KeyError natively",
    },
    'no source info for flag *': {
        "python": "excluded:Go Context.Source panic; Python equivalent raises KeyError natively",
    },

    # -- Go tool.go errors (JsonSchema) --
    'JsonSchema: *': {
        "python": "excluded:Go App.JsonSchema method panic; Python equivalent is json_schema() with different error",
    },
    "JsonSchema: * is a group, not a command": {
        "python": "excluded:Go App.JsonSchema method panic; Python equivalent is json_schema() with different error",
    },

    # -- Go check_runner.go errors (outcome not minted) --
    'check * returned an outcome not minted by its reporter; use reporter methods (Passed/Skipped/Found)': {
        "python": "excluded:Go runtime assertion for reporter-minted outcomes; Python uses type checking",
    },

    # =======================================================================
    # Dead code: present in both implementations but unreachable at runtime.
    # Excluded from coverage checks (no conformance test can trigger them).
    # =======================================================================
    'command *: flag * missing help text': {
        "python": "dead_code:Flag constructors validate help before command-level check can fire",
        "go": "dead_code:Flag constructors validate help before command-level check can fire",
    },

    # =======================================================================
    # Coverage-deferred: present in both implementations but require test
    # infrastructure not yet built.  Excluded from coverage checks but
    # remain parity-checked.
    # =======================================================================
    '--*: config value error: *': {
        "python": "coverage_deferred:Needs config file fixture support in conformance framework",
        "go": "coverage_deferred:Needs config file fixture support in conformance framework",
    },
    '--*: config value error: duplicate value *': {
        "python": "coverage_deferred:Needs config file fixture support in conformance framework",
        "go": "coverage_deferred:Needs config file fixture support in conformance framework",
    },
    "flag '--*' implies '--**', but '--**' was explicitly provided": {
        "python": "coverage_deferred:Needs Implies dependency test case in conformance framework",
        "go": "coverage_deferred:Needs Implies dependency test case in conformance framework",
    },
    '--*: cannot read stdin': {
        "python": "coverage_deferred:Requires stdin piping to subprocess, not supported in conformance runner",
        "go": "coverage_deferred:Requires stdin piping to subprocess, not supported in conformance runner",
    },
    '--*: stdin (@-) can only be used once per invocation': {
        "python": "coverage_deferred:Requires stdin piping to subprocess, not supported in conformance runner",
        "go": "coverage_deferred:Requires stdin piping to subprocess, not supported in conformance runner",
    },
    '--*: file exceeds 1 MB limit': {
        "python": "coverage_deferred:Requires a >1MB fixture file, impractical for conformance suite",
        "go": "coverage_deferred:Requires a >1MB fixture file, impractical for conformance suite",
    },
    '--*: cannot read file: *': {
        "python": "coverage_deferred:Requires a file with restricted permissions, platform-dependent",
        "go": "coverage_deferred:Requires a file with restricted permissions, platform-dependent",
    },
    'unknown parameter * for command *': {
        "python": "coverage_deferred:Invoke API error; needs programmatic call conformance test infrastructure",
        "go": "coverage_deferred:Invoke API error; needs programmatic call conformance test infrastructure",
    },
    'unknown parameter * for passthrough command *': {
        "python": "coverage_deferred:Invoke API error; needs programmatic call conformance test infrastructure",
        "go": "coverage_deferred:Invoke API error; needs programmatic call conformance test infrastructure",
    },
    'test-coverage: cannot create .strictcli/coverage/: *': {
        "python": "excluded:Python uses os.makedirs which raises OSError, not a formatted message",
        "go": "excluded:Go-specific formatted error for coverage shard directory creation failure",
    },
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
    check_provider_src: str,
    tagdsl_src: str,
    config_src: str,
    routing_src: str,
    invoke_src: str,
    errors_src: str = "",
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

    # --- Reporter-minting panics from check.go ---
    for m in panic_plain.finditer(check_src):
        results.append(("registration", m.group(1)))
    for m in panic_sprintf.finditer(check_src):
        results.append(("registration", m.group(1)))

    # --- Registration errors from check_runner.go (fmt.Errorf for cycle detection) ---
    for m in errorf_pat.finditer(check_runner_src):
        results.append(("registration", m.group(1)))

    # --- Reporter/materialization panics from check_provider.go ---
    for m in panic_plain.finditer(check_provider_src):
        results.append(("registration", m.group(1)))
    for m in panic_sprintf.finditer(check_provider_src):
        results.append(("registration", m.group(1)))

    # --- Registration errors from check_public.go (fmt.Errorf for public API) ---
    for m in errorf_pat.finditer(check_public_src):
        # Skip pure format-string wrappers like fmt.Errorf("%s", errMsg)
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
        if fmt_str.endswith(": "):
            continue
        results.append(("parse", fmt_str))
    # return nil, fmt.Sprintf("...", args) -- coerceInvokeDict
    for m in parse_sprintf_2.finditer(invoke_src):
        results.append(("registration", m.group(1)))

    # --- Centralized error templates from errors.go ---
    # errors.go contains fmt.Sprintf("...") and fmt.Errorf("...") patterns
    # that were extracted from other source files, plus const string literals.
    if errors_src:
        # fmt.Sprintf("...") -- registration error format functions
        errors_sprintf = re.compile(
            r'fmt\.Sprintf\(\s*"((?:[^"\\]|\\.)*)"',
        )
        for m in errors_sprintf.finditer(errors_src):
            results.append(("registration", m.group(1)))
        # fmt.Errorf("...") -- registration error format functions
        for m in errorf_pat.finditer(errors_src):
            results.append(("registration", m.group(1)))
        # const errXxx = "..." -- plain string constants
        const_err_pat = re.compile(
            r'^const\s+err\w+\s*=\s*"((?:[^"\\]|\\.)*)"',
            re.MULTILINE,
        )
        for m in const_err_pat.finditer(errors_src):
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
# 4. N-way parity comparison
# ---------------------------------------------------------------------------

def _get_status(sig: str, impl: str) -> str | None:
    """Return the declared status for a signature in an implementation.

    Returns None if no status is declared (meaning the signature is expected
    to be present in this impl by default).
    """
    entry = SIGNATURE_STATUS.get(sig)
    if entry is None:
        return None
    return entry.get(impl)


def _is_excluded(status: str | None) -> bool:
    """Return True if the status indicates a parity exclusion."""
    return status is not None and status.startswith("excluded:")


def _is_dead_code(status: str | None) -> bool:
    """Return True if the status indicates dead code."""
    return status is not None and status.startswith("dead_code:")


def _is_coverage_deferred(status: str | None) -> bool:
    """Return True if the status indicates deferred coverage."""
    return status is not None and status.startswith("coverage_deferred:")


def _is_coverage_excluded(sig: str) -> bool:
    """Return True if a signature is excluded from coverage checks.

    A signature is coverage-excluded if:
    - It is excluded from at least one implementation (parity exclusion), or
    - It is dead code in all implementations, or
    - It has deferred coverage in all implementations.
    """
    entry = SIGNATURE_STATUS.get(sig)
    if entry is None:
        return False

    # Any parity exclusion removes it from coverage
    for impl in IMPLEMENTATIONS:
        status = entry.get(impl)
        if _is_excluded(status):
            return True

    # Dead code in all implementations
    if all(_is_dead_code(entry.get(impl)) for impl in IMPLEMENTATIONS):
        return True

    # Coverage deferred in all implementations
    if all(_is_coverage_deferred(entry.get(impl)) for impl in IMPLEMENTATIONS):
        return True

    return False


def check_parity(
    impl_sigs: dict[str, dict[str, list[tuple[str, str]]]],
) -> list[str]:
    """N-way parity check across all implementations.

    For each signature in the union of all implementations' extracted sets,
    verifies that every implementation either has the signature or has an
    exclusion rationale declared in SIGNATURE_STATUS.
    """
    errors: list[str] = []
    all_sigs: set[str] = set()
    for sigs in impl_sigs.values():
        all_sigs.update(sigs.keys())

    for sig in sorted(all_sigs):
        for impl in IMPLEMENTATIONS:
            found = sig in impl_sigs[impl]
            status = _get_status(sig, impl)

            if found and _is_excluded(status):
                # Found in the impl but declared as excluded -- stale exclusion.
                # This is a warning, not an error (the exclusion is overly
                # conservative). Skip for now; could be tightened later.
                pass
            elif not found and status is None:
                # Not found and no exclusion declared -- parity error.
                # Which impls DO have it?
                sources = [
                    name for name, sigs in impl_sigs.items() if sig in sigs
                ]
                origins = []
                for name in sources:
                    raw_examples = ", ".join(
                        repr(raw) for _, raw in impl_sigs[name][sig][:2]
                    )
                    origins.append(f"{name}: {raw_examples}")
                errors.append(
                    f"{impl} missing error (no exclusion): {sig!r} "
                    f"(in: {'; '.join(origins)})"
                )

    return errors


# ---------------------------------------------------------------------------
# 5. Check test coverage
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
# 6. N-way shape diagnostic
# ---------------------------------------------------------------------------

def diagnose_new_target(
    target_name: str,
    impl_sigs: dict[str, dict[str, list[tuple[str, str]]]],
) -> list[str]:
    """Report every signature that would need an explicit answer for a new
    implementation target.

    A new target inherits no status entries, so every signature in the union
    requires either extraction (the new impl produces it) or an exclusion
    entry in SIGNATURE_STATUS.
    """
    all_sigs: set[str] = set()
    for sigs in impl_sigs.values():
        all_sigs.update(sigs.keys())

    needs_answer: list[str] = []
    for sig in sorted(all_sigs):
        status = _get_status(sig, target_name)
        if status is None:
            needs_answer.append(sig)

    return needs_answer


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
    go_check_provider_source = GO_CHECK_PROVIDER.read_text()
    go_tagdsl_source = GO_TAGDSL.read_text()
    go_config_source = GO_CONFIG.read_text()
    go_routing_source = GO_ROUTING.read_text()
    go_invoke_source = GO_INVOKE.read_text()
    go_errors_source = GO_ERRORS.read_text()

    # Extract raw error patterns
    py_raw = extract_python_errors(py_source)
    go_raw = extract_go_errors(
        go_strictcli_source, go_parse_source,
        go_check_source, go_check_runner_source,
        go_check_public_source, go_check_provider_source,
        go_tagdsl_source,
        go_config_source, go_routing_source,
        go_invoke_source,
        go_errors_source,
    )

    # Normalize to signatures
    py_items = [(cat, raw, normalize_python(raw)) for cat, raw in py_raw]
    go_items = [(cat, raw, normalize_go(raw)) for cat, raw in go_raw]

    py_sigs = deduplicate_signatures(py_items)
    go_sigs = deduplicate_signatures(go_items)

    impl_sigs: dict[str, dict[str, list[tuple[str, str]]]] = {
        "python": py_sigs,
        "go": go_sigs,
    }

    all_errors: list[str] = []

    # --- Check 1: N-way parity ---
    all_errors.extend(check_parity(impl_sigs))

    # --- Check 2: Test coverage ---
    # Only parse-time errors (category='parse') can be tested through the
    # conformance framework which exercises CLI behavior (argv -> stderr).
    # Registration-time errors (panics in Go, ValueError in Python during
    # app setup) are tested by each implementation's own unit tests.
    test_assertions = extract_test_stderr(CASES_DIR)

    # Build set of parse-time signatures only
    parse_sigs: set[str] = set()
    for impl_name, sigs in impl_sigs.items():
        for sig, origins in sigs.items():
            if any(cat == "parse" for cat, _ in origins):
                parse_sigs.add(sig)

    # Check coverage (excluding coverage-excluded signatures)
    uncovered: list[str] = []
    for sig in sorted(parse_sigs):
        if _is_coverage_excluded(sig):
            continue
        covered = any(
            signature_matches_assertion(sig, assertion)
            for assertion in test_assertions
        )
        if not covered:
            uncovered.append(sig)

    for sig in uncovered:
        sources = [
            name for name, sigs in impl_sigs.items() if sig in sigs
        ]
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
    all_sigs = set()
    for sigs in impl_sigs.values():
        all_sigs.update(sigs.keys())
    matched = set.intersection(*(set(s.keys()) for s in impl_sigs.values()))

    # Count exclusions per implementation
    excl_counts: dict[str, int] = {impl: 0 for impl in IMPLEMENTATIONS}
    dead_count = 0
    deferred_count = 0
    for sig, entry in SIGNATURE_STATUS.items():
        if sig not in all_sigs:
            # Stale entry (signature no longer extracted) -- skip counting
            continue
        is_dead = all(_is_dead_code(entry.get(impl)) for impl in IMPLEMENTATIONS)
        is_deferred = all(
            _is_coverage_deferred(entry.get(impl)) for impl in IMPLEMENTATIONS
        )
        if is_dead:
            dead_count += 1
        elif is_deferred:
            deferred_count += 1
        else:
            for impl in IMPLEMENTATIONS:
                if _is_excluded(entry.get(impl)):
                    excl_counts[impl] += 1

    coverable = parse_sigs - {s for s in parse_sigs if _is_coverage_excluded(s)}
    covered_count = len(coverable - set(uncovered))

    print("Error parity check passed.")
    print(f"  Matched signatures: {len(matched)}")
    for impl in IMPLEMENTATIONS:
        print(f"  {impl}-excluded: {excl_counts[impl]}")
    print(f"  Dead code (excluded): {dead_count}")
    print(f"  Coverage deferred: {deferred_count}")
    print(f"  Parse-time coverage: {covered_count}/{len(coverable)} signatures covered")
    print(f"  Total signatures: {len(all_sigs)}")

    # N-way shape diagnostic: show what a hypothetical third target would need
    fake_target = "_test_target"
    needs_answer = diagnose_new_target(fake_target, impl_sigs)
    print(f"  N-way shape check: adding target {fake_target!r} would require "
          f"{len(needs_answer)} explicit answers")

    return 0


if __name__ == "__main__":
    sys.exit(main())
