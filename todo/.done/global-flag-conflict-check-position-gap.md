# Global-flag config-conflict checking only covers the pre-command position

## Context

Conflict mode (app-level and per-flag) errors when a value is set both in the config file
and on the CLI (or env) with a divergent value. For GLOBAL flags, the conflict check runs
inside the global-flag extraction pass — which only sees global flags placed BEFORE the
command token.

## Problem

Global flags are accepted in both positions, but only one is guarded:

- `tool --some-global X cmd ...` → conflict-checked (error mode fires on divergence).
- `tool cmd --some-global X ...` → resolved by the command parser and NOT conflict-checked
  against config; silent cli-wins even when the flag declares per-flag error mode.

The post-command position is the natural way users type it, so a consumer adopting
per-flag error mode on a global flag gets protection only for the less common spelling.
Env-vs-config divergence is detected regardless of position (env resolution is
position-independent), so the gap is CLI-position-specific.

Discovered empirically by a consumer adopting per-flag ConflictMode on global flags: its
divergence tests only fired in the pre-command position.

## Expected

Position should not matter: a global flag set anywhere in argv with a config-divergent
value must trigger the conflict check under error mode.

## Fix direction

The command-parse path that resolves post-command global flags needs the same
effective-mode + coerce + divergence check the global extraction pass has (both languages;
conformance cases for both positions; error-parity).

## Effort

Small-medium: the check logic exists and is shared; the work is invoking it on the
post-command global resolution path in both implementations + conformance coverage.
