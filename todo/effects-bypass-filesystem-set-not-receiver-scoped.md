# effects-bypass: the filesystem bypass set is not receiver-scoped

## Problem

The `effects-bypass` check's `_BYPASS_FILESYSTEM` set contains bare method
names (notably `"replace"`, aimed at `os.replace`) and, unlike
`_BYPASS_NETWORK` (which is receiver-scoped), matches ANY `.replace(...)`
call on ANY receiver inside a reachable handler. Consequence observed in a
consumer: two ordinary `str.replace` calls (building a flag spelling from a
parameter name; normalizing a kind literal) were flagged as error-severity
"direct effect call(s) bypassing ctx.effects".

The finding's own remedy ("route it through ctx.effects") cannot be
followed for a string method — and the check's surrounding comments state
that a lint must never emit an unfollowable remedy. The consumer had to
rewrite the expressions without the method name (`"-".join(s.split("_"))`)
purely to dodge the matcher.

## Fix directions

1. Receiver-scope the filesystem set the same way the network set already
   is (e.g. only flag `os.replace` / `Path.replace` / bare `replace`
   imported from os) — the most correct fix; the two sets become
   symmetrical.
2. At minimum, drop `"replace"` from the unscoped set (it is the only
   member with a high-frequency str collision) — a stopgap that loses
   `os.replace` coverage.

(1) is the right shape. Red-green with a fixture handler carrying a
`str.replace` (must pass) and an `os.replace` (must be flagged).

## Also, smaller: the dry-run footer prints after a refusal

When a `--dry-run` invocation hard-errors (e.g. an argument-validation
refusal), the framework still prints "DRY RUN — no changes were made.
Would do:" after the error text, implying a plan where there is none. The
footer should be suppressed when the handler exited via an error.

## Effort

Small-medium (both), Python first, mirrored to the other language
implementations with conformance fixtures.
