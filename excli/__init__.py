"""An explicit, zero-dependency CLI framework for Python."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["App", "Flag", "Arg", "Tag", "Result", "flag", "arg"]

import contextlib
import inspect
import io
import os
import sys
from dataclasses import dataclass, field
from typing import Callable


# Sentinel for distinguishing "not provided" from actual values
class _MissingSentinel:
    def __repr__(self) -> str:
        return "_MISSING"


_MISSING = _MissingSentinel()


class _HelpRequested(Exception):
    """Raised when --help or -h is encountered."""

    def __init__(self, target: object) -> None:
        self.target = target
        super().__init__()


class _VersionRequested(Exception):
    """Raised when --version or -v is encountered."""


class _ParseError(Exception):
    """Raised for user-facing parse errors."""


def _require_non_empty_str(value: str, field_name: str, class_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{class_name}.{field_name} must be a non-empty string")


@dataclass
class Flag:
    """Represents a --flag declaration."""

    name: str
    type: type
    help: str
    short: str | None = None
    default: object = None
    env: str | None = None
    prefixed: bool = True
    negatable: bool = True

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Flag")
        if self.type not in (str, bool):
            raise ValueError(f"Flag.type must be str or bool, got {self.type!r}")
        # Resolve _MISSING sentinels based on type
        if isinstance(self.default, _MissingSentinel):
            if self.type is bool:
                self.default = False
            else:
                # str with _MISSING default means required (no default)
                self.default = None
        elif self.type is bool and self.default is None:
            self.default = False
        if isinstance(self.negatable, _MissingSentinel):
            self.negatable = self.type is bool
        elif self.type is str:
            # negatable is only meaningful for bool flags
            self.negatable = False


@dataclass
class Arg:
    """Represents a positional argument."""

    name: str
    help: str
    required: bool = True

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Arg")


@dataclass
class Tag:
    """A reusable bundle of flags."""

    name: str
    flags: list[Flag] = field(default_factory=list)


@dataclass
class Command:
    """A leaf command with a handler."""

    name: str
    help: str
    handler: Callable
    flags: list[Flag] = field(default_factory=list)
    args: list[Arg] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Command")


@dataclass
class Group:
    """A container for nested commands (one nesting level)."""

    name: str
    help: str
    commands: dict[str, Command] = field(default_factory=dict)
    env_prefix: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Group")

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        tags: list[Tag] | None = None,
    ) -> Callable:
        """Decorator to register a command within this group."""

        def decorator(func: Callable) -> Callable:
            cmd = _build_and_validate_command(
                name, help=help, handler=func, args=args, tags=tags, env_prefix=self.env_prefix
            )
            self.commands[name] = cmd
            return func

        return decorator


@dataclass
class Result:
    """Returned by app.test()."""

    stdout: str
    stderr: str
    exit_code: int


@dataclass
class App:
    """The root CLI application."""

    name: str
    version: str
    help: str
    env_prefix: str | None = None
    _commands: dict[str, Command] = field(default_factory=dict)
    _groups: dict[str, Group] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "App")

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        tags: list[Tag] | None = None,
    ) -> Callable:
        """Decorator to register a top-level command."""

        def decorator(func: Callable) -> Callable:
            cmd = _build_and_validate_command(
                name,
                help=help,
                handler=func,
                args=args,
                tags=tags,
                env_prefix=self.env_prefix,
            )
            self._commands[name] = cmd
            return func

        return decorator

    def group(self, name: str, *, help: str) -> Group:
        """Create and register a command group."""
        grp = Group(name=name, help=help, env_prefix=self.env_prefix)
        self._groups[name] = grp
        return grp

    def _parse(self, argv: list[str]) -> tuple[Command, dict[str, object]]:
        """Parse argv (without program name) into a resolved Command and kwargs."""

        # Step 1: intercept app-level --help/-h and --version/-v
        if not argv or argv == ["--help"] or argv == ["-h"]:
            raise _HelpRequested(target=self)
        if argv == ["--version"] or argv == ["-v"]:
            raise _VersionRequested()

        # Step 2: route to command or group
        token = argv[0]
        rest = argv[1:]

        if token in self._groups:
            group = self._groups[token]
            if not rest or rest == ["--help"] or rest == ["-h"]:
                raise _HelpRequested(target=group)
            sub_token = rest[0]
            rest = rest[1:]
            if sub_token not in group.commands:
                raise _ParseError(f"unknown command '{sub_token}'")
            cmd = group.commands[sub_token]
        elif token in self._commands:
            cmd = self._commands[token]
        else:
            raise _ParseError(f"unknown command '{token}'")

        # Check for command-level --help/-h
        if rest == ["--help"] or rest == ["-h"]:
            raise _HelpRequested(target=cmd)

        # Step 3: parse remaining tokens for the resolved command
        return _parse_command(cmd, rest)

    def _find_command_prefix(self, cmd: Command) -> str:
        """Find the group prefix for a command (for help formatting)."""
        for group in self._groups.values():
            if cmd in group.commands.values():
                return f"{group.name} "
        return ""

    def run(self) -> None:
        """Run the CLI application, reading from sys.argv."""
        argv = sys.argv[1:]
        try:
            cmd, kwargs = self._parse(argv)
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
        except _ParseError as e:
            print(f"error: {e}", file=sys.stderr)
            print(f"try '{self.name} --help'", file=sys.stderr)
            sys.exit(1)
        else:
            cmd.handler(**kwargs)
            sys.exit(0)

    def test(self, argv: list[str]) -> Result:
        """Run the CLI with given argv, capturing output and exit code."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0

        try:
            cmd, kwargs = self._parse(argv)
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
        except _ParseError as e:
            stderr_buf.write(f"error: {e}\n")
            stderr_buf.write(f"try '{self.name} --help'\n")
            exit_code = 1
        else:
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                try:
                    cmd.handler(**kwargs)
                except SystemExit as e:
                    exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)

        return Result(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            exit_code=exit_code,
        )


def _parse_command(cmd: Command, tokens: list[str]) -> tuple[Command, dict[str, object]]:
    """Parse tokens against a resolved command's flags and args."""

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

    # Track which flags were set by CLI args
    cli_set: dict[str, object] = {}  # flag.name -> value
    positionals: list[str] = []

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
                if f.type is bool:
                    raise _ParseError(
                        f"flag '{flag_part}' is a boolean flag and does not take a value"
                    )
                cli_set[f.name] = value_part
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
                if f.type is bool:
                    cli_set[f.name] = True
                    i += 1
                else:
                    # str flag: consume next token as value
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                        cli_set[f.name] = tokens[i + 1]
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
            else:
                raise _ParseError(f"unknown flag '{tok}'")
            continue

        # -x (short form)
        if tok.startswith("-") and len(tok) == 2:
            if tok in short_lookup:
                f = short_lookup[tok]
                if f.type is bool:
                    cli_set[f.name] = True
                    i += 1
                else:
                    # str flag: consume next token as value
                    if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                        cli_set[f.name] = tokens[i + 1]
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
            else:
                raise _ParseError(f"unknown flag '{tok}'")
            continue

        # Unknown flag-like token
        raise _ParseError(f"unknown flag '{tok}'")

    # Step 4: resolve env vars for flags not set by CLI
    for f in cmd.flags:
        if f.name in cli_set:
            continue
        if f.env is not None:
            env_val = os.environ.get(f.env)
            if env_val is not None:
                if f.type is bool:
                    lower = env_val.lower()
                    if lower in ("1", "true", "yes"):
                        cli_set[f.name] = True
                    elif lower in ("0", "false", "no"):
                        cli_set[f.name] = False
                    else:
                        raise _ParseError(
                            f"invalid boolean value {env_val!r} for env var "
                            f"'{f.env}' (flag '--{f.name}')"
                        )
                else:
                    cli_set[f.name] = env_val

    # Step 5: apply defaults
    for f in cmd.flags:
        if f.name in cli_set:
            continue
        if f.type is bool:
            # Bool flags always have a default (False unless overridden)
            cli_set[f.name] = f.default
        elif f.default is not None:
            cli_set[f.name] = f.default
        else:
            # str flag with no default and no value: required
            raise _ParseError(f"flag '--{f.name}' is required")

    # Step 6: resolve positional args
    arg_values: dict[str, str] = {}
    for idx, a in enumerate(cmd.args):
        if idx < len(positionals):
            arg_values[a.name] = positionals[idx]
        elif a.required:
            raise _ParseError(f"missing required argument '{a.name}'")
    if len(positionals) > len(cmd.args):
        raise _ParseError(f"unexpected argument '{positionals[len(cmd.args)]}'")

    # Step 7: build kwargs dict
    kwargs: dict[str, object] = {}
    for f in cmd.flags:
        kwargs[_flag_param_name(f.name)] = cli_set[f.name]
    for a in cmd.args:
        if a.name in arg_values:
            kwargs[a.name] = arg_values[a.name]

    return cmd, kwargs


def _flag_param_name(flag_name: str) -> str:
    """Convert a flag name like '--dry-run' to a Python parameter name 'dry_run'."""
    return flag_name.lstrip("-").replace("-", "_")


def _build_and_validate_command(
    name: str,
    *,
    help: str,
    handler: Callable,
    args: list[Arg] | None,
    tags: list[Tag] | None,
    env_prefix: str | None,
) -> Command:
    """Build a Command from a decorated handler, validate everything."""
    if not help or not help.strip():
        raise ValueError(f"command {name!r}: missing help text")

    # Collect flags attached by @excli.flag decorators
    decorator_flags: list[Flag] = list(getattr(handler, "_excli_flags", []))
    # Collect args attached by @excli.arg decorators
    decorator_args: list[Arg] = list(getattr(handler, "_excli_args", []))

    # Merge explicit args parameter
    all_args = list(args) if args else []
    all_args.extend(decorator_args)

    # Merge tags into flags
    resolved_tags = list(tags) if tags else []
    tag_flags: list[Flag] = []
    for tag in resolved_tags:
        tag_flags.extend(tag.flags)

    # All flags: decorator flags + tag flags
    all_flags = decorator_flags + tag_flags

    # Validate: no duplicate flag names
    seen_flag_names: set[str] = set()
    for f in all_flags:
        if f.name in seen_flag_names:
            raise ValueError(f"command {name!r}: duplicate flag name {f.name!r}")
        seen_flag_names.add(f.name)

    # Validate: no duplicate arg names
    seen_arg_names: set[str] = set()
    for a in all_args:
        if a.name in seen_arg_names:
            raise ValueError(f"command {name!r}: duplicate arg name {a.name!r}")
        seen_arg_names.add(a.name)

    # Validate: flag help text
    for f in all_flags:
        if not f.help or not f.help.strip():
            raise ValueError(
                f"command {name!r}: flag {f.name!r} missing help text"
            )

    # Validate: env prefix
    if env_prefix is not None:
        for f in all_flags:
            if f.env is not None and f.prefixed:
                expected_prefix = f"{env_prefix}_"
                if not f.env.startswith(expected_prefix):
                    raise ValueError(
                        f"command {name!r}: env var {f.env!r} for flag {f.name!r} "
                        f"must start with {expected_prefix!r} (or set prefixed=False)"
                    )

    # Validate: handler signature matches declared flags and args
    sig = inspect.signature(handler)
    param_names = set(sig.parameters.keys())

    expected_names: set[str] = set()
    for f in all_flags:
        expected_names.add(_flag_param_name(f.name))
    for a in all_args:
        expected_names.add(a.name)

    # Check each flag has a matching parameter
    for f in all_flags:
        pname = _flag_param_name(f.name)
        if pname not in param_names:
            raise ValueError(
                f"command {name!r}: handler missing parameter {pname!r} "
                f"for flag {f.name!r}"
            )

    # Check each arg has a matching parameter
    for a in all_args:
        if a.name not in param_names:
            raise ValueError(
                f"command {name!r}: handler missing parameter {a.name!r} "
                f"for arg {a.name!r}"
            )

    # Check for extra parameters
    extra = param_names - expected_names
    if extra:
        extra_name = sorted(extra)[0]
        raise ValueError(
            f"command {name!r}: handler has extra parameter {extra_name!r} "
            f"not matching any flag or arg"
        )

    return Command(
        name=name,
        help=help,
        handler=handler,
        flags=all_flags,
        args=all_args,
        tags=resolved_tags,
    )


def flag(
    name: str,
    *,
    short: str | None = None,
    type: type = str,
    default: object = _MISSING,
    help: str,
    env: str | None = None,
    prefixed: bool = True,
    negatable: object = _MISSING,
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
            prefixed=prefixed,
            negatable=negatable,
        )
        if not hasattr(func, "_excli_flags"):
            func._excli_flags = []
        func._excli_flags.append(f)
        return func

    return decorator


def arg(name: str, *, help: str, required: bool = True) -> Callable:
    """Module-level decorator to attach an Arg to a command handler."""

    def decorator(func: Callable) -> Callable:
        a = Arg(name=name, help=help, required=required)
        if not hasattr(func, "_excli_args"):
            func._excli_args = []
        func._excli_args.append(a)
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

    if app._commands:
        lines.append("")
        lines.append("Commands:")
        names = list(app._commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = app._commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    if app._groups:
        lines.append("")
        lines.append("Groups:")
        names = list(app._groups.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            grp = app._groups[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{grp.help}")

    lines.append("")
    lines.append(f"Use '{app.name} <command> --help' for more information.")

    return "\n".join(lines)


def _format_group_help(app: App, group: Group) -> str:
    """Format group-level help shown when the user runs 'myapp group --help'."""
    lines: list[str] = [f"{app.name} {group.name} -- {group.help}"]

    if group.commands:
        lines.append("")
        lines.append("Commands:")
        names = list(group.commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = group.commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    lines.append("")
    lines.append(
        f"Use '{app.name} {group.name} <command> --help' for more information."
    )

    return "\n".join(lines)


def _build_flag_spec(f: Flag) -> str:
    """Build the left-column spec string for a flag (e.g. '--target, -t <str>')."""
    parts: list[str] = []
    if f.type is bool and f.negatable:
        parts.append(f"--{f.name}, --no-{f.name}")
        if f.short:
            parts.append(f"-{f.short}")
    else:
        parts.append(f"--{f.name}")
        if f.short:
            parts.append(f"-{f.short}")
    spec = ", ".join(parts)
    if f.type is str:
        spec += " <str>"
    return spec


def _build_flag_meta(f: Flag) -> str:
    """Build the bracketed metadata suffix for a flag."""
    meta_parts: list[str] = []
    if f.env is not None:
        meta_parts.append(f"env: {f.env}")
    if f.type is bool:
        meta_parts.append(f"default: {'true' if f.default else 'false'}")
    elif f.default is not None:
        meta_parts.append(f"default: {f.default}")
    else:
        meta_parts.append("required")
    return " [" + "] [".join(meta_parts) + "]"


def _format_command_help(app: App, cmd: Command, prefix: str = "") -> str:
    """Format command-level help shown when the user runs 'myapp cmd --help'."""
    lines: list[str] = [f"{app.name} {prefix}{cmd.name} -- {cmd.help}"]

    if cmd.args:
        lines.append("")
        lines.append("Arguments:")
        max_len = max(len(a.name) for a in cmd.args)
        for a in cmd.args:
            padding = max_len - len(a.name) + 4
            help_text = a.help
            if not a.required:
                help_text += " (optional)"
            lines.append(f"  {a.name}{' ' * padding}{help_text}")

    if cmd.flags:
        lines.append("")
        lines.append("Flags:")
        specs = [_build_flag_spec(f) for f in cmd.flags]
        max_spec = max(len(s) for s in specs)
        for f, spec in zip(cmd.flags, specs):
            padding = max_spec - len(spec) + 4
            meta = _build_flag_meta(f)
            lines.append(f"  {spec}{' ' * padding}{f.help}{meta}")

    return "\n".join(lines)
