# Keyword collision in `_flag_param_name`

## Problem

`_flag_param_name` does not handle Python keyword collisions. When a CLI flag name matches a Python keyword (e.g., `--global`), the generated parameter name is an invalid Python identifier.

rlsbl currently monkey-patches `_flag_param_name` to work around this by appending `_` for keywords like `global`.

## Fix

The fix is 2 lines in `_flag_param_name`:

1. Add `import keyword` at the top of the module
2. Add `if keyword.iskeyword(name): return name + "_"` to `_flag_param_name`

## Downstream impact

Once this ships in a strictcli release, the rlsbl monkey-patch can be removed.
