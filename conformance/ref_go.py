"""Generate a temporary Go main.go from a conformance test case's app definition.

The generated code imports the go-strictcli package, builds the app as described
by the JSON definition, registers handlers that print template-substituted
output, and calls app.Run().
"""

from __future__ import annotations

import json
import tomllib


def _check_severities(checks_toml: str) -> dict[str, str]:
    """Parse the embedded checks_toml and return a name->severity map.

    The Go registration form (RegisterErrorCheck vs RegisterWarnCheck) is derived
    from severity -- there is no per-check registration field in the case fixture.
    """
    data = tomllib.loads(checks_toml)
    return {name: c["severity"] for name, c in data.get("checks", {}).items()}


def _go_str(s: str) -> str:
    """Escape a Python string into a Go double-quoted string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit_check_impl_body_go(check_def: dict, indent: str) -> list[str]:
    """Emit the reporter-minting body lines of a Go check impl.

    Shared by TOML-declared checks (RegisterErrorCheck / RegisterWarnCheck) and
    provider-sourced specs (NewErrorCheckSpec / NewWarnCheckSpec impls). Both
    receive ``(ctx, r)``; the body mints any problems then returns a terminal
    outcome via the reporter ``r``.
    """
    mint = check_def["mint"]
    message = check_def["message"]
    problems = check_def.get("problems", [])
    notes = check_def.get("notes", [])
    mint_method = {"passed": "Passed", "skipped": "Skipped", "found": "Found"}[mint]
    body = []
    for n in notes:
        body.append(f'{indent}r.Note({_go_str(n)})')
    for p in problems:
        pmethod = "Error" if p["severity"] == "error" else "Warn"
        body.append(f'{indent}r.{pmethod}({_go_str(p["text"])})')
    body.append(f'{indent}return r.{mint_method}({_go_str(message)})')
    return body


def _flag_param(name: str) -> str:
    """Convert a flag name to a Go map key (e.g. dry-run -> dry_run)."""
    return name.replace("-", "_")


def _emit_flag_opts(flag_def: dict) -> list[str]:
    """Return a list of FlagOption expressions for a flag definition."""
    opts = []
    if "short" in flag_def:
        opts.append(f'strictcli.Short("{flag_def["short"]}")')
    if "default_relative_to_root" in flag_def:
        rtr = flag_def["default_relative_to_root"]
        rtr_args = ", ".join([f'"{rtr["env_var"]}"'] + [f'"{p}"' for p in rtr.get("parts", [])])
        opts.append(f"strictcli.Default(strictcli.RelativeToRoot({rtr_args}))")
    elif "default" in flag_def:
        default = flag_def["default"]
        if default is None:
            opts.append("strictcli.Default(nil)")
        elif isinstance(default, bool):
            if default:
                opts.append("strictcli.Default(true)")
            else:
                opts.append("strictcli.Default(false)")
        elif isinstance(default, list):
            elems = []
            for elem in default:
                if isinstance(elem, str):
                    elems.append(f'"{elem}"')
                elif isinstance(elem, float):
                    elems.append(f"{elem}")
                elif isinstance(elem, int):
                    elems.append(f"{elem}")
            joined = ", ".join(elems)
            opts.append("strictcli.Default([]interface{}{" + joined + "})")
        elif isinstance(default, float):
            opts.append(f"strictcli.Default({default})")
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
    if "choices_float" in flag_def:
        args = ", ".join(str(c) for c in flag_def["choices_float"])
        opts.append(f"strictcli.Choices({args})")
    if flag_def.get("repeatable", False):
        opts.append("strictcli.Repeatable()")
    if "unique" in flag_def:
        val = "true" if flag_def["unique"] else "false"
        opts.append(f"strictcli.Unique({val})")
    else:
        ft = flag_def.get("type", "str")
        if ft.startswith("list[") or ft.startswith("dict["):
            # Compound types in Go require explicit unique; default to false
            opts.append("strictcli.Unique(false)")
    if "conflict_mode" in flag_def:
        opts.append(f'strictcli.ConflictMode("{flag_def["conflict_mode"]}")')
    if "env_separator" in flag_def:
        opts.append(f'strictcli.EnvSeparator("{flag_def["env_separator"]}")')
    if "negatable" in flag_def and not flag_def["negatable"]:
        opts.append("strictcli.NegatableOpt(false)")
    return opts


def _emit_flag(flag_def: dict) -> str:
    """Emit a strictcli.StringFlag/BoolFlag/IntFlag/ListFlag/DictFlag(...) call."""
    ftype = flag_def.get("type", "str")
    scalar_type_map = {"str": "StringFlag", "bool": "BoolFlag", "int": "IntFlag", "float": "FloatFlag"}
    list_type_map = {"list[str]": "TypeStr", "list[int]": "TypeInt", "list[float]": "TypeFloat"}
    dict_type_map = {"dict[str,str]": "TypeStr", "dict[str,int]": "TypeInt", "dict[str,float]": "TypeFloat"}
    opts = _emit_flag_opts(flag_def)
    opts_str = ""
    if opts:
        opts_str = ", " + ", ".join(opts)
    if ftype in list_type_map:
        return f'strictcli.ListFlag(strictcli.{list_type_map[ftype]}, "{flag_def["name"]}", "{flag_def["help"]}"{opts_str})'
    elif ftype in dict_type_map:
        return f'strictcli.DictFlag(strictcli.{dict_type_map[ftype]}, "{flag_def["name"]}", "{flag_def["help"]}"{opts_str})'
    else:
        constructor = scalar_type_map[ftype]
        return f'strictcli.{constructor}("{flag_def["name"]}", "{flag_def["help"]}"{opts_str})'


def _emit_arg(arg_def: dict) -> str:
    """Emit a strictcli.NewArg(...) call."""
    opts = []
    atype = arg_def.get("type", "str")
    if atype != "str":
        type_map = {"bool": "strictcli.TypeBool", "int": "strictcli.TypeInt", "float": "strictcli.TypeFloat"}
        opts.append(f"strictcli.ArgType({type_map[atype]})")
    if "required" in arg_def:
        if arg_def["required"]:
            opts.append("strictcli.ArgRequired(true)")
        else:
            opts.append("strictcli.ArgRequired(false)")
    if "default" in arg_def:
        default = arg_def["default"]
        if default is None:
            opts.append("strictcli.ArgDefault(nil)")
        elif isinstance(default, bool):
            opts.append(f"strictcli.ArgDefault({str(default).lower()})")
        elif isinstance(default, int):
            opts.append(f"strictcli.ArgDefault({default})")
        elif isinstance(default, float):
            opts.append(f"strictcli.ArgDefault({default})")
        else:
            opts.append(f'strictcli.ArgDefault("{default}")')
    if arg_def.get("variadic", False):
        opts.append("strictcli.Variadic()")
    if "choices_str" in arg_def:
        args = ", ".join(f'"{c}"' for c in arg_def["choices_str"])
        opts.append(f"strictcli.ArgChoices({args})")
    if "choices_int" in arg_def:
        args = ", ".join(str(c) for c in arg_def["choices_int"])
        opts.append(f"strictcli.ArgChoices({args})")
    if "choices_float" in arg_def:
        args = ", ".join(str(c) for c in arg_def["choices_float"])
        opts.append(f"strictcli.ArgChoices({args})")
    opts_str = ""
    if opts:
        opts_str = ", " + ", ".join(opts)
    return f'strictcli.NewArg("{arg_def["name"]}", "{arg_def["help"]}"{opts_str})'


def _collect_all_flag_defs(cmd_def: dict, global_flags: list[dict] | None = None) -> list[dict]:
    """Collect all flag definitions (global, direct, from flag sets, from mutex)."""
    flags = list(global_flags or [])
    flags.extend(cmd_def.get("flags", []))
    for fs in cmd_def.get("flag_sets", []):
        flags.extend(fs["flags"])
    for mg in cmd_def.get("mutex", []):
        flags.extend(mg["flags"])
    return flags


def _emit_handler_body(cmd_def: dict, indent: str, global_flags: list[dict] | None = None) -> str:
    """Emit the Go handler body that prints the template-substituted output.

    Handlers are ctx-first: ``{source:name}`` references resolve via
    ``ctx.Source(name)``; ``{name}`` references resolve to the flag/arg value.
    """
    import re
    template = cmd_def["handler_prints"]
    all_flags = _collect_all_flag_defs(cmd_def, global_flags)

    # Provenance references: {source:name} -> ctx.Source(name).
    source_refs = sorted(set(re.findall(r"\{source:([^}]+)\}", template)))

    # Collect all parameter names (flags then args)
    params = []
    for f in all_flags:
        params.append((_flag_param(f["name"]), f["name"], "flag", f))
    for a in cmd_def.get("args", []):
        params.append((a["name"], a["name"], "arg", a))

    if not params and not source_refs:
        return f'{indent}fmt.Println("{template}")'

    lines = []
    lines.append(f'{indent}_out := "{template}"')
    for name in source_refs:
        lines.append(f'{indent}_out = strings.ReplaceAll(_out, "{{source:{name}}}", ctx.Source("{name}"))')

    for param_key, orig_name, kind, defn in params:
        if kind == "flag":
            ftype = defn.get("type", "str")
            if ftype.startswith("list["):
                # List compound type: value is []interface{}
                item_type = ftype[5:-1]  # extract "int" from "list[int]"
                lines.append(f'{indent}{{')
                lines.append(f'{indent}\traw := args["{param_key}"]')
                lines.append(f'{indent}\tvar parts []string')
                lines.append(f'{indent}\tif raw != nil {{')
                lines.append(f'{indent}\t\tfor _, v := range raw.([]interface{{}}) {{')
                if item_type == "int":
                    lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%d", v.(int)))')
                else:
                    lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%v", v))')
                lines.append(f'{indent}\t\t}}')
                lines.append(f'{indent}\t}}')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", strings.Join(parts, ","))')
                lines.append(f'{indent}}}')
            elif ftype.startswith("dict["):
                # Dict compound type: value is map[string]interface{}
                lines.append(f'{indent}{{')
                lines.append(f'{indent}\traw := args["{param_key}"]')
                lines.append(f'{indent}\tvar parts []string')
                lines.append(f'{indent}\tif raw != nil {{')
                lines.append(f'{indent}\t\tm := raw.(map[string]interface{{}})')
                lines.append(f'{indent}\t\tfor k, v := range m {{')
                lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%s=%v", k, v))')
                lines.append(f'{indent}\t\t}}')
                lines.append(f'{indent}\t}}')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", strings.Join(parts, ","))')
                lines.append(f'{indent}}}')
            elif defn.get("repeatable", False):
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
                lines.append(f'{indent}if args["{param_key}"] == nil {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "None")')
                lines.append(f'{indent}}} else if args["{param_key}"].(bool) {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "true")')
                lines.append(f'{indent}}} else {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "false")')
                lines.append(f'{indent}}}')
            elif ftype == "int":
                lines.append(f'{indent}_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%d", args["{param_key}"].(int)))')
            elif ftype == "float":
                lines.append(f'{indent}_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%v", args["{param_key}"].(float64)))')
            else:
                # str -- might be nil for mutex flags with default=null
                lines.append(f'{indent}if args["{param_key}"] != nil {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%v", args["{param_key}"]))')
                lines.append(f'{indent}}} else {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "None")')
                lines.append(f'{indent}}}')
        elif kind == "arg" and defn.get("variadic", False):
            # Variadic arg: value is a list, print comma-separated
            atype = defn.get("type", "str")
            lines.append(f'{indent}{{')
            lines.append(f'{indent}\traw := args["{param_key}"]')
            lines.append(f'{indent}\tvar parts []string')
            lines.append(f'{indent}\tif raw != nil {{')
            lines.append(f'{indent}\t\tfor _, v := range raw.([]interface{{}}) {{')
            if atype == "int":
                lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%d", v.(int)))')
            else:
                lines.append(f'{indent}\t\t\tparts = append(parts, fmt.Sprintf("%v", v))')
            lines.append(f'{indent}\t\t}}')
            lines.append(f'{indent}\t}}')
            lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", strings.Join(parts, ","))')
            lines.append(f'{indent}}}')
        elif kind == "arg":
            atype = defn.get("type", "str")
            if atype == "bool":
                lines.append(f'{indent}if args["{param_key}"].(bool) {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "true")')
                lines.append(f'{indent}}} else {{')
                lines.append(f'{indent}\t_out = strings.ReplaceAll(_out, "{{{orig_name}}}", "false")')
                lines.append(f'{indent}}}')
            elif atype == "int":
                lines.append(f'{indent}_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%d", args["{param_key}"].(int)))')
            elif atype == "float":
                lines.append(f'{indent}_out = strings.ReplaceAll(_out, "{{{orig_name}}}", fmt.Sprintf("%v", args["{param_key}"].(float64)))')
            else:
                # str arg -- might be nil
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

    # Flag sets
    if cmd_def.get("flag_sets"):
        for fs in cmd_def["flag_sets"]:
            flag_exprs = [_emit_flag(f) for f in fs["flags"]]
            inner = ", ".join(flag_exprs)
            opts.append(f'strictcli.WithFlagSets(strictcli.FlagSet{{Name: "{fs["name"]}", Flags: []strictcli.Flag{{{inner}}}}})')

    # Mutex groups
    if cmd_def.get("mutex"):
        for mg in cmd_def["mutex"]:
            flag_exprs = [_emit_flag(f) for f in mg["flags"]]
            inner = ", ".join(flag_exprs)
            opts.append(f"strictcli.WithMutex(strictcli.MutexGroup{{Flags: []strictcli.Flag{{{inner}}}}})")

    # Dependencies
    if cmd_def.get("dependencies"):
        dep_exprs = []
        for dep in cmd_def["dependencies"]:
            if dep["type"] == "co_required":
                flags_inner = ", ".join(f'"{f}"' for f in dep["flags"])
                dep_exprs.append(f"strictcli.CoRequired{{Flags: []string{{{flags_inner}}}}}")
            elif dep["type"] == "requires":
                dep_exprs.append(
                    f'strictcli.Requires{{Flag: "{dep["flag"]}", DependsOn: "{dep["depends_on"]}"}}'
                )
            elif dep["type"] == "implies":
                val = "true" if dep["value"] else "false"
                dep_exprs.append(
                    f'strictcli.Implies{{Flag: "{dep["flag"]}", Implies: "{dep["implies"]}", Value: {val}}}'
                )
        inner = ", ".join(dep_exprs)
        opts.append(f"strictcli.WithDependencies({inner})")

    # Tags
    if cmd_def.get("tags"):
        tag_args = ", ".join(f'"{t}"' for t in cmd_def["tags"])
        opts.append(f"strictcli.WithTags({tag_args})")

    # Config fields
    if cmd_def.get("config_fields"):
        cf_args = ", ".join(f'"{f}"' for f in cmd_def["config_fields"])
        opts.append(f"strictcli.WithConfigFields({cf_args})")

    # Hidden
    if cmd_def.get("hidden", False):
        opts.append("strictcli.WithHidden()")

    # Interactive
    if cmd_def.get("interactive", False):
        opts.append("strictcli.WithInteractive()")

    return opts


def _emit_command_go(
    cmd_def: dict, target: str, indent: str,
    global_flags: list[dict] | None = None,
) -> list[str]:
    """Emit Go code to register a single command (normal or passthrough).

    Returns a list of code lines.
    """
    lines = []
    is_passthrough = cmd_def.get("passthrough", False)
    exit_code = cmd_def.get("handler_exit_code", 0)

    if is_passthrough:
        # Passthrough command: define handler, then register via Command + WithPassthrough.
        # This works for both App and Group targets (Group has no Passthrough method).
        handler_var = f"_pt_{cmd_def['name'].replace('-', '_')}"
        lines.append(f'{indent}{handler_var} := func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{{}}) int {{')
        lines.append(f'{indent}\t_ = ctx')
        if global_flags:
            # Print global flag values
            for gf in global_flags:
                gf_key = _flag_param(gf["name"])
                gftype = gf.get("type", "str")
                if gftype == "bool":
                    lines.append(f'{indent}\tif globals["{gf_key}"].(bool) {{')
                    lines.append(f'{indent}\t\tfmt.Println("{gf["name"]}=true")')
                    lines.append(f'{indent}\t}} else {{')
                    lines.append(f'{indent}\t\tfmt.Println("{gf["name"]}=false")')
                    lines.append(f'{indent}\t}}')
                elif gftype == "int":
                    lines.append(f'{indent}\tfmt.Printf("{gf["name"]}=%d\\n", globals["{gf_key}"].(int))')
                else:
                    lines.append(f'{indent}\tfmt.Printf("{gf["name"]}=%v\\n", globals["{gf_key}"])')
        # Print using passthrough_handler_prints template, or default format
        pt_template = cmd_def.get("passthrough_handler_prints")
        if pt_template:
            # Build Go code that substitutes {name} and {args} in the template
            lines.append(f'{indent}\t_ptOut := "{pt_template}"')
            lines.append(f'{indent}\t_ptOut = strings.ReplaceAll(_ptOut, "{{name}}", name)')
            lines.append(f'{indent}\t_ptOut = strings.ReplaceAll(_ptOut, "{{args}}", strings.Join(args, ","))')
            lines.append(f'{indent}\tfmt.Println(_ptOut)')
        else:
            lines.append(f'{indent}\tfmt.Printf("%s:%s\\n", name, strings.Join(args, ","))')
        lines.append(f'{indent}\treturn {exit_code}')
        lines.append(f'{indent}}}')
        # Build CmdOptions: WithPassthrough first, then any flags/args/flag_sets/mutex opts
        pt_opts = [f"strictcli.WithPassthrough({handler_var})"]
        pt_opts.extend(_emit_cmd_options(cmd_def, indent + "\t"))
        lines.append(f'{indent}{target}.Command("{cmd_def["name"]}", "{cmd_def["help"]}", nil, {", ".join(pt_opts)})')
    else:
        cmd_opts = _emit_cmd_options(cmd_def, indent + "\t")
        opts_args = ""
        if cmd_opts:
            opts_args = ", " + ", ".join(cmd_opts)
        lines.append(
            f'{indent}{target}.Command("{cmd_def["name"]}", "{cmd_def["help"]}", '
            f'func(ctx *strictcli.Context, args map[string]interface{{}}) strictcli.Outcome {{'
        )
        handler_returns = cmd_def.get("handler_returns")
        if handler_returns is not None:
            # Survivor-contract cases pin an explicit Outcome.
            lines.append(f'{indent}\t_ = ctx')
            lines.append(f'{indent}\t_ = args')
            lines.extend(_emit_handler_return_go(handler_returns, indent + "\t"))
        else:
            lines.append(_emit_handler_body(cmd_def, indent + "\t", global_flags))
            lines.append(f'{indent}\treturn strictcli.Exit({exit_code})')
        lines.append(f"{indent}}}{opts_args})")

    lines.append("")
    return lines


def _emit_handler_return_go(hr: dict, indent: str) -> list[str]:
    """Emit the return statement for a handler_returns spec (Go).

    Kinds: 'exit' (Exit(code)), 'data' (ExitData(0, data)), 'exit_data'
    (ExitData(code, data)), 'none' (Exit(0) -- Go has no None). 'bad' is
    Python-only (Go's type system makes an invalid return unrepresentable).
    """
    kind = hr["kind"]
    code = hr.get("code", 0)
    if kind == "exit":
        return [f"{indent}return strictcli.Exit({code})"]
    if kind == "none":
        return [f"{indent}return strictcli.Exit(0)"]
    if kind in ("data", "exit_data"):
        c = 0 if kind == "data" else code
        return [
            f"{indent}var _data interface{{}}",
            f"{indent}_ = json.Unmarshal([]byte({_go_str(json.dumps(hr['data']))}), &_data)",
            f"{indent}return strictcli.ExitData({c}, _data)",
        ]
    raise ValueError(f"unknown handler_returns kind (go): {kind!r}")


def generate(app_def: dict) -> str:
    """Generate a complete Go main.go from an app definition.

    Returns the source code as a string.
    """
    has_toml = bool(app_def.get("checks_toml"))
    has_providers = bool(app_def.get("providers"))
    has_checks = has_toml or has_providers

    # Detect whether any command emits structured data (handler_returns of
    # kind data/exit_data) -- those require encoding/json to build the value.
    def _needs_json(cmds: list) -> bool:
        for c in cmds or []:
            hr = c.get("handler_returns")
            if hr is not None and hr.get("kind") in ("data", "exit_data"):
                return True
        return False

    def _any_data_return(defn: dict) -> bool:
        if _needs_json(defn.get("commands", [])):
            return True
        for g in defn.get("groups", []):
            if _any_data_return(g):
                return True
        return False

    has_data_return = _any_data_return(app_def)

    lines = []
    lines.append("package main")
    lines.append("")
    lines.append("import (")
    if has_data_return:
        lines.append('\t"encoding/json"')
    if has_toml:
        lines.append('\t"crypto/sha256"')
    lines.append('\t"fmt"')
    lines.append('\t"os"')
    if has_toml:
        lines.append('\t"path/filepath"')
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
    # Recover from panics (registration errors) and exit with code 1
    lines.append('\tdefer func() {')
    lines.append('\t\tif r := recover(); r != nil {')
    lines.append('\t\t\tfmt.Fprintf(os.Stderr, "error: %v\\n", r)')
    lines.append('\t\t\tos.Exit(1)')
    lines.append('\t\t}')
    lines.append('\t}()')
    lines.append("")

    # Write checks.toml to a temp file and pass via WithChecks(path)
    if has_toml:
        checks_toml = app_def["checks_toml"]
        # Escape for Go double-quoted string
        escaped_toml = checks_toml.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        lines.append('\t// Write checks.toml to a deterministic temp path')
        lines.append(f'\tchecksHash := fmt.Sprintf("%x", sha256.Sum256([]byte("{escaped_toml}")))')
        lines.append(f'\tchecksPath := filepath.Join(os.TempDir(), "strictcli-checks-"+checksHash[:12]+".toml")')
        lines.append(f'\tos.WriteFile(checksPath, []byte("{escaped_toml}"), 0o644)')
        lines.append("")

    # Build app
    app_opts = []
    if "env_prefix" in app_def:
        app_opts.append(f'strictcli.WithEnvPrefix("{app_def["env_prefix"]}")')
    if app_def.get("config", False):
        app_opts.append("strictcli.WithConfig()")
    if "config_path" in app_def and app_def["config_path"] is not None:
        app_opts.append(f'strictcli.WithConfigPath("{app_def["config_path"]}")')
    if "config_format" in app_def and app_def["config_format"] != "json":
        app_opts.append(f'strictcli.WithConfigFormat("{app_def["config_format"]}")')
    if app_def.get("no_default_config_path", False):
        app_opts.append("strictcli.WithNoDefaultConfigPath()")
    if "config_conflict_mode" in app_def and app_def["config_conflict_mode"] != "cli-wins":
        app_opts.append(f'strictcli.WithConfigConflictMode("{app_def["config_conflict_mode"]}")')
    for env_var, default_path in app_def.get("infra_root", {}).items():
        app_opts.append(f'strictcli.WithInfraRoot("{env_var}", "{default_path}")')
    for env_var, hlp in app_def.get("handshake_env", {}).items():
        app_opts.append(f'strictcli.WithHandshakeEnv("{env_var}", "{hlp}")')
    if has_toml:
        app_opts.append('strictcli.WithChecks(checksPath)')
    opts_str = ""
    if app_opts:
        opts_str = ", " + ", ".join(app_opts)
    lines.append(f'\tapp := strictcli.NewApp("{app_def["name"]}", "{app_def["version"]}", "{app_def["help"]}"{opts_str})')
    lines.append("")

    # Register config fields (before commands, since commands may bind to them)
    for cf_def in app_def.get("config_fields_def", []):
        cf_opts = []
        cf_type = cf_def.get("type", "str")
        type_map = {"str": "strictcli.TypeStr", "bool": "strictcli.TypeBool",
                     "int": "strictcli.TypeInt", "float": "strictcli.TypeFloat"}
        cf_opts.append(f"strictcli.ConfigFieldType({type_map[cf_type]})")
        cf_opts.append(f'strictcli.ConfigFieldHelp("{cf_def["help"]}")')
        if "default" in cf_def:
            dv = cf_def["default"]
            if isinstance(dv, bool):
                cf_opts.append(f"strictcli.ConfigFieldDefault({str(dv).lower()})")
            elif isinstance(dv, int):
                cf_opts.append(f"strictcli.ConfigFieldDefault({dv})")
            elif isinstance(dv, float):
                cf_opts.append(f"strictcli.ConfigFieldDefault({dv})")
            else:
                cf_opts.append(f'strictcli.ConfigFieldDefault("{dv}")')
        lines.append(f'\tapp.ConfigField("{cf_def["name"]}", {", ".join(cf_opts)})')
    if app_def.get("config_fields_def"):
        lines.append("")

    # Register global flags
    global_flags = app_def.get("global_flags", [])
    for gf in global_flags:
        lines.append(f"\tapp.GlobalFlag({_emit_flag(gf)})")
    if global_flags:
        lines.append("")

    # Register groups first (recursive helper for nested groups)
    _go_group_counter = [0]

    def _emit_group_go(group_def: dict, parent_var: str, indent: str) -> None:
        _go_group_counter[0] += 1
        gvar = f"group_{group_def['name'].replace('-', '_')}_{_go_group_counter[0]}"
        tags_arg = ""
        if group_def.get("tags"):
            tag_args = ", ".join(f'"{t}"' for t in group_def["tags"])
            tags_arg = f", {tag_args}"
        lines.append(f'{indent}{gvar} := {parent_var}.Group("{group_def["name"]}", "{group_def["help"]}"{tags_arg})')
        if group_def.get("hidden", False):
            lines.append(f'{indent}{gvar}.Hidden = true')
        lines.append("")
        for cmd_def in group_def.get("commands", []):
            if cmd_def.get("deprecated"):
                lines.append(f'{indent}{gvar}.Deprecated("{cmd_def["name"]}", "{cmd_def.get("deprecated_message", "")}")')
                lines.append("")
            else:
                lines.extend(_emit_command_go(cmd_def, gvar, indent, global_flags))
        for sub_group_def in group_def.get("groups", []):
            _emit_group_go(sub_group_def, gvar, indent)

    for group_def in app_def.get("groups", []):
        _emit_group_go(group_def, "app", "\t")

    # Register top-level commands
    for cmd_def in app_def.get("commands", []):
        if cmd_def.get("deprecated"):
            lines.append(f'\tapp.Deprecated("{cmd_def["name"]}", "{cmd_def.get("deprecated_message", "")}")')
            lines.append("")
        else:
            lines.extend(_emit_command_go(cmd_def, "app", "\t", global_flags))

    # Register tag contracts.
    for tag, contract in app_def.get("tag_contracts", {}).items():
        lines.append(f'\tapp.TagContract("{tag}", "{contract["requires_flag"]}")')
    if app_def.get("tag_contracts"):
        lines.append("")

    # Register checks if defined. The registration form (RegisterErrorCheck vs
    # RegisterWarnCheck) is derived from the check's severity in the embedded
    # checks_toml -- the case only describes what the impl mints via its reporter.
    if has_toml:
        severities = _check_severities(app_def["checks_toml"])

        for check_def in app_def.get("checks", []):
            cname = check_def["name"]
            if severities.get(cname) == "warn":
                reg, reporter_type = "RegisterWarnCheck", "WarnReporter"
            else:
                reg, reporter_type = "RegisterErrorCheck", "ErrorReporter"
            lines.append(
                f'\tapp.{reg}("{cname}", func(ctx strictcli.CheckContext, r *strictcli.{reporter_type}) strictcli.CheckOutcome {{'
            )
            lines.extend(_emit_check_impl_body_go(check_def, "\t\t"))
            lines.append('\t})')
            lines.append("")

    # Register check providers. Each provider is a list of specs it returns;
    # every spec carries its 8 meta fields inline (providers have no TOML). The
    # registration form (NewErrorCheckSpec vs NewWarnCheckSpec) is the spec's
    # impl_form (defaults to its severity); a spec whose impl_form differs from
    # its meta severity pins the materialization-time severity-mismatch panic.
    if has_providers:
        def _go_str_list(items) -> str:
            return "[]string{" + ", ".join(_go_str(x) for x in items) + "}"

        for provider_specs in app_def["providers"]:
            lines.append('\tapp.RegisterCheckProvider(func() []strictcli.CheckSpec {')
            lines.append('\t\treturn []strictcli.CheckSpec{')
            for spec in provider_specs:
                impl_form = spec.get("impl_form", spec["severity"])
                if impl_form == "warn":
                    ctor, reporter_type = "NewWarnCheckSpec", "WarnReporter"
                else:
                    ctor, reporter_type = "NewErrorCheckSpec", "ErrorReporter"
                lines.append(f'\t\t\tstrictcli.{ctor}(')
                lines.append('\t\t\t\tstrictcli.CheckSpecMeta{')
                lines.append(f'\t\t\t\t\tName:         {_go_str(spec["name"])},')
                lines.append(f'\t\t\t\t\tTags:         {_go_str_list(spec["tags"])},')
                lines.append(f'\t\t\t\t\tSeverity:     {_go_str(spec["severity"])},')
                lines.append(f'\t\t\t\t\tFast:         {str(bool(spec["fast"])).lower()},')
                lines.append(f'\t\t\t\t\tPure:         {str(bool(spec["pure"])).lower()},')
                lines.append(f'\t\t\t\t\tNeedsNetwork: {str(bool(spec["needs_network"])).lower()},')
                lines.append(f'\t\t\t\t\tDependsOn:    {_go_str_list(spec["depends_on"])},')
                lines.append(f'\t\t\t\t\tScope:        {_go_str(spec.get("scope", ""))},')
                lines.append('\t\t\t\t},')
                lines.append(
                    f'\t\t\t\tfunc(ctx strictcli.CheckContext, r *strictcli.{reporter_type}) strictcli.CheckOutcome {{'
                )
                lines.extend(_emit_check_impl_body_go(spec, "\t\t\t\t\t"))
                lines.append('\t\t\t\t},')
                lines.append('\t\t\t),')
            lines.append('\t\t}')
            lines.append('\t})')
            lines.append("")

    if has_checks:
        lines.append('\t// Check context')
        lines.append('\tapp.SetCheckContext(func() strictcli.CheckContext {')
        lines.append('\t\treturn &testCheckCtx{}')
        lines.append('\t})')
        lines.append("")

    # Write config_content_late AFTER construction but BEFORE run
    if "config_content_late" in app_def:
        late_content = app_def["config_content_late"]
        config_path = app_def.get("config_path", "")
        if config_path:
            escaped = late_content.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
            lines.append(f'\tos.WriteFile("{config_path}", []byte("{escaped}"), 0o644)')
            lines.append("")

    lines.append("\tapp.Run()")
    lines.append("}")
    lines.append("")

    # Emit check context type if needed
    if has_checks:
        lines.append("type testCheckCtx struct{}")
        lines.append('func (c *testCheckCtx) ProjectRoot() string { return "." }')
        lines.append("")

    return "\n".join(lines)
