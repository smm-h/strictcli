# Optional flag values (nargs='?')

## Problem

strictcli currently requires all non-bool flags to consume exactly one token as their value. There's no way to define a flag that accepts zero or one arguments — the equivalent of argparse's `nargs='?'`.

## Use case

The real `claude --resume` accepts either:
- `--resume` (no arg) — opens a session picker
- `--resume SESSION_ID` — resumes a specific session

In strictcli, a `str` flag always consumes the next token or errors. The workaround is a separate bool flag (`--picker`) that maps to the no-argument behavior, but this is clunky and splits one concept across two flags.

## Proposed solution

Add an `optional_value` parameter to `Flag`:

```python
Flag(name="resume", type=str, short="r", optional_value=True, default=MISSING,
     help="resume a session (or open picker if no ID given)")
```

Behavior when `optional_value=True`:
- Flag not present: parameter gets `default`
- Flag present with no next token (or next token starts with `-`): parameter gets `None` (or a configurable `no_value_default`)
- Flag present with a value: parameter gets the value string

## Complexity

Medium. The parser needs to peek at the next token and decide whether it's a value or a separate flag/arg. Heuristic: if the next token starts with `-` and isn't a negative number, it's not a value.

## Consumers

claudewheel uses the `--picker` workaround today. If this feature lands, claudewheel could collapse `--picker` back into `--resume` with `optional_value=True`.
