# The dry-mode would-do log and a command's `--json` output share stdout

Filed 2026-08-05, found while migrating a consumer onto the redesigned confirm
protocol. This is a live incompatibility between two shipped features, not a
future concern: it broke a real orchestration path.

## What happens

A command that emits machine-readable JSON on stdout (its own `--json` flag)
and is run under `--dry-run` produces:

```
{
  "version": 1,
  "dry_run": true,
  ...
}
DRY RUN — no changes were made. Would do:
  1. run: ...
  2. write: ...
```

The framework's would-do log is appended to the SAME stream, after the
command's JSON document. A caller doing the obvious thing --
`json.loads(subprocess_stdout)` -- gets:

```
json.decoder.JSONDecodeError: Extra data: line 15 column 1
```

## Why it is not obviously a consumer bug

The contract makes both behaviours mandatory and gives the caller no lever:

- §3.2 pins the log's format and §3.5 requires it on every exit path.
- §3.4 says `--quiet` does nothing to it: "the would-do log is dry mode's
  primary output and is never suppressed".
- A command's own `--json` is an ordinary consumer flag the framework knows
  nothing about, so it cannot suppress the log either.

So any tool that (a) offers `--json` and (b) is driven as a subprocess under
`--dry-run` produces a stream that is neither valid JSON nor plain text. Every
such caller must independently reinvent the same tolerant parse. One consumer
now reads exactly one JSON document off the stream with `raw_decode` and
hard-errors on any trailing content that is not the log's header -- correct,
but it is a workaround for an ambiguity the framework created, and it hardcodes
the log's header string in a consumer.

## Directions worth considering

1. **Send the would-do log to stderr.** It is human output. Stderr is where the
   confirm prompt (§8.2), the truncation error (§3.3) and every framework
   diagnostic already go, and it makes the machine/human split total. Cost: any
   consumer or test that greps the log on stdout moves; §3.3 explicitly splits
   the log (stdout) from its error (stderr) today, so that pairing changes too.
2. **Suppress the log when the app declares a JSON output mode.** Requires a
   new declaration so the framework knows the command owns stdout. More
   machinery, and it makes the log conditional, which §3.4 deliberately refused.
3. **Emit the log as a JSON document when the command's output is JSON**, so
   the stream stays parseable. Requires the same declaration as (2).
4. **Do nothing and pin the contract**: state in §3 that a command owning
   stdout must read one document and skip the log, and give consumers a stable
   way to recognize the boundary (the header is already verbatim-pinned, so
   this is mostly a documentation change plus a helper).

Option 1 is the smallest change with the clearest invariant: stdout is the
command's, stderr is the framework's. Option 4 is the cheapest but leaves every
consumer carrying the same parser.

## Affected

- the dry-mode log renderer in all three implementations
- §3.2 / §3.3 / §3.4 / §3.5 of the effects contract
- the conformance cases that assert the log lands on stdout

## Effort

Small if option 1 or 4; moderate if a new declaration is introduced. The
decision is the work, not the code.
