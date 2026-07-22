#!/usr/bin/env python3
"""Schema parity check for strictcli conformance.

Defines a rich app (covering all feature combinations), runs --dump-schema on
every registered target (Python, Go, TypeScript), and compares the resulting
JSON schemas structurally N-way. All targets must produce identical schemas;
any difference is a parity gap, reported with the odd one(s) out.

Exit 0 if all schemas are identical, exit 1 with a diff report otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CONFORMANCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFORMANCE_DIR.parent
GO_PKG_DIR = PROJECT_ROOT / "go"
HARNESS_DIR = CONFORMANCE_DIR / "harness"
TS_DIR = PROJECT_ROOT / "typescript"
HARNESS_TS_ENTRY = CONFORMANCE_DIR / "harness_ts" / "main.js"

# Registration order is also the reporting order for N-way comparison.
TARGET_NAMES = ["python", "go", "typescript"]

# ---------------------------------------------------------------------------
# App definitions -- each exercises a different feature surface
# ---------------------------------------------------------------------------

# A rich app definition covering: all flag types, args, groups, nested groups,
# deprecated commands, mutex groups, dependencies (CoRequired, Requires, Implies),
# choices, repeatable flags, unique, env, env_separator, passthrough commands,
# config, tags, flag_sets, optional args, variadic args, negatable, prefixed,
# and short flags.
RICH_APP = {
    "name": "richapp",
    "version": "2.5.0",
    "help": "A comprehensive test app for schema parity",
    "env_prefix": "RICH",
    "config": True,
    "infra_root": {"RICH_HOME": "/var/lib/richapp"},
    "handshake_env": {"RICH_SESSION": "Session token from the invoking process"},
    "global_flags": [
        {
            "name": "verbose",
            "type": "bool",
            "help": "Enable verbose output",
            "short": "V",
            "default": False,
        },
        {
            "name": "log-level",
            "type": "str",
            "help": "Logging level",
            "default": "info",
            "env": "RICH_LOG_LEVEL",
            "choices_str": ["debug", "info", "warn", "error"],
        },
        # Global flag with a RelativeToRoot marker default. Locks in that markers
        # serialize identically (machine-stable) across both implementations.
        {
            "name": "state-file",
            "type": "str",
            "help": "State file relative to the infra root",
            "default_relative_to_root": {
                "env_var": "RICH_HOME",
                "parts": ["state", "app.db"],
            },
        },
    ],
    "commands": [
        # 1. Simple command with all flag types
        {
            "name": "types",
            "help": "Test all flag types",
            "handler_prints": "types",
            "flags": [
                {
                    "name": "name",
                    "type": "str",
                    "help": "A string flag",
                    "default": "world",
                },
                {
                    "name": "count",
                    "type": "int",
                    "help": "An integer flag",
                    "default": 42,
                },
                {
                    "name": "ratio",
                    "type": "float",
                    "help": "A float flag",
                    "default": 3.14,
                },
                {
                    "name": "dry-run",
                    "type": "bool",
                    "help": "Dry run mode",
                },
                # Command flag with a RelativeToRoot marker default.
                {
                    "name": "cache-file",
                    "type": "str",
                    "help": "Cache file relative to the infra root",
                    "default_relative_to_root": {
                        "env_var": "RICH_HOME",
                        "parts": ["cache.bin"],
                    },
                },
            ],
            "args": [
                {
                    "name": "target",
                    "help": "Target to process",
                },
            ],
        },
        # 2. Command with repeatable/unique flags and env_separator
        {
            "name": "multi",
            "help": "Test repeatable flags",
            "handler_prints": "multi",
            "flags": [
                {
                    "name": "tag",
                    "type": "str",
                    "help": "Tags to apply",
                    "repeatable": True,
                    "unique": True,
                    "env": "RICH_TAGS",
                    "env_separator": ",",
                },
                {
                    "name": "port",
                    "type": "int",
                    "help": "Ports to open",
                    "repeatable": True,
                    "unique": False,
                    "default": [80, 443],
                },
            ],
        },
        # 3. Command with mutex groups
        {
            "name": "output",
            "help": "Test mutex flags",
            "handler_prints": "output",
            "mutex": [
                {
                    "flags": [
                        {
                            "name": "json",
                            "type": "bool",
                            "help": "JSON output",
                        },
                        {
                            "name": "yaml",
                            "type": "bool",
                            "help": "YAML output",
                        },
                        {
                            "name": "text",
                            "type": "bool",
                            "help": "Text output",
                        },
                    ],
                },
            ],
        },
        # 4. Command with dependencies (CoRequired, Requires, Implies)
        {
            "name": "deploy",
            "help": "Test dependencies",
            "handler_prints": "deploy",
            "flags": [
                {
                    "name": "host",
                    "type": "str",
                    "help": "Deploy host",
                    "default": None,
                },
                {
                    "name": "port-num",
                    "type": "int",
                    "help": "Deploy port",
                    "default": None,
                },
                {
                    "name": "ssl",
                    "type": "bool",
                    "help": "Use SSL",
                },
                {
                    "name": "cert",
                    "type": "str",
                    "help": "SSL certificate path",
                    "default": None,
                },
            ],
            "dependencies": [
                {
                    "type": "co_required",
                    "flags": ["host", "port-num"],
                },
                {
                    "type": "requires",
                    "flag": "cert",
                    "depends_on": "ssl",
                },
            ],
        },
        # 5. Command with Implies dependency
        {
            "name": "notify",
            "help": "Test implies dependency",
            "handler_prints": "notify",
            "flags": [
                {
                    "name": "email",
                    "type": "bool",
                    "help": "Send email notification",
                },
                {
                    "name": "alert",
                    "type": "bool",
                    "help": "Enable alerts",
                },
            ],
            "dependencies": [
                {
                    "type": "implies",
                    "flag": "email",
                    "implies": "alert",
                    "value": True,
                },
            ],
        },
        # 6. Command with flag_sets
        {
            "name": "query",
            "help": "Test flag sets",
            "handler_prints": "query",
            "flag_sets": [
                {
                    "name": "pagination",
                    "flags": [
                        {
                            "name": "page",
                            "type": "int",
                            "help": "Page number",
                            "default": 1,
                        },
                        {
                            "name": "per-page",
                            "type": "int",
                            "help": "Items per page",
                            "default": 20,
                        },
                    ],
                },
            ],
        },
        # 6. Command with optional/variadic args
        {
            "name": "files",
            "help": "Test args",
            "handler_prints": "files",
            "args": [
                {
                    "name": "src",
                    "help": "Source directory",
                },
                {
                    "name": "extra",
                    "help": "Extra files",
                    "required": False,
                    "variadic": True,
                },
            ],
        },
        # 7. Passthrough command
        {
            "name": "exec",
            "help": "Execute a command",
            "passthrough": True,
            "handler_prints": "exec",
            "passthrough_handler_prints": "exec:{name}:{args}",
        },
        # 8. Command with tags
        {
            "name": "lint",
            "help": "Run linters",
            "handler_prints": "lint",
            "tags": ["quality", "ci"],
        },
        # 9. Deprecated command
        {
            "name": "old-cmd",
            "help": "Deprecated command",
            "deprecated": True,
            "deprecated_message": "Use 'new-cmd' instead",
        },
        # 10. Command with choices (int and float)
        {
            "name": "level",
            "help": "Test int/float choices",
            "handler_prints": "level",
            "flags": [
                {
                    "name": "priority",
                    "type": "int",
                    "help": "Priority level",
                    "choices_int": [1, 2, 3, 4, 5],
                    "default": 3,
                },
                {
                    "name": "threshold",
                    "type": "float",
                    "help": "Threshold value",
                    "choices_float": [0.1, 0.5, 0.9],
                    "default": 0.5,
                },
            ],
        },
        # 11. Command with short flag and prefixed env
        {
            "name": "info",
            "help": "Show info",
            "handler_prints": "info",
            "flags": [
                {
                    "name": "format",
                    "type": "str",
                    "help": "Output format",
                    "short": "f",
                    "default": "table",
                    "prefixed": True,
                },
                {
                    "name": "color-off",
                    "type": "bool",
                    "help": "Disable colors",
                    "negatable": False,
                },
            ],
        },
    ],
    "groups": [
        {
            "name": "db",
            "help": "Database operations",
            "tags": ["infra"],
            "commands": [
                {
                    "name": "migrate",
                    "help": "Run migrations",
                    "handler_prints": "migrate",
                    "flags": [
                        {
                            "name": "steps",
                            "type": "int",
                            "help": "Migration steps",
                            "default": None,
                        },
                    ],
                },
                {
                    "name": "seed",
                    "help": "Seed database",
                    "handler_prints": "seed",
                },
                # Deprecated command in group
                {
                    "name": "reset",
                    "help": "Reset database",
                    "deprecated": True,
                    "deprecated_message": "Use 'db migrate --steps -1' instead",
                },
            ],
            "groups": [
                # Nested group
                {
                    "name": "cache",
                    "help": "Cache operations",
                    "commands": [
                        {
                            "name": "clear",
                            "help": "Clear cache",
                            "handler_prints": "clear",
                        },
                        {
                            "name": "stats",
                            "help": "Show cache stats",
                            "handler_prints": "stats",
                            "flags": [
                                {
                                    "name": "detailed",
                                    "type": "bool",
                                    "help": "Show detailed stats",
                                },
                            ],
                        },
                    ],
                },
            ],
        },
    ],
}

# Minimal app -- tests that empty/default fields are also handled identically
MINIMAL_APP = {
    "name": "minimal",
    "version": "0.1.0",
    "help": "A minimal app",
    "commands": [
        {
            "name": "hello",
            "help": "Say hello",
            "handler_prints": "hello",
        },
    ],
}

# Config fields app -- tests that config_fields schema format matches
CONFIG_APP = {
    "name": "cfgapp",
    "version": "1.0.0",
    "help": "An app with config fields",
    "config": True,
    "config_fields_def": [
        {
            "name": "api.key",
            "type": "str",
            "help": "API key for the service",
        },
        {
            "name": "port",
            "type": "int",
            "help": "Port to listen on",
            "default": 8080,
        },
        {
            "name": "debug",
            "type": "bool",
            "help": "Enable debug mode",
            "default": False,
        },
    ],
    "commands": [
        {
            "name": "serve",
            "help": "Start the server",
            "handler_prints": "serve",
            "config_fields": ["api.key", "port"],
        },
        {
            "name": "status",
            "help": "Show status",
            "handler_prints": "status",
        },
    ],
}


# ---------------------------------------------------------------------------
# Helpers for running apps
# ---------------------------------------------------------------------------


def _make_project_dir(target: str, app_name: str) -> str:
    """Create a temp directory with the project file needed for --dump-schema."""
    d = tempfile.mkdtemp(prefix="strictcli_schema_")
    if target == "go":
        with open(os.path.join(d, "go.mod"), "w") as f:
            f.write(f"module {app_name}\n\ngo 1.21\n")
    elif target == "python":
        with open(os.path.join(d, "pyproject.toml"), "w") as f:
            f.write(f'[project]\nname = "{app_name}"\n')
    elif target == "typescript":
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"name": app_name}, f)
            f.write("\n")
    return d


def _generate_python_script(app_def: dict) -> str:
    """Generate a Python script from an app definition."""
    sys.path.insert(0, str(CONFORMANCE_DIR))
    from ref_python import generate
    script = generate(app_def)
    # Fix the sys.path to use an absolute path
    python_dir = str(PROJECT_ROOT / "python")
    script = script.replace(
        "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))",
        f"sys.path.insert(0, {python_dir!r})",
    )
    return script


def _build_harness() -> str:
    """Build the Go harness binary. Returns path to binary."""
    binary = str(HARNESS_DIR / "harness")
    result = subprocess.run(
        ["go", "build", "-o", binary, "."],
        cwd=str(HARNESS_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"harness build failed:\n{result.stderr}")
    return binary


def _build_ts_harness() -> str:
    """Build typescript/dist (the TS harness's only prerequisite). Returns the
    harness entry path (conformance/harness_ts/main.js, plain Node ESM)."""
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(TS_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"typescript dist build failed:\n{result.stdout}\n{result.stderr}"
        )
    return str(HARNESS_TS_ENTRY)


def _run_dump_schema(
    app_def: dict,
    target: str,
    harness_binary: str | None = None,
    ts_entry: str | None = None,
) -> dict:
    """Run --dump-schema for a given target and return the parsed schema JSON.

    Raises RuntimeError on failure.
    """
    proj_dir = _make_project_dir(target, app_def["name"])

    try:
        if target == "python":
            script = _generate_python_script(app_def)
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", prefix="strictcli_schema_py_",
                delete=False,
            ) as f:
                f.write(script)
                script_path = f.name
            try:
                result = subprocess.run(
                    [sys.executable, script_path, "--dump-schema"],
                    capture_output=True,
                    text=True,
                    cwd=proj_dir,
                    timeout=10,
                )
            finally:
                os.unlink(script_path)

        elif target == "go":
            assert harness_binary is not None
            # Write app definition to a temp file for the harness
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="strictcli_schema_def_",
                delete=False,
            ) as f:
                json.dump(app_def, f, sort_keys=True)
                def_path = f.name
            try:
                env = os.environ.copy()
                env["CONFORMANCE_APP_DEF"] = def_path
                result = subprocess.run(
                    [harness_binary, "--dump-schema"],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=proj_dir,
                    timeout=10,
                )
            finally:
                os.unlink(def_path)

        elif target == "typescript":
            assert ts_entry is not None
            # Write app definition to a temp file for the harness
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="strictcli_schema_def_",
                delete=False,
            ) as f:
                json.dump(app_def, f, sort_keys=True)
                def_path = f.name
            try:
                env = os.environ.copy()
                env["CONFORMANCE_APP_DEF"] = def_path
                result = subprocess.run(
                    ["node", ts_entry, "--dump-schema"],
                    capture_output=True,
                    text=True,
                    env=env,
                    cwd=proj_dir,
                    timeout=10,
                )
            finally:
                os.unlink(def_path)
        else:
            raise ValueError(f"unsupported target: {target}")

        if result.returncode != 0:
            raise RuntimeError(
                f"{target} --dump-schema exited {result.returncode}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        # The schema is written to .strictcli/schema.json in proj_dir
        schema_path = os.path.join(proj_dir, ".strictcli", "schema.json")
        if not os.path.exists(schema_path):
            # Try reading the path from stdout
            stdout_path = result.stdout.strip()
            if os.path.exists(stdout_path):
                schema_path = stdout_path
            else:
                raise RuntimeError(
                    f"{target}: schema file not found at {schema_path}\n"
                    f"stdout: {result.stdout}\n"
                    f"stderr: {result.stderr}"
                )

        with open(schema_path) as f:
            return json.load(f)

    finally:
        shutil.rmtree(proj_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Schema comparison
# ---------------------------------------------------------------------------


def _diff_schemas(
    schema_a: object,
    schema_b: object,
    label_a: str = "python",
    label_b: str = "go",
    path: str = "$",
) -> list[str]:
    """Recursively compare two JSON-like objects. Returns list of difference descriptions."""
    diffs: list[str] = []

    if type(schema_a) != type(schema_b):
        # Special case: both null
        if schema_a is None and schema_b is None:
            return diffs
        # Special case: int vs float (JSON numbers)
        if isinstance(schema_a, (int, float)) and isinstance(schema_b, (int, float)):
            if float(schema_a) != float(schema_b):
                diffs.append(
                    f"{path}: value mismatch: {label_a}={schema_a!r} {label_b}={schema_b!r}"
                )
            return diffs
        diffs.append(
            f"{path}: type mismatch: {label_a}={type(schema_a).__name__}({schema_a!r}) "
            f"{label_b}={type(schema_b).__name__}({schema_b!r})"
        )
        return diffs

    if isinstance(schema_a, dict):
        a_keys = set(schema_a.keys())
        b_keys = set(schema_b.keys())

        for k in sorted(a_keys - b_keys):
            diffs.append(
                f"{path}.{k}: present in {label_a} only (value={schema_a[k]!r})"
            )
        for k in sorted(b_keys - a_keys):
            diffs.append(
                f"{path}.{k}: present in {label_b} only (value={schema_b[k]!r})"
            )

        for k in sorted(a_keys & b_keys):
            diffs.extend(
                _diff_schemas(schema_a[k], schema_b[k], label_a, label_b, f"{path}.{k}")
            )

    elif isinstance(schema_a, list):
        if len(schema_a) != len(schema_b):
            diffs.append(
                f"{path}: list length mismatch: {label_a}={len(schema_a)} "
                f"{label_b}={len(schema_b)}"
            )
        for i in range(min(len(schema_a), len(schema_b))):
            diffs.extend(
                _diff_schemas(
                    schema_a[i], schema_b[i], label_a, label_b, f"{path}[{i}]"
                )
            )

    else:
        if schema_a != schema_b:
            diffs.append(
                f"{path}: value mismatch: {label_a}={schema_a!r} {label_b}={schema_b!r}"
            )

    return diffs


_SCALAR_LIST_CARRIERS = {"str", "int", "float"}


def _canonicalize_repeatable(node: object) -> None:
    """Rewrite repeatable-scalar flags to their list-carrier spelling, in place.

    Documented TS model constant (typescript/src/schema.ts doc block;
    ts-port-spec.md task 6.1 vocabulary note (a)): in TS, list carriers ARE the
    repeatable flags, so a scalar flag with repeatable=true is declared as
    list[T] and the schema emits {type: "list[T]"} with no "repeatable" key and
    no empty-list default. Python and Go emit {type: "T", repeatable: true,
    default: []}. Both spellings describe the identical flag; canonicalize every
    target to the list-carrier form so the N-way comparison sees one shape.
    """
    if isinstance(node, dict):
        if (
            node.get("repeatable") is True
            and node.get("type") in _SCALAR_LIST_CARRIERS
        ):
            node["type"] = f"list[{node['type']}]"
            del node["repeatable"]
            if node.get("default") == []:
                del node["default"]
        for v in node.values():
            _canonicalize_repeatable(v)
    elif isinstance(node, list):
        for v in node:
            _canonicalize_repeatable(v)


def _normalize_schema(schema: dict) -> dict:
    """Normalize a schema for comparison.

    - Remove project_id (depends on project file, always different between targets).
    - Canonicalize repeatable-scalar flags to the list-carrier spelling.
    """
    schema = json.loads(json.dumps(schema))  # deep copy
    schema.pop("project_id", None)
    _canonicalize_repeatable(schema)
    return schema


def _compare_schemas_nway(schemas: dict[str, dict]) -> list[str]:
    """All-identical assertion across N normalized schemas.

    Returns [] when every target's schema is identical. Otherwise groups the
    targets by identical schema content; when a unique largest group exists it
    is the majority and every other target is reported as the odd one out,
    diffed against the majority. With no unique majority (e.g. an even split),
    every other target is diffed against the first registered target.
    """
    keys = {t: json.dumps(s, sort_keys=True) for t, s in schemas.items()}
    groups: dict[str, list[str]] = {}
    for t in schemas:  # preserves registration order within groups
        groups.setdefault(keys[t], []).append(t)
    if len(groups) == 1:
        return []

    diffs: list[str] = []
    sizes = sorted((len(ts) for ts in groups.values()), reverse=True)
    majority_is_unique = len(sizes) == 1 or sizes[0] > sizes[1]

    if majority_is_unique:
        majority = max(groups.values(), key=len)
        odd = [t for t in schemas if t not in majority]
        diffs.append(
            f"odd one out: {', '.join(odd)} "
            f"(majority: {', '.join(majority)})"
        )
        base_label = f"majority({','.join(majority)})"
        base = schemas[majority[0]]
    else:
        ordered = list(schemas)
        base_label = ordered[0]
        base = schemas[base_label]
        odd = [t for t in ordered[1:] if keys[t] != keys[base_label]]
        diffs.append(
            f"no majority; diffing against {base_label}: {', '.join(odd)} differ"
        )

    for t in odd:
        diffs.extend(_diff_schemas(base, schemas[t], base_label, t))
    return diffs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    print("Building Go harness...", flush=True)
    try:
        harness = _build_harness()
    except RuntimeError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    print("Building TypeScript dist...", flush=True)
    try:
        ts_entry = _build_ts_harness()
    except RuntimeError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1

    app_defs = [
        ("rich app", RICH_APP),
        ("minimal app", MINIMAL_APP),
        ("config fields app", CONFIG_APP),
    ]

    all_diffs: list[tuple[str, list[str]]] = []

    for label, app_def in app_defs:
        print(f"Testing {label}...", flush=True)

        schemas: dict[str, dict] = {}
        failed = False
        for target in TARGET_NAMES:
            try:
                raw = _run_dump_schema(
                    app_def, target, harness_binary=harness, ts_entry=ts_entry
                )
            except RuntimeError as e:
                print(f"  {target} FAILED: {e}", file=sys.stderr)
                all_diffs.append((label, [f"{target} failed: {e}"]))
                failed = True
                break
            schemas[target] = _normalize_schema(raw)
        if failed:
            continue

        diffs = _compare_schemas_nway(schemas)
        if diffs:
            all_diffs.append((label, diffs))
            print(f"  {len(diffs)} difference(s) found")
        else:
            print(f"  PASS (schemas identical across {', '.join(TARGET_NAMES)})")

    # Cleanup harness
    harness_path = HARNESS_DIR / "harness"
    if harness_path.exists():
        os.unlink(harness_path)

    if all_diffs:
        print()
        print(f"Schema parity check FAILED ({sum(len(d) for _, d in all_diffs)} difference(s)):")
        print("=" * 60)
        for label, diffs in all_diffs:
            print(f"\n{label}:")
            for d in diffs:
                print(f"  - {d}")
        return 1

    print()
    print("Schema parity check passed.")
    print(f"  Apps tested: {len(app_defs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
