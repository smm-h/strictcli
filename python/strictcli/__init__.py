"""A strict, zero-dependency CLI framework for Python with mandatory help text, type-safe flags, groups, and schema export."""

from __future__ import annotations

__version__ = "0.24.2"

__all__ = [
    "App", "Flag", "Arg", "FlagSet", "MutexGroup", "CoRequired", "Requires",
    "Implies", "Passthrough", "DeprecatedCommand", "Result", "InvokeError",
    "flag", "arg",
    "CheckResult", "CheckContext", "CheckRunResult",
    "format_check_results", "format_check_results_json",
    "ConfigField",
    "Context",
    "Tool",
]

import contextlib
import keyword
import fnmatch
import importlib.metadata
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, get_args, get_origin, runtime_checkable


# Sentinel for distinguishing "not provided" from actual values
class _MissingSentinel:
    def __repr__(self) -> str:
        return "_MISSING"


_MISSING = _MissingSentinel()


# ---------------------------------------------------------------------------
# Source provenance (Phase 0c)
# ---------------------------------------------------------------------------

class _Source:
    """Where a flag value came from."""
    CLI = "cli"          # explicitly passed on the command line
    ENV = "env"          # from an environment variable
    CONFIG = "config"    # from a config file
    DEFAULT = "default"  # from the flag's default value
    IMPLIED = "implied"  # injected by an Implies dependency


class _SourcedEntry:
    """A value paired with its provenance source."""
    __slots__ = ("value", "source")

    def __init__(self, value: object, source: str) -> None:
        self.value = value
        self.source = source


class _SourcedStore:
    """Map of flag-name to _SourcedEntry with source-filtered presence queries.

    Replaces the plain ``cli_set: dict[str, object]`` in the validation
    pipeline, adding provenance tracking for each value.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _SourcedEntry] = {}

    def set(self, name: str, value: object, source: str) -> None:
        self._entries[name] = _SourcedEntry(value, source)

    def get(self, name: str) -> tuple[object, bool]:
        """Return (value, True) or (None, False)."""
        e = self._entries.get(name)
        if e is None:
            return None, False
        return e.value, True

    def has(self, name: str) -> bool:
        return name in self._entries

    def get_value(self, name: str) -> object:
        """Return the value or raise KeyError."""
        return self._entries[name].value

    def set_value(self, name: str, value: object) -> None:
        """Update the value of an existing entry, keeping its source."""
        self._entries[name].value = value

    def is_present_for_mutex(self, name: str) -> bool:
        """Present for mutex: only cli, env, config. NOT default or implied."""
        e = self._entries.get(name)
        if e is None:
            return False
        return e.source in (_Source.CLI, _Source.ENV, _Source.CONFIG)

    def is_present_for_deps(self, name: str) -> bool:
        """Present for deps (CoRequired, Requires): everything except default."""
        e = self._entries.get(name)
        if e is None:
            return False
        return e.source != _Source.DEFAULT

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __setitem__(self, name: str, value: object) -> None:
        # Convenience for migration: stores with SourceCLI by default.
        # Only used in parsing contexts where source is CLI.
        self._entries[name] = _SourcedEntry(value, _Source.CLI)

    def __getitem__(self, name: str) -> object:
        return self._entries[name].value

    def source_map(self) -> dict[str, str]:
        """Return a dict mapping flag names to source labels."""
        return {k: e.source for k, e in self._entries.items()}

    @classmethod
    def from_dict(cls, d: dict[str, object], source: str) -> "_SourcedStore":
        """Build a store from a plain dict, marking all entries with source."""
        store = cls()
        for k, v in d.items():
            store.set(k, v, source)
        return store


class Context:
    """Structured output context for command handlers.

    Provides info/warn/debug/error methods that route to the correct stream,
    and an emit method for structured data output.
    """

    def __init__(self, stdout=None, stderr=None, sources=None):
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._emit_data = _MISSING
        self._emit_called = False
        self._sources = sources or {}  # flag-name -> source label (cli/env/config/default/implied)

    def info(self, msg: str) -> None:
        """Write an informational message to stdout."""
        print(msg, file=self._stdout)

    def warn(self, msg: str) -> None:
        """Write a warning message to stderr."""
        print(msg, file=self._stderr)

    def debug(self, msg: str) -> None:
        """Write a debug message to stdout."""
        print(msg, file=self._stdout)

    def error(self, msg: str) -> None:
        """Write an error message to stderr."""
        print(msg, file=self._stderr)

    def source(self, name: str) -> str:
        """Return the provenance source label for a flag.

        Returns one of: "cli", "env", "config", "default", "implied".
        Raises KeyError if the flag name is not found.
        """
        key = name.replace("-", "_")
        if key in self._sources:
            return self._sources[key]
        # Try original name (with dashes)
        if name in self._sources:
            return self._sources[name]
        raise KeyError(f"no source info for flag {name!r}")

    def emit(self, data) -> None:
        """Write JSON-serialized data to stdout and store for programmatic retrieval.

        Raises RuntimeError if called more than once.
        """
        if self._emit_called:
            raise RuntimeError("emit called more than once; bundle data into a single value")
        self._emit_called = True
        self._emit_data = data
        print(json.dumps(data, default=str), file=self._stdout)


def _config_path(app_name: str, *, override: str | None = None, config_format: str = "json") -> str:
    """Compute the config file path for an app.

    If override is provided, expand ~ and return it directly.
    Otherwise compute from XDG_CONFIG_HOME + app_name.
    """
    if override is not None:
        return os.path.expanduser(override)
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    ext = "toml" if config_format == "toml" else "json"
    return os.path.join(config_home, app_name, f"config.{ext}")


def _load_config(
    app_name: str,
    *,
    config_path_override: str | None = None,
    config_format: str = "json",
) -> dict:
    """Load the config file for an app.

    Returns an empty dict if the file doesn't exist or contains invalid content.
    Invalid content prints a warning to stderr.
    """
    path = _config_path(app_name, override=config_path_override, config_format=config_format)
    if not os.path.isfile(path):
        return {}
    if config_format == "toml":
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            print(f"warning: invalid TOML in config file '{path}', ignoring", file=sys.stderr)
            return {}
    try:
        with open(path) as f:
            return json.loads(f.read())
    except (json.JSONDecodeError, ValueError):
        print(f"warning: invalid JSON in config file '{path}', ignoring", file=sys.stderr)
        return {}


def _toml_format_scalar(value: object) -> str:
    """Format a scalar value as a TOML literal."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_toml_flat(data: dict, path: str) -> None:
    """Write a flat dict as a TOML file.

    Supports str, int, float, bool, list, and dict values. This avoids
    requiring a TOML writer dependency for the simple key=value configs
    that 'config set' produces.
    """
    lines: list[str] = []
    # Write non-table values first, then tables
    tables: list[tuple[str, dict]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            tables.append((key, value))
        elif isinstance(value, list):
            elements = ", ".join(_toml_format_scalar(elem) for elem in value)
            lines.append(f"{key} = [{elements}]")
        else:
            lines.append(f"{key} = {_toml_format_scalar(value)}")
    # Write TOML tables for dict values
    for key, table in tables:
        lines.append("")
        lines.append(f"[{key}]")
        for k, v in table.items():
            lines.append(f"{k} = {_toml_format_scalar(v)}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n" if lines else "")


def _coerce_config_scalar(value: object, flag_type: type) -> object:
    """Coerce a single JSON config value to the given type.

    Returns the coerced value, or raises ValueError if coercion fails.
    """
    if flag_type is bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"expected boolean, got {_config_typename(value)}")
    if flag_type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ValueError(f"expected integer, got {_config_typename(value)}")
    if flag_type is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ValueError(f"expected float, got {_config_typename(value)}")
    if flag_type is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"expected string, got {_config_typename(value)}")
    raise ValueError(f"unsupported flag type {flag_type}")


def _coerce_config_value(value: object, flag: "Flag") -> object:
    """Coerce a JSON config value to the flag's type.

    Returns the coerced value, or raises ValueError if coercion fails.
    Handles scalar, array (repeatable), and object (dict) values.
    """
    # Dict flags expect a JSON object
    if flag.compound == "dict":
        if not isinstance(value, dict):
            raise ValueError(
                f"expected object for dict flag, got {_config_typename(value)}"
            )
        result = {}
        for k, v in value.items():
            try:
                result[k] = _coerce_config_scalar(v, flag.value_type)
            except ValueError:
                raise ValueError(
                    f"key '{k}': expected {flag.value_type.__name__}, "
                    f"got {_config_typename(v)}"
                )
        return result
    if isinstance(value, list):
        if not flag.repeatable:
            raise ValueError("expected scalar, got array")
        result_list = []
        for i, elem in enumerate(value):
            try:
                result_list.append(_coerce_config_scalar(elem, flag.type))
            except ValueError:
                raise ValueError(
                    f"element {i}: expected {flag.type.__name__}, "
                    f"got {_config_typename(elem)}"
                )
        return result_list
    if flag.repeatable:
        raise ValueError(
            f"expected array for repeatable flag, got {_config_typename(value)}"
        )
    return _coerce_config_scalar(value, flag.type)


def _format_config_value(value: object) -> str:
    """Format a config value for display, matching Go's formatConfigValue."""
    if value is None:
        return "<nil>"
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _nested_get(data: dict, dotted_key: str) -> tuple[bool, object]:
    """Look up a dot-separated key in a nested dict.

    Returns (found, value). If any intermediate segment is missing or
    not a dict, returns (False, None).
    """
    parts = dotted_key.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False, None
    return True, current[parts[-1]]


def _nested_set(data: dict, dotted_key: str, value: object) -> None:
    """Set a dot-separated key in a nested dict, creating intermediate dicts."""
    parts = dotted_key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _nested_delete(data: dict, dotted_key: str) -> bool:
    """Delete a dot-separated key from a nested dict.

    Returns True if the key was found and deleted, False otherwise.
    Cleans up empty intermediate dicts.
    """
    parts = dotted_key.split(".")
    # Walk to the parent, tracking the path for cleanup
    parents: list[tuple[dict, str]] = []
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        parents.append((current, part))
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    del current[parts[-1]]
    # Clean up empty intermediate dicts
    for parent, key in reversed(parents):
        if not parent[key]:
            del parent[key]
    return True


def _collect_nested_keys(data: dict, prefix: str = "") -> list[str]:
    """Collect all leaf keys from a nested dict as dot-separated paths.

    Non-dict values are leaves. Dict values are recursed into.
    """
    keys: list[str] = []
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_collect_nested_keys(v, full_key))
        else:
            keys.append(full_key)
    return keys


def _check_config_field_type(cf: "ConfigField", value: object) -> str | None:
    """Validate that a config file value matches the config field's declared type.

    Returns an error message, or None if the type matches.
    """
    type_name = cf.type.__name__
    if cf.type is bool:
        if not isinstance(value, bool):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    elif cf.type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    elif cf.type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    elif cf.type is str:
        if not isinstance(value, str):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    return None


def _config_set_field(
    key: str,
    value: str | None,
    cf: "ConfigField",
    existing: dict,
    path: str,
    config_format: str,
    kw: dict,
) -> int:
    """Handle 'config set' for a config field (not a flag).

    Returns an exit code (0 = success, 1 = error).
    """
    use_clear = kw.get("clear", False)
    use_default = kw.get("default", False)
    has_value = value is not None

    if use_clear:
        print("config set: --clear is only for repeatable flags", file=sys.stderr)
        return 1
    if use_clear and use_default:
        print("config set: --clear and --default are mutually exclusive",
              file=sys.stderr)
        return 1
    if has_value and use_default:
        print("config set: cannot provide a value with --default", file=sys.stderr)
        return 1
    if not has_value and not use_default:
        print("config set: provide a value or --default", file=sys.stderr)
        return 1

    if use_default:
        found = _nested_delete(existing, key)
        if not found:
            print(f"config set: key '{key}' not in config", file=sys.stderr)
            return 1
        _write_config_data(existing, path, config_format)
        return 0

    # Coerce string value to the config field's type
    try:
        if cf.type is bool:
            typed_value = _strict_bool(value)
        elif cf.type is int:
            typed_value = _strict_int(value)
        elif cf.type is float:
            try:
                typed_value = _strict_float(value)
            except ValueError as fe:
                msg = str(fe)
                if msg in ("NaN is not allowed", "Inf is not allowed"):
                    raise
                raise ValueError(f"expected float, got '{value}'") from fe
        else:
            typed_value = value
    except ValueError as e:
        print(f"config set: key '{key}': {e}", file=sys.stderr)
        return 1

    _nested_set(existing, key, typed_value)
    _write_config_data(existing, path, config_format)
    return 0


def _write_config_data(data: dict, path: str, config_format: str) -> None:
    """Write config data to disk in the appropriate format."""
    if config_format == "toml":
        _write_toml_nested(data, path)
    else:
        with open(path, "w") as fh:
            fh.write(json.dumps(data, indent=2) + "\n")


def _write_toml_nested(data: dict, path: str) -> None:
    """Write a nested dict as a TOML file with sections.

    Top-level scalars are written first, then nested dicts become [section] headers.
    Only supports one level of nesting (matching config field dot-name semantics).
    """
    lines: list[str] = []
    # Write top-level scalars first
    for key, value in data.items():
        if isinstance(value, dict):
            continue
        if isinstance(value, list):
            elements = ", ".join(_toml_format_scalar(elem) for elem in value)
            lines.append(f"{key} = [{elements}]")
        else:
            lines.append(f"{key} = {_toml_format_scalar(value)}")
    # Write sections for nested dicts
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        if lines:
            lines.append("")
        lines.append(f"[{key}]")
        for sub_key, sub_value in value.items():
            if isinstance(sub_value, dict):
                # Two-level nesting -- use dotted section header
                lines.append("")
                lines.append(f"[{key}.{sub_key}]")
                for k, v in sub_value.items():
                    lines.append(f"{k} = {_toml_format_scalar(v)}")
            elif isinstance(sub_value, list):
                elements = ", ".join(_toml_format_scalar(elem) for elem in sub_value)
                lines.append(f"{sub_key} = [{elements}]")
            else:
                lines.append(f"{sub_key} = {_toml_format_scalar(sub_value)}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n" if lines else "")


def _generate_config_template_toml(
    flags: list["Flag"],
    config_fields: dict[str, "ConfigField"],
) -> str:
    """Generate a TOML config template with comments."""
    lines: list[str] = []

    # Flag-backed keys (flat)
    for f in flags:
        param = _flag_param_name(f.name)
        lines.append(f"# {f.help}")
        if f.default is not None:
            lines.append(f"{param} = {_toml_format_scalar(f.default)}")
        else:
            lines.append(f"# {param} =")
        lines.append("")

    # Config field keys (possibly nested via dot names)
    # Group by first segment for TOML sections
    top_level: list[tuple[str, "ConfigField"]] = []
    sections: dict[str, list[tuple[str, "ConfigField"]]] = {}
    for name, cf in config_fields.items():
        parts = name.split(".")
        if len(parts) == 1:
            top_level.append((name, cf))
        else:
            section = parts[0]
            if section not in sections:
                sections[section] = []
            sections[section].append((name, cf))

    for name, cf in top_level:
        req = " (required)" if cf.required else ""
        lines.append(f"# {cf.help}{req}")
        if not cf.required:
            lines.append(f"{name} = {_toml_format_scalar(cf.default)}")
        else:
            lines.append(f"# {name} =")
        lines.append("")

    for section, fields in sections.items():
        lines.append(f"[{section}]")
        for name, cf in fields:
            # The key within the section is everything after the first dot
            sub_parts = name.split(".", 1)
            sub_key = sub_parts[1] if len(sub_parts) > 1 else sub_parts[0]
            # Handle deeper nesting
            deeper_parts = sub_key.split(".")
            if len(deeper_parts) > 1:
                # Need a sub-section
                sub_section = f"{section}.{deeper_parts[0]}"
                leaf_key = ".".join(deeper_parts[1:])
                lines.append("")
                lines.append(f"[{sub_section}]")
                req = " (required)" if cf.required else ""
                lines.append(f"# {cf.help}{req}")
                if not cf.required:
                    lines.append(f"{leaf_key} = {_toml_format_scalar(cf.default)}")
                else:
                    lines.append(f"# {leaf_key} =")
            else:
                req = " (required)" if cf.required else ""
                lines.append(f"# {cf.help}{req}")
                if not cf.required:
                    lines.append(f"{sub_key} = {_toml_format_scalar(cf.default)}")
                else:
                    lines.append(f"# {sub_key} =")
        lines.append("")

    return "\n".join(lines) + "\n" if lines else ""


def _generate_config_template_json(
    flags: list["Flag"],
    config_fields: dict[str, "ConfigField"],
) -> str:
    """Generate a JSON config template."""
    data: dict = {}
    # Flag-backed keys
    for f in flags:
        param = _flag_param_name(f.name)
        if f.default is not None:
            data[param] = f.default
        else:
            data[param] = None

    # Config field keys (nested via dot names)
    for name, cf in config_fields.items():
        if not cf.required:
            _nested_set(data, name, cf.default)
        else:
            _nested_set(data, name, None)

    return json.dumps(data, indent=2) + "\n"


def _split_escaped(value: str, sep: str) -> list[str]:
    """Split value on sep, treating backslash as escape character.

    Escaped sep becomes literal sep. Escaped backslash becomes literal backslash.
    Trailing backslash with nothing to escape becomes literal backslash.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\":
            if i + 1 < len(value):
                next_ch = value[i + 1]
                if next_ch == sep:
                    current.append(sep)
                    i += 2
                elif next_ch == "\\":
                    current.append("\\\\")
                    i += 2
                else:
                    current.append("\\")
                    current.append(next_ch)
                    i += 2
            else:
                # Trailing backslash
                current.append("\\\\")
                i += 1
        elif value[i] == sep:
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(value[i])
            i += 1
    parts.append("".join(current))
    return parts


def _find_duplicate(values: list) -> object | None:
    """Return the first duplicate value in the list, or None if all unique."""
    seen: set = set()
    for v in values:
        if v in seen:
            return v
        seen.add(v)
    return None


def _format_value_for_error(value: object) -> str:
    """Format a value for inclusion in error messages (without quotes).

    Floats always include a decimal point. Bools are lowercase.
    Strings are returned as-is.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        s = str(value)
        if "." not in s:
            s += ".0"
        return s
    return str(value)


def _config_typename(value: object) -> str:
    """Return a type name for config values, matching Go's typeName."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_CHECK_REQUIRED_FIELDS = {"tags", "severity", "fast", "pure", "needs_network", "depends_on"}
_CHECK_OPTIONAL_FIELDS = {"scope"}
_CHECK_VALID_SEVERITIES = {"error", "warn"}


def _parse_checks_toml(data: bytes) -> tuple[str, dict[str, _CheckDef]]:
    """Parse and validate checks TOML data, returning (app_name, check_defs).

    Raises ValueError on any schema violation or invalid TOML.
    """
    try:
        parsed = tomllib.loads(data.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"checks.toml: {exc}") from exc

    # Only "app" and [checks] are allowed at the top level
    for key in parsed:
        if key not in ("app", "checks"):
            raise ValueError(f'checks.toml: unknown top-level key "{key}"')

    # Validate required "app" field
    if "app" not in parsed:
        raise ValueError('checks.toml: missing required top-level key "app"')
    if not isinstance(parsed["app"], str) or not parsed["app"]:
        raise ValueError('checks.toml: "app" must be a non-empty string')
    app_name = parsed["app"]

    if "checks" not in parsed:
        return (app_name, {})

    checks_section = parsed["checks"]
    if not isinstance(checks_section, dict):
        raise ValueError("checks.toml: [checks] must be a table")

    result: dict[str, _CheckDef] = {}

    for name, fields in checks_section.items():
        # Validate check name
        if not _IDENTIFIER_RE.match(name):
            raise ValueError(
                f'checks.toml: invalid check name "{name}" '
                f"(must match [a-z][a-z0-9-]*)"
            )
        if not isinstance(fields, dict):
            raise ValueError(f'checks.toml: check "{name}" must be a table')

        # No unknown fields
        unknown = set(fields.keys()) - _CHECK_REQUIRED_FIELDS - _CHECK_OPTIONAL_FIELDS
        if unknown:
            raise ValueError(
                f'checks.toml: check "{name}": unknown field "{sorted(unknown)[0]}"'
            )

        # Required fields
        for req in sorted(_CHECK_REQUIRED_FIELDS):
            if req not in fields:
                raise ValueError(
                    f'checks.toml: check "{name}": missing required field "{req}"'
                )

        # Validate tags
        tags = fields["tags"]
        if not isinstance(tags, list):
            raise ValueError(
                f'checks.toml: check "{name}": "tags" must be a list of strings'
            )
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError(
                    f'checks.toml: check "{name}": "tags" entries must be non-empty strings'
                )

        # Validate severity
        severity = fields["severity"]
        if not isinstance(severity, str) or severity not in _CHECK_VALID_SEVERITIES:
            raise ValueError(
                f'checks.toml: check "{name}": "severity" must be "error" or "warn", '
                f"got {severity!r}"
            )

        # Validate booleans
        for bool_field in ("fast", "pure", "needs_network"):
            val = fields[bool_field]
            if not isinstance(val, bool):
                raise ValueError(
                    f'checks.toml: check "{name}": "{bool_field}" must be a boolean, '
                    f"got {type(val).__name__}"
                )

        # Validate depends_on
        depends_on = fields["depends_on"]
        if not isinstance(depends_on, list):
            raise ValueError(
                f'checks.toml: check "{name}": "depends_on" must be a list of strings'
            )
        for dep in depends_on:
            if not isinstance(dep, str):
                raise ValueError(
                    f'checks.toml: check "{name}": "depends_on" entries must be strings'
                )

        # Validate optional scope field
        scope = fields.get("scope", "")
        if not isinstance(scope, str):
            raise ValueError(
                f'checks.toml: check "{name}": "scope" must be a string, '
                f"got {type(scope).__name__}"
            )

        result[name] = _CheckDef(
            name=name,
            tags=tags,
            severity=severity,
            fast=fields["fast"],
            pure=fields["pure"],
            needs_network=fields["needs_network"],
            depends_on=depends_on,
            scope=scope,
        )

    # Cross-validate depends_on references
    for name, check_def in result.items():
        for dep in check_def.depends_on:
            if dep not in result:
                raise ValueError(
                    f'checks.toml: check "{name}": depends_on references '
                    f'unknown check "{dep}"'
                )

    return (app_name, result)


def _load_checks_toml(path: str | Path) -> tuple[str, dict[str, _CheckDef]]:
    """Read and parse a checks.toml file, returning (app_name, check_defs).

    Raises ValueError on any file error, schema violation, or invalid TOML.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"checks.toml: {exc}") from exc
    return _parse_checks_toml(raw)


class _HelpRequested(Exception):
    """Raised when --help or -h is encountered."""

    def __init__(self, target: object) -> None:
        self.target = target
        super().__init__()


class _VersionRequested(Exception):
    """Raised when --version or -v is encountered."""


class _DumpSchemaRequested(Exception):
    """Raised when --dump-schema is encountered."""


class _McpRequested(Exception):
    """Raised when --mcp is encountered."""


class _ParseError(Exception):
    """Raised for user-facing parse errors."""

    def __init__(self, message: str, command_prefix: str | None = None):
        super().__init__(message)
        self.command_prefix = command_prefix


class InvokeError(Exception):
    """Raised by app.call() for invocation errors (unknown command, missing flags, etc.)."""


def _strict_bool(s: str) -> bool:
    """Parse a boolean string strictly.

    Accepts: 1, true, yes (case-insensitive) -> True
    Accepts: 0, false, no (case-insensitive) -> False
    Everything else raises ValueError.
    """
    lower = s.lower()
    if lower in ("1", "true", "yes"):
        return True
    if lower in ("0", "false", "no"):
        return False
    raise ValueError(f"expected boolean, got '{s}'")


def _strict_int(s: str) -> int:
    """Parse an integer string strictly -- no leading/trailing whitespace allowed.

    Python's int() silently strips whitespace; Go's strconv.Atoi does not.
    This matches Go's stricter behavior. Additionally, the result is
    range-checked to fit in a signed 64-bit integer, matching Go's int/int64.

    All errors raise ValueError with the same message format as Go's
    parseIntStrict: "expected integer, got '<value>'".
    """
    if s != s.strip():
        raise ValueError(f"expected integer, got '{s}'")
    try:
        n = int(s)
    except ValueError:
        raise ValueError(f"expected integer, got '{s}'") from None
    if n < -(2**63) or n > 2**63 - 1:
        raise ValueError(f"expected integer, got '{s}'")
    return n


def _strict_float(s: str) -> float:
    """Parse a float string strictly -- no leading/trailing whitespace allowed.

    Rejects nan, inf, and -inf (case-insensitive) since these are valid Python
    floats but not useful CLI values.
    """
    if s != s.strip():
        raise ValueError(f"invalid literal for float(): {s!r}")
    low = s.lower()
    if low == "nan":
        raise ValueError("NaN is not allowed")
    if low in ("inf", "-inf", "+inf", "infinity", "-infinity", "+infinity"):
        raise ValueError("Inf is not allowed")
    return float(s)


def _float_parse_error(
    flag_name: str, raw: str, exc: ValueError, *, env: str | None = None,
) -> "_ParseError":
    """Build a _ParseError for a failed float parse.

    If the ValueError is a NaN/Inf rejection, use its message directly.
    Otherwise, produce the generic "expected float, got ..." message.
    """
    msg = str(exc)
    suffix = f" (from env var '{env}')" if env else ""
    if msg in ("NaN is not allowed", "Inf is not allowed"):
        return _ParseError(f"--{flag_name}: {msg}{suffix}")
    return _ParseError(f"--{flag_name}: expected float, got {raw!r}{suffix}")


def _coerce_arg_value(a: "Arg", raw: str) -> object:
    """Coerce a raw positional arg string to the declared type.

    Uses the same strict parsing functions as flags: _strict_int, _strict_float,
    _strict_bool. Error messages follow the same pattern as flag type errors,
    with "argument '<name>'" instead of "--<name>".
    """
    if a.type is str:
        return raw
    if a.type is int:
        try:
            return _strict_int(raw)
        except ValueError as e:
            raise _ParseError(f"argument '{a.name}': {e}")
    if a.type is float:
        try:
            return _strict_float(raw)
        except ValueError as e:
            msg = str(e)
            if msg in ("NaN is not allowed", "Inf is not allowed"):
                raise _ParseError(f"argument '{a.name}': {msg}")
            raise _ParseError(f"argument '{a.name}': expected float, got {raw!r}")
    if a.type is bool:
        try:
            return _strict_bool(raw)
        except ValueError as e:
            raise _ParseError(f"argument '{a.name}': {e}")
    # Unreachable (validated at registration), but defensive
    return raw  # pragma: no cover


_AT_PREFIX_MAX_SIZE = 1024 * 1024  # 1 MB


def _resolve_at_prefix(
    flag_name: str, raw: str, stdin_consumed_by: str | None,
) -> tuple[str, str | None]:
    """Resolve @-prefix for string flag values.

    Returns (resolved_value, updated_stdin_consumed_by).
    """
    if not raw.startswith("@"):
        return raw, stdin_consumed_by
    if raw.startswith("@@"):
        return raw[1:], stdin_consumed_by
    if raw == "@-":
        if stdin_consumed_by is not None:
            raise _ParseError(
                f"--{flag_name}: stdin (@-) can only be used once per invocation"
            )
        try:
            data = sys.stdin.read(_AT_PREFIX_MAX_SIZE + 1)
            if len(data) > _AT_PREFIX_MAX_SIZE:
                raise _ParseError(f"--{flag_name}: file exceeds 1 MB limit")
            return data.rstrip(), flag_name
        except _ParseError:
            raise
        except Exception:
            raise _ParseError(f"--{flag_name}: cannot read stdin")
    # @path -- read file
    path = raw[1:]
    if not os.path.exists(path):
        raise _ParseError(f"--{flag_name}: file not found: {path}")
    try:
        with open(path, "r") as f:
            data = f.read(_AT_PREFIX_MAX_SIZE + 1)
        if len(data) > _AT_PREFIX_MAX_SIZE:
            raise _ParseError(f"--{flag_name}: file exceeds 1 MB limit")
        return data.rstrip(), stdin_consumed_by
    except _ParseError:
        raise
    except Exception:
        raise _ParseError(f"--{flag_name}: cannot read file: {path}")


def _require_non_empty_str(value: str, field_name: str, class_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{class_name}.{field_name} must be a non-empty string")


def _parse_dict_value(
    flag_name: str, raw: str, value_type: type,
) -> tuple[str, object] | dict[str, object]:
    """Parse a dict flag value from CLI.

    Two formats:
    - key=value: splits on first '=', coerces value to value_type
    - JSON string starting with '{': parsed as JSON dict

    For key=value format, returns a (key, coerced_value) tuple.
    For JSON format, returns a dict of {key: coerced_value}.
    """
    # JSON format: detected by leading '{'
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise _ParseError(f"--{flag_name}: invalid JSON: {e}")
        if not isinstance(parsed, dict):
            raise _ParseError(
                f"--{flag_name}: JSON value must be an object, "
                f"got {type(parsed).__name__}"
            )
        result = {}
        for k, v in parsed.items():
            if not isinstance(k, str):
                raise _ParseError(
                    f"--{flag_name}: JSON key must be a string, got {k!r}"
                )
            result[k] = _coerce_dict_json_value(flag_name, k, v, value_type)
        return result

    # key=value format: split on first '='
    if "=" not in raw:
        raise _ParseError(
            f"--{flag_name}: expected key=value or JSON, got '{raw}'"
        )
    eq_pos = raw.index("=")
    key = raw[:eq_pos]
    val_str = raw[eq_pos + 1:]

    if not key:
        raise _ParseError(f"--{flag_name}: empty key in '{raw}'")

    if value_type is int:
        try:
            return (key, _strict_int(val_str))
        except ValueError as e:
            raise _ParseError(f"--{flag_name}: value for key '{key}': {e}")
    elif value_type is float:
        try:
            return (key, _strict_float(val_str))
        except ValueError as e:
            raise _float_parse_error(flag_name, val_str, e)
    else:  # str
        return (key, val_str)


def _coerce_dict_json_value(
    flag_name: str, key: str, value: object, value_type: type,
) -> object:
    """Coerce a JSON-parsed value to the dict's value type."""
    if value_type is str:
        if not isinstance(value, str):
            raise _ParseError(
                f"--{flag_name}: JSON value for key '{key}' must be a string, "
                f"got {_config_typename(value)}"
            )
        return value
    if value_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise _ParseError(
                f"--{flag_name}: JSON value for key '{key}' must be an integer, "
                f"got {_config_typename(value)}"
            )
        return value
    if value_type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise _ParseError(
                f"--{flag_name}: JSON value for key '{key}' must be a number, "
                f"got {_config_typename(value)}"
            )
        return float(value)
    raise _ParseError(f"--{flag_name}: unsupported value type {value_type}")


def _store_dict_flag(f: "Flag", raw: str, cli_set: dict) -> None:
    """Parse and store a dict flag value from a raw CLI string.

    Handles both key=value and JSON formats. For JSON, may add multiple
    entries at once. For key=value, adds one entry.
    """
    parsed = _parse_dict_value(f.name, raw, f.value_type)
    if isinstance(parsed, dict):
        # JSON format returned a full dict
        if f.name not in cli_set:
            cli_set[f.name] = {}
        for k, v in parsed.items():
            if k in cli_set[f.name]:
                raise _ParseError(f"--{f.name}: duplicate key '{k}'")
            cli_set[f.name][k] = v
    else:
        # key=value format returned a tuple
        k, v = parsed
        if f.name not in cli_set:
            cli_set[f.name] = {}
        if k in cli_set[f.name]:
            raise _ParseError(f"--{f.name}: duplicate key '{k}'")
        cli_set[f.name][k] = v


_SCALAR_TYPES = (str, bool, int, float)
_NON_BOOL_SCALAR_TYPES = (str, int, float)

# Names reserved by the framework for global flags.
# These cannot be used for user-defined global flags.
_RESERVED_GLOBAL_FLAG_NAMES = frozenset({
    "help", "h", "version", "v", "dump-schema", "mcp", "config",
})


def _parse_compound_type(
    raw_type: type, context: str,
) -> tuple[str, type | None, type | None]:
    """Parse a type annotation into (kind, item_type, value_type).

    Returns:
        ("scalar", None, None) for str/bool/int/float
        ("list", item_type, None) for list[T]
        ("dict", None, value_type) for dict[str, T]

    Raises ValueError for invalid compound types.
    """
    # Plain scalar types
    if raw_type in _SCALAR_TYPES:
        return ("scalar", None, None)

    # Bare list/dict without type args
    if raw_type is list:
        raise ValueError(
            f'{context}: list type requires an item type '
            f'(e.g., list[int]), got bare list'
        )
    if raw_type is dict:
        raise ValueError(
            f'{context}: dict type requires type arguments '
            f'(e.g., dict[str, int]), got bare dict'
        )

    origin = get_origin(raw_type)

    # list[T]
    if origin is list:
        args = get_args(raw_type)
        if not args:
            raise ValueError(
                f'{context}: list type requires an item type '
                f'(e.g., list[int]), got bare list'
            )
        if len(args) != 1:
            raise ValueError(
                f'{context}: list type takes exactly one type argument, '
                f'got {len(args)}'
            )
        item_type = args[0]
        if item_type not in _NON_BOOL_SCALAR_TYPES:
            raise ValueError(
                f'{context}: list item type must be str, int, or float, '
                f'got {item_type!r}'
            )
        return ("list", item_type, None)

    # dict[str, T]
    if origin is dict:
        args = get_args(raw_type)
        if not args:
            raise ValueError(
                f'{context}: dict type requires type arguments '
                f'(e.g., dict[str, int]), got bare dict'
            )
        if len(args) != 2:
            raise ValueError(
                f'{context}: dict type takes exactly two type arguments, '
                f'got {len(args)}'
            )
        key_type, val_type = args
        if key_type is not str:
            raise ValueError(
                f'{context}: dict key type must be str, got {key_type!r}'
            )
        if val_type not in _NON_BOOL_SCALAR_TYPES:
            raise ValueError(
                f'{context}: dict value type must be str, int, or float, '
                f'got {val_type!r}'
            )
        return ("dict", None, val_type)

    raise ValueError(
        f'{context}: type must be str, bool, int, float, '
        f'list[T], or dict[str, T], got {raw_type!r}'
    )


def _validate_element_type(
    flag_name: str, expected_type: type, value: object, context: str,
) -> None:
    """Validate that a value matches the expected scalar type."""
    if expected_type is str:
        if not isinstance(value, str):
            raise ValueError(
                f'Flag "{flag_name}": {context} is not of type str'
            )
    elif expected_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(
                f'Flag "{flag_name}": {context} is not of type int'
            )
    elif expected_type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f'Flag "{flag_name}": {context} is not of type float'
            )


@dataclass
class Flag:
    """Represents a --flag declaration."""

    name: str
    type: type
    help: str
    short: str | None = None
    default: object = None
    env: str | None = None
    env_separator: str | None = None
    prefixed: bool = True
    negatable: bool = True
    choices: list | None = None
    validate: Callable | None = None
    repeatable: bool = False
    unique: object = _MISSING
    # Compound type fields (set by __post_init__, not by caller)
    compound: str = "scalar"  # "scalar", "list", or "dict"
    item_type: type | None = None  # for list[T]: the T
    value_type: type | None = None  # for dict[str, T]: the T

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Flag")
        if self.name == "force":
            raise ValueError(
                "flag 'force' is a reserved name; use a qualified name "
                "like 'force-overwrite' or 'force-delete'"
            )
        if self.name.startswith("no-"):
            raise ValueError(
                f"flag '{self.name}': names starting with 'no-' are "
                f"reserved for the negation system; use a positive "
                f"name instead"
            )

        # Parse compound types (list[T], dict[str, T])
        kind, item_t, val_t = _parse_compound_type(
            self.type, f'Flag "{self.name}"',
        )
        self.compound = kind
        self.item_type = item_t
        self.value_type = val_t

        if kind == "list":
            # list[T] normalizes to: type=item_type, repeatable=True
            self.type = self.item_type
            if not self.repeatable:
                self.repeatable = True
            # unique defaults to False for list types if not specified
            if isinstance(self.unique, _MissingSentinel):
                self.unique = False
        elif kind == "dict":
            # dict[str, T] normalizes to: type stays as the original
            # dict[str, T] annotation. The value_type tracks the T.
            # Dict flags are implicitly repeatable (each --flag key=val
            # adds to the dict), but don't use the list-based repeatable
            # machinery. We store self.type as the value_type for coercion
            # dispatch, but keep compound="dict" to distinguish behavior.
            self.type = self.value_type
            # Dict flags cannot be combined with repeatable=True by the user
            if self.repeatable:
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot be combined '
                    f'with repeatable=True'
                )
            # Dict flags cannot have unique
            if not isinstance(self.unique, _MissingSentinel):
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot be combined with unique'
                )
            self.unique = False
            # Dict flags cannot have choices
            if self.choices is not None:
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot be combined with choices'
                )

        # Validate scalar type
        if kind == "scalar" and self.type not in (str, bool, int, float):
            raise ValueError(
                f"Flag.type must be str, bool, int, float, "
                f"list[T], or dict[str, T], got {self.type!r}"
            )
        # Validate repeatable
        if self.repeatable and self.type is bool:
            raise ValueError(f'Flag "{self.name}": repeatable is incompatible with type=bool')
        # Validate unique
        if self.compound != "dict":
            if self.repeatable and isinstance(self.unique, _MissingSentinel):
                raise ValueError(
                    f'Flag "{self.name}": repeatable requires explicit unique '
                    f"(unique=True or unique=False)"
                )
            if not isinstance(self.unique, _MissingSentinel) and self.unique is not True and self.unique is not False:
                raise ValueError(f'Flag "{self.name}": unique must be True or False')
            if (self.unique is True or self.unique is False) and not self.repeatable:
                raise ValueError(f'Flag "{self.name}": unique requires repeatable=True')
            if isinstance(self.unique, _MissingSentinel) and not self.repeatable:
                self.unique = False
        # Validate env_separator
        if self.compound == "dict":
            # Dict flags use JSON for env vars, not env_separator
            if self.env_separator is not None:
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot use env_separator '
                    f'(env vars are parsed as JSON)'
                )
        else:
            if self.env_separator is not None and not self.repeatable:
                raise ValueError(f'Flag "{self.name}": env_separator requires repeatable=True')
            if self.env_separator is not None and self.env is None:
                raise ValueError(f'Flag "{self.name}": env_separator requires env')
            if self.repeatable and self.env is not None and self.env_separator is None:
                raise ValueError(
                    f'Flag "{self.name}": repeatable flag with env requires env_separator'
                )
        if self.env_separator is not None and len(self.env_separator) != 1:
            raise ValueError(f'Flag "{self.name}": env_separator must be a single character')
        if self.env_separator == "\\":
            raise ValueError(f'Flag "{self.name}": env_separator cannot be a backslash')
        # Validate choices
        if self.choices is not None:
            if self.type is bool:
                raise ValueError(f'Flag "{self.name}": choices is incompatible with type=bool')
            if not isinstance(self.choices, list) or len(self.choices) == 0:
                raise ValueError(f'Flag "{self.name}": choices must be a non-empty list')
            for c in self.choices:
                if not isinstance(c, self.type):
                    raise ValueError(
                        f'Flag "{self.name}": choice {c!r} is not of type {self.type.__name__}'
                    )
        # Validate defaults for dict flags
        if self.compound == "dict":
            if not isinstance(self.default, _MissingSentinel):
                if self.default is not None:
                    if not isinstance(self.default, dict):
                        raise ValueError(
                            f'Flag "{self.name}": dict flag default must be a dict'
                        )
                    if len(self.default) == 0:
                        raise ValueError(
                            f'Flag "{self.name}": explicit empty default is '
                            f'redundant for dict flags, omit the default'
                        )
                    for k, v in self.default.items():
                        if not isinstance(k, str):
                            raise ValueError(
                                f'Flag "{self.name}": dict default key {k!r} '
                                f'must be a string'
                            )
                        _validate_element_type(
                            self.name, self.type, v,
                            f"dict default value for key {k!r}",
                        )
        # Validate repeatable flag defaults
        elif self.repeatable and not isinstance(self.default, _MissingSentinel):
            if self.default is not None:
                if not isinstance(self.default, list):
                    raise ValueError(
                        f'Flag "{self.name}": repeatable flag default must be a list'
                    )
                if len(self.default) == 0:
                    raise ValueError(
                        f'Flag "{self.name}": explicit empty default is redundant '
                        f"for repeatable flags, omit the default"
                    )
                # Validate element types
                type_name = {str: "str", int: "int", float: "float"}[self.type]
                for i, elem in enumerate(self.default):
                    if self.type is str:
                        if not isinstance(elem, str):
                            raise ValueError(
                                f'Flag "{self.name}": default element {i} is not of type {type_name}'
                            )
                    elif self.type is int:
                        if not isinstance(elem, int) or isinstance(elem, bool):
                            raise ValueError(
                                f'Flag "{self.name}": default element {i} is not of type {type_name}'
                            )
                    elif self.type is float:
                        if not isinstance(elem, (int, float)) or isinstance(elem, bool):
                            raise ValueError(
                                f'Flag "{self.name}": default element {i} is not of type {type_name}'
                            )
                        if isinstance(elem, int):
                            self.default[i] = float(elem)
        # Validate default type for int flags
        if self.type is int and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if not self.repeatable and self.compound != "dict" and not isinstance(self.default, int):
                raise ValueError(
                    f'Flag "{self.name}": type=int requires an int default, '
                    f"got {type(self.default).__name__!r}"
                )
        # Validate default type for float flags
        if self.type is float and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if not self.repeatable and self.compound != "dict" and not isinstance(self.default, (int, float)):
                raise ValueError(
                    f'Flag "{self.name}": type=float requires a float default, '
                    f"got {type(self.default).__name__!r}"
                )
        # Resolve _MISSING sentinels based on type
        if isinstance(self.default, _MissingSentinel) or (
            self.default is None and (
                self.compound == "dict" or self.repeatable
            )
        ):
            if self.compound == "dict":
                self.default = {}
            elif self.repeatable:
                self.default = []
            else:
                # No default means required (no default) — same for all types
                # including bool
                self.default = None
        # Validate default is in choices (after sentinel resolution)
        if self.choices is not None and self.default is not None:
            if not self.repeatable and self.default not in self.choices:
                raise ValueError(
                    f'Flag "{self.name}": default {self.default!r} is not in choices '
                    f"{self.choices!r}"
                )
        if isinstance(self.negatable, _MissingSentinel):
            self.negatable = self.type is bool
        elif self.type in (str, int, float):
            # negatable is only meaningful for bool flags
            self.negatable = False


@dataclass
class Arg:
    """Represents a positional argument."""

    name: str
    help: str
    required: bool = True
    default: object = _MISSING
    variadic: bool = False
    type: type = str
    choices: list | None = None
    # Compound type fields (set by __post_init__, not by caller)
    compound: str = "scalar"
    item_type: type | None = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Arg")
        if self.required and not isinstance(self.default, _MissingSentinel):
            raise ValueError("required arg cannot have a default")

        # Parse compound types for args (only list[T] is supported)
        origin = get_origin(self.type)
        if origin is list:
            args = get_args(self.type)
            if not args:
                raise ValueError(
                    f'Arg "{self.name}": list type requires an item type '
                    f'(e.g., list[int]), got bare list'
                )
            if len(args) != 1:
                raise ValueError(
                    f'Arg "{self.name}": list type takes exactly one type '
                    f'argument, got {len(args)}'
                )
            item_t = args[0]
            if item_t not in _NON_BOOL_SCALAR_TYPES:
                raise ValueError(
                    f'Arg "{self.name}": list item type must be str, int, '
                    f'or float, got {item_t!r}'
                )
            if not self.variadic:
                raise ValueError(
                    f'Arg "{self.name}": list type on args requires '
                    f'variadic=True'
                )
            self.compound = "list"
            self.item_type = item_t
            self.type = item_t
        elif origin is dict:
            raise ValueError(
                f'Arg "{self.name}": dict type is not supported on args'
            )
        # Validate type
        elif self.type not in (str, bool, int, float):
            raise ValueError(
                f"Arg.type must be str, bool, int, or float, got {self.type!r}"
            )
        # Validate choices
        if self.choices is not None:
            if self.type is bool:
                raise ValueError(
                    f'Arg "{self.name}": choices is incompatible with type=bool'
                )
            if not isinstance(self.choices, list) or len(self.choices) == 0:
                raise ValueError(
                    f'Arg "{self.name}": choices must be a non-empty list'
                )
            for c in self.choices:
                if not isinstance(c, self.type):
                    raise ValueError(
                        f'Arg "{self.name}": choice {c!r} is not of type '
                        f"{self.type.__name__}"
                    )
        # Validate default type matches declared type
        if not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if self.compound == "list":
                # self.type was normalized to the item type above; the
                # default itself must be a list of that item type.
                if not isinstance(self.default, list):
                    raise ValueError(
                        f'Arg "{self.name}": list arg default must be a list'
                    )
                if len(self.default) == 0:
                    raise ValueError(
                        f'Arg "{self.name}": explicit empty default is '
                        f"redundant for list args, omit the default"
                    )
                type_name = {str: "str", int: "int", float: "float"}[self.type]
                for i, elem in enumerate(self.default):
                    if self.type is str:
                        valid = isinstance(elem, str)
                    elif self.type is int:
                        valid = isinstance(elem, int) and not isinstance(elem, bool)
                    else:  # float
                        valid = (
                            isinstance(elem, (int, float))
                            and not isinstance(elem, bool)
                        )
                        if valid and isinstance(elem, int):
                            # Auto-coerce int to float, mirroring list flag defaults
                            self.default[i] = float(elem)
                    if not valid:
                        raise ValueError(
                            f'Arg "{self.name}": default element {i} '
                            f"is not of type {type_name}"
                        )
            elif self.type is int:
                if not isinstance(self.default, int) or isinstance(self.default, bool):
                    raise ValueError(
                        f'Arg "{self.name}": type=int requires an int default, '
                        f"got {type(self.default).__name__!r}"
                    )
            elif self.type is float:
                if not isinstance(self.default, (int, float)) or isinstance(self.default, bool):
                    raise ValueError(
                        f'Arg "{self.name}": type=float requires a float default, '
                        f"got {type(self.default).__name__!r}"
                    )
            elif self.type is bool:
                if not isinstance(self.default, bool):
                    raise ValueError(
                        f'Arg "{self.name}": type=bool requires a bool default, '
                        f"got {type(self.default).__name__!r}"
                    )
            elif self.type is str:
                if not isinstance(self.default, str):
                    raise ValueError(
                        f'Arg "{self.name}": type=str requires a str default, '
                        f"got {type(self.default).__name__!r}"
                    )
        # Validate default is in choices
        if self.choices is not None and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if self.default not in self.choices:
                raise ValueError(
                    f'Arg "{self.name}": default {self.default!r} is not in choices '
                    f"{self.choices!r}"
                )


@dataclass
class FlagSet:
    """A reusable bundle of flags."""

    name: str
    flags: list[Flag] = field(default_factory=list)


@dataclass
class MutexGroup:
    """A group of mutually exclusive flags."""

    flags: list[Flag] = field(default_factory=list)


@dataclass
class CoRequired:
    """Flags that must all appear together or none."""

    flags: list[str]


@dataclass
class Requires:
    """Flag that depends on another flag being present."""

    flag: str
    depends_on: str


@dataclass
class Implies:
    """When a trigger flag is provided, automatically set a target flag to a value."""

    flag: str       # trigger flag name
    implies: str    # target flag name
    value: bool     # value to set on target when trigger is present


@dataclass
class Passthrough:
    """Marks a command as passthrough -- all tokens after the command name are
    forwarded to the handler as a raw list, bypassing flag/arg parsing."""

    handler: Callable  # func(name: str, args: list[str], globals: dict) -> int


@dataclass
class DeprecatedCommand:
    """A declaration-only deprecated command: prints message to stderr and exits 1."""

    name: str
    message: str


@dataclass(frozen=True)
class Command:
    """A leaf command with a handler."""

    name: str
    help: str
    handler: Callable | None
    flags: tuple[Flag, ...] = ()
    args: tuple[Arg, ...] = ()
    flag_sets: tuple[FlagSet, ...] = ()
    mutex: tuple[MutexGroup, ...] = ()
    dependencies: tuple[CoRequired | Requires | Implies, ...] = ()
    passthrough: Passthrough | None = None
    tags: frozenset[str] = frozenset()
    hidden: bool = False
    interactive: bool = False
    config_fields: tuple[str, ...] = ()
    needs_context: bool = False

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Command")
        for tag in self.tags:
            if not _IDENTIFIER_RE.match(tag):
                raise ValueError(f'invalid tag name "{tag}": must match [a-z][a-z0-9-]*')


@dataclass
class Group:
    """A container for nested commands and subgroups (arbitrary depth)."""

    name: str
    help: str
    commands: dict[str, Command] = field(default_factory=dict)
    _groups: dict[str, Group] = field(default_factory=dict)
    deprecated: dict[str, DeprecatedCommand] = field(default_factory=dict)
    env_prefix: str | None = None
    _global_flags: list[Flag] = field(default_factory=list)
    tags: frozenset[str] = frozenset()
    _accumulated_tags: frozenset[str] = frozenset()
    hidden: bool = False
    _config_fields_ref: dict[str, ConfigField] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Group")
        for tag in self.tags:
            if not _IDENTIFIER_RE.match(tag):
                raise ValueError(f'invalid tag name "{tag}": must match [a-z][a-z0-9-]*')

    def group(self, name: str, *, help: str, tags: set[str] | None = None,
              hidden: bool = False) -> Group:
        """Create and register a child subgroup."""
        if name in self.commands:
            raise ValueError(
                f'group "{name}" collides with an existing command'
            )
        if name in self._groups:
            raise ValueError(
                f'group "{name}" is already registered'
            )
        own_tags = frozenset(tags or set())
        grp = Group(name=name, help=help, env_prefix=self.env_prefix,
                     _global_flags=self._global_flags,
                     tags=own_tags,
                     _accumulated_tags=self._accumulated_tags | own_tags,
                     hidden=hidden,
                     _config_fields_ref=self._config_fields_ref)
        self._groups[name] = grp
        return grp

    def deprecate(self, name: str, *, message: str) -> None:
        """Register a deprecated subcommand in this group."""
        if not name or not name.strip():
            raise ValueError("deprecated command name must be a non-empty string")
        if not message or not message.strip():
            raise ValueError(f'deprecated command "{name}": message must not be empty')
        if name in self.commands:
            raise ValueError(
                f'deprecated command "{name}" collides with an existing command'
            )
        if name in self._groups:
            raise ValueError(
                f'deprecated command "{name}" collides with an existing group'
            )
        if name in self.deprecated:
            raise ValueError(
                f'deprecated command "{name}" is already registered'
            )
        self.deprecated[name] = DeprecatedCommand(name=name, message=message)

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        flag_sets: list[FlagSet] | None = None,
        mutex: list[MutexGroup] | None = None,
        dependencies: list[CoRequired | Requires | Implies] | None = None,
        passthrough: Passthrough | None = None,
        tags: set[str] | None = None,
        hidden: bool = False,
        interactive: bool = False,
        config_fields: list[str] | None = None,
    ) -> Callable:
        """Decorator to register a command within this group."""

        def decorator(func: Callable) -> Callable:
            if name in self._groups:
                raise ValueError(
                    f'command "{name}" collides with an existing group'
                )
            cmd = _build_and_validate_command(
                name, help=help, handler=func, args=args, flag_sets=flag_sets, mutex=mutex,
                dependencies=dependencies,
                env_prefix=self.env_prefix,
                global_flags=self._global_flags,
                passthrough=passthrough,
                tags=tags,
                inherited_tags=self._accumulated_tags,
                hidden=hidden,
                interactive=interactive,
                config_fields=config_fields,
                config_fields_ref=self._config_fields_ref,
            )
            self.commands[name] = cmd
            return func

        return decorator


_CONFIG_FIELD_NAME_RE = re.compile(r"^_?[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


@dataclass
class ConfigField:
    """Declares a typed config file field.

    Fields with no default are required — the config system will error if
    they are missing from the config file. Fields with a default are optional.
    """

    name: str
    type: type
    help: str
    default: object = _MISSING
    required: bool = field(init=False)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "ConfigField")
        if self.type not in (str, bool, int, float):
            raise ValueError(
                f"ConfigField.type must be str, bool, int, or float, got {self.type!r}"
            )
        if not _CONFIG_FIELD_NAME_RE.match(self.name):
            raise ValueError(
                f'ConfigField name "{self.name}" is invalid: '
                f"must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* "
                f"(lowercase, dots for sections)"
            )
        self.required = isinstance(self.default, _MissingSentinel)
        if not self.required and not isinstance(self.default, self.type):
            raise ValueError(
                f'ConfigField "{self.name}": default value {self.default!r} '
                f"does not match type {self.type.__name__}"
            )


@dataclass
class Result:
    """Returned by app.test()."""

    stdout: str
    stderr: str
    exit_code: int
    data: object = None


@dataclass
class Tool:
    """A tool descriptor for exposing CLI commands to tool-using LLM agents."""

    name: str
    description: str
    parameters: dict
    execute: Callable


@dataclass
class CheckResult:
    """Result of running a single check."""

    status: str
    message: str
    details: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in ("pass", "fail", "warn", "skip"):
            raise ValueError(
                f'CheckResult.status must be one of "pass", "fail", "warn", "skip", '
                f"got {self.status!r}"
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("CheckResult.message must be a non-empty string")


@dataclass(frozen=True)
class CheckRunResult:
    """A named check result returned by App.run_checks()."""

    name: str
    result: CheckResult


@runtime_checkable
class CheckContext(Protocol):
    """Minimal interface that tool-specific check contexts must satisfy."""

    project_root: Path


@dataclass
class _CheckDef:
    """Internal definition of a single check loaded from TOML."""

    name: str
    tags: list[str]
    severity: str
    fast: bool
    pure: bool
    needs_network: bool
    depends_on: list[str]
    scope: str = ""
    impl: object | None = None


@dataclass
class App:
    """The root CLI application."""

    name: str
    help: str
    version: str | None = None
    env_prefix: str | None = None
    config: bool = False
    config_path: str | None = None
    config_format: str = "json"
    no_default_config_path: bool = False
    checks_path: str | Path | None = None
    checks_embed: bytes | None = None
    flags: list[Flag] = field(default_factory=list)
    _commands: dict[str, Command] = field(default_factory=dict)
    _groups: dict[str, Group] = field(default_factory=dict)
    _deprecated: dict[str, DeprecatedCommand] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Auto-detect version from package metadata if not provided
        if self.version is None:
            try:
                self.version = importlib.metadata.version(self.name)
            except importlib.metadata.PackageNotFoundError:
                self.version = "unknown"
        _require_non_empty_str(self.help, "help", "App")
        # Check for duplicate and reserved global flag names
        seen: set[str] = set()
        for f in self.flags:
            if f.name in seen:
                raise ValueError(f'duplicate global flag name "{f.name}"')
            if f.name in _RESERVED_GLOBAL_FLAG_NAMES:
                raise ValueError(
                    f'global flag name "{f.name}" is reserved'
                )
            if f.short and f.short in _RESERVED_GLOBAL_FLAG_NAMES:
                raise ValueError(
                    f'global short flag "{f.short}" is reserved'
                )
            seen.add(f.name)
        self._global_flags: list[Flag] = list(self.flags)
        self._last_global_values: dict[str, object] = {}
        # Validate config_format
        if self.config_format not in ("json", "toml"):
            raise ValueError(
                f'App.config_format must be "json" or "toml", got {self.config_format!r}'
            )
        # Register config subcommands if enabled (config data loaded at parse time)
        self._config_data: dict = {}
        if self.config:
            self._register_config_group()
        # Discover checks TOML
        self._check_context_factory: Callable | None = None
        self._scope_adapter: Callable | None = None
        if self.checks_path is not None and self.checks_embed is not None:
            raise ValueError("cannot use both checks_path and checks_embed")
        if self.checks_path is not None:
            checks_toml_path = Path(self.checks_path).resolve()
            if not checks_toml_path.is_file():
                raise ValueError(f"checks_path does not exist: {self.checks_path}")
            app_name, self._check_defs = _load_checks_toml(checks_toml_path)
            if app_name != self.name:
                raise ValueError(
                    f'checks.toml: app "{app_name}" does not match app name "{self.name}"'
                )
            self._checks_enabled = True
            self._register_check_command()
        elif self.checks_embed is not None:
            app_name, self._check_defs = _parse_checks_toml(self.checks_embed)
            if app_name != self.name:
                raise ValueError(
                    f'checks.toml: app "{app_name}" does not match app name "{self.name}"'
                )
            self._checks_enabled = True
            self._register_check_command()
        else:
            self._check_defs: dict[str, _CheckDef] = {}
            self._checks_enabled = False

        self._tag_contracts: dict[str, str] = {}

        # Config field declarations
        self._config_fields: dict[str, ConfigField] = {}
        self._framework_fields: dict[str, ConfigField] = {}

    @property
    def config_file_path(self) -> str:
        """Return the resolved config file path for this app."""
        return _config_path(self.name, override=self.config_path, config_format=self.config_format)

    def config_field(
        self,
        name: str,
        type: type,
        help: str,
        default: object = _MISSING,
    ) -> ConfigField:
        """Declare a typed config file field.

        Args:
            name: Field name. Dots allowed for TOML sections (e.g. "serve.port").
                  Names starting with underscore are reserved for framework fields.
            type: Field type — str, bool, int, or float.
            help: Help text describing the field.
            default: Default value. If omitted, the field is required.

        Returns:
            The registered ConfigField.

        Raises:
            ValueError: If the name is invalid, duplicated, reserved, or
                        the default doesn't match the declared type.
        """
        if name.startswith("_"):
            raise ValueError(
                f'config field name "{name}" is reserved: '
                f"names starting with underscore are reserved for framework fields"
            )
        if name in self._config_fields:
            raise ValueError(f'duplicate config field name "{name}"')
        if name in self._framework_fields:
            raise ValueError(
                f'config field name "{name}" conflicts with framework field'
            )
        cf = ConfigField(name=name, type=type, help=help, default=default)
        self._config_fields[name] = cf
        return cf

    def _register_framework_field(
        self,
        name: str,
        type: type,
        help: str,
    ) -> ConfigField:
        """Register a framework-owned config field (e.g. _schema_version).

        Framework fields must start with underscore. They are declared by the
        framework, not the user, and cannot conflict with user fields.
        """
        if not name.startswith("_"):
            raise ValueError(
                f'framework field name "{name}" must start with underscore'
            )
        if name in self._framework_fields:
            raise ValueError(f'duplicate framework field name "{name}"')
        if name in self._config_fields:
            raise ValueError(
                f'framework field name "{name}" conflicts with user config field'
            )
        # Framework fields are always optional (no default required from user).
        # Use _MISSING as default since they are managed internally.
        cf = ConfigField(name=name, type=type, help=help)
        self._framework_fields[name] = cf
        return cf

    def check(self, name: str):
        """Decorator to register a check implementation."""
        def decorator(fn):
            if not self._checks_enabled:
                raise ValueError(
                    f'cannot register check "{name}": '
                    f"checks not enabled"
                )
            if name not in self._check_defs:
                raise ValueError(
                    f'cannot register check "{name}": '
                    f"not declared in checks.toml"
                )
            if self._check_defs[name].impl is not None:
                raise ValueError(f'check "{name}": duplicate registration')
            self._check_defs[name].impl = fn
            return fn
        return decorator

    def _validate_check_registrations(self) -> str | None:
        """Validate that all declared checks have registered implementations.

        Returns an error message if any are missing, or None if all OK.
        """
        if not self._checks_enabled:
            return None
        missing = sorted(
            name for name, cdef in self._check_defs.items()
            if cdef.impl is None
        )
        if missing:
            return (
                "checks declared in checks.toml but not registered: "
                + ", ".join(missing)
            )
        return None

    def tag_contract(self, tag: str, *, requires_flag: str) -> None:
        """Declare that any command with the given tag must have the named flag."""
        if not _IDENTIFIER_RE.match(tag):
            raise ValueError(f'invalid tag name "{tag}": must match [a-z][a-z0-9-]*')
        self._tag_contracts[tag] = requires_flag

    def _validate_tag_contracts(self) -> str | None:
        """Check that all tag contracts are satisfied.

        Returns an error message if any command violates a contract, or None.
        """
        if not self._tag_contracts:
            return None

        def _check_commands(commands: dict) -> str | None:
            for cmd in commands.values():
                if cmd.passthrough is not None:
                    continue
                for tag in cmd.tags:
                    if tag in self._tag_contracts:
                        required_flag = self._tag_contracts[tag]
                        flag_names = {f.name for f in cmd.flags} | {f.name for f in self._global_flags}
                        if required_flag not in flag_names:
                            return (
                                f'command "{cmd.name}": tag "{tag}" requires '
                                f'flag "--{required_flag}"'
                            )
            return None

        def _check_groups(groups: dict) -> str | None:
            for group in groups.values():
                err = _check_commands(group.commands)
                if err:
                    return err
                err = _check_groups(group._groups)
                if err:
                    return err
            return None

        err = _check_commands(self._commands)
        if err:
            return err
        return _check_groups(self._groups)

    def _resolve_config_data(
        self,
        runtime_path_override: str | None = None,
        hermetic: bool = False,
    ) -> dict:
        """Single entry point for all config loading.

        The runtime_path_override and hermetic parameters are plumbed for
        future use (Phase 1) but currently inert.
        """
        if hermetic:
            return {}
        override = runtime_path_override or self.config_path
        return _load_config(
            self.name,
            config_path_override=override,
            config_format=self.config_format,
        )

    def _validate_config_fields(self, cmd: Command, config_data: dict) -> str | None:
        """Validate config file contents against the command's bound config fields.

        Checks:
        1. Each bound required config field exists in config with the correct type.
        2. Each key in config matches a registered flag, config field, or framework
           field. Unknown keys are hard errors.

        Returns an error message string, or None if all OK.
        """
        # Check bound required config fields exist with correct type
        for cf_name in cmd.config_fields:
            cf = self._config_fields.get(cf_name)
            if cf is None:
                # Should not happen (validated at registration), but be defensive
                return f'config field "{cf_name}" is not registered'
            found, value = _nested_get(config_data, cf_name)
            if not found:
                if cf.required:
                    return (
                        f'required config field "{cf_name}" is missing from '
                        f"config file"
                    )
                # Optional and missing -- that is fine
                continue
            # Validate type
            err = _check_config_field_type(cf, value)
            if err:
                return err

        # Check all keys in config file are known
        all_config_keys = _collect_nested_keys(config_data)
        # Build set of known keys
        all_flags = self._collect_all_flags()
        known_flag_keys = {_flag_param_name(f.name) for f in all_flags}
        known_field_keys = set(self._config_fields.keys())
        known_framework_keys = set(self._framework_fields.keys())

        for key in all_config_keys:
            if key in known_flag_keys:
                continue
            if key in known_field_keys:
                continue
            if key in known_framework_keys:
                continue
            return f'unknown key "{key}" in config file'

        return None

    def set_check_context(self, factory: Callable) -> None:
        """Set the factory function that creates CheckContext for check runs.

        The factory is called with no arguments and must return a CheckContext.
        """
        self._check_context_factory = factory

    def set_scope_adapter(self, adapter: Callable) -> None:
        """Set the scope adapter callback for scoped checks.

        The adapter is called as ``adapter(context, scope_string)`` and must
        return either a replacement context object (used for the check's impl)
        or a ``CheckResult`` (used directly, skipping the impl call).
        """
        self._scope_adapter = adapter

    def run_checks(
        self,
        context: CheckContext,
        *,
        tag_expr: str | None = None,
        name_glob: str | None = None,
        run_all: bool = False,
        ignore_warnings: bool = False,
    ) -> tuple[list[CheckRunResult], int]:
        """Run checks programmatically with filtering and dependency resolution.

        Returns (results, exit_code) where results is a list of CheckRunResult
        and exit_code is 0 if all pass (or all warn with ignore_warnings), else 1.
        """
        if not self._checks_enabled:
            raise ValueError("checks are not enabled on this App")
        err = self._validate_check_registrations()
        if err:
            raise ValueError(err)
        selected = _filter_checks(self._check_defs, tag_expr, name_glob, run_all)
        if not selected:
            return ([], 0)
        order = _resolve_check_order(self._check_defs, selected)
        raw_results, exit_code = _run_checks(
            self._check_defs, order, context, ignore_warnings,
            scope_adapter=self._scope_adapter,
        )
        results = [
            CheckRunResult(name=name, result=result)
            for name, result in raw_results
        ]
        return (results, exit_code)

    def _register_check_command(self) -> None:
        """Register the auto-generated 'check' command when checks.toml exists."""
        app_ref = self  # capture for closure

        def _check_handler(
            *, all: bool, tag: str, name: str,
            list: bool, json: bool, ignore_warnings: bool,
            verbose: bool, dry_run: bool, **_kw,
        ) -> int:
            # Treat empty strings as "not provided"
            tag_expr = tag if tag else None
            name_glob = name if name else None

            if list:
                _check_list_mode(app_ref._check_defs, json)
                return 0

            # Determine if any execution filter is active
            has_filter = all or tag_expr is not None or name_glob is not None

            if not has_filter:
                # No flags: show help for the check command
                check_cmd = app_ref._commands["check"]
                prefix = app_ref._find_command_prefix(check_cmd)
                print(_format_command_help(app_ref, check_cmd, prefix))
                return 0

            # Resolve filters and order
            selected = _filter_checks(app_ref._check_defs, tag_expr, name_glob, all)
            if not selected:
                print("No checks matched the given filters.")
                return 0
            order = _resolve_check_order(app_ref._check_defs, selected)

            if dry_run:
                _check_dry_run_mode(app_ref._check_defs, order)
                return 0

            # Execution mode: need a context
            if app_ref._check_context_factory is None:
                print(
                    "error: no check context configured. "
                    "Call app.set_check_context(factory) before running.",
                    file=sys.stderr,
                )
                return 1
            context = app_ref._check_context_factory()
            raw_results, exit_code = _run_checks(
                app_ref._check_defs, order, context, ignore_warnings,
                scope_adapter=app_ref._scope_adapter,
            )

            results_wrapped = [
                CheckRunResult(name=n, result=r) for n, r in raw_results
            ]
            if json:
                print(format_check_results_json(results_wrapped))
            else:
                output = format_check_results(results_wrapped, verbose)
                if output:
                    print(output)

            return exit_code

        # Filter out extra flags that already exist as global flags to avoid
        # collisions -- the handler receives global flag values automatically.
        global_flag_names = {gf.name for gf in self._global_flags}
        candidate_extra_flags = [
            Flag(name="all", type=bool, default=False, help="Run every registered check regardless of tag or name filters"),
            Flag(name="tag", type=str, default="", help="Tag DSL expression to select checks (e.g. 'changelog & !quality')"),
            Flag(name="name", type=str, default="", help="Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*')"),
            Flag(name="list", type=bool, default=False, help="List all registered checks with their tags and exit without running"),
            Flag(name="json", type=bool, default=False, help="Output check results as machine-readable JSON instead of human text"),
            Flag(name="ignore-warnings", type=bool, default=False, help="Treat warn-severity results as passing so they do not cause nonzero exit"),
            Flag(name="verbose", type=bool, default=False, help="Show full details for passing checks in addition to failures and warnings"),
            Flag(name="dry-run", type=bool, default=False, help="Show which checks would run based on current filters without executing them"),
        ]
        extra_flags = [f for f in candidate_extra_flags if f.name not in global_flag_names]
        check_cmd = _build_and_validate_command(
            "check",
            help="Run project checks registered via the check framework and report results",
            handler=_check_handler,
            args=None,
            flag_sets=None,
            mutex=None,
            dependencies=None,
            env_prefix=self.env_prefix,
            global_flags=self._global_flags,
            passthrough=None,
            extra_flags=extra_flags,
        )
        self._commands["check"] = check_cmd

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        flag_sets: list[FlagSet] | None = None,
        mutex: list[MutexGroup] | None = None,
        dependencies: list[CoRequired | Requires | Implies] | None = None,
        passthrough: Passthrough | None = None,
        tags: set[str] | None = None,
        hidden: bool = False,
        interactive: bool = False,
        config_fields: list[str] | None = None,
    ) -> Callable:
        """Decorator to register a top-level command."""

        def decorator(func: Callable) -> Callable:
            cmd = _build_and_validate_command(
                name,
                help=help,
                handler=func,
                args=args,
                flag_sets=flag_sets,
                mutex=mutex,
                dependencies=dependencies,
                env_prefix=self.env_prefix,
                global_flags=self._global_flags,
                passthrough=passthrough,
                tags=tags,
                inherited_tags=None,
                hidden=hidden,
                interactive=interactive,
                config_fields=config_fields,
                config_fields_ref=self._config_fields,
            )
            self._commands[name] = cmd
            return func

        return decorator

    def group(self, name: str, *, help: str, tags: set[str] | None = None,
              hidden: bool = False) -> Group:
        """Create and register a command group."""
        own_tags = frozenset(tags or set())
        grp = Group(name=name, help=help, env_prefix=self.env_prefix,
                     _global_flags=self._global_flags,
                     tags=own_tags,
                     _accumulated_tags=own_tags,
                     hidden=hidden,
                     _config_fields_ref=self._config_fields)
        self._groups[name] = grp
        return grp

    def deprecate(self, name: str, *, message: str) -> None:
        """Register a deprecated top-level command."""
        if not name or not name.strip():
            raise ValueError("deprecated command name must be a non-empty string")
        if not message or not message.strip():
            raise ValueError(f'deprecated command "{name}": message must not be empty')
        if name in self._commands:
            raise ValueError(
                f'deprecated command "{name}" collides with an existing command'
            )
        if name in self._groups:
            raise ValueError(
                f'deprecated command "{name}" collides with an existing group'
            )
        if name in self._deprecated:
            raise ValueError(
                f'deprecated command "{name}" is already registered'
            )
        self._deprecated[name] = DeprecatedCommand(name=name, message=message)

    def _collect_all_flags(self) -> list[Flag]:
        """Collect all flags (global + all commands in all groups), for config show."""
        flags: list[Flag] = list(self._global_flags)
        seen_names: set[str] = {f.name for f in flags}
        for cmd in self._commands.values():
            for f in cmd.flags:
                if f.name not in seen_names:
                    flags.append(f)
                    seen_names.add(f.name)

        def _collect_from_group(grp: Group) -> None:
            for cmd in grp.commands.values():
                for f in cmd.flags:
                    if f.name not in seen_names:
                        flags.append(f)
                        seen_names.add(f.name)
            for sub in grp._groups.values():
                _collect_from_group(sub)

        for name, grp in self._groups.items():
            if name == "config":
                continue  # skip auto-generated config group
            _collect_from_group(grp)
        return flags

    def _register_config_group(self) -> None:
        """Register the auto-generated 'config' command group."""
        config_grp = Group(
            name="config",
            help="Manage persistent configuration values stored in the config file",
            env_prefix=self.env_prefix,
            _global_flags=self._global_flags,
        )

        app_ref = self  # capture for closures

        # config path
        config_grp.commands["path"] = Command(
            name="path",
            help="Print the absolute path to the config file for this application",
            handler=lambda **_kw: print(_config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )),
        )

        # config show
        def _config_show_handler(**_kw) -> int:
            use_json = _kw.get("json", False)
            config_data = app_ref._resolve_config_data()
            all_flags = app_ref._collect_all_flags()
            if use_json:
                result = {}
                for f in all_flags:
                    param = _flag_param_name(f.name)
                    if param in config_data:
                        value = config_data[param]
                        source = "config"
                    elif f.default is not None:
                        value = f.default
                        source = "default"
                    else:
                        value = None
                        source = "default"
                    result[param] = {"value": value, "source": source}
                # Include config fields
                for cf_name, cf in app_ref._config_fields.items():
                    found, value = _nested_get(config_data, cf_name)
                    if found:
                        source = "config"
                    elif not isinstance(cf.default, _MissingSentinel):
                        value = cf.default
                        source = "default"
                    else:
                        value = None
                        source = "not set"
                    entry: dict = {
                        "value": value,
                        "source": source,
                        "type": cf.type.__name__,
                        "required": cf.required,
                        "help": cf.help,
                    }
                    if not isinstance(cf.default, _MissingSentinel):
                        entry["default"] = cf.default
                    result[cf_name] = entry
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0
            # --plain
            for f in all_flags:
                param = _flag_param_name(f.name)
                if param in config_data:
                    value = config_data[param]
                    source = "config"
                elif f.default is not None:
                    value = f.default
                    source = "default"
                else:
                    value = None
                    source = "default"
                print(f"{param} = {_format_config_value(value)}  (source: {source})")
            # Include config fields in plain output
            if app_ref._config_fields:
                print()
                print("Config fields:")
                for cf_name, cf in app_ref._config_fields.items():
                    found, value = _nested_get(config_data, cf_name)
                    if found:
                        source = "config"
                    elif not isinstance(cf.default, _MissingSentinel):
                        value = cf.default
                        source = "default"
                    else:
                        value = None
                        source = "not set"
                    req_str = "required" if cf.required else "optional"
                    print(
                        f"  {cf_name} ({cf.type.__name__}, {req_str})"
                        f" = {_format_config_value(value)}"
                        f"  (source: {source})"
                        f"  -- {cf.help}"
                    )
            return 0

        config_show_flags = [
            Flag(name="plain", type=bool, default=False, help="Display config values in a human-readable table format"),
            Flag(name="json", type=bool, default=False, help="Display config values as a JSON object with source metadata"),
        ]
        config_show_mutex = [MutexGroup(flags=config_show_flags)]
        config_grp.commands["show"] = Command(
            name="show",
            help="Show all config values with their sources (config file, env, or default)",
            handler=_config_show_handler,
            flags=tuple(config_show_flags),
            mutex=tuple(config_show_mutex),
        )

        # config set
        def _config_set_handler(key, value=None, **_kw) -> int:
            path = _config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            # Read existing config
            existing = app_ref._resolve_config_data()

            # Look up the key against registered flags and config fields
            all_flags = app_ref._collect_all_flags()
            matched_flag = None
            matched_config_field = None
            for f in all_flags:
                if _flag_param_name(f.name) == key:
                    matched_flag = f
                    break
            if matched_flag is None:
                # Check config fields
                if key in app_ref._config_fields:
                    matched_config_field = app_ref._config_fields[key]
            if matched_flag is None and matched_config_field is None:
                print(f"config set: unknown key '{key}'", file=sys.stderr)
                return 1

            # Config field path: simpler handling (no repeatable, no mutex)
            if matched_config_field is not None:
                return _config_set_field(
                    key, value, matched_config_field, existing, path,
                    app_ref.config_format, _kw,
                )

            use_clear = _kw.get("clear", False)
            use_default = _kw.get("default", False)

            # Validate: exactly one of (value, --clear, --default)
            has_value = value is not None
            if use_clear and use_default:
                print("config set: --clear and --default are mutually exclusive",
                      file=sys.stderr)
                return 1
            if has_value and use_clear:
                print("config set: cannot provide a value with --clear",
                      file=sys.stderr)
                return 1
            if has_value and use_default:
                print("config set: cannot provide a value with --default",
                      file=sys.stderr)
                return 1
            if not has_value and not use_clear and not use_default:
                print("config set: provide a value, --clear, or --default",
                      file=sys.stderr)
                return 1

            # --clear: repeatable/dict flags only
            if use_clear:
                if matched_flag.compound == "dict":
                    existing[key] = {}
                elif matched_flag.repeatable:
                    existing[key] = []
                else:
                    print("config set: --clear is only for repeatable flags",
                          file=sys.stderr)
                    return 1
                if app_ref.config_format == "toml":
                    _write_toml_flat(existing, path)
                else:
                    with open(path, "w") as fh:
                        fh.write(json.dumps(existing, indent=2) + "\n")
                return 0

            # --default: remove the key from config
            if use_default:
                if key not in existing:
                    print(f"config set: key '{key}' not in config",
                          file=sys.stderr)
                    return 1
                del existing[key]
                if app_ref.config_format == "toml":
                    _write_toml_flat(existing, path)
                else:
                    with open(path, "w") as fh:
                        fh.write(json.dumps(existing, indent=2) + "\n")
                return 0

            # Coerce the string value to the flag's type
            if matched_flag.compound == "dict":
                # Dict flags: parse as JSON
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as e:
                    print(f"config set: key '{key}': invalid JSON: {e}",
                          file=sys.stderr)
                    return 1
                if not isinstance(parsed, dict):
                    print(f"config set: key '{key}': expected JSON object",
                          file=sys.stderr)
                    return 1
                typed_value = {}
                for dk, dv in parsed.items():
                    try:
                        typed_value[dk] = _coerce_config_scalar(
                            dv, matched_flag.value_type,
                        )
                    except ValueError as e:
                        print(
                            f"config set: key '{key}': value for '{dk}': {e}",
                            file=sys.stderr,
                        )
                        return 1
            elif matched_flag.repeatable:
                # Split on comma, coerce each element
                parts = _split_escaped(value, ",")
                try:
                    if matched_flag.type == int:
                        typed_value = [_strict_int(p) for p in parts]
                    elif matched_flag.type == float:
                        coerced = []
                        for p in parts:
                            try:
                                coerced.append(_strict_float(p))
                            except ValueError as fe:
                                msg = str(fe)
                                if msg in ("NaN is not allowed",
                                           "Inf is not allowed"):
                                    raise
                                raise ValueError(
                                    f"expected float, got '{p}'"
                                ) from fe
                        typed_value = coerced
                    else:  # str
                        typed_value = parts
                except ValueError as e:
                    print(f"config set: key '{key}': {e}", file=sys.stderr)
                    return 1
                # Unique enforcement
                if matched_flag.unique:
                    dup = _find_duplicate(typed_value)
                    if dup is not None:
                        print(
                            f"config set: key '{key}': duplicate value "
                            f"'{_format_value_for_error(dup)}'",
                            file=sys.stderr,
                        )
                        return 1
            else:
                try:
                    if matched_flag.type == bool:
                        typed_value = _strict_bool(value)
                    elif matched_flag.type == int:
                        typed_value = _strict_int(value)
                    elif matched_flag.type == float:
                        try:
                            typed_value = _strict_float(value)
                        except ValueError as fe:
                            msg = str(fe)
                            if msg in ("NaN is not allowed",
                                       "Inf is not allowed"):
                                raise
                            raise ValueError(
                                f"expected float, got '{value}'"
                            ) from fe
                    else:  # str
                        typed_value = value
                except ValueError as e:
                    print(f"config set: key '{key}': {e}", file=sys.stderr)
                    return 1

            existing[key] = typed_value
            if app_ref.config_format == "toml":
                _write_toml_flat(existing, path)
            else:
                with open(path, "w") as fh:
                    fh.write(json.dumps(existing, indent=2) + "\n")
            return 0

        config_grp.commands["set"] = Command(
            name="set",
            help="Set a persistent config value that overrides the default for a flag",
            handler=_config_set_handler,
            args=(
                Arg(name="key", help="The config key to set, matching a registered flag name"),
                Arg(name="value",
                    help="Value to set (comma-separated for repeatable flags, use backslash to escape commas)",
                    required=False),
            ),
            flags=(
                Flag(name="clear", type=bool, default=False,
                     help="Clear a repeatable flag by setting its value to an empty list"),
                Flag(name="default", type=bool, default=False,
                     help="Reset a key to its default value by removing it from the config file"),
            ),
        )

        # config edit
        def _config_edit_handler(**_kw) -> None:
            path = _config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            if not os.path.isfile(path):
                if app_ref.config_format == "toml":
                    with open(path, "w") as fh:
                        fh.write("")
                else:
                    with open(path, "w") as fh:
                        fh.write("{}\n")
            editor = os.environ.get("EDITOR", "vi")
            subprocess.run([editor, path])

        config_grp.commands["edit"] = Command(
            name="edit",
            help="Open the config file for manual editing in $EDITOR (creates if missing)",
            handler=_config_edit_handler,
            interactive=True,
        )

        # config init
        def _config_init_handler(**_kw) -> int:
            cfg_path = _config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )
            if os.path.isfile(cfg_path):
                print(
                    f"config init: config file already exists: {cfg_path}",
                    file=sys.stderr,
                )
                return 1
            dir_path = os.path.dirname(cfg_path)
            os.makedirs(dir_path, exist_ok=True)
            if app_ref.config_format == "toml":
                content = _generate_config_template_toml(
                    app_ref._collect_all_flags(),
                    app_ref._config_fields,
                )
            else:
                content = _generate_config_template_json(
                    app_ref._collect_all_flags(),
                    app_ref._config_fields,
                )
            with open(cfg_path, "w") as fh:
                fh.write(content)
            print(cfg_path)
            return 0

        config_grp.commands["init"] = Command(
            name="init",
            help="Generate a template config file with documented fields and defaults",
            handler=_config_init_handler,
        )

        self._groups["config"] = config_grp

    def _pre_scan_reserved_flags(self, argv: list[str]) -> dict:
        """Position-aware pre-scan for --dump-schema, --mcp, --config.

        Scans the pre-command region of argv (before the first non-flag
        token, before ``--``).  Known global flags and their values are
        skipped so that a global-flag value matching a command name does
        not terminate the scan early.

        Returns a dict with keys: dump_schema, serve_mcp, config_path, err,
        cleaned_argv.
        """
        # Build a set of known global flag tokens with value-taking info
        known_flags: dict[str, bool] = {}  # token -> takes_value
        for f in self._global_flags:
            known_flags[f"--{f.name}"] = f.type is not bool
            if f.short:
                known_flags[f"-{f.short}"] = f.type is not bool
            if f.type is bool and f.negatable:
                known_flags[f"--no-{f.name}"] = False

        result: dict = {}
        exclude_indices: set[int] = set()
        i = 0
        while i < len(argv):
            tok = argv[i]

            # -- terminates the pre-command region
            if tok == "--":
                break

            # Non-flag token = command name: stop scanning
            if not tok.startswith("-") or tok == "-":
                break

            # --dump-schema
            if tok == "--dump-schema":
                result["dump_schema"] = True
                return result

            # --mcp
            if tok == "--mcp":
                result["serve_mcp"] = True
                return result

            # --config=<value>
            if tok.startswith("--config="):
                if not self.config:
                    result["err"] = (
                        "--config is not available: this app does not use config files"
                    )
                    return result
                val = tok[len("--config="):]
                if not val:
                    result["err"] = "flag '--config' requires a value"
                    return result
                result["config_path"] = val
                exclude_indices.add(i)
                i += 1
                continue

            # --config <value>
            if tok == "--config":
                if not self.config:
                    result["err"] = (
                        "--config is not available: this app does not use config files"
                    )
                    return result
                if i + 1 >= len(argv):
                    result["err"] = "flag '--config' requires a value"
                    return result
                result["config_path"] = argv[i + 1]
                exclude_indices.add(i)
                exclude_indices.add(i + 1)
                i += 2
                continue

            # Known global flag with --flag=value form: skip
            if tok.startswith("--") and "=" in tok:
                eq_pos = tok.index("=")
                flag_part = tok[:eq_pos]
                if flag_part in known_flags:
                    i += 1
                    continue
                # Unknown flag-like token: stop
                break

            # Known global flag: skip it (and its value if non-bool)
            if tok in known_flags:
                if known_flags[tok]:
                    i += 2
                else:
                    i += 1
                continue

            # Unknown flag-like token: stop
            break

        if exclude_indices:
            result["cleaned_argv"] = [
                tok for j, tok in enumerate(argv) if j not in exclude_indices
            ]
        else:
            result["cleaned_argv"] = argv

        return result

    def _parse(self, argv: list[str]) -> tuple[Command, dict[str, object] | list[str], dict[str, str]]:
        """Parse argv (without program name) into a resolved Command and kwargs.

        For normal commands, returns (Command, kwargs_dict, sources).
        For passthrough commands, returns (Command, raw_args_list, {}).
        Callers disambiguate by checking cmd.passthrough.

        After parsing, self._last_global_values holds the parsed global flag
        values (used by passthrough command handlers).
        """

        # Step 1: intercept app-level --help/-h, --version/-v
        if not argv or argv == ["--help"] or argv == ["-h"]:
            raise _HelpRequested(target=self)
        if argv == ["--version"] or argv == ["-v"]:
            raise _VersionRequested()

        # Position-aware pre-scan: intercept --dump-schema, --mcp, --config
        # in the pre-command region only (before command name, before --).
        pre_scan = self._pre_scan_reserved_flags(argv)
        if pre_scan.get("dump_schema"):
            raise _DumpSchemaRequested()
        if pre_scan.get("serve_mcp"):
            raise _McpRequested()
        if pre_scan.get("err"):
            raise _ParseError(pre_scan["err"])

        # Load config data once at parse time
        if self.config:
            runtime_override = pre_scan.get("config_path")
            hermetic = self.no_default_config_path and not runtime_override
            self._config_data = self._resolve_config_data(
                runtime_path_override=runtime_override,
                hermetic=hermetic,
            )

        # Step 1.5: parse global flags before command routing
        # Use cleaned argv (--config stripped) for the rest of the pipeline
        cleaned_argv = pre_scan.get("cleaned_argv", argv)
        self._stdin_consumed_by: str | None = None
        global_values, remaining = self._parse_global_flags(cleaned_argv)
        self._last_global_values = global_values

        # Step 2: route to command or group (iterative traversal for arbitrary depth)
        # If global flag parsing stopped at --, strip it before routing
        if remaining and remaining[0] == "--":
            remaining = remaining[1:]

        if not remaining or remaining == ["--help"] or remaining == ["-h"]:
            raise _HelpRequested(target=self)

        cmd, rest, path = self._resolve_command(remaining)

        # Check for command-level --help/-h anywhere in remaining tokens
        # (but not after "--" separator, which makes everything literal)
        if _tokens_contain_help(rest):
            raise _HelpRequested(target=cmd)

        # Step 2.5: validate config fields (exempt config subcommands)
        is_config_subcommand = bool(path) and path[0] == "config"
        if (self.config and self._config_fields
                and not is_config_subcommand):
            err = self._validate_config_fields(cmd, self._config_data)
            if err:
                raise _ParseError(err)

        # Passthrough commands: skip all flag/arg parsing, forward raw args
        if cmd.passthrough is not None:
            return cmd, rest, {}

        # Step 3: parse remaining tokens for the resolved command
        # Pass stdin_consumed_by as a mutable single-element list so
        # _parse_command can update the shared state.
        stdin_state: list[str | None] = [self._stdin_consumed_by]
        try:
            cmd, kwargs, post_global, sources = _parse_command(
                cmd, rest, self._global_flags, config_data=self._config_data,
                stdin_consumed_by=stdin_state,
            )
        except _ParseError as e:
            prefix_parts = [self.name] + path + [cmd.name]
            e.command_prefix = " ".join(prefix_parts)
            raise

        # Step 4: merge global flag values into kwargs
        # Post-command global flags override pre-command ones
        for gf in self._global_flags:
            if gf.name in post_global:
                global_values[gf.name] = post_global[gf.name]
            kwargs[_flag_param_name(gf.name)] = global_values[gf.name]

        return cmd, kwargs, sources

    def _resolve_command(
        self, path_segments: list[str]
    ) -> tuple[Command, list[str], list[str]]:
        """Traverse groups/commands tree to resolve a command from path segments.

        Takes the remaining argv tokens after global flag parsing (group names,
        command name, and command arguments).  Consumes group and command tokens
        from the front, returning the resolved Command, the unconsumed tokens
        (command arguments), and the list of group names traversed.

        Raises _HelpRequested for group-level help and _ParseError for
        deprecated or unknown commands.
        """
        current_groups = self._groups
        current_commands = self._commands
        current_deprecated = self._deprecated
        path: list[str] = []  # tracks group names for error messages and help prefix

        while path_segments:
            token = path_segments[0]

            if token in current_groups:
                group = current_groups[token]
                path.append(token)
                path_segments = path_segments[1:]

                if not path_segments or path_segments[0] in ("--help", "-h"):
                    raise _HelpRequested(target=group)

                # Descend into group
                current_groups = group._groups
                current_commands = group.commands
                current_deprecated = group.deprecated
                continue

            if token in current_commands:
                cmd = current_commands[token]
                rest = path_segments[1:]
                return cmd, rest, path

            if token in current_deprecated:
                dep = current_deprecated[token]
                raise _ParseError(
                    f"command '{token}' is deprecated: {dep.message}"
                )

            # Unknown command -- include path in error message
            if path:
                raise _ParseError(
                    f"unknown command '{token}' in '{' '.join(path)}'",
                    command_prefix=f"{self.name} {' '.join(path)}",
                )
            raise _ParseError(f"unknown command '{token}'")

        # Loop ended without finding a command -- path_segments was exhausted
        # by group traversal. This means the last group had no subcommand.
        # (Already handled by the help check inside the loop, but guard
        # against edge cases.)
        raise _HelpRequested(target=group)  # noqa: F821 -- 'group' always set when loop body ran

    def _parse_global_flags(
        self, argv: list[str]
    ) -> tuple[dict[str, object], list[str]]:
        """Parse global flags from argv, returning (global_values, remaining_tokens).

        Scans tokens from left to right. Global flags are consumed; the first
        non-global-flag token (the command name) and everything after it are
        returned as remaining tokens. A bare ``--`` stops global flag parsing
        and is included in the remaining tokens.
        """
        if not self._global_flags:
            return {}, argv

        # Build lookup tables
        long_lookup: dict[str, Flag] = {}
        short_lookup: dict[str, Flag] = {}
        negation_lookup: dict[str, Flag] = {}

        for f in self._global_flags:
            long_lookup[f"--{f.name}"] = f
            if f.short:
                short_lookup[f"-{f.short}"] = f
            if f.type is bool and f.negatable:
                negation_lookup[f"--no-{f.name}"] = f

        cli_set: dict[str, object] = {}
        remaining: list[str] = []
        i = 0

        def _store_value(f: Flag, value: object) -> None:
            """Store a parsed value, appending to a list for repeatable flags."""
            if f.compound == "dict":
                if f.name not in cli_set:
                    cli_set[f.name] = {}
                # value is a (key, val) tuple from _parse_dict_value
                k, v = value
                if k in cli_set[f.name]:
                    raise _ParseError(
                        f"--{f.name}: duplicate key '{k}'"
                    )
                cli_set[f.name][k] = v
            elif f.repeatable:
                if f.name not in cli_set:
                    cli_set[f.name] = []
                if f.unique and value in cli_set[f.name]:
                    raise _ParseError(
                        f"--{f.name}: duplicate value "
                        f"'{_format_value_for_error(value)}'"
                    )
                cli_set[f.name].append(value)
            else:
                cli_set[f.name] = value

        while i < len(argv):
            tok = argv[i]

            # -- stops global flag parsing; include it in remaining
            if tok == "--":
                remaining = argv[i:]
                break

            # --flag=value form
            if tok.startswith("--") and "=" in tok:
                eq_pos = tok.index("=")
                flag_part = tok[:eq_pos]
                value_part = tok[eq_pos + 1:]

                if flag_part in long_lookup:
                    f = long_lookup[flag_part]
                    if f.type is bool and f.compound != "dict":
                        raise _ParseError(
                            f"flag '{flag_part}' is a boolean flag and does not take a value"
                        )
                    if f.compound == "dict":
                        _store_dict_flag(f, value_part, cli_set)
                    elif f.type is int:
                        try:
                            _store_value(f, _strict_int(value_part))
                        except ValueError as e:
                            raise _ParseError(f"--{f.name}: {e}")
                    elif f.type is float:
                        try:
                            _store_value(f, _strict_float(value_part))
                        except ValueError as e:
                            raise _float_parse_error(f.name, value_part, e)
                    else:
                        resolved, self._stdin_consumed_by = _resolve_at_prefix(
                            f.name, value_part, self._stdin_consumed_by,
                        )
                        _store_value(f, resolved)
                    i += 1
                    continue
                elif flag_part in negation_lookup:
                    raise _ParseError(
                        f"flag '{flag_part}' is a boolean negation and does not take a value"
                    )
                else:
                    # Not a global flag -- this is the command name region
                    remaining = argv[i:]
                    break

            # --no-flag negation
            if tok in negation_lookup:
                f = negation_lookup[tok]
                cli_set[f.name] = False
                i += 1
                continue

            # --flag (long form)
            if tok.startswith("--") and tok in long_lookup:
                f = long_lookup[tok]
                if f.type is bool and f.compound != "dict":
                    cli_set[f.name] = True
                    i += 1
                else:
                    if i + 1 < len(argv):
                        raw = argv[i + 1]
                        if f.compound == "dict":
                            _store_dict_flag(f, raw, cli_set)
                        elif f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError as e:
                                raise _ParseError(f"--{f.name}: {e}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
                        else:
                            resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                f.name, raw, self._stdin_consumed_by,
                            )
                            _store_value(f, resolved)
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
                continue

            # -x (short form)
            if tok.startswith("-") and len(tok) == 2 and tok in short_lookup:
                f = short_lookup[tok]
                if f.type is bool and f.compound != "dict":
                    cli_set[f.name] = True
                    i += 1
                else:
                    if i + 1 < len(argv):
                        raw = argv[i + 1]
                        if f.compound == "dict":
                            _store_dict_flag(f, raw, cli_set)
                        elif f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError as e:
                                raise _ParseError(f"--{f.name}: {e}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
                        else:
                            resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                f.name, raw, self._stdin_consumed_by,
                            )
                            _store_value(f, resolved)
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
                continue

            # Not a global flag -- this is the command name or unknown token
            remaining = argv[i:]
            break
        else:
            # Loop completed without break -- all tokens consumed
            remaining = []

        # Resolve env vars for global flags not set by CLI
        for f in self._global_flags:
            if f.name in cli_set:
                continue
            if f.env is not None:
                env_val = os.environ.get(f.env)
                if env_val is not None:
                    if f.compound == "dict":
                        # Dict flags parse env vars as JSON
                        try:
                            parsed = json.loads(env_val)
                        except json.JSONDecodeError as e:
                            raise _ParseError(
                                f"--{f.name}: invalid JSON in env var "
                                f"'{f.env}': {e}"
                            )
                        if not isinstance(parsed, dict):
                            raise _ParseError(
                                f"--{f.name}: env var '{f.env}' must be a "
                                f"JSON object, got {type(parsed).__name__}"
                            )
                        result = {}
                        for k, v in parsed.items():
                            result[k] = _coerce_dict_json_value(
                                f.name, k, v, f.value_type,
                            )
                        cli_set[f.name] = result
                    elif f.type is bool:
                        try:
                            cli_set[f.name] = _strict_bool(env_val)
                        except ValueError:
                            raise _ParseError(
                                f"invalid boolean value {env_val!r} for env var "
                                f"'{f.env}' (flag '--{f.name}')"
                            )
                    elif f.type is int:
                        if f.repeatable and f.env_separator is not None:
                            parts = _split_escaped(env_val, f.env_separator)
                            coerced_list = []
                            for element in parts:
                                try:
                                    coerced_list.append(_strict_int(element))
                                except ValueError as e:
                                    raise _ParseError(
                                        f"--{f.name}: {e} (from env var '{f.env}')"
                                    )
                            if f.unique:
                                dup = _find_duplicate(coerced_list)
                                if dup is not None:
                                    raise _ParseError(
                                        f"--{f.name}: duplicate value "
                                        f"'{_format_value_for_error(dup)}' "
                                        f"(from env var '{f.env}')"
                                    )
                            cli_set[f.name] = coerced_list
                        else:
                            try:
                                coerced = _strict_int(env_val)
                            except ValueError as e:
                                raise _ParseError(
                                    f"--{f.name}: {e} (from env var '{f.env}')"
                                )
                            cli_set[f.name] = [coerced] if f.repeatable else coerced
                    elif f.type is float:
                        if f.repeatable and f.env_separator is not None:
                            parts = _split_escaped(env_val, f.env_separator)
                            coerced_list = []
                            for element in parts:
                                try:
                                    coerced_list.append(_strict_float(element))
                                except ValueError as e:
                                    raise _float_parse_error(
                                        f.name, element, e, env=f.env,
                                    )
                            if f.unique:
                                dup = _find_duplicate(coerced_list)
                                if dup is not None:
                                    raise _ParseError(
                                        f"--{f.name}: duplicate value "
                                        f"'{_format_value_for_error(dup)}' "
                                        f"(from env var '{f.env}')"
                                    )
                            cli_set[f.name] = coerced_list
                        else:
                            try:
                                coerced = _strict_float(env_val)
                            except ValueError as e:
                                raise _float_parse_error(f.name, env_val, e, env=f.env)
                            cli_set[f.name] = [coerced] if f.repeatable else coerced
                    else:
                        if f.repeatable and f.env_separator is not None:
                            parts = _split_escaped(env_val, f.env_separator)
                            coerced_list = []
                            for element in parts:
                                resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                    f.name, element, self._stdin_consumed_by,
                                )
                                coerced_list.append(resolved)
                            if f.unique:
                                dup = _find_duplicate(coerced_list)
                                if dup is not None:
                                    raise _ParseError(
                                        f"--{f.name}: duplicate value "
                                        f"'{_format_value_for_error(dup)}' "
                                        f"(from env var '{f.env}')"
                                    )
                            cli_set[f.name] = coerced_list
                        else:
                            resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                f.name, env_val, self._stdin_consumed_by,
                            )
                            cli_set[f.name] = [resolved] if f.repeatable else resolved

        # Resolve config values for global flags not set by CLI or env
        if self._config_data:
            for f in self._global_flags:
                if f.name in cli_set:
                    continue
                param = _flag_param_name(f.name)
                if param in self._config_data:
                    try:
                        coerced = _coerce_config_value(self._config_data[param], f)
                    except ValueError as e:
                        raise _ParseError(
                            f"--{f.name}: config value error: {e}"
                        )
                    if f.unique and isinstance(coerced, list):
                        dup = _find_duplicate(coerced)
                        if dup is not None:
                            raise _ParseError(
                                f"--{f.name}: config value error: "
                                f"duplicate value "
                                f"'{_format_value_for_error(dup)}'"
                            )
                    cli_set[f.name] = coerced

        # Apply defaults for global flags not set by CLI or env
        for f in self._global_flags:
            if f.name in cli_set:
                continue
            if f.repeatable:
                cli_set[f.name] = list(f.default) if f.default else []
            elif f.default is not None:
                cli_set[f.name] = f.default
            else:
                if f.type is bool and f.negatable:
                    raise _ParseError(
                        f"global flag '--{f.name}' must be passed as "
                        f"--{f.name} or --no-{f.name}"
                    )
                if f.type is bool and not f.negatable:
                    raise _ParseError(
                        f"global flag '--{f.name}' must be passed as "
                        f"--{f.name}"
                    )
                raise _ParseError(f"global flag '--{f.name}' is required")

        # Validate choices for global flags
        for f in self._global_flags:
            if f.name in cli_set:
                _validate_choices(f.name, cli_set[f.name], f.repeatable, f.choices)

        return cli_set, remaining

    def _find_command_prefix(self, cmd: Command) -> str:
        """Find the group prefix for a command (for help formatting).

        Traverses the group tree recursively to find the full path.
        """
        def _search_groups(groups: dict[str, Group], path: list[str]) -> str | None:
            for group in groups.values():
                if cmd in group.commands.values():
                    return " ".join(path + [group.name]) + " "
                result = _search_groups(group._groups, path + [group.name])
                if result is not None:
                    return result
            return None

        return _search_groups(self._groups, []) or ""

    def run(self) -> None:
        """Run the CLI application, reading from sys.argv."""
        check_err = self._validate_check_registrations()
        if check_err:
            print(f"error: {check_err}", file=sys.stderr)
            sys.exit(1)
        tag_err = self._validate_tag_contracts()
        if tag_err:
            print(f"error: {tag_err}", file=sys.stderr)
            sys.exit(1)
        argv = sys.argv[1:]
        try:
            cmd, data, sources = self._parse(argv)
        except _HelpRequested as e:
            if isinstance(e.target, App):
                print(_format_app_help(self))
            elif isinstance(e.target, Group):
                print(_format_group_help(self, e.target))
            elif isinstance(e.target, Command):
                prefix = self._find_command_prefix(e.target)
                print(_format_command_help(self, e.target, prefix))
            sys.exit(0)
        except _VersionRequested:
            print(_format_version(self))
            sys.exit(0)
        except _DumpSchemaRequested:
            try:
                path = _write_schema(self)
            except RuntimeError as e:
                print(f"error: {e}", file=sys.stderr)
                sys.exit(1)
            print(path)
            sys.exit(0)
        except _McpRequested:
            self.serve_mcp()
            sys.exit(0)
        except _ParseError as e:
            print(f"error: {e}", file=sys.stderr)
            prefix = e.command_prefix or self.name
            print(f"try '{prefix} --help'", file=sys.stderr)
            sys.exit(1)
        else:
            if cmd.passthrough is not None:
                result = cmd.passthrough.handler(cmd.name, data, self._last_global_values)
            elif cmd.needs_context:
                ctx = Context(stdout=sys.stdout, stderr=sys.stderr, sources=sources)
                result = cmd.handler(ctx, **data)
            else:
                result = cmd.handler(**data)
            if isinstance(result, int):
                sys.exit(result)
            elif result is None:
                sys.exit(0)
            else:
                print(json.dumps(result, default=str))
                sys.exit(0)

    def test(self, argv: list[str]) -> Result:
        """Run the CLI with given argv, capturing output and exit code."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0
        result_data = None

        check_err = self._validate_check_registrations()
        if check_err:
            stderr_buf.write(f"error: {check_err}\n")
            return Result(
                stdout=stdout_buf.getvalue(),
                stderr=stderr_buf.getvalue(),
                exit_code=1,
            )

        tag_err = self._validate_tag_contracts()
        if tag_err:
            stderr_buf.write(f"error: {tag_err}\n")
            return Result(
                stdout=stdout_buf.getvalue(),
                stderr=stderr_buf.getvalue(),
                exit_code=1,
            )

        try:
            cmd, data, sources = self._parse(argv)
        except _HelpRequested as e:
            if isinstance(e.target, App):
                stdout_buf.write(_format_app_help(self) + "\n")
            elif isinstance(e.target, Group):
                stdout_buf.write(_format_group_help(self, e.target) + "\n")
            elif isinstance(e.target, Command):
                prefix = self._find_command_prefix(e.target)
                stdout_buf.write(_format_command_help(self, e.target, prefix) + "\n")
        except _VersionRequested:
            stdout_buf.write(_format_version(self) + "\n")
        except _DumpSchemaRequested:
            try:
                path = _write_schema(self)
            except RuntimeError as e:
                stderr_buf.write(f"error: {e}\n")
                exit_code = 1
            else:
                stdout_buf.write(path + "\n")
        except _McpRequested:
            # In test mode, MCP requires real stdin/stdout; just acknowledge
            stderr_buf.write("error: --mcp requires interactive stdin/stdout\n")
            exit_code = 1
        except _ParseError as e:
            stderr_buf.write(f"error: {e}\n")
            prefix = e.command_prefix or self.name
            stderr_buf.write(f"try '{prefix} --help'\n")
            exit_code = 1
        else:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                try:
                    if cmd.passthrough is not None:
                        handler_return = cmd.passthrough.handler(
                            cmd.name, data, self._last_global_values,
                        )
                    elif cmd.needs_context:
                        ctx = Context(stdout=stdout_buf, stderr=stderr_buf, sources=sources)
                        handler_return = cmd.handler(ctx, **data)
                    else:
                        handler_return = cmd.handler(**data)
                    if isinstance(handler_return, int):
                        exit_code = handler_return
                    elif handler_return is not None:
                        result_data = handler_return
                    # Capture emit data from Context-aware handlers
                    if cmd.needs_context and not isinstance(ctx._emit_data, _MissingSentinel):
                        result_data = ctx._emit_data
                except SystemExit as e:
                    exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)

        return Result(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            exit_code=exit_code,
            data=result_data,
        )

    def _invoke(
        self, command_path: str, kwargs: dict[str, object]
    ) -> object:
        """Invoke a command programmatically with pre-typed kwargs.

        This is the internal pipeline for programmatic invocation. It bypasses
        CLI parsing, env var resolution, config file loading, and stdin
        handling. The caller provides fully-typed values directly.

        Args:
            command_path: dot-separated path to the command
                (e.g. "deploy" or "config.set").
            kwargs: handler keyword arguments. Flag names use underscores
                (e.g. dry_run). Positional args use their declared name.
                For passthrough commands, pass a single key "_args" with
                a list of raw string arguments.

        Returns:
            The handler's return value (structured data, int, or None).

        Raises:
            _ParseError: if validation fails (missing required flags,
                mutex violations, dependency errors, etc.).
            _HelpRequested: if the command path resolves to a group
                with no subcommand.
        """
        path_segments = command_path.split(".")
        cmd, _rest, _path = self._resolve_command(path_segments)

        # Passthrough commands: forward raw args to the passthrough handler
        if cmd.passthrough is not None:
            raw_args = kwargs.get("_args", [])

            # Build set of known global flag param names
            global_param_names: set[str] = set()
            for gf in self._global_flags:
                global_param_names.add(_flag_param_name(gf.name))

            # Validate that all kwargs keys are either "_args" or known global flags
            for key in kwargs:
                if key == "_args":
                    continue
                if key not in global_param_names:
                    raise _ParseError(
                        f"unknown parameter '{key}' for passthrough command '{cmd.name}'"
                    )

            # Build global values from kwargs, applying defaults for missing flags
            global_values: dict[str, object] = {}
            for gf in self._global_flags:
                param_name = _flag_param_name(gf.name)
                if param_name in kwargs:
                    global_values[param_name] = kwargs[param_name]
                elif gf.default is not None:
                    global_values[param_name] = gf.default
                else:
                    raise _ParseError(
                        f"global flag '--{gf.name}' is required"
                    )

            return cmd.passthrough.handler(
                cmd.name, raw_args, global_values,
            )

        # Build reverse mapping: param_name (underscore) -> flag.name (dashes)
        param_to_flag: dict[str, str] = {}
        for f in cmd.flags:
            param_to_flag[_flag_param_name(f.name)] = f.name

        # Also map global flags
        global_flag_names: set[str] = set()
        for gf in self._global_flags:
            param_to_flag[_flag_param_name(gf.name)] = gf.name
            global_flag_names.add(gf.name)

        # Collect arg names for this command
        arg_names: set[str] = {a.name for a in cmd.args}

        # Populate sourced store from kwargs. Provided kwargs are marked
        # _Source.CLI; absent flags will get _Source.DEFAULT when
        # _validate_and_build_kwargs applies defaults.
        store = _SourcedStore()
        positionals: list[str] = []

        for key, value in kwargs.items():
            if key in param_to_flag:
                # It's a flag -- store under flag.name (with dashes)
                flag_name = param_to_flag[key]
                store.set(flag_name, value, _Source.CLI)
            elif key in arg_names:
                # It's a positional arg -- collect into positionals in order
                # (handled below after iterating all kwargs)
                pass
            else:
                raise _ParseError(
                    f"unknown parameter '{key}' for command '{cmd.name}'"
                )

        # Build positionals list in declared arg order from kwargs
        for a in cmd.args:
            if a.name in kwargs:
                val = kwargs[a.name]
                if a.variadic:
                    # Variadic args expect a list
                    if isinstance(val, list):
                        positionals.extend(str(v) for v in val)
                    else:
                        positionals.append(str(val))
                else:
                    positionals.append(str(val))

        # Validate and build final kwargs via the shared validation pipeline
        _cmd, final_kwargs, _global_cli_set, invoke_sources = _validate_and_build_kwargs(
            cmd, store, positionals, global_flag_names,
        )

        # Merge global flag values into final kwargs
        for gf in self._global_flags:
            if gf.name in _global_cli_set:
                final_kwargs[_flag_param_name(gf.name)] = _global_cli_set[gf.name]
            elif _flag_param_name(gf.name) not in final_kwargs:
                # Global flag not provided -- use its default
                if gf.default is not None:
                    final_kwargs[_flag_param_name(gf.name)] = gf.default

        if cmd.needs_context:
            ctx = Context(stdout=sys.stdout, stderr=sys.stderr, sources=invoke_sources)
            result = cmd.handler(ctx, **final_kwargs)
            if not isinstance(ctx._emit_data, _MissingSentinel):
                return ctx._emit_data
            return result
        return cmd.handler(**final_kwargs)

    def call(self, command_path: str, **kwargs: object) -> object:
        """Invoke a command programmatically and return its result.

        Unlike _invoke(), this is the public API. It converts internal
        _ParseError exceptions to InvokeError so callers don't need to
        depend on private types.

        Args:
            command_path: dot-separated path to the command
                (e.g. "deploy" or "config.set").
            **kwargs: handler keyword arguments. Flag names use underscores
                (e.g. dry_run). Positional args use their declared name.
                For passthrough commands, pass _args=[...] for raw arguments.

        Returns:
            The handler's return value (structured data, int, or None).

        Raises:
            InvokeError: if validation fails (unknown command, missing
                required flags, mutex violations, dependency errors, etc.).
        """
        try:
            return self._invoke(command_path, kwargs)
        except _ParseError as e:
            raise InvokeError(str(e)) from e
        except _HelpRequested:
            raise InvokeError(
                f"'{command_path}' is a group, not a command"
            )

    async def acall(self, command_path: str, **kwargs: object) -> object:
        """Async version of call(). Runs the handler in a thread.

        Args:
            command_path: dot-separated path to the command.
            **kwargs: handler keyword arguments (same as call()).

        Returns:
            The handler's return value (structured data, int, or None).

        Raises:
            InvokeError: if validation fails.
        """
        import asyncio
        return await asyncio.to_thread(self.call, command_path, **kwargs)

    def json_schema(self, command_path: str) -> dict:
        """Produce a JSON Schema parameters object for a command's flags and args.

        Args:
            command_path: dot-separated path to the command (e.g. "deploy"
                or "config.show").

        Returns:
            A JSON Schema object with "type": "object", "properties",
            "required", and "additionalProperties": false.

        Raises:
            InvokeError: if the command path is invalid or resolves to a group.
        """
        path_segments = command_path.split(".")
        try:
            cmd, _rest, _path = self._resolve_command(path_segments)
        except _ParseError as e:
            raise InvokeError(str(e)) from e
        except _HelpRequested:
            raise InvokeError(
                f"'{command_path}' is a group, not a command"
            )
        return _build_json_schema(cmd)

    def as_tools(self) -> list[Tool]:
        """Export non-hidden, non-interactive leaf commands as Tool descriptors.

        Returns a list of Tool objects, one per eligible command plus a
        router tool. Each tool's execute function wraps acall().
        """
        tools: list[Tool] = []
        command_paths: list[str] = []

        # Collect leaf commands from top-level
        for name, cmd in self._commands.items():
            if cmd.hidden or cmd.interactive:
                continue
            path = name
            tools.append(self._make_tool(path, cmd))
            command_paths.append(path)

        # Collect leaf commands from groups (recursive)
        for group_name, group in self._groups.items():
            self._collect_tools_from_group(
                group, [group_name], tools, command_paths,
            )

        # Build the router tool
        tools.append(self._make_router_tool(command_paths))

        return tools

    def _collect_tools_from_group(
        self,
        group: Group,
        path: list[str],
        tools: list[Tool],
        command_paths: list[str],
    ) -> None:
        """Recursively collect non-hidden, non-interactive commands from a group."""
        if group.hidden:
            return
        for cmd_name, cmd in group.commands.items():
            if cmd.hidden or cmd.interactive:
                continue
            dotted = ".".join(path + [cmd_name])
            tools.append(self._make_tool(dotted, cmd))
            command_paths.append(dotted)
        for sub_name, sub_group in group._groups.items():
            self._collect_tools_from_group(
                sub_group, path + [sub_name], tools, command_paths,
            )

    def _make_tool(self, command_path: str, cmd: Command) -> Tool:
        """Build a Tool for a single command."""
        app_ref = self

        async def execute(**kwargs: object) -> object:
            return await app_ref.acall(command_path, **kwargs)

        return Tool(
            name=command_path,
            description=cmd.help,
            parameters=_build_json_schema(cmd),
            execute=execute,
        )

    def _make_router_tool(self, command_paths: list[str]) -> Tool:
        """Build the router tool that dispatches to per-command tools."""
        app_ref = self

        async def execute(command: str | None = None, **kwargs: object) -> object:
            if command is None:
                return command_paths[:]
            return await app_ref.acall(command, **kwargs)

        parameters: dict = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Command to execute (dot-separated path)"
                    ),
                    "enum": command_paths[:],
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }
        return Tool(
            name=self.name,
            description=f"Route to {self.name} commands",
            parameters=parameters,
            execute=execute,
        )

    def serve_mcp(
        self,
        *,
        input: io.TextIOBase | None = None,
        output: io.TextIOBase | None = None,
    ) -> None:
        """Run a JSON-RPC 2.0 MCP server on stdin/stdout.

        Reads one JSON object per line from input (default: sys.stdin),
        writes one JSON object per line to output (default: sys.stdout).
        Handles initialize, tools/list, tools/call, and notifications.

        The server runs until input is exhausted (EOF).
        """
        _run_mcp_server(self, input=input, output=output)


# JSON Schema type mapping for tool export
_JSON_SCHEMA_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _build_json_schema(cmd: Command) -> dict:
    """Build a JSON Schema parameters object for a command's flags and args."""
    properties: dict = {}
    required: list[str] = []

    for f in cmd.flags:
        param_name = _flag_param_name(f.name)
        prop: dict = {}

        if f.compound == "list":
            prop["type"] = "array"
            prop["items"] = {"type": _JSON_SCHEMA_TYPES[f.item_type]}
        elif f.compound == "dict":
            prop["type"] = "object"
            prop["additionalProperties"] = {
                "type": _JSON_SCHEMA_TYPES[f.value_type],
            }
        else:
            prop["type"] = _JSON_SCHEMA_TYPES[f.type]

        if f.choices is not None:
            prop["enum"] = f.choices[:]

        prop["description"] = f.help

        properties[param_name] = prop

        # A flag is required if it has no default (None for scalar).
        # Repeatable/dict flags always have a default (empty list/dict).
        is_required = (
            f.compound == "scalar"
            and f.default is None
        )
        if is_required:
            required.append(param_name)

    for a in cmd.args:
        prop = {}

        if a.compound == "list":
            prop["type"] = "array"
            prop["items"] = {"type": _JSON_SCHEMA_TYPES[a.item_type]}
        else:
            prop["type"] = _JSON_SCHEMA_TYPES[a.type]

        if a.choices is not None:
            prop["enum"] = a.choices[:]

        prop["description"] = a.help

        properties[a.name] = prop

        if a.required:
            required.append(a.name)

    schema: dict = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return schema


def _tokens_contain_help(tokens: list[str]) -> bool:
    """Check if --help or -h appears in tokens before any -- separator."""
    for tok in tokens:
        if tok == "--":
            return False
        if tok == "--help" or tok == "-h":
            return True
    return False


def _validate_choices(
    name: str,
    val: object,
    repeatable: bool,
    choices: list | None,
    *,
    is_arg: bool = False,
) -> None:
    """Validate a resolved flag or arg value against its choices list.

    Raises _ParseError on an invalid value. is_arg selects the message prefix
    ("argument 'name':" instead of "--name:"); the two f-strings are kept as
    full literals so conformance/check_error_parity.py can extract them.
    A None value is exempt from validation: None only arises when the flag or
    arg was not passed (an unset mutex flag, or default=None on an arg) -- a
    CLI-supplied value is never None.
    """
    if choices is None or val is None:
        return
    vals = val if repeatable else [val]
    for v in vals:
        if v not in choices:
            choices_str = ", ".join(str(c) for c in choices)
            if is_arg:
                raise _ParseError(
                    f"argument '{name}': invalid value '{v}', "
                    f"must be one of: {choices_str}"
                )
            raise _ParseError(
                f"--{name}: invalid value '{v}', must be one of: {choices_str}"
            )


def _validate_and_build_kwargs(
    cmd: Command,
    store: _SourcedStore,
    positionals: list[str],
    global_flag_names: set[str],
) -> tuple[Command, dict[str, object], dict[str, object], dict[str, str]]:
    """Validate parsed values and build the kwargs dict for the command handler.

    This is the second half of command parsing: mutex enforcement, implies
    resolution, dependency checks, defaults, choices validation, custom
    validation, positional arg resolution, and kwargs building. It operates
    on sourced values in the store and doesn't care how they were produced.

    Returns (cmd, kwargs, global_cli_set, sources) where sources maps
    flag param names to source labels (cli/env/config/default/implied).
    """
    # Step 4.5: enforce mutex group constraints (before defaults are applied).
    # Only cli/env/config sources count as "present" for mutex evaluation.
    # Default and implied sources do NOT trigger mutex violations.
    for mg in cmd.mutex:
        set_flags = [f for f in mg.flags if store.is_present_for_mutex(f.name)]
        if len(set_flags) > 1:
            names = " and ".join(f"--{f.name}" for f in set_flags)
            raise _ParseError(f"{names} are mutually exclusive")
        if len(set_flags) == 0:
            names = ", ".join(f"--{f.name}" for f in mg.flags)
            raise _ParseError(f"one of {names} is required")

    # Step 4.55: resolve Implies dependencies (before dependency checks, so
    # implied values participate in downstream CoRequired/Requires validation).
    # Implied values are stored with _Source.IMPLIED.
    for dep in cmd.dependencies:
        if isinstance(dep, Implies):
            if store.is_present_for_deps(dep.flag):
                if store.has(dep.implies):
                    if store[dep.implies] != dep.value:
                        neg = "no-" if not dep.value else ""
                        explicit_neg = "" if not dep.value else "no-"
                        raise _ParseError(
                            f"flag '--{dep.flag}' implies '--{neg}{dep.implies}', "
                            f"but '--{explicit_neg}{dep.implies}' was explicitly provided"
                        )
                else:
                    store.set(dep.implies, dep.value, _Source.IMPLIED)

    # Step 4.6: enforce flag dependencies (before defaults).
    # is_present_for_deps: cli, env, config, implied count. Default does NOT.
    for dep in cmd.dependencies:
        if isinstance(dep, CoRequired):
            present = [f for f in dep.flags if store.is_present_for_deps(f)]
            if 0 < len(present) < len(dep.flags):
                names = ", ".join(f"--{f}" for f in dep.flags)
                raise _ParseError(f"flags {names} must be used together")
        elif isinstance(dep, Requires):
            if store.is_present_for_deps(dep.flag) and not store.is_present_for_deps(dep.depends_on):
                raise _ParseError(
                    f"flag '--{dep.flag}' requires '--{dep.depends_on}'"
                )

    # Build set of flag names belonging to mutex groups (used in step 5
    # to suppress "required" errors -- mutex groups handle their own
    # required semantics)
    mutex_flag_names: set[str] = set()
    for mg in cmd.mutex:
        for mf in mg.flags:
            mutex_flag_names.add(mf.name)

    # Step 5: apply defaults (SourceDefault)
    for f in cmd.flags:
        if store.has(f.name):
            continue
        if f.compound == "dict":
            # Dict flags default to {} (never required)
            store.set(f.name, dict(f.default) if f.default else {}, _Source.DEFAULT)
        elif f.repeatable:
            # Repeatable flags default to [] (never required)
            store.set(f.name, list(f.default) if f.default else [], _Source.DEFAULT)
        elif f.default is not None:
            store.set(f.name, f.default, _Source.DEFAULT)
        elif f.name in mutex_flag_names:
            # Mutex group flags with no default get None instead of being
            # required -- the mutex group itself enforces required semantics
            store.set(f.name, None, _Source.DEFAULT)
        else:
            # Flag with no default and no value: required
            if f.type is bool and f.negatable:
                raise _ParseError(
                    f"flag '--{f.name}' must be passed as "
                    f"--{f.name} or --no-{f.name}"
                )
            if f.type is bool and not f.negatable:
                raise _ParseError(
                    f"flag '--{f.name}' must be passed as --{f.name}"
                )
            raise _ParseError(f"flag '--{f.name}' is required")

    # Step 5.5: validate choices
    for f in cmd.flags:
        if store.has(f.name):
            _validate_choices(f.name, store[f.name], f.repeatable, f.choices)

    # Step 5.6: custom validation
    for f in cmd.flags:
        if f.validate is not None and store.has(f.name):
            if f.repeatable:
                for val in store[f.name]:
                    try:
                        f.validate(val)
                    except ValueError as e:
                        raise _ParseError(f"--{f.name}: {e}")
            elif store[f.name] is not None:
                # None means the flag was not passed (an unset mutex flag) --
                # there is no value to validate.
                try:
                    f.validate(store[f.name])
                except ValueError as e:
                    raise _ParseError(f"--{f.name}: {e}")

    # Step 6: resolve positional args
    arg_values: dict[str, object] = {}
    has_variadic = cmd.args and cmd.args[-1].variadic
    fixed_args = cmd.args[:-1] if has_variadic else cmd.args
    for idx, a in enumerate(fixed_args):
        if idx < len(positionals):
            arg_values[a.name] = _coerce_arg_value(a, positionals[idx])
        elif a.required:
            raise _ParseError(f"missing required argument '{a.name}'")
        elif not isinstance(a.default, _MissingSentinel):
            arg_values[a.name] = a.default
    if has_variadic:
        va = cmd.args[-1]
        remaining_positionals = positionals[len(fixed_args):]
        if va.required and len(remaining_positionals) == 0:
            raise _ParseError(f"missing required argument '{va.name}'")
        arg_values[va.name] = [
            _coerce_arg_value(va, p) for p in remaining_positionals
        ]
    elif len(positionals) > len(cmd.args):
        raise _ParseError(f"unexpected argument '{positionals[len(cmd.args)]}'")

    # Step 6.5: validate arg choices
    for a in cmd.args:
        if a.name in arg_values:
            _validate_choices(
                a.name, arg_values[a.name], a.variadic, a.choices, is_arg=True,
            )

    # Step 7: build kwargs dict (command flags only)
    kwargs: dict[str, object] = {}
    for f in cmd.flags:
        kwargs[_flag_param_name(f.name)] = store[f.name]
    for a in cmd.args:
        if a.name in arg_values:
            kwargs[a.name] = arg_values[a.name]

    # Separate out global flag values parsed from post-command tokens
    global_cli_set: dict[str, object] = {}
    for name in global_flag_names:
        if store.has(name):
            global_cli_set[name] = store[name]

    # Build source map: param-name -> source label (for Context.source())
    sources: dict[str, str] = {}
    raw_sources = store.source_map()
    for f in cmd.flags:
        if f.name in raw_sources:
            sources[_flag_param_name(f.name)] = raw_sources[f.name]

    return cmd, kwargs, global_cli_set, sources


def _parse_command(
    cmd: Command,
    tokens: list[str],
    global_flags: list[Flag] | None = None,
    config_data: dict | None = None,
    stdin_consumed_by: list[str | None] | None = None,
) -> tuple[Command, dict[str, object], dict[str, object], dict[str, str]]:
    """Parse tokens against a resolved command's flags and args.

    Returns (cmd, kwargs, global_cli_set, sources) where global_cli_set contains
    any global flag values parsed from tokens appearing after the command name.

    stdin_consumed_by is a mutable single-element list tracking which flag
    has already consumed stdin via @-. Updated in-place.
    """
    if stdin_consumed_by is None:
        stdin_consumed_by = [None]

    # Build flag lookup dicts
    long_lookup: dict[str, Flag] = {}  # --flag-name -> Flag
    short_lookup: dict[str, Flag] = {}  # -x -> Flag
    negation_lookup: dict[str, Flag] = {}  # --no-flag-name -> Flag

    for f in cmd.flags:
        long_lookup[f"--{f.name}"] = f
        if f.short:
            short_lookup[f"-{f.short}"] = f
        if f.type is bool and f.negatable:
            negation_lookup[f"--no-{f.name}"] = f

    # Also include global flags in the lookup tables so they are recognized
    # when placed after the command name
    global_flag_names: set[str] = set()
    if global_flags:
        for f in global_flags:
            long_lookup[f"--{f.name}"] = f
            if f.short:
                short_lookup[f"-{f.short}"] = f
            if f.type is bool and f.negatable:
                negation_lookup[f"--no-{f.name}"] = f
            global_flag_names.add(f.name)

    # Track which flags were set by CLI args
    cli_set: dict[str, object] = {}  # flag.name -> value
    positionals: list[str] = []

    def _store_value(f: Flag, value: object) -> None:
        """Store a parsed value, appending to a list for repeatable flags."""
        if f.compound == "dict":
            if f.name not in cli_set:
                cli_set[f.name] = {}
            # value is a (key, val) tuple from _parse_dict_value
            k, v = value
            if k in cli_set[f.name]:
                raise _ParseError(
                    f"--{f.name}: duplicate key '{k}'"
                )
            cli_set[f.name][k] = v
        elif f.repeatable:
            if f.name not in cli_set:
                cli_set[f.name] = []
            if f.unique and value in cli_set[f.name]:
                raise _ParseError(
                    f"--{f.name}: duplicate value "
                    f"'{_format_value_for_error(value)}'"
                )
            cli_set[f.name].append(value)
        else:
            cli_set[f.name] = value

    i = 0
    stop_flags = False  # set when -- is encountered

    while i < len(tokens):
        tok = tokens[i]

        if stop_flags or not tok.startswith("-") or tok == "-":
            positionals.append(tok)
            i += 1
            continue

        if tok == "--":
            stop_flags = True
            i += 1
            continue

        # --flag=value form
        if tok.startswith("--") and "=" in tok:
            eq_pos = tok.index("=")
            flag_part = tok[:eq_pos]
            value_part = tok[eq_pos + 1 :]

            if flag_part in long_lookup:
                f = long_lookup[flag_part]
                if f.type is bool and f.compound != "dict":
                    raise _ParseError(
                        f"flag '{flag_part}' is a boolean flag and does not take a value"
                    )
                if f.compound == "dict":
                    _store_dict_flag(f, value_part, cli_set)
                elif f.type is int:
                    try:
                        _store_value(f, _strict_int(value_part))
                    except ValueError as e:
                        raise _ParseError(f"--{f.name}: {e}")
                elif f.type is float:
                    try:
                        _store_value(f, _strict_float(value_part))
                    except ValueError as e:
                        raise _float_parse_error(f.name, value_part, e)
                else:
                    resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                        f.name, value_part, stdin_consumed_by[0],
                    )
                    _store_value(f, resolved)
            elif flag_part in negation_lookup:
                raise _ParseError(
                    f"flag '{flag_part}' is a boolean negation and does not take a value"
                )
            else:
                raise _ParseError(f"unknown flag '{flag_part}'")
            i += 1
            continue

        # --no-flag negation
        if tok in negation_lookup:
            f = negation_lookup[tok]
            cli_set[f.name] = False
            i += 1
            continue

        # --flag (long form without =)
        if tok.startswith("--"):
            if tok in long_lookup:
                f = long_lookup[tok]
                if f.type is bool and f.compound != "dict":
                    cli_set[f.name] = True
                    i += 1
                else:
                    # str/int/float/dict flag: consume next token as value
                    if i + 1 < len(tokens):
                        raw = tokens[i + 1]
                        if f.compound == "dict":
                            _store_dict_flag(f, raw, cli_set)
                        elif f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError as e:
                                raise _ParseError(f"--{f.name}: {e}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
                        else:
                            resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                                f.name, raw, stdin_consumed_by[0],
                            )
                            _store_value(f, resolved)
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
            else:
                raise _ParseError(f"unknown flag '{tok}'")
            continue

        # -x (short form)
        if tok.startswith("-") and len(tok) == 2 and tok in short_lookup:
            f = short_lookup[tok]
            if f.type is bool and f.compound != "dict":
                cli_set[f.name] = True
                i += 1
            else:
                # str/int/float/dict flag: consume next token as value
                if i + 1 < len(tokens):
                    raw = tokens[i + 1]
                    if f.compound == "dict":
                        _store_dict_flag(f, raw, cli_set)
                    elif f.type is int:
                        try:
                            _store_value(f, _strict_int(raw))
                        except ValueError as e:
                            raise _ParseError(f"--{f.name}: {e}")
                    elif f.type is float:
                        try:
                            _store_value(f, _strict_float(raw))
                        except ValueError as e:
                            raise _float_parse_error(f.name, raw, e)
                    else:
                        resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                            f.name, raw, stdin_consumed_by[0],
                        )
                        _store_value(f, resolved)
                    i += 2
                else:
                    raise _ParseError(f"flag '{tok}' requires a value")
            continue

        # Token starts with "-" but doesn't match any known flag;
        # treat as a positional arg (e.g. negative numbers like -7, -3.14)
        positionals.append(tok)
        i += 1

    # Step 4: resolve env vars for flags not set by CLI
    for f in cmd.flags:
        if f.name in cli_set:
            continue
        if f.env is not None:
            env_val = os.environ.get(f.env)
            if env_val is not None:
                if f.compound == "dict":
                    # Dict flags parse env vars as JSON
                    try:
                        parsed = json.loads(env_val)
                    except json.JSONDecodeError as e:
                        raise _ParseError(
                            f"--{f.name}: invalid JSON in env var "
                            f"'{f.env}': {e}"
                        )
                    if not isinstance(parsed, dict):
                        raise _ParseError(
                            f"--{f.name}: env var '{f.env}' must be a JSON "
                            f"object, got {type(parsed).__name__}"
                        )
                    result = {}
                    for k, v in parsed.items():
                        result[k] = _coerce_dict_json_value(
                            f.name, k, v, f.value_type,
                        )
                    cli_set[f.name] = result
                elif f.type is bool:
                    try:
                        cli_set[f.name] = _strict_bool(env_val)
                    except ValueError:
                        raise _ParseError(
                            f"invalid boolean value {env_val!r} for env var "
                            f"'{f.env}' (flag '--{f.name}')"
                        )
                elif f.type is int:
                    if f.repeatable and f.env_separator is not None:
                        parts = _split_escaped(env_val, f.env_separator)
                        coerced_list = []
                        for element in parts:
                            try:
                                coerced_list.append(_strict_int(element))
                            except ValueError as e:
                                raise _ParseError(
                                    f"--{f.name}: {e} (from env var '{f.env}')"
                                )
                        if f.unique:
                            dup = _find_duplicate(coerced_list)
                            if dup is not None:
                                raise _ParseError(
                                    f"--{f.name}: duplicate value "
                                    f"'{_format_value_for_error(dup)}' "
                                    f"(from env var '{f.env}')"
                                )
                        cli_set[f.name] = coerced_list
                    else:
                        try:
                            coerced = _strict_int(env_val)
                        except ValueError as e:
                            raise _ParseError(
                                f"--{f.name}: {e} (from env var '{f.env}')"
                            )
                        cli_set[f.name] = [coerced] if f.repeatable else coerced
                elif f.type is float:
                    if f.repeatable and f.env_separator is not None:
                        parts = _split_escaped(env_val, f.env_separator)
                        coerced_list = []
                        for element in parts:
                            try:
                                coerced_list.append(_strict_float(element))
                            except ValueError as e:
                                raise _float_parse_error(
                                    f.name, element, e, env=f.env,
                                )
                        if f.unique:
                            dup = _find_duplicate(coerced_list)
                            if dup is not None:
                                raise _ParseError(
                                    f"--{f.name}: duplicate value "
                                    f"'{_format_value_for_error(dup)}' "
                                    f"(from env var '{f.env}')"
                                )
                        cli_set[f.name] = coerced_list
                    else:
                        try:
                            coerced = _strict_float(env_val)
                        except ValueError as e:
                            raise _float_parse_error(f.name, env_val, e, env=f.env)
                        cli_set[f.name] = [coerced] if f.repeatable else coerced
                else:
                    if f.repeatable and f.env_separator is not None:
                        parts = _split_escaped(env_val, f.env_separator)
                        coerced_list = []
                        for element in parts:
                            resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                                f.name, element, stdin_consumed_by[0],
                            )
                            coerced_list.append(resolved)
                        if f.unique:
                            dup = _find_duplicate(coerced_list)
                            if dup is not None:
                                raise _ParseError(
                                    f"--{f.name}: duplicate value "
                                    f"'{_format_value_for_error(dup)}' "
                                    f"(from env var '{f.env}')"
                                )
                        cli_set[f.name] = coerced_list
                    else:
                        resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                            f.name, env_val, stdin_consumed_by[0],
                        )
                        cli_set[f.name] = [resolved] if f.repeatable else resolved

    # Step 4.2: resolve config values for flags not set by CLI or env
    if config_data:
        for f in cmd.flags:
            if f.name in cli_set:
                continue
            param = _flag_param_name(f.name)
            if param in config_data:
                try:
                    coerced = _coerce_config_value(config_data[param], f)
                except ValueError as e:
                    raise _ParseError(
                        f"--{f.name}: config value error: {e}"
                    )
                if f.unique and isinstance(coerced, list):
                    dup = _find_duplicate(coerced)
                    if dup is not None:
                        raise _ParseError(
                            f"--{f.name}: config value error: "
                            f"duplicate value "
                            f"'{_format_value_for_error(dup)}'"
                        )
                cli_set[f.name] = coerced

    # Wrap cli_set into a _SourcedStore. Everything parsed above is marked
    # _Source.CLI -- env and config sources will get proper Source values
    # in Phase 2a; for now they are temporarily _Source.CLI.
    store = _SourcedStore.from_dict(cli_set, _Source.CLI)

    return _validate_and_build_kwargs(cmd, store, positionals, global_flag_names)


def _flag_param_name(flag_name: str) -> str:
    """Convert a flag name like '--dry-run' to a Python parameter name 'dry_run'.

    If the result is a Python keyword (e.g. 'global', 'class'), appends '_'
    per PEP 8 convention (e.g. 'global_', 'class_').
    """
    name = flag_name.lstrip("-").replace("-", "_")
    if keyword.iskeyword(name):
        name += "_"
    return name


def _build_and_validate_command(
    name: str,
    *,
    help: str,
    handler: Callable,
    args: list[Arg] | None,
    flag_sets: list[FlagSet] | None,
    mutex: list[MutexGroup] | None,
    dependencies: list[CoRequired | Requires | Implies] | None = None,
    env_prefix: str | None,
    global_flags: list[Flag] | None = None,
    passthrough: Passthrough | None = None,
    extra_flags: list[Flag] | None = None,
    tags: set[str] | None = None,
    inherited_tags: frozenset[str] | None = None,
    hidden: bool = False,
    interactive: bool = False,
    config_fields: list[str] | None = None,
    config_fields_ref: dict[str, ConfigField] | None = None,
) -> Command:
    """Build a Command from a decorated handler, validate everything."""
    if not help or not help.strip():
        raise ValueError(f'command "{name}": missing help text')

    effective_tags = (inherited_tags or frozenset()) | frozenset(tags or set())

    # Validate config_fields bindings (before passthrough check so both paths get it)
    resolved_config_fields: tuple[str, ...] = ()
    if config_fields:
        if config_fields_ref is None:
            config_fields_ref = {}
        for cf_name in config_fields:
            if cf_name not in config_fields_ref:
                raise ValueError(
                    f'command "{name}": config_fields references unknown '
                    f'config field "{cf_name}"'
                )
        resolved_config_fields = tuple(config_fields)

    # Passthrough commands must not have flags, args, flag sets, or mutex groups
    if passthrough is not None:
        decorator_flags = list(getattr(handler, "_strictcli_flags", []))
        decorator_args = list(getattr(handler, "_strictcli_args", []))
        has_flags = bool(decorator_flags)
        has_args = bool(args) or bool(decorator_args)
        has_flag_sets = bool(flag_sets)
        has_mutex = bool(mutex)
        if has_flags or has_args or has_flag_sets or has_mutex:
            parts = []
            if has_flags:
                parts.append("flags")
            if has_args:
                parts.append("args")
            if has_flag_sets:
                parts.append("flag sets")
            if has_mutex:
                parts.append("mutex groups")
            raise ValueError(
                f'command "{name}": passthrough commands cannot have '
                + ", ".join(parts)
            )
        return Command(
            name=name,
            help=help,
            handler=None,
            passthrough=passthrough,
            tags=effective_tags,
            hidden=hidden,
            interactive=interactive,
            config_fields=resolved_config_fields,
        )

    # Collect flags attached by @strictcli.flag decorators
    # Reverse because Python decorators execute bottom-to-top, so the list
    # is in reverse declaration order.
    decorator_flags: list[Flag] = list(reversed(getattr(handler, "_strictcli_flags", [])))
    # Collect args attached by @strictcli.arg decorators
    decorator_args: list[Arg] = list(getattr(handler, "_strictcli_args", []))

    # Merge explicit args parameter
    all_args = list(args) if args else []
    all_args.extend(decorator_args)

    # Merge flag sets into flags
    resolved_flag_sets = list(flag_sets) if flag_sets else []
    flag_set_flags: list[Flag] = []
    for flag_set in resolved_flag_sets:
        flag_set_flags.extend(flag_set.flags)

    # Resolve mutex groups and merge their flags
    resolved_mutex = list(mutex) if mutex else []
    mutex_flags: list[Flag] = []
    for mg in resolved_mutex:
        # Validate: mutex groups must have at least 2 flags
        if len(mg.flags) < 2:
            raise ValueError(
                f'command "{name}": mutex group must have at least 2 flags, '
                f"got {len(mg.flags)}"
            )
        mutex_flags.extend(mg.flags)

    # Validate: mutex flags must not overlap between groups
    mutex_flag_names: set[str] = set()
    for mg in resolved_mutex:
        for f in mg.flags:
            if f.name in mutex_flag_names:
                raise ValueError(
                    f'command "{name}": flag "{f.name}" appears in multiple mutex groups'
                )
            mutex_flag_names.add(f.name)

    # All flags: decorator flags + flag set flags + mutex flags + extra flags
    all_flags = decorator_flags + flag_set_flags + mutex_flags
    if extra_flags:
        all_flags.extend(extra_flags)

    # Validate: no duplicate flag names (catches mutex flags overlapping with
    # regular flags or flag set flags)
    seen_flag_names: set[str] = set()
    for f in all_flags:
        if f.name in seen_flag_names:
            raise ValueError(f'command "{name}": duplicate flag name "{f.name}"')
        seen_flag_names.add(f.name)

    # Validate: no collision with global flags
    if global_flags:
        global_flag_names = {gf.name for gf in global_flags}
        for f in all_flags:
            if f.name in global_flag_names:
                raise ValueError(
                    f'command "{name}": flag "{f.name}" collides with a global flag'
                )

    # Validate: no duplicate arg names
    seen_arg_names: set[str] = set()
    for a in all_args:
        if a.name in seen_arg_names:
            raise ValueError(f'command "{name}": duplicate arg name "{a.name}"')
        seen_arg_names.add(a.name)

    # Validate: variadic arg constraints
    variadic_count = sum(1 for a in all_args if a.variadic)
    if variadic_count > 1:
        raise ValueError(f'command "{name}": at most one variadic arg is allowed')
    if variadic_count == 1 and not all_args[-1].variadic:
        variadic_name = next(a.name for a in all_args if a.variadic)
        raise ValueError(f'command "{name}": variadic arg "{variadic_name}" must be the last arg')

    # Validate: flag help text
    for f in all_flags:
        if not f.help or not f.help.strip():
            raise ValueError(
                f'command "{name}": flag "{f.name}" missing help text'
            )

    # Validate: env prefix
    if env_prefix is not None:
        for f in all_flags:
            if f.env is not None and f.prefixed:
                expected_prefix = f"{env_prefix}_"
                if not f.env.startswith(expected_prefix):
                    raise ValueError(
                        f'command "{name}": env var "{f.env}" for flag "{f.name}" '
                        f'must start with "{expected_prefix}" (or set prefixed=false)'
                    )

    # Validate: handler signature matches declared flags and args
    sig = inspect.signature(handler)
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )
    param_names = set(sig.parameters.keys())

    # Detect Context injection: if the first parameter's annotation is Context,
    # exclude it from validation — it will be injected at dispatch time.
    needs_context = False
    params_list = list(sig.parameters.values())
    if params_list and params_list[0].annotation is Context:
        needs_context = True
        param_names.discard(params_list[0].name)

    expected_names: set[str] = set()
    for f in all_flags:
        expected_names.add(_flag_param_name(f.name))
    for a in all_args:
        expected_names.add(a.name)
    # Global flags are also passed to handlers
    if global_flags:
        for gf in global_flags:
            expected_names.add(_flag_param_name(gf.name))

    # Skip strict checks when handler accepts **kwargs -- it can receive
    # any parameter, so missing/extra checks are not meaningful.
    if not has_var_keyword:
        # Check each flag has a matching parameter
        for f in all_flags:
            pname = _flag_param_name(f.name)
            if pname not in param_names:
                raise ValueError(
                    f'command "{name}": handler missing parameter "{pname}" '
                    f'for flag "{f.name}"'
                )

        # Check each arg has a matching parameter
        for a in all_args:
            if a.name not in param_names:
                raise ValueError(
                    f'command "{name}": handler missing parameter "{a.name}" '
                    f'for arg "{a.name}"'
                )

        # Check for extra parameters
        extra = param_names - expected_names
        if extra:
            extra_name = sorted(extra)[0]
            raise ValueError(
                f'command "{name}": handler has extra parameter "{extra_name}" '
                f"not matching any flag or arg"
            )

    # Validate dependencies
    resolved_dependencies = list(dependencies) if dependencies else []
    for dep in resolved_dependencies:
        if isinstance(dep, CoRequired):
            if len(dep.flags) < 2:
                raise ValueError(
                    f'command "{name}": CoRequired must have at least 2 flags, '
                    f"got {len(dep.flags)}"
                )
            seen_dep_flags: set[str] = set()
            for flag_name in dep.flags:
                if flag_name not in seen_flag_names:
                    raise ValueError(
                        f'command "{name}": CoRequired references unknown flag '
                        f'"{flag_name}"'
                    )
                if flag_name in seen_dep_flags:
                    raise ValueError(
                        f'command "{name}": CoRequired has duplicate flag '
                        f'"{flag_name}"'
                    )
                seen_dep_flags.add(flag_name)
        elif isinstance(dep, Requires):
            if dep.flag not in seen_flag_names:
                raise ValueError(
                    f'command "{name}": Requires references unknown flag '
                    f'"{dep.flag}"'
                )
            if dep.depends_on not in seen_flag_names:
                raise ValueError(
                    f'command "{name}": Requires references unknown flag '
                    f'"{dep.depends_on}"'
                )
            if dep.flag == dep.depends_on:
                raise ValueError(
                    f'command "{name}": Requires flag and depends_on cannot be '
                    f'the same ("{dep.flag}")'
                )
        elif isinstance(dep, Implies):
            if dep.flag not in seen_flag_names:
                raise ValueError(
                    f'command "{name}": Implies references unknown flag '
                    f'"{dep.flag}"'
                )
            if dep.implies not in seen_flag_names:
                raise ValueError(
                    f'command "{name}": Implies references unknown flag '
                    f'"{dep.implies}"'
                )
            if dep.flag == dep.implies:
                raise ValueError(
                    f'command "{name}": Implies flag and implies cannot be '
                    f'the same ("{dep.flag}")'
                )
            # Look up the actual Flag objects to validate types
            all_flags_by_name = {f.name: f for f in all_flags}
            trigger_flag = all_flags_by_name[dep.flag]
            target_flag = all_flags_by_name[dep.implies]
            if trigger_flag.type is not bool:
                raise ValueError(
                    f'command "{name}": Implies trigger flag "{dep.flag}" '
                    f"must be a bool flag"
                )
            if target_flag.type is not bool:
                raise ValueError(
                    f'command "{name}": Implies target flag "{dep.implies}" '
                    f"must be a bool flag"
                )
            if not isinstance(dep.value, bool):
                raise ValueError(
                    f'command "{name}": Implies value must be a bool, '
                    f"got {type(dep.value).__name__!r}"
                )

    return Command(
        name=name,
        help=help,
        handler=handler,
        flags=tuple(all_flags),
        args=tuple(all_args),
        flag_sets=tuple(resolved_flag_sets),
        mutex=tuple(resolved_mutex),
        dependencies=tuple(resolved_dependencies),
        tags=effective_tags,
        hidden=hidden,
        interactive=interactive,
        config_fields=resolved_config_fields,
        needs_context=needs_context,
    )


def flag(
    name: str,
    *,
    short: str | None = None,
    type: type = str,
    default: object = _MISSING,
    help: str,
    env: str | None = None,
    env_separator: str | None = None,
    prefixed: bool = True,
    negatable: object = _MISSING,
    choices: list | None = None,
    validate: Callable | None = None,
    repeatable: bool = False,
    unique: object = _MISSING,
) -> Callable:
    """Module-level decorator to attach a Flag to a command handler."""

    def decorator(func: Callable) -> Callable:
        f = Flag(
            name=name,
            short=short,
            type=type,
            default=default,
            help=help,
            env=env,
            env_separator=env_separator,
            prefixed=prefixed,
            negatable=negatable,
            choices=choices,
            validate=validate,
            repeatable=repeatable,
            unique=unique,
        )
        if not hasattr(func, "_strictcli_flags"):
            func._strictcli_flags = []
        func._strictcli_flags.append(f)
        return func

    return decorator


def arg(
    name: str,
    *,
    help: str,
    required: bool = True,
    default: object = _MISSING,
    variadic: bool = False,
    type: type = str,
    choices: list | None = None,
) -> Callable:
    """Module-level decorator to attach an Arg to a command handler."""

    def decorator(func: Callable) -> Callable:
        a = Arg(
            name=name, help=help, required=required, default=default,
            variadic=variadic, type=type, choices=choices,
        )
        if not hasattr(func, "_strictcli_args"):
            func._strictcli_args = []
        func._strictcli_args.append(a)
        return func

    return decorator


# ---------------------------------------------------------------------------
# Help text formatters
# ---------------------------------------------------------------------------


def _format_version(app: App) -> str:
    """Format version string: '{name} {version}'."""
    return f"{app.name} {app.version}"


def _format_app_help(app: App) -> str:
    """Format app-level help shown when the user runs 'myapp --help'."""
    lines: list[str] = [f"{app.name} v{app.version} -- {app.help}"]

    visible_commands = {n: c for n, c in app._commands.items() if not c.hidden}
    if visible_commands:
        lines.append("")
        lines.append("Commands:")
        names = list(visible_commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = visible_commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    visible_groups = {n: g for n, g in app._groups.items() if not g.hidden}
    if visible_groups:
        lines.append("")
        lines.append("Groups:")
        names = list(visible_groups.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            grp = visible_groups[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{grp.help}")

    if app._deprecated:
        lines.append("")
        lines.append("Deprecated:")
        names = list(app._deprecated.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            dep = app._deprecated[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{dep.message}")

    if app._global_flags:
        lines.append("")
        lines.append("Global flags:")
        flag_strs = []
        for f in app._global_flags:
            parts = [f"--{f.name}"]
            if f.short:
                parts.append(f"-{f.short}")
            flag_strs.append((", ".join(parts), f.help))
        max_flag_len = max(len(s[0]) for s in flag_strs)
        for flag_str, help_text in flag_strs:
            padding = max_flag_len - len(flag_str) + 4
            lines.append(f"  {flag_str}{' ' * padding}{help_text}")

    lines.append("")
    lines.append(f"Use '{app.name} <command> --help' for more information.")

    return "\n".join(lines)


def _format_group_help(app: App, group: Group, path: list[str] | None = None) -> str:
    """Format group-level help shown when the user runs 'myapp group --help'.

    ``path`` is the list of group names leading to this group (e.g. ['dns', 'zone']).
    When None, the path is computed by searching the app's group tree.
    """
    if path is None:
        path = _find_group_path(app, group)
    full_path = " ".join(path)
    lines: list[str] = [f"{app.name} {full_path} -- {group.help}"]

    visible_commands = {n: c for n, c in group.commands.items() if not c.hidden}
    if visible_commands:
        lines.append("")
        lines.append("Commands:")
        names = list(visible_commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = visible_commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    visible_groups = {n: g for n, g in group._groups.items() if not g.hidden}
    if visible_groups:
        lines.append("")
        lines.append("Groups:")
        names = list(visible_groups.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            sub = visible_groups[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{sub.help}")

    if group.deprecated:
        lines.append("")
        lines.append("Deprecated:")
        names = list(group.deprecated.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            dep = group.deprecated[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{dep.message}")

    lines.append("")
    lines.append(
        f"Use '{app.name} {full_path} <command> --help' for more information."
    )

    return "\n".join(lines)


def _find_group_path(app: App, target: Group) -> list[str]:
    """Find the full path (list of group names) from app root to the target group."""
    def _search(groups: dict[str, Group], path: list[str]) -> list[str] | None:
        for name, grp in groups.items():
            current = path + [name]
            if grp is target:
                return current
            result = _search(grp._groups, current)
            if result is not None:
                return result
        return None

    result = _search(app._groups, [])
    # Fallback: just use the group name (shouldn't happen in practice)
    return result if result is not None else [target.name]


def _build_flag_spec(f: Flag) -> str:
    """Build the left-column spec string for a flag (e.g. '--target, -t <str>')."""
    parts: list[str] = []
    if f.type is bool and f.negatable and f.compound == "scalar":
        parts.append(f"--{f.name}, --no-{f.name}")
        if f.short:
            parts.append(f"-{f.short}")
    else:
        parts.append(f"--{f.name}")
        if f.short:
            parts.append(f"-{f.short}")
    spec = ", ".join(parts)
    if f.compound == "list":
        type_name = _TYPE_NAMES.get(f.item_type, "str")
        spec += f" <{type_name}>"
    elif f.compound == "dict":
        type_name = _TYPE_NAMES.get(f.value_type, "str")
        spec += f" <key={type_name}>"
    elif f.type is str:
        spec += " <str>"
    elif f.type is int:
        spec += " <int>"
    elif f.type is float:
        spec += " <float>"
    return spec


def _build_flag_meta(f: Flag) -> str:
    """Build the bracketed metadata suffix for a flag."""
    meta_parts: list[str] = []
    if f.compound == "list":
        meta_parts.append("list")
    elif f.compound == "dict":
        meta_parts.append("dict")
    elif f.repeatable:
        meta_parts.append("repeatable")
    if f.unique is True:
        meta_parts.append("unique")
    if f.choices is not None:
        choices_str = ", ".join(str(c) for c in f.choices)
        meta_parts.append(f"choices: {choices_str}")
    if f.env is not None:
        if f.env_separator is not None:
            meta_parts.append(f"env: {f.env} (sep: {f.env_separator})")
        else:
            meta_parts.append(f"env: {f.env}")
    if f.compound == "dict":
        # Dict flags are never required; show default only if non-empty
        if f.default:
            meta_parts.append(f"default: {f.default}")
    elif f.type is bool and f.compound == "scalar" and f.default is not None:
        meta_parts.append(f"default: {'true' if f.default else 'false'}")
    elif f.repeatable:
        # Repeatable flags are never required; show default only if non-empty
        if f.default:
            joined = ", ".join(_format_value_for_error(elem) for elem in f.default)
            meta_parts.append(f"default: {joined}")
    elif f.default is not None:
        meta_parts.append(f"default: {f.default}")
    else:
        meta_parts.append("required")
    return " [" + "] [".join(meta_parts) + "]"


def _format_command_help(app: App, cmd: Command, prefix: str = "") -> str:
    """Format command-level help shown when the user runs 'myapp cmd --help'."""
    lines: list[str] = [f"{app.name} {prefix}{cmd.name} -- {cmd.help}"]

    # Passthrough commands show only the header line (no flags/args section)
    if cmd.passthrough is not None:
        return "\n".join(lines)

    if cmd.args:
        lines.append("")
        lines.append("Arguments:")
        display_names = [f"{a.name}..." if a.variadic else a.name for a in cmd.args]
        max_len = max(len(dn) for dn in display_names)
        for a, dn in zip(cmd.args, display_names):
            padding = max_len - len(dn) + 4
            help_text = a.help
            meta_parts: list[str] = []
            if a.type is not str:
                meta_parts.append(f"type: {a.type.__name__}")
            if a.choices is not None:
                choices_str = ", ".join(str(c) for c in a.choices)
                meta_parts.append(f"choices: {choices_str}")
            if not a.required:
                if not isinstance(a.default, _MissingSentinel):
                    meta_parts.append(f"default: {a.default}")
                else:
                    meta_parts.append("optional")
            meta = ""
            if meta_parts:
                meta = " [" + "] [".join(meta_parts) + "]"
            lines.append(f"  {dn}{' ' * padding}{help_text}{meta}")

    # Collect flag names that belong to mutex groups
    mutex_flag_names: set[str] = set()
    for mg in cmd.mutex:
        for f in mg.flags:
            mutex_flag_names.add(f.name)

    # Regular flags (not in any mutex group)
    regular_flags = [f for f in cmd.flags if f.name not in mutex_flag_names]

    if regular_flags:
        lines.append("")
        lines.append("Flags:")
        specs = [_build_flag_spec(f) for f in regular_flags]
        max_spec = max(len(s) for s in specs)
        for f, spec in zip(regular_flags, specs):
            padding = max_spec - len(spec) + 4
            meta = _build_flag_meta(f)
            lines.append(f"  {spec}{' ' * padding}{f.help}{meta}")

    # Mutex groups
    for mg in cmd.mutex:
        lines.append("")
        label = "Flags (mutually exclusive):"
        lines.append(label)
        specs = [_build_flag_spec(f) for f in mg.flags]
        max_spec = max(len(s) for s in specs)
        for f, spec in zip(mg.flags, specs):
            padding = max_spec - len(spec) + 4
            meta = _build_flag_meta(f)
            lines.append(f"  {spec}{' ' * padding}{f.help}{meta}")

    # Global flags
    if app._global_flags:
        lines.append("")
        lines.append("Global flags:")
        specs = [_build_flag_spec(f) for f in app._global_flags]
        max_spec = max(len(s) for s in specs)
        for f, spec in zip(app._global_flags, specs):
            padding = max_spec - len(spec) + 4
            meta = _build_flag_meta(f)
            lines.append(f"  {spec}{' ' * padding}{f.help}{meta}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tag DSL
# ---------------------------------------------------------------------------

_TAG_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")


def _tagdsl_tokenize(expr: str) -> list[tuple[str, str, int]]:
    """Tokenize a tag expression into (type, value, position) tuples."""
    tokens: list[tuple[str, str, int]] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "&":
            tokens.append(("AND", "&", i))
            i += 1
        elif ch == "|":
            tokens.append(("OR", "|", i))
            i += 1
        elif ch == "^":
            tokens.append(("XOR", "^", i))
            i += 1
        elif ch == "-":
            tokens.append(("DIFF", "-", i))
            i += 1
        elif ch == "!":
            tokens.append(("NOT", "!", i))
            i += 1
        elif ch == "(":
            tokens.append(("LPAREN", "(", i))
            i += 1
        elif ch == ")":
            tokens.append(("RPAREN", ")", i))
            i += 1
        else:
            m = _TAG_NAME_RE.match(expr, i)
            if m:
                tokens.append(("IDENT", m.group(), i))
                i = m.end()
            else:
                raise ValueError(
                    f'tag expression: unexpected character "{ch}" at position {i}'
                )
    return tokens


def _tagdsl_parse(tokens: list[tuple[str, str, int]]) -> tuple:
    """Parse tag expression tokens into an AST using recursive descent.

    Precedence (tightest first): NOT, AND, XOR, OR, DIFF.
    """
    pos = 0

    def peek() -> tuple[str, str, int] | None:
        nonlocal pos
        if pos < len(tokens):
            return tokens[pos]
        return None

    def consume() -> tuple[str, str, int]:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def end_pos() -> int:
        if not tokens:
            return 0
        last = tokens[-1]
        return last[2] + len(last[1])

    def parse_atom() -> tuple:
        tok = peek()
        if tok is None:
            raise ValueError(
                f"tag expression: unexpected end of expression "
                f"at position {end_pos()}"
            )
        if tok[0] == "NOT":
            consume()
            child = parse_atom()
            return ("not", child)
        if tok[0] == "LPAREN":
            consume()
            node = parse_diff()
            closing = peek()
            if closing is None or closing[0] != "RPAREN":
                raise ValueError(
                    f'tag expression: expected ")" at position {end_pos()}'
                )
            consume()
            return node
        if tok[0] == "IDENT":
            consume()
            return ("ident", tok[1])
        raise ValueError(
            f'tag expression: unexpected token "{tok[1]}" at position {tok[2]}'
        )

    def parse_and() -> tuple:
        left = parse_atom()
        while True:
            tok = peek()
            if tok is None or tok[0] != "AND":
                break
            consume()
            right = parse_atom()
            left = ("and", left, right)
        return left

    def parse_xor() -> tuple:
        left = parse_and()
        while True:
            tok = peek()
            if tok is None or tok[0] != "XOR":
                break
            consume()
            right = parse_and()
            left = ("xor", left, right)
        return left

    def parse_or() -> tuple:
        left = parse_xor()
        while True:
            tok = peek()
            if tok is None or tok[0] != "OR":
                break
            consume()
            right = parse_xor()
            left = ("or", left, right)
        return left

    def parse_diff() -> tuple:
        left = parse_or()
        while True:
            tok = peek()
            if tok is None or tok[0] != "DIFF":
                break
            consume()
            right = parse_or()
            left = ("diff", left, right)
        return left

    result = parse_diff()
    tok = peek()
    if tok is not None:
        raise ValueError(
            f'tag expression: unexpected token "{tok[1]}" at position {tok[2]}'
        )
    return result


def _tagdsl_evaluate(ast: tuple, tags: set[str]) -> bool:
    """Evaluate a tag DSL AST against a set of tags."""
    kind = ast[0]
    if kind == "ident":
        return ast[1] in tags
    if kind == "not":
        return not _tagdsl_evaluate(ast[1], tags)
    if kind == "and":
        return _tagdsl_evaluate(ast[1], tags) and _tagdsl_evaluate(ast[2], tags)
    if kind == "or":
        return _tagdsl_evaluate(ast[1], tags) or _tagdsl_evaluate(ast[2], tags)
    if kind == "xor":
        return _tagdsl_evaluate(ast[1], tags) != _tagdsl_evaluate(ast[2], tags)
    if kind == "diff":
        return _tagdsl_evaluate(ast[1], tags) and not _tagdsl_evaluate(ast[2], tags)
    raise ValueError(f"tag expression: unknown AST node {kind!r}")


def _match_tag_expr(expr: str, tags: set[str]) -> bool:
    """Evaluate a tag expression against a set of tags. Returns bool."""
    tokens = _tagdsl_tokenize(expr)
    if not tokens:
        raise ValueError("tag expression: empty expression")
    ast = _tagdsl_parse(tokens)
    return _tagdsl_evaluate(ast, tags)


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------


def _filter_checks(
    check_defs: dict[str, _CheckDef],
    tag_expr: str | None,
    name_glob: str | None,
    run_all: bool,
) -> set[str]:
    """Filter checks by tag expression and/or name glob.

    Returns the set of selected check names.
    """
    if run_all:
        return set(check_defs.keys())

    by_tag: set[str] | None = None
    by_name: set[str] | None = None

    if tag_expr is not None:
        by_tag = {
            name for name, cdef in check_defs.items()
            if _match_tag_expr(tag_expr, set(cdef.tags))
        }

    if name_glob is not None:
        by_name = {
            name for name in check_defs
            if fnmatch.fnmatch(name, name_glob)
        }

    if by_tag is not None and by_name is not None:
        return by_tag & by_name
    if by_tag is not None:
        return by_tag
    if by_name is not None:
        return by_name
    return set()


def _resolve_check_order(
    check_defs: dict[str, _CheckDef], selected: set[str],
) -> list[str]:
    """Resolve execution order via topological sort, pulling in dependencies.

    If a selected check depends on an unselected check, the dependency is
    pulled into the execution set. Raises ValueError on cycles.
    """
    # Expand selected to include all transitive dependencies
    expanded: set[str] = set()
    stack = list(selected)
    while stack:
        name = stack.pop()
        if name in expanded:
            continue
        expanded.add(name)
        for dep in check_defs[name].depends_on:
            if dep not in expanded:
                stack.append(dep)

    # Build adjacency and in-degree for Kahn's algorithm
    in_degree: dict[str, int] = {name: 0 for name in expanded}
    dependents: dict[str, list[str]] = {name: [] for name in expanded}

    for name in expanded:
        for dep in check_defs[name].depends_on:
            if dep in expanded:
                dependents[dep].append(name)
                in_degree[name] += 1

    # Kahn's algorithm
    queue: deque[str] = deque(
        name for name in sorted(expanded) if in_degree[name] == 0
    )
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(dependents[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(order) != len(expanded):
        # Cycle detection: find a cycle for the error message
        remaining = expanded - set(order)
        cycle = _find_cycle(check_defs, remaining)
        raise ValueError(f"check dependency cycle: {cycle}")

    return order


def _find_cycle(
    check_defs: dict[str, _CheckDef], nodes: set[str],
) -> str:
    """Find and format a cycle among the given nodes for error reporting."""
    # DFS to find a cycle path
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> str | None:
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for dep in check_defs[node].depends_on:
            if dep not in nodes:
                continue
            if dep in path_set:
                # Found cycle: extract from dep to current node back to dep
                cycle_start = path.index(dep)
                cycle_path = path[cycle_start:] + [dep]
                return " -> ".join(cycle_path)
            if dep not in visited:
                result = dfs(dep)
                if result:
                    return result
        path.pop()
        path_set.discard(node)
        return None

    for node in sorted(nodes):
        if node not in visited:
            result = dfs(node)
            if result:
                return result
    return " -> ".join(sorted(nodes))


def _run_checks(
    check_defs: dict,
    check_names: list[str],
    context: CheckContext,
    ignore_warnings: bool,
    scope_adapter: object | None = None,
) -> tuple[list[tuple[str, CheckResult]], int]:
    """Execute checks in order, skipping dependents of failed checks.

    Returns (results_list, exit_code). exit_code is 0 if all pass (or all
    warn with ignore_warnings=True), 1 otherwise.
    """
    results: list[tuple[str, CheckResult]] = []
    # Checks whose dependents should be cascade-skipped: only fail or
    # cascade-skip qualifies. A warn satisfies the dependency (dependents
    # still run) regardless of ignore_warnings -- it only affects the exit
    # code. Explicit skip from an impl is not a failure either.
    failed_checks: set[str] = set()
    exit_code = 0

    def record(name: str, result: CheckResult) -> None:
        nonlocal exit_code
        if result.status == "fail":
            failed_checks.add(name)
            exit_code = 1
        elif result.status == "warn":
            if not ignore_warnings:
                exit_code = 1
        # "skip" from an impl or adapter: no cascade, no exit code change.

    for name in check_names:
        cdef = check_defs[name]

        # Check if any dependency failed
        failed_dep = None
        for dep in cdef.depends_on:
            if dep in failed_checks:
                failed_dep = dep
                break

        if failed_dep is not None:
            result = CheckResult(
                status="skip",
                message=f'skipped: dependency "{failed_dep}" failed',
            )
            failed_checks.add(name)
            results.append((name, result))
            exit_code = 1
            continue

        # Apply scope adapter if the check has a scope and an adapter is set
        check_context = context
        if cdef.scope and scope_adapter is not None:
            adapted = scope_adapter(context, cdef.scope)
            if isinstance(adapted, CheckResult):
                results.append((name, adapted))
                record(name, adapted)
                continue
            check_context = adapted

        result = cdef.impl(check_context)
        results.append((name, result))
        record(name, result)

    return results, exit_code


# ---------------------------------------------------------------------------
# Check command output helpers
# ---------------------------------------------------------------------------

_CHECK_STATUS_LABELS = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}


def _check_list_mode(check_defs: dict[str, _CheckDef], json_mode: bool) -> None:
    """Print check listing in human or JSON format."""
    # Sort alphabetically for deterministic output matching Go
    sorted_defs = sorted(check_defs.values(), key=lambda c: c.name)

    if json_mode:
        items = []
        for cdef in sorted_defs:
            entry: dict = {"name": cdef.name, "tags": cdef.tags, "severity": cdef.severity}
            if cdef.scope:
                entry["scope"] = cdef.scope
            items.append(entry)
        print(json.dumps(items, separators=(",", ":")))
        return

    if not check_defs:
        print("No checks defined.")
        return

    # Compute column widths
    name_width = max(len(cdef.name) for cdef in sorted_defs)
    name_width = max(name_width, len("NAME"))
    tags_width = max(len(", ".join(cdef.tags)) for cdef in sorted_defs)
    tags_width = max(tags_width, len("TAGS"))

    header = f"{'NAME':<{name_width}}   {'TAGS':<{tags_width}}   SEVERITY"
    print(header)
    for cdef in sorted_defs:
        tags_str = ", ".join(cdef.tags)
        print(f"{cdef.name:<{name_width}}   {tags_str:<{tags_width}}   {cdef.severity}")


def _check_dry_run_mode(
    check_defs: dict[str, _CheckDef], order: list[str],
) -> None:
    """Print execution plan without running checks."""
    print(f"Would run {len(order)} check{'s' if len(order) != 1 else ''}:")
    for i, name in enumerate(order, 1):
        cdef = check_defs[name]
        deps = [d for d in cdef.depends_on if d in set(order)]
        if deps:
            print(f"  {i}. {name} (depends on: {', '.join(deps)})")
        else:
            print(f"  {i}. {name}")



def format_check_results(
    results: list[CheckRunResult], verbose: bool = False,
) -> str:
    """Format check results as a human-readable aligned string."""
    if not results:
        return ""

    name_width = max(len(r.name) for r in results)
    lines: list[str] = []

    for r in results:
        label = _CHECK_STATUS_LABELS[r.result.status]
        lines.append(f"{label}  {r.name:<{name_width}}    {r.result.message}")

        show_details = r.result.details and (
            verbose or r.result.status in ("fail", "warn", "skip")
        )
        if show_details:
            for detail in r.result.details:
                lines.append(f"        {detail}")

    return "\n".join(lines)


def format_check_results_json(results: list[CheckRunResult]) -> str:
    """Format check results as a JSON string."""
    items = [
        {
            "name": r.name,
            "status": r.result.status,
            "message": r.result.message,
            "details": r.result.details if r.result.details is not None else [],
        }
        for r in results
    ]
    return json.dumps(items, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Schema serialization (--dump-schema)
# ---------------------------------------------------------------------------

_TYPE_NAMES = {str: "str", bool: "bool", int: "int", float: "float"}


def _serialize_flag(f: Flag) -> dict:
    """Serialize a Flag to a JSON-serializable dict.

    Identity fields (name, type, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    # Compound type serialization
    if f.compound == "list":
        type_obj = {
            "type": "array",
            "items": {"type": _TYPE_NAMES[f.item_type]},
        }
    elif f.compound == "dict":
        type_obj = {
            "type": "object",
            "additionalProperties": {"type": _TYPE_NAMES[f.value_type]},
        }
    else:
        type_obj = _TYPE_NAMES[f.type]

    d: dict = {
        "name": f.name,
        "type": type_obj,
        "help": f.help,
    }
    if f.short is not None:
        d["short"] = f.short
    # For dict flags, only emit default if non-empty
    if f.compound == "dict":
        if f.default:
            d["default"] = f.default
    elif f.default is not None:
        # For list (repeatable) flags, only emit if non-empty
        if f.compound == "list" and isinstance(f.default, list) and not f.default:
            pass  # omit empty list default
        else:
            d["default"] = f.default
    if f.env is not None:
        d["env"] = f.env
    if f.choices is not None:
        d["choices"] = f.choices
    if f.repeatable and f.compound != "list":
        # Only emit repeatable for plain repeatable flags, not list[T] flags
        d["repeatable"] = f.repeatable
    if f.unique is True:
        d["unique"] = True
    if f.env_separator is not None:
        d["env_separator"] = f.env_separator
    negatable = f.negatable if f.type is bool and f.compound == "scalar" else None
    if negatable is not None:
        d["negatable"] = negatable
    # hidden is currently always False, so always omitted
    return d


def _serialize_arg(a: Arg) -> dict:
    """Serialize an Arg to a JSON-serializable dict.

    Identity fields (name, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    d: dict = {
        "name": a.name,
        "help": a.help,
    }
    # Compound type serialization for args
    if a.compound == "list":
        d["type"] = {
            "type": "array",
            "items": {"type": _TYPE_NAMES[a.item_type]},
        }
    elif a.type is not str:
        d["type"] = a.type.__name__
    if not a.required:
        d["required"] = a.required
    if not isinstance(a.default, _MissingSentinel):
        d["default"] = a.default
    if a.variadic:
        d["variadic"] = a.variadic
    if a.choices is not None:
        d["choices"] = a.choices
    return d


def _serialize_command(cmd: Command) -> dict:
    """Serialize a Command to a JSON-serializable dict.

    Identity fields (name, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    d: dict = {
        "name": cmd.name,
        "help": cmd.help,
    }
    if cmd.passthrough is not None:
        d["passthrough"] = True
    flags = [_serialize_flag(f) for f in cmd.flags]
    if flags:
        d["flags"] = flags
    args = [_serialize_arg(a) for a in cmd.args]
    if args:
        d["args"] = args
    tags = sorted(cmd.tags)
    if tags:
        d["tags"] = tags
    constraints: list[dict] = []
    for mg in cmd.mutex:
        constraints.append({
            "type": "mutex",
            "flags": [f.name for f in mg.flags],
        })
    for dep in cmd.dependencies:
        if isinstance(dep, CoRequired):
            constraints.append({
                "type": "co_required",
                "flags": dep.flags,
            })
        elif isinstance(dep, Requires):
            constraints.append({
                "type": "requires",
                "flag": dep.flag,
                "depends_on": dep.depends_on,
            })
        elif isinstance(dep, Implies):
            constraints.append({
                "type": "implies",
                "flag": dep.flag,
                "implies": dep.implies,
                "value": dep.value,
            })
    if constraints:
        d["constraints"] = constraints
    if cmd.hidden:
        d["hidden"] = True
    if cmd.interactive:
        d["interactive"] = True
    if cmd.config_fields:
        d["config_fields"] = list(cmd.config_fields)
    return d


def _serialize_group(group: Group) -> dict:
    """Serialize a Group to a JSON-serializable dict (recursive).

    Identity fields (name, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    d: dict = {
        "name": group.name,
        "help": group.help,
    }
    commands = {name: _serialize_command(cmd) for name, cmd in group.commands.items()}
    if commands:
        d["commands"] = commands
    groups = {name: _serialize_group(g) for name, g in group._groups.items()}
    if groups:
        d["groups"] = groups
    deprecated = {name: dep.message for name, dep in group.deprecated.items()}
    if deprecated:
        d["deprecated"] = deprecated
    tags = sorted(group.tags)
    if tags:
        d["tags"] = tags
    if group.hidden:
        d["hidden"] = True
    return d


def _build_schema_defaults() -> dict:
    """Return the defaults object documenting what 'missing' means in the schema."""
    return {
        "schema_version": 1,
        "app": {
            "env_prefix": None,
            "config": False,
            "global_flags": [],
            "commands": {},
            "groups": {},
            "deprecated": {},
            "tag_contracts": {},
        },
        "flag": {
            "short": None,
            "default": None,
            "env": None,
            "choices": None,
            "repeatable": False,
            "unique": False,
            "env_separator": None,
            "negatable": None,
            "hidden": False,
        },
        "arg": {
            "type": "str",
            "required": True,
            "default": None,
            "variadic": False,
            "choices": None,
        },
        "command": {
            "passthrough": False,
            "flags": [],
            "args": [],
            "tags": [],
            "constraints": [],
            "hidden": False,
            "interactive": False,
        },
        "group": {
            "commands": {},
            "groups": {},
            "deprecated": {},
            "tags": [],
            "hidden": False,
        },
    }


def _read_project_id() -> str:
    """Read project name from pyproject.toml in the current working directory."""
    pyproject_path = Path(os.getcwd()) / "pyproject.toml"
    if not pyproject_path.exists():
        raise RuntimeError(
            "Cannot determine project_id: pyproject.toml not found "
            "or missing [project].name"
        )
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    project_name = data.get("project", {}).get("name")
    if not project_name:
        raise RuntimeError(
            "Cannot determine project_id: pyproject.toml not found "
            "or missing [project].name"
        )
    return project_name


def _collect_config_field_bindings(
    commands: dict[str, Command],
    bindings: dict[str, list[str]],
    path: list[str],
) -> None:
    """Walk commands and record which commands bind each config field."""
    for cmd in commands.values():
        cmd_path = " ".join(path + [cmd.name])
        for cf_name in cmd.config_fields:
            if cf_name in bindings:
                bindings[cf_name].append(cmd_path)


def _collect_config_field_bindings_from_group(
    group: Group,
    bindings: dict[str, list[str]],
    path: list[str],
) -> None:
    """Recursively walk groups to collect config field bindings."""
    group_path = path + [group.name]
    _collect_config_field_bindings(group.commands, bindings, group_path)
    for sub in group._groups.values():
        _collect_config_field_bindings_from_group(sub, bindings, group_path)


def _dump_schema(app: App) -> dict:
    """Produce a JSON-serializable dict representing the app's command tree.

    Fields whose values match the schema defaults are omitted.
    The top-level ``defaults`` key documents what each missing field means.
    """
    project_id = _read_project_id()
    schema: dict = {
        "schema_version": 1,
        "defaults": _build_schema_defaults(),
        "project_id": project_id,
        "name": app.name,
        "version": app.version,
        "help": app.help,
    }
    if app.env_prefix is not None:
        schema["env_prefix"] = app.env_prefix
    if app.config:
        schema["config"] = app.config
    global_flags = [_serialize_flag(f) for f in app._global_flags]
    if global_flags:
        schema["global_flags"] = global_flags
    commands = {name: _serialize_command(cmd) for name, cmd in app._commands.items()}
    if commands:
        schema["commands"] = commands
    groups = {name: _serialize_group(grp) for name, grp in app._groups.items()}
    if groups:
        schema["groups"] = groups
    deprecated = {name: dep.message for name, dep in app._deprecated.items()}
    if deprecated:
        schema["deprecated"] = deprecated
    if app._tag_contracts:
        schema["tag_contracts"] = dict(app._tag_contracts)
    if app._checks_enabled:
        checks_schema: dict = {}
        for name, cdef in app._check_defs.items():
            entry = {
                "tags": cdef.tags,
                "severity": cdef.severity,
                "fast": cdef.fast,
                "pure": cdef.pure,
                "needs_network": cdef.needs_network,
                "depends_on": cdef.depends_on,
            }
            if cdef.scope:
                entry["scope"] = cdef.scope
            checks_schema[name] = entry
        schema["checks"] = checks_schema
    if app._config_fields:
        # Build field definitions with bound command info
        cf_schema: dict = {}
        # Collect which commands bind each field
        bindings: dict[str, list[str]] = {
            name: [] for name in app._config_fields
        }
        _collect_config_field_bindings(app._commands, bindings, [])
        for grp in app._groups.values():
            _collect_config_field_bindings_from_group(grp, bindings, [])

        for name, cf in app._config_fields.items():
            entry: dict = {
                "type": cf.type.__name__,
                "help": cf.help,
                "required": cf.required,
            }
            if not isinstance(cf.default, _MissingSentinel):
                entry["default"] = cf.default
            if bindings.get(name):
                entry["bound_commands"] = bindings[name]
            cf_schema[name] = entry
        schema["config_fields"] = cf_schema
    return schema


def _check_schema_project_id(file_path: str, new_project_id: str) -> None:
    """Verify that an existing schema file belongs to the same project.

    Raises RuntimeError on mismatch. Silently passes on: missing file,
    unreadable file, JSON without project_id field, or matching project_id.
    """
    try:
        with open(file_path) as f:
            existing = json.loads(f.read())
    except (OSError, json.JSONDecodeError, ValueError):
        return
    existing_id = existing.get("project_id")
    if existing_id is None:
        return
    if existing_id != new_project_id:
        raise RuntimeError(
            f"Schema mismatch: existing schema belongs to project "
            f"'{existing_id}', not '{new_project_id}'. "
            f"Run from the correct project directory."
        )


def _write_schema(app: App) -> str:
    """Write the schema to .strictcli/schema.json and return the path."""
    schema = _dump_schema(app)
    dir_path = os.path.join(os.getcwd(), ".strictcli")
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, "schema.json")
    _check_schema_project_id(file_path, schema["project_id"])
    with open(file_path, "w") as f:
        f.write(json.dumps(schema, indent=2) + "\n")
    return file_path


# MCP server (--mcp)

def _mcp_collect_commands(app: App) -> dict[str, tuple[Command, str]]:
    """Collect non-hidden, non-interactive leaf commands as {dotted_path: (cmd, help)}.

    Returns a dict mapping dotted command paths to (Command, help_text) tuples.
    """
    commands: dict[str, tuple[Command, str]] = {}

    for name, cmd in app._commands.items():
        if cmd.hidden or cmd.interactive:
            continue
        commands[name] = (cmd, cmd.help)

    def _collect_from_group(
        group: Group, path: list[str],
    ) -> None:
        if group.hidden:
            return
        for cmd_name, cmd in group.commands.items():
            if cmd.hidden or cmd.interactive:
                continue
            dotted = ".".join(path + [cmd_name])
            commands[dotted] = (cmd, cmd.help)
        for sub_name, sub_group in group._groups.items():
            _collect_from_group(sub_group, path + [sub_name])

    for group_name, group in app._groups.items():
        _collect_from_group(group, [group_name])

    return commands


def _mcp_jsonrpc_error(
    req_id: object, code: int, message: str,
) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _mcp_handle_initialize(app: App, req_id: object) -> dict:
    """Handle the MCP 'initialize' request."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": app.name,
                "version": app.version,
            },
        },
    }


def _mcp_handle_tools_list(
    app: App, commands: dict[str, tuple[Command, str]], req_id: object,
) -> dict:
    """Handle the MCP 'tools/list' request."""
    tools = []
    for dotted_path, (cmd, help_text) in commands.items():
        tools.append({
            "name": dotted_path,
            "description": help_text,
            "inputSchema": _build_json_schema(cmd),
        })
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"tools": tools},
    }


def _mcp_handle_tools_call(
    app: App,
    commands: dict[str, tuple[Command, str]],
    req_id: object,
    params: dict,
) -> dict:
    """Handle the MCP 'tools/call' request."""
    tool_name = params.get("name")
    if not isinstance(tool_name, str):
        return _mcp_jsonrpc_error(
            req_id, -32602, "missing or invalid 'name' in params",
        )

    if tool_name not in commands:
        return _mcp_jsonrpc_error(
            req_id, -32602, f"unknown tool: {tool_name}",
        )

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _mcp_jsonrpc_error(
            req_id, -32602, "'arguments' must be an object",
        )

    try:
        result = app.call(tool_name, **arguments)
    except InvokeError as e:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            },
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(result, default=str),
            }],
        },
    }


def _run_mcp_server(
    app: App,
    *,
    input: io.TextIOBase | None = None,
    output: io.TextIOBase | None = None,
) -> None:
    """Run the MCP JSON-RPC 2.0 server loop.

    Reads one JSON object per line from input, writes responses to output.
    Notifications (no 'id' field) get no response.
    """
    inp = input if input is not None else sys.stdin
    out = output if output is not None else sys.stdout

    commands = _mcp_collect_commands(app)

    _MCP_HANDLERS = {
        "initialize": lambda req_id, _params: _mcp_handle_initialize(app, req_id),
        "tools/list": lambda req_id, _params: _mcp_handle_tools_list(
            app, commands, req_id,
        ),
        "tools/call": lambda req_id, params: _mcp_handle_tools_call(
            app, commands, req_id, params,
        ),
    }

    for line in inp:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # Malformed JSON -- send parse error if we can
            resp = _mcp_jsonrpc_error(None, -32700, "parse error")
            out.write(json.dumps(resp) + "\n")
            out.flush()
            continue

        if not isinstance(msg, dict):
            resp = _mcp_jsonrpc_error(None, -32600, "invalid request")
            out.write(json.dumps(resp) + "\n")
            out.flush()
            continue

        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # Notifications have no 'id' -- don't send a response
        if "id" not in msg:
            continue

        handler = _MCP_HANDLERS.get(method)
        if handler is not None:
            resp = handler(req_id, params)
        else:
            resp = _mcp_jsonrpc_error(
                req_id, -32601, f"method not found: {method}",
            )

        out.write(json.dumps(resp) + "\n")
        out.flush()
