# Python–Go reconciliation: divergences, unpinned behavior, and contract redesign

## Context

A deep audit (2026-07) of both implementations found: (a) latent Python↔Go behavioral divergences in places no conformance case pins; (b) internal inconsistencies *within* each implementation (multiple float formatters that disagree with each other); (c) a shared output-corruption bug; (d) a design-level root cause (the handler result contract) behind Go's API sprawl; (e) stale and false documentation. A full design review resolved every open question; this todo records those decisions as the reconciliation spec.

All behavioral changes must land red-green: pinning conformance cases first (verified failing or absent), then the fix, then green. Breaking changes are acceptable (0.x, minor bumps) and need changelog entries per the usual discipline.

## 1. Float formatting: adopt the SCF canon

**Ground truth (runtime-verified).** Python has three float→string paths that disagree with each other: `_format_value_for_error` (`python/strictcli/__init__.py:942-954`, appends `.0` when no `.` present), help defaults (`:6252/:6261/:6291`, plain `str()`), and `_toml_format_scalar` (`:378`). Go has four: `formatValueForError` (`parse.go:1160`, `'f'` format + `.0` append — expands `1.5e300` to a 301-digit string), `formatFloat` (`config.go:1342`) and `formatTomlValue` (`config.go:1330`) (both `%v` + `.0` append), and help defaults (`help.go:225/:395`, bare `%v`). The `.0`-append-after-exponent bug produces `"1e+20.0"` in Python's error path and Go's config/TOML paths; because Go's `%v` switches to scientific at exponent ≥ 6, Go's config/TOML output is corrupt from `1e6` upward (`1000000.0` → `"1e+06.0"`). Additionally the two languages disagree natively on trailing `.0`, exponent thresholds, exponent padding, and `-0.0`. No conformance case pins any float output value.

**Decided canon (SCF — strictcli canonical float), for all display contexts** (handler echo, `config show`, help defaults, error echoes):

1. Shortest decimal string that round-trips to the same IEEE-754 double (both languages already have shortest-digits primitives; wrap them, never trust their notation switching).
2. Integer-valued floats in fixed notation always carry trailing `.0` (`1.0`, `100.0`, `9007199254740992.0`). Floats are always visually distinct from ints.
3. `-0.0` is preserved as `-0.0` (lossless; distinct bit pattern).
4. Fixed notation for |x| in [1e-6, 1e21); scientific outside. (Deliberately chosen band — the only one backed by a written normative spec; neither language's native thresholds are inherited.)
5. Scientific spelling: lowercase `e`, explicit sign, no zero-padding — `1e+21`, `1e-7`, `1.5e+300`.
6. The `.0` rule exists only in the fixed-notation branch, never the scientific branch — the `1e+20.0` bug becomes unreachable by construction.

Reference battery: `1.0`→`1.0` · `-1.0`→`-1.0` · `0.5`→`0.5` · `-0.0`→`-0.0` · `100.0`→`100.0` · `1e15`→`1000000000000000.0` · `1e16`→`10000000000000000.0` · `1e20`→`100000000000000000000.0` · `1e21`→`1e+21` · `1e-4`→`0.0001` · `1e-5`→`0.00001` · `1e-7`→`1e-7` · `0.1`→`0.1` · `2^53`→`9007199254740992.0` · `1.5e300`→`1.5e+300`.

**Machine channel (explicit, not silent).** JSON contexts (`--dump-schema` defaults, JSON results) emit JSON number grammar, plus a lossless companion field for defaults where bit-exactness matters (e.g. `"default": 0.1, "default_bits": "0x3fb999999999999a"`). Display channel and machine channel are both declared contracts; the same value never silently renders differently within a channel.

**Enforcement stack.**
- One `formatFloatCanonical` function per language; every existing call site (all 3 Python + 4 Go paths) routes through it.
- Python is the reference formatter: a committed generator emits `conformance/float_vectors.json` (inputs stored as hex-float/uint64 bit patterns for exactness) over the curated battery plus a large adversarial set (threshold-straddlers, subnormals, `2^53±1`, `nextafter` neighbors, `-0.0`, full exponent range).
- Round-trip property test in each implementation: for random doubles, `parse(format(x))` is bit-identical to `x`.
- Differential fuzz in CI: random doubles formatted by both implementations, byte-equality + round-trip asserted, failures print the offending uint64. Shared seed for reproducibility.
- New `conformance/cases/float_format.json`: for each battery value — handler echo, `config show`, help-default snapshot, and a choices-error `stderr_equals`. `check_error_parity.py` gains float rows.

## 2. Handler result contract and registration model

**Root cause found.** Go grew three registration styles (`Command`, `DataCommand`, `RegisterHandler`) because its result contract could not express "nonzero exit WITH data". Fix the contract once and one registration style suffices.

**Decided result contract (strict), both languages:**
- A handler may return only: an int (exit code), nothing (exit 0), or a branded structured outcome built by an explicit factory (`outcome(exit=..., data=...)` / equivalent) carrying optional exit code and optional data.
- The implicit "return any other value and it gets JSON-printed" contract is **deleted**. Data emission is always a declared act. No shape-detection of look-alike objects — the brand disambiguates by construction.
- `ctx.emit` / `Context.Emit` is **deleted** in both languages. It is a once-per-invocation final-data channel (verified — not streaming), i.e. a pure duplicate of the outcome's data field. One way to return data.

**Decided registration model (one command carrier, both languages):**
- One conceptual command carrier: ordered positional-args list (order is meaningful data — declare it) + keyed flags collection, discriminated command kinds (normal / passthrough / deprecated).
- Go: collapse the trio. Delete `DataCommand`, `DataHandler`, `HandlerResult`, `RegisterHandler`, struct-tag `cli:`/`arg:` reflection, and the `RegisterGlobals[T]`/`Globals[T]` generics pair. One `Command` style remains; a typed `Get[T](kwargs, key)` accessor replaces verbose type assertions. `Passthrough`/`Deprecated` become discriminated variants of the one entry.
- Python: `@app.command` remains as sugar over the carrier; `needs_context` annotation-sniffing is **deleted** — the context becomes an always-passed argument (ignore it if unused). Passthrough/deprecate fold into the discriminated carrier model.

Conformance cases that exercised implicit JSON-printing, emit, or the removed Go styles get updated/re-pinned; the observable CLI behavior of the surviving contract is pinned with new cases (exit-only, data-only, exit+data).

## 3. Python: delete the silent version fallback

`python/strictcli/__init__.py:2488-2494`: `version=None` auto-detects via `importlib.metadata.version(self.name)` and on `PackageNotFoundError` silently sets `version = "unknown"`. Two violations in five lines: an inferred value in a declare-everything framework, and silent degradation instead of a hard error (plus a false app-name==distribution-name assumption). **Decision: delete the auto-detect entirely; `version` becomes a required App field** (matching Go). Breaking; changelog entry shows the one-line migration (`version=importlib.metadata.version("distname")` at the call site if wanted).

## 4. Python: `config set` must preserve comments

Go preserves comments/formatting via go-toml-edit; Python regenerates the file with its hand-rolled writer (`_write_toml_flat`/`_write_toml_nested`, docstring at `:387-389` admits the dependency avoidance) and destroys user comments — silently different destructive behavior for the same command. **Decision: Python adopts tomlkit** (the canonical format-preserving TOML library) for the config write path — its first runtime dependency, the same honest posture Go already has ("zero deps except TOML editing"). Pin with a conformance case: `config set` on a commented TOML config, comments survive byte-for-byte.

## 5. Go: centralize error messages in errors.go

All ~193 panic/error format templates move into one `errors.go` module of named format functions. Eliminates message drift between call sites within Go and makes parity extraction a trivial single-file parse (replacing ~15 hand-maintained regexes over 10 files in `check_error_parity.py`). Python already extracts cleanly (uniform raise sites); no Python change.

## 6. API-surface extraction: describe() self-dumps replace regex

`check_api_surface.py` currently regex-parses Go source (struct fields + option-function signatures, lines 225-271) — the checker's most brittle component. **Decision: Go gains a dev-only self-describe program using `reflect`** that dumps the real API surface (entities, fields, option funcs) as JSON; the checker consumes that instead of regexes. Python keeps its live introspection (same mechanism, different spelling). The checker's Go-specific exclusion dicts shrink accordingly.

## 7. Other pinned divergences (each: pinning case first, then fix)

- **Dict output order**: Go's multi-key dict output is map-iteration-randomized (every existing case uses single keys). Canon: deterministic insertion order. Fix Go; add multi-key cases.
- **Integer echo in the 2^53–2^63 range**: no accepted-value case exists in the danger zone. Add cases pinning exact echo of e.g. `9007199254740993` and `2^63-1`.
- **`@`-prefix trailing-trim**: the trim sets differ between languages. Canon: Go's trim set. Fix Python; pin with cases.
- **`config edit` failure handling**: Go errors when the editor fails; Python silently ignores. Canon: Go's hard error. Fix Python; pin.
- **MCP error strings**: casing differs (`Parse error` vs `parse error`) and Python has an extra `-32600` branch Go lacks. Canon: Go's strings; remove the Python-only branch. Pin.
- **Regex `$` laxity**: Python-only — `re` `$` matches before a trailing newline, so validation patterns accept trailing-newline input Go rejects. Fix Python (fullmatch/`\Z` semantics); pin with registration-error cases.
- **Go `Test()` 64 KB truncation**: Go's in-process test capture truncates output at 64 KB; Python's is unbounded. Remove the truncation.

## 8. Parity checker rework (generalize + harden)

- Parity mode in `conformance/run.py`: replace hardcoded pairwise diffing with N-way output identity (run all targets, assert all outputs byte-identical, flag the odd one out with its diff). Currently N=2; the machinery stops assuming two.
- `check_error_parity.py`: replace the two-directional diff with a canonical-multiset comparison (normalize each implementation's extracted messages into one canonical set, compare symmetrically, per-implementation exclusion lists). Consumes `errors.go` (item 5) for Go.
- `check_api_surface.py`: consume the describe() dumps (item 6); restructure entity/field mapping so adding a target is data, not code.

## 9. Wire up check_schema_parity.py

`conformance/check_schema_parity.py` (744 lines: generate apps, run `--dump-schema`, structurally diff the JSON) is orphaned — referenced by no checks.toml, tool, or CI — and uses the legacy dead codegen path. Per dead-code policy it is disconnected-but-valuable: whole-schema structural diffing catches divergences that the 2 existing dump_schema cases cannot. **Decision: port it onto the live harness execution path, register it as a `schema-parity` check in `conformance/conformance_tool/.strictcli/checks.toml`** so it runs under `--tag pre-release`.

## 10. Documentation debt

- Root `CLAUDE.md`: Python line count is ~7,500 (not "~2040"); Go is ~17 non-test files (not "five files, ~2680 lines"); the "zero dependencies (stdlib only)" claim for Go is **false** — `go/go.mod` requires `github.com/smm-h/go-toml-edit v0.2.2`, imported by core files `config.go:13` and `check.go:10` (go/README.md already admits it). Add missing subsystem docs: MCP server, as_tools/Tool, invoke/call + InvokeError, infra-root/handshake-env, provenance/Source, hermetic mode, `@`-prefix loading.
- Sub-project CLAUDE.md files (python/, go/, conformance/): stale `rlsbl release [patch|minor|major]` syntax, wrong manual-CHANGELOG instructions (CHANGELOG.md is generated), `conformance/CLAUDE.md` contains a literal `{{publishSetup}}` placeholder and a release-workflow section contradicting its dev_node status.
- Update docs wherever items 2–4 change public behavior (version required, emit removal, result contract, config set preservation).

## Affected files

- `python/strictcli/__init__.py` (float formatter unification, version, tomlkit config writer, emit/result contract, needs_context removal, regex `\Z`, `@`-trim, config-edit error, MCP strings)
- `python/pyproject.toml` (tomlkit dependency)
- `go/strictcli/`: `parse.go`, `config.go`, `help.go` (float canon), new `errors.go`, `strictcli.go` (trio collapse, result contract, Emit removal), `context.go` (generics pair removal), `mcp.go`, new self-describe entry point, Test() truncation site
- `conformance/`: `run.py`, `check_error_parity.py`, `check_api_surface.py`, `check_schema_parity.py`, `conformance_tool/` + its `checks.toml`, new `cases/float_format.json`, new multi-key dict / big-int / `@`-trim / config-edit / outcome-contract cases, new `float_vectors.json` + generator, fuzz harness
- Root `CLAUDE.md`, `README.md`, sub-project `CLAUDE.md` files
- Both `.rlsbl/`-managed changelogs (breaking entries: version required, emit removal, result contract, Go style collapse)

## Effort

Large — this is a coordinated breaking release of both implementations plus a conformance-suite hardening pass. Natural sequencing: pinning cases and the float canon first (they gate everything), then the result-contract/registration redesign (largest single item, Go-heavy), then the independent fixes (items 3–7), checker rework (8–9) alongside items 5–6, documentation (10) last. Items 3, 4, 7 are individually small; items 1, 2, 8 are the bulk.
