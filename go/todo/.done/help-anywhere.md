# Recognize --help anywhere in the argument list

## Problem

`--help` is only recognized as the first argument after the command name. If it appears after other flags, it's treated as an unknown flag and causes an error.

```
$ safegit commit -m "test" --help
error: unknown flag '--help'

$ safegit commit --help
safegit commit -- stage and commit files atomically
...
```

## Expected behavior

`--help` should be recognized anywhere in the argument list, just like it is in most CLI tools. When found, all other arguments should be ignored and help should be displayed.

## Affected code

`parse.go` in `parseCommand` -- the help check happens before the parsing loop starts. Moving it to also check during the loop (or pre-scanning for `--help` before parsing) would fix this.

## Effort

Small. Pre-scan the token list for `--help`/`-h` before entering the parse loop, or check for it inside the loop alongside other flags.
