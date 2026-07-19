# cli-test-coverage fails fleet-wide: committed manifest + ephemeral shards

## Context

The CLI test-coverage mechanism (test()+call() recording, per-process shards
under `.strictcli/coverage/`, committed covered-set manifest, provider-shipped
check) fails identically in at least five consumer repos observed 2026-07-19,
across both Python and Go consumers:

```
FAIL cli-test-coverage — no coverage data: .strictcli/coverage/ contains no
shard files [stale or empty manifest]
```

In three of the five repos this is the SOLE driver of `check --all` exit 1.

## Problem

The design commits the covered-set manifest but shards are generated
per-machine at test time (and are ephemeral/cleaned/gitignored). On any machine
that has not run the suite since the shards were last cleared — or in a repo
whose suite was run before the coverage feature was enabled — the check
hard-fails with "no coverage data" even though nothing is wrong with the
project. The verdict depends on local test-run history, not on the repo's
state: the same machine-dependent-verdict disease the check ecosystem
otherwise eliminates.

## Solutions

1. **Skip-with-reason when shards are absent but a manifest exists** — weakest;
   reintroduces a silent-ish skip.
2. **Derive the verdict from the committed manifest alone** (staleness vs the
   current command surface), treating shards as an optional freshness input —
   the check then answers "does every command have a covering test recorded"
   from committed state, deterministic on every machine.
3. **Auto-run or require the suite as a dependency of the check** (like
   test-suite dependencies) so shards always exist when the check runs —
   correct but couples check runtime to full-suite runtime.

Option 2 looks most aligned with deterministic-verdict principles; needs a
design pass on what the manifest must additionally record.

## Affected

- The provider-shipped cli-test-coverage check (both languages)
- Shard lifecycle / manifest schema

## Effort

Small-medium once the manifest-only verdict is designed; the check edit itself
is small.
