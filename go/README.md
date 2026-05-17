# strictcli

A strict, zero-dependency CLI framework for Go.

strictcli makes you declare everything -- every command, flag, argument, and environment variable must have help text or the framework panics at registration time. Types are `str`, `bool`, and `int` only; there is no magic type inference.

## Installation

```
go get github.com/smm-h/strictcli/go/strictcli
```

Requires Go 1.23+. Zero external dependencies (stdlib only).

## Quickstart

```go
package main

import (
    "fmt"

    "github.com/smm-h/strictcli/go/strictcli"
)

func main() {
    app := strictcli.NewApp("greet", "0.1.0", "a friendly greeter")

    app.Command("hello", "say hello", func(kwargs map[string]interface{}) int {
        name := kwargs["name"].(string)
        loud := kwargs["loud"].(bool)
        msg := fmt.Sprintf("Hello, %s!", name)
        if loud {
            msg = fmt.Sprintf("HELLO, %s!", name)
        }
        fmt.Println(msg)
        return 0
    },
        strictcli.WithArgs(strictcli.NewArg("name", "who to greet")),
        strictcli.WithFlags(
            strictcli.BoolFlag("loud", "shout the greeting", strictcli.Short("l")),
        ),
    )

    app.Run()
}
```

```
$ greet hello World
Hello, World!

$ greet hello --loud World
HELLO, WORLD!

$ greet hello --help
greet hello -- say hello

Arguments:
  name    who to greet

Flags:
  --loud, --no-loud, -l    shout the greeting [default: false]
```

## Features

- **Commands and groups** -- top-level commands and one level of nested groups
- **Three flag types** -- `StringFlag`, `BoolFlag`, `IntFlag`
- **Short aliases** -- single-character short forms (`-v`, `-o`)
- **Positional arguments** -- required, optional, and variadic
- **Environment variables** -- first-class env var backing with prefix enforcement
- **Tags** -- reusable bundles of flags shared across commands
- **Mutex groups** -- mutually exclusive flags (exactly one required)
- **CoRequired** -- flags that must appear together or not at all
- **Requires** -- flag A depends on flag B being present
- **Global flags** -- app-level flags available to all commands
- **Passthrough commands** -- bypass parsing, forward raw args to handler
- **Repeatable flags** -- flags that accept multiple occurrences (collected into a slice)
- **Choices** -- restrict flag values to an allowed set
- **Custom validation** -- per-flag validation functions
- **Auto-generated help** -- `--help` / `-h` at app, group, and command levels
- **Version flag** -- `--version` / `-v` prints app version
- **In-process testing** -- `app.Test(argv)` captures stdout, stderr, and exit code

## API Overview

### Core Types

| Type | Description |
|------|-------------|
| `App` | Root CLI application |
| `Command` | Leaf command with handler |
| `Group` | Container for nested commands |
| `Flag` | Flag declaration (use constructors below) |
| `Arg` | Positional argument |
| `Tag` | Reusable bundle of flags |
| `MutexGroup` | Mutually exclusive flag group |
| `CoRequired` | Flags that must appear together |
| `Requires` | One flag depends on another |
| `Result` | Return type of `App.Test()` |

### Constructors

```go
app := strictcli.NewApp(name, version, help string, opts ...AppOption)
flag := strictcli.StringFlag(name, help string, opts ...FlagOption)
flag := strictcli.BoolFlag(name, help string, opts ...FlagOption)
flag := strictcli.IntFlag(name, help string, opts ...FlagOption)
arg  := strictcli.NewArg(name, help string, opts ...ArgOption)
```

### Flag Options

| Function | Description |
|----------|-------------|
| `Short(s)` | Single-character alias |
| `Default(v)` | Default value (omit for required) |
| `Env(varName)` | Environment variable name |
| `Prefixed(b)` | Control env prefix validation |
| `Choices(vals...)` | Restrict to allowed values |
| `Repeatable()` | Accept multiple occurrences |
| `ValidateFn(fn)` | Custom validation function |
| `NegatableOpt(b)` | Control `--no-X` form for bool flags |

### Arg Options

| Function | Description |
|----------|-------------|
| `ArgRequired(b)` | Whether the arg is required |
| `ArgDefault(v)` | Default value for optional args |
| `Variadic()` | Collect remaining positional values |

### Command Options

| Function | Description |
|----------|-------------|
| `WithFlags(flags...)` | Add flags to a command |
| `WithArgs(args...)` | Add positional arguments |
| `WithTags(tags...)` | Attach tag bundles |
| `WithMutex(groups...)` | Add mutex groups |
| `WithDependencies(deps...)` | Add CoRequired/Requires constraints |
| `WithPassthrough(handler)` | Mark as passthrough command |

### App Methods

```go
app.Command(name, help, handler, opts...)   // Register a command
app.Passthrough(name, help, handler, opts...)  // Register passthrough command
app.Group(name, help) *Group                // Create a command group
app.GlobalFlag(flag)                        // Register a global flag
app.Run()                                   // Parse os.Args and execute
app.Test(argv []string) Result              // Run in-process, capture output
```

### App Options

| Function | Description |
|----------|-------------|
| `WithEnvPrefix(prefix)` | Set env var prefix for the app |

## Testing

`app.Test(argv)` runs the CLI in-process and returns a `Result`:

```go
result := app.Test([]string{"hello", "--loud", "World"})

if result.ExitCode != 0 {
    t.Fatalf("expected exit 0, got %d: %s", result.ExitCode, result.Stderr)
}
if result.Stdout != "HELLO, WORLD!\n" {
    t.Fatalf("unexpected output: %q", result.Stdout)
}
```

## See Also

- [strictcli root](https://github.com/smm-h/strictcli) -- monorepo with conformance tests and documentation
- [Python implementation](https://github.com/smm-h/strictcli/tree/main/python) -- PyPI package with the same semantics
