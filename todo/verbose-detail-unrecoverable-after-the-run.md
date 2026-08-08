# Verbose detail is unrecoverable once the run is over

## Context

Verbosity is decided before an invocation runs (`--verbose`/`--quiet` are
framework-owned reserved flags), but whether the verbose detail is needed is
usually discovered after the invocation finishes. The reserved flags act as
emission-time filters: whatever they suppress is never produced anywhere, in
any form.

## Problem

A caller runs a command, reads the normal output, and only then realizes the
diagnostic detail was needed. That detail is gone, and there is no honest way
to get it back:

- Re-running with `--verbose` is not the same execution. State has changed,
  and timing-dependent events (retries, waits, transient failures that
  resolved themselves) will not replay. The second run answers a different
  question than the one the caller has.
- Effectful commands cannot be safely re-run at all. The mutation already
  happened; the detail that would explain what it did during the run cannot be
  regenerated afterward by any means.
- For agent callers this is acute: the transcript is the only record of the
  run. An agent that omitted `--verbose` has permanently less information than
  one that passed it, and it cannot know in advance which runs will turn out
  to need the detail.

Concrete shapes of the loss:

- A command internally retries a transient failure and succeeds. Without
  `--verbose`, nothing anywhere records that the contention happened, so
  intermittent slowness or flakiness is undiagnosable after the fact.
- A long multi-step mutation partially fails. The non-verbose output names the
  failure, but the per-step detail that would explain how it got there was
  suppressed at emission time and the run cannot be repeated.
- A caller comparing two runs of the same command cannot tell whether they
  differed in behavior or only in what was printed.

This is framework-level, not app-level: apps cannot fix it individually
because the suppression happens in framework-owned flags before app code can
record anything.

(Deliberately problem-only; no solution prescribed.)
