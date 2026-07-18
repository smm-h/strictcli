# Rename Python releasable to py-strictcli (tag-prefix symmetry)

## Context

During TypeScript-implementation planning (2026-07), the tag-prefix namespace was reviewed. Today Python releases tag as `strictcli@v*`, Go as `go-strictcli@v*`, and the new TypeScript sub-project will tag as `ts-strictcli@v*`. Decision: eventually retire the bare `strictcli` tag prefix so every prefix names its language (`py-`/`go-`/`ts-strictcli`). Nothing is renamed now; this todo is the deferred rename.

Registry names are unaffected either way: npm `strictcli` (TypeScript implementation) and PyPI `strictcli` (Python implementation) keep the bare name. This rename touches only the rlsbl releasable name, the git tag prefix for future releases, and GitHub Release titles going forward. The rlsbl *project* name `strictcli` (in `[[projects]]`) also stays — it keys the PyPI package, workflow filenames, and JSONL `packages` fields.

## Problem

Renaming a releasable is currently a manual multi-step operation with two silent failure modes:

- Missing boundary alias tag: the next release finds no `py-strictcli@v*` tag but a finalized changelog for the current version, and rlsbl's destroyed-tag guard hard-errors.
- Missing publish-gate re-scaffold: the generated publish workflow's `startsWith(github.ref_name, 'strictcli@v')` conditions never match the new prefix, so releases appear to succeed while publishing nothing.

## Blocked on

rlsbl gaining a native `monorepo rename-releasable` command (todo filed in rlsbl, 2026-07). Do not perform the rename manually unless that feature is rejected there.

## Verified manual recipe (fallback only)

Verified against rlsbl source and the in-repo Go precedent (`go/v0.15.0` and `go-strictcli@v0.15.0` point at the same commit — the Go sub-project was renamed exactly this way):

1. Create boundary alias tag `py-strictcli@v<current>` at the same commit as `strictcli@v<current>`; push that one tag; create no GitHub Release for it.
2. `.rlsbl-monorepo/workspace.toml`: `[[releasables]] name = "py-strictcli"`; the python member's `releasable = "py-strictcli"`. Leave `[[projects]] name = "strictcli"` unchanged.
3. `git mv .rlsbl-monorepo/releasables/strictcli .rlsbl-monorepo/releasables/py-strictcli` (carries version, changes/, config.json, hooks/, releases/).
4. Delete the stale `.validated` cache inside the moved `changes/`.
5. Re-run monorepo sync to regenerate the publish gate (tag-prefix case + `startsWith` conditions) and `snapshot.json`.
6. Leave all existing `strictcli@v*` tags and their GitHub Releases untouched (they become unmanaged history, same as the old `go/v*` era).

Rejected alternatives: full retag of history (orphans 43 GitHub Releases into drafts, breaks external links); fresh start without alias tag (destroyed-tag guard fires and the changelog range collapses to full history — verified not viable).

## Affected files

- `.rlsbl-monorepo/workspace.toml`
- `.rlsbl-monorepo/releasables/strictcli/` (moved to `py-strictcli/`)
- `.github/workflows/publish.yml` (regenerated)
- `.rlsbl-monorepo/snapshot.json` (regenerated)
- One new git tag pushed to origin

## Effort

Trivial once the rlsbl command exists (one invocation + review). Manual fallback: one careful session with step-by-step verification.
