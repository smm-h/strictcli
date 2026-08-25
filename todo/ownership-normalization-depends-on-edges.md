# Ownership normalization: declared edges replace watch globs

## Background

rlsbl is adopting single-owner workspace attribution: every file has exactly
one owning member (most specific path wins; a mandatory root member owns the
remainder), the `watch` key is removed, and CI triggering derives from
declared `depends_on` edges (all dependency scopes trigger) plus built-in
rules — notably, a change to the CI router or workflows re-runs everything,
and workspace-root manifest changes trigger all members.

This workspace uses `watch` in two ways: the language members watch the
workflows directory (so a workflow edit re-runs everything — now a built-in
rule), and the conformance member watches all three implementation
directories (it validates them against each other, and already carries an
editable path dependency on the Python implementation).

## What to consider doing

- Have the conformance member declare `depends_on` on all three
  implementation members. This makes the real coupling graph-visible and
  drives its CI triggering under the new model.
- Delete the watch entries once the rlsbl model ships; the workflows
  triggering is covered by the built-in rule.
- Add the root member the new model requires (dev node — there is no root
  project); it owns the residual root files.

## Why

Under single-owner attribution the cross-territory watch globs are removed;
without declared edges the conformance suite would only run when its own
directory changed — never on the implementation changes it exists to check.
