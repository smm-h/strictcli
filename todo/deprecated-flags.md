# Deprecated-flag declarations: machine-readable rename bridges

Filed 2026-08-03.

## Context

Deprecation exists for commands only: `app.deprecate(name, message=...)` / `group.deprecate(...)` register a tombstone that prints the message to stderr and exits 1 (`python/strictcli/__init__.py:3815`, `:2274`; routing hard-error at `:4596-4600`; schema `deprecated: {name: message}` at `:7797-7799`). `Flag` and `Arg` have no deprecation surface at all.

Consequence for the surface-diff classifier: a flag rename (`--foo` → `--bar`) is structurally indistinguishable from remove+add. Without a declared bridge, rename detection is heuristic (help/type/env/short fingerprint matching) — a knowingly-unsound classifier.

## Decided design

- **Semantics: hard-error tombstone**, matching the command precedent. Warn-and-work was rejected (no-warnings / no-silent-degradation rules); alias-with-replacement was rejected as a compat shim in disguise (old surface keeps working — banned pre-stable). The tombstone carries a structured `replaced_by` field, which is the machine-readable bridge: using the old flag hard-errors with a message naming the replacement, and the classifier resolves the rename exactly.
- **Placement: a parallel `deprecated_flags` map** on Command/App mirroring the command mechanism (`App._deprecated`), keeping `Flag` clean and reserving the old name (collision checks like `:3822-3833`).
- **Commands gain `replaced_by` too**, changing the schema shape from `deprecated: {name: string}` to `{name: {message, replaced_by?}}`. This is a breaking schema change; the docs generator reads `deprecated` and must be updated in the same pass. Fold the shape change into the v2 migration (`todo/schema-v2-single-migration.md`) so the format bumps once.
- Global flags: declared at app level, tombstoned in every command namespace.
- Edge: flags named under the reserved `no-` prefix (pre-ban legacy) cannot be re-declared as tombstones; document as unsupported.

## Open sub-question

Extend the same treatment to `Arg` (positional renames/removals) and to `choices` values (a removed enum member is breaking with no declaration surface)?

- **A. Same pass** — one design, one triple-tax round, complete bridge coverage. More scope now.
- **B. Flags only now, args/choices later** — smaller change, but a second triple-tax round later for a mechanism that is conceptually identical.

Most-correct answer is A; the cost difference is real but bounded.

## Cost: the nine-touch-point triple-tax

A new flag-adjacent field touches (traced via the analogous `env_separator`): the Python dataclass+serializer+defaults block; the Go struct+option func+schema writer; the TS factories+types+schema writer; `conformance/ref_python.py` (two sites); both runtime harnesses; `conformance/schema.json` (`$defs.flag` has `additionalProperties: false` — unknown keys hard-fail); new `cases/` file (mirror `cases/deprecated.json`); `check_api_surface.py` entity descriptors (note: `deprecated`/`deprecated_message` currently sit in `_GLOBAL_SCHEMA_TEST_ONLY`, `:293-300`, and must move into the real-field regime); `check_error_parity.py` signature registration in all three; `RICH_APP` extension in `check_schema_parity.py`.

## Affected files

Listed above. Docs generator's deprecated-reader in the same pass.

## Dependencies

The surface-diff classifier's rename detection depends on this landing first (sound-before-shipped rule: no heuristic-classifier interim).

## Effort

L — the framework code is M, the conformance triple-tax dominates.
