# `Group.command` cannot declare `dry_run_supported=False`

## Context

`App.command` accepts `dry_run_supported: bool = True` and
`dry_run_unsupported_reason: str | None = None`, which is how a command that
cannot honestly preview refuses `--dry-run` at parse time with a stated reason
instead of rendering a preview that would lie.

`Group.command` does not accept either parameter. Its signature is otherwise
the same set (`effect`, `consequential`, `args`, `flag_sets`, `mutex`,
`dependencies`, `passthrough`, `grants`, `forwarding`, `tags`, `hidden`,
`interactive`, `config_fields`) minus those two.

## Problem

Passing `dry_run_supported=False` to a grouped command raises

```
TypeError: Group.command() got an unexpected keyword argument 'dry_run_supported'
```

A CLI that organizes its commands into groups therefore cannot make the
declaration at all for any of them. The commands that most need it tend to be
the grouped ones: multi-step pipelines whose later steps read state that
earlier steps write (build output, a regenerated index, a tree assembled from
several earlier writes). Recording those writes rather than performing them
produces a preview of a state that never existed.

The workaround available today is to say nothing and let the run stop at the
first recorded effect, which truncates the preview instead of refusing it.
That is strictly worse than the honest refusal the parameters exist to
express: the user gets a partial preview and no reason.

## Solutions

- (a) Add both parameters to `Group.command` and forward them to the same
  registration path `App.command` uses, including the three registration
  guardrails (illegal on `read_only`, illegal without a non-empty reason, a
  reason without the flag is illegal too). Pros: closes the gap where it is;
  no new concepts. Cons: none identified -- the parameters already exist one
  level up.
- (b) Have groups inherit a group-level default that individual commands can
  override. Pros: a group of pipeline commands declares once. Cons: a
  per-command reason is the useful part, and a group-level default would tempt
  a blanket reason that fits none of the members.
- (c) Document the gap and leave grouped commands unable to declare it.
  Weakest: it makes the honest refusal unavailable to exactly the commands
  that need it, and the truncated-preview behavior is silently different from
  the documented one.

(a) is the correct fix.

## Affected

The group registration path and whatever shares the command-registration
guardrails with it; the schema dump, if it records the two fields per command;
tests covering the registration guardrails for grouped commands.

## Effort

Small.
