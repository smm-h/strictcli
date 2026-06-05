# strictcli

Strict CLI framework — declare everything, infer nothing. Two first-class implementations (Python and Go) kept in sync via a conformance test suite.

## Monorepo structure

This is an rlsbl monorepo (`.rlsbl-monorepo/workspace.toml`). Each sub-project has its own version, changelog, and release cycle.

| Directory | What | Version file | Targets | Tests |
|-----------|------|-------------|---------|-------|
| `python/` | Python implementation (PyPI + npm) | `pyproject.toml` | pypi, npm | `uv run pytest` in `python/` |
| `go/` | Go implementation | `VERSION` | go | `go test ./... -race` in `go/` |
| `conformance/` | Cross-language conformance suite | n/a | plain | `python conformance/run.py --target python` / `--target go` |

**Note:** `conformance/` is a `dev_node` project. It has no changelog, no user-facing changes, and does not participate in the changelog system. It is not released independently -- releases happen only as part of monorepo batch releases (`rlsbl monorepo release`) if at all.

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

Single-file, zero-dependency implementation (~2040 lines). Key internal stages:

1. **Registration** — `@flag`/`@arg` decorators attach metadata to handlers; `@app.command()` triggers `_build_and_validate_command()` which merges tags, validates signatures, checks constraints.
2. **Global flag parsing** — `_parse_global_flags()` extracts app-level flags before and after the command token.
3. **Command routing** — first non-flag token selects the command or group.
4. **Command parsing** — `_parse_command()` resolves flags, args, env vars, defaults, mutex, choices, and custom validation.
5. **Execution** — handler called with kwargs; return value becomes exit code.

### Go (`go/strictcli/`)

Split across five files (~2680 non-test lines), zero dependencies (stdlib only):

- `strictcli.go` — types, constructors (functional options pattern), registration, orchestration.
- `parse.go` — two-phase flag/arg parsing, env resolution, validation.
- `help.go` — help text formatting at app/group/command levels.
- `config.go` — JSON config file loading, `config show/set/path/edit` subcommands.
- `schema.go` — `--dump-schema` implementation, writes `.strictcli/schema.json`.

Handlers receive `map[string]interface{}` (flag names with hyphens converted to underscores as keys).

### Conformance (`conformance/`)

JSON test cases in `cases/` define app structure + argv + expected output. `run.py` generates reference code (via `ref_python.py` / `ref_go.py`), executes it, and compares results. Go binaries are cached by app-definition hash.

## Cross-language parity rules

Both implementations must:

- Support exactly four types: `str`, `bool`, `int`, `float`.
- Use strict integer parsing (no leading/trailing whitespace, 64-bit signed bounds, no leading zeros in Go). Float parsing rejects NaN and Inf.
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
- Recursive group nesting: `group.group(name, help=...)` (Python) / `group.Group(name, help)` (Go). Arbitrary depth: App > Group > Group > ... > Command.
- Passthrough commands bypass all parsing — handler gets raw args plus global flag values.
- `CoRequired(flags=[...])` declares flags that must appear together. `Requires(flag=..., depends_on=...)` declares one-way dependency. `Implies(flag=..., implies=..., value=...)` auto-sets a bool flag when a trigger is provided. All passed via `dependencies=[...]`.
- `app.deprecate(name, message=...)` / `group.deprecate(name, message=...)` registers a retired command that prints the message to stderr and exits 1. Shown in help under a `Deprecated:` section.
- Validation errors at registration time use panics (Go) / ValueError (Python). Parse-time errors print to stderr and exit 1.
- `type=float` / `FloatFlag(...)` — float type support. NaN and Inf are rejected at parse time.
- JSON config file support — `App(config=True)` (Python) / `WithConfig()` (Go). Reads `~/.config/{name}/config.json`. Precedence: CLI > env > config > default. Auto-registers `config show/set/path/edit` subcommands.
- `--dump-schema` — auto-injected flag on every app. Writes `.strictcli/schema.json` describing the full CLI structure (commands, flags, args, groups).
- Auto-version (Python only) — `App(name="x", help="...")` without an explicit `version` auto-detects from `importlib.metadata`.
- `--help` / `-h` is recognized anywhere in argv, not just at token boundaries.
- `Default(nil)` fix (Go only) — flags with `Default(nil)` display `[optional]` in help instead of `[default: <nil>]`.
- Check system — first-class check/validation framework with double-entry security. See below.

### Check system

Enabled via `WithChecks(path)` (Go) / `checks_path=` (Python), pointing to a TOML file (source of truth, committed to repo). Checks are registered in code via `@app.check("name")` (Python) / `app.RegisterCheck("name", fn)` (Go). Both must agree — declared but unregistered or registered but undeclared are errors (double-entry security). The TOML file requires a top-level `app` field that must match the app name.

**TOML schema**: Required top-level `app` field (must match app name). `[checks.<name>]` sections with required fields: `tags` (list of strings), `severity` ("error"/"warn"), `fast` (bool), `pure` (bool), `needs_network` (bool), `depends_on` (list of check names). Check names: `[a-z][a-z0-9-]*`. Every field must be explicit — no defaults section. The `[checks]` section is optional — an `app` field with no checks is a valid TOML file.

**Check command**: auto-registered when checks are enabled via `WithChecks(path)` (Go) or `checks_path=` (Python). 8 flags: `--all`, `--tag <dsl>`, `--name <glob>`, `--list`, `--json`, `--ignore-warnings`, `--verbose`, `--dry-run`. No flags = show help. Hidden from help when no TOML exists.

**Tag DSL**: `--tag` accepts a set-operation expression. Operators by precedence (tightest first): `!` (NOT), `&` (AND), `^` (XOR), `|` (OR), `-` (DIFF). Parentheses for grouping. Example: `--tag "(release | changelog) & !slow"`.

**CheckResult**: `status` (pass/fail/warn/skip), `message` (str), `details` (list of str). Warn causes nonzero exit unless `--ignore-warnings`.

**CheckContext**: protocol/interface with single required field `ProjectRoot() string` / `project_root: Path`. Tool sets a factory via `app.set_check_context(factory)` / `app.SetCheckContext(factory)`.

**depends_on**: DAG resolution with cycle detection. Dependency failure skips dependents. Filtered-out dependencies are pulled back in when a selected check depends on them.

**Schema integration**: `--dump-schema` includes a `checks` top-level key when checks are enabled.

**Hooks**: strictcli does NOT manage `.git/hooks/`. External tools call `myapp check --tag pre-push` from their own hook scripts.

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
