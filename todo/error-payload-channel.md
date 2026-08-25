# Machine mode has no error-payload channel

## Problem

The envelope contract gives a command exactly one structured outlet: the
`payload` member, emitted on the success path and validated against the
command's declared schema. There is no counterpart for failures. A
consumer of a refusing or failing command today sees one of three
shapes, and has to handle all three:

1. A payload-carrying nonzero exit — only possible when the handler
   REACHES its payload emission despite the failure (the
   "operation stands, aftercare failed" family a consumer app built by
   hand: report-then-return instead of exiting, one payload at the end).
2. An envelope with `payload: null` and the structured facts pushed to
   STDERR as prose — the shape every parser-level and handler-level
   refusal produces. The facts exist (which paths, which reasons) but
   ride an unstructured channel.
3. NO envelope at all — any path that exits before dispatch finishes
   (`os.Exit` from a die-style helper bypasses the envelope emission
   entirely).

Consumer apps that want structured refusal reporting currently have no
sanctioned way to provide it: `Context.Payload` is one-shot and
schema-validated against the success shape, so a refusal payload would
fail validation, and inventing a second document breaks the
one-document-per-run contract.

## Solution sketch

Two composable pieces:

- **An error-payload member on the envelope** (e.g. `error_payload`,
  present-null on success), with an optionally-declarable per-command
  refusal schema. A command that declares none keeps today's shape; a
  command that declares one can hand structured refusal facts (the
  refused inputs, the reasons, the way out) to machine consumers inside
  the one-document contract.
- **Envelope-always at the framework level**: a dispatch-level seam that
  guarantees the envelope is emitted even when a handler exits early —
  e.g. the framework owns the exit (handlers return, never call
  os.Exit), or a registered atexit-style emission. This removes shape 3
  entirely; consumer code that dies before dispatch is the one residual
  documented exception.

## Affected

The envelope structure, `Context.Payload`'s one-shot rule, schema
declaration/validation, `--dump-schema` output.

## Effort

Medium: the member and its validation are straightforward; the
envelope-always guarantee touches the exit conventions and needs a
migration story for consumer apps that call os.Exit today.
