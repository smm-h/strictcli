---
title: Go Quickstart
description: "Build Go CLIs with strictcli: apps, WithEffect classification, flags, args, groups, the reserved quartet, and consequential consent on CLI, Call and MCP."
nav_group: "Guides"
nav_order: 1
---

# Go Quickstart

This guide walks through building a CLI application with the Go implementation of strictcli.

## Install

```bash
go get github.com/smm-h/strictcli/go/strictcli@latest
```

Import the package:

```go
import "github.com/smm-h/strictcli/go/strictcli"
```

## Creating an App

Every CLI starts with `NewApp`, which takes the application name, version
string, and help text as its three required arguments. Empty help text is a hard
error -- strictcli enforces self-documenting apps from the first line of code.
Additional options like `WithConfig()`, `WithEnvPrefix()`, and `WithConfigFormat()`
are passed as functional options after the help text.

```go validate
package main

import "github.com/smm-h/strictcli/go/strictcli"

func main() {
    app := strictcli.NewApp("mytool", "0.1.0", "A tool that does useful things")
    app.Command("hello", "Print a greeting", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        ctx.Info("Hello, world!")
        return strictcli.Exit(0)
    }, strictcli.WithEffect(strictcli.EffectReadOnly))
    app.Run()
}
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

Every command must declare what it does to the world. `WithEffect(...)` is a
mandatory `CmdOption` taking one of two exported constants -- there is no
default, and a command registered without it panics at registration time:

| Constant | Meaning |
|----------|---------|
| `strictcli.EffectReadOnly` | The command changes nothing. It never prompts, and calling a mutating member of the effects handle from it is a hard error at call time. |
| `strictcli.EffectMutating` | The command changes something. It participates in `--dry-run`, where its effects are recorded instead of performed. |

```go
app.Command("status", "Show deployment status", statusHandler,
    strictcli.WithEffect(strictcli.EffectReadOnly))

app.Command("deploy", "Deploy the app", deployHandler,
    strictcli.WithEffect(strictcli.EffectMutating))
```

Classification answers one question -- "should a dry run record this rather than
perform it?" It is deliberately **not** the same question as "is this dangerous
enough to interrupt someone for?", which is what
[`WithConsequential()`](#consequential-commands-and-the-confirm-protocol)
answers. A mutating command does not prompt unless it also declares itself
consequential.

Classification is a property of the command, so it is emitted in `--dump-schema`
output on every command entry and can be asserted against by check gates.
Deprecated commands are exempt: they have no handler, execute nothing, and
passing an effect to `app.Deprecated(...)` is a registration-time error.

## Handler Signature

Every command handler has a fixed signature that receives a context for
structured output and provenance, a map of parsed flag and arg values, and
returns a branded `Outcome` type that wraps the exit code and optional
structured data:

```go
func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome
```

- `ctx` provides structured output (`ctx.Info`, `ctx.Warn`, `ctx.Error`, `ctx.Debug`), provenance (`ctx.Source`), the four reserved-quartet values (`ctx.DryRun()`, `ctx.ApproveConsequential()`, `ctx.Quiet()`, `ctx.Verbose()`), and the effects handle (`ctx.Effects()`).
- `kwargs` is a map of flag and arg values, keyed by parameter name (dashes converted to underscores: `--log-file` becomes `log_file`). The reserved quartet is never in `kwargs` -- it arrives on `ctx`.
- Return `Exit(code)`. Structured output goes through `ctx.Payload(value)` on a command that declares `PayloadSchema(...)`, and is emitted under the framework-owned `--json`.

Use the typed helpers `Get` and `GetOpt` to extract values from kwargs:

```go
app.Command("greet", "Greet someone", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
    name := strictcli.Get[string](kwargs, "name")
    loud, provided := strictcli.GetOpt[bool](kwargs, "loud")

    msg := "Hello, " + name + "!"
    if provided && loud {
        msg = "HELLO, " + name + "!!!"
    }
    ctx.Info(msg)
    return strictcli.Exit(0)
}, strictcli.WithEffect(strictcli.EffectReadOnly), strictcli.WithFlags(
    strictcli.StringFlag("name", "Who to greet"),
    strictcli.BoolFlag("loud", "Shout the greeting", strictcli.Default(false)),
))
```

`Get[T]` panics if the key is absent, nil, or the wrong type. `GetOpt[T]` returns `(zero, false)` when the value is nil (not provided).

## Flags

strictcli provides 4 scalar flag constructors: `StringFlag`, `BoolFlag`,
`IntFlag`, and `FloatFlag`. The first 2 arguments (name and help) are always
required, and additional options like `Default()`, `Short()`, `Env()`, and
`Choices()` are passed as functional options. There are 7 available option
functions in total. A flag without a `Default()` is required -- the user must
provide it on every invocation.

### StringFlag

```go
strictcli.StringFlag("output", "Output file path")
strictcli.StringFlag("format", "Output format", strictcli.Default("json"))
strictcli.StringFlag("format", "Output format", strictcli.Choices("json", "yaml", "csv"))
```

A StringFlag with no `Default()` is required -- the user must provide it.

### BoolFlag

```go
strictcli.BoolFlag("cache", "Reuse the build cache", strictcli.Default(true))
strictcli.BoolFlag("watch", "Watch for changes")
```

Bool flags are negatable by default: `--cache` sets true, `--no-cache` sets false. A BoolFlag with no `Default()` is required -- the user must pass either `--flag` or `--no-flag` explicitly.

Note that `verbose` and `quiet` are not available as flag names: they belong to
the [reserved quartet](#the-reserved-flag-quartet) and arrive on `ctx` instead.

### IntFlag

```go
strictcli.IntFlag("port", "Server port", strictcli.Default(8080))
strictcli.IntFlag("retries", "Number of retries")
```

Integers are parsed strictly: no leading/trailing whitespace, 64-bit signed bounds, no leading zeros.

### FloatFlag

```go
strictcli.FloatFlag("threshold", "Score threshold", strictcli.Default(0.5))
strictcli.FloatFlag("rate", "Rate limit")
```

Float parsing rejects NaN and Inf.

### Flag Options

Options are passed as functional option arguments after the name and help text.
Multiple options can be combined on a single flag to set defaults, short aliases,
environment variable bindings, and value restrictions. The table below lists all
available options:

```go
strictcli.StringFlag("output", "Output file path",
    strictcli.Default("out.json"),   // Default value
    strictcli.Short("o"),            // -o shorthand
    strictcli.Env("MYTOOL_OUTPUT"),  // Read from env var
    strictcli.Choices("a", "b"),     // Restrict to choices
)
```

Available options:

| Option | Description |
|--------|-------------|
| `Default(v)` | Set default value. `Default(nil)` makes the flag optional with no value (displays `[optional]` in help). |
| `Short(s)` | Single-character short form (e.g., `Short("o")` for `-o`). |
| `Env(name)` | Environment variable to read from. Precedence: CLI > env > config > default. |
| `Choices(vals...)` | Restrict to specific values. Not available on bool flags. |
| `Prefixed(b)` | Whether env var prefix validation is applied (default: true). |
| `NegatableOpt(b)` | Override negation for bool flags (default: true for bool). |
| `ValidateFn(fn)` | Custom validation function. |

### Default(nil) for Optional Flags

Use `Default(nil)` when a flag is optional but has no meaningful default value.
This is distinct from omitting `Default()` entirely (which makes the flag
required) and from `Default("")` (which gives it an empty string default). In
help output, `Default(nil)` displays as `[optional]` instead of showing a
concrete default value:

```go
strictcli.StringFlag("config-path", "Override config location", strictcli.Default(nil))
```

In help output, this displays as `[optional]` rather than `[default: <nil>]`.

## Positional Arguments

Use `NewArg` to declare positional arguments passed via `WithArgs()`. Arguments
are required by default and are consumed in declaration order after all flags
have been parsed. Optional arguments use `ArgRequired(false)` and may declare a
default value via `ArgDefault()`.

```go
app.Command("deploy", "Deploy to an environment", handler,
    strictcli.WithEffect(strictcli.EffectMutating),
    strictcli.WithArgs(
        strictcli.NewArg("environment", "Target environment"),
        strictcli.NewArg("version", "Version to deploy", strictcli.ArgRequired(false), strictcli.ArgDefault("latest")),
    ),
)
```

Arg options:

| Option | Description |
|--------|-------------|
| `ArgRequired(b)` | Whether the argument is required (default: true). |
| `ArgDefault(v)` | Default value (only valid on non-required args). |
| `ArgType(t)` | Type (default: `TypeStr`). Accepts `TypeStr`, `TypeBool`, `TypeInt`, `TypeFloat`. |
| `ArgChoices(vals...)` | Restrict to specific values. |
| `Variadic()` | Collect all remaining positional values (must be the last arg). |

### Variadic Arguments

A variadic argument collects all remaining positional values into a slice. It
must be the last argument in the command's declaration, and only one variadic
argument is allowed per command. A variadic argument with the default required
setting needs at least one value to be provided.

```go
app.Command("process", "Process files", handler,
    strictcli.WithEffect(strictcli.EffectReadOnly),
    strictcli.WithArgs(
        strictcli.NewArg("files", "Files to process", strictcli.Variadic()),
    ),
)
```

Only one variadic argument is allowed, and it must be the last.

## Global Flags

Global flags are available to all commands and can appear before or after the
command name in argv. They are parsed during the global flag parsing stage,
before the command is resolved. Global flag names cannot collide with reserved
framework names like `help`, `version`, `dump-schema`, `mcp`, `config`, or
`hermetic`, nor with the reserved quartet.

```go
app := strictcli.NewApp("mytool", "0.1.0", "A useful tool")
app.GlobalFlag(strictcli.BoolFlag("color", "Colorize output", strictcli.Default(true)))
app.GlobalFlag(strictcli.StringFlag("log-level", "Log level", strictcli.Default("info"), strictcli.Choices("debug", "info", "warn", "error")))

app.Command("deploy", "Deploy the app", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
    color := strictcli.Get[bool](kwargs, "color")
    if !color {
        ctx.Info("Color disabled")
    }
    return strictcli.Exit(0)
}, strictcli.WithEffect(strictcli.EffectMutating))
```

Usage: `mytool --no-color deploy` or `mytool deploy --no-color` (global flags can appear before or after the command).

Reserved global flag names that cannot be used: `help`, `h`, `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`, plus the reserved quartet `dry-run`, `approve-consequential`, `quiet`, `verbose`. The name `yes` is banned outright -- the confirmation skip is `--approve-consequential`.

## Command Groups

Groups organize commands into namespaces, creating a hierarchical command
structure like `mytool dns zone list`. Groups can nest to arbitrary depth, and
each group requires a name and help text. When a group is reached without a
subcommand, the group's help text is displayed.

```go
app := strictcli.NewApp("mytool", "0.1.0", "Infrastructure tool")

dns := app.Group("dns", "DNS management")
dns.Command("list", "List DNS records", listHandler,
    strictcli.WithEffect(strictcli.EffectReadOnly))
dns.Command("create", "Create a DNS record", createHandler,
    strictcli.WithEffect(strictcli.EffectMutating))

zone := dns.Group("zone", "Zone management")
zone.Command("list", "List zones", zoneListHandler,
    strictcli.WithEffect(strictcli.EffectReadOnly))
zone.Command("delete", "Delete a zone", zoneDeleteHandler,
    strictcli.WithEffect(strictcli.EffectMutating), strictcli.WithConsequential())
```

Usage:

```
$ mytool dns list
$ mytool dns create --name example.com
$ mytool dns zone list
$ mytool dns zone delete --name example.com
```

## Flag Naming Conventions

strictcli enforces strict flag naming rules at registration time. Violations
cause panics because they are programmer errors that should be caught during
development, not runtime errors that users encounter. These rules prevent
ambiguous flag names and ensure the `--no-` negation namespace remains
uncontaminated.

### Bare `--force` is banned

The flag name cannot be exactly `"force"` because a generic force flag lets
automation bypass guardrails without specifying what is being forced. Use a
qualified name that describes the specific action being forced, making the
intent explicit and auditable:

```go
// This panics:
strictcli.BoolFlag("force", "Force the operation", strictcli.Default(false))

// Use a qualified name instead:
strictcli.BoolFlag("force-overwrite", "Overwrite existing files", strictcli.Default(false))
strictcli.BoolFlag("force-delete", "Delete without confirmation", strictcli.Default(false))
```

### `--no-*` prefix is reserved

Flag names cannot start with `no-` because the `--no-` prefix is auto-generated
by the negation system for boolean flags. Allowing user-defined flags in this
namespace would create double-negation ambiguity where `--no-no-cache` becomes
the negation form of a flag named `no-cache`:

```go
// This panics:
strictcli.BoolFlag("no-cache", "Disable caching", strictcli.Default(false))

// Use a positive name instead:
strictcli.BoolFlag("cache", "Enable caching", strictcli.Default(true))
// Users pass --no-cache to disable
```

### The reserved flag quartet

Four flag names are owned by the framework and cannot be declared at any level --
not as app global flags, not as command flags, not inside a flag set, not inside
a mutex group:

| Flag | Delivered as | Meaning |
|------|-------------|---------|
| `--dry-run` | `ctx.DryRun()` | Record effects instead of performing them, then print the would-do log |
| `--approve-consequential` | `ctx.ApproveConsequential()` | Answer the confirm prompt in advance |
| `--quiet` | `ctx.Quiet()` | Suppress `ctx.Info` output; warnings and errors still print |
| `--verbose` | `ctx.Verbose()` | Enable `ctx.Debug` output |

```go
// Every one of these panics:
strictcli.BoolFlag("dry-run", "Simulate the run", strictcli.Default(false))
strictcli.BoolFlag("verbose", "Be verbose", strictcli.Default(false))
strictcli.BoolFlag("quiet", "Be quiet", strictcli.Default(false))
```

The panic message is `flag name 'dry-run' is reserved by the framework
(dry-run, approve-consequential, quiet, verbose)`. The name `yes` is banned
outright with its own message pointing at `--approve-consequential`, so that a
private `--yes` cannot restate the confirmation skip in a different spelling.

All four are recognized anywhere in argv: `mytool deploy --dry-run` and
`mytool --dry-run deploy` are equivalent. Two boundaries stop the scan -- a bare
`--` (everything after it is data) and a passthrough command's name (its args
are forwarded to the child byte-for-byte).

### Refusing `--dry-run` with `WithDryRunUnsupported`

`--dry-run` works on every mutating command by default: its effects are recorded
rather than performed. Some commands cannot honor that honestly -- their effects
escape the effects handle, or their later steps read state that their earlier
(recorded, therefore un-performed) steps would have written. Such a command
declares the refusal with a mandatory reason:

```go
app.Command("migrate", "Run pending database migrations", migrateHandler,
    strictcli.WithEffect(strictcli.EffectMutating),
    strictcli.WithDryRunUnsupported(
        "each migration reads the schema the previous one wrote, "+
            "so a recorded run would report the wrong pending set"),
)
```

`--dry-run` is then refused at parse time rather than rendering a preview that
would lie:

```
$ mytool migrate --dry-run
error: --dry-run is not supported by command 'migrate': each migration reads the schema the previous one wrote, so a recorded run would report the wrong pending set
```

Two guardrails apply at registration time:

- `WithDryRunUnsupported` on a `read_only` command panics -- a command that changes nothing has no effects a preview could misrepresent.
- An empty reason panics -- say what a preview cannot honestly show.

The reason also appears in the command's help under a `Dry run:` section, and in
`--dump-schema` output as the pair `dry_run_supported` / `dry_run_unsupported_reason`.
Both keys are emitted only when declared, so a schema entry without them means
dry run is supported. `--help` always beats the refusal: asking what a command
does is never answered with a refusal to preview it.

## Consequential Commands and the Confirm Protocol

Classification says whether a dry run should record rather than perform.
`WithConsequential()` says something different: that these effects are worth
interrupting a human for. It is the **only** thing that makes the framework
prompt -- a plain mutating command never does.

```go
app.Command("destroy", "Destroy the cluster", destroyHandler,
    strictcli.WithEffect(strictcli.EffectMutating),
    strictcli.WithConsequential(),
    strictcli.WithArgs(strictcli.NewArg("cluster", "Cluster to destroy")),
)
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
`app.Test()` behaves as if `--approve-consequential` were passed; `app.Call()`
and the MCP server take the consent from the call instead and refuse a
consequential command without it:

```go
// Refused: command 'destroy' is consequential: pass approve_consequential to confirm
_, err := app.Call("destroy", map[string]interface{}{"env": "prod"})

// Proceeds
_, err = app.Call("destroy", map[string]interface{}{"env": "prod"},
    strictcli.WithApproveConsequential())
```

Over MCP the same consent is a top-level `tools/call` param, a sibling of
`name` and `arguments`, never a member of `arguments`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"destroy","arguments":{"env":"prod"},"approve_consequential":true}}
```

This is not human approval and is not meant to be: it makes the caller state,
in the call, that it is proceeding without a human. Tool descriptors and MCP
`tools/list` publish `Effect` and `Consequential` beside the argument schema so
a caller can see the requirement before it calls. There is no bypass flag:
`--approve-consequential` answers the prompt and does nothing else. A read-only
command cannot be declared consequential -- a command that changes nothing has
nothing to confirm -- and trying panics at registration time.

A consequential passthrough command is not exempt. The framework knows *less*
about what is about to happen there, not more.

### Help text is mandatory

Every flag, arg, command, group, and app must have non-empty help text. Missing
or empty help is a registration-time panic with no opt-out. This ensures that
every strictcli application is self-documenting from the first line of code, and
users always have access to meaningful help for every flag and command.

## Mutex Groups

Declare mutually exclusive flags using `WithMutex` and `MutexGroup`. At most
one flag in the group may have a value from an explicit source (CLI, env, or
config). If no flag in the group has a value and no defaults exist, a "one of
... is required" error is produced:

```go
app.Command("output", "Produce output", handler,
    strictcli.WithEffect(strictcli.EffectReadOnly),
    strictcli.WithMutex(strictcli.MutexGroup{
        Flags: []strictcli.Flag{
            strictcli.StringFlag("file", "Write to file"),
            strictcli.BoolFlag("stdout", "Write to stdout"),
        },
    }),
)
```

## Dependencies

Declare relationships between flags using `WithDependencies`. Three dependency
types are available: `Requires` (one-way dependency), `CoRequired` (must appear
together or not at all), and `Implies` (automatically sets a target flag when a
trigger is provided):

```go
app.Command("deploy", "Deploy the app", handler,
    strictcli.WithEffect(strictcli.EffectMutating),
    strictcli.WithFlags(
        strictcli.StringFlag("target", "Deploy target"),
        strictcli.StringFlag("region", "Target region"),
        strictcli.BoolFlag("canary", "Roll out to the canary fleet first", strictcli.Default(false)),
        strictcli.BoolFlag("wait", "Block until the rollout settles", strictcli.Default(false)),
    ),
    strictcli.WithDependencies(
        // --region requires --target to be present
        strictcli.Requires{Flag: "region", DependsOn: "target"},
        // --target and --region must both appear or neither
        strictcli.CoRequired{Flags: []string{"target", "region"}},
        // --canary implies --wait=true
        strictcli.Implies{Flag: "canary", Implies: "wait", Value: true},
    ),
)
```

Dependencies cannot reference the reserved quartet: `dry-run` is not a flag you
declare, so it cannot be a `Requires` target or an `Implies` subject.

## WithConfig -- Config File Support

`WithConfig()` enables automatic config file loading from the XDG config
directory and registers five `config` subcommands (`show`, `set`, `path`,
`edit`, `init`) for managing the configuration file. Config values participate
in the flag resolution cascade between env vars and defaults, with precedence
CLI > env > config > default.

```go
app := strictcli.NewApp("mytool", "0.1.0", "A configurable tool",
    strictcli.WithConfig(),
    strictcli.WithEnvPrefix("MYTOOL"),
)

app.Command("run", "Run the tool", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
    port := strictcli.Get[int](kwargs, "port")
    ctx.Info(fmt.Sprintf("Listening on port %d", port))
    return strictcli.Exit(0)
}, strictcli.WithEffect(strictcli.EffectReadOnly), strictcli.WithFlags(
    strictcli.IntFlag("port", "Server port", strictcli.Default(8080), strictcli.Env("MYTOOL_PORT")),
))
```

Config files live at `~/.config/mytool/config.json` by default. Value precedence: CLI > env > config > default.

### Config format

Default format is JSON. Use TOML with `WithConfigFormat("toml")` for
human-editable configuration files with comments. TOML parsing is strict and
rejects TOML-1.1-only constructs to maintain parity with the Python and Go
parsers:

```go
app := strictcli.NewApp("mytool", "0.1.0", "A configurable tool",
    strictcli.WithConfig(),
    strictcli.WithConfigFormat("toml"),
)
```

### Auto-registered config commands

When config is enabled, these five subcommands are registered automatically
under a `config` group. They provide a complete config management interface
without writing any additional code, covering display, modification, path
inspection, editor integration, and initialization of the config file with
default values:

- `mytool config show` -- display current config with value sources
- `mytool config set <key> <value>` -- set a config value
- `mytool config path` -- print the config file path
- `mytool config edit` -- open the config file in `$EDITOR`
- `mytool config init` -- create the config file with defaults

### Config path override

Override the config path at the CLI level with `--config <path>` (a reserved
global flag), or at construction time with `WithConfigPath(path)`. The CLI
override takes precedence over the construction-time path, which takes
precedence over the default XDG location. Using `--config` with a missing file
is a hard error:

```go
strictcli.WithConfigPath("/etc/mytool/config.json")
```

### Hermetic mode

`--hermetic` is a reserved global flag on every app. It skips config file loading and env var resolution entirely. Values come only from CLI tokens, declared defaults, and infrastructure roots.

## Schema Dump

Every strictcli app automatically supports `--dump-schema`, a reserved flag
that writes a JSON file describing the full CLI structure to
`.strictcli/schema.json` and prints the absolute path to stdout. The schema
includes all commands, flags, args, groups, constraints, and config field
declarations, and is used by external tools like rlsbl to verify that the CLI
surface stays in sync with documentation:

```
$ mytool --dump-schema
.strictcli/schema.json
```

The schema includes all commands, flags, args, groups, and their metadata. It is used by tools like rlsbl to keep documentation in sync with the CLI surface.

## Testing

Use `app.Test(argv)` to run the CLI in-process and capture output without
shelling out. The `Result` struct contains `Stdout`, `Stderr`, `ExitCode`, and
`Data` (the machine payload the handler supplied through `ctx.Payload`). This is the standard way to test
strictcli apps in Go unit tests:

```go
func TestGreet(t *testing.T) {
    app := strictcli.NewApp("mytool", "0.1.0", "test app")
    app.Command("greet", "Say hello", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        name := strictcli.Get[string](kwargs, "name")
        ctx.Info("Hello, " + name + "!")
        return strictcli.Exit(0)
    }, strictcli.WithEffect(strictcli.EffectReadOnly), strictcli.WithFlags(
        strictcli.StringFlag("name", "Who to greet"),
    ))

    r := app.Test([]string{"greet", "--name", "Alice"})
    if r.ExitCode != 0 {
        t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
    }
    if !strings.Contains(r.Stdout, "Hello, Alice!") {
        t.Fatalf("unexpected stdout: %q", r.Stdout)
    }
}
```

The `Result` struct contains `Stdout`, `Stderr`, `ExitCode`, and `Data` (the machine payload the handler supplied through `ctx.Payload`).

## Deprecated Commands

Register retired commands that print a deprecation message to stderr and exit
with code 1. Deprecated commands appear in help output under a `Deprecated:`
section, giving users visibility into the migration path:

```go
app.Deprecated("old-deploy", "Use 'deploy' instead. See https://example.com/migration")
```

## Passthrough Commands

Passthrough commands bypass all flag and argument parsing and forward raw args
directly to the handler. They are useful for wrapping external tools where the
argument format is not known in advance. Passthrough commands cannot have flags,
args, flag sets, or mutex groups:

```go
app.Passthrough("exec", "Execute a command", func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{}) int {
    ctx.Info(fmt.Sprintf("Running: %s %v", name, args))
    return 0
}, strictcli.WithEffect(strictcli.EffectMutating))
```

A passthrough is an ordinary command registration in Go, so it takes
`WithEffect(...)` like everything else, and may add `WithConsequential()`.
Because its args are forwarded to the child byte-for-byte, the reserved quartet
is not scanned after the passthrough command's name: `mytool exec deploy --dry-run`
passes `--dry-run` to the child.

## Full Example

```go validate
package main

import (
    "fmt"

    "github.com/smm-h/strictcli/go/strictcli"
)

func main() {
    app := strictcli.NewApp("deploy-tool", "0.1.0", "Deployment management tool",
        strictcli.WithConfig(),
        strictcli.WithEnvPrefix("DEPLOY"),
    )

    app.GlobalFlag(strictcli.BoolFlag("color", "Colorize output", strictcli.Default(true)))

    app.Command("status", "Show deployment status", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        env := strictcli.Get[string](kwargs, "environment")
        ctx.Debug(fmt.Sprintf("Checking status for environment: %s", env))
        ctx.Payload(map[string]interface{}{
            "environment": env,
            "status":      "healthy",
        })
        return strictcli.Exit(0)
    }, strictcli.WithEffect(strictcli.EffectReadOnly),
        strictcli.PayloadSchema(map[string]interface{}{"type": "object"}),
        strictcli.WithFlags(
        strictcli.StringFlag("environment", "Target environment",
            strictcli.Default("production"),
            strictcli.Short("e"),
            strictcli.Choices("production", "staging", "dev"),
        ),
    ))

    svc := app.Group("service", "Service management")
    svc.Command("restart", "Restart a service", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        name := strictcli.Get[string](kwargs, "name")
        timeout := strictcli.Get[int](kwargs, "timeout")
        ctx.Info(fmt.Sprintf("Restarting %s (timeout: %ds)", name, timeout))
        return strictcli.Exit(0)
    }, strictcli.WithEffect(strictcli.EffectMutating), strictcli.WithConsequential(),
        strictcli.WithFlags(
            strictcli.StringFlag("name", "Service name"),
            strictcli.IntFlag("timeout", "Shutdown timeout in seconds", strictcli.Default(30)),
        ))

    app.Run()
}
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
