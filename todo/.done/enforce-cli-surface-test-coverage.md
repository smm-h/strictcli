# Enforce test coverage for every command, subcommand, and flag

## Context

A consumer tool was discovered to have shipped a top-level CLI command that had
NEVER worked — it errored immediately on every single invocation, from the day
it was introduced until it was discovered by accident roughly two months later.
The command shelled out to an external tool with arguments that could never
satisfy the external tool's contract (a config file that existed in zero
deployments, plus a file format the external tool cannot parse). Not one test
exercised the command, so nothing ever caught it. The command passed
registration-time validation (strictcli's help-text and signature checks all
passed), was listed in `--help`, appeared in the schema dump, and was
documented — while being 100% dead on arrival.

strictcli's registration-time validation catches structural misconfiguration
(missing help, bad signatures, banned flag names), but nothing catches "this
command has zero tests." A command with zero tests can be completely broken
forever and nothing in the ecosystem notices.

## Problem

There is no enforcement that every registered command/subcommand (and ideally
every flag) is exercised by at least one test. The double-entry philosophy
(declared in TOML AND registered in code, both must agree) already exists for
checks — but the CLI surface itself has no analogous "declared AND tested"
invariant.

Since strictcli knows the complete CLI surface (it generates `--dump-schema`),
and since consumers are told to test exclusively through `app.test(argv)` /
`app.Test(argv)` (never shelling out), strictcli is uniquely positioned to
enforce this mechanically.

## Proposed solutions

### (a) test()-instrumented coverage manifest + built-in check — RECOMMENDED

`app.test()` / `app.Test()` already routes every test invocation through the
framework. Add opt-in instrumentation: when a coverage-recording mode is active
(e.g. an env var set by the test harness, or a `test_coverage=` App option),
every `test()` call appends the resolved command path (and the flags explicitly
passed) to a coverage manifest file. A new built-in check
(`cli-test-coverage`) then compares the manifest against the schema surface:
every command/subcommand must appear at least once; optionally every flag must
appear at least once across all invocations. Missing entries are a hard FAIL
listing exactly which commands/flags have zero test coverage.

- Pros: zero consumer effort beyond running their existing suite with recording
  on; the manifest is generated, committed, and CI-verified (same pattern as
  schema.json); works identically in both languages; the check plugs into the
  existing check framework and release preflight.
- Cons: needs a "run the suite, then run the check" sequencing in CI (the
  manifest must be fresh); flags coverage can be noisy (negations, globals) and
  probably needs to start command-level only.

### (b) Schema-diff against test-file static analysis

A checker script greps/parses test files for `app.test([...])` argv literals
and diffs the first tokens against the schema's command list.

- Pros: no runtime instrumentation; can run standalone.
- Cons: static analysis of argv literals is fragile (variables, parametrize,
  helpers that build argv); Go tests build argv dynamically; high
  false-negative rate. Weaker than (a) in every dimension except simplicity.

### (c) Registration-time `tested_by` declarations

Each command registration names its test(s); a check verifies the named tests
exist.

- Pros: explicit, declarative, matches "declare everything."
- Cons: declarations go stale (test renamed, command still points at it);
  verifying "the named test actually invokes this command" recreates problem
  (a); couples production code to test file layout. Worst option — double-entry
  without the mechanical verification that makes double-entry worth it.

## Enforcement level

Per ecosystem philosophy: the check should be a hard error (release-gating,
`preflight` tag) once a consumer opts in, with no bypass flag. Rollout needs an
adoption path: the check only activates when the coverage manifest exists, so
consumers opt in by generating it once — but once present, it gates.

## Affected

- `python/strictcli/__init__.py` — `app.test()` instrumentation, manifest
  writer, `cli-test-coverage` check implementation
- `go/strictcli/` — `App.Test()` instrumentation, same check
- Conformance: cases for manifest recording + the coverage check in both
  languages
- Docs: coverage manifest format, CI sequencing, adoption guide

## Effort estimate

Medium: the instrumentation is small (test() is a single choke point in each
language); the check is a set-diff against the schema; most of the work is the
manifest format spec, both-language parity, and conformance coverage.
