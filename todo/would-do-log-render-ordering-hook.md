# Would-do log render ordering is framework-fixed; consumers cannot compose output

## Context

Under `--dry-run`, the framework prints the recorded would-do log once, at
dispatch exit, unconditionally. A consumer whose preview output has structure —
e.g. it renders its own declared plan table for work that is not
effect-expressible, beneath an explicit boundary line — cannot place the
framework's log relative to its own sections. The log always lands LAST, below
whatever the handler printed, even when the handler's rendering is meant to
follow it.

## Problem

Observed in a real consumer: its preview renders (1) the recorded-effects
region, (2) a hard boundary line, (3) a declared table of post-boundary steps.
The framework's would-do log belongs in region (1), but prints after (3). The
consumer worked around it by rendering its own plan table for the recorded
region and adding an explanatory note about what follows — duplicating
presentation the framework owns and leaving two logs of the same effects in
different formats.

## Solutions

- (a) `ctx.effects.render_log()` / flush: an explicit call that renders the
  would-do log at the handler's chosen point and marks it consumed (dispatch
  exit then prints nothing). Opt-in; zero change for consumers that never call
  it. Cons: a handler that calls it and then records more effects needs defined
  semantics (append-only second flush, or hard error).
- (b) A declared render hook on the command/app (callback receiving the
  recorded log lines, returning the composed output). More inversion of
  control; heavier.
- (c) Structured access: expose the recorded effects to the handler
  (`ctx.effects.recorded()`), let it render everything itself, and suppress the
  framework print when accessed. Most flexible; risks divergent formatting
  across consumers — the framework's canonical rendering should stay the
  default and remain available as a helper.

(a) with the framework's canonical formatter reused is the smallest honest fix;
(c) subsumes it if structured access is wanted anyway. All three must keep the
contract's pinned log format byte-identical when the framework renders.

## Affected

All three implementations (the render site at dispatch exit; the contract's
would-do log section), conformance cases for the chosen surface, docs.

## Effort

Small-medium for (a): the flush call + consumed flag + double-flush semantics +
conformance cases ×3 languages.
