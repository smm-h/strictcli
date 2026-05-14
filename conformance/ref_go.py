"""Generate a temporary Go main.go from a conformance test case's app definition.

The generated code imports the go-strictcli package, builds the app as described
by the JSON definition, registers handlers that print template-substituted
output, and calls app.Run().
"""

from __future__ import annotations

import json


def _flag_param(name: str) -> str:
    """Convert a flag name to a Go map key (e.g. dry-run -> dry_run)."""
    return name.replace("-", "_")


def _emit_flag_opts(flag_def: dict) -> list[str]:
    """Return a list of FlagOption expressions for a flag definition."""
    opts = []
    if "short" in flag_def:
        opts.append(f'strictcli.Short("{flag_def["short"]}")')
    if "default" in flag_def:
        default = flag_def["default"]
        if default is None:
            opts.append("strictcli.Default(nil)")
        elif isinstance(default, bool):
            if default:
                opts.append("strictcli.Default(true)")
            else:
                opts.append("strictcli.Default(false)")
        elif isinstance(default, int):
            opts.append(f"strictcli.Default({default})")
        else:
            opts.append(f'strictcli.Default("{default}")')
    if "env" in flag_def:
        opts.append(f'strictcli.Env("{flag_def["env"]}")')
    if "prefixed" in flag_def:
        if flag_def["prefixed"]:
            opts.append("strictcli.Prefixed(true)")
        else:
            opts.append("strictcli.Prefixed(false)")
    if "choices_str" in flag_def:
        args = ", ".join(f'"{c}"' for c in flag_def["choices_str"])
        opts.append(f"strictcli.Choices({args})")
    if "choices_int" in flag_def:
        args = ", ".join(str(c) for c in flag_def["choices_int"])
        opts.append(f"strictcli.Choices({args})")
    if flag_def.get("repeatable", False):
        opts.append("strictcli.Repeatable()")
    return opts


def _emit_flag(flag_def: dict) -> str:
    """Emit a strictcli.StringFlag/BoolFlag/IntFlag(...) call."""
    ftype = flag_def.get("type", "str")
    type_map = {"str": "StringFlag", "bool": "BoolFlag", "int": "IntFlag"}
    constructor = type_map[ftype]
    opts = _emit_flag_opts(flag_def)
    opts_str = ""
    if opts:
        opts_str = ", " + ", ".join(opts)
    return f'strictcli.{constructor}("{flag_def["name"]}", "{flag_def["help"]}"{opts_str})'


def _emit_arg(arg_def: dict) -> str:
    """Emit a strictcli.NewArg(...) call."""
    opts = []
    if "required" in arg_def:
        if arg_def["required"]:
            opts.append("strictcli.ArgRequired(true)")
        else:
            opts.append("strictcli.ArgRequired(false)")
    if "default" in arg_def:
        default = arg_def["default"]
        if default is None:
            opts.append("strictcli.ArgDefault(nil)")
        else:
            opts.append(f'strictcli.ArgDefault("{default}")')
    opts_str = ""
    if opts:
        opts_str = ", " + ", ".join(opts)
    return f'strictcli.NewArg("{arg_def["name"]}", "{arg_def["help"]}"{opts_str})'


def _collect_all_flag_defs(cmd_def: dict) -> list[dict]:
    """Collect all flag definitions (direct, from tags, from mutex)."""
    flags = list(cmd_def.get("flags", []))
    for tag in cmd_def.get("tags", []):
        flags.extend(tag["flags"])
    for mg in cmd_def.get("mutex", []):
        flags.extend(mg["flags"])
    return flags


def _emit_handler_body(cmd_def: dict, indent: str) -> str:
    """Emit the Go handler body that prints the template-substituted output."""
    template = cmd_def["handler_prints"]
    all_flags = _collect_all_flag_defs(cmd_def)

    # Collect all parameter names (flags then args)
    params = []
    for f in all_flags:
        params.append((_flag_param(f["name"]), f["name"], "flag", f))
    for a in cmd_def.get("args", []):
        params.append((a["name"], a["name"], "arg", a))

    if not params:
        return f'{indent}fmt.Println("{template}")'

    lines = []
    lines.append(f'{indent}_out := "{template}"')

    for param_key, orig_name, kind, defn in params:
        if kind == "flag":
            ftype = defn.get("type", "str")
            if defn.get("repeatable", False):
                # Repeatable: value is []string or []int
                if ftype == "int":
                    lines.append(f'{indent}{{')
                    lines.append(f'{indent}\traw := args["{param_key}"]')
                    lines.append(f'{indent}\tvar parts []string')
                    lines.append(f'{indent}\tif raw != nil {{')
                    lines.append(f'{indent}\t\tfor _, v := range raw.([]interface{{}}) {{')
                    lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%d", v.(int)))')
                    lines.append(f'{indent}\t\t}}')
                    lines.append(f'{indent}\t}}')
                    lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", strings.Join(parts, ","))')
                    lines.append(f'{indent}}}')
                else:
                    lines.append(f'{indent}{{')
                    lines.append(f'{indent}\traw := args["{param_key}"]')
                    lines.append(f'{indent}\tvar parts []string')
                    lines.append(f'{indent}\tif raw != nil {{')
                    lines.append(f'{indent}\t\tfor _, v := range raw.([]interface{{}}) {{')
                    lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%v", v))')
                    lines.append(f'{indent}\t\t}}')
                    lines.append(f'{indent}\t}}')
                    lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", strings.Join(parts, ","))')
                    lines.append(f'{indent}}}')
            elif ftype == "bool":
                lines.append(f'{indent}if args["{param_key}"].(bool) {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "true")')
                lines.append(f'{indent}}} else {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "false")')
                lines.append(f'{indent}}}')
            elif ftype == "int":
                lines.append(f'{indent}_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%d", args["{param_key}"].(int)))')
            else:
                # str -- might be nil for mutex flags with default=null
                lines.append(f'{indent}if args["{param_key}"] != nil {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%v", args["{param_key}"]))')
                lines.append(f'{indent}}} else {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "None")')
                lines.append(f'{indent}}}')
        else:
            # arg -- always a string or nil
            lines.append(f'{indent}if args["{param_key}"] != nil {{')
            lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%v", args["{param_key}"]))')
            lines.append(f'{indent}}} else {{')
            lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "None")')
            lines.append(f'{indent}}}')

    lines.append(f'{indent}fmt.Println(_out)')
    return "\n".join(lines)


def _emit_cmd_options(cmd_def: dict, indent: str) -> list[str]:
    """Build the list of CmdOption expressions for a command registration."""
    opts = []

    # Args
    if cmd_def.get("args"):
        arg_exprs = [_emit_arg(a) for a in cmd_def["args"]]
        inner = ", ".join(arg_exprs)
        opts.append(f"strictcli.WithArgs({inner})")

    # Direct flags
    if cmd_def.get("flags"):
        flag_exprs = [_emit_flag(f) for f in cmd_def["flags"]]
        inner = ", ".join(flag_exprs)
        opts.append(f"strictcli.WithFlags({inner})")

    # Tags
    if cmd_def.get("tags"):
        for tag in cmd_def["tags"]:
            flag_exprs = [_emit_flag(f) for f in tag["flags"]]
            inner = ", ".join(flag_exprs)
            opts.append(f'strictcli.WithTags(strictcli.Tag{{Name: "{tag["name"]}", Flags: []strictcli.Flag{{{inner}}}}})')

    # Mutex groups
    if cmd_def.get("mutex"):
        for mg in cmd_def["mutex"]:
            flag_exprs = [_emit_flag(f) for f in mg["flags"]]
            inner = ", ".join(flag_exprs)
            required = "true" if mg.get("required", False) else "false"
            opts.append(f"strictcli.WithMutex(strictcli.MutexGroup{{Flags: []strictcli.Flag{{{inner}}}, Required: {required}}})")

    return opts


def generate(app_def: dict) -> str:
    """Generate a complete Go main.go from an app definition.

    Returns the source code as a string.
    """
    lines = []
    lines.append("package main")
    lines.append("")
    lines.append("import (")
    lines.append('\t"fmt"')
    lines.append('\t"strings"')
    lines.append("")
    lines.append('\t"github.com/smm-h/strictcli/go/strictcli"')
    lines.append(")")
    lines.append("")
    # Suppress unused-import errors if template has no substitutions
    lines.append("var _ = fmt.Println")
    lines.append("var _ = strings.ReplaceAll")
    lines.append("")
    lines.append("func main() {")

    # Build app
    app_opts = []
    if "env_prefix" in app_def:
        app_opts.append(f'strictcli.WithEnvPrefix("{app_def["env_prefix"]}")')
    opts_str = ""
    if app_opts:
        opts_str = ", " + ", ".join(app_opts)
    lines.append(f'\tapp := strictcli.NewApp("{app_def["name"]}", "{app_def["version"]}", "{app_def["help"]}"{opts_str})')
    lines.append("")

    # Register groups first
    for group_def in app_def.get("groups", []):
        gvar = f"group_{group_def['name'].replace('-', '_')}"
        lines.append(f'\t{gvar} := app.Group("{group_def["name"]}", "{group_def["help"]}")')
        lines.append("")
        for cmd_def in group_def.get("commands", []):
            handler_body = _emit_handler_body(cmd_def, "\t\t")
            cmd_opts = _emit_cmd_options(cmd_def, "\t\t")
            opts_args = ""
            if cmd_opts:
                opts_args = ", " + ", ".join(cmd_opts)
            lines.append(f'\t{gvar}.Command("{cmd_def["name"]}", "{cmd_def["help"]}", func(args map[string]interface{{}}) {{')
            lines.append(handler_body)
            lines.append(f"\t}}{opts_args})")
            lines.append("")

    # Register top-level commands
    for cmd_def in app_def.get("commands", []):
        handler_body = _emit_handler_body(cmd_def, "\t\t")
        cmd_opts = _emit_cmd_options(cmd_def, "\t\t")
        opts_args = ""
        if cmd_opts:
            opts_args = ", " + ", ".join(cmd_opts)
        lines.append(f'\tapp.Command("{cmd_def["name"]}", "{cmd_def["help"]}", func(args map[string]interface{{}}) {{')
        lines.append(handler_body)
        lines.append(f"\t}}{opts_args})")
        lines.append("")

    lines.append("\tapp.Run()")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)
