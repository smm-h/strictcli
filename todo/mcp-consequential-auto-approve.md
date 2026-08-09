# MCP silently auto-approves every consequential command

**Status: decision NOT made.** This file records a finding and one suggested
direction. The suggestion has not been chosen and should not be treated as
settled. A future session should decide deliberately.

## The finding

The confirmation for `consequential=True` commands is enforced in exactly one
place — the terminal entry point. Every other caller bypasses it entirely.

- Python: `App._confirm_consequential` (`python/strictcli/__init__.py:5791`) is
  called from one site, `App.run()` (`:7257`). The non-terminal refusal lives at
  `:5809-5811` (`if not sys.stdin.isatty()` → print → `sys.exit(1)`), message
  text at `:710`.
- Go: `confirmConsequential` (`go/strictcli/effects.go:1202`), called from
  `go/strictcli/strictcli.go:2175` and `:2185`.
- TypeScript: `typescript/src/confirm.ts`.

MCP is already a non-terminal caller, and it takes a different path:
`--mcp` → `serve_mcp` (`:7712`) → `_run_mcp_server` (`:10403`) →
`_mcp_handle_tools_call` (`:10345`) → `app.call` (`:7548`) → `App._invoke`
(`:7388`).

Three consequences, all verified by reading the code:

1. `_mcp_collect_commands` (`:10269`) filters on `cmd.hidden` and
   `cmd.interactive` only. **`consequential` is not a filter**, so every
   consequential command is exported as an MCP tool.
2. `_invoke` never calls `_confirm_consequential`. It constructs `Context(...)`
   at `:7536` with no `approve_consequential` and no `dry_run`, taking the class
   defaults (`approve_consequential: bool = False`, `:252`).
3. `_build_json_schema` (`:7738`) — the `inputSchema` MCP publishes — emits
   flags and args only. It carries **no `effect` field and no `consequential`
   field**. Those exist solely in `_serialize_command` (`:9931`), which feeds
   `--dump-schema`. An MCP client is never told which tools are consequential.

The docstrings across all three implementations are explicit and identical
("Never fires on the programmatic paths (test/call/_invoke/MCP), which have no
TTY contract and would hang"), so this is deliberate rather than an oversight.
The stated reason is hang-avoidance.

## Why it is a problem

The same condition — no terminal — produces `exit 1` on one path and `proceed`
on the other. The declaration therefore means something different depending on
which caller reaches the command, and nothing announces the difference.

A second consequence: **the consent decision leaves no trace.** On the terminal
path a human typing `y` leaves `ctx.approve_consequential` False; under MCP it is
also False. A handler cannot distinguish the two, and neither can an audit
record. Any design that wants the decision to be inspectable needs a new field
on `Context`.

## Suggested direction (a suggestion, not a decision)

Require explicit consent on programmatic calls, and record how it was obtained:

- Add `effect` and `consequential` to `_build_json_schema` so every non-CLI
  projection can see the classification, not just `--dump-schema`.
- Add an explicit consent argument to the programmatic call path that
  hard-errors when the target command is consequential and no consent was
  supplied.
- Record the consent source on `Context` so a handler or an audit trail can
  distinguish a human answering a prompt from a caller declaring approval.

Nothing then proceeds silently, and existing agent workflows keep working once
they declare intent. The honest limitation: a caller can always supply consent,
so this makes the bypass explicit rather than impossible.

## Other options considered, none chosen

| Option | Effect |
|---|---|
| Refuse consequential commands over MCP entirely | Doctrinally cleanest — consequential means interrupt a human, and MCP has none. Breaks every agent workflow that currently invokes one, with no path back short of a terminal. |
| Filter consequential commands out of the tool list | Consistent with how `hidden` and `interactive` already work; an agent cannot invoke what it cannot see. Same workflow breakage, and it hides the capability rather than declining it. |
| Keep auto-approving, document it as terminal-only | Nothing breaks and the behaviour stops being surprising. Concedes that the declaration means nothing outside one caller. |

Two questions worth settling alongside whichever option is chosen:

- **Is `consequential` a property of the command, or of the (command, channel)
  pair?** It is command-only today. A channel-aware declaration is a coherent
  alternative with a very different downstream shape.
- **Should `effect` / `consequential` appear in `_build_json_schema` at all?**
  That schema is consumed by LLM tool-callers, so adding fields changes what
  models see and may change how they behave. Adding them only to
  `_serialize_command` is the conservative read.

## Affected files

- `python/strictcli/__init__.py` — `_confirm_consequential` (:5791),
  `_invoke` (:7388), `call` (:7548), `_build_json_schema` (:7738),
  `_mcp_collect_commands` (:10269), `_mcp_handle_tools_call` (:10345),
  `Context` (:252)
- `go/strictcli/effects.go`, `go/strictcli/strictcli.go` — equivalents
- `typescript/src/confirm.ts` and its invoke path
- `conformance/cases/effects_consequential.json` — existing coverage of the
  terminal path; a decision here needs new cases for the programmatic path

## Effort

Small for the suggested direction: three parallel changes plus conformance
cases in the existing argv-in/exit-code-out format. Larger if the
command-versus-channel question is opened, since that changes the registration
surface in all three implementations.
