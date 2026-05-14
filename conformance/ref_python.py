"""Generate a temporary Python script from a conformance test case's app definition.

The generated script imports strictcli, builds the app as described by the JSON
definition, registers handlers that print template-substituted output, and calls
app.run().
"""

from __future__ import annotations

import json
import textwrap


def _flag_param(name: str) -> str:
    """Convert a flag name to a Python parameter name (e.g. dry-run -> dry_run)."""
    return name.replace("-", "_")


def _emit_flag(flag_def: dict, indent: str = "") -> str:
    """Emit a strictcli.Flag(...) expression from a flag JSON definition."""
    parts = [
        f"name={flag_def['name']!r}",
    ]
    ftype = flag_def.get("type", "str")
    type_map = {"str": "str", "bool": "bool", "int": "int"}
    parts.append(f"type={type_map[ftype]}")
    parts.append(f"help={flag_def['help']!r}")

    if "short" in flag_def:
        parts.append(f"short={flag_def['short']!r}")

    if "default" in flag_def:
        default = flag_def["default"]
        if default is None:
            parts.append("default=None")
        elif isinstance(default, bool):
            parts.append(f"default={default}")
        elif isinstance(default, int):
            parts.append(f"default={default}")
        else:
            parts.append(f"default={default!r}")

    if "env" in flag_def:
        parts.append(f"env={flag_def['env']!r}")

    if "prefixed" in flag_def:
        parts.append(f"prefixed={flag_def['prefixed']!r}")

    if "choices_str" in flag_def:
        parts.append(f"choices={flag_def['choices_str']!r}")

    if "choices_int" in flag_def:
        parts.append(f"choices={flag_def['choices_int']!r}")

    if flag_def.get("repeatable", False):
        parts.append("repeatable=True")

    return f"{indent}strictcli.Flag({', '.join(parts)})"


def _emit_tag(tag_def: dict, indent: str = "") -> str:
    """Emit a strictcli.Tag(...) expression."""
    flag_lines = [_emit_flag(f, indent + "        ") for f in tag_def["flags"]]
    flags_str = ",\n".join(flag_lines)
    return (
        f"{indent}strictcli.Tag(\n"
        f"{indent}    name={tag_def['name']!r},\n"
        f"{indent}    flags=[\n"
        f"{flags_str},\n"
        f"{indent}    ],\n"
        f"{indent})"
    )


def _emit_mutex(mutex_def: dict, indent: str = "") -> str:
    """Emit a strictcli.MutexGroup(...) expression."""
    flag_lines = [_emit_flag(f, indent + "        ") for f in mutex_def["flags"]]
    flags_str = ",\n".join(flag_lines)
    required = mutex_def.get("required", False)
    return (
        f"{indent}strictcli.MutexGroup(\n"
        f"{indent}    flags=[\n"
        f"{flags_str},\n"
        f"{indent}    ],\n"
        f"{indent}    required={required!r},\n"
        f"{indent})"
    )


def _collect_params(cmd_def: dict) -> list[str]:
    """Collect all parameter names for a command handler."""
    params = []
    # Flags from direct flags, tags, and mutex groups
    for f in cmd_def.get("flags", []):
        params.append(_flag_param(f["name"]))
    for tag in cmd_def.get("tags", []):
        for f in tag["flags"]:
            params.append(_flag_param(f["name"]))
    for mg in cmd_def.get("mutex", []):
        for f in mg["flags"]:
            params.append(_flag_param(f["name"]))
    # Args
    for a in cmd_def.get("args", []):
        params.append(a["name"])
    return params


def _collect_all_flag_defs(cmd_def: dict) -> list[dict]:
    """Collect all flag definitions (direct, from tags, from mutex)."""
    flags = list(cmd_def.get("flags", []))
    for tag in cmd_def.get("tags", []):
        flags.extend(tag["flags"])
    for mg in cmd_def.get("mutex", []):
        flags.extend(mg["flags"])
    return flags


def _emit_handler_body(cmd_def: dict) -> str:
    """Emit the handler body that prints the template-substituted output."""
    template = cmd_def["handler_prints"]
    all_flags = _collect_all_flag_defs(cmd_def)
    flag_types = {}
    for f in all_flags:
        flag_types[f["name"]] = f.get("type", "str")

    # Build a format expression
    params = _collect_params(cmd_def)
    if not params:
        return f"    print({template!r})"

    # We build the output using string concatenation to handle type formatting
    lines = []
    lines.append("    _parts = {}")
    for f in all_flags:
        pname = _flag_param(f["name"])
        ftype = f.get("type", "str")
        if f.get("repeatable", False):
            # For repeatable, print comma-separated values
            if ftype == "int":
                lines.append(
                    f"    _parts[{f['name']!r}] = ','.join(str(x) for x in {pname})"
                )
            else:
                lines.append(
                    f"    _parts[{f['name']!r}] = ','.join(str(x) for x in {pname})"
                )
        elif ftype == "bool":
            lines.append(
                f"    _parts[{f['name']!r}] = 'true' if {pname} else 'false'"
            )
        else:
            lines.append(f"    _parts[{f['name']!r}] = str({pname})")

    for a in cmd_def.get("args", []):
        lines.append(f"    _parts[{a['name']!r}] = str({a['name']})")

    lines.append(f"    _template = {template!r}")
    lines.append("    _out = _template")
    lines.append("    for _k, _v in _parts.items():")
    lines.append("        _out = _out.replace('{' + _k + '}', _v)")
    lines.append("    print(_out)")

    return "\n".join(lines)


def _emit_command_registration(
    cmd_def: dict, target: str, indent: str = ""
) -> str:
    """Emit the code to register a command on a target (app or group variable name).

    Returns multi-line code string.
    """
    lines = []
    params = _collect_params(cmd_def)

    # Build decorator kwargs
    decorator_parts = [f"{indent}@{target}.command("]
    decorator_parts.append(f"{indent}    {cmd_def['name']!r},")
    decorator_parts.append(f"{indent}    help={cmd_def['help']!r},")

    # args
    if cmd_def.get("args"):
        arg_exprs = []
        for a in cmd_def["args"]:
            aparts = [f"name={a['name']!r}", f"help={a['help']!r}"]
            if "required" in a:
                aparts.append(f"required={a['required']!r}")
            if "default" in a:
                aparts.append(f"default={a['default']!r}")
            arg_exprs.append(f"strictcli.Arg({', '.join(aparts)})")
        decorator_parts.append(
            f"{indent}    args=[{', '.join(arg_exprs)}],"
        )

    # tags
    if cmd_def.get("tags"):
        tag_exprs = [_emit_tag(t, indent + "        ") for t in cmd_def["tags"]]
        decorator_parts.append(f"{indent}    tags=[")
        for te in tag_exprs:
            decorator_parts.append(f"{te},")
        decorator_parts.append(f"{indent}    ],")

    # mutex
    if cmd_def.get("mutex"):
        mutex_exprs = [_emit_mutex(m, indent + "        ") for m in cmd_def["mutex"]]
        decorator_parts.append(f"{indent}    mutex=[")
        for me in mutex_exprs:
            decorator_parts.append(f"{me},")
        decorator_parts.append(f"{indent}    ],")

    decorator_parts.append(f"{indent})")

    # Flag decorators (for direct flags)
    flag_decorators = []
    for f in cmd_def.get("flags", []):
        fd_parts = [f"{f['name']!r}"]
        ftype = f.get("type", "str")
        if ftype != "str":
            fd_parts.append(f"type={ftype}")
        fd_parts.append(f"help={f['help']!r}")
        if "short" in f:
            fd_parts.append(f"short={f['short']!r}")
        if "default" in f:
            default = f["default"]
            if default is None:
                fd_parts.append("default=None")
            elif isinstance(default, bool):
                fd_parts.append(f"default={default}")
            elif isinstance(default, int):
                fd_parts.append(f"default={default}")
            else:
                fd_parts.append(f"default={default!r}")
        if "env" in f:
            fd_parts.append(f"env={f['env']!r}")
        if "prefixed" in f:
            fd_parts.append(f"prefixed={f['prefixed']!r}")
        if "choices_str" in f:
            fd_parts.append(f"choices={f['choices_str']!r}")
        if "choices_int" in f:
            fd_parts.append(f"choices={f['choices_int']!r}")
        if f.get("repeatable", False):
            fd_parts.append("repeatable=True")
        flag_decorators.append(
            f"{indent}@strictcli.flag({', '.join(fd_parts)})"
        )

    # Handler function
    # For optional args with no default, set handler param default to None
    param_strs = []
    for p in params:
        # Check if this param corresponds to an optional arg without a default
        is_optional_no_default = False
        for a in cmd_def.get("args", []):
            if a["name"] == p and not a.get("required", True) and "default" not in a:
                is_optional_no_default = True
                break
        if is_optional_no_default:
            param_strs.append(f"{p}=None")
        else:
            param_strs.append(p)
    param_str = ", ".join(param_strs)

    handler_body = _emit_handler_body(cmd_def)

    lines.extend(decorator_parts)
    for fd in flag_decorators:
        lines.append(fd)
    lines.append(f"{indent}def {cmd_def['name'].replace('-', '_')}_handler({param_str}):")
    lines.append(handler_body)
    lines.append("")

    return "\n".join(lines)


def generate(app_def: dict) -> str:
    """Generate a complete Python script from an app definition.

    Returns the script source as a string.
    """
    lines = []
    lines.append("import sys")
    lines.append("import os")
    lines.append("")
    lines.append("# Add strictcli to path")
    lines.append("sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))")
    lines.append("import strictcli")
    lines.append("")

    # Build app
    app_parts = [
        f"name={app_def['name']!r}",
        f"version={app_def['version']!r}",
        f"help={app_def['help']!r}",
    ]
    if "env_prefix" in app_def:
        app_parts.append(f"env_prefix={app_def['env_prefix']!r}")

    lines.append(f"app = strictcli.App({', '.join(app_parts)})")
    lines.append("")

    # Register groups first
    for group_def in app_def.get("groups", []):
        gvar = f"group_{group_def['name'].replace('-', '_')}"
        lines.append(
            f"{gvar} = app.group({group_def['name']!r}, help={group_def['help']!r})"
        )
        lines.append("")
        for cmd_def in group_def.get("commands", []):
            lines.append(_emit_command_registration(cmd_def, gvar))

    # Register top-level commands
    for cmd_def in app_def.get("commands", []):
        lines.append(_emit_command_registration(cmd_def, "app"))

    lines.append("app.run()")
    lines.append("")

    return "\n".join(lines)
