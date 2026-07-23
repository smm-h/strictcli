# Command capability tags (readonly, mutation, etc.)

## Problem

When strictcli commands become orxtra tools (see `orxt-tool-integration.md`), the AI agent needs to know which tools are safe to call in read-only contexts and which perform mutations. Currently, strictcli commands have no metadata about their side-effect profile.

## Desired behavior

Commands should be taggable with capability descriptors:
- `readonly` — no side effects, safe for consult/read-only sessions
- `mutation` — writes files, changes state
- `deploy` — pushes to external systems
- `destructive` — deletes, drops, irreversible
- Custom tags per application

Tags would be declared on the command definition and exposed in the schema dump, so the tool registry can filter tools by capability (e.g., "read-only agent gets only #readonly tools").

## Context

The orxtra tool module already strips mutation tools from consult sessions (`CONSULT_STRIP_TOOLS` in `_consult_tool.py`). If strictcli commands carry capability tags, this stripping can be data-driven instead of hardcoded.
