# strictcli

A strict CLI framework — declare everything, infer nothing.

strictcli has two first-class implementations kept in behavioral lockstep by a shared conformance test suite:

| Implementation | Install | Docs |
|---------------|---------|------|
| **Python** | `pip install strictcli` | [python/README.md](python/README.md) |
| **Go** | `go get github.com/smm-h/strictcli/go/strictcli` | [go/](go/) |

## Philosophy

Most CLI frameworks infer behavior from type hints, function signatures, or naming conventions. strictcli does the opposite: every flag, argument, command, and help string is declared explicitly. If something is missing, you get an error at registration time, not a confusing runtime surprise.

- **Three types only.** `str`, `bool`, `int` — no magic type coercion.
- **Mandatory help text.** Every flag, arg, command, and group must have help text.
- **Handler signature validation.** Parameter names must match declared flags and args exactly.
- **Registration-time errors.** Misconfigurations fail loud and early, not at parse time.
- **Zero dependencies.** Both implementations use only their language's standard library.

## Quick taste

### Python

```python
import strictcli

app = strictcli.App("greet", version="1.0.0", help="A greeting app")

@app.command("hello", help="Say hello")
@strictcli.flag("name", type=str, help="Who to greet")
@strictcli.flag("loud", type=bool, help="Shout it")
def hello(name, loud):
    msg = f"Hello, {name}!"
    print(msg.upper() if loud else msg)

app.run()
```

### Go

```go
package main

import "github.com/smm-h/strictcli/go/strictcli"

func main() {
    app := strictcli.NewApp("greet", "1.0.0", "A greeting app")

    app.Command("hello", "Say hello",
        func(args map[string]interface{}) int {
            name := args["name"].(string)
            loud := args["loud"].(bool)
            msg := "Hello, " + name + "!"
            if loud {
                msg = strings.ToUpper(msg)
            }
            fmt.Println(msg)
            return 0
        },
        strictcli.WithFlags(
            strictcli.StringFlag("name", "Who to greet"),
            strictcli.BoolFlag("loud", "Shout it"),
        ),
    )

    app.Run()
}
```

## Features

- Commands and command groups (two-level nesting)
- Deprecated commands — register retired commands that print a message and exit 1, shown in help under a `Deprecated:` section
- Flags: string, boolean (with `--no-` negation), integer
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
- In-process testing via `app.test()` / `app.Test()`

## Conformance

The `conformance/` directory contains a cross-language test suite that verifies both implementations produce identical output for identical inputs. It includes:

- 21 JSON test case files covering every feature
- API surface verification (`check_api_surface.py`)
- Error message parity checks (`check_error_parity.py`)
- Pairwise combination testing and fuzzing

Both implementations must pass all conformance tests before release.

## Project structure

```
strictcli/
  python/          Python implementation (PyPI + npm)
  go/              Go implementation
  conformance/     Cross-language conformance tests
```

Each sub-project has its own version, changelog, and release cycle, managed by [rlsbl](https://github.com/smm-h/rlsbl).

## License

MIT
