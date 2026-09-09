# A third effect class for commands that act but leave nothing behind

## Context

Every command declares `effect="read_only"` or `effect="mutating"`. A
`read_only` command promises it changes nothing, never prompts, and may not
call a mutating member of the effects handle (that is a hard error at call
time). A `mutating` command performs its effects through the handle,
participates in `--dry-run` (effects recorded, not performed), and may
additionally be declared `consequential` so a human must approve it.

The classification is binary, and the binary does not describe one real kind
of command: a command whose whole job is a transient interaction that leaves
nothing behind. The case that raised this is a tool whose main command opens a
native window, waits for a human to pick one of the declared choices (or for a
deadline to pass), prints the outcome, and exits. It binds a loopback port and
draws a window, both of which go through the effects handle, and it blocks and
interrupts a person for up to the deadline. It writes no file, no config, no
registry, no state of any kind.

## Problem

Neither class fits, and each misdescribes the command in a way that has
consequences:

- Declared `read_only`, it cannot call the handle members it needs (port bind,
  window), so it cannot be written against the handle at all. It also cannot
  offer a `--dry-run`, which is the preview a caller integrating it wants: the
  request validated and the dialog laid out as text, with no window opened.
  And "read only" is false as a promise: the command is not safe to run at any
  time unnoticed, since it interrupts a human and blocks.
- Declared `mutating`, it gets the handle and the dry run, but `mutating`
  reads as "changes something durable", which is false too. Anything that
  audits or documents the mutating set (the consequential curation, the
  generated command tables, a reader deciding whether a command is safe to
  retry) now carries a command that mutates nothing.

Today `mutating` is the honest choice between the two, because the regime's
classification is about effects rather than persistence. But the vocabulary
does not say that, and every consumer that reads `effect` as "durable change"
is misled.

## Solutions

### Option A: a third class, `ephemeral`

Add `effect="ephemeral"`: the command performs effects through the handle and
participates in `--dry-run` exactly like `mutating`, but declares that nothing
it does outlives the process (no filesystem write, no registry contact, no
durable state). Registration rules: an `ephemeral` command may be
`consequential` only if the framework decides interaction itself can be
consequential (probably not: it is the class consent prompts live in, and a
consent prompt must not open a consent prompt). Whether the handle can enforce
the promise (refusing a filesystem write from an ephemeral command the way it
refuses a mutating call from a read-only one) decides how much this is worth.

- Pros: the declaration says what the command is; docs tables, schema dumps
  and audits can show it; the handle can enforce "no durable write" at call
  time, which is the same mechanism that enforces `read_only` today; the dry
  run comes with it.
- Cons: three implementations plus the conformance suite, the schema, every
  docs table that enumerates classes, and every consumer that switches on the
  value; a third class is a permanent widening of the vocabulary.

### Option B: keep two classes, add a declared property

Keep `read_only`/`mutating` and add an orthogonal declaration such as
`durable=False` on a mutating command, meaning its effects do not outlive the
process. The handle enforces it the same way as in option A.

- Pros: no new class; the enumeration everyone switches on stays binary;
  the property can be enforced independently.
- Cons: two declarations to read instead of one; `mutating` still reads wrong
  on its own; the property is easy to omit, and an omitted property has to
  mean something (probably "durable", which is the safe default but makes the
  declaration opt-in rather than deliberate, against the mandatory-flags
  rule).

### Option C: document that `mutating` means "performs effects"

Change nothing in code; state in the effects docs and in the `effect`
parameter's help that the classification is about the handle, not
persistence, and that a transient interactive command is `mutating`.

- Pros: no code.
- Cons: leaves every reader of the value misled; nothing enforces "leaves
  nothing behind"; the case that raised this stays misdescribed in every
  generated table.

Option A is the most correct: the declaration should say what the command is,
and the handle should enforce it, which is the whole point of the regime.

## Affected files

- The command classification and effects handle in each implementation:
  `python/strictcli/__init__.py` (the classification section and the
  read-only refusal), the effects files under `go/strictcli/`, and
  `typescript/src/effects.ts` with `typescript/src/effects_exec.ts`.
- The schema the implementations dump (the `effect` value's enumeration).
- The conformance cases under `conformance/cases/` and the error-parity
  checks.
- The docs that enumerate the classes: `docs/architecture.md`,
  `docs/flag-system.md`, and the `docs/_CLAUDE.md` template, plus every
  consumer's generated command table once the schema carries the value.

## Effort

Medium. The class itself is small in each implementation; the cost is the
three-way parity, the schema bump, the conformance cases, and sweeping every
docs enumeration of the classes.
