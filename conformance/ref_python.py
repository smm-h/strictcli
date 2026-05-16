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

    if "negatable" in flag_def and not flag_def["negatable"]:
        parts.append("negatable=False")

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


def _collect_params(cmd_def: dict, global_flags: list[dict] | None = None) -> list[str]:
    """Collect all parameter names for a command handler."""
    params = []
    # Global flags (passed as kwargs to all handlers)
    for f in (global_flags or []):
        params.append(_flag_param(f["name"]))
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


def _collect_all_flag_defs(cmd_def: dict, global_flags: list[dict] | None = None) -> list[dict]:
    """Collect all flag definitions (global, direct, from tags, from mutex)."""
    flags = list(global_flags or [])
    flags.extend(cmd_def.get("flags", []))
    for tag in cmd_def.get("tags", []):
        flags.extend(tag["flags"])
    for mg in cmd_def.get("mutex", []):
        flags.extend(mg["flags"])
    return flags


def _emit_handler_body(cmd_def: dict, global_flags: list[dict] | None = None) -> str:
    """Emit the handler body that prints the template-substituted output."""
    template = cmd_def["handler_prints"]
    all_flags = _collect_all_flag_defs(cmd_def, global_flags)
    flag_types = {}
    for f in all_flags:
        flag_types[f["name"]] = f.get("type", "str")

    # Build a format expression
    params = _collect_params(cmd_def, global_flags)
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
        if a.get("variadic", False):
            # Variadic: value is a list, print comma-separated
            lines.append(f"    _parts[{a['name']!r}] = ','.join(str(x) for x in {a['name']})")
        else:
            lines.append(f"    _parts[{a['name']!r}] = str({a['name']})")

    lines.append(f"    _template = {template!r}")
    lines.append("    _out = _template")
    lines.append("    for _k, _v in _parts.items():")
    lines.append("        _out = _out.replace('{' + _k + '}', _v)")
    lines.append("    print(_out)")

    return "\n".join(lines)


def _emit_command_registration(
    cmd_def: dict, target: str, indent: str = "",
    global_flags: list[dict] | None = None,
) -> str:
    """Emit the code to register a command on a target (app or group variable name).

    Returns multi-line code string.
    """
    lines = []
    is_passthrough = cmd_def.get("passthrough", False)
    exit_code = cmd_def.get("handler_exit_code", 0)

    # --- Passthrough command ---
    if is_passthrough:
        handler_name = cmd_def['name'].replace('-', '_') + '_passthrough_handler'
        # Define the passthrough handler function first
        # Signature: func(name: str, args: list[str], globals: dict) -> int
        lines.append(f"{indent}def {handler_name}(name, args, globals):")
        if global_flags:
            # Print global flag values first
            for gf in global_flags:
                gf_name = gf["name"]
                ftype = gf.get("type", "str")
                if ftype == "bool":
                    lines.append(
                        f'{indent}    print({gf_name!r} + "=" + ("true" if globals[{gf_name!r}] else "false"))'
                    )
                else:
                    lines.append(
                        f'{indent}    print({gf_name!r} + "=" + str(globals[{gf_name!r}]))'
                    )
        # Print using passthrough_handler_prints template, or default format
        pt_template = cmd_def.get("passthrough_handler_prints")
        if pt_template:
            # Build the output by substituting {name} and {args} in the template
            lines.append(f'{indent}    _pt_out = {pt_template!r}')
            lines.append(f'{indent}    _pt_out = _pt_out.replace("{{name}}", name)')
            lines.append(f'{indent}    _pt_out = _pt_out.replace("{{args}}", ",".join(args))')
            lines.append(f'{indent}    print(_pt_out)')
        else:
            lines.append(f'{indent}    print(name + ":" + ",".join(args))')
        lines.append(f"{indent}    return {exit_code}")
        lines.append("")

        # Register the command with passthrough=Passthrough(handler=...)
        lines.append(f"{indent}@{target}.command(")
        lines.append(f"{indent}    {cmd_def['name']!r},")
        lines.append(f"{indent}    help={cmd_def['help']!r},")

        # If the test case also specifies flags/args/tags/mutex (registration error tests),
        # include them so the error is triggered
        if cmd_def.get("args"):
            arg_exprs = []
            for a in cmd_def["args"]:
                aparts = [f"name={a['name']!r}", f"help={a['help']!r}"]
                if "required" in a:
                    aparts.append(f"required={a['required']!r}")
                if "default" in a:
                    aparts.append(f"default={a['default']!r}")
                if a.get("variadic", False):
                    aparts.append("variadic=True")
                arg_exprs.append(f"strictcli.Arg({', '.join(aparts)})")
            lines.append(
                f"{indent}    args=[{', '.join(arg_exprs)}],"
            )

        lines.append(f"{indent}    passthrough=strictcli.Passthrough(handler={handler_name}),")
        lines.append(f"{indent})")

        # Emit flag decorators if present (for registration error tests)
        flag_decorators = []
        for f in cmd_def.get("flags", []):
            fd_parts = [f"{f['name']!r}"]
            ftype = f.get("type", "str")
            if ftype != "str":
                fd_parts.append(f"type={ftype}")
            fd_parts.append(f"help={f['help']!r}")
            flag_decorators.append(
                f"{indent}@strictcli.flag({', '.join(fd_parts)})"
            )
        for fd in flag_decorators:
            lines.append(fd)

        # The decorated function is a dummy (ignored for passthrough commands)
        dummy_name = cmd_def['name'].replace('-', '_') + '_cmd'
        lines.append(f"{indent}def {dummy_name}():")
        lines.append(f"{indent}    pass")
        lines.append("")
        return "\n".join(lines)

    # --- Normal command ---
    params = _collect_params(cmd_def, global_flags)

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
            if a.get("variadic", False):
                aparts.append("variadic=True")
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
        if "negatable" in f and not f["negatable"]:
            fd_parts.append("negatable=False")
        flag_decorators.append(
            f"{indent}@strictcli.flag({', '.join(fd_parts)})"
        )

    # Handler function
    # For optional args with no default, set handler param default to None
    # For variadic optional args, default to empty list
    param_strs = []
    for p in params:
        # Check if this param corresponds to an optional arg without a default
        is_optional_no_default = False
        is_variadic_optional = False
        for a in cmd_def.get("args", []):
            if a["name"] == p and a.get("variadic", False) and not a.get("required", True):
                is_variadic_optional = True
                break
            if a["name"] == p and not a.get("required", True) and "default" not in a:
                is_optional_no_default = True
                break
        if is_variadic_optional:
            param_strs.append(p)
        elif is_optional_no_default:
            param_strs.append(f"{p}=None")
        else:
            param_strs.append(p)
    param_str = ", ".join(param_strs)

    handler_body = _emit_handler_body(cmd_def, global_flags)

    lines.extend(decorator_parts)
    for fd in flag_decorators:
        lines.append(fd)
    lines.append(f"{indent}def {cmd_def['name'].replace('-', '_')}_handler({param_str}):")
    lines.append(handler_body)
    if exit_code != 0:
        lines.append(f"{indent}    return {exit_code}")
    else:
        lines.append(f"{indent}    return 0")
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
    global_flags = app_def.get("global_flags", [])
    app_parts = [
        f"name={app_def['name']!r}",
        f"version={app_def['version']!r}",
        f"help={app_def['help']!r}",
    ]
    if "env_prefix" in app_def:
        app_parts.append(f"env_prefix={app_def['env_prefix']!r}")
    if global_flags:
        gf_exprs = [_emit_flag(gf) for gf in global_flags]
        app_parts.append(f"flags=[{', '.join(gf_exprs)}]")

    lines.append("try:")
    lines.append(f"    app = strictcli.App({', '.join(app_parts)})")
    lines.append("")

    # Register groups first
    for group_def in app_def.get("groups", []):
        gvar = f"group_{group_def['name'].replace('-', '_')}"
        lines.append(
            f"    {gvar} = app.group({group_def['name']!r}, help={group_def['help']!r})"
        )
        lines.append("")
        for cmd_def in group_def.get("commands", []):
            lines.append(textwrap.indent(_emit_command_registration(
                cmd_def, gvar, global_flags=global_flags,
            ), "    "))

    # Register top-level commands
    for cmd_def in app_def.get("commands", []):
        lines.append(textwrap.indent(_emit_command_registration(
            cmd_def, "app", global_flags=global_flags,
        ), "    "))

    lines.append("    app.run()")
    lines.append("except ValueError as e:")
    lines.append("    print(f'error: {e}', file=sys.stderr)")
    lines.append("    sys.exit(1)")
    lines.append("")

    return "\n".join(lines)
