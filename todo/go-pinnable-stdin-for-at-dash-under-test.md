# go: the `@-` flag value reads os.Stdin directly, so a test cannot pin it

## Context

A string flag value spelled `@-` is resolved at parse time by reading the
process's standard input (`go/strictcli/parse.go`, the `@` resolution). `Test`
runs a full parse in-process.

## Problem

A test harness that wants deterministic input for a handler has no way to
supply what `@-` reads: the parse reads `os.Stdin` itself, before any handler
or context exists, and `SetConfirmIO` covers only the confirm protocol. A
consumer that pins every other nondeterministic source for its tests (clock,
randomness, the handler's own stdin reader) is left with one path that reads
the real process stdin, which under `go test` is whatever the test binary
inherited.

## Solutions

1. Let `ConfirmIO.In` (or a new app-level `SetStdin(io.Reader)` test-only
   seam, restored with nil) also serve `@-` resolution, so one seam pins every
   framework read of stdin. Recommended: one seam, one place to reason about,
   and `Test` callers already know `SetConfirmIO`.
2. Have `Test` take an options struct with a `Stdin io.Reader` and thread it
   into the parse. More explicit, but a signature change on `Test` and a
   second seam beside `SetConfirmIO`.

## Affected files

- `go/strictcli/parse.go` (the `@-` branch)
- `go/strictcli/effects.go` (`ConfirmIO`, `SetConfirmIO`) or a new seam
- `go/strictcli/parse_test.go`: a red-green test that `Test` with a pinned
  reader resolves `--flag @-` from the pin, not from `os.Stdin`
- the Python and TypeScript ports for parity, with a conformance case

## Effort

Small in Go; parity across the three implementations is the larger part.
