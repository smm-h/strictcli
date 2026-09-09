# Repo-local command declarations (opt-in) and a session-environment value for handlers

## Context

A consumer CLI built on strictcli was surveyed for every place where its
behavior differs between a headed run (a human at a controlling terminal) and
a headless one (print mode, piped stdin, a script, an agent, no terminal). The
survey produced a table of roughly thirty rows for two dozen commands and
pre-launch steps, and found that the table had to be maintained by hand: no
part of a command's definition records how the command treats the absence of
a human, so the documentation drifts from the code the moment either changes.

The survey also found that the consumer decides "is a human present" three
different ways in one process: the framework's consequential confirmation
tests whether stdin is a TTY, one of the consumer's own prompts tests stdin
too, and the consumer's launch path opens the controlling terminal directly.
A run with piped stdin at a real terminal is therefore interactive for one
surface and refused by another.

The consumer wants two things from strictcli, and neither is specific to the
headed-versus-headless question. That question is only the first declaration
the consumer would attach.

## Problem

### 1. A consumer cannot attach a required declaration to its own commands

`App.command` and `Group.command` take a closed set of keyword arguments in
every port. A consumer that wants every one of its commands to carry an
extra, repo-specific declaration (for example a sentence stating what the
command does when there is no human) has no door for it. A local wrapper
function around `App.command` gets the declaration required by the language,
but nothing stops a direct `App.command` call that bypasses the wrapper, so the
guarantee is a sweep test the consumer has to write, not a property of
registration.

The value of such a declaration is not that it is machine-interpreted. It is
that it sits in the same registration block as the handler, the help and the
effect: an agent that edits the body has to read that block first, sees the
declaration beside it, and is led to keep it truthful. A declaration that lives
anywhere else does not get that read.

### 2. Handlers have no framework-provided answer to "is a human present"

The dispatch context already hands every handler the dry-run decision. It
hands them nothing about interactivity, so each consumer computes it with its
own predicate, and the framework's confirmation computes it with yet another.

### 3. The framework's confirmation ties presence to stdin

The confirmation for a consequential command both decides presence from
`stdin.isatty()` and reads the answer from stdin. On POSIX the honest test for
"can this process prompt a human" is whether the controlling terminal
(`/dev/tty`) can be opened, independent of how stdin and stdout are wired;
the consumer's own prompting surfaces already work that way. Moving only the
check would be wrong: if presence were decided from the controlling terminal
but the answer still read from a piped stdin, the pipe's contents would be
consumed as the answer. Check and read have to move together onto the same
channel. Windows has no `/dev/tty`; its equivalent is opening `CONIN$`, with
the console API as the fallback, and the confirmation already handles a
Windows console's CRLF line endings, so a Windows branch is required.

## Solution

### A. Opt-in repo-local declarations, declared once on the App

The app constructor gains a required, explicit argument naming the local
declaration type, with a written-out "none" for projects that do not opt in.
The absence of the argument is refused, so the choice is visible in every
consumer rather than implied by omission.

- Python: `App(..., local_declarations=LocalDecl)` where `LocalDecl` is a
  dataclass the consumer defines with its required fields; `local_declarations=None`
  is the explicit unwrapped form. When a type is declared, every `App.command`
  and `Group.command` call must pass `local=LocalDecl(...)`; a registration
  without it is refused at registration (import time). The dataclass gives
  required-field enforcement at the call site.
- TypeScript: `App<Local = never>`. An app constructed with a type argument
  makes `command(def)` demand `def.local: Local`, checked by tsc; an app
  without one has no such key. The unwrapped form is spelled out in the
  constructor options rather than left to the default type argument.
- Go: `App[L any]` with `Command(name, help string, local L, handler, opts...)`.
  The unwrapped form is a named marker type (for example `NoLocal`) so the
  choice is written at the construction site; a wrapped app names its struct
  type and the compiler requires the argument. Field completeness is a
  `Validate()` run at registration that fails startup; Go cannot check it at
  compile time and the docs must say so.

Both public doors (app and group) funnel through the one internal builder, so
no registration path exists that skips the local declaration. The framework
never interprets the declaration's contents.

### B. A dump of local declarations, for documentation

The schema dump each port already writes gains an opaque per-command
`local` map carrying the consumer's declaration values verbatim, present only
for wrapped apps. This is the channel through which the values reach a
documentation generator that cannot import the consumer's code (any generator
for a Go or TypeScript consumer; the Python one could import live, but one
shape across three languages is the point). Consumers render whatever table
they want from it with their own docs directives; a freshness test on the
dump already exists in the consumer pattern.

### C. A session-environment value on the dispatch context

The context gains an enum with two values, headed and headless, computed once
per process by a single predicate: a controlling terminal can be opened and
the invocation is not print mode. Handlers may read it and branch, or ignore
it. The same predicate is what the consequential confirmation uses (see D), so
the framework and every consumer answer the presence question identically.
Dry-run stays its own existing axis on the context and is not folded in.

### D. The confirmation moves onto the controlling terminal

The consequential confirmation decides presence with the predicate from C and
prints the prompt and reads the answer through the controlling terminal, not
stdin, on POSIX; on Windows through `CONIN$` with the console API fallback.
The refusal wording is unchanged and still does not name the flag that lifts
the requirement (contract 8.3).

### E. A consistency check, shipped once

A check registered through the framework's check-provider mechanism, so
consumers run it via `rlsbl check` without rewriting it: for a wrapped app,
a reserved sentinel value in a declaration field (for example the literal
`same` in a field whose convention is "describe the headless divergence") is
legal only when the handler body never reads the environment value, and a
body that reads it must carry a non-sentinel value. The check is an AST
sweep over the direct handler body in each language; it cannot see reads that
happen inside helpers the handler calls, and the docs must say so. The
stronger form, recording whether the value was read during a dispatch and
asserting agreement in a conformance run, is a consumer-side test the
framework can make possible by exposing the read on the context.

### F. Conformance fixtures, all three ports

- An app constructed without the explicit local-declarations argument fails to build.
- A wrapped app with a registration lacking the local declaration fails before dispatch.
- A wrapped app with a declaration missing a required field fails before dispatch (compile time in TypeScript, import time in Python, startup in Go).
- An unwrapped app registers exactly as today.
- The schema dump carries the `local` map for a wrapped app and omits it for an unwrapped one.
- The environment value is headed with a controlling terminal and headless under print mode or with no terminal, in every port.
- The confirmation accepts a `y` typed at the controlling terminal while stdin is a pipe, and refuses with the unchanged wording when there is no terminal.

### G. What belongs to rlsbl, not here

Two pieces are named so the boundary is clear, but they are rlsbl work:

- The strictcli scaffold for a new project opts it in from day one with an
  empty local declaration type, so the door exists before there is a field to
  put in it.
- A project check that reports strictcli-based projects that are unwrapped,
  and one that reports a strictcli-based project importing another CLI
  framework, since strictcli cannot see commands that never touch it.

## Pros and cons

Opt-in with an explicit constructor argument, versus a mandatory field on
every command:

- Pro: additive for existing consumers except for one constructor line, so
  the release is the smallest possible breaking release rather than a
  fleet-wide sweep of every command.
- Pro: the framework stays generic; it never learns what any consumer's
  declaration means.
- Pro: the choice is written in every consumer, so no project is unwrapped by
  omission.
- Con: no fleet-wide guarantee that projects opt in; the scaffold default and
  the rlsbl check (section G) are the only pushes.
- Con: three enforcement strengths across the ports (compile time, import
  time, startup), which the docs must state plainly instead of claiming one.

Moving the confirmation onto the controlling terminal:

- Pro: one predicate for presence everywhere in the process; a piped-stdin
  run at a real terminal is treated consistently.
- Con: behavior change for any script that piped `y` into a consequential
  command instead of passing the consent flag; that was never a supported
  path, and the flag is the documented one, but the changelog entry must be
  marked breaking.
- Con: a Windows branch to write and test.

## Affected files

- `python/strictcli/__init__.py`: `App.__init__`, `App.command`, `Group.command`,
  the internal command builder and the `Command` dataclass, the dispatch
  context, the confirmation (`_msg_confirm_non_interactive` and the prompt
  and read around it), the schema dump, the check-provider registration.
- `go/strictcli/strictcli.go`: `New`, `App.Command`, `Group.Command`, the
  `Command` struct, `Context`, the confirmation, the schema dump.
- `typescript/src/app.ts`, `typescript/src/context.ts`, `typescript/src/confirm.ts`,
  `typescript/src/describe.ts`: the same surfaces.
- `conformance/`: the fixtures in section F, the API-surface and schema-parity
  checks that must learn the new fields.
- `docs/`: the effects and confirmation pages, a new page for local
  declarations and the environment value, and the per-port pages stating each
  port's enforcement strength.

## Effort

Large. Three ports, one breaking constructor argument, a behavior change to
the confirmation with a Windows branch, a new context value, a schema-dump
extension, a new check, and seven conformance fixtures times three. The
constructor change and the context value are mechanical; the confirmation
move and the Go generics are the parts that need design care.
