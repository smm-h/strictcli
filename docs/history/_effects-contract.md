# Effects-regime contract

Normative cross-language contract for the strictcli effects regime (command classification,
the `ctx.effects` handle, unsettled-value dry-run previews, resource tokens, grants, the
reserved-flag quartet, guard v2, and the conformance surface that pins them).

This document is the **specification** that the Python reference implementation, the Go and
TypeScript ports, and the conformance suite are all implemented against. It contains no TBDs.
Every decision-bearing ruling here was ratified upstream; the mechanical remainder was derived
from the code as it stands at the time of writing and is pinned here so implementors have
nothing left to decide. Where this document and an implementation disagree, this document wins
until it is amended.

Amended 2026-08-02 after an adversarial audit, folding in two freshly-ratified user rulings
(`skip_if_current` is preview-annotation-only; mutating passthrough commands prompt) and the
audit's defect list. Amended again 2026-08-03 after a re-audit, closing the residual gaps it
found -- all of them in §2.5's surface (TS declared return and parameter types, `url`'s
carrier-acceptance, carrier-valued `write` content, inapplicable options, void
non-forwardability, `body`'s exclusion, `grant=` on an observe) plus the effect log's
live-mode population and two unpinned spellings. §18 records the full provenance of every
decision, ratified and authored alike, and is exhaustive.

Amended a third time 2026-08-03 at the conformance-and-parity round, folding in five ratified
rulings (§18.4) that reconcile this document with the three shipped implementations. The governing
one inverts the precedence clause above for this round only: **where all three implementations
agree against this document's draft text, the implementations win and the document is amended.**
Every amendment is marked in place with the ruling letter it implements.

Amended a fourth time 2026-08-03 at the spec-audit remediation round (§18.5). That round's
governing rule is the **normal** one, not §18.4's inversion: an adversarial spec-only audit found
seven places where the implementations disagreed with this document, and in six of them the
document was right and the code was fixed. The exceptions are recorded: §11's scope is strengthened
in code *and* narrowed in text where TypeScript provably cannot deliver it (§17), §8.2 and §3.2
pin readings this document had left silent, and §8.4 corrects a claim that was simply false.

Amended a sixth time 2026-08-04 at the **consequence round** (§18.7), which rewrites §8. The
confirm protocol no longer infers the prompt from classification; commands declare themselves
`consequential` and the framework prompts for those and no others. `--yes` becomes
`--approve-consequential` in the reserved quartet, and `yes` stays banned. Adoption across six
consumers is the evidence: 63% of commands classified `mutating`, against ~5-10% that are
genuinely dangerous. §1's classification is unchanged -- it answers a different question, and it
answers it well.

Amended a seventh time 2026-08-06 at the ecosystem fix campaign's strictcli phase (§1.2/§1.5).
This is the first amendment that **reverses** a §16 exclusion: `dry_run_supported` moves from
"what the regime deliberately does NOT have" to a shipped registration-level declaration. The
reversal is narrow and the old bullet's reasoning survives it -- what §16 was guarding against
was runtime *negotiation* (discovery, probing, inheritance across a process boundary), and none
of that is added. A command states statically that a preview of it would lie, and the framework
refuses `--dry-run` for it. New §1.1a carries the field, guards, parse-time gate and help
rendering; new §12.2a carries the four message templates; §13 gains the schema pair and the
conformance-schema change; §16's bullet is struck through in place rather than deleted, so the
record of what was once excluded, and why it stopped being excluded, stays readable.

Amended 2026-08-13 at the **machine-interface round** (§18.9). This round adds machine mode and
its envelope (§19) and the process trace store's contract items (§20), and amends §3, §7, §14 and
§16 in place. The governing rule is the normal one -- this document wins until it is amended, and
it is amended here rather than contradicted. The round's shape in one sentence: **outside machine
mode nothing in this document changes at all**, and inside machine mode the envelope is the only
document stdout carries, with §3's promises re-stated over it rather than dropped -- the preview
is never absent, the truncation error and the abort marker become envelope members instead of
stderr lines, and §14.2's structured effect log stops being a test-only diagnostic and becomes the
preview's source. Sections are never renumbered in this document, so §19 and §20 sit physically
after §18.

Placement note: this file uses the `docs/history/_*.md` convention established by
`docs/history/_ts-port-spec.md`. The underscore prefix keeps it off the published docs site --
selfdoc's `resolve_all_docs` walks `docs/` recursively and treats every non-underscore `.md`
as a page.

---

## 0. Terminology

| Term | Meaning |
|------|---------|
| **Classification** | The mandatory per-command `effect` field: `"read_only"` or `"mutating"`. |
| **Effect** | A single recorded operation minted through the `ctx.effects` handle. |
| **Effect kind** | The coarse taxonomy of an effect (`PROC_MUTATE`, `PROC_SPAWN`, `FILE_WRITE`, `NET_MUTATE`, `CACHE_WRITE`). |
| **Dry mode** | The run is executing under the framework-owned `--dry-run` flag. Effects are *recorded*, never executed. |
| **Recorded mutation** | An effect that was recorded rather than executed (dry mode only). |
| **Observe** | A read-only operation performed through the effects handle (e.g. a process run on the `proc_observe_allowlist`). |
| **Post-mutation observe** | An observe issued after at least one mutation has been recorded in the same run. Its result is unknowable, so it yields an `Unsettled` carrier. |
| **Carrier** | An `Unsettled` value standing in for a result that cannot exist because nothing actually ran. |
| **Forwarding (a carrier)** | Passing a carrier as an argument to a later `ctx.effects` call. Legal; renders the brand inline. |
| **Extraction / branching** | Any attempt to read a concrete value out of a carrier, or to branch on it. Illegal; hard-errors and truncates the preview. |
| **Would-do log** | Dry mode's primary stdout output: the ordered, numbered rendering of the recorded effects. |
| **Resource token** | An opaque string naming what an effect produces. Declared metadata; compared by string equality only; never gates execution. |
| **Conditional annotation** | A `skip_if_current=` declaration. Preview-only: it renders a suffix in the would-do log and has no runtime behavior whatsoever. |
| **Grant** | A per-command, per-effect-kind authorization with a mandatory human reason. |
| **Guard v2** | The tightened handler-signature validation that no longer exempts `**kwargs` handlers. |
| **Declared forwarding** | The registration-time declaration that a handler deliberately accepts and forwards `**kwargs`. |
| **Framework-internal command** | A command strictcli auto-registers itself (`check`, the five `config` subcommands). Subject to every rule in this document, plus §10.4. |

Two rules govern the whole regime and override any local convenience:

- **Fail closed.** If the framework cannot prove an operation is safe to preview, it stops with a
  precise error instead of guessing.
- **Zero inference.** The framework never infers classification, never infers whether an argument
  is a path, never canonicalizes a resource token, never evaluates user predicates, and never
  tracks whether a resource is "current". Everything is declared.

---

## 1. Command classification

### 1.1 The field

Every command carries a mandatory field:

```
effect = "read_only" | "mutating"
```

There is **no default**. A command registered without it is a registration-time hard error in
all three implementations. This is a breaking change for every existing consumer and is the
headline entry of the coordinated release.

**Deprecated commands are classification-exempt.** `app.deprecate(name, message=...)` /
`group.deprecate(...)` / `(*App).Deprecated(...)` (Python `DeprecatedCommand`, Go `deprecatedCmd`,
TS `DeprecatedDef`)
registers a retired name that has **no handler** and executes nothing: it prints its message to
stderr and exits 1. It therefore carries no `effect`, and passing one is a registration-time hard
error (`errDeprecatedCommandEffect`, §12.2). Deprecated entries never prompt (§8) -- they carry no
`consequential` declaration either -- never reach
dispatch, and never appear in the would-do log. They are also not command entries in
`--dump-schema` output -- they serialize into the separate top-level `deprecated` list -- so §13's
"`effect` is always emitted on every command entry" rule is unaffected. §14's conformance-schema
change (§13, last paragraph) encodes the exemption explicitly.

### 1.1a The `dry_run_supported` declaration

*Added 2026-08-06 (ecosystem fix campaign §1.2), superseding §16's "no `dry_run_supported`
capability negotiation" bullet. Shipped in py-strictcli, go-strictcli and ts-strictcli in the
same coordinated release as this amendment.*

Alongside classification, a command may carry a second, **optional** registration-level
declaration:

```
dry_run_supported          = true | false     (absent means true)
dry_run_unsupported_reason = <non-empty string>
```

Absence means the regime's baseline, where a `mutating` command's effects are recorded rather
than performed (§3). A command declares it **false** when a preview of it would *lie*: when its
effects escape the effects handle, or when its later steps read state that its earlier --
recorded, therefore un-performed -- steps would have written. Rather than render a dishonest
preview, the framework refuses `--dry-run` for that command and states the reason.

| Impl | Spelling |
|------|----------|
| Python | `dry_run_supported=False` + `dry_run_unsupported_reason="..."` keywords on `app.command(...)` / `group.command(...)` / the `Command` dataclass. |
| Go | `WithDryRunUnsupported(reason)` -- a `CmdOption`. The two fields collapse into one option because the reason is mandatory whenever the refusal is declared, so an option carrying the reason cannot express the illegal states. |
| TypeScript | `dryRunSupported: false` + `dryRunUnsupportedReason: "..."` on the twin command factories and the passthrough twins. |

**Three registration-time guards**, shared by every registration surface in each implementation:

1. `dry_run_supported=false` on a `read_only` command is a hard error. This mirrors the
   `read_only` + `consequential` prohibition of §8.1 and for the same reason: a command that
   changes nothing records nothing, so a preview of it can never be dishonest and there is
   nothing to refuse.
2. `dry_run_supported=false` without a non-empty reason is a hard error. The refusal is only
   useful if it says what a preview cannot honestly show.
3. A reason without `dry_run_supported=false` is a hard error -- there is nothing to explain
   while dry run is supported. Go has no analog for this third guard: `WithDryRunUnsupported` is
   its only spelling, so the orphaned-reason state is unrepresentable there.

**The parse-time gate** sits immediately after the command-help check, so that `--help` always
beats the refusal: asking what a command does must never be answered with a refusal to preview
it. The gate covers `run`, `test` and the conformance harness in one place because it lives in
the shared parse path, not next to `_confirm_consequential`.

Two boundaries follow from §7.2's pre-scan and are stated here so implementors do not
rediscover them: a `--dry-run` after a bare `--` is data and does not trigger the refusal, and a
`--dry-run` after a passthrough command's name is forwarded to the child rather than scanned, so
a passthrough that declares the refusal is only protected against a `--dry-run` written before
its name.

**Help rendering.** A command that declares the refusal gains a `Dry run:` section in its
command-level help, byte-identical across implementations:

```

Dry run:
  --dry-run is not supported: <reason>
```

The baseline needs no announcement, so the section is rendered only for a declaring command; a
section on every command would be noise. It renders before the passthrough early-return, because
a passthrough can declare the refusal too and its help is the only place the reason would
otherwise appear.

### 1.2 Per-language spelling

| Impl | Spelling |
|------|----------|
| Python | `effect="mutating"` keyword on `app.command(...)` / `group.command(...)` / the `Command` dataclass, sitting beside the existing `interactive` field (`python/strictcli/__init__.py`, `Command` dataclass, adjacent to `interactive: bool = False`). |
| Go | `WithEffect(EffectMutating)` / `WithEffect(EffectReadOnly)` -- a `CmdOption`, registered in `go/strictcli/strictcli.go` alongside `WithInteractive()`. Constants `EffectReadOnly` and `EffectMutating` are exported. |
| TypeScript | Twin factories `defineReadOnlyCommand(...)` and `defineMutatingCommand(...)` (`typescript/src/factories.ts`), which **replace** `defineCommand`. |

`defineCommand` is **removed** from the TS surface entirely: the factory itself, its
`typescript/src/index.ts` re-export, and its `typescript/src/describe.ts` descriptor all go.
Pre-stable projects get no compatibility shim; the twin factories are the only mint. The two
factories differ in the `Context` type they narrow the handler's `ctx` parameter to (§2.4), and
in nothing else -- the options object is otherwise identical.

**Passthrough commands are classified the same way, through the same scheme.** The existing
`passthrough(...)` factory (`typescript/src/factories.ts`, producing `PassthroughDef`) is likewise
replaced by twins:

| Factory | Classification | Handler `ctx` |
|---------|---------------|---------------|
| `readOnlyPassthrough(...)` | `read_only` | `ReadOnlyContext` |
| `mutatingPassthrough(...)` | `mutating` | `MutatingContext` |

The naming morphology matches the command twins (the classification is spliced into the existing
factory name; `defineCommand` -> `defineReadOnlyCommand` / `defineMutatingCommand`, `passthrough`
-> `readOnlyPassthrough` / `mutatingPassthrough`). `PassthroughDef` gains a
`readonly effect: "read_only" | "mutating"` member. Python and Go need no new spelling: a
passthrough is an ordinary command registration there (`passthrough=Passthrough(...)` /
`WithPassthrough(...)`), so it takes `effect=` / `WithEffect(...)` like everything else.
A passthrough declares `consequential` like any other command and prompts on exactly the same
terms (§8.1).

**`typescript/src/describe.ts` outcome** (the dev-only API-surface dumper that
`conformance/check_api_surface.py` reads):

| Before | After |
|--------|-------|
| one `defineCommand` factory descriptor (`options_type: "CommandSpec"`) | two descriptors, `defineReadOnlyCommand` (`options_type: "ReadOnlyCommandSpec"`) and `defineMutatingCommand` (`options_type: "MutatingCommandSpec"`), each carrying the existing eleven `option_keys` plus `grants` and `forwarding`; the `defineCommand` descriptor is deleted, not renamed |
| one `passthrough` factory descriptor | two descriptors, `readOnlyPassthrough` and `mutatingPassthrough`, each with the existing `option_keys` (`handler`, `help`, `hidden`, `tags`) plus `grants`; the `passthrough` descriptor is deleted |
| `CommandDef` entity descriptor, commented "The command carrier built by defineCommand" | same entity, comment updated to "built by the twin factories", `members` gaining `effect`, `grants`, `forwarding` |
| `PassthroughDef` entity descriptor | `members` gaining `effect` and `grants` (not `forwarding` -- a passthrough's signature is deliberately unpoliced already, §10.2) |

Two spec types exist because the twins' handler signatures differ (the `ctx` narrowing of §2.4);
everything else in `ReadOnlyCommandSpec` and `MutatingCommandSpec` is identical.

### 1.3 What classification buys

- **`mutating`** -- the command participates in dry mode (§3) and may call the mutating members of
  the effects handle. It does **not** prompt: the confirm protocol keys on the separate
  `consequential` declaration (§8.1), not on classification.
- **`read_only`** -- the command never prompts (and cannot be declared consequential at all,
  §8.1), and calling any mutating member of the effects handle is a hard error at call time (§9.1).
  It may call `ctx.effects.run(...)` only for argv prefixes on the app-level
  `proc_observe_allowlist` (§6.2).

Classification is a property of the command, not of the invocation. It is emitted in the schema
(§13) and is what consumers' `check` gates assert against.

---

## 2. The effects handle

### 2.1 Access

| Impl | Accessor |
|------|----------|
| Python | `ctx.effects` (property on `Context`) |
| Go | `ctx.Effects()` (method on `*Context`) |
| TypeScript | `ctx.effects` (getter on `Context`) |

### 2.2 The closed method set

Exactly eight methods. The set is **closed**: no implementation may add a ninth without amending
this document, and there is no escape hatch that mints an unlisted effect.

| Method | Kind | What it does |
|--------|------|--------------|
| `run` | `PROC_MUTATE` (or an observe -- §6.2) | Run a subprocess to completion. |
| `spawn` | `PROC_SPAWN` | Start a subprocess without waiting. Spawning is itself an effect (§16). |
| `write` | `FILE_WRITE` | Write bytes to a path. |
| `mkdir` | `FILE_WRITE` | Create a directory. |
| `remove` | `FILE_WRITE` | Delete a path. |
| `rename` | `FILE_WRITE` | Move/rename a path. |
| `chmod` | `FILE_WRITE` | Change a path's mode. |
| `http` | `NET_MUTATE` | Perform a network request. |

Per-language casing: Python and TypeScript use the names above verbatim (`ctx.effects.run`,
`ctx.effects.mkdir`); Go exports them capitalized (`ctx.Effects().Run`, `ctx.Effects().Mkdir`,
`ctx.Effects().HTTP`).

`CACHE_WRITE` (§9.2) has **no** public method. It is minted only by framework-internal code.

### 2.3 Common parameters

Every method accepts, in addition to its own operation-specific arguments:

- `resource=` -- optional opaque resource token (§5.1). Plain string, declared metadata only.
- `skip_if_current=` -- optional resource token; preview-only conditional annotation (§5.2).
- `grant=` -- optional grant name; must name a grant declared on the command (§6.1).

Per-language spelling: Python keyword arguments; Go a trailing variadic `...EffectOption`
(`Resource(t)`, `SkipIfCurrent(t)`, `UseGrant(name)`) matching the existing `CmdOption` /
`AppOption` idiom; TypeScript an optional final options object
(`{ resource?, skipIfCurrent?, grant? }`).

### 2.4 TypeScript compile-time narrowing

`defineReadOnlyCommand` narrows the handler's `ctx` to a `ReadOnlyContext` whose `effects`
member exposes only `run`. `defineMutatingCommand` narrows to the full `MutatingContext`.
A `.write()` inside a read-only command is therefore a **compile error**, and a `tsc`-level
negative test pins it.

Compile-time narrowing is a TS-only affordance. Go cannot express it (accepted ceiling), and
Python does not attempt it. Every implementation carries the **mandatory runtime seal** (§4.4,
§15) regardless, because plain JavaScript consumers bypass the type system entirely.

The same narrowing applies to the passthrough twins: `readOnlyPassthrough` narrows to
`ReadOnlyContext`, `mutatingPassthrough` to `MutatingContext`.

### 2.5 Signatures, returns and error semantics

The API is deliberately thin. The regime's value is in *recording*, not in wrapping subprocess or
HTTP libraries: everything below is the minimum needed to describe an operation precisely enough
to log it and to run it.

#### 2.5.1 Result shapes

Three result shapes, plus the void case, cover all eight methods -- four rows.

| Shape | Members | Produced by |
|-------|---------|-------------|
| `Completed` | `exit_code` (int), `stdout` (text), `stderr` (text) | `run`, and `Spawned.wait()` |
| `Spawned` | `pid` (int), plus `wait(check=True)` returning `Completed` (§2.5.2) | `spawn` |
| `Response` | `status` (int), `body` (bytes), `headers` (mapping, header names lower-cased) | `http` |
| *(none)* | -- | `write`, `mkdir`, `remove`, `rename`, `chmod` |

`stdout` / `stderr` are the child's output decoded as **UTF-8, strictly** (invalid UTF-8 is an
error, §2.5.4), with a **single trailing newline removed if present**. That is the form callers
actually want, and -- critically -- it is the form that can be forwarded straight into a later
effect's argv (§2.5.5), which is what lets a data-flow preview work without per-mode handler code.

Because `spawn` always streams (§2.5.2), the `Completed` its `wait()` yields carries the real
`exit_code` and empty `stdout` / `stderr` -- the same shape `run` returns, populated to the extent
a streamed child can populate it.

Per-language spelling: Python frozen dataclasses `Completed` / `Spawned` / `Response`; Go structs
of the same names with method accessors (§2.5.3); TypeScript interfaces of the same names with
camelCased members (`exitCode`, `pid`, `status`).

#### 2.5.2 Parameters

The three common options of §2.3 (`resource=`, `skip_if_current=`, `grant=`) are accepted by all
eight methods **in addition** to the operation-specific parameters below. There is no `shell=`
parameter anywhere and no method ever accepts a shell string -- argv lists only.

| Method | Operation-specific parameters |
|--------|------------------------------|
| `run` | `argv` (sequence of strings, required; any element may instead be a forwarded carrier -- §2.5.5); `cwd` (path, default: inherit); `env` (mapping merged **over** the inherited environment, never replacing it; default: none); `check` (bool, default `true` -- §2.5.4); `stream` (bool, default `false`; when true the child inherits stdout/stderr and the returned `stdout` / `stderr` are empty strings) |
| `spawn` | `argv` (required); `cwd`; `env`. Always streams (the child inherits stdio). No `check` on the `spawn` call itself -- there is no exit status at call time; `Spawned.wait(check=True)` carries it and takes the opt-out (§2.5.4). |
| `write` | `path` (required); `content` (required -- bytes, or text which is encoded UTF-8, or a forwarded carrier (§2.5.5); the log's byte count is the encoded length, and is replaced by the brand when the content is an *unsettled* carrier -- §3.2) |
| `mkdir` | `path` (required). Missing parents are created; an already-existing directory is not an error. |
| `remove` | `path` (required). Removes a file, a symlink, or a directory tree **recursively**; a missing path is not an error. |
| `rename` | `src` (required); `dst` (required) |
| `chmod` | `path` (required); `mode` (int, required; rendered in the log as leading-zero octal, §3.2) |
| `http` | `method` (string, required, upper-case); `url` (string, required; may instead be a forwarded carrier -- §2.5.5); `body` (bytes, default none; never accepts a carrier -- §2.5.5); `headers` (mapping, default none); `check` (bool, default `true` -- §2.5.4) |

Per-language spelling follows §2.3: Python keyword arguments; TypeScript an optional final options
object (`cwd`, `env`, `check`, `stream`, `body`, `headers` alongside `resource`, `skipIfCurrent`,
`grant`); Go a trailing variadic `...EffectOption`, adding `Cwd(string)`,
`EffectEnv(map[string]string)`, `Check(bool)`, `Stream(bool)`, `Body([]byte)` and
`Header(k, v string)` to the three of §2.3.
`Spawned.wait()` accepts `check` and nothing else (Python `wait(check=True)`, Go
`Wait(opts ...EffectOption)` honouring `Check(bool)` only, TypeScript `wait({ check? })`).

**Go's environment option is spelled `EffectEnv`, not `Env`** (amended 2026-08-03, ruling B). The
package already exports `Env(varName string) FlagOption` and Go has no overloading, so the pinned
`Env` spelling was unavailable. Only the *constructor* moves: the option's canonical snake_case
name stays `env` (§12.8), so `errEffectOptionNotAccepted` renders byte-identically in all three.
This is the sole per-language deviation in the option constructor set.

**An option a method does not accept is a call-time hard error** (`errEffectOptionNotAccepted`,
§12.8), in all three implementations. Python and TypeScript reject the unknown keyword / options-
object key -- **Python through an explicit `**_options` catch-all on each of the eight methods**,
not through CPython's native `unexpected keyword argument` `TypeError`, so that the rendered text
is the pinned template rather than an interpreter message (amended 2026-08-03, ruling C; forced by
§14.5's own conformance case, which requires the byte-identical message in all three). Go, whose
options are a single untyped variadic, **validates its `...EffectOption`
list at call time** and errors on any option outside the receiving method's accepted set. There
is no silent ignoring: `ctx.effects.mkdir(p, stream=True)` and
`ctx.Effects().Mkdir(p, Stream(true))` both fail, loudly, at the call. The accepted set per method
is exactly the table above plus the three common options of §2.3.

#### 2.5.3 Returns, per language and per mode

Python and TypeScript return the **real result** in live mode and an `Unsettled` carrier in dry
mode (per §4.1: every recorded mutation, and every post-mutation observe). Void methods return
`None` / `undefined` in live mode.

**Python and TypeScript declare the settled types only.** Every effect method's declared return
type is its settled shape and nothing else: `run` and `Spawned.wait` return `Completed`, `spawn`
returns `Spawned`, `http` returns `Response`, and the five path-mutating methods return
`None` / `void`. There is **no `| Unsettled` union** anywhere in either surface and **no narrowing
predicate** -- no `isUnsettled()`, no `is_unsettled()`, no type guard, no discriminant member. In
dry mode the runtime value sitting at those positions is the `Unsettled` carrier -- Python's
poisoned-dunder object, TypeScript's Proxy (§4.4) -- which the static type deliberately does not
mention: a handler that only forwards it never notices, and a handler that extracts from it or
branches on it trips the runtime seal and truncates the preview (§3.3). This is exactly the
Go-parity **one body, both modes** model -- the same handler source is the correct source in live
and in dry mode, and the mismatch surfaces at runtime, where it is honest, instead of being
papered over at compile time by a narrowing branch.

There is no `isUnsettled()` / `is_unsettled()` because **branching on unsettledness is
mode-branching.** A predicate would let a handler take one path in live mode and another in dry
mode, at which point the preview stops describing the run that will actually happen -- precisely
what the truncation mechanism exists to make impossible to do silently. A handler that legitimately
needs to know the mode for some non-effect reason reads `ctx.dry_run` / `ctx.dryRun` (§7.2); no
property of a *carrier* answers that question, by construction.

Go has no union type, so **every Go effect method returns a carrier type, always** -- settled in
live mode (its extractors return real values) and unsettled in dry mode (its extractors panic with
the truncation error, §3.3). `Completed`, `Spawned` and `Response` are therefore settleable
carriers: non-comparable structs (the `[0]func()` field of §4.4) whose extractor methods are
`ExitCode() int` / `Stdout() string` / `Stderr() string`, `PID() int` /
`Wait(opts ...EffectOption) (Completed, error)`, and `Status() int` / `Body() []byte` /
`Header(name string) string` respectively. The void methods return the plain payload-less
`Unsettled` of §4.4, whose extractors panic in **both** modes -- it never carries a value, only a
brand, and exists solely to give every Go effect method one uniform return shape. It is **not**
forwardable: a void result stands for nothing in either mode, so passing one into a later effect
is a call-time hard error in both modes and in all three languages (§2.5.5, §12.8).
All four Go carrier types expose the unexported `brandForm() string` the effects API reads at the
forwarding boundary -- for the three settleable carriers, to render the brand into the log line;
for the void carrier, to recognize it there and reject it.

| Method | Python / TS live | Python / TS dry | Go (always) |
|--------|------------------|-----------------|-------------|
| `run` (mutating) | `Completed` | `Unsettled` | `(Completed, error)` |
| `run` (observe, pre-mutation) | `Completed` | `Completed` (it really executed) | `(Completed, error)` |
| `run` (observe, post-mutation) | `Completed` | `Unsettled`, `«stale: ...»` brand | `(Completed, error)` |
| `spawn` | `Spawned` | `Unsettled` | `(Spawned, error)` |
| `write` / `mkdir` / `remove` / `rename` / `chmod` | `None` / `undefined` | `Unsettled` | `(Unsettled, error)` |
| `http` | `Response` | `Unsettled` | `(Response, error)` |

The Python / TS columns are the **runtime** values. Both languages *declare* only the settled
column (§2.5.6): the dry-mode carrier is a runtime phenomenon their static types never name.

#### 2.5.4 Error semantics -- one rule

**A failed operation is an error, not a value.** A `run` whose child exits nonzero, and an `http`
whose response status is outside 200-299, fail the call: Python raises `EffectFailed`, TypeScript
throws `EffectFailed`, Go returns a non-nil `error` as its second result. Invalid UTF-8 on a
captured stream fails the same way. The rule is uniform across `run`, `Spawned.wait()` and `http`;
the five void methods fail only on the underlying OS error.

Passing `check=false` (Go: `Check(false)`) opts a single call out: the result is returned with its
real `exit_code` / `status` and the handler decides. The opt-out is available on all three of the
failing calls -- `run`, `http` and `Spawned.wait()` -- so a handler can read a spawned child's
nonzero exit code the same way it reads a `run`'s. This exists because the ratified real-mode
idempotency idiom (§5.2) branches on **allowlisted observes**, and exit codes are the most common
predicate (`git rev-parse --verify`, `git diff --quiet`); without the opt-out that idiom would be
unusable.

Raising by default -- rather than always returning a status for the handler to test -- is the
choice that keeps previews long: a handler that never tests a status never branches on a carrier,
so dry mode (where nothing runs and nothing can fail) walks straight past it. Testing a status the
handler *did* ask for is honest branching and truncates when the value is unsettled (§3.3), which
is exactly right.

In dry mode a recorded mutation never fails: nothing ran. Only pre-mutation observes, which really
execute, can fail during a dry run, and they fail identically to live mode.

Message templates: §12.8.

#### 2.5.5 Forwarding a carrier into a parameter

§4.3 makes forwarding legal. Concretely, a carrier (or, in live mode, a result object) may be
passed anywhere a string-ish parameter is expected: any `argv` element, `path`, `src`, `dst`,
`url`, or `content` -- six positions, and no others. `mode`, `method`, `body`, `cwd`, `env`,
`headers`, `check`, `stream` and the three common options do **not** accept carriers -- passing
one there is a call-time hard error (§12.8). The two lists together are exhaustive over §2.5.2:
every operation-specific parameter of every method appears in exactly one of them. `body` sits on
the excluding side deliberately -- an HTTP request body is a payload, not a name, and a preview
that forwarded one would have to render an arbitrary blob into a log line.

At that boundary the API coerces via each shape's declared **scalar projection**:

| Shape | Scalar projection |
|-------|-------------------|
| `Completed` | `stdout` (already decoded and newline-trimmed, §2.5.1) |
| `Response` | `body`, decoded UTF-8 strictly, one trailing newline removed |
| `Spawned` | none -- forwarding a `Spawned` into a string position is a call-time hard error |
| `Unsettled` (void carrier) | none, in either mode -- forwarding a void result is a call-time hard error |

**Void results are never forwardable.** `write`, `mkdir`, `remove`, `rename` and `chmod` produce
nothing a later effect could name, in either mode, so passing their result into any of the six
accepting positions is a call-time hard error in **both** modes and in all three languages -- the
same `errEffectParamRejectsCarrier` family as the excluded parameters (§12.8). In Python and
TypeScript this is nearly unreachable by accident (a void method returns `None` / `undefined` in
live mode, and the dry-mode carrier is the only thing there is to pass); in Go, where every method
returns a carrier type by construction (§2.5.3), it is the rule that keeps the carrier-always
model from implying a forwardability it never had.

In dry mode the value is unsettled, so the brand form renders instead (§4.2) and no projection is
taken. This is what makes the §3.2 example -- `run: gh release view «step 4 output»`, forwarding
the carrier of an `http` effect -- one piece of handler code that is correct in both modes.

Reading a *member* of a carrier is extraction, not forwarding: `result.stdout` on an `Unsettled`
hits the poisoned accessor and truncates (§4.4). Forward the whole result object; let the API
project it.

Go types the carrier-accepting parameters as `any` (`argv []any`, `path any`, `src any`,
`dst any`, `url any`, `content any`), accepting the natural Go type (`string`, `[]byte`) or a
carrier and hard-erroring at call time on anything else. This is a Go-specific ceiling (§17); the
common all-literal case reads acceptably (`[]any{"git", "tag", "v1.2.3"}`) and matches the repo's
existing `map[string]interface{}` handler-args idiom.

Python and TypeScript type the same six positions as unions of exactly the shapes that project,
which the declared-settled returns of §2.5.3 make precise:

| Position | Python type | TypeScript type |
|----------|-------------|-----------------|
| `argv` element | `str \| Completed \| Response` | `string \| Completed \| Response` |
| `path`, `src`, `dst`, `url` | `str \| os.PathLike[str] \| Completed \| Response` | `string \| Completed \| Response` |
| `content` | `str \| bytes \| Completed \| Response` | `string \| Uint8Array \| Completed \| Response` |

**Python's four path positions carry `os.PathLike[str]`** (amended 2026-08-03, ruling D). The
runtime has always accepted a path object there -- the operand resolver runs `os.fspath` before
anything else -- and strictcli ships a PEP 561 `py.typed` marker, so a declared union without it
would make `ctx.effects.write(Path("out.txt"), ...)` a type error against code that works. The row
is the unit: all four of `path`, `src`, `dst` and `url` widen together, because all four resolve
through the same code path and a surface where `rename(Path(a), Path(b))` type-checks but
`http("GET", url)` does not would be incoherent. `argv` elements and `content` are **not** path
positions and keep their pinned unions unchanged. TypeScript needs no counterpart: it has no
path-object protocol.

Python spells `argv` itself `Sequence[str | Completed | Response]`; TypeScript's `argv` is an array
of the element type. The two rows differ only in each language's native byte-string spelling
(`bytes` / `Uint8Array`).

`Spawned` is a member of none of them (it has no projection), the void return is a member of none
of them (void results are not forwardable), and `Unsettled` appears in none of them either -- in
dry mode the runtime carrier arrives at a position statically typed `Completed` or `Response`,
which is exactly what lets one handler body typecheck once and be correct in both modes. The unions
are written inline in the method signatures; they mint no new exported type and therefore no new
`describe.ts` entity (§1.2).

#### 2.5.6 Cross-language parity table

| Method | Python | Go | TypeScript |
|--------|--------|-----|-----------|
| `run` | `ctx.effects.run(argv: Sequence[str \| Completed \| Response], *, cwd=None, env=None, check=True, stream=False, resource=None, skip_if_current=None, grant=None) -> Completed` | `ctx.Effects().Run(argv []any, opts ...EffectOption) (Completed, error)` | `ctx.effects.run(argv, opts?) => Completed` |
| `spawn` | `ctx.effects.spawn(argv: Sequence[str \| Completed \| Response], *, cwd=None, env=None, ...) -> Spawned` | `ctx.Effects().Spawn(argv []any, opts ...EffectOption) (Spawned, error)` | `ctx.effects.spawn(argv, opts?) => Spawned` |
| `write` | `ctx.effects.write(path: str \| os.PathLike[str] \| Completed \| Response, content: str \| bytes \| Completed \| Response, ...) -> None` | `ctx.Effects().Write(path any, content any, opts ...EffectOption) (Unsettled, error)` | `ctx.effects.write(path, content, opts?) => void` |
| `mkdir` | `ctx.effects.mkdir(path: str \| os.PathLike[str] \| Completed \| Response, ...) -> None` | `ctx.Effects().Mkdir(path any, opts ...EffectOption) (Unsettled, error)` | `ctx.effects.mkdir(path, opts?) => void` |
| `remove` | `ctx.effects.remove(path: str \| os.PathLike[str] \| Completed \| Response, ...) -> None` | `ctx.Effects().Remove(path any, opts ...EffectOption) (Unsettled, error)` | `ctx.effects.remove(path, opts?) => void` |
| `rename` | `ctx.effects.rename(src: str \| os.PathLike[str] \| Completed \| Response, dst: str \| os.PathLike[str] \| Completed \| Response, ...) -> None` | `ctx.Effects().Rename(src, dst any, opts ...EffectOption) (Unsettled, error)` | `ctx.effects.rename(src, dst, opts?) => void` |
| `chmod` | `ctx.effects.chmod(path: str \| os.PathLike[str] \| Completed \| Response, mode, ...) -> None` | `ctx.Effects().Chmod(path any, mode int, opts ...EffectOption) (Unsettled, error)` | `ctx.effects.chmod(path, mode, opts?) => void` |
| `http` | `ctx.effects.http(method, url: str \| os.PathLike[str] \| Completed \| Response, *, body=None, headers=None, check=True, ...) -> Response` | `ctx.Effects().HTTP(method string, url any, opts ...EffectOption) (Response, error)` | `ctx.effects.http(method, url, opts?) => Response` |
| `Spawned.wait` | `spawned.wait(*, check=True) -> Completed` | `spawned.Wait(opts ...EffectOption) (Completed, error)` | `spawned.wait(opts?) => Completed` |

TypeScript parameter and member names camelCase (`skipIfCurrent`, `exitCode`); the options object
carries every keyword-style parameter. Go's second result is the §2.5.4 error in every case.

Neither the Python nor the TypeScript column carries `| Unsettled`: both declare the settled types
only (§2.5.3), and their carrier-accepting parameter positions are typed as the unions of §2.5.5.
Python annotates exactly those six positions and leaves every other parameter unannotated -- the
annotations exist to pin the forwarding boundary, not to retype the whole surface. `url` is typed
`any` in Go and `str | os.PathLike[str] | Completed | Response` /
`string | Completed | Response` in Python and
TypeScript because it is one of the six carrier-accepting positions; `method` and `body` are not,
and keep their concrete types.

The eight Python signatures additionally end in `**_options`, which is the catch-all that raises
`errEffectOptionNotAccepted` (§2.5.2, §12.8). It is a message-parity mechanism, not a parameter:
reaching it is always an error.
`Spawned.wait` is listed for completeness -- it is not a ninth method on the handle (§2.2), it is
the one member `Spawned` exposes besides `pid`, and it never yields a carrier: reaching it at all
means the `Spawned` was settled, since calling `.wait()` on an unsettled `Spawned` is extraction
(§4.4) and truncates.

---

## 3. Dry mode and the would-do log

### 3.1 Trigger

Dry mode is entered when the framework-owned `--dry-run` flag (§7) is present. In dry mode:

- No *application* effect is executed. Every one is recorded in order.
- Mutating effects return `Unsettled` carriers (§4).
- Observes issued *before* the first recorded mutation execute for real and return real values.
- Observes issued *after* the first recorded mutation return `Unsettled` carriers with the
  `«stale: ...»` brand form.
- **Framework-blessed `CACHE_WRITE`s (§9.2) execute even in dry mode.** They are the sole
  exception to "nothing runs": a dry run still writes its schema dump and its test-coverage
  shards, because those are the framework's own bookkeeping and suppressing them would make
  `--dump-schema --dry-run` and coverage-instrumented dry runs silently lossy. They are recorded
  in the structured effect log (§14.3) with `recorded: false`, and they are never written to the
  would-do log.
- The framework writes the would-do log to **stdout** on **every** exit path out of the dispatch
  (§3.5), and exits with the handler's exit code.

`--dry-run` on a `read_only` command is accepted and never errors. Its would-do log is **always
just the header with an empty body**: a read-only command can only produce observes and
framework-blessed cache writes, and neither is ever logged (§3.2, §9.2). The header is still
emitted, so the output is honest about the mode the run was in.

> **Amendment (2026-08-13, machine-interface round): every "stdout" in §3 means human mode.**
> In machine mode (§19) the would-do log is not written to stdout as text at all: the same
> records, in the same order, from the same seam, are carried in the envelope's `preview` member
> (§19.3), and the envelope is the only document stdout receives (§19.1). The read-only rule above
> survives exactly: what is a header with an empty body in human mode is an empty `preview` array
> in machine mode, and it is emitted just as unconditionally. Outside machine mode every sentence
> in §3 is unchanged, and `--json --dry-run` is a legal combination (§19.1).

### 3.2 The log format

Header line, verbatim:

```
DRY RUN — no changes were made. Would do:
```

(The dash is U+2014 EM DASH.)

Then one line per recorded effect, in record order, each of the form:

```
  <N>. <verb>: <detail><grant suffix><conditional suffix>
```

- Two leading spaces.
- `<N>` is the 1-based sequence number, no zero padding.
- `. ` (period, single space) separates the number from the verb.
- `<verb>: ` (colon, single space) separates the verb from the detail.

**The numbering is CONTIGUOUS OVER RENDERED LINES, not over all records** (amended 2026-08-03,
D3). `<N>` counts only the effects this log renders; `CACHE_WRITE`s are never rendered (§9.2) and
therefore never consume a number. The same counter feeds the `«step N output»` brand (§4.2) and
truncation's "ends at step N" (§3.3), so any record that took a number without producing a line
would silently shift three user-visible strings at once -- a coverage-instrumented dry run would
start its preview at `2.` for no reason a reader could see. Cache writes carry their own
independent 1-based sequence, so the `seq` field of §14.2 is still present and still meaningful on
every record; the two sequences simply do not share a counter.

Verb prefixes, one per method:

| Verb | Method | Detail |
|------|--------|--------|
| `run:` | `run` (mutating) | the argv, shell-free, space-joined |
| `spawn:` | `spawn` | the argv, shell-free, space-joined |
| `write:` | `write` | `<path> (<n> bytes)`, or `<path> (<brand>)` when the content is an unsettled carrier |
| `mkdir:` | `mkdir` | the path |
| `remove:` | `remove` | the path |
| `rename:` | `rename` | `<from> -> <to>` |
| `chmod:` | `chmod` | `<path> <mode>` where mode is octal with a leading `0` (e.g. `0755`) |
| `net:` | `http` | `<METHOD> <url>` |

Observes (§6.2) are **not** logged -- the log is a list of what *would change*.

Grant suffix, appended when the effect used a grant:

```
 (granted: <name> — <reason>)
```

(Leading space, U+2014 EM DASH between name and reason.)

Conditional suffix, appended when the effect declared `skip_if_current`:

```
 [unless resource '<token>' already current]
```

(Leading space, single quotes around the token.) When both suffixes apply, the grant suffix
comes first, then the conditional suffix.

Carriers forwarded into an effect render inline in the detail, in their brand form (§4.2). That
includes `write`'s `content`, which is not an argv position: when the content is an **unsettled**
carrier the brand takes the byte count's place, parentheses and all --

```
  3. write: VERSION («step 2 output»)
```

-- because nothing produced those bytes and the framework will not invent a count. The same
effect's structured record carries `bytes: null` (§14.2). Literal content is unaffected and still
renders `(<n> bytes)`, and so is a forwarded result that is *settled* -- a pre-mutation observe's
`Completed` (§3.1) projects normally even in dry mode, and its encoded length is a real number.

Fully worked example:

```
DRY RUN — no changes were made. Would do:
  1. run: git tag v1.2.3
  2. run: git push origin v1.2.3 (granted: push — release engine owns remote refs)
  3. write: CHANGELOG.md (4213 bytes)
  4. net: POST https://api.github.com/repos/o/r/releases [unless resource 'gh-release:v1.2.3' already current]
  5. run: gh release view «step 4 output»
```

### 3.3 Truncation

Extraction or branching on a carrier ends the preview. The framework prints the already-recorded
log (header + lines 1..N-1) to stdout, then writes to **stderr**, verbatim:

```
error: dry-run preview ends at step N: <cmd> branched on unsettled value «step M output» — cannot preview past this point
```

- `N` is the sequence number the preview reached (the next effect that would have been recorded).
- `<cmd>` is the dotted command path (`release.run`, not the app name).
- `«step M output»` is the offending carrier's brand form, rendered verbatim (so a stale-observe
  carrier renders as `«stale: <descr>»` instead).
- The dash is U+2014 EM DASH.

Exit code is `1`. This is an honest failure, not a warning: the framework refuses to invent a
value it cannot know.

> **Amendment (2026-08-13, machine-interface round): in machine mode the truncation error is an
> envelope member, not a stderr line.** The stream split above is a **human-mode** promise and is
> narrowed to it, not withdrawn: it exists so a caller piping stdout gets the preview and nothing
> else, and in machine mode the envelope delivers that property more strongly -- the preview and
> the reason it stopped are two members of one parseable document, so a caller cannot get the
> first without the second. The envelope's `preview_error` carries
> `{"kind": "truncated", "step": N, "command": …, "brand": …, "message": …}` where `message` is
> byte-identical to the §12.5 text above, `error: ` prefix included (§19.3). Exit code stays `1`,
> the same records are still carried, and nothing about the human-mode rendering changes.

### 3.4 What `--quiet` does to the log

Nothing. The would-do log is dry mode's primary output and is never suppressed (§7.4).

> **Amendment (2026-08-13, machine-interface round): the same holds in machine mode, structurally.**
> The envelope is not written through the writers `--quiet` suppresses (§19.2), so `--json --quiet`
> emits the complete envelope, `preview` and `diagnostics` included. `--quiet` and `--verbose`
> govern the **human** stream only; they never decide what an envelope contains. This is the same promise
> §3.4 already made, restated over the other rendering.

### 3.5 Every exit path renders the log

**The log renders on every path that leaves a dry-mode dispatch, not only on the normal return**
(amended 2026-08-04, D7). The operator asked for a preview and the framework recorded one;
whether the handler returned, exited, or fell over does not change what it owes them. Silence is
the one answer the framework must never give, because it is indistinguishable from "this command
would do nothing".

The paths, and what each renders:

| Path | stdout | stderr | Exit status |
|------|--------|--------|-------------|
| Normal return | the log | -- | the handler's exit code |
| Deliberate exit (Python `sys.exit(n)`) | the log | -- | `n` |
| Carrier extraction (§3.3) | the log so far | the truncation error | `1` |
| Any other unwind (exception / panic) | the log so far | the §12.11 marker | unchanged: the exception continues |

Two rulings are folded into that table.

**A deliberate exit renders exactly what an equivalent return renders.** `sys.exit(1)` and
`return 1` are the same intent spelled two ways -- the handler is done and wants that status -- so
they produce byte-identical output, with no marker and nothing on stderr. The preview is complete
by construction: the handler is unwinding, and everything it recorded, it recorded.

**An unexpected unwind renders the log AND marks it.** The recorded effects are still owed --
withholding them would punish the reader for the handler's crash -- but the framework cannot know
what the handler had left to record, so the log is followed by the §12.11 marker on **stderr**.
That split is deliberate and matches §3.3 exactly: the log is stdout's, and the sentence that
qualifies it is stderr's, so a caller piping stdout gets the preview and nothing else. The
exception is **not** swallowed: it continues to propagate untouched, and the process's exit status
and its own error report are whatever the language would have produced anyway. The framework
annotates the crash; it does not handle it.

Note what this rules out: the render is owned by the one seam every dispatch passes through
(Python's four exception clauses around the handler call -- exhaustive because `BaseException` is
the root; Go's `runSealed`; TypeScript's `runHandler`). It is not a list of paths that each
remember to render, because that list is exactly what was incomplete before.

**The one exit path outside this guarantee** is a handler that terminates the process itself --
Go's `os.Exit`, TypeScript's `process.exit`. Nothing renders, because no framework code runs: Go
skips every deferred function and Node tears the process down. This is a ceiling, not a defect
(§17), and it is the reason Python's `sys.exit` is *in* the table above -- it raises a catchable
`SystemExit` rather than terminating, so the framework really can honour it, and it is the
idiomatic way a Python handler reports failure.

> **Amendment (2026-08-13, machine-interface round): the guarantee is unconditional; only the
> rendering follows the mode.** §3.5's promise -- silence is the one answer the framework must
> never give -- is **discharged, not contradicted**, by machine mode. In machine mode the table's
> `stdout` column reads "the envelope, whose `preview` carries the log" on every row and its
> `stderr` column reads "--", because the truncation error (§3.3) and the abort marker (§12.11)
> become `preview_error` members (§19.3). Exit statuses are unchanged, and an unexpected unwind
> still propagates untouched -- the envelope is written at the same seam, before the exception
> continues. The one exit path outside the guarantee (`os.Exit` / `process.exit`) is outside it in
> machine mode too, and for the identical reason.
>
> A second amendment applies to the same seam: a handler may **claim** the render
> (`ctx.effects.recorded()`, §19.7), after which the framework's own end-of-dispatch emission is
> suppressed and the handler's `render_log()` produces byte-identical bytes at a point of its
> choosing. A run that claimed but never rendered is re-rendered at this seam, so the guarantee
> survives the claim intact: claiming moves the render, it can never remove it.

---

## 4. Unsettled carriers

The type is named `Unsettled` in all three implementations.

### 4.1 When a carrier is produced

- Every mutating effect recorded in dry mode returns one.
- Every post-mutation observe in dry mode returns one.
- Nothing else ever produces an *unsettled* one. Outside dry mode, and for pre-mutation observes,
  callers get real values -- in Python and TypeScript literally so (`None` / `undefined` from the
  void methods). Neither language's *declared* types ever mention `Unsettled` (§2.5.3): there the
  carrier is a runtime phenomenon only, which is precisely what lets one handler body be written
  once and be correct in both modes.
- **Go's carrier-always model is the one carve-out, and it is a spelling, not a semantic.** Every
  Go effect method returns a carrier type in every mode (§2.5.3), so a Go caller in live mode
  holds a *settled* `Completed` / `Spawned` / `Response` whose extractors return the real values;
  the two conditions above are still exactly the conditions under which a Go carrier is
  **unsettled**. Go's payload-less void `Unsettled` is a third thing again: returned by the five
  path-mutating methods in both modes, never settled, never forwardable (§2.5.5), standing for
  nothing at all.

### 4.2 Brand forms

Two, and only two:

| Form | Produced by |
|------|-------------|
| `«step N output»` | the carrier returned by recorded mutation number `N` |
| `«stale: <descr>»` | the carrier returned by a post-mutation observe; `<descr>` is the observe's short description (for `run`, the space-joined argv) |

(The guillemets are U+00AB and U+00BB.)

`N` is the would-do number of §3.2 -- the rendered-line counter, which `CACHE_WRITE`s never
advance (D3). The brand a handler forwards therefore always names a line the reader can see in the
preview.

### 4.3 Legal use: forwarding

Passing a carrier as an argument to a later `ctx.effects` call is legal and is the whole point of
the regime -- it is how a data-flow preview stays complete. The effects API recognizes carriers
at its own boundary and substitutes the brand form when rendering the log line. Forwarding does
not consume or settle the carrier; the same carrier may be forwarded any number of times.

### 4.4 Illegal use: extraction and branching, and the runtime seal

Any other use is a hard error that truncates (§3.3). The seal is **mandatory in every
implementation** and is installed at every ctx-construction site (§15).

**Python -- poisoned dunders.** `Unsettled` defines the following dunders to raise the truncation
error:

```
__bool__  __eq__  __ne__  __lt__  __le__  __gt__  __ge__  __hash__
__len__  __iter__  __contains__  __getitem__  __getattr__  __setattr__
__int__  __float__  __index__  __str__  __format__  __bytes__
__add__  __radd__  __mod__  __rmod__  __call__
```

This list is **complete**: a dunder not on it and not exempted below is not poisoned.

**`__setattr__` is on the list, and the write side matters as much as the read side** (amended
2026-08-03, D6). Without it `u._brand = "«forged»"` mints a preview line that describes nothing
and `u._forwardable = True` makes a void carrier -- which stands for nothing in either mode
(§2.5.5) -- forwardable, defeating the pin that void results are never forwardable. `__slots__`
does not close this: slots make attributes *fixed*, not *read-only*. Go and TypeScript were never
exposed -- Go's carrier fields are unexported and TypeScript's Proxy already traps `set` -- so this
is a Python-only parity repair. `Unsettled.__init__` writes its own four slots through
`object.__setattr__`, which is the only way to construct a carrier whose write path is poisoned.

`__repr__` is the **single** non-poisoned dunder: it returns `Unsettled(«step 3 output»)` so that
debuggers, tracebacks and logging never themselves detonate. `__class__` is untouched
(`isinstance` must work -- the effects API uses it at the forwarding boundary).

**Go -- non-comparable struct with panicking extractors.**

```go
type Unsettled struct {
    _     [0]func() // makes the struct non-comparable: `u == v` is a compile error
    brand string
}
```

Exported extractors `String() string`, `Bytes() []byte`, `Int() int64`, `Bool() bool` all panic
with the truncation error. Unexported `brandForm() string` is what the effects API reads at the
forwarding boundary. Extractor-panic ergonomics are an accepted ceiling (Go has no way to make
extraction a compile error); do not re-litigate at implementation.

`Unsettled` is Go's **void** carrier: it never carries a value, so its extractors panic in both
modes. Go's three settleable carriers -- `Completed`, `Spawned`, `Response` (§2.5.3) -- are built
the same way (the `[0]func()` non-comparability field, the unexported `brandForm()`), differing
only in that their shape-specific extractors return real values when the carrier is settled and
panic with the same truncation error when it is not. Python and TypeScript need no settleable
variant: they return the real result object directly in live mode.

**TypeScript -- branded type plus runtime Proxy seal.** The static type is a nominal brand
(`declare const unsettledBrand: unique symbol`) so typed consumers get compile errors. The
runtime value is a `Proxy` whose `get`, `set`, `has`, `deleteProperty`, `apply` and
`ownKeys` traps throw the truncation error, with exactly three exemptions: the internal brand
symbol (read by the effects API), `Symbol.toStringTag`, and `util.inspect.custom` /
`Symbol.for("nodejs.util.inspect.custom")` (returns the brand form, so Node's console does not
detonate). `valueOf`, `toString` and `Symbol.toPrimitive` are **not** exempt -- they throw.

Accepted TS ceiling: plain-JS truthiness (`if (x)`) and `===` cannot be trapped by a Proxy.
Those two gaps are lint-visible only (§11) and are recorded, not fixed.

---

## 5. Resource tokens and conditional annotations

### 5.1 Tokens

A resource token is **declared metadata**: a plain string naming what an effect touches. The
framework:

- compares tokens by **string equality only** -- no normalization, no case folding, no path
  canonicalization, no prefix matching;
- attaches no meaning to a token's shape; `remote:origin/main` and `gh-release:v1.2.3` are just
  strings that happen to read well;
- never invents a token. An effect without `resource=` simply has none;
- **never acts on a token.** A token does not gate, skip, order or deduplicate anything.

A token's only consumers are the would-do log's conditional suffix (§5.2), the structured effect
record's `resource` field (§14.2, hence `effects_equals` assertions), and any renderer a consumer
builds on top of that record. Declared on any effect as `resource=<token>`.

### 5.2 Conditional annotations (`skip_if_current`)

`skip_if_current=<token>` is a **preview annotation and nothing else.**

- **Dry mode** -- the effect is recorded like any other, and its log line carries the conditional
  suffix `[unless resource '<token>' already current]` (§3.2). The suffix is documentation for the
  human reading the preview: "the handler will skip this step if that resource is already
  current".
- **Real mode** -- the effect **executes unconditionally**. The declaration is inert.

There is **no current set**, no currency evaluation, no per-run resource tracking, and no
framework state of any kind behind this feature. The framework never decides whether a resource is
current; deciding that would mean evaluating a user predicate, which §0 forbids.

An effect may declare both `resource=` and `skip_if_current=`, and they may name the same token
(a self-documenting idempotent step).

**Where real-mode idempotency lives: in the handler.** The supported idiom is to branch on an
**allowlisted observe** (§6.2):

```
head = ctx.effects.run(["git", "rev-parse", "HEAD"], check=False)   # observe: real value
if head.exit_code == 0 and head.stdout == want:
    return 0                                                        # already current
ctx.effects.run(["git", "push", "origin", "main"],
                resource="remote:origin/main",
                skip_if_current="remote:origin/main")
```

This previews correctly because an observe issued *before* the first recorded mutation really
executes and returns a **real value even in dry mode** (§3.1). Branching on it is branching on a
real value, not on a carrier, so the preview walks straight through the `if` and records the
mutation with its conditional suffix. Only observes issued *after* a mutation has been recorded
yield carriers, and branching on those truncates (§3.3) -- correctly, because their result is
genuinely unknowable.

The declaration and the handler's guard are deliberately independent: the framework does not
verify that they agree, and cannot. `skip_if_current=` makes the handler's intent visible in the
preview; it does not implement it.

---

## 6. Grants and observe authorization

### 6.1 Grants

Declared per-command:

```
grants=[Grant(name, reason, kind)]
```

| Field | Type | Rules |
|-------|------|-------|
| `name` | string | matches `[a-z][a-z0-9-]*`; unique within the command |
| `reason` | string | non-empty; rendered verbatim in the log's grant suffix |
| `kind` | effect kind | one of `PROC_MUTATE`, `PROC_SPAWN`, `FILE_WRITE`, `NET_MUTATE` |

Per-language spelling: Python `grants=[Grant("push", "release engine owns remote refs",
PROC_MUTATE)]` on the command registration; Go `WithGrants(Grant{Name: ..., Reason: ...,
Kind: ...})` as a `CmdOption`; TypeScript `grants: [{ name, reason, kind }]` in the factory
options object.

An effect passing `grant="push"` must name a grant declared on the running command whose `kind`
matches the effect's kind -- mismatch or unknown name is a hard error at call time (§12.4). A
grant is not permission to do something otherwise forbidden; it is a *labelled* reason that
surfaces in the preview so that a reviewer reading a dry run sees why a dangerous step is there.
Grants are emitted in the schema (§13).

**A grant on an observe is a hard error at call time** (`errEffectGrantOnObserve`, §12.4). A grant
exists to label real work in the preview, and an observe produces no preview line at all -- it
already executed (§6.2), it is never recorded, and it is never logged (§3.2). There is nothing for
the label to appear on, so the declaration cannot mean anything, and declare-everything makes a
meaningless declaration an error rather than a silently-dropped no-op. Like the read-only
enforcement of §9.1 this is decided by the argv at the call, not at registration: a `run` that
matches an allowlist prefix *and* passes `grant=` fails, whatever the command's classification.

### 6.2 `proc_observe_allowlist`

App-level, not command-level:

```
proc_observe_allowlist=[["git", "status"], ["git", "rev-parse"], ["gh", "release", "view"]]
```

Each entry is an **argv prefix**: a list of strings matched element-wise against the leading
elements of the effect's argv, by string equality. A `ctx.effects.run(argv, ...)` whose argv
matches any listed prefix is an **observe**: it executes even in dry mode, returns a real value
(or an `Unsettled` `«stale: ...»` carrier if a mutation has already been recorded), and is not
written to the would-do log.

A `run` whose argv does not match any prefix is a `PROC_MUTATE`. In a `read_only` command,
issuing a non-matching `run` is a hard error (§12.4). Passing `grant=` on a *matching* `run` --
i.e. on an observe -- is likewise a hard error at call time (§6.1, §12.4).

Per-language spelling: Python `App(proc_observe_allowlist=[...])`; Go
`WithProcObserveAllowlist([][]string{...})` as an `AppOption`; TypeScript
`createApp({ procObserveAllowlist: [...] })`. Emitted in the schema (§13).

#### The breadth hazard (amended 2026-08-03, D4)

A prefix is matched element-wise, so **a short prefix is a near-blanket exemption for that
binary.** `proc_observe_allowlist=[["git"]]` makes *every* `git` invocation an observe -- including
`git push`, `git reset --hard` and `git clean -fdx`. Concretely, for every argv that matches:

- it **executes for real under `--dry-run`**, because observes are exactly the operations dry mode
  still performs (§3.1);
- it is **never written to the would-do log**, because the log lists what would change (§3.2), and
  an observe is declared not to;
- it is **legal inside a `read_only` command**, because read-only enforcement admits an
  allowlisted `run` (§9.1).

The framework guards only the **empty** prefix, which would match everything and is a registration
error. It does **not** infer a minimum specificity, and must not: §0's zero-inference rule owns
this. The allowlist is a **declared, source-visible, app-level choice**, and declaring it *is* the
authorization -- the app is stating that these argv prefixes change nothing and may really run
during a preview. A framework that silently narrowed, reordered or rejected a declared prefix
would be inventing policy the app did not write.

What the framework does instead is **say so out loud, at warn severity**: the built-in
`observe-allowlist-breadth` check (§11) warns for every single-token prefix. It is a warning and
not an error precisely because a one-token prefix can be correct -- an app whose only use of a
binary is genuinely read-only has nothing to fix -- and `--ignore-warnings` clears it. There is no
mechanism behind the warning: no specificity rule, no per-subcommand table, no runtime narrowing.

---

## 7. The reserved flag quartet

### 7.1 The four names

`dry-run`, `approve-consequential`, `quiet`, `verbose`. They join the existing reserved set
(`help`, `h`, `version`, `v`, `dump-schema`, `mcp`, `config`, `hermetic`) in all three
implementations:

- Python `_RESERVED_GLOBAL_FLAG_NAMES`
- Go `reservedGlobalFlagNames` (`go/strictcli/context.go`)
- TypeScript `RESERVED_GLOBAL_FLAG_NAMES` (`typescript/src/app.ts`)

The ban is **unconditional** and applies at every level -- command flags, flag-set flags,
mutex-group flags and app global flags -- not only to global flags. `--output` is explicitly
**not** reserved and stays available to apps.

The four flags have **no short forms**. Short-flag names are unaffected by this ban.
Positional arg names are unaffected (an arg has no `--` spelling).

> **Amendment (2026-08-13, machine-interface round): `json` joins the reserved set on the same
> unconditional tier.** The framework owns `--json` (machine mode, §19). Its ban is the
> **unconditional every-level** one described above -- command flags, flag-set flags, mutex-group
> flags and app globals -- not the global-only tier, so a consumer's command-local `--json` is a
> registration-time error exactly as a command-local `--dry-run` is. It shares §7.2's delivery
> rules verbatim: extracted by the pre-scan, stripped from argv before command parsing, recognized
> anywhere in argv with the same two boundaries (a bare `--`, a passthrough command's name),
> repetition and mixed positions a union, no short form ever.
>
> **The quartet stays a quartet.** `--json` is not a fifth member: the four are the effects
> regime's own flags and are named as a set throughout this document and across the fleet's
> documentation. `--json` is reserved *beside* them and specified in §19, which is where its
> semantics live. The only thing this amendment changes in §7 is the membership of the reserved
> *name* lists (Python `_RESERVED_GLOBAL_FLAG_NAMES`, Go `reservedGlobalFlagNames`, TypeScript
> `RESERVED_GLOBAL_FLAG_NAMES`) and the pre-scan's two-region table (§7.2), where `json` reads
> exactly as the quartet does in both regions. Its Context accessor follows the quartet's shape:
> `ctx.json` / `ctx.JSON()` / `ctx.json`.

#### `approve-consequential` replaced `yes` (amended 2026-08-04, §18.7)

The skip flag was `--yes`. It is now `--approve-consequential`, and **its unwieldiness is the
point**: `--yes` is three keystrokes and a word every shell user already types reflexively, so it
was destined to become muscle memory and to be appended to every invocation without a thought. A
flag that cannot become muscle memory stays a decision. There is no short form, and there will
never be one.

**`yes` stays on the banned-names list.** It owns no framework flag any more, so it could have been
released back to consumers -- and that is exactly why it is kept banned: a consumer's private
`--yes` would restate `--approve-consequential` in the very spelling this rename removed, and the
framework would have no way to tell the two apart at the call site. The ban is a separate template
from the quartet's, and it names the replacement (`errFlagNameYesBanned`, §12.1).

### 7.2 Delivery

The four flags are extracted by the pre-scan that already handles `--dump-schema`, `--mcp`,
`--config` and `--hermetic` (Python `App._pre_scan_reserved_flags`; Go's equivalent in
`strictcli.go`; TypeScript's in `parse.ts`), and are **removed from argv** before command
parsing.

Their values are delivered **on the Context, never as handler kwargs**:

| Impl | Accessors |
|------|-----------|
| Python | `ctx.dry_run`, `ctx.approve_consequential`, `ctx.quiet`, `ctx.verbose` (read-only properties) |
| Go | `ctx.DryRun()`, `ctx.ApproveConsequential()`, `ctx.Quiet()`, `ctx.Verbose()` |
| TypeScript | `ctx.dryRun`, `ctx.approveConsequential`, `ctx.quiet`, `ctx.verbose` (getters) |

Kwargs delivery is forbidden: injecting four mandatory parameters into every handler would
contradict guard v2 (§10), which is simultaneously *tightening* signature validation, and would
break every handler in the fleet for no benefit. `Context` must carry `quiet`/`verbose` anyway
(they gate its own output methods) and must carry `dry_run` anyway (it gates `ctx.effects`), so
the Context is the only coherent home.

#### The quartet is recognized ANYWHERE in argv (amended 2026-08-04, adoption ruling A1)

The draft pinned the quartet to the **pre-command region only** -- the pre-scan stopped at the
first non-flag token, so `app --dry-run cmd` worked and `app cmd --dry-run` was
`error: unknown flag '--dry-run'`. Python's recorded interpretation mirrored that to Go and TS and
the conformance cases asserted it. **Adoption falsified it.** Every documented invocation in this
ecosystem writes these flags *after* the command name, and the first consumer to migrate had to
rewrite argv before handing it to the framework -- a workaround that would have had to ship to
every consumer in the fleet. Where adoption contradicts the draft, adoption wins.

The precedent was already in the framework: **`--help` / `-h` is recognized anywhere in argv**,
not only at token boundaries. The quartet now behaves the same way. Semantically this is the
correct shape and the draft had it backwards: `--dry-run`'s applicability is *per-command* (a
`mutating` command accepts it, §3.1; a `read_only` command accepts it with an empty would-do body),
so requiring it before the command name asked the user to declare a per-command fact before naming
the command.

Everything else about §7.2 is unchanged, and the pre-scan now has two regions with two rulesets:

| Region | What it recognizes |
|--------|--------------------|
| pre-command (before the first non-flag token) | every reserved flag: `--dump-schema`, `--mcp`, `--config`, `--hermetic` **and** the quartet. Known global flags and their values are skipped so a global-flag value that looks like a command name does not end the region early. |
| command region | the **quartet only**. `--hermetic`, `--config`, `--dump-schema` and `--mcp` stay pre-command-only and remain unknown-flag errors after the command token. |

The quartet is still stripped from argv before command parsing; delivery is still on the Context
and never as handler kwargs; per-command applicability is unchanged (§3.1, §12.4 fire identically
whether `--dry-run` appeared before or after the command name). Repetition and mixing positions
are a union, not an error: `app --dry-run cmd --verbose` sets both.

The command-region scan stops for good at exactly two boundaries:

- **a bare `--`.** Every token after it is positional data, never a reserved flag.
  `app cmd -- --dry-run` passes the literal string `--dry-run` to the command. This matches
  `--help`, which is likewise not recognized after `--`.
- **a passthrough command's name** (§7.2.1).

The scan walks routing tokens through the group/command tree, so a quartet token may sit anywhere
among them: `app grp sub --dry-run` and `app grp --dry-run sub` both work. The walk never raises --
unknown, deprecated and mis-nested command tokens are the real parse's business, and the pre-scan
simply stops routing and keeps scanning for quartet tokens.

The one cost is the one `--help` already pays: a flag *value* spelled exactly like a quartet token
is eaten. `app cmd --message --dry-run` sets dry mode and leaves `--message` without a value.
`--message=--dry-run` and `--` both express the literal. This is the pinned, accepted cost of
anywhere-recognition, and it is not new machinery -- it is the identical hazard on the identical
scan shape.

#### 7.2.1 Passthrough args stay opaque

A **passthrough** command's args are the exception. When the routing walk resolves a passthrough
command, the scan stops at that command's token and every token after it is forwarded to the
handler byte-for-byte:

```
app exec --verbose child    ->  args = ["--verbose", "child"], ctx.verbose == false
app --verbose exec --verbose child  ->  args = ["--verbose", "child"], ctx.verbose == true
```

This is not an inconsistency with anywhere-recognition; it is what a passthrough *is* (§1.2: all
tokens after the command name are forwarded raw, bypassing parsing). Eating a passthrough's
`--verbose` would silently change what the child process does *and* strip the flag from the child's
argv -- a lossy, invisible corruption of another program's input. A framework that cannot see what
the child does must not edit what the child receives.

The **pre-command position is the escape hatch** and it is lossless: `app --verbose exec ...` sets
`ctx.verbose` for the passthrough's own dispatch while leaving the child's identically-spelled
argument untouched. Nothing is unreachable.

`--help` is deliberately *not* being brought into line here: it is intercepted for a passthrough
today, that behavior is pinned elsewhere and separately, and printing help is visible and harmless
where silently rewriting a child's argv is neither.

### 7.3 `--approve-consequential`

Consumed entirely by the framework's confirm protocol (§8). Exposed on the Context for symmetry
and for apps that want to propagate it to a child process; handlers are not expected to read it.

### 7.4 `--quiet` / `--verbose` gating semantics

Today `ctx.debug` writes unconditionally in all three implementations (Python `Context.debug`,
Go `(*Context).Debug` -- which carries the `// Future: will be gated by a verbose flag.` comment
this section discharges -- and TypeScript `Context.debug`). The pair now gates them:

| | `ctx.debug` | `ctx.info` | `ctx.warn` | `ctx.error` |
|---|---|---|---|---|
| default (neither flag) | hidden | shown | shown | shown |
| `--verbose` | shown | shown | shown | shown |
| `--quiet` | hidden | hidden | shown | shown |
| `--quiet --verbose` | hidden | hidden | shown | shown |

`--quiet` **dominates** `--verbose`. Passing both is not an error and produces no warning; quiet
simply wins. There is no mutex registration between them.

Never suppressed by `--quiet`, at any level:

- ~~structured handler data (the JSON that `outcome(data=...)` / `ExitData` prints to stdout);~~
  **amended 2026-08-13 -- see the box below;**
- the would-do log (§3.2) and the truncation error (§3.3);
- framework parse errors, registration errors and the confirm prompt;
- `ctx.warn` and `ctx.error`.

> **Amendment (2026-08-13, machine-interface round): the handler-data item is replaced by the
> envelope's structural exemption.** The channel the struck bullet protected -- `outcome(data=...)`
> / `ExitData(code, data)` printing bare JSON to stdout -- is **deleted** (§19.4). It had zero
> consumers in the fleet, and it was one half of a collision the framework had with itself: a
> command using it under `--dry-run` emitted the would-do log and a bare JSON document on the same
> stream, producing unparseable stdout with no consumer involved. Handlers now supply the machine
> payload through the dedicated payload API, which carries the declared schema binding (§19.4,
> §19.5), and the payload is emitted **only** as the envelope's `payload` member in machine mode.
>
> The never-suppressed promise is not weakened by the deletion, it is strengthened: the envelope
> is **structurally exempt** from quiet. It is not written through the writers `--quiet` suppresses,
> so `--quiet` has no mechanism by which to reach it, and `--json --quiet` emits the complete
> document -- `payload`, `preview` and `diagnostics` alike. This closes a live divergence the old
> wording could not: one implementation routed its machine output through the quiet-suppressible
> writer and emitted nothing whatsoever under quiet plus machine flags, while the other two printed
> the data.
>
> The table above is otherwise untouched. `--quiet` / `--verbose` govern the **human** stream and
> nothing else; they never decide the content of an envelope, and a diagnostic hidden from the
> terminal still appears in `diagnostics` with its level (§19.2).

### 7.5 Check-command subsumption

The auto-registered `check` command currently declares its own `--verbose` and its own
`--dry-run` among its eight flags (Python `App._register_check_command`, Go
`go/strictcli/check_cmd.go`, TypeScript `typescript/src/checks/cmd.ts`). Both names are now
banned, so both local flags are **dropped from the candidate list** and the check command reads
the framework-delivered values off the Context instead:

- `verbose` -> `ctx.verbose` (or `ctx.Verbose()`); behavior unchanged (per-check notes, durations,
  the trailing count summary).
- `dry_run` -> `ctx.dry_run` (or `ctx.DryRun()`); the handler's own behavior was, at the time this
  section was written, unchanged (list which checks would run without executing them). **Amended
  2026-08-12 — see the box below.**

> **Amendment (2026-08-12): `check --dry-run` runs the pure partition.** The list-without-running
> behavior above is retired. The check command's `--dry-run` no longer has a branch of its own: it
> selects the purity partition the programmatic surface already had (`run_checks(pure_only=True)` /
> `RunChecksOptions.PureOnly` / `runChecks(pureOnly)`), so the checks declared **pure and free of
> network** really execute and their results are printed exactly as in a full run, and only the
> impure remainder (plus any check whose dependency was listed) is rendered as the would-run plan
> under the unchanged `Would run N check(s):` header — printed even when the remainder is empty,
> the same way the would-do log prints its header with an empty body. Consequences: the exit code
> is now the executed partition's exit code (a rehearsal that finds a real failure fails), a check
> context is required for `--dry-run` as it is for a run, and the no-match and help branches run
> before the partition in all three implementations (Go previously printed `Would run 0 checks:`
> for both). Nothing outside the check command changes, and the framework's own would-do header
> still follows the handler's output.

`check --dry-run` is **not** behaviorally unchanged overall, though, and implementors must not
assume it is: `--dry-run` is now the framework flag, so passing it puts the whole run in dry mode
(§3.1). The observable difference is that after the handler's own output, the framework emits
the would-do log to stdout -- for `check`, which is `read_only`, that is the header line
`DRY RUN — no changes were made. Would do:` with an **empty body** (§3.1's read-only rule; the
check command's cache writes are `CACHE_WRITE`s and are never logged). Exit code is unchanged.
Any conformance case or consumer test asserting `check --dry-run` stdout must be updated for the
trailing header.

The remaining six check flags (`all`, `tag`, `name`, `list`, `json`, `ignore-warnings`) are
unaffected. The `check` command classifies as `read_only` (§9.2 covers its coverage-shard
writes).

The mechanism already exists in two of the three implementations: Python and TypeScript filter
their candidate check flags against the app's global flag names before registering. Go registers
its eight flags unconditionally and **must gain the same filter** -- otherwise the two dropped
names reappear as command flags and collide with the framework pre-scan.

`check --dry-run` subsumption is a forced consequence of the unconditional name ban, not a new
ruling: two flags cannot share a spelling.

---

## 8. The confirm protocol

Rewritten 2026-08-04 at the consequence round (§18.7). The regime originally **inferred** the
prompt from classification -- `mutating` ⇒ must confirm -- and that inference is now deleted.
The framework prompts for commands that **declare themselves consequential**, and for no others.

### 8.1 The declaration, and why classification could not be it

Every command may declare:

```
consequential = true
```

| Impl | Spelling |
|------|----------|
| Python | `consequential=True` keyword on `app.command(...)` / `group.command(...)`, beside `effect=`; the `Command` dataclass carries `consequential: bool = False` |
| Go | `WithConsequential()` -- a `CmdOption`, registered in `go/strictcli/strictcli.go` beside `WithEffect`; the `Command` struct carries `Consequential bool` |
| TypeScript | `consequential: true` on the twin-factory options object (`ReadOnlyCommandSpec`, `MutatingCommandSpec`, and both passthrough specs); `CommandDef` and `PassthroughDef` carry `readonly consequential: boolean` |

Unlike classification (§1.1) it is **not mandatory**. There is no `errCommandConsequentialMissing`,
and absence means "not consequential" -- the default is false in all three. Classification is
mandatory because the framework cannot act correctly without it (dry mode does not know whether to
record or execute); consequence is a human judgement about a small minority of commands, and making
it mandatory would force every registration to answer it, which is how a declaration becomes a
reflex.

**Declaring it on a `read_only` command is a registration-time hard error**
(`errCommandReadOnlyConsequential`, §12.2). A command that changes nothing has no effects to weigh.
`consequential` therefore implies `mutating`, and the confirm gate needs to read only the one field.

**The name is deliberately not the framework's reaction.** It is not `confirm`, not `prompt`, not
`requires_approval`. It states a property of the COMMAND -- *these effects are consequential* --
which is a fact the command's author knows and the framework never could. Today exactly one
behaviour hangs off it (the prompt); naming it after that behaviour would have welded the
declaration to one reaction and made every later use of the same fact a second, redundant
declaration.

#### Why the inference was wrong

The shipped regime inferred "mutating ⇒ must confirm". Adoption across six consumers falsified it:

- **391 of 624 commands (63%) classify `mutating`.** Two thirds of every CLI in the fleet prompted.
- The commands caught included `safegit commit`, `rlsbl changelog add`, `selfdoc gen`,
  `saferm delete` -- the *safe*, undoable deletion tool -- and `claudewheel launch`, which had to be
  special-cased or every session would have opened with a `Proceed? [y/N]`.
- The genuinely dangerous commands are roughly 5-10% of that set: a **~1:10 signal-to-noise ratio.**

A guardrail at 1:10 guarantees the skip flag is passed reflexively, and the guardrail becomes dead
code while still appearing present -- which is worse than not having it, because the appearance is
what a reviewer sees.

The diagnosis is that **one field was answering two questions**:

| Question | Answered by | Almost everything answers |
|----------|-------------|---------------------------|
| Should a dry run *record* this rather than execute it? | `effect` (§1.1) | yes -- correctly, and this is working and unchanged |
| Are these effects worth *interrupting someone* for? | `consequential` (§8.1) | no |

`effect` answers the first well and is not touched by this round. It never answered the second; it
was only ever a proxy for it, and the proxy is off by an order of magnitude.

### 8.1.1 When it fires

Before dispatching a command whose `consequential` is true, when **all** of the following hold:

- the dispatch path is the real CLI (`App.run` / `App.Run` / `App.run()`);
- `--dry-run` was not passed;
- `--approve-consequential` was not passed.

A plain `mutating` command **never prompts**. It never fires for `read_only` commands (which cannot
be consequential at all), or on the `test()` / `call()` / `_invoke` / MCP paths (§8.4).

**Passthrough commands are not exempt.** A passthrough declares `consequential` like any other
command (§1.2); a consequential passthrough prompts exactly like any other consequential command,
`--approve-consequential` skips the prompt exactly as elsewhere, and a passthrough that does not
declare it never prompts. That the passthrough's args are opaque to the framework is a reason to
confirm, not a reason to skip: the framework knows less about what is about to happen, not more.
The prompt names the passthrough's dotted command path like any other.

**The `interactive=True` confirm suppression is walked back** (§18.7, item 89). An earlier ruling
carved out `interactive` commands from the confirm protocol so that a command whose whole purpose
is to talk to the user did not open with an unrelated prompt. That carve-out is unnecessary under
the declaration: `claudewheel launch` is `mutating` and not consequential, so it simply never
prompts, with no exemption anywhere. `interactive`'s other, unrelated meaning -- visible in help,
excluded from tool export (§13, the MCP surface) -- is untouched. No suppression logic keyed on
`interactive` exists in any of the three implementations and none is to be added.

### 8.2 The prompt

Written to **stderr**, without a trailing newline:

```
about to run consequential command '<name>'. Proceed? [y/N] 
```

(Note the single trailing space. `<name>` is the dotted command path.)

The answer is read from stdin, one line. The line terminator is stripped as **exactly one `\n`,
then exactly one `\r`** -- never more of either, and never any other whitespace. After that,
exactly `y` or `Y` proceeds. Anything else -- including empty input, `yes`, `n`, `  y`, or EOF --
declines. On decline the framework writes `aborted` to stderr and exits `1`.

**The carriage return is pinned, and it is stripped** (amended 2026-08-03, D2). A human at a
Windows console types the same `y` as everyone else; their terminal terminates the line CRLF, and
a stdin stream that does not translate newlines hands the framework `"y\r\n"`. Declining there
would refuse an answer that was plainly given, so the framework accepts it. Stripping only the
terminator -- rather than `strip()`ing whitespace -- is what keeps `"  y"` a decline, which this
section requires. Go already did this (`strings.TrimSuffix(..., "\r")`); Python and TypeScript
now do too, and Python's previous `rstrip("\n")` (which stripped *every* trailing newline) is
replaced by the exactly-one rule.

### 8.3 Non-interactive stdin

If stdin is not a TTY, the framework does not prompt. It writes to stderr:

```
error: stdin is not interactive; pass --approve-consequential to confirm
```

and exits `1`. TTY detection is net-new in all three implementations (no `isatty` /
`IsTerminal` / `isTTY` call exists anywhere in the current sources): Python `sys.stdin.isatty()`,
Go a `golang.org/x/term`-free `os.Stdin.Stat()` mode check (Go stays zero-dependency), TypeScript
`process.stdin.isTTY === true`.

**Go excludes the null device explicitly** (amended 2026-08-04, §18.7 item 90). The draft pinned
Go's check to `fi.Mode() & os.ModeCharDevice != 0` alone, and `/dev/null` *is* a character device.
`myapp cmd < /dev/null` -- and every subprocess launched with a null stdin, which is what CI
runners and test harnesses do -- therefore read as **interactive** on Go and non-interactive on the
other two: the same invocation prompted in one implementation and hard-errored in the other two.
Go now additionally rejects a stdin that `os.SameFile`s `os.DevNull`, which is stdlib-only and
portable (the constant is `NUL` on Windows), so the zero-dependency property is preserved. The
residual gap -- another character device such as `/dev/zero` used as stdin still reads as
interactive on Go -- is pathological and is left as an accepted ceiling.

### 8.4 Programmatic dispatch

No programmatic path ever prompts and none emits the non-TTY error: these paths have no TTY
contract, and a prompt there would hang the caller. What they do about the requirement itself
splits in two (amended 2026-08-11, item 93):

- **`test()` / `Test()`** behaves as if `--approve-consequential` were passed. It takes argv, so a
  caller that wants the flag's semantics writes the flag.
- **`call()` / `Call()` / `invoke` / `invokeApp`, and the MCP server** take the consent from the
  call instead (§8.5). A consequential command reached without it is refused.

### 8.5 Consent on the non-CLI channels

Requiring confirmation is a property of the **command**, so every channel honours it. A command
that requires confirmation is still exported as a tool -- hiding it would remove the capability
rather than decline it -- but a caller must supply consent explicitly in the call and is refused
without it. This does not produce human approval and is not meant to: it makes the caller **state**
that it is proceeding without a human, in the call, where it can be recorded, instead of the
framework deciding that silently on everyone's behalf.

**Publication.** Every tool descriptor and every tool listing carries the classification beside the
descriptor's other fields, never inside the argument schema -- it describes the tool, not one of
its arguments. The field vocabulary is the schema dump's (§13): `effect` always, `consequential`
only when true.

| Surface | Where |
|---------|-------|
| `as_tools()` / `AsTools()` / `asTools()` | `Tool.effect` and `Tool.consequential` on the descriptor |
| MCP `tools/list` | `effect` and `consequential` keys beside `name`, `description`, `inputSchema` |

The router tool classifies `mutating` and is **not** consequential: the routed command's own
requirement is checked when the call reaches it, and the router forwards the caller's consent
unchanged. Marking the router consequential would demand consent for routing to a `read_only`
command, which confirms nothing.

**The consent argument**, spelled per-language because the call signatures differ. Behaviour is
identical; only the spelling is idiomatic:

| Implementation | Spelling |
|----------------|----------|
| Python | `app.call(path, approve_consequential=True, **kwargs)` -- keyword-only, and safe from collision because the name is framework-reserved so no command can declare it. `acall` and `Tool.execute` take the same keyword. |
| Go | `app.Call(path, kwargs, strictcli.WithApproveConsequential())` -- a variadic `CallOption`. Go's kwargs are a map, so consent cannot ride in them; the variadic option is this package's existing shape for a declaration that is not data. `Tool.Execute` takes the same variadic. |
| TypeScript | `app.call(path, kwargs, { approveConsequential: true })` -- a trailing options object (`CallOptions`). `Tool.execute` takes the same. |

**MCP** expresses consent as a top-level `tools/call` param, a sibling of `name` and `arguments`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"release","arguments":{},"approve_consequential":true}}
```

It is deliberately **not** a member of `arguments`. That object is the command's own argument
namespace, published with `additionalProperties: false`; a reserved name appearing there is an
unknown parameter and is reported as one, never promoted to consent. There is no server-side
default: absent means "not consented". A non-boolean value is a `-32602` protocol error
(`parameter 'approve_consequential' must be a boolean`); a refusal is ordinary `isError` tool-result
content, like any other invocation failure.

**The refusal**, byte-identical in all three implementations:

```
command '<path>' is consequential: pass approve_consequential to confirm
```

**Consent reaches the handler.** When it is given, `ctx.approve_consequential` /
`ctx.ApproveConsequential()` / `ctx.approveConsequential` reports `true` on the programmatic path,
exactly as it does when the CLI flag was passed -- so a handler or an audit record can see how the
run was consented to.

**Unaffected:** `read_only` and plain `mutating` commands. Consent is only ever demanded by the
`consequential` declaration.

**`--dry-run` reachability splits along the argv boundary, not the dispatch boundary** (amended
2026-08-03, D1; the previous text said `--dry-run` was unreachable through all of them "because
they bypass argv parsing entirely", which is false for `test()`):

| Path | Takes argv? | `--dry-run` reachable? |
|------|-------------|------------------------|
| `test()` / `Test()` / `app.test()` | yes -- it parses argv exactly as the CLI does | **yes**; `app.test(["--dry-run", ...])` enters dry mode, and the unit suites rely on it |
| `call()` / `Call()` / `_invoke` / `invokeApp` | no -- pre-typed kwargs | no |
| the MCP server | no -- it reaches dispatch through `call`/`invoke` | no |

Only the three argv-bypassing paths in the second and third rows cannot express the flag: there is
no argv for it to appear in. A programmatic caller on one of those paths that wants a preview
constructs the run through `test()` or through the CLI.

---

## 9. Read-only enforcement and the `CACHE_WRITE` exemption

### 9.1 Enforcement

In a command classified `read_only`, at effect-call time:

- `write`, `mkdir`, `remove`, `rename`, `chmod`, `http`, `spawn` -- hard error (§12.4).
- `run` -- allowed only when the argv matches a `proc_observe_allowlist` prefix (§6.2);
  otherwise hard error.

Enforcement is at **call time**, not registration time -- classification is static, the argv is
not.

### 9.2 `CACHE_WRITE`

The framework itself writes to disk during operations that are conceptually read-only. Those
writes are the `CACHE_WRITE` kind. `CACHE_WRITE`:

- has **no public method** on the effects handle and is unreachable from application code;
- never appears in the would-do log;
- never trips read-only enforcement;
- **executes even in dry mode** (§3.1), carrying `recorded: false`;
- is emitted in the structured effect log (§14.3) so conformance can assert its presence.

The closed list of framework-blessed cache writes -- exactly these three, nothing else:

| Site | Path | Source |
|------|------|--------|
| Schema dump | `.strictcli/schema.json` | Python `_write_schema`; Go and TS equivalents in their `schema` modules |
| Test-coverage shards | `.strictcli/coverage/<pid>.jsonl` | Python `App._record_coverage`; TS `recordCoverage` (`typescript/src/checks/coverage.ts`); Go equivalent |
| Test-coverage manifest | `.strictcli/test-coverage.json` | the merge step of the same subsystem |

Everything else the framework writes is an ordinary mutation of a `mutating` command, not a cache
write. Specifically, the five auto-registered `config` subcommands classify as:

| Subcommand | Classification |
|------------|----------------|
| `config show` | `read_only` |
| `config path` | `read_only` |
| `config set` | `mutating` |
| `config init` | `mutating` |
| `config edit` | `mutating` (already `interactive=True`) |

**None of the five declares `consequential`** (§8.1). Rewriting a config file and opening an editor
are reversible, routine operations; a framework that prompted on its own `config set` would be the
first and loudest demonstration of the 1:10 problem the declaration exists to fix.

Those five, and the `check` command, are the framework-internal commands of §10.4; their
classification only becomes enforceable once the `config` group's direct-`Command`-construction
bypass is closed, which §10.4 requires.

**Classifying the three mutating `config` subcommands is not enough: their mutations must ride
`ctx.effects`** (amended 2026-08-03, A4). Classification alone put
the run in dry mode, but the handlers wrote through bare `open` / `os.WriteFile` / `writeFileSync`
and launched `$EDITOR` through bare `subprocess.run` / `exec.Command` / `spawnSync`, so a dry run
printed `DRY RUN — no changes were made.` while rewriting the user's config file and opening their
editor. Every mutation in all three is now minted on the handle:

| Subcommand | Effects it mints |
|------------|------------------|
| `config set` | `mkdir` for the config directory when it does not exist; `write` of the serialized file (JSON re-serialization or the comment-preserving TOML splice) |
| `config init` | the same `mkdir`; `write` of the generated template |
| `config edit` | the same `mkdir`; `write` of the empty file when it does not exist; `run` of `[$EDITOR, path]` with `stream=true` |

Two details matter. The directory's existence is **probed with an ordinary filesystem
read** and the `mkdir` is issued only when it would create something -- reads are never effects,
branching on a real value walks the preview straight through (§5.2's idiom), and the preview stays
honest about what it would do. And `config edit`'s `run` keeps `check` at its default `true`, so
the editor's exit status is an error rather than a value (§2.5.4): nothing in these handlers ever
reads an exit code off a carrier, which is what lets one handler body be right in both modes.

An app-level cache write is an ordinary `FILE_WRITE` and requires a `mutating` command. There is
no way for an application to mint a `CACHE_WRITE`.

---

## 10. Guard v2 and declared forwarding

### 10.1 The v1 exemption being closed

Python's handler-signature validation (`_build_and_validate_command`) currently computes
`has_var_keyword` and then skips every missing-parameter and extra-parameter check when the
handler accepts `**kwargs`. That exemption is a hole: any handler can opt out of the entire
"declare everything" guarantee by adding `**kwargs`.

Guard v2 removes the blanket exemption. A `**kwargs` handler is now a registration error
**unless** the command declares forwarding.

### 10.2 Declared forwarding

Modelled structurally on `Passthrough`, which is the repo's existing precedent for "a handler
whose signature the framework deliberately does not police":

| Impl | Shape |
|------|-------|
| Python | `@dataclass class Forwarding: reason: str`; `forwarding: Forwarding \| None = None` field on `Command`; `forwarding=` keyword on `app.command(...)` / `group.command(...)` -- exactly mirroring `passthrough: Passthrough \| None = None`. |
| Go | `WithForwarding(reason string) CmdOption`, setting `Forwarding bool` + `ForwardingReason string` on `Command` -- mirroring `WithPassthrough`'s `Passthrough bool` + `PassthroughHandler` pair. |
| TypeScript | `forwarding: { reason: string }` in the `defineReadOnlyCommand` / `defineMutatingCommand` options object, surfacing as a `readonly forwarding?: { reason: string }` field on `CommandDef`. |

`reason` is mandatory and non-empty; it is emitted in the schema (§13) so that a `check` gate can
audit every forwarding site in a consumer.

When forwarding is declared, the framework skips the missing/extra parameter checks exactly as v1
did for `**kwargs` handlers -- the flags and args are still fully declared and still fully parsed;
only the *signature* cross-check is waived.

### 10.3 Parity note

Only Python has a `**kwargs` analog to guard: Go handlers take
`map[string]interface{}` and TypeScript handlers take a typed args object, neither of which can be
introspected for a var-keyword parameter. Guard v2's *enforcement* is therefore Python-only. The
*declaration* (`WithForwarding`, `forwarding:`) exists in all three so the API surface stays in
parity and consumers can label forwarding wrappers uniformly; in Go and TS declaring it is
inert beyond the schema emission. `check_api_surface.py` records this with an explicit
`impl_exclusions` rationale rather than treating it as a divergence.

### 10.4 Framework-internal handlers

strictcli auto-registers six commands of its own: `check` (§7.5) and the five `config`
subcommands (§9.2). Every one of their handlers accepts `**kwargs` today, and must keep doing so:
handlers receive the **app's global flag values** as keyword arguments, and those flags are
app-defined, so a framework-authored handler cannot name them. Guard v2 would reject all six.

They get **no exemption**. The mechanism is declared forwarding plus a verification that only the
framework can claim it:

1. **Declared forwarding.** Each of the six commands is registered with forwarding declared and
   the fixed reason string:

   ```
   framework-internal: absorbs app-defined global flag values
   ```

   This is ordinary `Forwarding` / `WithForwarding` / `forwarding:` (§10.2). It is emitted in the
   schema like any other forwarding, so a consumer's audit gate sees the six sites and can
   recognize them by that exact reason.

2. **The internal marker.** `Command` gains a private field -- Python `_framework_internal: bool`,
   Go `frameworkInternal bool`, TS `readonly frameworkInternal?: boolean` -- set **only** by
   strictcli's own registration paths (`_register_check_command`, `_register_config_group` and
   their Go/TS equivalents). It is not reachable from any public factory, option or spec: there is
   no `framework_internal=` keyword, no `WithFrameworkInternal()`, no `frameworkInternal` key in
   any options object. It is not emitted in the schema.

3. **Module verification (the hardening).** At registration, when the marker is set, the framework
   verifies the handler is defined inside strictcli's own module -- Python
   `getattr(handler, "__module__", None) == __name__`; Go, the handler's function pointer resolves
   into the strictcli package via `runtime.FuncForPC`; TS, the handler's identity is a member of a
   **`WeakSet<Function>` of framework-created handler identities**. If it is not, registration
   hard-errors with `errFrameworkInternalHandlerForeign` (§12.9). A consumer that reaches the
   marker by any route -- monkey-patching, prototype tampering, reflection -- therefore fails
   loudly at registration rather than silently inheriting a framework exemption.

   The TypeScript `WeakSet` is the mechanism, pinned: a module-level `const` declared in
   `typescript/src/app.ts` next to the single validated registration path, written by the two
   modules that mint internal handlers (`typescript/src/checks/cmd.ts` and
   `typescript/src/config.ts`) at the moment each handler is created, and **never re-exported from
   `typescript/src/index.ts`** -- so it is package-internal and unreachable from consumer code,
   exactly as the marker itself is. Verification is one membership test. It keys on **function
   identity**, not on `handler.name`, `Function.prototype.toString()` output or a marker property,
   because each of those is forgeable and identity is not; and it is a `WeakSet` rather than a
   `Set` so a handler that goes out of scope remains collectible.

**The `config` subcommands' validation bypass is closed in the same change.** Python's
`_register_config_group` currently builds all five commands by calling the `Command` constructor
directly, skipping `_build_and_validate_command` entirely -- so no signature validation, no flag
validation, and (under this contract) no classification check would ever run on them. That bypass
is deleted: all five go through `_build_and_validate_command` like every other command, which is
what makes §9.2's classification table enforceable, subjects them to guard v2, and routes them
through the marker + forwarding pair above. The Go and TypeScript equivalents are audited for the
same shape and converged onto their own single validated registration path. The `check` command
already routes through `_build_and_validate_command` and only needs the marker and the forwarding
declaration -- that asymmetry between `check` and `config` is the bug being closed, and after this
change there is exactly one registration path in each implementation, with no direct-construction
callers left outside it.

---

## 11. Bypass lint as check providers

Each implementation ships one **built-in check provider** registering **three** checks (amended
2026-08-03, D4/D5; a third added 2026-08-04, §18.7):

| Field | `effects-bypass` | `observe-allowlist-breadth` | `consequential-grant-agreement` |
|-------|------------------|-----------------------------|---------------------------------|
| tags | `["effects", "quality"]` | `["effects", "quality"]` | `["effects", "quality"]` |
| severity | `error` | `warn` | `warn` |
| fast | `true` | `true` | `true` |
| pure | `true` | `true` | `true` |
| needs_network | `false` | `false` | `false` |
| depends_on | `[]` | `[]` | `[]` |

`effects-bypass` statically analyses the consumer's own sources and fails on any direct process,
filesystem-mutation or network call **reachable from a registered command handler** that does not
go through `ctx.effects`. `observe-allowlist-breadth` reads the app's own declared
`proc_observe_allowlist` and warns on every single-token prefix (§6.2). All three are registered
through the existing provider hook (`App.register_check_provider` /
`(*App).RegisterCheckProvider` / the TS provider module), the same mechanism the built-in
`cli-test-coverage` check already uses, so a TOML-less app still gets working checks.

#### 11.0 `consequential-grant-agreement`

Reads the app's own registered commands -- no source analysis -- and warns for every command that
declares a grant of kind `proc_mutate` or `net_mutate` and does **not** declare itself
`consequential` (§8.1). The message is one line per finding, naming the command's dotted path, the
grant and the kind:

```
command '<path>' declares grant '<g>' (kind <k>) but is not consequential: a <k> effect leaves this process and the framework cannot walk it back, and the grant already says the step is worth explaining. Declare the command consequential, or drop the grant if the step is routine.
```

The pass message is `every escaping grant sits on a consequential command`; the found message is
`<n> grant(s) on non-consequential command(s)`.

**Why grants at all.** §6.1 says a grant exists "so that a reviewer reading a dry run sees why a
dangerous step is there." That is the same judgement `consequential` makes, stated per-effect
instead of per-command. When both are present they should almost always agree, and a disagreement
is worth saying out loud.

**Why only two of the four kinds.** `proc_mutate` runs another program and `net_mutate` changes
remote state; neither can be walked back by the framework, and remote state is the least
recoverable thing the regime can touch. `file_write` and `proc_spawn` are local and ordinarily
recoverable -- a written file is in the working tree, a spawned child's own effects ride its own
grants -- and flagging every one of them would re-create, inside the lint, exactly the 1:10 noise
ratio §8.1 exists to remove. Rejected: flagging any grant at all (too broad, for that reason), and
inferring irreversibility from the effect's arguments (§0's zero-inference rule forbids it, and
there is no irreversibility field to read).

**Why `warn` and not `error`.** The two declarations *can* legitimately disagree: a command may
declare a `proc_mutate` grant for a step that is genuinely routine (`git add`), and `consequential`
is deliberately not mandatory. An error-severity check would make the declaration mandatory
through the back door -- consumers would add `consequential` to clear a red gate rather than
because they judged the command consequential, which is precisely the reflex this whole round
removed, re-created one layer up. `effects-bypass` is `error` because a bypass is provably wrong;
this finding is provably *suspicious*, and the precedent for that severity is already set by
`observe-allowlist-breadth` (§18.5 item 81), which is likewise a "these declarations disagree and
either could be right" finding cleared by `--ignore-warnings`.

Analyser per language, all **regular dependencies** (no optional imports, no soft degradation):

| Impl | Analyser |
|------|----------|
| Python | stdlib `ast` |
| Go | stdlib `go/ast` + `go/parser` |
| TypeScript | the TypeScript compiler API -- `typescript` moves from `devDependencies` to `dependencies` in `typescript/package.json`. This is a published-surface change and gets its own changelog line. |

### 11.1 The scope rule, and what each language actually delivers

**Opting in is NOT the trigger.** An earlier reading -- "a call inside a function whose own body
mentions `.effects`" -- let two shapes escape completely: a handler that never mentions the handle
at all, and a bypass one helper-call away from a handler that does. Since this lint is the **sole
stated mitigation for the accepted no-sandbox ceiling** (§16, §17), both shapes are exactly the
ones an escaping consumer would reach for first. The scope is **reachability**.

**Roots** (both conditions, in every language):

1. a **registered command handler**, recognized per language as below;
2. as before, any function that reaches for `.effects` itself -- kept because a helper that uses
   the handle promises a complete preview whether or not the analyser can see who calls it.

**Closure**: from every root, follow **direct calls** to declared functions, transitively.

| Impl | Handler-root recognition | Closure unit | Alias handling |
|------|--------------------------|--------------|----------------|
| Python | a `.command` / `.passthrough` decorator on the function, or the function's name passed as `handler=` anywhere in the module | **intra-module** (one file): bare `name(...)` calls resolved against module-level `def`s | names assigned from an expression reaching `.effects` (`e = ctx.effects`) are the handle, not a bypass |
| Go | the function's **first parameter is `*Context`** (or `*strictcli.Context`) -- exactly the command-handler and passthrough-handler signatures, and nothing else in the surface | **intra-package** (one directory, across its files): bare `name(...)` calls resolved against that package's receiver-less top-level `func`s | names assigned from `ctx.Effects()`, plus parameters declared `*Effects` |
| TypeScript | the `handler:` property of a factory options object -- inline (`handler: (a, c) => {...}`, including through a wrapper call) or naming a declared function (`handler: deploy`) | **intra-file**: bare `name(` calls resolved against a token-level function table (`function f(...) {}`, `const f = (...) => {}`) | identifiers initialized from an expression ending in `.effects` |

A finding is reported **once per call site**, named for the innermost enclosing function.

**TypeScript's ceiling is real and is recorded, not papered over.** `typescript@7` is the native
port: it ships the scanner, `SyntaxKind` and the AST node predicates, but **no in-process parser**
-- building a syntax tree there means spawning the native language server against a resolved
tsconfig, which a check declared `fast` **and** `pure` must not do. What the scanner gives is brace
depth (real containment) and token adjacency (a serviceable function table and `handler:` root
detection), and the TS check builds an intra-file call graph on exactly that. It therefore closes
both escape shapes *within a file* and no further. The residual gap -- no cross-file/import
resolution, no scope or shadowing resolution, no method-call resolution, and handler roots
recognized only through the literal `handler:` spelling -- is an accepted ceiling (§17). This
document does not claim TypeScript delivers the intra-module reachability Python and Go do.

**Precision is bounded by the closed name lists, in every language.** The lists are matched on the
called name with coarse receiver gating, so a call whose *name* collides with a listed one is a
finding even when it is unrelated (`str.replace` matching `os.replace`, `app.call` matching
`subprocess.call`). Widening the scope to reachability widens that exposure proportionally. The
lists are deliberately **not** narrowed here: a lint that is the sole mitigation for a ceiling
fails closed, and a false positive is a visible, one-line fix in consumer code where a false
negative is silent.

**The one carve-out: a false positive that has no fix.** *Added 2026-08-09, from a consumer
report.* The paragraph above rests on "a false positive is a visible, one-line fix in consumer
code" -- the consumer routes the call through `ctx.effects` and the finding clears. That rationale
is **false** for a flagged call the handle could not carry: the handle's method set is closed
(§2) and has no in-process-observe method, so a finding on a pure in-process read cannot be acted
on at all. Its own remediation line ("route it through `ctx.effects`") is then a lie, and the
consumer's only exit is to rewrite working code into a shape the lint happens not to match.
Reported in the field: `platform.system()` -- a pure string read, no process -- flagged as
`os.system`, and a consumer rewrote it as a `platform.uname()` projection purely to clear the
gate.

So a leaf is narrowed when, and only when, **both** hold: its name collides with a call that
performs no effect at all, and that call has no route through the handle. The narrowing is
receiver gating, never leaf removal, so the real effect stays a finding:

| Impl | Leaf | Finding | Exempt |
|------|------|---------|--------|
| Python | `system` | receiver resolvable to `os` (`os.system`, `import os as o` + `o.system`, `from os import system` + bare call) | every other receiver -- `platform.system()`, `foo.system()` |
| TypeScript | `exec` | bare `exec(...)`, or a child_process receiver (`cp.exec`, `execa.exec`) | every other receiver -- `re.exec(line)` |
| Go | n/a | -- | no equivalent: the process list is already receiver-gated (`exec`/`syscall`/`os`/`cmd`) and the stdlib has no `os.System` |

Python resolves the receiver through the module's own imports, against a closed list of effect
modules, which is why the same table also closes two escapes the name-only matching left open
(`import requests as rq` + `rq.post`, `from subprocess import run` + a bare `run`). TypeScript has
no import resolution (§17), so a **bare** `exec(` stays a finding there -- unqualified `exec` in a
reachable scope is the child_process import in every realistic reading.

This carve-out does not reopen the general rule. A name collision with a call that *does* perform
an effect (`str.replace` vs `os.replace`) is still reported: routing it through the handle is
still possible, so the finding is still actionable.

Additionally, the TS `effects-bypass` check flags the two accepted Proxy ceilings (§4.4): a bare
truthiness test or a `===` comparison against a value the analyser can trace to an effects-handle
return. These are the only things the runtime seal cannot catch, so lint is the sole line of
defence and the check must name them explicitly.

---

## 12. Message templates

New templates land **identically in all three implementations**, in the three catalog files that
`conformance/check_error_parity.py` extracts from:

- Python -- `python/strictcli/__init__.py`; the extractor reads the source, and sees a template in
  exactly two shapes. First, inline `raise ValueError(...)` / `_ParseError(...)` / `EffectFailed(...)`
  strings. Second, a `_msg_*` function returning the finished string -- one function per template,
  the shape that mirrors Go's `err*` / `prompt*` functions. The second shape is what any template
  the raise-scan cannot see must use: the confirm protocol's three (§12.6), which are *printed*
  rather than raised; the truncation error (§12.5), which rides `_DryRunTruncated`; and the
  effect-parameter type guards, which raise `TypeError`. `TypeError` and `RuntimeError` are
  deliberately outside the raise-scan (`check_error_parity.py`'s manifest carries exclusion
  rationales that depend on it), so a template carried on one of them is invisible until it has a
  `_msg_*` function.
- Go -- `go/strictcli/errors.go` (an `err*` function per template)
- TypeScript -- `typescript/src/errors.ts` (an `err*` function per template, one-to-one with Go,
  under the same Go-source-file section headers the extractor keys on)

The structural model for a registration-time ban is the existing `force` triple:
`errFlagForceReserved` (Go `errors.go`, panicked from `validateFlagConfig` in
`go/strictcli/strictcli.go`), `errFlagForceReserved()` (TS `errors.ts`, thrown from
`validateFlagConfig` in `typescript/src/factories.ts`), and the inline `ValueError` in Python's
`Flag.__post_init__`. Every new registration-time template below follows that shape.

**Category placement.** `check_error_parity.py` sorts every template into `parse` or
`registration`, and only `parse` templates are required to have a covering conformance case. Go and
TypeScript express the split with dashed section headers whose text contains `(parse-time)`; Python
expresses it through the raised exception type plus a listed set of `_msg_*` function names. The
effects regime's split is pinned here, and the three catalogs' section markers must agree with it:

| Section | Category |
|---------|----------|
| §12.5 truncation | parse-time |
| §12.11 aborted preview | parse-time |
| §12.6 confirm trio | parse-time |
| §12.8 effect failure, carrier rejection and the option guard | parse-time |
| §12.1, §12.2, §12.3, §12.4, §12.7, §12.9, §12.10 | registration-time |

(§12.11 was added at the 2026-08-04 adoption round and takes the same category as §12.5, whose
message family it belongs to.) §12.4's templates fire at effect-call time rather than at
registration, but they take the registration-time category: the taxonomy's `parse` bucket is the set the coverage gate binds, and
the ruling pins that bucket to the three sections above.

**Go declaration form.** A template that interpolates nothing is a **`const`**, not a function --
matching `errors.go`'s existing style (`const errFlagForceReserved = "..."`,
`const errArgHelpEmpty = "..."`, and the ~20 other parameterless consts already there). Only
templates that interpolate become `func err*(...) string`. TypeScript keeps
`export function err*(): string` even when parameterless, matching its own existing style
(`errFlagForceReserved()`, `errArgHelpEmpty()`); the parity extractor keys on the name, which is
identical either way. Among the templates below this affects `errConfirmNonInteractive` and
`errConfirmDeclined` (§12.6), which are Go `const`s.

### 12.1 Reserved-name ban

```
flag name '<x>' is reserved by the framework (dry-run, approve-consequential, quiet, verbose)
```

Function name: `errFlagNameReservedByFramework(name)`. Raised from the same
`validateFlagConfig` / `Flag.__post_init__` sites as the `force` ban, and additionally from the
global-flag validation path so app globals are covered by the same message.

```
flag name 'yes' is banned by the framework: the confirmation skip is --approve-consequential
```

`errFlagNameYesBanned()` (Go: a parameterless `const`, per this section's Go declaration form).
Registration-time, raised from the same two sites. `yes` names no framework flag any more, so this
is a separate template from the quartet's and it states the reason plus the replacement rather than
listing a set the name is not in (§7.1).

### 12.2 Classification

```
command "<name>": effect classification is required (effect="read_only" or effect="mutating")
```

`errCommandEffectMissing(name)`. Registration-time.

```
command "<name>": invalid effect "<v>": must be "read_only" or "mutating"
```

`errCommandEffectInvalid(name, v)`. Registration-time.

```
deprecated command "<name>": effect classification does not apply (a deprecated command has no handler)
```

`errDeprecatedCommandEffect(name)`. Registration-time. Enforces §1.1's exemption in the one
direction that can be enforced -- a caller passing `effect=` to `deprecate(...)` is wrong.

```
command "<name>": a read_only command cannot be consequential (a command that changes nothing has nothing to confirm)
```

`errCommandReadOnlyConsequential(name)`. Registration-time, all three. Enforces §8.1: the two
declarations answer different questions, and the read-only answer to the first makes the second
unanswerable.

### 12.2a Dry-run declaration

*Added 2026-08-06 (ecosystem fix campaign §1.2), with §1.1a and §13's schema pair.*

```
command "<name>": a read_only command cannot declare dry_run_supported=false (a command that changes nothing has no effects a preview could misrepresent)
```

`errCommandReadOnlyDryRunUnsupported(name)`. Registration-time, all three. Enforces §1.1a's
first guard; mirrors `errCommandReadOnlyConsequential` above.

```
command "<name>": dry_run_supported=false requires a non-empty dry_run_unsupported_reason (say what a preview cannot honestly show)
```

`errCommandDryRunReasonMissing(name)`. Registration-time, all three. §1.1a's second guard.

```
command "<name>": dry_run_unsupported_reason requires dry_run_supported=false (there is nothing to explain while dry run is supported)
```

`errCommandDryRunReasonWithoutDeclaration(name)`. Registration-time, Python and TypeScript only.
Go has no analog and the template is absent from its catalog with an `impl_exclusions`
rationale: `WithDryRunUnsupported(reason)` is Go's only spelling, so an orphaned reason is
unrepresentable there (§1.1a, third guard).

```
--dry-run is not supported by command '<cmd_path>': <reason>
```

`errDryRunNotSupported(cmdPath, reason)`. **Parse-time**, all three -- it mirrors the unknown-flag
format rather than the registration-error format, because from the operator's side this is a
rejected flag. `<cmd_path>` is the dotted path (groups then command). Raised by the gate
described in §1.1a, which sits after the command-help check so `--help` wins.

### 12.3 Guard v2 and forwarding

```
command "<name>": handler accepts **kwargs but the command does not declare forwarding; add forwarding=Forwarding(reason=...) or name every parameter explicitly
```

`errHandlerVarKeywordUndeclared(name)`. Python-only enforcement (§10.3); the template exists in
all three catalogs with an `impl_exclusions` rationale for Go and TS.

```
command "<name>": forwarding reason must be a non-empty string
```

`errForwardingReasonEmpty(name)`. Registration-time, all three.

### 12.4 Effect call-time errors

```
command "<name>" is classified read_only; effects.<method> is a mutating operation
```

`errEffectMutatingInReadOnly(name, method)`.

```
command "<name>" is classified read_only; effects.run argv <argv> is not on the app's proc_observe_allowlist
```

`errEffectRunNotAllowlisted(name, argv)`. `<argv>` is the space-joined argv.

```
command "<name>": grant '<g>' is not declared on this command
```

`errEffectGrantUndeclared(name, g)`.

```
command "<name>": grant '<g>' is declared for kind <k1> but was used for a <k2> effect
```

`errEffectGrantKindMismatch(name, g, k1, k2)`.

```
command "<name>": grant '<g>' cannot be used on an observe (an allowlisted effects.run changes nothing)
```

`errEffectGrantOnObserve(name, g)`. Call-time. Enforces §6.1: an observe is never recorded and
never logged, so no preview line exists for the grant to label. The message takes **no argv
parameter** -- naming the argv would repeat what the caller just wrote without adding the one fact
the reader needs, which is *why* the grant cannot land. (Amended 2026-08-03, ruling A: the draft
above pinned an argv-carrying wording, all three implementations shipped this one, and where the
implementations agree against the draft the implementations win.)

### 12.5 Truncation

```
error: dry-run preview ends at step N: <cmd> branched on unsettled value «step M output» — cannot preview past this point
```

`errDryRunTruncated(step, cmd, brand)`. Note the template already carries its own `error: `
prefix (it is written to stderr directly, not through the parse-error formatter). Parse-time
section of the catalogs.

### 12.6 Confirm

```
about to run consequential command '<name>'. Proceed? [y/N] 
```

`promptConfirmConsequential(name)` -- a prompt, not an error, but it lives in the same catalog files
so parity is checked. Renamed from `promptConfirmMutating` at the consequence round (§18.7): the
prompt names what the command declared, not what it was classified.

```
error: stdin is not interactive; pass --approve-consequential to confirm
```

`errConfirmNonInteractive()`. **This one is now conformance-covered**: the runner pins each case's
stdin to the null device (§14.5), so §8.3's branch is a deterministic outcome in all three targets
rather than a template whose trigger the runner could not reach. The prompt itself and
`errConfirmDeclined` stay `coverage_deferred` -- they need an answer typed at a terminal.

```
aborted
```

`errConfirmDeclined()`.

### 12.7 Grant declaration

```
command "<name>": grant '<g>' reason must be a non-empty string
```

`errGrantReasonEmpty(name, g)`.

```
command "<name>": duplicate grant '<g>'
```

`errGrantDuplicate(name, g)`.

```
command "<name>": invalid grant name '<g>': must match [a-z][a-z0-9-]*
```

`errGrantNameInvalid(name, g)`.

### 12.8 Effect failure (§2.5.4)

```
command "<name>": effects.<method> failed: <argv> exited <code>
```

`errEffectRunFailed(name, method, argv, code)`. `<argv>` is the space-joined argv; `<method>` is
`run` or `spawn` (the latter when `Spawned.wait()` reports the failure).

```
command "<name>": effects.http failed: <METHOD> <url> returned <status>
```

`errEffectHTTPFailed(name, httpMethod, url, status)`.

```
command "<name>": effects.<method> produced output that is not valid UTF-8
```

`errEffectOutputNotUTF8(name, method)`.

```
command "<name>": effects.<method> parameter '<p>' does not accept an unsettled value
```

`errEffectParamRejectsCarrier(name, method, p)`. Call-time; raised in two situations. First, when
a carrier is passed to one of the parameters §2.5.5 excludes -- `mode`, `method`, `body`, `cwd`,
`env`, `headers`, `check`, `stream` and the three common options. Second, when a carrier that has
no scalar projection is forwarded into one of the six *accepting* positions: a `Spawned`, or a
void result (§2.5.5). The void case is an error in **both** modes and in all three
implementations; in Go, where the void carrier is never settled, the message reads literally.

```
command "<name>": effects.<method> does not accept option '<opt>'
```

`errEffectOptionNotAccepted(name, method, opt)`. Call-time, all three (§2.5.2). `<opt>` is the
option's **canonical snake_case name** (`check`, `stream`, `body`, `cwd`, `env`, `headers`,
`resource`, `skip_if_current`, `grant`), identical in every implementation, so the rendered message
is byte-identical too: Go's `EffectOption` values therefore carry that canonical name for the
message even though the constructor is spelled `Stream(bool)`. Python and TypeScript raise it from
the keyword / options-object-key check; Go from its call-time variadic validation.

### 12.9 Framework-internal handlers (§10.4)

```
command "<name>": handler is marked framework-internal but is not defined in the strictcli module
```

`errFrameworkInternalHandlerForeign(name)`. Registration-time, all three.

### 12.10 Argument guards and declaration guards

Added 2026-08-03 (ruling E). These templates shipped in the implementations without a §12 entry.
They are **added here rather than deleted from the code**: every one of them names a real
fail-closed guard, and deleting a guard to satisfy a document would be exactly backwards. Each has
one canonical wording, byte-identical wherever it exists.

Category: **registration-time** in the parity taxonomy. They are argument guards, not the §12.8
failure family, and the campaign's category ruling puts only §12.5, §12.6 and §12.8 in the
parse-time section.

**Effect argument type guards (call-time), all raised as the language's type error:**

```
command "<name>": effects.<method> parameter '<p>' must be a string, a path, or a forwarded effect result; got <t>
```

`errEffectParamNotStringish(name, method, p, t)` (Go: `errEffectParamType`). All three.

```
command "<name>": effects.<method> argv must not be empty
```

`errEffectArgvEmpty(name, method)`. All three.

```
command "<name>": effects.<method> argv must be a sequence of strings, not <t>
```

`errEffectArgvNotSequence(name, method, t)`. Python and TypeScript. **Go-excluded**: Go's `argv`
parameter is typed `[]any`, so a non-sequence argv is a compile error, not a runtime one.

```
command "<name>": effects.chmod parameter 'mode' must be an int, got <t>
```

`errEffectModeNotInt(name, t)`. Python and TypeScript. **Go-excluded**: `Chmod` takes `mode int`
positionally.

```
command "<name>": effects.http parameter 'method' must be a string, got <t>
```

`errEffectHTTPMethodNotString(name, t)`. Python and TypeScript. **Go-excluded**: `HTTP` takes
`method string` positionally.

**Handle availability.** The message names each language's own accessor spelling (§2.1), so the
three texts differ by exactly that noun phrase and each is excluded in the other two:

| Impl | Text |
|------|------|
| Python | `ctx.effects is unavailable: this Context was constructed outside a command dispatch` |
| TypeScript | `ctx.effects is unavailable: this Context was constructed outside a command dispatch` |
| Go | `ctx.Effects() is unavailable: this Context was constructed outside a command dispatch` |

`errEffectsUnavailable`.

**Declaration guards (registration-time):**

```
command "<name>": grant '<g>' has invalid kind '<k>': must be one of proc_mutate, proc_spawn, file_write, net_mutate
```

`errGrantKindInvalid(name, g, k)`. All three. It completes §12.7's grant-declaration trio.

```
command "<name>": grants must be Grant instances, got <t>
```

Python only. **Go- and TypeScript-excluded**: `WithGrants(...Grant)` and the `readonly Grant[]`
option are statically typed, so a non-grant element is a compile error.

```
proc_observe_allowlist entries must not be empty
```

`errProcObserveAllowlistEmptyPrefix`. All three. An empty prefix matches every argv, which would
turn the allowlist into a blanket exemption.

```
proc_observe_allowlist entries must be lists of strings, got <t>
```

`errProcObserveAllowlistNotStrings(t)`. Python and TypeScript. **Go-excluded**:
`WithProcObserveAllowlist([][]string)` is statically typed.

### 12.11 Aborted preview

Added 2026-08-04 (D7). The marker that follows a would-do log the dispatch did not finish (§3.5):

```
error: dry-run preview ends at step N: <cmd> aborted — the preview above may be incomplete
```

`errDryRunAborted(step, cmd)` / `_msg_dry_run_aborted(step, cmd)`. All three. Written straight to
**stderr**, which is why it carries its own `error: ` prefix, exactly like §12.5's truncation
error. Category: **parse-time**, and it files under the same section marker family in Go's and
TypeScript's catalogs.

`N` has the same meaning it has in §12.5: the would-do number the preview reached, i.e. the number
the next *rendered* effect would have taken (§3.2's rendered-line counter, so cache writes never
move it). `<cmd>` is the dotted command path, not the app name.

The shape is deliberately §12.5's, down to the `ends at step N: <cmd>` clause: both messages say
the preview stopped before the handler finished, and a reader should be able to recognize them as
one family and read only the tail to learn which happened. The tail is `may be incomplete`, not
`is incomplete`, because that is the precise claim: an exception escaped, and the framework cannot
know whether the handler had more to record. The message deliberately does **not** name the
exception type or repeat its message -- the language's own crash report already carries both, and
naming them here would put three different type vocabularies into a template that must be
byte-identical across three languages.

---

## 13. Schema fields

`--dump-schema` output (`.strictcli/schema.json`) gains:

**On every command entry** (Python `_serialize_command`, and the Go/TS equivalents):

| Key | Type | Emission |
|-----|------|----------|
| `effect` | `"read_only"` \| `"mutating"` | **always** -- classification is mandatory, so there is no default to omit against |
| `consequential` | `true` | omitted when false -- unlike classification it is NOT mandatory, and absence means "not consequential" (§8.1). It follows `hidden` / `interactive`'s omit-when-false shape, not `effect`'s always-emitted one |
| `dry_run_supported` | `false` | *Added 2026-08-06 (§1.1a).* Emitted **only when declared false**; absence means dry run is supported, which is the baseline. Same omit-when-baseline shape as `consequential` |
| `dry_run_unsupported_reason` | `str` | *Added 2026-08-06 (§1.1a).* Emitted exactly when `dry_run_supported` is, and never alone -- the pair is atomic, which is what §1.1a's second and third guards buy at registration time |
| `grants` | array of `{"name": str, "reason": str, "kind": str}` | omitted when empty; entries in declaration order; `kind` uses the lowercase kind name (`proc_mutate`, `proc_spawn`, `file_write`, `net_mutate`) |
| `forwarding` | `{"reason": str}` | omitted when absent |

**On the app entry:**

| Key | Type | Emission |
|-----|------|----------|
| `proc_observe_allowlist` | array of arrays of string | omitted when empty; prefixes in declaration order |

Deprecated commands do not appear here at all: they serialize into the separate top-level
`deprecated` list (Python `schema["deprecated"]`, Go/TS equivalents), not through
`_serialize_command`. §1.1's exemption therefore costs the dumped schema nothing.

The conformance case schema (`conformance/schema.json`) mirrors these under `$defs/command` and
`$defs/app`. `effect` must **not** be added to `$defs/command`'s top-level `required` list:
`$defs/command` already carries an `if`/`then` that reshapes deprecated entries, and a top-level
`required` applies conjunctively with the `then`, so a top-level entry would make `effect`
mandatory on deprecated commands too -- the opposite of §1.1. The concrete change, exactly:

- add `effect` (`{"enum": ["read_only", "mutating"]}`) to `$defs/command`'s `properties`;
- add `consequential` (`{"type": "boolean", "default": false}`) to the same `properties`, and to
  the deprecated branch's `then.properties` as `false`. It is deliberately **not** added to the
  `else` branch's `required`: it is not mandatory, and a schema that demanded it would re-impose
  exactly the per-registration answer §8.1 removed;
- leave the top-level `required` as `["name", "help"]`;
- add `"effect": false` to the deprecated branch's `then.properties`, alongside the existing
  `"handler_prints": false` / `"flags": false` / ... entries, so a deprecated case declaring
  `effect` fails validation;
- add an `else` branch to the same `if`: `{"required": ["effect"]}`, making classification
  mandatory for every non-deprecated command entry.

*Added 2026-08-06 (§1.1a):* the same treatment extends to the dry-run pair.

- add `dry_run_supported` (`{"type": "boolean", "default": true}`) and
  `dry_run_unsupported_reason` (`{"type": "string", "minLength": 1}`) to `$defs/command`'s
  `properties`. Like `consequential`, neither joins the top-level `required` nor the `else`
  branch's -- absence means supported, and a schema that demanded them would re-impose a
  per-registration answer to a question almost every command answers the same way. The
  `minLength: 1` encodes §1.1a's second guard at the case-schema layer;
- add both to the deprecated branch's `then.properties` as `false`, so a deprecated case
  declaring either fails validation. This follows from §1.1's exemption for the same reason
  `effect` and `consequential` do: a deprecated entry has no handler, so it has no effects a
  preview could misrepresent.

The same three keys (`grants`, `forwarding`, and app-level `proc_observe_allowlist`) are added to
`properties` as ordinary optional fields, with `grants` and `forwarding` also set `false` in the
deprecated `then.properties`.

`conformance/check_api_surface.py` gains the corresponding entity mappings on the existing
`EntityDescriptor` for `command` and `app`: `schema_to_go` entries
`"command.grants": "grants"` and `"app.proc_observe_allowlist": "procObserveAllowlist"`, and the
`ts_entity_exclusions` note for `forwarding` in Go/TS mirroring the existing `passthrough`
exclusion rationale.

`conformance/check_schema_parity.py` needs no shape change -- the new keys are ordinary fields.

---

## 14. Conformance surface

### 14.1 New expect key: `effects_equals`

Added to `$defs/expect` in `conformance/schema.json`, and dispatched in `run.py`'s expect block
alongside the existing `stdout_*` / `stderr_*` / `config_file_*` families:

```json
"effects_equals": {
  "type": "array",
  "items": { "$ref": "#/$defs/effect_record" },
  "description": "Deep-equality assertion against the structured effect log the run produced."
}
```

Comparison is deep equality over the parsed JSON arrays, in order. Absent optional keys and
explicit-null keys are equivalent. The one key that equivalence never reaches is `recorded`, which
is **required** on every record (§14.2) and therefore never absent -- that is the point of making
it required. Where the equivalence earns its keep is `bytes`: absent on every non-`write` effect,
and explicitly `null` on a `write` whose content was a forwarded carrier (§3.2). It is an ordinary
expect key: a case may combine it with `stdout_equals` (asserting the rendered log) and with
`exit_code`.

### 14.2 `$defs/effect_record`

```json
{
  "type": "object",
  "required": ["seq", "kind", "verb", "detail", "recorded"],
  "additionalProperties": false,
  "properties": {
    "seq":             { "type": "integer" },
    "kind":            { "enum": ["proc_mutate", "proc_spawn", "file_write", "net_mutate", "cache_write"] },
    "verb":            { "enum": ["run", "spawn", "write", "mkdir", "remove", "rename", "chmod", "net", "cache"] },
    "detail":          { "type": "string" },
    "bytes":           { "type": ["integer", "null"] },
    "resource":        { "type": "string" },
    "skip_if_current": { "type": "string" },
    "grant":           { "type": "string" },
    "recorded":        { "type": "boolean" }
  }
}
```

`detail` is the same string the would-do log renders after the verb (so forwarded carriers appear
in brand form). `bytes` is present only for `write`, and is `null` rather than an integer when that
`write`'s content was an unsettled carrier (§3.2) -- there are no bytes to count. A settled content
value, forwarded or literal, in either mode, carries its real encoded length. `recorded` is
`true` when the effect was recorded instead of performed, and `false` when it actually executed --
so framework-blessed `CACHE_WRITE`s carry `recorded: false` even during a dry run (§3.1).

**The structured effect log is populated in both modes,** and `recorded` is the key that says
which happened. A live run records every effect it performs, each with `recorded: false`; a dry
run records every application effect with `recorded: true` and the framework-blessed cache writes
it still performs with `recorded: false`. This is why `recorded` is in `required`: with it
optional, an absent key and an explicit `null` are equivalent under §14.1's comparison rule, and
"absent" would have had to mean both "live" and "unstated" at once. It is not the would-do log --
that is dry mode's stdout rendering (§3.2) and does not exist in live mode at all; the structured
log is a diagnostic, read only through the §14.3 accessor, and changes nothing about the run.

> **Amendment (2026-08-13, machine-interface round): the structured effect log graduates from
> test-only diagnostic to the envelope's source.** The record shape above is unchanged and stays
> the single definition -- what changes is its standing. It is no longer "a diagnostic read only
> through the §14.3 accessor": in machine mode the same records are the envelope's `preview` member
> (§19.3), and in either mode a handler may read them through `ctx.effects.recorded()` (§19.7).
> "Changes nothing about the run" still holds and is now the important half of the sentence: the
> log is produced identically whether or not anything reads it, and reading it never alters
> behaviour.
>
> `$defs/effect_record` gains **one optional key**, `children`: an array of `effect_record`s,
> making the shape recursive from day one for the compositional child previews of §19.8. It is
> absent on every record today and stays absent until §19.8 is implemented; the recursion is
> pinned now so the schema does not have to change shape when it is.

Observes (§6.2) do not appear in the structured effect log at all. The `kind` and `verb` enums
above have no observe member, and an observe recorded as a `proc_mutate`/`run` pair would be
indistinguishable from a real mutation -- which is exactly the confusion the log exists to
prevent. The log is what would change, in both its rendered (§3.2) and structured forms.

### 14.3 The effect-log side channel

The structured log cannot ride stdout without polluting byte-identity comparison, and conformance
runs implementations as subprocesses. It therefore uses the **same env-var file-handoff pattern
as the existing `CONFORMANCE_APP_DEF`**:

- `run.py` sets `CONFORMANCE_EFFECT_LOG=<temp path>` for a case that declares `effects_equals`,
  and only for such a case.
- When that variable is set, each harness -- after dispatch, before exit -- reads the framework's
  effect log through a dev accessor and writes it to that path as a single compact JSON array
  with sorted object keys.
- `run.py` reads and parses the file, compares, then unlinks it via the existing `cleanup_paths`
  machinery.

The framework accessor is `App.effect_log()` / `(*App).EffectLog()` / `app.effectLog()`, returning
the ordered records for the most recent dispatch -- in **either** mode, since the log is populated
in both (§14.2), which is what lets a case assert a live run's effects as readily as a dry run's.
~~It sits beside the existing test-only surfaces (`test()`, `_last_sources`) and is excluded from
the api-surface catalog the same way.~~ **Amended 2026-08-13 -- see the box below.**

> **Amendment (2026-08-13, machine-interface round): the accessor is public and its visibility
> converges.** The accessor's visibility diverges across the three implementations today -- exported
> public API in one, deliberately hidden in another, plain public in the third. Promotion makes it
> **public in all three** with one spelling per language, and it leaves the test-only enclosure: it
> is the envelope's source (§19.3), so it is part of the surface consumers may rely on and it joins
> the api-surface catalog rather than being excluded from it. The catalog will flag the change,
> which is correct -- it is a real surface addition.
>
> The file handoff above is unchanged and stays how conformance reads the log out of a subprocess.
> A case may now assert the same records twice over -- once through `CONFORMANCE_EFFECT_LOG` and
> once as the envelope's `preview` -- and that redundancy is the point: the two must agree
> record-for-record, in both modes.

This is deliberately **not** an env-var mode switch: it does not change any behavior, only where a
diagnostic is written. It is not the deleted A9 token (§16).

### 14.4 Handler vocabulary for effect-emitting handlers

The existing command-level handler vocabulary is `handler_prints`, `handler_exit_code`,
`handler_returns` and `passthrough_handler_prints`, materialized by `_emit_handler_body` /
`_emit_handler_return` (`conformance/ref_python.py`), `makeHandler` (`conformance/harness/main.go`)
and `makeHandler` (`conformance/harness_ts/main.js`). It gains one sibling key:

```json
"handler_effects": {
  "type": "array",
  "items": { "$ref": "#/$defs/handler_effect" },
  "description": "Effect calls the generated handler issues, in order, before its return."
}
```

`$defs/handler_effect`:

```json
{
  "type": "object",
  "required": ["method"],
  "additionalProperties": false,
  "properties": {
    "method":          { "enum": ["run", "spawn", "write", "mkdir", "remove", "rename", "chmod", "http"] },
    "argv":            { "type": "array", "items": { "type": "string" } },
    "path":            { "type": "string" },
    "to":              { "type": "string" },
    "mode":            { "type": "string" },
    "content":         { "type": "string" },
    "url":             { "type": "string" },
    "http_method":     { "type": "string" },
    "stream":          { "type": "boolean" },
    "resource":        { "type": "string" },
    "skip_if_current": { "type": "string" },
    "grant":           { "type": "string" },
    "forward_from":    { "type": "integer",
                         "description": "1-based index of an earlier handler_effects entry whose carrier is forwarded as the final argument of this call." },
    "extract_from":    { "type": "integer",
                         "description": "1-based index of an earlier entry whose carrier the handler EXTRACTS from (bool-tests it), triggering the truncation path. Terminal: nothing after this entry runs." }
  }
}
```

Interaction with the existing keys: `handler_effects` runs **before** the
`handler_prints` / `handler_returns` path, and does not replace it -- a case may emit effects and
then print or return normally. `extract_from` is terminal by construction (the extraction
truncates the run), so any later entries and any `handler_prints` are unreachable, which is what
the truncation cases want to assert.

Each of the three harnesses materializes this identically: iterate the array in order, call the
named effects method with the declared arguments, keep the returned carrier in a per-run slice
indexed by position so `forward_from` / `extract_from` can reference it. They pass **exactly the
keys the entry declares**, with no per-method filtering -- a case declaring a key the named method
does not accept is asserting the error, not misconfigured.

`stream` is the vocabulary's one option key. It maps to `run`'s `stream` parameter (§2.5.2), and
because no other method accepts it, declaring it on a non-`run` entry is how a case exercises
`errEffectOptionNotAccepted` (§12.8, §14.5). It is expressible in all three languages -- in Go,
`Stream(true)` is an ordinary `EffectOption` value that every method accepts syntactically and
that only `run` accepts at the call, which is exactly the shape the error covers.

### 14.5 Fixture app and parity checks

- `RICH_APP` lives in **`conformance/check_schema_parity.py`** (not `check_api_surface.py`): it is
  an app-*definition* dict fed to every implementation so their dumped schemas can be compared.
  Because classification is mandatory, the fixture cannot even be built without it: **every
  command entry in `RICH_APP` gains `effect`**, and its deprecated entries deliberately do not
  (§1.1). It additionally gains at least one command with `grants`, one with `forwarding`, and an
  app-level `proc_observe_allowlist`, so the new keys are exercised end-to-end.
  `check_schema_parity.py`'s comparison logic itself is unchanged -- the new keys are ordinary
  fields (§13) -- but the fixture edit is mandatory, not optional.
- The api-surface side of the same work is the `EntityDescriptor` mapping change already specified
  in §13, plus the `describe.ts` descriptor changes in §1.2.
- `check_error_parity.py` gains the §12 templates. Every parse-time template needs a covering
  conformance case (the extractor enforces it); registration-time templates need a
  `SIGNATURE_STATUS` entry only where an implementation legitimately lacks the message (§10.3).
- **Templates that cannot be covered by a conformance case need `coverage_deferred`
  `SIGNATURE_STATUS` entries**, one per implementation, following the file's existing precedent
  (the `'--*: cannot read stdin'` and `'--*: stdin (@-) can only be used once per invocation'` rows
  already carry
  `"coverage_deferred:Requires stdin piping to subprocess, not supported in conformance runner"`).
  Two of the three confirm-protocol templates are that case -- `promptConfirmConsequential` and
  `errConfirmDeclined` (§12.6) require an answer typed at a terminal, which the conformance runner
  cannot supply. `errConfirmNonInteractive` is **no longer deferred**: `run.py` pins every case's
  stdin to `subprocess.DEVNULL`, so §8.3's non-interactive branch is a deterministic outcome in all
  three targets and is covered by an ordinary case. Pinning stdin is itself required, not
  incidental -- a case must never depend on whether the operator happened to run the suite from a
  terminal. `errEffectHTTPFailed` (§12.8) gets
  its own deferral -- rationale: requires issuing a real network request, which conformance cases
  must not do.
- **§3.5's aborted path is covered by `targets: ["python", "typescript"]` cases** reached through
  the existing `handler_returns: {"kind": "bad"}` vocabulary, with `acknowledged_divergence` on
  stderr. Go is excluded for the same reason it is excluded from the bad-return case that set the
  precedent: its type system makes an invalid handler return unrepresentable, and the only other
  abort a case could induce is a panic, whose exit status (2) and goroutine dump cannot be asserted
  under a single `expect.exit_code`. Go's abort path is pinned by its own unit suite instead, on
  the same byte-exact strings. No new handler vocabulary was added for this: an abort a case can
  already express is preferable to a key that exists only to crash a handler.
- The cross-process cases that would have exercised an env-mode token are **not written**: A9
  deleted that mechanism (§16). What remains is in-process spawn-record assertions -- a `spawn`
  effect appearing in `effects_equals` with `recorded: true`.
- **The amendment round's two new templates are covered by ordinary cases, not deferred.**
  `errEffectGrantOnObserve` (§12.4) is expressible in the §14.4 vocabulary as it stands: an entry
  whose `argv` matches an app-level `proc_observe_allowlist` prefix and which also sets `grant`.
  `errEffectOptionNotAccepted` (§12.8) becomes expressible through the one vocabulary key §14.4
  adds, `stream`: an entry like `{"method": "mkdir", "path": "d", "stream": true}` reaches `mkdir`
  carrying an option `mkdir` does not accept, which is the error, and it reaches it identically in
  Python, Go and TypeScript because the harnesses pass the declared keys verbatim. `stream` was
  chosen over the other method-specific options because it is the only one no method but `run`
  accepts *and* whose Go spelling (`Stream(true)`) is an ordinary `EffectOption` any method takes
  syntactically -- a `mode`-on-`mkdir` case, by contrast, would not compile in Go, where `mode` is
  a positional parameter of `Chmod` and not an option at all.

---

## 15. Runtime-seal application sites

The seal (§4.4) is armed wherever a `Context` is constructed for handler dispatch. These are the
complete lists. Every site listed must construct the Context with the effects handle and the
reserved-flag values, and must arm carrier poisoning for the run.

### 15.1 Python -- 4 sites (`python/strictcli/__init__.py`)

| Symbol | Site |
|--------|------|
| `App.run` | the single post-parse `Context(...)` construction that serves both the passthrough and the normal handler branch |
| `App.test` | the capture-buffer `Context(...)` construction |
| `App._invoke` | the passthrough-command `Context(...)` construction |
| `App._invoke` | the normal-command `Context(...)` construction |

`App.call` / `App.acall` and the MCP server reach dispatch through `_invoke`, so they are covered
by the two `_invoke` sites; there is no separate MCP construction.

### 15.2 Go -- 5 sites

| File | Symbol | Site |
|------|--------|------|
| `go/strictcli/strictcli.go` | `(*App).Run` | passthrough branch `newContext(...)` |
| `go/strictcli/strictcli.go` | `(*App).Run` | normal-command `newContext(...)` |
| `go/strictcli/strictcli.go` | `(*App).Test` | the capture-pipe `newContext(...)` (single construction serving both branches) |
| `go/strictcli/invoke.go` | `(*App).invoke` | passthrough `newContext(io.Discard, io.Discard, nil, ...)` |
| `go/strictcli/invoke.go` | `(*App).invoke` | normal-command `newContext(io.Discard, io.Discard, sources, ...)` |

`(*App).Call` and the MCP server route through `(*App).invoke`.

The cleanest arming point is `newContext` itself (`go/strictcli/context.go`), which all five sites
already funnel through; the per-site work is passing the effects/reserved-flag state in.

### 15.3 TypeScript -- 4 sites

| File | Symbol | Site |
|------|--------|------|
| `typescript/src/app.ts` | `App.dispatch` (private; serves both `run()` and `test()` via its `mode` parameter) | the `"passthrough"` case `new Context(...)` |
| `typescript/src/app.ts` | `App.dispatch` | the `"command"` case `new Context(...)` |
| `typescript/src/invoke.ts` | `invokeApp` | `new Context(...)` |
| `typescript/src/invoke.ts` | `invokePassthrough` | `new Context(...)` |

`app.call()` and `serveMcp` route through `invokeApp`.

---

## 16. What the regime deliberately does NOT have

- **No cross-process effects-mode env token.** The `STRICTCLI_EFFECTS_MODE` family is deleted and
  must not be reintroduced under any name. Spawning is itself an effect (`spawn`), which is the
  entire mechanism: a dry run *records* the spawn instead of performing it, so there is nothing
  to propagate. When a consumer genuinely needs a child CLI to run dry, it passes `--dry-run`
  explicitly in the child's argv, like any other flag. Ambient mode inheritance is silent runtime
  behavior change and is forbidden.
- **No runtime currency machinery.** There is no current set, no resource-state tracking, no
  skip-if-current evaluation, no persistence, nothing that crosses a spawn. `resource=` is declared
  metadata and `skip_if_current=` is a preview annotation (§5). Real-mode idempotency is the
  handler's job and stays in handler code.
- ~~**No `dry_run_supported` capability negotiation** inside the framework.~~
  **Superseded 2026-08-06** (ecosystem fix campaign §1.2). The regime now carries a
  registration-level `dry_run_supported` **declaration** -- see §1.1a for the field, §12.2a for
  the message templates, and §13 for the schema pair. What stays excluded is what this bullet
  was actually guarding against: there is no *negotiation*. Nothing is discovered at runtime,
  nothing is probed, nothing is inherited across a process boundary, and no handler can change
  the answer once registration is over. A command states, once and statically, that a preview of
  it would lie; the framework refuses `--dry-run` for that command and says why. That is a
  declaration in exactly the same family as `effect` and `consequential`, which is why it
  belongs to the regime rather than contradicting it.
- **No inference** of classification from a command's name, tags, flags or handler body.
- **No partial preview fallback.** When the preview cannot continue it truncates loudly (§3.3);
  it never degrades to a best-effort guess.
- **No bypass flag.** There is no `--no-confirm`, no `--force-effects`, no way to disable the seal.
  `--approve-consequential` answers the prompt; it does not disable anything else.
- **No compatibility shim** for pre-classification commands. Every consumer classifies at its
  lock bump.

> **Amendment (2026-08-13, machine-interface round): the regime gains compositional child
> previews (§19.8) -- designed here, implemented later -- and the first bullet survives them
> intact.** A `spawn` or `run` declared **previewable** is, in dry mode, executed by the framework
> with `--dry-run --json` appended to the child's argv; the child's envelope is validated and its
> `preview` records are nested under the parent's record as `children` (§19.8, §14.2). Read the
> first bullet again and note that this is *precisely what it prescribes*: the mode is passed
> **explicitly in the child's argv, like any other flag**. Nothing is inherited, nothing is
> ambient, no environment variable carries a mode, and the child cannot tell how its argv was
> assembled. What stays forbidden is unchanged: a token that makes an unwitting child run dry.
>
> Two boundaries on the new capability, both fail-closed and both stated so the exclusion above is
> not quietly widened. It applies **only to declared effects** -- there is no discovery, no
> probing, and no attempt to guess whether an arbitrary child speaks the envelope. And a declared
> previewable child that does not produce a valid envelope, or produces one whose own
> `preview_error` is non-null, is a **hard error that truncates the parent's preview**: the
> framework will not silently degrade to recording a bare spawn, because a preview that quietly
> lost a subtree is exactly the "best-effort guess" the no-partial-fallback bullet forbids.
>
> **Status: designed, not implemented.** No implementation may adopt §19.8 partially. Its
> implementation trigger is stated in §19.8 and is external to this repository: the first
> envelope-speaking child in the fleet (the commit tool's migration) must exist before there is
> anything to compose with. Until then `children` is absent from every record, the `previewable`
> option is unregistered in all three implementations, and §12 carries no template for the
> failure above -- that template is authored at the implementation round.

`CONFORMANCE_EFFECT_LOG` (§14.3) is not an exception to the first bullet: it selects a diagnostic
*destination*, changes no behavior, is read only by the conformance harnesses (never by the
framework's dispatch path), and does not cross a process boundary as a mode.

`STRICTCLI_TRACE_PARENT` (§20) is not an exception either, and the reason is stronger than
`CONFORMANCE_EFFECT_LOG`'s. It carries an **identifier**, never a mode; the framework composes it
into a child's environment and never reads it back into a decision; and §20.2 makes
"no code path may branch on it" a ratified contract item enforced by conformance sweeps rather
than a promise. A variable no behaviour can depend on cannot inherit a mode.

---

## 17. Accepted ceilings

Recorded so implementors do not re-litigate them:

- **TypeScript**: plain-JS truthiness (`if (carrier)`) and `===` cannot be trapped by a `Proxy`.
  Lint-visible only (§11).
- **TypeScript**: the `effects-bypass` lint delivers **intra-file** reachability, not the
  intra-module reachability Python and Go deliver (§11.1). `typescript@7` ships no in-process
  parser -- only the scanner -- and the check is declared `fast` **and** `pure`, so spawning the
  native language server against a resolved tsconfig to obtain a syntax tree is not available. The
  concrete residual gap: a bypass in a helper defined in **another file** is not followed; names
  are matched as names, with no scope, shadowing or import resolution; method calls
  (`this.helper()`, `obj.helper()`) are not followed; and handler roots are recognized only through
  the literal `handler:` property spelling or an `.effects` mention. This is recorded rather than
  fixed because every available fix violates `fast` or `pure`. A consumer who wants the stronger
  guarantee keeps its effect-adjacent helpers in the file that registers the handler.
- **All three**: the lint's closed name lists are matched on the called name with coarse receiver
  gating, so name collisions with unrelated APIs (`str.replace` vs `os.replace`, `app.call` vs
  `subprocess.call`) are reported. Not narrowed: a lint that is the sole mitigation for the
  no-sandbox ceiling fails closed, and a false positive is a visible one-line fix where a false
  negative is silent (§11.1). The one carve-out, added 2026-08-09: a leaf whose collision is with
  a call the handle *could not carry* is receiver-gated, because there the one-line fix does not
  exist and the remediation line is a lie (§11.1's carve-out table).
- **Go**: extraction is a runtime panic, not a compile error. Non-comparability is the only
  compile-time protection available.
- **Go**: no compile-time ctx narrowing exists; the twin-factory affordance is TS-only.
- **Go**: carrier-accepting effect parameters are typed `any` (§2.5.5), so passing a wrong type is
  a call-time hard error rather than a compile error. Go has no union type; the alternative -- a
  sealed `Arg` interface with an `S("literal")` wrapper on every element -- was rejected as worse
  ergonomics for the overwhelmingly common all-literal case.
- **Go**: effect methods return `(carrier, error)` where Python and TypeScript raise/throw
  (§2.5.4). This is an idiom divergence, not a behavioral one: the same conditions produce a
  failure in all three. `check_error_parity.py` records it with an `impl_exclusions` rationale.
- **Go/TS**: a handler that calls `os.Exit` / `process.exit` renders no would-do log (§3.5). Both
  terminate the process outright -- Go documents that deferred functions do not run, and Node tears
  down without unwinding -- so there is no code the framework could place on that path. Python's
  `sys.exit` is *not* in this ceiling: it raises a catchable `SystemExit`, and §3.5 honours it. The
  rejected mitigation for TypeScript was a `process.on("exit")` hook that renders from the teardown
  callback: writes to a piped stdout are asynchronous there and can be dropped, so it would trade a
  silent miss for an intermittently truncated preview, which is worse than a documented ceiling. In
  both languages the idiomatic spelling of "end the run with status n" is a handler *return*, which
  renders correctly.
- **Go/TS**: guard v2 has no enforcement surface (§10.3).
- **The go-scope-adapter** stays parked; this contract does not touch it.

---

## 18. Decision provenance

This section is **exhaustive**: every decision in §§1-17 -- and, since the machine-interface round,
§§19-20, which are numbered after this section because sections here are never renumbered -- that
is not verbatim plan text is listed below, in one of three classes. If a statement in this document is not derivable from the ratified
pin list in the campaign ledger, it appears here.

### 18.1 User-ratified rulings folded in at the execution round (2026-08-02)

These are **ratified by the user**, not authored here. They amended an earlier draft of this
document after its adversarial audit, and they override anything that contradicts them.

1. **`skip_if_current` is preview-annotation-only** (§5.2). The earlier per-run "current set"
   evaluation model is deleted in full: no currency tracking, no skipping, no framework state.
   Dry mode renders the pinned conditional suffix; real mode executes unconditionally. Real-mode
   idempotency stays in handler code, which may branch on allowlisted-observe results because
   those return real values even in dry mode (§3.1, §6.2). `resource=` survives as declared
   metadata carried on the effect record (§5.1).
2. **Mutating passthrough commands prompt** (§8.1). The earlier passthrough exemption from the
   confirm protocol is deleted. A `mutating` passthrough prompts exactly like any other mutating
   command; `--yes` skips it; a `read_only` passthrough never prompts.
   *(Superseded in part by item 87: the prompt keys on `consequential`, not on classification, so
   a passthrough prompts on exactly the same terms as any other command -- which is what this item
   was really asserting -- and the skip flag is `--approve-consequential`. The no-exemption
   principle stands verbatim.)*
3. **Confirmed forced consequences** (ratified as forced, i.e. the user accepted that no
   alternative existed): TS `defineCommand` is removed and the twins are the sole registration
   surface (§1.2); the four additional `FILE_WRITE` log verbs stand (§3.2); `config set` is
   `mutating` (§9.2); framework-blessed `CACHE_WRITE`s execute even in dry mode (§3.1, §9.2);
   deprecated commands are classification-exempt (§1.1); framework-internal `**kwargs` handlers
   are rewritten or use declared forwarding under the module-verification hardening (§10.4).

### 18.2 Forced consequences (no design freedom existed)

Recorded so a reviewer does not mistake them for choices.

4. **`check --verbose` and `check --dry-run` are subsumed** (§7.5). Two flags cannot share a
   spelling, and the ban is unconditional; Go's check command must additionally gain the
   candidate-filter Python and TypeScript already have.
5. **Guard v2 enforcement is Python-only** (§10.3). Go handlers take `map[string]interface{}` and
   TypeScript handlers a typed args object; neither can be introspected for a var-keyword
   parameter. The *declaration* exists in all three so the API surface stays in parity.
6. **Truncation exits `1` and splits its streams** (§3.3): the already-recorded log to stdout, the
   pinned error text to stderr. Fail-closed admits no other outcome, and the log is dry mode's
   primary output so it must still be emitted.
7. **Observes execute in dry mode and are not logged** (§6.2, §3.2). An observe that did not
   execute could not return the real value the regime promises pre-mutation; an observe in the
   would-do log would misrepresent a read as a change.
8. **`--quiet` never suppresses the would-do log** (§3.4, §7.4). It is dry mode's primary output,
   not a diagnostic.
9. **Reserved-flag values are delivered on the Context, not as handler kwargs** (§7.2). Injecting
   four mandatory parameters into every handler would contradict guard v2 in the same release, and
   `Context` needs `quiet` / `verbose` / `dry_run` for its own gating regardless.
10. **A read-only dry run's would-do body is always empty** (§3.1). Observes are unlogged and
    cache writes are unlogged, so nothing can appear. The header is still emitted.

### 18.3 Spelling-level pins authored in this document

Mechanical decisions forced by the ratified semantics. None changes a ruling; each fixes a
spelling the pin list left open.

11. **Log line layout** -- `  <N>. <verb>: <detail>`: two-space indent, unpadded 1-based number,
    `. ` after the number, `: ` after the verb. The pin fixed "numbered verb-prefixed lines"
    without fixing the punctuation.
12. **Four additional verbs** -- `mkdir:`, `remove:`, `rename:`, `chmod:`. The pin named the verbs
    for the four kinds whose spelling was in question (`run:`, `write:`, `net:`, `spawn:`); the
    remaining four `FILE_WRITE` methods need verbs of their own, and reusing `write:` for
    `mkdir` would read as nonsense. The **kind** set is unchanged.
13. **Detail spelling per verb** -- byte count as `<path> (<n> bytes)`, rename as `<from> -> <to>`,
    chmod mode as leading-zero octal, `http` as `<METHOD> <url>`.
14. **Suffix ordering** -- grant suffix before conditional suffix when both apply.
15. **The four reserved flags have no short forms**, and the ban covers long flag names at every
    level but not arg names or short names.
16. **Concrete reserved-flag accessor names per language** (§7.2).
17. **`--quiet` + `--verbose` together is silently quiet**, not an error and not a mutex; the
    gating table of §7.4 and its never-suppressed list.
18. **Confirm answer grammar** -- exactly `y`/`Y` proceeds; everything else including EOF
    declines; decline prints `aborted` to stderr and exits 1.
19. **Programmatic dispatch behaves as if `--yes`** (§8.4) -- `test`, `call`/`Call`/`invoke` and
    the MCP server never prompt and never emit the non-TTY error, and `--dry-run` is not reachable
    through them. The only non-hanging option for callers with no TTY contract.
    *(Flag renamed by item 88 to `--approve-consequential`; the behaviour is unchanged. Also
    corrected by item 78 on `--dry-run` reachability through `test()`.)*
20. **Go's TTY check uses `os.Stdin.Stat()` + `os.ModeCharDevice`**, keeping the Go package
    zero-dependency. *(Narrowed by item 90: the mode check alone reads the null device as
    interactive, so the check additionally excludes a stdin that `os.SameFile`s `os.DevNull`. Still
    zero-dependency.)*
21. **Python's `__repr__` is the single non-poisoned dunder**, and `__class__` stays intact so
    `isinstance` works at the forwarding boundary; `__str__` and `__format__` ARE poisoned
    (stringifying a carrier in handler code is extraction, not forwarding).
22. **Go's carriers are made non-comparable via a `[0]func()` field**; brand read through an
    unexported `brandForm()`.
23. **TS Proxy exemptions are exactly three** -- the internal brand symbol,
    `Symbol.toStringTag`, and the Node inspect symbol.
24. **Grant `kind` is drawn from the effect-kind enum** and must match the effect it is used on;
    grant names match `[a-z][a-z0-9-]*`.
25. **`proc_observe_allowlist` matching is element-wise argv-prefix string equality.**
26. **`CACHE_WRITE` is unreachable from application code** and its site list is closed at three
    (§9.2); the five `config` subcommands' classifications are pinned in the same section.
27. **Declared forwarding mirrors `Passthrough`'s registration shape** and carries a mandatory
    `reason`.
28. **The bypass check is named `effects-bypass`** with the tag/severity/fast/pure/network values
    in §11.
29. **Error-template function names** (§12) follow the existing `err*` catalog convention, one
    function per template in Go and TS.
30. **Go templates that interpolate nothing are `const`s, not functions** (§12 preamble), matching
    `errors.go`'s existing style; TypeScript keeps a parameterless function. Affects
    `errConfirmNonInteractive` and `errConfirmDeclined`.
31. **Schema emission rules** (§13) -- `effect` always emitted (no default to omit against);
    `grants`, `forwarding` and `proc_observe_allowlist` omitted when empty.
32. **`effects_equals` compares a structured effect log**, whose record shape is `$defs/
    effect_record` (§14.2), delivered through the `CONFORMANCE_EFFECT_LOG` file handoff (§14.3)
    modelled on the existing `CONFORMANCE_APP_DEF` pattern, read via a test-only
    `App.effect_log()` accessor.
33. **`handler_effects` is the harness vocabulary extension** (§14.4), with `forward_from` and
    `extract_from` as 1-based back-references and `extract_from` terminal.
34. **Observes do not appear in the structured effect log either** (§14.2). Derived from the
    pinned `kind`/`verb` enums, which have no observe member; recording one as `proc_mutate`/`run`
    would make a read indistinguishable from a change.

The following pins were authored at the execution round, alongside the §18.1 rulings.

35. **The eight methods' parameters** (§2.5.2): `run(argv, cwd, env, check, stream)`;
    `spawn(argv, cwd, env)`; `write(path, content)`; `mkdir(path)`; `remove(path)`;
    `rename(src, dst)`; `chmod(path, mode)`; `http(method, url, body, headers, check)`. No method
    accepts a shell string. `env` merges over the inherited environment rather than replacing it.
36. **`mkdir` creates missing parents and tolerates an existing directory; `remove` is recursive
    and tolerates a missing path** (§2.5.2). One behavior each, no mode flags -- the would-do log
    shows exactly which path is affected, which is the regime's answer to the danger.
37. **Three result shapes** -- `Completed` (`exit_code`, `stdout`, `stderr`), `Spawned` (`pid`,
    `wait()`), `Response` (`status`, `body`, `headers`); the five path-mutating methods return no
    value (§2.5.1).
38. **`Spawned` is the reading of the pin's "spawn returns the same as run"** (§2.5.1): a minimal
    handle whose `wait()` yields exactly `run`'s `Completed`. §2.2 pins spawn as
    "without waiting", so the shapes are made identical at the point the result exists rather than
    at call time. This is the one place where the ratified direction admitted more than one
    reading; the alternative (returning `Completed` directly, i.e. waiting) contradicts §2.2.
39. **`stdout` / `stderr` are text, not bytes** -- decoded UTF-8 strictly, one trailing newline
    removed (§2.5.1). Chosen because it is the form that can be forwarded straight into a later
    effect's argv, which is what lets one piece of handler code be correct in both modes.
40. **Error semantics: a failed operation is an error, not a value** (§2.5.4). Nonzero exit and
    non-2xx status fail the call by default; `check=false` opts a single call out. Raising by
    default keeps previews long (a handler that never tests a status never branches on a carrier),
    and the opt-out is required for the §5.2 idempotency idiom, whose commonest predicate is an
    exit code.
41. **Go effect methods return `(carrier, error)`** where Python and TypeScript raise (§2.5.4,
    §17). Idiom divergence only; recorded with an `impl_exclusions` rationale.
42. **Go returns a carrier type always** (§2.5.3): `Completed`, `Spawned` and `Response` are
    settleable carriers whose extractors return real values in live mode and panic when unsettled;
    the payload-less `Unsettled` of §4.4 is the void carrier returned by the five path-mutating
    methods, giving Go one uniform return shape. (The original rationale -- "so a `write` result
    stays forwardable" -- is superseded by item 61: void results are never forwardable.)
43. **The forwarding boundary and its scalar projections** (§2.5.5): a carrier is accepted for any
    `argv` element, `path`, `src`, `dst`, `url` or `content`; `Completed` projects to `stdout`,
    `Response` to its decoded `body`, `Spawned` to nothing. Reading a member of a carrier remains
    extraction.
44. **Go types carrier-accepting parameters `any`** (§2.5.5, §17), hard-erroring at call time on
    anything that is neither the natural Go type nor a carrier.
45. **TS passthrough twins are `readOnlyPassthrough` / `mutatingPassthrough`** (§1.2), splicing
    the classification into the existing factory name exactly as the command twins splice it into
    `defineCommand`. `passthrough` is removed; `PassthroughDef` gains `effect` and `grants`.
46. **`describe.ts` gains two command-factory descriptors and two passthrough descriptors**, with
    two spec types `ReadOnlyCommandSpec` / `MutatingCommandSpec` because the twins' handler
    signatures differ; the `defineCommand` and `passthrough` descriptors are deleted, not renamed
    (§1.2).
47. **The conformance schema encodes the deprecated exemption as an `else` branch**, not as a
    top-level `required` entry (§13) -- a top-level `required` applies conjunctively with the
    existing deprecated `then` and would make `effect` mandatory on deprecated entries.
48. **`errDeprecatedCommandEffect`** (§12.2) enforces the exemption in the one enforceable
    direction.
49. **Framework-internal commands use declared forwarding plus a private marker and module
    verification** (§10.4), with the fixed reason string
    `framework-internal: absorbs app-defined global flag values`; the marker is unreachable from
    any public API and a foreign handler carrying it is `errFrameworkInternalHandlerForeign`
    (§12.9).
50. **The `config` group's direct-`Command`-construction bypass is deleted** (§10.4): all five
    subcommands route through the single validated registration path, in every implementation.
51. **§12.8's failure templates** -- `errEffectRunFailed`, `errEffectHTTPFailed`,
    `errEffectOutputNotUTF8`, `errEffectParamRejectsCarrier`.
52. **`coverage_deferred` `SIGNATURE_STATUS` entries** for the confirm-protocol templates and
    `errEffectHTTPFailed` (§14.5), reusing the runner's existing stdin-piping rationale string
    verbatim.
53. **`RICH_APP`'s fixture edit is mandatory** (§14.5): it lives in `check_schema_parity.py` and
    every one of its command entries gains `effect`, even though that file's comparison logic is
    unchanged.
54. **`check --dry-run` gains a trailing dry-run header** (§7.5), so its existing assertions must
    be updated.

The following pins were authored at the amendment round (2026-08-03), closing the residual gaps a
re-audit found. Every one is forced or spelling-level; none reopens a ratified ruling.

55. **TypeScript declares the settled return types only** (§2.5.3, §2.5.6): `Completed`, `Spawned`,
    `Response`, `void`, with no `| Unsettled` union anywhere in the surface. Forced by the
    one-body-both-modes model the whole regime rests on -- a declared union would oblige every
    handler to narrow before use, and narrowing is mode-branching.
56. **There is no `isUnsettled()` predicate, type guard or discriminant member** (§2.5.3). The same
    reasoning from the other side: a predicate is exactly the silent mode-branch the truncation
    mechanism exists to prevent. A handler that legitimately needs the mode reads `ctx.dryRun`
    (§7.2); no property of a carrier answers that question.
57. **TypeScript's carrier-accepting parameter types** (§2.5.5): `string | Completed | Response`
    for every `argv` element and for `path`, `src`, `dst` and `url`;
    `string | Uint8Array | Completed | Response` for `content`. Written inline in the signatures,
    minting no exported type and therefore no new `describe.ts` entity.
58. **`url` is carrier-accepting** (§2.5.2, §2.5.5, §2.5.6): `any` in Go, the union above in
    TypeScript. §2.5.5's accept list already named it while §2.5.6's Go signature typed it
    `string`; the signature was the error and is corrected. `method` and `body` remain excluded.
59. **`body` is not carrier-accepting** (§2.5.5, §12.8), which is what finally makes the exclude
    list exhaustive over §2.5.2. A request body is a payload, not a name, and a preview that
    forwarded one would have to render an arbitrary blob into a log line.
60. **A `write` whose content is an unsettled carrier renders the brand where the byte count goes**
    (§3.2) -- `write: <path> («step N output»)` -- and that effect's record carries `bytes: null`
    (§14.2). Nothing produced those bytes, and inventing a count is the one thing §0 forbids. Keyed
    on unsettledness, not on carrier-ness: a *settled* forwarded result (a pre-mutation observe's
    `Completed`, which is real even in dry mode) projects normally and renders a real count.
61. **Void results are never forwardable** (§2.5.5, §12.8): forwarding one is a call-time hard
    error in **both** modes and in all three implementations, in the
    `errEffectParamRejectsCarrier` family. This supersedes the original rationale for Go's void
    carrier (item 42) -- it exists to give Go's carrier-always model one uniform return shape, not
    to make a `write` result forwardable -- and §4.1's categorical "nothing else ever produces one
    / callers get real values" is amended to carve Go's carrier-always model out explicitly.
62. **An option a method does not accept is a call-time hard error** (§2.5.2, §12.8) in all three,
    `errEffectOptionNotAccepted`. Go validates its `...EffectOption` variadic at call time, and its
    options carry a canonical snake_case name so the rendered message is byte-identical across the
    three. Silently ignoring an inapplicable option is the one outcome declare-everything cannot
    have.
63. **`Spawned.wait` accepts `check`, with the same opt-out semantics as `run`** (§2.5.1, §2.5.2,
    §2.5.4, §2.5.6), defaulting to `true`. Without it no handler could read a spawned child's
    nonzero exit code -- the same gap `check=false` closes for `run`, and the §5.2 idiom's
    commonest predicate.
64. **`grant=` on an allowlisted observe is a call-time hard error** (§6.1, §6.2, §12.4),
    `errEffectGrantOnObserve`. A grant labels a recorded step in the preview; an observe is never
    recorded and never logged, so there is nothing for the label to appear on. A declaration that
    cannot mean anything is an error, not a no-op.
65. **TypeScript's module verification is a package-internal `WeakSet<Function>` of
    framework-created handler identities** (§10.4): declared in `typescript/src/app.ts`, written by
    the two modules that mint internal handlers, never re-exported from `typescript/src/index.ts`,
    keyed on function identity because `name` and source text are both forgeable, and weak so a
    discarded handler stays collectible.
66. **The structured effect log is populated in both modes** (§14.2, §14.3), live entries carrying
    `recorded: false`, and **`recorded` is a required key** of `$defs/effect_record`. Required is
    what kills the absent-versus-null ambiguity §14.1's equivalence rule would otherwise create,
    where "absent" would have had to mean both "live" and "unstated" at once.
67. **Conformance coverage for the two new templates, with no deferral** (§14.4, §14.5).
    `errEffectGrantOnObserve` needs no new vocabulary. `errEffectOptionNotAccepted` needs one key:
    `$defs/handler_effect` gains `stream` (boolean), the only method-specific option that both is
    accepted by exactly one method and, in Go, is an ordinary `EffectOption` every method takes
    syntactically -- so `{"method": "mkdir", "path": "d", "stream": true}` produces the same error
    in all three. The harnesses' pass-the-declared-keys-verbatim rule is pinned in the same place,
    since it is what makes such a case reach the call at all.

The last two were authored at the earlier execution round and omitted from this section by
oversight. They are recorded here so §18 is exhaustive; neither is new.

68. **`Response.headers` is keyed by lower-cased header name** (§2.5.1). HTTP header names are
    case-insensitive, so a mapping that preserved the wire casing would make a handler's lookup
    depend on the server's spelling.
69. **Absent optional keys and explicit nulls are equivalent under `effects_equals`** (§14.1).
    Now superseded for `recorded`, which item 66 makes required and therefore never absent; the
    equivalence continues to govern every other optional key, `bytes` (item 60) above all.

The following pin was **ratified by the user** at the closing round (2026-08-03), after the
execution of the Python implementation surfaced that items 55-57 had been written for TypeScript
alone.

70. **Python declares the settled return types only, and pins its carrier-accepting parameter
    annotations** (§2.5.3, §2.5.5, §2.5.6). Ratified: exactly the ruling items 55 and 56 made for
    TypeScript, applied to Python for exactly the same reason. A declared
    `-> Completed | Unsettled` obliges a type-checked caller to narrow before touching `.stdout`,
    and narrowing on unsettledness is mode-branching -- the thing the truncation mechanism exists
    to make honest. The declared returns are therefore `Completed`, `Spawned`, `Response` and
    `None`, with no `| Unsettled` union and no `is_unsettled()` predicate; the six
    carrier-accepting positions are annotated `str | Completed | Response`
    (`Sequence[str | Completed | Response]` for `argv`, `str | bytes | Completed | Response` for
    `content`), mirroring item 57's TypeScript unions. Runtime behavior is unchanged: dry-mode
    post-mutation calls still return the `Unsettled` carrier and its poisoned dunders still fire on
    extraction. Every other parameter stays unannotated -- the annotations pin the forwarding
    boundary and the return shape, which are the two things a caller could otherwise be misled
    about, and nothing else.

### 18.4 User-ratified rulings folded in at the conformance-and-parity round (2026-08-03)

These are **ratified by the user**, not authored here. They amend this document after the three
implementations shipped; each is marked in place at the section it changes.

71. **Where the three implementations agree against this document's draft text, the
    implementations win and the document is amended.** The governing ruling of the round; it
    inverts the precedence clause of the preamble for this round only. Its one concrete
    application is item 72.
72. **`errEffectGrantOnObserve` takes no argv parameter** (§12.4, ruling A). The draft pinned
    `... cannot be used on an observe; effects.run argv <argv> is on the app's
    proc_observe_allowlist`; all three implementations shipped
    `... cannot be used on an observe (an allowlisted effects.run changes nothing)`, which states
    the reason rather than restating the caller's own argv. The shipped wording is now the pinned
    wording, and the function signature drops to `(name, g)`.
73. **Go's environment option is `EffectEnv(map[string]string)`** (§2.5.2, §2.5.6, ruling B). The
    pinned `Env` spelling collides with the package's existing `Env(varName string) FlagOption`
    and Go has no overloading. Only the constructor moves; the canonical snake_case option name
    stays `env`, so `errEffectOptionNotAccepted` stays byte-identical across the three.
74. **Python gains an explicit `errEffectOptionNotAccepted`** (§2.5.2, §12.8, ruling C),
    through a `**_options` catch-all on each of the eight methods, raised as a `TypeError` (which
    is what CPython itself raises for an unexpected keyword, and what every other call-time
    argument guard on the handle raises) and made visible to the parity extractor by a `_msg_*`
    function. Forced by §14.5's own conformance case: `{"method": "mkdir", "path": "d",
    "stream": true}` must produce the byte-identical message in all three, and CPython's native
    `unexpected keyword argument` wording is not it.
75. **Python's four path positions widen to include `os.PathLike[str]`** (§2.5.5, §2.5.6,
    ruling D). The runtime already resolved them through `os.fspath`; a PEP 561 package must not
    type-error on `Path("out.txt")`. The §2.5.5 row is the unit -- `path`, `src`, `dst` and `url`
    widen together, because they share one resolver and a surface where some of them accept a path
    object and others do not would be incoherent. `argv` elements and `content` are unchanged.
76. **Templates present in the implementations but absent from §12 are added to §12, not deleted
    from the code** (§12.10, ruling E). Each names a real fail-closed guard; deleting a guard to
    satisfy a document is backwards. One canonical wording each, byte-identical wherever the
    template exists, with per-implementation exclusions recorded where a language's static typing
    makes the guard unreachable.
77. **The catalogs' category placement is pinned** (§12 preamble, ruling F): parse-time is exactly
    §12.5, §12.6 and §12.8; everything else is registration-time. Go's and TypeScript's section
    markers are brought into agreement so that the coverage requirements this document prescribes
    actually bind.

### 18.5 Amendments made at the spec-audit remediation round (2026-08-03)

A spec-only audit of this document against the three shipped implementations found seven defects
and six places where this document was silent or wrong. The implementation defects were fixed in
code; the six documentation items are amended in place and listed here. Every one of them is
**authored at this round**, not ratified upstream, and each is written to be reversible by naming
the alternative it rejected.

78. **§8.4's programmatic-dispatch clause is corrected (D1).** It claimed `--dry-run` is
    unreachable through `test()`, `call()`/`invoke` and MCP because "they bypass argv parsing
    entirely". `test()` does not bypass argv parsing -- it takes and parses argv exactly as the CLI
    does, and the unit suites of all three implementations rely on `app.test(["--dry-run", ...])`
    entering dry mode. The clause is now scoped to the three paths that really do take pre-typed
    kwargs. No behavior changed; the document was simply wrong.
79. **§8.2 pins the confirm answer's line terminator (D2).** It is exactly one `\n`, then exactly
    one `\r`, and nothing else. Go already stripped the carriage return, Python and TypeScript did
    not; the document was silent, so the divergence was invisible. Go's behavior is the one that is
    right for a human at any console -- a Windows terminal terminates the line CRLF, and refusing
    a `y` because of it would refuse an answer that was plainly given -- so Python and TypeScript
    were brought to it rather than the reverse. Stripping *only* the terminator, rather than
    whitespace, is what preserves this section's existing rule that `"  y"` declines. The
    alternative rejected: leaving Go to strip and the others not, which is a silent per-platform
    behavior split in the one prompt the user actually answers.
80. **§3.2, §4.2 and §14.2 pin the sequence numbering (D3).** The would-do number is contiguous
    over **rendered lines**; cache writes carry an independent counter. All three implementations
    had cache writes consuming would-do numbers, so a `test_coverage=True` dry run began its
    preview at `2.` and every `«step N output»` brand and truncation "ends at step N" shifted with
    it -- three user-visible strings moved by a record the reader can never see. The alternative
    reading (contiguous over all records, cache writes included) was rejected because it makes the
    rendered output depend on an invisible bookkeeping detail.
81. **§6.2 states the allowlist-breadth hazard plainly and §11 adds a WARN check (D4).** A
    single-token prefix such as `["git"]` exempts an entire binary: every matching invocation
    executes for real under `--dry-run`, is never logged, and is legal in a `read_only` command.
    No specificity rule was invented -- §0's zero-inference rule forbids one, and the allowlist is
    a declared, source-visible app-level choice that legitimately authorizes real execution in dry
    mode. The response is documentation plus a warning: `observe-allowlist-breadth`, severity
    `warn`, cleared by `--ignore-warnings`. Rejected: making it an error (a one-token prefix can be
    correct) and making the framework narrow the prefix itself (policy the app did not write).
82. **§11 is rewritten to describe what each language actually delivers (D5).** The section
    prescribed "reachable from a registered command handler"; all three implementations shipped "a
    call inside a function whose own body mentions `.effects`", which two trivial shapes escape.
    Python and Go now implement intra-module and intra-package reachability from handler roots.
    TypeScript cannot -- `typescript@7` has no in-process parser and the check is `fast` + `pure`
    -- so it implements the closest scanner-level approximation (a token function table plus an
    intra-file call graph rooted at `handler:` properties) and the residual gap is recorded in §17
    rather than left as a guarantee the implementation does not deliver. The closed name lists were
    deliberately **not** narrowed to offset the widened scope; the imprecision is recorded in §17
    instead, because a lint that is the sole mitigation for a ceiling must fail closed.
83. **§4.4 adds `__setattr__` to the poisoned-dunder list (D6).** The list is presented as
    complete, and `__setattr__`'s absence let `u._brand = "«forged»"` mint a fake preview line and
    `u._forwardable = True` make a void carrier forwardable -- both pins of §2.5.5 defeated from
    Python only, since Go's carrier fields are unexported and TypeScript's Proxy already traps
    `set`. `__delattr__` is deliberately **not** added: deleting a slot cannot forge anything (a
    subsequent read hits the poisoned `__getattr__` and truncates), so poisoning it would be a
    guardrail against nothing.

§9.2 additionally gained the table of effects the three mutating `config` subcommands now mint. It
is not a new decision -- the classification was already pinned and the handlers simply did not obey
it -- but it is recorded there because the previous text stated the classification without stating
that the mutations must ride the handle, and that gap is exactly what the implementations fell into.

### 18.6 Amendments made at the adoption round (2026-08-04)

The regime shipped, and the first consumer migrated onto it. Migration falsified two pins. This
round is governed by the same precedence rule item 71 established for implementations, extended
one step further: **where adoption contradicts this document's draft, adoption wins.** A pin whose
only evidence was the draft author's intuition does not outrank the first real invocation that
exercises it.

84. **The reserved quartet is recognized anywhere in argv (§7.2, ruling A1).** The draft pinned it
    to the pre-command region only, so `app cmd --dry-run` was `unknown flag '--dry-run'`. Every
    documented invocation in this ecosystem -- including the release protocol the consumer's own
    docs prescribe -- writes these flags *after* the command name, and the consumer had to rewrite
    argv before handing it to the framework to make its own documented commands work. That
    workaround would have had to ship to every consumer in the fleet. The precedent for the fix was
    already in the framework: `--help` / `-h` has always been recognized anywhere in argv, and the
    quartet now uses the identical scan shape with the identical accepted cost (a flag *value*
    spelled like a reserved token is eaten; `--flag=--dry-run` and `--` express the literal). The
    draft also had the semantics backwards: `--dry-run`'s applicability is per-command, so
    requiring it before the command name asked the user to declare a per-command fact before naming
    the command. Rejected alternatives: keeping the pin and shipping the argv-rewriting shim to
    ~23 consumers (a framework defect paid for by every consumer, forever); and making the quartet
    an ordinary auto-registered command flag (it would then appear in every command's help, collide
    with guard v2's signature validation, and reach handlers as kwargs, all of which §7.2 forbids
    for stated reasons that did not change).
85. **A passthrough command's args are the one boundary the quartet does not cross (§7.2.1,
    ruling A1).** The pre-command region's old stopping rule kept passthrough args opaque as a side
    effect; making the quartet position-free removed that side effect, so opacity is now stated
    directly and enforced by the routing walk. A passthrough is *defined* as forwarding its args
    raw (§1.2), and eating a child process's own `--verbose` would both change what the child does
    and strip the flag from its argv -- a silent, lossy edit of another program's input by a
    framework that cannot see what that program does. The pre-command position remains a lossless
    escape hatch, so nothing became unreachable. `--help`'s interception on the passthrough path is
    deliberately left alone: it is pinned separately, and printing help is visible and harmless
    where rewriting a child's argv is neither.

86. **The would-do log renders on every exit path out of a dispatch (§3.1, §3.5, §12.11, D7).**
    The draft pinned the render to "successful completion", and all three implementations
    implemented exactly that: a `mutating` handler that recorded effects and then left through
    `sys.exit(1)`, an exception or a panic printed **nothing at all** -- no header, no lines --
    even though the effects were recorded correctly. Adoption found it on a documentation `check`
    command that records a baseline write and then exits 1 when lints fail, which is the shape of
    every validation handler in this ecosystem: the runs where a reader most wants the preview are
    exactly the runs that lost it, and the silence was indistinguishable from "this command would
    do nothing". Safety was never at risk (nothing executed); honesty was, which is the property
    the regime exists to sell. The render is now owned by the single seam each implementation
    already funnels every dispatch through -- Python's exhaustive `BaseException`-rooted clause set,
    Go's `runSealed`, TypeScript's `runHandler` -- rather than by a list of paths that must each
    remember to call it, because that list is precisely what was incomplete. Three rulings inside
    the fix, each authored here:
    - *A deliberate exit renders what an equivalent return renders*, byte for byte and with no
      marker. **Rejected**: marking `sys.exit` as an abort. `sys.exit(1)` and `return 1` are one
      intent in two spellings, and making the preview depend on which one a handler happened to
      use would have shipped a second silent inconsistency in place of the first.
    - *An unexpected unwind renders the log AND a marker* (§12.11), log to stdout, marker to
      stderr, exception re-raised untouched. **Rejected**: rendering nothing on the crash path, on
      the reasoning that a partial preview misleads. It is the inverse -- the recorded effects are
      real and the reader is owed them; what they must not be told is that the list is complete,
      and one stderr line says exactly that while leaving stdout a clean preview. Also
      **rejected**: swallowing the exception to synthesize an exit code, which would have hidden a
      crash behind a tidy status and put the framework in charge of an error it knows nothing
      about. The marker deliberately reuses §12.5's `ends at step N: <cmd>` shape so the two
      early-ended-preview messages read as one family, and says "may be incomplete" rather than
      "is incomplete" because after an escaped exception that is the exact extent of what the
      framework knows.
    - *`os.Exit` / `process.exit` stay uncovered* and are recorded as a ceiling (§17).
      **Rejected**: a Node `process.on("exit")` render hook, which would write to stdout from a
      teardown callback where piped writes are asynchronous and droppable -- trading a silent miss
      for an intermittently truncated preview. Python's `sys.exit` is not in that ceiling precisely
      because it is an exception rather than a process teardown, so the asymmetry is a property of
      the three languages, not a parity gap: in all three, a handler *return* renders correctly,
      and that is the idiomatic spelling everywhere.

### 18.7 Amendments made at the consequence round (2026-08-04)

The regime shipped, six consumers adopted it, and adoption falsified the confirm protocol's
central inference. This round is governed by the same precedence rule item 84 established:
**where adoption contradicts this document's draft, adoption wins.** The rulings below are
**user-ratified**, not authored here, except where marked.

87. **The confirm protocol keys on a declared `consequential`, not on classification (§8, ruling
    C1).** The shipped regime inferred "mutating ⇒ must confirm". The evidence against it is
    counted, not felt: **391 of 624 commands across six consumers (63%) classify `mutating`**, so
    two thirds of every CLI in the fleet prompted -- including `safegit commit`,
    `rlsbl changelog add`, `selfdoc gen`, `saferm delete` (the *safe*, undoable deletion) and
    `claudewheel launch`, which had to be special-cased or every session would have opened with a
    `Proceed? [y/N]`. The genuinely dangerous commands are ~5-10% of that set: a **~1:10
    signal-to-noise ratio**, which guarantees the skip flag is passed reflexively and leaves the
    guardrail dead while it still *looks* present -- worse than absent, because the appearance is
    what a reviewer sees.

    The diagnosis is that **one field was answering two questions.** `effect` correctly answers
    *"should a dry run record rather than execute?"* -- almost everything that touches anything
    answers yes, which is right, and that machinery is working and untouched. Consequence asks
    *"are these effects worth interrupting someone for?"* -- almost nothing answers yes. `effect`
    was never an answer to the second, only a proxy, and the proxy is off by an order of magnitude.

    **Rejected alternatives**, each recorded so the ruling is reversible:
    - *Keep blanket confirmation and let consumers live with it.* This is the status quo whose
      failure the numbers describe; the reflex it trains is the failure.
    - *Name the declaration `confirm=True`.* Rejected because it names the framework's REACTION,
      not a property of the command. Consequence is a fact the author knows and the framework never
      could; the prompt is one thing the framework currently chooses to do about it. Naming the
      field after the reaction would weld them together and make every later use of the same fact a
      second, redundant declaration.
    - *App-level opt-in* (`createApp({confirmMutating: true})`), keeping the inference but letting
      an app turn it off wholesale. Rejected because it moves the decision to the wrong grain: the
      1:10 ratio is a property of the command set, not of the app, and an app-wide switch means
      either every command prompts or none does -- which is the same failure with an extra flag.
    - *Accept the break but keep a short skip flag.* Rejected: see item 88.

88. **The skip flag is `--approve-consequential`, and `yes` stays banned (§7.1, §7.3, §12.1,
    ruling C1).** The quartet becomes `dry-run`, `approve-consequential`, `quiet`, `verbose`.
    **The unwieldiness is deliberate and is pinned here so a later round does not "fix" it**:
    `--yes` is short, familiar and already reflexive in every shell, so it was destined to become
    muscle memory and be appended without thought. A flag that cannot become muscle memory stays a
    decision. There is no short form and there will never be one. `yes` is kept on the banned-names
    list -- it names no framework flag any more, which is exactly why releasing it would be a
    mistake: a consumer's private `--yes` would restate `--approve-consequential` in the very
    spelling this rename removed. Its ban message is its own template and points at the
    replacement (`errFlagNameYesBanned`). Context accessors move with it:
    `ctx.approve_consequential` / `ctx.ApproveConsequential()` / `ctx.approveConsequential`.

89. **The `interactive=True` confirm-suppression ruling is walked back (§8.1.1, ruling C1).** An
    earlier ruling exempted `interactive` commands from the confirm protocol so a command whose
    whole purpose is to talk to the user would not open with an unrelated prompt. Under the
    declaration the carve-out is unnecessary and therefore wrong to keep: `claudewheel launch` is
    `mutating` and not consequential, so it never prompts, with no exemption anywhere. It was never
    implemented in any of the three sources -- the walk-back is documentary, and its point is that
    no such suppression is to be added. `interactive`'s other, unrelated meaning (visible in help,
    excluded from tool export) is untouched.

90. **Go's TTY check excludes the null device (§8.3, authored at this round).** Surfaced by the
    new conformance coverage, not by the redesign. §8.3 pinned Go to
    `fi.Mode() & os.ModeCharDevice != 0` alone, and `/dev/null` *is* a character device, so
    `myapp cmd < /dev/null` -- and every subprocess launched with a null stdin, which is what CI
    runners and test harnesses do -- read as **interactive** on Go and non-interactive on Python
    and TypeScript: one invocation, two behaviours, invisible because no case had ever run with a
    non-TTY stdin. Go now also rejects a stdin that `os.SameFile`s `os.DevNull` -- stdlib-only and
    portable (`NUL` on Windows), so zero-dependency is preserved. **Rejected**: giving the
    conformance runner a pipe instead of the null device, which would have made the suite pass
    while leaving the divergence shipped; and adding `golang.org/x/term`, which trades a real
    dependency for a pathological residual case (`/dev/zero` as stdin still reads as interactive on
    Go, and is recorded as an accepted ceiling instead).

91. **The bypass provider gains `consequential-grant-agreement` at `warn` (§11.0, authored at this
    round).** A grant exists so a reviewer sees why a dangerous step is there (§6.1) -- the same
    judgement `consequential` makes, at per-effect grain. It fires only for `proc_mutate` and
    `net_mutate`, the two kinds that leave the process and cannot be walked back. **Rejected**:
    flagging every grant kind, which would rebuild the 1:10 noise ratio inside the lint;
    and `error` severity, which would make the declaration mandatory through the back door --
    consumers would add `consequential` to clear a red gate rather than because they judged the
    command consequential, re-creating the exact reflex this round removed one layer up. The
    severity precedent is `observe-allowlist-breadth` (item 81): a "these declarations disagree and
    either could be right" finding, cleared by `--ignore-warnings`.

92. **Conformance pins every case's stdin to the null device (§14.5, authored at this round).** A
    case must never depend on whether the operator ran the suite from a terminal. The immediate
    payoff is that `errConfirmNonInteractive` stops being `coverage_deferred` and becomes an
    ordinary covered template in all three targets; the immediate cost was item 90, which the
    pinning is what found.

### 18.8 Amendments made at the non-CLI consent round (2026-08-11)

93. **The confirmation requirement is honoured on every channel, not only the terminal one (§8.4,
    §8.5).** The shipped regime enforced it at exactly one entry point. Everywhere else the same
    condition -- no terminal -- produced the opposite outcome: `exit 1` on the CLI path, silent
    proceed on `call` and over MCP, with nothing announcing the difference. Worse, the two
    non-CLI channels could not even see the declaration: the tool descriptors and the MCP
    `tools/list` `inputSchema` carried flags and args only, so a consumer rendering a tool was
    never told which ones were consequential.

    The resolution keeps the declaration a property of the command and gives every channel a way
    to honour it: publish the classification beside the descriptor (never inside the argument
    schema), and require the programmatic caller to state consent in the call. The honest limit,
    recorded so nobody mistakes this for approval: **a caller can always supply consent.** The
    point is that it must now say so somewhere recordable, rather than the framework answering for
    it.

    **Rejected alternatives**, each recorded so the ruling is reversible:
    - *Refuse consequential commands over MCP entirely.* Doctrinally cleanest -- consequential
      means interrupt a human, and MCP has none -- but it removes the capability with no path back
      short of a terminal.
    - *Filter consequential commands out of the tool list*, the way `hidden` and `interactive`
      already work. Same breakage, and it hides the capability rather than declining it.
    - *Keep auto-approving and document it as terminal-only.* Nothing breaks, and the declaration
      means nothing outside one caller.
    - *Carry consent inside the MCP `arguments` object.* It would collide with the command's own
      argument namespace, which is published with `additionalProperties: false`, and a strict
      client would refuse to send a key the schema does not declare.
    - *Make `consequential` a property of the (command, channel) pair.* A coherent alternative with
      a very different downstream shape; it changes the registration surface in all three
      implementations and was not needed to close this hole.

94. **`test()` keeps its as-if-approved behaviour (§8.4, authored at this round).** It parses argv
    exactly as the CLI does, so a caller who wants the flag's semantics can write the flag; and
    every unit suite in the fleet drives consequential commands through it. Item 93 applies to the
    argv-bypassing paths only.

95. **Conformance grows a programmatic-call entry point and a case-level `stdin` (§14, authored at
    this round).** The harness drove argv and subprocesses only, which cannot reach `call()` at
    all and cannot feed the MCP server its JSON-RPC lines. Both extensions follow the `pre_test`
    precedent: one app-definition field consumed by each language adapter in a few lines
    (`pre_call`, plus `dump_tools` for the descriptor classification), and one case field
    (`stdin`) that run.py hands to the subprocess. Item 92's property is preserved -- a pipe
    carrying the case's own text is not a TTY either. The three MCP cases carry an
    `acknowledged_divergence` for stdout: the JSON-RPC wire form is each language's own encoder
    (Python spaces its separators, Go sorts map keys and renders an empty list as null), which was
    never part of the contract.

### 18.9 Amendments made at the machine-interface round (2026-08-13)

This round records rulings made upstream in a cross-repository campaign that resolved stream
ownership, machine output and process ancestry together. Items 96-110 are **ruled upstream**, not
authored here; items 111-112 are authored spellings in the §18.3 class (mechanical decisions
forced by the ruled semantics, fixing spellings the rulings left open). The round writes §19 and
§20 and amends §3.1, §3.3, §3.4, §3.5, §7.1, §7.4, §14.2, §14.3 and §16 in place.

96. **In machine mode the envelope is the sole stdout document, and it owns the preview (§19.1,
    §19.3).** The framework collided with itself before this ruling, with no consumer involved:
    a command supplying handler data under `--dry-run` wrote the would-do log and a bare JSON
    document to the same stream, and the auto-registered check command's own machine flag did the
    same. The resolution is not to silence one of them but to relocate the log's *content* into
    the document: one stream, one parseable object, both things inside it. A ten-option design
    ladder was generated and compared before the ruling; its top two rungs (a full run-report and
    event-stream redesign) were considered and deliberately **not** adopted, recorded here so a
    later campaign knows the ladder's top exists.

97. **`--json` and `--dry-run` stay a legal combination (§19.1).** Banning it was a live option
    and evidence killed it: a fleet consumer already ships a tested dry-run-plus-machine-output
    surface, and the correct fix for another consumer's preview depends on the combination
    existing.

98. **The stream-split items are narrowed to human mode; the never-conditional items are
    discharged (§3.3, §3.4, §3.5).** Two ratified promises were in the way, and neither is
    contradicted. The split (log to stdout, the sentence qualifying it to stderr) exists so a
    caller piping stdout gets the preview and nothing else -- the envelope delivers that property
    more strongly, since the preview and the reason it stopped are members of one document a
    caller parses together. "Never conditional" is discharged the same way: the preview is never
    absent in either mode, and only its *rendering* follows the declared output mode.

99. **The envelope's field set, and no timing fields (§19.2).** Interface version, app identity,
    command path, exit code, payload, preview flag, structured effects, diagnostics. Timing is
    excluded deliberately, not forgotten: a duration is nondeterministic by construction, and this
    document is compared byte-for-byte across three implementations.

100. **Declared outer field order is optional and for readability only (§19.2).** Conformance
     compares parsed structures, not serialized text -- key sets as sets, recursing on agreement --
     so key order is irrelevant to correctness across three serializers that order keys three
     different ways. The consequence for the payload's interior is the same and needs no rule at
     all: there is nothing to normalize.

101. **The envelope is structurally exempt from `--quiet` (§19.2, §7.4).** Not "exempted by a
     check" -- it is not written through the writers `--quiet` suppresses, so no mechanism exists
     by which quiet could reach it. This closes a shipped divergence in which one implementation emitted
     nothing at all under quiet plus machine flags while the other two emitted the data.

102. **`outcome(data=...)` / `ExitData(code, data)` is deleted and replaced by an explicit payload
     API (§19.4).** The bare-JSON-print channel had zero users across the fleet and was one half
     of item 96's self-collision. The replacement carries the schema binding, which the old
     channel structurally could not.

103. **Payload schemas are inline JSON Schema literals, with optional per-language builder sugar
     (§19.5).** The literal is the only canonical artifact: registered, byte-compared across the
     three implementations, published verbatim by the schema dump, enforced at emission. Builders
     are pure constructors of literals -- Go regains compile-time help -- whose output passes the
     identical registration-time validation.

104. **The validator is in-house over a deliberately closed subset (§19.5).** Measured evidence:
     across 1299 conformance tests the best third-party trio still disagrees on ten verdicts, and
     every one of them falls in a keyword the subset excludes. `pattern` is unfixable in
     principle -- Python `re`, Go RE2 and JavaScript `RegExp` are pairwise incompatible in seven
     measured ways -- and two shipping JavaScript validators fail `required` on prototype-chain
     keys today. An unknown keyword is a registration-time hard error, so subset creep is
     structurally blocked rather than discouraged.

105. **Payload numbers are IEEE-754 doubles, with an emission-time magnitude guard (§19.5).** Any
     integer beyond ±2^53 is rejected at emission; big identifiers are strings by declaration. The
     envelope is a public document and its consuming ecosystem is double-lossy regardless of what
     three implementations preserve internally, so exactness machinery would protect nothing past
     our own borders while adding a three-way divergence surface.

106. **The escaping regime is plain UTF-8 with no HTML escaping (§19.5).** Escape only what JSON
     mandates. The three implementations escape differently today and always have -- one escapes
     non-ASCII, one HTML-escapes angle brackets and ampersands, one does neither -- with zero test
     coverage, latent only because no case carries such a character. An envelope carrying app
     names, command paths and diagnostic text hits it immediately.

107. **Document-emitting commands declare stdout ownership (§19.6).** A command whose stdout *is*
     an artifact -- SQL, SVG, a hash-verified JSON document -- says so, and in machine mode its
     envelope and its diagnostics move to stderr so the artifact's bytes are untouched. The
     alternative, wrapping the artifact, breaks its reader by construction: at least one fleet
     consumer hash-verifies its own machine output.

108. **Render ordering is settled by a claim, not by a fixed position (§19.7).**
     `ctx.effects.recorded()` claims the render and suppresses the framework's own emission;
     `render_log()` produces byte-identical bytes wherever the handler puts them; a run that
     claimed but never rendered is re-rendered at the seam, so §3.5's guarantee survives.

109. **Compositional child previews are designed now and implemented later (§19.8).** Designing
     them in this round rather than deferring them is a deliberate user ruling: the preview schema
     is recursive from day one so it never has to change shape, and the ordering constraint is
     external -- an envelope-speaking child must exist before there is anything to compose with.
     A consumer's recorded-spawn preview deliberately stays as it is until this rung is
     implemented; no interim mechanism is built for a path this rung replaces.

110. **The process trace store's two contract items (§20).** Observational-only: no code path may
     branch on the ancestry stack, there is no accessor API, and conformance sweeps assert
     byte-identical output under a forged parent ID and under a broken store. Best-effort by
     declared design: a failure policy carve-out scoped to this store alone, with a write-once
     marker, no retries, no counter, and auto-created directories -- ruled deliberately against
     the husk pattern, because deleting operational telemetry should mean tracing resumes, not
     that it dies.

111. **Authored spellings for the envelope and the payload API (§19.2, §19.3, §19.4, §19.5,
     §19.6, §19.7, §19.8, §7.1).** None changes a ruling; each fixes a spelling the rulings left
     open, in the §18.3 class: the envelope's eight key names and the `preview_error` /
     `diagnostics` record shapes; `interface_version: 1` as this round's value; `command: null`
     for a run that resolved no command; the `--json` Context accessor names; the payload API's
     names (`ctx.payload` / `ctx.Payload` / `ctx.payload`) and its call-once rule; the
     `payload_schema` declaration's names; the `owns_stdout` declaration's names; the
     `previewable` effect option, the `children` record key and the nested rendering's indent.
     Where a ruling named a member without naming its shape -- "the truncation error and the abort
     marker become envelope members" -- the shape here is the minimal one that carries the
     existing §12.5 / §12.11 text verbatim rather than restating it in a second vocabulary.

112. **Authored spellings and one forced reading for the trace store (§20, and the spec page).**
     `spawned_at`'s format, the write-failure marker's filename and its content, and the store
     line's encoding are pinned in the published spec page (`docs/process-trace-store.md`), which
     is the artifact other tools implement against; §20 carries only the contract items. The
     entry's key names are **not** in this class -- they are ruled upstream and reproduced verbatim.

     The forced reading is §20.1's seam: the ruling says "the effects spawn seam" without saying
     which effects reach it, and only one reading is consistent with the rest of this document. A
     dry-mode `spawn` starts no process, so it can write no entry; an allowlisted observe really
     executes in dry mode (§3.1) and therefore can. Any other reading either records a spawn that
     did not happen or makes the entry's `dry_run` field permanently false. The same reading is what
     keeps the trace write outside §3.1's "nothing runs" rule instead of becoming a second
     framework-blessed exception to it.

Nothing else in this document was decided at authoring time. Every remaining statement is either
verbatim from the ratified pin list or a direct reading of the code as it stands, cited in place.

---

## 19. Machine mode and the envelope

Added 2026-08-13 at the machine-interface round (§18.9). This section is numbered after §18
because sections in this document are never renumbered; it is normative exactly as §§1-17 are.

### 19.1 The mode, its flag, and the one document

**Machine mode is entered by the framework-owned `--json` flag.** The name is reserved
unconditionally at every level (§7.1's amendment box): a consumer declaring `--json` on a command,
a flag set, a mutex group or as an app global is a registration-time error, exactly as it is for
`--dry-run`. Delivery follows §7.2 verbatim -- pre-scan extraction, stripped from argv before
command parsing, recognized anywhere in argv, the same two boundaries (a bare `--`, a passthrough
command's name), no short form -- and the value reaches the handler on the Context
(`ctx.json` / `ctx.JSON()` / `ctx.json`).

**In machine mode stdout carries exactly one document: the envelope**, serialized as JSON and
terminated by a single `\n`. Nothing else the framework emits reaches stdout -- not the would-do
log's text, not the truncation error, not the abort marker, not `ctx.info`. The framework's human
output goes through the context writers, which in machine mode write nothing; what those writers
were asked to say is carried in the envelope's `diagnostics` instead (§19.2). The single exception
is a command declaring stdout ownership, where the envelope moves to stderr and the command's
document owns stdout outright (§19.6).

**`--json` and `--dry-run` combine.** A preview in machine mode is an envelope whose `dry_run` is
true and whose `preview` carries the recorded effects. This combination is legal and is the point:
it is how a caller gets a machine-readable answer to "what would this do".

**Outside machine mode, nothing changes, ever.** Every promise §3 makes about the would-do log,
every suppression rule in §7.4, every stream in §3.5's table is exactly what it was before this
round.
There is no third mode and no per-command variation: a run is either in machine mode or it is not,
and the flag is the only thing that decides.

The framework governs what the framework emits. A handler that writes to the process's stdout
directly bypasses this section exactly as it bypasses §7.4's suppression rules today -- that is the same
accepted ceiling, not a new one, and §19.6 is the declared way to do it deliberately.

### 19.2 The envelope

| Key | Type | Meaning |
|-----|------|---------|
| `interface_version` | integer | The envelope contract's own version. `1` at this round; changed only by a later amendment to this section. |
| `app` | string | The app's declared name. |
| `app_version` | string | The app's declared version (mandatory on every app). |
| `command` | string \| null | The dotted command path (`release.run`), the same spelling §12.5's `<cmd>` uses. `null` when the run ended before a command resolved (a parse error, an unknown command, a pre-dispatch refusal). |
| `exit_code` | integer | The process's exit status. |
| `payload` | any \| null | The machine payload the handler supplied through §19.4's API, validated against the command's declared schema (§19.5). `null` when the handler supplied none. |
| `dry_run` | boolean | The preview flag: whether the run was in dry mode (§3.1). |
| `preview` | array of `effect_record` | The structured effects (§14.2, §19.3). Never absent; `[]` when nothing was recorded. |
| `preview_error` | object \| null | The terminal condition of a preview that did not finish (§19.3). `null` when the dispatch completed. |
| `diagnostics` | array of object | Every diagnostic the run emitted, in emission order: `{"level": "debug" \| "info" \| "warn" \| "error", "message": string}`. |

**No timing fields.** No duration, no timestamps, no counters derived from the clock. This is a
document three implementations must produce identically and a conformance suite compares
structurally; a wall-clock number is nondeterminism with no reader who needs it. A consumer
wanting timing measures the process it launched.

**Declared field order is optional and for readability only.** The three implementations serialize
differently -- one sorts keys, one preserves insertion order, one hand-writes -- and correctness is
decided by structural comparison: key sets compared as sets, recursing where they agree. Declaring
one logical order (the table's order) is cheap and reads better than alphabetical, and it is not a
requirement on any implementation. The same reasoning covers the payload's interior: there is
nothing to normalize and nothing to promise.

**The envelope is structurally exempt from `--quiet`.** It is not written through the writers
`--quiet` suppresses, so quiet has no mechanism by which to reach it (§7.4's amendment box).
`--json --quiet` emits the complete document. `--quiet` and `--verbose` govern the human stream
only: a
`ctx.debug` line hidden from a default-mode terminal still appears in `diagnostics` with
`"level": "debug"`, because the envelope's content is a function of what the run produced, never of
how a terminal was configured.

**Serialization** follows §19.5's escaping regime: plain UTF-8, escaping only what JSON mandates.

### 19.3 The `preview` member

`preview` is the structured effect log of §14.2, verbatim -- the same records, the same
`$defs/effect_record` shape, the same order, produced by the same seam. Machine mode does not
compute a second thing; it renders the one thing the framework already has, in the other form.
The would-do log (§3.2) is the text rendering of these records; `preview` is the structured one.

- **It is populated in both modes**, and `recorded` on each record says which happened (§14.2): a
  live run's records carry `recorded: false`, a dry run's application effects carry
  `recorded: true`, and framework-blessed cache writes carry `recorded: false` in either mode.
- **It is never absent and never conditional.** A read-only dry run yields `[]` -- the machine-mode
  equivalent of §3.1's header with an empty body, and emitted just as unconditionally. Silence
  remains the one answer the framework never gives (§3.5).
- **Observes never appear in it**, for §14.2's reason: the log is what would change.

`preview_error` carries the terminal condition, and is the machine-mode home of the two texts that
go to stderr in human mode:

```json
{
  "kind": "truncated",
  "step": 4,
  "command": "release.run",
  "brand": "«step 2 output»",
  "message": "error: dry-run preview ends at step 4: release.run branched on unsettled value «step 2 output» — cannot preview past this point"
}
```

- `kind` is `"truncated"` (§3.3: extraction or branching ended the preview) or `"aborted"` (§3.5:
  the dispatch unwound). The two are mutually exclusive by §3.5's table.
- `step` and `command` have exactly the meanings §12.5 and §12.11 give them: the would-do number
  the preview reached, over rendered lines (§3.2), and the dotted command path.
- `brand` is the offending carrier's brand form, present for `"truncated"` and `null` for
  `"aborted"` -- §12.11's marker deliberately names no value.
- `message` is the corresponding §12.5 / §12.11 text **byte-identical**, `error: ` prefix included.
  It is carried rather than restated so there is one text per condition, checked by the existing
  error-parity machinery, and a consumer that wants to print something has it.

Behaviour around the two conditions is unchanged: truncation still exits `1`; an unexpected unwind
still propagates untouched after the envelope is written at the same seam that renders the log in
human mode.

### 19.4 The payload API

`outcome(data=...)` and Go's `ExitData(code, data)` are **deleted**. The exit-code forms remain
(`outcome(exit_code)`, `Exit(code)`, a bare `int` / `undefined` return), and the JSON-printing
behaviour they carried is gone with no shim: this is a pre-stable framework, and the deleted
channel had zero consumers in the fleet.

Handlers supply the machine payload through a dedicated API instead:

| Impl | Call |
|------|------|
| Python | `ctx.payload(value)` |
| Go | `ctx.Payload(value)` |
| TypeScript | `ctx.payload(value)` |

- **The command must declare a payload schema** (§19.5). Calling the API on a command that
  declares none is a hard error at call time, naming the missing declaration -- registration cannot
  see that a handler intends to call it, so this is the earliest honest point.
- **At most once per dispatch.** A second call is a hard error at call time: two payloads are two
  answers to a question with one slot, and picking either silently is exactly the kind of guess
  this regime does not make.
- **The value is validated at emission** against the declared schema (§19.5). A payload that
  deviates fails the run rather than shipping a wrong shape.
- **The call is mode-independent.** A handler calls it identically in both modes and never branches
  on `ctx.json`; the framework decides what to do with the value. In machine mode it is the
  envelope's `payload`. Outside machine mode it is **not printed at all** -- that is precisely what
  deleting the bare-JSON-print channel means.
- **The programmatic surfaces keep their capture.** `test()` / `call()` / `Call()` return the
  payload the handler supplied where they previously returned the `data` it attached, so the
  in-process surfaces lose nothing.
- **Quiet cannot reach it**, for §19.2's structural reason.

### 19.5 Declared payload schemas

**Every command that can produce a payload declares that payload's JSON Schema at registration
time**, and the framework enforces the declaration at emission. This turns the envelope from a
shape held by convention into a contract each command states, and gives consumers something to
generate against.

| Impl | Declaration |
|------|-------------|
| Python | `payload_schema=` on the command decorator |
| Go | `PayloadSchema(schema)`, an ordinary `CmdOption` |
| TypeScript | `payloadSchema:` in the command definition object |

**The inline literal is the sole canonical artifact.** A declaration is a JSON Schema *literal* --
a dict / map / object written out in the source. It is registered as written, byte-compared across
the three implementations by conformance for every framework-owned command, published **verbatim**
by `--dump-schema`, and enforced at emission. There is no second representation that could drift.

**Builder sugar is optional and per-language.** A language may offer pure constructor functions
that *build* a literal (Go, which has no literal ergonomics to speak of, regains compile-time
help this way). Builders add no vocabulary and no semantics: their output is a literal, it passes
the identical registration-time validation, and a conformance case asserts that every builder
construct maps one-to-one onto the closed subset below. A builder is a convenience for writing the
canonical artifact, never an alternative to it.

**The validator is in-house, in each implementation, over a deliberately closed subset:**

| Keyword | Notes |
|---------|-------|
| `type` | including type **lists**, which is how nullability is expressed |
| `properties` | |
| `required` | |
| `items` | |
| `enum` | |
| `const` | |
| `additionalProperties` | boolean **or** schema; the schema form is how a dynamic-key map is declared |

**An unknown keyword is a registration-time hard error.** Not ignored, not warned about --
rejected, including near-miss typos. That is what keeps the subset closed: subset creep cannot
happen by accident, only by amending this table.

What the subset excludes and why it is not coming back: measured across 1299 conformance tests,
the best third-party validator trio still disagrees on ten verdicts, and every one of those falls
in an excluded keyword. `pattern` is unfixable in principle -- Python `re`, Go RE2 and JavaScript
`RegExp` are pairwise incompatible in seven measured ways, so a regex in a cross-language contract
means three contracts. Third-party validators are wired in as **dev-only cross-checks**
(python-jsonschema, santhosh-tekuri v6, hyperjump), asserting verdict agreement on every shared
vector; none is a runtime dependency of any implementation.

**Numbers are IEEE-754 doubles.** Python coerces to the double model. The validator **rejects at
emission** any integer whose magnitude exceeds 2^53: a big identifier -- a nanosecond timestamp, a
64-bit id -- is a **string by declaration**, not a number the framework hopes survives. The
envelope is a public document and its consuming ecosystem (`jq`, JavaScript) is double-lossy
regardless of what our three implementations preserve internally; exactness machinery would add a
three-way divergence surface protecting nothing past our own borders.

**Committed vector families**, each closing a hazard the closed subset does not remove by itself:

- the type matrix, including type lists;
- Python's traps: `bool` is an `int`, and `1 == 1.0 == True`;
- JavaScript prototype-chain keys (`__proto__`, `toString`, `constructor`) -- own-property
  discipline, since two shipping JavaScript validators fail `required` on them today;
- `enum` / `const` equality;
- unknown-keyword rejection, including near-miss typos.

**Escaping regime: plain UTF-8, no HTML escaping.** Escape exactly what JSON mandates -- quotes,
backslashes, control characters -- and emit everything else literally. Concretely: Python passes
`ensure_ascii=False`, Go sets `SetEscapeHTML(false)`, TypeScript is unchanged. This governs the
**whole envelope**, not only the payload, and it closes a live three-way divergence that was latent
only because no conformance case had ever carried a non-ASCII or HTML-special character. The
rejected regimes (ASCII-escaping everything, HTML-escaping) defend against byte-mangling transports
and raw HTML embedding -- contexts an envelope never enters -- at the cost of bloated, unreadable,
three-way-divergent bytes.

### 19.6 The owns-stdout declaration

Some commands' stdout **is** the artifact: a SQL dump, an SVG, a JSON document whose reader
hash-verifies it. Wrapping such a document in an envelope changes its bytes and breaks its reader.

Those commands declare it:

| Impl | Declaration |
|------|-------------|
| Python | `owns_stdout=True` |
| Go | `OwnsStdout()`, an ordinary `CmdOption` |
| TypeScript | `ownsStdout: true` |

For a command carrying the declaration, **in machine mode**:

- stdout carries the command's own document and nothing else, byte-exactly;
- the envelope goes to **stderr**, together with every framework diagnostic -- the stderr variant of
  framework output, scoped strictly to commands that declared it.

The envelope moving with the diagnostics is not an extra: leaving it on stdout would re-create the
exact two-documents-on-one-stream collision this round exists to remove. A caller of such a command
reads the artifact from stdout and, if it wants the envelope, reads stderr.

Outside machine mode the declaration changes nothing at all -- the command prints its document as
it always did, and the framework's human output is where §7.4 puts it. The scope is exactly the
declared commands: no other command's framework output ever moves to stderr.

### 19.7 Claimed rendering

The would-do log's position in the human stream was fixed: the framework rendered it at the end of
dispatch, after everything the handler had already printed. A handler that wanted the preview
*before* its own summary had no way to say so. It does now, and the mechanism is a **claim**:

| Impl | Calls |
|------|-------|
| Python | `ctx.effects.recorded()`, `ctx.effects.render_log()` |
| Go | `ctx.Effects().Recorded()`, `ctx.Effects().RenderLog()` |
| TypeScript | `ctx.effects.recorded()`, `ctx.effects.renderLog()` |

- `recorded()` returns the ordered records recorded so far in this dispatch -- the §14.2 shape,
  the handler-facing view of what §14.3's accessor returns for the whole run.
- **Calling `recorded()` claims the render.** The framework's own end-of-dispatch emission is
  suppressed for the rest of the run.
- `render_log()` renders those records in §3.2's exact form to the human stream, wherever the
  handler chooses to call it. **Byte-identical either way**: one renderer, one record list, so a
  handler that claims and renders produces exactly the bytes the framework would have produced,
  only earlier in the stream. That is the whole feature -- ordering, not content.
- **Claimed but never rendered is re-rendered at the seam.** A handler that reads the records and
  then forgets (or returns early, or unwinds) does not silence the preview: §3.5's guarantee is
  unconditional, and a claim can move the render but never remove it.
- **In machine mode `render_log()` is a no-op**, and claiming changes nothing: there is no human
  stream to order and the envelope's `preview` is unconditional either way. `recorded()` still
  returns the records, so a handler that reads them to shape its own payload behaves identically in
  both modes.

### 19.8 Compositional child previews -- designed, not yet implemented

A command that spawns another CLI can only record the spawn: the child's own effects are invisible
to the parent's preview, so a preview of a wrapper is a preview of the wrapping. When the child is
itself a strictcli app that speaks the envelope, that limit has an exact remedy, and this section
designs it in full. **It is not implemented at this round** (see the status note at the end).

**Declaration.** `run` and `spawn` gain one effect option, `previewable` (Python
`previewable=True`; Go `Previewable(true)`, an ordinary `EffectOption`; TypeScript
`previewable: true`), default false. It declares one fact the framework cannot know: *this argv
names a CLI that speaks the envelope*. No other method accepts it.

**Behaviour in dry mode.** For an effect declaring `previewable`, the framework does not merely
record the spawn:

1. it executes the child's argv with `--dry-run --json` appended;
2. it parses and validates the child's envelope (`interface_version` recognized, shape conforming);
3. it nests the child's `preview` records under the parent's own record as `children` -- an
   optional array of `effect_record`s, making the record shape **recursive from day one** (§14.2's
   amendment box).

Outside dry mode `previewable` does nothing whatsoever: the child runs for real, exactly as it does
today.

**Rendering.** In the would-do log, a child's lines follow its parent's line, indented by two
additional spaces per level, and numbered by the child's own 1-based counter. The parent's counter
(§3.2, and therefore the `«step N output»` brand and truncation's `step`) is **unaffected** by
nesting: a child's steps are the child's.

**Failure is fail-closed.** A declared previewable child that does not produce a valid envelope --
or produces one whose own `preview_error` is non-null -- is a hard error that truncates the
parent's preview. The framework does not degrade to recording a bare spawn: a preview that silently
lost a subtree is the "best-effort guess" §16 forbids.

**Why this does not reopen §16's first exclusion.** The mode is passed explicitly, in the child's
argv, exactly as a consumer would pass it by hand. No environment token carries a mode, nothing is
inherited, nothing is probed, and no child is treated as previewable unless an effect said so.

**Status and implementation trigger.** Designed at this round, implemented after an
envelope-speaking child exists in the fleet -- the commit tool's migration to the envelope is the
trigger. Until then: `children` is absent from every record, `previewable` is unregistered in all
three implementations, and §12 carries no template for the failure above (that template is authored
at the implementation round). No implementation may adopt this section partially, and no interim
mechanism is built for the consumer previews this section will replace.

---

## 20. The process trace store

Added 2026-08-13 at the machine-interface round (§18.9). The framework records process ancestry
universally: at the effects spawn seam it mints an identifier, appends one line to a local
append-only store, and composes the child's environment with that identifier so the child records
itself as a descendant. **The normative specification -- the environment variable, the line format,
the partition rules, the append discipline, the identifier profile and the failure marker -- is the
published page `docs/process-trace-store.md`,** which is the artifact other tools implement
against. This section carries only what belongs to the effects contract: two ratified items, and
the relationship to §16.

### 20.1 What the regime does

- At the effects spawn seam the framework mints one identifier, appends **one entry describing the
  spawning invocation** -- this app, this command, this process -- and composes
  `STRICTCLI_TRACE_PARENT=<that id>` into the **child's** environment. One entry per spawn.
  Nothing mutates in place: the spawning process's own environment is untouched, and the variable
  is a value passed down, never a channel back up.
- The entry's own `parent_id` is whatever `STRICTCLI_TRACE_PARENT` this process inherited, so
  walking `parent_id` links leads to the root of the chain. A process that never spawns writes
  nothing; a consumer at the leaf reads the variable from its own environment and resolves its
  immediate caller from the store.
- The entry describes the invocation, never its arguments: app, version, command path, the
  reserved-flag state, the machine-mode flag, consent, effect classification, pid, and the parent
  identifier. **Argv is never recorded** -- arguments carry secrets.
- **The seam is the real start of a child process** -- `spawn`, and `run` including the allowlisted
  observes of §6.2. This reading is forced by the rest of the regime rather than chosen: in dry
  mode a *recorded* spawn starts nothing, so it writes no entry (where nothing runs, nothing is
  traced), while an observe genuinely executes even in dry mode and therefore does write one,
  carrying `dry_run: true`. That is what the entry's reserved-flag state is for, and it is the only
  reading under which the flag can ever be true.
- **The write is framework bookkeeping, not an effect.** It is never minted through the effects
  handle, never appears in the structured effect log (§14.2), and is never rendered in the would-do
  log. It therefore adds **no exception** to §3.1's "nothing runs" rule and is not a second
  `CACHE_WRITE`-style carve-out: it accompanies real child-process starts and nothing else.

### 20.2 Observational-only (ratified contract item)

**No strictcli code path may branch on the content of the ancestry stack.** There is no accessor
API -- the framework does not expose the parent identifier, the chain, or anything derived from
them, and a consumer that wants ancestry parses the environment variable in its own capture seam
and reads the store itself.

This is enforced mechanically rather than promised. Two conformance sweeps:

- a **forged-ID sweep**, running with `STRICTCLI_TRACE_PARENT` set to an identifier no store ever
  minted;
- a **broken-store sweep**, running with the store directory unwritable;

both assert **byte-identical stdout, stderr and exit code** against the same runs without them.

That is the entire spoofing defense, and it is sufficient because it is total: a forged ancestry is
a false attribution claim, cross-checked by independently captured witnesses (parent process,
session identity, environment), and never an input to behaviour. A mechanism nothing can branch on
cannot be exploited by lying to it.

### 20.3 Failure policy: a scoped carve-out (ratified contract item)

The regime is fail-closed everywhere (§0). **This store is the one carve-out, it is scoped to this
store alone, and it is written down here so nobody generalizes it:** tracing is **best-effort by
declared design**.

- A write failure never fails the run and never emits a diagnostic.
- On the first write failure the framework creates a **write-once marker file** with `O_EXCL`,
  containing the first-failure timestamp. No counter -- counters race. A disk-full condition blinds
  the marker too, and that is accepted.
- **No retries**, ever.
- **Store directories are auto-created on write.** This is ruled deliberately against the husk
  pattern (a tool re-creating state a user deleted): deleting operational telemetry should mean
  tracing *resumes*, not that it dies permanently, and the store holds nothing a user is entitled
  to have stay deleted.
- The **primary detection channel is not the marker**: it is consumers noticing dangling parent
  identifiers at capture time, which is a real signal from a real reader rather than a file nobody
  opens.

The justification for the carve-out is that the store's failure mode is *losing a record of what
happened*, never *doing the wrong thing*. Nothing depends on it (§20.2 guarantees that
structurally), so a store that cannot be written costs observability and nothing else. Fail-closed
exists to stop the framework acting on what it cannot verify; here there is no action to stop.

### 20.4 Relationship to §16

`STRICTCLI_TRACE_PARENT` is not the deleted effects-mode token under a new name, and §16's first
bullet stands unamended. It carries an identifier, never a mode; the framework writes it into a
child's environment and never reads it back into a decision; and §20.2 makes that a contract item
enforced by sweeps rather than an assurance. A variable no behaviour may depend on cannot inherit
a mode.
