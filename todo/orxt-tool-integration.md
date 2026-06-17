# strictcli → orxt tool integration

## Problem

Every strictcli CLI command could automatically become an orxt tool, making it callable by AI agents without any additional wiring. Currently, strictcli defines commands with typed parameters, help text, and handlers — all the metadata orxt's tool registry needs. But there's no bridge between the two.

## Desired behavior

A strictcli-based CLI should be able to expose all its commands as orxt tools with zero additional code. The tool name, description, parameter schema, and handler are all derivable from the strictcli command definition.

## Context

veliu-dev (the internal company tool being built on orxt) has ~11 integration packages that are strictcli-based libraries. If strictcli commands automatically become orxt tools, every integration's CLI surface is also the AI's tool surface — one definition, two interfaces.

## Approach

Design TBD. Some directions:

- A `register_as_tools(registry: ToolRegistry)` function that walks a strictcli app's command tree and creates orxt Tool objects
- An orxt-aware mode where strictcli commands can be invoked programmatically (not just via subprocess/CLI)
- A schema dump format that orxt can consume to build tools without importing the CLI

## Constraints

- strictcli has zero dependencies today (Python) and stdlib-only (Go). orxt integration should be opt-in, not a hard dependency.
- The Go implementation needs parity if this ships in Python.
