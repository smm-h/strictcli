# Connection-env kind: a third infra-env primitive for connection URLs

## Context

strictcli has two env primitives today: `WithInfraRoot` (filesystem base
directories — eagerly resolved, defaulted, hermetic-IMMUNE) and
`WithHandshakeEnv` (cross-tool signals — lazily read, no default,
hermetic-IMMUNE). Per-flag `Env(...)` binding exists as a third channel and
is the only hermetic-SUPPRESSED one, but it lives on individual flags only.

A consumer project needs to declare a database/service connection URL env
var as first-class app-level configuration. None of the existing primitives
fits: a connection URL is behavioral ("reach outside the process"), so it
belongs in the hermetic-suppressed category — which no app-level primitive
provides. Two secondary gaps compound this:

- The check framework cannot deliver env values to check functions at all:
  `CheckContext` exposes only `ProjectRoot()`, and the auto-generated check
  command builds a fully-populated `*Context` and then discards it,
  invoking the zero-arg `SetCheckContext` factory instead.
- Multiple flags across commands bind the same conceptual env var
  individually (or forget to), with nothing enforcing consistency.

## Problem

1. No app-level env kind with hermetic-suppressed semantics exists —
   connection URLs end up in raw `os.Getenv` (invisible to help/schema,
   hermetic-blind) or per-flag `Env()` (inconsistent across commands,
   invisible to checks).
2. Checks cannot read any declared env value through the framework.
3. Nothing prevents a DB-URL-class flag from being registered unbound to
   the declared env var — consistency rests on review.

## Solution

Add a third env primitive — the CONNECTION ENV kind:

- Declared once at App level (name + help), surfaced in `--help` and the
  schema dump alongside the existing infra vars.
- Hermetic-SUPPRESSED: under `--hermetic` the value resolves as absent, so
  DB-dependent behavior (including checks) skips visibly instead of
  connecting.
- Lazily read, NO implicit default (missing means absent, never a
  fallback value).
- Flags bind to the declared connection env by reference (one declaration,
  many flags), with provenance reported through the existing
  `Context.Source()` (cli vs env).
- REGISTRATION-TIME hard error for URL-class flags not bound to a declared
  connection env (mechanical enforcement, not review hope — consistent
  with the house rule of hard constraints over soft guidance).
- Check-side access: widen the check-context path so check functions can
  read declared env values — reconcile the two context construction paths
  (the check command already holds a fully-built `*Context`; stop
  discarding it, or expose an `EnvValue`-style accessor on the check
  context backed by it).

## Affected

Env-primitive registration (App options), parse/hermetic handling, flag
binding, `CheckContext`/check-command plumbing, `--help`/schema dump
rendering, `Context.Source()` provenance, docs, tests (declaration, lazy
read, hermetic suppression, check-side access, registration-time
unbound-flag error, precedence cli > env).

## Effort

Medium. The mechanics are localized (env registry + one new kind + check
context widening); the tests enumerate the semantics above.
