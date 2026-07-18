# Handler redesign — remaining items

Items from the original handler-redesign-0.9.md that have not been implemented. The programmatic invocation work (app.call, InvokeError, structured returns, tool export, MCP) is done and tracked in todo/.done/handler-programmatic-invocation.md.

## 1. Output wrapper

Stateful wrapper injected as the handler's first argument for structured diagnostic output. Methods: info() (stdout, silenced by --quiet), debug() (stderr, only with --verbose), warn() (stderr, always), error() (stderr, always). Created per-invocation by the framework.

Changes handler signatures in both languages to accept an `out` parameter as the first positional argument.

Original plan: handler-redesign-0.9.md item 3, phased plan phase 2.1.

## 2. Framework-owned global flags (--quiet, --verbose, --output)

Three built-in global flags managed by the framework:
- `--quiet`: suppresses info-level output and subprocess stdout
- `--verbose`: enables debug-level output
- `--output`: selects output formatter (text/json/custom)

`--quiet` and `--verbose` are mutually exclusive. Requires framework-owned global flag infrastructure (separate from user-declared global flags, with collision detection).

Also includes pluggable formatter registry: `app.register_formatter(name, fn)` for custom output formats beyond text/json.

Original plan: handler-redesign-0.9.md items 3 and 5, phased plan phases 0.2, 2.2, 2.3.

## 3. Subprocess control

Framework-provided subprocess runner via `out.run(args)` / `out.Run(args...)` that injects the framework's stdout/stderr wrappers into child processes. Respects --quiet (suppresses subprocess stdout). Returns result with returncode, stdout, stderr.

Includes AST enforcement as a built-in strictcli check: statically analyzes handler source for direct subprocess usage (subprocess.run, os.system, os/exec.Command, etc.) and reports violations. Requires built-in check infrastructure extension.

Original plan: handler-redesign-0.9.md item 4, phased plan phases 3.1, 3.2.

## 4. Env var injection

Standalone env var declarations not tied to flags. Handlers declare env var needs via `@env("API_KEY", help=...)` (Python) / `EnvVar("API_KEY", "...", Required())` (Go). Framework reads from environment and injects into handler kwargs alongside parsed flags/args. Missing required env vars produce parse errors.

Distinct from the existing per-flag `env="VAR_NAME"` mechanism — this is for env vars that don't correspond to any flag (API keys, tokens, etc.).

Original plan: handler-redesign-0.9.md item 8, phased plan phase 4.1.

## 5. Pure parse mode

`app.parse(argv)` returning a ParseResult without executing the handler. ParseResult contains: command (str), kwargs (dict), errors (list), help_text (str or None), version_text (str or None).

Use cases: validation-only mode, introspection, building higher-level abstractions on top of strictcli.

Original plan: handler-redesign-0.9.md item 7, phased plan phase 1.1.

## 6. Typed handler inputs

**Python:** Extend `_build_and_validate_command()` to validate handler type hints against declared flag types at registration time. str flag must match str hint, bool flag must match bool hint, etc. Opt-in: handlers without type hints skip validation.

**Go:** Generic accessor `Get[T](kwargs, key)` replacing verbose `kwargs["key"].(string)` patterns.

Original plan: handler-redesign-0.9.md item 6, phased plan phases 1.2, 1.3.

## 7. run() returning exit code

`run()` / `Run()` returns int instead of calling `sys.exit()` / `os.Exit()`. Callers wrap with `sys.exit(app.run())` / `os.Exit(app.Run())`. Affects all consumer projects (~10 projects, ~97 handlers).

Original plan: handler-redesign-0.9.md item 1, phased plan phase 2.1.

## Dependencies

Items 1, 2, 3 form a chain: output wrapper enables framework flags which enable subprocess control. Items 4, 5, 6, 7 are independent of each other and of the chain.

## Not included (from original plan)

- **Pluggable config source** (item 9): config loader swappable between filesystem/in-memory/HTTP. Low priority, not tracked here.
- **Consumer migration** (item 11): each consumer project gets its own migration todo when this work ships.
- **Conformance suite updates** (item 10): will be done alongside each item above, not tracked separately.
