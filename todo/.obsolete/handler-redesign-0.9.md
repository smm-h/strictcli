# Handler redesign (Python 0.9 / Go 0.6)

Bundle of breaking changes that transform strictcli from a CLI-only framework into a layered system where handlers are pure library functions and the CLI is one adapter on top.

## Motivation

Two concrete use cases drive this:

1. **Native web/edge.** A future TypeScript implementation needs to run in browsers and Supabase edge functions — environments with no process, no filesystem, no shell. The handler contract must be pure enough to work without any of those.
2. **CLI as library.** Every CLI is a library at its core; the CLI is just a thin UI making it shell-callable. strictcli should make this natural: handlers are the library, the framework is the dispatch layer, and adapters connect interfaces (shell, HTTP, browser) to the core.

The redesign makes this architecture explicit and enforces it.

## Decisions

All decisions were made during an ASKME session. They are final unless revisited.

- **Release strategy:** single redesign release bundling all breaking changes. Python 0.9, Go 0.6.
- **Handler return type:** Result composite with `data`, `exit_code`, `error`.
- **Typed handler inputs:** Python gets signature validation via `inspect` (Option B). Go gets a generic accessor `Get[T](kwargs, key)` (Option A).
- **Output wrapper:** unified stateful wrapper managing verbosity/quietness, handles stdout/stderr routing by message level (info, debug, warn, error).
- **Subprocess control:** mandatory subprocess wrapper injecting the framework's stdio into child processes. AST-based enforcement via a built-in strictcli check (direct AST implementation, not a separate linter tool).
- **Output format flag:** `--output` global flag with a pluggable formatter registry. json and text built-in; users register custom formatters.
- **Pure parse mode:** `app.parse(argv)` returning a distinct `ParseResult` type (different from handler `Result`).
- **Framework exit behavior:** `run()` / `Run()` returns exit code instead of calling `sys.exit()` / `os.Exit()`.
- **Env var injection:** handlers declare env var needs, framework reads and injects them.
- **Pluggable config source:** config loader is swappable (filesystem, in-memory, HTTP, etc.).
- **Excluded:** dependency injection, progress/logging abstraction.
- **TS implementation:** happens after this redesign. TS is born with the new architecture.

## Work items

### 1. Framework returns exit code instead of calling exit

`run()` returns `int` instead of calling `sys.exit()` / `os.Exit()`. Callers wrap with `sys.exit(app.run())` / `os.Exit(app.Run())`.

**Python:**
- `run()` currently returns `None` and calls `sys.exit()` at 6 points (lines 1273, 1285, 1288, 1292, 1296, 1302).
- Change return type to `int`. Replace every `sys.exit(n)` with `return n`.

**Go:**
- `Run()` currently returns nothing and calls `os.Exit()` at 8 points (lines 767, 774, 778, 784, 787, 792, 797, 801).
- Change return type to `int`. Replace every `os.Exit(n)` with `return n`.

**Conformance:** update all test harness code that calls `run()` / `Run()` to wrap with exit.

**Consumer migration:** every consumer's `main()` needs `sys.exit(app.run())` / `os.Exit(app.Run())`. Affects all 10 consumers: rlsbl, selfdoc, claudewheel, claudestream, predraw, wesktop (Python); safegit, saferm, howmuchleft, migrable (Go).

**Effort:** small. ~1 session.

### 2. Handler Result composite

Handlers return a `Result` with three fields instead of printing output and returning an int.

**Python:**
```python
@dataclass
class HandlerResult:
    data: object = None      # structured output (dict, list, str, None)
    exit_code: int = 0
    error: str | None = None
```

Current `Result` (used by `test()`) stays for test output capture but is distinct from `HandlerResult`.

**Go:**
```go
type HandlerResult struct {
    Data     interface{}
    ExitCode int
    Error    string  // empty = no error
}
```

Current `Result` (used by `Test()`) stays.

**Handler type changes:**
- Python: handler returns `HandlerResult` instead of `int | None`. Current signature `cmd.handler(**data)` stays but return type changes.
- Go: handler type changes from `func(map[string]interface{}) int` to `func(map[string]interface{}) HandlerResult`. PassthroughHandler changes similarly.

**Framework changes:**
- `run()` / `Run()` receives `HandlerResult`, formats `data` via the output system, writes `error` to stderr if present, returns `exit_code`.
- `test()` / `Test()` receives `HandlerResult`, stores raw data in a new field on the test `Result` alongside captured stdout/stderr.

**Conformance:** new test cases for handlers that return data, error, and non-zero exit codes.

**Effort:** large. ~2-3 sessions. Touches every handler in every consumer.

### 3. Unified output wrapper

Stateful wrapper injected into handlers for diagnostic output. Primary output is the `HandlerResult.data`; the wrapper handles side-channel messages.

**API (Python):**
```python
def deploy(out, name: str, force: bool) -> HandlerResult:
    out.info("Deploying %s...", name)       # stdout, silenced by --quiet
    out.debug("Config: %s", config)         # stderr, only with --verbose
    out.warn("Deprecated flag used")        # stderr, always shown
    out.error("Connection failed")          # stderr, always shown
    return HandlerResult(data={"status": "ok"})
```

**API (Go):**
```go
func deploy(out *Output, kwargs map[string]interface{}) HandlerResult {
    out.Info("Deploying %s...", name)
    out.Debug("Config: %s", config)
    out.Warn("Deprecated flag used")
    out.Error("Connection failed")
    return HandlerResult{Data: map[string]interface{}{"status": "ok"}}
}
```

**Verbosity control:**
- `--quiet` silences info-level messages.
- `--verbose` shows debug-level messages.
- warn and error are always shown.
- These become built-in global flags managed by the framework.

**Routing:**
- info: stdout
- debug: stderr
- warn: stderr
- error: stderr

**Integration with test():**
- `test()` captures output wrapper messages alongside handler return data.
- Test `Result` gains fields for captured wrapper output.

**Effort:** medium. ~2 sessions.

### 4. Mandatory subprocess wrapper

Handlers must use a framework-provided subprocess runner. The runner injects the framework's stdout/stderr wrappers into child processes so verbosity control applies to shelled-out commands.

**Python:**
```python
def deploy(out, name: str) -> HandlerResult:
    result = out.run(["git", "push", "origin", "main"])
    # result.returncode, result.stdout, result.stderr available
    # subprocess stdout/stderr routed through the output wrapper
```

**Go:**
```go
func deploy(out *Output, kwargs map[string]interface{}) HandlerResult {
    result := out.Run("git", "push", "origin", "main")
    // result.ExitCode, result.Stdout, result.Stderr available
}
```

The wrapper replaces the real stdout/stderr file descriptors before spawning the subprocess, so child processes inherit the wrapper's output routing.

**AST enforcement (built-in strictcli check):**
- Python: parse handler source with `ast` module, walk for `subprocess.run`, `subprocess.Popen`, `subprocess.call`, `os.system`, `os.popen`, `os.exec*` calls. Hard error.
- Go: parse handler source with `go/ast`, walk for `os/exec.Command`, `os/exec.CommandContext`, `syscall.Exec` calls. Hard error.
- Registered as a built-in check (auto-registered when subprocess wrapper is used). Runs via `myapp check --tag subprocess`.
- Declared in `.strictcli/checks.toml` by the framework, not by the user.

**Effort:** medium-large. ~2-3 sessions. AST analysis is ~30-50 lines per language; subprocess fd redirection is the complex part.

### 5. Pluggable output format

`--output` global flag with a pluggable formatter registry. Formats the `HandlerResult.data` for display.

**Built-in formatters:**
- `text`: default. Converts data to human-readable text (str() or custom __str__).
- `json`: JSON serialization of data.

**Formatter registry:**
```python
app.register_formatter("table", my_table_formatter)
app.register_formatter("csv", my_csv_formatter)
```

```go
app.RegisterFormatter("table", myTableFormatter)
```

**Formatter interface:**
- Python: `Callable[[object], str]` — takes data, returns formatted string.
- Go: `func(interface{}) (string, error)` — takes data, returns formatted string.

**Flag behavior:**
- `--output json` selects the json formatter.
- `--output text` selects the text formatter (default).
- `--output <custom>` selects a user-registered formatter. Error if not registered.
- Commands that return `data=None` produce no output regardless of format.

**Effort:** small-medium. ~1 session. Depends on items 2 and 3.

### 6. Typed handler inputs

**Python (signature validation):**

At registration time, inspect the handler's type hints via `inspect.signature()`. Validate that:
- Every declared flag/arg has a matching parameter name in the handler signature.
- Type hints (if present) are compatible with the declared flag type (e.g., `str` flag matches `str` hint, `bool` flag matches `bool` hint).
- Raise `ValueError` at registration if there's a mismatch.

Handlers without type hints pass validation (opt-in enforcement). The `**kwargs` escape hatch continues to work.

The `_build_and_validate_command()` function (around line 2175) already validates parameter names. This extends it to also check types.

~50 lines of `inspect` module work. **Effort:** small. ~0.5 session.

**Go (generic accessor):**

Add a generic helper function:
```go
func Get[T any](kwargs map[string]interface{}, key string) T {
    v, ok := kwargs[key]
    if !ok {
        var zero T
        return zero
    }
    return v.(T)
}
```

Replaces verbose `kwargs["key"].(string)` and `if v := kwargs["key"]; v != nil { ... }` patterns. No handler signature change.

~20 lines. **Effort:** small. ~0.5 session.

### 7. Pure parse mode

`app.parse(argv)` returns a `ParseResult` without executing the handler.

**ParseResult type:**

```python
@dataclass
class ParseResult:
    command: str              # matched command name (dotted for nested: "group.cmd")
    kwargs: dict[str, object] # resolved flag/arg values (after env, config, defaults)
    errors: list[str]         # parse errors (empty = success)
    help_text: str | None     # help text if --help was in argv
    version_text: str | None  # version text if --version was in argv
```

```go
type ParseResult struct {
    Command     string
    Kwargs      map[string]interface{}
    Errors      []string
    HelpText    string  // empty if not requested
    VersionText string  // empty if not requested
}
```

**Use cases:** validation-only mode (web form checking), introspection, building higher-level abstractions on top of strictcli.

**Implementation:** the parsing logic already exists as an internal stage. This exposes the intermediate result. In Python, `_parse()` (internal) already produces this data. In Go, `doParse()` (internal) already produces `parseResult`.

**Effort:** small-medium. ~1 session. Mostly about defining the public type and wiring the internal parse result to it.

### 8. Env var injection

Handlers declare env var needs beyond flag-level env vars. The framework reads them from the environment and injects them into the handler kwargs.

**Current state:** flags already support `env="VAR_NAME"` for default resolution. But handlers that need env vars not tied to flags (API keys, tokens, etc.) read `os.environ` / `os.Getenv` directly.

**Proposed:**

```python
@app.command("deploy", help="Deploy the app")
@env("API_KEY", help="API authentication key")
@env("REGION", help="Deploy region", required=False)
def deploy(api_key: str, region: str | None, force: bool) -> HandlerResult:
    ...
```

```go
app.Command("deploy", "Deploy the app",
    strictcli.EnvVar("API_KEY", "API authentication key"),
    strictcli.EnvVar("REGION", "Deploy region", strictcli.Optional()),
    strictcli.BoolFlag("force", "Force deploy"),
    handler,
)
```

Env vars are read by the framework and injected into kwargs alongside parsed flags/args. Missing required env vars produce a parse error (same as missing required flags).

**Parity:** both implementations support identical env var declarations and error messages.

**Effort:** small-medium. ~1 session. The env var reading mechanism already exists for flags; this generalizes it.

### 9. Pluggable config source

Config loading decoupled from the filesystem. Default is filesystem (`~/.config/{name}/config.json`); users can provide alternative sources.

**Python:**
```python
app = App(
    name="myapp",
    help="...",
    config=True,
    config_source=my_custom_loader,  # Callable[[], dict]
)
```

**Go:**
```go
app := NewApp("myapp", "1.0", "...",
    WithConfig(),
    WithConfigSource(myCustomLoader),  // func() (map[string]interface{}, error)
)
```

**Config source interface:**
- Python: `Callable[[], dict[str, object]]` — returns config dict.
- Go: `func() (map[string]interface{}, error)` — returns config map.
- Default implementation reads from filesystem (current behavior).

**Impact on config subcommands:** `config show`, `config set`, `config path`, `config edit` assume filesystem. With a custom source:
- `config show` works (reads from source).
- `config set` needs a writer interface too, or is disabled for non-filesystem sources.
- `config path` and `config edit` are filesystem-only; disabled or hidden for custom sources.

**Effort:** medium. ~1-2 sessions. Refactor config loading into an interface, implement filesystem as default, handle subcommand availability.

### 10. Conformance suite updates

Every behavioral change above needs conformance test coverage.

**New test areas:**
- Handler returning `HandlerResult` with data/exit_code/error combinations
- Output wrapper message levels and verbosity control
- `--output json` / `--output text` formatting
- `app.parse(argv)` returning `ParseResult`
- `run()` returning exit code (not calling exit)
- Env var injection (required, optional, missing)
- `--quiet` and `--verbose` global flag behavior

**Existing test updates:**
- All existing test cases that check handler return behavior need updating (handlers return `HandlerResult` instead of `int`).
- Conformance reference code generators (`ref_python.py`, `ref_go.py`) need updating for new handler signatures.

**Effort:** medium. ~2 sessions. Spread across all other items.

### 11. Consumer migration

All 10 consumers need updating for the breaking changes. The migration per consumer involves:

1. Wrap `app.run()` with `sys.exit()` / `os.Exit()` (item 1).
2. Change handler return types from `int` to `HandlerResult` (item 2).
3. Replace `print()` / `fmt.Println()` with output wrapper calls (item 3).
4. Replace `subprocess.run()` / `exec.Command()` with `out.run()` / `out.Run()` (item 4).
5. Add type hints to Python handler signatures for validation (item 6, opt-in).

**Python consumers (6):** rlsbl (35 handlers), selfdoc (7), claudewheel (13), claudestream (4), predraw (6), wesktop (1).

**Go consumers (4):** safegit (14 handlers), saferm (5), howmuchleft (7), migrable (5).

**Total handlers to migrate:** ~97.

Consumer migration is out of scope for this todo — each consumer project gets its own migration todo filed when this work ships. Listed here for awareness.

**Effort:** large (across all consumer projects). ~1 session per consumer.

## Dependencies

```
1 (return exit code)
  \
   --> 2 (Result composite) --> 5 (output format flag)
  /                        \
3 (output wrapper)          --> 10 (conformance)
  \
   --> 4 (subprocess wrapper)

6 (typed inputs)     -- independent
7 (pure parse mode)  -- independent
8 (env var injection) -- independent
9 (pluggable config)  -- independent
```

Items 6, 7, 8, 9 have no dependencies on each other or on items 1-5. They can be done in any order.

Items 1, 2, 3 form the core chain: exit behavior enables the Result type, which enables the output wrapper. Item 5 (output format) depends on the Result type. Item 4 (subprocess) depends on the output wrapper.

## Effort summary

| Item | Effort | Sessions |
|------|--------|----------|
| 1. Return exit code | Small | 1 |
| 2. Result composite | Large | 2-3 |
| 3. Output wrapper | Medium | 2 |
| 4. Subprocess wrapper + AST check | Medium-large | 2-3 |
| 5. Output format flag | Small-medium | 1 |
| 6. Typed inputs (both languages) | Small | 1 |
| 7. Pure parse mode | Small-medium | 1 |
| 8. Env var injection | Small-medium | 1 |
| 9. Pluggable config | Medium | 1-2 |
| 10. Conformance updates | Medium | 2 |
| **Total** | | **~15-18 sessions** |

## Affected files

**Python:**
- `python/strictcli/__init__.py` — core implementation (all items)
- `python/pyproject.toml` — version bump to 0.9.0
- `python/package.json` — version bump to 0.9.0

**Go:**
- `go/strictcli/strictcli.go` — types, constructors, run/test (items 1, 2, 3, 6, 7)
- `go/strictcli/parse.go` — parsing, env resolution (items 7, 8)
- `go/strictcli/help.go` — help formatting (item 7)
- `go/strictcli/config.go` — config loading (item 9)
- `go/VERSION` — version bump to 0.6.0

**Conformance:**
- `conformance/cases/*.json` — new and updated test cases
- `conformance/ref_python.py` — updated reference code generator
- `conformance/ref_go.py` — updated reference code generator
- `conformance/run.py` — updated runner if Result types change

## Relationship to TS implementation

This redesign is the prerequisite for the TypeScript implementation. The TS implementation will be born with:

- Layered architecture (pure core + adapters for Node, browser, edge)
- Handler Result composite as the native return type
- Output wrapper as the primary diagnostic channel
- Pluggable config source (essential for browser/edge where there's no filesystem)
- Pure parse mode (essential for validation-only web use cases)

The TS implementation gets its own todo after this redesign ships.
