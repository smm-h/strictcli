---
title: Python Quickstart
description: "Build CLIs with strictcli in Python: apps, mandatory effect classification, flags, args, groups, the reserved flag quartet, and consequential confirmations."
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

```python validate
import strictcli

app = strictcli.App(name="mytool", version="0.1.0", help="A tool that does useful things")

@app.command("hello", help="Print a greeting", effect="read_only")
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

## Command Classification

Every command must declare what it does to the world. The `effect` keyword is
mandatory on `@app.command()` and takes exactly one of two values -- there is no
default, and a command registered without it raises `ValueError` at registration
time:

| Value | Meaning |
|-------|---------|
| `effect="read_only"` | The command changes nothing. It never prompts, and calling a mutating member of the effects handle from it is a hard error at call time. |
| `effect="mutating"` | The command changes something. It participates in `--dry-run`, where its effects are recorded instead of performed. |

```python
@app.command("status", help="Show deployment status", effect="read_only")
def status(ctx):
    ctx.info("healthy")

@app.command("deploy", help="Deploy the app", effect="mutating")
def deploy(ctx):
    ctx.info("deploying")
```

Classification answers one question -- "should a dry run record this rather than
perform it?" It is deliberately **not** the same question as "is this dangerous
enough to interrupt someone for?", which is what
[`consequential`](#consequential-commands-and-the-confirm-protocol) answers. A
`mutating` command does not prompt unless it also declares itself
`consequential`.

Classification is a property of the command, so it is emitted in `--dump-schema`
output on every command entry and can be asserted against by check gates.
Deprecated commands are exempt: they have no handler, execute nothing, and
passing `effect=` to `app.deprecate()` is a registration-time error.

## Handler Signature

Every command handler receives `ctx` as its first argument, providing structured
output methods and provenance introspection. Flag and arg values arrive as
keyword arguments with dashes converted to underscores (`--log-file` becomes
`log_file`). The return value must be `int` (exit code), `None` (exit 0), or
`strictcli.outcome()` for structured data -- any other return type is a hard
error.

```python
@app.command("greet", help="Greet someone", effect="read_only")
@strictcli.flag("name", type=str, help="Who to greet")
@strictcli.flag("loud", type=bool, default=False, help="Shout the greeting")
def greet(ctx, name, loud):
    msg = f"Hello, {name}!"
    if loud:
        msg = f"HELLO, {name}!!!"
    ctx.info(msg)
```

- `ctx` provides structured output (`ctx.info`, `ctx.warn`, `ctx.error`, `ctx.debug`), provenance (`ctx.source`), the four reserved-quartet values, and the effects handle (`ctx.effects`).
- Return `int` for an exit code, `None` for exit 0, or `strictcli.outcome(exit_code, data)` for structured output. Any other return type is a hard error.

### Context Methods

| Method | Stream | Purpose |
|--------|--------|---------|
| `ctx.info(msg)` | stdout | Informational messages (suppressed under `--quiet`) |
| `ctx.warn(msg)` | stderr | Warnings (never suppressed) |
| `ctx.error(msg)` | stderr | Errors (never suppressed) |
| `ctx.debug(msg)` | stdout | Debug output (shown only under `--verbose`) |
| `ctx.source(name)` | -- | Provenance of a flag value (`"cli"`, `"env"`, `"config"`, `"default"`, `"implied"`, `"infra"`) |

### Context Properties

The four reserved-quartet flags are never declared by you and never arrive as
handler kwargs -- the framework parses them and delivers them on `ctx`:

| Property | Set by |
|----------|--------|
| `ctx.dry_run` | `--dry-run` |
| `ctx.approve_consequential` | `--approve-consequential` |
| `ctx.quiet` | `--quiet` |
| `ctx.verbose` | `--verbose` |

`ctx.effects` is the recorded-effects handle. Under `--dry-run` its operations
are recorded and rendered as a would-do log instead of being performed, which is
what makes a preview honest.

### Returning Structured Data

Use `strictcli.outcome()` to return structured data from a command handler. The
data is JSON-printed to stdout and captured by `test()` and `call()` for
programmatic consumption. The `outcome()` factory is the only way to construct
a branded `Outcome` -- hand-forging the return value is rejected at runtime.

```python
@app.command("status", help="Show status", effect="read_only")
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
@app.command("build", help="Build the project", effect="mutating")
@strictcli.flag("output", type=str, help="Output file path")
@strictcli.flag("format", type=str, default="json", help="Output format")
def build(ctx, output, format):
    ctx.info(f"Building to {output} as {format}")
```

A string flag with no `default` is required -- the user must provide it.

### Bool Flags

```python
@app.command("deploy", help="Deploy the app", effect="mutating")
@strictcli.flag("cache", type=bool, default=True, help="Reuse the build cache")
@strictcli.flag("watch", type=bool, help="Watch for changes")
def deploy(ctx, cache, watch):
    if not cache:
        ctx.info("Cache disabled")
```

Bool flags are negatable by default: `--cache` sets `True`, `--no-cache` sets `False`. A bool flag with no `default` is required -- the user must pass either `--flag` or `--no-flag` explicitly.

Note that `verbose` and `quiet` are **not** available as flag names: they belong
to the [reserved quartet](#the-reserved-flag-quartet) and arrive on `ctx`
instead.

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
@strictcli.flag("recursive", short="r", type=bool, default=False, help="Recurse into subdirectories")
```

Usage: `-o myfile.txt`, `-r`.

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
@app.command("process", help="Process records", effect="read_only")
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
@app.command("deploy", help="Deploy to an environment", effect="mutating")
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
@app.command("process", help="Process files", effect="read_only")
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
`dump-schema`, `mcp`, `config`, or `hermetic`, nor with the reserved quartet:

```python
app = strictcli.App(
    name="mytool",
    version="0.1.0",
    help="A useful tool",
    flags=[
        strictcli.Flag(name="color", type=bool, default=True, help="Colorize output"),
        strictcli.Flag(name="log-level", type=str, default="info",
                       choices=["debug", "info", "warn", "error"], help="Log level"),
    ],
)

@app.command("deploy", help="Deploy the app", effect="mutating")
def deploy(ctx, color, log_level):
    if not color:
        ctx.info("Color disabled")
    ctx.info(f"Log level: {log_level}")
```

Usage: `mytool --no-color deploy` or `mytool deploy --no-color` (global flags can appear before or after the command).

Reserved global flag names that cannot be used: `help`, `h`, `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`, plus the reserved quartet `dry-run`, `approve-consequential`, `quiet`, `verbose`. The name `yes` is banned outright -- the confirmation skip is `--approve-consequential`.

## Command Groups

Groups organize commands into namespaces, creating a hierarchical command
structure like `mytool dns zone list`. Groups can nest to arbitrary depth, and
each group requires a name and help text. When a group is reached without a
subcommand, the group's help text is displayed.

```python
app = strictcli.App(name="mytool", version="0.1.0", help="Infrastructure tool")

dns = app.group("dns", help="DNS management")

@dns.command("list", help="List DNS records", effect="read_only")
def dns_list(ctx):
    ctx.info("Listing records...")

@dns.command("create", help="Create a DNS record", effect="mutating")
@strictcli.flag("name", type=str, help="Record name")
def dns_create(ctx, name):
    ctx.info(f"Creating record: {name}")

zone = dns.group("zone", help="Zone management")

@zone.command("list", help="List zones", effect="read_only")
def zone_list(ctx):
    ctx.info("Listing zones...")

@zone.command("delete", help="Delete a zone", effect="mutating", consequential=True)
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

### The reserved flag quartet

Four flag names are owned by the framework and cannot be declared at any level --
not as app global flags, not as command flags, not inside a flag set, not inside
a mutex group:

| Flag | Delivered as | Meaning |
|------|-------------|---------|
| `--dry-run` | `ctx.dry_run` | Record effects instead of performing them, then print the would-do log |
| `--approve-consequential` | `ctx.approve_consequential` | Answer the confirm prompt in advance |
| `--quiet` | `ctx.quiet` | Suppress `ctx.info` output; warnings and errors still print |
| `--verbose` | `ctx.verbose` | Enable `ctx.debug` output |

```python
# Every one of these raises ValueError:
strictcli.flag("dry-run", type=bool, default=False, help="Simulate the run")
strictcli.flag("verbose", type=bool, default=False, help="Be verbose")
strictcli.flag("quiet", type=bool, default=False, help="Be quiet")
```

The error message is `flag name 'dry-run' is reserved by the framework
(dry-run, approve-consequential, quiet, verbose)`. The name `yes` is banned
outright with its own message pointing at `--approve-consequential`, so that a
private `--yes` cannot restate the confirmation skip in a different spelling.

All four are recognized anywhere in argv: `mytool deploy --dry-run` and
`mytool --dry-run deploy` are equivalent. Two boundaries stop the scan -- a bare
`--` (everything after it is data) and a passthrough command's name (its args
are forwarded to the child byte-for-byte).

### Refusing `--dry-run` with `dry_run_supported`

`--dry-run` works on every `mutating` command by default: its effects are
recorded rather than performed. Some commands cannot honor that honestly --
their effects escape the effects handle, or their later steps read state that
their earlier (recorded, therefore un-performed) steps would have written. Such
a command declares `dry_run_supported=False` with a mandatory
`dry_run_unsupported_reason`:

```python
@app.command(
    "migrate",
    help="Run pending database migrations",
    effect="mutating",
    dry_run_supported=False,
    dry_run_unsupported_reason=(
        "each migration reads the schema the previous one wrote, "
        "so a recorded run would report the wrong pending set"
    ),
)
def migrate(ctx):
    ...
```

`--dry-run` is then refused at parse time rather than rendering a preview that
would lie:

```
$ mytool migrate --dry-run
error: --dry-run is not supported by command 'migrate': each migration reads the schema the previous one wrote, so a recorded run would report the wrong pending set
```

Three guardrails apply at registration time:

- `dry_run_supported=False` on a `read_only` command is an error -- a command that changes nothing has no effects a preview could misrepresent.
- `dry_run_supported=False` without a non-empty reason is an error -- say what a preview cannot honestly show.
- A `dry_run_unsupported_reason` without `dry_run_supported=False` is an error -- there is nothing to explain while dry run is supported.

The reason also appears in the command's help under a `Dry run:` section, and in
`--dump-schema` output as the pair `dry_run_supported` / `dry_run_unsupported_reason`.
Both keys are emitted only when declared, so a schema entry without them means
dry run is supported. `--help` always beats the refusal: asking what a command
does is never answered with a refusal to preview it.

## Consequential Commands and the Confirm Protocol

Classification says whether a dry run should record rather than perform.
`consequential` says something different: that these effects are worth
interrupting a human for. It is the **only** thing that makes the framework
prompt -- a plain `mutating` command never does.

```python
@app.command("destroy", help="Destroy the cluster", effect="mutating", consequential=True)
@strictcli.arg("cluster", help="Cluster to destroy")
def destroy(ctx, cluster):
    ctx.info(f"Destroying {cluster}")
```

Before dispatching, the framework prints the prompt to stderr and reads one line
from stdin:

```
$ mytool destroy prod
about to run consequential command 'destroy'. Proceed? [y/N]
```

Only `y` or `Y` proceeds. Anything else prints `aborted` to stderr and exits 1.

Two things skip the prompt, and neither disables anything else:

- `--approve-consequential` -- the operator answered in advance. This is what automation and CI pass.
- `--dry-run` -- nothing is being performed, so there is nothing to confirm.

When stdin is not a TTY and neither flag was passed, the framework refuses
rather than hanging or silently proceeding:

```
$ mytool destroy prod < /dev/null
error: stdin is not interactive; pass --approve-consequential to confirm
```

The prompt never fires on the programmatic paths, which have no TTY contract.
`app.test()` behaves as if `--approve-consequential` were passed; `app.call()`
(and `acall()`, and the MCP server) take the consent from the call instead and
refuse a consequential command without it:

```python
# Raises InvokeError:
#   command 'destroy' is consequential: pass approve_consequential to confirm
app.call("destroy", env="prod")

# Proceeds
app.call("destroy", approve_consequential=True, env="prod")
```

Over MCP the same consent is a top-level `tools/call` param, a sibling of
`name` and `arguments`, never a member of `arguments`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"destroy","arguments":{"env":"prod"},"approve_consequential":true}}
```

This is not human approval and is not meant to be: it makes the caller state,
in the call, that it is proceeding without a human. Tool descriptors and MCP
`tools/list` publish `effect` and `consequential` beside the argument schema so
a caller can see the requirement before it calls. There is no bypass flag:
`--approve-consequential` answers the prompt and does nothing else. A `read_only` command cannot be
declared consequential -- a command that changes nothing has nothing to confirm --
and trying raises `ValueError` at registration time.

A consequential passthrough command is not exempt. The framework knows *less*
about what is about to happen there, not more.

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
@app.command("output", help="Produce output", effect="read_only", mutex=[
    strictcli.MutexGroup(flags=[
        strictcli.Flag(name="file", type=str, help="Write to file"),
        strictcli.Flag(name="stdout-only", type=bool, default=False, help="Write to stdout"),
    ]),
])
def output(ctx, file, stdout_only):
    if file is not None:
        ctx.info(f"Writing to {file}")
```

Name every parameter explicitly. A handler that accepts `**kwargs` without the
command declaring `forwarding=strictcli.Forwarding(reason=...)` is a
registration-time error -- an unnamed parameter bag hides which flags a handler
actually consumes.

## Dependencies

Declare relationships between flags using the `dependencies` parameter. Three
dependency types are available: `Requires` (one-way dependency), `CoRequired`
(must appear together or not at all), and `Implies` (automatically sets a target
flag when a trigger is provided):

```python
@app.command("deploy", help="Deploy the app", effect="mutating", dependencies=[
    # --region requires --target to be present
    strictcli.Requires(flag="region", depends_on="target"),
    # --target and --region must both appear or neither
    strictcli.CoRequired(flags=["target", "region"]),
    # --canary implies --wait=True
    strictcli.Implies(flag="canary", implies="wait", value=True),
])
@strictcli.flag("target", type=str, help="Deploy target")
@strictcli.flag("region", type=str, help="Target region")
@strictcli.flag("canary", type=bool, default=False, help="Roll out to the canary fleet first")
@strictcli.flag("wait", type=bool, default=False, help="Block until the rollout settles")
def deploy(ctx, target, region, canary, wait):
    ctx.info(f"Deploying to {target} in {region}")
```

Dependencies cannot reference the reserved quartet: `dry-run` is not a flag you
declare, so it cannot be a `Requires` target or an `Implies` subject.

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

@app.command("list", help="List resources", effect="read_only", flag_sets=[auth_flags])
def list_cmd(ctx, token, region):
    ctx.info(f"Listing in {region}")

@app.command("delete", help="Delete a resource", effect="mutating",
             consequential=True, flag_sets=[auth_flags])
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

@app.command("run", help="Run the tool", effect="read_only")
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

    @app.command("greet", help="Say hello", effect="read_only")
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
@app.command("exec", help="Execute a command", effect="mutating",
             passthrough=strictcli.Passthrough(
    handler=lambda ctx, name, args, globals: (
        ctx.info(f"Running: {name} {args}") or 0
    ),
))
def exec_placeholder():
    pass  # handler is in the Passthrough object
```

The passthrough handler receives `(ctx, name, args, globals)` where `args` is the raw list of tokens and `globals` is a dict of global flag values.

A passthrough command is classified like any other command, and may declare
itself `consequential`. Because its args are forwarded to the child
byte-for-byte, the reserved quartet is not scanned after the passthrough
command's name: `mytool exec deploy --dry-run` passes `--dry-run` to the child.

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

```python validate
import strictcli

app = strictcli.App(
    name="deploy-tool",
    version="0.1.0",
    help="Deployment management tool",
    config=True,
    env_prefix="DEPLOY",
    flags=[
        strictcli.Flag(name="color", type=bool, default=True, help="Colorize output"),
    ],
)

@app.command("status", help="Show deployment status", effect="read_only")
@strictcli.flag("environment", short="e", type=str, default="production",
                choices=["production", "staging", "dev"], help="Target environment")
def status(ctx, color, environment):
    ctx.debug(f"Checking status for environment: {environment}")
    return strictcli.outcome(exit_code=0, data={
        "environment": environment,
        "status": "healthy",
    })

svc = app.group("service", help="Service management")

@svc.command("restart", help="Restart a service", effect="mutating", consequential=True)
@strictcli.flag("name", type=str, help="Service name")
@strictcli.flag("timeout", type=int, default=30, help="Shutdown timeout in seconds")
def restart(ctx, color, name, timeout):
    ctx.info(f"Restarting {name} (timeout: {timeout}s)")

app.run()
```

Usage:

```
$ deploy-tool status -e staging
{"environment":"staging","status":"healthy"}

$ deploy-tool --verbose status -e staging
Checking status for environment: staging
{"environment":"staging","status":"healthy"}

$ deploy-tool service restart --name api --timeout 60
about to run consequential command 'service restart'. Proceed? [y/N] y
Restarting api (timeout: 60s)

$ deploy-tool service restart --name api --approve-consequential
Restarting api (timeout: 30s)

$ deploy-tool config show
$ deploy-tool --dump-schema
```
