# Global flags + passthrough: extraction disagreement

## Problem

Python and Go disagree on whether global flags are extracted from argv tokens that appear after a passthrough command name.

Example: app with global flag `--verbose` and passthrough command `raw`.

- `["raw", "--verbose"]`:
  - Python: `verbose=false`, passthrough receives `["--verbose"]` (global flag not extracted after command)
  - Go: `verbose=true`, passthrough receives `[]` (global flag extracted from anywhere in argv)

## Root cause

Different global flag extraction architectures:

- Python's `_parse_global_flags`: scans left-to-right, stops at the first non-global-flag token (the command name). Post-command global flags are recognized inside `_parse_command` (which adds globals to its lookup tables), but `_parse_command` is skipped for passthrough commands.
- Go's `extractGlobalFlags`: scans the entire argv, extracts global flags from any position. Non-flag tokens (command name, positional args) are collected into `remaining`. Go's `parseCommand` receives a `globalFlags` parameter but never uses it.

## Impact

Found by differential fuzzing (`conformance/fuzz.py`). The passthrough handler receives different args depending on the implementation. Affects any user who sets global flags after a passthrough command name.

## Options

1. **Fix Go to match Python (stop at first non-flag token).** Simpler extraction, but breaks the ability to set global flags after the command name for non-passthrough commands. Go currently relies on full-argv extraction for this.
2. **Fix Go to stop extracting global flags after identifying a passthrough command.** Requires two-pass: first identify the command, then decide extraction strategy. More complex but preserves both behaviors.
3. **Fix Python to match Go (full-argv extraction).** Change `_parse_global_flags` to scan all tokens. Would need to remove global flag recognition from `_parse_command` to avoid double-parsing.
4. **Fix Go's `parseCommand` to actually use the `globalFlags` parameter** (currently unused), then change `extractGlobalFlags` to stop at first non-flag token (matching Python). This makes both implementations use the same architecture: pre-command globals + post-command globals via command parser.

Option 4 is probably the most correct.

## Affected files

- `python/strictcli/__init__.py` (`_parse_global_flags`, `_parse_command`)
- `go/strictcli/strictcli.go` (`extractGlobalFlags`)
- `go/strictcli/parse.go` (`parseCommand` — unused `globalFlags` param)

## Effort

Medium. Requires careful testing of all global flag interaction patterns.
