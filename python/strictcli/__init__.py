"""A strict CLI framework for Python with mandatory help text, type-safe flags, groups, and schema export."""

from __future__ import annotations

__version__ = "0.39.0"

__all__ = [
    "App", "Flag", "Arg", "FlagSet", "MutexGroup", "CoRequired", "Requires",
    "Implies", "Passthrough", "Forwarding", "DeprecatedCommand", "Result",
    "InvokeError",
    "Grant", "EffectFailed", "Unsettled", "Completed", "Spawned", "Response",
    "PROC_MUTATE", "PROC_SPAWN", "FILE_WRITE", "NET_MUTATE",
    "flag", "arg",
    "CheckContext", "ConnectionEnvReader", "CheckRunResult",
    "ErrorReporter", "WarnReporter", "SkipCheck",
    "CheckSpec", "error_check_spec", "warn_check_spec",
    "format_check_results", "format_check_results_json",
    "ConfigField",
    "Context",
    "Outcome", "outcome",
    "Tool",
    "RelativeToRoot",
]

import ast
import contextlib
import decimal
import keyword
import fnmatch
import inspect
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import tomllib

import tomlkit
from tomlkit.items import InlineTable, Table
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, NamedTuple, Protocol, TypeVar, get_args, get_origin, runtime_checkable

# TypeVar for decorator return types — preserves the decorated function's type
F = TypeVar("F", bound=Callable[..., Any])


# Sentinel for distinguishing "not provided" from actual values
class _MissingSentinel:
    def __repr__(self) -> str:
        return "_MISSING"


_MISSING = _MissingSentinel()

# The envelope contract's own version (effects contract §19.2). Changed only by
# a later amendment to that section.
_INTERFACE_VERSION = 1


class RelativeToRoot:
    """Opaque marker: a filesystem path relative to a declared infrastructure root.

    Produced as ``RelativeToRoot(env_var, *parts)`` and accepted by a flag's
    ``default=`` and by ``App(config_path=...)``. env_var names the root
    (declared via ``App(infra_root={env_var: default})``); parts are joined onto
    the resolved root path. Config-path markers resolve eagerly at construction;
    flag-default markers resolve when defaults are applied at parse time. A marker
    referencing an undeclared root is a registration-time hard error.
    """

    __slots__ = ("env_var", "parts")

    def __init__(self, env_var: str, *parts: str) -> None:
        self.env_var = env_var
        self.parts = list(parts)

    def __repr__(self) -> str:
        return f"RelativeToRoot({self.env_var!r}, {', '.join(map(repr, self.parts))})"


def _serialize_marker(ref: RelativeToRoot) -> dict:
    """Serialize a RelativeToRoot marker to a machine-stable JSON shape.

    Emits only the declared env var and path parts -- never the resolved,
    machine-specific path. The shape is identical across the Python and Go
    implementations so the schema round-trips and cross-language byte-compares.
    """
    return {"relative_to_root": {"env_var": ref.env_var, "parts": list(ref.parts)}}


def _resolve_infra_root_path(ref: RelativeToRoot, roots: dict[str, str]) -> str:
    """Resolve a RelativeToRoot marker against a roots map (env var -> path).

    Raises ValueError if the marker references an undeclared root.
    """
    root = roots.get(ref.env_var)
    if root is None:
        raise ValueError(
            f'RelativeToRoot references undeclared infra root "{ref.env_var}"; '
            f"declare it as an infra root"
        )
    return os.path.join(root, *ref.parts)


def _validate_connection_binding(f: "Flag", connection_env_names) -> None:
    """Enforce the connection-URL binding rules at registration time (mechanical
    enforcement, not review). A URL-class flag must bind to a declared connection
    env; the binding drives env resolution by reusing the per-flag env channel
    (connection_env is folded into env)."""
    if not f.connection_url and f.connection_env is None:
        return
    if f.connection_env is not None and f.env is not None and f.env != f.connection_env:
        raise ValueError(
            f'flag "{f.name}": a connection-URL binding cannot be combined with a per-flag env var'
        )
    if f.connection_url and f.connection_env is None:
        raise ValueError(
            f'flag "{f.name}": connection-URL flag must bind to a declared connection env'
        )
    if f.connection_env is not None and not f.connection_url:
        raise ValueError(
            f'flag "{f.name}": connection env binding requires the flag to be marked as a connection-URL flag'
        )
    if f.connection_env not in connection_env_names:
        raise ValueError(
            f'flag "{f.name}": connection-URL flag binds to undeclared connection env '
            f'"{f.connection_env}"; declare it as a connection env'
        )
    f.env = f.connection_env


# ---------------------------------------------------------------------------
# Source provenance (Phase 0c)
# ---------------------------------------------------------------------------

class _Source:
    """Where a flag value came from."""
    CLI = "cli"          # explicitly passed on the command line
    ENV = "env"          # from an environment variable
    CONFIG = "config"    # from a config file
    DEFAULT = "default"  # from the flag's default value
    IMPLIED = "implied"  # injected by an Implies dependency
    INFRA = "infra"      # default resolved through a RelativeToRoot infra root


class _SourcedEntry:
    """A value paired with its provenance source."""
    __slots__ = ("value", "source")

    def __init__(self, value: object, source: str) -> None:
        self.value = value
        self.source = source


class _SourcedStore:
    """Map of flag-name to _SourcedEntry with source-filtered presence queries.

    Replaces the plain ``cli_set: dict[str, object]`` in the validation
    pipeline, adding provenance tracking for each value.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _SourcedEntry] = {}

    def set(self, name: str, value: object, source: str) -> None:
        self._entries[name] = _SourcedEntry(value, source)

    def get(self, name: str) -> tuple[object, bool]:
        """Return (value, True) or (None, False)."""
        e = self._entries.get(name)
        if e is None:
            return None, False
        return e.value, True

    def has(self, name: str) -> bool:
        return name in self._entries

    def get_value(self, name: str) -> object:
        """Return the value or raise KeyError."""
        return self._entries[name].value

    def set_value(self, name: str, value: object) -> None:
        """Update the value of an existing entry, keeping its source."""
        self._entries[name].value = value

    def is_present_for_mutex(self, name: str) -> bool:
        """Present for mutex: only cli, env, config. NOT default or implied."""
        e = self._entries.get(name)
        if e is None:
            return False
        return e.source in (_Source.CLI, _Source.ENV, _Source.CONFIG)

    def is_present_for_deps(self, name: str) -> bool:
        """Present for deps (CoRequired, Requires): everything except default."""
        e = self._entries.get(name)
        if e is None:
            return False
        return e.source != _Source.DEFAULT

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __setitem__(self, name: str, value: object) -> None:
        # Convenience for migration: stores with SourceCLI by default.
        # Only used in parsing contexts where source is CLI.
        self._entries[name] = _SourcedEntry(value, _Source.CLI)

    def __getitem__(self, name: str) -> object:
        return self._entries[name].value

    def source_map(self) -> dict[str, str]:
        """Return a dict mapping flag names to source labels."""
        return {k: e.source for k, e in self._entries.items()}

    @classmethod
    def from_dict(cls, d: dict[str, object], source: str) -> "_SourcedStore":
        """Build a store from a plain dict, marking all entries with source."""
        store = cls()
        for k, v in d.items():
            store.set(k, v, source)
        return store


class _InfraAccess:
    """A Context's view of infrastructure env vars: resolved root values
    (captured at construction), declared handshake env vars (read live), and
    declared connection env vars (read live, but suppressed under --hermetic)."""

    __slots__ = ("roots", "handshakes", "connections", "hermetic")

    def __init__(self, roots: dict[str, str], handshakes: set[str],
                 connections: set[str] | None = None, hermetic: bool = False) -> None:
        self.roots = roots
        self.handshakes = handshakes
        self.connections = connections or set()
        self.hermetic = hermetic


class Context:
    """Structured output context for command handlers.

    Always injected as the first positional argument to every handler.
    Provides info/warn/debug/error methods that route to the correct stream,
    plus source/infra_value provenance accessors. To return structured data,
    a handler returns ``strictcli.outcome(data=...)``.
    """

    def __init__(self, stdout=None, stderr=None, sources=None, infra=None,
                 *, dry_run: bool = False,
                 approve_consequential: bool = False,
                 quiet: bool = False, verbose: bool = False,
                 json: bool = False,
                 effects: "_Effects | None" = None,
                 command_name: str = "",
                 payload_schema: object | None = None):
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._sources = sources or {}  # flag-name -> source label (cli/env/config/default/implied/infra)
        self._infra = infra  # _InfraAccess | None
        self._dry_run = dry_run
        self._approve_consequential = approve_consequential
        self._quiet = quiet
        self._verbose = verbose
        self._json = json
        self._effects = effects
        # The payload slot (contract §19.4): at most one value per dispatch,
        # settable only on a command that declared a payload schema.
        self._command_name = command_name
        self._payload_schema = payload_schema
        self._payload_value: object = _MISSING
        # The diagnostics this dispatch emitted, in emission order (contract
        # §19.2). In machine mode the context writers record here instead of
        # writing: what they were asked to say rides the envelope. Outside
        # machine mode the list stays empty and nothing changes.
        self._diagnostics: list[dict] = []

    @property
    def dry_run(self) -> bool:
        """True when the framework-owned ``--dry-run`` flag was passed."""
        return self._dry_run

    @property
    def approve_consequential(self) -> bool:
        """True when the framework-owned ``--approve-consequential`` flag was passed."""
        return self._approve_consequential

    @property
    def quiet(self) -> bool:
        """True when the framework-owned ``--quiet`` flag was passed."""
        return self._quiet

    @property
    def verbose(self) -> bool:
        """True when the framework-owned ``--verbose`` flag was passed."""
        return self._verbose

    @property
    def json(self) -> bool:
        """True when the framework-owned ``--json`` flag was passed.

        ``--json`` selects machine mode (contract §19.1). Handlers do not
        branch on it to decide whether to build a payload -- ``ctx.payload``
        is mode-independent and the framework decides what to do with the
        value -- but the flag is exposed for symmetry with the quartet and for
        apps that propagate it to a child process.
        """
        return self._json

    def payload(self, value: object) -> None:
        """Supply this dispatch's machine payload (contract §19.4).

        The call is mode-independent: a handler calls it identically in both
        modes and never branches on ``ctx.json``. In machine mode the value is
        emitted; outside machine mode it is not printed at all. ``test()`` and
        ``call()`` capture it either way.

        Three hard errors, all at call time:

        - the command declared no ``payload_schema=``, so there is nothing to
          validate the value against;
        - a payload was already supplied in this dispatch (one slot, one
          answer);
        - the value does not satisfy the declared schema (contract §19.5): a
          wrong shape fails here instead of shipping.
        """
        if self._payload_schema is None:
            raise RuntimeError(_msg_payload_no_schema(self._command_name))
        if self._payload_value is not _MISSING:
            raise RuntimeError(_msg_payload_already_set(self._command_name))
        found = _validate_payload_value(value, self._payload_schema)
        if found is not None:
            path, detail = found
            raise RuntimeError(
                _msg_payload_invalid(self._command_name, path, detail)
            )
        self._payload_value = value

    @property
    def effects(self) -> "_Effects":
        """The effects handle for this run (see the effects-regime contract)."""
        if self._effects is None:
            raise RuntimeError(_msg_effects_unavailable())
        return self._effects

    def _diagnostic(self, level: str, msg: str) -> bool:
        """Record a diagnostic in machine mode. True when it was recorded.

        In machine mode the writers below write nothing and what they were
        asked to say rides the envelope's ``diagnostics`` instead (§19.1).
        The recording is NOT filtered by ``--quiet`` or ``--verbose``: the
        envelope's content is a function of what the run produced, never of how
        a terminal was configured (§19.2).
        """
        if not self._json:
            return False
        self._diagnostics.append({"level": level, "message": msg})
        return True

    def info(self, msg: str) -> None:
        """Write an informational message to stdout (hidden under --quiet)."""
        if self._diagnostic("info", msg):
            return
        if self._quiet:
            return
        print(msg, file=self._stdout)

    def warn(self, msg: str) -> None:
        """Write a warning message to stderr (never suppressed)."""
        if self._diagnostic("warn", msg):
            return
        print(msg, file=self._stderr)

    def debug(self, msg: str) -> None:
        """Write a debug message to stdout (shown only under --verbose).

        ``--quiet`` dominates ``--verbose``: passing both hides debug output.
        """
        if self._diagnostic("debug", msg):
            return
        if self._quiet or not self._verbose:
            return
        print(msg, file=self._stdout)

    def error(self, msg: str) -> None:
        """Write an error message to stderr (never suppressed)."""
        if self._diagnostic("error", msg):
            return
        print(msg, file=self._stderr)

    def source(self, name: str) -> str:
        """Return the provenance source label for a flag.

        Returns one of: "cli", "env", "config", "default", "implied", "infra".
        ("infra" indicates the value came from a RelativeToRoot default resolved
        through a declared infrastructure root.)
        Raises KeyError if the flag name is not found.
        """
        key = name.replace("-", "_")
        if key in self._sources:
            return self._sources[key]
        # Try original name (with dashes)
        if name in self._sources:
            return self._sources[name]
        raise KeyError(f"no source info for flag {name!r}")

    def infra_value(self, env_var: str) -> tuple[str | None, bool]:
        """Return the value of a declared infrastructure env var.

        For a declared location root (``infra_root``), returns the value
        resolved eagerly at construction (env var if set, else the declared
        default) and ``True`` -- the resolved value is always available.

        For a declared handshake var (``handshake_env``), reads the environment
        LIVE at call time (handshakes are set by the invoking process and carry
        no construction-time value), returning ``(value, is_set)``.

        For a declared connection env (``connection_env``), reads the environment
        LIVE at call time and returns ``(value, is_set)`` -- EXCEPT under
        --hermetic, where it resolves as absent ``(None, False)`` so
        connection-dependent behavior skips visibly instead of connecting.

        Raises KeyError if env_var is not a declared root, handshake, or
        connection var.
        """
        if self._infra is not None:
            if env_var in self._infra.roots:
                return self._infra.roots[env_var], True
            if env_var in self._infra.handshakes:
                if env_var in os.environ:
                    return os.environ[env_var], True
                return None, False
            if env_var in self._infra.connections:
                if self._infra.hermetic:
                    return None, False
                if env_var in os.environ:
                    return os.environ[env_var], True
                return None, False
        raise KeyError(
            f'"{env_var}" is not a declared infra root, handshake, or connection env var'
        )

    def connection_env_value(self, env_var: str) -> tuple[str | None, bool]:
        """Return the value of a declared connection env (``connection_env``),
        read LIVE at call time -- EXCEPT under --hermetic, where it resolves as
        absent ``(None, False)``. Raises KeyError if env_var is not a declared
        connection env. This is the check-side and handler-side accessor for the
        connection-URL kind; see also ``infra_value``, which resolves all three
        kinds.
        """
        if self._infra is not None and env_var in self._infra.connections:
            if self._infra.hermetic:
                return None, False
            if env_var in os.environ:
                return os.environ[env_var], True
            return None, False
        raise KeyError(
            f'"{env_var}" is not a declared connection env var'
        )


# ---------------------------------------------------------------------------
# The effects regime
#
# Command classification (read_only / mutating), the ctx.effects handle, dry
# mode's would-do log, and the Unsettled carriers that make a data-flow preview
# complete without letting the framework invent a value it cannot know.
#
# Two rules govern the whole regime: FAIL CLOSED (when the framework cannot
# prove an operation is safe to preview, it stops with a precise error instead
# of guessing) and ZERO INFERENCE (nothing is inferred -- not classification,
# not whether an argument is a path, not whether a resource is current).
# ---------------------------------------------------------------------------

# Effect kinds. CACHE_WRITE has NO public method: it is minted only by
# framework-internal code (schema dump, test-coverage shards and manifest) and
# is unreachable from application code.
PROC_MUTATE = "proc_mutate"
PROC_SPAWN = "proc_spawn"
FILE_WRITE = "file_write"
NET_MUTATE = "net_mutate"
CACHE_WRITE = "cache_write"

# The kinds a Grant may be declared for (CACHE_WRITE is excluded: it is not
# reachable from application code, so nothing could ever use such a grant).
_GRANTABLE_KINDS = (PROC_MUTATE, PROC_SPAWN, FILE_WRITE, NET_MUTATE)
_GRANT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class EffectFailed(Exception):
    """A failed effect operation.

    A failed operation is an error, not a value: a ``run`` whose child exits
    nonzero and an ``http`` whose status is outside 200-299 raise this, as does
    invalid UTF-8 on a captured stream. ``check=False`` opts a single call out.
    """


class _DryRunTruncated(BaseException):
    """Raised when handler code extracts from or branches on an Unsettled value.

    Derives from BaseException deliberately: a handler's ``except Exception``
    must not be able to swallow the truncation and let the preview continue
    with a value the framework refuses to invent.
    """

    def __init__(self, message: str, log: "_EffectLog", *,
                 step: int, cmd_path: str, brand: str) -> None:
        super().__init__(message)
        self.message = message
        self.log = log
        # The three values §12.5's text is built from, kept apart from it so
        # the envelope's preview_error can carry them as members (§19.3)
        # without re-parsing the rendered message.
        self.step = step
        self.cmd_path = cmd_path
        self.brand = brand


@dataclass(frozen=True)
class Grant:
    """A per-command, per-effect-kind authorization with a mandatory reason.

    A grant is not permission to do something otherwise forbidden; it is a
    labelled reason that surfaces in the preview so a reviewer reading a dry
    run sees why a dangerous step is there.
    """

    name: str
    reason: str
    kind: str


@dataclass(frozen=True)
class Completed:
    """The result of a subprocess that ran to completion.

    ``stdout``/``stderr`` are the child's output decoded as UTF-8 strictly,
    with a single trailing newline removed if present -- the form that can be
    forwarded straight into a later effect's argv.
    """

    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Response:
    """The result of an HTTP request. Header names are lower-cased."""

    status: int
    body: bytes
    headers: dict


@dataclass(frozen=True)
class Spawned:
    """A handle for a started-but-not-awaited child process."""

    pid: int
    _proc: object = field(default=None, repr=False, compare=False)
    _cmd_path: str = field(default="", repr=False, compare=False)

    def wait(self, *, check: bool = True) -> Completed:
        """Wait for the child and return its Completed result.

        ``check`` mirrors ``run``'s opt-out: with the default ``True`` a
        nonzero exit raises :class:`EffectFailed`.
        """
        code = self._proc.wait()
        argv = " ".join(str(a) for a in self._proc.args)
        if check and code != 0:
            # One template covers run and spawn (the method name is the
            # parameter), so the parity catalogs carry one signature, not two.
            _raise_effect_run_failed(self._cmd_path, "spawn", argv, code)
        # spawn always streams (the child inherits stdio), so there is nothing
        # captured to report.
        return Completed(exit_code=code, stdout="", stderr="")


# The dunders Unsettled poisons. Every one of them is an EXTRACTION or a
# BRANCH: reading a concrete value out of a carrier, or deciding something from
# it. `__repr__` is the single non-poisoned dunder (so debuggers, tracebacks and
# logging never themselves detonate) and `__class__` is untouched (isinstance
# must work -- the effects API uses it at the forwarding boundary).
_UNSETTLED_POISONED_DUNDERS = (
    "__bool__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__hash__", "__len__", "__iter__", "__contains__", "__getitem__",
    "__getattr__", "__int__", "__float__", "__index__", "__str__",
    "__format__", "__bytes__", "__add__", "__radd__", "__mod__", "__rmod__",
    "__call__", "__setattr__",
)


class Unsettled:
    """A value standing in for a result that cannot exist because nothing ran.

    Produced by every mutating effect recorded in dry mode and by every
    post-mutation observe. FORWARDING one into a later ``ctx.effects`` call is
    legal and renders its brand inline; EXTRACTING from it or BRANCHING on it
    truncates the preview with a precise error.
    """

    __slots__ = ("_brand", "_log", "_cmd_path", "_forwardable")

    def __init__(self, brand: str, log: "_EffectLog", cmd_path: str,
                 forwardable: bool) -> None:
        # ``__setattr__`` is poisoned like every other extraction dunder, so the
        # constructor writes its own slots through ``object`` -- otherwise a
        # carrier could not be built at all. Poisoning the write side is what
        # stops ``u._brand = "«forged»"`` from minting a fake preview line and
        # ``u._forwardable = True`` from making a void carrier forwardable,
        # which is the same seal Go gets from unexported fields and TypeScript
        # from the Proxy's `set` trap.
        _set = object.__setattr__
        _set(self, "_brand", brand)
        _set(self, "_log", log)
        _set(self, "_cmd_path", cmd_path)
        # Void results (write/mkdir/remove/rename/chmod) and spawn results have
        # no scalar projection, so they are never forwardable -- in either mode.
        _set(self, "_forwardable", forwardable)

    def __repr__(self) -> str:
        return f"Unsettled({self._brand})"

    def _truncate(self) -> "_DryRunTruncated":
        step = self._log.next_seq()
        return _DryRunTruncated(
            _msg_dry_run_truncated(step, self._cmd_path, self._brand),
            self._log,
            step=step, cmd_path=self._cmd_path, brand=self._brand,
        )


def _make_poisoned_dunder(dunder_name: str):
    def _poisoned(self, *args, **kwargs):
        raise self._truncate()

    _poisoned.__name__ = dunder_name
    _poisoned.__qualname__ = f"Unsettled.{dunder_name}"
    _poisoned.__doc__ = (
        "Poisoned: extracting from or branching on an unsettled value "
        "truncates the dry-run preview."
    )
    return _poisoned


for _dunder in _UNSETTLED_POISONED_DUNDERS:
    setattr(Unsettled, _dunder, _make_poisoned_dunder(_dunder))
del _dunder


@dataclass
class _EffectRecord:
    """One entry in the structured effect log (see the conformance surface)."""

    seq: int
    kind: str
    verb: str
    detail: str
    bytes: int | None = None
    resource: str | None = None
    skip_if_current: str | None = None
    grant: str | None = None
    grant_reason: str | None = None
    recorded: bool = False

    def to_dict(self) -> dict:
        d: dict = {
            "seq": self.seq,
            "kind": self.kind,
            "verb": self.verb,
            "detail": self.detail,
            "recorded": self.recorded,
        }
        if self.bytes is not None:
            d["bytes"] = self.bytes
        if self.resource is not None:
            d["resource"] = self.resource
        if self.skip_if_current is not None:
            d["skip_if_current"] = self.skip_if_current
        if self.grant is not None:
            d["grant"] = self.grant
        return d

    def render(self) -> str:
        """Render this record as a would-do log line (without the indent)."""
        line = f"{self.seq}. {self.verb}: {self.detail}"
        if self.grant is not None:
            line += f" (granted: {self.grant} — {self.grant_reason})"
        if self.skip_if_current is not None:
            line += f" [unless resource '{self.skip_if_current}' already current]"
        return line


_DRY_RUN_HEADER = "DRY RUN — no changes were made. Would do:"


class _EffectLog:
    """The ordered effect records produced by one dispatch.

    TWO counters, deliberately. Would-do numbering is the numbering of the
    RENDERED lines: it feeds the log's ``<N>.`` prefix, the ``«step N output»``
    brand and the truncation error's "ends at step N". CACHE_WRITEs are never
    rendered, so they must never consume one of those numbers -- otherwise a
    coverage-instrumented run would silently start its preview at ``2.``. They
    get their own sequence instead, so every record still carries a ``seq``.
    """

    __slots__ = ("records", "_rendered", "_cached")

    def __init__(self) -> None:
        self.records: list[_EffectRecord] = []
        self._rendered = 0
        self._cached = 0

    def append(self, rec: _EffectRecord) -> None:
        self.records.append(rec)
        if rec.kind == CACHE_WRITE:
            self._cached += 1
        else:
            self._rendered += 1

    def next_seq(self) -> int:
        """The next would-do number. Pure: callers may ask without appending."""
        return self._rendered + 1

    def next_cache_seq(self) -> int:
        """The next CACHE_WRITE number, on its own counter."""
        return self._cached + 1

    def render(self) -> str:
        """Render the would-do log. CACHE_WRITEs are never written to it."""
        lines = [_DRY_RUN_HEADER]
        for rec in self.records:
            if rec.kind == CACHE_WRITE:
                continue
            lines.append("  " + rec.render())
        return "\n".join(lines)

    def to_list(self) -> list[dict]:
        return [rec.to_dict() for rec in self.records]


# Message templates that are NOT raised -- printed to stderr, or carried on a
# non-ValueError exception. Every one is a `_msg_*` function returning the
# finished string, which is the shape conformance/check_error_parity.py extracts
# (mirroring the Go `err*`/`prompt*` functions in errors.go and their TypeScript
# twins). A template that is only ever inlined at its use site is invisible to
# the extractor and silently drops out of the cross-language catalog.

def _msg_dry_run_truncated(step: int, cmd: str, brand: str) -> str:
    """The truncation error. Carries its own `error: ` prefix (it goes to
    stderr directly, not through the parse-error formatter)."""
    return (
        f"error: dry-run preview ends at step {step}: {cmd} branched on "
        f"unsettled value {brand} — cannot preview past this point"
    )


def _msg_dry_run_aborted(step: int, cmd: str) -> str:
    """The aborted-preview marker. Same shape and prefix as the truncation
    error above: both say the preview ended before the handler finished, and
    they differ only in why and in what the reader may conclude."""
    return (
        f"error: dry-run preview ends at step {step}: {cmd} aborted — "
        f"the preview above may be incomplete"
    )


def _msg_confirm_prompt(cmd_path: str) -> str:
    """The confirm prompt. A prompt, not an error, but parity is still checked."""
    return f"about to run consequential command '{cmd_path}'. Proceed? [y/N] "


def _strip_confirm_line(answer: str) -> str:
    """Strip the confirm answer's line terminator: one ``\\n``, then one ``\\r``.

    Exactly one of each, never more. The carriage return matters because a human
    at a Windows console types the same ``y`` as everyone else and their terminal
    terminates the line CRLF; a stdin stream that does not translate newlines
    hands us ``"y\\r\\n"``, and declining there would refuse an answer that was
    plainly given. Stripping only the terminator (rather than whitespace) keeps
    ``"  y"`` a decline, which §8.2 requires.
    """
    if answer.endswith("\n"):
        answer = answer[:-1]
    if answer.endswith("\r"):
        answer = answer[:-1]
    return answer


def _msg_confirm_non_interactive() -> str:
    return (
        "error: stdin is not interactive; pass --approve-consequential to confirm"
    )


def _msg_confirm_declined() -> str:
    return "aborted"


class _ConfirmIO:
    """The stdin side of the confirm protocol, isolated so tests can drive it.

    The TypeScript twin is the ``ConfirmIO`` interface in ``confirm.ts`` and the
    Go twin is the ``ConfirmIO`` struct; the two members mean the same thing in
    all three. Swapping it changes WHERE the answer comes from, never WHETHER
    the protocol runs -- there is no bypass here and never will be.
    """

    def is_interactive(self) -> bool:
        """True when stdin is a TTY."""
        return sys.stdin.isatty()

    def read_line(self) -> str:
        """Read one line from stdin, terminator included."""
        return sys.stdin.readline()


_REAL_CONFIRM_IO = _ConfirmIO()


def _msg_call_consequential_unconsented(cmd_path: str) -> str:
    """The programmatic-path refusal (contract §8.5).

    Requiring confirmation is a property of the COMMAND, so every channel has
    to honour it -- but a programmatic caller has no terminal to prompt. The
    refusal makes the caller state, in the call, that it is proceeding without
    a human, instead of the framework deciding that silently on its behalf.
    """
    return (
        f"command '{cmd_path}' is consequential: pass approve_consequential "
        f"to confirm"
    )


def _consequential_grant_warning(cmd_path: str, grant: str, kind: str) -> str:
    """The `consequential-grant-agreement` warning (contract §8.1, §11).

    A grant exists so a reviewer reading a preview sees WHY a dangerous step is
    there (§6.1) -- the same judgement ``consequential`` makes. When the grant's
    kind is one that leaves this process (``proc_mutate`` runs another program,
    ``net_mutate`` changes remote state), the two declarations should almost
    always agree. They can legitimately disagree, so this is a warning: making
    it an error would push consumers to declare ``consequential`` reflexively
    to clear a gate, which is exactly the reflex the declaration exists to end.
    """
    return (
        f"command '{cmd_path}' declares grant '{grant}' (kind {kind}) but is "
        f"not consequential: a {kind} effect leaves this process and the "
        f"framework cannot walk it back, and the grant already says the step "
        f"is worth explaining. Declare the command consequential, or drop the "
        f"grant if the step is routine."
    )


def _observe_allowlist_breadth_warning(binary: str) -> str:
    """The `observe-allowlist-breadth` warning (contract §6.2).

    A one-token prefix is a near-blanket exemption for that binary: EVERY
    invocation of it becomes an observe, which means it really executes under
    ``--dry-run``, is never written to the would-do log, and is legal inside a
    ``read_only`` command. That may be exactly what the app wants -- the
    allowlist is a declared, source-visible choice and it authorizes real
    execution in dry mode -- so this is a warning, not an error.
    """
    return (
        f"proc_observe_allowlist prefix ['{binary}'] is a single token: EVERY "
        f"'{binary}' invocation becomes an observe, so it really executes under "
        f"--dry-run, is never logged, and is legal in a read_only command. "
        f"Narrow it to the subcommands you actually observe."
    )


def _msg_effects_unavailable() -> str:
    return (
        "ctx.effects is unavailable: this Context was constructed "
        "outside a command dispatch"
    )


def _msg_payload_no_schema(name: str) -> str:
    """Message template: ctx.payload on a command declaring no schema (§19.4).

    Registration cannot see that a handler intends to call ctx.payload, so
    call time is the earliest honest point at which the missing declaration
    can be named.
    """
    return (
        f'command "{name}": ctx.payload requires a declared payload schema'
    )


def _msg_payload_already_set(name: str) -> str:
    """Message template: a second ctx.payload call in one dispatch (§19.4).

    Two payloads are two answers to a question with one slot; picking either
    silently is the kind of guess this regime does not make.
    """
    return (
        f'command "{name}": ctx.payload was already called '
        f"(a dispatch carries at most one payload)"
    )


def _msg_payload_schema_invalid(name: str, path: str, detail: str) -> str:
    """Message template: a declared payload schema is outside the subset (§19.5).

    Registration time. ``path`` names the position inside the declared literal
    (rooted at ``payload_schema``) and ``detail`` names the violated rule. Both
    are byte-identical across the three implementations, pinned by
    ``conformance/payload_schema_vectors.json``.
    """
    return (
        f'command "{name}": payload schema is invalid at {path}: {detail}'
    )


def _msg_payload_invalid(name: str, path: str, detail: str) -> str:
    """Message template: a payload deviates from its declared schema (§19.5).

    Emission time. ``path`` names the position inside the value (rooted at
    ``payload``) and ``detail`` names the violated constraint, so a wrong shape
    fails here instead of shipping.
    """
    return (
        f"command \"{name}\": payload does not satisfy the declared schema "
        f"at {path}: {detail}"
    )


# ---------------------------------------------------------------------------
# The declared payload schema's validator (contract §19.5)
#
# Two duties over one deliberately closed subset:
#
#   * registration-time validation of the declared literal -- an unknown
#     keyword anywhere is a hard error, which is what keeps the subset closed;
#   * emission-time validation of the value a handler supplies through
#     ctx.payload -- a payload that deviates from its declaration fails here
#     rather than shipping a wrong shape.
#
# Every detail string below is byte-identical to the Go and TypeScript
# validators'. They are deliberately NOT named ``_msg_*``: the error-parity
# extractor reads only the two outer templates above, and the details are
# pinned across implementations by the shared vectors instead.
# ---------------------------------------------------------------------------

# The closed subset, in the order the "unknown keyword" message lists it.
_PAYLOAD_SCHEMA_KEYWORDS = (
    "additionalProperties", "const", "enum", "items", "properties",
    "required", "type",
)

# The JSON Schema type names the subset admits, sorted.
_PAYLOAD_JSON_TYPES = (
    "array", "boolean", "integer", "null", "number", "object", "string",
)

# Decision 16's guard. Every IEEE-754 double whose magnitude exceeds 2^53 is
# already an integer (the spacing between representable doubles is at least 1
# from 2^52 upward), so "any integer above 2^53" and "any number above 2^53"
# are the same set -- which is why the guard is a plain magnitude test.
_PAYLOAD_MAX_MAGNITUDE = 2 ** 53

_PDETAIL_NOT_JSON = "the value is not representable in JSON"
_PDETAIL_MAGNITUDE = (
    "the number's magnitude exceeds 2^53 (declare a big identifier as a string)"
)
_PDETAIL_TYPE_SHAPE = '"type" must be a string or an array of strings'
_PDETAIL_TYPE_EMPTY = '"type" must not be an empty array'
_PDETAIL_PROPERTIES_SHAPE = '"properties" must be an object'
_PDETAIL_REQUIRED_SHAPE = '"required" must be an array of strings'
_PDETAIL_ENUM_SHAPE = '"enum" must be a non-empty array'
_PDETAIL_ADDPROPS_SHAPE = (
    '"additionalProperties" must be a boolean or a schema object'
)
_PDETAIL_ENUM_MISMATCH = "the value is not one of the declared enum values"
_PDETAIL_CONST_MISMATCH = "the value does not equal the declared const"


def _payload_quote(s: str) -> str:
    """Quote a string for a message or a path segment.

    §19.5's escaping regime, applied to one string: escape exactly what JSON
    mandates and emit everything else literally. ``json.dumps`` with
    ``ensure_ascii=False`` is precisely that; the Go and TypeScript validators
    hand-roll the same rule.
    """
    return json.dumps(s, ensure_ascii=False)


def _pdetail_unknown_keyword(kw: str) -> str:
    subset = ", ".join(_PAYLOAD_SCHEMA_KEYWORDS)
    return (
        f"unknown keyword {_payload_quote(kw)} "
        f"(the closed subset is: {subset})"
    )


def _pdetail_unknown_type(t: str) -> str:
    types = ", ".join(_PAYLOAD_JSON_TYPES)
    return (
        f"unknown type {_payload_quote(t)} "
        f"(the JSON Schema types are: {types})"
    )


def _pdetail_schema_not_object(got: str) -> str:
    return f"a schema must be an object, got {got}"


def _pdetail_type_duplicate(t: str) -> str:
    return f'"type" has a duplicate entry {_payload_quote(t)}'


def _pdetail_required_duplicate(k: str) -> str:
    return f'"required" has a duplicate entry {_payload_quote(k)}'


def _pdetail_expected_type(declared, got: str) -> str:
    """The type-mismatch detail, in its single and its list form."""
    if isinstance(declared, str):
        return f"expected type {_payload_quote(declared)}, got {got}"
    inner = ", ".join(_payload_quote(t) for t in declared)
    return f"expected type [{inner}], got {got}"


def _pdetail_required_missing(k: str) -> str:
    return f"required property {_payload_quote(k)} is missing"


def _pdetail_not_permitted(k: str) -> str:
    return (
        f"property {_payload_quote(k)} is not permitted "
        f"(additionalProperties is false)"
    )


def _payload_path_key(path: str, key: str) -> str:
    return f"{path}[{_payload_quote(key)}]"


def _payload_path_index(path: str, index: int) -> str:
    return f"{path}[{index}]"


def _payload_kind(value: object) -> str | None:
    """The JSON kind of a value, or None when it is not representable.

    ``integer`` is reported for any number with a zero fractional part, which
    is JSON Schema's own reading of the type and the only one three languages
    can agree on -- TypeScript has no separate integer type at all.
    ``bool`` is a subclass of ``int`` in Python and is deliberately classified
    first, so a boolean is never a number.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return "integer" if value.is_integer() else "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                return None
        return "object"
    return None


def _payload_over_magnitude(value: object) -> bool:
    """True when a number exceeds decision 16's magnitude guard."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) > _PAYLOAD_MAX_MAGNITUDE
    if isinstance(value, float):
        return abs(value) > float(_PAYLOAD_MAX_MAGNITUDE)
    return False


def _payload_scan_value(value: object, path: str):
    """Document check: representability and the magnitude guard, recursively.

    Runs over the WHOLE value before any keyword is consulted, so a payload
    that could not be emitted at all is reported as that rather than as a type
    mismatch. Traversal is deterministic in every implementation: arrays in
    index order, objects in sorted-key order.

    Returns ``(path, detail)`` for the first violation, or None.
    """
    kind = _payload_kind(value)
    if kind is None:
        return (path, _PDETAIL_NOT_JSON)
    if _payload_over_magnitude(value):
        return (path, _PDETAIL_MAGNITUDE)
    if kind == "array":
        for i, item in enumerate(value):
            found = _payload_scan_value(item, _payload_path_index(path, i))
            if found is not None:
                return found
    elif kind == "object":
        for key in sorted(value):
            found = _payload_scan_value(
                value[key], _payload_path_key(path, key)
            )
            if found is not None:
                return found
    return None


def _payload_deep_equal(a: object, b: object) -> bool:
    """JSON-value equality, used by ``enum`` and ``const``.

    Type-aware on purpose: a boolean is never equal to a number (Python's
    ``True == 1`` is exactly the trap this closes), and two numbers are equal
    when their values are, so ``1`` matches a declared ``1.0``.
    """
    ka = _payload_kind(a)
    kb = _payload_kind(b)
    if ka is None or kb is None:
        return False
    if ka in ("integer", "number") and kb in ("integer", "number"):
        return float(a) == float(b)
    if ka != kb:
        return False
    if ka == "null":
        return True
    if ka == "boolean":
        return bool(a) is bool(b)
    if ka == "string":
        return a == b
    if ka == "array":
        if len(a) != len(b):
            return False
        return all(_payload_deep_equal(x, y) for x, y in zip(a, b))
    # object
    if set(a) != set(b):
        return False
    return all(_payload_deep_equal(a[k], b[k]) for k in a)


def _payload_type_matches(declared: str, kind: str) -> bool:
    if declared == "integer":
        return kind == "integer"
    if declared == "number":
        return kind in ("integer", "number")
    return declared == kind


def _validate_payload_schema(schema: object, path: str = "payload_schema"):
    """Registration-time validation of one declared schema literal (§19.5).

    Returns ``(path, detail)`` for the first violation, or None. The keyword
    scan is sorted, so which of several violations is reported never depends on
    a dict's iteration order.
    """
    kind = _payload_kind(schema)
    if kind != "object":
        return (path, _pdetail_schema_not_object(kind or "unsupported"))

    for kw in sorted(schema):
        if kw not in _PAYLOAD_SCHEMA_KEYWORDS:
            return (path, _pdetail_unknown_keyword(kw))

    if "type" in schema:
        t = schema["type"]
        if isinstance(t, str):
            if t not in _PAYLOAD_JSON_TYPES:
                return (path, _pdetail_unknown_type(t))
        elif isinstance(t, list):
            if not t:
                return (path, _PDETAIL_TYPE_EMPTY)
            seen: list[str] = []
            for entry in t:
                if not isinstance(entry, str) or isinstance(entry, bool):
                    return (path, _PDETAIL_TYPE_SHAPE)
                if entry in seen:
                    return (path, _pdetail_type_duplicate(entry))
                seen.append(entry)
            for entry in t:
                if entry not in _PAYLOAD_JSON_TYPES:
                    return (path, _pdetail_unknown_type(entry))
        else:
            return (path, _PDETAIL_TYPE_SHAPE)

    if "required" in schema:
        req = schema["required"]
        if not isinstance(req, list):
            return (path, _PDETAIL_REQUIRED_SHAPE)
        seen_req: list[str] = []
        for entry in req:
            if not isinstance(entry, str) or isinstance(entry, bool):
                return (path, _PDETAIL_REQUIRED_SHAPE)
            if entry in seen_req:
                return (path, _pdetail_required_duplicate(entry))
            seen_req.append(entry)

    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values:
            return (path, _PDETAIL_ENUM_SHAPE)
        for i, entry in enumerate(values):
            found = _payload_scan_value(
                entry, _payload_path_index(f"{path}.enum", i)
            )
            if found is not None:
                return found

    if "const" in schema:
        found = _payload_scan_value(schema["const"], f"{path}.const")
        if found is not None:
            return found

    if "properties" in schema:
        props = schema["properties"]
        if _payload_kind(props) != "object":
            return (path, _PDETAIL_PROPERTIES_SHAPE)
        for key in sorted(props):
            found = _validate_payload_schema(
                props[key], _payload_path_key(f"{path}.properties", key)
            )
            if found is not None:
                return found

    if "items" in schema:
        found = _validate_payload_schema(schema["items"], f"{path}.items")
        if found is not None:
            return found

    if "additionalProperties" in schema:
        ap = schema["additionalProperties"]
        if not isinstance(ap, bool):
            if _payload_kind(ap) != "object":
                return (path, _PDETAIL_ADDPROPS_SHAPE)
            found = _validate_payload_schema(
                ap, f"{path}.additionalProperties"
            )
            if found is not None:
                return found

    return None


def _validate_payload_instance(value: object, schema: dict, path: str):
    """Emission-time validation of one value against one declared schema.

    Check order is pinned so that a value violating several constraints always
    reports the same one: type, then const, then enum, then (for an object)
    required, declared properties in sorted key order, and finally the
    additional properties in sorted key order; then (for an array) the items.

    Returns ``(path, detail)`` for the first violation, or None.
    """
    kind = _payload_kind(value)
    if kind is None:
        return (path, _PDETAIL_NOT_JSON)

    if "type" in schema:
        declared = schema["type"]
        if isinstance(declared, str):
            if not _payload_type_matches(declared, kind):
                return (path, _pdetail_expected_type(declared, kind))
        else:
            if not any(_payload_type_matches(t, kind) for t in declared):
                return (path, _pdetail_expected_type(list(declared), kind))

    if "const" in schema:
        if not _payload_deep_equal(value, schema["const"]):
            return (path, _PDETAIL_CONST_MISMATCH)

    if "enum" in schema:
        if not any(_payload_deep_equal(value, e) for e in schema["enum"]):
            return (path, _PDETAIL_ENUM_MISMATCH)

    if kind == "object":
        props = schema.get("properties")
        declared_names = set(props) if isinstance(props, dict) else set()
        for key in schema.get("required", ()):
            if key not in value:
                return (path, _pdetail_required_missing(key))
        if isinstance(props, dict):
            for key in sorted(props):
                if key in value:
                    found = _validate_payload_instance(
                        value[key], props[key], _payload_path_key(path, key)
                    )
                    if found is not None:
                        return found
        if "additionalProperties" in schema:
            ap = schema["additionalProperties"]
            if ap is not True:
                for key in sorted(value):
                    if key in declared_names:
                        continue
                    if ap is False:
                        return (path, _pdetail_not_permitted(key))
                    found = _validate_payload_instance(
                        value[key], ap, _payload_path_key(path, key)
                    )
                    if found is not None:
                        return found

    if kind == "array" and "items" in schema:
        for i, item in enumerate(value):
            found = _validate_payload_instance(
                item, schema["items"], _payload_path_index(path, i)
            )
            if found is not None:
                return found

    return None


def _validate_payload_value(value: object, schema: dict):
    """The whole emission-time duty: the document check, then the keywords."""
    found = _payload_scan_value(value, "payload")
    if found is not None:
        return found
    return _validate_payload_instance(value, schema, "payload")


# ---------------------------------------------------------------------------
# Builder sugar for the declared payload schema (contract §19.5, decision 14)
#
# Pure constructors of literals, and nothing more. They add no vocabulary and
# no semantics: each one produces exactly the dict an author could have
# written, that dict is the canonical artifact, and it passes the identical
# registration-time validation. A builder is a convenience for writing the
# canonical artifact, never an alternative to it -- which is why none of them
# validates anything: an unknown type name written through ``schema_type`` is
# rejected at registration exactly as the hand-written literal would be.
#
# The one-to-one mapping onto the closed subset is pinned across the three
# implementations by conformance/payload_schema_builders.json.
# ---------------------------------------------------------------------------


def schema_type(*names: str) -> dict:
    """``{"type": ...}`` -- one name, or a list of them for nullability."""
    if len(names) == 1:
        return {"type": names[0]}
    return {"type": list(names)}


def schema_array(items: dict) -> dict:
    """``{"type": "array", "items": ...}``."""
    return {"type": "array", "items": items}


def schema_object(
    *,
    properties: dict | None = None,
    required: list[str] | None = None,
    additional_properties: bool | dict | None = None,
) -> dict:
    """``{"type": "object", ...}``.

    Each keyword is emitted only when supplied, so ``schema_object()`` is the
    bare ``{"type": "object"}`` and an omitted ``additional_properties`` means
    the keyword is absent rather than ``true`` -- absence and ``true`` are the
    same behaviour but not the same declaration.
    """
    out: dict = {"type": "object"}
    if properties is not None:
        out["properties"] = properties
    if required is not None:
        out["required"] = required
    if additional_properties is not None:
        out["additionalProperties"] = additional_properties
    return out


def schema_enum(*values: object) -> dict:
    """``{"enum": [...]}``."""
    return {"enum": list(values)}


def schema_const(value: object) -> dict:
    """``{"const": ...}``."""
    return {"const": value}


def _msg_effect_argv_not_sequence(name: str, method: str, got: str) -> str:
    return (
        f'command "{name}": effects.{method} argv must be a '
        f"sequence of strings, not {got}"
    )


def _msg_effect_param_not_stringish(name: str, method: str, param: str,
                                    got: str) -> str:
    return (
        f'command "{name}": effects.{method} parameter '
        f"'{param}' must be a string, a path, or a forwarded effect result; "
        f"got {got}"
    )


def _msg_effect_mode_not_int(name: str, got: str) -> str:
    return (
        f'command "{name}": effects.chmod parameter \'mode\' '
        f"must be an int, got {got}"
    )


def _msg_effect_http_method_not_str(name: str, got: str) -> str:
    return (
        f'command "{name}": effects.http parameter \'method\' '
        f"must be a string, got {got}"
    )


def _msg_effect_option_not_accepted(name: str, method: str, opt: str) -> str:
    """An option the receiving method does not accept (contract §12.8).

    Python reaches this through each method's `**_options` catch-all rather than
    through CPython's native `unexpected keyword argument` TypeError, so the
    rendered text is byte-identical to Go's and TypeScript's.  `<opt>` is the
    canonical snake_case option name, which is what makes that identity hold.
    """
    return f'command "{name}": effects.{method} does not accept option \'{opt}\''


def _reject_unaccepted_options(name: str, method: str, options: dict) -> None:
    """Raise on the first unaccepted option, in the caller's declaration order.

    A `TypeError`, matching every other call-time argument guard on the handle
    (and what CPython itself raises for an unexpected keyword).
    """
    for opt in options:
        raise TypeError(_msg_effect_option_not_accepted(name, method, opt))


def _raise_effect_mutating_in_read_only(name: str, method: str):
    raise ValueError(
        f'command "{name}" is classified read_only; effects.{method} is a '
        f"mutating operation"
    )


def _raise_effect_run_not_allowlisted(name: str, argv: str):
    raise ValueError(
        f'command "{name}" is classified read_only; effects.run argv {argv} '
        f"is not on the app's proc_observe_allowlist"
    )


def _raise_effect_grant_undeclared(name: str, grant: str):
    raise ValueError(f'command "{name}": grant \'{grant}\' is not declared on this command')


def _raise_effect_grant_kind_mismatch(name: str, grant: str, k1: str, k2: str):
    raise ValueError(
        f'command "{name}": grant \'{grant}\' is declared for kind {k1} but '
        f"was used for a {k2} effect"
    )


def _raise_effect_grant_on_observe(name: str, grant: str):
    raise ValueError(
        f'command "{name}": grant \'{grant}\' cannot be used on an observe '
        f"(an allowlisted effects.run changes nothing)"
    )


def _raise_effect_run_failed(name: str, method: str, argv: str, code: int):
    raise EffectFailed(f'command "{name}": effects.{method} failed: {argv} exited {code}')


def _raise_effect_http_failed(name: str, http_method: str, url: str, status: int):
    raise EffectFailed(
        f'command "{name}": effects.http failed: {http_method} {url} '
        f"returned {status}"
    )


def _raise_effect_output_not_utf8(name: str, method: str, *, cause=None):
    raise EffectFailed(
        f'command "{name}": effects.{method} produced output that is not valid UTF-8'
    ) from cause


def _raise_effect_param_rejects_carrier(name: str, method: str, param: str):
    raise ValueError(
        f'command "{name}": effects.{method} parameter \'{param}\' does not '
        f"accept an unsettled value"
    )


def _raise_grant_reason_empty(name: str, grant: str):
    raise ValueError(f'command "{name}": grant \'{grant}\' reason must be a non-empty string')


def _raise_grant_duplicate(name: str, grant: str):
    raise ValueError(f'command "{name}": duplicate grant \'{grant}\'')


def _raise_grant_name_invalid(name: str, grant: str):
    raise ValueError(
        f'command "{name}": invalid grant name \'{grant}\': '
        f"must match [a-z][a-z0-9-]*"
    )


def _raise_grant_kind_invalid(name: str, grant: str, kind: object):
    raise ValueError(
        f'command "{name}": grant \'{grant}\' has invalid kind \'{kind}\': '
        f"must be one of proc_mutate, proc_spawn, file_write, net_mutate"
    )


_CARRIER_TYPES = (Unsettled, Completed, Response, Spawned)


class _Effects:
    """The effects handle reached as ``ctx.effects``.

    Exactly eight methods, and the set is CLOSED: there is no escape hatch that
    mints an unlisted effect, and CACHE_WRITE has no public method at all.
    """

    __slots__ = ("_cmd", "_cmd_path", "_dry_run", "_log", "_allowlist",
                 "_grants", "_mutation_recorded")

    def __init__(self, *, cmd: "Command", cmd_path: str, dry_run: bool,
                 log: _EffectLog, allowlist: tuple) -> None:
        self._cmd = cmd
        self._cmd_path = cmd_path
        self._dry_run = dry_run
        self._log = log
        self._allowlist = allowlist
        self._grants = {g.name: g for g in cmd.grants}
        self._mutation_recorded = False

    # -- helpers ---------------------------------------------------------

    def _reject_carrier_params(self, method: str, params: dict) -> None:
        """Hard-error when a carrier reaches a parameter that cannot take one."""
        for param, value in params.items():
            if isinstance(value, _CARRIER_TYPES):
                _raise_effect_param_rejects_carrier(self._cmd_path, method, param)
            if isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(k, _CARRIER_TYPES) or isinstance(v, _CARRIER_TYPES):
                        _raise_effect_param_rejects_carrier(
                            self._cmd_path, method, param,
                        )

    def _operand(self, value: object, method: str, param: str) -> tuple:
        """Resolve a carrier-accepting parameter.

        Returns ``(runtime_value, rendered)``. ``runtime_value`` is ``None``
        when the value is unsettled (nothing ran, so there is nothing to use);
        ``rendered`` is what the log line shows.
        """
        if isinstance(value, Unsettled):
            if not value._forwardable:
                _raise_effect_param_rejects_carrier(self._cmd_path, method, param)
            return None, value._brand
        if isinstance(value, Spawned):
            # A Spawned has no scalar projection.
            _raise_effect_param_rejects_carrier(self._cmd_path, method, param)
        if isinstance(value, Completed):
            return value.stdout, value.stdout
        if isinstance(value, Response):
            text = _decode_effect_output(
                value.body, self._cmd_path, "http",
            )
            return text, text
        if isinstance(value, str):
            return value, value
        if isinstance(value, os.PathLike):
            text = os.fspath(value)
            if isinstance(text, bytes):
                text = text.decode()
            return text, text
        raise TypeError(_msg_effect_param_not_stringish(
            self._cmd_path, method, param, type(value).__name__,
        ))

    def _content_operand(self, value: object) -> tuple:
        """Resolve ``write``'s content. Returns ``(bytes_or_None, rendered)``.

        The rendered form is the encoded byte count for a settled value, and the
        forwarded carrier's brand when the content is unsettled (there is no
        byte count to report -- nothing produced the bytes).
        """
        if isinstance(value, bytes):
            return value, f"{len(value)} bytes"
        if isinstance(value, str):
            data = value.encode("utf-8")
            return data, f"{len(data)} bytes"
        runtime, rendered = self._operand(value, "write", "content")
        if runtime is None:
            return None, rendered
        data = runtime.encode("utf-8")
        return data, f"{len(data)} bytes"

    def _authorize(self, method: str, kind: str, grant: str | None) -> Grant | None:
        """Read-only enforcement plus grant validation, at call time."""
        if self._cmd.effect == EFFECT_READ_ONLY:
            _raise_effect_mutating_in_read_only(self._cmd_path, method)
        return self._check_grant(kind, grant)

    def _check_grant(self, kind: str, grant: str | None) -> Grant | None:
        if grant is None:
            return None
        declared = self._grants.get(grant)
        if declared is None:
            _raise_effect_grant_undeclared(self._cmd_path, grant)
        if declared.kind != kind:
            _raise_effect_grant_kind_mismatch(
                self._cmd_path, grant, declared.kind, kind,
            )
        return declared

    def _record(self, *, kind: str, verb: str, detail: str,
                resource: str | None, skip_if_current: str | None,
                grant: Grant | None, nbytes: int | None = None,
                recorded: bool) -> _EffectRecord:
        rec = _EffectRecord(
            seq=self._log.next_seq(),
            kind=kind,
            verb=verb,
            detail=detail,
            bytes=nbytes,
            resource=resource,
            skip_if_current=skip_if_current,
            grant=grant.name if grant is not None else None,
            grant_reason=grant.reason if grant is not None else None,
            recorded=recorded,
        )
        self._log.append(rec)
        return rec

    def _carrier(self, seq: int, *, forwardable: bool) -> Unsettled:
        self._mutation_recorded = True
        return Unsettled(f"«step {seq} output»", self._log, self._cmd_path,
                         forwardable)

    def _stale(self, descr: str) -> Unsettled:
        return Unsettled(f"«stale: {descr}»", self._log, self._cmd_path, True)

    def _is_observe(self, argv: list) -> bool:
        """Element-wise argv-prefix matching by string equality. Nothing else."""
        for prefix in self._allowlist:
            if len(prefix) > len(argv):
                continue
            if all(
                isinstance(argv[i], str) and argv[i] == prefix[i]
                for i in range(len(prefix))
            ):
                return True
        return False

    def _resolve_argv(self, argv: object, method: str) -> tuple:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, (list, tuple)):
            raise TypeError(_msg_effect_argv_not_sequence(
                self._cmd_path, method, type(argv).__name__,
            ))
        if not argv:
            raise ValueError(
                f'command "{self._cmd_path}": effects.{method} argv must not be empty'
            )
        runtime: list = []
        rendered: list[str] = []
        for i, element in enumerate(argv):
            r, text = self._operand(element, method, f"argv[{i}]")
            runtime.append(r)
            rendered.append(text)
        return runtime, rendered

    # -- the eight methods -------------------------------------------------
    #
    # Every method DECLARES its settled return type and nothing else --
    # `Completed`, `Spawned`, `Response`, `None`. There is no `| Unsettled`
    # union in the surface and no is_unsettled() predicate, because branching
    # on unsettledness IS mode-branching: a declared union would oblige every
    # handler to narrow before touching `.stdout`, which is exactly the silent
    # mode-branch the truncation mechanism exists to prevent. In dry mode the
    # runtime value sitting at these positions is the `Unsettled` carrier,
    # which the static type deliberately does not mention -- a handler that
    # only forwards it never notices, and a handler that extracts from it
    # truncates the preview at runtime, where it is honest. A handler that
    # legitimately needs the mode reads `ctx.dry_run`.

    def run(self, argv: Sequence[str | Completed | Response], *, cwd=None,
            env=None, check=True, stream=False, resource=None,
            skip_if_current=None, grant=None, **_options) -> Completed:
        """Run a subprocess to completion (PROC_MUTATE, or an observe)."""
        _reject_unaccepted_options(self._cmd_path, "run", _options)
        self._reject_carrier_params("run", {
            "cwd": cwd, "env": env, "check": check, "stream": stream,
            "resource": resource,
            "skip_if_current": skip_if_current, "grant": grant,
        })
        runtime, rendered = self._resolve_argv(argv, "run")
        joined = " ".join(rendered)

        if self._is_observe(runtime):
            # An observe changes nothing: it is legal in a read_only command,
            # never written to the would-do log, and never carries a grant.
            if grant is not None:
                _raise_effect_grant_on_observe(self._cmd_path, grant)
            if self._dry_run and self._mutation_recorded:
                return self._stale(joined)
            return self._exec_run(runtime, joined, cwd, env, check, stream, "run")

        if self._cmd.effect == EFFECT_READ_ONLY:
            _raise_effect_run_not_allowlisted(self._cmd_path, joined)
        declared = self._check_grant(PROC_MUTATE, grant)

        if self._dry_run:
            rec = self._record(
                kind=PROC_MUTATE, verb="run", detail=joined, resource=resource,
                skip_if_current=skip_if_current, grant=declared, recorded=True,
            )
            return self._carrier(rec.seq, forwardable=True)

        self._record(
            kind=PROC_MUTATE, verb="run", detail=joined, resource=resource,
            skip_if_current=skip_if_current, grant=declared, recorded=False,
        )
        return self._exec_run(runtime, joined, cwd, env, check, stream, "run")

    def spawn(self, argv: Sequence[str | Completed | Response], *, cwd=None,
              env=None, resource=None, skip_if_current=None,
              grant=None, **_options) -> Spawned:
        """Start a subprocess without waiting (PROC_SPAWN).

        Spawning is itself an effect: a dry run RECORDS the spawn instead of
        performing it, which is why no cross-process mode token exists.
        """
        _reject_unaccepted_options(self._cmd_path, "spawn", _options)
        self._reject_carrier_params("spawn", {
            "cwd": cwd, "env": env, "resource": resource,
            "skip_if_current": skip_if_current, "grant": grant,
        })
        runtime, rendered = self._resolve_argv(argv, "spawn")
        joined = " ".join(rendered)
        declared = self._authorize("spawn", PROC_SPAWN, grant)

        if self._dry_run:
            rec = self._record(
                kind=PROC_SPAWN, verb="spawn", detail=joined, resource=resource,
                skip_if_current=skip_if_current, grant=declared, recorded=True,
            )
            return self._carrier(rec.seq, forwardable=False)

        self._record(
            kind=PROC_SPAWN, verb="spawn", detail=joined, resource=resource,
            skip_if_current=skip_if_current, grant=declared, recorded=False,
        )
        proc = subprocess.Popen(
            self._settled_argv(runtime, joined, "spawn"),
            cwd=cwd, env=self._merged_env(env),
        )
        return Spawned(pid=proc.pid, _proc=proc, _cmd_path=self._cmd_path)

    def write(self, path: str | os.PathLike[str] | Completed | Response,
              content: str | bytes | Completed | Response, *, resource=None,
              skip_if_current=None, grant=None, **_options) -> None:
        """Write bytes to a path (FILE_WRITE)."""
        _reject_unaccepted_options(self._cmd_path, "write", _options)
        self._reject_carrier_params("write", {
            "resource": resource, "skip_if_current": skip_if_current,
            "grant": grant,
        })
        rt_path, rendered_path = self._operand(path, "write", "path")
        data, rendered_content = self._content_operand(content)
        detail = f"{rendered_path} ({rendered_content})"
        declared = self._authorize("write", FILE_WRITE, grant)
        nbytes = len(data) if data is not None else None

        if self._dry_run:
            rec = self._record(
                kind=FILE_WRITE, verb="write", detail=detail, resource=resource,
                skip_if_current=skip_if_current, grant=declared, nbytes=nbytes,
                recorded=True,
            )
            return self._carrier(rec.seq, forwardable=False)

        self._record(
            kind=FILE_WRITE, verb="write", detail=detail, resource=resource,
            skip_if_current=skip_if_current, grant=declared, nbytes=nbytes,
            recorded=False,
        )
        with open(self._settled(rt_path, "write", "path"), "wb") as fh:
            fh.write(data)
        return None

    def mkdir(self, path: str | os.PathLike[str] | Completed | Response, *,
              resource=None, skip_if_current=None, grant=None,
              **_options) -> None:
        """Create a directory, parents included; an existing one is not an error."""
        _reject_unaccepted_options(self._cmd_path, "mkdir", _options)
        return self._path_effect(
            "mkdir", path, resource, skip_if_current, grant,
            lambda p: os.makedirs(p, exist_ok=True),
        )

    def remove(self, path: str | os.PathLike[str] | Completed | Response, *,
               resource=None, skip_if_current=None, grant=None,
               **_options) -> None:
        """Remove a file, symlink or directory tree; a missing path is not an error."""
        _reject_unaccepted_options(self._cmd_path, "remove", _options)
        return self._path_effect(
            "remove", path, resource, skip_if_current, grant, _remove_path,
        )

    def rename(self, src: str | os.PathLike[str] | Completed | Response,
               dst: str | os.PathLike[str] | Completed | Response, *,
               resource=None, skip_if_current=None, grant=None,
               **_options) -> None:
        """Move/rename a path (FILE_WRITE)."""
        _reject_unaccepted_options(self._cmd_path, "rename", _options)
        self._reject_carrier_params("rename", {
            "resource": resource, "skip_if_current": skip_if_current,
            "grant": grant,
        })
        rt_src, r_src = self._operand(src, "rename", "src")
        rt_dst, r_dst = self._operand(dst, "rename", "dst")
        detail = f"{r_src} -> {r_dst}"
        declared = self._authorize("rename", FILE_WRITE, grant)

        if self._dry_run:
            rec = self._record(
                kind=FILE_WRITE, verb="rename", detail=detail, resource=resource,
                skip_if_current=skip_if_current, grant=declared, recorded=True,
            )
            return self._carrier(rec.seq, forwardable=False)

        self._record(
            kind=FILE_WRITE, verb="rename", detail=detail, resource=resource,
            skip_if_current=skip_if_current, grant=declared, recorded=False,
        )
        os.replace(
            self._settled(rt_src, "rename", "src"),
            self._settled(rt_dst, "rename", "dst"),
        )
        return None

    def chmod(self, path: str | os.PathLike[str] | Completed | Response, mode,
              *, resource=None, skip_if_current=None, grant=None,
              **_options) -> None:
        """Change a path's mode (FILE_WRITE)."""
        _reject_unaccepted_options(self._cmd_path, "chmod", _options)
        self._reject_carrier_params("chmod", {
            "mode": mode, "resource": resource,
            "skip_if_current": skip_if_current, "grant": grant,
        })
        if not isinstance(mode, int) or isinstance(mode, bool):
            raise TypeError(_msg_effect_mode_not_int(
                self._cmd_path, type(mode).__name__,
            ))
        rt_path, r_path = self._operand(path, "chmod", "path")
        detail = f"{r_path} 0{mode:o}"
        declared = self._authorize("chmod", FILE_WRITE, grant)

        if self._dry_run:
            rec = self._record(
                kind=FILE_WRITE, verb="chmod", detail=detail, resource=resource,
                skip_if_current=skip_if_current, grant=declared, recorded=True,
            )
            return self._carrier(rec.seq, forwardable=False)

        self._record(
            kind=FILE_WRITE, verb="chmod", detail=detail, resource=resource,
            skip_if_current=skip_if_current, grant=declared, recorded=False,
        )
        os.chmod(self._settled(rt_path, "chmod", "path"), mode)
        return None

    def http(self, method, url: str | os.PathLike[str] | Completed | Response,
             *, body=None, headers=None, check=True, resource=None,
             skip_if_current=None, grant=None, **_options) -> Response:
        """Perform a network request (NET_MUTATE)."""
        _reject_unaccepted_options(self._cmd_path, "http", _options)
        self._reject_carrier_params("http", {
            "method": method, "body": body, "headers": headers,
            "check": check, "resource": resource,
            "skip_if_current": skip_if_current, "grant": grant,
        })
        if not isinstance(method, str):
            raise TypeError(_msg_effect_http_method_not_str(
                self._cmd_path, type(method).__name__,
            ))
        rt_url, r_url = self._operand(url, "http", "url")
        detail = f"{method} {r_url}"
        declared = self._authorize("http", NET_MUTATE, grant)

        if self._dry_run:
            rec = self._record(
                kind=NET_MUTATE, verb="net", detail=detail, resource=resource,
                skip_if_current=skip_if_current, grant=declared, recorded=True,
            )
            return self._carrier(rec.seq, forwardable=True)

        self._record(
            kind=NET_MUTATE, verb="net", detail=detail, resource=resource,
            skip_if_current=skip_if_current, grant=declared, recorded=False,
        )
        return self._exec_http(
            method, self._settled(rt_url, "http", "url"), body, headers, check,
        )

    # -- shared execution paths ------------------------------------------

    def _path_effect(self, verb, path, resource, skip_if_current, grant, perform):
        self._reject_carrier_params(verb, {
            "resource": resource, "skip_if_current": skip_if_current,
            "grant": grant,
        })
        rt_path, r_path = self._operand(path, verb, "path")
        declared = self._authorize(verb, FILE_WRITE, grant)

        if self._dry_run:
            rec = self._record(
                kind=FILE_WRITE, verb=verb, detail=r_path, resource=resource,
                skip_if_current=skip_if_current, grant=declared, recorded=True,
            )
            return self._carrier(rec.seq, forwardable=False)

        self._record(
            kind=FILE_WRITE, verb=verb, detail=r_path, resource=resource,
            skip_if_current=skip_if_current, grant=declared, recorded=False,
        )
        perform(self._settled(rt_path, verb, "path"))
        return None

    def _settled(self, value, method, param):
        if value is None:
            # Unreachable: an unsettled operand only survives in dry mode, where
            # nothing executes. Kept as a fail-closed backstop.
            _raise_effect_param_rejects_carrier(self._cmd_path, method, param)
        return value

    def _settled_argv(self, runtime, joined, method):
        for i, element in enumerate(runtime):
            if element is None:
                _raise_effect_param_rejects_carrier(
                    self._cmd_path, method, f"argv[{i}]",
                )
        return list(runtime)

    def _merged_env(self, env):
        """``env`` merges OVER the inherited environment, never replacing it."""
        if env is None:
            return None
        merged = dict(os.environ)
        merged.update({str(k): str(v) for k, v in env.items()})
        return merged

    def _exec_run(self, runtime, joined, cwd, env, check, stream, method):
        argv = self._settled_argv(runtime, joined, method)
        proc = subprocess.run(
            argv, cwd=cwd, env=self._merged_env(env),
            capture_output=not stream,
        )
        if stream:
            out = err = ""
        else:
            out = _decode_effect_output(proc.stdout, self._cmd_path, method)
            err = _decode_effect_output(proc.stderr, self._cmd_path, method)
        if check and proc.returncode != 0:
            _raise_effect_run_failed(
                self._cmd_path, method, joined, proc.returncode,
            )
        return Completed(exit_code=proc.returncode, stdout=out, stderr=err)

    def _exec_http(self, method, url, body, headers, check):
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, data=body, method=method)
        for key, value in (headers or {}).items():
            req.add_header(str(key), str(value))
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                payload = resp.read()
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            status = e.code
            payload = e.read()
            hdrs = {k.lower(): v for k, v in e.headers.items()}
        if check and not (200 <= status <= 299):
            _raise_effect_http_failed(self._cmd_path, method, url, status)
        return Response(status=status, body=payload, headers=hdrs)


def _decode_effect_output(data: bytes, cmd_path: str, method: str) -> str:
    """Decode captured output as UTF-8 strictly, dropping one trailing newline."""
    if data is None:
        return ""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        _raise_effect_output_not_utf8(cmd_path, method, cause=e)
    if text.endswith("\n"):
        text = text[:-1]
    return text


def _remove_path(path: str) -> None:
    """Remove a file, a symlink or a directory tree. A missing path is fine."""
    import shutil

    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _validate_grants(cmd_name: str, grants) -> tuple:
    """Validate a command's grant declarations at registration time."""
    resolved: list[Grant] = []
    seen: set[str] = set()
    for g in grants or ():
        if not isinstance(g, Grant):
            raise ValueError(
                f'command "{cmd_name}": grants must be Grant instances, '
                f"got {type(g).__name__}"
            )
        if not isinstance(g.name, str) or not _GRANT_NAME_RE.fullmatch(g.name):
            _raise_grant_name_invalid(cmd_name, g.name)
        if g.name in seen:
            _raise_grant_duplicate(cmd_name, g.name)
        if not isinstance(g.reason, str) or not g.reason.strip():
            _raise_grant_reason_empty(cmd_name, g.name)
        if g.kind not in _GRANTABLE_KINDS:
            _raise_grant_kind_invalid(cmd_name, g.name, g.kind)
        seen.add(g.name)
        resolved.append(g)
    return tuple(resolved)


# ---------------------------------------------------------------------------
# The effects-bypass lint (the `effects-bypass` check provider, see below)
#
# Closed lists, matched on the called attribute/function name: process starts,
# filesystem mutations, and network calls. The analyser is stdlib `ast` -- a
# regular dependency, no optional import and no soft degradation.
#
# Several leaves are RECEIVER-SCOPED: a name alone is not evidence of an
# effect, and a finding a consumer cannot act on is worse than no finding.
# `mapping.get(...)` is not a network call and `platform.system()` is not a
# process start, so those leaves are banned only through a receiver the
# module's own imports let the analyser resolve.
# ---------------------------------------------------------------------------

_BYPASS_PROCESS = frozenset({
    "run", "Popen", "call", "check_call", "check_output", "getoutput",
    "getstatusoutput", "popen", "execv", "execvp", "execve",
    "spawnv", "spawnl", "fork",
})
# Process leaves that start a process only through `os`. `system` is the whole
# set: `os.system` runs a shell, but `platform.system()` is a pure in-process
# string read -- no process, no effect, and nothing the effects handle could
# carry, since its closed method set has no in-process-observe method. Banning
# the leaf on any receiver produced a finding whose own remediation ("route it
# through ctx.effects") could not be followed, which is the one thing a lint
# must never emit. An UNKNOWN receiver (`foo.system()`) is exempt for the same
# reason the network leaves are receiver-scoped: without a resolvable binding
# to `os` there is no evidence a process starts, and a name is not evidence.
_BYPASS_PROCESS_OS_ONLY = frozenset({"system"})
_BYPASS_OS_RECEIVERS = frozenset({"os"})
_BYPASS_FILESYSTEM = frozenset({
    "remove", "unlink", "rmdir", "removedirs", "mkdir", "makedirs",
    "rename", "renames", "replace", "chmod", "chown", "symlink", "link",
    "truncate", "rmtree", "move", "copy", "copy2", "copyfile", "copytree",
    "write_text", "write_bytes", "touch", "symlink_to", "hardlink_to",
    "mkstemp", "mkdtemp",
})
_BYPASS_NETWORK = frozenset({
    "urlopen", "urlretrieve", "request", "get", "post", "put", "patch",
    "delete", "head", "HTTPConnection", "HTTPSConnection", "socket",
    "create_connection",
})
# Network members are banned only when reached through one of these receivers,
# so an ordinary `mapping.get(...)` inside a handler is not a finding.
_BYPASS_NETWORK_RECEIVERS = frozenset({
    "requests", "httpx", "urllib", "request", "http", "client", "socket",
    "aiohttp", "urllib3", "session", "Session",
})
_BYPASS_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    "site-packages", "build", "dist", ".tox", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", ".eggs",
})
# The modules whose imports bind a receiver the analyser trusts. Closed, like
# every other list here: `import requests as rq` must resolve to `requests` and
# `from os import system` to `os`, while `from mylib import get` must bind
# NOTHING -- widening this to every module would re-create exactly the ordinary
# `mapping.get(...)` noise the network receiver list exists to remove.
_BYPASS_EFFECT_MODULES = frozenset({
    "os", "os.path", "subprocess", "shutil", "pathlib", "socket", "tempfile",
    "requests", "httpx", "urllib", "urllib.request", "http", "http.client",
    "aiohttp", "urllib3",
})


class _BypassImports(NamedTuple):
    """What a module's imports say about the names it calls.

    ``receivers`` maps a bound module name to the effect module it denotes
    (``import os as o`` -> ``{"o": "os"}``); ``calls`` maps a bound member name
    to the ``(module, member)`` pair it came from (``from os import system as
    sh`` -> ``{"sh": ("os", "system")}``). Both are used to normalize a call
    before the ban lists see it, so the lists stay written in terms of real
    module and member names rather than whatever the consumer spelled.
    """

    receivers: dict
    calls: dict


_BYPASS_NO_IMPORTS = _BypassImports({}, {})


def _bypass_import_bindings(tree) -> _BypassImports:
    """Names bound to effect modules and to their members, in one module.

    Relative imports are skipped: ``from .os import system`` is the consumer's
    own module, not the stdlib one, and the analyser cannot resolve it.
    """
    receivers: dict = {}
    calls: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in _BYPASS_EFFECT_MODULES:
                    continue
                if alias.asname is None:
                    # `import os.path` binds `os`, and `os.system` still works.
                    bound = module = alias.name.split(".")[0]
                else:
                    bound = alias.asname
                    module = alias.name.rsplit(".", 1)[-1]
                receivers[bound] = module
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in _BYPASS_EFFECT_MODULES:
                continue
            module = node.module.rsplit(".", 1)[-1]
            for alias in node.names:
                calls[alias.asname or alias.name] = (module, alias.name)
    return _BypassImports(receivers, calls)


def _call_target_name(node) -> tuple:
    """Return ``(dotted_target, receiver)`` for a call's callee."""
    if isinstance(node, ast.Name):
        return node.id, None
    if isinstance(node, ast.Attribute):
        parts: list[str] = [node.attr]
        cur = node.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        receiver = parts[-2] if len(parts) >= 2 else None
        return ".".join(parts), receiver
    return None, None


def _reaches_effects_handle(node, aliases=frozenset()) -> bool:
    """True when a callee's receiver chain goes through ``.effects``.

    ``aliases`` are local names bound to the handle (``e = ctx.effects``), which
    is an ordinary way to write a handler and must not read as a bypass.
    """
    cur = node
    while isinstance(cur, ast.Attribute):
        if cur.attr == "effects":
            return True
        cur = cur.value
    return isinstance(cur, ast.Name) and cur.id in aliases


def _bypass_effects_aliases(tree) -> frozenset:
    """Names bound to the effects handle anywhere in the module.

    ``e = ctx.effects`` then ``e.write(...)`` is the same call as
    ``ctx.effects.write(...)``; without this the lint would report the handle
    itself as a bypass.
    """
    names: set = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if node.value is None or not _reaches_effects_handle(node.value):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return frozenset(names)


def _function_opts_into_effects(fn) -> bool:
    """True when a function body reaches for an ``.effects`` handle at all.

    One of the two root conditions: a function that uses the effects handle must
    route ALL of its effects through it, or the preview it promises is a lie.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and node.attr == "effects":
            return True
    return False


# Decorator leaf names that register a command handler. `@app.command(...)` and
# `@group.command(...)` are the whole registration surface; `passthrough` is
# listed because a consumer may spell a passthrough wrapper the same way.
_BYPASS_HANDLER_DECORATORS = frozenset({"command", "passthrough"})


def _decorator_leaf(node) -> str | None:
    """The last dotted component of a decorator expression, call or not."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _bypass_handler_names(tree) -> set:
    """Function names passed as ``handler=`` anywhere in the module.

    The second way a handler is registered: `Passthrough(handler=_pt)`,
    `app.command(..., handler=deploy)`. Name-based, because that is all a
    single-module AST can honestly resolve.
    """
    names: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "handler" and isinstance(kw.value, ast.Name):
                names.add(kw.value.id)
    return names


def _is_registered_handler(fn, handler_names: set) -> bool:
    """True when this function is a registered command handler."""
    for dec in fn.decorator_list:
        if _decorator_leaf(dec) in _BYPASS_HANDLER_DECORATORS:
            return True
    return fn.name in handler_names


def _bypass_direct_call_names(fn) -> set:
    """Bare ``name(...)`` callees inside a function's subtree."""
    names: set = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _bypass_reachable_functions(tree) -> set:
    """The ids of every function REACHABLE FROM A REGISTERED COMMAND HANDLER.

    §11's scope is reachability, not "a function whose own body mentions
    ``.effects``" -- a handler that never touches the handle, and a bypass one
    helper-call away, are both trivial escapes from the narrower reading, and
    this lint is the sole stated mitigation for the accepted no-sandbox ceiling.

    Roots are registered handlers (a `.command` / `.passthrough` decorator, or a
    name passed as `handler=`) plus, as before, any function that reaches for
    `.effects` itself. From each root the closure follows DIRECT calls to
    MODULE-LEVEL functions, transitively, within this one module -- the most a
    single-file AST can resolve without a symbol table.
    """
    module_funcs: dict = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_funcs.setdefault(node.name, node)

    handler_names = _bypass_handler_names(tree)
    queue = [
        fn for fn in ast.walk(tree)
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (_is_registered_handler(fn, handler_names)
             or _function_opts_into_effects(fn))
    ]
    reachable: set = set()
    while queue:
        fn = queue.pop()
        if id(fn) in reachable:
            continue
        reachable.add(id(fn))
        for name in _bypass_direct_call_names(fn):
            target = module_funcs.get(name)
            if target is not None and id(target) not in reachable:
                queue.append(target)
    return reachable


def _bypass_resolve_call(leaf: str, receiver,
                         imports: _BypassImports) -> tuple:
    """The ``(leaf, receiver)`` a call really goes through, per its imports.

    A bare name imported from an effect module answers with that module and the
    member's REAL name (``from os import system as sh`` -> ``("system",
    "os")``), and an aliased module receiver answers with the module it denotes
    (``import os as o`` -> ``os``). Anything else is returned untouched, so an
    unresolvable receiver stays unresolvable rather than being guessed at.
    """
    if receiver is None:
        bound = imports.calls.get(leaf)
        if bound is None:
            return leaf, None
        module, member = bound
        return member, module
    return leaf, imports.receivers.get(receiver, receiver)


def _bypass_call_is_banned(node, target: str, receiver,
                           imports: _BypassImports = _BYPASS_NO_IMPORTS) -> bool:
    """True when one call is a direct effect the handle should have carried.

    Two leaves are deliberately narrower than the rest: builtin ``open`` is a
    finding only in a writing mode, and ``system`` only through ``os`` --
    ``platform.system()`` observes this process and starts nothing, and the
    effects handle has no method that could carry it.

    Builtin ``open`` is answered BEFORE import resolution, because it is the
    one leaf whose meaning comes from being unqualified. Everything after it is
    resolved through the module's imports (see :func:`_bypass_resolve_call`),
    so the lists below are written in terms of real module and member names.
    """
    leaf = target.rsplit(".", 1)[-1]
    if leaf == "open" and receiver is None:
        return _open_is_write_mode(node)
    leaf, receiver = _bypass_resolve_call(leaf, receiver, imports)
    if leaf in _BYPASS_PROCESS_OS_ONLY:
        return receiver in _BYPASS_OS_RECEIVERS
    return (
        (leaf in _BYPASS_PROCESS and receiver is not None)
        or leaf in _BYPASS_FILESYSTEM
        or (leaf in _BYPASS_NETWORK and receiver in _BYPASS_NETWORK_RECEIVERS)
    )


def _bypass_walk(node, stack: list, reachable: set, findings: list, rel: str,
                 aliases: frozenset, imports: _BypassImports) -> None:
    """Walk one subtree, carrying the enclosing-function stack.

    A banned call is reported once, at the INNERMOST enclosing function, when
    any enclosing function is reachable -- so a bypass inside a nested closure
    is one finding, not one per enclosing scope.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        stack = stack + [node]
    elif isinstance(node, ast.Call):
        if stack and any(id(fn) in reachable for fn in stack):
            if not _reaches_effects_handle(node.func, aliases):
                target, receiver = _call_target_name(node.func)
                if target is not None and _bypass_call_is_banned(
                        node, target, receiver, imports):
                    findings.append((rel, node.lineno, stack[-1].name, target))
    for child in ast.iter_child_nodes(node):
        _bypass_walk(child, stack, reachable, findings, rel, aliases, imports)


def _open_is_write_mode(node) -> bool:
    """True when a bare ``open(...)`` call requests a writing mode."""
    mode = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    if not isinstance(mode, str):
        return False
    return any(ch in mode for ch in ("w", "a", "x", "+"))


def _scan_effects_bypasses(root: Path) -> list[tuple]:
    """Find direct effect calls REACHABLE FROM a registered command handler.

    Returns ``(relative_path, lineno, function_name, target)`` tuples, in file
    then line order. See :func:`_bypass_reachable_functions` for the scope rule.
    """
    findings: list[tuple] = []
    if not root.is_dir():
        return findings
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _BYPASS_SKIP_DIRS and not d.startswith(".")
        )
        for fname in sorted(filenames):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(dirpath, fname)
            try:
                tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                # A file the analyser cannot read is not evidence of a bypass.
                continue
            rel = os.path.relpath(path, root)
            reachable = _bypass_reachable_functions(tree)
            if not reachable:
                continue
            _bypass_walk(tree, [], reachable, findings, rel,
                         _bypass_effects_aliases(tree),
                         _bypass_import_bindings(tree))
    return findings



# Module-private brand token: an Outcome can be constructed only through the
# ``outcome()`` factory (which holds this token). Direct construction raises,
# so a return value is an Outcome only when the framework minted it -- no
# structural shape detection.
_OUTCOME_TOKEN = object()


@dataclass(frozen=True)
class Outcome:
    """A structured result returned by a command handler.

    Built exclusively via the :func:`outcome` factory. Carries an exit code and
    nothing else: the bare-JSON-print data channel was deleted (contract
    §19.4) and machine payloads are supplied through ``ctx.payload``.
    """

    exit_code: int
    _token: object = None

    def __post_init__(self) -> None:
        if self._token is not _OUTCOME_TOKEN:
            raise TypeError(
                "Outcome cannot be constructed directly; "
                "build one with strictcli.outcome(...)"
            )


def outcome(exit_code: int = 0) -> Outcome:
    """Build an :class:`Outcome` for a command handler to return.

    Args:
        exit_code: process exit code (default 0).
    """
    return Outcome(exit_code=exit_code, _token=_OUTCOME_TOKEN)


def _interpret_handler_return(result: object) -> int:
    """Map a command handler's return value to an exit code.

    The only permitted returns are ``int`` (exit code), ``None`` (exit 0),
    or an :class:`Outcome` built via :func:`outcome`. Anything else is a
    hard error.
    """
    if result is None:
        return 0
    if isinstance(result, Outcome):
        return result.exit_code
    if isinstance(result, int):
        return result
    raise TypeError(
        "command handler must return int (exit code), None (exit 0), or "
        f"strictcli.outcome(...); got {type(result).__name__}"
    )


def _config_path(app_name: str, *, override: str | None = None, config_format: str = "json") -> str:
    """Compute the config file path for an app.

    If override is provided, expand ~ and return it directly.
    Otherwise compute from XDG_CONFIG_HOME + app_name.
    """
    if override is not None:
        return os.path.expanduser(override)
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    ext = "toml" if config_format == "toml" else "json"
    return os.path.join(config_home, app_name, f"config.{ext}")


import re as _re


# Regex to extract position from tomllib error messages:
# "... (at line X, column Y)" pattern (Python 3.11-3.13)
_TOML_POSITION_RE = _re.compile(r"\(at line (\d+), column (\d+)\)")


class _ConfigLoadResult:
    """Result of loading a config file."""
    __slots__ = ("data", "parse_err")

    def __init__(self, data: dict | None = None, parse_err: str | None = None):
        self.data = data if data is not None else {}
        self.parse_err = parse_err


def _compute_json_position(text: str, offset: int) -> tuple[int, int]:
    """Convert a byte offset to 1-based (line, column)."""
    line = 1
    col = 1
    for i in range(min(offset, len(text))):
        if text[i] == "\n":
            line += 1
            col = 1
        else:
            col += 1
    return line, col


def _load_config(
    app_name: str,
    *,
    config_path_override: str | None = None,
    config_format: str = "json",
    is_runtime_flag: bool = False,
) -> _ConfigLoadResult:
    """Load the config file for an app.

    Missing file with is_runtime_flag=True is a hard error (user explicitly
    passed --config). Missing file otherwise is soft (returns empty dict).
    Malformed file is always a hard error with position information.
    """
    path = _config_path(app_name, override=config_path_override, config_format=config_format)
    if not os.path.isfile(path):
        if is_runtime_flag:
            return _ConfigLoadResult(parse_err=f"config file not found: {path}")
        return _ConfigLoadResult()
    if config_format == "toml":
        try:
            with open(path, "rb") as f:
                return _ConfigLoadResult(data=tomllib.load(f))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            msg = str(e)
            m = _TOML_POSITION_RE.search(msg)
            if m:
                line, col = int(m.group(1)), int(m.group(2))
                return _ConfigLoadResult(
                    parse_err=f"config file {path}: {msg} (line {line}, column {col})",
                )
            return _ConfigLoadResult(parse_err=f"config file {path}: {msg}")
    try:
        with open(path) as f:
            text = f.read()
            return _ConfigLoadResult(data=json.loads(text))
    except json.JSONDecodeError as e:
        line, col = _compute_json_position(text, e.pos) if e.pos is not None else (0, 0)
        if line > 0:
            return _ConfigLoadResult(
                parse_err=f"config file {path}: {e.msg} (line {line}, column {col})",
            )
        return _ConfigLoadResult(parse_err=f"config file {path}: {e.msg}")
    except ValueError as e:
        return _ConfigLoadResult(parse_err=f"config file {path}: {e}")


def _toml_format_scalar(value: object) -> str:
    """Format a scalar value as a TOML literal."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, float):
        return _format_float_canonical(value)
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _load_toml_doc(path: str) -> "tomlkit.TOMLDocument":
    """Load a TOML file as a comment/order-preserving tomlkit document.

    Returns an empty document if the file does not exist yet.
    """
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return tomlkit.parse(fh.read())
    return tomlkit.document()


def _toml_value_item(value: object) -> object:
    """Build a tomlkit item for ``value`` using canonical scalar formatting.

    Scalars and lists are rendered through ``_toml_format_scalar`` (so floats
    keep their canonical spelling) and re-parsed into properly formatted
    tomlkit items. Dicts become section tables with keys sorted for
    deterministic output.
    """
    if isinstance(value, dict):
        tbl = tomlkit.table()
        for k in sorted(value):
            tbl[k] = _toml_value_item(value[k])
        return tbl
    if isinstance(value, list):
        rendered = "[" + ", ".join(_toml_format_scalar(e) for e in value) + "]"
        return tomlkit.parse(f"_ = {rendered}")["_"]
    rendered = _toml_format_scalar(value)
    return tomlkit.parse(f"_ = {rendered}")["_"]


def _toml_set_nested(doc: "tomlkit.TOMLDocument", dotted_key: str, value: object) -> None:
    """Set a dot-separated key on a tomlkit document, preserving comments/order.

    Only the target key is (re)written; intermediate tables are created as
    needed. Comments and ordering of all other keys are untouched.
    """
    parts = dotted_key.split(".")
    current: object = doc
    for part in parts[:-1]:
        nxt = current.get(part) if hasattr(current, "get") else None
        if not isinstance(nxt, (Table, InlineTable)):
            tbl = tomlkit.table()
            current[part] = tbl
            current = current[part]
        else:
            current = nxt
    current[parts[-1]] = _toml_value_item(value)


def _toml_del_nested(doc: "tomlkit.TOMLDocument", dotted_key: str) -> bool:
    """Delete a dot-separated key from a tomlkit document.

    Returns True if the key was found and removed. Prunes now-empty
    intermediate tables. Comments/order of untouched keys are preserved.
    """
    parts = dotted_key.split(".")
    parents: list[tuple[object, str]] = []
    current: object = doc
    for part in parts[:-1]:
        nxt = current.get(part) if hasattr(current, "get") else None
        if not isinstance(nxt, (Table, InlineTable)):
            return False
        parents.append((current, part))
        current = nxt
    if parts[-1] not in current:
        return False
    del current[parts[-1]]
    for parent, key in reversed(parents):
        if len(parent[key]) == 0:
            del parent[key]
    return True


def _coerce_config_scalar(value: object, flag_type: type) -> object:
    """Coerce a single JSON config value to the given type.

    Returns the coerced value, or raises ValueError if coercion fails.
    """
    if flag_type is bool:
        if isinstance(value, bool):
            return value
        raise ValueError(f"expected boolean, got {_config_typename(value)}")
    if flag_type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise ValueError(f"expected integer, got {_config_typename(value)}")
    if flag_type is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise ValueError(f"expected float, got {_config_typename(value)}")
    if flag_type is str:
        if isinstance(value, str):
            return value
        raise ValueError(f"expected string, got {_config_typename(value)}")
    raise ValueError(f"unsupported flag type {flag_type}")


def _coerce_config_value(value: object, flag: "Flag") -> object:
    """Coerce a JSON config value to the flag's type.

    Returns the coerced value, or raises ValueError if coercion fails.
    Handles scalar, array (repeatable), and object (dict) values.
    """
    # Dict flags expect a JSON object
    if flag.compound == "dict":
        if not isinstance(value, dict):
            raise ValueError(
                f"expected object for dict flag, got {_config_typename(value)}"
            )
        result = {}
        for k, v in value.items():
            try:
                result[k] = _coerce_config_scalar(v, flag.value_type)
            except ValueError:
                raise ValueError(
                    f"key '{k}': expected {flag.value_type.__name__}, "
                    f"got {_config_typename(v)}"
                )
        return result
    if isinstance(value, list):
        if not flag.repeatable:
            raise ValueError("expected scalar, got array")
        result_list = []
        for i, elem in enumerate(value):
            try:
                result_list.append(_coerce_config_scalar(elem, flag.type))
            except ValueError:
                raise ValueError(
                    f"element {i}: expected {flag.type.__name__}, "
                    f"got {_config_typename(elem)}"
                )
        return result_list
    if flag.repeatable:
        raise ValueError(
            f"expected array for repeatable flag, got {_config_typename(value)}"
        )
    return _coerce_config_scalar(value, flag.type)


def _resolve_flag_show_source(f: "Flag", config_data: dict) -> tuple[object, str]:
    """Resolve the effective value and source for a flag in config show context.

    Precedence: env > config > default.
    "cli" is structurally impossible in config show because the app's own
    flags were never passed on the command line.
    """
    # Check env first (highest precedence after CLI)
    if f.env is not None:
        env_val = os.environ.get(f.env)
        if env_val is not None:
            # Coerce the env value to the flag's type for display
            if f.type is bool:
                try:
                    return _strict_bool(env_val), "env"
                except ValueError:
                    return env_val, "env"
            elif f.type is int:
                try:
                    return _strict_int(env_val), "env"
                except ValueError:
                    return env_val, "env"
            elif f.type is float:
                try:
                    return _strict_float(env_val), "env"
                except ValueError:
                    return env_val, "env"
            else:
                return env_val, "env"
    # Check config
    param = _flag_param_name(f.name)
    if param in config_data:
        return config_data[param], "config"
    # Default
    if f.default is not None:
        return f.default, "default"
    return None, "default"


def _format_config_value(value: object) -> str:
    """Format a config value for display, matching Go's formatConfigValue."""
    if value is None:
        return "<nil>"
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _format_float_canonical(value)
    return str(value)


def _nested_get(data: dict, dotted_key: str) -> tuple[bool, object]:
    """Look up a dot-separated key in a nested dict.

    Returns (found, value). If any intermediate segment is missing or
    not a dict, returns (False, None).
    """
    parts = dotted_key.split(".")
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False, None
    return True, current[parts[-1]]


def _nested_set(data: dict, dotted_key: str, value: object) -> None:
    """Set a dot-separated key in a nested dict, creating intermediate dicts."""
    parts = dotted_key.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _nested_delete(data: dict, dotted_key: str) -> bool:
    """Delete a dot-separated key from a nested dict.

    Returns True if the key was found and deleted, False otherwise.
    Cleans up empty intermediate dicts.
    """
    parts = dotted_key.split(".")
    # Walk to the parent, tracking the path for cleanup
    parents: list[tuple[dict, str]] = []
    current = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        parents.append((current, part))
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    del current[parts[-1]]
    # Clean up empty intermediate dicts
    for parent, key in reversed(parents):
        if not parent[key]:
            del parent[key]
    return True


def _collect_nested_keys(data: dict, prefix: str = "") -> list[str]:
    """Collect all leaf keys from a nested dict as dot-separated paths.

    Non-dict values are leaves. Dict values are recursed into.
    """
    keys: list[str] = []
    for k, v in data.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_collect_nested_keys(v, full_key))
        else:
            keys.append(full_key)
    return keys


def _check_config_field_type(cf: "ConfigField", value: object) -> str | None:
    """Validate that a config file value matches the config field's declared type.

    Returns an error message, or None if the type matches.
    """
    type_name = cf.type.__name__
    if cf.type is bool:
        if not isinstance(value, bool):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    elif cf.type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    elif cf.type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    elif cf.type is str:
        if not isinstance(value, str):
            return (
                f'config field "{cf.name}": expected {type_name}, '
                f"got {_config_typename(value)}"
            )
    return None


def _config_set_field(
    effects: "_Effects",
    key: str,
    value: str | None,
    cf: "ConfigField",
    existing: dict,
    path: str,
    config_format: str,
    kw: dict,
) -> int:
    """Handle 'config set' for a config field (not a flag).

    Returns an exit code (0 = success, 1 = error).
    """
    use_clear = kw.get("clear", False)
    use_default = kw.get("default", False)
    has_value = value is not None

    if use_clear:
        print("config set: --clear is only for repeatable flags", file=sys.stderr)
        return 1
    if use_clear and use_default:
        print("config set: --clear and --default are mutually exclusive",
              file=sys.stderr)
        return 1
    if has_value and use_default:
        print("config set: cannot provide a value with --default", file=sys.stderr)
        return 1
    if not has_value and not use_default:
        print("config set: provide a value or --default", file=sys.stderr)
        return 1

    if use_default:
        if not _write_config_unset(effects, existing, path, config_format, key):
            print(f"config set: key '{key}' not in config", file=sys.stderr)
            return 1
        return 0

    # Coerce string value to the config field's type
    try:
        if cf.type is bool:
            typed_value = _strict_bool(value)
        elif cf.type is int:
            typed_value = _strict_int(value)
        elif cf.type is float:
            try:
                typed_value = _strict_float(value)
            except ValueError as fe:
                msg = str(fe)
                if msg in ("NaN is not allowed", "Inf is not allowed"):
                    raise
                raise ValueError(f"expected float, got '{value}'") from fe
        else:
            typed_value = value
    except ValueError as e:
        print(f"config set: key '{key}': {e}", file=sys.stderr)
        return 1

    _write_config_set(effects, existing, path, config_format, key, typed_value)
    return 0


def _write_config_set(effects: "_Effects", data: dict, path: str,
                      config_format: str, key: str, value: object) -> None:
    """Set ``key`` = ``value`` in config and persist THROUGH ``ctx.effects``.

    For TOML, edits are comment/order-preserving: the existing file is loaded
    into a tomlkit document, only the changed key is written, and the document
    is dumped back. JSON is serialized from the in-memory ``data`` dict.

    The write is a `FILE_WRITE` on the effects handle, not a bare ``open``:
    ``config set`` is classified `mutating`, so under ``--dry-run`` the write
    must be RECORDED, never performed. A framework command that printed
    "DRY RUN -- no changes were made." while rewriting the user's config file
    would be the loudest possible counterexample to its own regime.
    """
    _nested_set(data, key, value)
    if config_format == "toml":
        doc = _load_toml_doc(path)
        _toml_set_nested(doc, key, value)
        text = tomlkit.dumps(doc)
    else:
        text = json.dumps(data, indent=2) + "\n"
    effects.write(path, text)


def _write_config_unset(effects: "_Effects", data: dict, path: str,
                        config_format: str, key: str) -> bool:
    """Remove ``key`` from config and persist. Returns False if key was absent.

    For TOML, the removal is comment/order-preserving (only the target key is
    dropped). JSON is serialized from the in-memory ``data`` dict. The write
    goes through ``ctx.effects`` for the reason spelled out above.
    """
    if not _nested_delete(data, key):
        return False
    if config_format == "toml":
        doc = _load_toml_doc(path)
        _toml_del_nested(doc, key)
        text = tomlkit.dumps(doc)
    else:
        text = json.dumps(data, indent=2) + "\n"
    effects.write(path, text)
    return True


def _ensure_config_dir(effects: "_Effects", path: str) -> None:
    """Record/perform the config file's parent directory creation.

    The existence probe is an ordinary filesystem READ (never an effect), and
    branching on it is branching on a real value, so the preview walks straight
    through it in both modes -- the §5.2 idiom. Probing keeps the preview honest:
    a `mkdir` line appears only when a directory would really be created.
    """
    dir_path = os.path.dirname(path)
    if dir_path and not os.path.isdir(dir_path):
        effects.mkdir(dir_path)


def _generate_config_template_toml(
    flags: list["Flag"],
    config_fields: dict[str, "ConfigField"],
) -> str:
    """Generate a TOML config template with comments."""
    lines: list[str] = []

    # A config field whose name equals a flag's param name is validation-only:
    # it annotates the flag and the key is rendered once (on the flag).
    flag_params = {_flag_param_name(f.name) for f in flags}
    colliding = {n: cf for n, cf in config_fields.items() if n in flag_params}

    # Flag-backed keys (flat)
    for f in flags:
        param = _flag_param_name(f.name)
        comment = f"# {f.help}"
        cf_collide = colliding.get(param)
        if cf_collide is not None:
            comment += f" -- {cf_collide.help}"
        lines.append(comment)
        if f.default is not None:
            lines.append(f"{param} = {_toml_format_scalar(f.default)}")
        else:
            lines.append(f"# {param} =")
        lines.append("")

    # Config field keys (possibly nested via dot names). Skip colliding fields
    # (already rendered on the flag line above).
    # Group by first segment for TOML sections
    top_level: list[tuple[str, "ConfigField"]] = []
    sections: dict[str, list[tuple[str, "ConfigField"]]] = {}
    for name, cf in config_fields.items():
        if name in colliding:
            continue
        parts = name.split(".")
        if len(parts) == 1:
            top_level.append((name, cf))
        else:
            section = parts[0]
            if section not in sections:
                sections[section] = []
            sections[section].append((name, cf))

    for name, cf in top_level:
        req = " (required)" if cf.required else ""
        lines.append(f"# {cf.help}{req}")
        if not cf.required:
            lines.append(f"{name} = {_toml_format_scalar(cf.default)}")
        else:
            lines.append(f"# {name} =")
        lines.append("")

    for section, fields in sections.items():
        lines.append(f"[{section}]")
        for name, cf in fields:
            # The key within the section is everything after the first dot
            sub_parts = name.split(".", 1)
            sub_key = sub_parts[1] if len(sub_parts) > 1 else sub_parts[0]
            # Handle deeper nesting
            deeper_parts = sub_key.split(".")
            if len(deeper_parts) > 1:
                # Need a sub-section
                sub_section = f"{section}.{deeper_parts[0]}"
                leaf_key = ".".join(deeper_parts[1:])
                lines.append("")
                lines.append(f"[{sub_section}]")
                req = " (required)" if cf.required else ""
                lines.append(f"# {cf.help}{req}")
                if not cf.required:
                    lines.append(f"{leaf_key} = {_toml_format_scalar(cf.default)}")
                else:
                    lines.append(f"# {leaf_key} =")
            else:
                req = " (required)" if cf.required else ""
                lines.append(f"# {cf.help}{req}")
                if not cf.required:
                    lines.append(f"{sub_key} = {_toml_format_scalar(cf.default)}")
                else:
                    lines.append(f"# {sub_key} =")
        lines.append("")

    return "\n".join(lines) + "\n" if lines else ""


def _generate_config_template_json(
    flags: list["Flag"],
    config_fields: dict[str, "ConfigField"],
) -> str:
    """Generate a JSON config template."""
    data: dict = {}
    # A config field colliding with a flag's param name is validation-only; the
    # flag owns the rendered value, so the key appears once.
    flag_params = {_flag_param_name(f.name) for f in flags}
    # Flag-backed keys
    for f in flags:
        param = _flag_param_name(f.name)
        if f.default is not None:
            data[param] = f.default
        else:
            data[param] = None

    # Config field keys (nested via dot names). Skip colliding fields (rendered
    # once via the flag above).
    for name, cf in config_fields.items():
        if name in flag_params:
            continue
        if not cf.required:
            _nested_set(data, name, cf.default)
        else:
            _nested_set(data, name, None)

    return json.dumps(data, indent=2) + "\n"


def _split_escaped(value: str, sep: str) -> list[str]:
    """Split value on sep, treating backslash as escape character.

    Escaped sep becomes literal sep. Escaped backslash becomes literal backslash.
    Trailing backslash with nothing to escape becomes literal backslash.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\":
            if i + 1 < len(value):
                next_ch = value[i + 1]
                if next_ch == sep:
                    current.append(sep)
                    i += 2
                elif next_ch == "\\":
                    current.append("\\\\")
                    i += 2
                else:
                    current.append("\\")
                    current.append(next_ch)
                    i += 2
            else:
                # Trailing backslash
                current.append("\\\\")
                i += 1
        elif value[i] == sep:
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(value[i])
            i += 1
    parts.append("".join(current))
    return parts


def _values_equal_for_conflict(cli_val: object, config_val: object, flag: "Flag") -> bool:
    """Compare a CLI/env value and a config value for conflict-mode equality.

    Equality semantics (pinned):
    - scalars: exact equality.
    - plain repeatable lists: order-sensitive exact equality.
    - Unique flags: order-insensitive multiset equality.

    When the two values are equal, config+CLI/env co-presence is NOT a conflict
    (they agree), so error mode does not fire.
    """
    if flag.unique is True and isinstance(cli_val, list) and isinstance(config_val, list):
        # Order-insensitive multiset comparison.
        return sorted(cli_val, key=repr) == sorted(config_val, key=repr)
    return cli_val == config_val


def _check_flag_configfield_default(
    flag_name: str, flag_default: object, cf: "ConfigField"
) -> None:
    """Raise ValueError when a colliding flag and config field have conflicting
    explicit defaults.

    A ConfigField whose name equals a flag's param name is a validation-only
    declaration -- it annotates the flag. Their defaults must agree. The matrix:
    both absent OK; equal OK; both present unequal = error; one absent OK (the
    flag's default wins for rendering). A flag default of None means "no
    default" (absent); a ConfigField default of _MISSING means absent.
    """
    flag_has_default = flag_default is not None
    cf_has_default = not isinstance(cf.default, _MissingSentinel)
    if flag_has_default and cf_has_default and flag_default != cf.default:
        raise ValueError(
            f'config field "{cf.name}" collides with flag "{flag_name}" but their defaults disagree ({cf.default!r} vs {flag_default!r}); remove one default or make them equal'
        )


def _find_duplicate(values: list) -> object | None:
    """Return the first duplicate value in the list, or None if all unique."""
    seen: set = set()
    for v in values:
        if v in seen:
            return v
        seen.add(v)
    return None


def _format_float_canonical(value: float) -> str:
    """Format a float in strictcli canonical form (SCF).

    Rules (must match the Go implementation for cross-language parity):
    1. Shortest decimal string that round-trips to the identical IEEE-754 double
       (Python's ``repr`` already yields shortest round-trip digits).
    2. Integer-valued floats in fixed notation always carry a trailing ``.0``.
    3. ``-0.0`` is preserved as ``-0.0``.
    4. Fixed notation for ``|x|`` in ``[1e-6, 1e21)``; scientific outside. Zero
       (``0.0`` / ``-0.0``) is always rendered fixed.
    5. Scientific spelling: lowercase ``e``, explicit sign, no zero-padding on
       the exponent (e.g. ``1e+21``, ``1e-7``, ``1.5e+300``).
    6. The ``.0`` rule applies only in the fixed branch, never scientific.
    """
    # Zero carve-out (covers both 0.0 and -0.0).
    if value == 0.0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    absval = -value if value < 0 else value
    sign = "-" if value < 0 else ""
    if 1e-6 <= absval < 1e21:
        # Fixed notation, expanded from the shortest round-trip digits.
        s = format(decimal.Decimal(repr(absval)), "f")
        if "." not in s:
            s += ".0"
        return sign + s
    # Scientific notation: one digit before the point, shortest mantissa.
    r = repr(absval)
    if "e" in r or "E" in r:
        mant, exp_part = re.split("[eE]", r)
        exp = int(exp_part)
    else:
        mant, exp = r, 0
    if "." in mant:
        int_part, frac_part = mant.split(".")
    else:
        int_part, frac_part = mant, ""
    digits = (int_part + frac_part).lstrip("0")
    point_exp = exp - len(frac_part)
    stripped = digits.rstrip("0")
    if stripped == "":
        stripped = "0"
    point_exp += len(digits) - len(stripped)
    digits = stripped
    sci_exp = point_exp + len(digits) - 1
    mantissa = digits if len(digits) == 1 else digits[0] + "." + digits[1:]
    exp_sign = "+" if sci_exp >= 0 else "-"
    return f"{sign}{mantissa}e{exp_sign}{abs(sci_exp)}"


def _format_dict_for_display(value: dict) -> str:
    """Render a dict flag value as canonical ``key=value`` pairs.

    Keys are sorted for deterministic output, matching Go's
    ``formatDictForDisplay``. Values are rendered via ``_format_value_for_error``.
    """
    parts = [f"{k}={_format_value_for_error(value[k])}" for k in sorted(value)]
    return ", ".join(parts)


def _format_default_for_help(value: object) -> str:
    """Format a default value for help text.

    Floats use the canonical form (SCF); dict values render as sorted
    ``key=value`` pairs (matching Go). Every other type is rendered as ``str``.
    """
    if isinstance(value, float):
        return _format_float_canonical(value)
    if isinstance(value, dict):
        return _format_dict_for_display(value)
    return str(value)


def _format_value_for_error(value: object) -> str:
    """Format a value for inclusion in error messages (without quotes).

    Floats use the canonical form (SCF). Bools are lowercase.
    Dict values render as sorted ``key=value`` pairs (matching Go).
    Strings are returned as-is.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _format_float_canonical(value)
    if isinstance(value, dict):
        return _format_dict_for_display(value)
    return str(value)


def _config_typename(value: object) -> str:
    """Return a type name for config values, matching Go's typeName."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_CHECK_REQUIRED_FIELDS = {"tags", "severity", "fast", "pure", "needs_network", "depends_on"}
_CHECK_OPTIONAL_FIELDS = {"scope"}
_CHECK_VALID_SEVERITIES = {"error", "warn"}


def _parse_checks_toml(data: bytes) -> tuple[str, dict[str, _CheckDef]]:
    """Parse and validate checks TOML data, returning (app_name, check_defs).

    Raises ValueError on any schema violation or invalid TOML.
    """
    try:
        parsed = tomllib.loads(data.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"checks.toml: {exc}") from exc

    # Only "app" and [checks] are allowed at the top level
    for key in parsed:
        if key not in ("app", "checks"):
            raise ValueError(f'checks.toml: unknown top-level key "{key}"')

    # Validate required "app" field
    if "app" not in parsed:
        raise ValueError('checks.toml: missing required top-level key "app"')
    if not isinstance(parsed["app"], str) or not parsed["app"]:
        raise ValueError('checks.toml: "app" must be a non-empty string')
    app_name = parsed["app"]

    if "checks" not in parsed:
        return (app_name, {})

    checks_section = parsed["checks"]
    if not isinstance(checks_section, dict):
        raise ValueError("checks.toml: [checks] must be a table")

    result: dict[str, _CheckDef] = {}

    for name, fields in checks_section.items():
        # Validate check name
        if not _IDENTIFIER_RE.fullmatch(name):
            raise ValueError(
                f'checks.toml: invalid check name "{name}" '
                f"(must match [a-z][a-z0-9-]*)"
            )
        if not isinstance(fields, dict):
            raise ValueError(f'checks.toml: check "{name}" must be a table')

        # No unknown fields
        unknown = set(fields.keys()) - _CHECK_REQUIRED_FIELDS - _CHECK_OPTIONAL_FIELDS
        if unknown:
            raise ValueError(
                f'checks.toml: check "{name}": unknown field "{sorted(unknown)[0]}"'
            )

        # Required fields
        for req in sorted(_CHECK_REQUIRED_FIELDS):
            if req not in fields:
                raise ValueError(
                    f'checks.toml: check "{name}": missing required field "{req}"'
                )

        # Validate tags
        tags = fields["tags"]
        if not isinstance(tags, list):
            raise ValueError(
                f'checks.toml: check "{name}": "tags" must be a list of strings'
            )
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError(
                    f'checks.toml: check "{name}": "tags" entries must be non-empty strings'
                )

        # Validate severity
        severity = fields["severity"]
        if not isinstance(severity, str) or severity not in _CHECK_VALID_SEVERITIES:
            raise ValueError(
                f'checks.toml: check "{name}": "severity" must be "error" or "warn", '
                f"got {severity!r}"
            )

        # Validate booleans
        for bool_field in ("fast", "pure", "needs_network"):
            val = fields[bool_field]
            if not isinstance(val, bool):
                raise ValueError(
                    f'checks.toml: check "{name}": "{bool_field}" must be a boolean, '
                    f"got {type(val).__name__}"
                )

        # Validate depends_on
        depends_on = fields["depends_on"]
        if not isinstance(depends_on, list):
            raise ValueError(
                f'checks.toml: check "{name}": "depends_on" must be a list of strings'
            )
        for dep in depends_on:
            if not isinstance(dep, str):
                raise ValueError(
                    f'checks.toml: check "{name}": "depends_on" entries must be strings'
                )

        # Validate optional scope field
        scope = fields.get("scope", "")
        if not isinstance(scope, str):
            raise ValueError(
                f'checks.toml: check "{name}": "scope" must be a string, '
                f"got {type(scope).__name__}"
            )

        result[name] = _CheckDef(
            name=name,
            tags=tags,
            severity=severity,
            fast=fields["fast"],
            pure=fields["pure"],
            needs_network=fields["needs_network"],
            depends_on=depends_on,
            scope=scope,
        )

    # Cross-validate depends_on references
    for name, check_def in result.items():
        for dep in check_def.depends_on:
            if dep not in result:
                raise ValueError(
                    f'checks.toml: check "{name}": depends_on references '
                    f'unknown check "{dep}"'
                )

    return (app_name, result)


def _load_checks_toml(path: str | Path) -> tuple[str, dict[str, _CheckDef]]:
    """Read and parse a checks.toml file, returning (app_name, check_defs).

    Raises ValueError on any file error, schema violation, or invalid TOML.
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"checks.toml: {exc}") from exc
    return _parse_checks_toml(raw)


class _HelpRequested(Exception):
    """Raised when --help or -h is encountered."""

    def __init__(self, target: object) -> None:
        self.target = target
        super().__init__()


class _VersionRequested(Exception):
    """Raised when --version or -v is encountered."""


class _DumpSchemaRequested(Exception):
    """Raised when --dump-schema is encountered."""


class _McpRequested(Exception):
    """Raised when --mcp is encountered."""


class _ParseError(Exception):
    """Raised for user-facing parse errors."""

    def __init__(self, message: str, command_prefix: str | None = None):
        super().__init__(message)
        self.command_prefix = command_prefix


class InvokeError(Exception):
    """Raised by app.call() for invocation errors (unknown command, missing flags, etc.)."""


def _strict_bool(s: str) -> bool:
    """Parse a boolean string strictly.

    Accepts: 1, true, yes (case-insensitive) -> True
    Accepts: 0, false, no (case-insensitive) -> False
    Everything else raises ValueError.
    """
    lower = s.lower()
    if lower in ("1", "true", "yes"):
        return True
    if lower in ("0", "false", "no"):
        return False
    raise ValueError(f"expected boolean, got '{s}'")


def _strict_int(s: str) -> int:
    """Parse an integer string strictly -- no leading/trailing whitespace allowed.

    Python's int() silently strips whitespace; Go's strconv.Atoi does not.
    This matches Go's stricter behavior. Additionally, the result is
    range-checked to fit in a signed 64-bit integer, matching Go's int/int64.

    All errors raise ValueError with the same message format as Go's
    parseIntStrict: "expected integer, got '<value>'".
    """
    if s != s.strip():
        raise ValueError(f"expected integer, got '{s}'")
    # Python's int() accepts PEP 515 underscore digit separators ('1_000');
    # Go's strconv and the TypeScript parser reject them. Reject to match canon.
    if "_" in s:
        raise ValueError(f"expected integer, got '{s}'")
    try:
        n = int(s)
    except ValueError:
        raise ValueError(f"expected integer, got '{s}'") from None
    if n < -(2**63) or n > 2**63 - 1:
        raise ValueError(f"expected integer, got '{s}'")
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
    result = float(s)
    # A finite literal that overflows to +/-inf ('1e999') is a parse failure,
    # not an Inf literal. Go and TypeScript reject it as an invalid float; use
    # the generic "expected float" path (not "Inf is not allowed") to match.
    if math.isinf(result):
        raise ValueError(f"invalid literal for float(): {s!r}")
    return result


def _float_parse_error(
    flag_name: str, raw: str, exc: ValueError, *, env: str | None = None,
) -> "_ParseError":
    """Build a _ParseError for a failed float parse.

    If the ValueError is a NaN/Inf rejection, use its message directly.
    Otherwise, produce the generic "expected float, got ..." message.
    """
    msg = str(exc)
    suffix = f" (from env var '{env}')" if env else ""
    if msg in ("NaN is not allowed", "Inf is not allowed"):
        return _ParseError(f"--{flag_name}: {msg}{suffix}")
    return _ParseError(f"--{flag_name}: expected float, got {raw!r}{suffix}")


def _coerce_arg_value(a: "Arg", raw: str) -> object:
    """Coerce a raw positional arg string to the declared type.

    Uses the same strict parsing functions as flags: _strict_int, _strict_float,
    _strict_bool. Error messages follow the same pattern as flag type errors,
    with "argument '<name>'" instead of "--<name>".
    """
    if a.type is str:
        return raw
    if a.type is int:
        try:
            return _strict_int(raw)
        except ValueError as e:
            raise _ParseError(f"argument '{a.name}': {e}")
    if a.type is float:
        try:
            return _strict_float(raw)
        except ValueError as e:
            msg = str(e)
            if msg in ("NaN is not allowed", "Inf is not allowed"):
                raise _ParseError(f"argument '{a.name}': {msg}")
            raise _ParseError(f"argument '{a.name}': expected float, got {raw!r}")
    if a.type is bool:
        try:
            return _strict_bool(raw)
        except ValueError as e:
            raise _ParseError(f"argument '{a.name}': {e}")
    # Unreachable (validated at registration), but defensive
    return raw  # pragma: no cover


_AT_PREFIX_MAX_SIZE = 1024 * 1024  # 1 MB


def _resolve_at_prefix(
    flag_name: str, raw: str, stdin_consumed_by: str | None,
) -> tuple[str, str | None]:
    """Resolve @-prefix for string flag values.

    Returns (resolved_value, updated_stdin_consumed_by).
    """
    if not raw.startswith("@"):
        return raw, stdin_consumed_by
    if raw.startswith("@@"):
        return raw[1:], stdin_consumed_by
    if raw == "@-":
        if stdin_consumed_by is not None:
            raise _ParseError(
                f"--{flag_name}: stdin (@-) can only be used once per invocation"
            )
        try:
            data = sys.stdin.read(_AT_PREFIX_MAX_SIZE + 1)
            if len(data) > _AT_PREFIX_MAX_SIZE:
                raise _ParseError(f"--{flag_name}: file exceeds 1 MB limit")
            return data.rstrip(" \t\n\r"), flag_name
        except _ParseError:
            raise
        except Exception:
            raise _ParseError(f"--{flag_name}: cannot read stdin")
    # @path -- read file
    path = raw[1:]
    if not os.path.exists(path):
        raise _ParseError(f"--{flag_name}: file not found: {path}")
    try:
        with open(path, "r") as f:
            data = f.read(_AT_PREFIX_MAX_SIZE + 1)
        if len(data) > _AT_PREFIX_MAX_SIZE:
            raise _ParseError(f"--{flag_name}: file exceeds 1 MB limit")
        return data.rstrip(" \t\n\r"), stdin_consumed_by
    except _ParseError:
        raise
    except Exception:
        raise _ParseError(f"--{flag_name}: cannot read file: {path}")


def _require_non_empty_str(value: str, field_name: str, class_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{class_name}.{field_name} must be a non-empty string")


def _parse_dict_value(
    flag_name: str, raw: str, value_type: type,
) -> tuple[str, object] | dict[str, object]:
    """Parse a dict flag value from CLI.

    Two formats:
    - key=value: splits on first '=', coerces value to value_type
    - JSON string starting with '{': parsed as JSON dict

    For key=value format, returns a (key, coerced_value) tuple.
    For JSON format, returns a dict of {key: coerced_value}.
    """
    # JSON format: detected by leading '{'
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise _ParseError(f"--{flag_name}: invalid JSON: {e}")
        if not isinstance(parsed, dict):
            raise _ParseError(
                f"--{flag_name}: JSON value must be an object, "
                f"got {type(parsed).__name__}"
            )
        result = {}
        for k, v in parsed.items():
            if not isinstance(k, str):
                raise _ParseError(
                    f"--{flag_name}: JSON key must be a string, got {k!r}"
                )
            result[k] = _coerce_dict_json_value(flag_name, k, v, value_type)
        return result

    # key=value format: split on first '='
    if "=" not in raw:
        raise _ParseError(
            f"--{flag_name}: expected key=value or JSON, got '{raw}'"
        )
    eq_pos = raw.index("=")
    key = raw[:eq_pos]
    val_str = raw[eq_pos + 1:]

    if not key:
        raise _ParseError(f"--{flag_name}: empty key in '{raw}'")

    if value_type is int:
        try:
            return (key, _strict_int(val_str))
        except ValueError as e:
            raise _ParseError(f"--{flag_name}: value for key '{key}': {e}")
    elif value_type is float:
        try:
            return (key, _strict_float(val_str))
        except ValueError as e:
            raise _float_parse_error(flag_name, val_str, e)
    else:  # str
        return (key, val_str)


def _coerce_dict_json_value(
    flag_name: str, key: str, value: object, value_type: type,
) -> object:
    """Coerce a JSON-parsed value to the dict's value type."""
    if value_type is str:
        if not isinstance(value, str):
            raise _ParseError(
                f"--{flag_name}: JSON value for key '{key}' must be a string, "
                f"got {_config_typename(value)}"
            )
        return value
    if value_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise _ParseError(
                f"--{flag_name}: JSON value for key '{key}' must be an integer, "
                f"got {_config_typename(value)}"
            )
        return value
    if value_type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise _ParseError(
                f"--{flag_name}: JSON value for key '{key}' must be a number, "
                f"got {_config_typename(value)}"
            )
        return float(value)
    raise _ParseError(f"--{flag_name}: unsupported value type {value_type}")


def _store_dict_flag(f: "Flag", raw: str, cli_set: dict) -> None:
    """Parse and store a dict flag value from a raw CLI string.

    Handles both key=value and JSON formats. For JSON, may add multiple
    entries at once. For key=value, adds one entry.
    """
    parsed = _parse_dict_value(f.name, raw, f.value_type)
    if isinstance(parsed, dict):
        # JSON format returned a full dict
        if f.name not in cli_set:
            cli_set[f.name] = {}
        for k, v in parsed.items():
            if k in cli_set[f.name]:
                raise _ParseError(f"--{f.name}: duplicate key '{k}'")
            cli_set[f.name][k] = v
    else:
        # key=value format returned a tuple
        k, v = parsed
        if f.name not in cli_set:
            cli_set[f.name] = {}
        if k in cli_set[f.name]:
            raise _ParseError(f"--{f.name}: duplicate key '{k}'")
        cli_set[f.name][k] = v


_SCALAR_TYPES = (str, bool, int, float)
_NON_BOOL_SCALAR_TYPES = (str, int, float)

# The reserved flag quartet owned by the effects regime. Banned unconditionally
# at EVERY level (app global flags, command flags, flag-set flags, mutex-group
# flags) -- not just at the global level. Short-flag names and positional arg
# names are unaffected by this ban, and the four flags themselves have no short
# forms.
_RESERVED_FRAMEWORK_FLAG_NAMES = frozenset({
    "dry-run", "approve-consequential", "quiet", "verbose",
})

# The machine-mode flag name, reserved on the SAME unconditional every-level
# tier as the quartet (contract §7.1's 2026-08-13 amendment). It is NOT a
# fifth member of the quartet -- the four are the effects regime's own flags
# and are named as a set throughout the contract -- so it carries its own
# reserved-name message and its own token entry.
_RESERVED_MACHINE_FLAG_NAME = "json"

# `yes` is NOT a framework flag any more -- it was replaced by
# --approve-consequential (contract §7.1) -- but it stays banned so nobody
# reintroduces a private --yes meaning the same thing. Its ban message points
# at the replacement.
_BANNED_FLAG_NAMES = frozenset({"yes"})

# The programmatic consent PARAMETER name, reserved on both the flag surface
# and the arg surface at every level. `call(..., approve_consequential=...)`
# is keyword-only and framework-owned, so a command declaring a parameter of
# this name would be unreachable over that channel while staying reachable
# over MCP -- two channels disagreeing about the same command. The quartet ban
# above covers the FLAG spelling `approve-consequential`; this covers the
# underscore spelling the parameter surface actually uses, and it is the one
# reserved name that reaches positional args too.
_RESERVED_CONSENT_PARAM_NAME = "approve_consequential"

# Names reserved by the framework for global flags. The pre-existing set is
# also what a SHORT flag name is checked against (the framework quartet bans
# long names only).
_RESERVED_GLOBAL_SHORT_NAMES = frozenset({
    "help", "h", "version", "v", "dump-schema", "mcp", "config", "hermetic",
})
_RESERVED_GLOBAL_FLAG_NAMES = (
    _RESERVED_GLOBAL_SHORT_NAMES
    | _RESERVED_FRAMEWORK_FLAG_NAMES
    | frozenset({_RESERVED_MACHINE_FLAG_NAME})
)


# argv token -> pre-scan result key for the reserved quartet.
_RESERVED_QUARTET_TOKENS = {
    "--dry-run": "dry_run",
    "--approve-consequential": "approve_consequential",
    "--quiet": "quiet",
    "--verbose": "verbose",
}

# What the pre-scan actually recognizes: the quartet plus --json, which reads
# exactly as the quartet does in BOTH argv regions (contract §7.1's amendment,
# §7.2). The quartet stays a quartet; the machine flag rides the same delivery
# rules without joining the set.
_RESERVED_PRESCAN_TOKENS = {
    **_RESERVED_QUARTET_TOKENS,
    "--json": "json",
}


def _raise_flag_name_reserved_by_framework(name: str):
    """Message template: a flag name collides with the reserved quartet."""
    raise ValueError(
        f"flag name '{name}' is reserved by the framework "
        f"(dry-run, approve-consequential, quiet, verbose)"
    )


def _raise_flag_name_json_reserved():
    """Message template: a flag name collides with the machine-mode flag.

    `--json` is framework-owned (contract §19.1): it selects machine mode and
    is delivered on the Context, never as a handler kwarg. The ban is the
    unconditional every-level one, exactly as the quartet's is.
    """
    raise ValueError(
        "flag name 'json' is reserved by the framework: "
        "--json selects machine mode"
    )


def _raise_flag_name_yes_banned():
    """Message template: a flag named `yes` is banned outright.

    `yes` owns no framework flag any more, but a private --yes would restate
    --approve-consequential in a spelling that IS muscle memory -- which is
    exactly what the rename removed.
    """
    raise ValueError(
        "flag name 'yes' is banned by the framework: "
        "the confirmation skip is --approve-consequential"
    )


def _raise_flag_name_consent_reserved():
    """Message template: a flag name collides with the consent parameter."""
    raise ValueError(
        "flag name 'approve_consequential' is reserved by the framework: "
        "it names the programmatic consent parameter"
    )


def _raise_arg_name_consent_reserved():
    """Message template: an arg name collides with the consent parameter."""
    raise ValueError(
        "arg name 'approve_consequential' is reserved by the framework: "
        "it names the programmatic consent parameter"
    )


def _parse_compound_type(
    raw_type: type, context: str,
) -> tuple[str, type | None, type | None]:
    """Parse a type annotation into (kind, item_type, value_type).

    Returns:
        ("scalar", None, None) for str/bool/int/float
        ("list", item_type, None) for list[T]
        ("dict", None, value_type) for dict[str, T]

    Raises ValueError for invalid compound types.
    """
    # Plain scalar types
    if raw_type in _SCALAR_TYPES:
        return ("scalar", None, None)

    # Bare list/dict without type args
    if raw_type is list:
        raise ValueError(
            f'{context}: list type requires an item type '
            f'(e.g., list[int]), got bare list'
        )
    if raw_type is dict:
        raise ValueError(
            f'{context}: dict type requires type arguments '
            f'(e.g., dict[str, int]), got bare dict'
        )

    origin = get_origin(raw_type)

    # list[T]
    if origin is list:
        args = get_args(raw_type)
        if not args:
            raise ValueError(
                f'{context}: list type requires an item type '
                f'(e.g., list[int]), got bare list'
            )
        if len(args) != 1:
            raise ValueError(
                f'{context}: list type takes exactly one type argument, '
                f'got {len(args)}'
            )
        item_type = args[0]
        if item_type not in _NON_BOOL_SCALAR_TYPES:
            raise ValueError(
                f'{context}: list item type must be str, int, or float, '
                f'got {item_type!r}'
            )
        return ("list", item_type, None)

    # dict[str, T]
    if origin is dict:
        args = get_args(raw_type)
        if not args:
            raise ValueError(
                f'{context}: dict type requires type arguments '
                f'(e.g., dict[str, int]), got bare dict'
            )
        if len(args) != 2:
            raise ValueError(
                f'{context}: dict type takes exactly two type arguments, '
                f'got {len(args)}'
            )
        key_type, val_type = args
        if key_type is not str:
            raise ValueError(
                f'{context}: dict key type must be str, got {key_type!r}'
            )
        if val_type not in _NON_BOOL_SCALAR_TYPES:
            raise ValueError(
                f'{context}: dict value type must be str, int, or float, '
                f'got {val_type!r}'
            )
        return ("dict", None, val_type)

    raise ValueError(
        f'{context}: type must be str, bool, int, float, '
        f'list[T], or dict[str, T], got {raw_type!r}'
    )


def _validate_element_type(
    flag_name: str, expected_type: type, value: object, context: str,
) -> None:
    """Validate that a value matches the expected scalar type."""
    if expected_type is str:
        if not isinstance(value, str):
            raise ValueError(
                f'Flag "{flag_name}": {context} is not of type str'
            )
    elif expected_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(
                f'Flag "{flag_name}": {context} is not of type int'
            )
    elif expected_type is float:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f'Flag "{flag_name}": {context} is not of type float'
            )


@dataclass
class Flag:
    """Represents a --flag declaration."""

    name: str
    type: type
    help: str
    short: str | None = None
    default: object = None
    env: str | None = None
    env_separator: str | None = None
    prefixed: bool = True
    negatable: bool = True
    choices: list | None = None
    validate: Callable | None = None
    repeatable: bool = False
    unique: object = _MISSING
    # Connection-URL binding. connection_url marks this flag as a connection-URL
    # (URL-class) flag; connection_env names the app-level connection env
    # (declared via App(connection_env=...)) it binds to. A URL-class flag MUST
    # bind to a declared connection env (enforced at registration). The binding
    # is hermetic-suppressed, lazily read, no default; the CLI token wins over
    # the env (source "cli" vs "env").
    connection_url: bool = False
    connection_env: str | None = None
    # Per-flag config conflict mode. _MISSING means "inherit the app default".
    # When set explicitly, must be "cli-wins" or "error". Applies to flags only:
    # standalone ConfigFields have no CLI/env conflict surface, and a
    # flag-colliding ConfigField inherits the flag's handling.
    conflict_mode: object = _MISSING
    # Compound type fields (set by __post_init__, not by caller)
    compound: str = "scalar"  # "scalar", "list", or "dict"
    item_type: type | None = None  # for list[T]: the T
    value_type: type | None = None  # for dict[str, T]: the T

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Flag")
        if self.name == "force":
            raise ValueError(
                "flag 'force' is a reserved name; use a qualified name "
                "like 'force-overwrite' or 'force-delete'"
            )
        if self.name in _RESERVED_FRAMEWORK_FLAG_NAMES:
            _raise_flag_name_reserved_by_framework(self.name)
        if self.name == _RESERVED_MACHINE_FLAG_NAME:
            _raise_flag_name_json_reserved()
        if self.name == _RESERVED_CONSENT_PARAM_NAME:
            _raise_flag_name_consent_reserved()
        if self.name in _BANNED_FLAG_NAMES:
            _raise_flag_name_yes_banned()
        if self.name.startswith("no-"):
            raise ValueError(
                f"flag '{self.name}': names starting with 'no-' are "
                f"reserved for the negation system; use a positive "
                f"name instead"
            )

        # Parse compound types (list[T], dict[str, T])
        kind, item_t, val_t = _parse_compound_type(
            self.type, f'Flag "{self.name}"',
        )
        self.compound = kind
        self.item_type = item_t
        self.value_type = val_t

        if kind == "list":
            # list[T] normalizes to: type=item_type, repeatable=True
            self.type = self.item_type
            if not self.repeatable:
                self.repeatable = True
            # unique defaults to False for list types if not specified
            if isinstance(self.unique, _MissingSentinel):
                self.unique = False
        elif kind == "dict":
            # dict[str, T] normalizes to: type stays as the original
            # dict[str, T] annotation. The value_type tracks the T.
            # Dict flags are implicitly repeatable (each --flag key=val
            # adds to the dict), but don't use the list-based repeatable
            # machinery. We store self.type as the value_type for coercion
            # dispatch, but keep compound="dict" to distinguish behavior.
            self.type = self.value_type
            # Dict flags cannot be combined with repeatable=True by the user
            if self.repeatable:
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot be combined '
                    f'with repeatable=True'
                )
            # Dict flags cannot have unique
            if not isinstance(self.unique, _MissingSentinel):
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot be combined with unique'
                )
            self.unique = False
            # Dict flags cannot have choices
            if self.choices is not None:
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot be combined with choices'
                )

        # Validate scalar type
        if kind == "scalar" and self.type not in (str, bool, int, float):
            raise ValueError(
                f"Flag.type must be str, bool, int, float, "
                f"list[T], or dict[str, T], got {self.type!r}"
            )
        # Validate repeatable
        if self.repeatable and self.type is bool:
            raise ValueError(f'Flag "{self.name}": repeatable is incompatible with type=bool')
        # Validate unique
        if self.compound != "dict":
            if self.repeatable and isinstance(self.unique, _MissingSentinel):
                raise ValueError(
                    f'Flag "{self.name}": repeatable requires explicit unique '
                    f"(unique=True or unique=False)"
                )
            if not isinstance(self.unique, _MissingSentinel) and self.unique is not True and self.unique is not False:
                raise ValueError(f'Flag "{self.name}": unique must be True or False')
            if (self.unique is True or self.unique is False) and not self.repeatable:
                raise ValueError(f'Flag "{self.name}": unique requires repeatable=True')
            if isinstance(self.unique, _MissingSentinel) and not self.repeatable:
                self.unique = False
        # Validate conflict_mode (per-flag override of the app config conflict mode)
        if not isinstance(self.conflict_mode, _MissingSentinel):
            if self.conflict_mode not in ("cli-wins", "error"):
                raise ValueError(
                    f'Flag "{self.name}": conflict_mode must be "cli-wins" or '
                    f'"error", got {self.conflict_mode!r}'
                )
        # Validate env_separator
        if self.compound == "dict":
            # Dict flags use JSON for env vars, not env_separator
            if self.env_separator is not None:
                raise ValueError(
                    f'Flag "{self.name}": dict type cannot use env_separator '
                    f'(env vars are parsed as JSON)'
                )
        else:
            if self.env_separator is not None and not self.repeatable:
                raise ValueError(f'Flag "{self.name}": env_separator requires repeatable=True')
            if self.env_separator is not None and self.env is None:
                raise ValueError(f'Flag "{self.name}": env_separator requires env')
            if self.repeatable and self.env is not None and self.env_separator is None:
                raise ValueError(
                    f'Flag "{self.name}": repeatable flag with env requires env_separator'
                )
        if self.env_separator is not None and len(self.env_separator) != 1:
            raise ValueError(f'Flag "{self.name}": env_separator must be a single character')
        if self.env_separator == "\\":
            raise ValueError(f'Flag "{self.name}": env_separator cannot be a backslash')
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
        # Validate defaults for dict flags
        if self.compound == "dict":
            if not isinstance(self.default, _MissingSentinel):
                if self.default is not None:
                    if not isinstance(self.default, dict):
                        raise ValueError(
                            f'Flag "{self.name}": dict flag default must be a dict'
                        )
                    if len(self.default) == 0:
                        raise ValueError(
                            f'Flag "{self.name}": explicit empty default is '
                            f'redundant for dict flags, omit the default'
                        )
                    for k, v in self.default.items():
                        if not isinstance(k, str):
                            raise ValueError(
                                f'Flag "{self.name}": dict default key {k!r} '
                                f'must be a string'
                            )
                        _validate_element_type(
                            self.name, self.type, v,
                            f"dict default value for key {k!r}",
                        )
        # Validate repeatable flag defaults
        elif self.repeatable and not isinstance(self.default, _MissingSentinel):
            if self.default is not None:
                if not isinstance(self.default, list):
                    raise ValueError(
                        f'Flag "{self.name}": repeatable flag default must be a list'
                    )
                if len(self.default) == 0:
                    raise ValueError(
                        f'Flag "{self.name}": explicit empty default is redundant '
                        f"for repeatable flags, omit the default"
                    )
                # Validate element types
                type_name = {str: "str", int: "int", float: "float"}[self.type]
                for i, elem in enumerate(self.default):
                    if self.type is str:
                        if not isinstance(elem, str):
                            raise ValueError(
                                f'Flag "{self.name}": default element {i} is not of type {type_name}'
                            )
                    elif self.type is int:
                        if not isinstance(elem, int) or isinstance(elem, bool):
                            raise ValueError(
                                f'Flag "{self.name}": default element {i} is not of type {type_name}'
                            )
                    elif self.type is float:
                        if not isinstance(elem, (int, float)) or isinstance(elem, bool):
                            raise ValueError(
                                f'Flag "{self.name}": default element {i} is not of type {type_name}'
                            )
                        if isinstance(elem, int):
                            self.default[i] = float(elem)
        # Validate default type for int flags
        if self.type is int and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if not self.repeatable and self.compound != "dict" and not isinstance(self.default, int):
                raise ValueError(
                    f'Flag "{self.name}": type=int requires an int default, '
                    f"got {type(self.default).__name__!r}"
                )
        # Validate default type for float flags
        if self.type is float and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if not self.repeatable and self.compound != "dict" and not isinstance(self.default, (int, float)):
                raise ValueError(
                    f'Flag "{self.name}": type=float requires a float default, '
                    f"got {type(self.default).__name__!r}"
                )
        # Resolve _MISSING sentinels based on type
        if isinstance(self.default, _MissingSentinel) or (
            self.default is None and (
                self.compound == "dict" or self.repeatable
            )
        ):
            if self.compound == "dict":
                self.default = {}
            elif self.repeatable:
                self.default = []
            else:
                # No default means required (no default) — same for all types
                # including bool
                self.default = None
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
    type: type = str
    choices: list | None = None
    # Compound type fields (set by __post_init__, not by caller)
    compound: str = "scalar"
    item_type: type | None = None

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Arg")
        if self.name == _RESERVED_CONSENT_PARAM_NAME:
            _raise_arg_name_consent_reserved()
        if self.required and not isinstance(self.default, _MissingSentinel):
            raise ValueError("required arg cannot have a default")

        # Parse compound types for args (only list[T] is supported)
        origin = get_origin(self.type)
        if origin is list:
            args = get_args(self.type)
            if not args:
                raise ValueError(
                    f'Arg "{self.name}": list type requires an item type '
                    f'(e.g., list[int]), got bare list'
                )
            if len(args) != 1:
                raise ValueError(
                    f'Arg "{self.name}": list type takes exactly one type '
                    f'argument, got {len(args)}'
                )
            item_t = args[0]
            if item_t not in _NON_BOOL_SCALAR_TYPES:
                raise ValueError(
                    f'Arg "{self.name}": list item type must be str, int, '
                    f'or float, got {item_t!r}'
                )
            if not self.variadic:
                raise ValueError(
                    f'Arg "{self.name}": list type on args requires '
                    f'variadic=True'
                )
            self.compound = "list"
            self.item_type = item_t
            self.type = item_t
        elif origin is dict:
            raise ValueError(
                f'Arg "{self.name}": dict type is not supported on args'
            )
        # Validate type
        elif self.type not in (str, bool, int, float):
            raise ValueError(
                f"Arg.type must be str, bool, int, or float, got {self.type!r}"
            )
        # Validate choices
        if self.choices is not None:
            if self.type is bool:
                raise ValueError(
                    f'Arg "{self.name}": choices is incompatible with type=bool'
                )
            if not isinstance(self.choices, list) or len(self.choices) == 0:
                raise ValueError(
                    f'Arg "{self.name}": choices must be a non-empty list'
                )
            for c in self.choices:
                if not isinstance(c, self.type):
                    raise ValueError(
                        f'Arg "{self.name}": choice {c!r} is not of type '
                        f"{self.type.__name__}"
                    )
        # Validate default type matches declared type
        if not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if self.compound == "list":
                # self.type was normalized to the item type above; the
                # default itself must be a list of that item type.
                if not isinstance(self.default, list):
                    raise ValueError(
                        f'Arg "{self.name}": list arg default must be a list'
                    )
                if len(self.default) == 0:
                    raise ValueError(
                        f'Arg "{self.name}": explicit empty default is '
                        f"redundant for list args, omit the default"
                    )
                type_name = {str: "str", int: "int", float: "float"}[self.type]
                for i, elem in enumerate(self.default):
                    if self.type is str:
                        valid = isinstance(elem, str)
                    elif self.type is int:
                        valid = isinstance(elem, int) and not isinstance(elem, bool)
                    else:  # float
                        valid = (
                            isinstance(elem, (int, float))
                            and not isinstance(elem, bool)
                        )
                        if valid and isinstance(elem, int):
                            # Auto-coerce int to float, mirroring list flag defaults
                            self.default[i] = float(elem)
                    if not valid:
                        raise ValueError(
                            f'Arg "{self.name}": default element {i} '
                            f"is not of type {type_name}"
                        )
            elif self.type is int:
                if not isinstance(self.default, int) or isinstance(self.default, bool):
                    raise ValueError(
                        f'Arg "{self.name}": type=int requires an int default, '
                        f"got {type(self.default).__name__!r}"
                    )
            elif self.type is float:
                if not isinstance(self.default, (int, float)) or isinstance(self.default, bool):
                    raise ValueError(
                        f'Arg "{self.name}": type=float requires a float default, '
                        f"got {type(self.default).__name__!r}"
                    )
            elif self.type is bool:
                if not isinstance(self.default, bool):
                    raise ValueError(
                        f'Arg "{self.name}": type=bool requires a bool default, '
                        f"got {type(self.default).__name__!r}"
                    )
            elif self.type is str:
                if not isinstance(self.default, str):
                    raise ValueError(
                        f'Arg "{self.name}": type=str requires a str default, '
                        f"got {type(self.default).__name__!r}"
                    )
        # Validate default is in choices
        if self.choices is not None and not isinstance(self.default, _MissingSentinel) and self.default is not None:
            if self.default not in self.choices:
                raise ValueError(
                    f'Arg "{self.name}": default {self.default!r} is not in choices '
                    f"{self.choices!r}"
                )


@dataclass
class FlagSet:
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

    handler: Callable  # func(ctx: Context, name: str, args: list[str], globals: dict) -> int | None | Outcome


@dataclass
class Forwarding:
    """Declares that a handler deliberately accepts and forwards ``**kwargs``.

    Guard v2 refuses a var-keyword handler unless the command declares
    forwarding. The ``reason`` is mandatory, non-empty, and emitted in the
    schema so a consumer's audit gate can review every forwarding site.
    """

    reason: str


# The one reason string strictcli's own auto-registered commands use. Their
# handlers must absorb the app's app-defined global flag values, which a
# framework-authored handler cannot name.
_FRAMEWORK_INTERNAL_FORWARDING_REASON = (
    "framework-internal: absorbs app-defined global flag values"
)

# Payload schemas for strictcli's own auto-registered commands (contract
# §19.5). Inline literals, byte-identical across the three implementations.
# The check command's payload is an array in both of its machine shapes -- the
# listing (--list) and the run results.
_CHECK_PAYLOAD_SCHEMA = {"type": "array", "items": {"type": "object"}}
# config show's payload is one object keyed by flag/config-field name, plus the
# "__infrastructure__" entry; the keys are dynamic, so the declaration names
# the container only.
_CONFIG_SHOW_PAYLOAD_SCHEMA = {"type": "object"}


def _raise_handler_var_keyword_undeclared(name: str):
    raise ValueError(
        f'command "{name}": handler accepts **kwargs but the command does not '
        f'declare forwarding; add forwarding=Forwarding(reason=...) or name '
        f'every parameter explicitly'
    )


def _raise_forwarding_reason_empty(name: str):
    raise ValueError(f'command "{name}": forwarding reason must be a non-empty string')


def _raise_framework_internal_handler_foreign(name: str):
    raise ValueError(
        f'command "{name}": handler is marked framework-internal but is not '
        f'defined in the strictcli module'
    )


@dataclass
class DeprecatedCommand:
    """A declaration-only deprecated command: prints message to stderr and exits 1."""

    name: str
    message: str


# The two legal command classifications. There is no default: every command
# declares one, and a command registered without it is a registration-time
# hard error. Deprecated commands are exempt (they have no handler).
EFFECT_READ_ONLY = "read_only"
EFFECT_MUTATING = "mutating"
_EFFECT_VALUES = (EFFECT_READ_ONLY, EFFECT_MUTATING)


def _raise_command_effect_missing(name: str):
    raise ValueError(
        f'command "{name}": effect classification is required '
        f'(effect="read_only" or effect="mutating")'
    )


def _raise_command_effect_invalid(name: str, value: object):
    raise ValueError(
        f'command "{name}": invalid effect "{value}": '
        f'must be "read_only" or "mutating"'
    )


def _raise_deprecated_command_effect(name: str):
    raise ValueError(
        f'deprecated command "{name}": effect classification does not apply '
        f'(a deprecated command has no handler)'
    )


def _raise_command_read_only_consequential(name: str):
    """A read_only command cannot be consequential (contract §8.1).

    Classification answers "should a dry run record rather than execute?";
    ``consequential`` answers "are these effects worth interrupting someone
    for?". A command that changes nothing has no effects to weigh, so the two
    declarations cannot both hold.
    """
    raise ValueError(
        f'command "{name}": a read_only command cannot be consequential '
        f'(a command that changes nothing has nothing to confirm)'
    )


def _raise_command_read_only_dry_run_unsupported(name: str):
    """A read_only command cannot declare ``dry_run_supported=False``.

    Mirrors the read_only + consequential prohibition: a command that changes
    nothing records nothing, so a preview of it can never be dishonest and
    there is no reason to refuse one.
    """
    raise ValueError(
        f'command "{name}": a read_only command cannot declare '
        f'dry_run_supported=false (a command that changes nothing has no '
        f'effects a preview could misrepresent)'
    )


def _raise_command_dry_run_reason_missing(name: str):
    raise ValueError(
        f'command "{name}": dry_run_supported=false requires a non-empty '
        f'dry_run_unsupported_reason (say what a preview cannot honestly show)'
    )


def _raise_command_dry_run_reason_without_declaration(name: str):
    raise ValueError(
        f'command "{name}": dry_run_unsupported_reason requires '
        f'dry_run_supported=false (there is nothing to explain while dry run '
        f'is supported)'
    )


def _validate_dry_run_declaration(
    name: str, effect: str, dry_run_supported: bool,
    dry_run_unsupported_reason: str | None,
) -> None:
    """The three registration-time guards on the dry-run declaration.

    Shared by :class:`Command.__post_init__` and
    :func:`_build_and_validate_command` so both registration surfaces reject
    the same shapes with the same messages.
    """
    has_reason = (
        isinstance(dry_run_unsupported_reason, str)
        and bool(dry_run_unsupported_reason.strip())
    )
    if not dry_run_supported:
        if effect == EFFECT_READ_ONLY:
            _raise_command_read_only_dry_run_unsupported(name)
        if not has_reason:
            _raise_command_dry_run_reason_missing(name)
    elif dry_run_unsupported_reason is not None:
        _raise_command_dry_run_reason_without_declaration(name)


@dataclass(frozen=True)
class Command:
    """A leaf command with a handler."""

    name: str
    help: str
    handler: Callable | None
    effect: str
    # Declared per-command (contract §8.1). NOT mandatory -- absence means
    # "not consequential". It is a property of the COMMAND, deliberately not
    # named after the framework's reaction to it, so other behaviours can hang
    # off it later. Today the framework prompts for exactly these commands.
    consequential: bool = False
    # Declared per-command. Absence means "dry run is supported", which is the
    # regime's baseline: a mutating command records rather than executes. A
    # command that declares it false is saying a preview of it would LIE --
    # its effects escape the effects handle, or its later steps read state the
    # recorded ones would have written -- so the framework refuses --dry-run
    # for it at parse time rather than rendering a preview nobody can trust.
    # The reason is mandatory and is shown in help and in the refusal.
    dry_run_supported: bool = True
    dry_run_unsupported_reason: str | None = None
    # The command's machine payload contract (contract §19.5): an inline JSON
    # Schema literal, registered as written. Absence means the command cannot
    # produce a payload -- ctx.payload is then a call-time hard error. The
    # literal is validated at registration over the closed subset, and the
    # value ctx.payload supplies is validated against it at emission.
    payload_schema: dict | None = None
    flags: tuple[Flag, ...] = ()
    args: tuple[Arg, ...] = ()
    flag_sets: tuple[FlagSet, ...] = ()
    mutex: tuple[MutexGroup, ...] = ()
    dependencies: tuple[CoRequired | Requires | Implies, ...] = ()
    passthrough: Passthrough | None = None
    tags: frozenset[str] = frozenset()
    hidden: bool = False
    interactive: bool = False
    config_fields: tuple[str, ...] = ()
    grants: tuple[Grant, ...] = ()
    forwarding: Forwarding | None = None
    # Private marker, set ONLY by strictcli's own registration paths. It is not
    # reachable from any public factory, option or keyword, and is not emitted
    # in the schema.
    _framework_internal: bool = False

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Command")
        if self.effect not in _EFFECT_VALUES:
            _raise_command_effect_invalid(self.name, self.effect)
        if self.consequential and self.effect == EFFECT_READ_ONLY:
            _raise_command_read_only_consequential(self.name)
        _validate_dry_run_declaration(
            self.name, self.effect, self.dry_run_supported,
            self.dry_run_unsupported_reason,
        )
        # The declared payload schema is validated as written, over the closed
        # subset (§19.5). An unknown keyword anywhere in the literal is a hard
        # error here, which is what keeps the subset closed by construction.
        if self.payload_schema is not None:
            found = _validate_payload_schema(self.payload_schema)
            if found is not None:
                raise ValueError(
                    _msg_payload_schema_invalid(self.name, found[0], found[1])
                )
        for tag in self.tags:
            if not _IDENTIFIER_RE.fullmatch(tag):
                raise ValueError(f'invalid tag name "{tag}": must match [a-z][a-z0-9-]*')


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
    tags: frozenset[str] = frozenset()
    _accumulated_tags: frozenset[str] = frozenset()
    hidden: bool = False
    _config_fields_ref: dict[str, ConfigField] = field(default_factory=dict)
    _infra_root_names: frozenset[str] = frozenset()
    _connection_env_names: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "Group")
        for tag in self.tags:
            if not _IDENTIFIER_RE.fullmatch(tag):
                raise ValueError(f'invalid tag name "{tag}": must match [a-z][a-z0-9-]*')

    def group(self, name: str, *, help: str, tags: set[str] | None = None,
              hidden: bool = False) -> Group:
        """Create and register a child subgroup."""
        if name in self.commands:
            raise ValueError(
                f'group "{name}" collides with an existing command'
            )
        if name in self._groups:
            raise ValueError(
                f'group "{name}" is already registered'
            )
        own_tags = frozenset(tags or set())
        grp = Group(name=name, help=help, env_prefix=self.env_prefix,
                     _global_flags=self._global_flags,
                     tags=own_tags,
                     _accumulated_tags=self._accumulated_tags | own_tags,
                     hidden=hidden,
                     _config_fields_ref=self._config_fields_ref,
                     _infra_root_names=self._infra_root_names,
                     _connection_env_names=self._connection_env_names)
        self._groups[name] = grp
        return grp

    def deprecate(self, name: str, *, message: str,
                  effect: str | None = None) -> None:
        """Register a deprecated subcommand in this group.

        Deprecated entries are classification-EXEMPT: they have no handler and
        execute nothing, so passing ``effect=`` is a registration-time error.
        """
        if effect is not None:
            _raise_deprecated_command_effect(name)
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
        effect: str | None = None,
        consequential: bool = False,
        dry_run_supported: bool = True,
        dry_run_unsupported_reason: str | None = None,
        payload_schema: dict | None = None,
        args: list[Arg] | None = None,
        flag_sets: list[FlagSet] | None = None,
        mutex: list[MutexGroup] | None = None,
        dependencies: list[CoRequired | Requires | Implies] | None = None,
        passthrough: Passthrough | None = None,
        grants: list[Grant] | None = None,
        forwarding: Forwarding | None = None,
        tags: set[str] | None = None,
        hidden: bool = False,
        interactive: bool = False,
        config_fields: list[str] | None = None,
    ) -> Callable[[F], F]:
        """Decorator to register a command within this group."""

        def decorator(func: F) -> F:
            if name in self._groups:
                raise ValueError(
                    f'command "{name}" collides with an existing group'
                )
            cmd = _build_and_validate_command(
                name, help=help, effect=effect,
                consequential=consequential,
                dry_run_supported=dry_run_supported,
                dry_run_unsupported_reason=dry_run_unsupported_reason,
                payload_schema=payload_schema,
                handler=func, args=args, flag_sets=flag_sets, mutex=mutex,
                dependencies=dependencies,
                env_prefix=self.env_prefix,
                global_flags=self._global_flags,
                passthrough=passthrough,
                grants=grants,
                forwarding=forwarding,
                tags=tags,
                inherited_tags=self._accumulated_tags,
                hidden=hidden,
                interactive=interactive,
                config_fields=config_fields,
                config_fields_ref=self._config_fields_ref,
                infra_root_names=self._infra_root_names,
                connection_env_names=self._connection_env_names,
            )
            self.commands[name] = cmd
            return func

        return decorator


_CONFIG_FIELD_NAME_RE = re.compile(r"^_?[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


@dataclass
class ConfigField:
    """Declares a typed config file field.

    Fields with no default are required — the config system will error if
    they are missing from the config file. Fields with a default are optional.
    """

    name: str
    type: type
    help: str
    default: object = _MISSING
    required: bool = field(init=False)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.help, "help", "ConfigField")
        if self.type not in (str, bool, int, float):
            raise ValueError(
                f"ConfigField.type must be str, bool, int, or float, got {self.type!r}"
            )
        if not _CONFIG_FIELD_NAME_RE.fullmatch(self.name):
            raise ValueError(
                f'ConfigField name "{self.name}" is invalid: '
                f"must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* "
                f"(lowercase, dots for sections)"
            )
        self.required = isinstance(self.default, _MissingSentinel)
        if not self.required and not isinstance(self.default, self.type):
            raise ValueError(
                f'ConfigField "{self.name}": default value {self.default!r} '
                f"does not match type {self.type.__name__}"
            )


@dataclass
class Result:
    """Returned by app.test()."""

    stdout: str
    stderr: str
    exit_code: int
    data: object = None


@dataclass(frozen=True)
class _DispatchResult:
    """What the one dispatch seam hands back to ``run()`` / ``test()``.

    ``payload`` is ``_MISSING`` when the handler supplied none (a dispatch
    that never reached a handler always has none).
    """

    exit_code: int
    payload: object = _MISSING


@dataclass
class Tool:
    """A tool descriptor for exposing CLI commands to tool-using LLM agents."""

    name: str
    description: str
    parameters: dict
    # The effects-regime classification, published BESIDE the argument schema
    # (never inside it): a consumer rendering this tool must be able to see
    # that the command changes things and that calling it requires stating
    # consent. Same vocabulary as the schema dump: `effect` is mandatory,
    # `consequential` defaults to False.
    effect: str
    consequential: bool
    execute: Callable


# Module-private mint token: a _CheckOutcome can be constructed only by code
# that holds this token (the reporters and the runner's internal skip mint).
# This is the seal that makes forging an outcome directly impossible.
_MINT_TOKEN = object()


@dataclass(frozen=True)
class _CheckProblem:
    """A single minted finding: text plus severity ("error" or "warn").

    Module-private -- problems are minted only via reporter methods.
    """

    text: str
    severity: str


@dataclass(frozen=True)
class _CheckOutcome:
    """The ceiling-typed result of a check implementation.

    Module-private with a construction guard: a valid outcome is obtained ONLY
    through reporter methods (passed/skipped/found) or the runner's internal
    skip mint, both of which pass ``_MINT_TOKEN``. Direct construction raises.
    """

    kind: str  # "passed", "skipped", "found"
    message: str
    problems: tuple[_CheckProblem, ...] = ()
    # notes is an informational, verdict-inert channel: notes are recorded
    # unconditionally on ANY outcome (including a pass) via reporter.note. They
    # are PROVABLY inert -- excluded from status derivation, gating, problem
    # ordering, and exit codes. They surface only under --verbose and in JSON.
    notes: tuple[str, ...] = ()
    _token: object = None

    def __post_init__(self) -> None:
        if self._token is not _MINT_TOKEN:
            raise TypeError(
                "_CheckOutcome cannot be constructed directly; "
                "obtain one from a reporter (passed/skipped/found)"
            )

    @property
    def status(self) -> str:
        """Derived verdict label ("pass"/"fail"/"warn"/"skip")."""
        return _derive_status(self)

    def _ordered_problems(self) -> tuple[_CheckProblem, ...]:
        """Problems grouped by severity: all error problems, then all warns."""
        errs = tuple(p for p in self.problems if p.severity == "error")
        warns = tuple(p for p in self.problems if p.severity == "warn")
        return errs + warns


def _mint_skip(message: str) -> _CheckOutcome:
    """Runner-internal mint for cascade/scope skip outcomes."""
    return _CheckOutcome(kind="skipped", message=message, _token=_MINT_TOKEN)


def _check_abort_text(name: str, type_name: str, message: str) -> str:
    """Build the attribution line for a check whose impl aborted.

    Names the check, the exception type (so a framework or harness bug stays
    identifiable) and the exception's own message. An empty message drops the
    colon rather than emitting a dangling one.
    """
    if message:
        return f'check "{name}" aborted with {type_name}: {message}'
    return f'check "{name}" aborted with {type_name}'


def _mint_check_abort(name: str, exc: BaseException) -> _CheckOutcome:
    """Runner-internal mint for a check whose impl raised.

    The abort is reported as THAT check's own failure: a found outcome carrying
    a single error-severity problem, so it derives FAIL, fails the run, and
    cascade-skips its dependents exactly like any other failing check. Every
    rendering surface (the result row, the problem line, both JSON fields)
    carries the full attribution, so no reader loses it.
    """
    text = _check_abort_text(name, type(exc).__name__, str(exc))
    return _CheckOutcome(
        kind="found",
        message=text,
        problems=(_CheckProblem(text=text, severity="error"),),
        _token=_MINT_TOKEN,
    )


def _derive_status(outcome: _CheckOutcome) -> str:
    """Map a minted outcome to its verdict label.

    passed => pass; skipped => skip; found with an error problem => fail;
    found with only warns => warn.
    """
    if outcome.kind == "passed":
        return "pass"
    if outcome.kind == "skipped":
        return "skip"
    if outcome.kind == "found":
        if any(p.severity == "error" for p in outcome.problems):
            return "fail"
        return "warn"
    # Defensive: outcomes are only ever minted with one of the three kinds
    # above. Mirrors the Go implementation's panic so the two stay in parity.
    raise ValueError(f"unknown check outcome kind {outcome.kind!r}")


class _ReporterCore:
    """Shared problem accumulator and minting surface for both reporters.

    Holds warn()/passed()/skipped()/found(). Error-minting lives ONLY on
    ErrorReporter, so WarnReporter structurally lacks it (accessing ``.error``
    on a WarnReporter is an AttributeError at runtime and a type error under
    mypy).
    """

    def __init__(self) -> None:
        self._problems: list[_CheckProblem] = []
        # Notes accumulate informational messages recorded via note(). They are
        # carried onto the minted outcome but never influence status, gating, or
        # exit codes -- a verdict-inert reporting channel.
        self._notes: list[str] = []

    def note(self, text: str) -> None:
        """Record an informational note. Non-empty text required.

        Notes are allowed on EVERY outcome, including a pass -- they never
        trigger the problems-present errors that passed()/skipped() enforce.
        Notes are verdict-inert: they surface only under --verbose and in JSON.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("note text must be a non-empty string")
        self._notes.append(text)

    # Reporter validation messages are worded identically to the Go
    # implementation (method-agnostic phrasing, no "warn(text)"/"Warn:" prefix)
    # so the two implementations are byte-for-byte in parity -- see
    # conformance/check_error_parity.py.
    def warn(self, text: str) -> None:
        """Mint a warn-severity problem. Non-empty text required."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("problem text must be a non-empty string")
        self._problems.append(_CheckProblem(text=text, severity="warn"))

    def passed(self, message: str) -> _CheckOutcome:
        """Finalize a terminal PASS. Errors if any problems were reported."""
        if not isinstance(message, str) or not message.strip():
            raise ValueError("outcome message must be a non-empty string")
        if self._problems:
            raise ValueError(
                "problems were reported; a check that found problems "
                "cannot pass -- use found instead"
            )
        return _CheckOutcome(
            kind="passed", message=message,
            notes=tuple(self._notes), _token=_MINT_TOKEN,
        )

    def skipped(self, reason: str) -> _CheckOutcome:
        """Finalize a terminal SKIP. Errors if any problems were reported."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("skip reason must be a non-empty string")
        if self._problems:
            raise ValueError(
                "problems were reported; a check that found problems "
                "cannot skip"
            )
        return _CheckOutcome(
            kind="skipped", message=reason,
            notes=tuple(self._notes), _token=_MINT_TOKEN,
        )

    def found(self, message: str) -> _CheckOutcome:
        """Finalize an outcome carrying the accumulated problems.

        Errors when nothing was reported -- nothing found means pass, so say so
        explicitly with passed().
        """
        if not isinstance(message, str) or not message.strip():
            raise ValueError("outcome message must be a non-empty string")
        if not self._problems:
            raise ValueError(
                "no problems were reported; nothing found means pass "
                "-- use passed instead"
            )
        return _CheckOutcome(
            kind="found",
            message=message,
            problems=tuple(self._problems),
            notes=tuple(self._notes),
            _token=_MINT_TOKEN,
        )


class WarnReporter(_ReporterCore):
    """Reporter handed to warn-severity check impls.

    Can mint warn-severity problems and terminal outcomes but structurally
    LACKS error-minting: there is no ``error`` method, so a warn check cannot
    produce an error-severity problem and can never cascade.
    """


class ErrorReporter(_ReporterCore):
    """Reporter handed to error-severity check impls.

    Everything WarnReporter has PLUS ``error`` (mints an error-severity problem).
    """

    def error(self, text: str) -> None:
        """Mint an error-severity problem. Non-empty text required."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("problem text must be a non-empty string")
        self._problems.append(_CheckProblem(text=text, severity="error"))


@dataclass(frozen=True)
class SkipCheck:
    """Directive a scope adapter returns to skip a check with a reason.

    The adapter can no longer mint arbitrary outcomes -- it either returns a
    replacement context (context projection) or this skip directive.
    """

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("SkipCheck.reason must be a non-empty string")


@dataclass(frozen=True)
class CheckRunResult:
    """A named check outcome returned by App.run_checks().

    The verdict is derived from the minted outcome; the runner's exit/cascade
    logic and the formatters all consume these same accessors (one source of
    truth).
    """

    name: str
    outcome: _CheckOutcome
    # Wall-clock time in integer milliseconds spent inside the check impl.
    # Captured around the impl call only; checks that never execute
    # (cascade-skipped) carry 0. Purely informational -- never affects status
    # or exit codes.
    duration_ms: int = 0

    @property
    def status(self) -> str:
        """Derived label: "pass", "fail", "warn", or "skip"."""
        return _derive_status(self.outcome)

    @property
    def message(self) -> str:
        """The outcome's human-readable message."""
        return self.outcome.message

    @property
    def problems(self) -> tuple[_CheckProblem, ...]:
        """The minted problems (error and warn severity) from this check run."""
        return self.outcome.problems

    @property
    def notes(self) -> tuple[str, ...]:
        """Informational notes recorded during the check run (verdict-inert)."""
        return self.outcome.notes

    def gated(self) -> bool:
        """Whether the outcome carries an error-severity problem (derived FAIL)."""
        return self.status == "fail"

    def warned(self) -> bool:
        """Whether the outcome carries only warn-severity problems (derived WARN)."""
        return self.status == "warn"


@runtime_checkable
class CheckContext(Protocol):
    """Minimal interface that tool-specific check contexts must satisfy."""

    project_root: Path


class ConnectionEnvReader(Protocol):
    """OPTIONAL capability a check context may expose: the value of a declared
    connection env (``connection_env``), read live -- EXCEPT under --hermetic,
    where it resolves as absent ``(None, False)`` so a check can skip visibly
    instead of connecting. The check command wraps the tool-supplied check
    context in a value that satisfies this protocol, backed by the app's declared
    connection envs and the invocation's hermetic state. Checks that need a
    connection URL call ``ctx.connection_env_value("DATABASE_URL")``.

    ``is_hermetic()`` reports whether the invocation ran under --hermetic. It
    exists so a check can DISTINGUISH the two cases that
    ``connection_env_value``'s ``present=False`` otherwise conflates:
    "--hermetic suppressed the connection env" vs "the env var is simply unset".
    A check that layers config fallbacks below the env must honor hermetic even
    when the env is unset -- otherwise it falls through to a config URL and
    connects, violating the hermetic guarantee::

        dsn, present = ctx.connection_env_value("DATABASE_URL")
        if not present:
            if ctx.is_hermetic():
                return reporter.skipped("hermetic: connection suppressed")
            # env unset but not hermetic -- config fallback is allowed here
    """

    def connection_env_value(self, env_var: str) -> "tuple[str | None, bool]": ...

    def is_hermetic(self) -> bool: ...


class _CheckContextWithConn:
    """Wraps a tool-supplied check context, delegating attribute access while
    adding connection-env access (hermetic-suppressed) so check functions can
    read declared connection envs without the tool implementing anything beyond
    ``project_root``."""

    def __init__(self, base, connections: frozenset[str], hermetic: bool) -> None:
        self._base = base
        self._connections = connections
        self._hermetic = hermetic

    def __getattr__(self, name):
        return getattr(self._base, name)

    def connection_env_value(self, env_var: str) -> "tuple[str | None, bool]":
        if env_var in self._connections:
            if self._hermetic:
                return None, False
            if env_var in os.environ:
                return os.environ[env_var], True
            return None, False
        raise KeyError(f'"{env_var}" is not a declared connection env var')

    def is_hermetic(self) -> bool:
        """Report whether the invocation ran under --hermetic. Mirrors the
        hermetic flag captured when the wrapper was built."""
        return self._hermetic


@dataclass
class _CheckDef:
    """Internal definition of a single check loaded from TOML."""

    name: str
    tags: list[str]
    severity: str
    fast: bool
    pure: bool
    needs_network: bool
    depends_on: list[str]
    scope: str = ""
    impl: object | None = None
    impl_form: str = ""  # "error" or "warn" -- registration form, for the severity cross-check


@dataclass(frozen=True)
class CheckSpec:
    """A fully-formed, ceiling-typed check produced by a check provider.

    Opaque by construction: build one only via :func:`error_check_spec` or
    :func:`warn_check_spec`, which bind the reporter form to the declared
    severity so the impl cannot mint a problem its severity forbids. Providers
    return lists of these (see :meth:`App.register_check_provider`).
    """

    name: str
    tags: list[str]
    severity: str
    fast: bool
    pure: bool
    needs_network: bool
    depends_on: list[str]
    scope: str
    _impl: Callable  # (ctx) -> _CheckOutcome, reporter already bound
    _impl_form: str  # "error" or "warn" -- bound by the constructor


def error_check_spec(
    *,
    name: str,
    tags: list[str],
    fast: bool,
    pure: bool,
    needs_network: bool,
    depends_on: list[str],
    impl: Callable,
    severity: str = "error",
    scope: str = "",
) -> CheckSpec:
    """Build an error-severity check spec for a provider.

    ``impl`` receives ``(ctx, reporter)`` where ``reporter`` is an
    :class:`ErrorReporter` (can mint both error- and warn-severity problems).
    ``severity`` must be ``"error"`` -- a mismatch is a hard error at
    materialization (the provider analog of the TOML/register severity check).
    """
    def run(ctx: CheckContext) -> _CheckOutcome:
        return impl(ctx, ErrorReporter())

    return CheckSpec(
        name=name, tags=list(tags), severity=severity, fast=fast, pure=pure,
        needs_network=needs_network, depends_on=list(depends_on), scope=scope,
        _impl=run, _impl_form="error",
    )


def warn_check_spec(
    *,
    name: str,
    tags: list[str],
    fast: bool,
    pure: bool,
    needs_network: bool,
    depends_on: list[str],
    impl: Callable,
    severity: str = "warn",
    scope: str = "",
) -> CheckSpec:
    """Build a warn-severity check spec for a provider.

    ``impl`` receives ``(ctx, reporter)`` where ``reporter`` is a
    :class:`WarnReporter`, which structurally lacks error-minting: a warn check
    cannot cascade. ``severity`` must be ``"warn"``.
    """
    def run(ctx: CheckContext) -> _CheckOutcome:
        return impl(ctx, WarnReporter())

    return CheckSpec(
        name=name, tags=list(tags), severity=severity, fast=fast, pure=pure,
        needs_network=needs_network, depends_on=list(depends_on), scope=scope,
        _impl=run, _impl_form="warn",
    )


@dataclass
class App:
    """The root CLI application."""

    name: str
    help: str
    version: str | None = None
    env_prefix: str | None = None
    config: bool = False
    config_path: str | None = None
    config_format: str = "json"
    config_conflict_mode: str = "cli-wins"
    no_default_config_path: bool = False
    # Infrastructure env vars. infra_root maps a location env var -> its default
    # path (dict preserves declaration order). handshake_env maps a cross-tool
    # protocol env var -> its help string.
    infra_root: dict[str, str] | None = None
    handshake_env: dict[str, str] | None = None
    # connection_env maps a behavioral "reach outside the process" env var
    # (e.g. a database/service URL) -> its help string. Unlike roots and
    # handshakes it is hermetic-SUPPRESSED: under --hermetic it resolves as
    # absent. No default, read lazily. Flags bind to it via connection_url=.
    connection_env: dict[str, str] | None = None
    # App-level observe authorization: a list of argv PREFIXES. A
    # ctx.effects.run whose argv matches one element-wise (string equality only)
    # is an observe: it executes even in dry mode, returns a real value, and is
    # never written to the would-do log.
    proc_observe_allowlist: list[list[str]] | None = None
    checks_path: str | Path | None = None
    checks_embed: bytes | None = None
    test_coverage: bool = False
    flags: list[Flag] = field(default_factory=list)
    _commands: dict[str, Command] = field(default_factory=dict)
    _groups: dict[str, Group] = field(default_factory=dict)
    _deprecated: dict[str, DeprecatedCommand] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_str(self.version, "version", "App")
        _require_non_empty_str(self.help, "help", "App")
        # Check for duplicate and reserved global flag names
        seen: set[str] = set()
        for f in self.flags:
            if f.name in seen:
                raise ValueError(f'duplicate global flag name "{f.name}"')
            if f.name in _RESERVED_FRAMEWORK_FLAG_NAMES:
                # Unreachable through Flag() construction (Flag.__post_init__
                # bans the quartet first); kept so the global-flag validation
                # path carries the same message for any other construction route.
                _raise_flag_name_reserved_by_framework(f.name)
            if f.name in _BANNED_FLAG_NAMES:
                # Likewise unreachable through Flag(); kept for parity with the
                # quartet's own belt-and-braces check on this path.
                _raise_flag_name_yes_banned()
            if f.name in _RESERVED_GLOBAL_FLAG_NAMES:
                raise ValueError(
                    f'global flag name "{f.name}" is reserved'
                )
            if f.short and f.short in _RESERVED_GLOBAL_SHORT_NAMES:
                raise ValueError(
                    f'global short flag "{f.short}" is reserved'
                )
            seen.add(f.name)
        self._global_flags: list[Flag] = list(self.flags)
        self._last_global_values: dict[str, object] = {}
        self._last_sources: dict[str, str] = {}
        self._last_hermetic: bool = False
        # Framework-owned reserved quartet, extracted by the pre-scan and
        # delivered on the Context (never as handler kwargs).
        self._last_dry_run: bool = False
        self._last_approve_consequential: bool = False
        self._last_quiet: bool = False
        # Machine mode (contract §19.1), delivered on the Context like the
        # quartet: extracted by the pre-scan, never a handler kwarg.
        self._last_json: bool = False
        self._last_verbose: bool = False

        # Observe allowlist: plain argv prefixes, compared by string equality.
        prefixes: list[tuple[str, ...]] = []
        for prefix in self.proc_observe_allowlist or ():
            if isinstance(prefix, str) or not isinstance(prefix, (list, tuple)):
                raise ValueError(
                    "proc_observe_allowlist entries must be lists of strings, "
                    f"got {type(prefix).__name__}"
                )
            if not prefix:
                raise ValueError(
                    "proc_observe_allowlist entries must not be empty"
                )
            for element in prefix:
                if not isinstance(element, str):
                    raise ValueError(
                        "proc_observe_allowlist entries must be lists of "
                        f"strings, got {type(element).__name__}"
                    )
            prefixes.append(tuple(prefix))
        self._proc_observe_allowlist: tuple[tuple[str, ...], ...] = tuple(prefixes)

        # The structured effect log for the most recent dispatch. Populated in
        # BOTH modes: recorded entries in dry mode, executed entries (with
        # recorded=False) in live mode, plus framework-blessed CACHE_WRITEs.
        self._effect_log = _EffectLog()

        # The stdin side of the confirm protocol. Swappable through the
        # test-only ``_set_confirm_io`` seam; the real reader by default.
        self._confirm_io: _ConfirmIO = _REAL_CONFIRM_IO

        # Resolve infrastructure roots eagerly, at construction. Infra vars have
        # no argv dependency, so resolution is sound here -- and this is WHY it
        # is hermetic-immune: there is no argv yet to consult, so --hermetic
        # (which only suppresses argv-derived config/env behavior) can never
        # affect location roots.
        self._infra_roots: dict[str, str] = {}
        self._infra_root_order: list[str] = []
        self._infra_root_defaults: dict[str, str] = {}
        self._infra_root_from_env: dict[str, bool] = {}
        if self.infra_root:
            for env_var, default_path in self.infra_root.items():
                if env_var in os.environ:
                    self._infra_roots[env_var] = os.path.expanduser(os.environ[env_var])
                    self._infra_root_from_env[env_var] = True
                else:
                    self._infra_roots[env_var] = os.path.expanduser(default_path)
                    self._infra_root_from_env[env_var] = False
                self._infra_root_order.append(env_var)
                self._infra_root_defaults[env_var] = default_path
        self._handshake_envs: dict[str, str] = dict(self.handshake_env) if self.handshake_env else {}
        self._handshake_order: list[str] = list(self.handshake_env.keys()) if self.handshake_env else []
        for ev in self._handshake_order:
            if not self._handshake_envs[ev] or not self._handshake_envs[ev].strip():
                raise ValueError(f'handshake env var "{ev}": help must be a non-empty string')
            if ev in self._infra_roots:
                raise ValueError(f'handshake env var "{ev}" is already declared as an infra root')
        # Connection env vars: behavioral, hermetic-suppressed, no default.
        self._connection_envs: dict[str, str] = dict(self.connection_env) if self.connection_env else {}
        self._connection_order: list[str] = list(self.connection_env.keys()) if self.connection_env else []
        for ev in self._connection_order:
            if not self._connection_envs[ev] or not self._connection_envs[ev].strip():
                raise ValueError(f'connection env var "{ev}": help must be a non-empty string')
            if ev in self._infra_roots:
                raise ValueError(f'connection env var "{ev}" is already declared as an infra root')
            if ev in self._handshake_envs:
                raise ValueError(f'connection env var "{ev}" is already declared as a handshake env var')
        self._connection_env_names: frozenset[str] = frozenset(self._connection_envs)
        # A shared frozenset of declared root names, threaded to commands/groups
        # so flag-default markers can be validated at registration time.
        self._infra_root_names: frozenset[str] = frozenset(self._infra_roots)
        # Resolve the config-path marker (if any) now that roots exist.
        if isinstance(self.config_path, RelativeToRoot):
            self.config_path = _resolve_infra_root_path(self.config_path, self._infra_roots)
        # Validate global flag default markers against declared roots and
        # connection-URL bindings against declared connection envs.
        for f in self._global_flags:
            self._validate_flag_infra_marker(f)
            _validate_connection_binding(f, self._connection_env_names)

        # Validate config_format
        if self.config_format not in ("json", "toml"):
            raise ValueError(
                f'App.config_format must be "json" or "toml", got {self.config_format!r}'
            )
        # Validate config_conflict_mode
        if self.config_conflict_mode not in ("cli-wins", "error"):
            raise ValueError(
                f'App.config_conflict_mode must be "cli-wins" or "error", got {self.config_conflict_mode!r}'
            )
        # Register config subcommands if enabled (config data loaded at parse time)
        self._config_data: dict = {}
        if self.config:
            self._register_config_group()
        # Discover checks TOML
        self._check_context_factory: Callable | None = None
        self._scope_adapter: Callable | None = None
        # Check-provider hook state. Providers populate the registry lazily at
        # the first registry read (materialization), memoized per cwd.
        self._check_providers: list[Callable] = []
        self._provider_sourced_names: set[str] = set()
        self._provider_materialized_cwd: str | None = None
        if self.checks_path is not None and self.checks_embed is not None:
            raise ValueError("cannot use both checks_path and checks_embed")
        if self.checks_path is not None:
            checks_toml_path = Path(self.checks_path).resolve()
            if not checks_toml_path.is_file():
                raise ValueError(f"checks_path does not exist: {self.checks_path}")
            app_name, parsed_defs = _load_checks_toml(checks_toml_path)
            if app_name != self.name:
                raise ValueError(
                    f'checks.toml: app "{app_name}" does not match app name "{self.name}"'
                )
            self._enable_checks()
            for cdef in parsed_defs.values():
                self._add_check_def(cdef)
        elif self.checks_embed is not None:
            app_name, parsed_defs = _parse_checks_toml(self.checks_embed)
            if app_name != self.name:
                raise ValueError(
                    f'checks.toml: app "{app_name}" does not match app name "{self.name}"'
                )
            self._enable_checks()
            for cdef in parsed_defs.values():
                self._add_check_def(cdef)
        else:
            self._check_defs: dict[str, _CheckDef] = {}
            self._checks_enabled = False

        self._tag_contracts: dict[str, str] = {}

        # Config field declarations
        self._config_fields: dict[str, ConfigField] = {}
        self._framework_fields: dict[str, ConfigField] = {}

        # Config parse error (for config show to pick up)
        self._config_parse_err: str | None = None

        # Test-coverage instrumentation. When enabled, every test() and call()
        # invocation records which command was dispatched so a check can verify
        # that every command in the app's surface has been exercised.
        self._coverage_shard_path: str | None = None
        self._coverage_dir: str | None = None
        self._coverage_manifest_path: str | None = None
        self._last_resolved_path: list[str] = []
        if self.test_coverage:
            # Anchor the coverage root to the cwd AT CONSTRUCTION TIME. Both the
            # recorder and the check provider use these absolute paths so that
            # tests which chdir still record into the repo, and a check evaluated
            # from a foreign cwd reads the app's own repo state.
            self._coverage_dir = os.path.abspath(
                os.path.join(".strictcli", "coverage")
            )
            self._coverage_manifest_path = os.path.abspath(
                os.path.join(".strictcli", "test-coverage.json")
            )
            self._coverage_shard_path = os.path.join(
                self._coverage_dir,
                f"{os.getpid()}.jsonl",
            )
            os.makedirs(self._coverage_dir, exist_ok=True)
            self.register_check_provider(self._test_coverage_provider)

    def _validate_flag_infra_marker(self, f: Flag) -> None:
        """Panic if a flag's default is a RelativeToRoot marker referencing an
        undeclared root. Called at registration for construction-time errors."""
        if isinstance(f.default, RelativeToRoot):
            if f.default.env_var not in self._infra_roots:
                raise ValueError(
                    f'flag "{f.name}": RelativeToRoot references undeclared infra '
                    f'root "{f.default.env_var}"; declare it as an infra root'
                )

    def _infra_access(self, hermetic: bool = False) -> "_InfraAccess | None":
        """Snapshot infra data for a Context: resolved roots + declared handshake
        env var names + declared connection env var names. Connection envs are
        suppressed when hermetic is True. Returns None when nothing is declared."""
        if not self._infra_roots and not self._handshake_envs and not self._connection_envs:
            return None
        return _InfraAccess(
            roots=dict(self._infra_roots),
            handshakes=set(self._handshake_envs),
            connections=set(self._connection_envs),
            hermetic=hermetic,
        )

    def _record_coverage(self, cmd_path: str) -> None:
        """Append a coverage record for the resolved command path.

        Each test() or call() invocation appends one JSONL line to the
        process's shard file (named "<pid>.jsonl"). Uniqueness across concurrent
        writers comes from the PID and O_APPEND; one shard per process is
        sufficient, so there is no per-write shard counter.
        """
        if self._coverage_shard_path is None:
            return
        path = self._coverage_shard_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"command": cmd_path}) + "\n")
        self._record_cache_write(path)

    def _collect_all_command_paths(self) -> set[str]:
        """Enumerate all non-deprecated leaf command paths as dotted strings."""
        paths: set[str] = set()

        for name in self._commands:
            paths.add(name)

        def _walk_group(group: Group, prefix: list[str]) -> None:
            for cmd_name in group.commands:
                paths.add(".".join(prefix + [cmd_name]))
            for sub_name, sub_group in group._groups.items():
                _walk_group(sub_group, prefix + [sub_name])

        for group_name, group in self._groups.items():
            _walk_group(group, [group_name])

        return paths

    def _collect_all_commands(self) -> list[tuple[str, "Command"]]:
        """Enumerate (dotted path, Command) pairs in registration order."""
        out: list[tuple[str, Command]] = []

        for name, cmd in self._commands.items():
            out.append((name, cmd))

        def _walk_group(group: Group, prefix: list[str]) -> None:
            for cmd_name, cmd in group.commands.items():
                out.append((".".join(prefix + [cmd_name]), cmd))
            for sub_name, sub_group in group._groups.items():
                _walk_group(sub_group, prefix + [sub_name])

        for group_name, group in self._groups.items():
            _walk_group(group, [group_name])

        return out

    def _test_coverage_provider(self) -> list[CheckSpec]:
        """Built-in check provider for cli-test-coverage.

        Registered automatically when test_coverage=True. The verdict is derived
        from committed state: the covered set is the union of the committed
        manifest (.strictcli/test-coverage.json) and any per-process shard files
        merged from .strictcli/coverage/. Every live registered command path
        (minus the injected check command) must be present in that union to pass;
        otherwise the check fails naming each uncovered command.

        Because the verdict reads the committed manifest, it is deterministic on
        every machine -- a machine that never ran the suite (no local shards)
        still gets a stable verdict from the committed manifest alone. Both the
        coverage dir and the manifest path are anchored to the App's
        construction-time cwd, so the check evaluated from a foreign cwd reads
        the app's own repo state.

        The manifest is rewritten as the monotonic union of its prior contents
        and the freshly merged shards, but ONLY when that content actually
        changes -- a pure check must not dirty a byte-identical file. Accepted
        staleness: deleting a test leaves its command covered in the manifest
        until the manifest is deliberately regenerated (e.g. by removing it and
        re-running the suite), because the union never removes a command.
        """
        def impl(ctx: CheckContext, reporter: "ErrorReporter") -> "_CheckOutcome":
            coverage_dir = self._coverage_dir
            manifest_path = self._coverage_manifest_path

            # Subject-matter gating (the sanctioned skip class, mirroring
            # project-type gating): when the anchored coverage root holds NEITHER
            # a committed manifest NOR any shard files, this is not the app's own
            # development tree -- e.g. an installed app running its checks from a
            # foreign project's cwd, where the construction-anchored root points
            # at a directory with no coverage state. Report a visible SKIP instead
            # of failing with the app's entire command surface listed as
            # uncovered. When EITHER exists, behavior is unchanged: a partial
            # manifest still fails honestly, and an empty-manifest file present
            # still means "coverage configured but empty" = fail listing all.
            manifest_exists = bool(manifest_path) and os.path.isfile(manifest_path)
            shards_exist = bool(coverage_dir) and os.path.isdir(coverage_dir) and any(
                fname.endswith(".jsonl") for fname in os.listdir(coverage_dir)
            )
            if not manifest_exists and not shards_exist:
                anchor = os.path.dirname(manifest_path) if manifest_path else coverage_dir
                return reporter.skipped(
                    f"no coverage state at {anchor} -- cli-test-coverage applies "
                    "to the app's own development tree"
                )

            covered: set[str] = set()

            # Seed from the committed manifest -- this is what makes the verdict
            # deterministic on machines that never ran the suite.
            if manifest_path and os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        covered.update(c for c in data if isinstance(c, str))
                except (json.JSONDecodeError, OSError):
                    pass

            # Merge shards (optional freshness input)
            if coverage_dir and os.path.isdir(coverage_dir):
                for fname in os.listdir(coverage_dir):
                    if not fname.endswith(".jsonl"):
                        continue
                    fpath = os.path.join(coverage_dir, fname)
                    with open(fpath, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            entry = json.loads(line)
                            if "command" in entry:
                                covered.add(entry["command"])

            # Rewrite the manifest as the monotonic union, but only when the
            # content actually changes (keeps a pure check from dirtying a
            # byte-identical file).
            if manifest_path and covered:
                new_content = json.dumps(sorted(covered), indent=2) + "\n"
                existing: str | None = None
                if os.path.isfile(manifest_path):
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            existing = f.read()
                    except OSError:
                        existing = None
                if existing != new_content:
                    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
                    with open(manifest_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    self._record_cache_write(manifest_path)

            # Compare against command surface (exclude the framework-injected
            # check command -- it is not a user command)
            all_commands = self._collect_all_command_paths()
            all_commands.discard("check")
            uncovered = sorted(all_commands - covered)

            if uncovered:
                for cmd in uncovered:
                    reporter.error(f"no test coverage for command: {cmd}")
                return reporter.found(
                    f"{len(uncovered)} command(s) with zero test coverage"
                )
            return reporter.passed(
                f"all {len(all_commands)} commands have test coverage"
            )

        return [
            error_check_spec(
                name="cli-test-coverage",
                tags=["test"],
                fast=True,
                pure=True,
                needs_network=False,
                depends_on=[],
                impl=impl,
            ),
        ]

    def _effects_bypass_provider(self) -> list[CheckSpec]:
        """Built-in check provider for the three effects-regime lints.

        Registered whenever the check system turns on, so a consumer that
        adopts checks at all gets all three without a TOML declaration:

        - ``effects-bypass`` (error) fails on any direct process,
          filesystem-mutation or network call REACHABLE FROM A REGISTERED
          COMMAND HANDLER. Its remediation is always "route it through
          ctx.effects", so a leaf the handle could not carry must never be a
          finding: the handle's closed method set has no in-process-observe
          method, which is why ``platform.system()`` is exempt while
          ``os.system(...)`` is not (see :data:`_BYPASS_PROCESS_OS_ONLY`);
        - ``observe-allowlist-breadth`` (warn) surfaces short
          ``proc_observe_allowlist`` prefixes, which authorize real execution
          under ``--dry-run``;
        - ``consequential-grant-agreement`` (warn) surfaces commands that
          declare a process- or network-mutating grant but do not declare
          themselves consequential.
        """
        def impl(ctx: CheckContext, reporter: "ErrorReporter") -> "_CheckOutcome":
            findings = _scan_effects_bypasses(Path(ctx.project_root))
            for rel, lineno, func_name, target in findings:
                reporter.error(
                    f"{rel}:{lineno}: {func_name} calls {target} directly; "
                    f"route it through ctx.effects"
                )
            if findings:
                return reporter.found(
                    f"{len(findings)} direct effect call(s) bypassing ctx.effects"
                )
            return reporter.passed("no direct effect calls bypass ctx.effects")

        def breadth_impl(ctx: CheckContext,
                         reporter: "WarnReporter") -> "_CheckOutcome":
            broad = [
                prefix for prefix in self._proc_observe_allowlist
                if len(prefix) == 1
            ]
            for prefix in broad:
                reporter.warn(_observe_allowlist_breadth_warning(prefix[0]))
            if broad:
                return reporter.found(
                    f"{len(broad)} single-token proc_observe_allowlist prefix(es)"
                )
            return reporter.passed(
                "no single-token proc_observe_allowlist prefixes"
            )

        def grant_agreement_impl(ctx: CheckContext,
                                 reporter: "WarnReporter") -> "_CheckOutcome":
            # Only the kinds that leave this process. A file_write or a
            # proc_spawn is local and ordinarily recoverable; a proc_mutate
            # runs another program and a net_mutate changes remote state, and
            # neither can be walked back by the framework. Widening this to
            # every grant kind would re-create the noise the consequential
            # declaration exists to remove.
            escaping = (PROC_MUTATE, NET_MUTATE)
            found = 0
            for cmd_path, cmd in self._collect_all_commands():
                if cmd.consequential:
                    continue
                for grant in cmd.grants:
                    if grant.kind not in escaping:
                        continue
                    found += 1
                    reporter.warn(_consequential_grant_warning(
                        cmd_path, grant.name, grant.kind,
                    ))
            if found:
                return reporter.found(
                    f"{found} grant(s) on non-consequential command(s)"
                )
            return reporter.passed(
                "every escaping grant sits on a consequential command"
            )

        return [
            error_check_spec(
                name="effects-bypass",
                tags=["effects", "quality"],
                fast=True,
                pure=True,
                needs_network=False,
                depends_on=[],
                impl=impl,
            ),
            warn_check_spec(
                name="observe-allowlist-breadth",
                tags=["effects", "quality"],
                fast=True,
                pure=True,
                needs_network=False,
                depends_on=[],
                impl=breadth_impl,
            ),
            warn_check_spec(
                name="consequential-grant-agreement",
                tags=["effects", "quality"],
                fast=True,
                pure=True,
                needs_network=False,
                depends_on=[],
                impl=grant_agreement_impl,
            ),
        ]

    @property
    def config_file_path(self) -> str:
        """Return the resolved config file path for this app."""
        return _config_path(self.name, override=self.config_path, config_format=self.config_format)

    def dump_schema_dict(self) -> dict:
        """Return the app's full schema as a dict, excluding ``project_id``.

        This is the public, CWD-free accessor for the schema. Unlike the
        ``--dump-schema`` flag (which writes ``.strictcli/schema.json`` and
        derives ``project_id`` from ``pyproject.toml`` in the current working
        directory), this method reads only the in-memory ``App`` and performs
        no filesystem or CWD access. The returned dict is byte-identical to the
        written schema file with the ``project_id`` field removed.
        """
        return _dump_schema_core(self)

    def config_field(
        self,
        name: str,
        type: type,
        help: str,
        default: object = _MISSING,
    ) -> ConfigField:
        """Declare a typed config file field.

        Args:
            name: Field name. Dots allowed for TOML sections (e.g. "serve.port").
                  Names starting with underscore are reserved for framework fields.
            type: Field type — str, bool, int, or float.
            help: Help text describing the field.
            default: Default value. If omitted, the field is required.

        Returns:
            The registered ConfigField.

        Raises:
            ValueError: If the name is invalid, duplicated, reserved, or
                        the default doesn't match the declared type.
        """
        if name.startswith("_"):
            raise ValueError(
                f'config field name "{name}" is reserved: '
                f"names starting with underscore are reserved for framework fields"
            )
        if name in self._config_fields:
            raise ValueError(f'duplicate config field name "{name}"')
        if name in self._framework_fields:
            raise ValueError(
                f'config field name "{name}" conflicts with framework field'
            )
        cf = ConfigField(name=name, type=type, help=help, default=default)
        # A config field colliding with an existing flag's param name is a
        # validation-only declaration that annotates the flag; their defaults
        # must agree. Flags registered after this field are checked from the
        # command-builder side instead.
        for f in self._collect_all_flags():
            if _flag_param_name(f.name) == name:
                _check_flag_configfield_default(f.name, f.default, cf)
        self._config_fields[name] = cf
        return cf

    def _register_framework_field(
        self,
        name: str,
        type: type,
        help: str,
    ) -> ConfigField:
        """Register a framework-owned config field (e.g. _schema_version).

        Framework fields must start with underscore. They are declared by the
        framework, not the user, and cannot conflict with user fields.
        """
        if not name.startswith("_"):
            raise ValueError(
                f'framework field name "{name}" must start with underscore'
            )
        if name in self._framework_fields:
            raise ValueError(f'duplicate framework field name "{name}"')
        if name in self._config_fields:
            raise ValueError(
                f'framework field name "{name}" conflicts with user config field'
            )
        # Framework fields are always optional (no default required from user).
        # Use _MISSING as default since they are managed internally.
        cf = ConfigField(name=name, type=type, help=help)
        self._framework_fields[name] = cf
        return cf

    def error_check(self, name: str) -> Callable[[F], F]:
        """Decorator registering an error-severity check implementation.

        The decorated function takes ``(ctx, reporter)`` where ``reporter`` is
        an :class:`ErrorReporter` (annotate it as such for mypy binding). It
        must return a :class:`_CheckOutcome` obtained from that reporter. The
        check must be declared ``severity = "error"`` in checks.toml.
        """
        return self._make_check_decorator(name, "error")

    def warn_check(self, name: str) -> Callable[[F], F]:
        """Decorator registering a warn-severity check implementation.

        The decorated function takes ``(ctx, reporter)`` where ``reporter`` is
        a :class:`WarnReporter` (which structurally lacks ``error``, so a warn
        check cannot cascade). The check must be declared ``severity = "warn"``.
        """
        return self._make_check_decorator(name, "warn")

    def _make_check_decorator(self, name: str, form: str) -> Callable[[F], F]:
        """Build the shared registration decorator for error/warn checks.

        Enforces the double-entry contract (declared vs registered) and
        cross-checks the registration FORM against the TOML-declared severity so
        that ``@app.error_check`` on a severity="warn" definition is a hard error.
        """
        def decorator(fn: F) -> F:
            if not self._checks_enabled:
                raise ValueError(
                    f'cannot register check "{name}": '
                    f"checks not enabled"
                )
            if name not in self._check_defs:
                raise ValueError(
                    f'cannot register check "{name}": '
                    f"not declared in checks.toml"
                )
            cdef = self._check_defs[name]
            if cdef.impl is not None:
                raise ValueError(f'check "{name}": duplicate registration')
            if cdef.severity != form:
                used = f"@app.{form}_check"
                want = f"@app.{cdef.severity}_check"
                raise ValueError(
                    f'check "{name}": declared severity "{cdef.severity}" in '
                    f"checks.toml but registered via {used}; use {want}"
                )
            reporter_cls = ErrorReporter if form == "error" else WarnReporter

            def run(ctx: CheckContext) -> _CheckOutcome:
                reporter = reporter_cls()
                return fn(ctx, reporter)

            cdef.impl = run
            cdef.impl_form = form
            return fn
        return decorator

    def _validate_check_registrations(self) -> str | None:
        """Validate that all declared checks have registered implementations.

        Returns an error message if any are missing, or None if all OK.
        """
        if not self._checks_enabled:
            return None
        missing = sorted(
            name for name, cdef in self._check_defs.items()
            if cdef.impl is None
        )
        if missing:
            return (
                "checks declared in checks.toml but not registered: "
                + ", ".join(missing)
            )
        return None

    def tag_contract(self, tag: str, *, requires_flag: str) -> None:
        """Declare that any command with the given tag must have the named flag."""
        if not _IDENTIFIER_RE.fullmatch(tag):
            raise ValueError(f'invalid tag name "{tag}": must match [a-z][a-z0-9-]*')
        self._tag_contracts[tag] = requires_flag

    def _validate_tag_contracts(self) -> str | None:
        """Check that all tag contracts are satisfied.

        Returns an error message if any command violates a contract, or None.
        """
        if not self._tag_contracts:
            return None

        def _check_commands(commands: dict) -> str | None:
            for cmd in commands.values():
                if cmd.passthrough is not None:
                    continue
                for tag in cmd.tags:
                    if tag in self._tag_contracts:
                        required_flag = self._tag_contracts[tag]
                        flag_names = {f.name for f in cmd.flags} | {f.name for f in self._global_flags}
                        if required_flag not in flag_names:
                            return (
                                f'command "{cmd.name}": tag "{tag}" requires '
                                f'flag "--{required_flag}"'
                            )
            return None

        def _check_groups(groups: dict) -> str | None:
            for group in groups.values():
                err = _check_commands(group.commands)
                if err:
                    return err
                err = _check_groups(group._groups)
                if err:
                    return err
            return None

        err = _check_commands(self._commands)
        if err:
            return err
        return _check_groups(self._groups)

    def _resolve_config_data(
        self,
        runtime_path_override: str | None = None,
        hermetic: bool = False,
        is_runtime_flag: bool = False,
    ) -> _ConfigLoadResult:
        """Single entry point for all config loading.

        is_runtime_flag indicates the path came from --config (hard error on missing).
        """
        if hermetic:
            return _ConfigLoadResult()
        override = runtime_path_override or self.config_path
        return _load_config(
            self.name,
            config_path_override=override,
            config_format=self.config_format,
            is_runtime_flag=is_runtime_flag,
        )

    def _validate_config_fields(self, cmd: Command, config_data: dict) -> str | None:
        """Validate config file contents against the command's bound config fields.

        Checks:
        1. Each bound required config field exists in config with the correct type.
        2. Each key in config matches a registered flag, config field, or framework
           field. Unknown keys are hard errors.

        Returns an error message string, or None if all OK.
        """
        # Check bound required config fields exist with correct type
        for cf_name in cmd.config_fields:
            cf = self._config_fields.get(cf_name)
            if cf is None:
                # Should not happen (validated at registration), but be defensive
                return f'config field "{cf_name}" is not registered'
            found, value = _nested_get(config_data, cf_name)
            if not found:
                if cf.required:
                    return (
                        f'required config field "{cf_name}" is missing from '
                        f"config file"
                    )
                # Optional and missing -- that is fine
                continue
            # Validate type
            err = _check_config_field_type(cf, value)
            if err:
                return err

        # Check all keys in config file are known
        all_config_keys = _collect_nested_keys(config_data)
        # Build set of known keys
        all_flags = self._collect_all_flags()
        known_flag_keys = {_flag_param_name(f.name) for f in all_flags}
        known_field_keys = set(self._config_fields.keys())
        known_framework_keys = set(self._framework_fields.keys())

        for key in all_config_keys:
            if key in known_flag_keys:
                continue
            if key in known_field_keys:
                continue
            if key in known_framework_keys:
                continue
            return f'unknown key "{key}" in config file'

        return None

    def set_check_context(self, factory: Callable) -> None:
        """Set the factory function that creates CheckContext for check runs.

        The factory is called with no arguments and must return a CheckContext.
        """
        self._check_context_factory = factory

    def _wrap_check_context(self, base):
        """Augment a tool-supplied check context with connection-env access
        (hermetic-suppressed). When no connection envs are declared, the base
        context is returned unchanged so the common case is unaffected."""
        if not self._connection_envs:
            return base
        return _CheckContextWithConn(base, self._connection_env_names, self._last_hermetic)

    def set_scope_adapter(self, adapter: Callable) -> None:
        """Set the scope adapter callback for scoped checks.

        The adapter is called as ``adapter(context, scope_string)`` and must
        return one of:

        - a replacement context object -- used as the check's context (context
          projection), or
        - a :class:`SkipCheck` directive -- skips the check with the given
          reason (no cascade, no exit-code change).

        The adapter can no longer mint arbitrary outcomes: it either projects
        the context or skips. (This is the Python-only scope hook; Go has no
        scope adapter -- see the note in the Go ``check.go``.)
        """
        self._scope_adapter = adapter

    def register_check_provider(
        self, provider: Callable[[], list[CheckSpec]],
    ) -> None:
        """Register a provider that supplies check specs at materialization time.

        Three check-system hooks (do not confuse them):

        1. Check provider (this method) -- REGISTRY POPULATION. A provider
           returns a list of fully-formed check specs (metadata + a ceiling-typed
           impl). Providers are the TOML-less way to add checks: they run lazily
           at the first registry read (materialization) and their specs go
           through the same single add-path as TOML-declared checks, so a name
           colliding with a TOML check or another provider's check is the usual
           hard error. Registering a provider ENABLES the check system (a
           TOML-less app with a provider gets a working ``check`` command).
        2. Check-context factory (:meth:`set_check_context`) -- PROJECT
           CONSTRUCTION. Called once per run to build the CheckContext handed to
           every check impl. Answers "what project are we checking?".
        3. Scope adapter (:meth:`set_scope_adapter`, Python-only) -- PER-CHECK
           CONTEXT PROJECTION. Called per scoped check to project the context or
           skip the check.

        A provider decides WHICH checks exist; the context factory decides WHAT
        project they see; the scope adapter decides HOW an individual check sees
        that project.

        A provider that returns an empty list is honest-empty (no checks for
        this context) and a valid no-op. A provider that raises is a hard error
        in every mode.

        Reentrancy: a provider must not trigger check execution during
        materialization (e.g. by calling :meth:`run_checks` or the check
        command). Doing so re-enters materialization while it is in progress --
        behavior is undefined (unbounded recursion). A provider's job is to
        return specs, nothing else.
        """
        if not callable(provider):
            raise ValueError("check provider must be callable")
        self._enable_checks()
        self._check_providers.append(provider)
        # Registering a new provider invalidates any prior materialization.
        self._provider_materialized_cwd = None

    def reset_check_provider_cache(self) -> None:
        """Drop provider-sourced definitions and clear the materialization memo.

        The next registry read re-runs all providers. Intended for tests and
        long-lived singletons. Does NOT unregister the providers themselves.
        """
        for name in self._provider_sourced_names:
            self._check_defs.pop(name, None)
        self._provider_sourced_names = set()
        self._provider_materialized_cwd = None

    def _materialize_check_providers(self) -> None:
        """Run providers and insert their specs, memoized on the cwd.

        Single chokepoint called at the start of every registry read (the check
        command handler and :meth:`run_checks`). A repeat call in the same cwd
        is a cheap no-op; a cwd change re-runs the providers (dropping the
        previous provider-sourced defs first).
        """
        if not self._check_providers:
            return
        cwd = os.getcwd()
        if self._provider_materialized_cwd == cwd:
            return
        # First materialization or cwd changed: drop stale provider defs, re-run.
        for name in self._provider_sourced_names:
            self._check_defs.pop(name, None)
        self._provider_sourced_names = set()
        for provider in self._check_providers:
            result = provider()  # a raising provider is a hard error in every mode
            if result is None:
                result = []
            if not isinstance(result, (list, tuple)):
                raise ValueError(
                    f"check provider must return a list of CheckSpec, "
                    f"got {type(result).__name__}"
                )
            for spec in result:
                if not isinstance(spec, CheckSpec):
                    raise ValueError(
                        f"check provider returned a non-CheckSpec value: {spec!r}"
                    )
                if spec.severity != spec._impl_form:
                    used = f"{spec._impl_form}_check_spec"
                    want = f"{spec.severity}_check_spec"
                    raise ValueError(
                        f'check "{spec.name}": declared severity '
                        f'"{spec.severity}" but registered via {used}; '
                        f"use {want}"
                    )
                cdef = _CheckDef(
                    name=spec.name, tags=list(spec.tags), severity=spec.severity,
                    fast=spec.fast, pure=spec.pure,
                    needs_network=spec.needs_network,
                    depends_on=list(spec.depends_on), scope=spec.scope,
                    impl=spec._impl, impl_form=spec._impl_form,
                )
                # Routes through the single add-path: a name colliding with a
                # TOML check or another provider's check is the usual hard error.
                self._add_check_def(cdef)
                self._provider_sourced_names.add(spec.name)
        self._provider_materialized_cwd = cwd

    def run_checks(
        self,
        context: CheckContext,
        *,
        tag_expr: str | None = None,
        name_glob: str | None = None,
        run_all: bool = False,
        ignore_warnings: bool = False,
        pure_only: bool = False,
    ) -> tuple[list[CheckRunResult], list[str], int]:
        """Run checks programmatically with filtering and dependency resolution.

        Returns (results, impure_listed, exit_code):

        - results: the executed checks as a list of CheckRunResult.
        - impure_listed: the ordered names of checks NOT executed because of the
          purity partition (empty unless ``pure_only`` is set). Listed checks
          contribute nothing to the exit code -- a consumer renders them as e.g.
          ``"would run: <name> (impure)"``.
        - exit_code: 0 if all executed checks pass (or all warn with
          ``ignore_warnings``), else 1.

        With ``pure_only`` set, only checks that are declared pure AND do not
        need network access execute; every other selected check (including a
        pure check that depends on a listed one) is listed instead. The default
        (``pure_only`` False) is byte-identical to the previous behavior.
        """
        if not self._checks_enabled:
            raise ValueError("checks are not enabled on this App")
        # Materialize provider-sourced checks before any registry read.
        self._materialize_check_providers()
        err = self._validate_check_registrations()
        if err:
            raise ValueError(err)
        selected = _filter_checks(self._check_defs, tag_expr, name_glob, run_all)
        if not selected:
            return ([], [], 0)
        order = _resolve_check_order(self._check_defs, selected)
        raw_results, impure_listed, exit_code = _run_checks(
            self._check_defs, order, context, ignore_warnings,
            scope_adapter=self._scope_adapter, pure_only=pure_only,
        )
        results = [
            CheckRunResult(name=name, outcome=outcome, duration_ms=duration_ms)
            for name, outcome, duration_ms in raw_results
        ]
        return (results, impure_listed, exit_code)

    def _enable_checks(self) -> None:
        """Turn on the check system exactly once.

        Flips ``_checks_enabled``, initializes the check registry if it is not
        already present, and registers the auto-generated ``check`` command a
        single time. Idempotent: calling it again is a no-op. Callers (currently
        the TOML-loading branches) route through this so that future check
        sources share the same enablement path.
        """
        if getattr(self, "_checks_enabled", False):
            return
        self._checks_enabled = True
        if not hasattr(self, "_check_defs"):
            self._check_defs: dict[str, _CheckDef] = {}
        self._register_check_command()
        # The built-in effects-bypass lint rides the same provider hook the
        # built-in cli-test-coverage check uses. Appended directly (not through
        # register_check_provider) because that method routes back here.
        self._check_providers.append(self._effects_bypass_provider)
        self._provider_materialized_cwd = None

    def _add_check_def(self, cdef: _CheckDef) -> None:
        """Single internal insertion point for check definitions.

        Rejects duplicate names as a hard error and inserts the definition into
        the registry. TOML loading routes through here; this is also the future
        insertion point for provider-sourced definitions.
        """
        if cdef.name in self._check_defs:
            raise ValueError(f'duplicate check definition "{cdef.name}"')
        self._check_defs[cdef.name] = cdef

    def _register_check_command(self) -> None:
        """Register the auto-generated 'check' command when checks.toml exists."""
        app_ref = self  # capture for closure

        def _check_handler(
            ctx, *, all: bool, tag: str, name: str,
            list: bool, ignore_warnings: bool,
            **_kw,
        ) -> int:
            # --verbose, --dry-run and --json are framework-owned reserved
            # names, so the check command declares none of them and reads their
            # values off the Context instead. The machine output is this
            # command's payload (contract §19.4), which is why --json is not a
            # flag here any more.
            verbose = ctx.verbose
            dry_run = ctx.dry_run
            json = ctx.json
            # Materialize provider-sourced checks before any registry read
            # (covers the list, dry-run, and execution branches below).
            app_ref._materialize_check_providers()
            # Treat empty strings as "not provided"
            tag_expr = tag if tag else None
            name_glob = name if name else None

            if list:
                if json:
                    ctx.payload(_check_list_items(app_ref._check_defs))
                else:
                    _check_list_mode(app_ref._check_defs)
                return 0

            # Determine if any execution filter is active
            has_filter = all or tag_expr is not None or name_glob is not None

            if not has_filter:
                # No flags: show help for the check command
                check_cmd = app_ref._commands["check"]
                prefix = app_ref._find_command_prefix(check_cmd)
                print(_format_command_help(app_ref, check_cmd, prefix))
                return 0

            # Resolve filters and order
            selected = _filter_checks(app_ref._check_defs, tag_expr, name_glob, all)
            if not selected:
                print("No checks matched the given filters.")
                return 0
            order = _resolve_check_order(app_ref._check_defs, selected)

            # Both a full run and a dry run execute checks, so both need a
            # context. --dry-run selects the purity partition instead of a
            # separate list-without-running branch: the checks declared pure
            # really run (that is what makes a rehearsal mean something) and the
            # impure remainder is rendered as the would-run plan.
            if app_ref._check_context_factory is None:
                print(
                    "error: no check context configured. "
                    "Call app.set_check_context(factory) before running.",
                    file=sys.stderr,
                )
                return 1
            context = app_ref._wrap_check_context(app_ref._check_context_factory())
            raw_results, impure_listed, exit_code = _run_checks(
                app_ref._check_defs, order, context, ignore_warnings,
                scope_adapter=app_ref._scope_adapter, pure_only=dry_run,
            )

            results_wrapped = [
                CheckRunResult(name=n, outcome=o, duration_ms=d)
                for n, o, d in raw_results
            ]
            if json:
                ctx.payload(_check_result_items(results_wrapped))
            else:
                output = format_check_results(results_wrapped, verbose)
                if output:
                    print(output)
            if dry_run:
                _check_dry_run_mode(app_ref._check_defs, impure_listed, order)

            return exit_code

        # Filter out extra flags that already exist as global flags to avoid
        # collisions -- the handler receives global flag values automatically.
        global_flag_names = {gf.name for gf in self._global_flags}
        candidate_extra_flags = [
            Flag(name="all", type=bool, default=False, help="Run every registered check regardless of tag or name filters"),
            Flag(name="tag", type=str, default="", help="Tag DSL expression to select checks (e.g. 'changelog & !quality')"),
            Flag(name="name", type=str, default="", help="Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*')"),
            Flag(name="list", type=bool, default=False, help="List all registered checks with their tags and exit without running"),
            Flag(name="ignore-warnings", type=bool, default=False, help="Treat warn-severity results as passing so they do not cause nonzero exit"),
        ]
        extra_flags = [f for f in candidate_extra_flags if f.name not in global_flag_names]
        # read_only: the check command's only writes are framework-blessed
        # CACHE_WRITEs (the coverage manifest), which never trip enforcement.
        self._commands["check"] = self._build_framework_command(
            "check",
            help="Run project checks registered via the check framework and report results",
            effect=EFFECT_READ_ONLY,
            handler=_check_handler,
            extra_flags=extra_flags,
            payload_schema=_CHECK_PAYLOAD_SCHEMA,
        )

    def command(
        self,
        name: str,
        *,
        help: str,
        effect: str | None = None,
        consequential: bool = False,
        dry_run_supported: bool = True,
        dry_run_unsupported_reason: str | None = None,
        payload_schema: dict | None = None,
        args: list[Arg] | None = None,
        flag_sets: list[FlagSet] | None = None,
        mutex: list[MutexGroup] | None = None,
        dependencies: list[CoRequired | Requires | Implies] | None = None,
        passthrough: Passthrough | None = None,
        grants: list[Grant] | None = None,
        forwarding: Forwarding | None = None,
        tags: set[str] | None = None,
        hidden: bool = False,
        interactive: bool = False,
        config_fields: list[str] | None = None,
    ) -> Callable[[F], F]:
        """Decorator to register a top-level command."""

        def decorator(func: F) -> F:
            cmd = _build_and_validate_command(
                name,
                help=help,
                effect=effect,
                consequential=consequential,
                dry_run_supported=dry_run_supported,
                dry_run_unsupported_reason=dry_run_unsupported_reason,
                payload_schema=payload_schema,
                handler=func,
                args=args,
                flag_sets=flag_sets,
                mutex=mutex,
                dependencies=dependencies,
                env_prefix=self.env_prefix,
                global_flags=self._global_flags,
                passthrough=passthrough,
                grants=grants,
                forwarding=forwarding,
                tags=tags,
                inherited_tags=None,
                hidden=hidden,
                interactive=interactive,
                config_fields=config_fields,
                config_fields_ref=self._config_fields,
                infra_root_names=self._infra_root_names,
                connection_env_names=self._connection_env_names,
            )
            self._commands[name] = cmd
            return func

        return decorator

    def group(self, name: str, *, help: str, tags: set[str] | None = None,
              hidden: bool = False) -> Group:
        """Create and register a command group."""
        own_tags = frozenset(tags or set())
        grp = Group(name=name, help=help, env_prefix=self.env_prefix,
                     _global_flags=self._global_flags,
                     tags=own_tags,
                     _accumulated_tags=own_tags,
                     hidden=hidden,
                     _config_fields_ref=self._config_fields,
                     _infra_root_names=self._infra_root_names,
                     _connection_env_names=self._connection_env_names)
        self._groups[name] = grp
        return grp

    def deprecate(self, name: str, *, message: str,
                  effect: str | None = None) -> None:
        """Register a deprecated top-level command.

        Deprecated entries are classification-EXEMPT: they have no handler and
        execute nothing, so passing ``effect=`` is a registration-time error.
        """
        if effect is not None:
            _raise_deprecated_command_effect(name)
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

        for name, grp in self._groups.items():
            if name == "config":
                continue  # skip auto-generated config group
            _collect_from_group(grp)
        return flags

    def _colliding_config_fields(self) -> dict[str, ConfigField]:
        """Return {flag_param_name: ConfigField} for config fields whose name
        equals a flag's param name.

        Such config fields are validation-only: they annotate the colliding
        flag rather than rendering as a separate config key. Callers use this to
        render the key once (on the flag line, with the config field's help as a
        trailing annotation).
        """
        flag_params = {_flag_param_name(f.name) for f in self._collect_all_flags()}
        return {
            name: cf
            for name, cf in self._config_fields.items()
            if name in flag_params
        }

    def _confirm_consequential(self, cmd: "Command", cmd_path: str) -> None:
        """The framework-owned confirm protocol.

        Fires before dispatching a command that DECLARES ITSELF consequential,
        on the real CLI path, when neither --dry-run nor
        --approve-consequential was passed. A plain ``mutating`` command never
        prompts: classification answers "should a dry run record rather than
        execute?", which is a different question from "are these effects worth
        interrupting someone for?". Never fires on the programmatic paths
        (test/call/_invoke/MCP), which have no TTY contract and would hang.

        A consequential PASSTHROUGH is not exempt: the framework knows LESS
        about what is about to happen, not more.
        """
        if not cmd.consequential:
            return
        if self._last_dry_run or self._last_approve_consequential:
            return
        io = self._confirm_io
        if not io.is_interactive():
            print(_msg_confirm_non_interactive(), file=sys.stderr)
            sys.exit(1)
        print(_msg_confirm_prompt(cmd_path), file=sys.stderr, end="", flush=True)
        try:
            answer = io.read_line()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if _strip_confirm_line(answer) not in ("y", "Y"):
            print(_msg_confirm_declined(), file=sys.stderr)
            sys.exit(1)

    def _arm_effects(self, cmd: "Command", cmd_path: str, *,
                     dry_run: bool) -> "_Effects":
        """Arm the effects handle for one dispatch (the runtime seal).

        Called at EVERY ctx-construction site that dispatches a handler, so
        there is no path on which ctx.effects is missing or a carrier escapes
        unpoisoned. The log itself is reset by :meth:`_begin_dispatch`, which
        runs earlier so pre-handler CACHE_WRITEs (coverage shards) land in the
        same dispatch's log.
        """
        return _Effects(
            cmd=cmd,
            cmd_path=cmd_path,
            dry_run=dry_run,
            log=self._effect_log,
            allowlist=self._proc_observe_allowlist,
        )

    def _begin_dispatch(self) -> None:
        """Start a new dispatch: reset the structured effect log."""
        self._effect_log = _EffectLog()

    def _render_dry_log(self, cmd_path: str, out, err, *, aborted: bool) -> None:
        """Write the would-do log for a dry run. No-op outside dry mode.

        Called on every exit path out of a dispatch, so a handler that leaves
        through ``sys.exit`` or an exception still shows the preview it was
        asked for. The log always goes to stdout and is never suppressed by
        ``--quiet``: it is dry mode's primary output.

        ``aborted`` marks a dispatch that did not finish. The log is still
        written -- the recorded effects are owed either way -- and the marker
        that follows it on stderr says the reader cannot assume the list is
        the whole preview. The truncation path (which ends the preview for its
        own pinned reason) renders itself and never comes through here.
        """
        if not self._last_dry_run:
            return
        print(self._effect_log.render(), file=out)
        if aborted:
            print(
                _msg_dry_run_aborted(self._effect_log.next_seq(), cmd_path),
                file=err,
            )

    def _record_cache_write(self, path: str) -> None:
        """Record a framework-blessed CACHE_WRITE.

        The closed list of sites is exactly three: the schema dump, the
        test-coverage shards, and the test-coverage manifest. CACHE_WRITEs have
        no public method, never appear in the would-do log, never trip
        read-only enforcement, and EXECUTE even in dry mode -- which is why
        they always carry ``recorded: false``.
        """
        log = self._effect_log
        log.append(_EffectRecord(
            seq=log.next_cache_seq(),
            kind=CACHE_WRITE,
            verb="cache",
            detail=path,
            recorded=False,
        ))

    def effect_log(self) -> list[dict]:
        """Return the structured effect records of the most recent dispatch.

        Public API (contract §14.3's amendment). It is the envelope's source
        (§19.3), so it is part of the surface consumers may rely on and it is
        in the api-surface catalog rather than excluded from it. The records
        are populated in both modes, so a live run's effects read as readily as
        a dry run's.
        """
        return self._effect_log.to_list()

    def _set_confirm_io(self, io: "_ConfirmIO | None") -> None:
        """Swap the stdin side of the confirm protocol (test-only seam).

        ``None`` restores the real stdin reader. The TypeScript twin is
        ``setConfirmIO`` in ``confirm.ts`` and the Go twin is
        ``App.SetConfirmIO``; all three change WHERE the answer comes from,
        never WHETHER the protocol runs. Private by name because Python has no
        package-private visibility -- this is not public API.
        """
        self._confirm_io = io if io is not None else _REAL_CONFIRM_IO

    def _build_framework_command(
        self,
        name: str,
        *,
        help: str,
        effect: str,
        handler: Callable,
        args: list[Arg] | None = None,
        mutex: list[MutexGroup] | None = None,
        extra_flags: list[Flag] | None = None,
        interactive: bool = False,
        payload_schema: dict | None = None,
    ) -> Command:
        """Build one of strictcli's own auto-registered commands.

        Framework-internal commands (``check`` and the five ``config``
        subcommands) go through the same single validated registration path as
        every consumer command -- there is no direct-``Command``-construction
        bypass left. Their handlers absorb the app's app-defined global flag
        values through ``**kwargs``, which is legal only because they declare
        forwarding, and the private ``_framework_internal`` marker (unreachable
        from any public factory) makes the framework verify that the handler is
        actually defined in this module.
        """
        return _build_and_validate_command(
            name,
            help=help,
            effect=effect,
            handler=handler,
            args=args,
            flag_sets=None,
            mutex=mutex,
            dependencies=None,
            env_prefix=self.env_prefix,
            global_flags=self._global_flags,
            passthrough=None,
            forwarding=Forwarding(reason=_FRAMEWORK_INTERNAL_FORWARDING_REASON),
            framework_internal=True,
            extra_flags=extra_flags,
            interactive=interactive,
            payload_schema=payload_schema,
        )

    def _register_config_group(self) -> None:
        """Register the auto-generated 'config' command group."""
        config_grp = Group(
            name="config",
            help="Manage persistent configuration values stored in the config file",
            env_prefix=self.env_prefix,
            _global_flags=self._global_flags,
        )

        app_ref = self  # capture for closures

        # config path
        def _config_path_handler(ctx, **_kw) -> None:
            print(_config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            ))

        config_grp.commands["path"] = self._build_framework_command(
            "path",
            help="Print the absolute path to this application's config file and nothing else, so the value can be piped straight into another command. The path is $XDG_CONFIG_HOME/<app>/config.<toml|json> (falling back to ~/.config), or the explicit override the application was built with. Printing it does not create the file, and reports the same path whether or not one exists yet.",
            effect=EFFECT_READ_ONLY,
            handler=_config_path_handler,
        )

        # config show
        #
        # Source resolution uses the shared precedence chain: env > config > default.
        # "cli" is structurally impossible here -- config show is a subcommand,
        # so the app's own flags were never passed on the command line.
        def _config_show_handler(ctx, **_kw) -> int:
            # If there was a config parse error, show it instead of values
            if app_ref._config_parse_err:
                print(f"error: {app_ref._config_parse_err}", file=sys.stderr)
                return 1
            # --json is framework-owned (contract §19.1): machine mode is
            # read off the Context and the object below is this command's
            # payload, not a locally-flagged print.
            use_json = ctx.json
            config_data = app_ref._config_data
            all_flags = app_ref._collect_all_flags()
            colliding = app_ref._colliding_config_fields()
            if use_json:
                result = {}
                for f in all_flags:
                    param = _flag_param_name(f.name)
                    value, source = _resolve_flag_show_source(f, config_data)
                    result[param] = {"value": value, "source": source}
                # Include config fields (skip those colliding with a flag: they
                # are validation-only and render once, on the flag entry).
                for cf_name, cf in app_ref._config_fields.items():
                    if cf_name in colliding:
                        continue
                    found, value = _nested_get(config_data, cf_name)
                    if found:
                        source = "config"
                    elif not isinstance(cf.default, _MissingSentinel):
                        value = cf.default
                        source = "default"
                    else:
                        value = None
                        source = "not set"
                    entry: dict = {
                        "value": value,
                        "source": source,
                        "type": cf.type.__name__,
                        "required": cf.required,
                        "help": cf.help,
                    }
                    if not isinstance(cf.default, _MissingSentinel):
                        entry["default"] = cf.default
                    result[cf_name] = entry
                # Infrastructure section (roots + handshakes + connections)
                if app_ref._infra_root_order or app_ref._handshake_order or app_ref._connection_order:
                    infra: dict = {}
                    for ev in app_ref._infra_root_order:
                        infra[ev] = {
                            "kind": "root",
                            "source": "env" if app_ref._infra_root_from_env[ev] else "default",
                            "resolved": app_ref._infra_roots[ev],
                        }
                    for ev in app_ref._handshake_order:
                        is_set = ev in os.environ
                        hs_entry: dict = {
                            "kind": "handshake",
                            "set": is_set,
                            "help": app_ref._handshake_envs[ev],
                        }
                        if is_set:
                            hs_entry["value"] = os.environ[ev]
                        infra[ev] = hs_entry
                    for ev in app_ref._connection_order:
                        is_set = ev in os.environ
                        conn_entry: dict = {
                            "kind": "connection",
                            "set": is_set,
                            "help": app_ref._connection_envs[ev],
                        }
                        if is_set:
                            conn_entry["value"] = os.environ[ev]
                        infra[ev] = conn_entry
                    result["__infrastructure__"] = infra
                # Sorted keys at every level: the three implementations build
                # this object in three orders (Go marshals a map, which sorts
                # recursively), and the payload is compared byte-for-byte by
                # conformance.
                ctx.payload(_deep_sorted(result))
                return 0
            # --plain
            for f in all_flags:
                param = _flag_param_name(f.name)
                value, source = _resolve_flag_show_source(f, config_data)
                line = f"{param} = {_format_config_value(value)}  (source: {source})"
                # A colliding config field annotates the flag line (rendered once).
                cf_collide = colliding.get(param)
                if cf_collide is not None:
                    line += f"  -- {cf_collide.help}"
                print(line)
            # Include config fields in plain output (skip colliding ones: they
            # are rendered as an annotation on the flag line above).
            non_colliding_fields = {
                n: cf for n, cf in app_ref._config_fields.items()
                if n not in colliding
            }
            if non_colliding_fields:
                print()
                print("Config fields:")
                for cf_name, cf in non_colliding_fields.items():
                    found, value = _nested_get(config_data, cf_name)
                    if found:
                        source = "config"
                    elif not isinstance(cf.default, _MissingSentinel):
                        value = cf.default
                        source = "default"
                    else:
                        value = None
                        source = "not set"
                    req_str = "required" if cf.required else "optional"
                    print(
                        f"  {cf_name} ({cf.type.__name__}, {req_str})"
                        f" = {_format_config_value(value)}"
                        f"  (source: {source})"
                        f"  -- {cf.help}"
                    )
            # Infrastructure section (roots + handshakes + connections)
            if app_ref._infra_root_order or app_ref._handshake_order or app_ref._connection_order:
                print()
                print("Infrastructure:")
                for ev in app_ref._infra_root_order:
                    src = "env-set" if app_ref._infra_root_from_env[ev] else "default"
                    print(f"  {ev} (root) = {app_ref._infra_roots[ev]}  (source: {src})")
                for ev in app_ref._handshake_order:
                    if ev in os.environ:
                        print(f"  {ev} (handshake) = {os.environ[ev]}  (set)  -- {app_ref._handshake_envs[ev]}")
                    else:
                        print(f"  {ev} (handshake) = <unset>  -- {app_ref._handshake_envs[ev]}")
                for ev in app_ref._connection_order:
                    if ev in os.environ:
                        print(f"  {ev} (connection) = {os.environ[ev]}  (set)  -- {app_ref._connection_envs[ev]}")
                    else:
                        print(f"  {ev} (connection) = <unset>  -- {app_ref._connection_envs[ev]}")
            return 0

        # --plain is the only local flag left: the machine form moved to the
        # framework-owned --json (contract §19.1), which cannot be declared
        # here, so the two-flag mutex group went with it.
        config_show_flags = [
            Flag(name="plain", type=bool, default=False, help="Display config values in a human-readable table format"),
        ]
        config_grp.commands["show"] = self._build_framework_command(
            "show",
            help="Show every flag and config field with its effective value and where that value came from, resolved through the precedence chain environment variable, then config file, then declared default. Declared infrastructure roots, handshake and connection environment variables are listed too. Choose --plain for an aligned human-readable table; the framework-owned --json yields the same information as a machine-readable object carrying each entry's type, default and help text.",
            effect=EFFECT_READ_ONLY,
            handler=_config_show_handler,
            extra_flags=config_show_flags,
            payload_schema=_CONFIG_SHOW_PAYLOAD_SCHEMA,
        )

        # config set
        def _config_set_handler(ctx, key, value=None, **_kw) -> int:
            path = _config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )
            # Every mutation this handler performs rides ctx.effects: the
            # command is classified `mutating`, so a dry run must RECORD them
            # and change nothing.
            effects = ctx.effects
            _ensure_config_dir(effects, path)
            # Read existing config (use already-loaded data from parse time)
            existing = app_ref._config_data

            # Look up the key against registered flags and config fields
            all_flags = app_ref._collect_all_flags()
            matched_flag = None
            matched_config_field = None
            for f in all_flags:
                if _flag_param_name(f.name) == key:
                    matched_flag = f
                    break
            if matched_flag is None:
                # Check config fields
                if key in app_ref._config_fields:
                    matched_config_field = app_ref._config_fields[key]
            if matched_flag is None and matched_config_field is None:
                print(f"config set: unknown key '{key}'", file=sys.stderr)
                return 1

            # Config field path: simpler handling (no repeatable, no mutex)
            if matched_config_field is not None:
                return _config_set_field(
                    effects, key, value, matched_config_field, existing, path,
                    app_ref.config_format, _kw,
                )

            use_clear = _kw.get("clear", False)
            use_default = _kw.get("default", False)

            # Validate: exactly one of (value, --clear, --default)
            has_value = value is not None
            if use_clear and use_default:
                print("config set: --clear and --default are mutually exclusive",
                      file=sys.stderr)
                return 1
            if has_value and use_clear:
                print("config set: cannot provide a value with --clear",
                      file=sys.stderr)
                return 1
            if has_value and use_default:
                print("config set: cannot provide a value with --default",
                      file=sys.stderr)
                return 1
            if not has_value and not use_clear and not use_default:
                print("config set: provide a value, --clear, or --default",
                      file=sys.stderr)
                return 1

            # --clear: repeatable/dict flags only
            if use_clear:
                if matched_flag.compound == "dict":
                    cleared: object = {}
                elif matched_flag.repeatable:
                    cleared = []
                else:
                    print("config set: --clear is only for repeatable flags",
                          file=sys.stderr)
                    return 1
                _write_config_set(effects, existing, path, app_ref.config_format, key, cleared)
                return 0

            # --default: remove the key from config
            if use_default:
                if not _write_config_unset(effects, existing, path, app_ref.config_format, key):
                    print(f"config set: key '{key}' not in config",
                          file=sys.stderr)
                    return 1
                return 0

            # Coerce the string value to the flag's type
            if matched_flag.compound == "dict":
                # Dict flags: parse as JSON
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError as e:
                    print(f"config set: key '{key}': invalid JSON: {e}",
                          file=sys.stderr)
                    return 1
                if not isinstance(parsed, dict):
                    print(f"config set: key '{key}': expected JSON object",
                          file=sys.stderr)
                    return 1
                typed_value = {}
                for dk, dv in parsed.items():
                    try:
                        typed_value[dk] = _coerce_config_scalar(
                            dv, matched_flag.value_type,
                        )
                    except ValueError as e:
                        print(
                            f"config set: key '{key}': value for '{dk}': {e}",
                            file=sys.stderr,
                        )
                        return 1
            elif matched_flag.repeatable:
                # Split on comma, coerce each element
                parts = _split_escaped(value, ",")
                try:
                    if matched_flag.type == int:
                        typed_value = [_strict_int(p) for p in parts]
                    elif matched_flag.type == float:
                        coerced = []
                        for p in parts:
                            try:
                                coerced.append(_strict_float(p))
                            except ValueError as fe:
                                msg = str(fe)
                                if msg in ("NaN is not allowed",
                                           "Inf is not allowed"):
                                    raise
                                raise ValueError(
                                    f"expected float, got '{p}'"
                                ) from fe
                        typed_value = coerced
                    else:  # str
                        typed_value = parts
                except ValueError as e:
                    print(f"config set: key '{key}': {e}", file=sys.stderr)
                    return 1
                # Unique enforcement
                if matched_flag.unique:
                    dup = _find_duplicate(typed_value)
                    if dup is not None:
                        print(
                            f"config set: key '{key}': duplicate value "
                            f"'{_format_value_for_error(dup)}'",
                            file=sys.stderr,
                        )
                        return 1
            else:
                try:
                    if matched_flag.type == bool:
                        typed_value = _strict_bool(value)
                    elif matched_flag.type == int:
                        typed_value = _strict_int(value)
                    elif matched_flag.type == float:
                        try:
                            typed_value = _strict_float(value)
                        except ValueError as fe:
                            msg = str(fe)
                            if msg in ("NaN is not allowed",
                                       "Inf is not allowed"):
                                raise
                            raise ValueError(
                                f"expected float, got '{value}'"
                            ) from fe
                    else:  # str
                        typed_value = value
                except ValueError as e:
                    print(f"config set: key '{key}': {e}", file=sys.stderr)
                    return 1

            _write_config_set(effects, existing, path, app_ref.config_format, key, typed_value)
            return 0

        config_grp.commands["set"] = self._build_framework_command(
            "set",
            help="Write a persistent value into the config file so it overrides a flag's declared default on every later run. The value is coerced to the flag's own type and rejected if it does not fit: repeatable flags take a comma-separated list (backslash-escape a literal comma) and are checked for duplicates, dict flags take a JSON object. Use --default to drop a key back to its default, and --clear to empty a repeatable flag.",
            effect=EFFECT_MUTATING,
            handler=_config_set_handler,
            args=[
                Arg(name="key", help="The config key to set, matching a registered flag name"),
                Arg(name="value",
                    help="Value to set (comma-separated for repeatable flags, use backslash to escape commas)",
                    required=False),
            ],
            extra_flags=[
                Flag(name="clear", type=bool, default=False,
                     help="Clear a repeatable flag by setting its value to an empty list"),
                Flag(name="default", type=bool, default=False,
                     help="Reset a key to its default value by removing it from the config file"),
            ],
        )

        # config edit
        def _config_edit_handler(ctx, **_kw) -> int:
            path = _config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )
            effects = ctx.effects
            _ensure_config_dir(effects, path)
            if not os.path.isfile(path):
                effects.write(path, "" if app_ref.config_format == "toml" else "{}\n")
            editor = os.environ.get("EDITOR", "vi")
            # LAUNCHING AN EDITOR IS A MUTATION. Routed through the handle, a
            # dry run records `run: <editor> <path>` and never opens anything;
            # a bare subprocess.run here would open the user's editor during a
            # run that announced it would change nothing.
            #
            # check=True (the default) is what keeps the preview walking: a
            # failed operation is an error, not a value (§2.5.4), so nothing
            # here ever reads an exit code off a carrier.
            try:
                effects.run([editor, path], stream=True)
            except (OSError, EffectFailed) as e:
                print(f"error: editor failed: {e}", file=sys.stderr)
                return 1
            return 0

        config_grp.commands["edit"] = self._build_framework_command(
            "edit",
            help="Open this application's config file in the editor named by $EDITOR, falling back to vi. The parent directory and an empty config file are created first if they do not exist, so the editor always opens something. Launching the editor counts as a mutation: under --dry-run the command records the editor invocation and opens nothing.",
            effect=EFFECT_MUTATING,
            handler=_config_edit_handler,
            interactive=True,
        )

        # config init
        def _config_init_handler(ctx, **_kw) -> int:
            cfg_path = _config_path(
                app_ref.name,
                override=app_ref.config_path,
                config_format=app_ref.config_format,
            )
            if os.path.isfile(cfg_path):
                print(
                    f"config init: config file already exists: {cfg_path}",
                    file=sys.stderr,
                )
                return 1
            effects = ctx.effects
            _ensure_config_dir(effects, cfg_path)
            if app_ref.config_format == "toml":
                content = _generate_config_template_toml(
                    app_ref._collect_all_flags(),
                    app_ref._config_fields,
                )
            else:
                content = _generate_config_template_json(
                    app_ref._collect_all_flags(),
                    app_ref._config_fields,
                )
            effects.write(cfg_path, content)
            print(cfg_path)
            return 0

        config_grp.commands["init"] = self._build_framework_command(
            "init",
            help="Create a starter config file listing every flag and config field the application declares, each commented with its help text, type and default value, so the file documents itself. The format follows whichever of TOML or JSON the application was built for. Refuses with an error if a config file already exists rather than overwriting it; the created path is printed on success.",
            effect=EFFECT_MUTATING,
            handler=_config_init_handler,
        )

        self._groups["config"] = config_grp

    def _pre_scan_reserved_flags(self, argv: list[str]) -> dict:
        """Pre-scan for the framework-owned reserved flags.

        Handles --dump-schema, --mcp, --config, --hermetic and the effects-regime
        quartet --dry-run/--approve-consequential/--quiet/--verbose.

        Two regions, two rulesets (contract §7.2, amended):

        - The **pre-command region** (before the first non-flag token, before
          ``--``) recognizes every reserved flag. Known global flags and their
          values are skipped so that a global-flag value matching a command name
          does not terminate the region early.
        - The **command region** recognizes ONLY the quartet, anywhere, exactly
          like --help/-h. --hermetic/--config/--dump-schema/--mcp stay
          pre-command-only. See _scan_command_region_quartet.

        Returns a dict with keys: dump_schema, serve_mcp, hermetic, config_path,
        dry_run, approve_consequential, quiet, verbose, err, cleaned_argv.
        """
        # Build a set of known global flag tokens with value-taking info
        known_flags: dict[str, bool] = {}  # token -> takes_value
        for f in self._global_flags:
            known_flags[f"--{f.name}"] = f.type is not bool
            if f.short:
                known_flags[f"-{f.short}"] = f.type is not bool
            if f.type is bool and f.negatable:
                known_flags[f"--no-{f.name}"] = False

        result: dict = {}
        exclude_indices: set[int] = set()
        # Index where the command region begins; -1 means "never reached one"
        # (a bare -- or an unknown flag-like token ended the scan for good).
        command_region_from = -1
        i = 0
        while i < len(argv):
            tok = argv[i]

            # -- terminates the whole scan: everything after it is data
            if tok == "--":
                break

            # Non-flag token = the command token: the command region starts here
            if not tok.startswith("-") or tok == "-":
                command_region_from = i
                break

            # --dump-schema
            if tok == "--dump-schema":
                result["dump_schema"] = True
                return result

            # --mcp
            if tok == "--mcp":
                result["serve_mcp"] = True
                return result

            # --hermetic (boolean, no value)
            if tok == "--hermetic":
                result["hermetic"] = True
                exclude_indices.add(i)
                i += 1
                continue

            # The reserved quartet plus --json: booleans, no values, stripped
            # from argv and delivered on the Context (never as handler kwargs).
            if tok in _RESERVED_PRESCAN_TOKENS:
                result[_RESERVED_PRESCAN_TOKENS[tok]] = True
                exclude_indices.add(i)
                i += 1
                continue

            # --config=<value>
            if tok.startswith("--config="):
                if not self.config:
                    result["err"] = (
                        "--config is not available: this app does not use config files"
                    )
                    return result
                val = tok[len("--config="):]
                if not val:
                    result["err"] = "flag '--config' requires a value"
                    return result
                result["config_path"] = val
                exclude_indices.add(i)
                i += 1
                continue

            # --config <value>
            if tok == "--config":
                if not self.config:
                    result["err"] = (
                        "--config is not available: this app does not use config files"
                    )
                    return result
                if i + 1 >= len(argv):
                    result["err"] = "flag '--config' requires a value"
                    return result
                result["config_path"] = argv[i + 1]
                exclude_indices.add(i)
                exclude_indices.add(i + 1)
                i += 2
                continue

            # Known global flag with --flag=value form: skip
            if tok.startswith("--") and "=" in tok:
                eq_pos = tok.index("=")
                flag_part = tok[:eq_pos]
                if flag_part in known_flags:
                    i += 1
                    continue
                # Unknown flag-like token: stop
                break

            # Known global flag: skip it (and its value if non-bool)
            if tok in known_flags:
                if known_flags[tok]:
                    i += 2
                else:
                    i += 1
                continue

            # Unknown flag-like token: stop
            break

        if command_region_from >= 0:
            self._scan_command_region_quartet(
                argv, command_region_from, result, exclude_indices,
            )

        if exclude_indices:
            result["cleaned_argv"] = [
                tok for j, tok in enumerate(argv) if j not in exclude_indices
            ]
        else:
            result["cleaned_argv"] = argv

        return result

    def _scan_command_region_quartet(
        self,
        argv: list[str],
        start: int,
        result: dict,
        exclude_indices: set[int],
    ) -> None:
        """Recognize the reserved quartet in the command region of argv.

        Contract §7.2 (amended 2026-08-04): the quartet's four tokens are
        recognized ANYWHERE in argv, exactly like --help/-h, because their
        applicability is per-command -- requiring them before the command name
        was backwards. Only the quartet is recognized here; --hermetic,
        --config, --dump-schema and --mcp remain pre-command-only.

        The scan stops for good at two boundaries:

        - a bare ``--``, after which every token is positional data;
        - a **passthrough** command's name, after which every token belongs to
          the child process and is forwarded byte-for-byte. Eating a child's own
          --verbose would silently change what the child does.

        Routing tokens are walked through the group/command tree so a quartet
        token may sit anywhere among them. Nothing here raises: routing errors
        are the real parse's job.

        Both boundaries are visible in the ``dry_run_supported=False`` refusal,
        which reads the flag this scan resolved. ``app cmd -- --dry-run`` and
        ``app passthrough --dry-run`` are NOT refused, because in neither case
        did the operator ask this app for a dry run: after ``--`` the token is
        the command's own data, and after a passthrough's name it is the child
        process's flag. ``app --dry-run passthrough`` IS refused -- there the
        token is unambiguously addressed to this app.
        """
        groups = self._groups
        commands = self._commands
        routing_done = False
        i = start
        while i < len(argv):
            tok = argv[i]

            if tok == "--":
                return

            if tok.startswith("-") and tok != "-":
                if tok in _RESERVED_PRESCAN_TOKENS:
                    result[_RESERVED_PRESCAN_TOKENS[tok]] = True
                    exclude_indices.add(i)
                i += 1
                continue

            # A non-flag token: a routing token until routing resolves.
            if not routing_done:
                grp = groups.get(tok)
                if grp is not None:
                    groups = grp._groups
                    commands = grp.commands
                    i += 1
                    continue
                cmd = commands.get(tok)
                if cmd is not None and cmd.passthrough is not None:
                    return
                # Resolved a normal command, or hit an unknown/deprecated token
                # the real parse will report: routing is over either way.
                routing_done = True

            i += 1

    def _parse(self, argv: list[str]) -> tuple[Command, dict[str, object] | list[str], dict[str, str]]:
        """Parse argv (without program name) into a resolved Command and kwargs.

        For normal commands, returns (Command, kwargs_dict, sources).
        For passthrough commands, returns (Command, raw_args_list, {}).
        Callers disambiguate by checking cmd.passthrough.

        After parsing, self._last_global_values holds the parsed global flag
        values (used by passthrough command handlers).
        """

        # Step 1: intercept app-level --help/-h, --version/-v
        if not argv or argv == ["--help"] or argv == ["-h"]:
            raise _HelpRequested(target=self)
        if argv == ["--version"] or argv == ["-v"]:
            raise _VersionRequested()

        # Position-aware pre-scan: intercept --dump-schema, --mcp, --config, --hermetic
        # in the pre-command region only (before command name, before --).
        pre_scan = self._pre_scan_reserved_flags(argv)

        # Record the reserved quartet -- and --json beside it -- for the
        # dispatch ctx. This runs BEFORE the pre-scan's own exits so every
        # parse error from here on knows whether the run is in machine mode
        # and can emit the envelope the mode owes it (§19.2).
        self._last_dry_run = bool(pre_scan.get("dry_run"))
        self._last_approve_consequential = bool(
            pre_scan.get("approve_consequential")
        )
        self._last_quiet = bool(pre_scan.get("quiet"))
        self._last_json = bool(pre_scan.get("json"))
        self._last_verbose = bool(pre_scan.get("verbose"))

        if pre_scan.get("dump_schema"):
            raise _DumpSchemaRequested()
        if pre_scan.get("serve_mcp"):
            raise _McpRequested()
        if pre_scan.get("err"):
            raise _ParseError(pre_scan["err"])

        is_hermetic = bool(pre_scan.get("hermetic"))
        # Record for the dispatch ctx: connection env access is suppressed under
        # --hermetic so connection-dependent behavior (incl. checks) skips.
        self._last_hermetic = is_hermetic

        # --hermetic + --config mutual exclusion
        if is_hermetic and pre_scan.get("config_path"):
            raise _ParseError("--hermetic and --config are mutually exclusive")

        # Load config data once at parse time.
        # When hermetic is active, skip config loading entirely (even XDG defaults).
        # Capture any parse error to handle config subcommand exemption later.
        config_load_err: str | None = None
        if self.config and not is_hermetic:
            runtime_override = pre_scan.get("config_path")
            hermetic = self.no_default_config_path and not runtime_override
            is_runtime_flag = bool(runtime_override)
            result = self._resolve_config_data(
                runtime_path_override=runtime_override,
                hermetic=hermetic,
                is_runtime_flag=is_runtime_flag,
            )
            if result.parse_err:
                config_load_err = result.parse_err
                self._config_data = {}
            else:
                self._config_data = result.data
        elif is_hermetic:
            # Hermetic mode: no config data at all
            self._config_data = None

        # Step 1.5: parse global flags before command routing
        # Use cleaned argv (--config/--hermetic stripped) for the rest of the pipeline
        cleaned_argv = pre_scan.get("cleaned_argv", argv)
        self._stdin_consumed_by: str | None = None
        global_values, global_source_map, remaining = self._parse_global_flags(
            cleaned_argv, hermetic=is_hermetic,
        )
        self._last_global_values = global_values

        # Step 2: route to command or group (iterative traversal for arbitrary depth)
        # If global flag parsing stopped at --, strip it before routing
        if remaining and remaining[0] == "--":
            remaining = remaining[1:]

        if not remaining or remaining == ["--help"] or remaining == ["-h"]:
            raise _HelpRequested(target=self)

        cmd, rest, path = self._resolve_command(remaining)
        self._last_resolved_path = path

        # Check for command-level --help/-h anywhere in remaining tokens
        # (but not after "--" separator, which makes everything literal)
        if _tokens_contain_help(rest):
            raise _HelpRequested(target=cmd)

        # A command that declares dry_run_supported=False refuses --dry-run
        # here, on every argv path (run/test/harness) at once, and AFTER the
        # command-help check above so `--help` always beats the refusal: asking
        # what a command does must never be answered with a refusal to preview
        # it. self._last_dry_run was set by the pre-scan, so this covers both
        # `app --dry-run cmd` and `app cmd --dry-run`; see
        # _scan_command_region_quartet for the two boundaries that make a
        # trailing --dry-run invisible here (a bare `--`, and a passthrough
        # command's name).
        if self._last_dry_run and not cmd.dry_run_supported:
            refused_path = ".".join(path + [cmd.name])
            raise _ParseError(
                f"--dry-run is not supported by command '{refused_path}': "
                f"{cmd.dry_run_unsupported_reason}"
            )

        # Config subcommand exemption: config edit, config path, config set
        # are exempt from config load errors (self-lock prevention).
        # config show handles the error specially (shows it as output).
        is_config_subcommand = bool(path) and path[0] == "config"

        # --hermetic + config subcommand = hard error
        if is_hermetic and is_config_subcommand:
            raise _ParseError("--hermetic cannot be used with config commands")

        if config_load_err:
            if not is_config_subcommand:
                raise _ParseError(config_load_err)
            # Store for config show to pick up
            self._config_parse_err = config_load_err

        # Step 2.5: validate config fields (exempt config subcommands)
        if (self.config and self._config_fields
                and not is_config_subcommand):
            err = self._validate_config_fields(cmd, self._config_data)
            if err:
                raise _ParseError(err)

        # Passthrough commands: skip all flag/arg parsing, forward raw args
        if cmd.passthrough is not None:
            return cmd, rest, {}

        # Step 3: parse remaining tokens for the resolved command
        # Pass stdin_consumed_by as a mutable single-element list so
        # _parse_command can update the shared state.
        stdin_state: list[str | None] = [self._stdin_consumed_by]
        try:
            cmd, kwargs, post_global, sources = _parse_command(
                cmd, rest, self._global_flags, config_data=self._config_data,
                stdin_consumed_by=stdin_state,
                conflict_mode=self.config_conflict_mode,
                hermetic=is_hermetic,
                infra_roots=self._infra_roots,
            )
        except _ParseError as e:
            prefix_parts = [self.name] + path + [cmd.name]
            e.command_prefix = " ".join(prefix_parts)
            raise

        # Step 4: merge global flag values into kwargs
        # Post-command global flags override pre-command ones
        for gf in self._global_flags:
            if gf.name in post_global:
                global_values[gf.name] = post_global[gf.name]
            kwargs[_flag_param_name(gf.name)] = global_values[gf.name]

        # Merge global sources into command sources. This mirrors the VALUE
        # merge above: for a global set post-command, _parse_command already
        # placed the correct (cli) source into `sources`, so the pre-command
        # source label (typically "default") must NOT overwrite it.
        post_global_params = {_flag_param_name(n) for n in post_global}
        for k, v in global_source_map.items():
            if k in post_global_params:
                continue  # post-command position wins
            sources[k] = v

        return cmd, kwargs, sources

    def _resolve_command(
        self, path_segments: list[str]
    ) -> tuple[Command, list[str], list[str]]:
        """Traverse groups/commands tree to resolve a command from path segments.

        Takes the remaining argv tokens after global flag parsing (group names,
        command name, and command arguments).  Consumes group and command tokens
        from the front, returning the resolved Command, the unconsumed tokens
        (command arguments), and the list of group names traversed.

        Raises _HelpRequested for group-level help and _ParseError for
        deprecated or unknown commands.
        """
        current_groups = self._groups
        current_commands = self._commands
        current_deprecated = self._deprecated
        path: list[str] = []  # tracks group names for error messages and help prefix

        while path_segments:
            token = path_segments[0]

            if token in current_groups:
                group = current_groups[token]
                path.append(token)
                path_segments = path_segments[1:]

                if not path_segments or path_segments[0] in ("--help", "-h"):
                    raise _HelpRequested(target=group)

                # Descend into group
                current_groups = group._groups
                current_commands = group.commands
                current_deprecated = group.deprecated
                continue

            if token in current_commands:
                cmd = current_commands[token]
                rest = path_segments[1:]
                return cmd, rest, path

            if token in current_deprecated:
                dep = current_deprecated[token]
                raise _ParseError(
                    f"command '{token}' is deprecated: {dep.message}"
                )

            # Unknown command -- include path in error message
            if path:
                raise _ParseError(
                    f"unknown command '{token}' in '{' '.join(path)}'",
                    command_prefix=f"{self.name} {' '.join(path)}",
                )
            raise _ParseError(f"unknown command '{token}'")

        # Loop ended without finding a command -- path_segments was exhausted
        # by group traversal. This means the last group had no subcommand.
        # (Already handled by the help check inside the loop, but guard
        # against edge cases.)
        raise _HelpRequested(target=group)  # noqa: F821 -- 'group' always set when loop body ran

    def _parse_global_flags(
        self, argv: list[str], *, hermetic: bool = False,
    ) -> tuple[dict[str, object], dict[str, str], list[str]]:
        """Parse global flags from argv, returning (global_values, global_sources, remaining_tokens).

        Scans tokens from left to right. Global flags are consumed; the first
        non-global-flag token (the command name) and everything after it are
        returned as remaining tokens. A bare ``--`` stops global flag parsing
        and is included in the remaining tokens.

        When hermetic is True, env var and config resolution are skipped entirely.
        """
        if not self._global_flags:
            return {}, {}, argv

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
            if f.compound == "dict":
                if f.name not in cli_set:
                    cli_set[f.name] = {}
                # value is a (key, val) tuple from _parse_dict_value
                k, v = value
                if k in cli_set[f.name]:
                    raise _ParseError(
                        f"--{f.name}: duplicate key '{k}'"
                    )
                cli_set[f.name][k] = v
            elif f.repeatable:
                if f.name not in cli_set:
                    cli_set[f.name] = []
                if f.unique and value in cli_set[f.name]:
                    raise _ParseError(
                        f"--{f.name}: duplicate value "
                        f"'{_format_value_for_error(value)}'"
                    )
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
                    if f.type is bool and f.compound != "dict":
                        raise _ParseError(
                            f"flag '{flag_part}' is a boolean flag and does not take a value"
                        )
                    if f.compound == "dict":
                        _store_dict_flag(f, value_part, cli_set)
                    elif f.type is int:
                        try:
                            _store_value(f, _strict_int(value_part))
                        except ValueError as e:
                            raise _ParseError(f"--{f.name}: {e}")
                    elif f.type is float:
                        try:
                            _store_value(f, _strict_float(value_part))
                        except ValueError as e:
                            raise _float_parse_error(f.name, value_part, e)
                    else:
                        resolved, self._stdin_consumed_by = _resolve_at_prefix(
                            f.name, value_part, self._stdin_consumed_by,
                        )
                        _store_value(f, resolved)
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
                if f.type is bool and f.compound != "dict":
                    cli_set[f.name] = True
                    i += 1
                else:
                    if i + 1 < len(argv):
                        raw = argv[i + 1]
                        if f.compound == "dict":
                            _store_dict_flag(f, raw, cli_set)
                        elif f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError as e:
                                raise _ParseError(f"--{f.name}: {e}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
                        else:
                            resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                f.name, raw, self._stdin_consumed_by,
                            )
                            _store_value(f, resolved)
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
                continue

            # -x (short form)
            if tok.startswith("-") and len(tok) == 2 and tok in short_lookup:
                f = short_lookup[tok]
                if f.type is bool and f.compound != "dict":
                    cli_set[f.name] = True
                    i += 1
                else:
                    if i + 1 < len(argv):
                        raw = argv[i + 1]
                        if f.compound == "dict":
                            _store_dict_flag(f, raw, cli_set)
                        elif f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError as e:
                                raise _ParseError(f"--{f.name}: {e}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
                        else:
                            resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                f.name, raw, self._stdin_consumed_by,
                            )
                            _store_value(f, resolved)
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

        # Track sources for global flags. Values already in cli_set are CLI.
        global_sources: dict[str, str] = {}
        for k in cli_set:
            global_sources[_flag_param_name(k)] = "cli"
        env_names: set[str] = set()
        config_names: set[str] = set()

        # Resolve env vars for global flags not set by CLI (skipped under --hermetic)
        for f in self._global_flags:
            if hermetic:
                break
            if f.name in cli_set:
                continue
            if f.env is not None:
                env_val = os.environ.get(f.env)
                if env_val is not None:
                    if f.compound == "dict":
                        # Dict flags parse env vars as JSON
                        try:
                            parsed = json.loads(env_val)
                        except json.JSONDecodeError as e:
                            raise _ParseError(
                                f"--{f.name}: invalid JSON in env var "
                                f"'{f.env}': {e}"
                            )
                        if not isinstance(parsed, dict):
                            raise _ParseError(
                                f"--{f.name}: env var '{f.env}' must be a "
                                f"JSON object, got {type(parsed).__name__}"
                            )
                        result = {}
                        for k, v in parsed.items():
                            result[k] = _coerce_dict_json_value(
                                f.name, k, v, f.value_type,
                            )
                        cli_set[f.name] = result
                    elif f.type is bool:
                        try:
                            cli_set[f.name] = _strict_bool(env_val)
                        except ValueError:
                            raise _ParseError(
                                f"invalid boolean value {env_val!r} for env var "
                                f"'{f.env}' (flag '--{f.name}')"
                            )
                    elif f.type is int:
                        if f.repeatable and f.env_separator is not None:
                            parts = _split_escaped(env_val, f.env_separator)
                            coerced_list = []
                            for element in parts:
                                try:
                                    coerced_list.append(_strict_int(element))
                                except ValueError as e:
                                    raise _ParseError(
                                        f"--{f.name}: {e} (from env var '{f.env}')"
                                    )
                            if f.unique:
                                dup = _find_duplicate(coerced_list)
                                if dup is not None:
                                    raise _ParseError(
                                        f"--{f.name}: duplicate value "
                                        f"'{_format_value_for_error(dup)}' "
                                        f"(from env var '{f.env}')"
                                    )
                            cli_set[f.name] = coerced_list
                        else:
                            try:
                                coerced = _strict_int(env_val)
                            except ValueError as e:
                                raise _ParseError(
                                    f"--{f.name}: {e} (from env var '{f.env}')"
                                )
                            cli_set[f.name] = [coerced] if f.repeatable else coerced
                    elif f.type is float:
                        if f.repeatable and f.env_separator is not None:
                            parts = _split_escaped(env_val, f.env_separator)
                            coerced_list = []
                            for element in parts:
                                try:
                                    coerced_list.append(_strict_float(element))
                                except ValueError as e:
                                    raise _float_parse_error(
                                        f.name, element, e, env=f.env,
                                    )
                            if f.unique:
                                dup = _find_duplicate(coerced_list)
                                if dup is not None:
                                    raise _ParseError(
                                        f"--{f.name}: duplicate value "
                                        f"'{_format_value_for_error(dup)}' "
                                        f"(from env var '{f.env}')"
                                    )
                            cli_set[f.name] = coerced_list
                        else:
                            try:
                                coerced = _strict_float(env_val)
                            except ValueError as e:
                                raise _float_parse_error(f.name, env_val, e, env=f.env)
                            cli_set[f.name] = [coerced] if f.repeatable else coerced
                    else:
                        if f.repeatable and f.env_separator is not None:
                            parts = _split_escaped(env_val, f.env_separator)
                            coerced_list = []
                            for element in parts:
                                resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                    f.name, element, self._stdin_consumed_by,
                                )
                                coerced_list.append(resolved)
                            if f.unique:
                                dup = _find_duplicate(coerced_list)
                                if dup is not None:
                                    raise _ParseError(
                                        f"--{f.name}: duplicate value "
                                        f"'{_format_value_for_error(dup)}' "
                                        f"(from env var '{f.env}')"
                                    )
                            cli_set[f.name] = coerced_list
                        else:
                            resolved, self._stdin_consumed_by = _resolve_at_prefix(
                                f.name, env_val, self._stdin_consumed_by,
                            )
                            cli_set[f.name] = [resolved] if f.repeatable else resolved
                    env_names.add(f.name)

        # Resolve config values for global flags not set by CLI or env.
        # In conflict mode "error", detect config+cli/env overlaps.
        # (Skipped under --hermetic since config is not loaded.)
        if self._config_data and not hermetic:
            for f in self._global_flags:
                param = _flag_param_name(f.name)
                if param not in self._config_data:
                    continue
                # Effective mode: per-flag override if set, else the app default.
                effective_mode = (
                    f.conflict_mode
                    if not isinstance(f.conflict_mode, _MissingSentinel)
                    else self.config_conflict_mode
                )
                if f.name in cli_set:
                    # Conflict ONLY when config diverges from the CLI/env value.
                    if effective_mode == "error":
                        try:
                            coerced = _coerce_config_value(self._config_data[param], f)
                        except ValueError as e:
                            raise _ParseError(
                                f"--{f.name}: config value error: {e}"
                            )
                        if not _values_equal_for_conflict(cli_set[f.name], coerced, f):
                            existing_source = global_sources.get(param, "cli")
                            raise _ParseError(
                                f"flag '{f.name}' set in both "
                                f"{existing_source} and config; remove one"
                            )
                    continue  # cli-wins, or error mode with matching values
                try:
                    coerced = _coerce_config_value(self._config_data[param], f)
                except ValueError as e:
                    raise _ParseError(
                        f"--{f.name}: config value error: {e}"
                    )
                if f.unique and isinstance(coerced, list):
                    dup = _find_duplicate(coerced)
                    if dup is not None:
                        raise _ParseError(
                            f"--{f.name}: config value error: "
                            f"duplicate value "
                            f"'{_format_value_for_error(dup)}'"
                        )
                cli_set[f.name] = coerced
                config_names.add(f.name)

        # Assign sources for env and config values
        for name in env_names:
            global_sources[_flag_param_name(name)] = "env"
        for name in config_names:
            global_sources[_flag_param_name(name)] = "config"

        # Apply defaults for global flags not set by CLI or env
        for f in self._global_flags:
            if f.name in cli_set:
                continue
            src_label = "default"
            if f.repeatable:
                cli_set[f.name] = list(f.default) if f.default else []
            elif isinstance(f.default, RelativeToRoot):
                cli_set[f.name] = _resolve_infra_root_path(f.default, self._infra_roots)
                src_label = "infra"
            elif f.default is not None:
                cli_set[f.name] = f.default
            else:
                if f.type is bool and f.negatable:
                    raise _ParseError(
                        f"global flag '--{f.name}' must be passed as "
                        f"--{f.name} or --no-{f.name}"
                    )
                if f.type is bool and not f.negatable:
                    raise _ParseError(
                        f"global flag '--{f.name}' must be passed as "
                        f"--{f.name}"
                    )
                raise _ParseError(f"global flag '--{f.name}' is required")
            global_sources[_flag_param_name(f.name)] = src_label

        # Validate choices for global flags
        for f in self._global_flags:
            if f.name in cli_set:
                _validate_choices(f.name, cli_set[f.name], f.repeatable, f.choices)

        return cli_set, global_sources, remaining

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
        result = self._dispatch(sys.argv[1:], sys.stdout, sys.stderr, "run")
        sys.exit(result.exit_code)

    def test(self, argv: list[str]) -> Result:
        """Run the CLI with given argv, capturing output and exit code."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        # The redirect wraps the whole dispatch so a handler that bypasses the
        # context writers and calls print() is captured too.
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            result = self._dispatch(argv, stdout_buf, stderr_buf, "test")
        return Result(
            stdout=stdout_buf.getvalue(),
            stderr=stderr_buf.getvalue(),
            exit_code=result.exit_code,
            data=(None if result.payload is _MISSING else result.payload),
        )

    def _dispatch(self, argv: list[str], out, err, mode: str) -> "_DispatchResult":
        """The single dispatch seam shared by ``run()`` and ``test()``.

        Parses, renders the pre-dispatch outcomes (help, version, schema dump,
        MCP, parse errors), executes the handler and finishes through the ONE
        ordered exit step (:meth:`_finish_dispatch`), which owns the payload,
        the would-do log and the exit code on every path out of the handler.
        """
        # Machine mode is not known until the pre-scan runs inside _parse, so
        # the flag starts false on every dispatch: a stale value from an
        # earlier run must never decide what this one emits. The registration
        # validations below run BEFORE the pre-scan and therefore cannot reach
        # machine mode at all -- they are app-definition errors, not run
        # results, and they emit no envelope.
        self._last_json = False

        check_err = self._validate_check_registrations()
        if check_err:
            print(f"error: {check_err}", file=err)
            return _DispatchResult(1)
        tag_err = self._validate_tag_contracts()
        if tag_err:
            print(f"error: {tag_err}", file=err)
            return _DispatchResult(1)

        try:
            cmd, data, sources = self._parse(argv)
        except _HelpRequested as e:
            if isinstance(e.target, App):
                print(_format_app_help(self), file=out)
            elif isinstance(e.target, Group):
                print(_format_group_help(self, e.target), file=out)
            elif isinstance(e.target, Command):
                prefix = self._find_command_prefix(e.target)
                print(_format_command_help(self, e.target, prefix), file=out)
            return _DispatchResult(0)
        except _VersionRequested:
            print(_format_version(self), file=out)
            return _DispatchResult(0)
        except _DumpSchemaRequested:
            try:
                path = _write_schema(self)
            except RuntimeError as e:
                print(f"error: {e}", file=err)
                return _DispatchResult(1)
            print(path, file=out)
            return _DispatchResult(0)
        except _McpRequested:
            if mode == "test":
                # In test mode, MCP requires real stdin/stdout; just acknowledge
                print("error: --mcp requires interactive stdin/stdout", file=err)
                return _DispatchResult(1)
            self.serve_mcp()
            return _DispatchResult(0)
        except _ParseError as e:
            print(f"error: {e}", file=err)
            prefix = e.command_prefix or self.name
            print(f"try '{prefix} --help'", file=err)
            # A run that ended before a command resolved still owes machine
            # mode its one document, with a null command (§19.2). The parse
            # error's own text stays on stderr: it does not go through the
            # context writers, so it is not one of the diagnostics the
            # envelope carries.
            if self._last_json:
                self._emit_envelope(
                    out, command=None, exit_code=1,
                    dry_run=self._last_dry_run, payload=_MISSING,
                    preview=[], preview_error=None, diagnostics=[],
                )
            return _DispatchResult(1)

        self._begin_dispatch()
        cmd_path = ".".join(self._last_resolved_path + [cmd.name])
        # Record test-coverage hit (command-level only, test mode only).
        if mode == "test" and self.test_coverage:
            self._record_coverage(cmd_path)
        # Store sources for function handlers that need provenance info
        self._last_sources = sources
        ctx = Context(
            stdout=out, stderr=err, sources=sources,
            infra=self._infra_access(self._last_hermetic),
            dry_run=self._last_dry_run,
            approve_consequential=self._last_approve_consequential,
            quiet=self._last_quiet, verbose=self._last_verbose,
            json=self._last_json,
            effects=self._arm_effects(
                cmd, cmd_path, dry_run=self._last_dry_run,
            ),
            command_name=cmd.name,
            payload_schema=cmd.payload_schema,
        )
        if mode == "run":
            # The confirm protocol fires only on the real CLI path.
            self._confirm_consequential(cmd, cmd_path)
        # The ordered exit step runs on EVERY exit path out of the dispatch,
        # not just the normal return: the operator asked for a preview and the
        # effects were recorded, so a handler that unwinds through sys.exit or
        # an exception still owes them the list. The clause set below is
        # exhaustive by construction -- BaseException is the root of the
        # hierarchy, so no unwind can slip past it.
        try:
            if cmd.passthrough is not None:
                handler_return = cmd.passthrough.handler(
                    ctx, cmd.name, data, self._last_global_values,
                )
            else:
                handler_return = cmd.handler(ctx, **data)
            exit_code = _interpret_handler_return(handler_return)
        except _DryRunTruncated as trunc:
            return self._finish_dispatch(
                ctx, cmd_path, 1, out, err,
                truncated=trunc, aborted=False,
            )
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
            self._finish_dispatch(ctx, cmd_path, code, out, err, aborted=False)
            if mode == "run":
                # The real CLI path lets the exit propagate untouched, so a
                # non-integer sys.exit() argument keeps printing itself.
                raise
            return _DispatchResult(code, ctx._payload_value)
        except BaseException:
            self._finish_dispatch(ctx, cmd_path, 1, out, err, aborted=True)
            raise
        return self._finish_dispatch(ctx, cmd_path, exit_code, out, err)

    def _finish_dispatch(
        self, ctx: "Context", cmd_path: str, exit_code: int, out, err,
        *, truncated: "_DryRunTruncated | None" = None,
        aborted: bool = False,
    ) -> "_DispatchResult":
        """The ONE ordered exit step: payload, preview log, exit code.

        Reachable from all four ways out of a dispatch (normal return, an
        explicit ``sys.exit``, a truncated preview and an unwinding abort), so
        there is exactly one place that decides what the framework emits at the
        end of a run and in what order.

        In machine mode this step emits the envelope INSTEAD of the human
        stream's would-do log, truncation error and abort marker: those texts
        become the envelope's ``preview`` and ``preview_error`` members
        (§19.1, §19.3), and stdout carries exactly one document.
        """
        if ctx._json:
            self._emit_envelope(
                out,
                command=cmd_path,
                exit_code=exit_code,
                dry_run=ctx._dry_run,
                payload=ctx._payload_value,
                preview=self._effect_log.to_list(),
                preview_error=self._preview_error(
                    cmd_path, ctx._dry_run, truncated, aborted,
                ),
                diagnostics=ctx._diagnostics,
            )
            return _DispatchResult(exit_code, ctx._payload_value)
        if truncated is not None:
            # The truncation path ends the preview for its own pinned reason:
            # it renders the log it already has and its own error, and never
            # goes through the generic would-do rendering.
            print(truncated.log.render(), file=out)
            print(truncated.message, file=err)
        else:
            self._render_dry_log(cmd_path, out, err, aborted=aborted)
        return _DispatchResult(exit_code, ctx._payload_value)

    def _preview_error(
        self, cmd_path: str, dry_run: bool,
        truncated: "_DryRunTruncated | None", aborted: bool,
    ) -> dict | None:
        """Build the envelope's ``preview_error`` member (§19.3).

        The two terminal conditions are mutually exclusive by §3.5's table.
        Each carries the §12.5 / §12.11 text byte-identically rather than
        restating it, so there is one text per condition.

        The abort branch is dry-mode-only, exactly as the human stream's
        marker is: the message says "dry-run preview ends at step N", which is
        not a true sentence about a live run.
        """
        if truncated is not None:
            return {
                "kind": "truncated",
                "step": truncated.step,
                "command": truncated.cmd_path,
                "brand": truncated.brand,
                "message": truncated.message,
            }
        if aborted and dry_run:
            step = self._effect_log.next_seq()
            return {
                "kind": "aborted",
                "step": step,
                "command": cmd_path,
                "brand": None,
                "message": _msg_dry_run_aborted(step, cmd_path),
            }
        return None

    def _emit_envelope(
        self, out, *, command: str | None, exit_code: int, dry_run: bool,
        payload: object, preview: list[dict], preview_error: dict | None,
        diagnostics: list[dict],
    ) -> None:
        """Write the envelope, machine mode's sole stdout document (§19.2).

        Field order follows §19.2's table: optional and for readability only,
        since conformance compares parsed structures. Record keys are sorted so
        the three implementations' serializers agree byte-for-byte.

        The serialization follows §19.5's escaping regime -- plain UTF-8,
        escaping only what JSON mandates -- and it is NOT written through the
        quiet-suppressible writers, so ``--quiet`` has no mechanism by which to
        reach it.
        """
        envelope = {
            "interface_version": _INTERFACE_VERSION,
            "app": self.name,
            "app_version": self.version,
            "command": command,
            "exit_code": exit_code,
            "payload": None if payload is _MISSING else payload,
            "dry_run": dry_run,
            "preview": [
                {key: rec[key] for key in sorted(rec)} for rec in preview
            ],
            "preview_error": preview_error,
            "diagnostics": diagnostics,
        }
        # No ``default=`` fallback: §19.5's emission-time validation already
        # refused every value the encoder could not represent, so a coercion
        # here could only invent a shape no declared schema describes. The two
        # siblings have no such fallback either.
        print(
            json.dumps(
                envelope, separators=(",", ":"), ensure_ascii=False,
            ),
            file=out,
        )

    def _invoke(
        self, command_path: str, kwargs: dict[str, object],
        *, approve_consequential: bool = False,
    ) -> object:
        """Invoke a command programmatically with pre-typed kwargs.

        This is the internal pipeline for programmatic invocation. It bypasses
        CLI parsing, env var resolution, config file loading, and stdin
        handling. The caller provides fully-typed values directly.

        Args:
            command_path: dot-separated path to the command
                (e.g. "deploy" or "config.set").
            kwargs: handler keyword arguments. Flag names use underscores
                (e.g. dry_run). Positional args use their declared name.
                For passthrough commands, pass a single key "_args" with
                a list of raw string arguments.
            approve_consequential: the caller's explicit consent. A command
                that declares itself consequential is refused without it.

        Returns:
            The handler's return value (structured data, int, or None).

        Raises:
            _ParseError: if validation fails (missing required flags,
                mutex violations, dependency errors, etc.), or if the command
                is consequential and no consent was supplied.
            _HelpRequested: if the command path resolves to a group
                with no subcommand.
        """
        path_segments = command_path.split(".")
        cmd, _rest, _path = self._resolve_command(path_segments)

        # The consent check (contract §8.5). There is no terminal here, so the
        # confirm protocol's prompt cannot fire -- the caller must have said so
        # in the call. Checked before anything is dispatched or recorded.
        if cmd.consequential and not approve_consequential:
            raise _ParseError(
                _msg_call_consequential_unconsented(command_path)
            )

        self._begin_dispatch()
        # Record test-coverage hit (command-level only).
        if self.test_coverage:
            self._record_coverage(command_path)

        # Passthrough commands: forward raw args to the passthrough handler
        if cmd.passthrough is not None:
            raw_args = kwargs.get("_args", [])

            # Build set of known global flag param names
            global_param_names: set[str] = set()
            for gf in self._global_flags:
                global_param_names.add(_flag_param_name(gf.name))

            # Validate that all kwargs keys are either "_args" or known global flags
            for key in kwargs:
                if key == "_args":
                    continue
                if key not in global_param_names:
                    raise _ParseError(
                        f"unknown parameter '{key}' for passthrough command '{cmd.name}'"
                    )

            # Build global values from kwargs, applying defaults for missing flags
            global_values: dict[str, object] = {}
            for gf in self._global_flags:
                param_name = _flag_param_name(gf.name)
                if param_name in kwargs:
                    global_values[param_name] = kwargs[param_name]
                elif isinstance(gf.default, RelativeToRoot):
                    global_values[param_name] = _resolve_infra_root_path(gf.default, self._infra_roots)
                elif gf.default is not None:
                    global_values[param_name] = gf.default
                else:
                    raise _ParseError(
                        f"global flag '--{gf.name}' is required"
                    )

            # Programmatic dispatch: --dry-run is not reachable (argv parsing
            # is bypassed entirely) and the confirm protocol's PROMPT never
            # fires -- there is no terminal. The requirement itself is honoured
            # above, and the caller's consent is delivered to the handler here.
            ctx = Context(
                stdout=sys.stdout, stderr=sys.stderr, sources={},
                infra=self._infra_access(),
                approve_consequential=approve_consequential,
                effects=self._arm_effects(cmd, command_path, dry_run=False),
                command_name=cmd.name,
                payload_schema=cmd.payload_schema,
            )
            result = cmd.passthrough.handler(
                ctx, cmd.name, raw_args, global_values,
            )
            _interpret_handler_return(result)  # validate return type
            # The programmatic surface keeps its capture: it returns the
            # payload the handler supplied (contract §19.4).
            if ctx._payload_value is not _MISSING:
                return ctx._payload_value
            if isinstance(result, Outcome):
                return None
            return result

        # Build reverse mapping: param_name (underscore) -> flag.name (dashes)
        param_to_flag: dict[str, str] = {}
        for f in cmd.flags:
            param_to_flag[_flag_param_name(f.name)] = f.name

        # Also map global flags
        global_flag_names: set[str] = set()
        for gf in self._global_flags:
            param_to_flag[_flag_param_name(gf.name)] = gf.name
            global_flag_names.add(gf.name)

        # Collect arg names for this command
        arg_names: set[str] = {a.name for a in cmd.args}

        # Populate sourced store from kwargs. Provided kwargs are marked
        # _Source.CLI; absent flags will get _Source.DEFAULT when
        # _validate_and_build_kwargs applies defaults.
        store = _SourcedStore()
        positionals: list[str] = []

        for key, value in kwargs.items():
            if key in param_to_flag:
                # It's a flag -- store under flag.name (with dashes)
                flag_name = param_to_flag[key]
                store.set(flag_name, value, _Source.CLI)
            elif key in arg_names:
                # It's a positional arg -- collect into positionals in order
                # (handled below after iterating all kwargs)
                pass
            else:
                raise _ParseError(
                    f"unknown parameter '{key}' for command '{cmd.name}'"
                )

        # Build positionals list in declared arg order from kwargs
        for a in cmd.args:
            if a.name in kwargs:
                val = kwargs[a.name]
                if a.variadic:
                    # Variadic args expect a list
                    if isinstance(val, list):
                        positionals.extend(str(v) for v in val)
                    else:
                        positionals.append(str(val))
                else:
                    positionals.append(str(val))

        # Validate and build final kwargs via the shared validation pipeline
        _cmd, final_kwargs, _global_cli_set, invoke_sources = _validate_and_build_kwargs(
            cmd, store, positionals, global_flag_names, self._infra_roots,
        )

        # Merge global flag values into final kwargs
        for gf in self._global_flags:
            if gf.name in _global_cli_set:
                final_kwargs[_flag_param_name(gf.name)] = _global_cli_set[gf.name]
            elif _flag_param_name(gf.name) not in final_kwargs:
                # Global flag not provided -- use its default
                if isinstance(gf.default, RelativeToRoot):
                    final_kwargs[_flag_param_name(gf.name)] = _resolve_infra_root_path(gf.default, self._infra_roots)
                    invoke_sources[_flag_param_name(gf.name)] = "infra"
                elif gf.default is not None:
                    final_kwargs[_flag_param_name(gf.name)] = gf.default

        # Store sources for function handlers that need provenance info
        self._last_sources = invoke_sources

        ctx = Context(
            stdout=sys.stdout, stderr=sys.stderr, sources=invoke_sources,
            infra=self._infra_access(),
            approve_consequential=approve_consequential,
            effects=self._arm_effects(cmd, command_path, dry_run=False),
            command_name=cmd.name,
            payload_schema=cmd.payload_schema,
        )
        result = cmd.handler(ctx, **final_kwargs)
        _interpret_handler_return(result)  # validate return type
        # The programmatic surface keeps its capture: it returns the payload
        # the handler supplied (contract §19.4).
        if ctx._payload_value is not _MISSING:
            return ctx._payload_value
        if isinstance(result, Outcome):
            return None
        return result

    def call(
        self, command_path: str, *, approve_consequential: bool = False,
        **kwargs: object,
    ) -> object:
        """Invoke a command programmatically and return its result.

        Unlike _invoke(), this is the public API. It converts internal
        _ParseError exceptions to InvokeError so callers don't need to
        depend on private types.

        Args:
            command_path: dot-separated path to the command
                (e.g. "deploy" or "config.set").
            approve_consequential: the caller's explicit consent, the
                programmatic counterpart of ``--approve-consequential``.
                Keyword-only, and never a handler kwarg: the name is
                framework-reserved, so no command can declare a parameter
                that collides with it. A command that declares itself
                consequential is refused without it. Read-only and plain
                mutating commands ignore it.
            **kwargs: handler keyword arguments. Flag names use underscores
                (e.g. dry_run). Positional args use their declared name.
                For passthrough commands, pass _args=[...] for raw arguments.

        Returns:
            The handler's return value (structured data, int, or None).

        Raises:
            InvokeError: if validation fails (unknown command, missing
                required flags, mutex violations, dependency errors, etc.),
                or if the command is consequential and no consent was given.
        """
        return self._call_with_kwargs(
            command_path, kwargs,
            approve_consequential=approve_consequential,
        )

    def _call_with_kwargs(
        self, command_path: str, kwargs: dict[str, object],
        *, approve_consequential: bool,
    ) -> object:
        """call() with the handler kwargs as a dict instead of a splat.

        The MCP server routes through here rather than ``call(**arguments)``:
        an ``approve_consequential`` key inside a tools/call ``arguments``
        object is a parameter of the command's own namespace -- no command can
        declare that reserved name, so it must surface as the usual
        unknown-parameter error, exactly as it does in the siblings whose
        kwargs are a map. Splatting it would silently promote it to consent.
        """
        try:
            return self._invoke(
                command_path, kwargs,
                approve_consequential=approve_consequential,
            )
        except _ParseError as e:
            raise InvokeError(str(e)) from e
        except _HelpRequested:
            raise InvokeError(
                f"'{command_path}' is a group, not a command"
            )

    async def acall(
        self, command_path: str, *, approve_consequential: bool = False,
        **kwargs: object,
    ) -> object:
        """Async version of call(). Runs the handler in a thread.

        Args:
            command_path: dot-separated path to the command.
            approve_consequential: the caller's explicit consent (same as
                call()).
            **kwargs: handler keyword arguments (same as call()).

        Returns:
            The handler's return value (structured data, int, or None).

        Raises:
            InvokeError: if validation fails, or if the command is
                consequential and no consent was given.
        """
        import asyncio
        # to_thread takes func positional-only, so a handler kwarg can never
        # shadow it.
        return await asyncio.to_thread(
            self.call, command_path,
            approve_consequential=approve_consequential, **kwargs,
        )

    def json_schema(self, command_path: str) -> dict:
        """Produce a JSON Schema parameters object for a command's flags and args.

        Args:
            command_path: dot-separated path to the command (e.g. "deploy"
                or "config.show").

        Returns:
            A JSON Schema object with "type": "object", "properties",
            "required", and "additionalProperties": false.

        Raises:
            InvokeError: if the command path is invalid or resolves to a group.
        """
        path_segments = command_path.split(".")
        try:
            cmd, _rest, _path = self._resolve_command(path_segments)
        except _ParseError as e:
            raise InvokeError(str(e)) from e
        except _HelpRequested:
            raise InvokeError(
                f"'{command_path}' is a group, not a command"
            )
        return _build_json_schema(cmd)

    def as_tools(self) -> list[Tool]:
        """Export non-hidden, non-interactive leaf commands as Tool descriptors.

        Returns a list of Tool objects, one per eligible command plus a
        router tool. Each tool's execute function wraps acall().
        """
        tools: list[Tool] = []
        command_paths: list[str] = []

        # Collect leaf commands from top-level
        for name, cmd in self._commands.items():
            if cmd.hidden or cmd.interactive:
                continue
            path = name
            tools.append(self._make_tool(path, cmd))
            command_paths.append(path)

        # Collect leaf commands from groups (recursive)
        for group_name, group in self._groups.items():
            self._collect_tools_from_group(
                group, [group_name], tools, command_paths,
            )

        # Build the router tool
        tools.append(self._make_router_tool(command_paths))

        return tools

    def _collect_tools_from_group(
        self,
        group: Group,
        path: list[str],
        tools: list[Tool],
        command_paths: list[str],
    ) -> None:
        """Recursively collect non-hidden, non-interactive commands from a group."""
        if group.hidden:
            return
        for cmd_name, cmd in group.commands.items():
            if cmd.hidden or cmd.interactive:
                continue
            dotted = ".".join(path + [cmd_name])
            tools.append(self._make_tool(dotted, cmd))
            command_paths.append(dotted)
        for sub_name, sub_group in group._groups.items():
            self._collect_tools_from_group(
                sub_group, path + [sub_name], tools, command_paths,
            )

    def _make_tool(self, command_path: str, cmd: Command) -> Tool:
        """Build a Tool for a single command."""
        app_ref = self

        async def execute(
            *, approve_consequential: bool = False, **kwargs: object,
        ) -> object:
            return await app_ref.acall(
                command_path,
                approve_consequential=approve_consequential,
                **kwargs,
            )

        return Tool(
            name=command_path,
            description=cmd.help,
            parameters=_build_json_schema(cmd),
            effect=cmd.effect,
            consequential=cmd.consequential,
            execute=execute,
        )

    def _make_router_tool(self, command_paths: list[str]) -> Tool:
        """Build the router tool that dispatches to per-command tools."""
        app_ref = self

        async def execute(
            command: str | None = None, *,
            approve_consequential: bool = False, **kwargs: object,
        ) -> object:
            if command is None:
                return command_paths[:]
            return await app_ref.acall(
                command,
                approve_consequential=approve_consequential,
                **kwargs,
            )

        parameters: dict = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Command to execute (dot-separated path)"
                    ),
                    "enum": command_paths[:],
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }
        # The router can reach a mutating command, so it classifies as
        # mutating. It is NOT itself consequential: the routed command's own
        # requirement is checked when the call reaches it, and the router
        # forwards the caller's consent unchanged. Marking the router
        # consequential would demand consent for routing to a read_only
        # command, which confirms nothing.
        return Tool(
            name=self.name,
            description=f"Route to {self.name} commands",
            parameters=parameters,
            effect=EFFECT_MUTATING,
            consequential=False,
            execute=execute,
        )

    def serve_mcp(
        self,
        *,
        input: io.TextIOBase | None = None,
        output: io.TextIOBase | None = None,
    ) -> None:
        """Run a JSON-RPC 2.0 MCP server on stdin/stdout.

        Reads one JSON object per line from input (default: sys.stdin),
        writes one JSON object per line to output (default: sys.stdout).
        Handles initialize, tools/list, tools/call, and notifications.

        The server runs until input is exhausted (EOF).
        """
        _run_mcp_server(self, input=input, output=output)


# JSON Schema type mapping for tool export
_JSON_SCHEMA_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _build_json_schema(cmd: Command) -> dict:
    """Build a JSON Schema parameters object for a command's flags and args."""
    properties: dict = {}
    required: list[str] = []

    for f in cmd.flags:
        param_name = _flag_param_name(f.name)
        prop: dict = {}

        if f.compound == "list":
            prop["type"] = "array"
            prop["items"] = {"type": _JSON_SCHEMA_TYPES[f.item_type]}
        elif f.compound == "dict":
            prop["type"] = "object"
            prop["additionalProperties"] = {
                "type": _JSON_SCHEMA_TYPES[f.value_type],
            }
        else:
            prop["type"] = _JSON_SCHEMA_TYPES[f.type]

        if f.choices is not None:
            prop["enum"] = f.choices[:]

        prop["description"] = f.help

        properties[param_name] = prop

        # A flag is required if it has no default (None for scalar).
        # Repeatable/dict flags always have a default (empty list/dict).
        is_required = (
            f.compound == "scalar"
            and f.default is None
        )
        if is_required:
            required.append(param_name)

    for a in cmd.args:
        prop = {}

        if a.compound == "list":
            prop["type"] = "array"
            prop["items"] = {"type": _JSON_SCHEMA_TYPES[a.item_type]}
        else:
            prop["type"] = _JSON_SCHEMA_TYPES[a.type]

        if a.choices is not None:
            prop["enum"] = a.choices[:]

        prop["description"] = a.help

        properties[a.name] = prop

        if a.required:
            required.append(a.name)

    schema: dict = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return schema


def _tokens_contain_help(tokens: list[str]) -> bool:
    """Check if --help or -h appears in tokens before any -- separator."""
    for tok in tokens:
        if tok == "--":
            return False
        if tok == "--help" or tok == "-h":
            return True
    return False


def _validate_choices(
    name: str,
    val: object,
    repeatable: bool,
    choices: list | None,
    *,
    is_arg: bool = False,
) -> None:
    """Validate a resolved flag or arg value against its choices list.

    Raises _ParseError on an invalid value. is_arg selects the message prefix
    ("argument 'name':" instead of "--name:"); the two f-strings are kept as
    full literals so conformance/check_error_parity.py can extract them.
    A None value is exempt from validation: None only arises when the flag or
    arg was not passed (an unset mutex flag, or default=None on an arg) -- a
    CLI-supplied value is never None.
    """
    if choices is None or val is None:
        return
    vals = val if repeatable else [val]
    for v in vals:
        if v not in choices:
            choices_str = ", ".join(
                _format_float_canonical(c) if isinstance(c, float) else str(c)
                for c in choices
            )
            v_str = _format_float_canonical(v) if isinstance(v, float) else str(v)
            if is_arg:
                raise _ParseError(
                    f"argument '{name}': invalid value '{v_str}', "
                    f"must be one of: {choices_str}"
                )
            raise _ParseError(
                f"--{name}: invalid value '{v_str}', must be one of: {choices_str}"
            )


def _validate_and_build_kwargs(
    cmd: Command,
    store: _SourcedStore,
    positionals: list[str],
    global_flag_names: set[str],
    infra_roots: dict[str, str] | None = None,
) -> tuple[Command, dict[str, object], dict[str, object], dict[str, str]]:
    """Validate parsed values and build the kwargs dict for the command handler.

    This is the second half of command parsing: mutex enforcement, implies
    resolution, dependency checks, defaults, choices validation, custom
    validation, positional arg resolution, and kwargs building. It operates
    on sourced values in the store and doesn't care how they were produced.

    Returns (cmd, kwargs, global_cli_set, sources) where sources maps
    flag param names to source labels (cli/env/config/default/implied).
    """
    # Step 4.5: enforce mutex group constraints (before defaults are applied).
    # Only cli/env/config sources count as "present" for mutex evaluation.
    # Default and implied sources do NOT trigger mutex violations.
    for mg in cmd.mutex:
        set_flags = [f for f in mg.flags if store.is_present_for_mutex(f.name)]
        if len(set_flags) > 1:
            names = " and ".join(f"--{f.name}" for f in set_flags)
            raise _ParseError(f"{names} are mutually exclusive")
        if len(set_flags) == 0:
            names = ", ".join(f"--{f.name}" for f in mg.flags)
            raise _ParseError(f"one of {names} is required")

    # Step 4.55: resolve Implies dependencies (before dependency checks, so
    # implied values participate in downstream CoRequired/Requires validation).
    # Implied values are stored with _Source.IMPLIED.
    for dep in cmd.dependencies:
        if isinstance(dep, Implies):
            if store.is_present_for_deps(dep.flag):
                if store.has(dep.implies):
                    if store[dep.implies] != dep.value:
                        neg = "no-" if not dep.value else ""
                        explicit_neg = "" if not dep.value else "no-"
                        raise _ParseError(
                            f"flag '--{dep.flag}' implies '--{neg}{dep.implies}', "
                            f"but '--{explicit_neg}{dep.implies}' was explicitly provided"
                        )
                else:
                    store.set(dep.implies, dep.value, _Source.IMPLIED)

    # Step 4.6: enforce flag dependencies (before defaults).
    # is_present_for_deps: cli, env, config, implied count. Default does NOT.
    for dep in cmd.dependencies:
        if isinstance(dep, CoRequired):
            present = [f for f in dep.flags if store.is_present_for_deps(f)]
            if 0 < len(present) < len(dep.flags):
                names = ", ".join(f"--{f}" for f in dep.flags)
                raise _ParseError(f"flags {names} must be used together")
        elif isinstance(dep, Requires):
            if store.is_present_for_deps(dep.flag) and not store.is_present_for_deps(dep.depends_on):
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

    # Step 5: apply defaults (SourceDefault)
    for f in cmd.flags:
        if store.has(f.name):
            continue
        if f.compound == "dict":
            # Dict flags default to {} (never required)
            store.set(f.name, dict(f.default) if f.default else {}, _Source.DEFAULT)
        elif f.repeatable:
            # Repeatable flags default to [] (never required)
            store.set(f.name, list(f.default) if f.default else [], _Source.DEFAULT)
        elif isinstance(f.default, RelativeToRoot):
            # A RelativeToRoot marker resolves through the declared infra roots
            # and reports source "infra" (distinguishable from a plain default).
            resolved = _resolve_infra_root_path(f.default, infra_roots or {})
            store.set(f.name, resolved, _Source.INFRA)
        elif f.default is not None:
            store.set(f.name, f.default, _Source.DEFAULT)
        elif f.name in mutex_flag_names:
            # Mutex group flags with no default get None instead of being
            # required -- the mutex group itself enforces required semantics
            store.set(f.name, None, _Source.DEFAULT)
        else:
            # Flag with no default and no value: required
            if f.type is bool and f.negatable:
                raise _ParseError(
                    f"flag '--{f.name}' must be passed as "
                    f"--{f.name} or --no-{f.name}"
                )
            if f.type is bool and not f.negatable:
                raise _ParseError(
                    f"flag '--{f.name}' must be passed as --{f.name}"
                )
            raise _ParseError(f"flag '--{f.name}' is required")

    # Step 5.5: validate choices
    for f in cmd.flags:
        if store.has(f.name):
            _validate_choices(f.name, store[f.name], f.repeatable, f.choices)

    # Step 5.6: custom validation
    for f in cmd.flags:
        if f.validate is not None and store.has(f.name):
            if f.repeatable:
                for val in store[f.name]:
                    try:
                        f.validate(val)
                    except ValueError as e:
                        raise _ParseError(f"--{f.name}: {e}")
            elif store[f.name] is not None:
                # None means the flag was not passed (an unset mutex flag) --
                # there is no value to validate.
                try:
                    f.validate(store[f.name])
                except ValueError as e:
                    raise _ParseError(f"--{f.name}: {e}")

    # Step 6: resolve positional args
    arg_values: dict[str, object] = {}
    has_variadic = cmd.args and cmd.args[-1].variadic
    fixed_args = cmd.args[:-1] if has_variadic else cmd.args
    for idx, a in enumerate(fixed_args):
        if idx < len(positionals):
            arg_values[a.name] = _coerce_arg_value(a, positionals[idx])
        elif a.required:
            raise _ParseError(f"missing required argument '{a.name}'")
        elif not isinstance(a.default, _MissingSentinel):
            arg_values[a.name] = a.default
    if has_variadic:
        va = cmd.args[-1]
        remaining_positionals = positionals[len(fixed_args):]
        if va.required and len(remaining_positionals) == 0:
            raise _ParseError(f"missing required argument '{va.name}'")
        arg_values[va.name] = [
            _coerce_arg_value(va, p) for p in remaining_positionals
        ]
    elif len(positionals) > len(cmd.args):
        raise _ParseError(f"unexpected argument '{positionals[len(cmd.args)]}'")

    # Step 6.5: validate arg choices
    for a in cmd.args:
        if a.name in arg_values:
            _validate_choices(
                a.name, arg_values[a.name], a.variadic, a.choices, is_arg=True,
            )

    # Step 7: build kwargs dict (command flags only)
    kwargs: dict[str, object] = {}
    for f in cmd.flags:
        kwargs[_flag_param_name(f.name)] = store[f.name]
    for a in cmd.args:
        if a.name in arg_values:
            kwargs[a.name] = arg_values[a.name]

    # Separate out global flag values parsed from post-command tokens
    global_cli_set: dict[str, object] = {}
    for name in global_flag_names:
        if store.has(name):
            global_cli_set[name] = store[name]

    # Build source map: param-name -> source label (for Context.source())
    sources: dict[str, str] = {}
    raw_sources = store.source_map()
    for f in cmd.flags:
        if f.name in raw_sources:
            sources[_flag_param_name(f.name)] = raw_sources[f.name]
    # Global flags parsed post-command emit their source label too (always
    # "cli" here, since post-command tokens are CLI-only -- env and config for
    # globals are resolved in the pre-command global-flag pass). Without this,
    # `tool cmd --global X` would report source "default" for the global.
    for name in global_flag_names:
        if name in raw_sources:
            sources[_flag_param_name(name)] = raw_sources[name]

    return cmd, kwargs, global_cli_set, sources


def _parse_command(
    cmd: Command,
    tokens: list[str],
    global_flags: list[Flag] | None = None,
    config_data: dict | None = None,
    stdin_consumed_by: list[str | None] | None = None,
    conflict_mode: str = "cli-wins",
    hermetic: bool = False,
    infra_roots: dict[str, str] | None = None,
) -> tuple[Command, dict[str, object], dict[str, object], dict[str, str]]:
    """Parse tokens against a resolved command's flags and args.

    Returns (cmd, kwargs, global_cli_set, sources) where global_cli_set contains
    any global flag values parsed from tokens appearing after the command name.

    stdin_consumed_by is a mutable single-element list tracking which flag
    has already consumed stdin via @-. Updated in-place.

    When hermetic is True, env var and config resolution are skipped entirely.
    """
    if stdin_consumed_by is None:
        stdin_consumed_by = [None]

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
        if f.compound == "dict":
            if f.name not in cli_set:
                cli_set[f.name] = {}
            # value is a (key, val) tuple from _parse_dict_value
            k, v = value
            if k in cli_set[f.name]:
                raise _ParseError(
                    f"--{f.name}: duplicate key '{k}'"
                )
            cli_set[f.name][k] = v
        elif f.repeatable:
            if f.name not in cli_set:
                cli_set[f.name] = []
            if f.unique and value in cli_set[f.name]:
                raise _ParseError(
                    f"--{f.name}: duplicate value "
                    f"'{_format_value_for_error(value)}'"
                )
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
                if f.type is bool and f.compound != "dict":
                    raise _ParseError(
                        f"flag '{flag_part}' is a boolean flag and does not take a value"
                    )
                if f.compound == "dict":
                    _store_dict_flag(f, value_part, cli_set)
                elif f.type is int:
                    try:
                        _store_value(f, _strict_int(value_part))
                    except ValueError as e:
                        raise _ParseError(f"--{f.name}: {e}")
                elif f.type is float:
                    try:
                        _store_value(f, _strict_float(value_part))
                    except ValueError as e:
                        raise _float_parse_error(f.name, value_part, e)
                else:
                    resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                        f.name, value_part, stdin_consumed_by[0],
                    )
                    _store_value(f, resolved)
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
                if f.type is bool and f.compound != "dict":
                    cli_set[f.name] = True
                    i += 1
                else:
                    # str/int/float/dict flag: consume next token as value
                    if i + 1 < len(tokens):
                        raw = tokens[i + 1]
                        if f.compound == "dict":
                            _store_dict_flag(f, raw, cli_set)
                        elif f.type is int:
                            try:
                                _store_value(f, _strict_int(raw))
                            except ValueError as e:
                                raise _ParseError(f"--{f.name}: {e}")
                        elif f.type is float:
                            try:
                                _store_value(f, _strict_float(raw))
                            except ValueError as e:
                                raise _float_parse_error(f.name, raw, e)
                        else:
                            resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                                f.name, raw, stdin_consumed_by[0],
                            )
                            _store_value(f, resolved)
                        i += 2
                    else:
                        raise _ParseError(f"flag '{tok}' requires a value")
            else:
                raise _ParseError(f"unknown flag '{tok}'")
            continue

        # -x (short form)
        if tok.startswith("-") and len(tok) == 2 and tok in short_lookup:
            f = short_lookup[tok]
            if f.type is bool and f.compound != "dict":
                cli_set[f.name] = True
                i += 1
            else:
                # str/int/float/dict flag: consume next token as value
                if i + 1 < len(tokens):
                    raw = tokens[i + 1]
                    if f.compound == "dict":
                        _store_dict_flag(f, raw, cli_set)
                    elif f.type is int:
                        try:
                            _store_value(f, _strict_int(raw))
                        except ValueError as e:
                            raise _ParseError(f"--{f.name}: {e}")
                    elif f.type is float:
                        try:
                            _store_value(f, _strict_float(raw))
                        except ValueError as e:
                            raise _float_parse_error(f.name, raw, e)
                    else:
                        resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                            f.name, raw, stdin_consumed_by[0],
                        )
                        _store_value(f, resolved)
                    i += 2
                else:
                    raise _ParseError(f"flag '{tok}' requires a value")
            continue

        # Token starts with "-" but doesn't match any known flag;
        # treat as a positional arg (e.g. negative numbers like -7, -3.14)
        positionals.append(tok)
        i += 1

    # Track which flag names are set by env vs config (for source attribution).
    env_names: set[str] = set()
    config_names: set[str] = set()

    # Step 4: resolve env vars for flags not set by CLI (skipped under --hermetic)
    for f in cmd.flags:
        if hermetic:
            break
        if f.name in cli_set:
            continue
        if f.env is not None:
            env_val = os.environ.get(f.env)
            if env_val is not None:
                if f.compound == "dict":
                    # Dict flags parse env vars as JSON
                    try:
                        parsed = json.loads(env_val)
                    except json.JSONDecodeError as e:
                        raise _ParseError(
                            f"--{f.name}: invalid JSON in env var "
                            f"'{f.env}': {e}"
                        )
                    if not isinstance(parsed, dict):
                        raise _ParseError(
                            f"--{f.name}: env var '{f.env}' must be a JSON "
                            f"object, got {type(parsed).__name__}"
                        )
                    result = {}
                    for k, v in parsed.items():
                        result[k] = _coerce_dict_json_value(
                            f.name, k, v, f.value_type,
                        )
                    cli_set[f.name] = result
                elif f.type is bool:
                    try:
                        cli_set[f.name] = _strict_bool(env_val)
                    except ValueError:
                        raise _ParseError(
                            f"invalid boolean value {env_val!r} for env var "
                            f"'{f.env}' (flag '--{f.name}')"
                        )
                elif f.type is int:
                    if f.repeatable and f.env_separator is not None:
                        parts = _split_escaped(env_val, f.env_separator)
                        coerced_list = []
                        for element in parts:
                            try:
                                coerced_list.append(_strict_int(element))
                            except ValueError as e:
                                raise _ParseError(
                                    f"--{f.name}: {e} (from env var '{f.env}')"
                                )
                        if f.unique:
                            dup = _find_duplicate(coerced_list)
                            if dup is not None:
                                raise _ParseError(
                                    f"--{f.name}: duplicate value "
                                    f"'{_format_value_for_error(dup)}' "
                                    f"(from env var '{f.env}')"
                                )
                        cli_set[f.name] = coerced_list
                    else:
                        try:
                            coerced = _strict_int(env_val)
                        except ValueError as e:
                            raise _ParseError(
                                f"--{f.name}: {e} (from env var '{f.env}')"
                            )
                        cli_set[f.name] = [coerced] if f.repeatable else coerced
                elif f.type is float:
                    if f.repeatable and f.env_separator is not None:
                        parts = _split_escaped(env_val, f.env_separator)
                        coerced_list = []
                        for element in parts:
                            try:
                                coerced_list.append(_strict_float(element))
                            except ValueError as e:
                                raise _float_parse_error(
                                    f.name, element, e, env=f.env,
                                )
                        if f.unique:
                            dup = _find_duplicate(coerced_list)
                            if dup is not None:
                                raise _ParseError(
                                    f"--{f.name}: duplicate value "
                                    f"'{_format_value_for_error(dup)}' "
                                    f"(from env var '{f.env}')"
                                )
                        cli_set[f.name] = coerced_list
                    else:
                        try:
                            coerced = _strict_float(env_val)
                        except ValueError as e:
                            raise _float_parse_error(f.name, env_val, e, env=f.env)
                        cli_set[f.name] = [coerced] if f.repeatable else coerced
                else:
                    if f.repeatable and f.env_separator is not None:
                        parts = _split_escaped(env_val, f.env_separator)
                        coerced_list = []
                        for element in parts:
                            resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                                f.name, element, stdin_consumed_by[0],
                            )
                            coerced_list.append(resolved)
                        if f.unique:
                            dup = _find_duplicate(coerced_list)
                            if dup is not None:
                                raise _ParseError(
                                    f"--{f.name}: duplicate value "
                                    f"'{_format_value_for_error(dup)}' "
                                    f"(from env var '{f.env}')"
                                )
                        cli_set[f.name] = coerced_list
                    else:
                        resolved, stdin_consumed_by[0] = _resolve_at_prefix(
                            f.name, env_val, stdin_consumed_by[0],
                        )
                        cli_set[f.name] = [resolved] if f.repeatable else resolved
                env_names.add(f.name)

    # Step 4.2: resolve config values for flags not set by CLI or env.
    # In conflict mode "error", detect when config would set a flag
    # already set by CLI or env. (Skipped under --hermetic.)
    if config_data and not hermetic:
        for f in cmd.flags:
            param = _flag_param_name(f.name)
            if param not in config_data:
                continue
            # Effective mode: per-flag override if set, else the app default.
            effective_mode = (
                f.conflict_mode
                if not isinstance(f.conflict_mode, _MissingSentinel)
                else conflict_mode
            )
            if f.name in cli_set:
                # Flag set by CLI or env, config also has a value. This is a
                # conflict ONLY when the values diverge; identical values agree.
                if effective_mode == "error":
                    try:
                        coerced = _coerce_config_value(config_data[param], f)
                    except ValueError as e:
                        raise _ParseError(
                            f"--{f.name}: config value error: {e}"
                        )
                    if not _values_equal_for_conflict(cli_set[f.name], coerced, f):
                        existing_source = "env" if f.name in env_names else "cli"
                        raise _ParseError(
                            f"flag '{f.name}' set in both "
                            f"{existing_source} and config; remove one"
                        )
                continue  # cli-wins, or error mode with matching values
            try:
                coerced = _coerce_config_value(config_data[param], f)
            except ValueError as e:
                raise _ParseError(
                    f"--{f.name}: config value error: {e}"
                )
            if f.unique and isinstance(coerced, list):
                dup = _find_duplicate(coerced)
                if dup is not None:
                    raise _ParseError(
                        f"--{f.name}: config value error: "
                        f"duplicate value "
                        f"'{_format_value_for_error(dup)}'"
                    )
            cli_set[f.name] = coerced
            config_names.add(f.name)

    # Step 4.3: config-conflict detection for GLOBAL flags parsed AFTER the
    # command name (`tool cmd --global X`). This is CONFLICT-DETECTION ONLY:
    # config values for globals were already APPLIED during the pre-command
    # global-flag pass (_parse_global_flags), so applying them again here would
    # be a second application site -- wrong even if idempotent. We must never
    # write a config value into cli_set for a global here. Globals that reach
    # cli_set at this point are purely CLI-parsed (post-command env for globals
    # is never resolved here), so the divergence source is always "cli".
    if config_data and not hermetic and global_flags:
        for f in global_flags:
            if f.name not in cli_set:
                continue
            param = _flag_param_name(f.name)
            if param not in config_data:
                continue
            effective_mode = (
                f.conflict_mode
                if not isinstance(f.conflict_mode, _MissingSentinel)
                else conflict_mode
            )
            if effective_mode != "error":
                continue
            try:
                coerced = _coerce_config_value(config_data[param], f)
            except ValueError as e:
                raise _ParseError(f"--{f.name}: config value error: {e}")
            if not _values_equal_for_conflict(cli_set[f.name], coerced, f):
                raise _ParseError(
                    f"flag '{f.name}' set in both cli and config; remove one"
                )

    # Wrap cli_set into a _SourcedStore with proper source attribution.
    # CLI-parsed values are _Source.CLI, env-resolved values are _Source.ENV,
    # and config-resolved values are _Source.CONFIG.
    store = _SourcedStore()
    for k, v in cli_set.items():
        if k in env_names:
            store.set(k, v, _Source.ENV)
        elif k in config_names:
            store.set(k, v, _Source.CONFIG)
        else:
            store.set(k, v, _Source.CLI)

    return _validate_and_build_kwargs(cmd, store, positionals, global_flag_names, infra_roots)


def _flag_param_name(flag_name: str) -> str:
    """Convert a flag name like '--dry-run' to a Python parameter name 'dry_run'.

    If the result is a Python keyword (e.g. 'global', 'class'), appends '_'
    per PEP 8 convention (e.g. 'global_', 'class_').
    """
    name = flag_name.lstrip("-").replace("-", "_")
    if keyword.iskeyword(name):
        name += "_"
    return name


def _build_and_validate_command(
    name: str,
    *,
    help: str,
    effect: str | None,
    consequential: bool = False,
    dry_run_supported: bool = True,
    dry_run_unsupported_reason: str | None = None,
    payload_schema: dict | None = None,
    handler: Callable,
    args: list[Arg] | None,
    flag_sets: list[FlagSet] | None,
    mutex: list[MutexGroup] | None,
    dependencies: list[CoRequired | Requires | Implies] | None = None,
    env_prefix: str | None,
    global_flags: list[Flag] | None = None,
    passthrough: Passthrough | None = None,
    grants: list[Grant] | None = None,
    forwarding: Forwarding | None = None,
    framework_internal: bool = False,
    extra_flags: list[Flag] | None = None,
    tags: set[str] | None = None,
    inherited_tags: frozenset[str] | None = None,
    hidden: bool = False,
    interactive: bool = False,
    config_fields: list[str] | None = None,
    config_fields_ref: dict[str, ConfigField] | None = None,
    infra_root_names: frozenset[str] | None = None,
    connection_env_names: frozenset[str] | None = None,
) -> Command:
    """Build a Command from a decorated handler, validate everything.

    This is the single registration path: every command in every app -- including
    strictcli's own framework-internal ``check`` and ``config`` commands -- is
    built here, so classification, signature validation and flag validation are
    unbypassable.
    """
    if not help or not help.strip():
        raise ValueError(f'command "{name}": missing help text')

    # Classification is mandatory and has no default.
    if effect is None:
        _raise_command_effect_missing(name)
    if effect not in _EFFECT_VALUES:
        _raise_command_effect_invalid(name, effect)

    # A read_only command cannot be consequential: it changes nothing, so
    # there is nothing to interrupt anyone for (contract §8.1).
    if consequential and effect == EFFECT_READ_ONLY:
        _raise_command_read_only_consequential(name)

    # The dry-run declaration: illegal on read_only, mandatory reason, and no
    # orphan reason. Checked here as well as in Command.__post_init__ so the
    # message names the command before any later validation can fire.
    _validate_dry_run_declaration(
        name, effect, dry_run_supported, dry_run_unsupported_reason,
    )

    resolved_grants = _validate_grants(name, grants)

    # Declared forwarding: the reason is mandatory and non-empty.
    if forwarding is not None:
        if not isinstance(forwarding.reason, str) or not forwarding.reason.strip():
            _raise_forwarding_reason_empty(name)

    # The framework-internal marker is only claimable by handlers defined in
    # this module. A consumer that reaches the marker by any route -- monkey-
    # patching, reflection, subclassing -- fails loudly here rather than
    # silently inheriting a framework exemption.
    if framework_internal:
        if getattr(handler, "__module__", None) != __name__:
            _raise_framework_internal_handler_foreign(name)

    effective_tags = (inherited_tags or frozenset()) | frozenset(tags or set())

    # Validate config_fields bindings (before passthrough check so both paths get it)
    resolved_config_fields: tuple[str, ...] = ()
    if config_fields:
        if config_fields_ref is None:
            config_fields_ref = {}
        for cf_name in config_fields:
            if cf_name not in config_fields_ref:
                raise ValueError(
                    f'command "{name}": config_fields references unknown '
                    f'config field "{cf_name}"'
                )
        resolved_config_fields = tuple(config_fields)

    # Passthrough commands must not have flags, args, flag sets, or mutex groups
    if passthrough is not None:
        decorator_flags = list(getattr(handler, "_strictcli_flags", []))
        decorator_args = list(getattr(handler, "_strictcli_args", []))
        has_flags = bool(decorator_flags)
        has_args = bool(args) or bool(decorator_args)
        has_flag_sets = bool(flag_sets)
        has_mutex = bool(mutex)
        if has_flags or has_args or has_flag_sets or has_mutex:
            parts = []
            if has_flags:
                parts.append("flags")
            if has_args:
                parts.append("args")
            if has_flag_sets:
                parts.append("flag sets")
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
            effect=effect,
            consequential=consequential,
            dry_run_supported=dry_run_supported,
            dry_run_unsupported_reason=dry_run_unsupported_reason,
            payload_schema=payload_schema,
            passthrough=passthrough,
            tags=effective_tags,
            hidden=hidden,
            interactive=interactive,
            config_fields=resolved_config_fields,
            grants=resolved_grants,
            forwarding=forwarding,
            _framework_internal=framework_internal,
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

    # Merge flag sets into flags
    resolved_flag_sets = list(flag_sets) if flag_sets else []
    flag_set_flags: list[Flag] = []
    for flag_set in resolved_flag_sets:
        flag_set_flags.extend(flag_set.flags)

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

    # All flags: decorator flags + flag set flags + mutex flags + extra flags
    all_flags = decorator_flags + flag_set_flags + mutex_flags
    if extra_flags:
        all_flags.extend(extra_flags)

    # Validate: no duplicate flag names (catches mutex flags overlapping with
    # regular flags or flag set flags)
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

    # Validate: a command flag colliding with a config field (validation-only
    # coexistence) must have an agreeing default. Config fields registered after
    # this command are checked from the App.config_field() side instead.
    if config_fields_ref:
        for f in all_flags:
            cf = config_fields_ref.get(_flag_param_name(f.name))
            if cf is not None:
                _check_flag_configfield_default(f.name, f.default, cf)

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

    # The first parameter is always the context slot: the framework injects a
    # Context as the handler's first positional argument at dispatch time. It
    # is never matched against a flag or arg, and needs no annotation.
    params_list = list(sig.parameters.values())
    if params_list:
        param_names.discard(params_list[0].name)

    expected_names: set[str] = set()
    for f in all_flags:
        expected_names.add(_flag_param_name(f.name))
    for a in all_args:
        expected_names.add(a.name)
    # Global flags are also passed to handlers
    if global_flags:
        for gf in global_flags:
            expected_names.add(_flag_param_name(gf.name))

    # Guard v2: a **kwargs handler no longer gets a blanket exemption from the
    # "declare everything" guarantee. It must declare forwarding, which waives
    # ONLY the signature cross-check -- flags and args are still fully declared
    # and still fully parsed.
    if has_var_keyword and forwarding is None:
        _raise_handler_var_keyword_undeclared(name)

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

    # Validate flag-default RelativeToRoot markers against declared roots.
    _root_names = infra_root_names or frozenset()
    for f in all_flags:
        if isinstance(f.default, RelativeToRoot) and f.default.env_var not in _root_names:
            raise ValueError(
                f'command "{name}": flag "{f.name}": RelativeToRoot references '
                f'undeclared infra root "{f.default.env_var}"; declare it as an infra root'
            )

    # Validate connection-URL bindings against declared connection envs.
    _conn_names = connection_env_names or frozenset()
    for f in all_flags:
        _validate_connection_binding(f, _conn_names)

    return Command(
        name=name,
        help=help,
        handler=handler,
        effect=effect,
        consequential=consequential,
        dry_run_supported=dry_run_supported,
        dry_run_unsupported_reason=dry_run_unsupported_reason,
        payload_schema=payload_schema,
        flags=tuple(all_flags),
        args=tuple(all_args),
        flag_sets=tuple(resolved_flag_sets),
        mutex=tuple(resolved_mutex),
        dependencies=tuple(resolved_dependencies),
        tags=effective_tags,
        hidden=hidden,
        interactive=interactive,
        config_fields=resolved_config_fields,
        grants=resolved_grants,
        forwarding=forwarding,
        _framework_internal=framework_internal,
    )


def flag(
    name: str,
    *,
    short: str | None = None,
    type: type = str,
    default: object = _MISSING,
    help: str,
    env: str | None = None,
    env_separator: str | None = None,
    prefixed: bool = True,
    negatable: object = _MISSING,
    choices: list | None = None,
    validate: Callable | None = None,
    repeatable: bool = False,
    unique: object = _MISSING,
    conflict_mode: object = _MISSING,
    connection_url: bool = False,
    connection_env: str | None = None,
) -> Callable[[F], F]:
    """Module-level decorator to attach a Flag to a command handler."""

    def decorator(func: F) -> F:
        f = Flag(
            name=name,
            short=short,
            type=type,
            default=default,
            help=help,
            env=env,
            env_separator=env_separator,
            prefixed=prefixed,
            negatable=negatable,
            choices=choices,
            validate=validate,
            repeatable=repeatable,
            unique=unique,
            conflict_mode=conflict_mode,
            connection_url=connection_url,
            connection_env=connection_env,
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
    type: type = str,
    choices: list | None = None,
) -> Callable[[F], F]:
    """Module-level decorator to attach an Arg to a command handler."""

    def decorator(func: F) -> F:
        a = Arg(
            name=name, help=help, required=required, default=default,
            variadic=variadic, type=type, choices=choices,
        )
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

    visible_commands = {n: c for n, c in app._commands.items() if not c.hidden}
    if visible_commands:
        lines.append("")
        lines.append("Commands:")
        names = list(visible_commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = visible_commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    visible_groups = {n: g for n, g in app._groups.items() if not g.hidden}
    if visible_groups:
        lines.append("")
        lines.append("Groups:")
        names = list(visible_groups.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            grp = visible_groups[name]
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

    if app._global_flags:
        lines.append("")
        lines.append("Global flags:")
        flag_strs = []
        for f in app._global_flags:
            parts = [f"--{f.name}"]
            if f.short:
                parts.append(f"-{f.short}")
            flag_strs.append((", ".join(parts), f.help))
        max_flag_len = max(len(s[0]) for s in flag_strs)
        for flag_str, help_text in flag_strs:
            padding = max_flag_len - len(flag_str) + 4
            lines.append(f"  {flag_str}{' ' * padding}{help_text}")

    if app._infra_root_order or app._handshake_order or app._connection_order:
        lines.append("")
        lines.append("Infrastructure:")
        lines.append("  (location/handshake env vars; not suppressed by --hermetic)")
        all_evs = list(app._infra_root_order) + list(app._handshake_order) + list(app._connection_order)
        max_len = max(len(ev) for ev in all_evs)
        for ev in app._infra_root_order:
            padding = max_len - len(ev) + 4
            lines.append(f"  {ev}{' ' * padding}root (default: {app._infra_root_defaults[ev]})")
        for ev in app._handshake_order:
            padding = max_len - len(ev) + 4
            lines.append(f"  {ev}{' ' * padding}{app._handshake_envs[ev]}")
        for ev in app._connection_order:
            padding = max_len - len(ev) + 4
            lines.append(f"  {ev}{' ' * padding}connection URL, suppressed by --hermetic ({app._connection_envs[ev]})")

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

    visible_commands = {n: c for n, c in group.commands.items() if not c.hidden}
    if visible_commands:
        lines.append("")
        lines.append("Commands:")
        names = list(visible_commands.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            cmd = visible_commands[name]
            padding = max_len - len(name) + 4
            lines.append(f"  {name}{' ' * padding}{cmd.help}")

    visible_groups = {n: g for n, g in group._groups.items() if not g.hidden}
    if visible_groups:
        lines.append("")
        lines.append("Groups:")
        names = list(visible_groups.keys())
        max_len = max(len(n) for n in names)
        for name in names:
            sub = visible_groups[name]
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
    if f.type is bool and f.negatable and f.compound == "scalar":
        parts.append(f"--{f.name}, --no-{f.name}")
        if f.short:
            parts.append(f"-{f.short}")
    else:
        parts.append(f"--{f.name}")
        if f.short:
            parts.append(f"-{f.short}")
    spec = ", ".join(parts)
    if f.compound == "list":
        type_name = _TYPE_NAMES.get(f.item_type, "str")
        spec += f" <{type_name}>"
    elif f.compound == "dict":
        type_name = _TYPE_NAMES.get(f.value_type, "str")
        spec += f" <key={type_name}>"
    elif f.type is str:
        spec += " <str>"
    elif f.type is int:
        spec += " <int>"
    elif f.type is float:
        spec += " <float>"
    return spec


def _build_flag_meta(f: Flag) -> str:
    """Build the bracketed metadata suffix for a flag."""
    meta_parts: list[str] = []
    if f.compound == "list":
        meta_parts.append("list")
    elif f.compound == "dict":
        meta_parts.append("dict")
    elif f.repeatable:
        meta_parts.append("repeatable")
    if f.unique is True:
        meta_parts.append("unique")
    if f.choices is not None:
        choices_str = ", ".join(str(c) for c in f.choices)
        meta_parts.append(f"choices: {choices_str}")
    if f.env is not None:
        if f.env_separator is not None:
            meta_parts.append(f"env: {f.env} (sep: {f.env_separator})")
        else:
            meta_parts.append(f"env: {f.env}")
    if f.compound == "dict":
        # Dict flags are never required; show default only if non-empty
        if f.default:
            meta_parts.append(f"default: {_format_default_for_help(f.default)}")
    elif f.type is bool and f.compound == "scalar" and f.default is not None:
        meta_parts.append(f"default: {'true' if f.default else 'false'}")
    elif f.repeatable:
        # Repeatable flags are never required; show default only if non-empty
        if f.default:
            joined = ", ".join(_format_value_for_error(elem) for elem in f.default)
            meta_parts.append(f"default: {joined}")
    elif f.default is not None:
        meta_parts.append(f"default: {_format_default_for_help(f.default)}")
    else:
        meta_parts.append("required")
    return " [" + "] [".join(meta_parts) + "]"


def _format_dry_run_section(cmd: Command) -> list[str]:
    """The `Dry run:` section of command help, or nothing.

    Rendered only for a command that declares ``dry_run_supported=False``: the
    baseline (dry run works) needs no announcement, and a section on every
    command would be noise. Byte-identical across implementations.
    """
    if cmd.dry_run_supported:
        return []
    return [
        "",
        "Dry run:",
        f"  --dry-run is not supported: {cmd.dry_run_unsupported_reason}",
    ]


def _format_command_help(app: App, cmd: Command, prefix: str = "") -> str:
    """Format command-level help shown when the user runs 'myapp cmd --help'."""
    lines: list[str] = [f"{app.name} {prefix}{cmd.name} -- {cmd.help}"]

    # Rendered before the passthrough early-return: a passthrough command can
    # declare the refusal too, and its help is the only place the reason would
    # otherwise be visible.
    lines.extend(_format_dry_run_section(cmd))

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
            meta_parts: list[str] = []
            if a.type is not str:
                meta_parts.append(f"type: {a.type.__name__}")
            if a.choices is not None:
                choices_str = ", ".join(str(c) for c in a.choices)
                meta_parts.append(f"choices: {choices_str}")
            if not a.required:
                if not isinstance(a.default, _MissingSentinel):
                    meta_parts.append(f"default: {_format_default_for_help(a.default)}")
                else:
                    meta_parts.append("optional")
            meta = ""
            if meta_parts:
                meta = " [" + "] [".join(meta_parts) + "]"
            lines.append(f"  {dn}{' ' * padding}{help_text}{meta}")

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
# Tag DSL
# ---------------------------------------------------------------------------

_TAG_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")


def _tagdsl_tokenize(expr: str) -> list[tuple[str, str, int]]:
    """Tokenize a tag expression into (type, value, position) tuples."""
    tokens: list[tuple[str, str, int]] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "&":
            tokens.append(("AND", "&", i))
            i += 1
        elif ch == "|":
            tokens.append(("OR", "|", i))
            i += 1
        elif ch == "^":
            tokens.append(("XOR", "^", i))
            i += 1
        elif ch == "-":
            tokens.append(("DIFF", "-", i))
            i += 1
        elif ch == "!":
            tokens.append(("NOT", "!", i))
            i += 1
        elif ch == "(":
            tokens.append(("LPAREN", "(", i))
            i += 1
        elif ch == ")":
            tokens.append(("RPAREN", ")", i))
            i += 1
        else:
            m = _TAG_NAME_RE.match(expr, i)
            if m:
                tokens.append(("IDENT", m.group(), i))
                i = m.end()
            else:
                raise ValueError(
                    f'tag expression: unexpected character "{ch}" at position {i}'
                )
    return tokens


def _tagdsl_parse(tokens: list[tuple[str, str, int]]) -> tuple:
    """Parse tag expression tokens into an AST using recursive descent.

    Precedence (tightest first): NOT, AND, XOR, OR, DIFF.
    """
    pos = 0

    def peek() -> tuple[str, str, int] | None:
        nonlocal pos
        if pos < len(tokens):
            return tokens[pos]
        return None

    def consume() -> tuple[str, str, int]:
        nonlocal pos
        tok = tokens[pos]
        pos += 1
        return tok

    def end_pos() -> int:
        if not tokens:
            return 0
        last = tokens[-1]
        return last[2] + len(last[1])

    def parse_atom() -> tuple:
        tok = peek()
        if tok is None:
            raise ValueError(
                f"tag expression: unexpected end of expression "
                f"at position {end_pos()}"
            )
        if tok[0] == "NOT":
            consume()
            child = parse_atom()
            return ("not", child)
        if tok[0] == "LPAREN":
            consume()
            node = parse_diff()
            closing = peek()
            if closing is None or closing[0] != "RPAREN":
                raise ValueError(
                    f'tag expression: expected ")" at position {end_pos()}'
                )
            consume()
            return node
        if tok[0] == "IDENT":
            consume()
            return ("ident", tok[1])
        raise ValueError(
            f'tag expression: unexpected token "{tok[1]}" at position {tok[2]}'
        )

    def parse_and() -> tuple:
        left = parse_atom()
        while True:
            tok = peek()
            if tok is None or tok[0] != "AND":
                break
            consume()
            right = parse_atom()
            left = ("and", left, right)
        return left

    def parse_xor() -> tuple:
        left = parse_and()
        while True:
            tok = peek()
            if tok is None or tok[0] != "XOR":
                break
            consume()
            right = parse_and()
            left = ("xor", left, right)
        return left

    def parse_or() -> tuple:
        left = parse_xor()
        while True:
            tok = peek()
            if tok is None or tok[0] != "OR":
                break
            consume()
            right = parse_xor()
            left = ("or", left, right)
        return left

    def parse_diff() -> tuple:
        left = parse_or()
        while True:
            tok = peek()
            if tok is None or tok[0] != "DIFF":
                break
            consume()
            right = parse_or()
            left = ("diff", left, right)
        return left

    result = parse_diff()
    tok = peek()
    if tok is not None:
        raise ValueError(
            f'tag expression: unexpected token "{tok[1]}" at position {tok[2]}'
        )
    return result


def _tagdsl_evaluate(ast: tuple, tags: set[str]) -> bool:
    """Evaluate a tag DSL AST against a set of tags."""
    kind = ast[0]
    if kind == "ident":
        return ast[1] in tags
    if kind == "not":
        return not _tagdsl_evaluate(ast[1], tags)
    if kind == "and":
        return _tagdsl_evaluate(ast[1], tags) and _tagdsl_evaluate(ast[2], tags)
    if kind == "or":
        return _tagdsl_evaluate(ast[1], tags) or _tagdsl_evaluate(ast[2], tags)
    if kind == "xor":
        return _tagdsl_evaluate(ast[1], tags) != _tagdsl_evaluate(ast[2], tags)
    if kind == "diff":
        return _tagdsl_evaluate(ast[1], tags) and not _tagdsl_evaluate(ast[2], tags)
    raise ValueError(f"tag expression: unknown AST node {kind!r}")


def _match_tag_expr(expr: str, tags: set[str]) -> bool:
    """Evaluate a tag expression against a set of tags. Returns bool."""
    tokens = _tagdsl_tokenize(expr)
    if not tokens:
        raise ValueError("tag expression: empty expression")
    ast = _tagdsl_parse(tokens)
    return _tagdsl_evaluate(ast, tags)


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------


def _filter_checks(
    check_defs: dict[str, _CheckDef],
    tag_expr: str | None,
    name_glob: str | None,
    run_all: bool,
) -> set[str]:
    """Filter checks by tag expression and/or name glob.

    Returns the set of selected check names.
    """
    if run_all:
        return set(check_defs.keys())

    by_tag: set[str] | None = None
    by_name: set[str] | None = None

    if tag_expr is not None:
        by_tag = {
            name for name, cdef in check_defs.items()
            if _match_tag_expr(tag_expr, set(cdef.tags))
        }

    if name_glob is not None:
        by_name = {
            name for name in check_defs
            if fnmatch.fnmatch(name, name_glob)
        }

    if by_tag is not None and by_name is not None:
        return by_tag & by_name
    if by_tag is not None:
        return by_tag
    if by_name is not None:
        return by_name
    return set()


def _resolve_check_order(
    check_defs: dict[str, _CheckDef], selected: set[str],
) -> list[str]:
    """Resolve execution order via topological sort, pulling in dependencies.

    If a selected check depends on an unselected check, the dependency is
    pulled into the execution set. Raises ValueError on cycles.
    """
    # Expand selected to include all transitive dependencies
    expanded: set[str] = set()
    stack = list(selected)
    while stack:
        name = stack.pop()
        if name in expanded:
            continue
        expanded.add(name)
        for dep in check_defs[name].depends_on:
            if dep not in expanded:
                stack.append(dep)

    # Build adjacency and in-degree for Kahn's algorithm
    in_degree: dict[str, int] = {name: 0 for name in expanded}
    dependents: dict[str, list[str]] = {name: [] for name in expanded}

    for name in expanded:
        for dep in check_defs[name].depends_on:
            if dep in expanded:
                dependents[dep].append(name)
                in_degree[name] += 1

    # Kahn's algorithm
    queue: deque[str] = deque(
        name for name in sorted(expanded) if in_degree[name] == 0
    )
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(dependents[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(order) != len(expanded):
        # Cycle detection: find a cycle for the error message
        remaining = expanded - set(order)
        cycle = _find_cycle(check_defs, remaining)
        raise ValueError(f"check dependency cycle: {cycle}")

    return order


def _find_cycle(
    check_defs: dict[str, _CheckDef], nodes: set[str],
) -> str:
    """Find and format a cycle among the given nodes for error reporting."""
    # DFS to find a cycle path
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> str | None:
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for dep in check_defs[node].depends_on:
            if dep not in nodes:
                continue
            if dep in path_set:
                # Found cycle: extract from dep to current node back to dep
                cycle_start = path.index(dep)
                cycle_path = path[cycle_start:] + [dep]
                return " -> ".join(cycle_path)
            if dep not in visited:
                result = dfs(dep)
                if result:
                    return result
        path.pop()
        path_set.discard(node)
        return None

    for node in sorted(nodes):
        if node not in visited:
            result = dfs(node)
            if result:
                return result
    return " -> ".join(sorted(nodes))


def _check_is_pure(cdef: _CheckDef) -> bool:
    """Whether a check is executable under the purity partition: declared pure
    AND not requiring network access. Everything else is "impure"."""
    return cdef.pure and not cdef.needs_network


def _run_checks(
    check_defs: dict,
    check_names: list[str],
    context: CheckContext,
    ignore_warnings: bool,
    scope_adapter: object | None = None,
    pure_only: bool = False,
) -> tuple[list[tuple[str, _CheckOutcome, int]], list[str], int]:
    """Execute checks in order, skipping dependents of gated (FAIL) checks.

    Returns (results_list, impure_listed, exit_code). Each results_list entry is
    (name, outcome, duration_ms) where duration_ms is the wall-clock time in
    integer milliseconds spent inside the impl (0 for non-executed checks).
    impure_listed holds the
    ordered names of checks left unexecuted by the purity partition (empty
    unless pure_only=True); listed checks contribute nothing to the exit code.
    exit_code is 0 if all executed checks pass (or all warn with
    ignore_warnings=True), 1 otherwise.

    Purity partition (pure_only): only pure, non-network checks execute; every
    other check is listed. A check also joins the listing if any dependency was
    listed (its precondition cannot be verified). The failed-dependency cascade
    takes precedence over the listing.
    """
    results: list[tuple[str, _CheckOutcome, int]] = []
    # Checks whose dependents should be cascade-skipped: cascade keys ONLY on a
    # derived FAIL (an error-severity problem present) or a cascade-skip. A WARN
    # outcome satisfies the dependency (dependents still run) and only affects
    # the exit code -- warn-severity checks physically cannot cascade because
    # WarnReporter lacks error-minting. An explicit SKIP is not a failure.
    failed_checks: set[str] = set()
    # Checks listed (not executed) under the purity partition, so dependents
    # whose precondition cannot be verified join the listing.
    listed_checks: set[str] = set()
    impure_listed: list[str] = []
    exit_code = 0

    def record(name: str, outcome: _CheckOutcome) -> None:
        nonlocal exit_code
        status = _derive_status(outcome)
        if status == "fail":
            failed_checks.add(name)
            exit_code = 1
        elif status == "warn":
            if not ignore_warnings:
                exit_code = 1
        # "pass" / "skip": no cascade, no exit code change.

    for name in check_names:
        cdef = check_defs[name]

        # Check if any dependency failed
        failed_dep = None
        for dep in cdef.depends_on:
            if dep in failed_checks:
                failed_dep = dep
                break

        if failed_dep is not None:
            outcome = _mint_skip(f'skipped: dependency "{failed_dep}" failed')
            failed_checks.add(name)
            results.append((name, outcome, 0))
            exit_code = 1
            continue

        # Purity partition: list (do not execute) impure checks and any check
        # that depends on a listed one. Listed checks contribute no exit code.
        if pure_only:
            listed = not _check_is_pure(cdef)
            if not listed:
                listed = any(dep in listed_checks for dep in cdef.depends_on)
            if listed:
                listed_checks.add(name)
                impure_listed.append(name)
                continue

        # Apply scope adapter if the check has a scope and an adapter is set.
        # The adapter returns a replacement context OR a SkipCheck directive.
        check_context = context
        if cdef.scope and scope_adapter is not None:
            adapted = scope_adapter(context, cdef.scope)
            if isinstance(adapted, SkipCheck):
                outcome = _mint_skip(f"skipped: {adapted.reason}")
                results.append((name, outcome, 0))
                # Explicit skip: no cascade, no exit code change.
                continue
            # A non-SkipCheck return is used as the check's replacement context.
            # Enforce the adapter contract: it must satisfy the CheckContext
            # protocol (expose a project_root attribute). Anything else is a
            # hard error rather than a bogus context silently handed to the impl.
            if not hasattr(adapted, "project_root"):
                raise TypeError(
                    f'scope adapter for check "{name}" returned {adapted!r}; a '
                    f"scope adapter must return a SkipCheck or a CheckContext "
                    f"(an object exposing a project_root attribute)"
                )
            check_context = adapted

        # Capture wall-clock duration around the impl call only.
        _start = time.perf_counter()
        try:
            outcome = cdef.impl(check_context)
        except Exception as exc:  # noqa: BLE001 -- containment is the point
            # A raising impl is contained here and reported as that check's own
            # failure: one broken check must not abort the whole run, and every
            # other selected check still executes. BaseException (a
            # KeyboardInterrupt, a SystemExit) is deliberately NOT contained --
            # those are the operator ending the process, not a broken check.
            duration_ms = int((time.perf_counter() - _start) * 1000)
            outcome = _mint_check_abort(name, exc)
            results.append((name, outcome, duration_ms))
            record(name, outcome)
            continue
        duration_ms = int((time.perf_counter() - _start) * 1000)
        # Belt-and-braces: an impl must return a reporter-minted outcome.
        if not isinstance(outcome, _CheckOutcome):
            raise TypeError(
                f'check "{name}" returned {outcome!r}, not an outcome minted by '
                f"its reporter (use passed/skipped/found)"
            )
        results.append((name, outcome, duration_ms))
        record(name, outcome)

    return results, impure_listed, exit_code


# ---------------------------------------------------------------------------
# Check command output helpers
# ---------------------------------------------------------------------------

_CHECK_STATUS_LABELS = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}


def _check_list_items(check_defs: dict[str, _CheckDef]) -> list[dict]:
    """The check listing as machine data (the check command's payload)."""
    items = []
    for cdef in sorted(check_defs.values(), key=lambda c: c.name):
        entry: dict = {"name": cdef.name, "tags": cdef.tags, "severity": cdef.severity}
        if cdef.scope:
            entry["scope"] = cdef.scope
        items.append(entry)
    return items


def _check_list_mode(check_defs: dict[str, _CheckDef]) -> None:
    """Print the human-readable check listing."""
    # Sort alphabetically for deterministic output matching Go
    sorted_defs = sorted(check_defs.values(), key=lambda c: c.name)

    if not check_defs:
        print("No checks defined.")
        return

    # Compute column widths
    name_width = max(len(cdef.name) for cdef in sorted_defs)
    name_width = max(name_width, len("NAME"))
    tags_width = max(len(", ".join(cdef.tags)) for cdef in sorted_defs)
    tags_width = max(tags_width, len("TAGS"))

    header = f"{'NAME':<{name_width}}   {'TAGS':<{tags_width}}   SEVERITY"
    print(header)
    for cdef in sorted_defs:
        tags_str = ", ".join(cdef.tags)
        print(f"{cdef.name:<{name_width}}   {tags_str:<{tags_width}}   {cdef.severity}")


def _check_dry_run_mode(
    check_defs: dict[str, _CheckDef], listed: list[str], order: list[str],
) -> None:
    """Print the would-run plan for the checks a dry run did NOT execute.

    ``listed`` is the purity partition's remainder (the impure checks and any
    check whose dependency was listed); ``order`` is the full selected order,
    used only to decide which dependencies are worth naming. The header is
    printed even when nothing was left over -- an empty plan is a statement
    ("everything selected ran"), the same way the framework's own would-do log
    prints its header with an empty body.
    """
    print(f"Would run {len(listed)} check{'s' if len(listed) != 1 else ''}:")
    for i, name in enumerate(listed, 1):
        cdef = check_defs[name]
        purity = "pure" if _check_is_pure(cdef) else "impure"
        deps = [d for d in cdef.depends_on if d in set(order)]
        if deps:
            print(f"  {i}. {name} (depends on: {', '.join(deps)}) [{purity}]")
        else:
            print(f"  {i}. {name} [{purity}]")



def format_check_results(
    results: list[CheckRunResult], verbose: bool = False,
) -> str:
    """Format check results as a human-readable aligned string.

    Shows the derived status label, name, and message, with minted problems
    listed under the check row grouped by severity (error problems first, then
    warn problems), each tagged with its severity. Problems appear for
    fail/warn/skip outcomes or when verbose is True.
    """
    if not results:
        return ""

    name_width = max(len(r.name) for r in results)
    lines: list[str] = []
    counts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}

    for r in results:
        status = r.status
        counts[status] += 1
        label = _CHECK_STATUS_LABELS[status]
        row = f"{label}  {r.name:<{name_width}}    {r.outcome.message}"
        # Under --verbose, append the per-check duration in a stable, pattern-
        # matchable shape: "(<n>ms)".
        if verbose:
            row += f" ({r.duration_ms}ms)"
        lines.append(row)

        show_problems = verbose or status in ("fail", "warn", "skip")
        if show_problems:
            for p in r.outcome._ordered_problems():
                lines.append(f"        [{p.severity}] {p.text}")
        # Notes are verdict-inert and surface ONLY under --verbose, on every
        # outcome including a pass.
        if verbose:
            for n in r.outcome.notes:
                lines.append(f"        [note] {n}")

    # Under --verbose, append a trailing blank line and a count summary.
    if verbose:
        lines.append("")
        lines.append(
            f"{counts['pass']} passed / {counts['fail']} failed / "
            f"{counts['warn']} warned / {counts['skip']} skipped"
        )

    return "\n".join(lines)


def _check_result_items(results: list[CheckRunResult]) -> list[dict]:
    """Check results as machine data (the check command's run payload).

    Each entry carries the derived status plus the minted problems (each with
    its severity and text). Problems serialize as [] when empty.
    """
    return [
        {
            "name": r.name,
            "status": r.status,
            "message": r.outcome.message,
            "problems": [
                {"severity": p.severity, "text": p.text}
                for p in r.outcome.problems
            ],
            "notes": list(r.outcome.notes),
            "duration_ms": r.duration_ms,
        }
        for r in results
    ]


def format_check_results_json(results: list[CheckRunResult]) -> str:
    """Format check results as a JSON string."""
    return json.dumps(_check_result_items(results), separators=(",", ":"))


# ---------------------------------------------------------------------------
# Schema serialization (--dump-schema)
# ---------------------------------------------------------------------------

_TYPE_NAMES = {str: "str", bool: "bool", int: "int", float: "float"}


def _serialize_flag(f: Flag) -> dict:
    """Serialize a Flag to a JSON-serializable dict.

    Identity fields (name, type, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    # Compound type serialization
    if f.compound == "list":
        type_obj = {
            "type": "array",
            "items": {"type": _TYPE_NAMES[f.item_type]},
        }
    elif f.compound == "dict":
        type_obj = {
            "type": "object",
            "additionalProperties": {"type": _TYPE_NAMES[f.value_type]},
        }
    else:
        type_obj = _TYPE_NAMES[f.type]

    d: dict = {
        "name": f.name,
        "type": type_obj,
        "help": f.help,
    }
    if f.short is not None:
        d["short"] = f.short
    # A RelativeToRoot marker default is serialized machine-stably: only the
    # declared env var and path parts (no resolved, machine-specific path). This
    # shape is identical across the Python and Go implementations.
    if isinstance(f.default, RelativeToRoot):
        d["default"] = _serialize_marker(f.default)
    # For dict flags, only emit default if non-empty
    elif f.compound == "dict":
        if f.default:
            d["default"] = f.default
    elif f.default is not None:
        # For list (repeatable) flags, only emit if non-empty
        if f.compound == "list" and isinstance(f.default, list) and not f.default:
            pass  # omit empty list default
        else:
            d["default"] = f.default
    if f.env is not None:
        d["env"] = f.env
    if f.choices is not None:
        d["choices"] = f.choices
    if f.repeatable and f.compound != "list":
        # Only emit repeatable for plain repeatable flags, not list[T] flags
        d["repeatable"] = f.repeatable
    if f.unique is True:
        d["unique"] = True
    # Per-flag conflict mode: serialized only when explicitly set (omitted when
    # inheriting the app default). This is additive; schema_version stays 1, so
    # consumers get no version signal for this field -- they must treat its
    # absence as "inherit the app-level config_conflict_mode".
    if not isinstance(f.conflict_mode, _MissingSentinel):
        d["conflict_mode"] = f.conflict_mode
    if f.env_separator is not None:
        d["env_separator"] = f.env_separator
    negatable = f.negatable if f.type is bool and f.compound == "scalar" else None
    if negatable is not None:
        d["negatable"] = negatable
    # hidden is currently always False, so always omitted
    return d


def _serialize_arg(a: Arg) -> dict:
    """Serialize an Arg to a JSON-serializable dict.

    Identity fields (name, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    d: dict = {
        "name": a.name,
        "help": a.help,
    }
    # Compound type serialization for args
    if a.compound == "list":
        d["type"] = {
            "type": "array",
            "items": {"type": _TYPE_NAMES[a.item_type]},
        }
    elif a.type is not str:
        d["type"] = a.type.__name__
    if not a.required:
        d["required"] = a.required
    if not isinstance(a.default, _MissingSentinel):
        d["default"] = a.default
    if a.variadic:
        d["variadic"] = a.variadic
    if a.choices is not None:
        d["choices"] = a.choices
    return d


def _deep_sorted(value: object) -> object:
    """Recursively sort dict keys, matching Go's map marshaling.

    Used by the framework's own machine payloads so the three implementations
    emit byte-identical documents; a consumer's payload is emitted exactly as
    it was supplied.
    """
    if isinstance(value, dict):
        return {k: _deep_sorted(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_deep_sorted(v) for v in value]
    return value


def _serialize_command(cmd: Command) -> dict:
    """Serialize a Command to a JSON-serializable dict.

    Identity fields (name, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    d: dict = {
        "name": cmd.name,
        "help": cmd.help,
        # Always emitted: classification is mandatory, so there is no default
        # to omit against.
        "effect": cmd.effect,
    }
    # Omitted when false: consequential is NOT mandatory, and absence means
    # "not consequential" (contract §8.1, §13).
    if cmd.consequential:
        d["consequential"] = True
    # Emitted only when declared: dry run is supported unless a command says
    # otherwise, so the pair appears exactly on the commands that refuse it.
    if not cmd.dry_run_supported:
        d["dry_run_supported"] = False
        d["dry_run_unsupported_reason"] = cmd.dry_run_unsupported_reason
    # The payload contract, published verbatim (contract §19.5): the inline
    # literal is the sole canonical artifact, so the dump carries it as
    # written rather than a re-rendering of it.
    if cmd.payload_schema is not None:
        d["payload_schema"] = cmd.payload_schema
    if cmd.passthrough is not None:
        d["passthrough"] = True
    flags = [_serialize_flag(f) for f in cmd.flags]
    if flags:
        d["flags"] = flags
    args = [_serialize_arg(a) for a in cmd.args]
    if args:
        d["args"] = args
    tags = sorted(cmd.tags)
    if tags:
        d["tags"] = tags
    constraints: list[dict] = []
    for mg in cmd.mutex:
        constraints.append({
            "type": "mutex",
            "flags": [f.name for f in mg.flags],
        })
    for dep in cmd.dependencies:
        if isinstance(dep, CoRequired):
            constraints.append({
                "type": "co_required",
                "flags": dep.flags,
            })
        elif isinstance(dep, Requires):
            constraints.append({
                "type": "requires",
                "flag": dep.flag,
                "depends_on": dep.depends_on,
            })
        elif isinstance(dep, Implies):
            constraints.append({
                "type": "implies",
                "flag": dep.flag,
                "implies": dep.implies,
                "value": dep.value,
            })
    if constraints:
        d["constraints"] = constraints
    if cmd.hidden:
        d["hidden"] = True
    if cmd.interactive:
        d["interactive"] = True
    if cmd.config_fields:
        d["config_fields"] = list(cmd.config_fields)
    if cmd.grants:
        d["grants"] = [
            {"name": g.name, "reason": g.reason, "kind": g.kind}
            for g in cmd.grants
        ]
    if cmd.forwarding is not None:
        d["forwarding"] = {"reason": cmd.forwarding.reason}
    return d


def _serialize_group(group: Group) -> dict:
    """Serialize a Group to a JSON-serializable dict (recursive).

    Identity fields (name, help) are always included.
    Other fields are omitted when they match the schema defaults.
    """
    d: dict = {
        "name": group.name,
        "help": group.help,
    }
    commands = {name: _serialize_command(cmd) for name, cmd in group.commands.items()}
    if commands:
        d["commands"] = commands
    groups = {name: _serialize_group(g) for name, g in group._groups.items()}
    if groups:
        d["groups"] = groups
    deprecated = {name: dep.message for name, dep in group.deprecated.items()}
    if deprecated:
        d["deprecated"] = deprecated
    tags = sorted(group.tags)
    if tags:
        d["tags"] = tags
    if group.hidden:
        d["hidden"] = True
    return d


def _build_schema_defaults() -> dict:
    """Return the defaults object documenting what 'missing' means in the schema."""
    return {
        "schema_version": 1,
        "app": {
            "env_prefix": None,
            "config": False,
            "global_flags": [],
            "commands": {},
            "groups": {},
            "deprecated": {},
            "tag_contracts": {},
        },
        "flag": {
            "short": None,
            "default": None,
            "env": None,
            "choices": None,
            "repeatable": False,
            "unique": False,
            "env_separator": None,
            "negatable": None,
            "hidden": False,
        },
        "arg": {
            "type": "str",
            "required": True,
            "default": None,
            "variadic": False,
            "choices": None,
        },
        "command": {
            "passthrough": False,
            "flags": [],
            "args": [],
            "tags": [],
            "constraints": [],
            "hidden": False,
            "interactive": False,
        },
        "group": {
            "commands": {},
            "groups": {},
            "deprecated": {},
            "tags": [],
            "hidden": False,
        },
    }


def _read_project_id() -> str:
    """Read project name from pyproject.toml in the current working directory."""
    pyproject_path = Path(os.getcwd()) / "pyproject.toml"
    if not pyproject_path.exists():
        raise RuntimeError(
            "Cannot determine project_id: pyproject.toml not found "
            "or missing [project].name"
        )
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    project_name = data.get("project", {}).get("name")
    if not project_name:
        raise RuntimeError(
            "Cannot determine project_id: pyproject.toml not found "
            "or missing [project].name"
        )
    return project_name


def _collect_config_field_bindings(
    commands: dict[str, Command],
    bindings: dict[str, list[str]],
    path: list[str],
) -> None:
    """Walk commands and record which commands bind each config field."""
    for cmd in commands.values():
        cmd_path = " ".join(path + [cmd.name])
        for cf_name in cmd.config_fields:
            if cf_name in bindings:
                bindings[cf_name].append(cmd_path)


def _collect_config_field_bindings_from_group(
    group: Group,
    bindings: dict[str, list[str]],
    path: list[str],
) -> None:
    """Recursively walk groups to collect config field bindings."""
    group_path = path + [group.name]
    _collect_config_field_bindings(group.commands, bindings, group_path)
    for sub in group._groups.values():
        _collect_config_field_bindings_from_group(sub, bindings, group_path)


def _dump_schema_core(app: App) -> dict:
    """Build the full schema dict, excluding ``project_id``.

    This is the CWD-free, filesystem-free core of schema production. It reads
    only the in-memory ``App`` (name, version, help, flags, commands, groups,
    etc.). ``project_id`` is added later by the file-writer path, since it is
    the only field that requires reading ``pyproject.toml`` from the CWD.

    Fields whose values match the schema defaults are omitted. The top-level
    ``defaults`` key documents what each missing field means.
    """
    schema: dict = {
        "schema_version": 1,
        "defaults": _build_schema_defaults(),
        "name": app.name,
        "version": app.version,
        "help": app.help,
    }
    if app.env_prefix is not None:
        schema["env_prefix"] = app.env_prefix
    if app.config:
        schema["config"] = app.config
    if app._proc_observe_allowlist:
        schema["proc_observe_allowlist"] = [
            list(prefix) for prefix in app._proc_observe_allowlist
        ]
    global_flags = [_serialize_flag(f) for f in app._global_flags]
    if global_flags:
        schema["global_flags"] = global_flags
    commands = {name: _serialize_command(cmd) for name, cmd in app._commands.items()}
    if commands:
        schema["commands"] = commands
    groups = {name: _serialize_group(grp) for name, grp in app._groups.items()}
    if groups:
        schema["groups"] = groups
    deprecated = {name: dep.message for name, dep in app._deprecated.items()}
    if deprecated:
        schema["deprecated"] = deprecated
    if app._tag_contracts:
        schema["tag_contracts"] = dict(app._tag_contracts)
    if app._checks_enabled:
        checks_schema: dict = {}
        for name, cdef in app._check_defs.items():
            entry = {
                "tags": cdef.tags,
                "severity": cdef.severity,
                "fast": cdef.fast,
                "pure": cdef.pure,
                "needs_network": cdef.needs_network,
                "depends_on": cdef.depends_on,
            }
            if cdef.scope:
                entry["scope"] = cdef.scope
            checks_schema[name] = entry
        schema["checks"] = checks_schema
    if app._config_fields:
        # Build field definitions with bound command info
        cf_schema: dict = {}
        # Collect which commands bind each field
        bindings: dict[str, list[str]] = {
            name: [] for name in app._config_fields
        }
        _collect_config_field_bindings(app._commands, bindings, [])
        for grp in app._groups.values():
            _collect_config_field_bindings_from_group(grp, bindings, [])

        for name, cf in app._config_fields.items():
            entry: dict = {
                "type": cf.type.__name__,
                "help": cf.help,
                "required": cf.required,
            }
            if not isinstance(cf.default, _MissingSentinel):
                entry["default"] = cf.default
            if bindings.get(name):
                entry["bound_commands"] = bindings[name]
            cf_schema[name] = entry
        schema["config_fields"] = cf_schema
    # infra: only present when roots or handshake vars are declared. Resolved
    # root values are intentionally EXCLUDED -- the schema must be machine-stable
    # (not machine-specific). Only the declared env var and default path (both
    # stable declarations) are emitted for roots.
    if app._infra_root_order or app._handshake_order or app._connection_order:
        infra: dict = {}
        if app._infra_root_order:
            infra["roots"] = [
                {"env_var": ev, "default": app._infra_root_defaults[ev]}
                for ev in app._infra_root_order
            ]
        if app._handshake_order:
            infra["handshakes"] = [
                {"env_var": ev, "help": app._handshake_envs[ev]}
                for ev in app._handshake_order
            ]
        if app._connection_order:
            infra["connections"] = [
                {"env_var": ev, "help": app._connection_envs[ev]}
                for ev in app._connection_order
            ]
        schema["infra"] = infra
    return schema


def _dump_schema(app: App) -> dict:
    """Produce the full schema dict including ``project_id`` (reads the CWD).

    Delegates the bulk of the work to :func:`_dump_schema_core` and inserts
    ``project_id`` immediately after ``defaults`` so the on-disk layout is
    stable and byte-identical to the core dict once ``project_id`` is removed.
    """
    core = _dump_schema_core(app)
    project_id = _read_project_id()
    result: dict = {}
    for key, value in core.items():
        result[key] = value
        if key == "defaults":
            result["project_id"] = project_id
    return result


def _check_schema_project_id(file_path: str, new_project_id: str) -> None:
    """Verify that an existing schema file belongs to the same project.

    Raises RuntimeError on mismatch. Silently passes on: missing file,
    unreadable file, JSON without project_id field, or matching project_id.
    """
    try:
        with open(file_path) as f:
            existing = json.loads(f.read())
    except (OSError, json.JSONDecodeError, ValueError):
        return
    existing_id = existing.get("project_id")
    if existing_id is None:
        return
    if existing_id != new_project_id:
        raise RuntimeError(
            f"Schema mismatch: existing schema belongs to project "
            f"'{existing_id}', not '{new_project_id}'. "
            f"Run from the correct project directory."
        )


def _write_schema(app: App) -> str:
    """Write the schema to .strictcli/schema.json and return the path."""
    schema = _dump_schema(app)
    dir_path = os.path.join(os.getcwd(), ".strictcli")
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, "schema.json")
    _check_schema_project_id(file_path, schema["project_id"])
    with open(file_path, "w") as f:
        f.write(json.dumps(schema, indent=2) + "\n")
    app._record_cache_write(file_path)
    return file_path


# MCP server (--mcp)

def _mcp_collect_commands(app: App) -> dict[str, tuple[Command, str]]:
    """Collect non-hidden, non-interactive leaf commands as {dotted_path: (cmd, help)}.

    Returns a dict mapping dotted command paths to (Command, help_text) tuples.
    """
    commands: dict[str, tuple[Command, str]] = {}

    for name, cmd in app._commands.items():
        if cmd.hidden or cmd.interactive:
            continue
        commands[name] = (cmd, cmd.help)

    def _collect_from_group(
        group: Group, path: list[str],
    ) -> None:
        if group.hidden:
            return
        for cmd_name, cmd in group.commands.items():
            if cmd.hidden or cmd.interactive:
                continue
            dotted = ".".join(path + [cmd_name])
            commands[dotted] = (cmd, cmd.help)
        for sub_name, sub_group in group._groups.items():
            _collect_from_group(sub_group, path + [sub_name])

    for group_name, group in app._groups.items():
        _collect_from_group(group, [group_name])

    return commands


def _mcp_jsonrpc_error(
    req_id: object, code: int, message: str,
) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _mcp_handle_initialize(app: App, req_id: object) -> dict:
    """Handle the MCP 'initialize' request."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": app.name,
                "version": app.version,
            },
        },
    }


def _mcp_handle_tools_list(
    app: App, commands: dict[str, tuple[Command, str]], req_id: object,
) -> dict:
    """Handle the MCP 'tools/list' request."""
    tools = []
    for dotted_path, (cmd, help_text) in commands.items():
        # The classification sits BESIDE inputSchema, never inside it: it
        # describes the tool, not an argument the caller passes. Same emission
        # rule as the schema dump -- `effect` always, `consequential` only when
        # true (absence means "not consequential").
        entry: dict = {
            "name": dotted_path,
            "description": help_text,
            "effect": cmd.effect,
            "inputSchema": _build_json_schema(cmd),
        }
        if cmd.consequential:
            entry["consequential"] = True
        tools.append(entry)
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"tools": tools},
    }


def _mcp_handle_tools_call(
    app: App,
    req_id: object,
    params: dict,
) -> dict:
    """Handle the MCP 'tools/call' request."""
    if "name" not in params:
        return _mcp_jsonrpc_error(
            req_id, -32602, "missing required parameter: name",
        )
    tool_name = params["name"]
    if not isinstance(tool_name, str):
        return _mcp_jsonrpc_error(
            req_id, -32602, "parameter 'name' must be a string",
        )

    # Unknown tools are NOT a -32602 protocol error: like Go, the name is
    # passed to app.call(), whose invocation error surfaces as tool-result
    # error content (isError) below.
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _mcp_jsonrpc_error(
            req_id, -32602, "parameter 'arguments' must be an object",
        )

    # Consent is a top-level param, a sibling of `name` and `arguments` --
    # never a member of `arguments`, which is the command's own argument
    # namespace and is published with additionalProperties: false. There is no
    # server-side default: absent means "not consented", and a consequential
    # tool is then refused.
    approve_consequential = params.get("approve_consequential", False)
    if not isinstance(approve_consequential, bool):
        return _mcp_jsonrpc_error(
            req_id, -32602,
            "parameter 'approve_consequential' must be a boolean",
        )

    try:
        result = app._call_with_kwargs(
            tool_name, dict(arguments),
            approve_consequential=approve_consequential,
        )
    except InvokeError as e:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            },
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{
                "type": "text",
                "text": json.dumps(result, default=str),
            }],
        },
    }


def _run_mcp_server(
    app: App,
    *,
    input: io.TextIOBase | None = None,
    output: io.TextIOBase | None = None,
) -> None:
    """Run the MCP JSON-RPC 2.0 server loop.

    Reads one JSON object per line from input, writes responses to output.
    Notifications (no 'id' field) get no response.
    """
    inp = input if input is not None else sys.stdin
    out = output if output is not None else sys.stdout

    commands = _mcp_collect_commands(app)

    _MCP_HANDLERS = {
        "initialize": lambda req_id, _params: _mcp_handle_initialize(app, req_id),
        "tools/list": lambda req_id, _params: _mcp_handle_tools_list(
            app, commands, req_id,
        ),
        "tools/call": lambda req_id, params: _mcp_handle_tools_call(
            app, req_id, params,
        ),
    }

    for line in inp:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            # Malformed JSON -- send parse error if we can
            resp = _mcp_jsonrpc_error(None, -32700, "Parse error")
            out.write(json.dumps(resp) + "\n")
            out.flush()
            continue

        # A non-object JSON value is a parse error, matching Go (which
        # unmarshals directly into a struct). The guard is retained -- deleting
        # it would crash on the msg.get(...) calls below -- but it now redirects
        # to the same -32700 "Parse error" response instead of -32600.
        if not isinstance(msg, dict):
            resp = _mcp_jsonrpc_error(None, -32700, "Parse error")
            out.write(json.dumps(resp) + "\n")
            out.flush()
            continue

        req_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        # Notifications have no 'id' -- don't send a response
        if "id" not in msg:
            continue

        handler = _MCP_HANDLERS.get(method)
        if handler is not None:
            resp = handler(req_id, params)
        else:
            resp = _mcp_jsonrpc_error(
                req_id, -32601, f"Method not found: {method}",
            )

        out.write(json.dumps(resp) + "\n")
        out.flush()
