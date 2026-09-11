# An opt-in TUI layer that starts on a bare invocation

## Context

A strictcli app invoked with no command token prints its app help. One
consumer wants a bare invocation to open an interactive terminal UI instead,
and today gets there by rewriting argv before strictcli runs: it inserts its
launcher command when the first non-reserved token is not a known subcommand
or app-level flag, keeping hand-maintained lists of both to decide. That
rewrite duplicates the framework's routing and cannot appear in help, the
schema dump or the MCP export.

A declared default command was considered as the fix and rejected: one
consumer's argv rewrite is not evidence for a routing feature, and a default
command changes what a bare invocation means for every app that declares one
without giving the framework anything to render or export.

The idea recorded here is different in kind. The consumer in question has a
hand-rolled terminal UI framework of its own: an event loop with keyboard
dispatch, a terminal abstraction, a renderer, a segment bar whose segments
declare what they require, themes, a wizard flow, a scrolling viewport and a
fuzzy picker. That framework is not specific to the consumer's domain. Extracted
into strictcli as an opt-in layer, it would give every strictcli app the same
capability: declare a TUI, and a bare invocation starts it.

## Problem

Interactive terminal UIs built beside strictcli apps are outside the
framework's model. They do not appear in help or the schema dump, their
actions are not commands, their effects do not go through the effects handle,
and `--dry-run`, `--json` and consent have no meaning inside them. Each consumer
that wants one builds it from scratch, and the one that exists already carries
its own routing hack to be reachable.

## Solutions

### Option A: an opt-in TUI layer inside strictcli (the proposal)

strictcli gains a declared TUI: an app-level opt-in naming a TUI definition
built from the extracted framework. A bare invocation starts it; every other
invocation is unchanged. Inside the TUI, actions are the app's own registered
commands, invoked through the programmatic door, so the effects regime,
consent, `--dry-run` previews and machine-mode results apply to TUI actions
the same way they apply to command lines. The TUI's existence and its actions
are exported in the schema dump.

Pros: one framework for the terminal UI and the CLI, with the strictness
carried into the interactive surface. The consumer's routing hack and its
private framework are deleted. Any app can opt in.

Cons: a large extraction and a new surface in three implementations, or a
Python-only surface with an explicit parity exclusion, which the idiom rules
would have to permit. The extracted framework's terminal handling is
Unix-specific today.

### Option B: the TUI layer as a separate package depending on strictcli

The same extraction, published as its own package that consumes strictcli's
programmatic door, with strictcli adding only the hook a bare invocation needs
to start a registered TUI.

Pros: strictcli's core stays a CLI framework; the TUI package can be
Python-only without a parity argument.

Cons: the hook in strictcli is the default-command feature under another
name, unless it is restricted to a registered TUI object rather than any
command.

### Option C: do nothing

The consumer keeps its argv rewrite and its private framework.

## Affected files

- The app declaration surface and the routing entry in each implementation
  (`python/strictcli/__init__.py`, `go/strictcli/strictcli.go`,
  `typescript/src/app.ts` and `parse.ts`), for the bare-invocation hook.
- A new package or subpackage for the extracted framework.
- The schema dump, the docs, and the conformance suite for whatever the
  declaration exports.

## Effort

Large. The extraction itself is a project; the strictcli-side hook is small
once the shape of the declaration is decided. This is a design round of its
own, not part of the machine-mode and effects campaign.
