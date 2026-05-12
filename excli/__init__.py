"""An explicit, zero-dependency CLI framework for Python."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["App", "Flag", "Arg", "Tag", "Result", "flag", "arg"]

import inspect
from dataclasses import dataclass, field
from typing import Callable


# Sentinel for distinguishing "not provided" from actual values
class _MissingSentinel:
    def __repr__(self) -> str:
        return "_MISSING"


_MISSING = _MissingSentinel()


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
                name, help=help, handler=func, args=args, tags=tags, env_prefix=None
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
        grp = Group(name=name, help=help)
        self._groups[name] = grp
        return grp


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
