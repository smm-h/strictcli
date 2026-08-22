# Dry-run and schema surface gaps found during consumer adoption

Four independent items, all surfaced while a consumer CLI adopted the
effects regime and the machine-mode schema deeply. Related but distinct
from `todo/dict-flag-validatefn-silently-skipped.md` and
`todo/effects-run-gaps-stdin-settledness-tee-observe-dryrun.md` (filed
earlier from the same adoption effort). Each deserves at least a
considered no.

## 1. No per-invocation dry-run refusal

`dry_run_supported=false` is per-command and total. A consumer command
that WRAPS a foreign tool (forwarding operator-typed argv) can preview
most invocations honestly but must refuse specific argv shapes whose
outcome it cannot compute (e.g. a flag that changes the wrapped tool's
result in a way the preview machinery cannot represent). Today the
consumer hand-rolls the refusal inside its handler: parse `--dry-run`'s
presence, print a reason, exit — duplicating the framework's own refusal
UX and bypassing its bookkeeping.

Missing shape: a handler-callable `RefuseDryRun(reason)` (or an error
type the dispatcher recognizes) that renders exactly like the
registration-time refusal — same wording, same exit code — but is
decided per invocation, after the handler has seen the argv.

## 2. The dry-run epilogue prints after a refusal

A command that exits nonzero under `--dry-run` (its own refusal, printed
to stderr) still gets the framework's end-of-dispatch epilogue on
stdout:

    DRY RUN — no changes were made. Would do:

with an empty would-do list. A refusal is not a preview; the epilogue
tells the operator a preview happened when the command just declined to
produce one. Suppress the epilogue when the handler returned nonzero and
nothing was recorded (or always when nonzero — decide which is honest).

## 3. `--dump-schema` writes the tracked file and has no stdout mode

Two halves:

- The flag's name and the general convention (`--dump-*` reads as
  "emit") suggest stdout; it actually REWRITES `.strictcli/schema.json`
  in place. An operator or tool running it to *inspect* the schema
  mutates the working tree as a side effect. At minimum document this
  loudly in the flag help; better, add a stdout spelling (`--dump-schema
  -` or a separate `--print-schema`) so inspection is side-effect-free.
- The dump embeds a build-derived pseudo-version, so a committed
  schema.json is stale-by-one-commit the moment anything else commits,
  and every regeneration produces a diff even when nothing about the
  surface changed. A deterministic version source (the declared app
  version, or omission outside release builds) would make the artifact
  stable between real surface changes.

## 4. The payload-schema subset admits no `description` keyword

Consumer payload schemas cannot carry per-member human-readable
descriptions; the semantics of a subtle member (e.g. a boolean whose
meaning is "found inside the tool's own state directory", not "path is
relative to it") can only live in a Go doc comment the machine-schema
consumer never sees. Admitting `description` (ignored by validation,
emitted in the dump) is small and benefits every consumer's machine
interface.

## Effort

1 and 2 small-to-medium (dispatcher changes with tests); 3 small; 4
small. Independent — any subset can ship alone.
