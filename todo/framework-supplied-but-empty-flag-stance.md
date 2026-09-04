# Proposal: a framework-level supplied-but-empty flag stance

## Context

strictcli already distinguishes "flag not supplied" from "flag supplied"
(absence reaches handlers as absence, never as `""` or `0`). But a flag
supplied with an explicitly EMPTY string value (`--name ""` or
`--name=`) is delivered to the handler as an ordinary value, and what
that means is left entirely to each consumer.

## Problem

In practice an explicitly-empty string value is almost never a
meaningful input: it is a shell-quoting accident or a templating bug,
and consumers either silently treat it as absent (the dangerous default
— an empty `--include` filter silently selecting everything is the
observed worst case) or hand-write per-flag refusals. Per-consumer
empty-string refusals are accumulating guardrails against the same bug
class; the framework is the place to close the class.

## Solutions

1. **Framework default: supplied-but-empty is a parse-time hard error**
   for string flags, with a per-flag opt-in (`AllowEmpty()` or similar)
   for the rare flag where empty is a legitimate value. Pros: closes the
   class everywhere at once, consistent with the no-implicit-defaults
   philosophy; cons: breaking for any consumer that relied on empty
   values (pre-stable, so acceptable), needs the opt-in escape to be a
   deliberate declaration rather than a convenience bypass.
2. A supplied-or-not predicate exposed to handlers plus a lint that
   flags string comparisons against `""`. Weaker: keeps the decision
   per-consumer, just makes it visible.
3. Status quo with documented guidance. Rejected by the philosophy:
   agents ignore guidance; hard constraints work.

(1) is the most correct: one registration-time stance, enforced by the
framework, mirrored across the language implementations, covered by the
conformance suite.

## Affected

- Flag parsing/validation in each language implementation, registration
  API (the explicit opt-in), conformance fixtures, docs.

## Effort

Medium (three implementations plus conformance).
