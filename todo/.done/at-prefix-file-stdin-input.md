# @file and @- prefix for string flag values

## Problem

String flag values that contain shell-special characters (backticks, $, !, etc.) require careful quoting. This is error-prone — e.g., `--description "emit \`name\`"` where forgetting the backslashes silently corrupts the value via command substitution. Every strictcli-based tool inherits this problem.

## Proposal

In the flag value resolver, before assigning a string flag's value, check for the `@` prefix:

- `--flag @path/to/file` — read the file contents and use as the flag value (trailing newline stripped)
- `--flag @-` — read stdin and use as the flag value (trailing newline stripped)
- `--flag @@literal` — escape: strip the leading `@`, use `@literal` as the literal value

This applies to all string-typed flags automatically. No per-flag opt-in needed.

## Behavior

- `@` prefix is only recognized on string flags. Numeric, boolean, and enum flags are unaffected.
- `@-` (stdin) can only be used by one flag per invocation. If two flags both try `@-`, the second gets empty input. Emit a warning or error.
- File-not-found on `@path` is a hard error with a clear message.
- The `@@` escape handles the rare case where a real value starts with `@`.

## Examples

```bash
# Read description from file (avoids shell escaping entirely)
rlsbl changelog add --description @/tmp/desc.md --type feature --commits abc123

# Pipe from stdin
echo '**Fix.** Emit `schema.enum_name` correctly.' | rlsbl changelog add --description @- --type fix --commits abc123

# Literal value starting with @
tool --email @@user@example.com
```

## Scope

Both Python and Go strictcli implementations. The resolution happens in the flag value parser, before the handler receives kwargs.

## Effort

Small. ~20 lines in each implementation's flag resolver.
