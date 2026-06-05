# Config specialized subcommands for ordered-set and list operations

## Context

Config arrays are now supported (repeatable flags read/write arrays in config files). `config set` does full replacement with comma-separated values. But fine-grained manipulation (add one element, remove one element, insert at position) requires specialized subcommands.

The `unique` flag option splits repeatable flags into two data structures:
- **Ordered set** (`unique=True`): uniqueness enforced, insertion order preserved
- **List** (`unique=False`): duplicates allowed, order matters

Each data structure gets its own set of subcommands. Using the wrong verb on the wrong data structure is a hard runtime error.

## Subcommands

### Ordered-set operations (`unique=True` flags only)

- `config add key value` -- add to ordered set; error if value already exists
- `config remove key value` -- remove from ordered set; error if value not present

### List operations (`unique=False` flags only)

- `config append key value` -- add to end of list
- `config prepend key value` -- add to beginning of list
- `config insert key index value` -- insert at position (zero-indexed)
- `config remove-first key value` -- remove first occurrence; error if not found
- `config remove-last key value` -- remove last occurrence; error if not found
- `config remove-all key value` -- remove all occurrences; error if not found
- `config get-count key value` -- print count of occurrences to stdout
- `config get-first key` -- print first element to stdout; error if empty
- `config get-last key` -- print last element to stdout; error if empty

## Design decisions (already made)

- All 13 subcommands (2 set + 11 list) are always registered, even if the app has no flags of the matching type. Using the wrong verb produces a runtime error, not a missing-command error.
- `config add` on a list flag (`unique=False`): hard error -- "config add is for unique flags, use config append"
- `config append` on an ordered-set flag (`unique=True`): hard error -- "config append is for non-unique flags, use config add"
- `config remove` on a list flag: hard error -- "config remove is for unique flags, use config remove-first, config remove-last, or config remove-all"
- `config remove-first`/`remove-last`/`remove-all` on an ordered-set flag: hard error -- "use config remove for unique flags"
- `config remove` on a value not in the set: hard error
- `config remove-first`/`remove-last` on a value not in the list: hard error
- `config remove-all` on a value not in the list: hard error
- `config add` with a value already in the set: hard error (duplicate)

## Implementation notes

- Both Python and Go must implement all subcommands with identical behavior and error messages
- Conformance tests needed for each subcommand
- Each subcommand writes the modified array back to config (JSON or TOML)
- Value coercion uses the same per-element type coercion as `config set`
- `config get-count`, `config get-first`, `config get-last` are read operations that reload config from disk
- `config insert` validates the index is within bounds (0 to len inclusive); error on out-of-bounds

## Effort

Medium-large. 13 subcommands across 2 implementations + conformance. Most share patterns (read config, validate key, validate data structure type, mutate array, write back). A helper function for the read-validate-write cycle would reduce duplication.
