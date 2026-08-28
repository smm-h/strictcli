# check --list ignores --tag and --name

## Problem

The framework-generated `check` command's `--list` branch returns before
any filtering, so `check --list --tag <t>` and `check --list --name <glob>`
print the entire check registry instead of the filtered subset:

```python
if list:
    ctx.payload(_check_list_items(app_ref._check_defs))   # whole registry
    _check_list_mode(app_ref._check_defs, ctx)            # whole registry
    return 0
# has_filter / _filter_checks(...) only reached below this
```

(Python 0.41.1, `_register_check_command` ~line 9821; `_filter_checks`
~16349 already computes exactly the set the list branch needs.)

The Go port has the identical defect: `go/strictcli/check_cmd.go:53`,
`if list { return Exit(a.checkList(ctx)) }` before the
`runAll || tagExpr || nameGlob` branch. The TypeScript port likely too.

## Fix

`--list` composes with the filters: apply `_filter_checks` (and the ports'
equivalents) before rendering, in both the human table and the JSON
payload. Cross-language: Python + Go (+ TS), plus the conformance suite.
Consumers' existing `--list` tests assert the unfiltered listing and will
need extending (not replacing) once filtering works.

## Effort

Small per language; the conformance case is the real deliverable.
