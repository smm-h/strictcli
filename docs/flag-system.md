---
title: Flag System
description: "strictcli's flag and argument system: the mandatory three-way presence declaration, four types, boolean negation and tri-state, repeatable flags, the reserved names, mutex election, and positional args."
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
@strictcli.flag("target", type=str, presence="required", help="deployment target")
@strictcli.flag("cache", type=bool, default=True, help="reuse the build cache")
@strictcli.flag("replicas", type=int, default=3, help="number of replicas")
@strictcli.flag("threshold", type=float, default=0.95, help="success threshold")
def deploy(ctx, target, cache, replicas, threshold):
    ...
```

Every flag also declares its **presence** -- one of `required`, `optional`, or a
`default` value. `presence="required"` above is that declaration; `default=`
on the other three is the same declaration in its value-carrying form. See
[The presence declaration](#the-presence-declaration) below.

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

## The presence declaration

Every flag and every positional argument declares **exactly one** of three facts
about itself, and declares it explicitly. Nothing about presence is inferred
from the shape of another declaration:

| Fact | What it means | Python | Go | TypeScript |
|------|---------------|--------|-----|-----------|
| **required** | a value must be supplied | `presence="required"` | `Required()` | `{ presence: "required" }` |
| **optional** | absence is legal and is delivered *as* absence | `presence="optional"` | `Optional()` | `{ presence: "optional" }` |
| **default** | the framework supplies the declared value when nothing else does | `default=<value>` | `Default(<value>)` | `{ presence: "default", default: <value> }` |

```python
# Required: some source must supply it on every invocation
@strictcli.flag("target", type=str, presence="required", help="deployment target")

# Default: 3 when nothing supplies a value
@strictcli.flag("replicas", type=int, default=3, help="number of replicas")

# Optional: the handler receives None when nothing supplies a value
@strictcli.flag("tag", type=str, presence="optional", help="release tag")
```

Declaring **none** of the three is a registration-time hard error naming all
three choices:

```
Flag "y": presence is undeclared: declare exactly one of presence="required", presence="optional", or default=<value>
```

Declaring **two** is a registration-time hard error naming the two that were
supplied:

```
Flag "z": presence is declared twice: presence="required" and default=a cannot be combined; declare exactly one
```

### A null default is not optionality

`default=None` (Python), `Default(nil)` (Go) and `default: null` (TypeScript)
are registration errors that redirect to the optional spelling. Optionality has
exactly one way to be written, and the value-shaped way is refused rather than
accepted as a synonym:

```
Flag "x": default=None does not declare optionality: use presence="optional" (it delivers None when the flag is absent)
```

`presence="optional"` is what delivers `None` / `nil` / `undefined`.

### What "required" requires

A `required` declaration is satisfied by **any source that supplies a value** -- a CLI
token, a bound environment variable, a config file entry, or an `Implies`
injection. It is not a "must be typed on the command line" rule. The one
exception belongs to [mutex groups](#mutex-groups), where env and config are not
consulted for a member at all.

### What "optional" delivers

An optional flag delivers absence as a **present key**: `None` in Python, `nil`
in Go, `undefined` in TypeScript. The keyword argument is always passed -- it is never
omitted -- so a handler reads it like any other value:

```python
@app.command("publish", help="publish a build", effect="mutating")
@strictcli.flag("tag", type=str, presence="optional", help="release tag")
def publish(ctx, tag):
    if tag is None:
        ctx.info("publishing untagged")
```

In Python a handler parameter bound to an optional flag or arg must either
declare no default at all (as above) or default to `None`. Anything else --
`def publish(ctx, tag="")` -- re-introduces at the handler boundary the sentinel
the declaration just removed, and is a registration-time hard error:

```
command "publish": handler parameter 'tag' is bound to optional flag '--tag' and must default to None
```

Go and TypeScript handlers receive one kwargs map / one args object, so they
have no per-parameter default and no such check.

### Was this supplied? `ctx.provided`

`ctx.provided(name)` (Python and TypeScript) / `ctx.Provided(name)` (Go) answers
whether the **invocation** caused a value, so no handler reconstructs that
boolean out of a sentinel:

| Source | `provided` |
|--------|-----------|
| `cli`, `env`, `config`, `implied` | **true** -- the invocation caused the value |
| `default`, `infra` | **false** -- the declaration caused it |

An optional flag that received nothing carries source `default` and reports
`false`. Unknown names raise exactly as `ctx.source` does.

### Presence in help output

Every flag and every arg renders **exactly one** presence part, and it is the
last bracketed part of the line:

| Declared | Rendered |
|----------|----------|
| required | `[required]` |
| optional | `[optional]` |
| default | `[default: <value>]` |

A declared empty collection renders `[default: []]` or `[default: {}]`, and a
required positional argument renders `[required]` like a required flag.

### Presence composed with other declarations

| Declared with | Behavior |
|---------------|----------|
| `choices` | a **declared default value** must be in `choices` at registration; absence is never matched against `choices`, so `optional` + `choices` checks nothing at registration and validates only supplied values |
| `env` / `config` | an env- or config-supplied value satisfies a `required` declaration and makes the flag *provided*; precedence stays CLI > env > config > default |
| `validate` | runs on a supplied value only -- **never** on a declared default, and never on absence |
| `Implies` target | the injected value satisfies a `required` declaration (implication resolves before defaults) |
| `Implies` trigger | fires when the flag is *provided*; a defaulted trigger never fires from its own default |
| `CoRequired` / `Requires` | a member is present iff it is *provided*, so a default never satisfies a dependency |
| mutex member | declaring `required` is a registration error; declare `optional` or a `default` |
| `RelativeToRoot` | the marker **is** a `default=` declaration; its value resolves at parse time with source label `infra` |

## Boolean flag semantics

Boolean flags have special behavior compared to other types, including automatic
negation form generation, required boolean semantics where callers must
explicitly pass `--flag` or `--no-flag`, a genuine tri-state under
`presence="optional"`, and strict env var parsing that accepts only a fixed set
of truthy and falsy strings.

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

A bool flag declaring `presence="required"` forces the caller to pass either
`--flag` or `--no-flag` explicitly, which is the mechanism for forcing explicit
intent on binary decisions (e.g., `--watch` / `--no-watch` during a release).
The error message reflects both accepted forms:

```python
@strictcli.flag("watch", type=bool, presence="required", help="watch CI after release")
```

```
flag '--watch' must be passed as --watch or --no-watch
```

### Tri-state booleans

A bool flag declaring `presence="optional"` is a genuine three-valued flag:
`--flag` is true, `--no-flag` is false, and absence is absence. This is what
retires the "use a string and treat the empty string as unset" idiom.

```python
@app.command("build", help="build the project", effect="mutating")
@strictcli.flag("cache", type=bool, presence="optional", help="reuse the build cache")
def build(ctx, cache):
    if cache is None:
        ctx.info("cache decision inherited from the profile")
```

### Non-negatable booleans

Setting `negatable=False` disables the `--no-flag` form, turning the flag into
a pure presence flag that is `True` when passed and otherwise takes whatever its
presence declaration says. This is useful for flags like `--debug` where
negation is not meaningful. A non-negatable bool declaring `presence="required"`
produces a simpler error message that only shows the positive form:

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
with each occurrence appending to a list. Like every other flag, a repeatable
flag declares its own presence -- there is no silent empty-list default. They
support uniqueness enforcement via the `unique` parameter and can split env var
values using a declared separator character.

```python
# An empty list when nothing is passed -- declared, not assumed
@strictcli.flag("tag", type=str, default=[], help="tags to apply", repeatable=True, unique=False)

# Absent when nothing is passed: the handler receives None, not []
@strictcli.flag("only", type=str, presence="optional", help="restrict to these", repeatable=True, unique=False)

# At least one occurrence must arrive from some source
@strictcli.flag("host", type=str, presence="required", help="hosts to contact", repeatable=True, unique=True)
```

```
mytool cmd --tag alpha --tag beta --tag gamma
# handler receives tag=["alpha", "beta", "gamma"]
```

### Rules for repeatable flags

- A repeatable flag declares presence like any other flag. `default=[]` is an explicit, legal declaration; `presence="optional"` delivers absence rather than `[]`; `presence="required"` demands at least one occurrence from some source.
- `type=bool` is incompatible with `repeatable=True`.
- `unique` must be set explicitly to `True` or `False`. When `unique=True`, duplicate values are rejected.
- If the flag has an `env` binding, `env_separator` is required (a single character used to split the env var value into list elements).
- A non-empty default must be a list of the correct element type.

### Compound types: list[T] and dict[str, T]

Repeatable flags can also be declared via compound types, which provide a more
concise syntax. The `list[T]` form is equivalent to `type=T, repeatable=True`,
and `dict[str, T]` creates a key-value flag where each occurrence adds a pair.
The element type `T` must be `str`, `int`, or `float` -- boolean elements are
not supported in compound types.

```python
@strictcli.flag("port", type=list[int], default=[], help="ports to bind")
```

This is equivalent to `type=int, repeatable=True` (with `unique` defaulting to `False`).

Dict flags use `dict[str, T]`:

```python
@strictcli.flag("label", type=dict[str, str], default={}, help="key=value labels")
```

Each occurrence adds a key-value pair. Duplicate keys are rejected. Dict flags cannot be combined with `repeatable=True`, `unique`, `choices`, or `env_separator`.

Compound flags declare presence honestly like every other flag: `default=[]` /
`default={}` for an empty collection, `presence="optional"` to receive absence
instead, `presence="required"` to demand at least one occurrence. A declared
empty collection renders `[default: []]` / `[default: {}]` in help.

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

### Every boolean states its presence, like every other flag

There is no implicit default for boolean flags, and none of the three
declarations is assumed. A bool silently defaulting to `False` has never been a
possibility, and after the presence declaration neither is a bool whose author
did not say which of the three it is:

```python
# Required: user must choose explicitly, with --watch or --no-watch
@strictcli.flag("watch", type=bool, presence="required", help="watch CI after release")

# Default True: user can override with --no-auto-commit
@strictcli.flag("auto-commit", type=bool, default=True, help="commit automatically")

# Default False: user can override with --recursive
@strictcli.flag("recursive", type=bool, default=False, help="recurse into subdirectories")

# Optional: True, False, or absent -- a real tri-state
@strictcli.flag("color", type=bool, presence="optional", help="colorize output")
```

### Dash-to-underscore conversion

Flag names use dashes (`--log-file`), but handler parameters use underscores (`log_file`). The conversion is automatic. If the resulting name is a Python keyword (e.g., `global`, `class`), an underscore is appended per PEP 8 convention (`global_`, `class_`).

## Choices

Flags (and args) can restrict values to a fixed set using the `choices`
parameter. Values not in the choices list produce a parse error listing all
allowed values. Choices are validated at registration time to ensure they match
the flag's declared type.

```python
@strictcli.flag("format", type=str, presence="required", choices=["json", "text", "csv"], help="output format")
```

Rules:
- `choices` is incompatible with `type=bool`.
- All choice values must match the declared type.
- If a `default` value is declared, it must be in the choices list. This is a check on declared *values*: `presence="optional"` declares no value, so it is checked against nothing at registration and absence is never matched against `choices` at parse time.
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

@strictcli.flag("port", type=int, presence="required", help="port number", validate=positive_int)
```

The callback receives the coerced value and should raise `ValueError` with a
message on failure. For repeatable flags, the callback is called once per
element. It runs on **supplied** values only: a declared default is the
author's to get right at registration, so `validate` never runs against it, and
it never runs on the absence an optional declaration delivers.

## Env var binding

Flags can be bound to environment variables via the `env` parameter, providing a
fallback source for values not passed on the command line. Environment variables
sit between CLI tokens and config file values in the resolution cascade (CLI >
env > config > default) and are skipped entirely under `--hermetic` mode.

```python
@strictcli.flag("token", type=str, presence="required", help="API token", env="MYAPP_TOKEN")
```

Precedence: CLI > env > config > default. An env- or config-supplied value
satisfies a `presence="required"` declaration -- what a required declaration
demands is a value arriving, not a token being typed -- and it makes the flag
*provided*, so
`ctx.provided("token")` is true with source `env` or `config`.

When the app declares an `env_prefix`, flag env vars must start with that prefix (enforced at registration). The `prefixed=False` option exempts a flag from this check.

## Positional arguments

Positional arguments are declared via `Arg` objects, passed to `@app.command()`
or attached via the `@strictcli.arg` decorator. Positional arguments are
consumed in declaration order after all flags have been parsed, and support the
same four scalar types as flags plus variadic collection into lists.

```python
@app.command("greet", help="say hello", effect="read_only")
@strictcli.arg("name", help="who to greet", presence="required")
def greet(ctx, name):
    ctx.info(f"Hello, {name}!")
```

### Arg presence

Positional args take **the same three facts and the same one-spelling rule** as
flags. There is no `required=` parameter on an arg: it was an implicit default
(an arg that declared nothing was required by omission), and paired with
`default=` it spelled one fact across two fields.

| Fact | Python | Go | TypeScript |
|------|--------|-----|-----------|
| required | `presence="required"` | `ArgRequired()` | `{ presence: "required" }` |
| optional | `presence="optional"` | `ArgOptional()` | `{ presence: "optional" }` |
| default | `default=<value>` | `ArgDefault(<value>)` | `{ presence: "default", default: <value> }` |

```python
# A default when the token is absent
@strictcli.arg("output", help="output file", default="out.txt")

# Absence delivered as absence: the handler receives None
@strictcli.arg("note", help="an optional note", presence="optional")
```

An optional arg delivers absence as a **present key** (`None` / `nil` /
`undefined`) exactly as an optional flag does -- it does not omit the keyword
argument.

### Variadic args

A variadic arg collects all remaining positional tokens into a list, and must be
the last positional argument in the command's declaration. At most one variadic
arg is allowed per command. Because a variadic always delivers a list,
`presence="required"` means *at least one value* and `presence="optional"` means
*possibly none*; a `default` on a variadic arg is a registration error.

```python
@app.command(
    "process",
    help="process files",
    effect="read_only",
    args=[strictcli.Arg(name="files", help="input files", variadic=True, presence="required")],
)
def process(ctx, files):
    for f in files:
        ctx.info(f"Processing {f}")
```

```
mytool process a.txt b.txt c.txt
# files=["a.txt", "b.txt", "c.txt"]
```

The empty case is spelled once, as `presence="optional"`. Declaring a default
instead is refused:

```
Arg "files": a variadic arg cannot declare default=: it always delivers a list, so declare presence="required" for at least one value or presence="optional" for possibly none
```

Variadic args support typed collection via `type=list[int]` (which also requires `variadic=True`).

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
@strictcli.flag("target", type=str, presence="required", help="deployment target")
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
| `default` | From the flag's declared default value -- and the label an optional flag carries when nothing supplied it |
| `implied` | Injected by an `Implies` dependency |
| `infra` | Default resolved through a `RelativeToRoot` infrastructure root |

For the yes/no question -- *did the invocation cause this value?* -- use
[`ctx.provided(name)`](#was-this-supplied-ctxprovided) rather than comparing
labels by hand. `ctx.source` is not superseded: it answers the narrower question
of *which* origin, and is still the accessor for a handler that must distinguish
env from config.

### Handler return values

Handlers must return one of three strictly validated types, and any other return
type is a hard error that immediately terminates the program. This strict
contract prevents silent bugs where a handler accidentally returns a string,
list, or other value that the framework would not know how to interpret:
- `int` -- exit code (0 = success)
- `None` -- exit 0
- `strictcli.outcome(exit_code)` -- a branded exit-code result (structured output goes through `ctx.payload(...)`)

Any other return type is a hard error. Structured output is a separate channel: a command declares its payload's JSON Schema with `payload_schema=` and its handler supplies the value through `ctx.payload(...)`, which is printed only under the framework-owned `--json` and captured by `app.test()` and `app.call()` in either mode.

## Global flags

Flags can be declared at the app level, making them available to all commands
in the application. Global flags are parsed before the command token during the
global flag parsing stage, and their values are passed to every handler alongside
the command's own flags. Global flag names cannot collide with reserved framework
names like `help`, `version`, `dump-schema`, `mcp`, `config`, or `hermetic`, nor
with the reserved quartet `dry-run`, `approve-consequential`, `quiet`, `verbose`,
nor with `json`, which selects machine mode.

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
        strictcli.Flag(name="token", type=str, presence="required", help="API token", env="MYAPP_TOKEN"),
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

Mutually exclusive flags are declared via `MutexGroup`, which enforces that
**exactly one** member is chosen in each invocation. A mutex group must contain
at least 2 flags, and a flag cannot appear in multiple mutex groups.

### What elects a member

Only a **command-line token** elects. A bool member is elected by `--<name>`,
and only when it resolves to **true**: `--no-<name>` *declines* the option --
it says "not this one", and elects nothing. Every other type elects on presence
with any value, including the empty string (`--profile ""` is an explicit act;
whether `""` is legal for that flag is the flag's own value validation).

Three errors, checked in this order per group:

| Situation | Error |
|-----------|-------|
| More than one member elected | `--a and --b are mutually exclusive` |
| One elected, another declined | `--no-b cannot be combined with --a (--no-b declines an option; it does not choose one)` |
| Nothing elected | `one of --a, --b is required`, plus ` (--no-b declines an option; it does not choose one)` when a member was declined |

### Env and config do not elect

Election is command-line-only, and this is the framework's one deliberate
exception to the ordinary CLI > env > config > default precedence. A value that
would reach a mutex member from an environment variable or a config file
neither elects it nor is delivered to the handler: an unelected member gets
whatever its own presence declaration says -- its declared default, or
`None` / `nil` / `undefined` when it declares `optional` -- and its source
label is `default`. A mutex group exists to make the
operator choose in the invocation, so an inherited environment cannot make that
choice -- nor silently sit beside a typed one.

### Handlers test absence, never truthiness

A handler on a mutex member must test `is None` (Python) / `== nil` (Go) /
`=== undefined` (TypeScript). A truthiness test misreads an elected `--profile ""`
as "not chosen", and reads an unelected bool member the same way an elected
`false` would read if one could exist.

```python
@app.command(
    "output",
    help="produce output",
    effect="read_only",
    mutex=[strictcli.MutexGroup(flags=[
        strictcli.Flag(name="as-table", type=bool, presence="optional", help="table output"),
        strictcli.Flag(name="as-csv", type=bool, presence="optional", help="CSV output"),
    ])],
)
def output(ctx, as_table, as_csv):
    ...
```

### A member declares its own absence

A mutex member declares presence like every other flag, and there is no
exemption that fills it in. The ordinary declaration for a member is
`presence="optional"`: the group enforces cardinality **on top of** presence,
never instead of it. A `default` is legal too -- §21's unelected member delivers
it. What a member cannot declare is `required`: the group's own requirement is
what makes the choice mandatory, and a member that must always be typed
contradicts a group that permits exactly one.

```
Flag "as-table": a mutex member cannot declare presence="required": the group's own requirement is what makes the choice mandatory
```

(`json` is not usable as a flag name anywhere: it is reserved for machine mode.)

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

All three read presence through the same predicate `ctx.provided` uses: a flag
counts as present when the **invocation** caused its value, so a declared
default -- including a `RelativeToRoot` default with the `infra` label -- never
satisfies a `Requires` or completes a `CoRequired` group, and an `Implies`
trigger never fires from its own default.

## Help text is mandatory

Every `Flag`, `Arg`, `Command`, `Group`, and `App` must have non-empty help
text. Missing or empty help is a registration-time error with no opt-out and no
way to silence the check. This is a deliberate design choice: self-documenting
CLIs are non-negotiable, and the framework enforces this at the earliest
possible point rather than waiting for a user to encounter an undocumented flag
at runtime.
