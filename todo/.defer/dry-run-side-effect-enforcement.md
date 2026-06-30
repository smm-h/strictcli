# Enforce that --dry-run commands cannot have side effects

## Problem

`--dry-run` is supposed to mean "preview without writing any changes to disk." But there's no mechanism to enforce this. A command can accept `--dry-run`, check it in some code paths, and still write files, mutate state, or call external services in other code paths. The flag is a convention, not a constraint.

Real-world example: safegit's `scrub run --dry-run` wrote real git objects to the object store, recorded scrub policies to a JSONL file, and in one version even rewrote all refs — all while `--dry-run` was set. The flag was checked in some places and missed in others. The result was a "dry-run" that executed a full destructive history rewrite.

## The ask

Find a way to make `--dry-run` a hard constraint rather than a soft convention. When `--dry-run` is set, any attempt to produce side effects should error, not silently succeed. The framework should enforce this, not individual commands.

Possible directions (non-exhaustive, figure out what works):
- Intercept filesystem writes, network calls, or subprocess spawning when dry-run is active
- Provide a dry-run context that wraps I/O operations and errors on write attempts
- Static analysis or code generation that verifies dry-run paths don't call write functions
- A testing harness that runs commands with --dry-run in a read-only sandbox and fails if anything was written
- Type-system-level enforcement (e.g., dry-run handlers receive a read-only context type that doesn't have write methods)

The hardest part is that commands often need to compute what WOULD change (which requires reading state) without actually changing it. The enforcement must distinguish reads from writes.

## Why this matters

AI agents treat `--dry-run` as a safety guarantee. If they believe dry-run is safe, they use it freely to preview operations. When dry-run lies, the agent causes damage while thinking it's being careful. The guarantee must be structural, not behavioral.
