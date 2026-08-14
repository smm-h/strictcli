#!/usr/bin/env python3
"""Rewrite conformance/schema.json for the scoped-selector + schema-v2 round.

One-time migration, kept beside its siblings in `conformance/scripts/` for the
same reason they are kept: the transformation is the record of what moved.

What it does (effects contract §13's item-207 box, §24, §25.6):

- `$defs/flag` gains `elect_by` and `choices` (an array of the new
  `$defs/choice`), plus the `if`/`then`/`else` split that makes `elect_by` the
  input-side discriminator.
- `$defs/choice` is added: `name` and `help` required, `flags` (a recursive
  `$ref` to `$defs/flag`) and `value` (the member payload, its own KEY rather
  than the dump's first-`flags`-entry placement) optional.
- The three surviving typed choice keys (`choices_str` / `choices_int` /
  `choices_float`) take record-shaped items on both the flag and the arg
  entry (§24.2's deleted bare-value entry).
- `$defs/mutex_group` is deleted with the construct, along with the command
  entry's `mutex` property and its `false` pin in the deprecated branch.
"""
from __future__ import annotations

import json
import pathlib

SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "schema.json"

RECORD_DESC = (
    "Choices for {kind}-type {surface}s, in the record spelling (contract "
    "§24.2): every entry is a value plus OPTIONAL help. The bare-value entry "
    "is deleted -- an entry that may carry help and an entry that carries none "
    "would be two spellings of one fact. The split by type survives because "
    "its reason is the input side's alone: JSON cannot tell an integer choice "
    "from a float one, and each harness must know which typed constructor to "
    "call."
)


def choice_record(json_type: str, kind: str, surface: str) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["value"],
            "additionalProperties": False,
            "properties": {
                "value": {"type": json_type},
                "help": {"type": "string", "minLength": 1},
            },
        },
        "description": RECORD_DESC.format(kind=kind, surface=surface),
    }


CHOICE_DEF = {
    "type": "object",
    "required": ["name", "help"],
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "The choice's name. Under member spelling it IS the electing "
                "flag's own name (contract §24.4)."
            ),
        },
        "help": {
            "type": "string",
            "description": (
                "Mandatory on a choice -- which is what makes a selector "
                "always render as a help block (§24.10), and what "
                "errChoiceHelpEmpty refuses."
            ),
        },
        "value": {
            "type": "object",
            "required": ["type", "help"],
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": ["str", "int", "float"]},
                "help": {"type": "string"},
            },
            "description": (
                "A member-spelled choice's own payload (§24.4). It is the "
                "choice object's own KEY here, and NOT the first entry of "
                "`flags` the way the dump places it (§25.6): a case spelling "
                "it the dump's way would be indistinguishable from a case "
                "declaring a scoped flag named `value`, which is the input "
                "errScopedNameValueReserved is asserted against. It declares "
                "no presence, because electing the member supplies the value. "
                "Spellable on a token-spelled choice too -- that is the input "
                "errTokenChoiceCarriesPayload is asserted against."
            ),
        },
        "flags": {
            "type": "array",
            "items": {"$ref": "#/$defs/flag"},
            "description": (
                "The choice's scope: the flags that exist only while it is "
                "elected. Recursion costs the schema nothing -- a nested "
                "selector is an ordinary flag entry carrying its own "
                "`elect_by` and `choices`, to any depth -- and presence stays "
                "mandatory at every depth through the `required` list the "
                "ref already carries."
            ),
        },
    },
    "description": (
        "One choice of a selector (contract §24.1, §13's item-207 box): a "
        "name, mandatory help, an optional member payload, and the scope it "
        "owns."
    ),
}

ELECT_BY_PROP = {
    "type": "string",
    "enum": ["selector-token", "member-flags"],
    "description": (
        "Declares this flag a SELECTOR and names its spelling (contract "
        "§24.12's own two strings, the same pair §25.6 publishes). "
        "`selector-token` is `--via email`; `member-flags` spells each choice "
        "as its own flag and never types the selector's name."
    ),
}

CHOICES_PROP = {
    "type": "array",
    "items": {"$ref": "#/$defs/choice"},
    "description": (
        "A selector's choices, in declaration order. On a flag entry "
        "`choices` always means choice objects and `choices_<T>` always means "
        "value records -- which is what lets the two constructs share one "
        "flag entry without collision."
    ),
}

ELECT_BY_SPLIT = {
    "$comment": (
        "Contract §13 (item 207): `elect_by` is the input-side discriminator, "
        "exactly as it is the dump's (§25.6). An entry carrying it is a "
        "selector -- it declares `choices` and none of the value-flag keys; an "
        "entry not carrying it is an ordinary flag and declares no `choices`. "
        "A case that spells an illegal combination (to assert a registration "
        "error) declares skip_schema_validation."
    ),
    "if": {"required": ["elect_by"]},
    "then": {
        "not": {
            "anyOf": [
                {"required": ["type"]},
                {"required": ["choices_str"]},
                {"required": ["choices_int"]},
                {"required": ["choices_float"]},
                {"required": ["repeatable"]},
                {"required": ["validate"]},
            ]
        }
    },
    "else": {"not": {"required": ["choices"]}},
}


def main() -> None:
    raw = SCHEMA.read_text()
    doc = json.loads(raw)
    defs = doc["$defs"]

    # --- $defs/choice ------------------------------------------------------
    # Placed immediately before $defs/flag, mirroring the order §25.9's entity
    # sequence uses on the dump side.
    rebuilt: dict = {}
    for key, value in defs.items():
        if key == "flag":
            rebuilt["choice"] = CHOICE_DEF
        if key == "mutex_group":
            continue  # deleted with MutexGroup (§24.14, §25.7)
        rebuilt[key] = value
    defs = doc["$defs"] = rebuilt

    # --- $defs/flag --------------------------------------------------------
    flag = defs["flag"]
    flag["allOf"].append(ELECT_BY_SPLIT)
    props = flag["properties"]
    props["choices_str"] = choice_record("string", "str", "flag")
    props["choices_int"] = choice_record("integer", "int", "flag")
    props["choices_float"] = choice_record("number", "float", "flag")
    # A selector's `default` is the flat map §25.6 publishes:
    # {"choice": "<name>", "<field>": <value>, ...}. It validates under the
    # existing object branch, which is widened by one scalar so a bool field
    # of the defaulted scope is spellable.
    obj_branch = next(
        b for b in props["default"]["oneOf"] if b.get("type") == "object"
    )
    if {"type": "boolean"} not in obj_branch["additionalProperties"]["oneOf"]:
        obj_branch["additionalProperties"]["oneOf"].append({"type": "boolean"})
    obj_branch["$comment"] = (
        "A dict flag's declared default (contract §23.5's dict row), and a "
        "SELECTOR's defaulted selection, which is the same flat map §25.6 "
        "publishes: the choice's name under the reserved key `choice` "
        "followed by each field that has a value."
    )
    # Ordered so the two selector keys sit together, after the value-flag
    # `choices_<T>` trio they are never spelled beside.
    props["elect_by"] = ELECT_BY_PROP
    props["choices"] = CHOICES_PROP

    # --- $defs/arg ---------------------------------------------------------
    aprops = defs["arg"]["properties"]
    aprops["choices_str"] = choice_record("string", "str", "arg")
    aprops["choices_int"] = choice_record("integer", "int", "arg")
    aprops["choices_float"] = choice_record("number", "float", "arg")

    # --- command entry -----------------------------------------------------
    cmd = defs["command"]
    cmd["properties"].pop("mutex", None)
    cmd["then"]["properties"].pop("mutex", None)
    dep_desc = cmd["properties"]["deprecated"]["description"]
    cmd["properties"]["deprecated"]["description"] = dep_desc.replace(
        "flags, args, flag_sets, mutex, dependencies",
        "flags, args, flag_sets, dependencies",
    )

    SCHEMA.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"rewrote {SCHEMA}")


if __name__ == "__main__":
    main()
