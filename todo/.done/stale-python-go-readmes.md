# Python and Go READMEs are severely stale

## Problem

The root-level README.md and CLAUDE.md are up to date, but the per-implementation READMEs (`python/README.md` and `go/README.md`) have not been updated since early in the project and are actively misleading.

## Python README.md

- Line 5 claims "Types are `str` and `bool` only" — wrong, the framework now supports `str`, `bool`, `int`, and `float`
- Line 469 explicitly says "Only str and bool. No int, float, or list types. Parse them yourself in the handler" — directly contradicted by the implementation
- Line 69 says "Create groups for two-level nesting" — wrong, recursive nesting to arbitrary depth is now supported
- Missing entirely: float type, int type, config file support, --dump-schema, auto-version, help-anywhere, kwargs handler skip, check system, recursive nesting (beyond 2 levels), implies/dependencies

## Go README.md

- Line 5 claims "Types are `str`, `bool`, and `int` only" — missing `float`
- Missing: float type, config file support, --dump-schema, help-anywhere, check system, recursive nesting

## What's needed

Both per-implementation READMEs need a comprehensive update covering all features through 0.8.3. The root README already documents all features — the per-implementation READMEs should be consistent with it while focusing on language-specific API details and examples.

The Python README is the more urgent case since it contains directly contradictory statements.
