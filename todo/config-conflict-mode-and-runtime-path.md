# Config: runtime path selection, conflict-on-overlap mode, hard-error loading

## Context

A consumer tool wanted file-based defaults with strict semantics: no default
config path (the user must explicitly name the file per invocation), and
"config file and CLI flag both set the same key" as a hard error instead of a
silent CLI-wins override. None of this is expressible in strictcli today, so
the tool had to hand-roll a small loader and an argv scanner outside the
framework. These semantics are generally useful and belong in the framework so
every strictcli tool can opt into them declaratively.

## Problems (Go implementation; Python mirrors them)

1. **Config path is fixed at NewApp time.** `configPath()`
   (go/strictcli/config.go, ~line 302) accepts only the `WithConfigPath`
   override or falls back to XDG. There is no way to choose the file per
   invocation (e.g. a reserved `--config <path>` flag), and no way to say
   "no default path at all -- load config only when explicitly requested."
2. **CLI silently overrides config.** parse.go (~line 380) skips config
   resolution for any flag already in `cliSet`. Conformance blesses this
   (config_advanced.json "precedence - CLI wins over config"). There is no
   opt-in mode that treats the overlap as an error, and no `Conflicts`-style
   dependency type ("if A present then B must be absent") -- `MutexGroup` is
   exactly-one and provenance-blind, so it cannot express it either.
3. **Malformed config is a warning, not an error.** `loadConfig`
   (config.go, ~lines 326-346) prints `warning: invalid TOML ... ignoring` and
   continues with an empty map. This is silent degradation: a user with a
   typo'd config file gets default behavior with no failure. Per the house
   philosophy (hard errors, not warnings -- agents ignore warnings), an
   enabled-but-broken config should abort. Same for an explicitly named file
   that does not exist. Note go-toml-edit already returns rich `ParseError`
   (line/column/snippet) that loadConfig currently discards.
4. **No provenance for handlers.** The value-source attribution computed
   inside `config show` (config.go, ~lines 604-703) is not exported; handlers
   receive only resolved values and cannot distinguish CLI / env / config /
   default. Exposing a per-flag source map would let tools implement custom
   policies the framework does not anticipate.

## Proposed solutions

### A. Runtime config path (reserved flag)

An app option, e.g. `WithConfigFlag()`, that registers a reserved global
`--config <path>` flag and defers config loading until after argv is scanned
for it. Combined with the absence of `WithConfigPath`, an app could declare
"no default path": config loads only when `--config` is passed.

- Pros: per-invocation config becomes first-class; "explicit mode selection"
  becomes expressible; `config` command group could operate on the named file.
- Cons: config loading moves from NewApp-finalize to parse time -- the eager
  `loadConfig` at strictcli.go ~1117 and the `config` subcommands' fresh loads
  need rework; schema/help must present the reserved flag consistently.

### B. Conflict-on-overlap mode

An app or per-flag option, e.g. `WithConfigConflictMode("error")` (default
`"cli-wins"` for compatibility), that makes "key present in loaded config AND
flag explicitly passed on CLI" a parse error naming the key.

- Pros: eliminates the silent-override class entirely for tools that want it;
  trivial to check at the existing merge point (parse.go config loop already
  knows both facts).
- Cons: needs a conformance-case update strategy since current cases lock in
  silent CLI-wins; interaction with env-supplied values must be defined
  (env counts as explicit or not).

### C. Hard-error config loading

Change `loadConfig` failure behavior: when config is enabled and the file
exists but is malformed, error out (exit nonzero) with the go-toml-edit
ParseError position instead of warning-and-ignoring. When the path was given
explicitly (WithConfigPath or proposal A's flag) and the file is missing,
error as well; a missing file at the implicit XDG default path stays soft.

- Pros: aligns with the hard-errors philosophy; typos surface immediately.
- Cons: technically breaking for anyone relying on ignore-on-malformed
  (arguably nobody should); needs conformance updates.

### D. Provenance exposure (nice-to-have)

Export the per-flag source map (`cli` / `env` / `config` / `default`) --
either as a second handler argument (breaking), a context-style accessor, or a
framework field in kwargs (e.g. reserved key). Enables consumer-side policies
without framework changes for each.

- Pros: unlocks custom policies generally.
- Cons: API-surface growth; reserved-kwarg approach needs a collision-safe key.

A + B + C together cover the concrete consumer need; D is independent.

## Affected files

- go/strictcli/strictcli.go (app options, finalize-time eager load ~1110-1125)
- go/strictcli/config.go (configPath, loadConfig, config command group)
- go/strictcli/parse.go (config merge loop ~374-400, error paths)
- python/strictcli/__init__.py (mirror all of the above)
- conformance/cases/config_advanced.json and new cases (runtime path, conflict
  mode, malformed-file hard error)
- docs (config documentation pages)

## Effort estimate

Medium. Each piece is small in isolation, but the loading-time move (A) touches
app lifecycle, and both implementations plus conformance must stay in lockstep.
Roughly: A ~1 day, B ~half day, C ~half day, D ~half day, across both
languages including conformance and docs.
