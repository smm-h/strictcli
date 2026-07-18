# strictcli

A strict CLI framework for Go.

strictcli makes you declare everything -- every command, flag, argument, and environment variable must have help text or the framework panics at registration time. Four types only: `str`, `bool`, `int`, `float`. No magic type inference, no implicit defaults.

## Installation

```
go get github.com/smm-h/strictcli/go/strictcli
```

Requires Go 1.25+. One dependency: [go-toml-edit](https://github.com/smm-h/go-toml-edit) for TOML config/checks support.

## Quickstart

```go
package main

import (
    "fmt"
    "strings"

    "github.com/smm-h/strictcli/go/strictcli"
)

func main() {
    app := strictcli.NewApp("greet", "1.0.0", "A greeting app")

    app.Command("hello", "Say hello",
        func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
            name := strictcli.Get[string](kwargs, "name")
            loud := strictcli.Get[bool](kwargs, "loud")
            msg := fmt.Sprintf("Hello, %s!", name)
            if loud {
                msg = strings.ToUpper(msg)
            }
            ctx.Info(msg)
            return strictcli.Exit(0)
        },
        strictcli.WithFlags(
            strictcli.StringFlag("name", "Who to greet"),
            strictcli.BoolFlag("loud", "Shout it", strictcli.Default(false)),
        ),
    )

    app.Run()
}
```

Name, version, and help are all required `NewApp` arguments.

```
$ greet hello --name World
Hello, World!

$ greet hello --name World --loud
HELLO, WORLD!

$ greet hello --help
greet hello -- Say hello

Flags:
  --name <str>         Who to greet [required]
  --loud, --no-loud    Shout it [default: false]
```

## Features

### Commands and groups

Top-level commands with `app.Command`, nested groups with `app.Group`. Groups nest recursively to arbitrary depth via `group.Group`.

```go
db := app.Group("db", "Database operations")
schema := db.Group("schema", "Schema management")

schema.Command("migrate", "Run migrations",
    func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome {
        ctx.Info("migrating")
        return strictcli.Exit(0)
    },
)
```

Invoked as `myapp db schema migrate`.

### Four flag types

`StringFlag`, `BoolFlag`, `IntFlag`, `FloatFlag`. No magic coercion -- parse errors are clear and immediate.

```go
strictcli.StringFlag("output", "Output path", strictcli.Default("out.txt")),
strictcli.BoolFlag("verbose", "Verbose output"),
strictcli.IntFlag("port", "Port number"),
strictcli.FloatFlag("threshold", "Score threshold"),
```

Bool flags support `--flag` / `--no-flag` negation (disable with `NegatableOpt(false)`) and have no implicit default: without `Default(...)` they are required and must be passed explicitly as `--flag` or `--no-flag`. Float parsing rejects NaN and Inf.

### Compound types

`ListFlag` and `DictFlag` for collecting multiple values.

```go
strictcli.ListFlag(strictcli.TypeStr, "tags", "Tags to apply", strictcli.Unique(true)),
strictcli.DictFlag(strictcli.TypeStr, "env", "Environment variables", strictcli.Unique(false)),
```

List flags accept `--tags a --tags b`. Dict flags accept `--env KEY=VALUE` pairs or JSON objects. Both are always repeatable and therefore require an explicit `Unique(true)` or `Unique(false)`.

### Positional arguments

Required by default. Support optional (`ArgRequired(false)`), default values (`ArgDefault(v)`), and variadic (`Variadic()`).

```go
app.Command("copy", "Copy files",
    handler,
    strictcli.WithArgs(
        strictcli.NewArg("src", "Source path"),
        strictcli.NewArg("dst", "Destination path"),
    ),
)
```

### Short flag aliases

Single-character shortcuts for any flag.

```go
strictcli.BoolFlag("verbose", "Verbose output", strictcli.Short("v")),
strictcli.StringFlag("output", "Output path", strictcli.Short("o"), strictcli.Default(".")),
```

### Environment variable binding

Flags can be backed by environment variables. Prefix enforcement keeps your config namespace clean.

```go
app := strictcli.NewApp("myapp", "1.0.0", "My app", strictcli.WithEnvPrefix("MYAPP"))

strictcli.StringFlag("region", "Cloud region",
    strictcli.Env("MYAPP_REGION"), strictcli.Default("us-east-1")),
```

All env vars must start with the declared prefix. Use `Prefixed(false)` for external env vars. Precedence: CLI > env > config > default.

Bool env vars accept `1|true|yes` / `0|false|no` (case-insensitive).

### FlagSets

Reusable bundles of flags shared across commands.

```go
authFlags := strictcli.FlagSet{
    Name: "auth",
    Flags: []strictcli.Flag{
        strictcli.StringFlag("token", "Auth token", strictcli.Default("")),
        strictcli.BoolFlag("insecure", "Skip TLS verification"),
    },
}

app.Command("deploy", "Deploy", handler,
    strictcli.WithFlagSets(authFlags),
)
```

### Mutually exclusive flag groups

Exactly one flag from the group must be provided.

```go
app.Command("log", "Show logs", handler,
    strictcli.WithMutex(strictcli.MutexGroup{
        Flags: []strictcli.Flag{
            strictcli.BoolFlag("verbose", "Verbose output"),
            strictcli.BoolFlag("quiet", "Quiet output"),
        },
    }),
)
```

### Flag dependencies

Three relationship types, all passed via `WithDependencies(...)`:

- `CoRequired{Flags: []string{"output", "format"}}` -- all must appear together, or none
- `Requires{Flag: "verbose", DependsOn: "output"}` -- one-way dependency
- `Implies{Flag: "verbose", Implies: "log-output", Value: true}` -- auto-set a bool flag when another is provided; explicit contradictions are parse errors

```go
app.Command("export", "Export data", handler,
    strictcli.WithFlags(...),
    strictcli.WithDependencies(
        strictcli.CoRequired{Flags: []string{"output", "format"}},
        strictcli.Requires{Flag: "verbose", DependsOn: "output"},
        strictcli.Implies{Flag: "verbose", Implies: "log-output", Value: true},
    ),
)
```

### Global flags

App-level flags available to all commands, parsed before and after the command token.

```go
app.GlobalFlag(strictcli.BoolFlag("verbose", "Verbose output"))
```

### Passthrough commands

Bypass all parsing -- handler gets raw args plus global flag values.

```go
app.Passthrough("run", "Run a script",
    func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{}) int {
        // args contains everything after the command name
        return 0
    },
)
```

### Repeatable flags

Flags that accumulate values across multiple occurrences. Requires explicit `Unique(true)` or `Unique(false)`.

```go
strictcli.StringFlag("tag", "Add a tag", strictcli.Repeatable(), strictcli.Unique(true)),
```

### Choices

Restrict flag values to an allowed set.

```go
strictcli.StringFlag("format", "Output format", strictcli.Choices("json", "csv", "xml")),
```

### Custom validation

Per-flag validation functions.

```go
strictcli.IntFlag("port", "Port number",
    strictcli.ValidateFn(func(v interface{}) error {
        if n := v.(int); n < 1 || n > 65535 {
            return fmt.Errorf("port must be 1-65535, got %d", n)
        }
        return nil
    }),
),
```

### Deprecated commands

Register retired commands that print a message to stderr and exit 1.

```go
app.Deprecated("old-cmd", "Use 'new-cmd' instead")
group.Deprecated("legacy-lint", "Use 'lint' instead")
```

Deprecated commands appear in help output under a `Deprecated:` section.

### Hidden commands and groups

Commands and groups can be hidden from help output while remaining functional.

```go
app.Command("internal-debug", "Debug internals", handler,
    strictcli.WithHidden(),
)
```

### JSON config file support

Reads `~/.config/{name}/config.json` (or TOML). Auto-registers `config show/set/path/edit` subcommands.

```go
app := strictcli.NewApp("myapp", "1.0.0", "My app", strictcli.WithConfig())
```

Precedence: CLI > env > config > default. Config fields can be declared with typed validation:

```go
app.ConfigField("serve.port",
    strictcli.ConfigFieldType(strictcli.TypeInt),
    strictcli.ConfigFieldHelp("Server port"),
    strictcli.ConfigFieldDefault(8080),
)
```

### Schema dump

`--dump-schema` is auto-injected on every app. Writes `.strictcli/schema.json` describing the full CLI structure (commands, flags, args, groups, checks).

### Check system

First-class check/validation framework with double-entry security. Enabled via `WithChecks(path)` pointing to a TOML file.

```go
app := strictcli.NewApp("myapp", "1.0.0", "My app", strictcli.WithChecks("checks.toml"))

app.RegisterErrorCheck("lint", func(ctx strictcli.CheckContext, r *strictcli.ErrorReporter) strictcli.CheckOutcome {
    return r.Passed("All good")
})
```

Checks are declared in TOML and registered in code -- both must agree. Registration form matches the declared severity: `RegisterErrorCheck` for `severity = "error"` checks (reporter has `Error` and `Warn`), `RegisterWarnCheck` for `severity = "warn"` checks (reporter structurally lacks `Error`). A `CheckOutcome` is minted only via reporter methods: `Passed(message)`, `Skipped(reason)`, or `Found(message)` after accumulating problems with `r.Error(text)` / `r.Warn(text)`; `r.Note(text)` records verdict-inert informational notes. Auto-registers a `check` command with tag DSL filtering (`--tag "release & !slow"`), JSON output, and dependency resolution.

### Context

`Context` is constructed by the framework for every dispatch and passed as the first argument to every handler. It provides structured output methods -- `Info(msg)` (stdout), `Warn(msg)` (stderr), `Debug(msg)` (stdout), `Error(msg)` (stderr) -- plus provenance: `Source(name)` returns where a flag's value came from (`"cli"`, `"env"`, `"config"`, `"default"`, `"implied"`, or `"infra"`), and `InfraValue(envVar)` reads a declared infrastructure env var.

### Tool export

`app.AsTools()` exports non-hidden commands as `Tool` descriptors for LLM agents.

```go
tools := app.AsTools()
// Each Tool has: Name, Description, Parameters (JSON Schema), Execute
```

### MCP server

`app.ServeMCP()` runs a JSON-RPC 2.0 MCP server on stdin/stdout, exposing commands as tools for AI clients. Triggered via `--mcp` flag.

### Help and version

- `--help` / `-h` recognized anywhere in argv, at app, group, and command levels
- `--version` / `-v` prints app version
- Help is auto-generated with flag types, defaults, env var names, and choices

## Handlers

Every command handler has the ctx-first signature:

```go
func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome
```

`kwargs` holds the parsed flag and arg values, keyed by parameter name (hyphens converted to underscores: `--dry-run` becomes `dry_run`). `ctx` provides structured output and provenance (see Context above).

### Outcome

`Outcome` is an opaque, branded return type. It is constructed ONLY via two functions:

```go
return strictcli.Exit(0)                                          // exit code, no data
return strictcli.ExitData(0, map[string]interface{}{"ok": true})  // exit code + structured data
```

When data is present, the framework JSON-marshals it to stdout as one compact line and makes it available programmatically via `Test` (in `Result.Data`) and `Call`. Data emission is possible only through `ExitData` -- there is no other channel.

### Typed kwargs accessors

`Get[T]` and `GetOpt[T]` replace raw type assertions on `kwargs`:

```go
name := strictcli.Get[string](kwargs, "name")      // panics if absent, nil, or wrong type
port, ok := strictcli.GetOpt[int](kwargs, "port")  // (zero, false) when the value is nil (not provided)
```

`Get` treats a nil value as an error (nil means "not provided"); use `GetOpt` for optional flags without defaults.

### Passthrough handlers

Passthrough commands bypass parsing and use a distinct signature returning a plain exit code:

```go
func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{}) int
```

## Testing

`app.Test(argv)` runs the CLI in-process and returns a `Result`:

```go
result := app.Test([]string{"hello", "--name", "World", "--loud"})

if result.ExitCode != 0 {
    t.Fatalf("expected exit 0, got %d: %s", result.ExitCode, result.Stderr)
}
if !strings.Contains(result.Stdout, "HELLO, WORLD!") {
    t.Fatalf("unexpected output: %q", result.Stdout)
}
```

`Result` carries `Stdout`, `Stderr`, `ExitCode`, and `Data` (the structured value from an `ExitData` outcome, `nil` otherwise).

## API reference

### Constructors

```go
app  := strictcli.NewApp(name, version, help, opts ...AppOption)
flag := strictcli.StringFlag(name, help, opts ...FlagOption)
flag := strictcli.BoolFlag(name, help, opts ...FlagOption)
flag := strictcli.IntFlag(name, help, opts ...FlagOption)
flag := strictcli.FloatFlag(name, help, opts ...FlagOption)
flag := strictcli.ListFlag(itemType, name, help, opts ...FlagOption)
flag := strictcli.DictFlag(valueType, name, help, opts ...FlagOption)
arg  := strictcli.NewArg(name, help, opts ...ArgOption)
```

### Flag options

| Function | Description |
|----------|-------------|
| `Short(s)` | Single-character alias |
| `Default(v)` | Default value (omit for required) |
| `Env(varName)` | Environment variable name |
| `Prefixed(b)` | Control env prefix validation |
| `Choices(vals...)` | Restrict to allowed values |
| `Repeatable()` | Accept multiple occurrences |
| `Unique(b)` | Deduplicate repeatable values |
| `ValidateFn(fn)` | Custom validation function |
| `NegatableOpt(b)` | Control `--no-X` form for bool flags |

### Arg options

| Function | Description |
|----------|-------------|
| `ArgRequired(b)` | Whether the arg is required |
| `ArgDefault(v)` | Default value for optional args |
| `Variadic()` | Collect remaining positional values |

### Command options

| Function | Description |
|----------|-------------|
| `WithFlags(flags...)` | Add flags to a command |
| `WithArgs(args...)` | Add positional arguments |
| `WithFlagSets(flagSets...)` | Attach flag set bundles |
| `WithMutex(groups...)` | Add mutex groups |
| `WithDependencies(deps...)` | Add CoRequired/Requires/Implies constraints |
| `WithPassthrough(handler)` | Mark as passthrough command |
| `WithHidden()` | Hide from help output |

### App options

| Function | Description |
|----------|-------------|
| `WithEnvPrefix(prefix)` | Set env var prefix |
| `WithConfig()` | Enable config file support |
| `WithConfigPath(path)` | Override config file path |
| `WithConfigFormat(fmt)` | Set config format ("json" or "toml") |
| `WithChecks(path)` | Enable check system |
| `WithChecksEmbed(data)` | Enable check system with embedded TOML |

### App methods

| Method | Description |
|--------|-------------|
| `app.Command(name, help, handler, opts...)` | Register a command |
| `app.Passthrough(name, help, handler, opts...)` | Register a passthrough command |
| `app.Group(name, help)` | Create a command group |
| `app.GlobalFlag(flag)` | Register a global flag |
| `app.Deprecated(name, message)` | Register a deprecated command |
| `app.Run()` | Parse `os.Args` and execute |
| `app.Test(argv)` | Run in-process, return `Result` |
| `app.Call(commandPath, kwargs)` | Invoke a command programmatically; returns data (ExitData) or exit code |
| `app.AsTools()` | Export commands as `Tool` descriptors |
| `app.ServeMCP()` | Run MCP server on stdin/stdout |
| `app.ConfigField(name, opts...)` | Declare a typed config field |
| `app.RegisterErrorCheck(name, fn)` | Register an error-severity check handler |
| `app.RegisterWarnCheck(name, fn)` | Register a warn-severity check handler |
| `app.SetCheckContext(factory)` | Set the check context factory |

### Core types

| Type | Description |
|------|-------------|
| `App` | Root CLI application |
| `Command` | Leaf command with handler |
| `Group` | Container for nested commands |
| `Flag` | Flag declaration |
| `Arg` | Positional argument |
| `FlagSet` | Reusable flag bundle |
| `MutexGroup` | Mutually exclusive flags |
| `CoRequired` | Flags that must appear together |
| `Requires` | One flag depends on another |
| `Implies` | Auto-set a bool flag from another |
| `Result` | Return type of `app.Test()` (Stdout, Stderr, ExitCode, Data) |
| `Tool` | LLM tool descriptor |
| `Outcome` | Branded handler return type (via `Exit` / `ExitData` only) |
| `Context` | Structured output and provenance (Info/Warn/Debug/Error/Source/InfraValue) |
| `CheckOutcome` | Check result, minted only via reporter methods |
| `ErrorReporter` / `WarnReporter` | Problem accumulators passed to check handlers |
| `CheckContext` | Interface for check context |
| `ConfigField` | Typed config file field |

## Design principles

- **Help is mandatory.** Every command, flag, and argument must have help text. Missing help panics at registration time.
- **Four types only.** `str`, `bool`, `int`, `float` -- plus compound `list` and `dict`. No magic type coercion.
- **One handler contract.** `func(ctx *Context, kwargs map[string]interface{}) Outcome`, with kwargs keyed by parameter name (hyphens become underscores) and exit codes/data flowing only through `Exit` / `ExitData`.
- **Registration-time errors.** Misconfigurations panic loud and early, not at parse time.
- **Minimal dependencies.** One dependency ([go-toml-edit](https://github.com/smm-h/go-toml-edit)) for TOML support.

## See also

- [strictcli monorepo](https://github.com/smm-h/strictcli) -- conformance tests, Python implementation, and project documentation
- [Python implementation](https://github.com/smm-h/strictcli/tree/main/python) -- same semantics, decorator-based API

## License

MIT
