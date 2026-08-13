---
title: Flag System
description: "strictcli's flag and argument system: four types, defaults, boolean negation, repeatable flags, the reserved quartet and consent parameter, and positional args."
nav_group: "Guides"
nav_order: 3
---

# Flag System

strictcli's flag system is strict by design. Every flag must have help text, every type must be explicit, and every default must be deliberate. This guide covers the full flag and argument system using Python examples. The Go and TypeScript implementations have identical semantics (see the quickstart guides for language-specific syntax).

## Flag types

strictcli supports exactly four scalar types: `str`, `bool`, `int`, and `float`.
There is no implicit type inference -- every flag declares its type explicitly at
registration time. Additionally, compound types `list[T]` and `dict[str, T]`
are available for repeatable and key-value flags. The type determines how values
are parsed from CLI tokens, environment variables, and config files.

```python
@app.command("deploy", help="deploy the application", effect="mutating")
@strictcli.flag("target", type=str, help="deployment target")
@strictcli.flag("cache", type=bool, default=True, help="reuse the build cache")
@strictcli.flag("replicas", type=int, default=3, help="number of replicas")
@strictcli.flag("threshold", type=float, default=0.95, help="success threshold")
def deploy(ctx, target, cache, replicas, threshold):
    ...
```

Every command declares its `effect` -- `"read_only"` or `"mutating"` -- and the
declaration is mandatory. See the [Python quickstart](python-quickstart.md#command-classification)
for what classification buys.

### String flags

String flags (`type=str`, the default) take a value from the next token or via
`--flag=value` syntax. They support the `@-prefix` resolution system, which
allows reading values from files, stdin, or literal at-signs, making it easy to
pass large values or secrets without exposing them on the command line.

String flags support `@-prefix` resolution: `@path` reads the value from a file, `@-` reads from stdin (once per invocation), and `@@` is a literal `@` escape.

```
mytool deploy --target @config/target.txt
echo "production" | mytool deploy --target @-
mytool deploy --target @@literal-at-sign
```

### Boolean flags

Boolean flags (`type=bool`) do not take a value argument -- they are pure
presence/absence flags. `--flag` sets the value to `True`, and the
auto-generated `--no-flag` negation form sets it to `False`. The `--flag=value`
syntax is rejected as a parse error because boolean flags should never accept
an ambiguous string value.

```
mytool deploy --cache          # cache=True
mytool deploy --no-cache       # cache=False
```

### Integer flags

Integer flags (`type=int`) use strict parsing with no leading or trailing
whitespace, no leading zeros (in Go), and 64-bit signed bounds. The value comes
from the next token or `--flag=value` syntax. Negative integers like `-7` are
supported as positional arguments because tokens starting with `-` that do not
match any declared flag are treated as positional values rather than unknown
flags.

### Float flags

Float flags (`type=float`) also use strict parsing and reject NaN and Inf at
parse time to prevent invalid numeric states from reaching handlers. All three
implementations use the strictcli canonical float form (SCF), a
shortest-round-trip representation that produces identical output byte-for-byte
across Python, Go, and TypeScript. The canonical form is verified by exhaustive
bit-pattern tests committed in the conformance suite.

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

Boolean flags have special behavior compared to other types, including automatic
negation form generation, required boolean semantics where callers must
explicitly pass `--flag` or `--no-flag`, and strict env var parsing that accepts
only a fixed set of truthy and falsy strings.

### Automatic negation (--flag / --no-flag)

By default, every bool flag is negatable: strictcli auto-generates a
`--no-flag` counterpart at registration time. Both forms appear in help output
and both are accepted on the command line. This ensures that callers can always
explicitly set a boolean to either true or false, which is especially important
for flags with `Default(true)` where the caller needs a way to opt out.

```python
@strictcli.flag("auto-commit", type=bool, default=True, help="commit after changes")
```

This creates both `--auto-commit` (sets True) and `--no-auto-commit` (sets False). The help output displays both forms:

```
  --auto-commit, --no-auto-commit    commit after changes [default: true]
```

### Required booleans

A bool flag without a default is required -- the user must pass either `--flag`
or `--no-flag` explicitly. This is a deliberate design choice that forces
callers to declare their intent on binary decisions rather than relying on
implicit defaults. The error message for a missing required boolean reflects
both accepted forms:

```
flag '--watch' must be passed as --watch or --no-watch
```

This is the mechanism for forcing explicit intent on binary decisions (e.g., `--watch` / `--no-watch` during a release).

### Non-negatable booleans

Setting `negatable=False` disables the `--no-flag` form, turning the flag into
a pure presence flag that is `True` when passed and falls through to its default
otherwise. This is useful for flags like `--debug` where negation is not
meaningful. Non-negatable bool flags without a default produce a different,
simpler error message that only shows the positive form:

```
flag '--debug' must be passed as --debug
```

For non-bool types (`str`, `int`, `float`), the `negatable` parameter is silently ignored.

### Env var parsing for booleans

Boolean flags accept a fixed set of env var strings for parsing, validated
case-insensitively. Any string not in this set produces a parse error with a
message listing the accepted values. This strict parsing prevents ambiguous
truthy/falsy interpretations that differ across languages:

- True: `1`, `true`, `yes` (3 accepted truthy strings)
- False: `0`, `false`, `no` (3 accepted falsy strings)

## Short flags

Flags can declare a single-character short form that serves as an alias for the
long flag name. Short flags follow the same parsing rules as their long
counterparts, including type coercion, env var fallback, and config file
resolution. Short flags are shown alongside long flags in help output.

```python
@strictcli.flag("recursive", short="r", type=bool, default=False, help="recurse into subdirectories")
```

This allows `-r` as an alias for `--recursive`. Short flags follow the same parsing rules as their long counterparts. The reserved quartet has no short forms, and the quartet's ban applies to long names only -- a short flag named `v` is legal.

## Repeatable flags

A flag with `repeatable=True` can be passed multiple times on the command line,
with each occurrence appending to a list. Repeatable flags are never required
and always default to an empty list. They support uniqueness enforcement via the
`unique` parameter and can split env var values using a declared separator
character.

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

Repeatable flags can also be declared via compound types, which provide a more
concise syntax. The `list[T]` form is equivalent to `type=T, repeatable=True`,
and `dict[str, T]` creates a key-value flag where each occurrence adds a pair.
The element type `T` must be `str`, `int`, or `float` -- boolean elements are
not supported in compound types.

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

strictcli enforces naming rules at registration time (in `Flag.__post_init__`
for Python, `validateFlagConfig` for Go and TypeScript). Violations raise
`ValueError` in Python, panic in Go, or throw a `RegistrationError` in
TypeScript, preventing the app from starting. These rules prevent ambiguous flag
names and ensure the negation namespace remains uncontaminated.

### Bare --force is banned

The flag name `force` is rejected outright because a generic force flag lets
agents and automation bypass guardrails without specifying what they are forcing.
Qualified names like `force-overwrite` or `force-delete` make the intent
explicit and auditable. Use a qualified name that describes what is being
forced:

```python
# Rejected: ValueError
@strictcli.flag("force", type=bool, default=False, help="force it")

# Accepted: qualified name
@strictcli.flag("force-overwrite", type=bool, default=False, help="overwrite existing files")
@strictcli.flag("force-delete", type=bool, default=False, help="delete without confirmation")
```

The error message: `flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'`.

### --no-* prefix is reserved

Flag names starting with `no-` are rejected because the `--no-` prefix is
auto-generated by the negation system for boolean flags. Allowing user-defined
flags in this namespace would create ambiguity: a flag named `no-cache` would
generate a `--no-no-cache` negation form, which is confusing. The positive name
should be used instead, and the framework generates the negation automatically.

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

# Optional: defaults to False, user can override with --recursive
@strictcli.flag("recursive", type=bool, default=False, help="recurse into subdirectories")
```

### Dash-to-underscore conversion

Flag names use dashes (`--log-file`), but handler parameters use underscores (`log_file`). The conversion is automatic. If the resulting name is a Python keyword (e.g., `global`, `class`), an underscore is appended per PEP 8 convention (`global_`, `class_`).

## Choices

Flags (and args) can restrict values to a fixed set using the `choices`
parameter. Values not in the choices list produce a parse error listing all
allowed values. Choices are validated at registration time to ensure they match
the flag's declared type.

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

A `validate` callback runs after type coercion and choices validation, giving
the flag author a way to enforce arbitrary constraints on the parsed value. The
callback receives the coerced value and should raise `ValueError` with a
descriptive message on failure. For repeatable flags, the callback is called
once per element.

```python
def positive_int(val):
    if val <= 0:
        raise ValueError("must be positive")

@strictcli.flag("port", type=int, help="port number", validate=positive_int)
```

The callback receives the coerced value and should raise `ValueError` with a message on failure. For repeatable flags, the callback is called once per element.

## Env var binding

Flags can be bound to environment variables via the `env` parameter, providing a
fallback source for values not passed on the command line. Environment variables
sit between CLI tokens and config file values in the resolution cascade (CLI >
env > config > default) and are skipped entirely under `--hermetic` mode.

```python
@strictcli.flag("token", type=str, help="API token", env="MYAPP_TOKEN")
```

Precedence: CLI > env > config > default.

When the app declares an `env_prefix`, flag env vars must start with that prefix (enforced at registration). The `prefixed=False` option exempts a flag from this check.

## Positional arguments

Positional arguments are declared via `Arg` objects, passed to `@app.command()`
or attached via the `@strictcli.arg` decorator. Positional arguments are
consumed in declaration order after all flags have been parsed, and support the
same four scalar types as flags plus variadic collection into lists.

```python
@app.command("greet", help="say hello", effect="read_only")
@strictcli.arg("name", help="who to greet")
def greet(ctx, name):
    ctx.info(f"Hello, {name}!")
```

### Required vs optional args

By default, positional args are required (`required=True`). Optional args use
`required=False` and may declare a default value. A required arg cannot have a
default -- this invariant is enforced at registration time to prevent ambiguous
declarations where a supposedly required arg silently falls through to a default
value.

```python
@strictcli.arg("output", help="output file", required=False, default="out.txt")
```

A required arg cannot have a default -- this is enforced at registration.

### Variadic args

A variadic arg collects all remaining positional tokens into a list, and must be
the last positional argument in the command's declaration. At most one variadic
arg is allowed per command. A variadic arg with `required=True` (the default)
requires at least one value to be provided.

```python
@app.command(
    "process",
    help="process files",
    effect="read_only",
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

Args support the same four scalar types as flags: `str`, `bool`, `int`, and
`float`. Type coercion uses the same strict parsing rules, and variadic args
additionally support the `list[T]` compound type for typed collection. Dict
types are not supported on positional args.

## The context object

Every command handler receives a `Context` as its first argument (in Go and
Python; TypeScript uses args-first, ctx-second). The context provides structured
output methods for writing to stdout and stderr, provenance introspection via
`ctx.source()`, and infrastructure value access via `ctx.infra_value()`. The
context is the primary interface between the handler and the framework.

```python
@app.command("deploy", help="deploy the app", effect="mutating")
@strictcli.flag("target", type=str, help="deployment target")
def deploy(ctx, target):
    ctx.info(f"Deploying to {target}")      # stdout
    ctx.warn("Deployment is slow today")     # stderr
    ctx.debug("Connecting...")               # stdout, only under --verbose
    ctx.error("Connection failed")           # stderr
```

### Output methods

| Method | Stream | Purpose |
|--------|--------|---------|
| `ctx.info(msg)` | stdout | Informational messages (suppressed under `--quiet`) |
| `ctx.warn(msg)` | stderr | Warnings (never suppressed) |
| `ctx.debug(msg)` | stdout | Debug output (shown only under `--verbose`) |
| `ctx.error(msg)` | stderr | Error messages (never suppressed) |

### The reserved quartet on the context

`--dry-run`, `--approve-consequential`, `--quiet` and `--verbose` are framework
flag names that cannot be declared at any level. They never arrive as handler
parameters -- their values are read from the context as `ctx.dry_run`,
`ctx.approve_consequential`, `ctx.quiet` and `ctx.verbose`. Declaring a flag
with any of those four names raises `ValueError` at registration time.

### The consent parameter name

`approve_consequential` -- the underscore spelling, the one the *parameter*
surface uses -- is reserved separately, and it is the only reserved name that
reaches positional args as well as flags. It is how a caller states consent
programmatically (`app.call(..., approve_consequential=True)`,
`WithApproveConsequential()`, `{ approveConsequential: true }`) and over MCP
(a top-level `tools/call` param). Declaring a flag or an arg of that name is a
registration-time hard error in every implementation:

```
flag name 'approve_consequential' is reserved by the framework: it names the programmatic consent parameter
arg name 'approve_consequential' is reserved by the framework: it names the programmatic consent parameter
```

Without the reservation the same command would mean different things on
different channels: in Python a positional arg of that name is swallowed by
`call()`'s keyword-only consent parameter while MCP still reaches it. Go and
TypeScript pass kwargs as a map and an options object, so they are structurally
immune -- but the name is framework vocabulary everywhere, so all three refuse
it identically. The hyphenated `approve-consequential` is already banned as a
flag name by the quartet; as an *arg* name it stays legal, because an arg has
no `--` spelling and never becomes that parameter.

### Provenance: ctx.source()

`ctx.source(name)` returns where a flag's value came from as a string label,
enabling handlers to alter behavior based on whether a value was explicitly
provided by the user or fell through to its default. The method accepts both
dashed names (`log-file`) and underscored names (`log_file`).

```python
@app.command("cmd", help="a command", effect="read_only")
@strictcli.flag("target", type=str, default="local", help="target", env="MYAPP_TARGET")
def cmd(ctx, target):
    source = ctx.source("target")  # "cli", "env", "config", "default", "implied", or "infra"
    ctx.info(f"target={target} (from {source})")
```

The 6 source labels:

| Label | Meaning |
|-------|---------|
| `cli` | Explicitly passed on the command line |
| `env` | From an environment variable |
| `config` | From a config file |
| `default` | From the flag's declared default value |
| `implied` | Injected by an `Implies` dependency |
| `infra` | Default resolved through a `RelativeToRoot` infrastructure root |

### Handler return values

Handlers must return one of three strictly validated types, and any other return
type is a hard error that immediately terminates the program. This strict
contract prevents silent bugs where a handler accidentally returns a string,
list, or other value that the framework would not know how to interpret:
- `int` -- exit code (0 = success)
- `None` -- exit 0
- `strictcli.outcome(exit_code)` -- a branded exit-code result (structured output goes through `ctx.payload(...)`)

Any other return type is a hard error. When `outcome()` includes `data`, it is JSON-printed to stdout and captured by `app.test()` and `app.call()`.

## Global flags

Flags can be declared at the app level, making them available to all commands
in the application. Global flags are parsed before the command token during the
global flag parsing stage, and their values are passed to every handler alongside
the command's own flags. Global flag names cannot collide with reserved framework
names like `help`, `version`, `dump-schema`, `mcp`, `config`, or `hermetic`, nor
with the reserved quartet `dry-run`, `approve-consequential`, `quiet`, `verbose`.

```python
app = strictcli.App(
    name="mytool",
    version="1.0.0",
    help="my tool",
    flags=[
        strictcli.Flag(name="color", type=bool, default=True, help="colorize output"),
        strictcli.Flag(name="output", type=str, default="text", help="output format"),
    ],
)
```

Global flags are parsed before the command token and are passed to every handler.

## Flag sets

Reusable flag bundles avoid repetition across commands by grouping related flags
into a named `FlagSet` that can be attached to multiple commands. Each command
that uses a flag set receives all its flags as if they were declared directly on
the command, including type checking, env var binding, and constraint
validation.

```python
auth_flags = strictcli.FlagSet(
    name="auth",
    flags=[
        strictcli.Flag(name="token", type=str, help="API token", env="MYAPP_TOKEN"),
        strictcli.Flag(name="region", type=str, default="us-east-1", help="AWS region"),
    ],
)

@app.command("deploy", help="deploy", effect="mutating", flag_sets=[auth_flags])
def deploy(ctx, token, region):
    ...

@app.command("status", help="check status", effect="read_only", flag_sets=[auth_flags])
def status(ctx, token, region):
    ...
```

## Mutex groups

Mutually exclusive flags are declared via `MutexGroup`, which enforces that at
most one flag in the group has a value from an explicit source (CLI, env, or
config). Default and implied values do not trigger mutex violations. A mutex
group must contain at least 2 flags, and a flag cannot appear in multiple mutex
groups.

```python
@app.command(
    "output",
    help="produce output",
    effect="read_only",
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

Three dependency types control relationships between flags, enforcing
constraints that go beyond simple mutual exclusion. `CoRequired` ensures flags
appear together, `Requires` creates one-way dependencies, and `Implies`
automatically sets a target flag's value when a trigger flag is provided.

```python
@app.command(
    "cmd",
    help="a command",
    effect="mutating",
    dependencies=[
        # All must appear together or none
        strictcli.CoRequired(flags=["host", "port"]),

        # One-way: --trace requires --log-file
        strictcli.Requires(flag="trace", depends_on="log-file"),

        # Auto-set: when --fast is passed, set --no-embeddings
        strictcli.Implies(flag="fast", implies="embeddings", value=False),
    ],
)
```

Dependencies can only reference flags you declared. The reserved quartet is not
declarable, so `dry-run`, `approve-consequential`, `quiet` and `verbose` can
never appear in a `Requires`, `CoRequired` or `Implies`.

## Help text is mandatory

Every `Flag`, `Arg`, `Command`, `Group`, and `App` must have non-empty help
text. Missing or empty help is a registration-time error with no opt-out and no
way to silence the check. This is a deliberate design choice: self-documenting
CLIs are non-negotiable, and the framework enforces this at the earliest
possible point rather than waiting for a user to encounter an undocumented flag
at runtime.
