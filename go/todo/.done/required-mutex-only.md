# Remove optional mutex groups

## Problem

Mutex groups currently have a `Required` boolean: `Required: true` means exactly one flag must be chosen, `Required: false` means at most one (but none is fine).

Optional mutex groups encourage implicit defaults -- when no flag is passed, the handler silently picks a behavior. This is the same class of problem as implicit config defaults: the user should be explicit about what they want.

## Proposed change

Remove the `Required` field from `MutexGroup`. All mutex groups are always required (exactly one flag must be provided). If a command has a mode that means "do nothing special," it should be an explicit flag in the group.

Example -- instead of an optional mutex where none = health check:

```go
WithMutex(MutexGroup{
    Flags: []Flag{fixFlag, uninstallFlag},
    Required: false, // none = health check mode
})
```

Make it a required mutex with an explicit flag for every mode:

```go
WithMutex(MutexGroup{
    Flags: []Flag{diagnoseFlag, fixFlag, uninstallFlag},
})
```

## Migration

- Remove the `Required` field from `MutexGroup` (or ignore it / always treat as true).
- Update validation to always require exactly one flag from each mutex group.
- Update help generation to always show mutex flags as required.
- Update any tests that use optional mutex groups.

## Effort

Small. The change is mostly deletion (remove the `Required` branch in validation). The conformance test suite may need updates.
