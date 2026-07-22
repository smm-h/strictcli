# Globals redesign, design A: reserved flags, effect typing, effects handles

Filed 2026-07-22. This is the adopted design ("A", rungs 3+4+5+7 of a ten-rung ladder; the
declined summit, rung 10, is recorded in `todo/.defer/effect-interpreter-execution-model.md`).
All design decisions below are LOCKED — made explicitly by the user on 2026-07-22. Nothing
here is open for reinterpretation by an implementor.

## Context

Motivating incident: a consumer CLI command received `dry_run` into `**kwargs`, dropped it,
and published a package to a public registry during a `--dry-run`. A first fix ("guard v1",
committed but UNRELEASED: `_validate_global_flag_params`, python/strictcli/__init__.py:3223,
plus python/tests/test_global_flag_param_guard.py) forces every handler to name a parameter
per app-level global. The residual bug class remains: a handler can NAME a flag and IGNORE
it. A consumer census found, in one consumer alone, twelve mutating commands that accept
`--dry-run` and silently execute for real (one of them pushes to a git remote).

Design A makes honoring structural rather than cooperative, everywhere except one
deliberately accepted, lint-visible seam.

## Prerequisite before implementation starts

Read and reconcile the four overlapping deferred todos from June (do NOT skip this; they
predate this design and may contain conflicting or better rulings that must be resolved as
design input, not discovered mid-build):

- `todo/.defer/dry-run-airtight-enforcement.md`
- `todo/.defer/dry-run-side-effect-enforcement.md`
- `todo/.defer/globals-declarative-contract.md`
- `todo/.defer/write-grant-parameter.md`

If any of them is superseded by this design, move it to `todo/.obsolete/`; if partially
relevant, split per the todo-immutability rules.

## Locked decisions (the design)

1. **Framework-reserved flags with app-level opt-in.** `--dry-run`, `--yes`, and `--quiet`
   stop being app-declared globals and become framework-provided flags (like `--help`/
   `--version`), with fixed spelling and semantics, enabled per app via explicit opt-in
   switches on App construction (shape like `mutation_confirm=True, dry_run=True,
   quiet=True`). Apps that do not opt in keep today's surface. Rationale: the framework owns
   the semantics (see 4-6), so it must own the flags; one ecosystem-wide spelling, no
   per-app redeclaration drift.
2. **Two classes for remaining app-declared globals.** Each app-declared global is tagged
   `universal` (output modifiers; auto-delivered to every command; handlers must name the
   snake_case parameter — guard semantics) or `scoped` (behavior gates; per-command opt-in;
   parse-time hard rejection elsewhere). No untagged globals.
3. **Effect typing.** Every command may declare `read_only` or `mutating` (a registration
   field on the frozen Command dataclass, sibling to the existing `interactive` bool,
   __init__.py:2151). Gate applicability derives from it: reserved `--dry-run`/`--yes` (and
   scoped gates) attach to `mutating` commands and are parse-time-rejected on `read_only`
   ones. ABSENCE of a declaration is the fail-safe: the command is treated as read-only for
   gate applicability (all gates rejected loudly), and the lint (decision 9) flags effectful
   calls inside unclassified or read_only handlers. No mandatory empty boilerplate.
   `read_only` PERMITS framework-blessed internal cache writes (idempotent, safe to delete,
   invisible within the run) — read_only means "no user-visible/consequential mutation,"
   not "no writes at all"; document this definition normatively.
4. **Framework-owned confirmation.** For `mutating` commands in apps that opt in, the
   framework prompts y/N before invoking the handler; a negative answer aborts cleanly;
   `--yes` skips. On non-interactive stdin the framework raises a clean hard error naming
   the remediation ("stdin is not interactive; pass --yes to confirm") — never a traceback.
   Handlers never receive a `yes` parameter.
5. **Framework-owned quiet.** `--quiet` is honored at the Context output layer (info/debug
   filtering at __init__.py:220-230); handlers never receive a `quiet` parameter.
6. **Dry-run via injected effect handles.** Side effects flow through handles on Context
   (`ctx.effects.run()`, `.write()`, and the method set fixed in the Phase-2 contract). In
   dry mode the framework injects a recording no-op implementation and renders the recorded
   would-do log; in real mode, the live one. Handler code is identical in both modes.
   Handlers do not branch on a `dry_run` kwarg; the mode lives in the handle.
7. **Forwarding registration for wrapper/factory apps.** A first-class registration mode
   (analogous to passthrough) where a generic wrapper handler explicitly receives the
   globals as a dict argument and forwards them. No silent swallowing — delivery is explicit
   data. The guard exempts only declared forwarders. (Exists for one large consumer that
   registers hundreds of commands through a generic `def wrapper(ctx, **kwargs)` factory.)
8. **Guard v2 replaces guard v1 — v1 never ships.** New semantics: every handler names
   exactly its supported scoped globals plus all universal ones; declaration, signature, and
   parse acceptance stay mutually consistent; all violations collected into ONE startup
   ValueError before any parsing, on every entry path (run/test/call/_invoke/MCP).
   HARDENING: the framework-handler exemption (`_strictcli_framework_handler`,
   __init__.py:1587) additionally verifies the marked handler's defining module is strictcli
   itself; a consumer-marked handler is a hard error. Rewrite
   test_global_flag_param_guard.py for v2 semantics.
9. **Bypass lint.** A check provider (strictcli `check` integration) that flags direct
   ambient-effect usage (subprocess, socket, write-mode open, os.system) in handler modules
   — rung-8 detection without rung-8 sandbox enforcement. Hard error on findings in
   `mutating` handlers that opted into effects; the deliberate seam stays visible, never
   silent.
10. **Parse-time rejection format** mimics the existing unknown-flag error exactly
    (`error: unknown flag '--x'` + `try '<app> <cmd> --help'`, __init__.py:5815,
    conformance/cases/flags.json:373): `error: command '<name>' does not support '--dry-run'`.
    Enforced at BOTH choke points: `_parse_command` (argv) and `_invoke` (call()/MCP).
11. **No warnings, no escape hatches, no opt-outs** anywhere in the above. All errors hard.
12. **Single breaking release.** Guard v1 and this redesign ship as ONE breaking change;
    consumers never see the intermediate state. Consumer migration beyond the primary
    gate-using consumer is explicitly OUT of this todo's scope — after the work lands, smoke
    tests of consumers' installed binaries produce a graded breakage list, and migration is
    a separate, later-planned effort.

## Phased work (dependency-ordered; no design left inside)

- **Contract phase**: write the normative spec of decisions 1-11 (reserved-flag semantics,
  opt-in switches, class tags, effect classes and the cache-permitting read_only
  definition, forwarding registration, the ctx.effects method set and dry-mode recording
  semantics, prompt wording + non-TTY error text, guard v2 rules, lint scope, rejection
  message format); extend conformance/schema.json (command-level effect class, global-flag
  class field, app opt-in switches, forwarding mode) and author the cross-language fixture
  set including dry-mode performed-set-empty assertions.
- **Python reference implementation**: everything in decisions 1-10 in
  python/strictcli/__init__.py + the lint provider; schema-dump extension; rewrite affected
  tests; full suite green.
- **Go + TypeScript parity**: same features in go/strictcli/ and typescript/src/;
  conformance harness green across all three implementations against the contract fixtures.
- **Verification**: fresh spec-only audit of the whole feature against the contract; then
  smoke tests running each consumer's installed binary to grade breakage (evidence for the
  separate consumer-migration decision).
- **Release**: one breaking release via the standard release flow, on explicit user trigger
  only. Changelog: single breaking entry covering the whole redesign (the existing
  unreleased guard-v1 breaking entry must be superseded/amended, not duplicated).

## Affected files

- `python/strictcli/__init__.py` — guard (3223), delivery loop (4433-4438), parse
  (_parse_command 5693, _parse 4433), _invoke (5055), Context (205-274), Command dataclass
  (2136-2158), registration/decorators, schema dump (7473+, 7673).
- `python/tests/` — test_global_flag_param_guard.py (rewrite), test_global_flags.py, plus
  new tests per feature.
- `go/strictcli/` (strictcli.go, parse.go, context.go, schema.go), `typescript/src/`
  (app.ts, parse.ts, factories.ts, types.ts, schema.ts) — parity implementations.
- `conformance/schema.json`, `conformance/cases/`, harnesses, check_schema_parity.py.
- `CLAUDE.md` / docs — replace the guard-v1 documentation with the v2 + design-A model.
- `.rlsbl-monorepo/releasables/py-strictcli/changes/unreleased.jsonl` — amend the breaking
  entry.

## Effort estimate

Weeks-scale. The Go/TS parity phase is the bulk. Contract and Python phases are
sequential; parity is parallelizable per language; verification and release follow.
