# Scalar parsing: stale "no leading zeros" doc claim, and Go-only hex-float acceptance

Two defects in the strict scalar-parsing layer, found by reading the parsers and
the conformance corpus side by side. Both verified against the working tree.

## Problem 1: docs claim "no leading zeros" but conformance asserts acceptance

`conformance/cases/boundary.json` contains a case passing `--port 007` to an
`int` flag and expecting exit 0 with `port=7` — acceptance, in all three
implementations. Multiple docs claim the opposite (search anchor: the phrase
"leading zeros"):

- `docs/_CLAUDE.md` — "no leading zeros in Go"
- `docs/go-quickstart.md` — unqualified "no leading zeros"
- `docs/python-quickstart.md` — unqualified
- `docs/typescript-quickstart.md` — two occurrences, unqualified
- `docs/flag-system.md` — "no leading zeros (in Go)"
- `docs/architecture.md` — unqualified
- generated `docs/_build/` outputs derived from the above

The docs and the committed conformance expectation contradict each other; one of
them is wrong, and the choice should be deliberate.

### Solutions

- **A. Fix the docs** — delete the claim; behavior stays "leading zeros
  accepted, parsed base-10". Pros: no behavior change; conformance already pins
  acceptance in all three languages. Cons: `007` silently meaning 7 can
  surprise octal-minded callers, and the strict-parsing philosophy arguably
  wants the stricter reading.
- **B. Make the docs true** — reject leading zeros in all three parsers, add an
  error template (plus error-parity entry) and a conformance case asserting
  rejection. Pros: stricter; removes the octal-ambiguity class entirely, which
  fits "declare everything, infer nothing". Cons: breaking change for callers
  passing zero-padded integers (dates, IDs); needs a changelog entry and a
  migration note.

Either way the current contradictory state is the defect.

## Problem 2: Go accepts hex float literals; Python and TypeScript reject them

`typescript/src/values.ts` carries the comment: `Go-only hex floats ("0x10p2")
are rejected, matching Python.` — i.e. TS and Python deliberately reject hex
float syntax. But Go's `parseFloatStrictValue` (`go/strictcli/parse.go`) only
checks surrounding whitespace and then calls `strconv.ParseFloat`, which
accepts hex float literals (`"0x10p2"` parses to 64). So `--rate 0x10p2`
succeeds under the Go implementation and errors under Python/TS — a
cross-language parity break.

It survives because no conformance vector covers hex-float input: if one
existed, conformance-parity would already be red.

### Solutions

- **A. Reject hex floats in Go** (match the direction Python/TS already chose
  deliberately): guard before `strconv.ParseFloat` (e.g. refuse inputs
  containing `0x`/`0X`), and add a conformance case asserting rejection in all
  three implementations. Pros: restores parity toward the stricter behavior;
  matches the TS comment's stated intent. Cons: none apparent — no doc promises
  hex floats.
- **B. Accept hex floats everywhere.** Pros: none apparent. Cons: widens the
  accepted grammar in all three languages against the strict-parsing
  philosophy.

Whichever direction: add the hex-float conformance vector — the coverage gap is
what let the divergence survive, and per red-green the vector should exist (and
fail) before the fix.

## Affected files

- `go/strictcli/parse.go` (`parseFloatStrictValue`)
- `conformance/cases/` (new vector(s): hex float; leading zeros already covered
  by `boundary.json` — moves or changes only if Problem 1 resolves toward
  rejection)
- `docs/_CLAUDE.md`, `docs/go-quickstart.md`, `docs/python-quickstart.md`,
  `docs/typescript-quickstart.md`, `docs/flag-system.md`,
  `docs/architecture.md` (+ regenerate `docs/_build/`)
- error template files (`go/strictcli/errors.go`, Python inline templates,
  `typescript/src/errors.ts`) only if a new error message is introduced

## Effort

Small. Problem 2 (guard + vector): roughly an hour. Problem 1 is a decision
plus either doc edits (minutes) or a three-implementation behavior change with
error templates and parity updates (half a day).
