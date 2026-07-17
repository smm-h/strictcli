#!/usr/bin/env python3
"""API surface check for strictcli conformance.

Introspects Python classes, parses Go API surface via the describe_go AST
dumper, reads the conformance schema, and verifies that every real API field
exists in all three places (with known exclusions for runtime-only or
non-serializable features).

The Go side uses the describe_go program (conformance/describe_go/) which
parses Go source with go/ast and dumps the full API surface as JSON. This
replaces the fragile regex extraction that previously scanned Go source text.

Each entity (Flag, Arg, App, etc.) is described by an EntityDescriptor that
bundles the schema def name, per-language source, name maps, and exclusions.
Adding a new target is a data-entry task: provide a new descriptor with the
target's fields, name mappings, and exclusions.

Exit 0 if all checks pass, exit 1 with a diff report otherwise.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFORMANCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFORMANCE_DIR.parent
SCHEMA_PATH = CONFORMANCE_DIR / "schema.json"
DESCRIBE_GO_DIR = CONFORMANCE_DIR / "describe_go"

# ---------------------------------------------------------------------------
# Target sources: per-language field extraction
# ---------------------------------------------------------------------------


def _get_go_api() -> dict:
    """Run the describe_go AST dumper and return its JSON output.

    The dumper re-parses Go source on every invocation, so the check
    always reflects the current working-tree state.
    """
    proc = subprocess.run(
        ["go", "run", "."],
        cwd=DESCRIBE_GO_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"describe_go failed (exit {proc.returncode}):", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(2)
    return json.loads(proc.stdout)


def get_go_fields_from_api(api: dict) -> dict[str, set[str]]:
    """Extract {struct_name: {exported_field_names}} from describe_go JSON.

    Also includes '_option_funcs' key with the set of option constructor names.
    """
    result: dict[str, set[str]] = {}
    for s in api["structs"]:
        exported = {f["name"] for f in s["fields"] if f["exported"]}
        if exported:
            result[s["name"]] = exported
    result["_option_funcs"] = {f["name"] for f in api["option_constructors"]}
    return result


def get_go_all_fields_from_api(api: dict) -> dict[str, dict[str, bool]]:
    """Extract {struct_name: {field_name: exported}} from describe_go JSON.

    Includes both exported and unexported fields for schema-to-Go validation.
    """
    result: dict[str, dict[str, bool]] = {}
    for s in api["structs"]:
        result[s["name"]] = {f["name"]: f["exported"] for f in s["fields"]}
    return result


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
# Entity descriptors
#
# Each descriptor bundles everything needed to check one entity across all
# targets.  Adding a new target is data entry: provide field names, name
# maps, and exclusions in the descriptor.
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class EntityDescriptor:
    """Describes one API entity for cross-target surface checking."""

    # Schema def name (e.g., "flag"), Python class name, Go struct name
    schema_def: str
    python_cls: str
    go_struct: str

    # Python field -> schema field(s).  Qualified key "ClassName.field" for
    # per-entity overrides; plain "field" for global mappings applied to
    # this entity.
    python_to_schema: dict[str, list[str]] = dataclasses.field(default_factory=dict)

    # Go exported field -> schema field (unqualified).
    go_to_schema: dict[str, str] = dataclasses.field(default_factory=dict)

    # Schema field -> Python field.  Qualified key "schema_def.field" or
    # plain "field".
    schema_to_python: dict[str, str] = dataclasses.field(default_factory=dict)

    # Schema field -> Go field (exported or unexported).  Qualified key
    # "schema_def.field" or plain "field".
    schema_to_go: dict[str, str] = dataclasses.field(default_factory=dict)

    # Implementation fields excluded from the schema (global, keyed by field
    # name with rationale string).
    impl_exclusions: dict[str, str] = dataclasses.field(default_factory=dict)

    # Per-language entity-specific field exclusions.
    python_entity_exclusions: set[str] = dataclasses.field(default_factory=set)

    # Schema fields that are test-harness-only (not real API fields).
    schema_test_only: set[str] = dataclasses.field(default_factory=set)

    # Schema per-entity exclusions (e.g., JSON discriminator "type" field).
    schema_entity_exclusions: set[str] = dataclasses.field(default_factory=set)

    # Schema fields that map to Python runtime attributes (set in
    # __post_init__, not dataclass fields).  Rationale string.
    schema_python_runtime: dict[str, str] = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared exclusions (apply to multiple entities)
# ---------------------------------------------------------------------------

# Implementation fields excluded from the schema across all entities.
_GLOBAL_IMPL_EXCLUSIONS: dict[str, str] = {
    "validate": "callable, not serializable to JSON",
    "Validate": "callable, not serializable to JSON (Go struct field)",
    "ValidateFn": "callable, not serializable to JSON (Go option func)",
    "handler": "runtime-only (Python)",
    "Handler": "runtime-only (Go)",
    "PassthroughHandler": "runtime-only (Go)",
    "hasDefault": "private implementation detail (Go)",
    "hasConflictMode": "private implementation detail (Go)",
    "type": "Python Flag.type uses native types; schema uses 'type' string enum",
    "checks_embed": "runtime-only (bytes data, not serializable to JSON schema)",
    "checksEmbed": "runtime-only (Go field for WithChecksEmbed, not serializable to JSON schema)",
}

# Schema fields that exist only for the test harness (not real API fields).
# Shared across all entities.
_GLOBAL_SCHEMA_TEST_ONLY: set[str] = {
    "handler_prints",
    "handler_exit_code",
    "passthrough_handler_prints",
    "deprecated",
    "deprecated_message",
    "checks",
    "checks_toml",
    "providers",
    "config_content",
    "config_content_late",
    "config_fields_def",
    "handler_returns",
    "default_relative_to_root",
}

# Shared name mappings (applied to any entity that uses them).
_SHARED_PYTHON_TO_SCHEMA: dict[str, list[str]] = {
    "choices": ["choices_str", "choices_int", "choices_float"],
    "env_prefix": ["env_prefix"],
    "variadic": ["variadic"],
    "negatable": ["negatable"],
}

_SHARED_GO_TO_SCHEMA: dict[str, str] = {
    "IsVariadic": "variadic",
    "Negatable": "negatable",
    "EnvPrefix": "env_prefix",
    "EnvSeparator": "env_separator",
    "Choices": "choices_str",
    "Type": "type",
    "ConflictMode": "conflict_mode",
}

_SHARED_SCHEMA_TO_PYTHON: dict[str, str] = {
    "choices_str": "choices",
    "choices_int": "choices",
    "choices_float": "choices",
    "env_prefix": "env_prefix",
    "variadic": "variadic",
    "negatable": "negatable",
}

_SHARED_SCHEMA_TO_GO: dict[str, str] = {
    "choices_str": "Choices",
    "choices_int": "Choices",
    "choices_float": "Choices",
    "variadic": "IsVariadic",
    "negatable": "Negatable",
    "env_prefix": "EnvPrefix",
    "env_separator": "EnvSeparator",
    "type": "Type",
    "depends_on": "DependsOn",
}


def _build_descriptors() -> list[EntityDescriptor]:
    """Build the list of entity descriptors."""
    return [
        EntityDescriptor(
            schema_def="flag",
            python_cls="Flag",
            go_struct="Flag",
            python_to_schema=_SHARED_PYTHON_TO_SCHEMA,
            go_to_schema=_SHARED_GO_TO_SCHEMA,
            schema_to_python=_SHARED_SCHEMA_TO_PYTHON,
            schema_to_go=_SHARED_SCHEMA_TO_GO,
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            python_entity_exclusions={"compound", "item_type", "value_type"},
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
        ),
        EntityDescriptor(
            schema_def="arg",
            python_cls="Arg",
            go_struct="Arg",
            python_to_schema=_SHARED_PYTHON_TO_SCHEMA,
            go_to_schema=_SHARED_GO_TO_SCHEMA,
            schema_to_python=_SHARED_SCHEMA_TO_PYTHON,
            schema_to_go=_SHARED_SCHEMA_TO_GO,
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            python_entity_exclusions={"compound", "item_type"},
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
        ),
        EntityDescriptor(
            schema_def="flag_set",
            python_cls="FlagSet",
            go_struct="FlagSet",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
        ),
        EntityDescriptor(
            schema_def="mutex_group",
            python_cls="MutexGroup",
            go_struct="MutexGroup",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
        ),
        EntityDescriptor(
            schema_def="co_required",
            python_cls="CoRequired",
            go_struct="CoRequired",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_entity_exclusions={"type"},
        ),
        EntityDescriptor(
            schema_def="requires",
            python_cls="Requires",
            go_struct="Requires",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_to_go=_SHARED_SCHEMA_TO_GO,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_entity_exclusions={"type"},
        ),
        EntityDescriptor(
            schema_def="command",
            python_cls="Command",
            go_struct="Command",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            python_entity_exclusions={"needs_context"},
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_to_python={
                "command.flags": "flags",
                "command.args": "args",
            },
            schema_to_go={
                "command.flags": "flags",
                "command.args": "args",
                "command.flag_sets": "flagSets",
                "command.mutex": "mutex",
                "command.dependencies": "dependencies",
                "command.tags": "tags",
                "command.config_fields": "configFields",
            },
        ),
        EntityDescriptor(
            schema_def="app",
            python_cls="App",
            go_struct="App",
            python_to_schema={
                **_SHARED_PYTHON_TO_SCHEMA,
                "App.flags": ["global_flags"],
            },
            go_to_schema=_SHARED_GO_TO_SCHEMA,
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_to_python={
                **_SHARED_SCHEMA_TO_PYTHON,
                "app.global_flags": "flags",
                "app.commands": "_commands",
                "app.groups": "_groups",
                "app.tag_contracts": "_tag_contracts",
            },
            schema_to_go={
                **_SHARED_SCHEMA_TO_GO,
                "app.commands": "commands",
                "app.global_flags": "globalFlags",
                "app.groups": "groups",
                "app.config": "configEnabled",
                "app.config_path": "configPathOverride",
                "app.config_format": "configFormat",
                "app.no_default_config_path": "noDefaultConfigPath",
                "app.config_conflict_mode": "configConflictMode",
                "app.checks_path": "checksPath",
                "app.infra_root": "infraRootDecls",
                "app.handshake_env": "handshakeEnvs",
                "app.tag_contracts": "tagContracts",
            },
            schema_python_runtime={
                "app.tag_contracts": "_tag_contracts (set in __post_init__, not a dataclass field)",
            },
        ),
        EntityDescriptor(
            schema_def="group",
            python_cls="Group",
            go_struct="Group",
            python_to_schema=_SHARED_PYTHON_TO_SCHEMA,
            go_to_schema=_SHARED_GO_TO_SCHEMA,
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            python_entity_exclusions={"env_prefix", "deprecated"},
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_to_python=_SHARED_SCHEMA_TO_PYTHON,
            schema_to_go={
                **_SHARED_SCHEMA_TO_GO,
                "group.tags": "tags",
                "group.commands": "Commands",
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Entity checking (unified, descriptor-driven)
# ---------------------------------------------------------------------------

def _resolve_python_to_schema(desc: EntityDescriptor, field: str) -> list[str] | None:
    """Resolve a Python field to schema field(s) using the descriptor's name map."""
    qualified = f"{desc.python_cls}.{field}"
    if qualified in desc.python_to_schema:
        return desc.python_to_schema[qualified]
    if field in desc.python_to_schema:
        return desc.python_to_schema[field]
    return None


def _resolve_go_to_schema(desc: EntityDescriptor, field: str) -> str | None:
    """Resolve a Go field to its schema name using the descriptor's name map."""
    return desc.go_to_schema.get(field)


def _resolve_schema_to_python(desc: EntityDescriptor, field: str) -> str:
    """Resolve a schema field to its Python field name."""
    qualified = f"{desc.schema_def}.{field}"
    if qualified in desc.schema_to_python:
        return desc.schema_to_python[qualified]
    if field in desc.schema_to_python:
        return desc.schema_to_python[field]
    return field


def _resolve_schema_to_go(desc: EntityDescriptor, field: str) -> str:
    """Resolve a schema field to its Go field name."""
    qualified = f"{desc.schema_def}.{field}"
    if qualified in desc.schema_to_go:
        return desc.schema_to_go[qualified]
    if field in desc.schema_to_go:
        return desc.schema_to_go[field]
    # Convert snake_case to PascalCase
    return "".join(part.capitalize() for part in field.split("_"))


def check_entity(
    desc: EntityDescriptor,
    py_fields: dict[str, set[str]],
    go_fields: dict[str, set[str]],
    go_all_fields: dict[str, dict[str, bool]],
    schema_fields: dict[str, set[str]],
) -> list[str]:
    """Check one entity across Python, Go, and schema using its descriptor."""
    errors: list[str] = []
    s_fields = schema_fields.get(desc.schema_def, set())
    py_set = py_fields.get(desc.python_cls, set())
    go_exported = go_fields.get(desc.go_struct, set())
    go_all = go_all_fields.get(desc.go_struct, {})

    # --- Python -> Schema ---
    if py_set and s_fields:
        for field in sorted(py_set):
            if field.startswith("_"):
                continue
            if field in desc.impl_exclusions:
                continue
            if field in desc.python_entity_exclusions:
                continue

            mapped = _resolve_python_to_schema(desc, field)
            if mapped is not None:
                if not any(m in s_fields for m in mapped):
                    errors.append(
                        f"Python {desc.python_cls}.{field} -> schema {desc.schema_def}: "
                        f"expected one of {mapped}, found none"
                    )
            elif field not in s_fields:
                errors.append(
                    f"Python {desc.python_cls}.{field} not found in schema {desc.schema_def}"
                )

    # --- Go -> Schema ---
    if go_exported and s_fields:
        for field in sorted(go_exported):
            if field in desc.impl_exclusions:
                continue

            mapped = _resolve_go_to_schema(desc, field)
            if mapped is not None:
                if mapped not in s_fields:
                    errors.append(
                        f"Go {desc.go_struct}.{field} -> schema {desc.schema_def}: "
                        f"expected '{mapped}', not found"
                    )
            else:
                # Go PascalCase -> snake_case
                snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()
                if snake not in s_fields:
                    errors.append(
                        f"Go {desc.go_struct}.{field} (as '{snake}') "
                        f"not found in schema {desc.schema_def}"
                    )

    # --- Schema -> both implementations ---
    if s_fields:
        for field in sorted(s_fields):
            if field in desc.schema_test_only:
                continue
            if field in desc.schema_entity_exclusions:
                continue

            # Check Python
            py_name = _resolve_schema_to_python(desc, field)
            py_check = py_name in py_set or f"_{py_name}" in py_set
            qualified_py = f"{desc.schema_def}.{field}"
            if not py_check and qualified_py in desc.schema_python_runtime:
                py_check = True
            if not py_check:
                errors.append(
                    f"Schema {desc.schema_def}.{field} (as '{py_name}') "
                    f"not found in Python {desc.python_cls}"
                )

            # Check Go -- use describe_go's full field list (exported + unexported)
            go_name = _resolve_schema_to_go(desc, field)
            go_check = go_name in go_all
            if not go_check:
                errors.append(
                    f"Schema {desc.schema_def}.{field} (as '{go_name}') "
                    f"not found in Go {desc.go_struct}"
                )

    return errors


# ---------------------------------------------------------------------------
# Option function coverage check
# ---------------------------------------------------------------------------

# Known Go option constructors (must be updated when new ones are added).
KNOWN_OPTION_FUNCS: set[str] = {
    "Short", "Default", "Env", "Prefixed", "Choices", "Repeatable",
    "ValidateFn", "NegatableOpt",
    "ArgRequired", "ArgDefault", "Variadic", "ArgType", "ArgChoices",
    "WithArgs", "WithFlags", "WithFlagSets", "WithMutex", "WithDependencies",
    "WithPassthrough", "WithEnvPrefix", "WithConfig",
    "WithConfigPath", "WithConfigFormat",
    "WithChecks", "WithChecksEmbed",
    "WithTags",
    "WithHidden", "WithInteractive", "WithConfigFields",
    "Unique", "EnvSeparator", "ConflictMode",
    "WithNoDefaultConfigPath",
    "WithConfigConflictMode",
    "WithInfraRoot", "WithHandshakeEnv", "WithConfigPathRelativeToRoot",
    "RelativeToRoot",
    # ConfigFieldOption constructors (from describe_go, not matched by old regex)
    "ConfigFieldDefault", "ConfigFieldHelp", "ConfigFieldType",
}


def check_option_funcs_coverage(go_fields: dict[str, set[str]]) -> list[str]:
    """Verify that Go option functions map to known features."""
    actual = go_fields.get("_option_funcs", set())
    unknown = actual - KNOWN_OPTION_FUNCS
    errors: list[str] = []
    for func_name in sorted(unknown):
        errors.append(
            f"Go option function '{func_name}' is not in the known list -- "
            f"add it to the surface check or to the exclusion list"
        )
    return errors


# ---------------------------------------------------------------------------
# Cross-implementation parity for public check runner API
# ---------------------------------------------------------------------------

# Types that exist in both implementations but NOT in the conformance schema.
CHECK_RUNNER_TYPES: list[tuple[str, str, dict[str, str]]] = [
    ("CheckRunResult", "CheckRunResult", {
        "name": "Name",
        "outcome": "Outcome",
    }),
    ("RunChecksOptions", "RunChecksOptions", {
        "tag_expr": "TagExpr",
        "name_glob": "NameGlob",
        "run_all": "RunAll",
        "ignore_warnings": "IgnoreWarnings",
    }),
]

# Methods on App that must exist in both implementations.
CHECK_RUNNER_APP_METHODS: list[tuple[str, str]] = [
    ("run_checks", "RunChecks"),
    ("tag_contract", "TagContract"),
    ("register_check_provider", "RegisterCheckProvider"),
    ("reset_check_provider_cache", "ResetCheckProviderCache"),
]

# Module-level (Python) / package-level (Go) functions.
CHECK_RUNNER_FUNCTIONS: list[tuple[str, str]] = [
    ("format_check_results", "FormatCheckResults"),
    ("format_check_results_json", "FormatCheckResultsJSON"),
    ("error_check_spec", "NewErrorCheckSpec"),
    ("warn_check_spec", "NewWarnCheckSpec"),
]

# Public check-outcome types that must exist in BOTH implementations.
CHECK_RUNNER_SHARED_TYPES: list[str] = [
    "ErrorReporter",
    "WarnReporter",
    "CheckSpec",
]

# Python-only check symbols.
PYTHON_ONLY_CHECK_SYMBOLS: list[str] = [
    "SkipCheck",
]

# Go-only typed kwargs accessors (Python handlers receive natively-typed **kwargs).
OUTCOME_GO_ONLY_ACCESSORS: list[str] = ["Get", "GetOpt"]


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


def get_python_check_runner_types() -> dict[str, set[str]]:
    """Return {class_name: {field_names}} for Python check runner dataclasses."""
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli
    result: dict[str, set[str]] = {}
    for cls in [strictcli.CheckRunResult]:
        fields = {f.name for f in dataclasses.fields(cls)}
        result[cls.__name__] = fields
    return result


def check_outcome_api(go_api: dict) -> list[str]:
    """Check the Outcome return-contract surface exists in both implementations."""
    errors: list[str] = []
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli

    # Shared branded type: Outcome exists in both.
    if not hasattr(strictcli, "Outcome"):
        errors.append("Python type 'Outcome' not found in strictcli module")

    go_struct_names = {s["name"] for s in go_api["structs"]}
    if "Outcome" not in go_struct_names:
        errors.append("Go type 'Outcome' not found")

    # Python factory.
    py_funcs = get_python_module_functions()
    if "outcome" not in py_funcs:
        errors.append("Python module function 'outcome' not found")

    # Go constructors (package-level funcs).
    go_func_names = {f["name"] for f in go_api["functions"]}
    for gofn in ("Exit", "ExitData"):
        if gofn not in go_func_names:
            errors.append(f"Go constructor '{gofn}' not found")

    # Go-only generic typed accessors.
    go_generic_names = {f["name"] for f in go_api["generic_functions"]}
    for gofn in OUTCOME_GO_ONLY_ACCESSORS:
        if gofn not in go_generic_names:
            errors.append(f"Go generic accessor '{gofn}' not found")

    return errors


def check_check_runner_types(
    go_api: dict,
    go_fields: dict[str, set[str]],
) -> list[str]:
    """Check that check runner types have matching fields in Python and Go."""
    errors: list[str] = []
    py_types = get_python_check_runner_types()

    for py_cls, go_struct, field_map in CHECK_RUNNER_TYPES:
        # Check Python fields exist
        py_set = py_types.get(py_cls, set())
        if not py_set and py_cls == "RunChecksOptions":
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


def check_check_runner_methods(go_api: dict) -> list[str]:
    """Check that App methods for the check runner exist in both implementations."""
    errors: list[str] = []
    py_methods = get_python_app_methods()
    go_methods = {
        m["name"] for m in go_api["methods"]
        if m["receiver"] in ("*App", "App")
    }

    for py_method, go_method in CHECK_RUNNER_APP_METHODS:
        if py_method not in py_methods:
            errors.append(f"Python App.{py_method}() not found")
        if go_method not in go_methods:
            errors.append(f"Go App.{go_method}() not found")

    return errors


def check_check_runner_functions(go_api: dict) -> list[str]:
    """Check that package/module-level functions for the check runner exist in both."""
    errors: list[str] = []
    py_funcs = get_python_module_functions()
    go_funcs = {f["name"] for f in go_api["functions"]}

    for py_func, go_func in CHECK_RUNNER_FUNCTIONS:
        if py_func not in py_funcs:
            errors.append(f"Python module function '{py_func}' not found")
        if go_func not in go_funcs:
            errors.append(f"Go package function '{go_func}' not found")

    return errors


def check_check_runner_shared_types(go_api: dict) -> list[str]:
    """Check that the shared check-outcome types exist in both implementations."""
    errors: list[str] = []
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli

    go_struct_names = {s["name"] for s in go_api["structs"]}

    for name in CHECK_RUNNER_SHARED_TYPES:
        if not hasattr(strictcli, name):
            errors.append(f"Python type '{name}' not found in strictcli module")
        if name not in go_struct_names:
            errors.append(f"Go type '{name}' not found")

    for name in PYTHON_ONLY_CHECK_SYMBOLS:
        if not hasattr(strictcli, name):
            errors.append(f"Python-only symbol '{name}' not found in strictcli module")

    return errors


# ---------------------------------------------------------------------------
# New-target stub generator
# ---------------------------------------------------------------------------

def generate_target_stub(target_name: str) -> EntityDescriptor:
    """Generate a descriptor stub for a hypothetical new target.

    Every field is empty -- the caller must fill in field names, name maps,
    and exclusions for the new target.  This demonstrates that adding a
    target is purely data entry.
    """
    return EntityDescriptor(
        schema_def="example",
        python_cls="Example",
        go_struct="Example",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    py_fields = get_python_fields()
    go_api = _get_go_api()
    go_fields = get_go_fields_from_api(go_api)
    go_all_fields = get_go_all_fields_from_api(go_api)
    schema_fields = get_schema_fields()

    descriptors = _build_descriptors()

    all_errors: list[str] = []

    # Entity checks (descriptor-driven)
    for desc in descriptors:
        all_errors.extend(
            check_entity(desc, py_fields, go_fields, go_all_fields, schema_fields)
        )

    # Option function coverage
    all_errors.extend(check_option_funcs_coverage(go_fields))

    # Check runner parity
    all_errors.extend(check_check_runner_types(go_api, go_fields))
    all_errors.extend(check_check_runner_methods(go_api))
    all_errors.extend(check_check_runner_functions(go_api))
    all_errors.extend(check_check_runner_shared_types(go_api))
    all_errors.extend(check_outcome_api(go_api))

    if all_errors:
        print(f"API surface check FAILED ({len(all_errors)} issue(s)):\n")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("API surface check passed.")
    # Print summary
    for desc in descriptors:
        s_count = len(schema_fields.get(desc.schema_def, set()) - desc.schema_test_only)
        py_count = len({
            f for f in py_fields.get(desc.python_cls, set())
            if not f.startswith("_") and f not in desc.impl_exclusions
        })
        go_count = len({
            f for f in go_fields.get(desc.go_struct, set())
            if f not in desc.impl_exclusions
        })
        print(f"  {desc.schema_def}: schema={s_count} python={py_count} go={go_count}")
    option_count = len(go_fields.get("_option_funcs", set()))
    print(f"  Go option functions: {option_count}")
    # Print check runner parity summary
    for py_cls, go_struct, field_map in CHECK_RUNNER_TYPES:
        print(f"  {py_cls}/{go_struct}: {len(field_map)} fields (cross-impl parity)")
    print(f"  App methods (check runner): {len(CHECK_RUNNER_APP_METHODS)}")
    print(f"  Package functions (check runner): {len(CHECK_RUNNER_FUNCTIONS)}")
    print(f"  Shared check types (cross-impl): {len(CHECK_RUNNER_SHARED_TYPES)}")
    print(f"  Python-only check symbols: {len(PYTHON_ONLY_CHECK_SYMBOLS)}")
    print(f"  Outcome API: Outcome type + outcome()/Exit/ExitData + Go accessors {OUTCOME_GO_ONLY_ACCESSORS}")
    # New-target diagnostic
    stub = generate_target_stub("rust")
    print(f"  New-target stub: {len(dataclasses.fields(stub))} fields to fill per entity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
