# Three mutation shapes the effects handle's closed method set cannot describe

Filed from Go consumer adoption of the effects regime (go-strictcli 0.28.2). The eight-method
set covered the great majority of real mutation sites cleanly. Three shapes did not fit, and
in each case the consumer had to move the mutation OFF the handle and guard it on
`ctx.DryRun()` instead -- which is exactly the "handler branches on mode" outcome the regime
exists to remove.

This is a design question, not a bug report: §2.2 pins the set as closed, and the honest answer
may well be "these stay outside the handle, and the contract should say so". What is missing
today is that the contract says nothing about them, so each consumer invents its own treatment.

## 1. Append-only writes

`write` is whole-content: it takes the bytes and replaces the file. A consumer whose audit
trail is an append-only JSONL log, written with `O_APPEND` precisely so that concurrent
processes can each add a line without coordination, cannot express an append as a `write`
without a read-modify-write that destroys the atomicity guarantee the log exists for.

The consumer's only options are (a) leave the append outside the handle, so the preview never
mentions it, or (b) mint a `write` that lies about both the content and the concurrency
semantics. Both consumers that hit this chose (a).

Possible answers: an `append` method (kind `FILE_WRITE`, log verb `append:`, detail
`<path> (+<n> bytes)`); or an explicit contract statement that append-only trails are outside
the regime, with the reasoning recorded so nobody re-litigates it per repo.

## 2. Subprocesses that need stdin

`run` takes `argv`, `cwd`, `env`, `check` and `stream`. It has no stdin. A consumer whose hook
protocol feeds each hook script a payload on stdin (the git pre-push format is the concrete
case) cannot mint the hook run at all, so under `--dry-run` it must skip running hooks entirely
and say so in prose.

Note that stdin is a *payload*, which is the same reason `body` is excluded from carrier
forwarding in §2.5.5 -- so the argument for leaving it out is real. But the effect is that a
whole class of subprocess invocation is unrepresentable rather than merely unforwardable.

Possible answers: a `stdin=` parameter on `run` and `spawn` accepting bytes only (never a
carrier, matching `body`), rendered in the log as `run: <argv> (<n> bytes on stdin)`; or an
explicit exclusion in §2.5.2 with the reasoning.

## 3. Streaming and verifying producers

Two shapes appeared in consumers, both compound:

- **Streaming archive creation**: walk a directory tree, tar it, compress it, write the result.
  Expressing it as `write(path, content)` means materializing the whole archive in memory
  first, which is not viable for a tree of arbitrary size.
- **Verified copy**: copy a file to a new location and confirm the destination hash matches
  before removing the source. This is the cross-device fallback under a `rename`, so a consumer
  that mints `rename` for the common case silently loses the fallback for the cross-device one.

Both consumers ended up with a plan/execute split: a read-only planning call, then a
dry-mode-only `recordArchival`-style function that mints the closest primitives to *describe*
the operation, with the real compound implementation called only in a live run. It works and it
is documented at each site, but it is the one place in each repo where the record and the act
are different calls, and the framework offers no vocabulary for it.

Possible answers: a documented "described effect" idiom (a way to mint a log line for a
compound operation whose execution the handler owns, so the split is a declared framework
concept rather than a per-consumer workaround); or an explicit contract statement that
compound operations are the handler's business and the plan/execute split is the sanctioned
shape.

## Why it matters

The regime's value is that the preview describes the run. Every mutation that leaves the
handle is a line missing from the preview, and every `if ctx.DryRun()` in a handler is a place
where the two modes can drift apart unnoticed. Three shapes is not many, but they are all in
tooling whose whole purpose is the mutation in question, so the missing lines are the
interesting ones.

## Effort

Contract statement only: an hour. `append` + `stdin`: half a day each across three
implementations plus conformance cases. The described-effect idiom is a design round, not an
implementation.
