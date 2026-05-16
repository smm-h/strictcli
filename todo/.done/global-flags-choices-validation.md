# Global flags: choices validation not enforced

## Problem

Both Python and Go implementations do not validate choices for global flags. A global flag with `choices: ["a", "b"]` silently accepts any value (e.g., `--flag c`).

## Root cause

Global flag parsing (`_parse_global_flags` in Python, `extractGlobalFlags` in Go) does not run the choices validation step. Choices validation only happens in command-level parsing (`_parse_command` / `parseCommand`).

## Impact

Found during Phase 6 composition test writing. Users relying on choices for global flags get no validation.

## Fix

Add choices validation to the global flag parsing path in both implementations, after all global flag values are resolved (CLI + env + defaults).

## Affected files

- `python/strictcli/__init__.py` (`_parse_global_flags`)
- `go/strictcli/strictcli.go` (`extractGlobalFlags`)

## Effort

Low. Copy the choices validation loop from command-level parsing to global-level parsing.
