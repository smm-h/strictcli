# strictcli

Strict CLI framework — declare everything, infer nothing. Multiple first-class implementations kept in behavioral lockstep via a conformance test suite.

## Monorepo structure

This is an rlsbl monorepo (`.rlsbl-monorepo/workspace.toml`). Each sub-project has its own version, changelog, and release cycle.

| Directory | What | Version file | Targets | Tests |
|-----------|------|-------------|---------|-------|
| `python/` | Python implementation (PyPI) | `pyproject.toml` | pypi | `uv run pytest` in `python/` |
| `go/` | Go implementation | `VERSION` | go | `go test ./... -race` in `go/` |
| `conformance/` | Cross-language conformance suite | n/a | plain | `python conformance/run.py --target python` / `--target go` |

**Note:** `conformance/` is a `dev_node` project. It has no changelog, no user-facing changes, and does not participate in the changelog system. It is not released independently -- releases happen only as part of monorepo batch releases (`rlsbl monorepo release`) if at all.

## Building and testing

```bash
# Python
cd python && uv sync && uv run pytest

# Go
cd go && go test ./strictcli/... -race

# Conformance (requires all implementations)
cd conformance && python run.py --target python && python run.py --target go
```

## Architecture

### Python (`python/strictcli/__init__.py`)

Single-file implementation (~7,840 lines, tomlkit dependency). Key internal stages:

1. **Registration** — `@flag`/`@arg` decorators attach metadata to handlers; `@app.command()` triggers `_build_and_validate_command()` which merges tags, validates signatures, checks constraints.
2. **Global flag parsing** — `_parse_global_flags()` extracts app-level flags before and after the command token.
3. **Command routing** — first non-flag token selects the command or group.
4. **Command parsing** — `_parse_command()` resolves flags, args, env vars, defaults, mutex, choices, and custom validation.
5. **Execution** — handler called with ctx-first signature (`ctx, **kwargs`); the return value must be `int` (exit code), `None` (exit 0), or `strictcli.outcome(...)` — anything else is a hard error.

### Go (`go/strictcli/`)

Split across 20 non-test files (~11,040 lines), one dependency (go-toml-edit):

- `strictcli.go` — types, constructors (functional options pattern), registration, infra root/handshake declarations, reserved-flag pre-scan, orchestration.
- `parse.go` — two-phase flag/arg parsing, env resolution (skipped under `--hermetic`), validation.
- `routing.go` — command routing and group traversal.
- `invoke.go` — programmatic invocation (`Call`), kwarg coercion, `InvokeError`.
- `context.go` — `Context` type: structured output (Info/Warn/Debug/Error), provenance (`Source`), infra access (`InfraValue`).
- `outcome.go` — `Outcome` return type (`Exit(code)`, `ExitData(code, data)`), typed kwargs helpers `Get`/`GetOpt`.
- `errors.go` — centralized error/panic message templates for the whole package.
- `help.go` — help text formatting at app/group/command levels (including the `Infrastructure:` section).
- `config.go` — JSON/TOML config file loading, `config show/set/path/edit/init` subcommands.
- `schema.go` — `--dump-schema` implementation, writes `.strictcli/schema.json`.
- `float.go` — strict float parsing with NaN/Inf rejection.
- `tagdsl.go` — tag DSL parser (NOT/AND/XOR/OR/DIFF operators).
- `check.go` — check registration, `CheckResult` with notes, `CheckOutcome` types.
- `check_cmd.go` — auto-registered `check` command with tag DSL, glob, JSON output.
- `check_runner.go` — DAG-ordered check execution with timing (`DurationMs`).
- `check_provider.go` — `CheckProvider` interface for external check sources.
- `check_public.go` — public API surface for the check system.
- `coverage.go` — CLI test-coverage recording plus the built-in `cli-test-coverage` check provider.
- `mcp.go` — MCP (Model Context Protocol) JSON-RPC 2.0 server on stdin/stdout (initialize, tools/list, tools/call).
- `tool.go` — `Tool` descriptors for exposing commands to tool-using LLM agents (MCP + JSON schema).

Handlers use ctx-first signatures: `func(ctx *Context, args map[string]interface{}) Outcome`. The `Context` provides structured output, provenance, and infra access; `Outcome` is the branded return type replacing raw exit codes.

### Conformance (`conformance/`)

JSON test cases in `cases/` (57 files) define app structure + argv + expected output. `run.py` drives targets differently:

- **Python**: generates a reference script via `ref_python.py` and executes it with the case argv.
- **Go**: builds a single persistent harness binary (`conformance/harness/`, built once per run, cleaned up afterward) that interprets the app definition at runtime. `run.py` writes the app definition JSON to a temp file and passes its path via the `CONFORMANCE_APP_DEF` env var. There is NO per-app-hash Go binary cache.
- `ref_go.py` (Go codegen) is legacy and still used ONLY by `fuzz.py`.

## Cross-language parity rules

All implementations must:

- Support exactly four types: `str`, `bool`, `int`, `float`.
- Use strict integer parsing (no leading/trailing whitespace, 64-bit signed bounds, no leading zeros in Go). Float parsing rejects NaN and Inf.
- Accept the same boolean env var strings: `1|true|yes` / `0|false|no` (case-insensitive).
- Produce identical error messages for identical inputs (checked by `check_error_parity.py`).
- Export the same API surface (checked by `check_api_surface.py`).
- Produce identical error messages for dependency violations (checked by `check_error_parity.py`).
- Pass all conformance cases for every target before release.

When adding a feature to one implementation, add it to all implementations and add conformance cases.

## Key conventions

- Flags with dashes (`--dry-run`) become underscore parameters (`dry_run`) in handlers.
- `app.test(argv)` / `app.Test(argv)` runs the CLI in-process for unit tests — never shell out.
- Help text is mandatory on every Flag, Arg, Command, Group, and App. Missing help is a registration-time error.
- Recursive group nesting: `group.group(name, help=...)` (Python) / `group.Group(name, help)` (Go). Arbitrary depth: App > Group > Group > ... > Command.
- Passthrough commands bypass all parsing — handler gets raw args plus global flag values.
- `CoRequired(flags=[...])` declares flags that must appear together. `Requires(flag=..., depends_on=...)` declares one-way dependency. `Implies(flag=..., implies=..., value=...)` auto-sets a bool flag when a trigger is provided. All passed via `dependencies=[...]`.
- `app.deprecate(name, message=...)` / `group.deprecate(name, message=...)` registers a retired command that prints the message to stderr and exits 1. Shown in help under a `Deprecated:` section.
- Validation errors at registration time use panics (Go) / ValueError (Python). Parse-time errors print to stderr and exit 1.
- `type=float` / `FloatFlag(...)` — float type support. NaN and Inf are rejected at parse time.
- Config file support — `App(config=True)` (Python) / `WithConfig()` (Go). Format is JSON (default) or TOML (`config_format="toml"` / `WithConfigFormat("toml")`). Reads `~/.config/{name}/config.json` (or `.toml`). Precedence: CLI > env > config > default. Auto-registers `config show/set/path/edit/init` subcommands.
- `--dump-schema` — auto-injected flag on every app. Writes `.strictcli/schema.json` describing the full CLI structure (commands, flags, args, groups).
- `--help` / `-h` is recognized anywhere in argv, not just at token boundaries.
- `Default(nil)` fix (Go only) — flags with `Default(nil)` display `[optional]` in help instead of `[default: <nil>]`.
- Check system — first-class check/validation framework with double-entry security. See below.

### Handler result contract

Handlers are ctx-first in every implementation; there is no legacy no-ctx signature and no `ctx.emit` — structured data flows back only through the return value.

- **Go**: `func(ctx *Context, kwargs map[string]interface{}) Outcome`. Return `Exit(code)` (exit code, no data) or `ExitData(code, data)` (data is JSON-marshaled to stdout and captured by `Test()`/`Call()`).
- **Python**: `def handler(ctx, **kwargs)` returning `int` (exit code), `None` (exit 0), or `strictcli.outcome(exit_code, data)`. Any other return type is a hard error. `Outcome` is branded — it cannot be constructed directly, only via the `outcome()` factory. When `data` is not None it is JSON-printed to stdout and captured by `test()`/`call()`.

### Provenance

Every resolved flag value carries a source label: `cli`, `env`, `config`, `default`, `implied` (injected by an Implies dependency), or `infra` (a `RelativeToRoot` default resolved through a declared infrastructure root).

- Handler access: `ctx.Source(name)` (Go, panics if the flag is unknown) / `ctx.source(name)` (Python, raises KeyError). Both accept dashed or underscored names. Python additionally exposes `ctx.source_map()`.
- `config show` displays each value's source.

### Infrastructure env vars (infra roots + handshake)

There are two kinds of declared infrastructure env vars; each is shown in help under an `Infrastructure:` section (annotated as not suppressed by `--hermetic`):

- **Infra roots** — `WithInfraRoot(envVar, defaultPath)` (Go) / `App(infra_root={env_var: default_path})` (Python). A location root: env var value if set, else the declared default (`~` expanded), resolved EAGERLY at construction time. Resolution has no argv dependency, which is why it is hermetic-immune.
- **Handshake env vars** — `WithHandshakeEnv(envVar, help)` (Go) / `App(handshake_env={env_var: help})` (Python). Cross-tool protocol signals set by the invoking process: no default, no eager capture, read LIVE at call time. A handshake var must not collide with a declared root.
- **`RelativeToRoot(envVar, parts...)`** — opaque path marker relative to a declared root. Accepted as a flag `default=` (resolved when defaults are applied at parse time; source label `infra`) and as the config path (`WithConfigPathRelativeToRoot(envVar, parts...)` in Go / `App(config_path=RelativeToRoot(...))` in Python; resolved eagerly at construction). Referencing an undeclared root is a registration-time hard error.
- **Handler access**: `ctx.InfraValue(envVar)` (Go) / `ctx.infra_value(env_var)` (Python) returns `(value, ok)`. For roots the value is the construction-time resolution and the boolean is always true; for handshakes it is a live `os.environ` lookup and the boolean means "is set". Undeclared vars panic (Go) / raise KeyError (Python) — declare everything.

### Hermetic mode

`--hermetic` is a reserved global flag on every app, intercepted by a position-aware pre-scan (alongside `--dump-schema`, `--mcp`, `--config`). Semantics:

- Skips config file loading entirely (even the default XDG path) and skips env var resolution for flags. Values come only from CLI tokens, declared defaults, and infra roots.
- Mutually exclusive with `--config` (parse error: `--hermetic and --config are mutually exclusive`).
- Cannot be combined with the `config` subcommands (parse error: `--hermetic cannot be used with config commands`).
- Does NOT suppress infra roots or handshake env vars — those are resolved at construction / read live and are explicitly hermetic-immune.

### Programmatic invocation

`app.Call(commandPath, kwargs)` (Go) / `app.call(command_path, **kwargs)` (Python; async variant `app.acall(...)` runs the handler in a thread). Runs a command in-process with pre-typed values, bypassing CLI parsing, env var resolution, config loading, and stdin handling.

- `commandPath` is dot-separated (`"deploy"`, `"dns.zone.create"`). Kwargs use underscored parameter names. Passthrough commands take a single `_args` key with the raw argument list.
- Returns the handler's structured data when present, else the exit code (Go) / the handler's return value (Python).
- Failures (unknown command, missing required flags, mutex violations, dependency errors) produce `InvokeError` — returned as the error in Go, raised as an exception in Python.

### Check system

Enabled via `WithChecks(path)` (Go) / `checks_path=` (Python), pointing to a TOML file (source of truth, committed to repo). Checks are registered in code via `@app.check("name")` (Python) / `app.RegisterCheck("name", fn)` (Go). Declaration and registration must agree — declared but unregistered or registered but undeclared are errors (double-entry security). The TOML file requires a top-level `app` field that must match the app name.

**TOML schema**: Required top-level `app` field (must match app name). `[checks.<name>]` sections with required fields: `tags` (list of strings), `severity` ("error"/"warn"), `fast` (bool), `pure` (bool), `needs_network` (bool), `depends_on` (list of check names). Check names: `[a-z][a-z0-9-]*`. Every field must be explicit — no defaults section. The `[checks]` section is optional — an `app` field with no checks is a valid TOML file.

**Check command**: auto-registered when checks are enabled via `WithChecks(path)` (Go) or `checks_path=` (Python). 8 flags: `--all`, `--tag <dsl>`, `--name <glob>`, `--list`, `--json`, `--ignore-warnings`, `--verbose`, `--dry-run`. No flags = show help. Hidden from help when no TOML exists.

**Tag DSL**: `--tag` accepts a set-operation expression. Operators by precedence (tightest first): `!` (NOT), `&` (AND), `^` (XOR), `|` (OR), `-` (DIFF). Parentheses for grouping. Example: `--tag "(release | changelog) & !slow"`.

**CheckResult**: `status` (pass/fail/warn/skip), `message` (str), `details` (list of str), `notes` (informational messages recorded via `Note()`, verdict-inert). Warn causes nonzero exit unless `--ignore-warnings`. `CheckRunResult` wraps `CheckOutcome` with `DurationMs` (wall-clock timing in integer milliseconds).

**CheckContext**: protocol/interface with single required field `ProjectRoot() string` / `project_root: Path`. Tool sets a factory via `app.set_check_context(factory)` / `app.SetCheckContext(factory)`.

**depends_on**: DAG resolution with cycle detection. Dependency failure skips dependents. Filtered-out dependencies are pulled back in when a selected check depends on them.

**Schema integration**: `--dump-schema` includes a `checks` top-level key when checks are enabled.

**Hooks**: strictcli does NOT manage `.git/hooks/`. External tools call `myapp check --tag pre-push` from their own hook scripts.

## Release workflow

Each sub-project releases independently via `rlsbl release` from its own directory. See sub-project CLAUDE.md files and the parent `~/Projects/CLAUDE.md` for rlsbl details.

## Useful commands

```bash
# Check rlsbl status across sub-projects
cd python && rlsbl status
cd go && rlsbl status
cd conformance && rlsbl status

# API surface check
cd conformance && python check_api_surface.py

# Error message parity check
cd conformance && python check_error_parity.py
```
