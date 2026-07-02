# kwargs hyphen-to-underscore normalization is a silent bug factory

## Problem

strictcli normalizes flag names from hyphens to underscores when building the kwargs map (`flagParamName` in strictcli.go replaces `-` with `_`). But consumers access kwargs with string literals that must manually match the normalized name. Two bug classes result:

1. **Key-name mismatch**: Consumer writes `kwargs["older-than"]` but the key is `"older_than"`. The comma-ok pattern returns zero value silently; a bare assertion panics. Both were found in pgdesign — the `--older-than` flag on `testdb gc` was silently broken (always errored "required"), and `--split-by-file` panicked when not passed.

2. **Bare type assertions**: `kwargs["key"].(bool)` panics if the key is nil (e.g., optional flag not passed). 42 bare assertions exist in pgdesign alone. They're safe today because strictcli guarantees boolean flags have defaults, but removing a flag without updating the handler would cause a runtime panic with no compile-time warning.

## Root cause

The kwargs API is `map[string]interface{}` — stringly typed with no compile-time connection between flag registration and access. The normalization happens at storage time (in strictcli) but consumers must replicate it mentally at access time.

## Proposed solutions

### Short-term: MustGet helper with normalization

Add a typed accessor that normalizes at the access site:

```go
func MustGetBool(kwargs map[string]interface{}, name string) bool
func MustGetString(kwargs map[string]interface{}, name string) string
func GetString(kwargs map[string]interface{}, name string) (string, bool)
```

These normalize the name internally (replace `-` with `_`) before lookup. `MustGet` panics with a clear message including the flag name. `Get` returns comma-ok. Consumers write `MustGetBool(kwargs, "dry-run")` using the flag's registration name, and normalization is handled internally.

### Long-term: Typed handler signatures

Generate or require typed structs per command:

```go
type BuildFlags struct {
    DryRun   bool   `flag:"dry-run"`
    NoCommit bool   `flag:"no-commit"`
    Quiet    bool   `flag:"quiet"`
}
```

strictcli populates the struct via reflection from the registered flags. The handler signature becomes `func(flags BuildFlags) int`. No map access, no string keys, no normalization concern. Mismatches between struct fields and registered flags are caught at registration time.

## Impact

Every strictcli consumer with hyphenated flags is vulnerable. The bug is silent (comma-ok returns zero value, bare assertion panics at runtime) and impossible to detect without running the specific code path that accesses the mismatched key.
