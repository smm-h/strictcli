#!/usr/bin/env python3
"""API surface check for strictcli conformance.

Introspects Python classes, parses Go structs, reads the conformance schema,
and verifies that every real API field exists in all three places (with known
exclusions for runtime-only or non-serializable features).

Exit 0 if all checks pass, exit 1 with a diff report otherwise.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFORMANCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFORMANCE_DIR.parent
SCHEMA_PATH = CONFORMANCE_DIR / "schema.json"
GO_SOURCE = PROJECT_ROOT / "go" / "strictcli" / "strictcli.go"

# ---------------------------------------------------------------------------
# Known exclusions (present in implementations but intentionally absent from
# the schema, or present in the schema only for test harness purposes)
# ---------------------------------------------------------------------------

# Implementation fields excluded from the schema (with rationale):
IMPL_EXCLUSIONS: dict[str, str] = {
    "validate": "callable, not serializable to JSON",
    "Validate": "callable, not serializable to JSON (Go struct field)",
    "ValidateFn": "callable, not serializable to JSON (Go option func)",
    "handler": "runtime-only (Python)",
    "Handler": "runtime-only (Go)",
    "PassthroughHandler": "runtime-only (Go)",
    "hasDefault": "private implementation detail (Go)",
    "type": "Python Flag.type uses native types; schema uses 'type' string enum",
}

# Per-entity exclusions: fields present in one implementation but not
# meaningful in the schema for that entity (not private, but structural).
PER_ENTITY_EXCLUSIONS: dict[str, set[str]] = {
    # Python Group.env_prefix is inherited from App at runtime, not a schema
    # concept on Group itself (schema Group has no env_prefix).
    # Python Group.deprecated is a runtime dict of DeprecatedCommand objects,
    # not serializable to the schema (deprecated commands are declared via
    # command.deprecated/deprecated_message in test case definitions).
    "Group": {"env_prefix", "deprecated"},
}

# Schema fields that exist only for the test harness (not real API fields):
SCHEMA_TEST_ONLY: set[str] = {
    "handler_prints",
    "handler_exit_code",
    "passthrough_handler_prints",
    # deprecated/deprecated_message describe deprecated commands in the JSON
    # test definition -- they are not attributes of the Command struct itself.
    "deprecated",
    "deprecated_message",
    # checks/checks_toml tell the conformance code generators what to generate
    # (e.g. error parity checks) -- not part of the strictcli API.
    "checks",
    "checks_toml",
}

# Per-entity schema fields that are JSON discriminators, not real API fields:
SCHEMA_PER_ENTITY_EXCLUSIONS: dict[str, set[str]] = {
    "co_required": {"type"},
    "requires": {"type"},
}

# ---------------------------------------------------------------------------
# Name mappings between implementations and schema
# ---------------------------------------------------------------------------

# Python field name -> schema field name(s)
# Keyed as "ClassName.field" for per-entity mappings, or just "field" for global.
PYTHON_TO_SCHEMA: dict[str, list[str]] = {
    "choices": ["choices_str", "choices_int", "choices_float"],
    "env_prefix": ["env_prefix"],
    "variadic": ["variadic"],
    "negatable": ["negatable"],
    "App.flags": ["global_flags"],  # Python App.flags = schema app.global_flags
}

# Go exported field name -> schema field name
GO_TO_SCHEMA: dict[str, str] = {
    "IsVariadic": "variadic",
    "Negatable": "negatable",
    "EnvPrefix": "env_prefix",
    "Choices": "choices_str",  # schema splits into choices_str/choices_int
    "Type": "type",
}

# Schema field name -> Python field name
# Keyed as "entity.field" for per-entity overrides, or just "field" for global.
SCHEMA_TO_PYTHON: dict[str, str] = {
    "choices_str": "choices",
    "choices_int": "choices",
    "choices_float": "choices",
    "env_prefix": "env_prefix",
    "variadic": "variadic",
    "negatable": "negatable",
    "app.global_flags": "flags",  # schema app.global_flags = Python App.flags
    "app.commands": "_commands",  # schema app.commands = Python App._commands
    "app.groups": "_groups",  # schema app.groups = Python App._groups
}

# Schema field name -> Go exported field name
# Keyed as "entity.field" for per-entity overrides, or just "field" for global.
SCHEMA_TO_GO: dict[str, str] = {
    "choices_str": "Choices",
    "choices_int": "Choices",
    "choices_float": "Choices",
    "variadic": "IsVariadic",
    "negatable": "Negatable",
    "env_prefix": "EnvPrefix",
    "type": "Type",
    "depends_on": "DependsOn",
    "app.commands": "commands",  # Go App.commands (unexported, set via method)
    "app.global_flags": "globalFlags",  # Go App.globalFlags (unexported, set via method)
    "app.groups": "groups",  # Go App.groups (unexported, set via method)
    "app.config": "configEnabled",  # Go App.configEnabled (unexported, set via WithConfig())
    "app.config_path": "configPathOverride",  # Go App.configPathOverride (unexported, set via WithConfigPath())
    "app.config_format": "configFormat",  # Go App.configFormat (unexported, set via WithConfigFormat())
    "app.checks_path": "checksPath",  # Go App.checksPath (unexported, set via WithChecks())
    "group.commands": "Commands",  # Go Group.Commands (exported)
}


# ---------------------------------------------------------------------------
# 1. Introspect Python
# ---------------------------------------------------------------------------

def get_python_fields() -> dict[str, set[str]]:
    """Return {class_name: {field_names}} for Python dataclasses."""
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli

    # Command is internal but part of the conformance surface
    from strictcli import Command

    result: dict[str, set[str]] = {}
    for cls in [
        strictcli.Flag, strictcli.Arg, strictcli.Tag,
        strictcli.MutexGroup, strictcli.CoRequired, strictcli.Requires,
        strictcli.App, strictcli.Group,
        Command,
    ]:
        fields = {f.name for f in dataclasses.fields(cls)}
        result[cls.__name__] = fields

    # Also capture decorator factory signatures
    for func_name in ("flag", "arg"):
        func = getattr(strictcli, func_name)
        sig = inspect.signature(func)
        result[f"{func_name}()"] = set(sig.parameters.keys())

    return result


# ---------------------------------------------------------------------------
# 2. Introspect Go (parse source text)
# ---------------------------------------------------------------------------

def get_go_source() -> str:
    """Return the Go source text."""
    return GO_SOURCE.read_text()


def get_go_fields(source: str) -> dict[str, set[str]]:
    """Return {struct_name: {exported_field_names}} from Go source."""
    result: dict[str, set[str]] = {}

    # Parse struct definitions
    # Match: type StructName struct { ... }
    struct_pattern = re.compile(
        r"^type\s+(\w+)\s+struct\s*\{(.*?)\n\}",
        re.MULTILINE | re.DOTALL,
    )
    for m in struct_pattern.finditer(source):
        name = m.group(1)
        body = m.group(2)
        fields: set[str] = set()
        for line in body.split("\n"):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("/*"):
                continue
            # Exported fields start with uppercase
            field_match = re.match(r"^([A-Z]\w*)\s+", line)
            if field_match:
                fields.add(field_match.group(1))
        if fields:
            result[name] = fields

    # Parse exported option functions
    # These are standalone funcs that return FlagOption, ArgOption, CmdOption, AppOption
    option_funcs: set[str] = set()
    func_pattern = re.compile(
        r"^func\s+([A-Z]\w*)\(.*?\)\s+(?:FlagOption|ArgOption|CmdOption|AppOption)\s*\{",
        re.MULTILINE,
    )
    for m in func_pattern.finditer(source):
        option_funcs.add(m.group(1))
    result["_option_funcs"] = option_funcs

    return result


# ---------------------------------------------------------------------------
# 3. Read schema
# ---------------------------------------------------------------------------

def get_schema_fields() -> dict[str, set[str]]:
    """Return {def_name: {field_names}} from the conformance schema."""
    schema = json.loads(SCHEMA_PATH.read_text())
    defs = schema.get("$defs", {})
    result: dict[str, set[str]] = {}
    for def_name, def_body in defs.items():
        props = def_body.get("properties", {})
        if props:
            result[def_name] = set(props.keys())
    return result


# ---------------------------------------------------------------------------
# 4. Compare
# ---------------------------------------------------------------------------

# Mapping from schema def names to (Python class name, Go struct name)
ENTITY_MAP: list[tuple[str, str, str]] = [
    ("flag", "Flag", "Flag"),
    ("arg", "Arg", "Arg"),
    ("tag", "Tag", "Tag"),
    ("mutex_group", "MutexGroup", "MutexGroup"),
    ("co_required", "CoRequired", "CoRequired"),
    ("requires", "Requires", "Requires"),
    ("command", "Command", "Command"),
    ("app", "App", "App"),
    ("group", "Group", "Group"),
]


def check_python_in_schema(
    py_fields: dict[str, set[str]],
    schema_fields: dict[str, set[str]],
) -> list[str]:
    """Check that every Python field exists in the schema (or is excluded)."""
    errors: list[str] = []
    for schema_def, py_cls, _ in ENTITY_MAP:
        if py_cls not in py_fields or schema_def not in schema_fields:
            continue
        s_fields = schema_fields[schema_def]
        entity_excl = PER_ENTITY_EXCLUSIONS.get(py_cls, set())
        for field in sorted(py_fields[py_cls]):
            # Skip private fields
            if field.startswith("_"):
                continue
            # Skip known exclusions
            if field in IMPL_EXCLUSIONS:
                continue
            # Skip per-entity exclusions
            if field in entity_excl:
                continue
            # Check with name mapping (qualified key takes priority)
            qualified_key = f"{py_cls}.{field}"
            if qualified_key in PYTHON_TO_SCHEMA:
                mapped = PYTHON_TO_SCHEMA[qualified_key]
                if not any(m in s_fields for m in mapped):
                    errors.append(
                        f"Python {py_cls}.{field} -> schema {schema_def}: "
                        f"expected one of {mapped}, found none"
                    )
            elif field in PYTHON_TO_SCHEMA:
                mapped = PYTHON_TO_SCHEMA[field]
                if not any(m in s_fields for m in mapped):
                    errors.append(
                        f"Python {py_cls}.{field} -> schema {schema_def}: "
                        f"expected one of {mapped}, found none"
                    )
            elif field not in s_fields:
                errors.append(
                    f"Python {py_cls}.{field} not found in schema {schema_def}"
                )
    return errors


def check_go_in_schema(
    go_fields: dict[str, set[str]],
    schema_fields: dict[str, set[str]],
) -> list[str]:
    """Check that every Go exported field exists in the schema (or is excluded)."""
    errors: list[str] = []
    for schema_def, _, go_struct in ENTITY_MAP:
        if go_struct not in go_fields or schema_def not in schema_fields:
            continue
        s_fields = schema_fields[schema_def]
        for field in sorted(go_fields[go_struct]):
            # Skip known exclusions
            if field in IMPL_EXCLUSIONS:
                continue
            # Map Go name to schema name
            if field in GO_TO_SCHEMA:
                mapped = GO_TO_SCHEMA[field]
                if mapped not in s_fields:
                    errors.append(
                        f"Go {go_struct}.{field} -> schema {schema_def}: "
                        f"expected '{mapped}', not found"
                    )
            else:
                # Go uses PascalCase, schema uses snake_case
                snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()
                if snake not in s_fields:
                    errors.append(
                        f"Go {go_struct}.{field} (as '{snake}') "
                        f"not found in schema {schema_def}"
                    )
    return errors


def _resolve_schema_to_python(schema_def: str, field: str) -> str:
    """Resolve a schema field to its Python field name."""
    qualified = f"{schema_def}.{field}"
    if qualified in SCHEMA_TO_PYTHON:
        return SCHEMA_TO_PYTHON[qualified]
    if field in SCHEMA_TO_PYTHON:
        return SCHEMA_TO_PYTHON[field]
    return field


def _resolve_schema_to_go(schema_def: str, field: str) -> str:
    """Resolve a schema field to its Go field name."""
    qualified = f"{schema_def}.{field}"
    if qualified in SCHEMA_TO_GO:
        return SCHEMA_TO_GO[qualified]
    if field in SCHEMA_TO_GO:
        return SCHEMA_TO_GO[field]
    # Convert snake_case to PascalCase
    return "".join(part.capitalize() for part in field.split("_"))


def check_schema_in_impls(
    py_fields: dict[str, set[str]],
    go_fields: dict[str, set[str]],
    schema_fields: dict[str, set[str]],
    go_source_text: str,
) -> list[str]:
    """Check that every schema field that is a real API field exists in both implementations."""
    errors: list[str] = []
    for schema_def, py_cls, go_struct in ENTITY_MAP:
        if schema_def not in schema_fields:
            continue
        py_set = py_fields.get(py_cls, set())
        go_exported = go_fields.get(go_struct, set())

        for field in sorted(schema_fields[schema_def]):
            # Skip test-only fields
            if field in SCHEMA_TEST_ONLY:
                continue
            # Skip per-entity schema exclusions (e.g. JSON discriminator "type")
            if field in SCHEMA_PER_ENTITY_EXCLUSIONS.get(schema_def, set()):
                continue

            # Check Python
            py_name = _resolve_schema_to_python(schema_def, field)
            py_check = py_name in py_set or f"_{py_name}" in py_set
            if not py_check:
                errors.append(
                    f"Schema {schema_def}.{field} (as '{py_name}') "
                    f"not found in Python {py_cls}"
                )

            # Check Go -- field may be exported (in go_exported set) or
            # unexported (lowercase in the struct body, accessed via methods).
            go_name = _resolve_schema_to_go(schema_def, field)
            go_check = go_name in go_exported
            if not go_check:
                # For unexported Go fields, verify they exist in the struct
                # body by checking for the field name in the source text
                go_check = _go_struct_has_field(go_source_text, go_struct, go_name)
            if not go_check:
                errors.append(
                    f"Schema {schema_def}.{field} (as '{go_name}') "
                    f"not found in Go {go_struct}"
                )
    return errors


def _go_struct_has_field(source: str, struct_name: str, field_name: str) -> bool:
    """Check if a Go struct has a field (exported or unexported) by parsing source."""
    pattern = re.compile(
        rf"^type\s+{re.escape(struct_name)}\s+struct\s*\{{(.*?)\n\}}",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(source)
    if not m:
        return False
    body = m.group(1)
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        field_match = re.match(r"^(\w+)\s+", line)
        if field_match and field_match.group(1) == field_name:
            return True
    return False


def check_option_funcs_coverage(
    go_fields: dict[str, set[str]],
) -> list[str]:
    """Verify that Go option functions map to known features."""
    # This is informational -- we just ensure we know about all option funcs
    known_option_funcs = {
        "Short", "Default", "Env", "Prefixed", "Choices", "Repeatable",
        "ValidateFn", "NegatableOpt",
        "ArgRequired", "ArgDefault", "Variadic",
        "WithArgs", "WithFlags", "WithTags", "WithMutex", "WithDependencies",
        "WithPassthrough", "WithEnvPrefix", "WithConfig",
        "WithConfigPath", "WithConfigFormat",
        "WithChecks",
    }
    actual = go_fields.get("_option_funcs", set())
    unknown = actual - known_option_funcs
    errors: list[str] = []
    for func_name in sorted(unknown):
        errors.append(
            f"Go option function '{func_name}' is not in the known list -- "
            f"add it to the surface check or to the exclusion list"
        )
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    py_fields = get_python_fields()
    go_source = get_go_source()
    go_fields = get_go_fields(go_source)
    schema_fields = get_schema_fields()

    all_errors: list[str] = []
    all_errors.extend(check_python_in_schema(py_fields, schema_fields))
    all_errors.extend(check_go_in_schema(go_fields, schema_fields))
    all_errors.extend(check_schema_in_impls(py_fields, go_fields, schema_fields, go_source))
    all_errors.extend(check_option_funcs_coverage(go_fields))

    if all_errors:
        print(f"API surface check FAILED ({len(all_errors)} issue(s)):\n")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("API surface check passed.")
    # Print summary
    for schema_def, py_cls, go_struct in ENTITY_MAP:
        s_count = len(schema_fields.get(schema_def, set()) - SCHEMA_TEST_ONLY)
        py_count = len({
            f for f in py_fields.get(py_cls, set())
            if not f.startswith("_") and f not in IMPL_EXCLUSIONS
        })
        go_count = len({
            f for f in go_fields.get(go_struct, set())
            if f not in IMPL_EXCLUSIONS
        })
        print(f"  {schema_def}: schema={s_count} python={py_count} go={go_count}")
    option_count = len(go_fields.get("_option_funcs", set()))
    print(f"  Go option functions: {option_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
