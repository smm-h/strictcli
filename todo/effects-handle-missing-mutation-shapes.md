# Effects handle: mutation shapes the closed method set cannot express

## Context

The effects handle's closed method set is Run, Spawn, Write, Mkdir, Remove,
Rename, Chmod, HTTP. Consumer audits keep finding the same small set of
real-world mutation shapes that none of the eight can express, forcing
those operations off-handle -- each one a place where `--dry-run` honesty
and the effects-bypass discipline stop applying, held together only by
comments and per-command `dry_run_supported=false` declarations.

## The missing shapes

1. **Append-only file write.** `Write` is whole-content truncating
   (os.WriteFile). Journals and audit logs need open-append-write under an
   exclusive advisory lock (flock) -- truncation is precisely the failure
   the pattern exists to prevent. Shape: an append method (or a Write
   option) with optional flock semantics, whose dry-run record renders as
   "append N bytes to <path>".
2. **Exclusive create.** Lock files need O_CREAT|O_EXCL: atomically create
   iff absent, error if present. `Write` silently truncates an existing
   file -- the exact wrong behavior for a lock. Shape: a create-exclusive
   method (or Write option) whose failure-on-exists is part of the
   contract, not an error path.
3. **Subprocess stdin.** Neither Run nor Spawn can feed stdin to a child.
   Hook protocols (git's pre-push stdin contract and anything shaped like
   it) require handing the child a byte payload on stdin.
4. **Subprocess timeout with escalation.** Run/Spawn have no deadline. An
   operator-supplied script needs: deadline, SIGTERM, grace period,
   SIGKILL, kill the process GROUP (not just the direct child --
   grandchildren surviving a timeout is a real observed failure mode), and
   a distinguishable timed-out result.
5. **Streaming output access.** Run's stream option pipes the child's
   output to the parent's stdout/stderr and discards it from the result;
   Spawn hard-wires the same. There is no way to both stream and capture,
   and no incremental reader for long-running producers.

Shapes 3-5 typically occur together (running an operator-supplied hook
script: stdin payload + timeout/kill-tree + streamed-and-captured output),
so they may be one design ("hook execution") rather than three options.

## Why this cannot stay consumer-side

A consumer cannot wrap these shapes onto the handle from outside: the
handle's value is that dry-run recording, grants, and the bypass check see
every mutation, and an off-handle exec or file write is invisible to all
three by construction. Every consumer with a journal, a lock file, or an
operator-hook protocol currently carries the same off-handle exceptions
with the same apologetic comments.

## Decisions inside the design

- Methods vs options: new handle methods (AppendWrite, CreateExclusive,
  RunHook) vs options on Write/Run. Options keep the set nominally
  "eight"; methods keep each accepted-option table small and honest.
- Dry-run rendering for each: an append records size + target; an
  exclusive create records target + the on-exists contract; a hook run
  records argv + stdin size + timeout policy.
- Whether flock semantics belong in the framework or stay consumer-side
  with only the open-append-write minted (the lock is advisory
  coordination, not a mutation per se; but splitting them re-opens a
  bypass seam).
- Grant kinds: file_write covers 1-2; proc_mutate/proc_spawn cover 3-5,
  or a distinct hook grant.

## Affected areas

- effects.go method set + per-method accepted options, all three language
  implementations in lockstep
- Dry-run would-do rendering and the recorded-effect schema
- Grants and the effects-bypass check
- Docs: the effects-contract section

## Effort estimate

Medium: the shapes are small individually; the cost is the three-language
lockstep, the dry-run record design, and the hook-execution composite
(3-5) which deserves one coherent design rather than three bolted options.
