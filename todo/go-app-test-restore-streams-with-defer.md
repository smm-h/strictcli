# go: App.Test must restore os.Stdout and os.Stderr with defer

## Context

`App.Test` in `go/strictcli/strictcli.go` swaps `os.Stdout` and `os.Stderr`
for pipe write ends, runs the handler inside `runSealed`, and restores the
originals afterwards with plain assignments after the call returns.

## Problem

`runSealed` re-panics after finishing a dispatch whose handler panicked (it
emits the machine-mode wrapper with exit status 2 and then propagates the
panic). Because the restore is not deferred, a handler panic under `Test`
propagates past the restore, and the process keeps the pipe ends as its
`os.Stdout` and `os.Stderr` for the rest of its life. Every later `fmt.Println`
in that process, including the test binary's own output, is lost. Observed by
a consumer test suite: after a test that drives a panicking handler through
`App.Test` (for example the payload-without-schema hard error), subsequent
writes to real stdout and stderr produce nothing, and test files only keep
working when such a test happens to run last.

## Solutions

1. Restore with `defer` immediately after the swap, and close/drain the pipes
   in the same deferred block. Recommended: it is the ordinary Go shape for a
   swap-and-restore, and it makes the drain goroutines and the restore
   independent of whether the handler returned or panicked.
2. Recover the panic inside `Test`, restore, then re-panic. Equivalent
   outcome with more code; only preferable if the drain must complete before
   the panic propagates, which `defer` also achieves if the drain wait is in
   the deferred block.

## Affected files

- `go/strictcli/strictcli.go` (`App.Test`, the swap and restore around
  `runSealed`)
- `go/strictcli/strictcli_test.go` or `effects_test.go`: a red-green test that
  drives a panicking handler through `Test` inside a `recover`, then asserts
  that `os.Stdout` and `os.Stderr` are the originals again.

## Effort

Small: one deferred block plus one regression test.
