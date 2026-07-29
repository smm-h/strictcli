---
title: Go Quickstart
description: "Getting started with strictcli in Go: install, create apps, define commands, add flags and args, use groups, and enable config/schema support."
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

Every CLI starts with `NewApp`. All three arguments (name, version, help) are required. Empty help text is a hard error.

```go
package main

import "github.com/smm-h/strictcli/go/strictcli"

func main() {
    app := strictcli.NewApp("mytool", "0.1.0", "A tool that does useful things")
    app.Command("hello", "Print a greeting", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        ctx.Info("Hello, world!")
        return strictcli.Exit(0)
    })
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

## Handler Signature

Every command handler has the signature:

```go
func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome
```

- `ctx` provides structured output (`ctx.Info`, `ctx.Warn`, `ctx.Error`, `ctx.Debug`) and provenance (`ctx.Source`).
- `kwargs` is a map of flag and arg values, keyed by parameter name (dashes converted to underscores: `--dry-run` becomes `dry_run`).
- Return `Exit(code)` for exit-code-only results, or `ExitData(code, data)` to emit structured JSON data to stdout.

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
}, strictcli.WithFlags(
    strictcli.StringFlag("name", "Who to greet"),
    strictcli.BoolFlag("loud", "Shout the greeting", strictcli.Default(false)),
))
```

`Get[T]` panics if the key is absent, nil, or the wrong type. `GetOpt[T]` returns `(zero, false)` when the value is nil (not provided).

## Flags

strictcli provides four scalar flag constructors. The first two arguments (name, help) are always required. Additional options are passed as functional options.

### StringFlag

```go
strictcli.StringFlag("output", "Output file path")
strictcli.StringFlag("format", "Output format", strictcli.Default("json"))
strictcli.StringFlag("format", "Output format", strictcli.Choices("json", "yaml", "csv"))
```

A StringFlag with no `Default()` is required -- the user must provide it.

### BoolFlag

```go
strictcli.BoolFlag("verbose", "Enable verbose output", strictcli.Default(false))
strictcli.BoolFlag("watch", "Watch for changes")
```

Bool flags are negatable by default: `--verbose` sets true, `--no-verbose` sets false. A BoolFlag with no `Default()` is required -- the user must pass either `--flag` or `--no-flag` explicitly.

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

Options are passed after the name and help:

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

Use `Default(nil)` when a flag is optional but has no meaningful default:

```go
strictcli.StringFlag("config-path", "Override config location", strictcli.Default(nil))
```

In help output, this displays as `[optional]` rather than `[default: <nil>]`.

## Positional Arguments

Use `NewArg` to declare positional arguments. Arguments are required by default.

```go
app.Command("deploy", "Deploy to an environment", handler,
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

A variadic argument collects all remaining positional values into a slice:

```go
app.Command("process", "Process files", handler,
    strictcli.WithArgs(
        strictcli.NewArg("files", "Files to process", strictcli.Variadic()),
    ),
)
```

Only one variadic argument is allowed, and it must be the last.

## Global Flags

Global flags are available to all commands. They appear before the command name in argv.

```go
app := strictcli.NewApp("mytool", "0.1.0", "A useful tool")
app.GlobalFlag(strictcli.BoolFlag("verbose", "Enable verbose output", strictcli.Default(false)))
app.GlobalFlag(strictcli.StringFlag("log-level", "Log level", strictcli.Default("info"), strictcli.Choices("debug", "info", "warn", "error")))

app.Command("deploy", "Deploy the app", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
    verbose := strictcli.Get[bool](kwargs, "verbose")
    if verbose {
        ctx.Info("Verbose mode enabled")
    }
    return strictcli.Exit(0)
})
```

Usage: `mytool --verbose deploy` or `mytool deploy --verbose` (global flags can appear before or after the command).

Reserved global flag names that cannot be used: `help`, `h`, `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`.

## Command Groups

Groups organize commands into namespaces. Groups can nest to arbitrary depth.

```go
app := strictcli.NewApp("mytool", "0.1.0", "Infrastructure tool")

dns := app.Group("dns", "DNS management")
dns.Command("list", "List DNS records", listHandler)
dns.Command("create", "Create a DNS record", createHandler)

zone := dns.Group("zone", "Zone management")
zone.Command("list", "List zones", zoneListHandler)
zone.Command("delete", "Delete a zone", zoneDeleteHandler)
```

Usage:

```
$ mytool dns list
$ mytool dns create --name example.com
$ mytool dns zone list
$ mytool dns zone delete --name example.com
```

## Flag Naming Conventions

strictcli enforces strict flag naming rules at registration time. Violations are panics (programmer errors caught at startup).

### Bare `--force` is banned

The flag name cannot be exactly `"force"`. Use a qualified name that describes what is being forced:

```go
// This panics:
strictcli.BoolFlag("force", "Force the operation", strictcli.Default(false))

// Use a qualified name instead:
strictcli.BoolFlag("force-overwrite", "Overwrite existing files", strictcli.Default(false))
strictcli.BoolFlag("force-delete", "Delete without confirmation", strictcli.Default(false))
```

### `--no-*` prefix is reserved

Flag names cannot start with `no-`. The `--no-` prefix is auto-generated by the negation system for bool flags:

```go
// This panics:
strictcli.BoolFlag("no-cache", "Disable caching", strictcli.Default(false))

// Use a positive name instead:
strictcli.BoolFlag("cache", "Enable caching", strictcli.Default(true))
// Users pass --no-cache to disable
```

### Help text is mandatory

Every flag, arg, command, group, and app must have non-empty help text. Missing help is a registration-time panic.

## Mutex Groups

Declare mutually exclusive flags -- exactly one must be provided:

```go
app.Command("output", "Produce output", handler,
    strictcli.WithMutex(strictcli.MutexGroup{
        Flags: []strictcli.Flag{
            strictcli.StringFlag("file", "Write to file"),
            strictcli.BoolFlag("stdout", "Write to stdout"),
        },
    }),
)
```

## Dependencies

Declare relationships between flags using `WithDependencies`:

```go
app.Command("deploy", "Deploy the app", handler,
    strictcli.WithFlags(
        strictcli.StringFlag("target", "Deploy target"),
        strictcli.StringFlag("region", "Target region"),
        strictcli.BoolFlag("dry-run", "Simulate the deploy", strictcli.Default(false)),
        strictcli.BoolFlag("auto-approve", "Skip confirmation", strictcli.Default(false)),
    ),
    strictcli.WithDependencies(
        // --region requires --target to be present
        strictcli.Requires{Flag: "region", DependsOn: "target"},
        // --target and --region must both appear or neither
        strictcli.CoRequired{Flags: []string{"target", "region"}},
        // --auto-approve implies --dry-run=false
        strictcli.Implies{Flag: "auto-approve", Implies: "dry-run", Value: false},
    ),
)
```

## WithConfig -- Config File Support

`WithConfig()` enables automatic config file loading and registers `config show/set/path/edit/init` subcommands.

```go
app := strictcli.NewApp("mytool", "0.1.0", "A configurable tool",
    strictcli.WithConfig(),
    strictcli.WithEnvPrefix("MYTOOL"),
)

app.Command("run", "Run the tool", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
    port := strictcli.Get[int](kwargs, "port")
    ctx.Info(fmt.Sprintf("Listening on port %d", port))
    return strictcli.Exit(0)
}, strictcli.WithFlags(
    strictcli.IntFlag("port", "Server port", strictcli.Default(8080), strictcli.Env("MYTOOL_PORT")),
))
```

Config files live at `~/.config/mytool/config.json` by default. Value precedence: CLI > env > config > default.

### Config format

Default format is JSON. Use TOML with `WithConfigFormat("toml")`:

```go
app := strictcli.NewApp("mytool", "0.1.0", "A configurable tool",
    strictcli.WithConfig(),
    strictcli.WithConfigFormat("toml"),
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

Override the config path at the CLI level with `--config <path>`, or at construction with `WithConfigPath(path)`:

```go
strictcli.WithConfigPath("/etc/mytool/config.json")
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

Use `app.Test(argv)` to run the CLI in-process and capture output:

```go
func TestGreet(t *testing.T) {
    app := strictcli.NewApp("mytool", "0.1.0", "test app")
    app.Command("greet", "Say hello", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        name := strictcli.Get[string](kwargs, "name")
        ctx.Info("Hello, " + name + "!")
        return strictcli.Exit(0)
    }, strictcli.WithFlags(
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

The `Result` struct contains `Stdout`, `Stderr`, `ExitCode`, and `Data` (structured data from `ExitData`).

## Deprecated Commands

Register retired commands that print a message and exit 1:

```go
app.Deprecated("old-deploy", "Use 'deploy' instead. See https://example.com/migration")
```

## Passthrough Commands

Passthrough commands bypass all flag/arg parsing and forward raw args to the handler:

```go
app.Passthrough("exec", "Execute a command", func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{}) int {
    ctx.Info(fmt.Sprintf("Running: %s %v", name, args))
    return 0
})
```

## Full Example

```go
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

    app.GlobalFlag(strictcli.BoolFlag("verbose", "Enable verbose output", strictcli.Default(false)))

    app.Command("status", "Show deployment status", func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        verbose := strictcli.Get[bool](kwargs, "verbose")
        env := strictcli.Get[string](kwargs, "environment")
        if verbose {
            ctx.Info(fmt.Sprintf("Checking status for environment: %s", env))
        }
        return strictcli.ExitData(0, map[string]interface{}{
            "environment": env,
            "status":      "healthy",
        })
    }, strictcli.WithFlags(
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
    }, strictcli.WithFlags(
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

$ deploy-tool --verbose service restart --name api --timeout 60
Checking status for environment: production
Restarting api (timeout: 60s)

$ deploy-tool config show
$ deploy-tool --dump-schema
```
