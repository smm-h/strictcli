# Machine-mode refusal data, effects-handle verbs, and a passthrough vocabulary

## Context

A Go consumer built on strictcli wraps another tool's subprocesses behind its
own guard checks (locks, a dirty-tree check, per-command allowlists of the
wrapped tool's options), records what it did in an append-only log, and offers
`--dry-run` previews of every operation. An audit of that consumer's machine
contract, its preview honesty, its log, and its documentation found a set of
gaps that are structural on the framework side: the consumer cannot close them
by itself without either re-implementing a framework concern locally (which it
would then have to delete when the framework catches up) or leaving a hole and
documenting it.

This file collects every such gap in one place, including speculative items
and open decisions, so the framework work can be planned as one body rather
than arriving as a trickle of one-line requests. Each item states the problem
as observed in the framework's own code, the options, their pros and cons, the
affected files, and an effort estimate. Locations name functions rather than
line numbers where the function name is stable.

The consumer's own rulings that shape the priorities here:

- Every outcome of a command should answer a machine consumer with the output
  document plus data whenever data exists, refusals included. The consumer
  will ship the framework-independent half now (handlers return instead of
  exiting; every command declares a payload) and wait for the framework's
  refusal channel rather than build a local one.
- The consumer intends to derive its operation log from the effects handle's
  record rather than narrate it by hand in every handler, so the handle's
  coverage of the consumer's writes has to be complete.
- The consumer keeps enforcing its own allowlists for passthrough commands
  until the framework's declaration has a second consumer; what it wants from
  the framework first is rendering and export, not enforcement.

## Item 1. The machine-mode document is skipped when a handler exits the process

**Problem.** `finishDispatch` (strictcli.go) is the one ordered exit step, and
`runSealed` reaches it through deferred paths on every way out of a dispatch —
normal return, `Exit`, panic. A handler that calls `os.Exit` directly runs no
deferred function, so in machine mode stdout is empty: no document, no
`exit_code` member, nothing. The consumer had roughly two hundred such call
sites, most inside a `die(code, msg)` helper that also released its locks. The
contract says handlers return; nothing enforces it and nothing helps a consumer
find the violations.

**Options.**

- (a) Documentation only: state in the contract that `os.Exit` in a handler
  loses the document. Pro: free. Con: the consumer already knew and still had
  two hundred sites; a rule with no check is not a rule.
- (b) A published guard helper: a test-only package (for example
  `strictcli/testkit`) exporting an AST scan that refuses `os.Exit`,
  `log.Fatal*` and any consumer-named exit helper inside the packages a
  consumer names, with a declared exemption table (the consumer's own signal
  handler and pre-dispatch code). Pro: makes the contract checkable in every
  consumer with one test; the consumer already writes such scans by hand for
  other invariants. Con: a helper a consumer must opt into; new test surface.
- (c) Framework-owned exit: every handler returns an outcome value and the
  framework is the only caller of `os.Exit`. Pro: the strongest statement.
  Con: no framework can intercept a direct `os.Exit`, so (c) reduces to (b)
  plus documentation; it is not a separate option in practice.

**Recommendation.** (b), with the contract sentence from (a).

**Affected files.** New test-support package; docs of the dispatch contract.

**Effort.** Small.

## Item 2. A declared payload schema with no payload emitted is silently null

**Problem.** `validateEmittedPayload` (strictcli.go) returns early when
`ctx.payloadSet` is false. A command that declares a `PayloadSchema` and then
completes at exit 0 without ever calling `Payload(...)` emits `payload: null`
and nothing objects. In the consumer this hid seventeen commands whose results
reach only the human channel that machine mode suppresses.

**Options.**

- (a) A hard error at emission when the exit code is 0, a schema is declared,
  and no payload was set. A refusal on a nonzero exit is exempt until Item 3
  gives it a channel. Pro: the silent null becomes impossible for successes.
  Con: a `--dry-run` that stops short of the point where a payload would be
  built has to either set one or be exempt — a decision to make deliberately
  (see open decisions).
- (b) A per-command `PayloadRequired` option. Pro: opt-in, no surprise. Con: a
  knob every consumer leaves off; the framework's own guidance says mandatory
  over optional.
- (c) Status quo, documented. Con: leaves the defect class in every consumer.

**Recommendation.** (a).

**Affected files.** `validateEmittedPayload`, its tests, the payload section of
the contract.

**Effort.** Small.

## Item 3. No channel for structured refusal data

**Problem.** The output document's member set is fixed (`interface_version`,
`app`, `app_version`, `command`, `exit_code`, `payload`, `dry_run`, `writes`,
`preview`, `preview_error`, `diagnostics`) and the payload schema a command
declares describes the performed operation. A refusal therefore cannot carry
data: which paths were dirty, which offenders were grouped by which shape,
which health checks failed. Consumers answer refusals with `payload: null` and
prose on stderr, and agents end up parsing stderr. One consumer's "the
operation stands but a later step did not finish" family already ships a
payload on a nonzero exit (the created object plus a residue list), so
"payload on nonzero exit" is already a legitimate shape and the refusal channel
must not break it.

**Options.**

- (a) An `error_payload` member plus a `RefusalSchema(...)` command option,
  validated at emission the way `payload` is. The member set grows, so
  `interface_version` moves from 2 to 3 per the rule stated beside the
  document type. Pro: additive; the success payload's meaning is untouched;
  consumers declare the refusal shape per command. Con: two slots whose
  co-occurrence rules must be stated (may both be present? on which exit
  codes?); a version bump that every consumer's parser must follow.
- (b) No framework change: permit a payload on a nonzero exit under a
  consumer-declared discriminated union (`outcome: performed | previewed |
  refused` inside the payload). Pro: available today. Con: redefines what
  `payload` means, locally, per consumer; when (a) or (c) ships the local
  spelling must be deleted (pre-stable, no compatibility), so it is throwaway
  work; two consumers would invent two discriminators.
- (c) A framework-owned `outcome` member in the document with values
  `performed`, `previewed`, `refused`, and one `payload` slot whose schema is
  selected by the outcome (`PayloadSchema` for performed and previewed,
  `RefusalSchema` for refused). Pro: one slot, one discriminator the framework
  owns, no co-occurrence rules. Con: a larger interface change than (a); the
  previewed/performed distinction duplicates `dry_run`.

**Recommendation.** (a) or (c); (c) is the cleaner model, (a) the smaller
change. This is an open decision (below). Never (b).

**Affected files.** The document type and its emission in strictcli.go,
`validateEmittedPayload`, `payload_schema.go`, the contract's machine-mode
sections, the schema dump.

**Effort.** Medium, plus the interface-version bump and its documentation.

## Item 4. The effects handle's closed method set lacks symlink, append, and hard link

**Problem.** The `Effects` method set is `Run`, `Spawn`, `Write`, `Mkdir`,
`Remove`, `Rename`, `Chmod`, `HTTP` (effects.go). Three writes a guarded
consumer performs have no verb:

- **Symlink.** Materializing a symbolic-link resolution into a working tree
  (`os.Symlink`). Today it bypasses the handle: not recorded in a preview, not
  refused in preview mode.
- **Append.** An append-only log whose atomicity is an exclusive `flock` held
  across the append. `Write` is whole-content and would destroy the O_APPEND
  concurrency guarantee, so the consumer appends outside the handle by
  declared exception — which means a preview cannot record "one log line would
  be appended" and a derived operation log cannot see it.
- **Link.** Atomic lock publication by `link(2)`: a record is written to a
  temporary sibling and linked into place, EEXIST being the one-winner signal.

**Options.**

- (a) Add `Symlink(target, path)`, `Append(path, data)` and `Link(old, new)`
  with the same dry-run recording, resource tagging and refusal-in-preview
  behavior as the existing verbs. Pro: the handle's coverage becomes complete
  for this consumer class; each verb is small. Con: three more members of a
  deliberately closed set; `Append` needs a decision about who holds the lock
  (the framework takes the flock, or the caller passes an already-locked
  descriptor).
- (b) A generic `Custom(verb, resource, detail, func)` recorded effect. Pro:
  any future write is coverable. Con: an escape hatch — any unrecorded write
  can be laundered as "recorded" with a made-up verb; the closed set exists
  to prevent that.
- (c) Nothing; consumers document the holes. Con: preview honesty and derived
  logs stay incomplete by declaration forever.

**Recommendation.** (a). Lock ownership for `Append` is an open decision.

**Affected files.** effects.go, the effects section of the contract, the
schema of effect records if `Link`/`Symlink` need new detail shapes.

**Effort.** Medium.

## Item 5. Reading the effects record back claims the render, and records carry argv verbatim

**Problem.** `Effects.Recorded()` (effects.go) sets `log.claimed = true` and
returns the records; the end-of-dispatch would-do rendering is then suppressed
unless the consumer calls `RenderLog()` itself. A consumer that reads the
record in order to persist it (as its own operation log) must know this or it
silently loses the human preview. Separately, `effectRecord` is a closed shape
with no annotation slot, and a `Run` record's `detail` carries the full argv —
persisting records therefore risks writing secrets (a history-rewrite
consumer has a test forbidding pattern text in its log).

**Options.**

- (a) A non-claiming read (`Peek()`, or `Recorded()` stops claiming and a
  separate `ClaimRender()` exists for consumers that really do take over the
  render). Pro: reading is no longer a side effect. Con: a semantic change to
  an existing method.
- (b) A summary projection (`RecordedSummary()`) that returns verb, resource
  and sequence and omits `detail`. Pro: exactly the shape a persisted log
  wants; no redaction logic. Con: a second reader to keep in step.
- (c) A per-call `Redact(...)` or `Annotate(...)` option on the mutating verbs.
  Pro: fine-grained. Con: every call site has to remember it; the consumer's
  own rule is that such things are structural, not per-site.

**Recommendation.** (a) and (b).

**Affected files.** effects.go, the effects section of the contract.

**Effort.** Small to medium.

## Item 6. Passthrough commands cannot declare a vocabulary

**Problem.** `App.Passthrough` (strictcli.go) registers a command with no
flags and no positional declarations. Consequences: `--help` renders only the
help prose; `--dump-schema` exports `"passthrough": true` and nothing else; a
documentation generator reading the schema sees nothing. A consumer that
implements a deliberate subset of the wrapped tool's options therefore keeps a
hand-written default-deny allowlist per passthrough command, a help string
that restates it, a documentation table that restates it again, per-command
guide paragraphs, and a value-arity table for its own argv parser — five
copies of each option set, kept in step by hand.

**Options.**

- (a) `WithPassthroughVocabulary(...)`: per option, its spellings, a verdict
  (allow, or refuse with a reason), a value arity (none, attached only,
  separate), a short gloss for documentation and a long reason for the refusal
  message; plus an argument-grammar statement. The framework renders it in
  `--help`, exports it in the schema, and enforces default-deny before the
  handler runs. Pro: one declaration, every rendering derived; enforcement
  gains the framework's registration-time checks. Con: moves a consumer's core
  promise (its subset law) into a dependency; a large feature shaped by one
  consumer's needs.
- (b) Declaration, rendering and export only; enforcement stays with the
  consumer. Pro: kills the documentation copies without moving the promise;
  smaller. Con: the declaration and the consumer's enforcement table can
  drift unless the consumer derives one from the other — which it can, since
  both are its own code.
- (c) Nothing. Con: five copies, forever.

**Recommendation.** (b) first. (a) only when a second consumer exists. A
documentation-site directive that renders the exported vocabulary is a
separate item for the documentation tool, not for strictcli.

**Affected files.** `Passthrough` and `PassthroughHandler`, the schema dump,
help rendering.

**Effort.** Large.

## Item 7 (speculative). Known versus unknowable values in preview records

**Problem.** A consumer's ref-update port substitutes a placeholder for a
commit identifier in dry-run because the commit is not written in a preview;
but for a fast-forward the identifier is known in advance, and the placeholder
hides a fact the preview could state. Nothing in the effect record
distinguishes "not computable in a preview" from "computable and omitted".

**Option.** A typed marker for unknowable detail values in effect records, so
a renderer and a machine consumer can tell the two apart. Low priority; the
consumer can solve its own instance without it.

## Item 8 (speculative). A diagnostics guard

**Problem.** `Context.Info`, `Warn`, `Debug` and `Error` feed the document's
`diagnostics` member in machine mode. A consumer that prints its human text
with `fmt.Printf` has `diagnostics: []` on every run, so machine mode carries
none of the explanation the human sees.

**Option.** A guard helper (pairs with Item 1's) refusing `fmt.Print*` to
stdout outside a consumer-declared set of renderer functions. Low priority.

## Item 9 (open question). `--dump-schema` writes into the tree

**Observation.** With `WithSchemaPathRelativeToRoot`, `--dump-schema` writes
the tracked schema file in place. That is what a release step wants; it also
means an operator or a test that runs `--dump-schema` to look at the schema
modifies a tracked file as a side effect. Whether a stdout form (`--dump-schema
-`) or a refusal when the target differs from the committed copy is wanted is
an open question, not a request.

## Open decisions

- Item 3: `error_payload` as an additive member (a) or a framework-owned
  `outcome` discriminator with one payload slot (c).
- Item 2: whether a `--dry-run` that completes at exit 0 without a payload is
  exempt from the hard error, or must set a preview payload.
- Item 4: for `Append`, whether the framework takes the exclusive lock or the
  caller passes an already-locked descriptor.
- Item 6: (b) now and (a) later, or (a) directly — and whether enforcement of
  a passthrough vocabulary belongs in the framework at all.
- Item 9: whether `--dump-schema` should have a non-writing form.

## Ordering

Items 1, 2 and 5 are small and independent; do them first. Item 4 next — it
blocks a consumer's preview completeness and its derived operation log. Item 3
carries the interface-version bump and should be batched with any other change
to the document's member set. Item 6 last, in its (b) form.
