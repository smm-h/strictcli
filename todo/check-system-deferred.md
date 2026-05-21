# Check system: deferred features

Features intentionally deferred from the initial check system implementation (v0.8.0). To be added when real usage (especially rlsbl migration) reveals the right patterns.

## --fix mechanism

The `fix_capable` field was dropped from the TOML schema. When added back, it needs:

- A `fix_capable = true/false` field in `.strictcli/checks.toml`
- A mechanism for check functions to provide fix callbacks
- The `--fix` flag on the check command (already reserved in the design but not implemented)
- Re-run logic: after applying fixes, re-run the fixed checks to verify

Design options discussed but not decided:
- Check function receives a `fix: bool` parameter and branches internally
- Check function returns a fix callback on CheckResult
- Separate `@app.check_fix("name")` registration alongside `@app.check("name")`

The rlsbl migration will be the primary driver -- rlsbl's `doctor --fix` already has fix logic for removing stale locks, pushing tags, and creating GitHub Releases.

## Parallel check execution

Checks currently run sequentially in topological order. Checks at the same topological level with no shared state could run concurrently.

Considerations:
- In-process checks share the process; thread safety must be guaranteed
- The `pure` metadata field was designed to enable this (pure checks have no side effects)
- Neither Python nor Go strictcli has any concurrent execution code today
- Benefit is proportional to the number of slow checks -- rlsbl has ~3 network checks that could parallelize

## Per-check timeouts

Checks that shell out to external commands (via subprocess inside the check function) can hang. A `timeout` field in the TOML schema would allow the runner to kill hung checks.

Considerations:
- What happens on timeout: fail with a clear message, or skip?
- Default timeout: none? 30s? Configurable globally?
- Python: `signal.alarm` or threading timer. Go: `context.WithTimeout`

## Caching / skip logic

rlsbl's changelog validate caches results in `.rlsbl/changes/.validated` (stores HEAD SHA) and skips re-validation when HEAD hasn't moved. A similar mechanism in strictcli's check runner could skip checks that passed recently.

Considerations:
- Cache key: what constitutes "nothing changed"? Git HEAD? File mtimes? Content hashes?
- Cache location: `.strictcli/checks.cache`?
- Opt-in per check via a `cacheable` TOML field?
- The `pure` field is relevant: only pure checks can be safely cached

## Affected files

- `python/strictcli/__init__.py` -- runner, TOML schema, check command
- `go/strictcli/check.go` -- TOML schema
- `go/strictcli/check_runner.go` -- runner
- `go/strictcli/check_cmd.go` -- check command
- `conformance/schema.json` -- test case schema
- `conformance/cases/checks.json` -- test cases
