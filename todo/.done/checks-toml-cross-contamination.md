# checks.toml cross-contamination: CWD-based discovery is not app-scoped

## Problem

`.strictcli/checks.toml` is discovered by CWD, not by app name. When any strictcli-based tool (safegit, selfdoc, rlsbl) runs from a directory that has a `.strictcli/checks.toml` belonging to a different app, it discovers those checks, fails validation, and exits with:

```
error: checks declared in .strictcli/checks.toml but not registered: <check names>
```

This affects every project that uses the check system. Discovered in the wakethemup project where `wake` declares 6 checks — running `safegit commit` from that directory fails.

## Root cause

Three design decisions combine to create the bug:

1. **CWD-based discovery with no app scoping** (`strictcli.go:563-575`): `NewApp()` looks for `<CWD>/.strictcli/checks.toml` regardless of which app is running. There is no app-name filtering.

2. **Unconditional validation at Run() time** (`strictcli.go:807-811`): `validateCheckRegistrations()` runs before argument parsing, on every invocation — not just when the `check` command is used. Even `safegit commit` triggers it.

3. **Hard error on unregistered checks** (`strictcli.go:612-627`): If any check in the discovered file lacks a registered implementation, the app exits immediately.

## Affected code

- `strictcli.go:563-575` — CWD-based discovery in `NewApp()`
- `strictcli.go:612-627` — `validateCheckRegistrations()`
- `strictcli.go:807-811` — unconditional call in `Run()`
- `check.go:65-69` — parser rejects unknown top-level keys (only allows `"checks"`)

## Solutions

### A. App field in checks.toml (recommended)

Add a required top-level `app = "wake"` field to checks.toml. During discovery, after parsing, compare against `a.Name`. If mismatch, skip the file. Minimally invasive — existing files just need one line added.

Requires relaxing the top-level key validation in `check.go:65-69` to allow `"app"` alongside `"checks"`.

### B. Scope path to app name

Change discovery from `.strictcli/checks.toml` to `.strictcli/<appname>/checks.toml`. Cleanest structurally but breaking change for all existing check files.

### C. Don't discover unless app opts in

Add a `WithChecks()` app option. Only probe CWD when the app explicitly enables the check system. Apps that don't use checks (safegit, rlsbl, selfdoc) never discover foreign files. Can be combined with A or B.

### D. Defer validation to check command

Move `validateCheckRegistrations()` from `Run()` into the check command handler. Fixes the symptom for non-check invocations but doesn't fix the discovery mismatch — `NewApp()` still registers a foreign `check` command, and `RegisterCheck()` panics if the check name isn't in the foreign file.

## Recommendation

A + C together: apps that don't opt in never probe CWD (eliminates the problem for safegit/selfdoc/rlsbl), and apps that do opt in validate the `app` field (eliminates cross-app contamination in shared directories).

## Effort

Small — the discovery code, parser, and validation are all in well-isolated functions. Main work is deciding the approach and updating existing checks.toml files.
