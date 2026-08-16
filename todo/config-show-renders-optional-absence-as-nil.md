# `config show` renders an optional flag's absence as `<nil>`

## Context

The presence round made `optional` a first-class declaration: a flag that
declares it and receives nothing delivers absence (`nil` in Go), carries source
`default`, and reports `provided() == false`. Every surface that publishes a
flag's state was updated for this -- help renders `[optional]`, the schema
carries `"presence": "optional"`, the MCP projection reads the declared field.

The framework's own built-in `config show` command was not.

## Problem

`config show` prints one line per config-visible flag as
`<name> = <value>  (source: <src>)`. The value goes through Go's default
formatting, so a flag that declares `Optional()` and received nothing prints the
formatting of a nil interface:

```
store_dir = /mnt/x  (source: config)  -- where the tool keeps its data...
index_path = RelativeToRoot('TOOL_ROOT', 'db', 'index.db')  (source: default)
exclude_patterns = ["(?i)token", "(?i)secret", ...]  (source: default)
recursive = <nil>  (source: default)
ignore_missing = <nil>  (source: default)
interactive = <nil>  (source: default)
reason = <nil>  (source: default)
command = <nil>  (source: default)
```

`<nil>` is Go's internal spelling for an empty interface value. It is not a
value anyone could type back, it is not the framework's own vocabulary for
absence anywhere else, and it appears on a page an operator reads to find out
what their configuration currently is.

This is a **new** output shape, produced by the migration rather than by any
declaration change the operator made. Before the presence round these same flags
carried `Default(false)` / `Default("")` and printed `false` / an empty string.
The mutating-default ban then forbade those defaults outright on any flag of a
`mutating` command, so every such flag in every consuming CLI moved to
`Optional()` -- which means this is not one project's cosmetic problem. Any tool
whose mutating commands' flags are config-visible gets a `config show` page full
of `<nil>`, and every one of them got it in the same release.

The same question exists for the other three implementations: whatever Python
prints for `None` and TypeScript for `undefined` in their `config show`
equivalents is the same missing decision, and the three should agree.

## What to decide

The framework already has a rendering vocabulary for this state on the help
surface -- `[optional]` -- and a source label for it, `default`, which §23.6
pins as "the declaration decided". `config show` needs the same treatment
decided once and spelled identically in all three languages. Candidates, none of
them adopted here:

- print nothing after the `=` and let the source label carry it;
- print a word from a closed vocabulary (`(unset)`, `(absent)`, `(not set)`);
- omit the line entirely for a flag that declares `optional` and received
  nothing, on the grounds that `config show` is a report of configuration and an
  absent optional is not configured.

The third changes what the page enumerates, so it is a real design question
rather than a formatting one -- a reader who wants to know which keys are
settable would lose them from the listing.

Whichever is chosen, the same rule should reach the source column: a flag that
declares `optional` and received nothing reports source `default` today, which
reads as "a default supplied this" for a declaration that has no default value.

## Related, smaller

`config set`'s reshaped member-spelled selector carries three flags whose help
text is below the length the docs generator's own `CLI002` check wants:

```
warning: [CLI002] flag '--value' help text too short (24 chars, minimum 50)
warning: [CLI002] flag '--clear' help text too short (23 chars, minimum 50)
warning: [CLI002] flag '--default' help text too short (37 chars, minimum 50)
```

Every consuming project's docs build emits these three warnings for a command
none of them declared. The help texts are pinned verbatim in the contract, so
lengthening them is an amendment rather than an edit.

## Affected

The framework's built-in `config show` implementation in all three languages,
plus whatever conformance case covers its output.

## Effort

Small once the vocabulary is decided: one formatting site per language, plus a
conformance case asserting the chosen spelling. The decision is the work.
