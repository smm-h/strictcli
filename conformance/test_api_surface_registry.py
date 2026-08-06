#!/usr/bin/env python3
"""Unit tests for check_api_surface.py's TS name-registry integrity.

The TS arms of `check_entity` only check names that land in the entity's TS
name universe (struct members UNION the option_keys of the factories that
build the struct).  A registry entry naming a symbol that no longer exists
therefore does not fail -- it silently shrinks the universe, and the check
reports a vacuous PASS.  That is exactly what happened when the single
`defineCommand` factory was replaced by the effect-classified twins: the
`CommandDef -> defineCommand` entry outlived its target, so every command
spec-only key stopped being checked against the schema.

These tests pin the union (both twins contribute) and the guardrail that makes
the failure mode impossible to reintroduce silently.

Runnable under pytest (auto-discovered) or standalone
(`python3 test_api_surface_registry.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_api_surface as cas


def _command_descriptor() -> cas.EntityDescriptor:
    for desc in cas._build_descriptors():
        if desc.schema_def == "command":
            return desc
    raise AssertionError("no descriptor for the 'command' entity")


# ---------------------------------------------------------------------------
# The registry maps every struct to the factories that actually build it
# ---------------------------------------------------------------------------

def test_command_def_maps_to_both_effect_classified_twins():
    """`defineCommand` no longer exists; the twins are the only builders."""
    assert cas.TS_STRUCT_OPTION_CTOR["CommandDef"] == [
        "defineReadOnlyCommand",
        "defineMutatingCommand",
    ]


def test_registry_values_are_lists_not_bare_names():
    """A bare string silently iterates as characters in the union loop."""
    for struct, ctors in cas.TS_STRUCT_OPTION_CTOR.items():
        assert isinstance(ctors, list), f"{struct} maps to {ctors!r}"
        assert ctors, f"{struct} maps to an empty factory list"


# ---------------------------------------------------------------------------
# The universe is a real union
# ---------------------------------------------------------------------------

def test_command_universe_unions_the_keys_of_both_twins():
    universe = cas._ts_entity_universe(
        _command_descriptor(),
        {"CommandDef": {"kind", "name"}},
        {
            "defineReadOnlyCommand": {"readOnlyOnlyKey", "sharedKey"},
            "defineMutatingCommand": {"mutatingOnlyKey", "sharedKey"},
        },
    )
    assert universe == {
        "kind",
        "name",
        "readOnlyOnlyKey",
        "mutatingOnlyKey",
        "sharedKey",
    }


def test_a_struct_with_no_registered_factory_is_just_its_members():
    desc = cas.EntityDescriptor(
        schema_def="group", python_cls="Group", go_struct="Group",
        ts_struct="Group",
    )
    assert cas._ts_entity_universe(desc, {"Group": {"name"}}, {"flag": {"x"}}) == {
        "name"
    }


# ---------------------------------------------------------------------------
# The guardrail: a registry target that vanished must be a hard error
# ---------------------------------------------------------------------------

def test_a_missing_option_constructor_is_reported():
    desc = _command_descriptor()
    errors = cas.check_ts_registry_targets(
        [desc],
        {name: set() for name in cas.TS_STRUCT_OPTION_CTOR},
        {"flag": set(), "arg": set(), "createApp": set()},
    )
    joined = "\n".join(errors)
    assert "defineReadOnlyCommand" in joined
    assert "defineMutatingCommand" in joined


def test_a_missing_struct_is_reported():
    desc = _command_descriptor()
    errors = cas.check_ts_registry_targets([desc], {}, {})
    joined = "\n".join(errors)
    assert "ts_struct 'CommandDef'" in joined
    assert "TS_STRUCT_OPTION_CTOR key 'CommandDef'" in joined


def test_a_fully_present_registry_reports_nothing():
    descriptors = cas._build_descriptors()
    ts_structs = {d.ts_struct: set() for d in descriptors if d.ts_struct}
    ts_structs.update({name: set() for name in cas.TS_STRUCT_OPTION_CTOR})
    ts_ctor_keys = {
        ctor: set()
        for ctors in cas.TS_STRUCT_OPTION_CTOR.values()
        for ctor in ctors
    }
    assert cas.check_ts_registry_targets(descriptors, ts_structs, ts_ctor_keys) == []


if __name__ == "__main__":
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {_name}: {exc}")
    sys.exit(1 if failures else 0)
