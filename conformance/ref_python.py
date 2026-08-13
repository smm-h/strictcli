"""Generate a temporary Python script from a conformance test case's app definition.

The generated script imports strictcli, builds the app as described by the JSON
definition, registers handlers that print template-substituted output, and calls
app.run().
"""

from __future__ import annotations

import json
import keyword
import textwrap
import tomllib

# The message a `handler_aborts` handler carries, identical in all three
# harnesses so the abort's surfaced stderr line is byte-identical across
# targets. Every harness prints it as "error: <message>".
HANDLER_ABORT_MESSAGE = "conformance: handler aborted"

# The message an `aborts` check impl carries. The three harnesses raise/throw/
# panic a type spelled CheckAborted with this exact message, so the framework's
# containment line -- which names the type -- is byte-identical across targets.
CHECK_ABORT_MESSAGE = "conformance: check aborted"


def _check_severities(checks_toml: str) -> dict[str, str]:
    """Parse the embedded checks_toml and return a name->severity map.

    The registration form (error vs warn) is derived from severity -- there is
    no per-check registration field in the case fixture.
    """
    data = tomllib.loads(checks_toml)
    return {name: c["severity"] for name, c in data.get("checks", {}).items()}


def _emit_check_impl_body(check_def: dict, indent: str) -> list[str]:
    """Emit the reporter-minting body lines of a check impl.

    Shared by TOML-declared checks (``@app.error_check`` / ``@app.warn_check``)
    and provider-sourced specs (``error_check_spec`` / ``warn_check_spec``
    impls). Both receive ``(ctx, reporter)``; the body mints any problems then
    returns a terminal outcome via the reporter.

    With ``aborts`` the body mints nothing and unwinds instead, which is how a
    case reaches the runner's per-check containment.
    """
    if check_def.get("aborts", False):
        return [f"{indent}raise CheckAborted({CHECK_ABORT_MESSAGE!r})"]
    mint = check_def["mint"]
    message = check_def["message"]
    problems = check_def.get("problems", [])
    notes = check_def.get("notes", [])
    body = []
    for n in notes:
        body.append(f"{indent}reporter.note({n!r})")
    for p in problems:
        pmethod = "error" if p["severity"] == "error" else "warn"
        body.append(f"{indent}reporter.{pmethod}({p['text']!r})")
    body.append(f"{indent}return reporter.{mint}({message!r})")
    return body


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

    if "default_relative_to_root" in flag_def:
        rtr = flag_def["default_relative_to_root"]
        rtr_args = ", ".join([repr(rtr["env_var"])] + [repr(p) for p in rtr.get("parts", [])])
        parts.append(f"default=strictcli.RelativeToRoot({rtr_args})")
    elif "default" in flag_def:
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

    if "conflict_mode" in flag_def:
        parts.append(f"conflict_mode={flag_def['conflict_mode']!r}")

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
    """Emit the handler body that prints the template-substituted output.

    Handlers are ctx-first: ``{source:name}`` references resolve via
    ``ctx.source(name)``; ``{name}`` references resolve to the flag/arg value
    from kwargs, type-formatted.
    """
    import re
    template = cmd_def["handler_prints"]
    all_flags = _collect_all_flag_defs(cmd_def, global_flags)
    flag_types = {}
    for f in all_flags:
        flag_types[f["name"]] = f.get("type", "str")

    # Provenance references: {source:name} -> ctx.source(name).
    source_refs = sorted(set(re.findall(r"\{source:([^}]+)\}", template)))

    # Build a format expression
    params = _collect_params(cmd_def, global_flags)
    if not params and not source_refs:
        return f"    print({template!r})"

    # We build the output using string concatenation to handle type formatting
    lines = []
    lines.append("    _parts = {}")
    for name in source_refs:
        lines.append(f"    _parts[{('source:' + name)!r}] = ctx.source({name!r})")
    for f in all_flags:
        pname = _flag_param(f["name"])
        ftype = f.get("type", "str")
        if ftype.startswith("list["):
            # List compound type: print comma-separated
            lines.append(
                f"    _parts[{f['name']!r}] = ','.join(str(x) for x in {pname})"
            )
        elif ftype.startswith("dict["):
            # Dict compound type: print key=value pairs comma-separated, keys
            # sorted for deterministic (cross-target) output.
            lines.append(
                f"    _parts[{f['name']!r}] = ','.join(f'{{k}}={{v}}' for k, v in sorted({pname}.items()))"
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


# ---------------------------------------------------------------------------
# The effects vocabulary (effects contract §14.4)
#
# `handler_effects` is materialized identically by all three harnesses: iterate
# the array in order, call the named method with EXACTLY the keys the entry
# declares (no per-method filtering -- a case declaring a key the method does
# not accept is asserting the error), and keep the returned carrier in a per-run
# map indexed by position so `forward_from` / `extract_from` can reference it.
# ---------------------------------------------------------------------------

# The carrier-accepting positional each method's `forward_from` supplies. It is
# the method's LAST carrier-accepting argument (§2.5.5); `run` and `spawn` have
# only `argv`, so the carrier is appended as its final element.
_FORWARD_TARGET = {
    "run": "argv",
    "spawn": "argv",
    "write": "content",
    "mkdir": "path",
    "remove": "path",
    "rename": "to",
    "chmod": "path",
    "http": "url",
}

# The option keys the vocabulary carries, in the order the harnesses pass them.
_EFFECT_OPTION_KEYS = ("stream", "resource", "skip_if_current", "grant")


def _deprecated_effect_arg(cmd_def: dict) -> str:
    """The `effect=` argument for a deprecated registration, if the case declares one.

    Deprecated commands are classification-EXEMPT (§1.1), so a case that
    declares `effect` on a deprecated entry is asserting the registration hard
    error `errDeprecatedCommandEffect`. Forwarding it is the only way to reach
    that guard.
    """
    if "effect" not in cmd_def:
        return ""
    return f", effect={cmd_def['effect']!r}"


def _emit_classification(cmd_def: dict, indent: str) -> list[str]:
    """Emit the effects-regime keywords: effect, consequential, grants, forwarding.

    `effect` is mandatory on every non-deprecated command (§1.1), so it is
    emitted whenever the case declares it and omitted when it does not -- a case
    that omits it is asserting the registration hard error.
    """
    lines: list[str] = []
    if "effect" in cmd_def:
        lines.append(f"{indent}effect={cmd_def['effect']!r},")
    # `consequential` is NOT mandatory (§8.1): absence means "not
    # consequential", so it is emitted only when the case declares it.
    if "consequential" in cmd_def:
        lines.append(f"{indent}consequential={cmd_def['consequential']!r},")
    # `dry_run_supported` is likewise NOT mandatory: absence means supported.
    # Only false is declarable, and it carries a mandatory reason.
    if "dry_run_supported" in cmd_def:
        lines.append(
            f"{indent}dry_run_supported={cmd_def['dry_run_supported']!r},"
        )
    if "dry_run_unsupported_reason" in cmd_def:
        lines.append(
            f"{indent}dry_run_unsupported_reason="
            f"{cmd_def['dry_run_unsupported_reason']!r},"
        )
    # The machine payload's declared schema (§19.5). A handler_returns of kind
    # "data"/"exit_data" supplies a payload, and ctx.payload refuses to run on a
    # command that declares no schema -- so the harness declares the permissive
    # literal for exactly those commands. The literal is identical in all three
    # harnesses, which is what keeps the schema dump in parity.
    # A case may declare its own literal with "payload_schema", which is how
    # the closed subset's enforcement becomes observable through the CLI: the
    # schema dump publishes it verbatim and a payload is validated against it.
    _hr_kind = (cmd_def.get("handler_returns") or {}).get("kind")
    if "payload_schema" in cmd_def:
        lines.append(
            f"{indent}payload_schema={cmd_def['payload_schema']!r},"
        )
    elif _hr_kind in ("data", "exit_data"):
        lines.append(f"{indent}payload_schema={{}},")
    if cmd_def.get("grants"):
        exprs = [
            f"strictcli.Grant(name={g['name']!r}, reason={g['reason']!r}, "
            f"kind={g['kind']!r})"
            for g in cmd_def["grants"]
        ]
        lines.append(f"{indent}grants=[{', '.join(exprs)}],")
    if "forwarding" in cmd_def:
        reason = cmd_def["forwarding"]["reason"]
        lines.append(
            f"{indent}forwarding=strictcli.Forwarding(reason={reason!r}),"
        )
    return lines


def _emit_handler_effects(cmd_def: dict, indent: str) -> list[str]:
    """Emit the effect calls a generated handler issues, in order."""
    entries = cmd_def.get("handler_effects")
    if not entries:
        return []

    lines = [f"{indent}_eff = {{}}"]
    for i, e in enumerate(entries, start=1):
        method = e["method"]

        extract_from = e.get("extract_from")
        if extract_from is not None:
            # Extraction is terminal by construction: it truncates the preview,
            # so nothing after this entry runs.
            lines.append(f"{indent}bool(_eff[{extract_from}])")
            break

        forward_from = e.get("forward_from")
        fwd = f"_eff[{forward_from}]" if forward_from is not None else None
        target = _FORWARD_TARGET[method]

        pos: list[str] = []
        if method in ("run", "spawn"):
            argv = [repr(a) for a in e.get("argv", [])]
            if fwd is not None and target == "argv":
                argv.append(fwd)
            pos.append(f"[{', '.join(argv)}]")
        elif method == "write":
            pos.append(fwd if (fwd and target == "path") else repr(e["path"]))
            pos.append(fwd if (fwd and target == "content") else repr(e["content"]))
        elif method in ("mkdir", "remove"):
            pos.append(fwd if fwd is not None else repr(e["path"]))
        elif method == "rename":
            pos.append(repr(e["path"]))
            pos.append(fwd if fwd is not None else repr(e["to"]))
        elif method == "chmod":
            pos.append(fwd if fwd is not None else repr(e["path"]))
            pos.append(str(int(e["mode"], 8)))
        elif method == "http":
            pos.append(repr(e["http_method"]))
            pos.append(fwd if fwd is not None else repr(e["url"]))

        for key in _EFFECT_OPTION_KEYS:
            if key in e:
                pos.append(f"{key}={e[key]!r}")

        lines.append(f"{indent}_eff[{i}] = ctx.effects.{method}({', '.join(pos)})")
    return lines


def _emit_handler_diagnostics(cmd_def: dict, indent: str) -> list[str]:
    """Emit the Context diagnostic calls a generated handler issues, in order.

    The four levels are gated by --quiet / --verbose (effects contract §7.4);
    the harness itself does no gating, it just calls the named method.
    """
    lines: list[str] = []
    for d in cmd_def.get("handler_diagnostics", []):
        lines.append(f"{indent}ctx.{d['level']}({d['message']!r})")
    return lines


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
        # Signature: func(ctx, name: str, args: list[str], globals: dict) -> int
        lines.append(f"{indent}def {handler_name}(ctx, name, args, globals):")
        pt_aborts = cmd_def.get("handler_aborts", False)
        if pt_aborts:
            # The handler unwinds instead of printing and returning.
            lines.append(f"{indent}    raise ValueError({HANDLER_ABORT_MESSAGE!r})")
        if global_flags and not pt_aborts:
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
        if pt_aborts:
            pass
        elif pt_template:
            # Build the output by substituting {name} and {args} in the template
            lines.append(f'{indent}    _pt_out = {pt_template!r}')
            lines.append(f'{indent}    _pt_out = _pt_out.replace("{{name}}", name)')
            lines.append(f'{indent}    _pt_out = _pt_out.replace("{{args}}", ",".join(args))')
            lines.append(f'{indent}    print(_pt_out)')
        else:
            lines.append(f'{indent}    print(name + ":" + ",".join(args))')
        if not pt_aborts:
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
        lines.extend(_emit_classification(cmd_def, indent + "    "))
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

    # effect / grants / forwarding (the effects regime, §1.1, §6.1, §10.2)
    decorator_parts.extend(_emit_classification(cmd_def, indent + "    "))

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
        if "default_relative_to_root" in f:
            rtr = f["default_relative_to_root"]
            rtr_args = ", ".join([repr(rtr["env_var"])] + [repr(p) for p in rtr.get("parts", [])])
            fd_parts.append(f"default=strictcli.RelativeToRoot({rtr_args})")
        elif "default" in f:
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
        if "conflict_mode" in f:
            fd_parts.append(f"conflict_mode={f['conflict_mode']!r}")
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
    # Handlers are ctx-first under the unified contract.
    sig_params = ", ".join(["ctx"] + param_strs)
    fn_name = f"{cmd_def['name'].replace('-', '_')}_handler"

    lines.extend(decorator_parts)
    for fd in flag_decorators:
        lines.append(fd)
    lines.append(f"{indent}def {fn_name}({sig_params}):")

    # handler_effects runs BEFORE the handler_prints / handler_returns path and
    # does not replace it (§14.4). handler_diagnostics follows it, still before
    # that path.
    effect_lines = _emit_handler_effects(cmd_def, indent + "    ")
    lines.extend(effect_lines)
    diag_lines = _emit_handler_diagnostics(cmd_def, indent + "    ")
    lines.extend(diag_lines)

    handler_returns = cmd_def.get("handler_returns")
    if cmd_def.get("handler_aborts", False):
        # The handler ABORTS rather than returning (§12.3's unwinding path).
        # ValueError, not a bespoke type: the script's top-level catch prints
        # it as "error: <msg>", which is byte-for-byte what the Go harness's
        # recover and the TS harness's catch print for the same abort.
        lines.append(f"{indent}    raise ValueError({HANDLER_ABORT_MESSAGE!r})")
    elif handler_returns is not None:
        # Survivor-contract cases pin an explicit return value.
        lines.extend(_emit_handler_return(handler_returns, indent + "    "))
    else:
        # A handler_effects-only command prints nothing; the effect calls above
        # are its whole body.
        if "handler_prints" in cmd_def:
            lines.append(_emit_handler_body(cmd_def, global_flags))
        elif not effect_lines and not diag_lines:
            lines.append(f"{indent}    pass")
        # Unified return: build an Outcome carrying the exit code.
        lines.append(f"{indent}    return strictcli.outcome(exit_code={exit_code})")
    lines.append("")

    return "\n".join(lines)


def _emit_handler_return(hr: dict, indent: str) -> list[str]:
    """Emit the return statement for a handler_returns spec.

    Kinds: 'exit' (outcome(exit_code)), 'data' (ctx.payload + outcome()),
    'exit_data' (ctx.payload + outcome(exit_code)), 'none' (return None ->
    exit 0), and 'bad' (return an invalid value -> the framework's TypeError
    hard error).
    """
    kind = hr["kind"]
    code = hr.get("code", 0)
    if kind == "exit":
        return [f"{indent}return strictcli.outcome(exit_code={code})"]
    if kind == "data":
        return [
            f"{indent}ctx.payload({hr['data']!r})",
            f"{indent}return strictcli.outcome()",
        ]
    if kind == "exit_data":
        return [
            f"{indent}ctx.payload({hr['data']!r})",
            f"{indent}return strictcli.outcome(exit_code={code})",
        ]
    if kind == "none":
        return [f"{indent}return None"]
    if kind == "bad":
        # A return that is not int, None, or Outcome -- triggers the hard error.
        return [f"{indent}return ['not-an-outcome']"]
    raise ValueError(f"unknown handler_returns kind: {kind!r}")


def generate(app_def: dict) -> str:
    """Generate a complete Python script from an app definition.

    Returns the script source as a string.
    """
    has_toml = bool(app_def.get("checks_toml"))
    has_providers = bool(app_def.get("providers"))
    has_test_coverage = bool(app_def.get("test_coverage"))
    has_checks = has_toml or has_providers or has_test_coverage

    lines = []
    lines.append("import sys")
    lines.append("import os")
    if has_toml:
        lines.append("import hashlib")
    if has_checks:
        lines.append("import pathlib")
    lines.append("")
    lines.append("# Add strictcli to path")
    lines.append("sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))")
    lines.append("import strictcli")
    lines.append("")

    # The aborting-check exception type. Spelled identically in all three
    # harnesses so the framework's containment line names the same type on
    # every target.
    if any(c.get("aborts", False) for c in app_def.get("checks", [])):
        lines.append("class CheckAborted(Exception):")
        lines.append("    pass")
        lines.append("")

    # Write checks.toml to a temp file and pass via checks_path=
    if has_toml:
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
    if app_def.get("no_default_config_path", False):
        app_parts.append("no_default_config_path=True")
    if "config_conflict_mode" in app_def and app_def["config_conflict_mode"] != "cli-wins":
        app_parts.append(f"config_conflict_mode={app_def['config_conflict_mode']!r}")
    if "infra_root" in app_def:
        app_parts.append(f"infra_root={app_def['infra_root']!r}")
    if "handshake_env" in app_def:
        app_parts.append(f"handshake_env={app_def['handshake_env']!r}")
    if has_toml:
        app_parts.append("checks_path=_checks_path")
    if app_def.get("test_coverage", False):
        app_parts.append("test_coverage=True")
    if app_def.get("proc_observe_allowlist"):
        app_parts.append(
            f"proc_observe_allowlist={app_def['proc_observe_allowlist']!r}"
        )
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
                    f"{indent}{gvar}.deprecate({cmd_def['name']!r}, "
                    f"message={cmd_def.get('deprecated_message', '')!r}"
                    f"{_deprecated_effect_arg(cmd_def)})"
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
                f"    app.deprecate({cmd_def['name']!r}, "
                f"message={cmd_def.get('deprecated_message', '')!r}"
                f"{_deprecated_effect_arg(cmd_def)})"
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

    # Register checks if defined. The registration form (error_check vs
    # warn_check) is derived from the check's severity in the embedded
    # checks_toml -- the case only describes what the impl mints via its reporter.
    if has_toml:
        severities = _check_severities(app_def["checks_toml"])
        for check_def in app_def.get("checks", []):
            cname = check_def["name"]
            decorator = "warn_check" if severities.get(cname) == "warn" else "error_check"
            fn_name = f"check_{cname.replace('-', '_')}"
            lines.append(f"    @app.{decorator}({cname!r})")
            lines.append(f"    def {fn_name}(ctx, reporter):")
            lines.extend(_emit_check_impl_body(check_def, "        "))
            lines.append("")

    # Register check providers. Each provider is a list of specs it returns;
    # every spec carries its 8 meta fields inline (providers have no TOML). The
    # registration form (error_check_spec vs warn_check_spec) is the spec's
    # impl_form (defaults to its severity); a spec whose impl_form differs from
    # its severity pins the materialization-time severity-mismatch hard error.
    if has_providers:
        for pi, provider_specs in enumerate(app_def["providers"]):
            lines.append(f"    def _provider_{pi}():")
            spec_meta = []
            for si, spec in enumerate(provider_specs):
                impl_name = f"_impl_{pi}_{si}"
                lines.append(f"        def {impl_name}(ctx, reporter):")
                lines.extend(_emit_check_impl_body(spec, "            "))
                spec_meta.append((impl_name, spec))
            lines.append("        return [")
            for impl_name, spec in spec_meta:
                impl_form = spec.get("impl_form", spec["severity"])
                ctor = "warn_check_spec" if impl_form == "warn" else "error_check_spec"
                lines.append(f"            strictcli.{ctor}(")
                lines.append(f"                name={spec['name']!r},")
                lines.append(f"                tags={spec['tags']!r},")
                lines.append(f"                severity={spec['severity']!r},")
                lines.append(f"                fast={bool(spec['fast'])},")
                lines.append(f"                pure={bool(spec['pure'])},")
                lines.append(f"                needs_network={bool(spec['needs_network'])},")
                lines.append(f"                depends_on={spec['depends_on']!r},")
                lines.append(f"                scope={spec.get('scope', '')!r},")
                lines.append(f"                impl={impl_name},")
                lines.append(f"            ),")
            lines.append("        ]")
            lines.append(f"    app.register_check_provider(_provider_{pi})")
            lines.append("")

    if has_checks:
        lines.append("    class _CheckCtx:")
        lines.append("        project_root = pathlib.Path('.')")
        lines.append("")
        lines.append("    app.set_check_context(lambda: _CheckCtx())")
        lines.append("")

    # The confirm protocol's interactive branch is otherwise unreachable from a
    # subprocess: a case's stdin is a pipe, and a pipe is not a TTY in any of
    # the three implementations. The framework's test-only confirm seam says the
    # answer channel IS interactive and leaves the answer itself coming from the
    # case's real stdin -- WHERE the answer comes from, never WHETHER the
    # protocol runs.
    if app_def.get("confirm_stdin_interactive", False):
        lines.append("    class _ConfirmStdin:")
        lines.append("        def is_interactive(self):")
        lines.append("            return True")
        lines.append("")
        lines.append("        def read_line(self):")
        lines.append("            return sys.stdin.readline()")
        lines.append("")
        lines.append("    app._set_confirm_io(_ConfirmStdin())")
        lines.append("")

    # Write config_content_late AFTER construction but BEFORE run
    if "config_content_late" in app_def:
        late_content = app_def["config_content_late"]
        config_path_expr = f"app._config_path_override" if "config_path" in app_def else "None"
        lines.append(f"    # Write late config content")
        lines.append(f"    with open({app_def['config_path']!r}, 'w') as _lcf:")
        lines.append(f"        _lcf.write({late_content!r})")
        lines.append("")

    # Pre-test argv lists: run app.test() for each before app.run().
    # Used by test_coverage conformance cases to generate shard files.
    for pre_argv in app_def.get("pre_test", []):
        lines.append(f"    app.test({pre_argv!r})")
    if app_def.get("pre_test"):
        lines.append("")

    # Tool descriptor dump: the exported classification, one line per tool.
    if app_def.get("dump_tools"):
        lines.append("    for _tool in app.as_tools():")
        lines.append("        print(f'tool: {_tool.name} effect={_tool.effect} "
                     "consequential={str(_tool.consequential).lower()}')")
        lines.append("")

    # Programmatic calls: the app.call() channel, which argv cannot reach.
    for pre_call in app_def.get("pre_call", []):
        cmd = pre_call["command"]
        kwargs = pre_call.get("kwargs", {})
        approve = bool(pre_call.get("approve_consequential", False))
        lines.append("    try:")
        lines.append(
            f"        app.call({cmd!r}, approve_consequential={approve!r}, "
            f"**{kwargs!r})"
        )
        lines.append(f"        print('call ok: {cmd}')")
        lines.append("    except strictcli.InvokeError as _ce:")
        lines.append("        print(f'call error: {_ce}', file=sys.stderr)")
    if app_def.get("pre_call"):
        lines.append("")

    # The structured effect-log side channel (§14.3): the same env-var file
    # handoff as CONFORMANCE_APP_DEF. app.run() ends in sys.exit, so the write
    # rides atexit -- the Python counterpart of the Go harness's SetExitHook and
    # the TS harness's process.on("exit").
    lines.append("    _effect_log_path = os.environ.get('CONFORMANCE_EFFECT_LOG')")
    lines.append("    if _effect_log_path:")
    lines.append("        import atexit, json as _json")
    lines.append("")
    lines.append("        def _write_effect_log():")
    lines.append("            with open(_effect_log_path, 'w') as _elf:")
    lines.append("                _json.dump(app.effect_log(), _elf, sort_keys=True,")
    lines.append("                           separators=(',', ':'))")
    lines.append("")
    lines.append("        atexit.register(_write_effect_log)")
    lines.append("")
    lines.append("    app.run()")
    # The sibling harnesses both wrap the whole run: Go recovers any panic and
    # TypeScript catches any throw, each printing "error: <msg>" and exiting 1.
    # Python catches every Exception for the same reach. (SystemExit and the
    # framework's _DryRunTruncated derive from BaseException and stay uncaught,
    # exactly as before.)
    #
    # The framework's own error vocabulary prints bare, because the siblings
    # mirror those messages verbatim: ValueError, and EffectFailed -- the
    # effect-failure type whose Go and TypeScript equivalents also print bare.
    # Everything else is tagged with its type name, so a genuine harness bug
    # (a codegen TypeError, an AttributeError) stays distinguishable from a
    # framework error instead of masquerading as one.
    lines.append("except (ValueError, strictcli.EffectFailed) as e:")
    lines.append("    print(f'error: {e}', file=sys.stderr)")
    lines.append("    sys.exit(1)")
    lines.append("except Exception as e:")
    lines.append("    print(f'error: {type(e).__name__}: {e}', file=sys.stderr)")
    lines.append("    sys.exit(1)")
    lines.append("")

    return "\n".join(lines)
