---
title: Flag System
description: "Complete guide to strictcli's flag and argument system: types, defaults, boolean negation, repeatable flags, naming rules, positional arguments, and the context object."
nav_group: "Guides"
nav_order: 3
---

# Flag System

strictcli's flag system is strict by design. Every flag must have help text, every type must be explicit, and every default must be deliberate. This guide covers the full flag and argument system using Python examples. The Go and TypeScript implementations have identical semantics (see the quickstart guides for language-specific syntax).

## Flag types

strictcli supports exactly four scalar types: `str`, `bool`, `int`, and `float`. There is no implicit type inference -- every flag declares its type explicitly.

```python
@app.command("deploy", help="deploy the application")
@strictcli.flag("target", type=str, help="deployment target")
@strictcli.flag("verbose", type=bool, default=False, help="enable verbose output")
@strictcli.flag("replicas", type=int, default=3, help="number of replicas")
@strictcli.flag("threshold", type=float, default=0.95, help="success threshold")
def deploy(ctx, target, verbose, replicas, threshold):
    ...
```

### String flags

String flags (`type=str`, the default) take a value from the next token or via `--flag=value` syntax.

String flags support `@-prefix` resolution: `@path` reads the value from a file, `@-` reads from stdin (once per invocation), and `@@` is a literal `@` escape.

```
mytool deploy --target @config/target.txt
echo "production" | mytool deploy --target @-
mytool deploy --target @@literal-at-sign
```

### Boolean flags

Boolean flags (`type=bool`) do not take a value argument. `--flag` sets it to `True`; `--no-flag` sets it to `False`. The `--flag=value` form is rejected.

```
mytool deploy --verbose        # verbose=True
mytool deploy --no-verbose     # verbose=False
```

### Integer flags

Integer flags (`type=int`) use strict parsing: no leading/trailing whitespace, no leading zeros, 64-bit signed bounds. The value comes from the next token or `--flag=value`.

### Float flags

Float flags (`type=float`) also use strict parsing. NaN and Inf are rejected at parse time. All three implementations use a canonical decimal form (SCF) that produces identical output byte-for-byte.

## Required vs optional flags

A flag without a default is required. A flag with a default is optional. There is no `required=True` parameter -- the presence or absence of a default is the sole mechanism.

```python
# Required: no default, must be passed on every invocation
@strictcli.flag("target", type=str, help="deployment target")

# Optional: has a default, may be omitted
@strictcli.flag("replicas", type=int, default=3, help="number of replicas")
```

In help output, required flags show `[required]` and optional flags show `[default: <value>]`.

### How defaults work internally

When a `Flag` is constructed without a `default` (or with `default=_MISSING`), its internal default is set to `None`. At parse time, if no value arrives from CLI, env, or config, a flag with `default=None` triggers an error: `flag '--target' is required`.

For repeatable flags and dict flags, the default is always resolved to an empty list or empty dict respectively -- they are never required.

## Boolean flag semantics

Boolean flags have special behavior compared to other types.

### Automatic negation (--flag / --no-flag)

By default, every bool flag is negatable: strictcli auto-generates a `--no-flag` counterpart. Both forms must appear in the user's mental model.

```python
@strictcli.flag("auto-commit", type=bool, default=True, help="commit after changes")
```

This creates both `--auto-commit` (sets True) and `--no-auto-commit` (sets False). The help output displays both forms:

```
  --auto-commit, --no-auto-commit    commit after changes [default: true]
```

### Required booleans

A bool flag without a default is required. The user must pass either `--flag` or `--no-flag`. The error message reflects this:

```
flag '--watch' must be passed as --watch or --no-watch
```

This is the mechanism for forcing explicit intent on binary decisions (e.g., `--watch` / `--no-watch` during a release).

### Non-negatable booleans

Setting `negatable=False` disables the `--no-flag` form. The flag becomes a pure presence flag (True when passed, default otherwise). Non-negatable bool flags without a default produce a different error:

```
flag '--debug' must be passed as --debug
```

For non-bool types (`str`, `int`, `float`), the `negatable` parameter is silently ignored.

### Env var parsing for booleans

Boolean flags accept these env var strings (case-insensitive):

- True: `1`, `true`, `yes`
- False: `0`, `false`, `no`

## Short flags

Flags can declare a single-character short form:

```python
@strictcli.flag("verbose", short="v", type=bool, default=False, help="verbose output")
```

This allows `-v` as an alias for `--verbose`. Short flags follow the same parsing rules as their long counterparts.

## Repeatable flags

A flag with `repeatable=True` can be passed multiple times. Each occurrence appends to a list.

```python
@strictcli.flag("tag", type=str, help="tags to apply", repeatable=True, unique=False)
```

```
mytool cmd --tag alpha --tag beta --tag gamma
# handler receives tag=["alpha", "beta", "gamma"]
```

### Rules for repeatable flags

- Repeatable flags are never required. They default to an empty list `[]`.
- `type=bool` is incompatible with `repeatable=True`.
- `unique` must be set explicitly to `True` or `False`. When `unique=True`, duplicate values are rejected.
- If the flag has an `env` binding, `env_separator` is required (a single character used to split the env var value into list elements).
- An explicit default on a repeatable flag must be a non-empty list of the correct type. To default to an empty list, omit the default entirely.

### Compound types: list[T] and dict[str, T]

Repeatable flags can also be declared via compound types:

```python
@strictcli.flag("port", type=list[int], help="ports to bind")
```

This is equivalent to `type=int, repeatable=True` (with `unique` defaulting to `False`).

Dict flags use `dict[str, T]`:

```python
@strictcli.flag("label", type=dict[str, str], help="key=value labels")
```

Each occurrence adds a key-value pair. Duplicate keys are rejected. Dict flags cannot be combined with `repeatable=True`, `unique`, `choices`, or `env_separator`.

## Flag naming rules

strictcli enforces naming rules at registration time (in `Flag.__post_init__`). Violations raise `ValueError` and prevent the app from starting.

### Bare --force is banned

The flag name `force` is rejected outright. Use a qualified name that describes what is being forced:

```python
# Rejected: ValueError
@strictcli.flag("force", type=bool, default=False, help="force it")

# Accepted: qualified name
@strictcli.flag("force-overwrite", type=bool, default=False, help="overwrite existing files")
@strictcli.flag("force-delete", type=bool, default=False, help="delete without confirmation")
```

The error message: `flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'`.

### --no-* prefix is reserved

Flag names starting with `no-` are rejected. The `--no-` prefix is auto-generated by the negation system for boolean flags; user-defined flags cannot occupy that namespace.

```python
# Rejected: ValueError
@strictcli.flag("no-cache", type=bool, default=False, help="disable cache")

# Accepted: positive name, negation is auto-generated
@strictcli.flag("cache", type=bool, default=True, help="use cache")
# User passes --cache or --no-cache
```

The error message: `flag 'no-cache': names starting with 'no-' are reserved for the negation system; use a positive name instead`.

### All booleans must have explicit defaults or be required

There is no implicit default for boolean flags. A bool flag without a `default` is required (the user must pass `--flag` or `--no-flag`). A bool flag with a `default` is optional. There is no middle ground where a bool silently defaults to `False`.

```python
# Required: user must choose explicitly
@strictcli.flag("watch", type=bool, help="watch CI after release")

# Optional: defaults to True, user can override with --no-auto-commit
@strictcli.flag("auto-commit", type=bool, default=True, help="commit automatically")

# Optional: defaults to False, user can override with --verbose
@strictcli.flag("verbose", type=bool, default=False, help="verbose output")
```

### Dash-to-underscore conversion

Flag names use dashes (`--dry-run`), but handler parameters use underscores (`dry_run`). The conversion is automatic. If the resulting name is a Python keyword (e.g., `global`, `class`), an underscore is appended per PEP 8 convention (`global_`, `class_`).

## Choices

Flags (and args) can restrict values to a fixed set:

```python
@strictcli.flag("format", type=str, choices=["json", "text", "csv"], help="output format")
```

Rules:
- `choices` is incompatible with `type=bool`.
- All choice values must match the declared type.
- If a default is set, it must be in the choices list.
- For repeatable flags, each individual value is validated against the choices.
- Dict flags cannot have choices.

## Custom validation

A `validate` callback runs after type coercion:

```python
def positive_int(val):
    if val <= 0:
        raise ValueError("must be positive")

@strictcli.flag("port", type=int, help="port number", validate=positive_int)
```

The callback receives the coerced value and should raise `ValueError` with a message on failure. For repeatable flags, the callback is called once per element.

## Env var binding

Flags can be bound to environment variables:

```python
@strictcli.flag("token", type=str, help="API token", env="MYAPP_TOKEN")
```

Precedence: CLI > env > config > default.

When the app declares an `env_prefix`, flag env vars must start with that prefix (enforced at registration). The `prefixed=False` option exempts a flag from this check.

## Positional arguments

Positional arguments are declared via `Arg` objects, passed to `@app.command()` or attached via the `@strictcli.arg` decorator.

```python
@app.command("greet", help="say hello")
@strictcli.arg("name", help="who to greet")
def greet(ctx, name):
    ctx.info(f"Hello, {name}!")
```

### Required vs optional args

By default, positional args are required (`required=True`). Optional args use `required=False` and may declare a default:

```python
@strictcli.arg("output", help="output file", required=False, default="out.txt")
```

A required arg cannot have a default -- this is enforced at registration.

### Variadic args

A variadic arg collects all remaining positional tokens into a list:

```python
@app.command(
    "process",
    help="process files",
    args=[strictcli.Arg(name="files", help="input files", variadic=True)],
)
def process(ctx, files):
    for f in files:
        ctx.info(f"Processing {f}")
```

```
mytool process a.txt b.txt c.txt
# files=["a.txt", "b.txt", "c.txt"]
```

A variadic arg with `required=True` (the default) requires at least one value. Variadic args support typed collection via `type=list[int]` (which also requires `variadic=True`).

### Arg types

Args support the same four types as flags: `str`, `bool`, `int`, `float`. Type coercion uses the same strict parsing.

## The context object

Every command handler receives a `Context` as its first argument. The context provides structured output and provenance introspection.

```python
@app.command("deploy", help="deploy the app")
@strictcli.flag("target", type=str, help="deployment target")
def deploy(ctx, target):
    ctx.info(f"Deploying to {target}")      # stdout
    ctx.warn("Deployment is slow today")     # stderr
    ctx.debug("Connecting...")               # stdout
    ctx.error("Connection failed")           # stderr
```

### Output methods

| Method | Stream | Purpose |
|--------|--------|---------|
| `ctx.info(msg)` | stdout | Informational messages |
| `ctx.warn(msg)` | stderr | Warnings |
| `ctx.debug(msg)` | stdout | Debug output |
| `ctx.error(msg)` | stderr | Error messages |

### Provenance: ctx.source()

`ctx.source(name)` returns where a flag's value came from. Accepts dashed or underscored names.

```python
@app.command("cmd", help="a command")
@strictcli.flag("target", type=str, default="local", help="target", env="MYAPP_TARGET")
def cmd(ctx, target):
    source = ctx.source("target")  # "cli", "env", "config", "default", "implied", or "infra"
    ctx.info(f"target={target} (from {source})")
```

Source labels:

| Label | Meaning |
|-------|---------|
| `cli` | Explicitly passed on the command line |
| `env` | From an environment variable |
| `config` | From a config file |
| `default` | From the flag's declared default value |
| `implied` | Injected by an `Implies` dependency |
| `infra` | Default resolved through a `RelativeToRoot` infrastructure root |

### Handler return values

Handlers must return one of:
- `int` -- exit code (0 = success)
- `None` -- exit 0
- `strictcli.outcome(exit_code, data)` -- structured result with optional data

Any other return type is a hard error. When `outcome()` includes `data`, it is JSON-printed to stdout and captured by `app.test()` and `app.call()`.

## Global flags

Flags can be declared at the app level, making them available to all commands:

```python
app = strictcli.App(
    name="mytool",
    version="1.0.0",
    help="my tool",
    flags=[
        strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
        strictcli.Flag(name="output", type=str, default="text", help="output format"),
    ],
)
```

Global flags are parsed before the command token and are passed to every handler.

## Flag sets

Reusable flag bundles avoid repetition across commands:

```python
auth_flags = strictcli.FlagSet(
    name="auth",
    flags=[
        strictcli.Flag(name="token", type=str, help="API token", env="MYAPP_TOKEN"),
        strictcli.Flag(name="region", type=str, default="us-east-1", help="AWS region"),
    ],
)

@app.command("deploy", help="deploy", flag_sets=[auth_flags])
def deploy(ctx, token, region):
    ...

@app.command("status", help="check status", flag_sets=[auth_flags])
def status(ctx, token, region):
    ...
```

## Mutex groups

Mutually exclusive flags are declared via `MutexGroup`:

```python
@app.command(
    "output",
    help="produce output",
    mutex=[strictcli.MutexGroup(flags=[
        strictcli.Flag(name="json", type=bool, default=False, help="JSON output"),
        strictcli.Flag(name="csv", type=bool, default=False, help="CSV output"),
    ])],
)
def output(ctx, json, csv):
    ...
```

A mutex group must contain at least two flags. Flags in a mutex group with no default get `None` instead of being required -- the group itself enforces that at least one is chosen.

## Dependencies

Three dependency types control flag relationships:

```python
@app.command(
    "cmd",
    help="a command",
    dependencies=[
        # All must appear together or none
        strictcli.CoRequired(flags=["host", "port"]),

        # One-way: --verbose requires --log-file
        strictcli.Requires(flag="verbose", depends_on="log-file"),

        # Auto-set: when --fast is passed, set --no-embeddings
        strictcli.Implies(flag="fast", implies="embeddings", value=False),
    ],
)
```

## Help text is mandatory

Every `Flag`, `Arg`, `Command`, `Group`, and `App` must have non-empty help text. Missing or empty help is a registration-time error. This is a hard constraint with no opt-out.
