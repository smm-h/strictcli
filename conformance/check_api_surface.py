#!/usr/bin/env python3
"""API surface check for strictcli conformance.

Introspects Python classes, parses Go API surface via the describe_go AST
dumper, runs the TypeScript describe self-dump, reads the conformance schema,
and verifies that every real API field exists in all places (with known
exclusions for runtime-only or non-serializable features).

The Go side uses the describe_go program (conformance/describe_go/) which
parses Go source with go/ast and dumps the full API surface as JSON. This
replaces the fragile regex extraction that previously scanned Go source text.

The TypeScript side uses typescript/src/describe.ts (a hand-maintained
registry whose accuracy is enforced by typescript/tests/describe.test.ts in
both directions), run via `node dist/describe.js` after rebuilding dist so
the dump always reflects the current working tree.

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
TYPESCRIPT_DIR = PROJECT_ROOT / "typescript"

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


def _get_ts_api() -> dict:
    """Rebuild typescript/dist and run the describe.ts self-dump via node.

    Like describe_go, the dump must reflect the current working-tree state,
    so dist is rebuilt first (same discipline as run.py's _ensure_ts_harness).
    """
    build = subprocess.run(
        ["npm", "run", "build"],
        cwd=TYPESCRIPT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build.returncode != 0:
        print(f"typescript build failed (exit {build.returncode}):", file=sys.stderr)
        print(build.stdout, file=sys.stderr)
        print(build.stderr, file=sys.stderr)
        sys.exit(2)
    proc = subprocess.run(
        ["node", "dist/describe.js"],
        cwd=TYPESCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"describe.js failed (exit {proc.returncode}):", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(2)
    return json.loads(proc.stdout)


def get_ts_struct_fields_from_api(api: dict) -> dict[str, set[str]]:
    """Extract {struct_name: {member_names}} from the TS describe JSON."""
    return {s["name"]: set(s["members"]) for s in api["structs"]}


def get_ts_ctor_keys_from_api(api: dict) -> dict[str, set[str]]:
    """Extract {option_constructor_name: {option_keys}} from the TS describe JSON."""
    return {c["name"]: set(c["option_keys"]) for c in api["option_constructors"]}


def get_ts_function_names(api: dict) -> set[str]:
    """Callable public TS names: positional-arg functions + option constructors."""
    return set(api["functions"]) | {c["name"] for c in api["option_constructors"]}


def get_ts_type_names(api: dict) -> set[str]:
    """Public TS type names: type-only exports, classes, and struct interfaces."""
    return set(api["types"]) | set(api["classes"]) | {s["name"] for s in api["structs"]}


def get_ts_index_exports() -> set[str]:
    """Parse typescript/src/index.ts and return every exported name.

    Covers `export {...}`, `export type {...}`, and `export const NAME`
    forms (the only forms index.ts uses).
    """
    src = (TYPESCRIPT_DIR / "src" / "index.ts").read_text()
    names: set[str] = set()
    for m in re.finditer(r"export\s+(?:type\s+)?\{([^}]*)\}", src):
        for name in m.group(1).split(","):
            name = name.strip()
            if name:
                names.add(name)
    for m in re.finditer(r"export\s+const\s+(\w+)", src):
        names.add(m.group(1))
    return names


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

    # TypeScript struct name in the describe.ts dump.  The entity's TS name
    # universe is the struct's members plus the option_keys of its owning
    # factory (see TS_STRUCT_OPTION_CTOR).
    ts_struct: str = ""

    # TS name -> schema field.  Qualified key "TsStruct.name" or plain
    # "name".  Unmapped names fall back to camelCase -> snake_case.
    ts_to_schema: dict[str, str] = dataclasses.field(default_factory=dict)

    # Schema field -> TS name.  Qualified key "schema_def.field" or plain
    # "field".  Unmapped fields fall back to snake_case -> camelCase.
    schema_to_ts: dict[str, str] = dataclasses.field(default_factory=dict)

    # TS-specific exclusions with rationale.  Keys are checked against BOTH
    # namespaces: TS member/option names (TS -> Schema arm) and schema field
    # names (Schema -> TS arm).
    ts_entity_exclusions: dict[str, str] = dataclasses.field(default_factory=dict)


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
    "pre_test",
    "coverage_manifest",
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

# TS struct -> owning factory whose option_keys extend the entity's TS name
# universe (TS spec/option object types live under the factory in describe.ts,
# not as separate structs).
TS_STRUCT_OPTION_CTOR: dict[str, str] = {
    "FlagDef": "flag",
    "ArgDef": "arg",
    "CommandDef": "defineCommand",
    "App": "createApp",
}

_SHARED_TS_TO_SCHEMA: dict[str, str] = {
    "choices": "choices_str",
    "schema": "type",
}

_SHARED_SCHEMA_TO_TS: dict[str, str] = {
    "choices_str": "choices",
    "choices_int": "choices",
    "choices_float": "choices",
    "type": "schema",
}

# Structural TS members present on every def-union carrier; excluded from the
# TS -> Schema arm with rationale (analogous to _GLOBAL_IMPL_EXCLUSIONS).
_SHARED_TS_EXCLUSIONS: dict[str, str] = {
    "kind": "TS discriminant tag on def-union carriers (FlagDef/ArgDef/FlagSet/...), no schema analog",
    "carrier": "runtime type carrier (t.str/t.int/...); the schema 'type' string corresponds to the 'schema' member",
    "opts": "raw options object retained by the factory; its keys are checked individually via option_keys",
    "_out": "phantom type-only member for handler-arg inference, never exists at runtime",
    "allFlags": "derived merged flag map (flags + flagSets), not independent API",
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
            ts_struct="FlagDef",
            ts_to_schema=_SHARED_TS_TO_SCHEMA,
            schema_to_ts=_SHARED_SCHEMA_TO_TS,
            ts_entity_exclusions=_SHARED_TS_EXCLUSIONS,
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
            ts_struct="ArgDef",
            ts_to_schema=_SHARED_TS_TO_SCHEMA,
            schema_to_ts=_SHARED_SCHEMA_TO_TS,
            ts_entity_exclusions=_SHARED_TS_EXCLUSIONS,
        ),
        EntityDescriptor(
            schema_def="flag_set",
            python_cls="FlagSet",
            go_struct="FlagSet",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            ts_struct="FlagSet",
            ts_entity_exclusions=_SHARED_TS_EXCLUSIONS,
        ),
        EntityDescriptor(
            schema_def="mutex_group",
            python_cls="MutexGroup",
            go_struct="MutexGroup",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            ts_struct="MutexGroup",
            ts_entity_exclusions=_SHARED_TS_EXCLUSIONS,
        ),
        EntityDescriptor(
            schema_def="co_required",
            python_cls="CoRequired",
            go_struct="CoRequired",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_entity_exclusions={"type"},
            ts_struct="CoRequired",
            ts_entity_exclusions=_SHARED_TS_EXCLUSIONS,
        ),
        EntityDescriptor(
            schema_def="requires",
            python_cls="Requires",
            go_struct="Requires",
            impl_exclusions=_GLOBAL_IMPL_EXCLUSIONS,
            schema_to_go=_SHARED_SCHEMA_TO_GO,
            schema_test_only=_GLOBAL_SCHEMA_TEST_ONLY,
            schema_entity_exclusions={"type"},
            ts_struct="Requires",
            ts_entity_exclusions=_SHARED_TS_EXCLUSIONS,
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
            ts_struct="CommandDef",
            ts_to_schema=_SHARED_TS_TO_SCHEMA,
            schema_to_ts=_SHARED_SCHEMA_TO_TS,
            ts_entity_exclusions={
                **_SHARED_TS_EXCLUSIONS,
                "passthrough": "TS models passthrough commands as a separate "
                "PassthroughDef carrier (own passthrough() factory), not a "
                "bool field on CommandDef",
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
                "app.test_coverage": "testCoverage",
            },
            schema_python_runtime={
                "app.tag_contracts": "_tag_contracts (set in __post_init__, not a dataclass field)",
            },
            ts_struct="App",
            ts_to_schema={
                **_SHARED_TS_TO_SCHEMA,
                "App.flags": "global_flags",
            },
            schema_to_ts={
                **_SHARED_SCHEMA_TO_TS,
                "app.global_flags": "flags",
            },
            ts_entity_exclusions={
                **_SHARED_TS_EXCLUSIONS,
                "commands": "registered via app.command(); held in internal "
                "closure state, not exposed as an App member or AppSpec key",
                "groups": "registered via app.group(); held in internal "
                "closure state, not exposed as an App member or AppSpec key",
                "tag_contracts": "registered via the app.tagContract() method "
                "(covered by the app-method parity table), not an AppSpec key",
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
            ts_struct="Group",
            ts_entity_exclusions={
                **_SHARED_TS_EXCLUSIONS,
                "commands": "registered via group.command(); held in internal "
                "closure state, not exposed as a Group member",
                "groups": "registered via group.group(); held in internal "
                "closure state, not exposed as a Group member",
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


def _resolve_ts_to_schema(desc: EntityDescriptor, field: str) -> str:
    """Resolve a TS name to its schema field name."""
    qualified = f"{desc.ts_struct}.{field}"
    if qualified in desc.ts_to_schema:
        return desc.ts_to_schema[qualified]
    if field in desc.ts_to_schema:
        return desc.ts_to_schema[field]
    # Convert camelCase to snake_case
    return re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()


def _resolve_schema_to_ts(desc: EntityDescriptor, field: str) -> str:
    """Resolve a schema field to its TS name."""
    qualified = f"{desc.schema_def}.{field}"
    if qualified in desc.schema_to_ts:
        return desc.schema_to_ts[qualified]
    if field in desc.schema_to_ts:
        return desc.schema_to_ts[field]
    # Convert snake_case to camelCase
    parts = field.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _ts_entity_universe(
    desc: EntityDescriptor,
    ts_structs: dict[str, set[str]],
    ts_ctor_keys: dict[str, set[str]],
) -> set[str]:
    """TS names belonging to an entity: struct members + owning factory keys."""
    if not desc.ts_struct:
        return set()
    universe = set(ts_structs.get(desc.ts_struct, set()))
    ctor = TS_STRUCT_OPTION_CTOR.get(desc.ts_struct)
    if ctor is not None:
        universe |= ts_ctor_keys.get(ctor, set())
    return universe


def check_entity(
    desc: EntityDescriptor,
    py_fields: dict[str, set[str]],
    go_fields: dict[str, set[str]],
    go_all_fields: dict[str, dict[str, bool]],
    schema_fields: dict[str, set[str]],
    ts_structs: dict[str, set[str]],
    ts_ctor_keys: dict[str, set[str]],
) -> list[str]:
    """Check one entity across Python, Go, TypeScript, and schema."""
    errors: list[str] = []
    s_fields = schema_fields.get(desc.schema_def, set())
    py_set = py_fields.get(desc.python_cls, set())
    go_exported = go_fields.get(desc.go_struct, set())
    go_all = go_all_fields.get(desc.go_struct, {})
    ts_universe = _ts_entity_universe(desc, ts_structs, ts_ctor_keys)

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

    # --- TypeScript -> Schema ---
    if ts_universe and s_fields:
        for field in sorted(ts_universe):
            if field in desc.impl_exclusions:
                continue
            if field in desc.ts_entity_exclusions:
                continue

            mapped = _resolve_ts_to_schema(desc, field)
            if mapped not in s_fields:
                errors.append(
                    f"TS {desc.ts_struct}.{field} (as '{mapped}') "
                    f"not found in schema {desc.schema_def}"
                )

    # --- Schema -> all implementations ---
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

            # Check TypeScript -- struct members + owning factory option_keys
            if ts_universe and field not in desc.ts_entity_exclusions:
                ts_name = _resolve_schema_to_ts(desc, field)
                if ts_name not in ts_universe:
                    errors.append(
                        f"Schema {desc.schema_def}.{field} (as '{ts_name}') "
                        f"not found in TS {desc.ts_struct}"
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
    "WithTestCoverage",
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


# Known TS public names (TS column of the KNOWN_OPTION_FUNCS discipline):
# every name exported from typescript/src/index.ts, values and types alike.
# Must be updated when the TS public surface changes.
KNOWN_TS_PUBLIC_NAMES: set[str] = {
    # Values: factories, functions, classes, constants
    "arg", "coRequired", "createApp", "defineCommand", "deprecated",
    "errorCheckSpec", "flag", "flagSet", "implies", "mutexGroup",
    "outcome", "passthrough", "relativeToRoot", "requires", "warnCheckSpec",
    "formatCheckResults", "formatCheckResultsJSON",
    "CheckRunResult", "CheckSpec", "Context", "ErrorReporter",
    "InvokeError", "WarnReporter",
    "VERSION", "t",
    # Type-only exports
    "AnyArg", "AnyCommand", "AnyFlag", "AnyFlagSet", "AnyMutexGroup",
    "App", "AppSpec", "ArgDef", "ArgOpts", "Carrier",
    "CheckContext", "CheckOutcome", "CheckProblem", "CheckSeverity",
    "CheckStatus", "CoRequired", "CommandDef", "CommandSpec",
    "ConfigFieldSpec", "ConflictMode", "Dependency", "DeprecatedDef",
    "DictSchema", "ElemSchema", "ElementOf", "ErrorCheckSpecInit",
    "FlagDef", "FlagMap", "FlagOpts", "FlagSet", "Group", "GroupSpec",
    "Handler", "HandlerArgs", "HandlerResult", "HandlerReturn",
    "Implies", "InferHandler", "InferHandlerArgs", "InfraAccess",
    "InfraRootPath", "ListSchema", "McpIO", "MutexGroup", "Outcome",
    "PassthroughArgs", "PassthroughDef", "PassthroughHandler",
    "Requires", "Result", "RunChecksOptions", "RunChecksResult",
    "ScalarSchema", "Schema", "Tool", "WarnCheckSpecInit", "Writer",
}


def check_ts_public_names(ts_api: dict) -> list[str]:
    """Verify TS public names (describe dump + index.ts) match the known list.

    Both sources are compared against KNOWN_TS_PUBLIC_NAMES in both
    directions, so a name added to (or dropped from) either the describe
    registry or index.ts without updating the other -- or this list -- fails.
    """
    errors: list[str] = []
    describe_names = (
        get_ts_function_names(ts_api)
        | set(ts_api["classes"])
        | {c["name"] for c in ts_api["constants"]}
        | set(ts_api["types"])
    )
    index_names = get_ts_index_exports()

    for name in sorted(describe_names - KNOWN_TS_PUBLIC_NAMES):
        errors.append(
            f"TS public name '{name}' (from describe output) is not in "
            f"KNOWN_TS_PUBLIC_NAMES -- add it to the surface check"
        )
    for name in sorted(KNOWN_TS_PUBLIC_NAMES - describe_names):
        errors.append(
            f"Known TS public name '{name}' missing from describe output"
        )
    for name in sorted(index_names - KNOWN_TS_PUBLIC_NAMES):
        errors.append(
            f"TS public name '{name}' (exported from index.ts) is not in "
            f"KNOWN_TS_PUBLIC_NAMES -- add it to the surface check"
        )
    for name in sorted(KNOWN_TS_PUBLIC_NAMES - index_names):
        errors.append(
            f"Known TS public name '{name}' not exported from index.ts"
        )
    return errors


# ---------------------------------------------------------------------------
# Cross-implementation parity for public check runner API
# ---------------------------------------------------------------------------

# Types that exist in all implementations but NOT in the conformance schema.
# Columns: Python class, Go struct, TS class/interface,
# {py_field: (go_field, ts_member)}.
CHECK_RUNNER_TYPES: list[tuple[str, str, str, dict[str, tuple[str, str]]]] = [
    ("CheckRunResult", "CheckRunResult", "CheckRunResult", {
        "name": ("Name", "name"),
        "outcome": ("Outcome", "outcome"),
    }),
    ("RunChecksOptions", "RunChecksOptions", "RunChecksOptions", {
        "tag_expr": ("TagExpr", "tagExpr"),
        "name_glob": ("NameGlob", "nameGlob"),
        "run_all": ("RunAll", "runAll"),
        "ignore_warnings": ("IgnoreWarnings", "ignoreWarnings"),
    }),
]

# Methods on App that must exist in all implementations (Python, Go, TS).
CHECK_RUNNER_APP_METHODS: list[tuple[str, str, str]] = [
    ("run_checks", "RunChecks", "runChecks"),
    ("tag_contract", "TagContract", "tagContract"),
    ("register_check_provider", "RegisterCheckProvider", "registerCheckProvider"),
    ("reset_check_provider_cache", "ResetCheckProviderCache", "resetCheckProviderCache"),
]

# Module-level (Python) / package-level (Go) / module-export (TS) functions.
CHECK_RUNNER_FUNCTIONS: list[tuple[str, str, str]] = [
    ("format_check_results", "FormatCheckResults", "formatCheckResults"),
    ("format_check_results_json", "FormatCheckResultsJSON", "formatCheckResultsJSON"),
    ("error_check_spec", "NewErrorCheckSpec", "errorCheckSpec"),
    ("warn_check_spec", "NewWarnCheckSpec", "warnCheckSpec"),
]

# Public check-outcome types that must exist in ALL implementations
# (same name in Python, Go, and TS).
CHECK_RUNNER_SHARED_TYPES: list[str] = [
    "ErrorReporter",
    "WarnReporter",
    "CheckSpec",
]

# Python-only check symbols.
PYTHON_ONLY_CHECK_SYMBOLS: list[str] = [
    "SkipCheck",
]

# Go-only typed kwargs accessors (Python and TS handlers receive
# natively-typed kwargs/args, so this bug class cannot occur there).
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


def check_outcome_api(go_api: dict, ts_api: dict) -> list[str]:
    """Check the Outcome return-contract surface exists in all implementations."""
    errors: list[str] = []
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli

    # Shared branded type: Outcome exists everywhere.
    if not hasattr(strictcli, "Outcome"):
        errors.append("Python type 'Outcome' not found in strictcli module")

    go_struct_names = {s["name"] for s in go_api["structs"]}
    if "Outcome" not in go_struct_names:
        errors.append("Go type 'Outcome' not found")

    if "Outcome" not in get_ts_type_names(ts_api):
        errors.append("TS type 'Outcome' not found")

    # Python factory.
    py_funcs = get_python_module_functions()
    if "outcome" not in py_funcs:
        errors.append("Python module function 'outcome' not found")

    # TS factory.
    if "outcome" not in get_ts_function_names(ts_api):
        errors.append("TS function 'outcome' not found")

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
    ts_structs: dict[str, set[str]],
) -> list[str]:
    """Check that check runner types have matching fields in Python, Go, and TS."""
    errors: list[str] = []
    py_types = get_python_check_runner_types()

    for py_cls, go_struct, ts_struct, field_map in CHECK_RUNNER_TYPES:
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
            for go_field, _ in field_map.values():
                if go_field not in go_set:
                    errors.append(
                        f"Go {go_struct}.{go_field} not found "
                        f"(expected fields: {sorted(go_set)})"
                    )

        # Check TS members exist
        ts_set = ts_structs.get(ts_struct, set())
        if not ts_set:
            errors.append(f"TS struct {ts_struct} not found in describe output")
        else:
            for _, ts_member in field_map.values():
                if ts_member not in ts_set:
                    errors.append(
                        f"TS {ts_struct}.{ts_member} not found "
                        f"(expected members: {sorted(ts_set)})"
                    )

    return errors


def check_check_runner_methods(go_api: dict, ts_api: dict) -> list[str]:
    """Check that App methods for the check runner exist in all implementations."""
    errors: list[str] = []
    py_methods = get_python_app_methods()
    go_methods = {
        m["name"] for m in go_api["methods"]
        if m["receiver"] in ("*App", "App")
    }
    ts_methods = {
        m["name"] for m in ts_api["methods"]
        if m["receiver"] == "App"
    }

    for py_method, go_method, ts_method in CHECK_RUNNER_APP_METHODS:
        if py_method not in py_methods:
            errors.append(f"Python App.{py_method}() not found")
        if go_method not in go_methods:
            errors.append(f"Go App.{go_method}() not found")
        if ts_method not in ts_methods:
            errors.append(f"TS App.{ts_method}() not found")

    return errors


def check_check_runner_functions(go_api: dict, ts_api: dict) -> list[str]:
    """Check that package/module-level check runner functions exist everywhere."""
    errors: list[str] = []
    py_funcs = get_python_module_functions()
    go_funcs = {f["name"] for f in go_api["functions"]}
    ts_funcs = get_ts_function_names(ts_api)

    for py_func, go_func, ts_func in CHECK_RUNNER_FUNCTIONS:
        if py_func not in py_funcs:
            errors.append(f"Python module function '{py_func}' not found")
        if go_func not in go_funcs:
            errors.append(f"Go package function '{go_func}' not found")
        if ts_func not in ts_funcs:
            errors.append(f"TS function '{ts_func}' not found")

    return errors


def check_check_runner_shared_types(go_api: dict, ts_api: dict) -> list[str]:
    """Check that the shared check-outcome types exist in all implementations."""
    errors: list[str] = []
    sys.path.insert(0, str(PROJECT_ROOT / "python"))
    import strictcli

    go_struct_names = {s["name"] for s in go_api["structs"]}
    ts_type_names = get_ts_type_names(ts_api)

    for name in CHECK_RUNNER_SHARED_TYPES:
        if not hasattr(strictcli, name):
            errors.append(f"Python type '{name}' not found in strictcli module")
        if name not in go_struct_names:
            errors.append(f"Go type '{name}' not found")
        if name not in ts_type_names:
            errors.append(f"TS type '{name}' not found")

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
    ts_api = _get_ts_api()
    ts_structs = get_ts_struct_fields_from_api(ts_api)
    ts_ctor_keys = get_ts_ctor_keys_from_api(ts_api)

    descriptors = _build_descriptors()

    all_errors: list[str] = []

    # Entity checks (descriptor-driven)
    for desc in descriptors:
        all_errors.extend(
            check_entity(
                desc, py_fields, go_fields, go_all_fields, schema_fields,
                ts_structs, ts_ctor_keys,
            )
        )

    # Option function coverage
    all_errors.extend(check_option_funcs_coverage(go_fields))

    # TS public-name coverage (describe dump + index.ts vs known list)
    all_errors.extend(check_ts_public_names(ts_api))

    # Check runner parity
    all_errors.extend(check_check_runner_types(go_api, go_fields, ts_structs))
    all_errors.extend(check_check_runner_methods(go_api, ts_api))
    all_errors.extend(check_check_runner_functions(go_api, ts_api))
    all_errors.extend(check_check_runner_shared_types(go_api, ts_api))
    all_errors.extend(check_outcome_api(go_api, ts_api))

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
        ts_count = len({
            f for f in _ts_entity_universe(desc, ts_structs, ts_ctor_keys)
            if f not in desc.impl_exclusions and f not in desc.ts_entity_exclusions
        })
        print(
            f"  {desc.schema_def}: schema={s_count} python={py_count} "
            f"go={go_count} ts={ts_count}"
        )
    option_count = len(go_fields.get("_option_funcs", set()))
    print(f"  Go option functions: {option_count}")
    print(f"  TS public names: {len(KNOWN_TS_PUBLIC_NAMES)}")
    # Print check runner parity summary
    for py_cls, go_struct, ts_struct, field_map in CHECK_RUNNER_TYPES:
        print(
            f"  {py_cls}/{go_struct}/{ts_struct}: {len(field_map)} fields "
            f"(cross-impl parity)"
        )
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
