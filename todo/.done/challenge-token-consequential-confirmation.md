# --approve-consequential is a static bypass, not a challenge — consider a challenge-token confirmation design

## Context

The consequential-command gate is framework-owned: `--approve-consequential`
is a reserved quartet token (`strictcli.go:2396`), pre-scanned onto the App
(`strictcli.go:403, 2658`), and consumed by `confirmDecision`
(`effects.go:1223-1239`), fired before the handler runs (`strictcli.go:2175,
2185`). The decision logic:

```
if !cmd.Consequential            -> proceed
if dryRun || approveConsequential -> proceed
if !interactive                  -> confirmNonInteractive (exit 1)
else                             -> TTY y/N prompt
```

The non-interactive refusal (`errors.go:1306`) is:
`error: stdin is not interactive; pass --approve-consequential to confirm`

## Problem

For AI agents — the primary consumers per the projects-wide philosophy — this
gate adds no friction and no information:

- The error message **prints the exact token that lifts it**. An agent's
  natural recovery is to append the flag to the identical command line and
  re-run. Observed in practice: an agent purging archive items hit the
  refusal and cleared it by reflex within one retry.
- The flag is a **static boolean**: it carries no argument, commits to
  nothing, and can be baked into scripts/muscle memory. The historical rename
  from `--yes` ("its unwieldiness is the point",
  `docs/history/_effects-contract.md`) deters *typing*, not copy-paste.
- The framework gate fires pre-dispatch, when only the command path is known.
  The information that would make confirmation meaningful — the resolved set
  of things about to be destroyed — exists only inside the handler, after
  selector resolution. Consumer CLIs typically ALSO have their own in-handler
  prompt that enumerates the doomed items, and that better-informed gate tends
  to be skippable with a one-character `-f` style flag. The gate that knows
  the least is the one the framework enforces.

Expected shape (per project owner): a dry run prints a confirmation token that
commits to the planned destruction; the real run must present that token. The
agent is thereby forced through the preview — it cannot approve what it has
not seen.

No nonce/challenge mechanism exists anywhere in the codebase today (grep for
nonce/challenge/token/plan-hash: zero relevant hits across Go/Python/TS).

## Solutions

- **A — consumer-local, stateless plan digest (framework unchanged).**
  Consumer CLIs implement it themselves: `--dry-run <destructive-cmd>` prints
  `confirmation token: <12 hex>` = truncated SHA-256 over the canonical
  resolved plan (ordered item tuples + selector), salted with a per-install
  random value. Real run requires `--confirm-plan <token>`; handler recomputes
  and hard-errors on mismatch, showing the drift. Pros: no framework change,
  no cross-language parity work; commits to the exact item set so it
  self-invalidates when state changes between preview and execution;
  interactive humans keep the TTY prompt. Cons: every consumer reinvents it
  (divergent spellings/semantics); coexistence with the framework flag must be
  settled or it becomes three gates; salt is local so the token is friction,
  not cryptography; still one-line chainable via command substitution.
- **B — consumer-local single-use nonce persisted in consumer state.**
  Preview mints a random token, stores (token, plan_digest, expiry) in the
  consumer's own DB/state dir; real run validates, requires digest equality,
  marks consumed. Pros: token genuinely cannot be produced without running
  the preview; single-use; time-bounded; the challenge table doubles as an
  audit trail of previews. Cons: preview must WRITE state, which collides
  with any dry-run-never-writes invariant (may need a dedicated `--plan`
  subcommand emitting a plan file instead — closer to the file-driven-over-
  flag-driven philosophy); needs GC of stale tokens; still chainable.
- **C — framework-level challenge (`--approve-consequential=<token>`).**
  Make the quartet token value-carrying and add a contract API (e.g.
  `ctx.ConfirmPlan(digest)`) so the gate can move into the handler where the
  resolved plan exists; pre-dispatch argv-only commitment is nearly worthless
  for `--all`-style selectors. Pros: one mechanism for every consumer CLI in
  the ecosystem; keeps the confirmation protocol framework-owned as the
  effects contract intends; strongest ecosystem-wide fit for hard-constraints
  philosophy. Cons: most expensive by far — quartet shape change across three
  lockstep implementations (Go/Python/TS), conformance suite, error-parity
  vectors, effects-contract sections 7.3/8.x, and every consumer app;
  handler-level gating is a contract-level change.

Cross-cutting (applies to any option):

- `errors.go:1306` must stop printing the answer. Say HOW to obtain the token
  ("re-run this selection with --dry-run") without printing it — otherwise
  the teach-the-bypass flaw survives the redesign.
- The fate of consumer-side `-f`/`--skip-confirmation` flags needs deciding:
  today they skip the only gate that enumerates what dies. Options: remove,
  replace with the token, or keep for interactive humans only.
- `--dry-run` currently short-circuits the framework gate (`effects.go:1227`).
  Under a challenge design the dry run becomes the token SOURCE — that branch
  acquires a second job.

## Affected files

- `go/strictcli/strictcli.go:403, 832-835, 2175, 2185, 2206, 2396, 2658`
- `go/strictcli/effects.go:1202-1239`
- `go/strictcli/errors.go:1302-1308`
- `go/strictcli/context.go:74-78, 191-209`
- Python/TS counterparts (lockstep parity) if option C
- `docs/history/_effects-contract.md` sections 7.3, 8.1-8.4 if option C
- Conformance suite + error-parity vectors if option C

## Effort

- A: small-medium per consumer (no framework work).
- B: medium per consumer (state, GC, plan-file design).
- C: large (three implementations + contract + conformance + consumer
  migration).
