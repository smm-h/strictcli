"""An explicit, zero-dependency CLI framework for Python."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["App", "Flag", "Arg", "Tag", "Result"]

from dataclasses import dataclass, field
from typing import Callable


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
        # Set sensible defaults based on type
        if self.type is bool and self.default is None:
            self.default = False
        if self.type is str:
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
