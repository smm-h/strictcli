# Effects Run gaps found in consumer adoption: stdin, settled-ness, tee, observe-under-dry-run, Completed constructability

Five related gaps in the effects handle's `Run`/`Completed` surface, all
found while a consumer CLI adopted the effects regime for its subprocess
execution. Each is independently small; together they force consumers into
port-based indirection and off-handle escape paths.

## 1. Run assigns no stdin to its children

`execRun` never sets `cmd.Stdin`. Consequences observed in a consumer:

- Any operator-facing subprocess run through the handle cannot read the
  terminal (its fd 0 is /dev/null in practice). Editors that open
  /dev/tty still work; anything reading stdin does not — interactive
  passthroughs are structurally broken through the handle.
- Plumbing that consumes stdin (e.g. `git apply --cached`, `git mktree`,
  `git hash-object --stdin`) cannot be minted at all and must stay
  off-handle, with the reason documented at every such site.

A `Stdin(io.Reader)`/`StdinInherit()` option pair (mutually exclusive)
would close both.

## 2. Completed exposes no settled-ness probe, and cannot be constructed by consumers

`Completed.settled` is unexported and all three accessors (`ExitCode`,
`Stdout`, `Stderr`) panic when unsettled. Two consequences:

- A caller that receives a `Completed` from a shared code path cannot ask
  "did anything actually run?" without out-of-band knowledge of the mode.
  `Effects.Recorded()` cannot serve as the probe because calling it claims
  the would-do render (suppressing the framework's own end-of-dispatch
  preview emission).
- A consumer cannot construct a settled `Completed` in its own tests, so
  any interface it defines around the handle needs a hand-rolled port type
  instead of the framework's own vocabulary.

A public `Settled() bool` (or `Executed() bool`) plus a test-constructor
(`strictclitest.Completed(...)` or an exported struct literal path) would
close both.

## 3. Run streams OR captures, never both (no tee)

With `Stream(true)` the output goes to the terminal and `Completed`'s
`Stdout()`/`Stderr()` are empty; without it, output is buffered and only
available after exit. A consumer that must CLASSIFY a child's stderr
(retry-vs-terminal decisions) is forced into capture mode, and its users
lose live progress for long-running children. A tee mode (stream AND
retain) is the missing shape.

## 4. The observe branch executes under dry-run, non-uniformly

In dry-run mode, an argv matching the proc-observe allowlist is EXECUTED
(and returns a settled `Completed`) — but only until a mutation has been
recorded, after which observes return an unsettled stale-brand carrier.
Two issues:

- The non-uniformity means the same observe call changes behavior based on
  invisible prior state within the dispatch.
- Nothing surfaces to the consumer that an observe executed during what
  the operator asked to be a dry run; combined with gap 2 there is no way
  to detect it either. A consumer keying dry-run behavior off its own
  parsed flag can be silently wrong the day an allowlist prefix overlaps a
  mutating argv family (guarded today only by consumer-side discipline
  tests).

At minimum, document the contract precisely; ideally make observe behavior
under dry-run uniform and probeable.

## 5. (Aggregating note) These interact

The consumer-side workarounds compound: no stdin forces off-handle sites;
no settled-ness probe plus no constructor forces a port type; no tee forces
buffered UX for classified subprocesses; the observe non-uniformity forces
premise-pinning source-scan tests. Closing 1-3 removes most of the
off-handle surface a disciplined consumer needs.

## Effort

Each item small-to-medium in isolation; the stdin and settled-ness items
are the highest-leverage.
