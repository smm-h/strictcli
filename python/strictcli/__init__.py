"""A strict, zero-dependency CLI framework for Python."""

from __future__ import annotations

__version__ = "0.2.0"

__all__ = ["App", "Flag", "Arg", "Tag", "MutexGroup", "Passthrough", "Result", "flag", "arg"]

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


def _strict_int(s: str) -> int:
    """Parse an integer string strictly -- no leading/trailing whitespace allowed.

    Python's int() silently strips whitespace; Go's strconv.Atoi does not.
    This matches Go's stricter behavior. Additionally, the result is
    range-checked to fit in a signed 64-bit integer, matching Go's int/int64.
    """
    if s != s.strip():
        raise ValueError(f"invalid literal for int() with base 10: {s!r}")
    n = int(s)
    if n < -(2**63) or n > 2**63 - 1:
        raise ValueError("integer out of range")
    return n


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
    choices: list | None = None
    validate: Callable | None = None
    repeatable: bool = False

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Flag")
        if self.type not in (str, bool, int):
            raise ValueError(f"Flag.type must be str, bool, or int, got {self.type!r}")
        # Validate repeatable
        if self.repeatable and self.type is bool:
            raise ValueError(f'Flag "{self.name}": repeatable is incompatible with type=bool')
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
        # Validate default type for int flags
        if self.type is int and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if not self.repeatable and not isinstance(self.default, int):
                raise ValueError(
                    f'Flag "{self.name}": type=int requires an int default, '
                    f"got {type(self.default).__name__!r}"
                )
        # Resolve _MISSING sentinels based on type
        if isinstance(self.default, _MissingSentinel):
            if self.repeatable:
                self.default = []
            elif self.type is bool:
                self.default = False
            else:
                # str/int with _MISSING default means required (no default)
                self.default = None
        elif self.type is bool and self.default is None:
            self.default = False
        # Validate default is in choices (after sentinel resolution)
        if self.choices is not None and self.default is not None:
            if not self.repeatable and self.default not in self.choices:
                raise ValueError(
                    f'Flag "{self.name}": default {self.default!r} is not in choices '
                    f"{self.choices!r}"
                )
        if isinstance(self.negatable, _MissingSentinel):
            self.negatable = self.type is bool
        elif self.type in (str, int):
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

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Arg")
        if self.required and not isinstance(self.default, _MissingSentinel):
            raise ValueError("required arg cannot have a default")


@dataclass
class Tag:
    """A reusable bundle of flags."""

    name: str
    flags: list[Flag] = field(default_factory=list)


@dataclass
class MutexGroup:
    """A group of mutually exclusive flags."""

    flags: list[Flag] = field(default_factory=list)
    required: bool = False


@dataclass
class Passthrough:
    """Marks a command as passthrough -- all tokens after the command name are
    forwarded to the handler as a raw list, bypassing flag/arg parsing."""

    handler: Callable  # func(name: str, args: list[str], globals: dict) -> int


@dataclass
class Command:
    """A leaf command with a handler."""

    name: str
    help: str
    handler: Callable | None
    flags: list[Flag] = field(default_factory=list)
    args: list[Arg] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)
    mutex: list[MutexGroup] = field(default_factory=list)
    passthrough: Passthrough | None = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Command")


@dataclass
class Group:
    """A container for nested commands (one nesting level)."""

    name: str
    help: str
    commands: dict[str, Command] = field(default_factory=dict)
    env_prefix: str | None = None
    _global_flags: list[Flag] = field(default_factory=list)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Group")

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        tags: list[Tag] | None = None,
        mutex: list[MutexGroup] | None = None,
        passthrough: Passthrough | None = None,
    ) -> Callable:
        """Decorator to register a command within this group."""

        def decorator(func: Callable) -> Callable:
            cmd = _build_and_validate_command(
                name, help=help, handler=func, args=args, tags=tags, mutex=mutex,
                env_prefix=self.env_prefix,
                global_flags=self._global_flags,
                passthrough=passthrough,
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
    flags: list[Flag] = field(default_factory=list)
    _commands: dict[str, Command] = field(default_factory=dict)
    _groups: dict[str, Group] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "App")
        # Check for duplicate global flag names
        seen: set[str] = set()
        for f in self.flags:
            if f.name in seen:
                raise ValueError(f'duplicate global flag name "{f.name}"')
            seen.add(f.name)
        self._global_flags: list[Flag] = list(self.flags)
        self._last_global_values: dict[str, object] = {}

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        tags: list[Tag] | None = None,
        mutex: list[MutexGroup] | None = None,
        passthrough: Passthrough | None = None,
    ) -> Callable:
        """Decorator to register a top-level command."""

        def decorator(func: Callable) -> Callable:
            cmd = _build_and_validate_command(
                name,
                help=help,
                handler=func,
                args=args,
                tags=tags,
                mutex=mutex,
                env_prefix=self.env_prefix,
                global_flags=self._global_flags,
                passthrough=passthrough,
            )
            self._commands[name] = cmd
            return func

        return decorator

    def group(self, name: str, *, help: str) -> Group:
        """Create and register a command group."""
        grp = Group(name=name, help=help, env_prefix=self.env_prefix,
                     _global_flags=self._global_flags)
        self._groups[name] = grp
        return grp

    def _parse(self, argv: list[str]) -> tuple[Command, dict[str, object] | list[str]]:
        """Parse argv (without program name) into a resolved Command and kwargs.

        For normal commands, returns (Command, kwargs_dict).
        For passthrough commands, returns (Command, raw_args_list).
        Callers disambiguate by checking cmd.passthrough.

        After parsing, self._last_global_values holds the parsed global flag
        values (used by passthrough command handlers).
        """

        # Step 1: intercept app-level --help/-h and --version/-v
        if not argv or argv == ["--help"] or argv == ["-h"]:
            raise _HelpRequested(target=self)
        if argv == ["--version"] or argv == ["-v"]:
            raise _VersionRequested()

        # Step 1.5: parse global flags before command routing
        global_values, remaining = self._parse_global_flags(argv)
        self._last_global_values = global_values

        # Step 2: route to command or group
        # If global flag parsing stopped at --, strip it before routing
        if remaining and remaining[0] == "--":
            remaining = remaining[1:]

        if not remaining or remaining == ["--help"] or remaining == ["-h"]:
            raise _HelpRequested(target=self)

        token = remaining[0]
        rest = remaining[1:]

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

        # Passthrough commands: skip all flag/arg parsing, forward raw args
        if cmd.passthrough is not None:
            return cmd, rest

        # Step 3: parse remaining tokens for the resolved command
        cmd, kwargs, post_global = _parse_command(cmd, rest, self._global_flags)

        # Step 4: merge global flag values into kwargs
        # Post-command global flags override pre-command ones
        for gf in self._global_flags:
            if gf.name in post_global:
                global_values[gf.name] = post_global[gf.name]
            kwargs[_flag_param_name(gf.name)] = global_values[gf.name]

        return cmd, kwargs

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
            if f.repeatable:
                if f.name not in cli_set:
                    cli_set[f.name] = []
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
                    if f.type is bool:
                        raise _ParseError(
                            f"flag '{flag_part}' is a boolean flag and does not take a value"
                        )
                    if f.type is int:
                        try:
                            _store_value(f, _strict_int(value_part))
                        except ValueError:
                            raise _ParseError(
                                f"--{f.name}: expected integer, got {value_part!r}"
                            )
                    else:
                        _store_value(f, value_part)
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
                if f.type is bool:
                    cli_set[f.name] = True
                    i += 1
                else:
                    if i + 1 < len(argv):
                        raw = argv[i + 1]
                        if f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError:
                                raise _ParseError(
                                    f"--{f.name}: expected integer, got {raw!r}"
                                )
                        else:
                            _store_value(f, raw)
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
                continue

            # -x (short form)
            if tok.startswith("-") and len(tok) == 2 and tok in short_lookup:
                f = short_lookup[tok]
                if f.type is bool:
                    cli_set[f.name] = True
                    i += 1
                else:
                    if i + 1 < len(argv):
                        raw = argv[i + 1]
                        if f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError:
                                raise _ParseError(
                                    f"--{f.name}: expected integer, got {raw!r}"
                                )
                        else:
                            _store_value(f, raw)
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
                    elif f.type is int:
                        try:
                            coerced = _strict_int(env_val)
                        except ValueError:
                            raise _ParseError(
                                f"--{f.name}: expected integer, got {env_val!r} "
                                f"(from env var '{f.env}')"
                            )
                        cli_set[f.name] = [coerced] if f.repeatable else coerced
                    else:
                        cli_set[f.name] = [env_val] if f.repeatable else env_val

        # Apply defaults for global flags not set by CLI or env
        for f in self._global_flags:
            if f.name in cli_set:
                continue
            if f.repeatable:
                cli_set[f.name] = list(f.default) if f.default else []
            elif f.type is bool:
                cli_set[f.name] = f.default
            elif f.default is not None:
                cli_set[f.name] = f.default
            else:
                raise _ParseError(f"global flag '--{f.name}' is required")

        return cli_set, remaining

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
            cmd, data = self._parse(argv)
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
            if cmd.passthrough is not None:
                code = cmd.passthrough.handler(cmd.name, data, self._last_global_values)
            else:
                code = cmd.handler(**data)
            sys.exit(code if isinstance(code, int) else 0)

    def test(self, argv: list[str]) -> Result:
        """Run the CLI with given argv, capturing output and exit code."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0

        try:
            cmd, data = self._parse(argv)
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
                    if cmd.passthrough is not None:
                        code = cmd.passthrough.handler(
                            cmd.name, data, self._last_global_values,
                        )
                    else:
                        code = cmd.handler(**data)
                    if isinstance(code, int):
                        exit_code = code
                except SystemExit as e:
                    exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)

        return Result(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            exit_code=exit_code,
        )


def _parse_command(
    cmd: Command,
    tokens: list[str],
    global_flags: list[Flag] | None = None,
) -> tuple[Command, dict[str, object], dict[str, object]]:
    """Parse tokens against a resolved command's flags and args.

    Returns (cmd, kwargs, global_cli_set) where global_cli_set contains
    any global flag values parsed from tokens appearing after the command name.
    """

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
        if f.repeatable:
            if f.name not in cli_set:
                cli_set[f.name] = []
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
                if f.type is bool:
                    raise _ParseError(
                        f"flag '{flag_part}' is a boolean flag and does not take a value"
                    )
                if f.type is int:
                    try:
                        _store_value(f, _strict_int(value_part))
                    except ValueError:
                        raise _ParseError(f"--{f.name}: expected integer, got {value_part!r}")
                else:
                    _store_value(f, value_part)
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
                    # str/int flag: consume next token as value
                    if i + 1 < len(tokens):
                        raw = tokens[i + 1]
                        if f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError:
                                raise _ParseError(f"--{f.name}: expected integer, got {raw!r}")
                        else:
                            _store_value(f, raw)
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
                    # str/int flag: consume next token as value
                    if i + 1 < len(tokens):
                        raw = tokens[i + 1]
                        if f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError:
                                raise _ParseError(f"--{f.name}: expected integer, got {raw!r}")
                        else:
                            _store_value(f, raw)
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
                elif f.type is int:
                    try:
                        coerced = _strict_int(env_val)
                    except ValueError:
                        raise _ParseError(
                            f"--{f.name}: expected integer, got {env_val!r} "
                            f"(from env var '{f.env}')"
                        )
                    cli_set[f.name] = [coerced] if f.repeatable else coerced
                else:
                    cli_set[f.name] = [env_val] if f.repeatable else env_val

    # Step 4.5: enforce mutex group constraints (before defaults are applied,
    # so cli_set only contains values explicitly provided via CLI or env)
    for mg in cmd.mutex:
        set_flags = [f for f in mg.flags if f.name in cli_set]
        if len(set_flags) > 1:
            names = " and ".join(f"--{f.name}" for f in set_flags)
            raise _ParseError(f"{names} are mutually exclusive")
        if mg.required and len(set_flags) == 0:
            names = ", ".join(f"--{f.name}" for f in mg.flags)
            raise _ParseError(f"one of {names} is required")

    # Build set of flag names belonging to mutex groups (used in step 5
    # to suppress "required" errors -- mutex groups handle their own
    # required/optional semantics via MutexGroup.required)
    mutex_flag_names: set[str] = set()
    for mg in cmd.mutex:
        for mf in mg.flags:
            mutex_flag_names.add(mf.name)

    # Step 5: apply defaults
    for f in cmd.flags:
        if f.name in cli_set:
            continue
        if f.repeatable:
            # Repeatable flags default to [] (never required)
            cli_set[f.name] = list(f.default) if f.default else []
        elif f.type is bool:
            # Bool flags always have a default (False unless overridden)
            cli_set[f.name] = f.default
        elif f.default is not None:
            cli_set[f.name] = f.default
        elif f.name in mutex_flag_names:
            # Mutex group flags with no default get None instead of being
            # required -- the mutex group itself enforces required semantics
            cli_set[f.name] = None
        else:
            # str/int flag with no default and no value: required
            raise _ParseError(f"flag '--{f.name}' is required")

    # Step 5.5: validate choices
    for f in cmd.flags:
        if f.choices is not None and f.name in cli_set:
            if f.repeatable:
                for val in cli_set[f.name]:
                    if val not in f.choices:
                        choices_str = ", ".join(str(c) for c in f.choices)
                        raise _ParseError(
                            f"--{f.name}: invalid value '{val}', must be one of: {choices_str}"
                        )
            else:
                val = cli_set[f.name]
                if val not in f.choices:
                    choices_str = ", ".join(str(c) for c in f.choices)
                    raise _ParseError(
                        f"--{f.name}: invalid value '{val}', must be one of: {choices_str}"
                    )

    # Step 5.6: custom validation
    for f in cmd.flags:
        if f.validate is not None and f.name in cli_set:
            if f.repeatable:
                for val in cli_set[f.name]:
                    try:
                        f.validate(val)
                    except ValueError as e:
                        raise _ParseError(f"--{f.name}: {e}")
            else:
                try:
                    f.validate(cli_set[f.name])
                except ValueError as e:
                    raise _ParseError(f"--{f.name}: {e}")

    # Step 6: resolve positional args
    arg_values: dict[str, object] = {}
    has_variadic = cmd.args and cmd.args[-1].variadic
    fixed_args = cmd.args[:-1] if has_variadic else cmd.args
    for idx, a in enumerate(fixed_args):
        if idx < len(positionals):
            arg_values[a.name] = positionals[idx]
        elif a.required:
            raise _ParseError(f"missing required argument '{a.name}'")
        elif not isinstance(a.default, _MissingSentinel):
            arg_values[a.name] = a.default
    if has_variadic:
        va = cmd.args[-1]
        remaining_positionals = positionals[len(fixed_args):]
        if va.required and len(remaining_positionals) == 0:
            raise _ParseError(f"missing required argument '{va.name}'")
        arg_values[va.name] = remaining_positionals
    elif len(positionals) > len(cmd.args):
        raise _ParseError(f"unexpected argument '{positionals[len(cmd.args)]}'")

    # Step 7: build kwargs dict (command flags only)
    kwargs: dict[str, object] = {}
    for f in cmd.flags:
        kwargs[_flag_param_name(f.name)] = cli_set[f.name]
    for a in cmd.args:
        if a.name in arg_values:
            kwargs[a.name] = arg_values[a.name]

    # Separate out global flag values parsed from post-command tokens
    global_cli_set: dict[str, object] = {}
    for name in global_flag_names:
        if name in cli_set:
            global_cli_set[name] = cli_set[name]

    return cmd, kwargs, global_cli_set


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
    mutex: list[MutexGroup] | None,
    env_prefix: str | None,
    global_flags: list[Flag] | None = None,
    passthrough: Passthrough | None = None,
) -> Command:
    """Build a Command from a decorated handler, validate everything."""
    if not help or not help.strip():
        raise ValueError(f'command "{name}": missing help text')

    # Passthrough commands must not have flags, args, tags, or mutex groups
    if passthrough is not None:
        decorator_flags = list(getattr(handler, "_strictcli_flags", []))
        decorator_args = list(getattr(handler, "_strictcli_args", []))
        has_flags = bool(decorator_flags)
        has_args = bool(args) or bool(decorator_args)
        has_tags = bool(tags)
        has_mutex = bool(mutex)
        if has_flags or has_args or has_tags or has_mutex:
            parts = []
            if has_flags:
                parts.append("flags")
            if has_args:
                parts.append("args")
            if has_tags:
                parts.append("tags")
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

    # Merge tags into flags
    resolved_tags = list(tags) if tags else []
    tag_flags: list[Flag] = []
    for tag in resolved_tags:
        tag_flags.extend(tag.flags)

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

    # All flags: decorator flags + tag flags + mutex flags
    all_flags = decorator_flags + tag_flags + mutex_flags

    # Validate: no duplicate flag names (catches mutex flags overlapping with
    # regular flags or tag flags)
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
    param_names = set(sig.parameters.keys())

    expected_names: set[str] = set()
    for f in all_flags:
        expected_names.add(_flag_param_name(f.name))
    for a in all_args:
        expected_names.add(a.name)
    # Global flags are also passed to handlers
    if global_flags:
        for gf in global_flags:
            expected_names.add(_flag_param_name(gf.name))

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

    return Command(
        name=name,
        help=help,
        handler=handler,
        flags=all_flags,
        args=all_args,
        tags=resolved_tags,
        mutex=resolved_mutex,
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
    choices: list | None = None,
    validate: Callable | None = None,
    repeatable: bool = False,
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
            choices=choices,
            validate=validate,
            repeatable=repeatable,
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
) -> Callable:
    """Module-level decorator to attach an Arg to a command handler."""

    def decorator(func: Callable) -> Callable:
        a = Arg(name=name, help=help, required=required, default=default, variadic=variadic)
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
    elif f.type is int:
        spec += " <int>"
    return spec


def _build_flag_meta(f: Flag) -> str:
    """Build the bracketed metadata suffix for a flag."""
    meta_parts: list[str] = []
    if f.repeatable:
        meta_parts.append("repeatable")
    if f.choices is not None:
        choices_str = ", ".join(str(c) for c in f.choices)
        meta_parts.append(f"choices: {choices_str}")
    if f.env is not None:
        meta_parts.append(f"env: {f.env}")
    if f.type is bool:
        meta_parts.append(f"default: {'true' if f.default else 'false'}")
    elif f.repeatable:
        # Repeatable flags are never required; no default shown
        pass
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
            if not a.required:
                if not isinstance(a.default, _MissingSentinel):
                    help_text += f" [default: {a.default}]"
                else:
                    help_text += " (optional)"
            lines.append(f"  {dn}{' ' * padding}{help_text}")

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
        label = "Flags (mutually exclusive, required):" if mg.required else "Flags (mutually exclusive):"
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
