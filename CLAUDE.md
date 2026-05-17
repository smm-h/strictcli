# strictcli

Strict CLI framework — declare everything, infer nothing. Two first-class implementations (Python and Go) kept in sync via a conformance test suite.

## Monorepo structure

This is an rlsbl monorepo (`.rlsbl-monorepo/workspace.toml`). Each sub-project has its own version, changelog, and release cycle.

| Directory | What | Version file | Targets | Tests |
|-----------|------|-------------|---------|-------|
| `python/` | Python implementation (PyPI + npm) | `pyproject.toml` | pypi, npm | `uv run pytest` in `python/` |
| `go/` | Go implementation | `VERSION` | go | `go test ./... -race` in `go/` |
| `conformance/` | Cross-language conformance suite | n/a | plain | `python conformance/run.py --target python` / `--target go` |

## Building and testing

```bash
# Python
cd python && uv sync && uv run pytest

# Go
cd go && go test ./strictcli/... -race

# Conformance (requires both implementations)
cd conformance && python run.py --target python && python run.py --target go
```

## Architecture

### Python (`python/strictcli/__init__.py`)

Single-file, zero-dependency implementation (~1350 lines). Key internal stages:

1. **Registration** — `@flag`/`@arg` decorators attach metadata to handlers; `@app.command()` triggers `_build_and_validate_command()` which merges tags, validates signatures, checks constraints.
2. **Global flag parsing** — `_parse_global_flags()` extracts app-level flags before and after the command token.
3. **Command routing** — first non-flag token selects the command or group.
4. **Command parsing** — `_parse_command()` resolves flags, args, env vars, defaults, mutex, choices, and custom validation.
5. **Execution** — handler called with kwargs; return value becomes exit code.

### Go (`go/strictcli/`)

Split across three files, zero dependencies (stdlib only):

- `strictcli.go` — types, constructors (functional options pattern), registration, orchestration.
- `parse.go` — two-phase flag/arg parsing, env resolution, validation.
- `help.go` — help text formatting at app/group/command levels.

Handlers receive `map[string]interface{}` (flag names with hyphens converted to underscores as keys).

### Conformance (`conformance/`)

JSON test cases in `cases/` define app structure + argv + expected output. `run.py` generates reference code (via `ref_python.py` / `ref_go.py`), executes it, and compares results. Go binaries are cached by app-definition hash.

## Cross-language parity rules

Both implementations must:

- Support exactly three types: `str`, `bool`, `int`.
- Use strict integer parsing (no leading/trailing whitespace, 64-bit signed bounds, no leading zeros in Go).
- Accept the same boolean env var strings: `1|true|yes` / `0|false|no` (case-insensitive).
- Produce identical error messages for identical inputs (checked by `check_error_parity.py`).
- Export the same API surface (checked by `check_api_surface.py`).
- Produce identical error messages for dependency violations (checked by `check_error_parity.py`).
- Pass all conformance cases for both targets before release.

When adding a feature to one implementation, add it to both and add conformance cases.

## Key conventions

- Flags with dashes (`--dry-run`) become underscore parameters (`dry_run`) in handlers.
- `app.test(argv)` / `app.Test(argv)` runs the CLI in-process for unit tests — never shell out.
- Help text is mandatory on every Flag, Arg, Command, Group, and App. Missing help is a registration-time error.
- Only two levels of nesting: App > Group > Command or App > Command. No deeper.
- Passthrough commands bypass all parsing — handler gets raw args plus global flag values.
- `CoRequired(flags=[...])` declares flags that must appear together. `Requires(flag=..., depends_on=...)` declares one-way dependency. Both passed via `dependencies=[...]`.
- Validation errors at registration time use panics (Go) / ValueError (Python). Parse-time errors print to stderr and exit 1.

## Release workflow

Each sub-project releases independently via `rlsbl release` from its own directory. See sub-project CLAUDE.md files and the parent `~/Projects/CLAUDE.md` for rlsbl details.

## Useful commands

```bash
# Check rlsbl status across sub-projects
cd python && rlsbl status
cd go && rlsbl status
cd conformance && rlsbl status

# API surface check
cd conformance && python check_api_surface.py

# Error message parity check
cd conformance && python check_error_parity.py
```
