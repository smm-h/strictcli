"""Generate a temporary Python script from a conformance test case's app definition.

The generated script imports strictcli, builds the app as described by the JSON
definition, registers handlers that print template-substituted output, and calls
app.run().
"""

from __future__ import annotations

import json
import keyword
import textwrap


def _flag_param(name: str) -> str:
    """Convert a flag name to a Python parameter name (e.g. dry-run -> dry_run).

    If the result is a Python keyword (e.g. 'global', 'class'), appends '_'
    per PEP 8 convention to match strictcli's _flag_param_name().
    """
    result = name.replace("-", "_")
    if keyword.iskeyword(result):
        result += "_"
    return result


def _emit_flag(flag_def: dict, indent: str = "") -> str:
    """Emit a strictcli.Flag(...) expression from a flag JSON definition."""
    parts = [
        f"name={flag_def['name']!r}",
    ]
    ftype = flag_def.get("type", "str")
    scalar_type_map = {"str": "str", "bool": "bool", "int": "int", "float": "float"}
    compound_type_map = {
        "list[str]": "list[str]", "list[int]": "list[int]", "list[float]": "list[float]",
        "dict[str,str]": "dict[str, str]", "dict[str,int]": "dict[str, int]",
        "dict[str,float]": "dict[str, float]",
    }
    if ftype in compound_type_map:
        parts.append(f"type={compound_type_map[ftype]}")
    else:
        parts.append(f"type={scalar_type_map[ftype]}")
    parts.append(f"help={flag_def['help']!r}")

    if "short" in flag_def:
        parts.append(f"short={flag_def['short']!r}")

    if "default" in flag_def:
        default = flag_def["default"]
        if default is None:
            parts.append("default=None")
        elif isinstance(default, bool):
            parts.append(f"default={default}")
        elif isinstance(default, (int, float)):
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

    if "choices_float" in flag_def:
        parts.append(f"choices={flag_def['choices_float']!r}")

    if flag_def.get("repeatable", False):
        parts.append("repeatable=True")

    if "unique" in flag_def:
        parts.append(f"unique={flag_def['unique']}")

    if "env_separator" in flag_def:
        parts.append(f"env_separator={flag_def['env_separator']!r}")

    if "negatable" in flag_def and not flag_def["negatable"]:
        parts.append("negatable=False")

    return f"{indent}strictcli.Flag({', '.join(parts)})"


def _emit_flag_set(fs_def: dict, indent: str = "") -> str:
    """Emit a strictcli.FlagSet(...) expression."""
    flag_lines = [_emit_flag(f, indent + "        ") for f in fs_def["flags"]]
    flags_str = ",\n".join(flag_lines)
    return (
        f"{indent}strictcli.FlagSet(\n"
        f"{indent}    name={fs_def['name']!r},\n"
        f"{indent}    flags=[\n"
        f"{flags_str},\n"
        f"{indent}    ],\n"
        f"{indent})"
    )


def _emit_mutex(mutex_def: dict, indent: str = "") -> str:
    """Emit a strictcli.MutexGroup(...) expression."""
    flag_lines = [_emit_flag(f, indent + "        ") for f in mutex_def["flags"]]
    flags_str = ",\n".join(flag_lines)
    return (
        f"{indent}strictcli.MutexGroup(\n"
        f"{indent}    flags=[\n"
        f"{flags_str},\n"
        f"{indent}    ],\n"
        f"{indent})"
    )


def _collect_params(cmd_def: dict, global_flags: list[dict] | None = None) -> list[str]:
    """Collect all parameter names for a command handler."""
    params = []
    # Global flags (passed as kwargs to all handlers)
    for f in (global_flags or []):
        params.append(_flag_param(f["name"]))
    # Flags from direct flags, flag sets, and mutex groups
    for f in cmd_def.get("flags", []):
        params.append(_flag_param(f["name"]))
    for fs in cmd_def.get("flag_sets", []):
        for f in fs["flags"]:
            params.append(_flag_param(f["name"]))
    for mg in cmd_def.get("mutex", []):
        for f in mg["flags"]:
            params.append(_flag_param(f["name"]))
    # Args
    for a in cmd_def.get("args", []):
        params.append(a["name"])
    return params


def _collect_all_flag_defs(cmd_def: dict, global_flags: list[dict] | None = None) -> list[dict]:
    """Collect all flag definitions (global, direct, from flag sets, from mutex)."""
    flags = list(global_flags or [])
    flags.extend(cmd_def.get("flags", []))
    for fs in cmd_def.get("flag_sets", []):
        flags.extend(fs["flags"])
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
        if ftype.startswith("list["):
            # List compound type: print comma-separated
            lines.append(
                f"    _parts[{f['name']!r}] = ','.join(str(x) for x in {pname})"
            )
        elif ftype.startswith("dict["):
            # Dict compound type: print key=value pairs comma-separated
            lines.append(
                f"    _parts[{f['name']!r}] = ','.join(f'{{k}}={{v}}' for k, v in {pname}.items())"
            )
        elif f.get("repeatable", False):
            # For repeatable, print comma-separated values
            lines.append(
                f"    _parts[{f['name']!r}] = ','.join(str(x) for x in {pname})"
            )
        elif ftype == "bool":
            lines.append(
                f"    _parts[{f['name']!r}] = 'None' if {pname} is None else ('true' if {pname} else 'false')"
            )
        else:
            lines.append(f"    _parts[{f['name']!r}] = str({pname})")

    for a in cmd_def.get("args", []):
        atype = a.get("type", "str")
        if a.get("variadic", False):
            # Variadic: value is a list, print comma-separated
            lines.append(f"    _parts[{a['name']!r}] = ','.join(str(x) for x in {a['name']})")
        elif atype == "bool":
            lines.append(
                f"    _parts[{a['name']!r}] = 'true' if {a['name']} else 'false'"
            )
        else:
            lines.append(f"    _parts[{a['name']!r}] = str({a['name']})")

    lines.append(f"    _template = {template!r}")
    lines.append("    _out = _template")
    lines.append("    for _k, _v in _parts.items():")
    lines.append("        _out = _out.replace('{' + _k + '}', _v)")
    lines.append("    print(_out)")

    return "\n".join(lines)


def _emit_context_handler_body(cmd_def: dict, global_flags: list[dict] | None = None) -> str:
    """Emit the handler body for context-style handlers.

    The template uses {source:name} to print ctx.source(name) and
    {name} to print the flag value from kwargs.
    """
    import re
    template = cmd_def["handler_prints"]

    lines = []
    lines.append("    _out = ''")

    # Split template into parts: {source:name} refs and {name} refs and literals
    parts = re.split(r'\{(source:[^}]+|[^}]+)\}', template)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # Literal text
            if part:
                lines.append(f"    _out += {part!r}")
        else:
            if part.startswith("source:"):
                flag_name = part[7:]
                lines.append(f"    _out += ctx.source({flag_name!r})")
            else:
                # Value reference -- use kwargs
                param = _flag_param(part)
                lines.append(f"    _out += str({param})")

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

        # If the test case also specifies flags/args/flag_sets/mutex (registration error tests),
        # include them so the error is triggered
        if cmd_def.get("args"):
            arg_exprs = []
            for a in cmd_def["args"]:
                aparts = [f"name={a['name']!r}", f"help={a['help']!r}"]
                atype = a.get("type", "str")
                if atype != "str":
                    type_map = {"bool": "bool", "int": "int", "float": "float"}
                    aparts.append(f"type={type_map[atype]}")
                if "required" in a:
                    aparts.append(f"required={a['required']!r}")
                if "default" in a:
                    aparts.append(f"default={a['default']!r}")
                if a.get("variadic", False):
                    aparts.append("variadic=True")
                if "choices_str" in a:
                    aparts.append(f"choices={a['choices_str']!r}")
                if "choices_int" in a:
                    aparts.append(f"choices={a['choices_int']!r}")
                if "choices_float" in a:
                    aparts.append(f"choices={a['choices_float']!r}")
                arg_exprs.append(f"strictcli.Arg({', '.join(aparts)})")
            lines.append(
                f"{indent}    args=[{', '.join(arg_exprs)}],"
            )

        if cmd_def.get("flag_sets"):
            fs_exprs = [_emit_flag_set(t, indent + "        ") for t in cmd_def["flag_sets"]]
            lines.append(f"{indent}    flag_sets=[")
            for te in fs_exprs:
                lines.append(f"{te},")
            lines.append(f"{indent}    ],")

        if cmd_def.get("mutex"):
            mutex_exprs = [_emit_mutex(m, indent + "        ") for m in cmd_def["mutex"]]
            lines.append(f"{indent}    mutex=[")
            for me in mutex_exprs:
                lines.append(f"{me},")
            lines.append(f"{indent}    ],")

        if cmd_def.get("dependencies"):
            dep_exprs = []
            for dep in cmd_def["dependencies"]:
                if dep["type"] == "co_required":
                    flags_repr = repr(dep["flags"])
                    dep_exprs.append(f"strictcli.CoRequired(flags={flags_repr})")
                elif dep["type"] == "requires":
                    dep_exprs.append(
                        f"strictcli.Requires(flag={dep['flag']!r}, depends_on={dep['depends_on']!r})"
                    )
                elif dep["type"] == "implies":
                    val = "True" if dep["value"] else "False"
                    dep_exprs.append(
                        f"strictcli.Implies(flag={dep['flag']!r}, implies={dep['implies']!r}, value={val})"
                    )
            lines.append(f"{indent}    dependencies=[{', '.join(dep_exprs)}],")

        if cmd_def.get("tags"):
            tag_set = ", ".join(repr(t) for t in cmd_def["tags"])
            lines.append(f"{indent}    tags={{{tag_set}}},")
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
            atype = a.get("type", "str")
            if atype != "str":
                type_map = {"bool": "bool", "int": "int", "float": "float"}
                aparts.append(f"type={type_map[atype]}")
            if "required" in a:
                aparts.append(f"required={a['required']!r}")
            if "default" in a:
                aparts.append(f"default={a['default']!r}")
            if a.get("variadic", False):
                aparts.append("variadic=True")
            if "choices_str" in a:
                aparts.append(f"choices={a['choices_str']!r}")
            if "choices_int" in a:
                aparts.append(f"choices={a['choices_int']!r}")
            if "choices_float" in a:
                aparts.append(f"choices={a['choices_float']!r}")
            arg_exprs.append(f"strictcli.Arg({', '.join(aparts)})")
        decorator_parts.append(
            f"{indent}    args=[{', '.join(arg_exprs)}],"
        )

    # flag sets
    if cmd_def.get("flag_sets"):
        fs_exprs = [_emit_flag_set(t, indent + "        ") for t in cmd_def["flag_sets"]]
        decorator_parts.append(f"{indent}    flag_sets=[")
        for te in fs_exprs:
            decorator_parts.append(f"{te},")
        decorator_parts.append(f"{indent}    ],")

    # mutex
    if cmd_def.get("mutex"):
        mutex_exprs = [_emit_mutex(m, indent + "        ") for m in cmd_def["mutex"]]
        decorator_parts.append(f"{indent}    mutex=[")
        for me in mutex_exprs:
            decorator_parts.append(f"{me},")
        decorator_parts.append(f"{indent}    ],")

    # dependencies
    if cmd_def.get("dependencies"):
        dep_exprs = []
        for dep in cmd_def["dependencies"]:
            if dep["type"] == "co_required":
                flags_repr = repr(dep["flags"])
                dep_exprs.append(f"strictcli.CoRequired(flags={flags_repr})")
            elif dep["type"] == "requires":
                dep_exprs.append(
                    f"strictcli.Requires(flag={dep['flag']!r}, depends_on={dep['depends_on']!r})"
                )
            elif dep["type"] == "implies":
                val = "True" if dep["value"] else "False"
                dep_exprs.append(
                    f"strictcli.Implies(flag={dep['flag']!r}, implies={dep['implies']!r}, value={val})"
                )
        decorator_parts.append(f"{indent}    dependencies=[{', '.join(dep_exprs)}],")

    # tags
    if cmd_def.get("tags"):
        tag_set = ", ".join(repr(t) for t in cmd_def["tags"])
        decorator_parts.append(f"{indent}    tags={{{tag_set}}},")

    # config_fields
    if cmd_def.get("config_fields"):
        cf_list = repr(cmd_def["config_fields"])
        decorator_parts.append(f"{indent}    config_fields={cf_list},")

    # hidden
    if cmd_def.get("hidden", False):
        decorator_parts.append(f"{indent}    hidden=True,")

    # interactive
    if cmd_def.get("interactive", False):
        decorator_parts.append(f"{indent}    interactive=True,")

    decorator_parts.append(f"{indent})")

    # Flag decorators (for direct flags)
    compound_type_map = {
        "list[str]": "list[str]", "list[int]": "list[int]", "list[float]": "list[float]",
        "dict[str,str]": "dict[str, str]", "dict[str,int]": "dict[str, int]",
        "dict[str,float]": "dict[str, float]",
    }
    flag_decorators = []
    for f in cmd_def.get("flags", []):
        fd_parts = [f"{f['name']!r}"]
        ftype = f.get("type", "str")
        if ftype in compound_type_map:
            fd_parts.append(f"type={compound_type_map[ftype]}")
        elif ftype != "str":
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
            elif isinstance(default, (int, float)):
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
        if "choices_float" in f:
            fd_parts.append(f"choices={f['choices_float']!r}")
        if f.get("repeatable", False):
            fd_parts.append("repeatable=True")
        if "unique" in f:
            fd_parts.append(f"unique={f['unique']}")
        if "env_separator" in f:
            fd_parts.append(f"env_separator={f['env_separator']!r}")
        if "negatable" in f and not f["negatable"]:
            fd_parts.append("negatable=False")
        flag_decorators.append(
            f"{indent}@strictcli.flag({', '.join(fd_parts)})"
        )

    # Handler function
    # For optional args with no default, set handler param default to None
    # For variadic optional args, default to empty list
    # De-duplicate params to avoid SyntaxError (library validation catches duplicates at registration)
    seen_params = set()
    unique_params = []
    for p in params:
        if p not in seen_params:
            seen_params.add(p)
            unique_params.append(p)
    params = unique_params

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

    handler_style = cmd_def.get("handler_style", "classic")

    if handler_style == "context":
        handler_body = _emit_context_handler_body(cmd_def, global_flags)
        lines.extend(decorator_parts)
        for fd in flag_decorators:
            lines.append(fd)
        # Context handler: first param is ctx with type annotation
        lines.append(f"{indent}def {cmd_def['name'].replace('-', '_')}_handler(ctx: strictcli.Context, {param_str}):")
        lines.append(handler_body)
        if exit_code != 0:
            lines.append(f"{indent}    return {exit_code}")
        else:
            lines.append(f"{indent}    return 0")
        lines.append("")
    else:
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
    has_checks = bool(app_def.get("checks_toml"))

    lines = []
    lines.append("import sys")
    lines.append("import os")
    if has_checks:
        lines.append("import hashlib")
        lines.append("import pathlib")
    lines.append("")
    lines.append("# Add strictcli to path")
    lines.append("sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))")
    lines.append("import strictcli")
    lines.append("")

    # Write checks.toml to a temp file and pass via checks_path=
    if has_checks:
        checks_toml = app_def["checks_toml"]
        lines.append("# Write checks.toml to a deterministic temp path")
        lines.append(f"_hash = hashlib.sha256({checks_toml!r}.encode()).hexdigest()[:12]")
        lines.append("_checks_path = os.path.join(os.environ.get('TMPDIR', '/tmp'), f'strictcli-checks-{_hash}.toml')")
        lines.append(f"with open(_checks_path, 'w') as _f:")
        lines.append(f"    _f.write({checks_toml!r})")
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
    if app_def.get("config", False):
        app_parts.append("config=True")
    if "config_path" in app_def and app_def["config_path"] is not None:
        app_parts.append(f"config_path={app_def['config_path']!r}")
    if "config_format" in app_def and app_def["config_format"] != "json":
        app_parts.append(f"config_format={app_def['config_format']!r}")
    if has_checks:
        app_parts.append("checks_path=_checks_path")
    if global_flags:
        gf_exprs = [_emit_flag(gf) for gf in global_flags]
        app_parts.append(f"flags=[{', '.join(gf_exprs)}]")

    lines.append("try:")
    lines.append(f"    app = strictcli.App({', '.join(app_parts)})")
    lines.append("")

    # Register config fields (before commands, since commands may bind to them)
    for cf_def in app_def.get("config_fields_def", []):
        cf_parts = [f"{cf_def['name']!r}", f"type={cf_def['type']!s}"]
        cf_parts.append(f"help={cf_def['help']!r}")
        if "default" in cf_def:
            cf_parts.append(f"default={cf_def['default']!r}")
        lines.append(f"    app.config_field({', '.join(cf_parts)})")
    if app_def.get("config_fields_def"):
        lines.append("")

    # Register groups first (recursive helper for nested groups)
    def _emit_group(group_def: dict, parent_var: str, indent: str) -> None:
        gvar = f"group_{group_def['name'].replace('-', '_')}"
        tags_arg = ""
        if group_def.get("tags"):
            tag_set = ", ".join(repr(t) for t in group_def["tags"])
            tags_arg = f", tags={{{tag_set}}}"
        hidden_arg = ""
        if group_def.get("hidden", False):
            hidden_arg = ", hidden=True"
        lines.append(
            f"{indent}{gvar} = {parent_var}.group({group_def['name']!r}, help={group_def['help']!r}{tags_arg}{hidden_arg})"
        )
        lines.append("")
        for cmd_def in group_def.get("commands", []):
            if cmd_def.get("deprecated"):
                lines.append(
                    f"{indent}{gvar}.deprecate({cmd_def['name']!r}, message={cmd_def.get('deprecated_message', '')!r})"
                )
                lines.append("")
            else:
                lines.append(textwrap.indent(_emit_command_registration(
                    cmd_def, gvar, global_flags=global_flags,
                ), indent))
        for sub_group_def in group_def.get("groups", []):
            _emit_group(sub_group_def, gvar, indent)

    for group_def in app_def.get("groups", []):
        _emit_group(group_def, "app", "    ")

    # Register top-level commands
    for cmd_def in app_def.get("commands", []):
        if cmd_def.get("deprecated"):
            lines.append(
                f"    app.deprecate({cmd_def['name']!r}, message={cmd_def.get('deprecated_message', '')!r})"
            )
            lines.append("")
        else:
            lines.append(textwrap.indent(_emit_command_registration(
                cmd_def, "app", global_flags=global_flags,
            ), "    "))

    # Register tag contracts
    for tag, contract in app_def.get("tag_contracts", {}).items():
        lines.append(f"    app.tag_contract({tag!r}, requires_flag={contract['requires_flag']!r})")
    if app_def.get("tag_contracts"):
        lines.append("")

    # Register checks if defined
    if has_checks:
        for check_def in app_def.get("checks", []):
            cname = check_def["name"]
            cstatus = check_def["check_returns"]
            cmessage = check_def["check_message"]
            cdetails = check_def.get("check_details", [])
            lines.append(f"    @app.check({cname!r})")
            lines.append(f"    def check_{cname.replace('-', '_')}(ctx):")
            lines.append(f"        return strictcli.CheckResult(status={cstatus!r}, message={cmessage!r}, details={cdetails!r})")
            lines.append("")

        lines.append("    class _CheckCtx:")
        lines.append("        project_root = pathlib.Path('.')")
        lines.append("")
        lines.append("    app.set_check_context(lambda: _CheckCtx())")
        lines.append("")

    # Write config_content_late AFTER construction but BEFORE run
    if "config_content_late" in app_def:
        late_content = app_def["config_content_late"]
        config_path_expr = f"app._config_path_override" if "config_path" in app_def else "None"
        lines.append(f"    # Write late config content")
        lines.append(f"    with open({app_def['config_path']!r}, 'w') as _lcf:")
        lines.append(f"        _lcf.write({late_content!r})")
        lines.append("")

    lines.append("    app.run()")
    lines.append("except ValueError as e:")
    lines.append("    print(f'error: {e}', file=sys.stderr)")
    lines.append("    sys.exit(1)")
    lines.append("")

    return "\n".join(lines)
