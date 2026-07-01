# strictcli

A strict, zero-dependency CLI framework for Python.

strictcli makes you declare everything -- every command, flag, argument, and environment variable must have help text or the framework errors at registration time. Four types only: `str`, `bool`, `int`, `float`. No magic type inference, no implicit defaults.

## Installation

```
pip install strictcli
```

Or with uv:

```
uv add strictcli
```

Requires Python 3.11+. Zero external dependencies.

## Quickstart

```python
import strictcli

app = strictcli.App("greet", version="1.0.0", help="A greeting app")

@app.command("hello", help="Say hello")
@strictcli.flag("name", type=str, help="Who to greet")
@strictcli.flag("loud", type=bool, help="Shout it")
def hello(name, loud):
    msg = f"Hello, {name}!"
    print(msg.upper() if loud else msg)

app.run()
```

```
$ python greet.py hello --name World
Hello, World!

$ python greet.py hello --name World --loud
HELLO, WORLD!

$ python greet.py hello --help
greet hello -- Say hello

Flags:
  --name <str>              Who to greet
  --loud, --no-loud         Shout it [default: false]
```

## Features

### Commands and groups

Top-level commands with `@app.command`, nested groups with `app.group`. Groups nest recursively to arbitrary depth via `group.group`.

```python
db = app.group("db", help="Database operations")
schema = db.group("schema", help="Schema management")

@schema.command("migrate", help="Run migrations")
def migrate():
    print("migrating")
```

Invoked as `myapp db schema migrate`.

### Four flag types

`str`, `bool`, `int`, and `float`. No magic coercion -- parse errors are clear and immediate.

```python
@strictcli.flag("port", type=int, help="Port number")
@strictcli.flag("threshold", type=float, help="Score threshold")
@strictcli.flag("verbose", type=bool, help="Verbose output")
@strictcli.flag("output", type=str, help="Output path", default="out.txt")
```

Bool flags default to `False`, support `--flag` / `--no-flag` negation (disable with `negatable=False`). Float parsing rejects NaN and Inf.

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
@app.command("show", help="Show a file")
@strictcli.arg("path", help="File to show")
def show(path): ...

# Inline form
@app.command("copy", help="Copy files", args=[
    strictcli.Arg(name="src", help="Source"),
    strictcli.Arg(name="dst", help="Destination"),
])
def copy(src, dst): ...
```

### Short flag aliases

Single-character shortcuts for any flag.

```python
@strictcli.flag("verbose", short="v", type=bool, help="Verbose output")
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
        strictcli.Flag(name="insecure", type=bool, help="Skip TLS verification"),
    ],
)

@app.command("deploy", help="Deploy", flag_sets=[auth_flags])
def deploy(token, insecure): ...
```

### Mutually exclusive flag groups

Exactly one flag from the group must be provided.

```python
@app.command("log", help="Show logs", mutex=[
    strictcli.MutexGroup(flags=[
        strictcli.Flag(name="verbose", type=bool, help="Verbose output"),
        strictcli.Flag(name="quiet", type=bool, help="Quiet output"),
    ]),
])
def log(verbose, quiet): ...
```

### Flag dependencies

Three relationship types, all passed via `dependencies=[...]`:

- `CoRequired(flags=["output", "format"])` -- all must appear together, or none
- `Requires(flag="verbose", depends_on="output")` -- one-way dependency
- `Implies(flag="verbose", implies="log_output", value=True)` -- auto-set a bool flag when another is provided; explicit contradictions are parse errors

```python
@app.command("export", help="Export data", dependencies=[
    strictcli.CoRequired(flags=["output", "format"]),
    strictcli.Requires(flag="verbose", depends_on="output"),
    strictcli.Implies(flag="verbose", implies="log_output", value=True),
])
```

### Global flags

App-level flags available to all commands, parsed before and after the command token.

```python
app = strictcli.App("myapp", version="1.0.0", help="My app", flags=[
    strictcli.Flag(name="verbose", type=bool, help="Verbose output"),
])
```

### Passthrough commands

Bypass all parsing -- handler gets raw args plus global flag values.

```python
@app.command("run", help="Run a script", passthrough=True)
def run(args, verbose):
    subprocess.run(args)
```

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
@app.command("internal-debug", help="Debug internals", hidden=True)
def internal_debug(): ...
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

### Schema dump

`--dump-schema` is auto-injected on every app. Writes `.strictcli/schema.json` describing the full CLI structure (commands, flags, args, groups, checks).

### Check system

First-class check/validation framework with double-entry security. Enabled via `checks_path=` pointing to a TOML file.

```python
app = strictcli.App("myapp", version="1.0.0", help="My app", checks_path="checks.toml")

@app.check("lint")
def lint(context):
    return strictcli.CheckResult(status="pass", message="All good")
```

Checks are declared in TOML and registered in code -- both must agree. Auto-registers a `check` command with tag DSL filtering (`--tag "release & !slow"`), JSON output, and dependency resolution.

### Auto-version

`App(name="x", help="...")` without an explicit `version` auto-detects from `importlib.metadata`.

### Tool export

`app.as_tools()` exports non-hidden, non-interactive commands as `Tool` descriptors for LLM agents.

```python
tools = app.as_tools()
# Each Tool has: name, description, parameters (JSON Schema), execute
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
| `CheckResult` | Check execution result |
| `CheckContext` | Protocol for check context |
| `ConfigField` | Typed config file field |

### Decorators

| Decorator | Description |
|-----------|-------------|
| `@app.command(name, help=...)` | Register a command |
| `@strictcli.flag(name, type=, help=...)` | Declare a flag |
| `@strictcli.arg(name, help=...)` | Declare a positional argument |
| `@app.check(name)` | Register a check handler |

### App methods

| Method | Description |
|--------|-------------|
| `app.command(name, help=...)` | Register a command (decorator) |
| `app.group(name, help=...)` | Create a command group |
| `app.deprecate(name, message=...)` | Register a deprecated command |
| `app.run()` | Parse `sys.argv` and execute |
| `app.test(argv)` | Run in-process, return `Result` |
| `app.as_tools()` | Export commands as `Tool` descriptors |
| `app.serve_mcp()` | Run MCP server on stdin/stdout |
| `app.config_field(name, type=, help=...)` | Declare a typed config field |
| `app.check(name)` | Register a check handler (decorator) |
| `app.set_check_context(factory)` | Set the check context factory |

## Design principles

- **Help is mandatory.** Every command, flag, and argument must have help text. Missing help raises `ValueError` at registration time.
- **Four types only.** `str`, `bool`, `int`, `float` -- plus compound `list[T]` and `dict[str, T]`. No magic type coercion.
- **Handler signatures are validated.** Parameter names must match declared flags and args exactly. Extra or missing parameters raise `ValueError`.
- **Registration-time errors.** Misconfigurations fail loud and early, not at parse time.
- **Zero dependencies.** Standard library only.

## See also

- [strictcli monorepo](https://github.com/smm-h/strictcli) -- conformance tests, Go implementation, and project documentation
- [Go implementation](https://github.com/smm-h/strictcli/tree/main/go) -- same semantics, functional options API

## License

MIT
