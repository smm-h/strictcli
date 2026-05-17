# Optional flags with Default(nil) display as [required] in help

## Problem

When a string flag uses `Default(nil)` to make it optional (nil if not provided), the help output shows it as `[required]`. This is cosmetically wrong -- the flag is optional and nil-checked in the handler.

Example from safegit:

```
--branch <str>    commit to a different branch [required]
```

The user sees `[required]` and thinks they must provide `--branch`, but they don't.

## Expected behavior

Flags with `Default(nil)` should display as `[optional]` or show no annotation (since the flag has a default, even if that default is nil).

## Affected code

`help.go` in the flag metadata builder -- it checks whether a flag has a default and renders `[required]` when no default is set. `Default(nil)` sets `hasDefault = true` but the value is `nil`, which may be treated the same as "no default" in the display logic.

## Effort

Small. Fix the condition in help rendering to distinguish "no default" from "default is nil."
