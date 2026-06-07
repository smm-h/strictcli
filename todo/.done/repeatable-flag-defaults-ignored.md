# Bug: Repeatable flag defaults are not applied in args map

## Problem

In `go/strictcli/strictcli.go`, the "Apply defaults for global flags not set" block (around line 1406) always sets repeatable flags to `[]interface{}{}` regardless of their `Default` value:

```go
if f.Repeatable {
    globalValues[f.Name] = []interface{}{}  // ignores f.Default
}
```

This means `Default([]string{"a", "b"})` on a repeatable flag is silently ignored in the args map. The default IS stored in the flag metadata (shown by `config show`), but handlers always receive an empty slice when no CLI args, env var, or config file value is provided.

The same pattern exists in the command-level flag resolution (search for similar blocks).

## Expected behavior

```go
if f.Repeatable {
    if f.hasDefault && f.Default != nil {
        globalValues[f.Name] = f.Default
    } else {
        globalValues[f.Name] = []interface{}{}
    }
}
```

## Impact

saferm wants to register `exclude_env_patterns` as a repeatable string flag with 5 default patterns. Without this fix, the defaults must be applied manually in saferm's handler code.

## Discovered by

saferm project, verifying strictcli v0.12.0 array config support (June 2026).
