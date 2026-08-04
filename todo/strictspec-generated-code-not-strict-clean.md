# strictspec generated code fails mypy --strict and blanket-noqas ruff

## Context

strictspec's Python code generator emits `_gen_*.py` validator/binding files
(with DO-NOT-EDIT headers) into consumer projects. A consumer running
`mypy --strict` and `ruff` over its whole tree found the generated output
fails both:

- **mypy --strict**: bare `dict` without type arguments; `X | None` values
  bound into non-Optional dataclass fields.
- **ruff PGH004**: a blanket `# ruff: noqa` header instead of targeted codes.

## Problem

Consumers that enforce strict typing and lint gates over their source tree
must special-case generated files (mypy exclusion patterns, per-file-ignore
blocks for `**/_gen_*.py`) — accumulating tool-config carve-outs for output
the generator could simply emit correctly. The blanket noqa also suppresses
every future rule for those files, hiding real issues.

## Expected

Generated code should pass `mypy --strict` as emitted (typed dict parameters,
Optional-consistent field bindings) and carry targeted suppressions only where
genuinely needed (with the specific rule codes), so consumers need zero
special-casing.

## Notes

The consumer-side exclusions are explicitly interim policy pending this fix;
they should be removable once the generator is clean. The TypeScript-side
generator (if any) should be checked for the same classes.

## Effort

M — generator template changes + a conformance check that generated output
passes strict mypy in the generator's own test suite (the structural fix that
prevents regression).
