# Globals redesign (design A): three contract addenda

Filed 2026-07-24 by the consumer-side design round, as locked requirements to fold
into the design recorded in `todo/globals-redesign-design-a.md`. These are
constraints the reference implementation must satisfy; none reopen decided items.

## 1. Per-command dry-run opt-out: `dry_run_supported = false`

A mutating command must be able to declare that it does not support `--dry-run`,
causing the framework to hard-reject the flag with a clear error (naming the
command and the reason) instead of running a fake or partial rehearsal.

Motivation: chained mutating commands whose later steps consume the products of
earlier remote effects (push then clone-the-pushed-repo then operate-inside-it)
cannot honestly rehearse — recording-instead-of-performing produces nonsense
mid-chain. The honest behaviors are either a genuine plan mode implemented by the
command itself or loud rejection; silent partial rehearsal is forbidden. The
opt-out must be rare and justified per command — it is not an escape hatch to be
sprinkled; consider requiring a `dry_run_unsupported_reason` string so every use
is self-documenting.

## 2. Reserved-flag collision is a registration-time hard error

When the framework-reserved flags (`--dry-run`/`--yes`/`--quiet`) are enabled and
the app itself declares a flag with one of those names, registration fails with a
hard error. No shadowing, no precedence rules, no warning-and-continue.

## 3. Effects context must be inheritable across subprocess boundaries

Handlers spawn nested CLI invocations of the same or sibling tools (a command
that clones a repo and runs another of the tool's own subcommands inside the
clone is a real, current pattern). The dry/effects context must propagate to
spawned child processes (environment-carried), so that:

- dry mode reaches the child instead of the child mutating for real, and
- the planned lint ("no direct subprocess/socket use in handlers") does not
  create a false sense of safety: it can catch leaf calls while a recursive
  invocation escapes the effects layer entirely.

The propagation mechanism should be part of the contract (documented env
variable(s) set by the framework when effects handles are active), not an
implementation detail, since consumers must be able to test it.
