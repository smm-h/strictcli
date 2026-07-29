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

Every CLI starts with `App`, which takes the application name, version string,
and help text as required arguments. Empty help text is a hard error -- strictcli
enforces self-documenting apps from the first line of code. Additional options
like `config=True`, `env_prefix=`, and `config_format=` are passed as keyword
arguments.

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

Every command handler receives `ctx` as its first argument, providing structured
output methods and provenance introspection. Flag and arg values arrive as
keyword arguments with dashes converted to underscores (`--dry-run` becomes
`dry_run`). The return value must be `int` (exit code), `None` (exit 0), or
`strictcli.outcome()` for structured data -- any other return type is a hard
error.

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

Use `strictcli.outcome()` to return structured data from a command handler. The
data is JSON-printed to stdout and captured by `test()` and `call()` for
programmatic consumption. The `outcome()` factory is the only way to construct
a branded `Outcome` -- hand-forging the return value is rejected at runtime.

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

Flags are declared with the `@strictcli.flag()` decorator, which attaches flag
metadata to the handler function before command registration. The `name` and
`help` arguments are always required. strictcli supports four scalar types:
`str` (default), `bool`, `int`, and `float`, plus compound types `list[T]` and
`dict[str, T]` for repeatable and key-value flags.

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

All available `@strictcli.flag()` parameters are listed below. The `name` and
`help` parameters are always required and must be non-empty strings. The
remaining parameters control type, defaults, choices, environment variable
binding, short aliases, custom validation callbacks, and repeat semantics
including uniqueness enforcement and env var splitting for repeatable flags:

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

Restrict a flag to specific values using the `choices` parameter. Values not in
the choices list produce a parse error listing all allowed values. All choice
values must match the declared flag type, and bool flags cannot have choices:

```python
@strictcli.flag("format", type=str, choices=["json", "yaml", "csv"], help="Output format")
@strictcli.flag("level", type=int, choices=[1, 2, 3], help="Compression level")
```

### Environment Variables

Read flag values from the environment using the `env` parameter. Environment
variables sit between CLI tokens and config file values in the resolution
cascade (CLI > env > config > default), and are skipped entirely under
`--hermetic` mode:

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

A repeatable flag can appear multiple times on the command line, collecting
values into a list. Repeatable flags are never required and default to an empty
list. The `unique` parameter is mandatory: set `unique=True` to reject duplicate
values, or `unique=False` to allow them:

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

Use `@strictcli.arg()` to declare positional arguments that are consumed in
declaration order after all flags have been parsed. Arguments are required by
default. Optional arguments use `required=False` and may declare a default
value.

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

A variadic argument collects all remaining positional values into a list. It
must be the last positional argument in the command's declaration, and only one
variadic argument is allowed per command. A variadic arg with `required=True`
(the default) requires at least one value:

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

Global flags are available to all commands and can appear before or after the
command name in argv. Pass them via the `flags` parameter on `App`. Global flag
names cannot collide with reserved framework names like `help`, `version`,
`dump-schema`, `mcp`, `config`, or `hermetic`:

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

Groups organize commands into namespaces, creating a hierarchical command
structure like `mytool dns zone list`. Groups can nest to arbitrary depth, and
each group requires a name and help text. When a group is reached without a
subcommand, the group's help text is displayed.

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

strictcli enforces strict flag naming rules at registration time to prevent
ambiguous flag names and protect the negation namespace. Violations raise
`ValueError` with a descriptive message explaining what is wrong and how to fix
it. These rules are identical across all three implementations.

### Bare `--force` is banned

The flag name cannot be exactly `"force"` because a generic force flag lets
automation bypass guardrails without specifying what is being forced. Use a
qualified name that describes the specific action being forced, making the
intent explicit and auditable:

```python
# This raises ValueError:
strictcli.flag("force", type=bool, default=False, help="Force the operation")

# Use a qualified name instead:
strictcli.flag("force-overwrite", type=bool, default=False, help="Overwrite existing files")
strictcli.flag("force-delete", type=bool, default=False, help="Delete without confirmation")
```

### `--no-*` prefix is reserved

Flag names cannot start with `no-` because the `--no-` prefix is auto-generated
by the negation system for boolean flags. Allowing user-defined flags in this
namespace would create double-negation ambiguity where `--no-no-cache` becomes
the negation form of a flag named `no-cache`:

```python
# This raises ValueError:
strictcli.flag("no-cache", type=bool, default=False, help="Disable caching")

# Use a positive name instead:
strictcli.flag("cache", type=bool, default=True, help="Enable caching")
# Users pass --no-cache to disable
```

### `--dry-run` is the standard name

Use `--dry-run` for dry-run flags (not `--dry` or any other abbreviation). This
is a naming convention enforced across all strictcli projects to ensure
consistent flag names that agents and users can predict without checking help
text.

### Help text is mandatory

Every flag, arg, command, group, and app must have non-empty help text. Missing
or empty help raises `ValueError` at registration time with no opt-out. This
ensures that every strictcli application is self-documenting and users always
have access to meaningful help for every flag and command.

## Mutex Groups

Declare mutually exclusive flags using `MutexGroup` via the `mutex` parameter.
At most one flag in the group may have a value from an explicit source (CLI, env,
or config). A mutex group must contain at least 2 flags, and flags in a mutex
group with no default get `None` instead of being required:

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

Declare relationships between flags using the `dependencies` parameter. Three
dependency types are available: `Requires` (one-way dependency), `CoRequired`
(must appear together or not at all), and `Implies` (automatically sets a target
flag when a trigger is provided):

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

Reuse the same set of flags across multiple commands by grouping them into a
named `FlagSet`. Each command that uses a flag set receives all its flags as if
they were declared directly on the command, including type checking, env var
binding, and constraint validation:

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

Pass `config=True` to `App` to enable automatic config file loading from the
XDG config directory and register five `config` subcommands (`show`, `set`,
`path`, `edit`, `init`) for managing the configuration file. Config values
participate in the flag resolution cascade between env vars and defaults.

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

Default format is JSON, which uses the standard library parser. Use TOML with
`config_format="toml"` for human-editable configuration files with comments and
section headers. TOML parsing is strict and rejects 6 TOML-1.1-only constructs
(including backslash-e escapes and trailing commas in inline tables) to maintain
byte-level parity across the Python, Go, and TypeScript implementations:

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

When config is enabled, these five subcommands are registered automatically
under a `config` group. They provide a complete config management interface
without any additional code, covering display of current values with their
provenance sources, in-place modification, path inspection, editor integration,
and initialization of the config file with default values:

- `mytool config show` -- display current config with value sources
- `mytool config set <key> <value>` -- set a config value
- `mytool config path` -- print the config file path
- `mytool config edit` -- open the config file in `$EDITOR`
- `mytool config init` -- create the config file with defaults

### Config path override

Override the config path at the CLI level with `--config <path>` (a reserved
global flag), or at construction time with `config_path=`. The CLI override
takes precedence over the construction-time path, which takes precedence over
the default XDG location. Using `--config` with a missing file is a hard error:

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

Declare typed config-only fields (not backed by CLI flags) with
`config_field()`. Config fields are validated at runtime when their bound
commands are dispatched: required fields must be present in the config file with
the correct type:

```python
app.config_field("serve.port", type=int, help="Default server port", default=8080)
app.config_field("serve.host", type=str, help="Bind address", default="localhost")
app.config_field("api_key", type=str, help="API key")  # required -- no default
```

### Hermetic mode

`--hermetic` is a reserved global flag on every app. It skips config file loading and env var resolution entirely. Values come only from CLI tokens, declared defaults, and infrastructure roots.

## Schema Dump

Every strictcli app automatically supports `--dump-schema`, a reserved flag
that writes a JSON file describing the full CLI structure to
`.strictcli/schema.json` and prints the absolute path to stdout. The schema
includes all commands, flags, args, groups, constraints, and config field
declarations:

```
$ mytool --dump-schema
.strictcli/schema.json
```

The schema includes all commands, flags, args, groups, and their metadata. It is used by tools like rlsbl to keep documentation in sync with the CLI surface.

## Testing

Use `app.test(argv)` to run the CLI in-process and capture output without
shelling out. The `Result` object contains `stdout`, `stderr`, `exit_code`, and
`data` (structured data from `outcome()`). This is the standard way to test
strictcli apps:

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

Use `app.call(command_path, **kwargs)` to invoke a command in-process with
pre-typed values, bypassing CLI parsing, env var resolution, and config file
loading. This is useful for testing, automation, and composing commands
programmatically without constructing argv strings:

```python
result = app.call("deploy", target="staging", region="us-west")
```

The `command_path` is dot-separated for nested commands: `"dns.zone.create"`. Failures raise `InvokeError`.

## Deprecated Commands

Register retired commands that print a deprecation message to stderr and exit
with code 1. Deprecated commands appear in help output under a `Deprecated:`
section, giving users visibility into the migration path:

```python
app.deprecate("old-deploy", message="Use 'deploy' instead. See https://example.com/migration")
```

Deprecated commands appear in help under a `Deprecated:` section.

## Passthrough Commands

Passthrough commands bypass all flag and argument parsing and forward raw args
directly to the handler. They are useful for wrapping external tools where the
argument format is not known in advance. Passthrough commands cannot have flags,
args, flag sets, or mutex groups:

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

strictcli distinguishes between two kinds of errors, each handled differently.
Registration-time errors are programmer mistakes caught at startup, while
parse-time errors are user input mistakes caught during command-line parsing.
Both produce specific, actionable messages:

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
