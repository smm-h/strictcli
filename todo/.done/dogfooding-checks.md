# Dogfooding: use the check system for strictcli's own pre-release checks

## Problem

strictcli's CI runs three conformance checkers (API surface, error parity, conformance suite) but they're only caught in CI, not locally. The v0.8.0 release shipped with all three failing, requiring three patch releases to fix. The check system we just built solves exactly this problem -- we should use it ourselves.

## What needs to happen

1. Create a small strictcli-based CLI tool in the repo (e.g., `tools/dev.py` or `dev/main.go`) that uses strictcli and registers the conformance checkers as checks.

2. Register checks in `.strictcli/checks.toml`:
   - `api-surface` -- runs `check_api_surface.py`, tagged `pre-release`
   - `error-parity` -- runs `check_error_parity.py`, tagged `pre-release`
   - `conformance-python` -- runs `run.py --target python`, tagged `pre-release`
   - `conformance-go` -- runs `run.py --target go`, tagged `pre-release`
   - `conformance-parity` -- runs `run.py --both`, tagged `pre-release`

3. Update pre-release hooks to call `dev check --tag pre-release` (or equivalent).

## Bootstrapping concern

strictcli is a library, not a CLI app. The dev tool would be a small internal app that uses strictcli to validate strictcli. This is circular but not problematic -- the dev tool depends on the installed version of strictcli, not the version being released.

## Effort

Small. The dev tool is ~50 lines. The checks are thin wrappers around subprocess calls to existing scripts. The TOML is ~30 lines.
