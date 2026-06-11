# Public API for running checks programmatically

## Problem

rlsbl's deprecated pre-push-check command needs to run checks in-process (not via subprocess). Currently it uses private functions: `strictcli._filter_checks`, `strictcli._resolve_check_order`, `strictcli._run_checks`, `strictcli._check_format_human`. These are undocumented and could break on any strictcli update.

## Proposed solution

Add a public method to the App class:

```python
def run_checks(
    self,
    context,
    tag_expr: str | None = None,
    name_glob: str | None = None,
    run_all: bool = False,
    ignore_warnings: bool = False,
) -> tuple[list[tuple[str, CheckResult]], int]:
```

Returns (results_list, exit_code). The results list contains (check_name, CheckResult) tuples. Exit code is 0 if all passed, 1 if any failed.

Also expose a public formatting function:

```python
def format_check_results(results, verbose=False) -> str:
```

## Consumer

rlsbl's pre-push-check deprecation shim (rlsbl/commands/pre_push_check.py) is the primary consumer.

## Effort

Small. The implementation already exists as private functions. This is just promoting them to public API with a stable signature.
