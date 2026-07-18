# strictcli

A strict CLI framework — declare everything, infer nothing.

strictcli has multiple first-class implementations kept in behavioral lockstep by a shared conformance test suite:

| Implementation | Install | Docs |
|---------------|---------|------|
| **Python** | `pip install strictcli` | [python/README.md](python/README.md) |
| **Go** | `go get github.com/smm-h/strictcli/go/strictcli` | [go/](go/) |

## Philosophy

Most CLI frameworks infer behavior from type hints, function signatures, or naming conventions. strictcli does the opposite: every flag, argument, command, and help string is declared explicitly. If something is missing, you get an error at registration time, not a confusing runtime surprise.

- **Four types only.** `str`, `bool`, `int`, `float` — no magic type coercion. NaN and Inf are rejected.
- **Mandatory help text.** Every flag, arg, command, and group must have help text.
- **Handler signature validation.** Parameter names must match declared flags and args exactly.
- **Registration-time errors.** Misconfigurations fail loud and early, not at parse time.
- **One dependency per implementation.** Each implementation uses its language's standard library plus a single TOML library: Python depends on [tomlkit](https://pypi.org/project/tomlkit/), Go depends on [go-toml-edit](https://github.com/smm-h/go-toml-edit).

## Quick taste

### Python

```python
import strictcli

app = strictcli.App("greet", version="1.0.0", help="A greeting app")

@app.command("hello", help="Say hello")
@strictcli.flag("name", type=str, help="Who to greet")
@strictcli.flag("loud", type=bool, default=False, help="Shout it")
def hello(ctx, name, loud):
    msg = f"Hello, {name}!"
    print(msg.upper() if loud else msg)

app.run()
```

### Go

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
        func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
            name := args["name"].(string)
            loud := args["loud"].(bool)
            msg := "Hello, " + name + "!"
            if loud {
                msg = strings.ToUpper(msg)
            }
            fmt.Println(msg)
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

## Features

- Commands and command groups (recursive nesting to arbitrary depth)
- Deprecated commands — register retired commands that print a message and exit 1, shown in help under a `Deprecated:` section
- Flags: string, boolean (with `--no-` negation), integer, float (NaN/Inf rejected)
- Short flag aliases (`-v` for `--verbose`)
- Positional arguments (required, optional with defaults, variadic)
- Environment variable binding with prefix enforcement
- Flag tags — reusable bundles of flags shared across commands
- Mutually exclusive flag groups (exactly one required)
- Implies dependencies — auto-set a bool flag when another flag is provided; explicit contradictions are parse errors
- Global flags (parsed before and after the command token)
- Passthrough commands — delegate unparsed args to another tool
- Repeatable flags (accumulate values into a list)
- Choices — restrict flag values to an allowed set
- Custom validation functions per flag
- Auto-generated help at every level (app, group, command)
- Built-in `--version` / `-v` support
- Auto-version detection from package metadata (Python only)
- Config file support (JSON or TOML) — reads `~/.config/{name}/config.json` (or `.toml`), auto-registers `config show/set/path/edit/init` subcommands. Precedence: CLI > env > config > default.
- `--hermetic` — reserved global flag that skips config loading and env var resolution entirely, so values come only from the CLI and declared defaults
- Infrastructure env vars — declared location roots (resolved at construction, usable in defaults via `RelativeToRoot`) and handshake vars (cross-tool protocol signals, read live)
- Value provenance — every resolved flag reports its source (`cli`/`env`/`config`/`default`/`implied`/`infra`) via the handler context
- Programmatic invocation — `app.call()` / `app.Call()` runs a command in-process with typed kwargs, bypassing CLI parsing; failures surface as `InvokeError`
- Check system — first-class check/validation framework with a TOML manifest, tag DSL, and DAG-ordered execution
- MCP server mode — expose commands as tools over the Model Context Protocol
- `--dump-schema` — auto-injected flag that writes `.strictcli/schema.json` describing the full CLI structure
- `--help` / `-h` recognized anywhere in argv
- In-process testing via `app.test()` / `app.Test()`

## Conformance

The `conformance/` directory contains a cross-language test suite that verifies all implementations produce identical output for identical inputs. It includes:

- 57 JSON test case files covering every feature
- API surface verification (`check_api_surface.py`)
- Error message parity checks (`check_error_parity.py`)
- Pairwise combination testing and fuzzing

All implementations must pass all conformance tests before release.

## Project structure

```
strictcli/
  python/          Python implementation (PyPI)
  go/              Go implementation
  conformance/     Cross-language conformance tests
```

Each sub-project has its own version, changelog, and release cycle, managed by [rlsbl](https://github.com/smm-h/rlsbl).

## License

MIT
