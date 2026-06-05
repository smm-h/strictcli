# Bug: WithConfigFormat("toml") accepted but loadConfig always parses JSON

## Problem

`WithConfigFormat("toml")` is accepted as a valid option and changes the config file extension to `.toml` in the default path computation. However, `loadConfig()` in `go/strictcli/config.go` (around line 36-49) always calls `json.Unmarshal` regardless of the `format` field. The `format` parameter only affects the filename, not the parsing.

This means:
- `WithConfigFormat("toml")` causes strictcli to look for `config.toml`
- When it finds and reads the file, it tries to parse TOML content as JSON
- Parsing fails silently or with a confusing JSON parse error

## Expected behavior

When `WithConfigFormat("toml")` is set, `loadConfig()` should use a TOML parser (e.g., `BurntSushi/toml` or `pelletier/go-toml`) to decode the config file. Similarly, `config set` should write TOML when the format is "toml".

## Impact

saferm wants to migrate from its hand-rolled TOML config (`~/.saferm/config.toml`) to strictcli's config system, but needs TOML support to maintain the same config format. Currently blocked on this bug.

## Discovered by

saferm project, investigating strictcli config adoption (June 2026).
