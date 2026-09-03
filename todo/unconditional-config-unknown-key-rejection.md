# Make config-file unknown-key rejection unconditional (all implementations)

## Context

strictcli validates the keys of a user's config file against the known-key
set (flag param names, declared config fields, framework fields) and rejects
unknown keys with a hard error. But the rejection is CONDITIONAL: in the Go
implementation it runs only when the app declares at least one config field
(`len(a.configFields) > 0`, guarded in the invoke path alongside
`configEnabled` and the config-subcommand exception). The other
implementations carry the same conditionality, with the check fused into
the bound-config-field validation rather than a separate function — so the
structural location differs per implementation even though the behavior
matches.

## Problem

An app that declares only flags (no config fields) gets NO unknown-key
rejection at all: junk or typo'd keys in its users' config files pass
silently. That is a silent-tolerance hole of exactly the class the
framework's philosophy forbids (hard errors over silent acceptance; no
quiet degradation). It is unclear whether the conditionality was a
deliberate decision or an oversight — no comment or document explains it.

## Proposed work

1. Investigate intent: check history and any design notes for a reason the
   rejection is conditional. If a deliberate reason exists, record it where
   the condition lives and close this todo.
2. Absent a deliberate reason: make unknown-key rejection unconditional in
   ALL implementations in the same change, preserving cross-implementation
   behavior parity (the conditionality sits in structurally different
   places per implementation, so this is a per-implementation edit, not a
   mechanical port).
3. This is a behavior change for flag-only apps: their users' stray config
   keys start erroring. That is the point, but it belongs in the changelog
   as a breaking-type entry, and the parity test suites should pin the new
   behavior.

## Affected surface

- Go: the invoke-path guard around `validateUnknownConfigKeys` and the
  validator itself.
- The other implementations: the equivalent condition inside their
  bound-config-field validation.
- Parity test suites in each implementation.

## Effort

Small once the intent question is answered: the condition removal is a few
lines per implementation; the work is the parity-preserving coordination
and the behavior-change communication.
