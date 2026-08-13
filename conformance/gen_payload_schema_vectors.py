#!/usr/bin/env python3
"""Generate conformance/payload_schema_vectors.json.

Cross-language vectors for the declared-payload-schema validator (effects
contract §19.5). Every vector is authored here -- nothing is derived from any
implementation -- and all three implementations replay the committed file in
their own unit suites, asserting the same verdict AND the same error text.

Two families:

* ``schema_vectors`` -- registration-time schema validation. A vector carries
  a schema literal and either ``valid: true`` or the exact ``path``/``detail``
  the rejection must name.
* ``instance_vectors`` -- emission-time instance validation. A vector carries a
  schema, a value, and either ``valid: true`` or the exact ``path``/``detail``.

The error text an implementation produces is
``command "<name>": payload schema is invalid at <path>: <detail>`` for the
first family and
``command "<name>": payload does not satisfy the declared schema at <path>: <detail>``
for the second. Only ``path`` and ``detail`` are recorded, because the outer
template lives in each implementation's error catalog and is parity-checked
there.

A vector may carry ``unrepresentable_in`` (a list of implementation names) with
a mandatory ``unrepresentable_reason``. Such a vector is skipped by exactly the
named implementations, for a structural reason, never for convenience. Today
this is used once: an integer of 2^53+1 does not exist in TypeScript -- every
route to a number goes through a double, so the literal rounds to 2^53 before
any validator can see it.

Regeneration is byte-stable: the tables below are literal and ordered.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "payload_schema_vectors.json"

# ---------------------------------------------------------------------------
# Detail strings -- the exact texts every implementation must produce.
# ---------------------------------------------------------------------------

CLOSED_SUBSET = (
    "additionalProperties, const, enum, items, properties, required, type"
)
JSON_TYPES = "array, boolean, integer, null, number, object, string"

D_NOT_JSON = "the value is not representable in JSON"
D_MAGNITUDE = (
    "the number's magnitude exceeds 2^53 (declare a big identifier as a string)"
)
D_TYPE_SHAPE = '"type" must be a string or an array of strings'
D_TYPE_EMPTY = '"type" must not be an empty array'
D_PROPERTIES_SHAPE = '"properties" must be an object'
D_REQUIRED_SHAPE = '"required" must be an array of strings'
D_ENUM_SHAPE = '"enum" must be a non-empty array'
D_ADDPROPS_SHAPE = '"additionalProperties" must be a boolean or a schema object'
D_ENUM_MISMATCH = "the value is not one of the declared enum values"
D_CONST_MISMATCH = "the value does not equal the declared const"


def d_unknown_keyword(kw: str) -> str:
    return f'unknown keyword "{kw}" (the closed subset is: {CLOSED_SUBSET})'


def d_unknown_type(t: str) -> str:
    return f'unknown type "{t}" (the JSON Schema types are: {JSON_TYPES})'


def d_schema_not_object(got: str) -> str:
    return f"a schema must be an object, got {got}"


def d_type_duplicate(t: str) -> str:
    return f'"type" has a duplicate entry "{t}"'


def d_required_duplicate(k: str) -> str:
    return f'"required" has a duplicate entry "{k}"'


def d_expected_type(t: str, got: str) -> str:
    return f'expected type "{t}", got {got}'


def d_expected_types(types: list[str], got: str) -> str:
    inner = ", ".join(f'"{t}"' for t in types)
    return f"expected type [{inner}], got {got}"


def d_required_missing(k: str) -> str:
    return f"required property {json.dumps(k, ensure_ascii=False)} is missing"


def d_not_permitted(k: str) -> str:
    key = json.dumps(k, ensure_ascii=False)
    return f"property {key} is not permitted (additionalProperties is false)"


# ---------------------------------------------------------------------------
# Registration-time vectors
# ---------------------------------------------------------------------------

SCHEMA_OK: list[tuple[str, dict]] = [
    ("empty schema", {}),
    ("type object", {"type": "object"}),
    ("type list for nullability", {"type": ["string", "null"]}),
    ("every json type in one list", {
        "type": ["array", "boolean", "integer", "null", "number", "object", "string"],
    }),
    ("array of integers", {"type": "array", "items": {"type": "integer"}}),
    ("closed object", {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }),
    ("dynamic-key map via additionalProperties schema", {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }),
    ("additionalProperties true", {"additionalProperties": True}),
    ("enum of mixed json values", {"enum": ["a", 1, None, True]}),
    ("const of a composite", {"const": {"a": [1, 2]}}),
    ("const at the 2^53 boundary", {"const": 9007199254740992}),
    ("prototype-chain keys are ordinary property names", {
        "type": "object",
        "properties": {
            "__proto__": {"type": "string"},
            "toString": {"type": "integer"},
            "constructor": {"type": "boolean"},
        },
    }),
    ("empty properties", {"properties": {}}),
    ("empty required", {"required": []}),
    ("deep nesting", {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"b": {"type": "array", "items": {"type": "string"}}},
        },
    }),
]

SCHEMA_BAD: list[tuple[str, dict, str, str]] = [
    # (name, schema, path, detail)
    ("unknown keyword at the root", {"type": "object", "minProperties": 1},
     "payload_schema", d_unknown_keyword("minProperties")),
    ("near-miss typo: requird", {"requird": ["a"]},
     "payload_schema", d_unknown_keyword("requird")),
    ("near-miss typo: additionalproperties",
     {"type": "object", "additionalproperties": False},
     "payload_schema", d_unknown_keyword("additionalproperties")),
    ("near-miss typo: propreties", {"propreties": {}},
     "payload_schema", d_unknown_keyword("propreties")),
    ("near-miss typo: Type", {"Type": "string"},
     "payload_schema", d_unknown_keyword("Type")),
    ("excluded keyword: pattern", {"type": "string", "pattern": "^a"},
     "payload_schema", d_unknown_keyword("pattern")),
    ("excluded keyword: $ref", {"$ref": "#/$defs/x"},
     "payload_schema", d_unknown_keyword("$ref")),
    ("excluded keyword: anyOf", {"anyOf": [{"type": "string"}]},
     "payload_schema", d_unknown_keyword("anyOf")),
    ("excluded keyword: minimum", {"type": "integer", "minimum": 0},
     "payload_schema", d_unknown_keyword("minimum")),
    ("excluded keyword: format", {"type": "string", "format": "uri"},
     "payload_schema", d_unknown_keyword("format")),
    ("excluded keyword: description (no allowlist of harmless extras)",
     {"type": "string", "description": "a name"},
     "payload_schema", d_unknown_keyword("description")),
    ("excluded keyword: title", {"type": "object", "title": "T"},
     "payload_schema", d_unknown_keyword("title")),
    ("excluded keyword: $schema", {"$schema": "https://json-schema.org/draft/2020-12/schema"},
     "payload_schema", d_unknown_keyword("$schema")),
    ("unknown keyword inside properties",
     {"type": "object", "properties": {"a": {"type": "string", "minLength": 1}}},
     'payload_schema.properties["a"]', d_unknown_keyword("minLength")),
    ("unknown keyword inside items",
     {"type": "array", "items": {"maxItems": 2}},
     "payload_schema.items", d_unknown_keyword("maxItems")),
    ("unknown keyword inside an additionalProperties schema",
     {"type": "object", "additionalProperties": {"uniqueItems": True}},
     "payload_schema.additionalProperties", d_unknown_keyword("uniqueItems")),
    ("unknown keyword three levels down",
     {"type": "object", "properties": {"a": {"type": "array", "items": {"exclusiveMinimum": 0}}}},
     'payload_schema.properties["a"].items', d_unknown_keyword("exclusiveMinimum")),
    ("a property subschema must be an object",
     {"type": "object", "properties": {"a": "string"}},
     'payload_schema.properties["a"]', d_schema_not_object("string")),
    ("a boolean is not a schema (JSON Schema's boolean form is excluded)",
     {"type": "array", "items": True},
     "payload_schema.items", d_schema_not_object("boolean")),
    ("items must not be an array (the tuple form is excluded)",
     {"type": "array", "items": [{"type": "string"}]},
     "payload_schema.items", d_schema_not_object("array")),
    ("a null subschema", {"type": "object", "properties": {"a": None}},
     'payload_schema.properties["a"]', d_schema_not_object("null")),
    ("properties must be an object", {"type": "object", "properties": []},
     "payload_schema", D_PROPERTIES_SHAPE),
    ("required must be an array", {"type": "object", "required": "a"},
     "payload_schema", D_REQUIRED_SHAPE),
    ("required entries must be strings", {"type": "object", "required": ["a", 1]},
     "payload_schema", D_REQUIRED_SHAPE),
    ("required entries must be unique", {"type": "object", "required": ["a", "a"]},
     "payload_schema", d_required_duplicate("a")),
    ("type must be a string or an array", {"type": 1},
     "payload_schema", D_TYPE_SHAPE),
    ("type array entries must be strings", {"type": ["string", 1]},
     "payload_schema", D_TYPE_SHAPE),
    ("type array must not be empty", {"type": []},
     "payload_schema", D_TYPE_EMPTY),
    ("type array entries must be unique", {"type": ["string", "string"]},
     "payload_schema", d_type_duplicate("string")),
    ("unknown type name", {"type": "strng"},
     "payload_schema", d_unknown_type("strng")),
    ("unknown type name inside a list", {"type": ["string", "strng"]},
     "payload_schema", d_unknown_type("strng")),
    ("any is not a JSON Schema type", {"type": "any"},
     "payload_schema", d_unknown_type("any")),
    ("enum must be an array", {"enum": {}},
     "payload_schema", D_ENUM_SHAPE),
    ("enum must not be empty", {"enum": []},
     "payload_schema", D_ENUM_SHAPE),
    ("additionalProperties must be a boolean or a schema",
     {"type": "object", "additionalProperties": 1},
     "payload_schema", D_ADDPROPS_SHAPE),
    ("additionalProperties must not be a string",
     {"type": "object", "additionalProperties": "false"},
     "payload_schema", D_ADDPROPS_SHAPE),
    ("additionalProperties must not be null",
     {"type": "object", "additionalProperties": None},
     "payload_schema", D_ADDPROPS_SHAPE),
    ("a const above the magnitude guard is unmatchable",
     {"const": 9007199254740994},
     "payload_schema.const", D_MAGNITUDE),
    ("an enum entry above the magnitude guard is unmatchable",
     {"enum": [1, 18014398509481984]},
     "payload_schema.enum[1]", D_MAGNITUDE),
    ("the magnitude guard reaches inside a composite const",
     {"const": {"id": [0, -18014398509481984]}},
     'payload_schema.const["id"][1]', D_MAGNITUDE),
]

# ---------------------------------------------------------------------------
# Emission-time vectors
# ---------------------------------------------------------------------------

# The type matrix. Rows are declared types, columns are values. The value's
# reported type name (the "got" clause) is the second element.
MATRIX_VALUES: list[tuple[str, object, str]] = [
    ("null", None, "null"),
    ("true", True, "boolean"),
    ("false", False, "boolean"),
    ("1", 1, "integer"),
    ("1.0", 1.0, "integer"),
    ("1.5", 1.5, "number"),
    ('"s"', "s", "string"),
    ("[1]", [1], "array"),
    ('{"a":1}', {"a": 1}, "object"),
]

# Which declared types accept which value labels. Standard JSON Schema
# semantics: "integer" accepts any number with a zero fractional part, and a
# boolean is never a number.
MATRIX_ACCEPTS: dict[str, set[str]] = {
    "null": {"null"},
    "boolean": {"true", "false"},
    "integer": {"1", "1.0"},
    "number": {"1", "1.0", "1.5"},
    "string": {'"s"'},
    "array": {"[1]"},
    "object": {'{"a":1}'},
}

MATRIX_TYPES = ["null", "boolean", "integer", "number", "string", "array", "object"]


def type_matrix() -> list[dict]:
    out: list[dict] = []
    for t in MATRIX_TYPES:
        for label, value, got in MATRIX_VALUES:
            ok = label in MATRIX_ACCEPTS[t]
            vec: dict = {
                "name": f"type matrix: {t} accepts {label}" if ok
                else f"type matrix: {t} rejects {label}",
                "schema": {"type": t},
                "value": value,
                "valid": ok,
            }
            if not ok:
                vec["path"] = "payload"
                vec["detail"] = d_expected_type(t, got)
            out.append(vec)
    return out


INSTANCE_EXTRA: list[dict] = []


def add_ok(name: str, schema: dict, value: object) -> None:
    INSTANCE_EXTRA.append(
        {"name": name, "schema": schema, "value": value, "valid": True}
    )


def add_bad(name: str, schema: dict, value: object, path: str, detail: str,
            unrepresentable_in: list[str] | None = None,
            unrepresentable_reason: str | None = None) -> None:
    vec: dict = {
        "name": name,
        "schema": schema,
        "value": value,
        "valid": False,
        "path": path,
        "detail": detail,
    }
    if unrepresentable_in:
        vec["unrepresentable_in"] = unrepresentable_in
        vec["unrepresentable_reason"] = unrepresentable_reason
    INSTANCE_EXTRA.append(vec)


def build_instance_extras() -> None:
    INSTANCE_EXTRA.clear()

    # -- the empty schema accepts anything representable -------------------
    add_ok("empty schema accepts an object", {}, {"a": [1, "b", None]})
    add_ok("empty schema accepts null", {}, None)
    add_ok("empty schema accepts a string", {}, "x")

    # -- type lists --------------------------------------------------------
    add_ok("type list accepts the first member", {"type": ["string", "null"]}, "s")
    add_ok("type list accepts null", {"type": ["string", "null"]}, None)
    add_bad("type list rejects a non-member", {"type": ["string", "null"]}, 1,
            "payload", d_expected_types(["string", "null"], "integer"))
    add_bad("type list renders in its declared order",
            {"type": ["null", "integer"]}, "s",
            "payload", d_expected_types(["null", "integer"], "string"))

    # -- Python's traps ----------------------------------------------------
    add_bad("a bool is not an integer", {"type": "integer"}, True,
            "payload", d_expected_type("integer", "boolean"))
    add_bad("a bool is not a number", {"type": "number"}, False,
            "payload", d_expected_type("number", "boolean"))
    add_bad("an integer is not a bool", {"type": "boolean"}, 1,
            "payload", d_expected_type("boolean", "integer"))
    add_bad("zero is not false", {"type": "boolean"}, 0,
            "payload", d_expected_type("boolean", "integer"))
    add_ok("1.0 satisfies integer", {"type": "integer"}, 1.0)
    add_bad("1.5 does not satisfy integer", {"type": "integer"}, 1.5,
            "payload", d_expected_type("integer", "number"))
    add_bad("true does not match enum [1]", {"enum": [1]}, True,
            "payload", D_ENUM_MISMATCH)
    add_bad("1 does not match enum [true]", {"enum": [True]}, 1,
            "payload", D_ENUM_MISMATCH)
    add_bad("false does not match enum [0]", {"enum": [0]}, False,
            "payload", D_ENUM_MISMATCH)
    add_bad("true does not match const 1", {"const": 1}, True,
            "payload", D_CONST_MISMATCH)
    add_bad("1 does not match const true", {"const": True}, 1,
            "payload", D_CONST_MISMATCH)
    add_ok("1.0 matches const 1", {"const": 1}, 1.0)
    add_ok("1 matches enum [1.0]", {"enum": [1.0]}, 1)
    add_ok("true matches const true", {"const": True}, True)
    add_ok("false matches enum [false]", {"enum": [False]}, False)

    # -- JavaScript's prototype chain --------------------------------------
    for key in ("__proto__", "toString", "constructor"):
        add_bad(f"required {key} is missing from an empty object",
                {"type": "object", "required": [key]}, {},
                "payload", d_required_missing(key))
    add_ok("required __proto__ is satisfied by an own property",
           {"type": "object", "required": ["__proto__"]}, {"__proto__": 1})
    add_ok("required toString is satisfied by an own property",
           {"type": "object", "required": ["toString"]}, {"toString": "x"})
    add_ok("required constructor is satisfied by an own property",
           {"type": "object", "required": ["constructor"]}, {"constructor": None})
    add_bad("a prototype-chain key is an ordinary additional property",
            {"type": "object", "additionalProperties": False}, {"toString": 1},
            "payload", d_not_permitted("toString"))
    add_bad("a prototype-chain key is validated as a declared property",
            {"type": "object", "properties": {"__proto__": {"type": "integer"}}},
            {"__proto__": "x"},
            'payload["__proto__"]', d_expected_type("integer", "string"))
    add_ok("a prototype-chain key deep-compares as an ordinary key",
           {"enum": [{"toString": 1}]}, {"toString": 1})
    add_ok("valueOf is not implicitly present",
           {"type": "object", "additionalProperties": False}, {})

    # -- properties / required / additionalProperties -----------------------
    add_ok("properties does not imply required",
           {"type": "object", "properties": {"a": {"type": "string"}}}, {})
    add_ok("a declared property validates",
           {"type": "object", "properties": {"a": {"type": "string"}}}, {"a": "x"})
    add_bad("a declared property is validated",
            {"type": "object", "properties": {"a": {"type": "string"}}}, {"a": 1},
            'payload["a"]', d_expected_type("string", "integer"))
    add_ok("additionalProperties true admits anything",
           {"type": "object", "additionalProperties": True}, {"x": 1})
    add_ok("additionalProperties absent admits anything",
           {"type": "object", "properties": {"a": {"type": "string"}}},
           {"a": "x", "b": 2})
    add_bad("additionalProperties false rejects an undeclared key",
            {"type": "object", "properties": {"a": {"type": "integer"}},
             "additionalProperties": False}, {"a": 1, "b": 2},
            "payload", d_not_permitted("b"))
    add_ok("additionalProperties false admits the declared keys",
           {"type": "object", "properties": {"a": {"type": "integer"}},
            "additionalProperties": False}, {"a": 1})
    add_bad("undeclared keys are reported in sorted order",
            {"type": "object", "additionalProperties": False}, {"z": 1, "b": 2},
            "payload", d_not_permitted("b"))
    add_ok("an additionalProperties schema validates the dynamic keys",
           {"type": "object", "properties": {"a": {"type": "integer"}},
            "additionalProperties": {"type": "string"}}, {"a": 1, "b": "x"})
    add_bad("an additionalProperties schema rejects a bad dynamic value",
            {"type": "object", "properties": {"a": {"type": "integer"}},
             "additionalProperties": {"type": "string"}}, {"a": 1, "b": 2},
            'payload["b"]', d_expected_type("string", "integer"))
    add_bad("missing required is reported in declared order",
            {"type": "object", "required": ["b", "a"]}, {},
            "payload", d_required_missing("b"))
    add_ok("required is satisfied by a null value",
           {"type": "object", "required": ["a"]}, {"a": None})

    # -- items -------------------------------------------------------------
    add_ok("items validates every element",
           {"type": "array", "items": {"type": "string"}}, ["a", "b"])
    add_ok("items over an empty array",
           {"type": "array", "items": {"type": "string"}}, [])
    add_bad("items reports the offending index",
            {"type": "array", "items": {"type": "string"}}, ["a", 2],
            "payload[1]", d_expected_type("string", "integer"))
    add_bad("nested items report a nested index",
            {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
            [[1], [2, "x"]],
            "payload[1][1]", d_expected_type("integer", "string"))

    # -- applicators apply only to their own type ---------------------------
    add_ok("items is inert for a non-array", {"items": {"type": "string"}}, {"a": 1})
    add_ok("properties is inert for a non-object",
           {"properties": {"a": {"type": "string"}}}, [1])
    add_ok("required is inert for a non-object", {"required": ["a"]}, "s")
    add_ok("additionalProperties is inert for a non-object",
           {"additionalProperties": False}, [1, 2])

    # -- enum / const deep equality -----------------------------------------
    add_ok("enum matches an array member", {"enum": [[1, 2], {"a": 1}]}, [1, 2])
    add_bad("array order is significant", {"enum": [[1, 2]]}, [2, 1],
            "payload", D_ENUM_MISMATCH)
    add_ok("enum matches an object member", {"enum": [[1, 2], {"a": 1}]}, {"a": 1})
    add_bad("an extra key breaks object equality", {"enum": [{"a": 1}]},
            {"a": 1, "b": 2}, "payload", D_ENUM_MISMATCH)
    add_bad("a missing key breaks object equality", {"enum": [{"a": 1, "b": 2}]},
            {"a": 1}, "payload", D_ENUM_MISMATCH)
    add_ok("object key order is insignificant", {"const": {"a": 1, "b": 2}},
           {"b": 2, "a": 1})
    add_ok("const matches a deep composite", {"const": {"a": [1, {"b": None}]}},
           {"a": [1, {"b": None}]})
    add_bad("null is not false in a deep composite",
            {"const": {"a": [1, {"b": None}]}}, {"a": [1, {"b": False}]},
            "payload", D_CONST_MISMATCH)
    add_bad("enum is case-sensitive", {"enum": ["a"]}, "A",
            "payload", D_ENUM_MISMATCH)
    add_ok("const null matches null", {"const": None}, None)
    add_bad("const null does not match false", {"const": None}, False,
            "payload", D_CONST_MISMATCH)
    add_ok("const of an empty object", {"const": {}}, {})
    add_bad("const of an empty object rejects a populated one", {"const": {}},
            {"a": 1}, "payload", D_CONST_MISMATCH)
    add_ok("enum inside properties",
           {"type": "object", "properties": {"s": {"enum": ["pass", "fail"]}}},
           {"s": "fail"})
    add_bad("enum inside properties reports the member path",
            {"type": "object", "properties": {"s": {"enum": ["pass", "fail"]}}},
            {"s": "warn"}, 'payload["s"]', D_ENUM_MISMATCH)

    # -- the magnitude guard ------------------------------------------------
    add_ok("2^53 is legal", {}, 9007199254740992)
    add_ok("-2^53 is legal", {}, -9007199254740992)
    add_ok("2^53-1 is legal", {}, 9007199254740991)
    add_bad("2^53+2 is rejected", {}, 9007199254740994, "payload", D_MAGNITUDE)
    add_bad("-(2^53+2) is rejected", {}, -9007199254740994, "payload", D_MAGNITUDE)
    add_bad("2^54 is rejected", {}, 18014398509481984, "payload", D_MAGNITUDE)
    add_bad(
        "2^53+1 is rejected", {}, 9007199254740993, "payload", D_MAGNITUDE,
        unrepresentable_in=["typescript"],
        unrepresentable_reason=(
            "TypeScript has no integer type: 9007199254740993 rounds to 2^53 "
            "before any validator can observe it, so the vector cannot be "
            "presented to the TS validator at all"
        ),
    )
    add_bad("a large double is rejected too (every double above 2^53 is an integer)",
            {"type": "number"}, 1e300, "payload", D_MAGNITUDE)
    add_bad("the guard reaches inside an object", {"type": "object"},
            {"id": 18014398509481984}, 'payload["id"]', D_MAGNITUDE)
    add_bad("the guard reaches inside an array", {}, [1, 18014398509481984],
            "payload[1]", D_MAGNITUDE)
    add_bad("the guard runs before the type check", {"type": "string"},
            18014398509481984, "payload", D_MAGNITUDE)
    add_ok("a small negative float is untouched", {"type": "number"}, -0.5)

    # -- ordering between checks -------------------------------------------
    add_bad("required is reported before a property mismatch",
            {"type": "object", "properties": {"a": {"type": "integer"}},
             "required": ["b"]}, {"a": "x"},
            "payload", d_required_missing("b"))
    add_bad("the type check precedes const",
            {"type": "string", "const": "x"}, 1,
            "payload", d_expected_type("string", "integer"))
    add_bad("properties are reported in sorted key order",
            {"type": "object", "properties": {"z": {"type": "integer"},
                                              "b": {"type": "integer"}}},
            {"z": "x", "b": "y"},
            'payload["b"]', d_expected_type("integer", "string"))

    # -- path rendering -----------------------------------------------------
    add_bad("a deep path names every step",
            {"type": "object", "properties": {"a": {"type": "object", "properties": {
                "b": {"type": "array", "items": {"type": "integer"}}}}}},
            {"a": {"b": [1, "x"]}},
            'payload["a"]["b"][1]', d_expected_type("integer", "string"))
    add_bad("a key with a dot is bracketed, not joined",
            {"type": "object", "properties": {"a.b": {"type": "integer"}}},
            {"a.b": "x"}, 'payload["a.b"]', d_expected_type("integer", "string"))
    add_bad("a key with a quote is escaped",
            {"type": "object", "properties": {'a"b': {"type": "integer"}}},
            {'a"b': "x"}, 'payload["a\\"b"]', d_expected_type("integer", "string"))
    add_bad("a required key with a quote is escaped in the detail",
            {"type": "object", "required": ['a"b']}, {},
            "payload", d_required_missing('a"b'))
    add_ok("a non-ASCII key is emitted literally",
           {"type": "object", "properties": {"héllo": {"type": "string"}}},
           {"héllo": "日本語"})
    add_bad("a non-ASCII key in a path is emitted literally",
            {"type": "object", "properties": {"héllo": {"type": "string"}}},
            {"héllo": 1}, 'payload["héllo"]', d_expected_type("string", "integer"))


def main() -> None:
    build_instance_extras()
    schema_vectors: list[dict] = []
    for name, schema in SCHEMA_OK:
        schema_vectors.append({"name": name, "schema": schema, "valid": True})
    for name, schema, path, detail in SCHEMA_BAD:
        schema_vectors.append({
            "name": name, "schema": schema, "valid": False,
            "path": path, "detail": detail,
        })
    instance_vectors = type_matrix() + INSTANCE_EXTRA

    seen: set[str] = set()
    for vec in schema_vectors:
        key = "schema:" + vec["name"]
        if key in seen:
            raise SystemExit(f"duplicate vector name: {vec['name']}")
        seen.add(key)
    for vec in instance_vectors:
        key = "instance:" + vec["name"]
        if key in seen:
            raise SystemExit(f"duplicate vector name: {vec['name']}")
        seen.add(key)

    doc = {
        "_comment": (
            "Generated by conformance/gen_payload_schema_vectors.py -- do not "
            "edit. Cross-language vectors for the declared-payload-schema "
            "validator (effects contract §19.5). Replayed by the Python, Go "
            "and TypeScript unit suites."
        ),
        "schema_vector_count": len(schema_vectors),
        "instance_vector_count": len(instance_vectors),
        "schema_vectors": schema_vectors,
        "instance_vectors": instance_vectors,
    }
    OUT_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(schema_vectors)} schema vectors and "
        f"{len(instance_vectors)} instance vectors to {OUT_PATH}"
    )


if __name__ == "__main__":
    main()
