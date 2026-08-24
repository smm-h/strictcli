# Framework-managed output size: commands drown signal in noise

## Context

strictcli already owns the output-verbosity surface: `--quiet`, `--verbose`,
and `--json` are framework-owned flags on every command. But what a command
actually prints is entirely up to the command author, and in practice authors
print everything they know. A render-style command in a consumer CLI prints a
one-line JSON report that is thousands of characters long: overall metrics,
per-track metric maps, per-platform tables, and a full array of advisory lint
findings — all on one line, all by default. The two or three numbers a human
(or an agent) actually needs are buried in the middle. Nothing in the
framework pushes back on this, so every consumer CLI drifts toward
maximal output.

## Problem

- Default (non-`--verbose`, non-`--json`) output has no size discipline.
  Agents reading command output burn context on noise; humans cannot find
  the useful line.
- The framework owns the verbosity flags but not the verbosity *behavior*:
  there is no framework-level notion of "summary payload" vs "full payload",
  so `--verbose` and `--json` mean whatever each command decides, and the
  default tier is usually identical to the full tier.
- There is no mechanism that even measures output size, let alone one that
  flags a command printing kilobytes by default.

## Possible solutions

### A. Structured report API with framework-rendered tiers

Commands hand the framework a structured result (summary fields + detail
sections) instead of printing directly. The framework renders: default =
summary fields only, `--verbose` = summary + detail sections, `--json` =
the full machine payload.

- Pros: single authority for tier semantics; consistent across every
  consumer CLI; `--json` guaranteed complete precisely because the default
  is allowed to be terse; fits the existing framework-owned-flags philosophy.
- Cons: largest API change; every existing command must migrate its output
  path; the report data model must be general enough for tables, maps,
  and finding lists.

### B. Registration-time output budget with a hard error

Commands keep printing freely, but the framework counts bytes written to
stdout in the default tier and hard-errors (or fails the command's tests)
when a command exceeds a declared budget. A command that genuinely needs a
large default output must declare that intent at registration with a reason,
mirroring how other deliberate exceptions are declared.

- Pros: small surface; immediately enforceable on existing commands; makes
  oversized default output a visible, deliberate declaration instead of
  drift.
- Cons: a budget is a blunt instrument — it caps size without improving
  structure; risk of authors "fixing" a breach by deleting useful output
  rather than tiering it; runtime enforcement of an authoring-time concern.

### C. Lint-style authoring check only

No runtime behavior change; a check (in the framework's test helpers or a
conformance suite) measures representative default outputs and reports
commands whose default tier exceeds a threshold.

- Pros: cheapest; no API change; no runtime cost.
- Cons: advisory pressure only unless wired into a blocking check; does not
  give authors a better mechanism, just a complaint.

A is the structural fix (the framework cannot police what it does not
render); B is enforcement without structure; C is pressure without either.
A combined path — A for new commands, B as the floor for unmigrated ones —
is plausible but doubles the surface.

## Affected areas

Not surveyed from inside the framework; expected to touch the command
registration/declaration surface, the output/rendering path, and the
handling of the framework-owned `--quiet`/`--verbose`/`--json` flags.

## Effort estimate

- A: large — new report data model, rendering, migration of existing
  commands and docs.
- B: medium — stdout accounting, a registration-time declaration, tests.
- C: small — one measuring check plus threshold config.
