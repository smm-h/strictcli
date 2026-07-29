---
title: Python Quickstart
description: "Getting started with strictcli in Python: install, create apps, define commands, add flags and args, use groups, and enable config/schema support."
nav_group: "Guides"
nav_order: 2
---

# Python Quickstart

This guide walks through building a CLI application with the Python implementation of strictcli.

## Install

```bash
pip install strictcli
```

Import the package:

```python
import strictcli
```

## Creating an App

Every CLI starts with `App`. The `name`, `version`, and `help` arguments are all required. Empty help text is a hard error.

```python
import strictcli

app = strictcli.App(name="mytool", version="0.1.0", help="A tool that does useful things")

@app.command("hello", help="Print a greeting")
def hello(ctx):
    ctx.info("Hello, world!")

app.run()
```

Running this:

```
$ mytool hello
Hello, world!

$ mytool --help
mytool v0.1.0 -- A tool that does useful things

Commands:
  hello    Print a greeting

$ mytool --version
mytool 0.1.0
```

## Handler Signature

Every command handler receives `ctx` as its first argument. Flag and arg values arrive as keyword arguments (dashes converted to underscores: `--dry-run` becomes `dry_run`).

```python
@app.command("greet", help="Greet someone")
@strictcli.flag("name", type=str, help="Who to greet")
@strictcli.flag("loud", type=bool, default=False, help="Shout the greeting")
def greet(ctx, name, loud):
    msg = f"Hello, {name}!"
    if loud:
        msg = f"HELLO, {name}!!!"
    ctx.info(msg)
```

- `ctx` provides structured output (`ctx.info`, `ctx.warn`, `ctx.error`, `ctx.debug`) and provenance (`ctx.source`).
- Return `int` for an exit code, `None` for exit 0, or `strictcli.outcome(exit_code, data)` for structured output. Any other return type is a hard error.

### Context Methods

| Method | Stream | Purpose |
|--------|--------|---------|
| `ctx.info(msg)` | stdout | Informational messages |
| `ctx.warn(msg)` | stderr | Warnings |
| `ctx.error(msg)` | stderr | Errors |
| `ctx.debug(msg)` | stdout | Debug output |
| `ctx.source(name)` | -- | Provenance of a flag value (`"cli"`, `"env"`, `"config"`, `"default"`, `"implied"`, `"infra"`) |

### Returning Structured Data

Use `strictcli.outcome()` to return structured data. The data is JSON-printed to stdout and captured by `test()` and `call()`.

```python
@app.command("status", help="Show status")
def status(ctx):
    return strictcli.outcome(exit_code=0, data={"healthy": True, "uptime": 3600})
```

```
$ mytool status
{"healthy":true,"uptime":3600}
```

## Flags

Flags are declared with the `@strictcli.flag()` decorator. The `name` and `help` arguments are always required. strictcli supports four scalar types: `str`, `bool`, `int`, and `float`.

### String Flags

```python
@app.command("build", help="Build the project")
@strictcli.flag("output", type=str, help="Output file path")
@strictcli.flag("format", type=str, default="json", help="Output format")
def build(ctx, output, format):
    ctx.info(f"Building to {output} as {format}")
```

A string flag with no `default` is required -- the user must provide it.

### Bool Flags

```python
@app.command("deploy", help="Deploy the app")
@strictcli.flag("verbose", type=bool, default=False, help="Enable verbose output")
@strictcli.flag("watch", type=bool, help="Watch for changes")
def deploy(ctx, verbose, watch):
    if verbose:
        ctx.info("Verbose mode enabled")
```

Bool flags are negatable by default: `--verbose` sets `True`, `--no-verbose` sets `False`. A bool flag with no `default` is required -- the user must pass either `--flag` or `--no-flag` explicitly.

### Int Flags

```python
@strictcli.flag("port", type=int, default=8080, help="Server port")
@strictcli.flag("retries", type=int, help="Number of retries")
```

Integers are parsed strictly: no leading/trailing whitespace, 64-bit signed bounds, no leading zeros.

### Float Flags

```python
@strictcli.flag("threshold", type=float, default=0.5, help="Score threshold")
@strictcli.flag("rate", type=float, help="Rate limit")
```

Float parsing rejects NaN and Inf.

### Flag Options

All available `@strictcli.flag()` parameters:

| Parameter | Description |
|-----------|-------------|
| `name` | Flag name (required). Becomes `--name` on the CLI. |
| `help` | Help text (required). Must be non-empty. |
| `type` | Value type: `str`, `bool`, `int`, or `float` (default: `str`). |
| `default` | Default value. Omit for required flags. |
| `short` | Single-character short form (e.g., `short="o"` for `-o`). |
| `env` | Environment variable name. Precedence: CLI > env > config > default. |
| `choices` | List of allowed values. Not available on bool flags. |
| `validate` | Custom validation function. |
| `repeatable` | If `True`, the flag can appear multiple times, collecting values into a list. |
| `unique` | Requires explicit `True` or `False` when `repeatable=True`. Rejects duplicate values when `True`. |
| `env_separator` | Single character to split env var values for repeatable flags. Required when both `repeatable` and `env` are set. |

### Short Flags

```python
@strictcli.flag("output", short="o", type=str, help="Output file")
@strictcli.flag("verbose", short="v", type=bool, default=False, help="Be verbose")
```

Usage: `-o myfile.txt`, `-v`.

### Choices

Restrict a flag to specific values:

```python
@strictcli.flag("format", type=str, choices=["json", "yaml", "csv"], help="Output format")
@strictcli.flag("level", type=int, choices=[1, 2, 3], help="Compression level")
```

### Environment Variables

Read flag values from the environment:

```python
@strictcli.flag("token", type=str, env="MYTOOL_TOKEN", help="API token")
```

Precedence: CLI > env > config > default. Boolean env values accept `1|true|yes` / `0|false|no` (case-insensitive).

### Required vs Optional

- **Required**: omit the `default` parameter. The user must provide the flag.
- **Optional with default**: set `default=value`.

```python
@strictcli.flag("target", type=str, help="Deploy target")           # required
@strictcli.flag("region", type=str, default="us-east", help="AWS region")  # optional
```

### Repeatable Flags

A repeatable flag can appear multiple times, collecting values into a list:

```python
@app.command("process", help="Process records")
@strictcli.flag("record", type=str, help="A record to process", repeatable=True, unique=False)
def process(ctx, record):
    for r in record:
        ctx.info(f"Processing: {r}")
```

```
$ mytool process --record alpha --record beta --record gamma
Processing: alpha
Processing: beta
Processing: gamma
```

When no occurrences are provided, the default is an empty list. The `unique` parameter is mandatory on repeatable flags: set `unique=True` to reject duplicate values, or `unique=False` to allow them.

You can also use `list[T]` as the type, which is equivalent to `repeatable=True` with the appropriate item type:

```python
@strictcli.flag("port", type=list[int], help="Ports to listen on", unique=False)
```

## Positional Arguments

Use `@strictcli.arg()` to declare positional arguments. Arguments are required by default.

```python
@app.command("deploy", help="Deploy to an environment")
@strictcli.arg("environment", help="Target environment")
@strictcli.arg("version", help="Version to deploy", required=False, default="latest")
def deploy(ctx, environment, version):
    ctx.info(f"Deploying {version} to {environment}")
```

### Arg Parameters

| Parameter | Description |
|-----------|-------------|
| `name` | Argument name (required). |
| `help` | Help text (required). |
| `required` | Whether the argument is required (default: `True`). |
| `default` | Default value (only valid on non-required args). |
| `type` | Type: `str`, `bool`, `int`, or `float` (default: `str`). |
| `variadic` | If `True`, collects all remaining positional values. Must be the last arg. |
| `choices` | List of allowed values. |

### Variadic Arguments

A variadic argument collects all remaining positional values into a list:

```python
@app.command("process", help="Process files")
@strictcli.arg("files", help="Files to process", variadic=True)
def process(ctx, files):
    for f in files:
        ctx.info(f"Processing: {f}")
```

```
$ mytool process a.txt b.txt c.txt
Processing: a.txt
Processing: b.txt
Processing: c.txt
```

Only one variadic argument is allowed, and it must be the last. You can also use `list[T]` as the type for typed variadic args (e.g., `type=list[int], variadic=True`).

## Global Flags

Global flags are available to all commands. Pass them via the `flags` parameter on `App`:

```python
app = strictcli.App(
    name="mytool",
    version="0.1.0",
    help="A useful tool",
    flags=[
        strictcli.Flag(name="verbose", type=bool, default=False, help="Enable verbose output"),
        strictcli.Flag(name="log-level", type=str, default="info",
                       choices=["debug", "info", "warn", "error"], help="Log level"),
    ],
)

@app.command("deploy", help="Deploy the app")
def deploy(ctx, verbose, log_level):
    if verbose:
        ctx.info("Verbose mode enabled")
    ctx.info(f"Log level: {log_level}")
```

Usage: `mytool --verbose deploy` or `mytool deploy --verbose` (global flags can appear before or after the command).

Reserved global flag names that cannot be used: `help`, `h`, `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`.

## Command Groups

Groups organize commands into namespaces. Groups can nest to arbitrary depth.

```python
app = strictcli.App(name="mytool", version="0.1.0", help="Infrastructure tool")

dns = app.group("dns", help="DNS management")

@dns.command("list", help="List DNS records")
def dns_list(ctx):
    ctx.info("Listing records...")

@dns.command("create", help="Create a DNS record")
@strictcli.flag("name", type=str, help="Record name")
def dns_create(ctx, name):
    ctx.info(f"Creating record: {name}")

zone = dns.group("zone", help="Zone management")

@zone.command("list", help="List zones")
def zone_list(ctx):
    ctx.info("Listing zones...")

@zone.command("delete", help="Delete a zone")
@strictcli.flag("name", type=str, help="Zone name")
def zone_delete(ctx, name):
    ctx.info(f"Deleting zone: {name}")
```

Usage:

```
$ mytool dns list
$ mytool dns create --name example.com
$ mytool dns zone list
$ mytool dns zone delete --name example.com
```

## Flag Naming Conventions

strictcli enforces strict flag naming rules at registration time. Violations raise `ValueError`.

### Bare `--force` is banned

The flag name cannot be exactly `"force"`. Use a qualified name that describes what is being forced:

```python
# This raises ValueError:
strictcli.flag("force", type=bool, default=False, help="Force the operation")

# Use a qualified name instead:
strictcli.flag("force-overwrite", type=bool, default=False, help="Overwrite existing files")
strictcli.flag("force-delete", type=bool, default=False, help="Delete without confirmation")
```

### `--no-*` prefix is reserved

Flag names cannot start with `no-`. The `--no-` prefix is auto-generated by the negation system for bool flags:

```python
# This raises ValueError:
strictcli.flag("no-cache", type=bool, default=False, help="Disable caching")

# Use a positive name instead:
strictcli.flag("cache", type=bool, default=True, help="Enable caching")
# Users pass --no-cache to disable
```

### `--dry-run` is the standard name

Use `--dry-run` for dry-run flags (not `--dry`).

### Help text is mandatory

Every flag, arg, command, group, and app must have non-empty help text. Missing help raises `ValueError` at registration time.

## Mutex Groups

Declare mutually exclusive flags -- at most one may be provided:

```python
@app.command("output", help="Produce output", mutex=[
    strictcli.MutexGroup(flags=[
        strictcli.Flag(name="file", type=str, help="Write to file"),
        strictcli.Flag(name="stdout-only", type=bool, default=False, help="Write to stdout"),
    ]),
])
def output(ctx, **kwargs):
    pass
```

## Dependencies

Declare relationships between flags using the `dependencies` parameter:

```python
@app.command("deploy", help="Deploy the app", dependencies=[
    # --region requires --target to be present
    strictcli.Requires(flag="region", depends_on="target"),
    # --target and --region must both appear or neither
    strictcli.CoRequired(flags=["target", "region"]),
    # --auto-approve implies --dry-run=False
    strictcli.Implies(flag="auto-approve", implies="dry-run", value=False),
])
@strictcli.flag("target", type=str, help="Deploy target")
@strictcli.flag("region", type=str, help="Target region")
@strictcli.flag("dry-run", type=bool, default=False, help="Simulate the deploy")
@strictcli.flag("auto-approve", type=bool, default=False, help="Skip confirmation")
def deploy(ctx, target, region, dry_run, auto_approve):
    ctx.info(f"Deploying to {target} in {region}")
```

| Dependency | Behavior |
|------------|----------|
| `Requires(flag, depends_on)` | If `flag` is provided, `depends_on` must also be provided. |
| `CoRequired(flags)` | All listed flags must appear together, or none of them. |
| `Implies(flag, implies, value)` | When `flag` is provided, automatically set `implies` to `value`. |

## Flag Sets

Reuse the same set of flags across multiple commands:

```python
auth_flags = strictcli.FlagSet(name="auth", flags=[
    strictcli.Flag(name="token", type=str, env="MYTOOL_TOKEN", help="API token"),
    strictcli.Flag(name="region", type=str, default="us-east", help="API region"),
])

@app.command("list", help="List resources", flag_sets=[auth_flags])
def list_cmd(ctx, token, region):
    ctx.info(f"Listing in {region}")

@app.command("delete", help="Delete a resource", flag_sets=[auth_flags])
@strictcli.flag("resource-id", type=str, help="Resource to delete")
def delete_cmd(ctx, token, region, resource_id):
    ctx.info(f"Deleting {resource_id}")
```

## Config File Support

Pass `config=True` to `App` to enable automatic config file loading and register `config show/set/path/edit/init` subcommands.

```python
app = strictcli.App(
    name="mytool",
    version="0.1.0",
    help="A configurable tool",
    config=True,
    env_prefix="MYTOOL",
)

@app.command("run", help="Run the tool")
@strictcli.flag("port", type=int, default=8080, env="MYTOOL_PORT", help="Server port")
def run(ctx, port):
    ctx.info(f"Listening on port {port}")
```

Config files live at `~/.config/mytool/config.json` by default. Value precedence: CLI > env > config > default.

### Config format

Default format is JSON. Use TOML with `config_format="toml"`:

```python
app = strictcli.App(
    name="mytool",
    version="0.1.0",
    help="A configurable tool",
    config=True,
    config_format="toml",
)
```

### Auto-registered config commands

When config is enabled, these subcommands are registered automatically:

- `mytool config show` -- display current config with value sources
- `mytool config set <key> <value>` -- set a config value
- `mytool config path` -- print the config file path
- `mytool config edit` -- open the config file in `$EDITOR`
- `mytool config init` -- create the config file with defaults

### Config path override

Override the config path at the CLI level with `--config <path>`, or at construction with `config_path=`:

```python
app = strictcli.App(
    name="mytool",
    version="0.1.0",
    help="A configurable tool",
    config=True,
    config_path="~/.mytool/config.json",
)
```

### Config fields

Declare typed config-only fields (not backed by CLI flags) with `config_field()`:

```python
app.config_field("serve.port", type=int, help="Default server port", default=8080)
app.config_field("serve.host", type=str, help="Bind address", default="localhost")
app.config_field("api_key", type=str, help="API key")  # required -- no default
```

### Hermetic mode

`--hermetic` is a reserved global flag on every app. It skips config file loading and env var resolution entirely. Values come only from CLI tokens, declared defaults, and infrastructure roots.

## Schema Dump

Every strictcli app automatically supports `--dump-schema`. It writes a JSON file describing the full CLI structure to `.strictcli/schema.json` and prints the path:

```
$ mytool --dump-schema
.strictcli/schema.json
```

The schema includes all commands, flags, args, groups, and their metadata. It is used by tools like rlsbl to keep documentation in sync with the CLI surface.

## Testing

Use `app.test(argv)` to run the CLI in-process and capture output:

```python
def test_greet():
    app = strictcli.App(name="mytool", version="0.1.0", help="test app")

    @app.command("greet", help="Say hello")
    @strictcli.flag("name", type=str, help="Who to greet")
    def greet(ctx, name):
        ctx.info(f"Hello, {name}!")

    r = app.test(["greet", "--name", "Alice"])
    assert r.exit_code == 0
    assert "Hello, Alice!" in r.stdout
```

The `Result` object contains `stdout`, `stderr`, `exit_code`, and `data` (structured data from `outcome()`).

### Programmatic Invocation

Use `app.call(command_path, **kwargs)` to invoke a command in-process with pre-typed values, bypassing CLI parsing and env resolution:

```python
result = app.call("deploy", target="staging", region="us-west")
```

The `command_path` is dot-separated for nested commands: `"dns.zone.create"`. Failures raise `InvokeError`.

## Deprecated Commands

Register retired commands that print a message and exit 1:

```python
app.deprecate("old-deploy", message="Use 'deploy' instead. See https://example.com/migration")
```

Deprecated commands appear in help under a `Deprecated:` section.

## Passthrough Commands

Passthrough commands bypass all flag/arg parsing and forward raw args to the handler:

```python
@app.command("exec", help="Execute a command", passthrough=strictcli.Passthrough(
    handler=lambda ctx, name, args, globals: (
        ctx.info(f"Running: {name} {args}") or 0
    ),
))
def exec_placeholder():
    pass  # handler is in the Passthrough object
```

The passthrough handler receives `(ctx, name, args, globals)` where `args` is the raw list of tokens and `globals` is a dict of global flag values.

## Error Handling

strictcli distinguishes between two kinds of errors:

- **Registration-time errors** (`ValueError`): raised when declaring apps, commands, flags, or args with invalid configuration (missing help text, banned flag names, type mismatches). These are programmer errors caught at startup.
- **Parse-time errors**: printed to stderr and exit 1. Include unknown flags, missing required values, type coercion failures, mutex violations, and dependency errors.

```
$ mytool deploy --unknown-flag
error: unknown flag "--unknown-flag"
try 'mytool deploy --help'

$ mytool deploy
error: missing required flag "--target"
try 'mytool deploy --help'
```

## Full Example

```python
import strictcli

app = strictcli.App(
    name="deploy-tool",
    version="0.1.0",
    help="Deployment management tool",
    config=True,
    env_prefix="DEPLOY",
    flags=[
        strictcli.Flag(name="verbose", type=bool, default=False, help="Enable verbose output"),
    ],
)

@app.command("status", help="Show deployment status")
@strictcli.flag("environment", short="e", type=str, default="production",
                choices=["production", "staging", "dev"], help="Target environment")
def status(ctx, verbose, environment):
    if verbose:
        ctx.info(f"Checking status for environment: {environment}")
    return strictcli.outcome(exit_code=0, data={
        "environment": environment,
        "status": "healthy",
    })

svc = app.group("service", help="Service management")

@svc.command("restart", help="Restart a service")
@strictcli.flag("name", type=str, help="Service name")
@strictcli.flag("timeout", type=int, default=30, help="Shutdown timeout in seconds")
def restart(ctx, verbose, name, timeout):
    ctx.info(f"Restarting {name} (timeout: {timeout}s)")

app.run()
```

Usage:

```
$ deploy-tool status -e staging
{"environment":"staging","status":"healthy"}

$ deploy-tool --verbose service restart --name api --timeout 60
Restarting api (timeout: 60s)

$ deploy-tool config show
$ deploy-tool --dump-schema
```
