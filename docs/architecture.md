---
title: Architecture and Internals
description: "strictcli internals: the five-stage parse pipeline, its two-region reserved-flag pre-scan, presence resolution, registration-time validation, the schema format, and config."
nav_group: "Guides"
nav_order: 10
---

# Architecture and Internals

strictcli is a strict CLI framework implemented in Python, Go, and TypeScript,
kept in behavioral lockstep by a shared conformance test suite. This document
explains how the framework works internally, covering the parse pipeline, the
registration-time validation model, the schema format, the config system, flag
negation, and the error handling philosophy.

## Implementation layout

Each implementation has its own internal structure, but all follow the same
logical architecture. The Python implementation is a single-file module, the Go
implementation is split across roughly 20 source files, and the TypeScript
implementation uses roughly 30 source files compiled to ESM. Despite these
structural differences, the three codebases produce identical error messages,
identical help output, and identical schema JSON.

- **Python** (`python/strictcli/__init__.py`): single-file implementation, one
  external dependency (tomlkit for TOML editing).
- **Go** (`go/strictcli/`): split across ~20 source files, one external
  dependency (go-toml-edit for TOML editing).
- **TypeScript** (`typescript/src/`): split across ~30 source files (pure ESM,
  Node >= 22), two external dependencies (smol-toml for parsing,
  toml-eslint-parser for comment-preserving edits).

All three produce identical error messages, identical help output, identical
schema JSON, and pass the same conformance test cases.

## The parse pipeline

Every invocation flows through the same five-stage pipeline: reserved flag
pre-scan, global flag parsing, command routing, command parsing, and dispatch.
The stages are named identically in all implementations and execute in the same
order. The Go function names below appear alongside the Python and TypeScript
equivalents where they differ; the behavior at each stage is enforced to be
identical by the conformance test suite.

### Stage 1: reserved flag pre-scan

Before any global flag or command parsing begins, a pre-scan examines argv for
the 9 framework-reserved flags and removes the ones it consumes. The scan splits
argv into 2 regions with 2 different rulesets: the pre-command region recognizes
all 9, while the command region recognizes only 5 -- the 4 flags of the
effects-regime quartet plus `--json`. Both regions stop at a bare `--`, and the
command region also stops at a passthrough command's name.

**The pre-command region** -- everything before the first non-flag token or a
`--` separator -- recognizes every reserved flag:

- `--dump-schema`: triggers schema generation and exits immediately.
- `--mcp`: starts the MCP JSON-RPC server on stdin/stdout.
- `--hermetic`: enables hermetic mode (suppresses env vars and config file
  loading for the rest of the parse).
- `--config <path>`: overrides the config file path.
- The effects-regime quartet `--dry-run`, `--approve-consequential`, `--quiet`,
  `--verbose`.
- `--json`: selects machine mode. It is not a fifth member of the quartet --
  the four are the effects regime's own flags -- but it is delivered by the
  same rules, in both regions.

The pre-scan does not consume these tokens from argv for `--hermetic`,
`--config`, the quartet and `--json`; instead it records their presence and
builds a "cleaned argv" with them stripped out. `--dump-schema` and `--mcp`
cause an immediate return (no further parsing occurs).

The pre-scan also skips over known global flags (long, short, and negation
forms) so a global-flag value that happens to look like a command name does not
end the region early.

**The command region** -- from the command token onward -- recognizes the
**quartet and `--json` only**, anywhere, exactly like `--help` / `-h`. `myapp deploy --dry-run`
and `myapp --dry-run deploy` are equivalent; `myapp dns zone create --dry-run`
works at any nesting depth. `--hermetic`, `--config`, `--dump-schema` and `--mcp`
are *not* recognized here and become unknown-flag errors after the command token.

The command-region scan stops for good at two boundaries:

- **A bare `--`.** Every token after it is positional data, never a reserved
  flag: `myapp cmd -- --dry-run` passes the literal string `--dry-run` to the
  command.
- **A passthrough command's name.** A passthrough's args belong to the child
  process and are forwarded byte-for-byte, so `myapp exec --verbose child` gives
  the handler `["--verbose", "child"]` and leaves `ctx.verbose` false. The
  pre-command position is the escape hatch: `myapp --verbose exec --verbose child`
  sets `ctx.verbose` *and* still forwards the child's own `--verbose` untouched.

Anywhere-recognition costs exactly what `--help` already costs: a flag *value*
spelled like one of those tokens is eaten. Write `--message=--dry-run` or use
`--` to pass one literally.

**Go**: `App.preScanReservedFlags()` in `strictcli.go`.
**Python**: `App._pre_scan_reserved_flags()` in `__init__.py`.
**TypeScript**: `preScanReservedFlags()` in `parse.ts`.

### Stage 2: global flag parsing

The cleaned argv is scanned left-to-right for global flags. Global flags can
appear before the command name. The first token that is not a recognized global
flag (and is not `--`) is treated as the start of the command region; it and all
subsequent tokens become "remaining tokens."

Token forms recognized:

- `--flag-name value` (two tokens, value consumed)
- `--flag-name=value` (single token, `=`-split)
- `-x value` (short form, two tokens)
- `--no-flag-name` (boolean negation, single token)
- `--flag-name` alone for bool flags (sets to true)
- `--` stops global flag scanning; included in remaining tokens

After CLI tokens are consumed, env vars are resolved for any global flags that
were not set on the command line (skipped entirely under `--hermetic`). Then
config values are resolved for any global flags not set by CLI or env (again
skipped under `--hermetic`). Finally, defaults are applied for any global flags
still missing a value.

The result is a triple: `(global_values, global_sources, remaining_tokens)`.

**Go**: `App.extractGlobalFlags()` in `strictcli.go`.
**Python**: `App._parse_global_flags()` in `__init__.py`.
**TypeScript**: `extractGlobalFlags()` in `parse.ts`.

### Stage 3: command routing

The first token of the remaining argv selects a command or group. If it matches
a group, the router descends into that group and repeats the lookup with the
next token. This continues to arbitrary depth: App > Group > Group > ... >
Command.

At each level the router checks, in order:

1. Groups (descend if matched).
2. Commands (return the resolved command).
3. Deprecated commands (produce an error message with the deprecation notice).
4. Unknown (produce an error).

If a group is reached but no further tokens remain (or only `--help`), the
group's help text is displayed.

**Go**: `App.resolveCommand()` in `routing.go`.
**Python**: `App._resolve_command()` in `__init__.py`.
**TypeScript**: `resolveCommand()` in `routing.ts`.

### Stage 4: command parsing

The remaining tokens (after the command name was consumed by routing) are parsed
against the resolved command's declared flags and positional arguments. The
parser builds three lookup tables from the command's flags (long form, short
form, and negation form), then consumes tokens left-to-right. After CLI tokens
are processed, the value resolution cascade applies env vars, config values, and
defaults in that order, followed by constraint validation for mutex groups and
dependencies.

- **Long lookup**: `--flag-name` to flag definition.
- **Short lookup**: `-x` to flag definition.
- **Negation lookup**: `--no-flag-name` to flag definition (for negatable bool
  flags only).

Global flags are also added to these tables so they can be specified after the
command name.

Tokens are consumed left-to-right:

- If a token matches a long, short, or negation form, the corresponding value
  is consumed and stored.
- `--` stops flag parsing; all remaining tokens become positional arguments.
- Tokens starting with `-` that do not match any known flag are treated as
  positional arguments (allowing negative numbers like `-7`).
- All other tokens become positional arguments.

For non-bool flags, value coercion happens immediately at parse time:

- **str**: stored as-is after `@`-prefix resolution (`@file` reads from file,
  `@-` reads from stdin, `@@literal` strips the leading `@`).
- **bool**: `--flag` sets true, `--no-flag` sets false, no raw value accepted
  (`--flag=value` is an error).
- **int**: strict integer parsing -- no leading/trailing whitespace, no leading
  zeros (Go), 64-bit signed range. TypeScript uses `bigint` as its int type.
- **float**: strict float parsing in strictcli canonical form (SCF) -- NaN and
  Inf are rejected, the shortest round-trip representation is used.

After CLI tokens are consumed, the value resolution cascade runs (each step
skipped under `--hermetic`):

1. **Env vars**: for each flag not set by CLI, check its declared env var. Bool
   env vars accept `1|true|yes` / `0|false|no` (case-insensitive). Repeatable
   flags split the env value by the declared env_separator. Dict flags parse the
   env value as JSON.
2. **Config file**: for each flag not set by CLI or env, check the loaded config
   data. Config values are coerced to the flag's type.
3. **Presence resolution**: for each flag still unset, act on its declared
   presence. A `default` declaration supplies its value (source `default`); an
   `optional` declaration delivers absence -- `None` / `nil` / `undefined` as a
   present key, also labelled `default`, since the declaration is what decided;
   a `required` declaration with no value from any source produces a "missing
   required flag" error. There is no silent empty-collection default: a
   repeatable or dict flag that wants `[]` / `{}` declares it.
4. **InfraRootPath resolution**: if a flag's default is a `RelativeToRoot`
   marker, it is resolved against the declared infrastructure roots at this
   point, and its source is labeled "infra" instead of "default."

After all values are resolved, constraint validation runs:

- **Mutex groups**: exactly one member must be *elected*, and only a
  command-line token elects. A bool member elects only when it resolves to
  true, so `--no-x` declines instead of choosing; every other type elects on
  presence with any value. Env- and config-sourced values on a mutex member
  elect nothing and are dropped, so an unelected member delivers whatever its
  own presence declaration says -- its declared default, or absence when it
  declares `optional`. The group enforces cardinality on top of presence, never
  instead of it, and a member declaring `required` does not register. Two
  elections are "mutually exclusive", an election
  beside a declined member is "cannot be combined with", and no election is
  "one of ... is required". See the flag-system page for the full rules.
- **CoRequired**: all named flags must be present together, or none.
- **Requires**: if flag A is present, flag B must also be present.
- **Implies**: if flag A is present, flag B is automatically set to the implied
  value. If the user explicitly provided a contradicting value for B, it is a
  parse error.

Finally, choices validation runs for any flag or arg with a declared set of
allowed values.

**Go**: `parseCommand()` in `parse.go`.
**Python**: `_parse_command()` in `__init__.py`.
**TypeScript**: `parseCommand()` in `parse.ts`.

### Stage 5: dispatch

The handler is called with the resolved context and the kwargs map once all flag
values have been resolved and constraints validated. Each implementation has its
own handler signature, but all share the same strict contract: the return value
must be an exit code, nothing (implicit exit 0), or a branded outcome carrying
the exit code. Any other return type is a hard error.

- **Go**: `func(ctx *Context, kwargs map[string]interface{}) Outcome`
- **Python**: `def handler(ctx, **kwargs)` returning `int`, `None`, or
  `outcome(code)`
- **TypeScript**: `(args, ctx) => number | undefined | outcome(code)`

The return value is interpreted strictly. In Go, the handler must return an
`Outcome` (created via `Exit(code)`). In Python, only `int`, `None`, or a
branded `outcome(...)` are accepted; any other return type is a hard error. In
TypeScript, the same contract applies with `number`, `undefined`, or a branded
`outcome(...)`.

Structured output does not ride the return value. A command declares its
payload's JSON Schema at registration time and its handler supplies the value
through `ctx.payload(value)` / `ctx.Payload(value)` -- at most once per
dispatch, and only on a command that declared a schema. The payload is printed
only under the framework-owned `--json`; `Test()` / `test()` and `Call()` /
`call()` capture it in either mode.

## Source provenance

Every resolved flag value carries a source label tracking where its value came
from. Source provenance enables intelligent constraint evaluation: mutex checks
consider only the cli source, while dependency checks consider everything
except defaults. Handlers can inspect provenance at runtime
to alter behavior based on whether a value was explicitly provided or fell
through to its default. The six source labels are:

| Label | Meaning |
|-------|---------|
| `cli` | Explicitly passed on the command line |
| `env` | From an environment variable |
| `config` | From a config file |
| `default` | From the flag's declared default value -- and the label an `optional` declaration carries when nothing supplied a value |
| `implied` | Injected by an `Implies` dependency |
| `infra` | Default resolved through a `RelativeToRoot` infrastructure root |

No seventh label is minted for "declared optional, received nothing": `default`
already means "the declaration decided", and an optional declaration deciding on
absence is that.

Provenance is tracked internally by a `SourcedStore` (Go/TypeScript) or
`_SourcedStore` (Python) that pairs each value with its source label.
Provenance matters for constraint evaluation:

- **Mutex election** considers only the `cli` source. A member whose value came
  from `env` or `config` neither elects nor keeps that value: the entry is
  dropped before dependency validation, so the member ends up labeled `default`.
- **Dependency checks** (`CoRequired`, `Requires`, and the `Implies` trigger)
  consider `cli`, `env`, `config` and `implied`, and exclude both `default` and
  `infra`. A flag that got its value from `implied` is considered "present" for
  dependency purposes; a flag carrying only a declared default -- including a
  `RelativeToRoot` default with the `infra` label -- is not.

Handlers access provenance via `ctx.Source(name)` (Go) / `ctx.source(name)`
(Python) / `ctx.source(name)` (TypeScript). The name can be dashed
(`dry-run`) or underscored (`dry_run`); both forms are accepted.

For the yes/no question -- *did the invocation cause this value?* -- handlers use
`ctx.Provided(name)` (Go) / `ctx.provided(name)` (Python and TypeScript), which
reads the same predicate the dependency checks do, so the framework has one
definition of "was this supplied" rather than two. An unknown name behaves
exactly as it does on `ctx.source`, with the same message.

## Registration-time validation

strictcli enforces over 30 invariants at the moment flags, args, commands, and
groups are constructed. This is a deliberate design: if a declaration is
invalid, the program panics (Go), raises `ValueError` (Python), or throws a
`RegistrationError` (TypeScript) before any parsing occurs. The user never
sees a confusing runtime error caused by a misconfigured CLI. These checks
span 4 categories: flag naming, type checking, arg validation, and command
validation.

### Flag naming rules

Flag names are validated at registration time by `validateFlagConfig` (Go),
`Flag.__post_init__` (Python), and `validateFlagConfig` (TypeScript). These
rules prevent ambiguous flag names that would conflict with the framework's
automatic negation system, and ensure that every flag is self-documenting by
requiring help text. The bare name `force` is banned to prevent agents from
taking shortcuts with a generic override flag.

- **Help text is mandatory.** Every flag must have a non-empty help string.
- **Presence is mandatory.** Every flag declares exactly one of required,
  optional, or a default value. Declaring none names all three choices;
  declaring two names the two that were supplied; a null-valued default
  (`default=None` / `Default(nil)` / `default: null`) is refused with a
  redirect to the optional spelling.
- **`force` is banned.** The bare name `force` is reserved. Use a qualified
  name like `force-overwrite` or `force-delete`.
- **`no-` prefix is reserved.** Flag names cannot start with `no-`. This prefix
  is auto-generated by the negation system for negatable boolean flags.

### Type checking

The four scalar types (`str`, `bool`, `int`, `float`) and compound types
(`list[T]`, `dict[str,T]`) are strictly validated at registration time to catch
type mismatches, invalid defaults, and incompatible flag option combinations
before any user input is parsed. Every type constraint is enforced identically
across Python, Go, and TypeScript:

- Default values must match the declared type. A `float` flag with an `int`
  default is a hard error. A `str` flag with a `bool` default is a hard error.
- Choices must all be of the declared type.
- Compound types (`list[T]`, `dict[str,T]`) validate their element type at
  registration: `T` must be `str`, `int`, or `float` (never `bool`).
- Repeatable flags cannot be `bool`.
- Repeatable flags require explicit `unique` (true or false) -- no implicit
  default.
- A repeatable or dict flag declares presence like any other flag. An explicit
  `default=[]` / `default={}` is legal, and so is `optional` or `required`.
- `unique` requires `repeatable`.
- Dict flags cannot be combined with `repeatable`, `unique`, `choices`, or
  `env_separator`.
- `env_separator` requires `repeatable`, requires `env`, must be a single
  character, and cannot be a backslash.

### Arg validation

- Help text is mandatory.
- Presence is mandatory, with the same three facts and the same one-spelling
  rule flags use. There is no `required=` field on an arg.
- A variadic arg cannot declare a default: it always delivers a list, so the
  empty case is `optional`.
- Only scalar types and `list[T]` are allowed. `dict` types are not supported
  on positional args.
- `list[T]` requires `variadic=true`.
- Variadic args must be last.
- At most one variadic arg per command.
- Duplicate arg names within a command are a hard error.
- Choices type must match the arg's declared type.
- Default values must match the declared type and be in the choices set (if
  declared).

### Command validation

Command-level validation is enforced by `buildAndValidateCommand` (Go),
`_build_and_validate_command` (Python), and the equivalent validation in
`app.ts` (TypeScript). These checks verify that each command is internally
consistent: no duplicate flag names, no collisions with global flags, valid
mutex groups and dependency declarations, and mandatory help text on every
command.

- Help text is mandatory.
- Duplicate flag names within a command are a hard error.
- Flags cannot collide with global flags.
- Mutex groups must have at least 2 flags.
- A flag cannot appear in multiple mutex groups.
- `CoRequired` must reference at least 2 flags and all must be declared.
- `Requires` must reference declared flags and cannot be self-referential.
- `Implies` trigger and target must be bool flags; target must be different
  from trigger.
- Passthrough commands cannot have flags, args, flag sets, or mutex groups.

### Global flag validation

- Global flag names cannot collide with reserved framework names: `help`, `h`,
  `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`.
- Duplicate global flag names are a hard error.

### Tag validation

Tag names must match `[a-z][a-z0-9-]*`. Tag contracts (`TagContract` in Go,
`tag_contract` in Python) declare that any command tagged with a given tag must
have a specific flag; this is validated at `Run`/`Test` time across the entire
command tree.

## The schema format (`.strictcli/schema.json`)

`--dump-schema` is a reserved flag on every strictcli app. It writes a JSON file
describing the entire CLI surface -- every command, group, flag, positional
argument, constraint, and config field -- and prints the absolute path to
stdout. External tools like rlsbl use this schema during release to verify that
the CLI surface is up-to-date and that no flags or commands were silently
removed.

**Where it writes is declared, not discovered.** The location is decided once,
at App construction:

| Declaration | Result |
|-------------|--------|
| `schema_path="build/cli-schema.json"` (Python) / `WithSchemaPath(...)` (Go) / `schemaPath: ...` (TypeScript) | that path -- absolute, or relative to the construction-time working directory |
| `schema_path=RelativeToRoot("MYAPP_HOME", "schema.json")` / `WithSchemaPathRelativeToRoot(...)` / `schemaPath: relativeToRoot(...)` | resolved through the declared infrastructure root, eagerly, at construction |
| undeclared | `.strictcli/schema.json` **anchored at the construction-time working directory** |

The anchor is what keeps the write off the caller's working directory: a `chdir`
between construction and dispatch cannot move the file, exactly as it cannot
move the test-coverage root.

### Top-level fields

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `int` | Always `1` |
| `name` | `string` | App name |
| `version` | `string` | App version |
| `help` | `string` | App help text |
| `project_id` | `string` | Language-specific project identifier (Go module path, Python package name, npm package name) |
| `env_prefix` | `string?` | Env var prefix (null if not set) |
| `config` | `bool` | Whether config file support is enabled |
| `global_flags` | `Flag[]` | Global flag definitions |
| `commands` | `{name: Command}` | Top-level commands |
| `groups` | `{name: Group}` | Top-level groups |
| `deprecated` | `{name: message}` | Deprecated command names and messages |
| `tag_contracts` | `{tag: flag_name}` | Tag contract declarations |
| `defaults` | `object` | Default values for omitted fields (see below) |
| `config_fields` | `{name: ConfigFieldSchema}?` | Config field declarations (only when fields are declared) |
| `checks` | `{name: CheckSchema}?` | Check declarations (only when checks are enabled) |
| `infra` | `InfraSchema?` | Infrastructure env var declarations (only when roots/handshakes/connections exist) |

### Defaults object

The `defaults` key contains the canonical default value for every field that can
be omitted from the schema. A consumer reconstructs omitted fields by reading
from `defaults`. For example, if a flag has no `short` key, the consumer uses
`defaults.flag.short` (which is `null`). This convention keeps the schema
compact while remaining lossless.

`presence` appears in neither the `flag` nor the `arg` defaults, and that is
deliberate: it is **always emitted** on every flag and arg entry, so there is no
default to omit against. Its value is `"required"`, `"optional"` or `"default"`,
and a `default` key accompanies it exactly when `presence` is `"default"` --
then always, including for `[]`, `{}`, `""`, `false` and `0`. The arg entry's
old `required` key is deleted with the derivation behind it.

```json
{
  "schema_version": 1,
  "app": {
    "env_prefix": null,
    "config": false,
    "global_flags": [],
    "commands": {},
    "groups": {},
    "deprecated": {},
    "tag_contracts": {}
  },
  "flag": {
    "short": null,
    "default": null,
    "env": null,
    "choices": null,
    "repeatable": false,
    "unique": false,
    "env_separator": null,
    "negatable": null,
    "hidden": false
  },
  "arg": {
    "type": "str",
    "default": null,
    "variadic": false,
    "choices": null
  },
  "command": {
    "passthrough": false,
    "flags": [],
    "args": [],
    "tags": [],
    "constraints": [],
    "hidden": false,
    "interactive": false
  },
  "group": {
    "commands": {},
    "groups": {},
    "deprecated": {},
    "tags": [],
    "hidden": false
  }
}
```

### Constraint serialization

Constraints (mutex groups and dependencies) are serialized in the `constraints`
array of each command. The schema supports four constraint types: `mutex` for
mutually exclusive flag groups, `co_required` for flags that must appear
together, `requires` for one-way dependencies between flags, and `implies` for
automatic boolean flag injection when a trigger flag is present.

```json
[
  {"type": "mutex", "flags": ["as-table", "as-csv"]},
  {"type": "co_required", "flags": ["host", "port"]},
  {"type": "requires", "flag": "port", "depends_on": "host"},
  {"type": "implies", "flag": "trace", "implies": "debug", "value": true}
]
```

### InfraRootPath serialization

Flag defaults that are `RelativeToRoot` markers are serialized in a
machine-stable form that never contains resolved, machine-specific paths. The
serialized shape includes the environment variable name and the relative path
parts, allowing any consumer to reconstruct the absolute path on their own
machine. This representation is identical across all three implementations so
schemas byte-compare across languages.

```json
{
  "default": {
    "relative_to_root": {
      "env_var": "MY_ROOT",
      "parts": ["data", "cache"]
    }
  }
}
```

This shape is identical across all three implementations so schemas
byte-compare across languages.

### Schema freshness

The schema file is used by external tools (rlsbl uses it during release to
verify the CLI surface is up-to-date). A `project_id` field prevents accidental
overwrites across projects sharing a working directory: if the existing schema
file has a different `project_id`, the write is refused.

## How WithConfig works internally

Config file support is enabled via `WithConfig()` (Go), `App(config=True)`
(Python), or `createApp({config: true})` (TypeScript). When config support is
enabled, the framework auto-registers a `config` command group with five
subcommands for managing the configuration file, resolves the config file path
from XDG defaults or explicit overrides, and integrates config values into the
flag resolution cascade between env vars and defaults. Enabling it triggers the
following at construction time:

1. **Auto-registers the `config` group** with five subcommands: `config show`,
   `config set`, `config path`, `config edit`, `config init`.
2. **Resolves the config file path.** Default location is the XDG config
   directory: `~/.config/{app_name}/config.{json|toml}`. This can be overridden
   by `WithConfigPath(path)`, `WithConfigPathRelativeToRoot(envVar, parts...)`,
   or the runtime `--config <path>` flag.

### Config loading flow

Config data is loaded once per parse, at the start of the parse pipeline (after
the pre-scan, before global flag parsing). The loading process determines which
file to read based on a priority chain of runtime override, app-level override,
and XDG default path, then parses the file as JSON or TOML depending on the
configured format. Missing files are handled differently depending on whether
the path was explicitly provided or is the default:

1. Determine the path: runtime `--config` override > app-level override > XDG
   default. If `no_default_config_path` is set and no runtime override was
   given, no config file is loaded.
2. Read and parse the file. JSON files use the standard library parser; TOML
   files use the TOML library. Malformed files produce a parse error with line
   and column information.
3. If the file is missing: with a runtime `--config` flag, this is a hard
   error. Without one (default XDG path), it is silently ignored (empty config
   data).
4. The parsed config data is a flat or nested key-value map. Nested keys use
   dot-separated paths in TOML (e.g., `[database]` / `host = ...` becomes
   `database.host`).

### Config field declarations

`App.ConfigField(name, type, help, default)` (Go) / `app.config_field(name,
type, help, default)` (Python) declares a typed config-file-only field. Config
fields are validated at run time when their bound commands are dispatched:
required fields must be present with the correct type.

A config field whose name matches a flag's parameter name (the underscored
form) is a "colliding" field -- a validation-only annotation that ties the
flag to a config-file key. Their defaults must agree. The flag's config value
is resolved through the normal CLI > env > config > default cascade; the
config field does not create a separate config key.

### Config conflict modes

The `config_conflict_mode` (app-level) and `conflict_mode` (per-flag) control
what happens when a flag's value comes from both the config file and the CLI or
env var. The default mode is `cli-wins`, where command-line and environment
values take precedence over config file values. The alternative `error` mode
treats dual-source values as a hard error, enforcing that each flag has exactly
one explicit source of truth:

- `cli-wins` (default): the CLI or env value takes precedence. The config
  value is silently ignored.
- `error`: having a value from both sources is a hard error, unless the values
  are identical (in which case no conflict exists).

### Hermetic mode interaction

`--hermetic` skips config file loading entirely. Config subcommands cannot be
used with `--hermetic` (hard error). This is enforced in the pre-scan: if both
`--hermetic` and `--config` are present, parsing fails immediately.

## Flag negation system

Every boolean flag in strictcli automatically generates a `--no-{name}`
negation form, allowing callers to explicitly set a boolean flag to false on the
command line. This is a core part of strictcli's design philosophy: when a
boolean flag declares itself required, the caller must pass either `--flag` or
`--no-flag` explicitly, eliminating implicit assumptions about flag state.
Negation behavior is controlled by the `negatable` property:

- For `bool` flags, `negatable` defaults to `true`. The framework automatically
  populates the negation lookup table with `--no-{name}` pointing to the same
  flag.
- For non-bool flags (`str`, `int`, `float`, and compound types), `negatable`
  is forced to `false` regardless of what the user declares.

### How negation works at parse time

The negation lookup is a separate table built alongside the long and short
lookup tables during command parsing. For each negatable boolean flag, the
parser registers `--no-{name}` in the negation table pointing back to the
original flag definition. When a token like `--no-verbose` is encountered during
left-to-right token consumption, the parser checks the negation table first:

1. Look it up in the negation table. If found, set the flag's value to `false`
   with source `cli`.
2. If `--no-verbose=value` is encountered, it is an error: boolean negations
   do not take a value.

### The `no-` prefix ban

Flag names starting with `no-` are banned at registration time. This prevents
ambiguity: if a flag named `no-cache` existed, `--no-no-cache` would be its
negation form, which is confusing. The ban ensures the `--no-` prefix is
exclusively the framework's negation mechanism.

### Schema representation

In the schema JSON, bool flags always include the `negatable` key with an
explicit true or false value, making the negation behavior machine-readable for
external tools that consume the schema. Non-bool flags omit the key entirely
because negation is not applicable to them; the schema defaults section
specifies `null` as the default for `negatable`, which consumers interpret as
"not applicable to this flag type."

### Bool flags and the presence declaration

A bool flag declaring `required` forces the user to pass either `--flag` or
`--no-flag`, which is how a caller is made to state intent on a binary decision.
A bool declaring `Default(true)` or `Default(false)` falls through to that value.
A bool declaring `optional` is a genuine three-valued flag: `--flag` is true,
`--no-flag` is false, and absence is delivered as absence -- which is what
retires the "use a string and treat the empty string as unset" idiom.

## Error handling philosophy

strictcli follows a strict, no-silent-defaults error philosophy. Every error
condition produces a specific, actionable message with enough context to fix the
problem. There are no warnings that continue execution -- if something is wrong,
the framework fails immediately. Error messages are byte-identical across all
three implementations, enforced by the conformance suite's error parity check
that compares every error template one-to-one.

### Two error categories

1. **Registration-time errors** (programmer errors): these indicate a bug in
   the CLI definition. They produce a panic (Go), `ValueError` (Python), or
   `RegistrationError` (TypeScript). The program cannot start.

2. **Parse-time errors** (user errors): these indicate incorrect input. They
   print an error message to stderr with a `try '...' --help` hint and exit
   with code 1.

### Error message parity

All three implementations produce byte-identical error messages for identical
inputs. This is enforced by the `check_error_parity.py` conformance check,
which extracts every error template from all implementations and verifies
they match one-to-one.

Error templates are centralized in a single file per implementation:

- **Go**: `errors.go` -- functions returning format strings.
- **Python**: inline in `__init__.py` (using f-strings with the same
  placeholders as the Go templates).
- **TypeScript**: `errors.ts` -- functions returning format strings, mirroring
  `errors.go` one-to-one.

### No implicit defaults

strictcli does not silently fill in default values for configuration that
affects behavior, and it does not infer presence either: a flag or arg that
declares none of required / optional / default does not register at all. These
rules exist to prevent a common class of bugs where a CLI tool silently uses a
default that the caller did not know about.

A `required` bool must be explicitly passed as `--flag` or `--no-flag`. A
repeatable or dict flag gets no silent `[]` / `{}` -- it declares one, or
declares `optional`, or declares `required`. Repeatable flags require explicit
`unique` declaration. Env separator is mandatory for repeatable flags with env
var support.

### No unknown flags

Any `--flag` token that does not match a declared flag is a hard error. There
is no "ignore unknown flags" mode. This prevents silent typo bugs where
`--quite` (typo for `--quiet`) is silently ignored.

### Strict type parsing

Integer parsing rejects leading whitespace, trailing whitespace, and (in Go)
leading zeros. Float parsing rejects NaN and Inf. Bool env vars accept only
the exact set `1|true|yes` / `0|false|no` (case-insensitive); anything else is
an error.

## Conformance testing

The three implementations are kept in lockstep by a conformance test suite
(`conformance/`). JSON test cases define an app structure, argv, and expected
output. A runner generates the app in each language and executes it, comparing
results.

Conformance checks run as part of CI and include:

- **conformance-python/go/typescript**: all JSON test cases pass in each
  implementation.
- **conformance-parity**: outputs are byte-identical across implementations
  (with acknowledged divergences for language-specific output).
- **error-parity**: every error template exists in all implementations with
  identical format strings.
- **api-surface**: the public API surface matches across implementations.
- **schema-parity**: the schema JSON produced by each implementation is
  byte-identical for the same app definition.
- **float-fuzz**: exhaustive bit-pattern verification of the canonical float
  format (SCF) across all implementations.
