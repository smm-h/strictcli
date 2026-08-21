# Conditional consequential: make it official or ban it

## Context

`consequential` is a static registration property: a command either always
participates in the confirm protocol or never does. Real CLIs keep producing
commands where only *some* invocations warrant confirmation:

- A choice flag selects among modes of which exactly one is destructive
  (e.g. a maintenance command whose `--action` includes an `uninstall`
  member alongside harmless diagnose/repair members).
- An optional flag raises the stakes of an otherwise routine operation
  (e.g. a force flag on a push-like command).
- A runtime-discovered condition raises the stakes (e.g. the operation's
  target turns out to be publicly visible, which the caller may not know
  and cannot declare).

## Problem

Because the framework offers only the static property, consumers hand-roll
app-level confirmation seams for these cases: they detect the condition
themselves, prompt at a TTY themselves, honor `--approve-consequential` (or
mint a dedicated consent flag for runtime-discovered conditions) themselves,
and implement decline-exits-nonzero and machine-mode-refuses themselves.

This fragments the confirm protocol:

- The framework cannot see these prompts, so nothing validates them at
  registration and nothing guarantees they behave uniformly (TTY detection,
  decline semantics, `--json` interaction, `--dry-run` interplay).
- The consequential set stops being a curated, visible list -- part of it
  lives in registration, part in scattered handler code.
- Every consumer re-derives the same seam slightly differently, which is
  the drift the effects regime exists to prevent.

## The ruling to make

Two coherent positions; pick one and enforce it.

### A. Make the conditional form official

Registration-time declaration for conditions the caller types, e.g.
`WithConsequentialWhen(...)` tied to a specific flag's presence or to a
named member of a choice flag. The framework then owns the prompt, the
`--approve-consequential` answer, decline semantics, and machine-mode
refusal, exactly as for static consequential.

- Pros: one protocol, uniform semantics, the condition is declared (zero
  inference -- the trigger is a flag the caller typed, visible in the
  schema); the consequential set stays enumerable (static members plus
  declared conditions).
- Cons: predicate scope must be deliberately narrow (flag presence /
  choice-member equality only -- never arbitrary predicates, or the
  declaration stops being analyzable); runtime-discovered conditions are
  NOT coverable by a registration-time declaration and need either a
  separate runtime confirmation API (with its own dedicated-consent-flag
  convention, since the blanket flag must not pre-answer a condition the
  caller could not have known) or an explicit statement that they remain
  app-level.

### B. Ban it: divide into separate commands/flags

Document and enforce that conditionally-destructive surfaces must be split:
the destructive member becomes its own command (or its own required flag
spelling) registered statically consequential; the harmless members stay
non-consequential.

- Pros: the consequential set is fully static and visible; the framework
  stays smaller; command lines become more explicit (a destructive
  invocation is a visibly different command, which suits the
  verbose-over-terse philosophy).
- Cons: command-surface proliferation; enforcement is hard to make
  mechanical (detecting a hand-rolled prompt in handler code is not
  reliably lintable, so the ban is documentation plus review pressure);
  and runtime-discovered conditions cannot be split statically at all --
  under a pure ban they degenerate into always-consequential (prompting in
  the safe case too, eroding the signal) or stay hand-rolled anyway.

### The runtime-discovered case decides more than it seems

Both rulings handle the typed-flag case cleanly. Neither handles the
runtime-discovered case without something new. Whichever ruling is chosen
should explicitly state what a consumer does when the stakes are only
knowable mid-execution: an official runtime confirmation API, a documented
app-level seam pattern with named requirements (TTY prompt, dedicated
consent flag, decline exits nonzero, machine mode refuses), or a statement
that such conditions must be restructured out (e.g. a mandatory
pre-declaration flag that makes the caller assert the condition's answer
up front).

## Affected areas

- Registration surface (`WithConsequential` family) in all three language
  implementations, kept in lockstep
- The confirm protocol implementation (prompt, `--approve-consequential`,
  decline, machine-mode refusal)
- Schema dump (declared conditions should be visible in `--dump-schema`)
- Docs: the effects-regime contract section
- If A: registration-time validation (a declared condition must reference
  an existing flag/member; a `read_only` command still cannot declare one)
- If B: the documented design rule plus whatever check pressure is feasible

## Effort estimate

Ruling A: medium -- new registration option, confirm-protocol wiring,
schema exposure, tests, three implementations. Ruling B: small in code
(documentation and a design rule), but pushes migration cost onto
consumers. The runtime-discovered-case statement is required under both.
