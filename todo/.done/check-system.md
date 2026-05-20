# Check system: first-class composable checks

## Context

Multiple CLI tools built on strictcli need structured, composable health/validation checks. Today each tool reinvents this: rlsbl has `doctor` (decorator-based registry with 11 checks), `monorepo lint` (2 ad-hoc checks), and `changelog validate` (5 checks) -- all with different patterns, metadata, and output formats. Other tools have similar needs.

The check system should be a strictcli-level feature that any strictcli-based CLI can use, providing a standard way to define, compose, filter, and run checks.

## What we need

### Check registration

Decorator-based registration on plain functions:

```python
@check(
    name="deps.stale",
    fast=True,
    needs_network=False,
    pure=True,
    scope="workspace",
    tags=["deps"],
    fix_capable=True,
    severity="error",
    depends_on=["deps.graph"],
)
def check_stale_deps(ctx: CheckContext) -> CheckResult:
    ...
```

### Check metadata (full taxonomy)

Each check declares:

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Dot-separated hierarchical name (e.g., `deps.stale`, `deps.unused`, `changelog.coverage`) |
| `fast` | bool | Completes in under ~1s with no I/O. Enables `--quick` filter |
| `needs_network` | bool | Requires network access. Enables `--offline` filter |
| `pure` | bool | Guaranteed no side effects (no file writes, no git operations, no network mutations) |
| `scope` | str | What level it operates at: `project`, `workspace`, `global` |
| `tags` | list[str] | Arbitrary tags for grouping (e.g., `deps`, `changelog`, `structure`) |
| `fix_capable` | bool | Supports `--fix` auto-remediation |
| `severity` | str | Default severity: `error` or `warn`. All checks exit nonzero on failure regardless -- severity is metadata for consumers |
| `depends_on` | list[str] | Other check names that must run first. Runner auto-resolves order. If a dependency fails, dependents are skipped |

### Check composition

Explicit composition rules in a config file (not naming-convention aliases):

```toml
[check.groups]
quick = ["structure.*", "changelog.schema"]
full = ["*"]
deps = ["deps.stale", "deps.unused", "deps.undeclared"]
pre-push = ["changelog.coverage", "structure.*"]
```

When the user runs `check deps`, strictcli looks up the `deps` group in config and runs all listed checks. Glob patterns (`deps.*`) expand against all registered check names.

If no group matches, strictcli tries exact check name match (`check deps.stale`). If that also fails, error with suggestions.

Built-in flags provided by strictcli for free:
- `--all`: run every registered check
- `--quick`: run only checks where `fast=True` and `pure=True`
- `--offline`: exclude checks where `needs_network=True`
- `--fix`: for `fix_capable` checks, auto-apply fixes instead of just reporting
- `--json`: output results as JSON array
- `--name <pattern>`: run checks matching a glob pattern

### Check output

Checks return a structured `CheckResult`:

```python
@dataclass
class CheckResult:
    status: str              # "pass", "fail", "skip"
    message: str             # one-line summary
    details: list[str]       # specific findings (one per issue found)
    fix: Callable | None     # optional fix callback, called when --fix is passed
```

Output modes (configurable):
- **Human** (default): aligned table like current doctor output, with details expanded below each failing check
- **JSON**: array of `{name, status, message, details}` objects
- **Quiet**: only failing check names, one per line (for scripting)

### Check runner behavior

- Resolves `depends_on` into a DAG, runs in topological order
- Checks with no dependencies can run in parallel (opt-in via `parallel=True` metadata?)
- If a dependency check fails, all dependents are skipped with status `"skip"` and message explaining which dependency failed
- All checks are errors: nonzero exit on any failure
- `--fix` runs fixes for all `fix_capable` checks that failed, then re-runs those checks to verify the fix worked

### What strictcli provides vs what the CLI tool provides

**strictcli provides:**
- The `@check` decorator and `CheckResult` dataclass
- The check runner (resolution, ordering, filtering, output formatting)
- The `check` subcommand with all built-in flags
- Group expansion from config

**The CLI tool provides:**
- Actual check functions decorated with `@check`
- Group definitions in its config
- A `CheckContext` object with tool-specific state (project root, workspace graph, config, etc.)

## Open questions

- Should check groups support exclusion patterns? e.g., `full = ["*", "!slow.*"]`
- Should `depends_on` support group names or only individual check names?
- How does `CheckContext` get populated? Does strictcli provide a hook for the CLI tool to build it before checks run?
- Should there be a `check list` subcommand that shows all registered checks with their metadata?
- Should parallel execution be a metadata flag (`parallel=True`) or inferred from `pure=True`?
- How do checks interact with the existing strictcli permission/validation model?

## Migration path for rlsbl

rlsbl currently has:
- `doctor.py`: 11 checks in `CHECK_REGISTRY` (decorator-based, returns `(status, message)` tuples) + 3 ad-hoc monorepo checks
- `monorepo lint`: 2 structural checks (unregistered/stale projects)
- `changelog validate`: 5 validation checks

All of these would migrate to `@check`-decorated functions. The `doctor` command becomes `rlsbl check --all` (or a group alias). `monorepo lint` checks merge in with `scope="workspace"`. Changelog checks get `tags=["changelog"]`.
