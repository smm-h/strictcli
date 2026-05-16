# Global flags: repeatable not supported

## Problem

Neither Python nor Go correctly handles repeatable global flags. Python iterates over string characters instead of treating the value as a list. Go panics on a type assertion.

## Root cause

Global flag parsing was implemented for scalar values only. The repeatable flag logic (accumulating values into a list) exists in command-level parsing but was never ported to global flag parsing.

## Impact

Found during Phase 6 composition test writing. Users cannot use repeatable global flags.

## Fix

Port the repeatable flag accumulation logic from command-level parsing to global-level parsing in both implementations.

## Affected files

- `python/strictcli/__init__.py` (`_parse_global_flags`)
- `go/strictcli/strictcli.go` (`extractGlobalFlags`)

## Effort

Medium. The accumulation logic is non-trivial (initialize empty list, append on each occurrence, handle env vars as single-element list).
