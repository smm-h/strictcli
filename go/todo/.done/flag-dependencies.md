# Cross-flag dependency support

## Problem

There is no way to declare that one flag requires another. For example, safegit's `rewrite-author` command has `--old-name` and `--new-name` flags that must always be used together -- passing one without the other is invalid. Same for `--old-email` / `--new-email`.

Currently the only way to enforce this is post-parse validation in the handler, which duplicates the kind of constraint logic that strictcli already handles for mutex groups, required flags, and choices.

## Proposed feature

A mechanism to declare that flag A requires flag B (and optionally vice versa). When A is provided but B is missing, strictcli reports the error before the handler is called.

Possible API:

```go
app.Command("rewrite-author", "...", handler,
    WithFlags(
        StringFlag("old-name", "...", Default(nil)),
        StringFlag("new-name", "...", Default(nil)),
        StringFlag("old-email", "...", Default(nil)),
        StringFlag("new-email", "...", Default(nil)),
    ),
    WithDependencies(
        Requires("old-name", "new-name"),
        Requires("new-name", "old-name"),
        Requires("old-email", "new-email"),
        Requires("new-email", "old-email"),
    ),
)
```

Or a bidirectional shorthand:

```go
WithDependencies(
    CoRequired("old-name", "new-name"),
    CoRequired("old-email", "new-email"),
)
```

## Constraints

- Should compose with mutex groups (a dependency target can be in a mutex group).
- Validation happens at parse time alongside mutex checks, before the handler is called.
- Error messages should be clear: `flag '--old-name' requires '--new-name'`.
- Should work with both required and optional flags.

## Motivation

safegit's `rewrite-author` migration to structured parsing is blocked on this feature.

## Effort

Small-medium. The dependency graph is simple (pairs, not chains). Validation is a post-parse check similar to mutex enforcement.
