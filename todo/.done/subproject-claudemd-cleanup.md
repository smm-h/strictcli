# Sub-project CLAUDE.md cleanup (split from reconciliation-residuals.md, 2026-07-18)

The parent todo's 10 items were addressed across the v0.29.0 + v0.23.0 coordinated
breaking release (2026-07-17/18); this is the remaining documentation piece.

`python/CLAUDE.md`, `go/CLAUDE.md`, and `conformance/CLAUDE.md` have stale content:
- `rlsbl release [patch|minor|major]` syntax (should be `rlsbl release run`)
- Manual CHANGELOG.md editing instructions (CHANGELOG.md is generated from JSONL)
- `conformance/CLAUDE.md` contains a literal `{{publishSetup}}` placeholder and a
  release-workflow section contradicting its dev_node status

## Effort

Small — under an hour.
