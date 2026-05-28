# Default subcommand for command groups

## Problem

strictcli command groups require an explicit subcommand. `rlsbl release` (bare, no subcommand) shows group help instead of running the most common subcommand (`release run`). This adds a typing tax on the most frequent operation.

## Proposed solution

Allow groups to designate one subcommand as the default:

```python
release_group = app.group("release", help="...", default="run")
```

When no subcommand token is found after the group name, the parser injects the default and re-parses.

## Three invariants (must be enforced at framework level)

1. **`--help` always binds to the group**, not the default subcommand. `rlsbl release --help` shows group help listing all subcommands.

2. **The default subcommand cannot accept positional arguments.** Otherwise `rlsbl release <value>` is ambiguous with `rlsbl release <subcommand>`.

3. **The group cannot define non-global flags** when a default subcommand is set. All non-global flags on a group with a default are forwarded to the default subcommand.

## Help output

The default should be annotated in help:

```
rlsbl release [subcommand]

Default: run (rlsbl release = rlsbl release run)

Subcommands:
  run     Execute the release pipeline (default)
  retry   Re-trigger CI for a completed release
  init    Scaffold release intent file
  ...
```

## Motivation

`rlsbl release run --watch --yes` is typed frequently. `rlsbl release --watch --yes` saves one word on every invocation. The group structure provides discoverability; the default provides ergonomics.

## Effort

Medium. Parser changes to detect missing subcommand and inject default. Help formatter changes for the annotation. Validation for the three invariants.
