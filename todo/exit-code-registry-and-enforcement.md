# Exit-code registry: declared vocabulary, framework-enforced

## Context

The framework itself exits with only 0 and 1: success (plus --help/--version/
--dump-schema paths) and everything else -- parse errors, registration
failures, declined confirmations all map to 1. Everything beyond that is
consumer territory, and consumers grow real exit-code vocabularies: distinct
codes for guard refusals, timeout classes, subsystem failures, and
passthrough propagation of a wrapped tool's own codes.

## Problem

The framework offers nothing to declare, validate, or render that
vocabulary, so in practice a consumer's exit codes end up:

- **Scattered.** Constants declared per-file next to their commands, plus
  bare literals at direct exit sites, with no single authority. An audit of
  one mature consumer found its vocabulary declared across six-plus
  locations, with several codes existing only as inline literals.
- **Drifting from docs.** Hand-maintained exit-code tables in the
  documentation omit real codes and document codes that do not exist.
  Nothing ties the table to the code.
- **Inconsistent with the framework.** A consumer documents "exit 2 = usage
  error" for its own in-handler argument guards, while every framework-level
  parse/usage error exits 1 -- so the same class of mistake produces
  different codes depending on which layer catches it, and no ruling exists
  on which is right.
- **Fragile in the error path.** Typed error values carrying codes are
  consumed by bare type assertions; one added `%w` wrap silently degrades a
  meaningful code to 1 with nothing catching it.

This is the same shape as other framework-vs-consumer seams: the fact
(the vocabulary) should be declared once, validated at registration, and
everything else derived from it.

## The feature to rule on

Three escalating levels; pick the target (they nest, so a lower level can
ship first).

### A. Declared registry, schema exposure

An app-level declaration, e.g. `WithExitCodes(...)`: each entry is a code, a
stable name, and a mandatory meaning string. Registration-time validation:
codes unique; 0 and 1 refused (framework-owned); optionally warn on ranges
with established outside meanings (sysexits 64-78, shell 126/127/128+N).
The declared table rides `--dump-schema`, so generated docs render the
exit-code table from the declaration and hand-maintained tables (and their
drift class) disappear.

- Pros: single authority, docs generated not hand-kept, cheap to adopt
  incrementally; no behavioral change to any consumer.
- Cons: declaration is not enforcement -- a bare literal at an exit site
  can still bypass the registry silently.

### B. Registry plus mechanical enforcement

Handlers stop exiting directly: they return a declared code (or a typed
error carrying one), and the framework performs the exit. A check in the
existing check family flags direct `os.Exit` / exit-literal usage in app
code, the way the effects-bypass check flags subprocess calls made behind
the effects handle's back. The framework consumes typed errors with
`errors.As`-style unwrapping so wrapping cannot silently strip a code.

- Pros: undeclared codes become structurally impossible rather than
  discouraged; the wrap-degradation trap is closed in one place for every
  consumer.
- Cons: consumers with pre-framework exit paths (direct exit sites that
  deliberately bypass the envelope) need a migration story; the check needs
  the same reachability analysis the effects-bypass check already does.

### C. Rule the usage-code question while at it

Whether in-handler argument validation should exit 1 (matching the
framework's own parse errors -- one usage code everywhere) or whether the
framework should adopt a distinct usage code itself (e.g. 2, the common
Unix convention) for both parse-level and handler-level usage errors. Either
answer is defensible; the current split -- framework says 1, consumers
document 2 -- is the worst of both. This ruling belongs to the framework
because parse-level errors are framework-emitted and consumers cannot
change them.

## Affected areas

- Registration surface + validation (all three language implementations,
  kept in lockstep)
- `--dump-schema` output (declared exit codes as a new section)
- The dispatch exit path (level B: framework-performed exits, typed-error
  unwrapping)
- The check framework (level B: a bare-exit check)
- Docs: the app-authoring guide's error-handling section
- Downstream: doc generators can render exit-code tables from the schema

## Effort estimate

Level A: small-medium -- declaration, validation, schema plumbing, tests,
three implementations. Level B: medium -- the exit-path inversion plus the
check. Level C: a ruling plus a one-line change wherever the answer lands.
