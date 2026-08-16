# The config mechanism is half-built: decide whether to complete it, demote it, or remove it

## Summary

strictcli ships a native config-file mechanism (`WithConfig()`, `ConfigField`, a
five-command `config` group, config-backed flag resolution). Investigation of the
Go implementation at v0.33.0 found it works as documented for **config-backed
flags**, but the **`ConfigField` half is not reachable from consumer code**: a
declared config field's value never arrives at a handler, and no accessor exists
to fetch it.

The result is that `ConfigField` can only ever function as a validation-and-help
annotation on a name that a *flag* already owns. That is how the one substantive
consumer uses it, working around the shape rather than using it as declared.

This todo records the full findings and lays out three paths. It does not pick
one — the trade-off is a framework-design call.

## How this came up

A Go consumer needed to move several parameters off the command line after
v0.33.0's mutating-default ban (§27.1) made `Default()` illegal on mutating
commands. The obvious question was whether a config file could supply those
values instead. It can — that part works, and is documented below as a confirmed
fact. But investigating how to *read* a config value in a handler surfaced that
there is no way to, unless the value is also declared as a flag.

## Confirmed behavior (Go v0.33.0)

Verified against the working checkout and, where marked, empirically against a
binary built from it.

### What works

**Declaration surface**

| Symbol | file:line |
| --- | --- |
| `WithConfig()` | `strictcli.go:539` |
| `WithConfigPath(path)` | `strictcli.go:546` |
| `WithConfigPathRelativeToRoot(envVar, parts...)` | `strictcli.go:639` |
| `WithConfigFormat(format)` | `strictcli.go:553` |
| `WithNoDefaultConfigPath()` | `strictcli.go:562` |
| `WithConfigConflictMode(mode)` | `strictcli.go:572` |
| `App.ConfigField(name, opts...)` | `config.go:162` |
| `ConfigFieldType/Help/Default` | `config.go:133,140,147` |
| `WithConfigFields(fields...)` | `strictcli.go:1147` |

**Formats.** JSON and TOML only, consumer-selected; default `"json"`
(`strictcli.go:1906-1907`). Anything else is a construction-time hard exit
(`strictcli.go:1910`). Parsing at `config.go:374-399`; malformed input errors
with line/column.

**Path resolution** (`config.go:335-352`), in order: runtime `--config <path>`
(pre-command global, pre-scanned at `strictcli.go:3092-3124`); then app-level
`WithConfigPath` / `WithConfigPathRelativeToRoot`; then
`$XDG_CONFIG_HOME/<app>/config.<ext>` falling back to `$HOME/.config/...`.
No cwd walk-up. `WithNoDefaultConfigPath()` removes the third tier
(`strictcli.go:3295`). Missing file is a hard error when named by `--config`
and silently an empty map at the default path (`config.go:365-373`).

**Precedence.** `CLI > env > config > default`, implemented at
`parse.go:502-618` with source labels assigned at `parse.go:624-633`.
`ConflictMode("error")` turns a divergent dual source into a hard error;
identical values are not a conflict (`parse.go:550-567`, messages at
`errors.go:649-653` and `errors.go:661`).

**Config values are a first-class source.** `type Source` at `parse.go:16`,
members at `parse.go:18-25`, labels at `parse.go:28-44`. `SourceConfig` is set
at `parse.go:580` / `parse.go:629`. `Context.Provided` returns true for it
(`context.go:291-297`), and the doc comment at `context.go:282-286` states the
intent directly: *"Sources cli, env, config and implied are provided; default
and infra are not."* `isPresentForDeps` agrees (`parse.go:122-132`).

**Consequence, verified empirically:** a `Required()` flag on a *mutating*
command whose value comes from the config file satisfies both the parse
requirement and §27.1's ban. The ban is a registration-time walk over
`presence` (`update.go:310-346`, skip at `update.go:329-331`) and never consults
a runtime source. Config is therefore a legitimate answer to the ban, not a
loophole around it.

**The `config` command group** — `registerConfigGroup` (`config.go:807-1265`),
all-or-nothing with `WithConfig()`: `config path` (`config.go:811`),
`config show` (`config.go:822`), `config set` (`config.go:1037`), `config edit`
(`config.go:1205`), `config init` (`config.go:1241`).

**Schema.** Top-level `config`, `config_format`, `config_path`,
`config_conflict_mode`, `config_fields` (`schema.go:657-674`); per-command bound
list at `schema.go:437-439`.

**Validation.** `validateBoundConfigFields` (`config.go:1270-1290`): missing
required field (`config.go:1281`), wrong type (`config.go:1286`). Unknown-key
rejection at `config.go:1315`.

### What does not work, or surprises

**1. `ConfigField` values never reach the handler. This is the core finding.**

`context.go` exposes exactly `DryRun, ApproveConsequential, Quiet, Verbose,
JSON, Payload, Effects, InfraValue, ConnectionEnvValue, Info, Warn, Debug,
Error, Source, Provided, Unset`. There is no `ConfigField` / `ConfigValue`
accessor. `validateBoundConfigFields` (`config.go:1270-1290`) validates and
returns; nothing forwards the value.

Verified empirically: with two bound config fields present in the file and
bound via `WithConfigFields`, the handler's kwargs contained only the flag —
both config fields were absent.

The Python implementation has no accessor either, so this is a cross-language
design state rather than a Go omission.

The practical effect: the only way to get a config value into consumer code is
to declare a **flag** with the matching param name and let the config-backed
cascade fill it. At that point `ConfigField` on the same name is explicitly
demoted to a validation-only annotation (`config.go:229-233`,
`strictcli.go:2172-2188`), and its explicit default must agree with the flag's
or registration panics.

**2. `ConfigField` is scalars-only** (`config.go:189` — `TypeStr/Bool/Int/Float`).
Config-*backed flags* handle lists and dicts fine (`coerceConfigValue`,
`config.go:526-579`), so a list-valued flag can read from config but cannot be
annotated with a field. The one substantive consumer carries a source comment
recording exactly this: a list flag was left without a `ConfigField` and without
`ConflictMode` because the field type system could not express it.

**3. Config keys are a single flat namespace.** Keyed by flag param name
(`parse.go:540-541`, `config.go:788`). Two commands sharing a flag name read the
same key; there is no per-command scoping. Dotted `ConfigField` names produce
TOML `[section]` grouping in `config init` output (`config.go:1348-1402`), but a
section namespaces *fields*, not commands. Name regex at `config.go:158`.

This is fine for a flag meaning the same thing everywhere and unusable for a
common name like `out` that means something different per command.

**4. Unknown-key rejection is conditional on declaring at least one
`ConfigField`** (`strictcli.go:3408`). An app with `WithConfig()` and zero
config fields silently accepts arbitrary junk keys. Verified empirically. That
is a soft failure in a framework whose stated philosophy is hard errors only.

**5. `config set` ignores the runtime `--config` override.** It computes its
target from the declared/XDG path only (`config.go:1039`). Verified empirically:
invoking with `--config <other>.toml` previewed a write to the XDG path, not to
the named file. Defensible as "set edits *your* config", but it is undocumented
and surprising — the same invocation reads one file and writes another.

**6. Config membership is invisible in `--help`.** The meta-parts builder
(`help.go:585-614`) emits `env: VAR` but has no config counterpart. A flag
readable from config looks identical to one that is not. A colliding field's
help text surfaces only in `config show` (`config.go:937-939`) and in the
`config init` template (`config.go:1336-1338`).

**7. `--hermetic` suppresses config loading entirely.** Mutually exclusive with
`--config` (`errors.go:529`) and with any `config` subcommand (`errors.go:531`).
A `Required()` flag supplied only by config therefore becomes a hard error under
`--hermetic`. Correct behavior, but it means "config satisfies the ban" carries
an asterisk that consumers must know about.

**8. The framework does not exempt its own commands from §27.1.** `config set`'s
`--value/--clear/--default` is a member-spelled selector, and the comment at
`config.go:1012-1027` records that its previous two-bool shape was refused by the
mutating-default ban. Worth preserving as precedent in whatever is decided.

## Adoption

Two consumers across the fleet use the mechanism at all:

- **One Go consumer, substantively**: `WithConfig()` + a root-relative TOML path
  + `WithConfigFormat("toml")`, with two global flags carrying `ConfigField`
  annotations and `ConflictMode("error")`. It uses the colliding-field pattern
  throughout — the flag's default is the authority, the field supplies help and
  unknown-key validation. It is a working consumer of the feature and any
  removal breaks it.

- **One Python consumer, minimally**: sets the config flag and nothing else — no
  fields, no path or format override. It gets the `config` group and
  flag-from-config resolution for free.

Notably, **three separate consumers hit §27.1's mutating-default ban and none of
them reached for config to resolve it.** All three chose `Optional()` plus a
fallback applied in the handler, including the Go consumer that already *has* a
config file and could have routed the values through it. That is a signal worth
weighing: when the ban forced a choice, nobody found config to be the ergonomic
answer, even where it was already wired up.

## The paths

### Path A — complete it

Give `ConfigField` a handler-reachable value and make it a real declaration.

- Add a context accessor (`ctx.ConfigValue(name)` or similar) returning the
  validated, typed value, with a source label consistent with the existing
  `Source` enum.
- Widen `ConfigField` beyond scalars so a list- or dict-valued key can be
  declared and annotated like any other.
- Make unknown-key rejection unconditional rather than contingent on at least
  one field being declared.
- Surface config membership in `--help`, alongside the existing `env: VAR` part.
- Document the `config set` path asymmetry, or change it to honor `--config`.

**Pros.** The feature becomes what its API already implies. Consumers stop
needing a shadow flag for every config value, which is currently the only route
into a handler. Removes the scalars-only cliff that already forced one consumer
into an inconsistent design. Aligns with the framework's hard-errors philosophy
by closing the silent junk-key hole.

**Cons.** Largest surface. Three implementations plus the conformance suite. A
new accessor is new public API that must be designed carefully — in particular
what it returns for an absent optional field, and whether it participates in
`Provided()`. Widening the field type system touches validation, `config init`
rendering, `config show`, and the schema.

**Effort.** Large. Two to four days across the three implementations, most of it
in test and conformance work rather than the accessor itself.

### Path B — demote it honestly

Accept that `ConfigField` is an annotation on a flag, and say so everywhere.

- Document it as such in the architecture docs and the API comments: it never
  delivers a value; it annotates a flag-owned name with help, a type assertion
  and unknown-key participation.
- Consider renaming to reflect that (`ConfigAnnotation`, `ConfigKeyDoc`, or
  similar) so the name stops promising a value channel.
- Keep the scalars-only limit but document it at the declaration site rather
  than leaving consumers to discover it.
- Still worth fixing independently: the conditional unknown-key rejection (#4)
  and the `--help` invisibility (#6), neither of which depends on this choice.

**Pros.** Small, honest, and immediately reduces the chance of the next consumer
building the same wrong mental model. No new public API to get wrong. Preserves
the working consumer unchanged.

**Cons.** Leaves a declaration construct whose only function is to describe
something else. A consumer who wants a config-only value still cannot have one
without inventing a flag for it. Renaming is itself a breaking change for the
one substantive consumer, so it would need to ride a minor bump.

**Effort.** Small. Half a day for documentation; one day if the rename is
included.

### Path C — remove the config mechanism

Delete `WithConfig()`, `ConfigField`, the `config` command group, and the
config tier of the precedence chain. Consumers that want a config file read one
themselves.

**Pros.** Removes a feature with two consumers, one of them nominal, whose
`ConfigField` half is unreachable and whose flat namespace limits it to
app-global settings. Shrinks the precedence chain from four tiers to three,
which simplifies `parse.go`, the source enum, `Provided()`, `--hermetic`
interactions, `config set`'s path asymmetry, and the schema. Fewer auto-
registered commands appearing in consumer CLIs unbidden.

**Cons.** Breaks a real, working consumer, which would have to hand-roll
replacement config parsing — and hand-rolled config is precisely what the
framework exists to prevent, so this trades a framework problem for a consumer
problem in every app that wants a config file. Loses genuinely good properties
that are hard to reproduce by hand: source labels, `ConflictMode("error")`,
`--hermetic` suppression, schema publication, and the free `config` command
group. It also removes a legitimate answer to §27.1's ban.

**Effort.** Large, and irreversible in practice. Two days of removal plus a
migration path for the existing consumer, and it is a breaking change requiring
a minor bump.

### Path D — leave it as is

Change nothing; treat the current state as the intended design.

**Pros.** Zero cost. Nothing is actually broken for the current consumers, both
of whom already work within the shape.

**Cons.** The next consumer repeats the same investigation and reaches the same
confusion. The junk-key hole (#4) and the `--help` invisibility (#6) stay,
and both are defects independent of the larger question.

**Effort.** None.

## Recommendation

None offered — this is a framework-design call about what the construct is *for*.
The evidence above is the input.

Two observations that may help weigh it:

1. The adoption pattern is informative but not decisive. Three consumers meeting
   the mutating-default ban all chose handler fallbacks over config, including
   one that already had config wired up. That suggests config is not the natural
   answer to the ban — but it does not say the feature is unwanted, since its
   actual user uses it for something else entirely (a persistent per-user
   setting, not a per-invocation parameter).

2. Items #4 (conditional unknown-key rejection) and #6 (config invisible in
   `--help`) are worth fixing under Paths A, B, and D alike. They are small,
   independent of the larger decision, and #4 in particular is a silent-accept
   in a framework that bans silent-accepts.

## Affected files

Go implementation:

- `go/strictcli/config.go` — the whole mechanism: field declaration, path
  resolution, parsing, coercion, validation, the five `config` subcommands
- `go/strictcli/strictcli.go` — app options (`:539-572`, `:639`), `WithConfigFields`
  (`:1147`), format validation (`:1906-1910`), collision handling
  (`:2172-2188`), `--config` pre-scan (`:3092-3124`), default-path suppression
  (`:3295`), unknown-key condition (`:3408`)
- `go/strictcli/parse.go` — precedence (`:502-618`), source labels (`:624-633`),
  conflict detection (`:550-567`), the `Source` enum (`:16-44`),
  `isPresentForDeps` (`:122-132`)
- `go/strictcli/context.go` — where an accessor would go (`:282-297` for the
  `Provided` semantics it must fit)
- `go/strictcli/help.go` — meta-parts builder (`:585-614`) for #6
- `go/strictcli/schema.go` — config keys (`:657-674`), per-command bound list
  (`:437-439`)
- `go/strictcli/errors.go` — conflict messages (`:649-661`), hermetic exclusions
  (`:529-531`)

Python and TypeScript implementations: the equivalent surfaces, plus the
conformance suite, which enforces cross-implementation parity on error templates
and would need updating for any message change.

Docs: `docs/architecture.md` (config precedence at `:220-230` and `:1195-1207`;
schema keys at `:658-669`; config-field entry shape at `:890`).

## Effort estimate

| Path | Effort |
| --- | --- |
| A — complete it | Large (2-4 days, three implementations + conformance) |
| B — demote it honestly | Small (0.5 day docs; 1 day with rename) |
| C — remove it | Large (2 days + consumer migration; breaking) |
| D — leave as is | None |
| #4 and #6 alone | Small (0.5 day), and worth doing under A, B or D |
