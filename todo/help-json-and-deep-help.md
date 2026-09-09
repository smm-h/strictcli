# help: --json is silently ignored, and help cannot traverse the command tree

## Context

Two related gaps in the help surface, both observed driving a large
strictcli-based application from the terminal.

## Problem 1: `--help --json` silently ignores the machine-mode flag

`<app> <group> --help --json` renders ordinary human help. `--json` is
framework-owned machine mode (contract section 19.1), defined over a
command's payload emission — and help short-circuits before any payload
exists, so the flag is never honored and never refused. That is the exact
silently-ignored-intention pattern the framework's own philosophy bans:
the invocation stated machine mode and got neither machine output nor an
error. The machine-readable surface exists (`--dump-schema`), but nothing
tells the caller that, and `--help --json` looks like it should work.

Fix shapes (either satisfies the contract; the first is more useful):

1. **Make help a payload in machine mode**: `--help --json` emits the
   per-command/per-group slice of what `--dump-schema` already produces,
   through the same renderer so the two can never drift. Agents get
   per-command schema without dumping the whole application.
2. **Refuse the combination by name**: "help has no machine form; use
   --dump-schema" — help stays human-only, but the ignore becomes an
   explicit refusal.

## Problem 2: no nested/deep help — the command tree is invisible

`<app> --help` lists top-level commands and groups, but a group's entry
shows only the group name and description — not the commands inside it.
There is no way to see the whole command tree at a glance, and no way to
traverse it without invoking `--help` once per group by hand. For an
application with many groups this makes discovery a manual walk, and the
only full-tree view is `--dump-schema`, which is a machine document, not
a readable overview.

Proposed:

- **Nested group rendering**: a group's entry in help output includes an
  indented one-line-per-subcommand listing (name + short description), at
  least one level deep, so `<app> --help` answers "what can this app do"
  instead of "what are the top-level names".
- **A full-tree mode**: an explicit way to render the entire command tree
  recursively with one invocation (a dedicated flag on help or a
  framework-owned command — naming to be decided at implementation per
  the plain-naming rule). Depth-limited output or pagination may be
  needed for very large applications.
- Combined with fix 1 above, the same traversal should exist in machine
  mode, so an agent can request the full tree or any subtree as one
  structured document scoped smaller than the whole `--dump-schema`.

## Affected area

The help renderer and its routing (where `--help` short-circuits), the
machine-mode emission seam (contract sections 19.4/19.5), and the schema
renderer shared with `--dump-schema`. Conformance suite entries for both
behaviors across language ports, if the help contract is part of the
cross-port conformance surface.

## Effort

Problem 1 fix shape 1: small-to-medium (routing help through the schema
renderer under machine mode). Problem 2: medium (renderer work plus the
depth/tree-mode surface decisions and their registration-time rules).
