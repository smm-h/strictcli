# Handler programmatic invocation (done)

Subset of the handler redesign (handler-redesign-0.9.md) that was implemented, though via a different design than originally specified.

## What was implemented

### app.call() / Call() — programmatic invocation

Both Python and Go support programmatic command invocation: `app.call("command", kwargs)` / `app.Call("command", kwargs)`. This bypasses CLI parsing entirely and invokes the handler directly with the provided arguments, returning a structured result.

InvokeError is raised/returned when the command doesn't exist or argument validation fails.

### Structured handler returns

Implemented differently from the todo's universal HandlerResult proposal:

- **Python:** Duck typing. Handlers can return dicts, dataclass instances, or any object. The framework captures whatever the handler returns in `Result.data`. No enforced HandlerResult type.
- **Go:** DataCommand type and HandlerResult struct. Commands that return structured data use `DataCommand` registration. The handler returns `HandlerResult` with `Data` and `ExitCode` fields.

### app.acall() — async variant (Python-only)

Async counterpart to `app.call()` for use in async contexts.

### Internal _invoke() pipeline

Shared internal execution path that both `run()`/`test()` and `call()`/`acall()` use, consolidating handler invocation logic.

### Tool export (as_tools, json_schema, Tool type)

Commands can be exported as tool definitions for LLM integration: `app.as_tools()` returns Tool objects with `json_schema` for function-calling interfaces.

### MCP projection (serve_mcp, --mcp flag)

Built on top of tool export. `app.serve_mcp()` starts an MCP server exposing commands as tools. The `--mcp` flag is auto-injected to enable this from the CLI.

## Relationship to original plan

The original plan (handler-redesign-0.9.md items 1-2, phased plan phases 0.1 and 2.1) envisioned a universal HandlerResult type that all handlers would return. What was implemented instead is a more pragmatic approach: Python uses duck typing, Go uses an opt-in DataCommand pattern. The programmatic invocation (call/Call) and tool export features were not in the original plan at all but emerged from the same motivation of treating CLI handlers as library functions.
