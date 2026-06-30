# Airtight dry-run enforcement at the framework level

## Status

Deferred. The investigation concluded that airtight enforcement (guaranteeing zero side effects in dry-run mode regardless of handler implementation) is not feasible cross-platform without OS-level sandboxing.

## Investigation findings

### What the framework CAN enforce (filesystem)

The Context's Writable() gate (Solution 6) can prevent filesystem writes via Context methods. If a handler calls ctx.Writable() in dry-run mode, it panics. Auto-generated dry-run tests (Solution 9) can run every mutating handler in dry-run mode and verify no filesystem mutations occurred.

### What the framework CANNOT enforce (subprocesses)

The framework cannot distinguish read subprocesses (git status, git log) from write subprocesses (git push, npm publish). Three approaches were evaluated:

- **RunRead/RunWrite split**: handler must classify each subprocess call. Still relies on handler author getting it right. Does not solve the problem.
- **Subprocess allow-list**: command declares which subprocesses are read-safe. Enforceable but per-command maintenance burden. Fragile when tools change behavior.
- **OS sandboxing (bwrap, landlock, seccomp)**: airtight for filesystem but Linux-only. bwrap is a CLI tool (~30% overhead, acceptable), but tool-specific incompatibilities (git writes lock files even in its own dry-run). Landlock requires kernel 5.13+. seccomp requires BPF program generation. None work on macOS/Windows.

### The core problem

Subprocess execution is inherently opaque to the framework. A subprocess can read or write to any resource (files, network, databases) and the framework has no way to know which. The only airtight solution is OS-level sandboxing, which is platform-specific.

## Deferred work items

### Writable gate (Solution 6)

ctx.Writable() returns a write-capable context or panics in dry-run. Single audit point. Handlers must branch on DryRun() before calling Writable(). ~200 LOC per language.

### Auto dry-run tests (Solution 9)

Framework auto-generates a dry-run test for every command that declares needs_dry_run=true. The test runs the handler with a recording context and asserts zero write calls succeeded. ~150 LOC per language. Requires test input generation per command.

### Write grant parameter (Solution 10)

Separate WriteGrant parameter on handler's Run method. Write capability is a distinct resource. Most principled but highest handler complexity (two parameters). ~350 LOC per language. Filed separately.

### Capability tags

Auto-derive readonly/mutation/destructive tags from command declarations (needs_dry_run, Context usage). Feed into schema dump for AI agent tool filtering. Depends on the enforcement model being implemented first.

### Operation tracking

Context records intended operations for dry-run reporting ("would write state.json", "would run git push"). Auto-printed or available via ctx.PlannedOps(). Depends on the enforcement model.

## Why not partial enforcement?

Claiming "dry-run is enforced" when subprocesses can still produce side effects is worse than no enforcement. Agents trust the framework's guarantees. A partial guarantee that silently fails for subprocess-based writes creates false confidence. Better to defer entirely and implement honestly when a cross-platform solution exists, or when the scope is narrowed to specific enforcement layers with documented gaps.

## Prerequisites for revisiting

- Cross-platform subprocess sandboxing (or decision to be Linux-only for this feature)
- Unified Context architecture shipped (struct handlers, output methods, globals)
- Clear scope decision: filesystem-only enforcement acceptable, or subprocess coverage required?
