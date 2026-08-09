# Declarative global flag contract on handler structs (Solution 10)

## Context

When designing how global flags reach struct handlers, Solution 10 (declarative contract) was the most strictcli-philosophy-aligned but highest friction. Solution 6 (globals on Context via generics) was chosen for initial implementation. This todo captures Solution 10 for later.

## The design

The app defines a globals struct type with FrameworkFlags embedded. Every handler struct MUST embed the globals type. The framework validates at registration time that every handler includes the embedding. Adding a new global flag breaks every handler struct (by design -- forces explicit threading).

```go
type FrameworkFlags struct {
    DryRun bool `cli:"dry-run"`
}

type SafegitGlobals struct {
    strictcli.FrameworkFlags
    Quiet   bool   `cli:"quiet,global"`
    Verbose bool   `cli:"verbose,global"`
    Yes     bool   `cli:"yes,global"`
}

type CommitHandler struct {
    SafegitGlobals                       // mandatory embedding
    Message []string `cli:"m,required"`
}

func (h *CommitHandler) Run(ctx strictcli.Context) int {
    if h.DryRun { ... }
    if h.Quiet { ... }
}
```

## Why deferred

- Solution 6 is simpler and non-breaking when adding globals
- Solution 10's mandatory embedding creates coupling that may be too rigid
- Need real-world experience with Solution 6 before deciding if the stricter model is worth it

## Advantages over Solution 6

- Direct field access (h.Quiet) vs method call (Globals[T](ctx).Quiet)
- No Go generics requirement
- Zero runtime overhead (no type assertion per Globals() call)
- Closer to safegit's existing globalsToFlags() pattern
- Forces every handler to acknowledge every global flag
- Refactoring a flag from command to global doesn't change handler access patterns

## Prerequisites

- Solution 6 shipped and in use across consumers
- Feedback on whether the indirection of Globals[T](ctx) is painful in practice
