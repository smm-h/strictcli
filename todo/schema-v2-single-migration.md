# Schema format v2: one migration for canonical serialization + behavioral completeness

Filed 2026-08-03.

## Context

Three schema-format-touching changes are in flight or planned. Per the collapse-multi-pass rule they must land as ONE `schema_version: 2` migration, not three consecutive bumps each rippling through three implementations, the conformance corpus, the docs generator, and the surface-diff tool:

1. **Canonical serialization** (this todo's core).
2. **Serializing currently-invisible behaviors** (this todo's second half).
3. **The globals redesign** (`todo/globals-redesign-design-a.md`), which already adds schema fields and may force the version bump on its own.

## Problem 1: serialization differences are compensated, not eliminated

Cross-language schema identity today is structural-after-normalization, not literal:

- Go does not pin key order (marshals through a map — `go/strictcli/schema.go` `writeSchema`; the TS module comment documents this: "Go sorts JSON map keys on marshal, so it pins content, not order"). Verified on disk: Go-emitted schemas start with `"commands"`, Python-emitted with `"schema_version"`.
- Go emits `"default": []` for repeatable flags where Python omits it; the parity checker deletes it via `_canonicalize_repeatable` (`conformance/check_schema_parity.py:726-751`).
- Compound-type spelling differs by language (object form vs `list[str]` string form).

Every consumer inherits the compensation layer, and each normalization rule is a place where a real change can be silently absorbed as serialization noise.

## Problem 2: the schema is blind to real behavior

Not serialized in v1 (verified against `_dump_schema_core`, `python/strictcli/__init__.py:7777-7862`): `config_format` (json/toml), `config_path`, `config_conflict_mode`, per-flag `conflict_mode` inheritance resolution, `flag_sets`, `prefixed`. Consequence: an app can relocate every user's config file while its schema stays byte-identical. The `defaults` block is also incomplete (`_build_schema_defaults`, `:7672-7719` — no conflict_mode, config_fields, checks, infra, constraint subtypes) and documents a field that does not exist (`defaults.flag.hidden`, `:7555`).

## The v2 definition

- **Declared key order**: canonical serialization order specified per entity in `conformance/schema.json` (`$defs`, the existing catalogue of every serializable entity), emitted identically by all three implementations. Go gets a custom ordered writer (the TS writer, built for SCF floats and bare bigints, is the in-repo template proving stock serializers can be replaced).
- **One spelling per construct**: omit-empty defaults everywhere; a single compound-type form.
- **Complete behavioral surface**: serialize the Problem-2 fields; complete the `defaults` block; remove the phantom field.
- **Globals redesign fields** fold in per that todo.

After v2: `schema-parity` becomes byte-equality (delete `_canonicalize_repeatable` and the structural comparator's tolerance), conformance gains byte-identical-dump cases, git diffs of committed schemas become readable fleet-wide, and the surface-diff tool needs no normalization layer for v2-to-v2 comparisons.

## Options considered

- **Three separate bumps** (serialize gaps now, canonicalize later, globals later): rejected — each bump triples through implementations + corpus + consumers.
- **Canonicalize without extending** (byte-stability but keep blind spots): rejected — the classifier's blind spots become permanent doctrine.
- **Single coordinated v2** (chosen): largest single change, but one migration, one consumer update round, one corpus revision.

## Affected files

- `python/strictcli/__init__.py` (serializer + defaults block), `go/strictcli/schema.go` (ordered writer, omit-empty), `typescript/src/schema.ts` (order table, spelling).
- `conformance/schema.json` ($defs key-order + new fields), `conformance/cases/` (byte-identity cases), `conformance/check_schema_parity.py` (byte-equality mode).
- Consumers to update in the same pass: the docs generator's schema reader, freshness checks, the surface-diff tool's materializer (reads v1 forever, v2 natively).

## Effort

L — tripled implementation + corpus + consumer round. Sequencing: land WITH the globals redesign; before the surface-diff classifier hardens (v2 then serves as its validation corpus).
