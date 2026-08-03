# Trio purity: drive the registered cross-implementation extras to zero

Filed 2026-08-03.

## Context

The stated goal for the three implementations is exact symmetry: none has anything the others lack. The enforcement machinery (conformance cases, error-parity, api-surface with exclusion registers, fuzzer) holds behavior in lockstep, and the doctrine is in CLAUDE.md ("When adding a feature to one implementation, add it to all"). But a short list of genuine extras exists today, documented in the repo's own conventions:

1. **Python `app.acall(...)`** — async variant of programmatic invocation. No Go/TS counterpart.
2. **Python `ctx.source_map()`** — "Python additionally exposes" per CLAUDE.md. No Go/TS counterpart.
3. **Go `Default(nil)` help nuance** — "(Go only)": flags with `Default(nil)` display `[optional]` instead of `[default: <nil>]`.
4. **TypeScript args-first handler signature** — `handler: (args, ctx) =>` while Go and Python are ctx-first. A deliberate structural divergence, not an accident.

(Serialization asymmetries are covered separately by `todo/schema-v2-single-migration.md`. Language-idiom exclusions in `check_api_surface.py` — non-serializable callables, private Go fields — are not extras and stay.)

## Decisions to make (not yet made — options below)

### Items 1-3: port or remove?

- **Port to all three**: `acall` → Go has no async idiom mismatch (goroutines make a dedicated variant questionable — a Go `Acall` may be un-idiomatic noise); `source_map` → mechanical, genuinely useful, cheap in Go/TS; `Default(nil)` display → trivial to replicate in Python/TS help renderers.
  - Pros: nothing is lost; symmetry achieved additively.
  - Cons: `acall` in Go/TS is API surface added only for symmetry's sake — surface nobody asked for.
- **Remove from the one that has it**: delete `acall` (callers wrap in their own async), delete `source_map` (callers iterate `source()`), normalize the `Default(nil)` display in Go to match the others.
  - Pros: smallest total surface; symmetry by subtraction.
  - Cons: breaking for existing Python callers (0.x, so minor bump); `source_map` and the nil-display are arguably the better behaviors — removing them makes all three slightly worse.
- Reasonable split verdict: port `source_map` and the `[optional]` display (they are improvements), decide `acall` on its own merits (port vs remove).

### Item 4: TS handler signature

- **Unify to ctx-first** (breaking change for every TS consumer): full symmetry, one documented contract. The TS type-inference machinery (`infer.ts`) was built around args-first; unification is M-L work plus a breaking release.
- **Declare permanent idiom**: record args-first in the api-surface exclusion register with rationale (TS ergonomics: args destructuring dominates usage). Symmetry doctrine gains one permanent, documented exception.

## Affected files

Per item: `python/strictcli/__init__.py`, `go/strictcli/*`, `typescript/src/{app,infer,index}.ts`, conformance cases for whatever lands, CLAUDE.md conventions section, `check_api_surface.py` exclusion registers (entries removed or made permanent-with-rationale).

## Effort

Items 1-3: S-M each. Item 4 unification: M-L plus a breaking TS release; declaring it permanent: S.
