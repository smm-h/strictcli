# Support multiple strictcli mains per Go module (per-main schema dump)

## Context

The Go convention today is one strictcli CLI per project, with `--dump-schema` writing a single `.strictcli/schema.json`. A consumer Go module has several strictcli-based mains under `cmd/` (an ops CLI, a codegen tool, a benchmark harness) and wants all of them to be strictcli apps. Downstream consumers of the schema (rlsbl's release-time schema dump, selfdoc's CLI reference generation) currently assume exactly one schema file per project — rlsbl hard-errors at release when more than one main imports strictcli (a corresponding todo is filed in rlsbl).

## Problem

- `--dump-schema` output path is fixed at `.strictcli/schema.json`, so two apps in one module would overwrite each other.
- No convention exists for schema-consumers to discover N schemas in one project.

## Solutions

- (a) **Recommended:** per-main output derived from the app name: `--dump-schema` writes `.strictcli/<app-name>/schema.json` (app name is already mandatory at `NewApp`). Keep reading the legacy flat path as a fallback for single-app projects, or migrate consumers in lockstep since both are in-ecosystem. Discovery = glob `.strictcli/*/schema.json`.
  - Pros: zero new flags, deterministic, consumers discover by glob.
  - Cons: layout migration for existing single-app projects (mechanical; consumers are all in-ecosystem).
- (b) Configurable output path flag (`--dump-schema-path`). Pros: no convention change. Cons: violates the declare-everything philosophy by pushing layout decisions to invocation time; consumers can't discover schemas without extra config.
- (c) Single merged multi-app schema file. Pros: one file. Cons: schema format change ripples through every consumer; app identity inside the file becomes load-bearing.

## Affected

- go/strictcli/schema.go (dump path derivation) and the Python twin (conformance parity — schema output behavior is cross-checked by the conformance suite).
- Docs.
- Coordinated consumers: rlsbl strictcli_detect + release schema-dump step; selfdoc strictcli_support (CLI reference generation should render one reference per app).

## Effort

S–M in strictcli itself (plus conformance updates); consumer coordination tracked in their own todos.
