# v0.20.0 Go changelog defects: wrong option name, missing feature entry

## Context

A consumer integrating against the v0.20.0 Go config features found two
defects in the go-strictcli changelog
(`.rlsbl-monorepo/releasables/go-strictcli/CHANGELOG.md`) while verifying the
release against the actual code.

## Problems

1. **Wrong API name.** The changelog names the no-default-path option
   `NoDefaultConfigPath()`, but the actual exported symbol is
   `WithNoDefaultConfigPath()` (go/strictcli/strictcli.go, ~line 338).
   Integrators copy option names from release notes; this one does not
   compile.
2. **Missing feature entry.** `WithConfigConflictMode("error")` shipped in
   v0.20.0 (go/strictcli/strictcli.go ~line 348; enforcement in parse.go
   ~501-512 and strictcli.go ~2426-2433; conformance
   `conformance/cases/config_hard_error.json`) but is absent from the
   version's Features list. It is only alluded to in the context blurb, which
   misdescribes it as being about "ambiguous flag definitions" — it is about
   config/CLI(/env) overlap being a hard error instead of silent CLI-wins.

## Proposed solution

Fix the released changelog entries with `rlsbl changelog amend` on the
0.20.0 JSONL file (correct the option name; add a feature entry for
`WithConfigConflictMode` with an accurate one-line description), then
regenerate CHANGELOG.md and re-sync the GitHub Release notes with
`rlsbl release edit 0.20.0`.

- Pros: release notes become accurate for the API most consumers will
  integrate next; cheap.
- Cons: none; amend exists exactly for this.

## Affected files

- `.rlsbl-monorepo/releasables/go-strictcli/changes/0.20.0.jsonl` (via amend)
- Generated CHANGELOG.md / GitHub Release notes (via generate + release edit)

## Effort estimate

Minutes.
