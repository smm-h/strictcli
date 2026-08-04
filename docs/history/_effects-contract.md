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
error (`errDeprecatedCommandEffect`, §12.2). Deprecated entries never prompt (§8), never reach
dispatch, and never appear in the would-do log. They are also not command entries in
`--dump-schema` output -- they serialize into the separate top-level `deprecated` list -- so §13's
"`effect` is always emitted on every command entry" rule is unaffected. §14's conformance-schema
change (§13, last paragraph) encodes the exemption explicitly.

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
A `mutating` passthrough prompts like any other mutating command (§8.1).

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

- **`mutating`** -- the command is subject to the confirm protocol (§8), participates in dry mode
  (§3), and may call the mutating members of the effects handle.
- **`read_only`** -- the command never prompts, and calling any mutating member of the effects
  handle is a hard error at call time (§9.1). It may call `ctx.effects.run(...)` only for argv
  prefixes on the app-level `proc_observe_allowlist` (§6.2).

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

### 3.4 What `--quiet` does to the log

Nothing. The would-do log is dry mode's primary output and is never suppressed (§7.4).

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

`dry-run`, `yes`, `quiet`, `verbose`. They join the existing reserved set
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

### 7.2 Delivery

The four flags are extracted by the pre-scan that already handles `--dump-schema`, `--mcp`,
`--config` and `--hermetic` (Python `App._pre_scan_reserved_flags`; Go's equivalent in
`strictcli.go`; TypeScript's in `parse.ts`), and are **removed from argv** before command
parsing.

Their values are delivered **on the Context, never as handler kwargs**:

| Impl | Accessors |
|------|-----------|
| Python | `ctx.dry_run`, `ctx.yes`, `ctx.quiet`, `ctx.verbose` (read-only properties) |
| Go | `ctx.DryRun()`, `ctx.Yes()`, `ctx.Quiet()`, `ctx.Verbose()` |
| TypeScript | `ctx.dryRun`, `ctx.yes`, `ctx.quiet`, `ctx.verbose` (getters) |

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

### 7.3 `--yes`

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

- structured handler data (the JSON that `outcome(data=...)` / `ExitData` prints to stdout);
- the would-do log (§3.2) and the truncation error (§3.3);
- framework parse errors, registration errors and the confirm prompt;
- `ctx.warn` and `ctx.error`.

### 7.5 Check-command subsumption

The auto-registered `check` command currently declares its own `--verbose` and its own
`--dry-run` among its eight flags (Python `App._register_check_command`, Go
`go/strictcli/check_cmd.go`, TypeScript `typescript/src/checks/cmd.ts`). Both names are now
banned, so both local flags are **dropped from the candidate list** and the check command reads
the framework-delivered values off the Context instead:

- `verbose` -> `ctx.verbose` (or `ctx.Verbose()`); behavior unchanged (per-check notes, durations,
  the trailing count summary).
- `dry_run` -> `ctx.dry_run` (or `ctx.DryRun()`); the handler's own behavior is unchanged (list
  which checks would run without executing them).

`check --dry-run` is **not** behaviorally unchanged overall, though, and implementors must not
assume it is: `--dry-run` is now the framework flag, so passing it puts the whole run in dry mode
(§3.1). The observable difference is that after the handler's listing output, the framework emits
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

### 8.1 When it fires

Before dispatching a command classified `mutating`, when **all** of the following hold:

- the dispatch path is the real CLI (`App.run` / `App.Run` / `App.run()`);
- `--dry-run` was not passed;
- `--yes` was not passed.

It never fires for `read_only` commands, or on the `test()` / `call()` / `_invoke` / MCP paths
(§8.4).

**Passthrough commands are not exempt.** A passthrough is classified like any other command
(§1.2); a `mutating` passthrough prompts exactly like any other mutating command, `--yes` skips
the prompt exactly as elsewhere, and a `read_only` passthrough never prompts. That the
passthrough's args are opaque to the framework is a reason to confirm, not a reason to skip: the
framework knows less about what is about to happen, not more. The prompt names the passthrough's
dotted command path like any other.

### 8.2 The prompt

Written to **stderr**, without a trailing newline:

```
about to run mutating command '<name>'. Proceed? [y/N] 
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
error: stdin is not interactive; pass --yes to confirm
```

and exits `1`. TTY detection is net-new in all three implementations (no `isatty` /
`IsTerminal` / `isTTY` call exists anywhere in the current sources): Python `sys.stdin.isatty()`,
Go `term.IsTerminal(int(os.Stdin.Fd()))` via a `golang.org/x/term`-free `os.Stdin.Stat()` mode
check (Go stays zero-dependency: `fi.Mode() & os.ModeCharDevice != 0`), TypeScript
`process.stdin.isTTY === true`.

### 8.4 Programmatic dispatch

`test()`, `call()` / `Call()` / `invoke`, and the MCP server behave **as if `--yes` were
passed**: they never prompt and never emit the non-TTY error. These paths have no TTY contract,
and a prompt there would hang the caller.

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

Those five, and the `check` command, are the framework-internal commands of §10.4; their
classification only becomes enforceable once the `config` group's direct-`Command`-construction
bypass is closed, which §10.4 requires.

**Classifying the three mutating `config` subcommands is not enough: their mutations must ride
`ctx.effects`** (amended 2026-08-03, A4). Classification alone bought the confirm prompt and put
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

Each implementation ships one **built-in check provider** registering **two** checks (amended
2026-08-03, D4/D5):

| Field | `effects-bypass` | `observe-allowlist-breadth` |
|-------|------------------|-----------------------------|
| tags | `["effects", "quality"]` | `["effects", "quality"]` |
| severity | `error` | `warn` |
| fast | `true` | `true` |
| pure | `true` | `true` |
| needs_network | `false` | `false` |
| depends_on | `[]` | `[]` |

`effects-bypass` statically analyses the consumer's own sources and fails on any direct process,
filesystem-mutation or network call **reachable from a registered command handler** that does not
go through `ctx.effects`. `observe-allowlist-breadth` reads the app's own declared
`proc_observe_allowlist` and warns on every single-token prefix (§6.2). Both are registered through
the existing provider hook (`App.register_check_provider` / `(*App).RegisterCheckProvider` / the TS
provider module), the same mechanism the built-in `cli-test-coverage` check already uses, so a
TOML-less app still gets working checks.

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
flag name '<x>' is reserved by the framework (dry-run, yes, quiet, verbose)
```

Function name: `errFlagNameReservedByFramework(name)`. Raised from the same
`validateFlagConfig` / `Flag.__post_init__` sites as the `force` ban, and additionally from the
global-flag validation path so app globals are covered by the same message.

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
about to run mutating command '<name>'. Proceed? [y/N] 
```

`promptConfirmMutating(name)` -- a prompt, not an error, but it lives in the same catalog files so
parity is checked.

```
error: stdin is not interactive; pass --yes to confirm
```

`errConfirmNonInteractive()`.

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
- leave the top-level `required` as `["name", "help"]`;
- add `"effect": false` to the deprecated branch's `then.properties`, alongside the existing
  `"handler_prints": false` / `"flags": false` / ... entries, so a deprecated case declaring
  `effect` fails validation;
- add an `else` branch to the same `if`: `{"required": ["effect"]}`, making classification
  mandatory for every non-deprecated command entry.

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
It sits beside the existing test-only surfaces (`test()`, `_last_sources`) and is excluded from
the api-surface catalog the same way.

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
  The confirm-protocol templates are exactly that case -- `promptConfirmMutating`,
  `errConfirmNonInteractive` and `errConfirmDeclined` (§12.6) all require driving stdin and/or
  faking TTY-ness of a subprocess, which the conformance runner does not do. Use the existing
  rationale string verbatim so the precedent stays greppable. `errEffectHTTPFailed` (§12.8) gets
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
- **No `dry_run_supported` capability negotiation** inside the framework.
- **No inference** of classification from a command's name, tags, flags or handler body.
- **No partial preview fallback.** When the preview cannot continue it truncates loudly (§3.3);
  it never degrades to a best-effort guess.
- **No bypass flag.** There is no `--no-confirm`, no `--force-effects`, no way to disable the seal.
  `--yes` answers the prompt; it does not disable anything else.
- **No compatibility shim** for pre-classification commands. Every consumer classifies at its
  lock bump.

`CONFORMANCE_EFFECT_LOG` (§14.3) is not an exception to the first bullet: it selects a diagnostic
*destination*, changes no behavior, is read only by the conformance harnesses (never by the
framework's dispatch path), and does not cross a process boundary as a mode.

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
  negative is silent (§11.1).
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

This section is **exhaustive**: every decision in §§1-17 that is not verbatim plan text is listed
below, in one of three classes. If a statement in this document is not derivable from the ratified
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
20. **Go's TTY check uses `os.Stdin.Stat()` + `os.ModeCharDevice`**, keeping the Go package
    zero-dependency.
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

Nothing else in this document was decided at authoring time. Every remaining statement is either
verbatim from the ratified pin list or a direct reading of the code as it stands, cited in place.
