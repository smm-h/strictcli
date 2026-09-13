# go: a dry run previews a Write whose parent directory does not exist

## Context

`Effects.Write` (and `Chmod`, `Rename`) in `go/strictcli/effects.go` record
the effect in dry mode and perform it in live mode. `Write` does not create
parent directories; a live write into a missing directory fails with the
operating system's `no such file or directory`.

## Problem

In dry mode the same call records `write: notes/milk.md (9 bytes)` and the
dispatch exits 0, so the preview says the write would happen when the live
run cannot perform it. A consumer hit this with a handler that wrote
`notes/<file>` without a preceding `Mkdir`: the dry run was clean, the live
run failed. A preview that lists an effect the live run would refuse is the
one thing dry mode exists to never do.

The same shape applies to `Rename` with a missing source or a missing
destination directory, and to `Chmod` and `Remove` on a missing path.

## Solutions

1. In dry mode, check the precondition the live call would need (parent
   directory exists for `Write`; source exists and destination directory
   exists for `Rename`; path exists for `Remove` and `Chmod`) and, when it
   fails, record the effect with a visible annotation and end the preview the
   way an unsettled read does: exit 1 with the partial would-do log and a line
   naming the missing precondition. Recommended: it keeps the preview honest
   without changing live behavior, and the annotation tells the author which
   `Mkdir` is missing. An earlier recorded `Mkdir` of that directory in the
   same dry run satisfies the precondition (the preview tracks what it would
   have created).
2. Make `Write` create parent directories in live mode and record a
   `mkdir` line for them in dry mode. Simpler for authors, but it widens what
   a `Write` does and hides a decision (which directories get created) that
   the effects log should state.

## Affected files

- `go/strictcli/effects.go` (`Write`, `Rename`, `Remove`, `Chmod`, the
  dry-mode branch of `pathEffect`)
- `go/strictcli/effects_test.go`: red-green tests for each precondition,
  including the case where an earlier recorded `Mkdir` satisfies it
- the Python and TypeScript ports for parity, with conformance cases

## Effort

Medium: the precondition checks are small, the preview bookkeeping of
"directories this dry run would have created" is the real work, and parity
across three implementations plus conformance cases follows.
