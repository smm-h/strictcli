# TagContract does not check global flags

## Problem

`checkCommandTagContract` (strictcli.go:1205) only checks `cmd.flags` when validating tag contracts. It does not check global flags, flag set flags, or mutex group flags. If a tag contract requires a flag named "json" and "json" is registered as a global flag, the contract fails even though the flag IS available to every command at parse time.

This makes TagContract unusable for the most common pattern: global flags like `--json`, `--verbose`, `--dry-run` that many commands share.

## Reproduction

Register a global `--json` flag, tag a command with `WithTags("json")`, add `TagContract("json", "json")`. The contract fails at `Run()`/`Test()` time because `checkCommandTagContract` only iterates `cmd.flags` (line 1215), not `app.globalFlags`.

A command cannot work around this by adding a local `--json` flag -- strictcli panics on name collision between global and command-level flags (line 2199-2201).

## Fix

Thread `a.globalFlags` into `checkCommandTagContract` and `checkGroupTagContracts`. Expand the flag search loop to also check global flags (and flag sets + mutex flags for completeness, matching what `buildAndValidateCommand` already does with `allFlags`). ~10 lines across 3 functions.

## Test

Add `TestTagContractSatisfiedByGlobalFlag`: register a global flag, tag a command with a contract referencing it, verify no validation error.
