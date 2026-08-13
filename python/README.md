# strictcli

A strict CLI framework for Python.

strictcli makes you declare everything -- every command, flag, argument, and environment variable must have help text or the framework errors at registration time. Four types only: `str`, `bool`, `int`, `float`. No magic type inference, no implicit defaults.

## Installation

```
pip install strictcli
```

Or with uv:

```
uv add strictcli
```

Requires Python 3.11+. One runtime dependency: [tomlkit](https://pypi.org/project/tomlkit/), for comment-preserving TOML config support.

## Quickstart

```python validate
import strictcli

app = strictcli.App("greet", version="1.0.0", help="A greeting app")

@app.command("hello", help="Say hello", effect="read_only")
@strictcli.flag("name", type=str, help="Who to greet")
@strictcli.flag("loud", type=bool, default=False, help="Shout it")
def hello(ctx, name, loud):
    msg = f"Hello, {name}!"
    ctx.info(msg.upper() if loud else msg)

app.run()
```

Every handler is **ctx-first**: the framework injects a `Context` as the first
positional argument, and flag and arg values follow as keyword arguments. Every
command declares its `effect` -- `"read_only"` or `"mutating"` -- and the
declaration is mandatory.

```
$ python greet.py hello --name World
Hello, World!

$ python greet.py hello --name World --loud
HELLO, WORLD!

$ python greet.py hello --help
greet hello -- Say hello

Flags:
  --name <str>         Who to greet [required]
  --loud, --no-loud    Shout it [default: false]
```

## Features

### Commands and groups

Top-level commands with `@app.command`, nested groups with `app.group`. Groups nest recursively to arbitrary depth via `group.group`.

```python
db = app.group("db", help="Database operations")
schema = db.group("schema", help="Schema management")

@schema.command("migrate", help="Run migrations", effect="mutating")
def migrate(ctx):
    ctx.info("migrating")
```

Invoked as `myapp db schema migrate`.

### Four flag types

`str`, `bool`, `int`, and `float`. No magic coercion -- parse errors are clear and immediate.

```python
@strictcli.flag("port", type=int, help="Port number")
@strictcli.flag("threshold", type=float, help="Score threshold")
@strictcli.flag("cache", type=bool, default=True, help="Reuse the build cache")
@strictcli.flag("output", type=str, help="Output path", default="out.txt")
```

Bool flags support `--flag` / `--no-flag` negation (disable with `negatable=False`) and have **no implicit default**: without `default=` they are required and the user must pass `--flag` or `--no-flag` explicitly. Float parsing rejects NaN and Inf.

### Compound types

`list[T]` and `dict[str, T]` for collecting multiple values.

```python
@strictcli.flag("tags", type=list[str], help="Tags to apply", unique=True)
@strictcli.flag("env", type=dict[str, str], help="Environment variables")
```

List flags accept `--tags a --tags b`. Dict flags accept `--env KEY=VALUE` pairs or JSON objects.

### Positional arguments

Two equivalent declaration forms. Arguments can be required, optional (with `required=False`), or variadic.

```python
# Decorator form
@app.command("show", help="Show a file", effect="read_only")
@strictcli.arg("path", help="File to show")
def show(ctx, path): ...

# Inline form
@app.command("copy", help="Copy files", effect="mutating", args=[
    strictcli.Arg(name="src", help="Source"),
    strictcli.Arg(name="dst", help="Destination"),
])
def copy(ctx, src, dst): ...
```

### Short flag aliases

Single-character shortcuts for any flag.

```python
@strictcli.flag("recursive", short="r", type=bool, default=False, help="Recurse into subdirectories")
@strictcli.flag("output", short="o", type=str, help="Output path", default=".")
```

### Environment variable binding

Flags can be backed by environment variables. Prefix enforcement keeps your config namespace clean.

```python
app = strictcli.App("myapp", version="1.0.0", help="My app", env_prefix="MYAPP")

@strictcli.flag("region", type=str, help="Cloud region", env="MYAPP_REGION", default="us-east-1")
```

All env vars must start with the declared prefix. Use `prefixed=False` for external env vars like `GITHUB_TOKEN`. Precedence: CLI > env > config > default.

Bool env vars accept `1|true|yes` / `0|false|no` (case-insensitive).

### FlagSets

Reusable bundles of flags shared across commands.

```python
auth_flags = strictcli.FlagSet(
    name="auth",
    flags=[
        strictcli.Flag(name="token", type=str, help="Auth token", default=""),
        strictcli.Flag(name="insecure", type=bool, default=False, help="Skip TLS verification"),
    ],
)

@app.command("deploy", help="Deploy", effect="mutating", flag_sets=[auth_flags])
def deploy(ctx, token, insecure): ...
```

### Mutually exclusive flag groups

Exactly one flag from the group must be provided.

```python
@app.command("log", help="Show logs", effect="read_only", mutex=[
    strictcli.MutexGroup(flags=[
        strictcli.Flag(name="since", type=str, help="Show logs since a timestamp"),
        strictcli.Flag(name="tail", type=int, help="Show the last N lines"),
    ]),
])
def log(ctx, since, tail): ...
```

### Flag dependencies

Three relationship types, all passed via `dependencies=[...]`:

- `CoRequired(flags=["output", "format"])` -- all must appear together, or none
- `Requires(flag="trace", depends_on="output")` -- one-way dependency
- `Implies(flag="trace", implies="log-output", value=True)` -- auto-set a bool flag when another is provided; explicit contradictions are parse errors

```python
@app.command("export", help="Export data", effect="mutating", dependencies=[
    strictcli.CoRequired(flags=["output", "format"]),
    strictcli.Requires(flag="trace", depends_on="output"),
    strictcli.Implies(flag="trace", implies="log-output", value=True),
])
@strictcli.flag("output", type=str, default=None, help="Output path")
@strictcli.flag("format", type=str, default=None, help="Output format")
@strictcli.flag("trace", type=bool, default=False, help="Emit a trace")
@strictcli.flag("log-output", type=bool, default=False, help="Log the output path")
def export(ctx, output, format, trace, log_output): ...
```

Dependencies can only reference flags you declared, so the reserved quartet
(`dry-run`, `approve-consequential`, `quiet`, `verbose`) can never appear in one.

### Global flags

App-level flags available to all commands, parsed before and after the command token.

```python
app = strictcli.App("myapp", version="1.0.0", help="My app", flags=[
    strictcli.Flag(name="color", type=bool, default=True, help="Colorize output"),
])
```

Global flag names cannot collide with the framework's reserved names (`help`,
`h`, `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`) or with the
reserved quartet.

### Passthrough commands

Bypass all parsing -- handler gets raw args plus global flag values.

```python
@app.command("run", help="Run a script", effect="mutating", passthrough=True)
def run(ctx, args, color):
    ctx.effects.run(args)
```

The reserved quartet is not scanned after a passthrough command's name: its args
are forwarded to the child byte-for-byte, so `myapp run deploy --dry-run` passes
`--dry-run` to the child.

### Repeatable flags

Flags that accumulate values across multiple occurrences. Requires explicit `unique=True` or `unique=False`.

```python
@strictcli.flag("tag", type=str, help="Add a tag", repeatable=True, unique=True)
```

### Choices

Restrict flag values to an allowed set.

```python
@strictcli.flag("format", type=str, help="Output format", choices=["json", "csv", "xml"])
```

### Custom validation

Per-flag validation functions.

```python
@strictcli.flag("port", type=int, help="Port number", validate=lambda v: 1 <= v <= 65535)
```

### Deprecated commands

Register retired commands that print a message to stderr and exit 1.

```python
app.deprecate("init", message="Use 'setup' instead")
db.deprecate("reset", message="Use 'db wipe' instead")
```

Deprecated commands appear in help output under a `Deprecated:` section.

### Hidden commands and groups

Commands and groups can be hidden from help output while remaining functional.

```python
@app.command("internal-debug", help="Debug internals", effect="read_only", hidden=True)
def internal_debug(ctx): ...
```

### JSON config file support

Reads `~/.config/{name}/config.json` (or TOML). Auto-registers `config show/set/path/edit` subcommands.

```python
app = strictcli.App("myapp", version="1.0.0", help="My app", config=True)
```

Precedence: CLI > env > config > default. Config fields can be declared with typed validation:

```python
app.config_field("serve.port", type=int, help="Server port", default=8080)
```

### The effects regime

Every command declares `effect="read_only"` or `effect="mutating"` -- there is no
default and no inference. A read-only command changes nothing and calling a
mutating member of `ctx.effects` from one is a hard error at call time. A
mutating command participates in `--dry-run`, where the eight recorded
operations (`run`, `spawn`, `write`, `mkdir`, `remove`, `rename`, `chmod`,
`http`) are recorded rather than performed and rendered as a would-do log.

Four flag names are owned by the framework and cannot be declared at any level
(app flags, command flags, flag sets, mutex groups). They arrive on the context,
never as handler kwargs:

| Flag | Context property |
|------|-----------------|
| `--dry-run` | `ctx.dry_run` |
| `--approve-consequential` | `ctx.approve_consequential` |
| `--quiet` | `ctx.quiet` |
| `--verbose` | `ctx.verbose` |

A flag named `yes` is banned outright -- the confirmation skip is
`--approve-consequential`.

A command whose preview would lie declares the refusal instead of rendering one:

```python
@app.command("migrate", help="Run migrations", effect="mutating",
             dry_run_supported=False,
             dry_run_unsupported_reason="each migration reads the schema the previous one wrote")
def migrate(ctx): ...
```

`--dry-run` is then refused at parse time with the reason, which also appears in
the command's help under a `Dry run:` section and in the schema.

### Consequential commands

`consequential=True` is the only thing that makes the framework prompt -- a plain
mutating command never does. Classification answers "should a dry run record
this?"; `consequential` answers "are these effects worth interrupting someone
for?"

```python
@app.command("destroy", help="Destroy the cluster", effect="mutating", consequential=True)
def destroy(ctx): ...
```

Before dispatch the framework prints `about to run consequential command
'destroy'. Proceed? [y/N] ` to stderr and reads one line from stdin; only `y` or
`Y` proceeds. `--approve-consequential` answers in advance, and `--dry-run`
skips the prompt because nothing is being performed. A non-interactive stdin
without either flag is a hard error rather than a hang. Declaring
`consequential=True` on a read-only command raises `ValueError`.

### Schema dump

`--dump-schema` is auto-injected on every app. Writes `.strictcli/schema.json` describing the full CLI structure (commands, flags, args, groups, checks). Every command entry carries its `effect`; `consequential`, `dry_run_supported` and `dry_run_unsupported_reason` are emitted only when declared.

### Check system

First-class check/validation framework with double-entry security. Enabled via `checks_path=` pointing to a TOML file.

```python
app = strictcli.App("myapp", version="1.0.0", help="My app", checks_path="checks.toml")

@app.error_check("lint")
def lint(ctx, reporter: strictcli.ErrorReporter):
    if problems := find_problems():
        for p in problems:
            reporter.error(p)
        return reporter.found("lint problems found")
    return reporter.passed("All good")
```

Checks are declared in TOML and registered in code -- both must agree. The
registration form must match the declared severity: `@app.error_check` for
`severity = "error"` (its reporter has `error` and `warn`), `@app.warn_check`
for `severity = "warn"` (its reporter structurally lacks `error`, so a warn
check cannot cascade). An outcome is minted only through a reporter method --
`passed(message)`, `skipped(reason)`, or `found(message)` after accumulating
problems; `reporter.note(text)` records verdict-inert informational notes.
Auto-registers a `check` command with tag DSL filtering
(`--tag "release & !slow"`), JSON output, and dependency resolution.

### Auto-version

`App(name="x", help="...")` without an explicit `version` auto-detects from `importlib.metadata`.

### Tool export

`app.as_tools()` exports non-hidden, non-interactive commands as `Tool` descriptors for LLM agents.

```python
tools = app.as_tools()
# Each Tool has: name, description, parameters (JSON Schema), effect,
# consequential, execute
```

`effect` and `consequential` publish the effects-regime classification beside
the argument schema, so a caller can see before it calls that a tool changes
things and that invoking it requires stating consent:

```python
release = next(t for t in tools if t.name == "release")
release.consequential            # True
await release.execute()          # InvokeError: ... the call must carry confirmation
await release.execute(approve_consequential=True)   # proceeds
```

### MCP server

`app.serve_mcp()` runs a JSON-RPC 2.0 MCP server on stdin/stdout, exposing commands as tools for AI clients. Triggered via `--mcp` flag.

### Help and version

- `--help` / `-h` recognized anywhere in argv, at app, group, and command levels
- `--version` / `-v` prints app version
- Help is auto-generated with flag types, defaults, env var names, and choices

## Testing

`app.test(argv)` runs the CLI in-process and returns a `Result`:

```python
result = app.test(["hello", "--name", "World", "--loud"])

assert result.exit_code == 0
assert "HELLO, WORLD!" in result.stdout
assert result.stderr == ""
```

The confirm protocol never fires on `test()` or `call()` -- the programmatic
paths have no TTY contract, so a consequential command is dispatched directly.

## API reference

### Core types

| Type | Description |
|------|-------------|
| `App` | Root CLI application |
| `Flag` | Flag declaration |
| `Arg` | Positional argument |
| `FlagSet` | Reusable flag bundle |
| `MutexGroup` | Mutually exclusive flags |
| `CoRequired` | Flags that must appear together |
| `Requires` | One flag depends on another |
| `Implies` | Auto-set a bool flag from another |
| `Result` | Return type of `app.test()` |
| `Tool` | LLM tool descriptor |
| `CheckRunResult` | Check execution result with wall-clock timing |
| `CheckContext` | Protocol for check context |
| `ErrorReporter` / `WarnReporter` | Problem accumulators passed to check handlers |
| `ConfigField` | Typed config file field |

### Decorators

| Decorator | Description |
|-----------|-------------|
| `@app.command(name, help=..., effect=...)` | Register a command (`effect` is mandatory) |
| `@strictcli.flag(name, type=, help=...)` | Declare a flag |
| `@strictcli.arg(name, help=...)` | Declare a positional argument |
| `@app.error_check(name)` / `@app.warn_check(name)` | Register a check handler |

### App methods

| Method | Description |
|--------|-------------|
| `app.command(name, help=..., effect=...)` | Register a command (decorator; `effect` is mandatory) |
| `app.group(name, help=...)` | Create a command group |
| `app.deprecate(name, message=...)` | Register a deprecated command |
| `app.run()` | Parse `sys.argv` and execute |
| `app.test(argv)` | Run in-process, return `Result` |
| `app.as_tools()` | Export commands as `Tool` descriptors |
| `app.serve_mcp()` | Run MCP server on stdin/stdout |
| `app.config_field(name, type=, help=...)` | Declare a typed config field |
| `app.error_check(name)` / `app.warn_check(name)` | Register a check handler (decorator) |
| `app.set_check_context(factory)` | Set the check context factory |

## Design principles

- **Help is mandatory.** Every command, flag, and argument must have help text. Missing help raises `ValueError` at registration time.
- **Four types only.** `str`, `bool`, `int`, `float` -- plus compound `list[T]` and `dict[str, T]`. No magic type coercion.
- **Handler signatures are validated.** Parameter names must match declared flags and args exactly. Extra or missing parameters raise `ValueError`.
- **Effect classification is mandatory.** Every command declares `read_only` or `mutating`. There is no default and no inference.
- **Registration-time errors.** Misconfigurations fail loud and early, not at parse time.
- **Minimal dependencies.** The standard library plus [tomlkit](https://pypi.org/project/tomlkit/) for TOML config support.

## See also

- [strictcli monorepo](https://github.com/smm-h/strictcli) -- conformance tests, Go implementation, and project documentation
- [Go implementation](https://github.com/smm-h/strictcli/tree/main/go) -- same semantics, functional options API

## License

MIT
