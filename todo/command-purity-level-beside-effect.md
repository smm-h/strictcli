# Publish a command's purity level beside its effect classification

## Context

A command's effect classification (`read_only`, `mutating`, `consequential`)
is published in help, in `--dump-schema` and in MCP tool descriptors, so a
caller can see before it calls whether a command changes the world. A
consumer built on top of the Go implementation carries a finer property at
compile time: whether a read-only command is additionally pure (touches no
clock, no randomness, no stdin, no file), or deterministic (no clock, no
randomness). A caller that knows a command is pure can memoize its result
keyed on its input; a test harness that knows a command is deterministic can
assert byte-identical output across runs; a `--json` consumer gets a contract
instead of a hope. The property exists in the consumer's type system, but
the framework has no field to publish it into, so the only route today is a
sentence in the command's help text, which no schema or MCP consumer can
read.

## Problem

There is no registration-time way to state a purity level on a read-only
command, and no key in the schema dump, the tool descriptor or the MCP
`tools/list` entry that carries one.

## Proposal

An optional purity level on read-only commands, closed and ordered:

| Level | Meaning |
| --- | --- |
| `deterministic` | the command's output depends only on its resolved inputs and the files and environment it declares; no clock, no randomness |
| `pure` | deterministic, and additionally no stdin and no file or environment read; the output is a function of the resolved inputs alone |

Declared through each language's own idiom (a keyword on the Python
decorator, a functional option in Go, a field on the TypeScript command
object), refused at registration on a mutating or consequential command,
published as a `purity` key beside `effect` on the command's schema entry, as
a `purity` member of the tool descriptor, and in help as one bracketed part on
the command's line. The framework verifies nothing: the level is the
declarer's claim, the way `effect` is. Conformance cases cover the schema
key, the help rendering, the registration refusal on a mutating command and
the MCP descriptor in all three implementations.

## Alternatives

- Leave it to help text. Visible to humans at once, invisible to every
  machine consumer, and it is the hand-rolled workaround the project treats
  as a framework gap.
- A free-form `properties` list. Open vocabularies do not render; the closed
  two-level form gives every surface a sentence to print.

## Affected files

- `python/strictcli/__init__.py`: registration, help rendering, schema dump,
  tool export, MCP.
- `go/strictcli/`: the command option, help.go, schema, tool.go, mcp.
- `typescript/src/`: factories, help.ts, schema.ts, tool.ts, mcp.ts.
- `conformance/cases/`: new cases for each surface; `check_api_surface.py`
  and `check_error_parity.py` entries for the registration refusal.

## Effort

Medium: one small closed enum threaded through four surfaces in three
implementations, plus conformance cases.
