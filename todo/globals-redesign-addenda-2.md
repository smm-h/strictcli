# Globals redesign — addenda batch 2 (design sessions 2026-07-26 → 2026-07-28)

Second addenda batch to `globals-redesign-design-a.md` + `globals-redesign-addenda.md`.
Provenance: decisions marked `[%%]` were adopted from recommendations (freely reversible,
never to be cited as deliberate intent); unmarked decisions were made deliberately by the user.

## A4 — Guard-v1 correction (factual)

Guard v1 **never existed**: no `_validate_global_flag_params`, no `_strictcli_framework_handler`,
no `test_global_flag_param_guard.py` anywhere in history, and no unreleased breaking changelog
entry to amend. Guard v2 is **net-new**, not a rewrite. The actual baseline hole is the
`**kwargs` exemption in Python's handler-signature validation (`_build_and_validate_command`,
skip-all-checks on VAR_KEYWORD). Go (map kwargs) and TS (typed object args) have **no equivalent
hole** — guard v2 is Python-scoped; Go/TS need only verification tests. All line numbers in the
design record are stale (the file has grown); re-locate at implementation time.

## A5 — Unconditional reserved-name ban `[%%]`

`dry-run`, `yes`, `quiet` are banned as user-declared flag names at registration time in ALL
apps, regardless of reserved-flags opt-in — resolving the record's opt-in-conditional wording.
Mechanism mirrors the existing bare-`force` and `no-` prefix bans (per-flag validation + the
reserved-global-set enforcement), in all three languages.

## A6 — Classification mandatory for all apps `[%%]`

`read_only`/`mutating` is a required command field with **no default** in every app (walks back
the record's D3 default) — the help-text precedent: core metadata is unconditionally mandatory.
Registration hard-errors on an unclassified command. Framework-internal commands (config group +
check; 6 per language) are classified by the framework itself. Consequence: every consumer
breaks at its next lock bump; a **single dedicated fleet sweep immediately after the release**
`[%%]` classifies all consumers (the bool-flag-wave precedent).

## A7 — The effects contract (the "Phase-2 contract", now defined) `[%%]`

- Closed generic kind vocabulary: `PROC_OBSERVE`, `PROC_MUTATE`, `FILE_READ`, `FILE_WRITE`,
  `NET_OBSERVE`, `NET_MUTATE`, `CACHE_WRITE`. Consumer domain vocabulary never enters the
  framework (payload labels only).
- Consumer-declared argv allowlists authorize `PROC_OBSERVE` (observes execute even in dry mode).
- Per-command effect-kind declarations narrow the handle at construction.
- **SealedDryHandle**: dry mode injects a different type lacking mutating methods (the
  sealed-reporter pattern generalized). A `read_only` command's handle lacks mutating methods
  in live mode too — misclassification is impotent on the blessed path.
- Per-command **grants** (name + reason) authorize declared real work during dry mode.
  `CACHE_WRITE` is the mechanical definition of D3's "framework-blessed cache writes".
- The would-do log is framework-owned and rendered by the framework.

## A8 — Effects visibility `[%%]`

`test()`'s Result gains `effects` (the CheckResult notes/duration precedent). `run` prints the
rendered log. `call()` is UNCHANGED in v1 — no envelope. The **MCP layer renders the would-do
log into the tool response content when a tool runs in dry mode** (agents must never receive a
silent preview). Recorded v2 trigger: the first programmatic consumer needing effects via
`call()` adopts the `{data, effects}` envelope — not before.

## A9 — Cross-process contract `[%%]`

- `STRICTCLI_EFFECTS_MODE` lattice token: effective mode = join(inherited, local); `record`
  dominates; conflicts are impossible by construction. Plus `STRICTCLI_EFFECTS_ORIGIN`/`_DEPTH`
  provenance (stale-leak diagnosis, recursion ceiling).
- Explicitly NO on-disk corroboration — polarity rule: corroboration hardens fail-open signals;
  this signal fails closed (a stray leak causes refusal/recording, never damage).
- **Spawn-is-an-effect**: `ctx.effects.spawn` records instead of forking in dry mode, so
  non-strictcli children (git, npm, …) are never invoked; real spawns stamp token + provenance.
- A strictcli child under the inherited token: effects-regime commands **auto-record**
  (announced on stderr); legacy/unclassified mutating commands **hard-refuse** at dispatch via
  the classification; read-only proceeds. No override flag. Dry dominates orchestration
  handshakes.
- Reserved env category with its own collision check + help annotation, mirroring the
  infra-env/handshake plumbing (the new connection-env kind is the closest template).

## A10 — Guard v2 + forwarding registration `[%%]`

Close the Python `**kwargs` exemption; add a **declared forwarding-registration mode** for
wrapper-style consumers (one known consumer registers hundreds of commands through a single
`**kwargs` wrapper — forwarding mode must ship in the same release or that consumer cannot
upgrade).

## A11 — Bypass lint (shipped check providers)

Hard error on direct subprocess/socket/write-open in handler modules; grant/escape usage
counted. Python via stdlib `ast`; Go via `go/ast`; **TS via the `typescript` compiler API**
(deliberate user ruling — full AST fidelity in lockstep, dependency accepted).

## A12 — TS staging: full three-way lockstep

Deliberate user ruling (overriding a defer recommendation): the complete effects regime —
declarative surface AND behavioral core — ships in Python, Go, and TypeScript together in one
coordinated breaking release.

## A13 — Conformance impact

Case `env` blocks already exist. Novel work: an effects assertion primitive (e.g.
`effects_equals`) and child-harness spawn support for cross-process cases (no child-process
assertion exists today). Schema gains the command/app fields; `check_schema_parity`,
`check_api_surface`, `check_error_parity` need updates; new error templates centralized.

## A14 — `.defer/` dispositions (execute during Phase 0 of implementation)

- `effect-interpreter-execution-model.md`: stays `.defer/` untouched (the preserved summit).
- `write-grant-parameter.md`, `globals-declarative-contract.md`: stay `.defer/` (not-taken
  alternatives).
- `dry-run-airtight-enforcement.md`, `dry-run-side-effect-enforcement.md`: superseded portions
  move to `.obsolete/` when the regime ships; the OS-sandbox conclusions remain referenced from
  the interpreter todo.
