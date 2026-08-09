# Auto-generated per-command dry-run assertions

Filed 2026-08-09, split out of `todo/.done/dry-run-airtight-enforcement.md` (item S9 of that
file). That file was moved to `.done/` because the effects regime satisfied or superseded
everything else it parked; this one idea is the only part that was never built, so it is
preserved here rather than lost in a closed file.

## Problem

The effects regime makes dry-run honoring structural: a command declares `effect`, side
effects flow through the closed `ctx.effects` method set, and in dry mode calls record instead
of performing. What it does NOT provide is a per-command *guarantee that anyone checked*.
Nothing asserts, for each registered command, that a dry run of that command performs zero
effects. The absence shows up as:

- A handler can drift (a new direct ambient call, a write moved above an early return) and
  only the `effects-bypass` lint stands between that and a real mutation during a preview.
  The lint is a static receiver-scoped scan; it is not an executed proof for a given command.
- `cli-test-coverage` tracks which commands `app.test()` exercised at all. That is a
  different property: a command can be covered by tests and still never be exercised under
  `--dry-run`.

## Direction (as parked, not designed)

A framework-provided test facility that, for every registered command, runs it under dry mode
and asserts the performed-set is empty — either as a generated per-command assertion or as a
single suite-level sweep with a per-command marker (the original file's sketch used a
`needs_dry_run`-style marker; nothing of that name exists in any implementation today).

Open questions that make this a design item rather than a task: how a sweep supplies valid
arguments for every command without a fixture per command; whether commands declaring
`dry_run_supported=False` are asserted to refuse rather than to perform nothing; whether the
facility belongs in the framework, in the conformance suite, or as a check provider; and
whether it applies to `read_only` commands (which already hard-error on unallowlisted
mutating effect calls) or only to `mutating` ones.

## Why deferred

It is a genuine gap, but a smaller one than it looks: the regime already fails closed at the
seam for anything routed through `ctx.effects`, and the bypass lint covers the ambient-call
drift case statically. The value here is defense in depth for handler drift, which matters
most as the number of mutating commands grows across consumers.

## Affected areas

- Framework test facility surface (Python reference first, then Go/TS parity).
- Possibly `conformance/` if the sweep is expressed as fixtures.
- Interaction with `dry_run_supported=False` commands and with the `cli-test-coverage` check.
