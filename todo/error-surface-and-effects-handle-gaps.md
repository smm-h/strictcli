# Error surface and effects-handle gaps surfaced by a consumer migration

A Go consumer's migration to go-strictcli v0.33.0 surfaced two clusters of framework
gaps. All findings below were verified against this repo's source and, where noted,
reproduced against a real binary. Line numbers are as of go-strictcli v0.33.0 /
py 0.41.0 / ts 0.40.0.

## Decision record

Per the owner's decision-origin convention: `[deliberate]` = the owner's explicit
decision (paraphrased). `[trust]` = adopted from a recommended option, weakly held,
freely reversible. `[open]` = undecided.

- **[deliberate]** The one-line form of the omitted-required-choices message is
  implemented directly (not via this todo); the MULTI-LINE BLOCK form is deferred and
  is item 1b below.
- **[deliberate]** An exclusive-create option on the effects handle is deferred to
  this todo; the consumer takes a simple check-then-write in the meantime.
- **[trust]** The `--help`-vs-required-global-flag inconsistency (item 2) is to be
  confirmed and fixed here rather than left.
- **[open]** Whether items 3a/3b ride the next release together with the one-line
  message change (an argument exists that deferring them forces consumers into a
  second dependency bump and a TOCTOU downgrade in the interim).

## 1. Refusals never name declared choices

When a required flag carrying helped choices (`Ch(value, help)`) is OMITTED, the error
is `flag '--mode' is required` — indistinguishable from a flag with no choices. The
per-choice help in `choiceRecords` is read ONLY by help rendering (`help.go:456-463`)
and the schema (`schema.go:143-158,196-198`); no error message anywhere reads it.
Reproduced live; also live in this fleet: a required two-choice flag on a consumer
refuses with the bare message today.

Five sites know about choices and do not say so (fix them together or the framework is
inconsistent about whether a refusal names its legal values):

| # | Case | Site |
| --- | --- | --- |
| 1 | omitted required value flag | `go/strictcli/parse.go:684` (inline, NOT in errors.go) |
| 2 | omitted required global flag | same function via `strictcli.go:3776` (prefix param) |
| 3 | omitted required flag in an elected scope | `scope_parse.go:699` (same call; suffix appended to the message string) |
| 4 | omitted required positional with ArgChoices | `errors.go:721` via `parse.go:1032,1057,1092,1101,1105` |
| 5 | required token-spelled selector, nothing elected | `scope_parse.go:450` (reads choiceDecls, whose help is mandatory) |

Contrast: the member-spelled selector already names its members (`errOneOfRequired`,
`errors.go:673`); the invalid-VALUE error already names the values but not the help
(`errors.go:740`).

Sites 1-3 are one edit (one shared function). The one-line form reuses the existing
`must be one of:` phrasing so a flag's two refusals read as a pair.

### 1b. The deferred block form (per-choice help in the refusal)

`error:` header line, then the same aligned rows `--help` renders, then the framework's
separate `try '... --help'` hint (printed independently at `strictcli.go:2546-2554` /
`:2893` — NOT appended to the message, so a block sits cleanly above it). Verified
constraints, so nobody rediscovers them:

- There is NO structured error channel to break: under `--json` the envelope carries no
  message (parse errors go to stderr as prose; `emitPreDispatchEnvelope` fills payload
  from nothing). `--quiet` is inert on parse errors. MCP and `InvokeError` carry opaque
  strings; newlines survive.
- It would be the framework's FIRST multi-line message anywhere (zero `\n` in any error
  template in any of the three implementations; TS's quoting helper actively escapes
  newlines). The stated one-sentence-per-rule convention is the real counterargument.
- The scope suffix is APPENDED to the message string (`scope_parse.go:699-702`); a naive
  block leaves ` under '--via email'` orphaned after the last choice row — restructure so
  the suffix attaches to the first line.
- The help-side row renderer is not directly callable (alignment is computed by the
  caller across the whole flag block); extract a small `choiceHelpRows` helper shared by
  help and the error path. `choiceRecordsCarryHelp` (`help.go:538`) is already free.
- Parity mechanics (`conformance/check_error_parity.py`): static extraction, normalized
  signatures, byte-equal across the three implementations. Multi-line IS expressible,
  with two silent traps proven by running the checker: Python MUST use a triple-quoted
  literal with a real newline (an `\n` escape is mangled to a literal `n` by the
  extractor at `:1427-1429` and reads as cross-language drift); Go MUST use `\n` inside
  `fmt.Sprintf` (a backtick raw string extracts ZERO templates). Go's extractor reads
  `errors.go` only, so the parse.go template needs its `SIGNATURE_STATUS` exclusion
  entry updated (`:300-310`), and one conformance case must cover the new signature or
  the coverage check fails.
- Blast radius measured: 79 assertions carry the old text (18 conformance in 10 case
  files; unit: Go 14, Py 21, TS 26), but only ~1 conformance case and ~18 unit
  assertions name a flag that actually declares choices — a change conditioned on
  declared choices leaves the rest byte-identical. Python has FIVE spellings of the
  sentence (`__init__.py:11304, 11733, 12677` [the one shared helper], `14050, 14339`)
  — consolidate while there. TS has one template (`errors.ts:2297-2305`) with four
  callers; growing its signature touches `src/describe.ts` / the api-surface check.

## 2. `--help` loses to a required global flag

With a required GLOBAL flag declared, `app cmd --help` exits 1 with
`error: global flag '--x' is required` instead of printing help. A required COMMAND
flag does not do this, and help deliberately beats every other refusal including the
dry-run-unsupported one. Reproduced with a throwaway app. Likely sites: the global-flag
resolution path (`strictcli.go:3776` / `invoke.go:148`) running before the help check.
Confirm intent, then fix in the same pass as item 1 (same neighborhood); mirror in py/ts
and add a conformance case.

## 3. Effects-handle completeness

The handle's set is closed (eight methods) and three real operations are inexpressible,
all hit by one consumer in a single migration:

- **3a. Exclusive create.** `Write` ends in an unconditional truncating
  `os.WriteFile(target, data, 0o644)` (`effects.go:884-921`). A consumer whose refusal
  was an atomic `O_EXCL` open must downgrade to stat-then-write (TOCTOU) or branch on
  dry-run in application code — the exact patterns the handle exists to prevent.
  Proposal: an `Exclusive()` EffectOption on `Write`; live mode uses
  `O_CREATE|O_EXCL`, dry mode records `write (exclusive)` and still refuses when the
  target exists (the refusal is a read, valid in both modes).
- **3b. File mode.** `Write` hardcodes 0644, `Mkdir` 0755; a read-only output needs a
  second `Chmod` call and two preview lines. Proposal: a `Mode(fs.FileMode)` option on
  both.
- **3c. Append.** No append method or option; an `O_APPEND` log write is inexpressible
  through the handle (a consumer's long-running server logs this way — that consumer
  path correctly declares dry-run unsupported, but the gap is general).
- **3d. `effects-bypass` reachability is same-package-only** (`effects_bypass.go:361`):
  it flags direct `os.WriteFile`/`MkdirAll`/... only in the package where the handler
  lives, so writes delegated into a consumer's internal packages are invisible to the
  check. Either walk cross-package within the consumer's module, or document the limit
  loudly where the check is described.

All three implementations + conformance cases per the usual lockstep rule. Effort:
1 (one-line form) is done elsewhere; 1b ~1 day across three implementations plus
conformance; 2 small; 3a+3b ~1 day; 3c small; 3d medium (analyzer work).
