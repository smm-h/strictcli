#!/usr/bin/env python3
"""Differential fuzzer for strictcli conformance.

Generates random argv sequences -- and, for the constraint family, the
declaration they run against -- then runs each pair against every registered
implementation (Python, Go, TypeScript) and compares their results N-way. A
divergence is any disagreement in exit code, or in stdout when all
implementations exit 0; the odd-one-out is identified by majority. Divergences
are recorded and minimized.

Execution reuses run.py's target machinery: the Python reference script is
generated via ref_python codegen, while Go and TypeScript run through the same
runtime harnesses run.py uses (the `conformance/harness` binary and
`conformance/harness_ts/main.js`, both reading the app definition from the
CONFORMANCE_APP_DEF env var). Harnesses are built once per run.

Usage:
    python conformance/fuzz.py --iterations 1000
    python conformance/fuzz.py --iterations 100 --seed 42
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from typing import Callable

# Reuse run.py's target descriptors, harness builds, and N-way divergence
# reporting rather than duplicating any of it here.
from run import (
    CONFORMANCE_DIR,
    TARGETS,
    _ensure_harness,
    _ensure_ts_harness,
    _normalize,
    _normalize_temp_paths,
    _stream_divergence,
)

# ---------------------------------------------------------------------------
# App definitions
# ---------------------------------------------------------------------------

SIMPLE_APP: dict = {
    "name": "fuzzapp",
    "version": "1.0.0",
    "help": "a simple app for fuzzing",
    "commands": [
        {
            "name": "run",
            "help": "run something",
            "effect": "read_only",
            "flags": [
                {
                    "name": "name",
                    "type": "str",
                    "help": "a name",
                    "presence": "default",
                    "default": "world",
                },
                {
                    "name": "chatter",
                    "type": "bool",
                    "help": "chatter output",
                    "presence": "optional",
                },
            ],
            "handler_prints": "run name={name} chatter={chatter}",
        },
    ],
}

COMPLEX_APP: dict = {
    "name": "fuzzapp",
    "version": "2.0.0",
    "help": "a complex app for fuzzing",
    "global_flags": [
        {
            "name": "chatter",
            "type": "bool",
            "help": "chatter output",
            "presence": "optional",
        },
    ],
    "commands": [
        {
            "name": "raw",
            "help": "passthrough command",
            "effect": "read_only",
            "passthrough": True,
            "passthrough_handler_prints": "{name}:{args}",
        },
    ],
    "groups": [
        {
            "name": "db",
            "help": "database operations",
            "commands": [
                {
                    "name": "migrate",
                    "help": "run migrations",
                    "effect": "read_only",
                    "flags": [
                        {
                            "name": "target",
                            "type": "str",
                            "help": "deploy target",
                            "presence": "required",
                            "choices_str": ["prod", "staging"],
                        },
                        {
                            "name": "count",
                            "type": "int",
                            "help": "number of migrations",
                            "presence": "default",
                            "default": 1,
                        },
                        {
                            "name": "pretend",
                            "type": "bool",
                            "help": "pretend mode",
                            "presence": "optional",
                        },
                    ],
                    "args": [
                        {
                            "name": "path",
                            "help": "migration path",
                            "presence": "required",
                        },
                    ],
                    "handler_prints": "migrate target={target} count={count} pretend={pretend} path={path} chatter={chatter}",
                },
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# The constraint app is GENERATED per iteration (contract §26)
# ---------------------------------------------------------------------------
#
# The two fixed apps above are hand-written; the constraint family is not,
# because what has to be fuzzed is the interaction between a random declaration
# and a random invocation: which members a constraint names, which election
# selector each one declares, whether a nested constraint sits between them, and
# which of them the argv engages. A fixed app would fuzz only the second half.
#
# The generator obeys the same FILTERED-STATE discipline generate_pairwise.py
# states for its own axes: it never emits a declaration that registration
# refuses, so every divergence this family reports is a parse-time or
# rendering-time disagreement rather than three implementations agreeing that a
# declaration is illegal. What is filtered, and the rule that filters it:
#
#   - no member declares `required` (§26.5 refuses one in both families);
#   - a bool member always declares its election, `true` or `present` (§26.3's
#     mandatory-election refusal);
#   - `true` is emitted only on a bool and `non_empty` only on a sized value --
#     str, list, dict and the variadic arg (§26.3's two type refusals);
#   - a nested member names an EARLIER constraint only, so the reference graph
#     is acyclic by construction (§26.2), and it carries no election of its own;
#   - every member of one constraint is a distinct name (errConstraintMemberDuplicate);
#   - a token-spelled selector member declares a choice default rather than
#     requiredness, since a choice flag may not declare optional (§23) and a
#     required member is refused;
#   - constraint names are `c<i>` and flag names `f<i>`, so a name never
#     collides with a flag or arg name (§26.8's step 1).

_CONSTRAINT_FLAG_TYPES = ["str", "bool", "int", "float", "list[str]", "dict[str,str]"]

_CONSTRAINT_DEFAULTS: dict = {
    "str": "dflt",
    "bool": False,
    "int": 7,
    "float": 1.5,
    "list[str]": ["dflt"],
    "dict[str,str]": {"k": "v"},
}


def _legal_whens(type_word: str, variadic: bool = False) -> list[str | None]:
    """The election selectors §26.3 allows on a member of this declared type.

    `None` means the member omits `when` entirely, which is the `present`
    default and a declaration state of its own. A bool never gets it: omitting
    the election on a bool is a registration error, because `present` there
    would let `--no-x` engage a constraint while selecting nothing.
    """
    if variadic:
        # A variadic arg is SIZED whatever its element type, so `non_empty` is
        # legal on it and equal to `present` (§26.3's pinned box).
        return [None, "present", "non_empty"]
    if type_word == "bool":
        return ["true", "present"]
    if type_word in ("int", "float"):
        return [None, "present"]
    return [None, "present", "non_empty"]


def _gen_constraint_app(rng: random.Random) -> dict:
    """Generate one app whose command declares a random legal constraint set."""
    flags: list[dict] = []
    # (member name, the elections legal on it)
    pool: list[tuple[str, list[str | None]]] = []

    for i in range(rng.randint(2, 4)):
        type_word = rng.choice(_CONSTRAINT_FLAG_TYPES)
        name = f"f{i}"
        flag = {"name": name, "type": type_word, "help": f"flag {i}"}
        if rng.random() < 0.5:
            flag["presence"] = "optional"
        else:
            flag["presence"] = "default"
            flag["default"] = _CONSTRAINT_DEFAULTS[type_word]
        flags.append(flag)
        pool.append((name, _legal_whens(type_word)))

    args: list[dict] = []
    if rng.random() < 0.5:
        args.append({
            "name": "targets",
            "help": "the targets",
            "presence": "optional",
            "variadic": True,
        })
        pool.append(("targets", _legal_whens("str", variadic=True)))

    if rng.random() < 0.35:
        # A token-spelled selector is an ordinary root-scope flag here, and
        # `present` is the only election legal on it -- its value is a record,
        # so `true` and `non_empty` have nothing to test (§26.2).
        flags.append({
            "name": "via",
            "help": "delivery channel",
            "presence": "default",
            "default": {"choice": "email"},
            "elect_by": "selector-token",
            "choices": [
                {"name": "email", "help": "as email"},
                {"name": "sms", "help": "as sms"},
            ],
        })
        pool.append(("via", [None, "present"]))

    constraints: list[dict] = []
    for ci in range(rng.randint(1, 2)):
        count = rng.randint(2, min(3, len(pool)))
        members = []
        for name, whens in rng.sample(pool, count):
            when = rng.choice(whens)
            members.append({"name": name} if when is None else {"name": name, "when": when})
        if constraints and rng.random() < 0.5:
            # A nested member is engaged when its own members are, and declares
            # no election of its own.
            members.append({"name": rng.choice([c["name"] for c in constraints])})
        constraints.append({
            "type": rng.choice(["at_least_one", "all_or_none"]),
            "name": f"c{ci}",
            "members": members,
        })

    printed = [f["name"] for f in flags] + [a["name"] for a in args]
    command = {
        "name": "run",
        "help": "run something",
        "effect": "read_only",
        "flags": flags,
        "constraints": constraints,
        "handler_prints": " ".join(f"{n}={{{n}}}" for n in printed),
    }
    if args:
        command["args"] = args

    return {
        "name": "fuzzapp",
        "version": "3.0.0",
        "help": "a generated app for constraint fuzzing",
        "commands": [command],
    }


# ---------------------------------------------------------------------------
# The update app is GENERATED per iteration (contract §27)
# ---------------------------------------------------------------------------
#
# Same reason as the constraint family: what has to be fuzzed is the
# interaction between a random declaration and a random invocation -- which
# flags are properties, which of them are nullable, whether the resource has
# identity members, which write mode it declares, and which of all that the
# argv supplies, clears or negates. A fixed app would fuzz only the second
# half.
#
# The FILTERED-STATE discipline, and the rule that filters each state:
#
#   - the command declares `effect="mutating"`, because update_of on a
#     read_only command is a registration error (§27.2) -- so §27.1's ban
#     applies, and NO declaration the generator emits carries a value default;
#   - every property is an optional root-scope FLAG, never an arg, never a
#     choice flag, never required (§27.3);
#   - at least one property is always declared (§27.2's errUpdatePropertiesEmpty);
#   - identity members are ordinary flags, required or optional, and never
#     nullable (§27.6's errNullableNotProperty);
#   - `nullable` is emitted only on a property, and flag names are `p<i>` /
#     `id<i>`, so `unset-<prop>` can never collide with a declared flag
#     (§27.6's errUnsetNameReserved);
#   - the resource name is `dns-record` and the write mode is one of the two
#     legal words, so neither charset nor vocabulary guard can fire.
#
# What is left for the fuzzer to disagree about is therefore parse-time and
# rendering-time only: the at-least-one-property refusal, the value-and-unset
# collision, the write set's two renderings, and the tri-state bool property.

_UPDATE_PROPERTY_TYPES = ["str", "bool", "int", "float", "list[str]", "dict[str,str]"]


def _gen_update_app(rng: random.Random) -> dict:
    """Generate one app whose command declares a random legal update."""
    flags: list[dict] = []
    properties: list[str] = []
    identity: list[str] = []

    for i in range(rng.randint(1, 4)):
        name = f"p{i}"
        flags.append({
            "name": name,
            "type": rng.choice(_UPDATE_PROPERTY_TYPES),
            "help": f"property {i}",
            "presence": "optional",
            **({"nullable": True} if rng.random() < 0.5 else {}),
        })
        properties.append(name)

    for i in range(rng.randint(0, 2)):
        name = f"id{i}"
        flags.append({
            "name": name,
            "type": "str",
            "help": f"identity {i}",
            "presence": rng.choice(["required", "optional"]),
        })
        identity.append(name)

    if rng.random() < 0.3:
        # A flag named in NEITHER list is neither, and that is legal and
        # ordinary (§27.3) -- it must never join the write set.
        flags.append({"name": "format", "type": "str", "help": "how to render",
                      "presence": "optional"})

    printed = [f["name"] for f in flags]
    command = {
        "name": "update-record",
        "help": "change one record in place",
        "effect": "mutating",
        "update_of": {
            "resource": "dns-record",
            "write_mode": rng.choice(["sparse", "full_replace"]),
            "identity": identity,
            "properties": properties,
        },
        "flags": flags,
        "handler_prints": " ".join(f"{n}={{{n}}}" for n in printed),
    }
    return {
        "name": "fuzzapp",
        "version": "4.0.0",
        "help": "a generated app for update fuzzing",
        "commands": [command],
    }


# ---------------------------------------------------------------------------
# Execution (through run.py's runtime-harness target machinery)
# ---------------------------------------------------------------------------

TIMEOUT = 5

# Result of running one target: (exit_code, stdout, stderr). Exit code -1 means
# the run timed out.
RunResult = tuple[int, str, str]


def _run(target: str, app_def: dict, argv: list[str]) -> RunResult:
    """Run one implementation of `app_def` with `argv`. Returns (exit, out, err).

    Uses run.py's target descriptor to prepare the command (Python: ref_python
    codegen; Go/TypeScript: the runtime harness reading CONFORMANCE_APP_DEF).
    """
    prep = TARGETS[target].prepare(app_def, argv)
    env = os.environ.copy()
    env.update(prep.extra_env)
    try:
        result = subprocess.run(
            prep.argv,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(CONFORMANCE_DIR),
            timeout=TIMEOUT,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    finally:
        for path in prep.cleanup_paths:
            if path is not None and os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# Divergence detection (N-way, odd-one-out by majority)
# ---------------------------------------------------------------------------


def _check_divergence(results: dict[str, RunResult]) -> str | None:
    """Return a description of the N-way divergence, or None if all agree.

    Compares exit codes across all targets; when every target exits 0, also
    compares normalized stdout. Uses run.py's _stream_divergence to identify the
    odd one(s) out by majority. A trailing per-target detail block aids
    reproduction.
    """
    exit_lines = _stream_divergence(
        "exit_code", {t: str(r[0]) for t, r in results.items()}
    )
    stdout_lines: list[str] = []
    if all(r[0] == 0 for r in results.values()):
        stdout_lines = _stream_divergence(
            "stdout",
            {t: _normalize_temp_paths(_normalize(r[1])) for t, r in results.items()},
        )
    if not exit_lines and not stdout_lines:
        return None

    lines = exit_lines + stdout_lines
    lines.append("  per-target detail:")
    for t in sorted(results):
        exit_code, stdout, stderr = results[t]
        lines.append(
            f"    {t}: exit={exit_code} "
            f"stdout={stdout.rstrip()!r} stderr={stderr.rstrip()!r}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Argv generation
# ---------------------------------------------------------------------------

# Tokens used across all strategies
_GARBAGE = [
    "", " ", "foo", "bar", "baz", "123", "-", "---", "--=val",
    "--unknown", "-x", "-xyz", "true", "false", "null", "0", "-1",
    "a b", "a=b", "--", "'quoted'", '"double"',
]


def _gen_argv_simple(rng: random.Random) -> list[str]:
    """Generate a random argv for the simple app."""
    tokens: list[str] = []
    strategy = rng.choice([
        "valid_basic", "valid_flags", "garbage", "help_interspersed",
        "mixed", "empty", "double_dash", "flag_styles",
    ])

    if strategy == "valid_basic":
        tokens.append("run")
        if rng.random() < 0.5:
            tokens.extend(["--name", rng.choice(["alice", "bob", ""])])
        if rng.random() < 0.5:
            tokens.append("--verbose")

    elif strategy == "valid_flags":
        tokens.append("run")
        # Random flag styles
        for _ in range(rng.randint(0, 4)):
            flag = rng.choice(["--name", "--verbose"])
            if flag == "--name":
                style = rng.choice(["space", "equals"])
                val = rng.choice(["alice", "bob", "", "123", "true"])
                if style == "equals":
                    tokens.append(f"--name={val}")
                else:
                    tokens.extend(["--name", val])
            else:
                tokens.append("--verbose")

    elif strategy == "garbage":
        n = rng.randint(0, 6)
        for _ in range(n):
            tokens.append(rng.choice(_GARBAGE))

    elif strategy == "help_interspersed":
        parts = ["run", "--name", "val", "--verbose"]
        rng.shuffle(parts)
        pos = rng.randint(0, len(parts))
        flag = rng.choice(["--help", "-h", "--version", "-v"])
        parts.insert(pos, flag)
        tokens = parts

    elif strategy == "mixed":
        tokens.append(rng.choice(["run", "unknown", "db", ""]))
        for _ in range(rng.randint(0, 5)):
            tokens.append(rng.choice(
                ["--name", "val", "--verbose", "--unknown", "-x", "extra", "--"]
            ))

    elif strategy == "empty":
        pass  # empty argv

    elif strategy == "double_dash":
        tokens.append("run")
        if rng.random() < 0.5:
            tokens.extend(["--name", "val"])
        tokens.append("--")
        for _ in range(rng.randint(0, 3)):
            tokens.append(rng.choice(["--name", "extra", "--verbose", "pos"]))

    elif strategy == "flag_styles":
        tokens.append("run")
        # Mix of --flag=val, --flag val, repeated flags, wrong types
        for _ in range(rng.randint(1, 5)):
            pick = rng.choice(["name_eq", "name_sp", "verbose", "dup_verbose", "bad_bool"])
            if pick == "name_eq":
                tokens.append(f"--name={rng.choice(['a', 'b', ''])}")
            elif pick == "name_sp":
                tokens.extend(["--name", rng.choice(["a", "b", ""])])
            elif pick == "verbose":
                tokens.append("--verbose")
            elif pick == "dup_verbose":
                tokens.extend(["--verbose", "--verbose"])
            elif pick == "bad_bool":
                tokens.extend(["--verbose", "notabool"])

    return tokens


def _gen_argv_complex(rng: random.Random) -> list[str]:
    """Generate a random argv for the complex app."""
    tokens: list[str] = []
    strategy = rng.choice([
        "valid_migrate", "valid_raw", "garbage", "help_interspersed",
        "mixed", "empty", "double_dash", "missing_required",
        "choices_invalid", "int_flag_bad",
    ])

    if strategy == "valid_migrate":
        tokens.extend(["db", "migrate"])
        if rng.random() < 0.7:
            target = rng.choice(["prod", "staging"])
            if rng.random() < 0.5:
                tokens.extend(["--target", target])
            else:
                tokens.append(f"--target={target}")
        if rng.random() < 0.5:
            count = rng.choice(["1", "5", "0", "-1", "abc"])
            if rng.random() < 0.5:
                tokens.extend(["--count", count])
            else:
                tokens.append(f"--count={count}")
        if rng.random() < 0.4:
            tokens.append("--dry-run")
        if rng.random() < 0.3:
            tokens.append("--verbose")
        # path arg (required) -- sometimes omit to test error
        if rng.random() < 0.8:
            tokens.append(rng.choice(["./migrations", "/tmp/m", "path with space"]))

    elif strategy == "valid_raw":
        tokens.append("raw")
        for _ in range(rng.randint(0, 5)):
            tokens.append(rng.choice(["--some-flag", "val", "-x", "pos", "--", "--verbose"]))

    elif strategy == "garbage":
        n = rng.randint(0, 6)
        for _ in range(n):
            tokens.append(rng.choice(_GARBAGE))

    elif strategy == "help_interspersed":
        base = rng.choice([
            ["db", "migrate", "--target", "prod", "./m"],
            ["raw", "extra"],
            ["db"],
            [],
        ])
        pos = rng.randint(0, len(base))
        flag = rng.choice(["--help", "-h", "--version", "-v"])
        base.insert(pos, flag)
        tokens = base

    elif strategy == "mixed":
        first = rng.choice(["db", "raw", "unknown", "migrate", ""])
        tokens.append(first)
        if first == "db":
            tokens.append(rng.choice(["migrate", "unknown", "--help", ""]))
        for _ in range(rng.randint(0, 4)):
            tokens.append(rng.choice([
                "--target", "prod", "staging", "--count", "3", "--dry-run",
                "--verbose", "--unknown", "-x", "extra", "--",
            ]))

    elif strategy == "empty":
        pass

    elif strategy == "double_dash":
        tokens.extend(["db", "migrate", "--target", "prod"])
        tokens.append("--")
        for _ in range(rng.randint(0, 3)):
            tokens.append(rng.choice(["--count", "extra", "pos"]))

    elif strategy == "missing_required":
        tokens.extend(["db", "migrate"])
        # Omit --target (required via choices) and/or path arg
        if rng.random() < 0.5:
            tokens.extend(["--count", str(rng.randint(1, 10))])
        if rng.random() < 0.3:
            tokens.append("--dry-run")

    elif strategy == "choices_invalid":
        tokens.extend(["db", "migrate"])
        bad_target = rng.choice(["dev", "local", "production", "PROD", ""])
        if rng.random() < 0.5:
            tokens.extend(["--target", bad_target])
        else:
            tokens.append(f"--target={bad_target}")
        tokens.append("./m")

    elif strategy == "int_flag_bad":
        tokens.extend(["db", "migrate", "--target", "prod"])
        bad_int = rng.choice(["abc", "1.5", "", "true", "99999999999999999999"])
        if rng.random() < 0.5:
            tokens.extend(["--count", bad_int])
        else:
            tokens.append(f"--count={bad_int}")
        tokens.append("./m")

    return tokens


def _supply_tokens(rng: random.Random, flag: dict) -> list[str]:
    """Argv tokens that supply one generated flag, sometimes ill-formed."""
    name = flag["name"]
    type_word = flag.get("type")
    if flag.get("elect_by"):
        return ["--via", rng.choice(["email", "sms", "carrier-pigeon"])]
    if type_word == "bool":
        return [rng.choice([f"--{name}", f"--no-{name}"])]
    if type_word == "list[str]":
        return [tok for v in rng.sample(["a", "b", "c"], rng.randint(1, 3))
                for tok in (f"--{name}", v)]
    if type_word == "dict[str,str]":
        return [f"--{name}", rng.choice(["k=v", "k=", "novalue"])]
    if type_word == "int":
        return [f"--{name}", rng.choice(["3", "0", "-1", "abc", ""])]
    if type_word == "float":
        return [f"--{name}", rng.choice(["1.5", "0", "nan", "abc", ""])]
    value = rng.choice(["x", "", "a b", "--looks-like-a-flag"])
    return [f"--{name}={value}"] if rng.random() < 0.3 else [f"--{name}", value]


def _gen_argv_constraints(rng: random.Random, app_def: dict) -> list[str]:
    """Generate a random argv for a generated constraint app."""
    command = app_def["commands"][0]
    flags = command["flags"]
    has_args = bool(command.get("args"))

    strategy = rng.choice([
        "engage_none", "engage_some", "engage_all", "decline_bools",
        "garbage", "help_interspersed", "double_dash",
    ])

    if strategy == "engage_none":
        return ["run"]

    if strategy == "help_interspersed":
        tokens = ["run"]
        for flag in flags:
            if rng.random() < 0.4:
                tokens.extend(_supply_tokens(rng, flag))
        tokens.insert(rng.randint(0, len(tokens)), rng.choice(["--help", "-h"]))
        return tokens

    if strategy == "garbage":
        return ["run"] + [rng.choice(_GARBAGE) for _ in range(rng.randint(1, 4))]

    tokens = ["run"]
    for flag in flags:
        if strategy == "engage_all":
            supply = True
        elif strategy == "decline_bools":
            supply = flag.get("type") == "bool" or rng.random() < 0.3
        else:
            supply = rng.random() < 0.5
        if not supply:
            continue
        if strategy == "decline_bools" and flag.get("type") == "bool":
            tokens.append(f"--no-{flag['name']}")
        else:
            tokens.extend(_supply_tokens(rng, flag))

    if has_args and (strategy == "engage_all" or rng.random() < 0.5):
        tokens.extend(rng.sample(["one", "two", "three"], rng.randint(1, 3)))

    if strategy == "double_dash":
        tokens.append("--")
        tokens.extend(rng.choice([[], ["extra"], ["--f0", "pos"]]))

    return tokens


def _gen_argv_update(rng: random.Random, app_def: dict) -> list[str]:
    """Generate a random argv for a generated update app."""
    command = app_def["commands"][0]
    flags = command["flags"]
    properties = set(command["update_of"]["properties"])
    nullable = {f["name"] for f in flags if f.get("nullable")}

    strategy = rng.choice([
        "write_none", "write_some", "write_all", "clear_some",
        "value_and_clear", "decline_bools", "inline_unset", "unset_negation",
    ])
    mode = rng.choice([[], ["--dry-run"], ["--json"], ["--json", "--dry-run"]])
    tokens = [*mode, "update-record"]

    for flag in flags:
        name = flag["name"]
        if name not in properties:
            # Identity and the unclassified flag: supply a required one always,
            # the rest sometimes.
            if flag.get("presence") == "required" or rng.random() < 0.5:
                tokens.extend(_supply_tokens(rng, flag))
            continue
        if strategy == "write_none":
            continue
        if strategy == "write_all":
            supply = True
        else:
            supply = rng.random() < 0.5
        if not supply:
            continue
        if strategy == "decline_bools" and flag.get("type") == "bool":
            tokens.append(f"--no-{name}")
        elif strategy == "clear_some" and name in nullable:
            tokens.append(f"--unset-{name}")
        elif strategy == "value_and_clear" and name in nullable:
            tokens.extend(_supply_tokens(rng, flag))
            tokens.append(f"--unset-{name}")
        elif strategy == "inline_unset" and name in nullable:
            tokens.append(f"--unset-{name}=x")
        elif strategy == "unset_negation" and name in nullable:
            tokens.append(f"--no-unset-{name}")
        else:
            tokens.extend(_supply_tokens(rng, flag))

    return tokens


def _case_simple(rng: random.Random) -> tuple[dict, list[str]]:
    return SIMPLE_APP, _gen_argv_simple(rng)


def _case_complex(rng: random.Random) -> tuple[dict, list[str]]:
    return COMPLEX_APP, _gen_argv_complex(rng)


def _case_constraints(rng: random.Random) -> tuple[dict, list[str]]:
    app_def = _gen_constraint_app(rng)
    return app_def, _gen_argv_constraints(rng, app_def)


def _case_update(rng: random.Random) -> tuple[dict, list[str]]:
    app_def = _gen_update_app(rng)
    return app_def, _gen_argv_update(rng, app_def)


# One entry per fuzzed family: the label, and the factory producing this
# iteration's (app definition, argv) pair. The first two families reuse a fixed
# app; the constraint and update families generate their declarations too.
FAMILIES: list[tuple[str, Callable[[random.Random], tuple[dict, list[str]]]]] = [
    ("simple", _case_simple),
    ("complex", _case_complex),
    ("constraints", _case_constraints),
    ("update", _case_update),
]


# ---------------------------------------------------------------------------
# Minimization
# ---------------------------------------------------------------------------


def _minimize(
    app_def: dict,
    argv: list[str],
    target_names: list[str],
) -> list[str]:
    """Remove tokens one at a time, keeping the smallest argv that still diverges."""
    best = list(argv)

    changed = True
    while changed:
        changed = False
        for i in range(len(best)):
            candidate = best[:i] + best[i + 1:]
            results = {t: _run(t, app_def, candidate) for t in target_names}
            if _check_divergence(results):
                best = candidate
                changed = True
                break  # restart from beginning with shorter list

    return best


# ---------------------------------------------------------------------------
# Main fuzzing loop
# ---------------------------------------------------------------------------


def fuzz(iterations: int, seed: int | None) -> list[dict]:
    """Run the fuzzer. Returns a list of divergence records."""
    if seed is None:
        seed = int(time.time() * 1000) % (2**32)
    print(f"Seed: {seed}")
    print(f"Iterations: {iterations} ({iterations} per fuzzed family)")

    rng = random.Random(seed)

    target_names = list(TARGETS)
    print(f"Targets: {', '.join(target_names)}")

    # Build the runtime harnesses once for the whole run (Python needs none).
    print("Building Go harness...", flush=True)
    _ensure_harness()
    print("Building TypeScript dist...", flush=True)
    _ensure_ts_harness()
    print()

    divergences: list[dict] = []

    total = 0
    for label, factory in FAMILIES:
        print(f"--- Fuzzing '{label}' app ({iterations} iterations) ---")

        for i in range(1, iterations + 1):
            app_def, argv = factory(rng)
            results = {t: _run(t, app_def, argv) for t in target_names}

            desc = _check_divergence(results)
            if desc is not None:
                # Minimize
                minimal = _minimize(app_def, argv, target_names)
                # Re-run minimal to get fresh description
                min_results = {t: _run(t, app_def, minimal) for t in target_names}
                min_desc = _check_divergence(min_results) or desc

                record = {
                    "app": label,
                    "seed": seed,
                    "iteration": i,
                    "app_def": app_def,
                    "original_argv": argv,
                    "minimal_argv": minimal,
                    "description": min_desc,
                }
                divergences.append(record)
                print(f"  [{i}/{iterations}] DIVERGENCE: argv={argv}")
                print(f"             minimal: {minimal}")
                print(f"             {min_desc.splitlines()[0]}")

            if i % 100 == 0:
                print(f"  [{i}/{iterations}] {len(divergences)} divergence(s) so far", flush=True)

            total += 1

        print()

    # Final report
    print("=" * 60)
    print(f"Total iterations: {total}")
    print(f"Divergences found: {len(divergences)}")

    if divergences:
        # Deduplicate by minimal argv
        seen: set[str] = set()
        unique: list[dict] = []
        for d in divergences:
            # The app definition is part of the key: the constraint family
            # generates one per iteration, so two records may share an argv and
            # disagree about a different declaration.
            key = f"{d['app']}:{json.dumps(d['app_def'], sort_keys=True)}:{d['minimal_argv']}"
            if key not in seen:
                seen.add(key)
                unique.append(d)

        print(f"Unique minimal reproducers: {len(unique)}")
        print()
        for j, d in enumerate(unique, 1):
            print(f"Reproducer {j} ({d['app']} app):")
            print(f"  app: {json.dumps(d['app_def'])}")
            print(f"  argv: {d['minimal_argv']}")
            for line in d["description"].splitlines():
                print(f"  {line}")
            print()
    else:
        print("No divergences found.")

    return divergences


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Differential argv fuzzer for strictcli"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        required=True,
        help="Number of random inputs per fuzzed family",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    divergences = fuzz(args.iterations, args.seed)
    sys.exit(1 if divergences else 0)


if __name__ == "__main__":
    main()
