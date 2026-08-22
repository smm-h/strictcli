# DictFlag's ValidateFn is silently skipped, and dict values cannot be constrained at all

## Problem

A `DictFlag`'s per-element `ValidateFn` never runs — and never errors about
not running.

Mechanics (verified against the current source):

- `strictcli.go:1296` (`DictFlag`) sets `Repeatable: true` unconditionally
  (`:1303`, again `:1309`) and stores the parsed value as
  `map[string]interface{}`.
- `parse.go:794-812` validates a repeatable flag by asserting
  `val.([]interface{})` and, when the assertion fails, `continue`s — so for
  a dict flag (whose value is a map, not a slice) the loop silently skips
  validation entirely. No error, no warning: the declared validator is dead
  code.
- There is no second route to constrain dict values: `Choices()` panics on
  a dict flag (pinned by `TestDictFlagNoChoices`).

Net effect: `key=value` pairs with a closed value set are unrepresentable
as a dict flag. A consumer wanting validated `path=choice` pairs has to use
a repeatable `StringFlag` with a per-element `ValidateFn` (which does run)
and split on the separator itself — losing the dict shape the flag type
exists for.

## Expected behavior (one of)

1. Dict flags run their `ValidateFn` per entry (probably per `key=value`
   element as typed, so the validator can see both halves), OR
2. registration refuses a `ValidateFn` on a dict flag loudly, so the dead
   declaration is impossible, AND `Choices` (or an equivalent) becomes
   representable for dict values.

Silently accepting-and-ignoring a declared validator is the worst of the
three worlds and contradicts the framework's own hard-errors philosophy.

## Repro sketch

Declare a `DictFlag` with a `ValidateFn` that always errors; pass any
`key=value` on the command line; the command runs, the validator never
fires.

## Effort

Small-to-medium: the parse.go loop needs a map-aware branch (or a
registration-time refusal); tests for both the running-validator path and
the refusal path.
