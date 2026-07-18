# Reconciliation residuals (successor to python-go-reconciliation.md)

The parent todo's 10 items were addressed across the v0.29.0 + v0.23.0 coordinated
breaking release (2026-07-17/18). Items 1-4 shipped in full (float canon, handler
contract, version required, tomlkit config writes). Items 5-9 shipped substantially
(errors.go centralized, describe_go dumper built, 7/7 divergences fixed, parity
checker N-way + multiset, schema-parity wired). Item 10 partially done (root
CLAUDE.md updated).

Two small residuals remain:

## 1. Delete old Go regex parsing in check_api_surface.py

The `describe_go` AST dumper is built and wired into the api-surface checker, but
the old regex-based Go source parsing functions (`get_go_source`, `get_go_fields`,
`_go_struct_has_field`) were not deleted — the checker still has both paths.
Delete the dead regex functions and verify the checker still exits 0 consuming
only the dumper output.

## 2. Sub-project CLAUDE.md cleanup

`python/CLAUDE.md`, `go/CLAUDE.md`, and `conformance/CLAUDE.md` have stale content:
- `rlsbl release [patch|minor|major]` syntax (should be `rlsbl release run`)
- Manual CHANGELOG.md editing instructions (CHANGELOG.md is generated from JSONL)
- `conformance/CLAUDE.md` contains a literal `{{publishSetup}}` placeholder and a
  release-workflow section contradicting its dev_node status

## Effort

Small — an hour total for both items.
