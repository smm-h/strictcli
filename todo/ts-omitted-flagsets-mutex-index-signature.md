# TS: omitting `flagSets`/`mutex` widens `HandlerArgs` with an index signature

## Context

Found while integration-testing the TypeScript implementation
(strictcli@0.37.0, verified identically under tsc 5.9.3 and 7.0.2, so
it is not a compiler-version artifact).

## Problem

When a command spec omits `flagSets` and `mutex`, the corresponding
generic parameters fall back to their *constraint* instead of their
`readonly []` default. `HandlerArgs` then takes the intersection
branch, and the handler's `args` picks up a string index signature:

- `keyof typeof args` becomes `string | number`
- `args.totallyUndeclared` typechecks, with type `{} | undefined`

Declared keys keep their exact types, so this is a typo hazard rather
than a wrong-type hazard — but it silently defeats the exact-keys
guarantee that is one of the TS implementation's selling points over
the Python side.

## Workaround (verified)

Declaring `flagSets: []` and `mutex: []` explicitly restores exact
keys, and is accepted at registration and runtime.

## Fix direction

Make the omitted-property case infer the `readonly []` default rather
than the constraint — typically by giving the generic parameters
defaults that actually apply on omission (e.g. inferring from the
spec object type with `extends undefined ? readonly [] : ...`, or
splitting the intersection so the index-signature branch only engages
when a non-empty tuple is inferred). A compile-fail fixture in
`tests/negative/` asserting that undeclared `args` keys error when
`flagSets`/`mutex` are omitted would lock the guarantee.

## Affected files

- `typescript/src/factories.ts` (the command-spec generics and
  `HandlerArgs` derivation)
- `typescript/tests/negative/` (new fixture)

## Effort

Small-medium: the type-level fix is a few lines but generics-with-
defaults inference is fiddly; the fixture is trivial.
