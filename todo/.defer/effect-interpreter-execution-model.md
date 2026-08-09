# Effect-interpreter execution model (rung 10, deferred)

Filed 2026-07-22, deferred by explicit decision on the same day. This records the summit
design of a ten-rung ladder produced while redesigning global-flag handling; the adopted
design ("A") is rungs 3+4+5+7 of that ladder. This file preserves rung 10 ("B") so the
option survives with its reasoning intact.

AMENDED 2026-08-09 by explicit user authorization (todo files are otherwise immutable): the
sections describing the ADOPTED alternative were rewritten to match what actually shipped,
because design A's framing changed materially during implementation. The rung-10 design
itself is unchanged.

## Context

Motivating incident: a consumer CLI command received `dry_run` into `**kwargs`, dropped it,
and published a package to a public registry during a `--dry-run`. A consumer census then
found roughly a dozen mutating commands in one consumer alone that accepted `--dry-run` and
silently executed for real — the residual class being a handler that receives a flag and
ignores it.

What actually shipped — the effects regime (py 0.35.0 breaking through 0.38.0, go 0.30.0,
ts 0.37.0) — closes most of that class:

- The framework-reserved quartet `--dry-run`, `--approve-consequential`, `--quiet`,
  `--verbose` is reserved unconditionally at every level and delivered on the Context, never
  as handler kwargs; `--yes` is banned at registration. (The universal-vs-scoped global
  classes and app-level opt-in switches the original design proposed were never built —
  reserving the quartet outright made them unnecessary.)
- Every command declares `effect = "read_only" | "mutating"`, mandatory, no default. This
  answers only "should a dry run record instead of perform?".
- `consequential = True` is a SEPARATE declaration and the only thing that triggers a
  confirmation prompt (with a clean non-TTY refusal naming `--approve-consequential`). The
  original design keyed confirmation on `mutating`; fleet adoption falsified that — 391 of
  624 commands classify mutating, so a prompt keyed there would have been dead-but-present.
- Dry-run honoring flows through `ctx.effects`: a closed 8-method set with `Unsettled` value
  carriers and a runtime seal. In dry mode calls record instead of performing, so handler code
  is identical in both modes and never branches on a flag. `Grant` objects label why a
  mutation is permitted, `Forwarding(reason=...)` covers wrapper handlers, and
  `dry_run_supported=False` plus a mandatory reason lets a command refuse to preview honestly.
- A receiver-aware `effects-bypass` check provider flags direct ambient-effect usage in
  handler modules, alongside warn-level `observe-allowlist-breadth` and
  `consequential-grant-agreement`.

The shipped regime's one seam, deliberately accepted and recorded as a ceiling in its own
contract (`docs/history/_effects-contract.md`, §§16-17): `ctx.effects` is cooperative. A
handler can bypass it with a direct ambient call, and the lint — the sole mitigation for the
absence of OS sandboxing — makes that visible without making it impossible.

## Problem this deferred design solves

- The cooperative seam: under the shipped regime, "dry-run performed a real mutation" is
  still expressible by a handler that routes around the handles.
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

The shipped regime keeps this design reachable at roughly its marginal cost: routing all side
effects through the single `ctx.effects` object — now done fleet-wide and enforced by the
bypass lint — is precisely the refactor this design requires anyway, and handle call-sites
convert to yield-sites near-mechanically. Revisit this design if:

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
