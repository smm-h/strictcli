# First-class "infrastructure env var" primitive (WithInfraEnv)

## Context

`--hermetic` suppresses config-file loading and strictcli-managed env vars. But consumer
tools commonly have a *base-directory* env var (a `<TOOL>_HOME`-style override that decides
where the tool's data lives) read via raw `os.Getenv`, outside strictcli's env machinery.
Result: hermetic runs suppress app *configuration* while the base-dir var still applies —
an asymmetry each tool currently handles ad hoc (raw Getenv + prose documentation).

Routing such a var through ordinary strictcli env binding is a trap: hermetic would then
suppress it, and test harnesses that rely on the var for isolation would silently point at
the user's real data directory — a data-integrity hazard, not a hygiene win.

## Proposal

A first-class primitive — e.g. `WithInfraEnv("TOOL_HOME", help=...)` (Go) /
`infra_env=` (Python) — that the framework understands as *location, not behavior*:

- Always read, even under `--hermetic` (the contract explicitly documents that hermetic
  suppresses config and behavioral env, never infrastructure/location).
- Reported in `--dump-schema`, `--help`, and `config show` under a distinct
  "Infrastructure" heading (with the not-suppressed-by-hermetic annotation).
- Defined precedence and a single resolution path (no more raw `os.Getenv` in consumers).
- `$HOME`/XDG conceptually belong to the same category; the primitive names the boundary
  that today exists only in per-tool prose.

## Why

- Eliminates the per-tool asymmetry-documentation class; the distinction becomes a shared,
  enforced invariant instead of a convention.
- Makes `--hermetic`'s contract precise and self-documenting.
- Consumers get uniform introspection (schema/help/config-show) for base-dir overrides.

## Scope notes

- Both languages + conformance cases (hermetic run with infra env set → var still applies;
  schema/help surfaces).
- Migration: consumers move raw Getenv reads onto the primitive one by one; no behavior
  change (the var was already un-suppressed — the primitive just declares it).

## Effort

Medium: new registration surface in both implementations, hermetic-path plumbing,
schema/help/config-show rendering, conformance coverage.
