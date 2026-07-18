# Reconciliation residuals — item 1 (split from reconciliation-residuals.md, 2026-07-18)

## 1. Delete old Go regex parsing in check_api_surface.py

The `describe_go` AST dumper is built and wired into the api-surface checker, but
the old regex-based Go source parsing functions (`get_go_source`, `get_go_fields`,
`_go_struct_has_field`) were not deleted — the checker still has both paths.
Delete the dead regex functions and verify the checker still exits 0 consuming
only the dumper output.

---

Obsoletion note (2026-07-18): an independent audit of check_api_surface.py on disk
found none of these functions exist — the checker's Go arm consumes only the
describe_go JSON dump (`_get_go_api` / `get_go_fields_from_api` /
`get_go_all_fields_from_api`) and has no regex extraction path. The item described
work that was already complete when the file was written.
