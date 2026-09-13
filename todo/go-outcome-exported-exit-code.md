# go: Outcome needs an exported exit-code accessor

## Context

`Outcome` (`go/strictcli/outcome.go`) is the branded handler result, minted
only by `Exit(code)`. Its exit code is an unexported field the framework reads
when it ends a dispatch.

## Problem

A wrapper that adapts a handler of its own shape onto go-strictcli's
`PassthroughHandler` (which returns a plain `int`) has to turn an `Outcome`
back into its code, and there is no exported way to do it. The only options
are reflection on the unexported field, which breaks silently if the struct
changes, or re-minting the code through a second channel. A consumer chose
the reflection route and confined it to one function; that is a shape the
framework should not force.

## Solutions

1. Add `func (o Outcome) Code() int`. Recommended: the brand stays intact
   (only `Exit` mints, `Code` reads), the method is one line, and it gives
   every adapter, test and wrapper the same read the framework itself uses.
2. Change `PassthroughHandler` to return `Outcome` like every other handler.
   Consistent, but a breaking change to every passthrough consumer, and the
   read is still needed elsewhere (tests asserting on an outcome).

## Affected files

- `go/strictcli/outcome.go` (the method)
- `go/strictcli/outcome_test.go` (a test that `Exit(3).Code() == 3`)
- the Python and TypeScript ports for parity (`outcome.exit_code`, `outcome.exitCode`), if the API surface check requires it

## Effort

Small.
