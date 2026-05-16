#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["allpairspy"]
# ///
"""Generate pairwise combinatorial test cases for strictcli conformance.

Uses allpairspy to produce a covering array of all 2-way flag feature
combinations, then writes JSON test cases to conformance/cases/pairwise.json.

Axes:
  - Flag type: str, bool, int
  - Short: yes, no
  - Default: present, absent
  - Env: present, absent
  - Repeatable: yes, no (only str/int; forced "no" for bool)
  - Choices: present, absent (only str/int; forced "absent" for bool)
  - Negatable: true, false (only bool; forced "na" for str/int)
  - Mutex: yes, no

Invalid combinations filtered:
  - bool + repeatable=yes
  - bool + choices=present
  - non-bool + negatable in (true, false) [forced to "na"]
"""

from __future__ import annotations

import json
from pathlib import Path

from allpairspy import AllPairs

# Axis values
FLAG_TYPES = ["str", "bool", "int"]
SHORT_OPTS = ["yes", "no"]
DEFAULT_OPTS = ["present", "absent"]
ENV_OPTS = ["present", "absent"]
REPEATABLE_OPTS = ["yes", "no"]
CHOICES_OPTS = ["present", "absent"]
NEGATABLE_OPTS = ["true", "false", "na"]
MUTEX_OPTS = ["yes", "no"]

PARAMETERS = [
    FLAG_TYPES,       # 0: type
    SHORT_OPTS,       # 1: short
    DEFAULT_OPTS,     # 2: default
    ENV_OPTS,         # 3: env
    REPEATABLE_OPTS,  # 4: repeatable
    CHOICES_OPTS,     # 5: choices
    NEGATABLE_OPTS,   # 6: negatable
    MUTEX_OPTS,       # 7: mutex
]


def is_valid_combination(row: list) -> bool:
    """Filter out invalid combinations during generation.

    allpairspy calls this incrementally with partial rows, so we check
    each constraint only when the relevant indices are present.
    """
    flag_type = row[0]

    if len(row) > 4:
        repeatable = row[4]
        if flag_type == "bool" and repeatable == "yes":
            return False
    if len(row) > 5:
        choices = row[5]
        if flag_type == "bool" and choices == "present":
            return False
    if len(row) > 6:
        negatable = row[6]
        # negatable is only meaningful for bool
        if flag_type == "bool" and negatable == "na":
            return False
        if flag_type != "bool" and negatable != "na":
            return False
    return True


def _short_letter(flag_type: str) -> str:
    """Return a short letter for the flag type."""
    return {"str": "s", "bool": "b", "int": "n"}[flag_type]


def _default_value(flag_type: str) -> str | int | bool:
    """Return a sensible default value for the flag type."""
    return {"str": "default_val", "bool": False, "int": 42}[flag_type]


def _choices_for_type(flag_type: str) -> list:
    """Return a choices list that includes the test value."""
    if flag_type == "str":
        return ["test_val", "other_val", "third_val"]
    elif flag_type == "int":
        return [99, 50, 1]
    return []


def _expected_output(
    flag_name: str,
    flag_type: str,
    is_repeatable: bool,
    is_negatable_test: bool,
    has_choices: bool,
    provided_via: str,
) -> str:
    """Compute the expected stdout_contains substring for a test case."""
    if flag_type == "bool":
        if is_negatable_test:
            return f"{flag_name}=false"
        if provided_via == "default":
            return f"{flag_name}=false"
        if provided_via == "env":
            return f"{flag_name}=true"
        # provided_via == "cli"
        return f"{flag_name}=true"

    if flag_type == "str":
        if is_repeatable and provided_via == "cli":
            return f"{flag_name}=test_val,test_val"
        if provided_via == "default":
            return f"{flag_name}=default_val"
        if provided_via == "env":
            return f"{flag_name}=test_val" if has_choices else f"{flag_name}=env_val"
        # provided_via == "cli"
        return f"{flag_name}=test_val"

    # int
    if is_repeatable and provided_via == "cli":
        return f"{flag_name}=99,99"
    if provided_via == "default":
        return f"{flag_name}=42"
    if provided_via == "env":
        return f"{flag_name}=99" if has_choices else f"{flag_name}=77"
    # provided_via == "cli"
    return f"{flag_name}=99"


def generate_test_case(row_idx: int, row: list) -> dict:
    """Generate a single test case from a pairwise row."""
    flag_type = row[0]
    has_short = row[1] == "yes"
    has_default = row[2] == "present"
    has_env = row[3] == "present"
    is_repeatable = row[4] == "yes"
    has_choices = row[5] == "present"
    is_negatable_true = row[6] == "true"  # only meaningful when type=bool
    is_mutex = row[7] == "yes"

    # Repeatable flags cannot have scalar defaults -- they default to [].
    # Suppress the default axis when both are set.
    if is_repeatable and has_default:
        has_default = False

    flag_name = f"flag{row_idx}"
    env_var = f"MYAPP_{flag_name.upper()}"

    # Describe the combination for the test name
    features = [f"type={flag_type}"]
    if has_short:
        features.append("short")
    if has_default:
        features.append("default")
    if has_env:
        features.append("env")
    if is_repeatable:
        features.append("repeatable")
    if has_choices:
        features.append("choices")
    if flag_type == "bool":
        features.append(f"negatable={row[6]}")
    if is_mutex:
        features.append("mutex")

    name = f"pairwise: {', '.join(features)}"

    # Build the flag definition
    flag_def: dict = {
        "name": flag_name,
        "type": flag_type,
        "help": f"test flag {row_idx}",
    }

    if has_short:
        flag_def["short"] = _short_letter(flag_type)

    if has_default:
        flag_def["default"] = _default_value(flag_type)

    if has_env:
        flag_def["env"] = env_var

    if is_repeatable:
        flag_def["repeatable"] = True

    if has_choices:
        if flag_type == "str":
            flag_def["choices_str"] = _choices_for_type("str")
        elif flag_type == "int":
            flag_def["choices_int"] = _choices_for_type("int")

    if flag_type == "bool":
        flag_def["negatable"] = is_negatable_true

    # Decide how the value is provided and what output to expect.
    # Priority: negatable test > env > default > CLI
    test_negation = flag_type == "bool" and is_negatable_true
    provided_via = "cli"
    argv = ["cmd"]
    env_dict: dict[str, str] = {}
    app_needs_env_prefix = has_env

    if test_negation:
        # Test --no-flagname
        provided_via = "cli"
        argv.append(f"--no-{flag_name}")
    elif has_env:
        # Provide via env (also tests env-over-default when both present)
        provided_via = "env"
        if flag_type == "bool":
            env_dict[env_var] = "true"
        elif flag_type == "str":
            env_dict[env_var] = "test_val" if has_choices else "env_val"
        elif flag_type == "int":
            env_dict[env_var] = "99" if has_choices else "77"
    elif has_default:
        # Let default apply, don't provide the flag
        provided_via = "default"
    else:
        # No default, no env: must provide via CLI
        provided_via = "cli"
        if flag_type == "bool":
            argv.append(f"--{flag_name}")
        elif flag_type == "str":
            if is_repeatable:
                argv.extend([f"--{flag_name}", "test_val", f"--{flag_name}", "test_val"])
            elif has_short:
                argv.extend([f"-{_short_letter(flag_type)}", "test_val"])
            else:
                argv.extend([f"--{flag_name}", "test_val"])
        elif flag_type == "int":
            if is_repeatable:
                argv.extend([f"--{flag_name}", "99", f"--{flag_name}", "99"])
            elif has_short:
                argv.extend([f"-{_short_letter(flag_type)}", "99"])
            else:
                argv.extend([f"--{flag_name}", "99"])

    expected = _expected_output(
        flag_name, flag_type, is_repeatable, test_negation,
        has_choices, provided_via,
    )

    # Build the handler_prints template
    handler_prints = f"{flag_name}={{{flag_name}}}"

    # Build the command
    command: dict = {
        "name": "cmd",
        "help": "a command",
        "handler_prints": handler_prints,
    }

    # Place flag: if mutex, put in mutex group with a companion flag
    if is_mutex:
        companion_name = f"alt{row_idx}"
        companion_def: dict = {
            "name": companion_name,
            "type": flag_type,
            "help": f"mutex companion {row_idx}",
        }
        if flag_type == "bool":
            companion_def["negatable"] = is_negatable_true
        elif has_default:
            # Give companion a default so it doesn't error as required
            companion_def["default"] = _default_value(flag_type)
        elif has_env:
            # Give companion a default=null so it's optional but we don't
            # need to provide it
            companion_def["default"] = None

        command["mutex"] = [{
            "flags": [flag_def, companion_def]
        }]
        handler_prints = f"{flag_name}={{{flag_name}}} {companion_name}={{{companion_name}}}"
        command["handler_prints"] = handler_prints
    else:
        command["flags"] = [flag_def]

    # Build the app
    app: dict = {
        "name": "myapp",
        "version": "1.0.0",
        "help": "test",
        "commands": [command],
    }

    if app_needs_env_prefix:
        app["env_prefix"] = "MYAPP"

    # Build the test case
    case: dict = {
        "name": name,
        "app": app,
        "argv": argv,
        "expect": {
            "exit_code": 0,
            "stdout_contains": expected,
        },
    }

    if env_dict:
        case["env"] = env_dict

    return case


def main() -> None:
    rows = list(AllPairs(PARAMETERS, filter_func=is_valid_combination))

    print(f"Generated {len(rows)} pairwise combinations")

    cases = []
    for idx, row in enumerate(rows):
        case = generate_test_case(idx, list(row))
        cases.append(case)

    out_path = Path(__file__).resolve().parent / "cases" / "pairwise.json"
    with open(out_path, "w") as f:
        json.dump(cases, f, indent=2)
        f.write("\n")

    print(f"Wrote {len(cases)} test cases to {out_path}")


if __name__ == "__main__":
    main()
