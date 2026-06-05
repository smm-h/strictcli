# Array/list config support for config files and config set

## Problem

`coerceConfigValue()` in `go/strictcli/config.go` only handles scalar types (bool, int, float, string). When a TOML config file contains an array value like:

```toml
exclude_env_patterns = ["(?i)token", "(?i)secret", "(?i)password"]
```

The TOML parser returns `[]interface{}`, which `coerceConfigValue` doesn't handle. It falls through to the error case. Similarly, `config set` has no way to write array values.

This blocks consumers that have list-valued config keys from migrating to strictcli's config system.

## Expected behavior

- TOML arrays should be readable from config files and applied to repeatable flags
- `config set` should accept array values (e.g., `config set patterns "a,b,c"` or `config set patterns --add "a"`)
- `config show` should display array values

## Impact

saferm wants to migrate from its hand-rolled TOML config to strictcli's config system, but has `exclude_env_patterns` (a string list) that can't be represented as a strictcli flag/config key. The migration is blocked on this.

## Discovered by

saferm project, investigating strictcli config adoption (June 2026).
