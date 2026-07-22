# Effect-interpreter execution model (rung 10, deferred)

Filed 2026-07-22, deferred by explicit decision on the same day. This records the summit
design of a ten-rung ladder produced while redesigning global-flag handling; the adopted
design ("A") is rungs 3+4+5+7 of that ladder. This file preserves rung 10 ("B") so the
option survives with its reasoning intact.

## Context

Motivating incident: a consumer CLI command received `dry_run` into `**kwargs`, dropped it,
and published a package to a public registry during a `--dry-run`. The first fix (guard v1)
forced handlers to name every global flag; the residual class — a handler that NAMES a flag
and IGNORES it — remained. A consumer census found roughly a dozen mutating commands in one
consumer alone that accept `--dry-run` and silently execute for real.

The adopted design A closes most of the class:

- Global flags split into two classes: universal (output modifiers; auto-delivered, handlers
  must name them) and scoped (behavior gates like dry-run/yes; per-command opt-in, parse-time
  hard rejection elsewhere; absence of a declaration means "supports none").
- Every command declares `read_only` or `mutating`; gate applicability derives from it.
- `--yes` confirmation is framework-owned (prompt before dispatch, clean non-TTY hard error);
  `--quiet` is honored at the Context output layer. Handlers never see either.
- Dry-run honoring flows through injected, mode-aware effect handles (`ctx.effects.run()`,
  `.write()`, etc.): in dry mode the framework injects a recording no-op implementation, so
  handler code is identical in both modes.
- A lint-style check provider flags direct subprocess/socket/ambient-effect usage in handler
  modules.

A's one seam, deliberately accepted: `ctx.effects` is cooperative. A handler can bypass it
with a direct ambient call; the lint makes that visible but does not make it impossible.

## Problem this deferred design solves

- The cooperative seam: with A, "dry-run performed a real mutation" is still expressible by
  a handler that routes around the handles.
- Simulation drift: any handle-based dry mode is only as faithful as the no-op
  implementations; there is no structural guarantee that dry and real paths stay in step.
- Per-language enforcement asymmetry: sealing the seam by sandboxing (rung 8 of the ladder,
  explicitly declined) would require audit hooks in Python, lint/build-tag walls in Go, and
  module-graph restriction in TypeScript — three different guarantees, which breaks the
  conformance-parity spine of this project.

## The design

Handlers become resumable effect streams; the framework is the interpreter.

- A handler never touches the world. It yields effect REQUESTS one at a time (Python:
  generator/coroutine; Go: channel-driven step function; TS: async generator) and is resumed
  with each RESULT. Effects may depend on prior effects' results (the property that pure
  plan-returning handlers, rung 9, cannot express).
- The interpreter performs requests in real mode; in dry mode it simulates results and
  records an effect log while performing nothing. `--dry-run`, `--yes`, `--quiet` all become
  interpreter modes over one protocol: dry mode = simulate; yes = prompt before the first
  mutating effect; quiet = filter emitted output effects.
- The effect protocol is a serializable request/response contract (one normative spec,
  request and response shapes per effect kind). A command's read_only/mutating nature is
  derived: whether its stream ever yields a mutating effect. No per-command declarations of
  any kind remain.
- Conformance story: fixtures assert the exact ordered effect stream for a given app-def and
  argv, and assert the performed-set is empty in dry mode — identical across all three
  implementations. This is the strongest conformance story of any rung.

Properties: accept-but-ignore is not forbidden but MEANINGLESS — there is no flag to ignore
and no user code that can act. Silent swallowing, sandbox bypass, and dry/real drift are all
structurally eliminated at once. There is no cleaner design above this one; its only costs
are effort and paradigm.

## Pros

- Eliminates the entire bug class by construction, including A's cooperative seam.
- Zero declaration ritual; effect class derived, not declared.
- Best-possible conformance testability (byte-comparable effect streams).
- Uniform extensibility: a new effect kind is one protocol addition + three interpreter
  implementations + fixtures.

## Cons

- A framework rewrite: resumable-handler runtime + interpreter in three languages, plus the
  protocol spec. The hardest kind of parity (suspension semantics, error propagation, async).
- Every effectful consumer handler must be rewritten in effect-yielding style; per app it is
  effectively big-bang (a handler is either yielded or it is not).
- New paradigm for every future author; stack traces cross the yield boundary; higher misuse
  surface for shortcut-prone agent authors.
- Dry-mode fidelity depends on simulated results; a wrong simulation sends the resumed
  handler down untraveled paths.

## Why deferred (and what preserves the path)

A keeps B reachable at roughly its marginal cost: routing all side effects through the
single `ctx.effects` object is precisely the refactor B requires anyway, and handle
call-sites convert to yield-sites near-mechanically. Revisit this design if:

- the lint seam produces a real incident (a handler bypassing the handles and mutating in
  dry mode), or
- a new effect kind strains the handle model (handles multiplying per domain), or
- dry/real drift bugs appear in handle no-op implementations.

## Affected files (as of filing)

- `python/strictcli/__init__.py` — dispatch, delivery loop, Context; would gain the
  interpreter and resumable invocation.
- `go/strictcli/` and `typescript/src/` — same, per implementation.
- `conformance/schema.json`, `conformance/cases/`, harnesses — effect-protocol spec and
  stream fixtures.
- All consumer apps' mutating handlers (rewrite to yielding style).

## Effort estimate

Multi-month. The runtime/interpreter blocks everything downstream; consumer migration is
per-app big-bang. Compare: design A was estimated at weeks-scale and parallelizable.
