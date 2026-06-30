# Write grant as separate handler parameter (enforcement Solution 10)

## Context

When designing the dry-run enforcement model, Solution 10 (write grant parameter) was the most principled but highest complexity. Solution 6+9 (Writable gate + auto tests) was chosen for initial implementation. Both were subsequently deferred when the investigation concluded that airtight enforcement requires OS sandboxing. This todo captures Solution 10 specifically.

## The design

Write capability is a separate parameter on the handler's Run method. The handler receives a ReadContext (always available) and a WriteGrant (framework-controlled). In dry-run mode, the WriteGrant's methods panic. The separation makes write capability a value that flows through the program, not a property hidden inside the context.

```go
type ReadContext interface {
    ReadFile(path string) ([]byte, error)
    Info(msg string)
    DryRun() bool
}

type WriteGrant struct { /* framework-controlled */ }
func (g WriteGrant) WriteFile(path string, data []byte, perm os.FileMode) error { ... }
func (g WriteGrant) Remove(path string) error { ... }
func (g WriteGrant) Run(name string, args ...string) (RunResult, error) { ... }

type MutatingCmd interface {
    Run(ctx ReadContext, w WriteGrant) int
}
```

## Why deferred (twice)

First deferred in favor of Solution 6+9 (simpler, one handler parameter). Then the entire dry-run enforcement effort was deferred because airtight enforcement requires OS sandboxing.

## Advantages over Writable gate (Solution 6)

- Write capability is visible in the handler signature (two params vs one)
- Code review can audit write usage by following the grant parameter
- Read-only commands have a fundamentally different signature (no WriteGrant)
- More natural for helper function APIs: pass ctx for reads, grant for writes

## Disadvantages

- Two handler parameters increases cognitive load
- Helper functions must accept both ctx and grant
- Less Pythonic (Python doesn't naturally use capability tokens)

## Prerequisites

- Dry-run enforcement effort resumed (see dry-run-airtight-enforcement.md in .defer/)
- Unified Context architecture shipped
- Decision on whether airtight subprocess enforcement is a prerequisite
