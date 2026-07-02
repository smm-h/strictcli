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
GO_SOURCE_DIR = PROJECT_ROOT / "go" / "strictcli"

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
    "checks_embed": "runtime-only (bytes data, not serializable to JSON schema)",
    "checksEmbed": "runtime-only (Go field for WithChecksEmbed, not serializable to JSON schema)",
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
    # Python-only compound type fields. Go encodes compound types in the
    # FlagType bitfield, so these have no Go or schema counterpart.
    "Flag": {"compound", "item_type", "value_type"},
    "Arg": {"compound", "item_type"},
    # Python Command.needs_context is derived from handler type annotations
    # at registration time (first param annotated as Context). Go uses a
    # different dispatch mechanism (struct handlers with explicit Context
    # field). Not a user-facing schema concept.
    "Command": {"needs_context"},
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
    # config_content provides inline config file content for test cases --
    # not a real App parameter (the test runner writes it to a temp file).
    "config_content",
    # config_fields_def defines config field registrations in test cases --
    # not a real App struct field (it drives code generation).
    "config_fields_def",
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
    "EnvSeparator": "env_separator",
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
    "app.tag_contracts": "_tag_contracts",
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
    "env_separator": "EnvSeparator",
    "type": "Type",
    "depends_on": "DependsOn",
    "app.commands": "commands",  # Go App.commands (unexported, set via method)
    "app.global_flags": "globalFlags",  # Go App.globalFlags (unexported, set via method)
    "app.groups": "groups",  # Go App.groups (unexported, set via method)
    "app.config": "configEnabled",  # Go App.configEnabled (unexported, set via WithConfig())
    "app.config_path": "configPathOverride",  # Go App.configPathOverride (unexported, set via WithConfigPath())
    "app.config_format": "configFormat",  # Go App.configFormat (unexported, set via WithConfigFormat())
    "app.checks_path": "checksPath",  # Go App.checksPath (unexported, set via WithChecks())
    "app.tag_contracts": "tagContracts",  # Go App.tagContracts (unexported, set via TagContract())
    "command.flags": "flags",  # Go Command.flags (unexported)
    "command.args": "args",  # Go Command.args (unexported)
    "command.flag_sets": "flagSets",  # Go Command.flagSets (unexported)
    "command.mutex": "mutex",  # Go Command.mutex (unexported)
    "command.dependencies": "dependencies",  # Go Command.dependencies (unexported)
    "command.tags": "tags",  # Go Command.tags (unexported)
    "command.config_fields": "configFields",  # Go Command.configFields (unexported)
    "group.tags": "tags",  # Go Group.tags (unexported)
    "group.commands": "Commands",  # Go Group.Commands (exported)
}

# Schema fields that map to Python runtime attributes (set in __post_init__,
# not dataclass fields). These pass the Python check unconditionally since
# get_python_fields() only collects dataclass fields.
SCHEMA_PYTHON_RUNTIME_ATTRS: dict[str, str] = {
    "app.tag_contracts": "_tag_contracts (set in __post_init__, not a dataclass field)",
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
        strictcli.Flag, strictcli.Arg, strictcli.FlagSet,
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
    """Return the combined Go source text from all non-test files."""
    parts = []
    for p in sorted(GO_SOURCE_DIR.glob("*.go")):
        if p.name.endswith("_test.go"):
            continue
        parts.append(p.read_text())
    return "\n".join(parts)


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
    ("flag_set", "FlagSet", "FlagSet"),
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
            # Also accept runtime attributes (set in __post_init__, not dataclass fields)
            qualified_py = f"{schema_def}.{field}"
            if not py_check and qualified_py in SCHEMA_PYTHON_RUNTIME_ATTRS:
                py_check = True
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
        "ArgRequired", "ArgDefault", "Variadic", "ArgType", "ArgChoices",
        "WithArgs", "WithFlags", "WithFlagSets", "WithMutex", "WithDependencies",
        "WithPassthrough", "WithEnvPrefix", "WithConfig",
        "WithConfigPath", "WithConfigFormat",
        "WithChecks", "WithChecksEmbed",
        "WithTags",
        "WithHidden", "WithInteractive", "WithConfigFields",
        "Unique", "EnvSeparator",
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
# 5. Cross-implementation parity for public check runner API
# ---------------------------------------------------------------------------

# Types that exist in both implementations but NOT in the conformance schema.
# (python_class, go_struct, {python_field: go_field})
CHECK_RUNNER_TYPES: list[tuple[str, str, dict[str, str]]] = [
    ("CheckRunResult", "CheckRunResult", {
        "name": "Name",
        "result": "Result",
    }),
    ("RunChecksOptions", "RunChecksOptions", {
        "tag_expr": "TagExpr",
        "name_glob": "NameGlob",
        "run_all": "RunAll",
        "ignore_warnings": "IgnoreWarnings",
    }),
]

# Methods on App that must exist in both implementations.
# (python_method, go_method)
CHECK_RUNNER_APP_METHODS: list[tuple[str, str]] = [
    ("run_checks", "RunChecks"),
    ("tag_contract", "TagContract"),
]

# Module-level (Python) / package-level (Go) functions.
# (python_func, go_func)
CHECK_RUNNER_FUNCTIONS: list[tuple[str, str]] = [
    ("format_check_results", "FormatCheckResults"),
    ("format_check_results_json", "FormatCheckResultsJSON"),
]


def get_python_check_runner_types() -> dict[str, set[str]]:
    """Return {class_name: {field_names}} for Python check runner dataclasses."""
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli

    result: dict[str, set[str]] = {}
    for cls in [strictcli.CheckRunResult]:
        fields = {f.name for f in dataclasses.fields(cls)}
        result[cls.__name__] = fields
    return result


def get_python_module_functions() -> set[str]:
    """Return the set of public function names in the strictcli module."""
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli
    return {
        name for name, obj in inspect.getmembers(strictcli, inspect.isfunction)
        if not name.startswith("_")
    }


def get_python_app_methods() -> set[str]:
    """Return the set of public method names on the App class."""
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli
    return {
        name for name, obj in inspect.getmembers(strictcli.App, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def get_go_exported_funcs(source: str) -> set[str]:
    """Return exported package-level function names (not methods) from Go source."""
    # Match: func FuncName(...) but NOT func (receiver) FuncName(...)
    pattern = re.compile(r"^func\s+([A-Z]\w*)\(", re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(source)}


def get_go_app_methods(source: str) -> set[str]:
    """Return exported method names on App from Go source."""
    # Match: func (a *App) MethodName(... or func (a App) MethodName(...
    pattern = re.compile(r"^func\s+\(\w+\s+\*?App\)\s+([A-Z]\w*)\(", re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(source)}


def check_check_runner_types(
    go_source: str,
    go_fields: dict[str, set[str]],
) -> list[str]:
    """Check that check runner types have matching fields in Python and Go."""
    errors: list[str] = []
    py_types = get_python_check_runner_types()

    for py_cls, go_struct, field_map in CHECK_RUNNER_TYPES:
        # Check Python fields exist
        py_set = py_types.get(py_cls, set())
        if not py_set and py_cls == "RunChecksOptions":
            # RunChecksOptions is not a Python dataclass -- it's kwargs on run_checks().
            # Check that the method signature has the right parameters instead.
            py_app_methods = get_python_app_methods()
            if "run_checks" not in py_app_methods:
                errors.append(
                    f"Python App.run_checks() not found (needed for RunChecksOptions parity)"
                )
            else:
                import strictcli
                sig = inspect.signature(strictcli.App.run_checks)
                py_params = set(sig.parameters.keys()) - {"self"}
                for py_field in field_map:
                    if py_field not in py_params:
                        errors.append(
                            f"RunChecksOptions field '{py_field}' not in Python "
                            f"App.run_checks() parameters: {sorted(py_params)}"
                        )
        else:
            for py_field in field_map:
                if py_field not in py_set:
                    errors.append(
                        f"Python {py_cls}.{py_field} not found "
                        f"(expected fields: {sorted(py_set)})"
                    )

        # Check Go fields exist
        go_set = go_fields.get(go_struct, set())
        if not go_set:
            errors.append(f"Go struct {go_struct} not found in source")
        else:
            for go_field in field_map.values():
                if go_field not in go_set:
                    errors.append(
                        f"Go {go_struct}.{go_field} not found "
                        f"(expected fields: {sorted(go_set)})"
                    )

    return errors


def check_check_runner_methods(go_source: str) -> list[str]:
    """Check that App methods for the check runner exist in both implementations."""
    errors: list[str] = []
    py_methods = get_python_app_methods()
    go_methods = get_go_app_methods(go_source)

    for py_method, go_method in CHECK_RUNNER_APP_METHODS:
        if py_method not in py_methods:
            errors.append(f"Python App.{py_method}() not found")
        if go_method not in go_methods:
            errors.append(f"Go App.{go_method}() not found")

    return errors


def check_check_runner_functions(go_source: str) -> list[str]:
    """Check that package/module-level functions for the check runner exist in both."""
    errors: list[str] = []
    py_funcs = get_python_module_functions()
    go_funcs = get_go_exported_funcs(go_source)

    for py_func, go_func in CHECK_RUNNER_FUNCTIONS:
        if py_func not in py_funcs:
            errors.append(f"Python module function '{py_func}' not found")
        if go_func not in go_funcs:
            errors.append(f"Go package function '{go_func}' not found")

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
    all_errors.extend(check_check_runner_types(go_source, go_fields))
    all_errors.extend(check_check_runner_methods(go_source))
    all_errors.extend(check_check_runner_functions(go_source))

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
    # Print check runner parity summary
    for py_cls, go_struct, field_map in CHECK_RUNNER_TYPES:
        print(f"  {py_cls}/{go_struct}: {len(field_map)} fields (cross-impl parity)")
    print(f"  App methods (check runner): {len(CHECK_RUNNER_APP_METHODS)}")
    print(f"  Package functions (check runner): {len(CHECK_RUNNER_FUNCTIONS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
