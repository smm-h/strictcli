"""A strict, zero-dependency CLI framework for Python."""

from __future__ import annotations

__version__ = "0.7.0"

__all__ = [
    "App", "Flag", "Arg", "Tag", "MutexGroup", "CoRequired", "Requires",
    "Implies", "Passthrough", "DeprecatedCommand", "Result", "flag", "arg",
]

import contextlib
import importlib.metadata
import inspect
import io
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable


# Sentinel for distinguishing "not provided" from actual values
class _MissingSentinel:
    def __repr__(self) -> str:
        return "_MISSING"


_MISSING = _MissingSentinel()


def _config_path(app_name: str) -> str:
    """Compute the config file path for an app."""
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(config_home, app_name, "config.json")


def _load_config(app_name: str) -> dict:
    """Load the JSON config file for an app.

    Returns an empty dict if the file doesn't exist or contains invalid JSON.
    Invalid JSON prints a warning to stderr.
    """
    path = _config_path(app_name)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.loads(f.read())
    except (json.JSONDecodeError, ValueError):
        print(f"warning: invalid JSON in config file '{path}', ignoring", file=sys.stderr)
        return {}


def _coerce_config_value(value: object, flag: "Flag") -> object:
    """Coerce a JSON config value to the flag's type.

    Returns the coerced value, or raises ValueError if coercion fails.
    """
    if flag.type is bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"expected boolean, got {type(value).__name__}")
    if flag.type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ValueError(f"expected integer, got {type(value).__name__}")
    if flag.type is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ValueError(f"expected float, got {type(value).__name__}")
    if flag.type is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"expected string, got {type(value).__name__}")
    raise ValueError(f"unsupported flag type {flag.type}")


class _HelpRequested(Exception):
    """Raised when --help or -h is encountered."""

    def __init__(self, target: object) -> None:
        self.target = target
        super().__init__()


class _VersionRequested(Exception):
    """Raised when --version or -v is encountered."""


class _DumpSchemaRequested(Exception):
    """Raised when --dump-schema is encountered."""


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
    if msg in ("NaN is not allowed", "Inf is not allowed"):
        return _ParseError(f"--{flag_name}: {msg}")
    suffix = f" (from env var '{env}')" if env else ""
    return _ParseError(f"--{flag_name}: expected float, got {raw!r}{suffix}")


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
        if self.type not in (str, bool, int, float):
            raise ValueError(f"Flag.type must be str, bool, int, or float, got {self.type!r}")
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
        # Validate default type for float flags
        if self.type is float and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if not self.repeatable and not isinstance(self.default, (int, float)):
                raise ValueError(
                    f'Flag "{self.name}": type=float requires a float default, '
                    f"got {type(self.default).__name__!r}"
                )
        # Resolve _MISSING sentinels based on type
        if isinstance(self.default, _MissingSentinel):
            if self.repeatable:
                self.default = []
            elif self.type is bool:
                self.default = False
            else:
                # str/int/float with _MISSING default means required (no default)
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
    dependencies: list[CoRequired | Requires | Implies] = field(default_factory=list)
    passthrough: Passthrough | None = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Command")


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

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Group")

    def group(self, name: str, *, help: str) -> Group:
        """Create and register a child subgroup."""
        if name in self.commands:
            raise ValueError(
                f'group "{name}" collides with an existing command'
            )
        if name in self._groups:
            raise ValueError(
                f'group "{name}" is already registered'
            )
        grp = Group(name=name, help=help, env_prefix=self.env_prefix,
                     _global_flags=self._global_flags)
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
        tags: list[Tag] | None = None,
        mutex: list[MutexGroup] | None = None,
        dependencies: list[CoRequired | Requires | Implies] | None = None,
        passthrough: Passthrough | None = None,
    ) -> Callable:
        """Decorator to register a command within this group."""

        def decorator(func: Callable) -> Callable:
            if name in self._groups:
                raise ValueError(
                    f'command "{name}" collides with an existing group'
                )
            cmd = _build_and_validate_command(
                name, help=help, handler=func, args=args, tags=tags, mutex=mutex,
                dependencies=dependencies,
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
    help: str
    version: str | None = None
    env_prefix: str | None = None
    config: bool = False
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
        # Check for duplicate global flag names
        seen: set[str] = set()
        for f in self.flags:
            if f.name in seen:
                raise ValueError(f'duplicate global flag name "{f.name}"')
            seen.add(f.name)
        self._global_flags: list[Flag] = list(self.flags)
        self._last_global_values: dict[str, object] = {}
        # Load config and register config subcommands if enabled
        self._config_data: dict = {}
        if self.config:
            self._config_data = _load_config(self.name)
            self._register_config_group()

    def command(
        self,
        name: str,
        *,
        help: str,
        args: list[Arg] | None = None,
        tags: list[Tag] | None = None,
        mutex: list[MutexGroup] | None = None,
        dependencies: list[CoRequired | Requires | Implies] | None = None,
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
                dependencies=dependencies,
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

        for grp in self._groups.values():
            _collect_from_group(grp)
        return flags

    def _register_config_group(self) -> None:
        """Register the auto-generated 'config' command group."""
        config_grp = Group(
            name="config",
            help="Manage configuration",
            env_prefix=self.env_prefix,
            _global_flags=self._global_flags,
        )

        app_ref = self  # capture for closures

        # config path
        config_grp.commands["path"] = Command(
            name="path",
            help="Print the config file path",
            handler=lambda **_kw: print(_config_path(app_ref.name)),
        )

        # config show
        def _config_show_handler(**_kw) -> None:
            config_data = _load_config(app_ref.name)
            all_flags = app_ref._collect_all_flags()
            for f in all_flags:
                param = _flag_param_name(f.name)
                # Determine source and value
                if param in config_data:
                    value = config_data[param]
                    source = "config"
                elif f.default is not None:
                    value = f.default
                    source = "default"
                else:
                    value = None
                    source = "default"
                print(f"{param} = {value}  (source: {source})")

        config_grp.commands["show"] = Command(
            name="show",
            help="Show all config values with source attribution",
            handler=_config_show_handler,
        )

        # config set
        def _config_set_handler(key, value, **_kw) -> None:
            path = _config_path(app_ref.name)
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            # Read existing config
            existing: dict = {}
            if os.path.isfile(path):
                try:
                    with open(path) as fh:
                        existing = json.loads(fh.read())
                except (json.JSONDecodeError, ValueError):
                    existing = {}
            existing[key] = value
            with open(path, "w") as fh:
                fh.write(json.dumps(existing, indent=2) + "\n")

        config_grp.commands["set"] = Command(
            name="set",
            help="Set a config value",
            handler=_config_set_handler,
            args=[
                Arg(name="key", help="Config key to set"),
                Arg(name="value", help="Value to set"),
            ],
        )

        # config edit
        def _config_edit_handler(**_kw) -> None:
            path = _config_path(app_ref.name)
            dir_path = os.path.dirname(path)
            os.makedirs(dir_path, exist_ok=True)
            if not os.path.isfile(path):
                with open(path, "w") as fh:
                    fh.write("{}\n")
            editor = os.environ.get("EDITOR", "vi")
            subprocess.run([editor, path])

        config_grp.commands["edit"] = Command(
            name="edit",
            help="Open the config file in $EDITOR",
            handler=_config_edit_handler,
        )

        self._groups["config"] = config_grp

    def _parse(self, argv: list[str]) -> tuple[Command, dict[str, object] | list[str]]:
        """Parse argv (without program name) into a resolved Command and kwargs.

        For normal commands, returns (Command, kwargs_dict).
        For passthrough commands, returns (Command, raw_args_list).
        Callers disambiguate by checking cmd.passthrough.

        After parsing, self._last_global_values holds the parsed global flag
        values (used by passthrough command handlers).
        """

        # Step 1: intercept app-level --help/-h, --version/-v, --dump-schema
        if not argv or argv == ["--help"] or argv == ["-h"]:
            raise _HelpRequested(target=self)
        if argv == ["--version"] or argv == ["-v"]:
            raise _VersionRequested()
        if "--dump-schema" in argv:
            raise _DumpSchemaRequested()

        # Step 1.5: parse global flags before command routing
        global_values, remaining = self._parse_global_flags(argv)
        self._last_global_values = global_values

        # Step 2: route to command or group (iterative traversal for arbitrary depth)
        # If global flag parsing stopped at --, strip it before routing
        if remaining and remaining[0] == "--":
            remaining = remaining[1:]

        if not remaining or remaining == ["--help"] or remaining == ["-h"]:
            raise _HelpRequested(target=self)

        current_groups = self._groups
        current_commands = self._commands
        current_deprecated = self._deprecated
        path: list[str] = []  # tracks group names for error messages and help prefix

        while remaining:
            token = remaining[0]

            if token in current_groups:
                group = current_groups[token]
                path.append(token)
                remaining = remaining[1:]

                if not remaining or remaining[0] in ("--help", "-h"):
                    raise _HelpRequested(target=group)

                # Descend into group
                current_groups = group._groups
                current_commands = group.commands
                current_deprecated = group.deprecated
                continue

            if token in current_commands:
                cmd = current_commands[token]
                rest = remaining[1:]
                break

            if token in current_deprecated:
                dep = current_deprecated[token]
                raise _ParseError(
                    f"command '{token}' is deprecated: {dep.message}"
                )

            # Unknown command -- include path in error message
            if path:
                raise _ParseError(
                    f"unknown command '{token}' in '{' '.join(path)}'"
                )
            raise _ParseError(f"unknown command '{token}'")
        else:
            # Loop ended without finding a command -- remaining was exhausted
            # by group traversal. This means the last group had no subcommand.
            # (Already handled by the help check inside the loop, but guard
            # against edge cases.)
            raise _HelpRequested(target=group)

        # Check for command-level --help/-h anywhere in remaining tokens
        # (but not after "--" separator, which makes everything literal)
        if _tokens_contain_help(rest):
            raise _HelpRequested(target=cmd)

        # Passthrough commands: skip all flag/arg parsing, forward raw args
        if cmd.passthrough is not None:
            return cmd, rest

        # Step 3: parse remaining tokens for the resolved command
        cmd, kwargs, post_global = _parse_command(
            cmd, rest, self._global_flags, config_data=self._config_data,
        )

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
                    elif f.type is float:
                        try:
                            _store_value(f, _strict_float(value_part))
                        except ValueError as e:
                            raise _float_parse_error(f.name, value_part, e)
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
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
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
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
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
                    elif f.type is float:
                        try:
                            coerced = _strict_float(env_val)
                        except ValueError as e:
                            raise _float_parse_error(f.name, env_val, e, env=f.env)
                        cli_set[f.name] = [coerced] if f.repeatable else coerced
                    else:
                        cli_set[f.name] = [env_val] if f.repeatable else env_val

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
                    cli_set[f.name] = coerced

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

        # Validate choices for global flags
        for f in self._global_flags:
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
        except _DumpSchemaRequested:
            path = _write_schema(self)
            print(path)
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
        except _DumpSchemaRequested:
            path = _write_schema(self)
            stdout_buf.write(path + "\n")
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


def _tokens_contain_help(tokens: list[str]) -> bool:
    """Check if --help or -h appears in tokens before any -- separator."""
    for tok in tokens:
        if tok == "--":
            return False
        if tok == "--help" or tok == "-h":
            return True
    return False


def _parse_command(
    cmd: Command,
    tokens: list[str],
    global_flags: list[Flag] | None = None,
    config_data: dict | None = None,
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
                elif f.type is float:
                    try:
                        _store_value(f, _strict_float(value_part))
                    except ValueError as e:
                        raise _float_parse_error(f.name, value_part, e)
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
                    # str/int/float flag: consume next token as value
                    if i + 1 < len(tokens):
                        raw = tokens[i + 1]
                        if f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError:
                                raise _ParseError(f"--{f.name}: expected integer, got {raw!r}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
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
                    # str/int/float flag: consume next token as value
                    if i + 1 < len(tokens):
                        raw = tokens[i + 1]
                        if f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError:
                                raise _ParseError(f"--{f.name}: expected integer, got {raw!r}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
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
                elif f.type is float:
                    try:
                        coerced = _strict_float(env_val)
                    except ValueError as e:
                        raise _float_parse_error(f.name, env_val, e, env=f.env)
                    cli_set[f.name] = [coerced] if f.repeatable else coerced
                else:
                    cli_set[f.name] = [env_val] if f.repeatable else env_val

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
                cli_set[f.name] = coerced

    # Step 4.5: enforce mutex group constraints (before defaults are applied,
    # so cli_set only contains values explicitly provided via CLI or env)
    for mg in cmd.mutex:
        set_flags = [f for f in mg.flags if f.name in cli_set]
        if len(set_flags) > 1:
            names = " and ".join(f"--{f.name}" for f in set_flags)
            raise _ParseError(f"{names} are mutually exclusive")
        if len(set_flags) == 0:
            names = ", ".join(f"--{f.name}" for f in mg.flags)
            raise _ParseError(f"one of {names} is required")

    # Step 4.55: resolve Implies dependencies (before dependency checks, so
    # implied values participate in downstream CoRequired/Requires validation)
    for dep in cmd.dependencies:
        if isinstance(dep, Implies):
            if dep.flag in cli_set:
                if dep.implies in cli_set:
                    if cli_set[dep.implies] != dep.value:
                        neg = "no-" if not dep.value else ""
                        explicit_neg = "" if not dep.value else "no-"
                        raise _ParseError(
                            f"flag '--{dep.flag}' implies '--{neg}{dep.implies}', "
                            f"but '--{explicit_neg}{dep.implies}' was explicitly provided"
                        )
                else:
                    cli_set[dep.implies] = dep.value

    # Step 4.6: enforce flag dependencies (before defaults, so cli_set only
    # contains values explicitly provided via CLI or env)
    for dep in cmd.dependencies:
        if isinstance(dep, CoRequired):
            present = [f for f in dep.flags if f in cli_set]
            if 0 < len(present) < len(dep.flags):
                names = ", ".join(f"--{f}" for f in dep.flags)
                raise _ParseError(f"flags {names} must be used together")
        elif isinstance(dep, Requires):
            if dep.flag in cli_set and dep.depends_on not in cli_set:
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
            # str/int/float flag with no default and no value: required
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
    dependencies: list[CoRequired | Requires | Implies] | None = None,
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
    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )
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
        flags=all_flags,
        args=all_args,
        tags=resolved_tags,
        mutex=resolved_mutex,
        dependencies=resolved_dependencies,
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

    if app._deprecated:
        lines.append("")
        lines.append("Deprecated:")
        names = list(app._deprecated.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            dep = app._deprecated[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{dep.message}")

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

    if group.commands:
        lines.append("")
        lines.append("Commands:")
        names = list(group.commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = group.commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    if group._groups:
        lines.append("")
        lines.append("Groups:")
        names = list(group._groups.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            sub = group._groups[name]
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
    elif f.type is float:
        spec += " <float>"
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
# Schema serialization (--dump-schema)
# ---------------------------------------------------------------------------

_TYPE_NAMES = {str: "str", bool: "bool", int: "int", float: "float"}


def _serialize_flag(f: Flag) -> dict:
    """Serialize a Flag to a JSON-serializable dict."""
    return {
        "name": f.name,
        "type": _TYPE_NAMES[f.type],
        "help": f.help,
        "short": f.short,
        "default": f.default,
        "env": f.env,
        "choices": f.choices,
        "repeatable": f.repeatable,
        "negatable": f.negatable if f.type is bool else None,
        "hidden": False,
    }


def _serialize_arg(a: Arg) -> dict:
    """Serialize an Arg to a JSON-serializable dict."""
    return {
        "name": a.name,
        "help": a.help,
        "required": a.required,
        "variadic": a.variadic,
    }


def _serialize_command(cmd: Command) -> dict:
    """Serialize a Command to a JSON-serializable dict."""
    return {
        "name": cmd.name,
        "help": cmd.help,
        "flags": [_serialize_flag(f) for f in cmd.flags],
        "args": [_serialize_arg(a) for a in cmd.args],
        "passthrough": cmd.passthrough is not None,
    }


def _serialize_group(group: Group) -> dict:
    """Serialize a Group to a JSON-serializable dict (recursive)."""
    return {
        "name": group.name,
        "help": group.help,
        "commands": {name: _serialize_command(cmd) for name, cmd in group.commands.items()},
        "groups": {name: _serialize_group(g) for name, g in group._groups.items()},
        "deprecated": {name: dep.message for name, dep in group.deprecated.items()},
    }


def _dump_schema(app: App) -> dict:
    """Produce a JSON-serializable dict representing the app's command tree."""
    return {
        "name": app.name,
        "version": app.version,
        "help": app.help,
        "env_prefix": app.env_prefix,
        "config": app.config,
        "global_flags": [_serialize_flag(f) for f in app._global_flags],
        "commands": {name: _serialize_command(cmd) for name, cmd in app._commands.items()},
        "groups": {name: _serialize_group(grp) for name, grp in app._groups.items()},
        "deprecated": {name: dep.message for name, dep in app._deprecated.items()},
    }


def _write_schema(app: App) -> str:
    """Write the schema to .strictcli/schema.json and return the path."""
    schema = _dump_schema(app)
    dir_path = os.path.join(os.getcwd(), ".strictcli")
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, "schema.json")
    with open(file_path, "w") as f:
        f.write(json.dumps(schema, indent=2) + "\n")
    return file_path
