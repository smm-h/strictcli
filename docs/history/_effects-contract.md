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

Amended a ninth time 2026-08-13 at the **machine-interface round** (§18.9). This round adds machine mode and
its envelope (§19) and the process trace store's contract items (§20), and amends §3, §7, §14 and
§16 in place. The governing rule is the normal one -- this document wins until it is amended, and
it is amended here rather than contradicted. The round's shape in one sentence: **outside machine
mode nothing in this document changes at all**, and inside machine mode the envelope is the only
document stdout carries, with §3's promises re-stated over it rather than dropped -- the preview
is never absent, the truncation error and the abort marker become envelope members instead of
stderr lines, and §14.2's structured effect log stops being a test-only diagnostic and becomes the
preview's source. Sections are never renumbered in this document, so §19 and §20 sit physically
after §18.

Amended a tenth time 2026-08-13 at the **mutex-election round** (§18.10), which adds §21. Five
upstream rulings fix what a typed token does to a mutex group: a bool member elects only when it
resolves to true, so `--no-x` declines instead of choosing; every other type elects on presence
with any value; the unsatisfied-group error teaches when a declined member is what left it
unsatisfied; a redundant negation beside a real election is a parse error rather than an accepted
no-op; and election is command-line-only, so env and config neither elect a member nor supply its
value. Nothing outside mutex groups changes. The round is a **breaking** change to parse-time
behaviour, and it deletes the motivation for the hand-written "nothing was chosen" guards the
consumers grew against the old semantics.

Amended an eleventh time 2026-08-14 at the **protocol round** (§18.11), which adds §22. The MCP
server stops pinning the protocol's first revision and speaks `2026-07-28`: per-request metadata
instead of a handshake, a mandatory `server/discover`, a `resultType` on every result, the
per-request client-capability declaration, and the revision's own error codes. On top of that it
mints and verifies an integrity-protected continuation state and runs the confirmation
round-trip, so the one channel that can reach a human now asks one instead of taking a caller's
word for it. §8.3, §8.4, §8.5, §12.6 and §18.8's item 93 are amended in place rather than
contradicted, and the two refusal messages stop printing the token that lifts them.

Amended a twelfth time 2026-08-14 at the **confirmation round** (§18.12), which finishes what the
protocol round deferred in §22.6. A modern client that did not declare it can render a form
elicitation no longer gets §8.5's refusal: it gets the revision's own `-32021`
`MissingRequiredClientCapability`, carrying what it would have to declare. The legacy era stops
being the protocol's first revision and becomes `2025-11-25`, the last handshake-based one, where
the same confirmation is delivered as a server-initiated `elicitation/create` request correlated
by the very continuation blob the modern era puts in `requestState` -- one mint-and-verify path,
two delivery vehicles. §22.1, §22.3 and §22.6 are amended in place and §22.7 is added.

Amended a thirteenth time 2026-08-14 at the **presence round** (§18.14), which adds §23. Every
flag and every positional argument now declares **exactly one** of required, optional, or a default
value, and every derivation of that fact is deleted: Python's collapse of `default=None` into
"required", Go's `hasDefault`-only inference, TypeScript's `default === undefined`, the framework's
silent empty-collection default for compound flags, and the parse-time exemption that handed mutex
members an absent value the declaration never asked for. §21.3 is amended in place, §13 gains the
one canonical `presence` key that ends the schema's requiredness erasure, and §12 gains the round's
registration-error family. The round is a **breaking** change to registration in all three
languages: a declaration that does not state its presence does not register. It is the first phase
of the declaration-regime campaign, and it deliberately stops there -- the constraint system and
the update-command construct are separate rounds with their own amendments.

Amended a fourteenth time 2026-08-14 at the **scoped-selector round** (§18.15), which adds §24. A
choice becomes a **declaration scope**: a selector flag elects exactly one of its declared choices,
each choice owns the flags that exist only while it is elected, and the handler receives **one
tagged value** per selector instead of a handful of loosely-related top-level flags. The round
**subsumes and deletes `MutexGroup`** -- a mutex group is this construct with the type information
thrown away -- so §21 is superseded item by item rather than erased, and its election vocabulary
(a bool elects only on true, `--no-x` declines, a redundant negation is a parse error, election is
command-line-only) survives verbatim as the semantics of **member spelling**. §12 gains the round's
error family as §12.13, §21 carries the supersession box, and §23.5's mutex row, §23.9's
constraint-system bullet and §12.12's mutex-member template are amended in place. The round is a
**breaking** change to registration, to parse-time behaviour and to handler signatures in all three
languages. It is the second phase of the declaration-regime campaign, and it deliberately stops
short of two things it enables: the surviving constraint families (§24.14) and the dumped schema's
selector encoding (§24.11), each of which is a round with its own amendment.

Amended a fifteenth time 2026-08-14 at the **schema-v2 round** (§18.16), which adds §25. The dumped
schema becomes `schema_version: 2` in a single migration: a flag's and an arg's value shape becomes a
**real JSON Schema fragment** from a closed four-keyword subset under `value_schema`, arity becomes a
property of that value (so the `repeatable` key dies and the parity checker's last normalization rule
goes with it), compound args are unified rather than banned, an int choice beyond ±2^53 is refused at
registration, and a **selector** carries the framework-native `choices`/`elect_by` encoding §24.11
deliberately left to this round. The document also gains a byte canon, a declared key order per
entity, a rewritten `defaults` block, and the behavioral keys the dump was blind to. §13's
flag-entry, arg-entry and defaults-block text is superseded by two boxes there, §12 gains the round's
one registration guard as §12.14, and §25 ships in the **same release as §24** for the reason §24.11
pins. It is the third phase of the declaration-regime campaign.

The ordinal above counts amendment **rounds**, not the paragraphs of this header: the fifth round
(the adoption round, §18.6) and the eighth (the non-CLI consent round, §18.8) recorded their
rulings in §18 without adding a paragraph here, which is why the header reads first, second,
third, fourth, sixth, seventh, ninth. The sixth paragraph's own ordinal is the precedent -- it
already counts a round that wrote no header paragraph.

The machine-interface round was **swept** the same day, after an independent audit found sites
that the round's own changes falsified and the round had left un-amended. Every sweep amendment
is marked `Amendment (2026-08-13, machine-interface round -- sweep)` and they touch §0, §2.5,
§7.2, §7.5, §9.2, §12.1, §13, §14.2, §18.2 and §20.1. **The sweep changed no decision**: it
propagated decisions already made into the sites that still contradicted them, and it re-labelled
one reading that had been presented as forced when it was authored (§20.1, item 112). §18.9
records what the sweep authored.

The presence round was likewise **swept the same day, after its implementation**, once all three
languages had shipped §23. Every sweep amendment is marked `Amendment (2026-08-14, presence round
-- implementation sweep)` and they touch §12.12, §23.3, §23.5, §23.6 and §23.8; §18.14 carries them
as items 151-158, continuing that round's numbering. **The sweep reverses no ruling.** It pins
spellings the pre-implementation text left open (the arg twins' parenthetical, the
three-declarations rendering, two language-specific template families), deletes a template family
the round's own rules made unreachable, and records three places where the round's text described
convergence that did not yet exist -- Python's `validate`-on-default, Go's and TypeScript's
dependency predicate counting an `infra` default as supplied, and two help renderings. Those three
are behaviour changes, named as such rather than left inside a table cell.

One sweep spelling was **reversed the same day** by a post-sweep ruling: §12.1's reserved-name ban
for `json` keeps the separate `json`-specific template the three implementations carry, instead of
the sweep's appended-to-the-quartet rendering. The superseded box stays in place under a
superseded marker, the reversal is recorded in item 111's ledger, and nothing else the sweep
touched changes.

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
| **Would-do log** | ~~Dry mode's primary stdout output:~~ *(amended 2026-08-13, machine-interface round -- sweep)* Dry mode's primary **human-mode** stdout output: the ordered, numbered rendering of the recorded effects. In machine mode there is no text log on stdout at all: the same records are the envelope's `preview` member (§19.3), so the content is relocated into the envelope, never dropped -- and `render_log()` is a no-op there (§19.7). |
| **Resource token** | An opaque string naming what an effect produces. Declared metadata; compared by string equality only; never gates execution. |
| **Conditional annotation** | A `skip_if_current=` declaration. Preview-only: it renders a suffix in the would-do log and has no runtime behavior whatsoever. |
| **Grant** | A per-command, per-effect-kind authorization with a mandatory human reason. |
| **Guard v2** | The tightened handler-signature validation that no longer exempts `**kwargs` handlers. |
| **Declared forwarding** | The registration-time declaration that a handler deliberately accepts and forwards `**kwargs`. |
| **Framework-internal command** | A command strictcli auto-registers itself (`check`, the five `config` subcommands). Subject to every rule in this document, plus §10.4. |
| **Presence** | *(added 2026-08-14, presence round)* The mandatory per-flag and per-arg declaration of what absence means: `required`, `optional`, or a `default` value. Exactly one, always declared, never derived (§23). |
| **Provided** | *(added 2026-08-14, presence round)* A resolved value whose source is `cli`, `env`, `config` or `implied` -- i.e. the invocation supplied it. A value whose source is `default` or `infra` is not provided: the declaration supplied it (§23.6). |
| **Selector** | *(added 2026-08-14, scoped-selector round)* A flag that elects exactly one of its declared choices. Spelled with a token of its own (`--via email`) or as its members' own flags (`--profile work` / `--all-profiles`), and delivering one tagged value (§24). |
| **Choice** | *(added 2026-08-14, scoped-selector round)* One alternative of a selector: a name, mandatory help, and the scope of flags that exist only while it is elected. Distinct from a **choice entry**, which is one value (plus optional help) of a plain `choices=` value flag (§24.2). |
| **Scope** | *(added 2026-08-14, scoped-selector round)* The set of declarations a choice owns. The command itself is the **root scope**, so nesting is uniform all the way down (§24.1). |
| **Elected / out of scope** | *(added 2026-08-14, scoped-selector round)* A choice is *elected* when the invocation selected it; a flag is *out of scope* when it was supplied but its owning choice was not elected -- a distinct parse error, never "unknown flag" (§24.3, §12.13). |

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

> **Amendment (2026-08-13, machine-interface round -- sweep): `STRICTCLI_TRACE_PARENT` in a
> handler-supplied `env` loses to the framework's ancestry composition.** `env` merges over the
> inherited environment, and nothing stops a handler naming this variable in that mapping. The
> framework's composition (§20.1) is applied **after** the handler's merge, on `run` and `spawn`
> alike, so the value the child actually receives is always the identifier of the entry the
> framework just wrote for this invocation. A handler therefore cannot sever the chain by clearing
> the variable and cannot forge a different ancestor by setting it -- not because forging is
> dangerous (§20.2 makes forged ancestry harmless), but because a link the framework writes and a
> link a handler writes would be two answers to one question, and the framework's is the one it can
> account for. Every other key the handler supplies keeps winning over the inherited environment
> exactly as before; the framework composes no other variable into a child's environment. This
> precedence is not derivable from a ruling -- it is an authored spelling, recorded in item 112.

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
~~mutex-group flags~~ *(amended 2026-08-14, scoped-selector round, §18.15 item 169)* **flags
declared inside a choice's scope, at any depth (§24.7)** and app global flags -- not only to global
flags. `--output` is explicitly **not** reserved and stays available to apps. The level list is
enumerated rather than left as "every level" because the enumeration is what an implementation
checks against, and a ban enforced only against a flat root list is this construct's most likely
correctness defect; the same substitution applies to the `json` box below.

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
| pre-command (before the first non-flag token) | every reserved flag: `--dump-schema`, `--mcp`, `--config`, `--hermetic` **and** the quartet *(and `--json` -- sweep, see the box below)*. Known global flags and their values are skipped so a global-flag value that looks like a command name does not end the region early. |
| command region | ~~the **quartet only**~~ *(amended -- see the box below)* the **quartet and `--json`**. `--hermetic`, `--config`, `--dump-schema` and `--mcp` stay pre-command-only and remain unknown-flag errors after the command token. |

> **Amendment (2026-08-13, machine-interface round -- sweep): `--json` reads identically in both
> regions.** §7.1's amendment box already said so ("the pre-scan's two-region table (§7.2), where
> `json` reads exactly as the quartet does in both regions"); the table itself still said
> *quartet only*, which the box falsified. `--json` is recognized in the pre-command region as
> every reserved flag is, and in the command region as the quartet is -- `app --json cmd` and
> `app cmd --json` are equivalent, and `app grp --json sub` works like `app grp --dry-run sub`.
>
> Everything else in §7.2 reads with `--json` included and needs no separate statement: it is
> stripped from argv before command parsing, delivered on the Context and never as a handler kwarg
> (`ctx.json` / `ctx.JSON()` / `ctx.json`), a union under repetition and mixed positions, stopped
> for good at the same two boundaries (a bare `--`, a passthrough command's name, §7.2.1), and it
> pays the same accepted cost as `--help` and the quartet: a flag *value* spelled exactly
> `--json` is eaten, with `--message=--json` and `--` as the literal spellings. It has no short
> form and never will.
>
> `--json` is still **not** a fifth member of the quartet (§7.1): the quartet is named as a set
> throughout this document, and `--json`'s semantics live in §19. Where a sentence below says
> "the quartet" about *delivery*, read it as covering `--json` too; where it says "the quartet"
> about the effects regime's own four flags, it means the four.

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
the framework-delivered values off the Context instead *(**a third name joins them 2026-08-13** --
`--json`; the counts in this section are corrected in the sweep box at its end)*:

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

~~The remaining six check flags (`all`, `tag`, `name`, `list`, `json`, `ignore-warnings`) are
unaffected.~~ **Amended 2026-08-13 -- see the box below.** The `check` command classifies as
`read_only` (§9.2 covers its coverage-shard writes).

The mechanism already exists in two of the three implementations: Python and TypeScript filter
their candidate check flags against the app's global flag names before registering. Go registers
its eight flags unconditionally and **must gain the same filter** -- otherwise the ~~two~~ **three**
dropped names reappear as command flags and collide with the framework pre-scan.

`check --dry-run` subsumption is a forced consequence of the unconditional name ban, not a new
ruling: two flags cannot share a spelling.

> **Amendment (2026-08-13, machine-interface round -- sweep): `check --json` and
> `config show --json` are subsumed by the reserved global flag, on identical grounds.** §7.1's
> box put `json` on the same unconditional every-level tier as the quartet, so a command-local
> `--json` is a registration-time error exactly as a command-local `--dry-run` is -- and the two
> framework-internal commands that declare one are the check command and `config show`. Both local
> flags are **dropped from their candidate lists**, which is §18.2 item 4's flag subsumption
> applied to a third name, not a new ruling: two flags cannot share a spelling, and the framework
> now owns this one.
>
> **The counts, corrected.** The check command declared eight local flags; the quartet's ban
> removed two (`verbose`, `dry-run`); `json`'s ban removes a third. **Five** local flags remain --
> `all`, `tag`, `name`, `list`, `ignore-warnings` -- and the struck sentence above ("the remaining
> six ... are unaffected", which named `json` among them) is wrong in both the count and the claim.
> Go's missing candidate filter must now drop **three** names, not two. `config show` loses its
> single local `--json` and keeps the rest of its surface unchanged.
>
> **Nothing is lost, and the shapes converge.** What those two flags printed is exactly what
> machine mode now yields as each command's `payload` (§19.4), validated against the command's
> declared payload schema (§19.5). Their **differing** shapes go with them: check's compact array
> and `config show`'s indented object were two hand-rolled spellings of machine output, and one
> envelope replaces both. Because these are framework-internal commands (§10.4), their payload
> schemas are framework-owned literals and are byte-compared across the three implementations by
> conformance (§19.5).
>
> **Two consequences to implement, not to decide.** `--json` is delivered on the Context like the
> quartet (§7.2), so neither handler receives it as a kwarg -- and neither needs to read it: the
> payload call is mode-independent (§19.4), so both handlers call it unconditionally and the
> framework decides what to do with the value. And `check --json --quiet` now emits the complete
> envelope, because the envelope is structurally exempt from quiet (§19.2, §7.4's box); that closes
> the shipped divergence in which one implementation routed check's machine output through the
> quiet-suppressible writer and printed nothing at all under both flags.

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
error: stdin is not interactive; a consequential command must be confirmed at a terminal
```

and exits `1`. (Amended 2026-08-14, §18.11 item 121: the message no longer prints the token that
lifts it. See §12.6's amendment box for why.) TTY detection is net-new in all three implementations (no `isatty` /
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

> **Amendment (2026-08-14, protocol round -- §18.11, item 120).** The seam is unchanged; what
> changed is that one transport now has a way to *obtain* consent rather than only to carry it.
> Over the modern protocol revision the server answers an unconsented consequential call with a
> confirmation request and a continuation state, and the retry's acceptance is the consent
> `Call` is given (§22.5). Everything §8.5 says about the shared seam still holds verbatim: the
> declaration is a property of the command (§8.1), the seam refuses without consent, and each
> transport is responsible for obtaining it. This is the first transport that asks a human.

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

Since the protocol round (§22.5) the param is no longer the only way consent reaches the server on
that transport: a client that declares it can render an elicitation is *asked*, and its answer is
the consent. The param remains what it always was -- a caller stating, in the call, that it is
proceeding without a human.

**The refusal**, byte-identical in all three implementations:

```
command '<path>' is consequential: the call must carry confirmation
```

> **Amendment (2026-08-14, protocol round -- §18.11, item 121).** The text was
> `command '<path>' is consequential: pass approve_consequential to confirm`, and it is amended
> for the same reason as §8.3's: a refusal that spells its own override teaches the override. The
> consent argument itself is unchanged and is documented in the table above, in the quickstarts
> and in the READMEs -- the refusal simply stops being one of those places.

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
write. *(**Amended 2026-08-13, machine-interface round -- sweep:** one third class now exists --
the process trace store's write; see the box after this section's tables.)* Specifically, the five
auto-registered `config` subcommands classify as:

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

> **Amendment (2026-08-13, machine-interface round -- sweep): the trace-store write is a third
> class, and this section's "everything else" no longer covers it.** The process trace store
> (§20) appends one line to a file on disk at the effects spawn seam. That write is neither an
> ordinary mutation of a `mutating` command nor a `CACHE_WRITE`:
>
> - it is **framework bookkeeping outside the effects handle** -- never minted through
>   `ctx.effects`, so it has no kind, no verb, no `seq` and no record. It never appears in the
>   structured effect log (§14.2, §19.3) and is never rendered in the would-do log (§3.2);
> - it **fires in `read_only` commands**, and legitimately so: the seam includes the allowlisted
>   observes of §6.2 (§20.1), which really start child processes and really execute in dry mode
>   (§3.1). §9.1's read-only enforcement is untouched by this -- enforcement is about what is
>   minted on the handle, and nothing here is minted;
> - it is **not a fourth entry in the closed `CACHE_WRITE` list above**, which stays at exactly
>   three sites. `CACHE_WRITE` is a kind on the effect log; the trace write is not on the log at
>   all, so widening the list would misfile it as a thing conformance can assert with
>   `effects_equals`, which it deliberately cannot;
> - it is **best-effort**, which no other write in this document is (§20.3's scoped carve-out).
>
> Read this section's "everything else" sentence as governing what an application or a framework
> command does *through the regime*. The trace write sits beside the regime and is specified in
> §20 and in `docs/process-trace-store.md`.

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
message family it belongs to. §12.12, §12.13 and §12.14 were added after this table and **declare
their own category in place**: §12.12 and §12.14 are registration-time throughout, and §12.13
splits -- its election,
scope and delivery templates are parse-time and its declaration guards are registration-time. The
table is not the authority for a section that states its own category; it is the authority for the
sections it lists.) §12.4's templates fire at effect-call time rather than at
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

> **Amendment (2026-08-13, machine-interface round -- sweep): the rendered list gains `json`.**
> **Superseded by the next box (2026-08-13, post-sweep ruling).** The spelling below was never
> implemented: all three implementations carry a separate `json`-specific template instead, and the
> ruling is that the separate template stands. This box is kept in place because the reasoning the
> ruling reverses is recorded in it.
>
> `json` joined the reserved set on the same unconditional every-level tier (§7.1's box), and it is
> refused from the same sites by the same template -- so the template that names the set must name
> it, or a consumer whose command-local `--json` is rejected reads a message listing four names
> that do not include the one it wrote. The text becomes, byte-exactly:
>
> ```
> flag name '<x>' is reserved by the framework (dry-run, approve-consequential, quiet, verbose, json)
> ```
>
> `json` is **appended after the quartet** rather than sorted in: the quartet's own order is
> unchanged and stays readable as a set, and the newest reservation reads last. That ordering is an
> authored spelling (item 111's sweep addition), not a ruling.
>
> **A separate `json`-specific template was considered and rejected.** The precedent for one exists
> -- `errFlagNameYesBanned` below is exactly that -- but it applies for a reason `json` does not
> share: `yes` names **no** framework flag, so a message listing the set the name is not in would
> explain nothing, and the template has to state the reason and the replacement instead. `json`
> names a framework flag, so it is in the set, and the set-listing template is the one that fits.
> Two templates for one condition would also mean two texts to keep in parity for one registration
> error. The function name, the raising sites
> and the separate `errFlagNameYesBanned` template below are all unchanged, and the parity
> extractor keys on the function name, so this is a one-line text change in three implementations
> plus its parity vector.

> **Amendment (2026-08-13, post-sweep ruling): the `json` ban is its own template, and the
> quartet's rendered list is unchanged.** This reverses the box above. The reserved-name ban for
> `json` is, byte-exactly:
>
> ```
> flag name 'json' is reserved by the framework: --json selects machine mode
> ```
>
> Python `_raise_flag_name_json_reserved()`, Go `errFlagNameJSONReserved` (a parameterless `const`,
> per this section's Go declaration form), TypeScript `errFlagNameJsonReserved()`. Registration-time,
> raised from the same two sites as the quartet's ban -- `Flag.__post_init__` /
> `validateFlagConfig` and the global-flag validation path -- and covered by its own parity vector
> (`conformance/cases/machine_mode.json`). The quartet's template keeps its four names and is
> untouched:
>
> ```
> flag name '<x>' is reserved by the framework (dry-run, approve-consequential, quiet, verbose)
> ```
>
> **Why the reversal.** The sweep box argued that `json` names a framework flag, so it belongs in
> the set the set-listing template renders, and that the `yes` precedent does not transfer because
> `yes` names no framework flag. Two things outweigh that. First, the separate template **names the
> remedy**: a consumer told only that `json` is in a list of five reserved names learns that its
> flag is refused, while `--json selects machine mode` also tells it what owns the name and why it
> can never have it -- the same service `errFlagNameYesBanned` performs, which is why that template
> is modeled on it. Second, §7.1's and §7.2's own amendments insist that **`json` is not a fifth
> member of the quartet**; a template that enumerates it inside the quartet's parenthesized set is
> the one place the framework would say otherwise, in the message a consumer is most likely to read
> about the reserved names. Keeping `json` out of that enumeration is the spelling consistent with
> the rest of §7.
>
> The cost the sweep box named -- two texts in parity for one registration condition -- is real and
> accepted: it is the cost `yes` already pays, both are parameterless, and the parity extractor keys
> on function names, so the pair is checked as two templates in three languages exactly as every
> other pair is. Item 111's ledger records the reversal.

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
error: stdin is not interactive; a consequential command must be confirmed at a terminal
```

`errConfirmNonInteractive()`. **This one is now conformance-covered**: the runner pins each case's
stdin to the null device (§14.5), so §8.3's branch is a deterministic outcome in all three targets
rather than a template whose trigger the runner could not reach. The prompt itself and
`errConfirmDeclined` stay `coverage_deferred` -- they need an answer typed at a terminal.

> **Amendment (2026-08-14, protocol round -- §18.11, item 121).** The text was
> `error: stdin is not interactive; pass --approve-consequential to confirm`. It printed the exact
> token that lifts it, and the reflex it taught was to append that token and re-run -- which is
> the opposite of the judgement `consequential` asks for, and was observed in practice within one
> retry. The amended text names what is required and never how to force the command through
> without it. `--approve-consequential` remains documented surface (§7.3); a refusal is simply not
> where it is advertised.

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

### 12.12 The presence declaration

Added 2026-08-14 (presence round, §18.14). Every template here is **registration-time** in the
parity taxonomy: stderr, `error: ` prefix, exit code 1, exactly like §12.10's declaration guards
and the existing `Flag "<name>": ...` family.

Every template here except the last carries a per-language noun phrase, because the thing it names
is a **spelling** and the three languages spell it differently. This is §12.10's handle-availability
precedent, applied to a larger triple: **the sentence is byte-identical and the spellings inside it
are each language's own**, and a conformance case asserts the whole line per target rather than a
shared one. Nothing else in the texts varies.

**The spellings**, referred to below as `<required-spelling>`, `<optional-spelling>` and
`<default-spelling>` -- three per surface, and the surface is whichever of `Flag` / `Arg` the
message names:

| | Python | Go | TypeScript |
|---|---|---|---|
| flag, required | `presence="required"` | `Required()` | `presence: "required"` |
| flag, optional | `presence="optional"` | `Optional()` | `presence: "optional"` |
| flag, default | `default=<value>` | `Default(<value>)` | `presence: "default" with default: <value>` |
| arg, required | `presence="required"` | `ArgRequired()` | `presence: "required"` |
| arg, optional | `presence="optional"` | `ArgOptional()` | `presence: "optional"` |
| arg, default | `default=<value>` | `ArgDefault(<value>)` | `presence: "default" with default: <value>` |

**Nothing declared** -- the zero case, which is also the `_MISSING`-sentinel path in Python and the
bare struct literal in Go:

```
Flag "<name>": presence is undeclared: declare exactly one of <required-spelling>, <optional-spelling>, or <default-spelling>
```

```
Arg "<name>": presence is undeclared: declare exactly one of <required-spelling>, <optional-spelling>, or <default-spelling>
```

`errFlagPresenceUndeclared(name)` / `errArgPresenceUndeclared(name)`. All three.

**Two declared** -- the message names the two that were supplied, rendered in the canonical order
`required`, `optional`, `default` regardless of the order they were written in, so the line is
deterministic:

```
Flag "<name>": presence is declared twice: <first> and <second> cannot be combined; declare exactly one
```

```
Arg "<name>": presence is declared twice: <first> and <second> cannot be combined; declare exactly one
```

`errFlagPresenceDeclaredTwice(name, first, second)` / `errArgPresenceDeclaredTwice(name, first,
second)`. All three. `<first>` and `<second>` are drawn from the table above; the `<value>` of a
default spelling is rendered by the same value formatter the other declaration guards use
(`formatValueForError` / `_format_value_for_error`).

> **Amendment (2026-08-14, presence round -- implementation sweep): three declarations at once,
> and the nil default's spelling inside this message.** Two pins the paragraph above left open,
> both surfaced by writing the resolver:
>
> - **Three declared is not a fourth message.** A declaration carrying all three facts renders the
>   same declared-twice error, naming the **first two** in the canonical order `required`,
>   `optional`, `default`. The message's job is to say that more than one was declared and to name
>   what to remove, and a third name changes neither. The count is never printed, so a
>   two-declaration error and a three-declaration error are byte-identical whenever they share
>   their first two spellings.
> - **Go renders a nil default as `Default(nil)` / `ArgDefault(nil)`** inside this message rather
>   than routing it through `formatValueForError`. The null-valued default has its own error
>   (§23.1), but the count check runs first, so `Required()` written beside `Default(nil)` reaches
>   the declared-twice message and must name the spelling that was actually written.

**The null-valued default** -- one spelling per fact, so the value-shaped spelling of optionality is
refused and redirected rather than accepted as a second synonym:

| Impl | Text |
|------|------|
| Python | `Flag "<name>": default=None does not declare optionality: use presence="optional" (it delivers None when the flag is absent)` |
| Go | `Flag "<name>": Default(nil) does not declare optionality: use Optional() (it delivers nil when the flag is absent)` |
| TypeScript | `Flag "<name>": default: null does not declare optionality: use presence: "optional" (it delivers undefined when the flag is absent)` |

`errFlagDefaultNullNotOptional(name)`, and the `Arg "<name>": ...` twin
`errArgDefaultNullNotOptional(name)` with `ArgDefault(nil)` / `ArgOptional()` in Go. All three. The
parenthetical is not decoration: the value the reader wanted is exactly what the redirected
spelling delivers, and saying so is what stops the redirect reading like a prohibition.

> **Amendment (2026-08-14, presence round -- implementation sweep): the arg twins substitute the
> noun in the trailing parenthetical too.** The paragraph above named the substitutions the twin
> makes in the Go row (`ArgDefault(nil)`, `ArgOptional()`) and said nothing about the
> parenthetical, which left `(it delivers nil when the flag is absent)` readable as the twin's own
> text on an arg. All three implementations wrote the noun substitution independently, and it is
> pinned here as the general rule rather than as three coincidences:
>
> **An `Arg` message is the `Flag` message with three substitutions and no others** -- `Flag` ->
> `Arg` in the prefix, the flag spellings -> the arg spellings, and the noun in every trailing
> parenthetical -> `arg`. That third substitution governs the whole §12.12 family, not just the
> null-default redirect.
>
> The three arg-side texts of the redirect are therefore:
>
> | Impl | Text |
> |------|------|
> | Python | `Arg "<name>": default=None does not declare optionality: use presence="optional" (it delivers None when the arg is absent)` |
> | Go | `Arg "<name>": ArgDefault(nil) does not declare optionality: use ArgOptional() (it delivers nil when the arg is absent)` |
> | TypeScript | `Arg "<name>": default: null does not declare optionality: use presence: "optional" (it delivers undefined when the arg is absent)` |

**A mutex member declaring requiredness** (§21, §23.5's mutex row):

```
Flag "<name>": a mutex member cannot declare <required-spelling>: the group's own requirement is what makes the choice mandatory
```

`errFlagMutexMemberRequired(name)`. All three.

> **Amendment (2026-08-14, scoped-selector round, §18.15 item 178): this template is deleted, and
> the rule it carried inverts.** `MutexGroup` is subsumed and deleted (§21's box, §24.4), so no
> declaration can reach this message and item 149's rule applies -- a template no code path can
> reach is a claim about behaviour that does not exist. Its replacement is not a rename: under
> member spelling the member flag **must** declare requiredness, read as *required once this member
> is elected*, and anything else is refused (§12.13's `errMemberFlagPresence`). The two messages
> state opposite rules about the same declaration, which is why the old one is removed from all
> three catalogs rather than left beside the new one.

**A variadic arg declaring a default** (§23.3):

```
Arg "<name>": a variadic arg cannot declare <default-spelling>: it always delivers a list, so declare <required-spelling> for at least one value or <optional-spelling> for possibly none
```

`errArgVariadicDefault(name)`. All three. The `<default-spelling>` here renders without its
`<value>` clause -- `default=`, `ArgDefault()`, `presence: "default"` -- because the message is
about the spelling being inapplicable, not about the value that was written.

**The handler-parameter check** (§23.3's re-sentinelization block, L1.6):

```
command "<name>": handler parameter '<param>' is bound to optional flag '--<flag>' and must default to None
```

`_msg_handler_param_optional_default(name, param, flag)`. **Python only.** Go- and
TypeScript-excluded, and not because the hazard is smaller there: their handlers receive one
`map[string]interface{}` / one args object, so there is no per-parameter default for a handler
author to re-sentinelize with. There is no site to check, not a check that was skipped. The arg
twin substitutes `optional arg '<arg>'` for `optional flag '--<flag>'`
(`_msg_handler_param_optional_arg_default`).

> **Amendment (2026-08-14, presence round -- implementation sweep): two language-specific template
> families, excluded from cross-language error parity by construction.** Every other template in
> this section is one sentence in three spellings. These two are not. Each names a state **only
> one language's spelling can reach**, so a sibling has no input that could produce the message,
> and a parity assertion over it would be asserting that the other two implementations carry text
> no code path can print. They are recorded here so their absence elsewhere reads as a consequence
> of the spelling rather than as a parity defect, and `check_error_parity.py` carries them as
> `excluded:` entries with that rationale.
>
> **Python only -- a `presence=` value that is neither fact.** Python spells the declaration as a
> keyword taking a string, so `presence="defualt"`, `presence="default"` and `presence=3` are all
> writable. Go's three sibling `FlagOption`s and TypeScript's discriminated union have no input
> that could carry a bad presence value: there is nothing to mistype.
>
> ```
> Flag "<name>": presence must be "required" or "optional", got '<value>'; a default value is declared with default=<value>
> ```
>
> `_raise_presence_value_invalid(surface, name, value)`, with `Arg` substituted for `Flag` on the
> arg surface. `<value>` is the repr of what was written, and `default=<value>` in the trailing
> clause is literal -- it is the spelling being named, not an interpolation. The redirect is the
> same discipline as the null-default message: naming the third spelling is what stops the error
> leaving the reader with two of three.
>
> **TypeScript only -- `presence: "default"` with no `default`.** TypeScript is the only language
> whose default spelling has **two parts**, so the union member can reach the factory carrying its
> discriminant and not its value, through a widened option object the compiler never narrowed.
> Python's `default=<value>` and Go's `Default(v)` *are* the value, so a half-written default
> declaration is inexpressible there.
>
> ```
> Flag "<name>": presence: "default" requires a default value: declare default: <value>, or presence: "optional" for no value
> ```
>
> ```
> Arg "<name>": presence: "default" requires a default value: declare default: <value>, or presence: "optional" for no value
> ```
>
> `errFlagDefaultValueMissing(name)` / `errArgDefaultValueMissing(name)`. Both `<value>` tokens are
> literal here for the same reason: the message names the spelling to write, and there is no value
> in hand to interpolate.

**Deleted at this round.** ~~Four registration templates lose~~ *(amended 2026-08-14, presence
round -- implementation sweep: the count is no longer four; see the amendment box under the table)*
Registration templates that lose their reason to exist are removed from all three catalogs, not
left dormant:

| Template | Text | Why it goes |
|---|---|---|
| `errFlagExplicitEmptyDefaultRedundantList` | `Flag "<name>": explicit empty default is redundant for list flags, omit the default` | An explicit `[]` is now a declaration, and omitting it is now an error (§23.5's compound row) |
| `errFlagExplicitEmptyDefaultRedundantDict` | `Flag "<name>": explicit empty default is redundant for dict flags, omit the default` | as above, with `{}` |
| `errFlagExplicitEmptyDefaultRedundantRepeatable` | `Flag "<name>": explicit empty default is redundant for repeatable flags, omit the default` | as above |
| `errRequiredArgCannotHaveDefault` | `required arg cannot have a default` | Subsumed by the two-declared error, which says the same thing for every pair and names both spellings. It is also the one message in the family with no `Arg "<name>": ` prefix, so nothing is lost twice |

> **Amendment (2026-08-14, presence round -- implementation sweep): the unreachable arg-side
> list-default validation family goes with them.** A second group, found by reading the arg
> factories after the round's own rules were in place. All of it validates the **default value of
> a list-typed positional arg**, and after §23.3 no such declaration can exist: a list-typed arg
> must be variadic, and a variadic arg refuses any default. The reason is one sentence and it
> covers every row -- *a list-typed arg must be variadic, and a variadic arg refuses any default,
> so these can never fire.*
>
> | Template | Text |
> |---|---|
> | `errArgListDefaultMustBeList` | `Arg "<name>": list arg default must be a list` |
> | `errArgExplicitEmptyDefaultRedundantList` | `Arg "<name>": explicit empty default is redundant for list args, omit the default` |
> | the arg-side element-type checks (`errArgDefaultElementTypeMismatch`) | `Arg "<name>": default element <i> is not of type <type>` |
>
> **All three implementations delete them.** Go carries the whole group and removes it with its
> call sites; TypeScript removes `errArgExplicitEmptyDefaultRedundantList`; Python's equivalent
> block was already deleted when the round rewrote the arg surface, so the deletion is what put
> the other two where Python already stood. The rule is §12.12's standing one, applied to
> unreachability rather than to obsolescence: a template no code path can reach is a claim about
> behaviour that does not exist, and leaving it in the catalog would make the error-parity surface
> assert agreement about a message none of the three can print.

### 12.13 The scoped-selector construct

Added 2026-08-14 (scoped-selector round, §18.15). The family splits across both parity categories,
and the split is pinned here rather than derived: the **election, scope and delivery** templates are
**parse-time** (stderr, exit 1, one covering conformance case each); the **declaration guards** are
**registration-time**, in §12.10's and §12.12's class.

Templates that name a *spelling* carry a per-language noun phrase and are asserted per target, which
is §12.12's mechanism unchanged: **the sentence is byte-identical and the spellings inside it are
each language's own**. §12.12's `<required-spelling>` / `<optional-spelling>` / `<default-spelling>`
table is reused verbatim; this section adds three rows -- `<record-spelling>` (§24.2's value-flag
entry), `<selector-spelling>` (§24.12's selector constructor) and its member-spelled twin
`<member-selector-spelling>`:

| | Python | Go | TypeScript |
|---|---|---|---|
| `<record-spelling>` | `Choice(<value>, help=...)` | `Ch(<value>, "<help>")` | `{ value: <value>, help: "..." }` |
| `<selector-spelling>` | `choice_flag(...)` | `ChoiceFlag(...)` | `choiceFlag(...)` |
| `<member-selector-spelling>` | `choice_flag(..., elect_by="member-flags")` | `MemberChoiceFlag(...)` | `memberChoiceFlag(...)` |

**The scope path is itself a pinned format.** Every template below that names a scope renders it the
same way, and three implementations must agree on it byte-for-byte at every depth:

- one segment per election on the path, outermost first, joined by a single space;
- a token-spelled segment is `--<selector> <choice>`; a member-spelled segment is `--<choice>`
  (the member's own flag, which is the only token a reader ever types);
- the whole path is wrapped in single quotes wherever a template names one:
  `'--via email'`, `'--visibility user-facing --type feature'`, `'--profile'`.

Lists of flags follow the catalog's existing split, which this round does not disturb: a **single**
flag is quoted (`flag '--subject'`, as in the existing `flag '--x' is required`), and a **member
list** is unquoted and comma-joined (`--profile, --all-profiles`, as in §21.4's `one of --a, --b is
required`).

**Reused unchanged, with no new template.** Five conditions this construct creates are already
spelled by the existing catalog, and reusing them is deliberate -- a migrated declaration must not
change the bytes a user reads for a condition that did not change:

| Condition | Existing template |
|---|---|
| a value that names no declared choice | `--<sel>: invalid value '<v>', must be one of: <names>` (`errFlagInvalidChoice`) |
| a required token-spelled selector that elected nothing, with no scoped flag supplied | `flag '--<sel>' is required` (the framework's existing required-flag text, Go's prefixed form in `parse.go`) |
| a required member-spelled selector that elected nothing | `one of --<a>, --<b> is required` + §21.4's decline clause (`errOneOfRequired`, `errMutexDeclineClause`) |
| two members elected at once | `--<a> and --<b> are mutually exclusive` (`errMutuallyExclusive`) |
| a member declined beside a real election | `--no-<b> cannot be combined with --<a> (--no-<b> declines an option; it does not choose one)` (`errMutexRedundantNegation`) |

The last three are §21.4's three errors, which this round carries over verbatim into member spelling
(§24.4). What they gain is the scope suffix below, when the selector they belong to is itself
scoped.

**The scope suffix** -- a clause, not a template of its own, appended to the two presence messages
above when the flag or the selector lives inside a scope:

```
 under '<scope path>'
```

`errScopeSuffix(path)`. All three. So a required flag one level down reads
`flag '--recipient' is required under '--via email'`, and a required member-spelled selector one
level down reads `one of --profile, --all-profiles is required under '--mode advanced'`. The
suffix is empty at root scope, which is what makes every root-scope message byte-identical to what
it was before this round.

**The out-of-scope flag** -- the round's central error, and deliberately **not** "unknown flag": the
flag is declared, it is simply not in the elected scope, and the sentence names both sides.

```
flag '--<x>' is only valid under <owners>, but <why>
```

`errFlagOutOfScope(x, owners, why)`. All three. `<owners>` is one or more scope paths in
declaration order joined by ` or `; a name reused by sibling scopes therefore reads
`only valid under '--mode a' or '--mode b'`. `<why>` names the **first (outermost) unsatisfied
election on the first owner's path**, never the innermost one -- a flag two levels down whose outer
election is the one that failed blames the outer election, because that is the token the user would
have to change. It is one of three clause templates:

```
'<elected path>' was elected<origin>
'--<sel>' was not provided
none of <members> was elected
```

`errScopeWhyElected(path, origin)`, `errScopeWhyNotProvided(sel)`, `errScopeWhyNoMemberElected(members)`.
All three. The second fires when a **required** token-spelled selector elected nothing and a flag of
one of its scopes was supplied anyway -- `--subject hi` with no `--via` -- which the precedence rule
reports here rather than as `flag '--via' is required`, because naming the flag the reader actually
typed is the more useful of the two true statements (§24.3). The third is its member-spelled twin,
which cannot name a selector token because none is ever typed.

`<origin>` is empty when the election came from the command line, and otherwise names where it came
from, because an ambient election refusing a typed flag is the one case where the user cannot see
the cause in their own command line (§24.6):

```
 from env var '<VAR>'
 from config key '<key>'
 by default
```

`errElectionOriginEnv(var)`, `errElectionOriginConfig(key)`, `errElectionOriginDefault` (Go: a
parameterless `const`). All three. The same three clauses are appended to the scope suffix's
messages, so `flag '--phone-number' is required under '--via sms' (elected from env var
'NOTIFY_VIA')` -- with the parenthesized form used there because the clause follows a complete
sentence rather than a verb.

**A selector elected more than once** -- last-wins is right for a plain flag and wrong for an
election, because discarding a value would discard a whole scope with it:

```
--<sel>: elected more than once, as '<a>' and '<b>'
```

`errSelectorElectedTwice(sel, values)`. All three. Values in command-line order, each quoted, joined
by ` and `. The member-spelled twin is §21.4's `--<a> and --<b> are mutually exclusive`, which is
why this template names values rather than flags.

**Registration guards.** All registration-time, all three implementations unless a row says
otherwise, all in the `Flag "<name>": ` / `Choice "<c>" of "<sel>": ` / `command "<name>": ` prefix
families the catalog already uses. `Choice "<c>" of "<sel>": ` is new and is the only new prefix:
a choice name is unique only within its selector, so the prefix names both.

| Template | Text |
|---|---|
| `errSelectorOptional(name)` | `Flag "<name>": a choice flag cannot declare <optional-spelling>: an absent selection is a choice nobody named, so name it as a choice of its own` |
| `errSelectorNoChoices(name)` | `Flag "<name>": a choice flag must declare at least two choices` |
| `errChoiceDuplicateName(sel, c)` | `Flag "<sel>": choice "<c>" is declared twice` |
| `errChoiceHelpEmpty(sel, c)` | `Choice "<c>" of "<sel>": help text is required` |
| `errSelectorDefaultUnknownChoice(sel, v, names)` | `Flag "<sel>": <default-spelling> names no declared choice: must be one of: <names>` |
| `errSelectorDefaultIncomplete(sel, c, sub)` | `Flag "<sel>": <default-spelling> elects choice "<c>", whose scope declares the required flag '--<sub>': a defaulted selection must be complete with nothing typed`. **Python-excluded** -- Python's default *is* a choice instance, so the incomplete state is unconstructable rather than refused (§24.5) |
| `errMemberFlagPresence(sel, m)` | `Choice "<m>" of "<sel>": a member flag must declare <required-spelling>, read as required once this member is elected` |
| `errMemberSelectorShort(sel)` | `Flag "<sel>": a member-spelled choice flag is never typed, so it cannot carry a short: declare the short on a member` |
| `errMemberDefaultCarriesValue(sel, c)` | `Flag "<sel>": <default-spelling> elects choice "<c>", whose flag carries a value nothing supplies: only a payload-less member can be a default` |
| `errChoicesEntryNotRecord(name, i)` | `Flag "<name>": choices entry <i> is a bare value: declare it as <record-spelling>` |
| `errChoicesEntryIsChoiceClass(name, i, cls)` | `Flag "<name>": choices entry <i> is the choice class '<cls>', which declares a scope: a choice with a scope belongs to a choice flag, declared with <selector-spelling>`. **Python-only** -- Go's `Ch` and TypeScript's record literal are distinct types from a choice, so the sibling mis-declaration is a compile error (§24.12) |

**Reserved names inside a scope** (S15, §24.7). Two names are reserved because the delivered record
uses them, and the rest of the reserved surface is not a new template at all -- it is the existing
bans, re-run at every depth:

```
Choice "<c>" of "<sel>": flag name 'choice' is reserved by the framework: it tags the delivered record
Choice "<c>" of "<sel>": flag name 'value' is reserved by the framework: it carries a member-spelled choice's own payload
```

`errScopedNameChoiceReserved(c, sel)` / `errScopedNameValueReserved(c, sel)`. All three. **Every
existing name ban applies unchanged at every depth** -- the reserved quartet and `json` (§12.1),
`yes`, bare `force`, the `no-` prefix, and `approve_consequential` -- and they raise their existing
templates from the scoped declaration sites too. A ban that is checked only on a flat root list is
the single most likely correctness defect in this construct, and it is named here so that it is a
requirement rather than a discovery.

**Name collisions** (§24.7). Five, and each names both sites:

| Template | Text |
|---|---|
| `errScopedNameCollidesRoot(c, sel, x)` | `Choice "<c>" of "<sel>": flag '--<x>' collides with a command-level flag of the same name: the scoped one could never be reached` |
| `errScopedNameCollidesSelector(c, sel, x)` | `Choice "<c>" of "<sel>": flag '--<x>' collides with the choice flag's own name` |
| `errSiblingScopeTypeMismatch(sel, x, a, b)` | `Flag "<sel>": flag '--<x>' is declared by choices "<a>" and "<b>" with different types: sibling scopes may reuse a name only with an identical type, because tokenizing '--<x>' cannot wait for an election` |
| `errCoElectableNameReuse(name, x, p1, p2)` | `command "<name>": flag '--<x>' is declared under '<p1>' and under '<p2>', which can be elected at the same time: simultaneously electable scopes may not reuse a flag name` |
| `errShortCollidesAcrossScopes(name, s, a, b)` | `command "<name>": short '-<s>' is claimed by '--<a>' and '--<b>', which can be elected at the same time` |

**Scoped positionals** (S15, §24.7):

```
Choice "<c>" of "<sel>": positional args cannot be declared inside a choice scope: a positional's meaning would depend on an election that may be typed after it
```

`errScopedPositional(c, sel)`. All three.

**A constraint naming a scoped flag** (S9, §24.8):

```
command "<name>": <Family> references '<x>', which is declared under '<scope path>': dependency constraints operate at root scope only
```

`errConstraintReferencesScopedFlag(name, family, x, path)`. All three. `<Family>` is the declared
family's own spelling (`CoRequired`, `Requires`, `Implies`), which is how the existing
`... references unknown flag ...` trio already names itself.

**Python-only: the handler-annotation family** (S11, §24.12). Three templates that name a state only
Python's spelling can reach, and they are `excluded:` entries in `check_error_parity.py` with that
rationale -- §12.12's precedent, applied for the same reason and not as a parity defect. Go's
handler receives one `map[string]interface{}` and TypeScript's receives one inferred args object, so
neither has a per-parameter annotation to check or to get wrong.

```
command "<name>": handler parameter '<param>' is bound to choice flag '--<sel>' and must be annotated <union>, got <written>
```

```
command "<name>": a command declaring a choice flag cannot use a **kwargs handler: the elected value must reach a named, annotated parameter
```

```
command "<name>": handler parameter '<param>' annotation <written> cannot be resolved at registration: a choice class must be importable at run time, not only under TYPE_CHECKING
```

`_raise_handler_selector_annotation(name, param, sel, union, written)`,
`_raise_handler_kwargs_with_selector(name)`,
`_raise_handler_annotation_unresolved(name, param, written)`. `<union>` renders the declared choice
classes in declaration order joined by ` | ` (plus nothing else -- a selector is never optional,
§24.5), and `<written>` is the annotation as written, rendered by the same value formatter the rest
of the family uses.

### 12.14 The schema-v2 declaration guard

Added 2026-08-14 (schema-v2 round, §18.16). One condition on two surfaces, **registration-time**, in
§12.10's and §12.12's class. It is the only new template the round needs: everything else v2 changes
is a serialization rule, and a serialization rule has no message.

A `choices=` entry whose value is an integer of magnitude greater than 2^53 cannot survive the
fragment that publishes it. §25.2's `value_schema` carries the declared values as a JSON Schema
`enum`, and a reader that parses JSON numbers as IEEE-754 doubles -- which every reader of a
`.strictcli/schema.json` is entitled to be -- reads back a **different integer**. The framework
refuses the declaration rather than publishing a fragment it already knows will be misread:

```
Flag "<name>": choice <v>: the number's magnitude exceeds 2^53 (declare a big identifier as a string)
```

```
Arg "<name>": choice <v>: the number's magnitude exceeds 2^53 (declare a big identifier as a string)
```

`errFlagChoiceMagnitude(name, value)` and `errArgChoiceMagnitude(name, value)` (Go and TypeScript).
Python raises both inline from `Flag.__post_init__` and `Arg.__post_init__`, beside the existing
choices guards they join (`choices must be a non-empty list`, `choices is incompatible with
type=bool`), which is the shape those neighbours already have and the first of the two shapes
§12's preamble lets the extractor see.

**The clause after the colon is reused byte-for-byte** from the payload regime:
`_PDETAIL_MAGNITUDE` / `pdetailMagnitude` (§19.5's decision-16 guard,
`the number's magnitude exceeds 2^53 (declare a big identifier as a string)`). The two are the same
condition at two boundaries -- there, a value being written into the envelope; here, a value being
written into the schema file -- and a second wording for one fact is what §12.13's reuse table
exists to prevent. The prefix is each surface's own existing one, so the sentence reads as a member
of the choices family rather than as an import from another section.

`<v>` renders as the integer's decimal digits, with a leading `-` when negative and no separators of
any kind. Python's `repr` of an `int`, Go's `%d` and TypeScript's `String(bigint)` coincide there,
so this template needs no per-language value formatter and no `<...-spelling>` row.

**Float choices are deliberately exempt**, and the asymmetry is the point rather than an oversight.
A float choice is published through the canonical float form (§25.8), which is by construction the
shortest string that round-trips to the identical double -- so a double-parsing reader recovers the
declared value exactly. An integer above 2^53 has no such string: the value is simply not
representable in the reader's number type. The guard therefore fires on the case where information
is lost and stays silent on the case where none is.

**Category.** Registration-time, so the coverage rule that binds `parse` templates does not reach
it; it is asserted **per target** in a conformance case, the way `conformance/cases/
presence_registration.json` asserts §12.12's guards.

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

> **Amendment (2026-08-13, machine-interface round -- sweep): the dumped schema gains
> `payload_schema` and `owns_stdout`.** §19.5 promises that a command's payload-schema literal is
> "published **verbatim** by `--dump-schema`", and §19.6 adds a registration-level declaration --
> both are command-entry facts, and this section is where command-entry facts are pinned. Without
> them the promise names an output key that no section defines.
>
> **On every command entry**, alongside the table above:
>
> | Key | Type | Emission |
> |-----|------|----------|
> | `payload_schema` | object | *Added 2026-08-13 (§19.5).* The registered literal, **as registered**: the same keys with the same values, with no normalization, no re-ordering pass and no round-trip through a builder. Omitted when the command declares none, and absence means the command produces no payload. Key order inside it is whatever the implementation's serializer does to every other object it writes (§19.2's optional-order reasoning applies unchanged); "verbatim" is a promise about content, since three serializers cannot promise bytes |
> | `owns_stdout` | `true` | *Added 2026-08-13 (§19.6).* Emitted **only when declared true**; absence means the framework owns stdout, which is the baseline. The omit-when-baseline shape of `consequential` and `dry_run_supported`, not `effect`'s always-emitted one |
>
> **`previewable` is deliberately not here.** It is an *effect-call* option (§19.8) -- an argument
> to a `run` or `spawn` inside a handler body -- and the dumped schema describes commands, groups,
> flags and args, none of which can see a call the handler has not made yet. It stays absent from
> the schema when §19.8 is implemented, for the same reason `resource=` and `grant=` are absent
> while a command's *declared* `grants` are present: the regime publishes declarations, never call
> sites.
>
> **The conformance case schema** (`conformance/schema.json`) mirrors the pair under
> `$defs/command`, following the shape §13 already uses:
>
> - add `payload_schema` (`{"type": "object"}`) and `owns_stdout`
>   (`{"type": "boolean", "default": false}`) to `$defs/command`'s `properties`;
> - add both to the deprecated branch's `then.properties` as `false` -- a deprecated entry has no
>   handler, so it can neither produce a payload nor own stdout, the same reasoning §1.1's
>   exemption gives for `effect` and `consequential`;
> - neither joins the top-level `required` nor the `else` branch's: almost every command declares
>   neither, and demanding them would re-impose a per-registration answer to a question with one
>   overwhelming default.
>
> `conformance/check_api_surface.py` gains the corresponding entity mappings on the `command`
> `EntityDescriptor`, mirroring the existing `"command.grants": "grants"` entry
> (`"command.payload_schema"` -> `payloadSchema`, `"command.owns_stdout"` -> `ownsStdout`).
> `check_schema_parity.py` again needs no shape change: both are ordinary fields.

> **Amendment (2026-08-14, presence round): every flag entry and every arg entry carries
> `presence`, and the requiredness erasure ends.** Until this round the dumped schema described a
> flag's presence **nowhere**: a required flag and an explicitly-optional one serialized
> identically, because the only evidence was a `default` key that both of them omit. Schema parity
> across the three implementations therefore passed *by erasure* -- three implementations agreeing
> about a fact none of them emitted. §23 makes presence a declaration, and a declaration this
> document pins is published.
>
> **On every flag entry and every arg entry:**
>
> | Key | Type | Emission |
> |-----|------|----------|
> | `presence` | `"required"` \| `"optional"` \| `"default"` | **always** -- presence is mandatory, so there is no default to omit against. `effect`'s always-emitted shape, not `consequential`'s omit-when-baseline one |
> | `default` | the declared value | Emitted **exactly when** `presence` is `"default"`, and then **always**, whatever the value: `[]`, `{}`, `""`, `false` and `0` are emitted, because under §23 they are declarations rather than the absence of one. The omit-when-empty rules for compound defaults (Python's `if f.default:`, Go's `dflt != nil`, TypeScript's `length > 0` / `size > 0`) are deleted |
>
> The arg entry's **`required` key is deleted** from the dumped schema. It was the arg-side
> spelling of the same fact, emitted only when false, and keeping it beside `presence` would put
> two keys on one fact -- the very thing §23.3 removes from the registration surface.
>
> A `RelativeToRoot` marker default is unchanged in shape (`§13`'s machine-stable env-var-plus-parts
> form) and reports `presence: "default"`, because that is what it is: a declared default whose
> resolution is deferred to parse time and labelled `infra` (§23.5's infra row).
>
> **The conformance case schema** (`conformance/schema.json`) mirrors the key on the **input** side,
> where it is what a case *declares* rather than what a dump *reports*:
>
> - add `presence` (`{"enum": ["required", "optional", "default"]}`) to `$defs/flag`'s and
>   `$defs/arg`'s `properties`, and to **both** `required` lists -- every declared flag and arg in
>   every case states its presence, which is the case-schema encoding of §23.1's zero-declaration
>   error;
> - delete `required` from `$defs/arg`'s `properties`, following the dumped schema;
> - **keep `null` in `$defs/flag`'s `default` `oneOf`.** It stops being a legal declaration and
>   becomes the input the redirect error (§12.12) is asserted against, so a case must still be able
>   to express it. A schema that could not spell the refused declaration could not test the refusal.
>
> `conformance/check_schema_parity.py` **does** need a shape change here, and it is the point of the
> item rather than an afterthought: the erasure is what let three implementations certify agreement
> about a fact none of them emitted, so the parity check gains an assertion that `presence` is
> present on every flag and arg entry of every dump it compares. A missing key is a failure, never a
> silently-equal pair of absences.
>
> **The MCP projection collapses onto the same field.** A parameter appears in a tool schema's
> `required` array **iff its declared presence is `required`** -- flags and args alike. The three
> hand-written derivations are deleted (Python's `compound == "scalar" and default is None`, Go's
> four-clause `isRequired`, TypeScript's `kind === "scalar" && schema !== "bool" && default ===
> undefined`), and with them the three-way disagreement about **required bools**: they were required
> in Python's projection and excluded from Go's and TypeScript's on the reasoning that "bool flags
> always have a default", which §23 makes false by construction. Required bools now appear in all
> three, which is what Python already did.

> **Amendment (2026-08-14, scoped-selector round, §18.15 item 173; recorded at the read-back audit,
> §18.17 item 199): the MCP requiredness `iff` above is a ROOT-SCOPE rule.** A flag declared inside a
> choice's scope is projected as a top-level property and **never** appears in `required`, whatever
> its own presence declares: its requiredness is conditional on an election, and the tool schema has
> no vocabulary for a conditional requirement. The scope rule is carried in the tool description
> instead and enforced at call time with the CLI parser's own sentence (§24.11). A **selector's** own
> property follows the rule above unchanged -- it is in `required` exactly when the selector declares
> `required`. Nothing about the CLI-side or the dumped `presence` key moves; this narrows the MCP
> projection alone, at the one place §24 gave a flag a conditional existence.

> **Amendment (2026-08-14, schema-v2 round): the dumped schema becomes `schema_version: 2`, and the
> flag and arg entries' value keys are superseded by §25.** The full v2 format -- the fragment
> subset, the arity rule, the choices and selector encodings, the byte canon, the key order, the
> rewritten defaults block and the behavioral-completeness keys -- is **§25**, which is the normative
> record for all of it. This box records only what §13's own text stops saying, so that no reader of
> this section is left with a v1 sentence that v2 contradicts.
>
> - **`schema_version` becomes `2`** at both sites that emit it in every implementation: the
>   top-level key and the copy inside the `defaults` block (Python `_dump_schema_core` and
>   `_build_schema_defaults`, Go `dumpSchemaCore` and `buildSchemaDefaults`, TypeScript
>   `dumpSchemaCore` and `buildSchemaDefaults`). One version covers the whole migration; §25.1 states
>   why it is one and not three.
> - **The flag and arg entries' `type` key is deleted** and replaced by `value_schema`, a real JSON
>   Schema fragment from the closed four-keyword subset (§25.2). The three v1 spellings of one fact
>   -- Python's `{"type": "array", "items": {"type": "str"}}` with strictcli type names, Go's
>   `"list[str]"`, TypeScript's `"list[str]"` / `"dict[str,str]"` carrier strings -- all go with it.
> - **The flag entry's `repeatable` key is deleted** (§25.3): the fragment carries the arity, so the
>   key was a second spelling of a fact the value shape already states. `conformance/
>   check_schema_parity.py`'s `_canonicalize_repeatable` normalization (and its call from
>   `_normalize_schema`) is deleted with it.
> - **The `constraints` array loses its `mutex` subtype**, because `MutexGroup` is deleted (§24.4,
>   item 178). The surviving subtypes are `co_required`, `requires` and `implies`, catalogued in
>   §25.7.
> - **Everything else §13 pins stands unchanged**: `effect`, `consequential`, the dry-run pair,
>   `grants`, `forwarding`, `payload_schema`, `owns_stdout`, app-level `proc_observe_allowlist`, and
>   the presence box's `presence` / `default` rules on every flag and arg entry. v2 changes how a
>   value's *shape* is published, not which command-entry facts are published.
>
> **The conformance case schema** (`conformance/schema.json`) follows on the input side, where these
> are what a case *declares*: ~~`$defs/flag` and `$defs/arg` lose `type`'s v1 spelling in favour of the
> declaration surfaces §25 names, `$defs/flag` loses `repeatable`,~~ `$defs/mutex_group` is deleted
> with the construct, ~~and `$defs/config_field_def`'s `type` enum is replaced per §25.7.~~
> `check_schema_parity.py` gains the byte-equality mode §25.8 requires and keeps the `presence`
> assertion the box above added.

> **Correction (2026-08-14, read-back audit, §18.17 item 200): the struck clauses above confused a
> dumped key with a declaration key, and the case schema keeps all three.** `$defs/flag`'s and
> `$defs/arg`'s `type`, and `$defs/flag`'s `repeatable`, are how a **case declares a carrier and its
> arity** -- the input side -- not how a dump publishes a value's shape. §25.3 keeps *both*
> declaration spellings and unifies only what they publish, §25.13's arity fixes need cases that
> declare exactly those two shapes, and §25.15 adds no declaration surface at all. Deleting those
> keys would make the declarations unspellable and the round's own coverage unwritable.
> `$defs/config_field_def`'s `type` is a declaration for the same reason and likewise stays; what
> §25.7 moves is the config-field **entry** a dump writes. What the case schema really loses is
> `$defs/mutex_group`, deleted with the construct (§24.4, §25.7).
>
> What it still **needs** is named here rather than left for an implementor to discover, and is
> **not** authored: neither the scoped-selector round nor the schema-v2 round pinned a case-level
> spelling for a selector, for a choice's scope, or for §24.2's record-shaped `choices` entries --
> and §12.13's parse-time templates each require a covering case that cannot be written without one.

> **Amendment (2026-08-14, schema-v2 round): the app and command entries gain the behavioral keys
> the dump was blind to, and the `defaults` block is rewritten.** Also §25's, and recorded here for
> the same reason as the box above.
>
> **On the app entry:** `config_format`, `config_path` and `config_conflict_mode`, each omitted at
> its baseline (§25.11). Until v2 an app could relocate every user's config file, or switch it from
> JSON to TOML, while its dumped schema stayed byte-identical -- the schema described a surface it
> could not see.
>
> **On every command entry:** `flag_sets`, recording the grouping that v1 discarded when it merged a
> set's flags into the command's flag list.
>
> **On every flag entry:** `prefixed`, omitted when true.
>
> **The `defaults` block** stops documenting a field that does not exist (`defaults.flag.hidden`: no
> implementation has a flag-level `hidden`, and no serializer has ever emitted one), drops the
> `default: null` entries the presence round left behind on both the flag and the arg baselines
> (`default` has had no baseline since presence became the authority -- it is emitted exactly when
> `presence` is `"default"`), and gains baselines for the entities it never covered. §25.10 is the
> block, written out.

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

**The literal immediately below is superseded** (2026-08-13, machine-interface round -- sweep).
It is kept unerased, per this document's convention: the record shape it describes is otherwise
unchanged, and the reason it had to change is worth reading. The literal in force is the second
one.

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

**Amended 2026-08-13 (machine-interface round -- sweep): the literal in force is the one below.**
The struck literal declares `additionalProperties: false` and no `children` key, so under it a
record carrying children -- the shape the amendment box further down pins "from day one" -- fails
validation outright. A closed shape is exactly why the key had to be written into the literal
rather than left to arrive as an extra property, so the closure **stays** and the key joins it:

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
    "recorded":        { "type": "boolean" },
    "children":        { "type": "array", "items": { "$ref": "#/$defs/effect_record" } }
  }
}
```

`children` is optional and absent from every record until §19.8 is implemented; nothing else in the
shape moves. The self-`$ref` is what makes the recursion real rather than promised -- a nested
child record is validated by the same definition at every depth, so the schema does not have to
change shape when §19.8 ships.

One thing this recursion is **not**: `$ref` is not in §19.5's closed validator subset, and it does
not need to be. This literal is `conformance/schema.json`'s definition of a *case-file* record,
consumed by the ordinary JSON Schema tooling the conformance suite already runs; §19.5's subset
governs the payload schemas commands declare and the in-house validator enforces at emission. Two
artifacts, two vocabularies, no overlap.

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
every section numbered after this one (§§19-25), which sit there because sections here are never
renumbered -- that
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
   *(Extended by item 111 / §7.1 and §7.5's sweep box: `json` joins the same unconditional tier, so
   `check --json` and `config show --json` are subsumed on identical grounds. Three names drop from
   the check command's candidate list, not two, and the data those flags printed is now the
   command's payload, §19.4.)*
5. **Guard v2 enforcement is Python-only** (§10.3). Go handlers take `map[string]interface{}` and
   TypeScript handlers a typed args object; neither can be introspected for a var-keyword
   parameter. The *declaration* exists in all three so the API surface stays in parity.
6. **Truncation exits `1` and splits its streams** (§3.3): the already-recorded log to stdout, the
   pinned error text to stderr. Fail-closed admits no other outcome, and the log is dry mode's
   primary output so it must still be emitted.
   *(Narrowed to human mode by item 98 / §19.3: in machine mode there is no split, because there
   are no two streams to split -- the records are the envelope's `preview` and the pinned text is
   `preview_error.message`, byte-identical, in one document. The exit code stays `1` and the
   must-still-be-emitted half is what the narrowing preserves.)*
7. **Observes execute in dry mode and are not logged** (§6.2, §3.2). An observe that did not
   execute could not return the real value the regime promises pre-mutation; an observe in the
   would-do log would misrepresent a read as a change.
8. **`--quiet` never suppresses the would-do log** (§3.4, §7.4). It is dry mode's primary output,
   not a diagnostic.
   *(Discharged more strongly by item 101 / §19.2 in machine mode: the preview rides the envelope,
   which is structurally exempt from quiet -- not exempted by a check that could be forgotten, but
   never written through the writers quiet suppresses. Outside machine mode this item is unchanged
   and still governs.)*
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

    > **Amendment (2026-08-14, protocol round -- §18.11, item 120).** This item's honest limit --
    > "a caller can always supply consent" -- was true of the transport as it stood, and is why
    > the item said the point is that it must say so somewhere recordable. The protocol round
    > removes the limit for the one transport that can now reach a human: over the modern
    > revision the server *asks*, through the client, and the answer is the consent (§22.5). The
    > declaration stays a property of the command, which is what the campaign's decision 6 ruled
    > and what this item already assumed; the channel-pair alternative above stays rejected, and
    > for the same reason -- what varies is the delivery, never the fact.

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

**Swept 2026-08-13**, after an independent audit found sites the round's own changes falsified and
had left standing. The sweep amended §0, §2.5, §7.2, §7.5, §9.2, §12.1, §13, §14.2's printed
literal, §18.2's items 4/6/8 and §20.1, and added the status note and the literal-path rule to
`docs/process-trace-store.md`. **It decided nothing new.** Items 96-110 are untouched by it; items
111 and 112 gain the spellings it authored, marked below; and one sentence of item 112 is corrected,
because a reading it presented as forced is authored (§20.1).

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

     **Added at the sweep**, same class, none of them a ruling: ~~the reserved-name error template's
     rendered list order (§12.1) -- `json` appended after the quartet rather than sorted in, so the
     quartet's order survives and the newest reservation reads last~~ *(reversed -- see below)*; the two schema-dump emission
     shapes (§13) -- `payload_schema` omitted when undeclared and published as registered,
     `owns_stdout` emitted only when true, both following `consequential`'s omit-when-baseline
     shape and their case-schema mirroring following §13's existing deprecated-branch pattern;
     and the `children` key's spelling in the printed `$defs/effect_record` literal (§14.2) --
     a self-`$ref`, with `additionalProperties: false` deliberately kept, since a closed shape is
     the reason the key had to be declared rather than tolerated.

     **Reversed after the sweep (2026-08-13), same class:** the sweep's `json`-in-the-rendered-list
     spelling (§12.1) is withdrawn, and the **separate `json`-specific template** the three
     implementations already carry stands instead --
     `flag name 'json' is reserved by the framework: --json selects machine mode`, modeled on
     `errFlagNameYesBanned`. The sweep authored an ordering rule for a list `json` no longer joins,
     so that spelling is void rather than superseded by another ordering. Two reasons, recorded so a
     later round does not re-derive the sweep's version: the separate template **names the remedy**
     (what owns the name, and that it selects machine mode) where the set-listing template only
     places the name in a list; and §7.1's and §7.2's amendments both insist `json` is **not** a
     fifth member of the quartet, which an enumeration reading
     `(dry-run, approve-consequential, quiet, verbose, json)` would contradict in the message a
     consumer most often reads about reserved names. The accepted cost is a second parameterless
     template in three languages -- the cost `yes` already pays -- and it buys the parity extractor
     two separately keyed function names rather than one text that has to serve two conditions.
     The sweep's own counter-argument (a set-listing template fits a name that IS in the set) is
     preserved verbatim in §12.1's superseded box.

112. **Authored spellings and one adopted reading for the trace store (§20, and the spec page).**
     *(This item was headed "one forced reading" until the sweep; see the correction below.)*
     `spawned_at`'s format, the write-failure marker's filename and its content, and
     the store line's encoding are pinned in the published spec page
     (`docs/process-trace-store.md`), which is the artifact other tools implement against; §20
     carries only the contract items. The entry's key names are **not** in this class -- they are
     ruled upstream and reproduced verbatim.

     ~~The forced reading is §20.1's seam: the ruling says "the effects spawn seam" without saying
     which effects reach it, and only one reading is consistent with the rest of this document. A
     dry-mode `spawn` starts no process, so it can write no entry; an allowlisted observe really
     executes in dry mode (§3.1) and therefore can. Any other reading either records a spawn that
     did not happen or makes the entry's `dry_run` field permanently false.~~ **Corrected at the
     sweep:** §20.1's seam reading is **authored, not forced**. The ruling says "the effects spawn
     seam" without saying which effects reach it; the reading adopted -- real child-process starts
     only, so a recorded dry-mode spawn writes nothing and an allowlisted observe writes an entry
     carrying `dry_run: true` -- is the one this document adopts and defends, not the only one the
     regime permits. The "records a spawn that did not happen" objection does not close the
     alternative, because the spec page's own definition says an entry describes the **spawning
     invocation**, not the child; a dry-mode entry would therefore be a truthful record of an
     invocation that previewed a spawn. What rules it out here is the argument in §20.1, weighed
     and adopted, and it is reversible by amending that bullet. The half that *is* forced stands:
     under any reading excluding observes, the entry's `dry_run` field could never be true. The
     same reading keeps the trace write outside §3.1's "nothing runs" rule instead of making it a
     second framework-blessed exception to it.

     **Added at the sweep**, all page-level authored spellings that were in force but unlisted:
     the store directory's creation mode (`0700`); the every-key-always-present rule and its
     corollary that an absent key makes a line malformed rather than defaulted; `command: null`
     for an invocation that resolved no command and `parent_id: null` for a root; `pid` being the
     **spawning** process's own pid rather than the child's; the requirement that the identifier's
     80 random bits come from a cryptographically secure source; the rule that readers ignore any
     file in the trace directory not matching the partition-name pattern; and the failure marker
     living inside the trace directory, which is what makes that reader rule necessary. Added by
     the sweep itself: **the store path is the literal ruled path** -- `~/.local/share/strictcli/trace/`
     with `~` expanded and nothing else consulted, explicitly **not** derived from `XDG_DATA_HOME`
     or any other variable, because two conforming writers disagreeing about the location would
     produce two stores on one machine and a chain dangling in both.

     Two §19.4 derivations belong in this class too, and are recorded here rather than left
     implicit: calling the payload API on a command that declares **no** payload schema is a
     **call-time** hard error, because registration cannot see that a handler intends to call it,
     which makes the call the earliest honest point; and the programmatic surfaces (`test()`,
     `call()`, `Call()`) **keep their capture**, returning the payload the handler supplied exactly
     where they previously returned the `data` it attached, so deleting the bare-JSON-print channel
     costs the in-process surfaces nothing.

     One further authored spelling, at §2.5.2: when a handler's `env` mapping names
     `STRICTCLI_TRACE_PARENT`, the framework's ancestry composition is applied **after** the merge
     and wins. Nothing in the rulings decides this, and the alternative (handler wins) would let a
     handler sever or forge the chain through an ordinary environment override.

     **Added at the implementation round (2026-08-13), all on the spec page and all marked there as
     authored**, at points the page had been silent on and an implementation could not avoid
     deciding:

     - **The entry is written immediately before the child-start attempt**, so an entry exists even
       when the start itself fails. Forced in ordering (the identifier must exist to be composed
       into the environment the child starts with), authored in consequence (nothing retracts it).
     - **A write failure removes the variable from the child's environment** rather than leaving
       whatever this process inherited. The alternative re-attributes the child to its grandparent
       -- a wrong link where an absent one is honest.
     - **An inherited value that is not a valid identifier records `parent_id: null`.** The
       alternative -- copying it verbatim, as the entry table's wording taken alone would allow --
       puts a string no conforming reader can parse where every other identifier is profile-valid.
       The cost is recorded rather than hidden: the store then cannot distinguish a real root from a
       polluted variable, and the [Consumers] rule that malformed data is recorded verbatim as an
       anomaly is what still catches it, at the consumer's own capture seam where the polluted
       variable actually is.
     - **Files are created with mode `0600`**, partitions and marker alike -- the page pinned the
       directory's `0700` and said nothing about the files, which would otherwise follow the umask.
     - **The marker's timestamp is unclamped**: no partition was selected when the write failed, so
       there is no range to clamp into.

     **Amended at the lookup-rule audit (2026-08-13), on the spec page and marked there in place.**
     An independent audit found the page's lookup rule falsified by the page's own rolling rule, and
     the correction is authored in this same class:

     - **The range invariant is ONE-SIDED.** The clamp bounds an entry's timestamp from below -- an
       entry is never older than the label of the file it is written to -- and bounds nothing from
       above. The page's claim that every entry lies *within* its file's half-open range was false:
       a file rolls only when it is at least 8 MB **and** the hour has advanced, so a small file
       keeps taking entries for hours, and once it finally crosses the threshold the next partition
       is labelled for the hour that write happens in. The earlier file is then holding entries at
       or beyond the newer file's label.
     - **Lookup is a binary search followed by a backward walk.** Search the sorted labels for the
       greatest one not after the identifier's embedded timestamp, read that partition, and **on a
       miss continue with the next older partition until the entry is found or the partitions are
       exhausted.** The audit constructed the falsifying store -- an hour-09 entry in a `...T04`
       partition beside a `...T09` partition -- where the single-search rule reports a live entry as
       missing and a consumer then records a dangling parent that is not dangling.
     - **No writer behaviour changes.** All three implementations already clamped exactly as the
       one-sided invariant describes; what was wrong was the page's statement of the invariant and
       the reader rule derived from it. The test-side chain resolvers in this repository (the only
       readers it owns, per §20.2) implement the amended rule, and each language's suite pins the
       stranded-entry store.
     - **The page's entry example was internally inconsistent** and is regenerated: its identifier
       decoded to `2025-07-03T19:45:10.869Z` while the `spawned_at` on the same line read
       `2026-08-13T04:17:52.913Z`, contradicting the page's own rule that `spawned_at` is exactly
       the millisecond embedded in `id`.

Nothing else in this document was decided at authoring time. Every remaining statement is either
verbatim from the ratified pin list or a direct reading of the code as it stands, cited in place.

### 18.10 Amendments made at the mutex-election round (2026-08-13)

This round records five rulings made upstream about **which typed token elects a mutex group's
member** (campaign decisions A1-A5). Items 113-117 are ruled upstream, not authored here; item 118
is an authored spelling in the §18.3 class, fixing the message texts and the value-delivery
consequence the rulings left open. The round writes §21 and amends nothing else: mutex election is
a parse-time constraint, not an effects-regime one, and it touches this document only because
this document is where cross-language spellings are pinned. Item 119 was added afterwards and is
neither a ruling nor a spelling: it records a carve-out to §21.3's wording that every
implementation already had, and changed no code.

The evidence behind the round, measured across six consumer projects: 18 production mutex groups,
15 of them containing a bool, 14 carrying the present-false hole, 8 carrying hand-written
"nothing was chosen" guards written to compensate for it, and 2 actively dangerous -- one where
declining a mode silently selected the *other* mode's destructive behaviour, one where declining
a narrowing option silently widened the operation to everything. Zero legitimate present-false
uses were found.

113. **A bool member elects its group only when its resolved value is true (§21.2).** A
     present-but-false member -- `--no-x` on the command line -- elects nothing. Before this
     ruling, presence alone elected, so typing the negation of one option *chose* it, which is
     the inversion the two dangerous sites shipped.

114. **A string member elects on presence with any value, including the empty string (§21.2).**
     Typing `--profile ""` is an explicit act; whether `""` is a legal value for that flag is
     flag-level value validation and never the mutex layer's business. The handler-side
     consequence is stated in the docs: a handler on a mutex member tests `is None`, never
     truthiness.

115. **The unsatisfied-group error teaches, when a declined member is what made it unsatisfied
     (§21.4).** `one of --profile, --all-profiles is required (--no-all-profiles declines an
     option; it does not choose one)`. The clause is appended only when at least one bool member
     was present-and-false on the command line; the bare message is otherwise unchanged.

116. **A redundant negation beside a real election is a parse error (§21.4).** `--profile work
     --no-all-profiles` is refused rather than accepted-and-ignored: every typed token does
     something or errors. It is NOT the "mutually exclusive" case and does not borrow that
     message, which would be a lie -- nothing about the two tokens conflicts; the second one
     simply cannot mean what typing it suggests.

117. **Mutex election is CLI-only (§21.3).** Env and config sources no longer elect a member. A
     mutex group exists to force the operator to choose *in the invocation*; a value inherited
     from an environment two shells up, or from a config file written last year, is not that
     choice. Measured usage of env- or config-elected mutex members across the fleet: zero.

118. **Authored spellings and the value-delivery consequence (§21).** Ruled upstream: the
     teaching clause's wording (item 115) and that A4 is an error (item 116). Authored here:

     - **The A4 message text**, pinned byte-identically in three languages:
       `<declined> cannot be combined with <elected> (<first-declined> declines an option; it
       does not choose one)`, where `<declined>` renders each declined member as `--no-<name>`
       in group-declaration order joined by ` and `, `<elected>` renders the electing member as
       `--<name>`, and the parenthetical repeats item 115's clause verbatim so the two errors
       teach with one sentence, not two.
     - **The clause names the FIRST declined member in group-declaration order** when more than
       one member was declined. Item 115's ruling shows the one-member case only, and a clause
       that grew a list would stop reading as a sentence.
     - **The error precedence inside one group**: more than one election is the mutually-exclusive
       error (unchanged text, listing the electing members only); exactly one election plus at
       least one declined member is the A4 error; no election is the required error, with the
       clause when anything was declined.
     - **An unelected member never carries an env or config value (§21.3).** Item 117 says those
       sources do not *elect*; it does not say what happens to the value. Leaving the value in
       place preserves exactly the hazard the round exists to remove: `--url` typed on the command
       line beside a stale `FILE` in the environment would deliver *both* members non-empty, and
       every handler in the fleet reads such a group by testing its members in declaration order.
       So a mutex member's value comes from the command line or from that flag's own declared
       default, and env and config are not consulted for it at all. The suppression happens before
       dependency validation, so `Requires`/`CoRequired`/`Implies` see the same state the mutex
       layer does. A *declared default* still applies to an unelected member -- a default is a
       property of the flag, not an election, and item 117 says nothing about it.

119. **Clarification (not a semantics change): `config_conflict_mode="error"` still fires on an
     elected member (§21.3).** §21.3's "not consulted at all" was written about election and
     value delivery, and read literally it also denies the both-sources conflict check, which
     was never true of any implementation. The conflict check is a value-hygiene rule about the
     operator's own configuration -- it runs before mutex suppression, elects nothing and
     delivers nothing -- so an app with `config_conflict_mode="error"`, a config value for a
     member, and a diverging command-line election of that same member reports the conflict and
     exits. On an unelected member no conflict is reachable: nothing on the command line can
     diverge from the config value. The behaviour predates the mutex-election round, is pinned
     by `test_conflict_mode_fires_before_mutex` (Python) and
     `TestConfigConflictModeFiresBeforeMutex` (Go), and no implementation changed for this item
     -- §21.3 gained the carve-out paragraph, and nothing else.

### 18.11 Amendments made at the protocol round (2026-08-14)

This round implements campaign decisions 5, 6 and 26 and the audit additions attached to them. It
adds §22 and amends §8.3, §8.4, §8.5, §12.6 and item 93 in place. Items 120-122 are **ruled
upstream**; items 123-126 are authored spellings in the §18.3 class -- the mechanical remainder
the rulings left open, decided here so implementors had nothing left to decide.

120. **The shared seam requires consent, and each transport obtains it (campaign decision 5).**
     Ruled upstream against this repository's two open records: the MCP auto-approve finding and
     the challenge-token design's three lettered options. `Call` gaining a consent parameter had
     already been implemented at the non-CLI consent round (item 93); what this round adds is the
     other half of the ruling -- a transport that *obtains* the consent rather than only carrying
     it. The stated cost of the seam change was verified to be zero: `Call` has exactly three
     callers, all inside this repository.

121. **A refusal must not print the token that lifts it (audit addition to decision 5).** Both
     refusals are amended (§8.3, §8.5, §12.6). The observed failure was an agent clearing the
     non-interactive refusal by appending the flag it named, within one retry. The amended texts
     name what is required -- confirmation -- and never how to force the command through without
     it, following the same rule the campaign's decision 25 applies to a missing tool: name the
     remedy, never an override.

122. **The confirmation semantics are published as a declared feature (campaign decision 26).**
     A NAME (`dev.smmh.strictcli/consequential-confirmation`), never a version number, matching
     decision 9's features-not-numbers ruling. The tool descriptors' `effect` / `consequential`
     properties (item 93) are the other machine-readable half; the published page and the
     client-declaration error are the next round's.

123. **The server is dual-era, and the legacy branch is untouched (§22.1).** The alternative was
     to delete the handshake outright. Retaining it costs one boolean of connection state, is
     exactly what the modern revision specifies for a server serving both, and leaves §11.6's
     legacy branch somewhere to live. A request carrying neither era's marker is refused rather
     than guessed at, which is the same rule as everywhere else in this document.

124. **An unrecognized key under a reserved prefix is refused, not ignored (§22.2).** The
     protocol defines the prefix as its own namespace but does not say what a server must do with
     an unknown key in it. Ignoring it would mean silently accepting a vocabulary this server does
     not speak, which is the failure mode this framework exists to prevent.

125. **The continuation's shape: HMAC-SHA256, a per-process key, 300 seconds, single use
     (§22.4).** The protocol requires integrity protection and *recommends* the three bindings;
     it explicitly leaves single use to the server, and this server enforces it. 300 seconds is
     the one number with no external anchor: long enough for a human to answer a dialogue the
     client renders, short enough that a captured blob is worth little. The principal is
     self-reported on this transport and §22.4a says so rather than implying otherwise.

126. **Conformance grows a capture-and-splice step vocabulary (§22.5's cases).** A round-trip
     cannot be scripted from static lines, because the retry has to quote a blob that is
     unguessable by construction. Steps gain `capture` (a name and a dotted path into the reply)
     and `send` gains `{{name}}` and `{{name|tamper}}`. The vocabulary is closed, and `tamper` is
     the whole reason it exists: an integrity-protected value that no case ever corrupts is an
     unchecked value.

### 18.12 Amendments made at the confirmation round (2026-08-14)

This round finishes §22.6's deferrals: the client-declaration error, the legacy era's branch, and
the published page that campaign decision 26 requires. It amends §22.1, §22.3 and §22.6 in place
and adds §22.7. Nothing here is a new ruling -- the rulings are decisions 5, 9 and 26, already
recorded at §18.11 -- so every item below is an authored spelling in the §18.3 class: the
mechanical remainder those rulings left open, decided here so implementors had nothing left to
decide.

127. **The undeclared-capability answer is `-32021`, and it names FORM mode (§22.3).** The
     revision forbids sending an input request the client never declared it could fulfil and
     assigns the code for saying so; the message is the revision's own example text, and
     `data.requiredCapabilities` is a client-capabilities object. Naming `{"elicitation":{}}`
     there would have been the shorter spelling and the wrong one: it reads as "any elicitation
     mode", and a client that came back declaring URL mode only would be refused a second time.
     The refusal names what is required and never how to proceed without confirming, which is
     item 121's rule applied to a machine reader.

128. **The legacy era advances to `2025-11-25` (§22.1, §22.7).** The alternatives were to stay on
     the protocol's first revision (`2024-11-05`, which has no elicitation at all, so the legacy
     branch could not exist) or to pick `2025-06-18` (which introduced elicitation, but before the
     `mode` field). `2025-11-25` is the newest handshake-based revision -- the era's own boundary
     as the modern revision draws it -- and it is the one whose `elicitation/create` params are
     spelled exactly as §22.5's are, so the same request object serves both vehicles. The legacy
     negotiation rule tells a server to answer with the latest version it supports, which this is.

129. **The continuation blob IS the legacy correlation id (§22.7).** A server-initiated request
     needs its response matched to it, and the obvious spellings -- a counter, a random token, a
     map from id to pending call -- would have been a second correlation mechanism beside the one
     §22.4 already built. JSON-RPC obliges a client to echo the id verbatim, which is the same
     obligation the modern era puts on `requestState`, so the blob rides as the id and is verified
     on return through the one mint-and-verify path. A matching id that fails the MAC, the expiry,
     the principal, the digest or the single-use check confirms nothing.

130. **In the legacy era everything that is not an explicit acceptance aborts, and there is no
     re-ask (§22.7).** The modern era re-asks a client that came back without an answer because
     the client is free to return whenever it likes; here the server is holding the request open
     and a non-answer -- a decline, a cancel, an unreadable result, a JSON-RPC error, or the
     stream ending -- is a decision. Fail-closed is the only reading consistent with §8: an
     unconfirmed consequential command does not run.

131. **Client traffic that arrives while the server is waiting is held, not dropped (§22.7).** A
     response whose id is not the awaited one is discarded, because this server sent no such
     request; a request or a notification is queued and served after the interrupted call
     completes. Dropping it would silently lose a client's work, and answering it mid-exchange
     would make the loop reentrant for no gain.

132. **The declared feature is advertised in both eras (§22.7).** `server/discover` advertises it
     under `capabilities.extensions`; the handshake result advertises the same name under
     `capabilities.experimental`, which is where the legacy revision puts a non-standard server
     capability. One name, two advertisements -- a legacy client can learn this server asks
     without inferring it from a revision date, which is the whole of decision 26.

133. **The published page is `docs/mcp-confirmation.md`.** Decision 26's third surface. It is a
     hand-written page on the published docs site (not under `docs/history/_*`, which is
     deliberately unpublished), and it carries the dialogue in both eras, the feature name, and
     what a client must declare. The quickstarts link to it rather than restating it.

### 18.13 Corrections made after the confirmation round's audit (2026-08-14)

An independent audit of §22's seam found three defects between what this document says and what
the three implementations did. Nothing below is a new ruling or a changed guarantee: each item
records the mechanics that were missing where the document already promised the behaviour, and
the correction that made the promise true.

134. **The legacy abort was not consuming its continuation (§22.7 item 4, §22.4).** Item 130 says
     everything that is not an explicit acceptance aborts, and §22.4 says verification is
     consumption -- but the legacy loop only reached the verify (and therefore the spent-id set)
     when a well-formed `result` came back. A stream that ended, a JSON-RPC error response, and an
     answer under an id the server never minted all aborted **without spending the blob**, which
     left it valid for the rest of its five minutes, bound to the same principal and the same
     request digest the modern era mints. The client could then present it as `requestState` on
     the modern path with an acceptance of its own writing, and the consequential command it had
     just aborted **ran**. Fail-closed was a promise the code did not keep. The correction is one
     line of position, in all three implementations: consumption happens as soon as the awaited
     answer resolves, before any exit is chosen, so writing the elicitation is what commits the
     blob. A blob whose exchange never started (a non-consequential command, a client that
     declared no elicitation) is never minted and so has nothing to spend.

135. **The blob's base64url spelling is validated, not left to three decoders (§22.4).** §22.4
     says unpadded base64url and §22.2 says the refusals are byte-identical; both were true of
     the *messages* and false of the *verdicts*. Each language was reading the segments with its
     own stock decoder, and those accept different texts: a `requestState` with one `=` appended
     was refused by Go and **accepted by Python and TypeScript, which then ran the command**. The
     audit found that one; writing the vector set found three more, all of them shared by
     languages the audit had cleared -- an embedded newline (Go's decoder skips them), a
     character outside the alphabet (Node's decoder skips them), and a final character whose
     ignored trailing bits are non-zero, which every one of the three accepted as an alias for
     the canonical blob. The correction is one predicate, written the same way in all three:
     alphabet only, no padding, no length one past a multiple of four, zero trailing bits, run on
     each segment before the decode. A canonically-spelled blob is unaffected -- no encoder emits
     anything else -- so this only narrows what a client can hand back.

136. **All three sort the `_meta` key set, not just Go (§22.2).** §22.2 recorded the sort as a Go
     implementation note -- Go's map iteration is randomized, so it had to sort to be
     deterministic at all -- and Python and TypeScript validated in document order. A request
     carrying two offending keys therefore got a *different named key* from each, which is a
     refusal text that is not byte-identical, against §22.2's own promise. Sorted was already the
     documented order, so the correction is to sort in the other two rather than to unpick Go's.
     TypeScript sorts over the encoded UTF-8 bytes: its default comparison is over UTF-16 code
     units, which orders an astral character before a BMP one and would have reintroduced the
     same divergence in a narrower corner.

### 18.14 Amendments made at the presence round (2026-08-14)

This round is the first phase of the declaration-regime campaign. It adds §23, adds §12.12, amends
§0 and §13, and amends §21.3 in place. Items 137, 138, 143 and 147 are **ruled upstream**; the rest
are authored spellings in the §18.3 class -- the mechanical remainder the rulings left open, decided
here so implementors have nothing left to decide, and ~~written **before** any implementation, which
is the §19 discipline this campaign adopted explicitly.~~ *(amended 2026-08-14, implementation
sweep)* written **before** any implementation, which is the §19 discipline this campaign adopted
explicitly. **Items 137-150 are that pre-implementation record and are unchanged. Items 151-~~158~~
159 *(extended 2026-08-14, conformance sweep)* were added after the three implementations
shipped**, and each of them records something the implementations surfaced -- or, for item 159, the
cross-language sweep did -- that the pre-implementation text had left open, under-specified, or
described as settled when it was not. They are all in the §18.3 authored class -- implementation-
forced spellings and convergence picks -- and carry no origin tag, because none of them is an
upstream ruling of either kind.

**Origin tags.** This section is the first in §18 to carry them, because the campaign's own decision
record distinguishes two kinds of upstream ruling and the distinction should survive into this
document. `[%%]` marks a ruling adopted from a **recommendation** -- the user picked a recommended
option, which is trust rather than a deliberate directive, and such a ruling is **freely
reversible**: a later session finding it wrong should walk it back without treating it as settled
intent. `(D)` would mark the user's own proposal or an explicit directive. **Every ruled item in
this round is `[%%]`.** None of them is a deliberate directive, and nothing here should ever be
cited back as one.

The evidence behind the round, measured across the fleet: 140-182 Python flags written for a
"not provided" meaning Python did not have and silently required instead, three dead
"no fields specified" guards behind them, 214-375 flags using `default=""` as an absence sentinel,
9 sites writing a tool-picked value on absence, 2 shipped commands writing the wrong value on
every edit because absence forced a restatement, a schema that erased requiredness so parity passed
by erasure, three MCP projections disagreeing about required bools, and zero conformance coverage
of optional-flag absence in any language.

137. **[%%] Every flag declares exactly one of required, optional, or a value default (§23.1).**
     Omitting all three is a registration-time hard error; supplying two is a registration-time
     hard error. The rejected alternatives are on the record: a silent fleet-wide flip of the
     177 affected sites (a no-silent-degradation violation), and keeping both `presence=` and a
     null-valued default as synonyms (two spellings for one fact). What was ruled is the rule and
     the shape; the per-language spellings are item 139's.

138. **[%%] A null-valued default is a registration error that redirects to the optional spelling
     (§23.1, §12.12).** `default=None`, `Default(nil)` and `default: null` stop being declarations.
     Go and TypeScript **lose a working spelling** here, which is the cost of the ruling and is
     paid deliberately: their `Default(nil)` / `default: null` delivered exactly the right
     behaviour, and letting it stand beside `presence="optional"` would leave optionality with two
     spellings in two languages and one in the third. The redirect names what to write instead and
     says what it delivers, so the error teaches rather than forbids.

139. **The authored spellings, per language (§23.2, §23.3).** Python `presence="required"` /
     `presence="optional"` / `default=<value>`; Go the three sibling `FlagOption`s `Required()` /
     `Optional()` / `Default(v)`; TypeScript a discriminated union on `presence` with members
     `{presence:"required"}`, `{presence:"optional"}` and `{presence:"default", default: Out}`.
     Each follows its own framework's existing conventions rather than a shared invented one:
     Python already declares with keywords, Go already declares with functional options, and
     TypeScript's `ArgOpts` has been a three-shape union since the port -- the flag surface adopts
     the precedent that already existed one factory over. The Go struct-literal path is pinned as
     part of the same item: a `Flag` literal that never passes through the constructors declares no
     presence and does not register, which incidentally closes the trap where an exported `Default`
     field set on a literal was silently ignored because the unexported `hasDefault` stayed false.

140. **The arg surface takes the same three-way declaration, and `required=` is deleted
     (§23.3).** Ruled: the model is the same for args. Authored: that `required=` /
     `ArgRequired(bool)` / `required?: boolean` are **removed** rather than kept beside it.
     `required=True` was an implicit default -- the same derivation the round removes from flags --
     and `required=False` plus `default=` spelled one fact across two fields with a guard holding
     the illegal corner shut. Authored with it: `default` on a variadic arg is a registration error
     (a variadic always delivers a list, so the empty case is `optional`), and an optional arg
     delivers a **present key** holding absence rather than omitting the kwarg, which is the same
     rejection of key-absence delivery the round applies to flags.

141. **All five derivations are deleted, including the mutex-member exemption (§23.4).** Python's
     `default=None` collapse, Go's `hasDefault`-only inference, TypeScript's `default === undefined`,
     the silent empty-collection default for compound flags, and the parse-time exemption that
     handed mutex members an absent value their declaration never asked for. The last one is a
     prerequisite for the constraint round, and it is also what makes §21 read correctly: a group
     decides which member is chosen, a member decides what its own absence means.

142. **The composition matrix (§23.5).** Fifteen rows, each with an answer per presence, because a
     three-way declaration multiplied by every other declaration in the framework is exactly where
     an unstated cell becomes an implementation divergence. The two whole-table rules decide the
     most cells: the default-in-choices check applies to declared **values** and never to
     absence (which is what lets `choices` compose with `optional` in both directions), and
     requiredness is satisfied by **any** source that provides a value -- CLI, env, config or an
     implication -- rather than by a command-line token specifically. Three cells are authored
     decisions rather than descriptions of today: a mutex member declaring requiredness is a
     registration error (the group's own requirement is what makes the choice mandatory); a
     `CoRequired` group containing a required member is legal and forces every other member in
     every invocation; and an `Implies` trigger never fires from its own default.

143. **[%%] `ctx.provided(name)` is the idiomatic "was this supplied?" accessor (§23.6).** Ruled:
     the accessor exists in all three languages and `ctx.source()` stays for its narrower
     origin-distinguishing uses. Authored: the per-language spellings (`ctx.provided` /
     `ctx.Provided` / `ctx.provided`) and the semantics -- `cli`, `env`, `config` and `implied`
     count as provided, `default` and `infra` do not. The dividing line is *what caused the value*:
     the invocation, or the declaration. `implied` is on the provided side because an implied value
     exists only when the invocation contained the trigger; `infra` is on the other side because a
     `RelativeToRoot` default is a declared default whose label merely says which default it was.
     An optional flag that received nothing carries source `default` rather than a seventh label:
     an optional declaration deciding on absence **is** the declaration deciding. Unknown names
     reuse `ctx.source`'s existing behaviour and its existing message.

144. **The dumped schema gains one canonical `presence` key, and the arg-side `required` key is
     deleted (§13's amendment box).** Always emitted, `effect`'s shape rather than
     `consequential`'s, on flag entries and arg entries alike; `default` emitted exactly when
     `presence` is `"default"` and then **always**, including for `[]`, `{}`, `""`, `false` and
     `0`, since under §23 those are declarations rather than the absence of one. The
     omit-when-empty compound rules die with it. `check_schema_parity.py` gains an assertion that
     the key is present on every entry: the erasure is precisely what let three implementations
     certify agreement about a fact none of them emitted, and a parity check that cannot fail on a
     missing field would let it happen again. The conformance **case** schema keeps `null` in its
     `default` union so a case can still spell the declaration item 138 refuses.

145. **The three MCP requiredness derivations collapse onto the declared field (§13's amendment
     box).** A parameter is in a tool schema's `required` array iff its declared presence is
     `required` -- flags and args alike. The three-way disagreement about **required bools** goes
     with them: Go and TypeScript excluded bools on the reasoning that "bool flags always have a
     default", which this round makes false by construction, so they now match what Python already
     emitted.

146. **The help markers converge, and two renderings change bytes (§23.8).** Every flag and every
     arg renders exactly one presence part, last on the line: `[required]`, `[optional]`, or
     `[default: <value>]`. `[optional]` was Go-and-TypeScript-only and Python gains it, which is
     the majority rendering and the only one that can express the new declaration. The two authored
     changes are the ones the invariant forces: a declared empty collection renders
     `[default: []]` / `[default: {}]` where all three rendered nothing before (the empty
     collection used to be the framework's own silent default, so there was nothing to announce),
     and a **required positional arg** renders `[required]` where all three rendered no marker --
     there is no usage line in this framework's help output, so a required positional was the one
     declaration whose presence a reader could not see. The literal empty-collection spellings are
     used rather than a new word, so the help vocabulary does not grow.

147. **[%%] A Python handler parameter bound to an optional flag must default to `None`
     (§23.3, §12.12).** The cheap half of a rung the campaign otherwise rejected: it blocks
     re-sentinelization at the handler boundary, which is where the declaration's honesty would
     otherwise be undone one line later. Authored: the message text, the extension of the same rule
     to optional **args**, and the exclusion of Go and TypeScript -- their handlers receive one
     kwargs map / one args object, so there is no per-parameter default to check. That is an absent
     site, not a skipped check.

148. **§21.3 is amended in place rather than contradicted (§21.3, §23.4).** Its sentence "an
     unelected member delivers its declared default, or nothing when it **declares none**" was
     written when declaring nothing was a legal state. After this round the same behaviour is
     reached by declaring `optional`, so the clause is struck and restated with the new spelling
     and everything else about §21 stands: election is still CLI-only, env and config are still not
     consulted for a member, a declared default still applies to an unelected member, and the
     `config_conflict_mode` carve-out of item 119 is untouched.

149. **Four registration templates are deleted (§12.12).** The three
     `explicit empty default is redundant for <kind> flags, omit the default` errors, because an
     explicit `[]` or `{}` is now a declaration and omitting it is now the error; and
     `required arg cannot have a default`, because the two-declared error says the same thing for
     every pair and names both spellings. They are removed from all three catalogs rather than left
     dormant: a template no code path can reach is a claim about behaviour that no longer exists.

150. **The round's boundary is declared, not left to inference (§23.9).** `ConfigField`
     requiredness keeps its derivation -- a config field has no command-line presence, no help
     marker, no MCP projection and no `provided` question, so the failure this round removes cannot
     arise for it. The constraint system, the update-command construct and the consumer-side
     retirement of the `default=""` idiom are separate work with their own amendments. Stating the
     boundary is what stops a later reader treating an untouched surface as an oversight.

**Added after implementation (2026-08-14, implementation sweep).** Items 151-158 continue this
round's numbering rather than opening a section of their own: they belong to the presence round,
they amend only sections the round added or rewrote, and none of them reverses a ruling above.
Three are convergence picks -- one implementation was right and the other two change (152, 156,
157) -- and the rest are spellings the pre-implementation text left open. All are §18.3-class.

151. **The arg twins substitute the noun in the trailing parenthetical (§12.12).** An `Arg` message
     is its `Flag` message with three substitutions and no others: the prefix, the spellings, and
     the noun inside every trailing parenthetical (`... when the arg is absent`). The
     pre-implementation text named the first two and left the third to inference, which made the
     flag-side parenthetical readable as the arg twin's own text. All three implementations wrote
     the substitution independently; pinning it turns three coincidences into the rule that governs
     the whole family, including any template the family later grows.

152. **The unreachable arg-side list-default validation family is deleted (§12.12).** Three
     templates validating the default value of a **list-typed positional arg** -- must-be-a-list,
     explicit-empty-is-redundant, and the element-type loop behind them. A list-typed arg must be
     variadic and a variadic arg refuses any default (item 140), so no declaration can reach them.
     All three implementations delete the family; Python's block was already gone from the round's
     own arg rewrite, so this is Go and TypeScript converging onto where Python stood. The rule
     applied is item 149's, extended from obsolescence to unreachability: a template no code path
     can reach is a claim about behaviour that does not exist, and keeping it would make the
     error-parity surface certify agreement about a message none of the three can print.

153. **Two language-specific template families are ratified, and excluded from cross-language error
     parity (§12.12).** Each names a state only one language's spelling can reach, so a sibling has
     no input that could produce it. Python-only: a `presence=` value that is neither `"required"`
     nor `"optional"`, which exists because Python spells the declaration as a keyword taking a
     string and Go's options and TypeScript's union have nothing to mistype. TypeScript-only:
     `presence: "default"` carrying no `default`, which exists because TypeScript is the only
     language whose default spelling has two parts -- Python's `default=<value>` and Go's
     `Default(v)` *are* the value. The exclusion is a consequence of the spellings item 139
     authored, not a parity defect, and it is recorded here so a later reader does not "fix" it by
     porting dead text into two catalogs.

154. **Three declarations at once, and the nil default's spelling inside the declared-twice message
     (§12.12).** A declaration carrying all three facts renders the same declared-twice error,
     naming the **first two** in the canonical order `required`, `optional`, `default` -- the
     message's job is to say more than one was declared and to name what to remove, and a third
     name changes neither. The count is never printed, so a two- and a three-declaration error are
     byte-identical when their first two spellings agree. Second: Go renders a nil default as
     `Default(nil)` / `ArgDefault(nil)` inside that message rather than through
     `formatValueForError`, because the count check runs before the null-default refusal, so
     `Required()` beside `Default(nil)` reaches the declared-twice message and must name what was
     written.

155. **The handler-parameter check reads narrowly (§23.3).** It fires only when the bound parameter
     **has** a default and that default is not `None`; a **bare** parameter is legal. The wide
     reading -- every optional-bound parameter written `=None` -- is unimplementable, because
     Python forbids a parameter without a default after one that has it, so the rule would force
     handler authors to reorder parameter lists that have nothing to do with presence. It is also
     unnecessary: absence arrives as a present key on every dispatch, so a bare parameter receives
     the framework's `None` and there is no competing value. The hazard item 147 exists for is a
     *written* sentinel, and a bare parameter writes none.

156. **The `validate` row's `default` cell supersedes shipped Python behaviour (§23.5).** Item
     142's matrix was presented as pinning cells that were either new decisions or unwritten
     descriptions of today. This cell is neither: Python **ran `validate` on the declared default**
     when nothing supplied a value, and Go and TypeScript did not. The matrix picks the majority,
     Python changes, and the reason is the round's own -- a default is the declaration's value, the
     author's to get right at registration, and validating it at parse time makes a declaration's
     legality depend on an invocation that never mentioned it. Recorded as a behaviour change so a
     reader of the cell does not take it for a restatement.

157. **The dependency predicate excludes `infra`, which changes shipped Go and TypeScript behaviour
     (§23.6).** Item 143 said `ctx.provided` reuses the predicate `CoRequired`, `Requires` and
     `Implies` already use, "so the framework has one definition of was this supplied, not two". It
     had two: all three excluded `default`, but only Python also excluded `infra`, so a
     `RelativeToRoot`-defaulted flag inside a dependency family counted as present in Go and
     TypeScript. The pin is one predicate excluding both labels in all three, with Python as the
     reference. The consequence is real: an infra-defaulted flag no longer satisfies a dependency
     on its own. That is the direction item 143's own dividing line requires -- an infra default is
     a declared default whose label says only *which* default it was.

158. **Three help renderings the presence invariant reached (§23.8).** A **bool default renders
     lowercase everywhere**, positional args included: item 146 said so about flags, and Python's
     arg side rendered `[default: True]` through its generic formatter, so one declared value
     rendered two ways in one help page. A **non-empty dict default renders as sorted `key=value`
     pairs** (`[default: a=1, b=2]`) in all three, which closes a live divergence rather than
     restating agreement -- Go rendered nothing at all for one, leaving the line without the
     presence part the invariant requires. And the **app-level `Global flags:` summary carries no
     bracketed metadata and deliberately keeps none**: it is an index of what exists, the flag's
     full line is rendered at command level where it is used, and putting a presence part in both
     places would state one fact twice in a single help run.

159. **An infra-rooted default renders as its declaration, and Go stops leaking its struct
     formatting (§23.8).** A `RelativeToRoot` default's presence part is
     `[default: RelativeToRoot('<VAR>', '<part>', ...)]` in all three implementations, quoted as
     Python's `repr` quotes a string and never carrying the resolved, machine-specific path. Python
     and TypeScript already produced exactly this; **Go rendered `[default: {MYAPP_ROOT [store]}]`**
     -- `fmt`'s `%v` on a marker that had no display form, which put Go's internal struct shape in
     the help output of a declaration a reader wrote by name. This is the third rendering the
     invariant reached that item 158 did not enumerate, found by the cross-language sweep rather
     than by the implementations themselves, and it converges onto the majority form.

### 18.15 Amendments made at the scoped-selector round (2026-08-14)

This round is the second phase of the declaration-regime campaign. It adds §24 and §12.13, adds four
§0 terminology rows, supersedes §21 item by item, and amends §7.1, §19.1, §23.1, §23.5, §23.9 and
§12.12's mutex entry in place -- the §7.1 and §19.1 amendments being item 169's every-level name-ban
substitution, and §23.1's the same substitution on the presence rule's own level list. §23.2, §23.4
and §23.5's second whole-table note were amended later, at the read-back audit (§18.17 item 201),
which found them falsified by this round and unamended. Numbering continues §18.14's rather than
restarting, for the reason that section gives: these are the same campaign's ledger.

**Origin tags**, per §18.14's preamble. `(D)` marks the user's own proposal or an explicit
directive; `[%%]` marks a ruling adopted from a **recommendation**, which is trust rather than
deliberate intent and is **freely reversible** -- a later session finding it wrong should walk it
back without treating it as settled. Untagged items are authored spellings in the §18.3 class: the
mechanical remainder the rulings left open, decided here so implementors have nothing left to decide.
This round is the first to carry `(D)` items: the construct itself and member spelling are the
user's own proposals, sketched by the user before any ladder ran.

**One item carries no tag on purpose.** The constraint-system restatement (item 176) is recorded
untagged because the campaign's own decision record carries it untagged: it is neither a directive
nor an adopted recommendation but the consequence of items 160 and 161 -- once exactly-one is a
selector, it is no longer a constraint family, and no separate decision was taken.

**Written before any implementation**, which is the §19 discipline this campaign adopted explicitly
and the presence round's items 137-150 followed. Anything the implementations surface later
continues this numbering as a sweep, exactly as items 151-159 did.

**The evidence behind the round**: three complete prototypes (`py/`, `go/`, `ts/`), one per
language, each with a running parser, registration validation, help rendering, schema and MCP
projections, error catalogue and a full challenge list. They proved the shape before it was ruled
on, and they produced two findings no design discussion had: **member spelling reproduces §21's
mutex sentences byte-for-byte**, so a migrated group changes no user-visible text; and the construct
deletes handler code that exists in the fleet today -- the `unreachable: the mutex guarantees
exactly one` branches, the "nothing was chosen" guards, and the "required exactly when user-facing"
checks. The fleet numbers behind the same pressure are §18.14's: 18 mutex groups, 15 containing a
bool, 14 with the present-false hole, 8 carrying hand-written no-choice guards, 2 actively dangerous.

160. **(D) The scoped-selector construct is adopted (§24.1-§24.3).** A choice is a declaration
     scope: a selector elects exactly one choice, each choice owns flags legal only while it is
     elected, an out-of-scope flag is a distinct parse error naming both sides, parsing is
     order-independent, recursion is legal to any depth, and delivery is **one tagged value per
     selector**. Sub-flags are never top-level handler arguments, which is what keeps §23's
     delivery invariant untouched rather than merely compatible -- and one level down §23 applies
     again unchanged, so an optional sub-flag delivers absence as a present field. Sub-flags declare
     presence like everything else. Authored with it: the four parse phases, the
     **election -> scope -> value -> presence** precedence rule, and the outermost-unsatisfied-election
     blame rule -- all three needed a decision, because without them the reported error depends on
     declaration order.

161. **(D) Member spelling ships in the first cut, and `MutexGroup` is subsumed and deleted
     (§24.4, §21's box).** A choice may be spelled as its own flag carrying its payload. The
     prototypes proved today's mutex sentences and `--no-x` decline semantics reproduce
     byte-for-byte, and members gain scopes -- so `--profile work --create-missing` parses and
     `--all-profiles --create-missing` is a scope error, where a group could only ignore it.
     Authored: the member flag's own presence **must** be `required` (read as *required once this
     member is elected*), a member-spelled selector cannot carry a short, and a payload is exactly
     one value under the reserved name `value`.

162. **[%%] Two constructs, one machinery, with a structural boundary (§24.2).** `choices=`
     survives as the value-flag spelling -- bare-scalar delivery, all three presences, all sources
     -- and the selector owns scopes and member spelling. The boundary: **need a scope or member
     spelling -> selector; a plain constrained value -> choices flag.** The graduation cost (scalar
     handler contract becomes a record) is accepted and stated in the section rather than left for
     a consumer to discover at migration time.

163. **The authored spellings, per language (§24.12).** Python `@choice`-decorated frozen
     keyword-only dataclasses plus `choice_flag` / `sub_flag` / `sub_choice_flag`, with
     **the field name as the flag name** and `elect_by=` mandatory with no default; Go
     `ChoiceFlag` / `MemberChoiceFlag` with `Choice(...)` **identity values**, `*Elected` delivery
     and `Match` / `When`; TypeScript `choiceFlag` / `memberChoiceFlag` with a keyed choice map and
     a discriminated union derived from the literal. Each is the shape its language's prototype
     validated and its existing idiom already pointed at (B9). Three authored details inside the
     item: Python's member payload is a `value` field declared with `member_value(help=...)`
     (replacing the prototype's `carries=`, which named a field the reserved name now fixes); Go's
     member spelling is a **twin constructor** rather than an `AsMembers()` option, so one fact is
     one declaration instead of two that must agree; and Go's `Match` is exhaustive at dispatch,
     which §17's accepted-ceiling reading covers.

164. **The value-flag record spelling, and the deletion of the bare-value entry (§24.2, §24.12).**
     A `choices=` entry is always a record: Python `Choice(<value>, help=...)`, Go
     `Ch(<value>, "<help>")`, TypeScript `{ value, help? }`. Help on an entry is **optional** --
     which is what keeps item 172's one-line rendering reachable -- and non-empty when supplied.
     The bare-value entry is deleted, because an entry with help and an entry without would be two
     spellings of one fact; the cost is that every choices flag in the fleet is a mechanical
     rewrite, which the campaign's migration already reaches. Go spells "no help" as `""` for lack
     of optional parameters, which cannot be mistaken for anything else since an empty help string
     is refused everywhere it is mandatory.

165. **[%%] Go's `FlagOption` becomes an interface (§24.12).** `type FlagOption interface{
     applyFlag(*Flag) }` with a `flagOptFunc` adapter, because a func type cannot also carry a
     choice's name, help, scope and **identity** -- and identity is what removes stringly-typed
     switches from handler code. Every constructor signature is unchanged; the only caller shape
     that breaks is a hand-written `FlagOption` func literal, which can reach only exported `Flag`
     fields, cannot declare presence, and therefore already fails registration today. A delete, not
     a shim.

166. **[%%] A selector declares `required` or a `default`; `optional` is refused (§24.5,
     §12.13).** An absent selection is a choice nobody named, so the refusal redirects to naming it
     -- ruling B2 made structural, in the one place a consumer would otherwise reintroduce
     at-most-one. Authored: the message, and that it carries §12.12's per-language
     `<optional-spelling>` inside the pinned sentence.

167. **[%%] A defaulted selection is complete, and the mechanism differs by language (§24.5).**
     Python's default **is a choice instance**, so an incomplete defaulted selection is
     unconstructable; Go's and TypeScript's default names a choice, so completeness is a
     registration check refusing a defaulted choice whose scope declares a required sub-flag. One
     semantic, two mechanisms, and therefore a **Python-excluded** template -- §12.12's
     language-specific precedent, applied because Python has no input that could produce it, not
     because a check was skipped. Authored: that electing a choice on the command line never
     borrows the default's values, and that a member-spelled default may only elect a payload-less
     member.

168. **[%%] Sources: token spelling takes all of them, member spelling is command-line only, and
     ambient values for non-elected scopes are conditional bindings (§24.6).** A token-spelled
     selector is an ordinary value flag; a member-spelled one carries §21.3's rule with its reason
     intact. A scoped flag's env or config binding is consulted when its scope is elected and
     otherwise never consulted -- a declaration property evaluated identically every run, which is
     what keeps it inside the no-silent-degradation rule rather than beside it. Authored, and the
     load the rule needs to be honest: **every skipped binding is named under `--verbose`**, one
     debug-level line per binding in declaration order, with the exact text pinned in §12.13; and
     **an election from a non-CLI source names itself in every message it causes**, through three
     origin clauses, because otherwise a refusal blames a command line that does not contain the
     cause.

169. **[%%] Names, reserved keys, positionals and depth (§24.7).** Scoped positionals are banned;
     `choice` and `value` are reserved in the delivery record; nesting depth is unlimited; sibling
     scopes may reuse a flag name only with an identical type and arity (tokenization precedes
     election); simultaneously electable scopes may not reuse a name at all. Authored: the flat map
     encoding `{"choice": ..., <fields>}` that makes the two names reserved (the nested alternative
     costs a level on every machine-side call for a collision two reserved names already close);
     that choice names use the flag-name charset in both spellings; that root-versus-scoped and
     selector-name collisions are refusals; that shorts are claimed across simultaneously live
     scopes; and that **every existing name ban re-runs at every depth** -- written as a
     requirement because a ban enforced only against a flat root list is this construct's most
     likely correctness defect.

170. **[%%] Dependency constraints operate at root scope only (§24.8).** A constraint naming a
     scoped flag is a registration error. The reason is that the scope already **is** the
     constraint -- a co-requirement, an exclusivity and a conditional requirement in one
     declaration -- and expressing one fact in two mechanisms is how the two disagree later.
     In-scope constraints are recorded as the sanctioned extension, to be added as a nested
     declaration when a real site appears, never as a root constraint reaching into a scope by
     name.

171. **[%%] Scoped provided-ness is answered by the delivered record (§24.9).** `ctx.provided` and
     `ctx.source` deliberately do not see scope interiors: a scoped name is not unique
     command-wide, so a scoped flag is simply not in the per-parse store and asking raises the
     existing unknown-name error rather than minting a second vocabulary. Authored: the per-language
     spellings, and **why they diverge** -- the record's fields are user-named, so a `provided`
     method would occupy a name a scope might want; Python and TypeScript therefore spell it as a
     function over the record and only Go as a method, because Go's fields live in a `Fields` map
     where a method name cannot collide with one.

172. **[%%] Help renders the indented choice block iff any choice carries help or a scope
     (§24.10).** Otherwise today's one-line `[choices: ...]` form. A selector is therefore always a
     block (its choices carry mandatory help) and a value flag is a block exactly when its entries
     were given help. Authored: the layout -- two columns of indent per level, one alignment column
     across the whole command's flag block, §23.8's exactly-one-presence-part invariant holding at
     every depth, and a member-spelled selector rendering as a heading carrying
     `(exactly one of the following)` because it has no token of its own to render.

173. **[%%] The MCP projection is flatten plus a description map (§24.11).** One object schema, the
     selector as an `enum` property, every scoped flag a top-level property that is never in
     `required`, and wrong combinations refused at call time with the CLI's own sentence.
     Authored: the description block's format -- one line per scope at every depth, keyed by a
     `<selector>=<choice>` path in the schema's property names, parameters in declaration order with
     their presence in parentheses, `(no parameters)` for an empty scope -- and that a
     member-spelled selector projects **identically** to a token-spelled one, because tokenization
     is a command-line fact and there are no tokens at this boundary. `oneOf` in the tool schema is
     recorded as the future upgrade behind a measurement of client handling; one-tool-per-choice is
     recorded as rejected, with its multiplication and its break of one-command-one-tool identity.

174. **[%%] Python's handler-annotation check is mandatory (§24.12, §12.13).** The parameter bound
     to a selector must annotate exactly the declared union, `**kwargs` handlers are banned on
     selector-carrying commands, and the annotation-resolution rule is pinned: `get_type_hints`
     against module globals plus the decorating frame's locals, with a `TYPE_CHECKING`-only name a
     registration error naming it rather than a `NameError` at import time. Without the check a
     developer can annotate one choice class, and `assert_never` then passes the type checker while
     silently skipping branches -- the check is what makes exhaustiveness **sound** rather than
     hoped for. Its three templates are Python-only and excluded from parity by construction, for
     item 153's reason.

175. **[%%] Multi-elect is deferred and recorded (§24.13).** Not a rejection: §24.7's collision
     rules are written against **simultaneously electable scopes** rather than siblings precisely
     so that adopting any-of narrows an existing rule instead of contradicting one. What it would
     force is recorded -- sibling name reuse becoming illegal, sequence delivery, `optional`'s two
     possible meanings against §23's ban on silent empty collections, no spelling for which
     election a required sub-flag belongs to, and the need to reconcile repetition with the
     existing repeatable/unique vocabulary rather than inventing a second one.

176. **The constraint system is restructured (§24.14, §23.9's box).** Exactly-one leaves the
     constraint system entirely: every exactly-one shape is a selector, and no `ExactlyOne`
     constructor or cardinality parameter may reintroduce one. The still-unbuilt constraint round
     keeps pure co-occurrence -- at-least-one and all-or-none -- with by-name members, generalized
     operands, the declared election vocabulary and first-class rendering. Two of its planned items
     are **superseded rather than deferred**: per-choice help is item 164's record, and the
     dissolution of bool-only groups is this construct. There is still no at-most-one at any
     cardinality. Untagged, per this section's preamble: it is the consequence of items 160 and
     161, not a separate decision.

177. **The message family, and what is deliberately reused (§12.13).** Authored: the **scope-path
     rendering format** (one segment per election, outermost first, space-joined; token segments
     `--<sel> <choice>`, member segments `--<choice>`; single-quoted wherever a template names one),
     the out-of-scope frame and its three "why" clauses, the three election-origin clauses, the
     scope suffix, the double-election message, and the whole registration-guard table. Equally
     deliberate is what gains **no** new template: the invalid-choice sentence, the required-flag
     sentence and §21.4's three mutex sentences are **reused unchanged**, so a migrated declaration
     does not change the bytes a user reads for a condition that did not change. The new
     `Choice "<c>" of "<sel>": ` prefix is the round's only new prefix family, and it names both
     because a choice name is unique only within its selector.

178. **§21 is superseded item by item rather than deleted (§21's box, §23.5, §12.12).**
     `MutexGroup` is removed from all three implementations with no shim and no deprecation period,
     but §21 stays: most of it was never about the construct. §21.1's vocabulary and §21.2's
     per-type election rules survive verbatim as member spelling; §21.3's CLI-only rule survives for
     member spelling and explicitly does **not** extend to a token-spelled selector; item 119's
     `config_conflict_mode` carve-out survives untouched. Three things retire and are struck in
     place: §21.2's handler advice (a handler no longer sees per-member values, so there is nothing
     to test for absence), §21.3's "an unelected member delivers its declared default" (an unelected
     scope is not delivered at all), and §23.5's mutex row. One rule **inverts**: §12.12's
     `errFlagMutexMemberRequired` said a member may not declare requiredness, and a member flag now
     must -- so the old template is deleted under item 149's rule rather than reworded, since the
     two state opposite rules about the same declaration.

179. **The round's boundary is declared, not left to inference (§24.11, §24.15).** The dumped
     schema's selector encoding is **not** authored here -- a variant is inexpressible in the closed
     subset, so the encoding belongs to the schema-v2 amendment -- but its **requirements** are
     (nested choices and scopes, per-choice help, each scoped entry's presence and default, the
     spelling), and a dump that flattens a selector away is named as an illegal intermediate state
     rather than tolerated, because it would restore exactly the erasure §13's presence box ended.
     The two amendments therefore ship into one release. Also untouched and stated: the surviving
     constraint families, the update-command construct, nested config-file layout for scoped flags,
     `Requires` / `Implies` semantics at root scope, and the consumer migration itself.

### 18.16 Amendments made at the schema-v2 round (2026-08-14)

This round is the third phase of the declaration-regime campaign. It adds §25 and §12.14, and
supersedes §13's flag-entry, arg-entry and defaults-block text through two boxes there. Numbering
continues §18.15's, for the reason §18.14 gave: the same campaign's ledger.

**Origin tags**, per §18.14's preamble. `[%%]` marks a ruling adopted from a recommendation --
trust rather than deliberate intent, and **freely reversible**. The campaign's decision record
states that S17's rulings are `[%%]` throughout, so every item tracing to S17 carries it. Untagged
items are authored spellings in the §18.3 class: the mechanical remainder the ruling left open,
decided here so implementors have nothing left to decide.

**Written before any implementation**, the discipline this campaign adopted explicitly. Anything the
implementations surface later continues this numbering as a sweep, exactly as items 151-159 did.

**The evidence behind the round** is the working tree, read at authoring time rather than taken from
the todos' line anchors (which had drifted). Six findings shaped items below and none of them came
from a design discussion: Go's schema writer marshals through `encoding/json` and therefore never
touches Go's own canonical float formatter; the `repeatable` normalization in
`check_schema_parity.py` is the last compensation layer standing between three implementations and
byte equality; the same `enum`-at-the-root bug exists in all three MCP projections, with two extra
arity defects in Python's alone; the dumped `checks` block is a function of process history rather
than of the declaration in two of three implementations; rlsbl re-encodes every dumped schema at
release time with Python's encoder; and selfdoc's arg table still reads a key the **presence round
deleted**, so it labels every positional arg required today.

180. **[%%] `schema_version` becomes 2, once, for the whole migration (§25.1, §13's first box).**
     Emitted at both existing sites in all three implementations -- the top-level key and the copy
     inside `defaults`. Three strands collapse into it: S17's value-shape work, the canonical-
     serialization and behavioral-completeness items of strictcli's own schema-v2 todo, and the
     byte-level encoding canon of the canonical-encoding todo. Authored with it: the correction that
     **the globals redesign is not part of v2**. That todo named it as the third strand; it has since
     shipped (its todo is in `todo/.done/`, and `effect`, `consequential`, the dry-run pair,
     `grants`, `forwarding` and `proc_observe_allowlist` are emitted by all three serializers at
     version 1), so v2 collapses two items rather than three and carries no globals work.

181. **[%%] Flag and arg value shapes become real JSON Schema fragments under `value_schema`
     (§25.2).** A closed subset of four keywords -- `type`, `items`, `additionalProperties`, `enum`
     -- with **JSON Schema's** type names. The v1 `type` key dies with its three spellings, one of
     which (Python's) was already JSON-Schema-shaped and wrong in exactly one way: `"str"` is not a
     JSON Schema type name. Authored: the fragment table, one row per carrier; the intra-fragment
     key order; that a dict's keys need no expression because they are structurally `string` in all
     three implementations (Python refuses a non-`str` key type, Go's dict carriers do not
     parameterize the key, TypeScript has only the three `dict[str,...]` carriers); and that an
     **optional flag emits the plain type with no `null`** -- presence is the sole authority on
     absence, and a nullable fragment would restore the two-keys-one-fact shape §13's presence box
     ended.

182. **[%%] Arity is a property of the value, and `repeatable` dies (§25.3, §13's first box).** A
     repeatable scalar flag and a `list[T]` flag publish the identical array fragment, and the
     `repeatable` key -- which restated a fact the shape already carried -- is deleted. With it goes
     `check_schema_parity.py`'s `_canonicalize_repeatable` and its call in `_normalize_schema`: the
     last normalization rule, and therefore the last place a real divergence could be absorbed as
     serialization noise. Authored: that **`variadic` survives** on the arg entry, because it names a
     token-consumption rule (this arg takes every remaining positional, and only the last arg may)
     rather than a value shape, and a consumer needs it to render `<files>...`.

183. **[%%] Compound args are unified rather than banned (§25.4).** One published fragment for every
     arg that collects a typed list, whichever spelling declared it. Per language, verified on disk
     rather than taken from the ruling's summary: **TypeScript** gains `list[T]` variadic args (its
     registration refusal of a list carrier is deleted; the element-carrier spelling stays legal and
     stays idiomatic); **Go's `ArgType` validation already exists** in `NewArg` -- list types require
     variadic, item types are scalar-only, dict is refused, the scalar set is closed -- so the
     ruling's Go clause names work already done; **Python** needs no registration change. Authored
     as the consequence nobody had noticed: Go must **delete
     `errArgChoicesIncompatibleListType`**, because once the two spellings are one declaration, a
     choices ban that fires on one and not the other is two rules for one fact (item 149's rule).

184. **[%%] An int choice beyond ±2^53 is a registration error (§12.14).** The fragment publishes
     choices as a JSON `enum`, and a reader that parses JSON numbers as doubles reads a different
     integer back. Authored: both surfaces (`Flag "<name>":` and `Arg "<name>":` prefixes), the
     reuse of §19.5's existing magnitude clause **byte-for-byte** rather than a second wording for
     one fact, the `<v>` rendering (decimal digits, leading `-`, no separators -- where Python's
     `repr`, Go's `%d` and TypeScript's `String(bigint)` coincide, so the template needs no
     per-language spelling row), and that **float choices are exempt** because the canonical float
     form is by construction the shortest string that round-trips to the identical double, so
     nothing is lost there.

185. **[%%] Choices split across two keys, and the sibling key keeps the name `choices` (§25.5).**
     The `enum` lives in the fragment -- **inside `items`** for an array-shaped carrier, at the root
     for a scalar one -- and item 164's value-plus-help records live beside it. Authored: the sibling
     key's name (`choices`, the name the fact has always had, rather than a new one) and its shape
     (`{"value": ..., "help": ...}` in declaration order, `value` emitted with its own type and never
     stringified), plus the emission rule that makes the two spellings of "no help" produce identical
     bytes: **`help` is omitted when empty**, since Go spells no-help as `""` for lack of optional
     parameters and an empty string must not out-diff an absent one.

186. **A selector carries a native encoding and no fragment (§25.6, §24.11's requirement).**
     Authored in full, because §24.11 pinned the requirements and left the encoding blank: the
     `choices` array of choice objects (`name`, `help`, `flags`), each scoped entry a **full flag
     entry** with its own fragment and presence -- which is what makes recursion free and what makes
     the encoding satisfy the requirement rather than gesture at it; `elect_by` carrying §24.12's own
     two-value vocabulary (`"selector-token"` / `"member-flags"`) rather than a second pair of names
     for one fact; the **presence of `elect_by` as the discriminator** between a selector's choice
     objects and a value flag's choice records; a member payload as the first `flags` entry under the
     reserved name `value` with `presence: "required"`, mirroring item 169's flat delivery map; and a
     selector's `default` published in that same flat map form (`{"choice": ..., <fields>}`, fields
     with no value omitted, which is unambiguous because `null` is not a declarable default), the one
     encoding that spans item 167's two mechanisms without either language borrowing the other's.
     Recorded as considered and rejected: a `selector` wrapper key, which would rename a fact that
     already has a name and provide a discriminator `elect_by` already provides.

187. **[%%] Config-field entries move to fragments; check entries have nothing to move (§25.7).**
     A config field's `type` (three spellings again) becomes `value_schema`, always a scalar row --
     verified scalar-only in all three implementations. Authored: that the config field's `required`
     key **stays**, because it is not §23's presence declaration under another name (a config field
     has no CLI surface and no three-way declaration; `required` there means the file must contain
     it), and that a **check entry carries no value shape at all**, so the ruling's clause about
     check entries resolves to a verified nothing. What v2 does reach in the `checks` block is a real
     defect found in the tree: TypeScript filters provider-sourced names and Python and Go do not, so
     in two of three implementations the block is a function of process history rather than of the
     declaration. The exclusion becomes structural in all three.

188. **[%%] The byte canon (§25.8).** One dumper-independent encoding, the float canon's precedent
     extended from one value type to the whole document. Authored: escape exactly what JSON mandates
     and nothing else (§19.5's own sentence, applied document-wide) -- no `\uXXXX` for non-ASCII
     (Python must pass `ensure_ascii=False`), no HTML escaping (Go must turn `encoding/json`'s off),
     no escaped `/`, and a lone surrogate escaped as `\uDXXX` as the single non-mandated escape,
     because the alternative is invalid UTF-8; two-space indent, `": "`, one member per line, empty
     containers inline, exactly one trailing newline; integers as bare tokens. And the finding that
     grounds the ruling's Go clause: **Go's writer bypasses Go's own canonical float formatter**,
     marshalling the committed document through `encoding/json` while `formatFloatCanonical` sits
     unused beside it.

189. **The canonical key order, per entity (§25.9).** Authored in full: the top-level order, the
     flag, arg, command, group, choice, config-field, check, grant, infra and constraint orders, and
     the **two rules for keyed objects** -- `commands` / `groups` / `config_fields` in declaration
     order, which all three retain, and `checks` / `deprecated` / `tag_contracts` sorted by key,
     because Go retains no declaration order for two of them and a canon no implementation can
     produce is not a canon. Recorded with it: every key in the sorted positions is ASCII by
     registration rule, so byte, code-point and UTF-16 order coincide and no collation needs
     specifying. Derived from Python's insertion order, the format's dominant serializer (TypeScript
     documents that it follows Python; Go pins content, not order), with two authored deviations
     named as such -- the value key takes a uniform position across flag and arg entries, and the
     env-related keys are grouped.

190. **The `defaults` block, rewritten (§25.10, §13's second box).** Deleted: `flag.hidden`, the
     phantom the todo named and the tree confirms (no implementation has a flag-level `hidden`);
     `flag.default` and `arg.default`, leftovers the presence round did not sweep, which now state
     something false because `default`'s emission is governed by `presence` rather than by a
     baseline; `flag.repeatable` and `arg.type`, whose keys are gone. Added: baselines for the
     entities the block never covered (`config_field`, `check`, `infra`), the app-level config keys,
     the command-level effects keys, and `flag_sets`. Authored: that keys with **no** baseline stay
     absent from the block on purpose, and that the "constraint subtypes" gap the todo lists is
     closed by §25.7's catalogue rather than by the block, because a subtype catalogue is not an
     omission baseline and the block is defined as the omission map.

191. **[%%] Behavioral completeness: the dump stops being blind (§25.11).** `config_format`,
     `config_path` and `config_conflict_mode` on the app; `prefixed` on the flag; `flag_sets` on the
     command -- each omitted at its baseline, so a departure from framework behavior is exactly what
     makes a key appear. Until v2 an app could relocate every user's config file, or switch its
     format, with a byte-identical schema. Authored: that **`config_path` publishes the declaration
     and never the resolution** (a declared literal as declared, exactly as an infra root's `default`
     already is; a `RelativeToRoot` in §13's machine-stable marker shape), which costs Python a
     change because it resolves the marker eagerly at construction and overwrites the declaration;
     `flag_sets`' shape (`{"name", "flags"}` in declaration order, members keeping their ordinary
     entries, so a grouping is added without duplicating a declaration); and that publishing the
     app-level conflict mode is what finally makes a per-flag `conflict_mode: null` resolvable.

192. **[%%] Fragment validity is one Python-side conformance check (§25.12).** `schema-fragments`,
     in `conformance/check_schema_fragments.py`, reading all three targets' dumps and validating
     every fragment -- at every depth, including inside a selector's scopes -- with the framework's
     own registration-time payload-schema validator, plus its own narrower four-keyword assertion.
     One check over three dumps, never three implementations asserting about themselves. Recorded as
     a dependency between two items: **item 184 is what makes this validation sound**,
     because the payload validator scans `enum` members with the magnitude guard, so without the
     registration refusal the framework would emit a document its own validator rejects. Authored:
     the check's name, file, registration, tags and the assertion that an entry which must carry a
     fragment does -- an agreed absence must never read as agreement, which is the presence round's
     lesson applied one key over.

193. **[%%] The MCP projections' `enum` root-placement bug is fixed in all three (§25.13).** For an
     array-shaped parameter, `enum` belongs inside `items`; all three place it at the property root
     today, which says the array itself must equal one of the choices. Recorded with it, from the
     tree rather than the ruling: **two arity defects in Python's projection alone** -- a repeatable
     scalar flag and a variadic scalar arg both project as scalars, where Go reads `f.Repeatable` /
     `a.IsVariadic` and TypeScript reads `a.opts.variadic` and both project arrays. After this round
     every projection derives its parameter shape from the same arity rule the fragment states, so a
     tool schema and a dumped schema cannot disagree.

194. **The `mutex` constraint subtype is deleted (§25.7, §13's first box).** It goes with
     `MutexGroup` (item 178), leaving `co_required`, `requires` and `implies` as the closed
     catalogue, in the case schema as well as the dump. Untagged: it is the consequence of item 178,
     not a separate decision.

195. **[%%] Consumer ordering is a contract note, not an implementation detail (§25.14).** rlsbl's
     release-time re-serializer is fixed and released **before** any fleet re-dump: it reads the
     freshly dumped file with `json.load` and rewrites it whole with Python's encoder to patch one
     key, so a Go- or TypeScript-written schema is re-escaped by a Python encoder at every release
     and the byte canon survives only until publication. selfdoc's reader updates in the consumer
     window between the strictcli release and the fleet re-dump -- two named sites, one of which is
     **already broken today** because it reads the `required` key the presence round deleted and
     therefore labels every positional arg required. The single-release pin with §24 is
     cross-referenced from §24.11 and item 179 rather than restated.

196. **The boundary is declared, not left to inference (§25.15).** No fifth keyword and no `oneOf`
     in the fragment subset -- a selector's variant is encoded natively instead, and the tool
     schema's `oneOf` stays §24.11's recorded future upgrade. No v1 compatibility path of any kind:
     the version key tells a reader which format it holds, and pre-stable projects carry no
     compatibility surfaces. No new declaration surface beyond the one widening the unification
     ruling requires (TypeScript's list-carrier variadic arg). Nothing about `presence` or `default`,
     which the presence round settled and this round republishes unchanged.

### 18.17 Corrections made at the read-back audit of the two-amendment round (2026-08-14)

An independent read-back audit of the scoped-selector round (§18.15) and the schema-v2 round
(§18.16) checked the two sections against each other, against the campaign's rulings S1-S17, and
against the sites the two rounds' own changes falsified. **Nothing below is a new ruling or a
changed guarantee**, which is why this section follows §18.13's shape rather than opening a round of
its own: each item either propagates a decision already taken into a site that still contradicted
it, or corrects a count, a list or a claim. Numbering continues §18.16's, for the reason §18.14
gave. The campaign rulings were verified transcribed without drift, the ledger runs 160-196
unbroken, and the reused code-level strings were checked against the three implementations
(`pdetailMagnitude` / `_PDETAIL_MAGNITUDE` byte-for-byte, §21.4's four mutex functions including the
` and ` join, `errFlagInvalidChoice` and the prefixed required-flag text).

197. **The header gains the schema-v2 round's paragraph.** Every round that adds a normative section
     had written one; the fifteenth did not, and the header therefore described a document whose
     last section it never mentioned. The paragraph added is a summary of §18.16 and §25 and decides
     nothing. The round-versus-paragraph note below it is unaffected: it enumerates the *early*
     rounds that wrote no paragraph, and both remain paragraph-less.

198. **Three counts and lists in §12 are corrected.** §12's category table named §12.12 and §12.13
     as the sections declaring their own category and omitted §12.14, which does the same
     (registration-time); §12.13's preamble said it adds two spelling rows while its table adds
     three; and §12.13's name-collision table is introduced as "Four" while listing five templates.
     All three are plain corrections with no text of any template touched.

199. **§13's MCP requiredness rule is narrowed to root scope (§24.11).** The presence round pinned
     "a parameter appears in a tool schema's `required` array **iff** its declared presence is
     `required`". §24.11 then made a scoped flag's requiredness conditional and excluded it from
     `required` entirely -- and said so in §24, while §13, which is where the MCP requiredness rule
     is pinned, still read as an unqualified `iff`. The exception is now carried in §13's presence
     box. A selector's own property follows the original rule unchanged.

200. **§13's case-schema clause confused a dumped key with a declaration key.** The schema-v2 box
     told `conformance/schema.json` to drop `type` from `$defs/flag` and `$defs/arg` and
     `repeatable` from `$defs/flag` -- but those are the input side, how a *case declares* a carrier
     and its arity, not how a dump publishes a value's shape. §25.3 keeps both declaration spellings
     and unifies only what they publish, §25.13's arity fixes need cases that declare exactly those
     two shapes, and §25.15 adds no declaration surface. The clauses are struck and the reason
     recorded in place; `$defs/mutex_group`'s deletion, the one case-schema change v2 really forces,
     stands. Named with it, and **not** authored here: neither round pinned a case-level spelling
     for a selector, a choice's scope, or §24.2's record-shaped `choices` entries, and §12.13's
     parse-time templates each require a covering case that cannot be written without one.

201. **The presence round's remaining mutex text is superseded (§23.2, §23.4, §23.5).** §18.15's
     supersession reached §23.1, §23.5's mutex row and §23.9's bullet, and left three sites
     standing: §23.2's closing sentence ("after this round the member declares
     `presence: "optional"`"), §23.4's last row and the paragraph under it (whose "the group
     enforces cardinality on top of presence" names a construct that no longer exists, and whose
     replacement is now the opposite declaration), and §23.5's second whole-table note (whose "one
     exception is the mutex row" names a row that same round superseded). All three are amended in
     place with the round's own rulings; none reverses anything.

202. **§24.3's sibling-reuse clause names arity, matching §24.7 and item 169.** The rule is
     "identical type **and arity**" in §24.7 and in the ledger, and §24.3 stated it as "identical
     type". The prose is aligned. Recorded as **open rather than authored**: §12.13's
     `errSiblingScopeTypeMismatch` likewise names only types (`... declared by choices "<a>" and
     "<b>" with different types`), so an arity-only violation -- one scope declaring `--x`
     repeatable and its sibling declaring it scalar -- has a rule and no message. Widening that
     template's sentence or minting a sibling for it is a spelling decision this audit does not
     take.

203. **§25.9's array-order rule carves out the member payload's pinned position.** §25.6 places a
     member-spelled choice's `value` entry **first** in that choice's `flags` array; §25.9 said
     array order is always declaration order, and the payload is declared through a different
     constructor with no position of its own. The specific rule wins and §25.9 now says so.

204. **§25.10's always-emitted list stops claiming a fragment on every entry, and two missing
     baselines are named.** The list included `value_schema` unqualified, which §25.2's own table
     and §25.6 contradict: a selector carries none, and the absence is the declaration. Recorded as
     **open rather than authored**: a selector choice object's `flags` (omitted when the scope is
     empty) and a value-flag choice record's `help` (omitted when absent) are omit-at-baseline keys
     on entities the `defaults` block has no entry for, so the block is not yet the complete
     omission map it is defined to be. Naming those entities is a spelling decision, and this audit
     leaves it to the round that takes it.

205. **Two ledger-level lists are completed.** §18's own preamble still scoped its exhaustiveness
     claim to "§§19-20", four sections after that stopped being true; it now reads §§19-25. And
     §18.15's preamble listed the sites that round amended in place without naming §7.1, §19.1 or
     §23.1, all three of which carry its item-169 and item-178 markers.

206. **Three spellings the audit found unpinned and deliberately did not author.** Recorded so they
     are a known remainder rather than a discovery at implementation time: §24.4 says declaring a
     payload on a **token**-spelled choice is a registration error and §12.13 carries no template
     for it; §12.13 pins `<member-selector-spelling>` and no template in the section uses it; and
     the origin clauses appended to a scope-suffix message are shown only through the example
     `flag '--phone-number' is required under '--via sms' (elected from env var 'NOTIFY_VIA')`,
     whose `(elected` … `)` wrapper composes exactly from the pinned clause but has no template name
     of its own.

---

## 19. Machine mode and the envelope

Added 2026-08-13 at the machine-interface round (§18.9). This section is numbered after §18
because sections in this document are never renumbered; it is normative exactly as §§1-17 are.

### 19.1 The mode, its flag, and the one document

**Machine mode is entered by the framework-owned `--json` flag.** The name is reserved
unconditionally at every level (§7.1's amendment box): a consumer declaring `--json` on a command,
a flag set, ~~a mutex group~~ *(amended 2026-08-14, scoped-selector round, §18.15 item 169)* **a
choice's scope at any depth** or as an app global is a registration-time error, exactly as it is for
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
round. There is no third mode and no per-command variation: a run is either in machine mode or it is not,
and the flag is the only thing that decides.

The framework governs what the framework emits. A handler that writes to the process's stdout
directly bypasses this section exactly as it bypasses §7.4's suppression rules today -- the same
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
only: a `ctx.debug` line hidden from a default-mode terminal still appears in `diagnostics` with
`"level": "debug"`, because the envelope's content is a function of what the run produced, never of
how a terminal was configured.

**Serialization** follows §19.5's escaping regime: plain UTF-8, escaping only what JSON mandates.

> **Amendment (2026-08-13, machine-interface remediation round): `exit_code` on the unwind path is
> the language's own status, and is the envelope's one intrinsically language-specific field.**
> This decides nothing new; it writes down what `exit_code` ("the process's exit status") already
> means when composed with §3.5, because an implementation had read it the other way and shipped a
> number that contradicted the process it described.
>
> §3.5 is explicit that an unexpected unwind is **not** handled: the exception continues to
> propagate untouched and "the process's exit status and its own error report are whatever the
> language would have produced anyway". So on that path the framework does not choose the status --
> the language does. An unrecovered Go panic exits **2**; an uncaught Python exception and an
> uncaught Node throw both exit **1**. The envelope reports the number its own process will leave
> with, which means Go's aborted-dispatch envelope reads `"exit_code": 2` where its siblings read
> `"exit_code": 1`.
>
> **The rejected alternative, recorded so it is not re-proposed:** having Go's `Run()` convert the
> abort into a deliberate `os.Exit(1)` after the envelope is written. It would make the three
> documents identical, and §3.5 forbids it twice over -- it swallows the panic and it replaces the
> crash report the same sentence promises. Uniformity bought by suppressing a language's own crash
> output is not uniformity worth having.
>
> **Consequence for conformance.** An aborting case is split by target rather than asserting a
> status no implementation produces, and a harness must not normalize the status away: the Go
> harness reproduces `2` and normalizes only the crash *report*, so the aborting cases' stderr stays
> comparable while their exit status stays honest.

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
  observes of §6.2. ~~This reading is forced by the rest of the regime rather than chosen:~~
  *(amended 2026-08-13, machine-interface round -- sweep)* **This is the reading this document
  adopts**, authored at the round and disclosed as authored (item 112), and reversible by amending
  this bullet: in dry mode a *recorded* spawn starts nothing, so it writes no entry (where nothing
  runs, nothing is traced), while an observe genuinely executes even in dry mode and therefore does
  write one, carrying `dry_run: true`. That is what the entry's reserved-flag state is for, and no
  reading that excludes observes can ever make the flag true -- **that** half is forced.
- **The write is framework bookkeeping, not an effect.** It is never minted through the effects
  handle, never appears in the structured effect log (§14.2), and is never rendered in the would-do
  log. It therefore adds **no exception** to §3.1's "nothing runs" rule and is not a second
  `CACHE_WRITE`-style carve-out: it accompanies real child-process starts and nothing else. §9.2's
  sweep box records the same fact from the other side -- this is a third class of framework write,
  outside both the effects handle and the closed `CACHE_WRITE` list, and it fires in `read_only`
  commands through the observes above.

> **Amendment (2026-08-13, machine-interface round -- sweep): why the adopted seam reading is
> adopted, and what the alternative was.** The bullet above originally called the reading forced.
> It is not, and saying so overstated the case: the alternative -- writing an entry for a
> *recorded* dry-mode spawn as well -- is not self-contradictory. The spec page defines an entry as
> describing the **spawning invocation**, never the child, so an entry written during a preview
> would be a truthful record of an invocation that previewed a spawn rather than a claim that a
> process started.
>
> The reading is adopted anyway, on three grounds, so that a later round weighs them rather than
> re-deriving them:
>
> - **A parent identifier no child ever received links to nothing.** The entry's whole purpose is
>   to be the target of some child's `parent_id`. In dry mode no child is launched, so the entry
>   would be minted, written and then never referenced -- indistinguishable, to every reader, from
>   an entry whose child crashed before writing its own.
> - **It keeps the store's write set equal to the set of real process starts**, which is the
>   sentence a consumer can reason about without knowing anything about dry mode. The alternative
>   makes "one entry per spawn" mean "one entry per spawn or per previewed spawn", and every
>   consumer then needs the `dry_run` field to interpret the *existence* of an entry rather than
>   just its content.
> - **It is what keeps the write outside §3.1.** A write that happens where the regime promises
>   nothing runs would need its own carve-out from the "nothing runs" rule, alongside the
>   framework-blessed `CACHE_WRITE`s -- a second exception bought for entries nothing links to.
>
> What survives unconditionally, under any reading: an observe genuinely executes in dry mode
> (§3.1), so if observes are in the seam at all, `dry_run: true` is reachable, and if they are not,
> the entry's `dry_run` field is dead weight that can never be true.

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

---

## 21. Mutex election

Added 2026-08-13 at the mutex-election round (§18.10). Sections in this document are never
renumbered, so §21 sits physically after §20. It is normative exactly as §§1-17 are.

A `MutexGroup` declares that **exactly one** of its members is chosen in each invocation. This
section defines what "chosen" means. Nothing here is conditional on the effects regime; it is
pinned in this document because this document is where cross-language message spellings live.

> **Amendment (2026-08-14, scoped-selector round, §18.15 item 178): `MutexGroup` is subsumed and
> deleted; this section's semantics survive it as member spelling.** §24's selector construct
> expresses "exactly one of these, and each may carry a payload of its own" with the type
> information kept rather than thrown away, and its **member spelling** (§24.4) is this section:
> each choice is spelled as its own flag, no selector token is ever typed, and the three
> prototypes reproduced these error sentences byte-for-byte before the ruling was taken. So
> `MutexGroup` is **removed from all three implementations** -- there is no shim, no alias and no
> deprecation period (0.x policy) -- and every fleet group migrates to a member-spelled selector in
> the same campaign pass.
>
> This section is **not** deleted with the construct, because most of it was never about the
> construct: it is what a typed token does to an election, and elections outlive `MutexGroup`. Item
> by item:
>
> | Item | Verdict |
> |---|---|
> | §21.1 vocabulary (`elects` / `declines` / `unelected`) | **Survives verbatim**, re-homed to member spelling. `unelected` additionally means the member's **scope** is not live, which is the whole of what the new construct adds to the old word |
> | §21.2 what elects, by type | **Survives verbatim**: a bool member elects only when it resolves to **true**, `--no-<name>` declines, and every other type elects on presence with any value including `""`. This is a member-spelling rule; a **token**-spelled selector elects by naming a choice and has no per-type question to answer |
> | §21.2's handler consequence (`test for absence, never truthiness`) | **Retires.** The handler no longer receives members as separate values -- it receives one tagged record (§24.1) -- so there is no absent value left to test. The rule it replaced (a member elected with `""` is present) survives as election semantics; the advice about handler code has nothing left to advise |
> | §21.3 CLI-only election, and the env/config suppression | **Survives for member spelling** and is now stated as a rule with a reason rather than as the framework's one special case: a member-spelled election is a token the operator types (§24.6). It does **not** extend to a token-spelled selector, which is an ordinary value flag and elects from any source (§24.6, ruling S5) |
> | §21.3's `config_conflict_mode="error"` carve-out (item 119) | **Survives untouched**, on member flags, for its original reason: it is a value-hygiene check about the operator's own configuration and it runs before suppression |
> | §21.3's "an unelected member delivers its declared default" | **Retires** -- struck and restated below. An unelected member's scope is not delivered at all, so there is no per-member value for a default to fill |
> | §21.4's three errors | **Survive verbatim** as member spelling's errors, plus §12.13's scope suffix when the selector is itself scoped |
> | The construct `MutexGroup` itself, its owns-the-`Flag`-objects reference model, and §23.5's mutex row | **Deleted** (§24.4, §24.14) |
>
> One rule **inverts**, and it is called out rather than left inside a table cell: §12.12's
> `errFlagMutexMemberRequired` said a member may not declare requiredness. A member flag now
> **must** declare it (`Choice "<m>" of "<sel>": a member flag must declare <required-spelling>`,
> §12.13), read as *required once this member is elected*. The old template is deleted; see the box
> under §12.12's mutex entry.

### 21.1 Vocabulary

| Term | Meaning |
|------|---------|
| **elects** | A typed token selects this member as the group's choice. |
| **declines** | A typed token names this member and states it is NOT the choice: `--no-<name>` on a bool member. |
| **unelected** | Neither elected nor declined -- the member was not named in the invocation. |

### 21.2 What elects, by type

- A **bool** member is elected by `--<name>` on the command line, and only when the value it
  resolves to is **true**. `--no-<name>` **declines**: it elects nothing.
- Every **other** type is elected by presence on the command line, whatever the value. `--profile ""`
  elects. Whether the empty string is a legal value for that flag is the flag's own value
  validation (`choices`, `validate`) and is checked after the group is satisfied, never instead
  of it.

~~The consequence for handlers is one line, and it is stated in the flag-system documentation: a
handler on a mutex member tests for **absence** (`is None` / `== nil` / `=== undefined`), never
for truthiness. A member elected with an empty string is present; a bool member left unelected
is not.~~ *(struck 2026-08-14, scoped-selector round, §18.15 item 178)* The handler consequence is
gone with the construct: a member-spelled selector delivers **one tagged record** (§24.1), so a
handler never sees a per-member value and has nothing to test for absence. The election reading the
struck paragraph rested on is unchanged and is stated where it belongs, one paragraph up -- a member
elected with an empty string is elected, and a bool member left unelected is not.

### 21.3 CLI-only

**Only command-line tokens elect.** A value that reaches a mutex member from an environment
variable or a config file elects nothing, and it does not satisfy the group.

Env and config are, further, **not consulted at all** for a mutex member's value: ~~an unelected
member delivers its declared default, or~~ ~~nothing (`None` / `nil` / `undefined`) when it declares
none~~ *(amended 2026-08-14, presence round, §18.14 item 148)* ~~nothing (`None` / `nil` /
`undefined`) when it declares `optional`,~~ *(struck 2026-08-14, scoped-selector round, §18.15 item
178: an unelected member has no delivered value at all -- its scope is not live, and §24.1's tagged
record carries only the elected choice's fields. What survives is the suppression itself: env and
config are not consulted for a member flag)* regardless of what the environment or the config file
holds for it. The suppression is
applied before dependency validation, so `Requires`, `CoRequired` and `Implies` observe the same
state the group does, and the resulting source label is `default`, never `env` or `config`.

This is a **deliberate special case**, and the only one in the framework: for every flag that is
not a mutex member, the ordinary precedence (CLI > env > config > default) is untouched. The
justification is that a mutex group exists to make the operator choose *in the invocation*, and
an inherited environment is not that choice. The cost is stated rather than hidden: an operator
who wants a default choice for such a group cannot express it through env or config, and must
either type the flag or the application must stop using a mutex group for that decision.

**One carve-out: `config_conflict_mode="error"` still fires on an elected member.** "Not
consulted at all" describes value *delivery* and election. It does not describe the
both-sources conflict check, which is a value-hygiene rule about the operator's own
configuration and runs **before** mutex suppression. So an app configured with
`config_conflict_mode="error"` that has a config value for a member the command line then
elects with a diverging value reports the conflict (`... is set in both ...`) and exits, rather
than suppressing the config value silently. The conflict check never elects anything and never
delivers a value: on an *unelected* member no conflict is possible, because the command line
supplied nothing to diverge from. This is pre-existing behaviour, pinned by
`test_conflict_mode_fires_before_mutex` in the Python suite and by
`TestConfigConflictModeFiresBeforeMutex` in the Go suite, and it is recorded here as a
clarification of §21.3's wording, not as a change to it (§18.10 item 119).

### 21.4 The three errors

Evaluated per group, in this order:

1. **More than one member elected** -- `--a and --b are mutually exclusive`, listing the electing
   members only, in group-declaration order. Declined members never appear here.
2. **Exactly one member elected, and at least one member declined** --
   `--no-b cannot be combined with --a (--no-b declines an option; it does not choose one)`.
   Declined members render as `--no-<name>` in group-declaration order joined by ` and `; the
   parenthetical names the **first** declined member.
3. **No member elected** -- `one of --a, --b is required`, with
   ` (--no-b declines an option; it does not choose one)` appended when at least one member was
   declined, naming the first declined member.

All three are parse errors: stderr, exit code 1, byte-identical in all three implementations.

---

## 22. The protocol server

Added 2026-08-14 at the **protocol round** (§18.11). Sections in this document are never
renumbered, so §22 sits physically after §21. It is normative exactly as §§1-17 are.

The framework exposes every tool-eligible command over the Model Context Protocol under the
reserved `--mcp` flag. Until this round the server pinned the protocol's **first** revision
(`2024-11-05`) -- two revisions before the one that introduced a confirmation mechanism at all --
so the one channel that could have asked a human had no way to ask.

### 22.1 The two eras

| Era | Revision | Selected by | Shape |
|-----|----------|-------------|-------|
| **Modern** | `2026-07-28` | a request carrying `_meta['io.modelcontextprotocol/protocolVersion']` | stateless: every request declares its version and the client's capabilities; every result carries a `resultType`; `server/discover` replaces the handshake |
| **Legacy** | `2025-11-25` | an `initialize` request, scoped to the process | the last handshake-based revision: a session, and server-to-client requests sent as requests (§22.7) |

A request that carries neither the modern metadata nor a preceding `initialize` is **malformed**
and is refused with `-32602`; nothing is inferred from its shape. The legacy latch is the only
piece of connection state the server keeps, and the modern era never consults it -- which is what
the modern revision's own dual-era rule requires of a server serving both.

~~The legacy era is untouched by this round on purpose. It is where §11.6's server-initiated
delivery will live; moving it now would have meant designing that branch here.~~
**Amended 2026-08-14 (confirmation round, §18.12 item 128).** That branch was designed and built,
and the legacy era moved with it: the advertised revision is now `2025-11-25`, the newest
handshake-based one, which is the version the legacy negotiation rule tells a server to answer
with and the first that supports the mechanism this document is about. What the era *is* --
selected by `initialize`, scoped to the process, never consulted by a modern request -- is
unchanged. §22.7 has the delivery.

### 22.2 Per-request metadata

A modern request's `_meta` block is validated before anything else looks at it:

| Key | Required | Rule |
|-----|----------|------|
| `io.modelcontextprotocol/protocolVersion` | yes | a string; selects the era, and a value other than `2026-07-28` is refused with `-32022` |
| `io.modelcontextprotocol/clientCapabilities` | yes | an object; what the server may rely on the client to do |
| `io.modelcontextprotocol/clientInfo` | no | an object when present; the client's self-report |
| `io.modelcontextprotocol/logLevel`, `io.modelcontextprotocol/subscriptionId` | no | recognized and ignored |
| `progressToken`, `traceparent`, `tracestate`, `baggage` | no | recognized and ignored |

Every key is additionally checked against the protocol's key-name grammar: an optional
dot-separated prefix, a slash, and a name that (unless empty) begins and ends alphanumeric.
**A key under a prefix the protocol reserves for itself** -- any prefix whose second label is
`modelcontextprotocol` or `mcp` -- **that this revision does not define is refused, not ignored.**
A vendor-prefixed key (`com.example.mcp/thing`) is carried without complaint. The refusals:

```
missing required request metadata: _meta['io.modelcontextprotocol/protocolVersion']
missing required request metadata: _meta['io.modelcontextprotocol/clientCapabilities']
parameter '_meta' must be an object
_meta['io.modelcontextprotocol/protocolVersion'] must be a string
_meta['io.modelcontextprotocol/clientCapabilities'] must be an object
_meta['io.modelcontextprotocol/clientInfo'] must be an object
invalid _meta key name: '<key>'
unrecognized reserved _meta key: '<key>'
```

All are `-32602`, byte-identical in all three implementations. **Every implementation sorts the
key set before validating**, so a request carrying more than one offending key is refused by
naming the same key everywhere -- the lexically first offender, whichever of the two key rules it
breaks. Go sorts because its map iteration is randomized; Python and TypeScript sort because a
document's own order is a different answer (corrected 2026-08-14, §18.13 item 136). The order is
over UTF-8 bytes, which is Go's `sort.Strings` and Python's code-point sort; TypeScript compares
the encoded bytes rather than its default UTF-16 code units.

### 22.3 Discovery, result types, error codes and the declared feature

**`server/discover`** is mandatory in the modern revision and is what replaces the handshake:

```json
{"resultType":"complete",
 "supportedVersions":["2026-07-28"],
 "capabilities":{"tools":{},"extensions":{"dev.smmh.strictcli/consequential-confirmation":{}}},
 "instructions":"<the app's declared help>",
 "ttlMs":3600000,"cacheScope":"public",
 "_meta":{"io.modelcontextprotocol/serverInfo":{"name":"<app>","version":"<version>"}}}
```

- **`resultType`** is on every modern result: `"complete"` for a finished one, `"input_required"`
  for the interim one of §22.5. Legacy results carry none, exactly as they never did.
- **The server identity** rides every modern result's own `_meta`, which is where the handshake's
  `serverInfo` went.
- **Cacheability.** `tools/list` and `server/discover` carry `ttlMs: 3600000` and
  `cacheScope: "public"`. The tool list is derived from the app's static command registration, so
  it cannot vary per client and cannot change while the process runs.
- **The declared feature** is `dev.smmh.strictcli/consequential-confirmation`, an extension
  identifier under the framework's own vendor prefix. It is a **NAME, not a version number**
  (campaign decision 26, following decision 9's features-not-numbers reasoning): a new name
  appears only if the confirmation dance changes incompatibly. A client learns that this server
  asks before running a consequential tool without inferring it from a revision date.
- **Error codes.** `-32022` (unsupported protocol version) is emitted with
  `data: {"supported": ["2026-07-28"], "requested": "<what was asked for>"}`. `-32020`
  (header mismatch) is HTTP-transport-only and unreachable here. ~~`-32021` (missing required
  client capability) is not emitted at this round -- see §22.6.~~
  **Amended 2026-08-14 (confirmation round, §18.12 item 127): `-32021` is emitted**, and it is the
  whole answer to an unconsented consequential `tools/call` from a client whose declaration does
  not cover a form elicitation:

  ```json
  {"code":-32021,
   "message":"Server requires the elicitation capability for this request",
   "data":{"requiredCapabilities":{"elicitation":{"form":{}}}}}
  ```

  `data.requiredCapabilities` is a client-capabilities object, as the revision specifies, and it
  names **form** mode: a client that declared only URL-mode elicitation cannot render this
  question either, and answering it `{"elicitation":{}}` would send it back with a declaration
  this server would refuse a second time.

### 22.4 The continuation primitive

The modern revision is stateless: a server that needs more input answers with what it needs and
whatever it must remember, and the client echoes that back on a retry which is otherwise a fresh,
independent request. **The state therefore travels through the client, which makes it
attacker-controlled input rather than server memory**, and the protocol requires it be treated
as such.

The blob is `<payload>.<mac>`, both unpadded base64url:

| Field | Meaning |
|-------|---------|
| `v` | the payload format, `1` |
| `jti` | 128 random bits; what makes single use enforceable |
| `prin` | the principal it was issued to (§22.4a) |
| `exp` | mint time + **300 seconds** |
| `req` | a digest of the originating request |

The MAC is **HMAC-SHA256** over the payload bytes under a **key minted for this process and never
emitted**. A blob is therefore unforgeable without reading the process's memory, and worthless to
any other process. There is no fixed key and no injectable clock anywhere in this design: the
campaign's decision 7 rejected determinism injection precisely because a leaked fixed key makes
the blob forgeable by anyone reading the published source.

`req` is `SHA-256("tools/call\n<tool name>\n<canonical arguments>")`, where the canonical form
sorts object keys, emits no insignificant whitespace, and renders floats in the framework's
canonical form (§SCF) -- so the digest depends on what the caller said, never on how their encoder
spelled it.

**Verification is also consumption.** In order: shape, then MAC, then payload version, then
expiry, then principal, then request digest, then the spent-id set; a blob that passes every check
is recorded as spent, so a second presentation is refused even though it is still perfectly
well-formed, unexpired and correctly bound. The refusals, all `-32602` and byte-identical:

```
requestState failed verification
requestState has expired
requestState was issued to a different client
requestState does not match this request
requestState has already been used
```

Spent ids are pruned once they are past their own expiry, so the set cannot grow without bound.

**The spelling is checked before the decode** (corrected 2026-08-14, §18.13 item 135). "Unpadded
base64url" is a set of texts, and the three languages' stock decoders do not agree on which:
Python's ignores stray characters and accepts padding, Node's ignores anything outside the
alphabet, Go's skips newlines, and all three ignore the trailing bits of a final character that
does not fill a byte. Each segment is therefore validated as canonical -- alphabet only, no
padding, a length a byte string can produce, zero trailing bits -- before any decoder sees it, so
the three refuse exactly the same texts, with `requestState failed verification`.

#### 22.4a The principal, stated honestly

On this transport there is no authenticated principal. The binding uses the client's self-reported
`io.modelcontextprotocol/clientInfo` (`"<name>/<version>"`, or `"/"` when the fields are absent
and `""` when the whole block is), and it is therefore a **consistency check, not authentication**:
it stops a blob minted for one declared client being redeemed by another, and nothing more. What
actually contains a stolen blob is the per-process key plus the five-minute expiry plus single
use. This is stated here rather than implied because the protocol's own text says self-reported
identity must not be relied on for security decisions, and this document should not be read as
doing so.

### 22.5 The confirmation round-trip

A modern `tools/call` naming a `consequential` command, carrying no consent, from a client that
declared it can render a form elicitation, is answered with:

```json
{"resultType":"input_required",
 "inputRequests":{"consequential-confirmation":{
   "method":"elicitation/create",
   "params":{"mode":"form",
             "message":"about to run consequential command '<path>'. Proceed?",
             "requestedSchema":{"type":"object",
               "properties":{"proceed":{"type":"boolean","title":"Proceed",
                 "description":"Whether to run the consequential command."}},
               "required":["proceed"]}}}},
 "requestState":"<§22.4's blob>",
 "_meta":{"io.modelcontextprotocol/serverInfo":{...}}}
```

The message is the terminal prompt's words (§12.6) minus its keystroke hint: **one vocabulary for
one question, however it is delivered.**

The retry echoes the state and carries the answer under the same key:

| Answer | Outcome |
|--------|---------|
| `{"action":"accept","content":{"proceed":true}}` | the call proceeds with consent; `ctx.approve_consequential` reports true, exactly as §8.5 promises |
| `{"action":"accept","content":{"proceed":false}}` | aborted -- the action names what the client did with the dialogue, the field is the answer to the question |
| `{"action":"decline"}` / `{"action":"cancel"}` | aborted |
| absent | the state is spent; the server asks again with a **fresh** state, which is what the protocol says to do rather than erroring |
| anything else | `-32602 inputResponses['consequential-confirmation'] is not an elicitation result` |

An abort is ordinary tool-result content: `isError: true` with the text `aborted`, which is
§12.6's word for the same decision at a terminal.

**`inputResponses` without `requestState` is `-32602`**
(`parameter 'inputResponses' requires the requestState it was issued with`): an answer that cannot
be verified is not an answer. A non-string `requestState` and a non-object `inputResponses` are
`-32602` on the same grounds.

Two things do **not** change. A `read_only` or plain `mutating` command is never asked about. A
call that states consent (`approve_consequential: true`) proceeds without the round-trip -- it is
a caller declaring it is proceeding without a human, which is what §8.5 made it.

### 22.6 What the protocol round deliberately left to the next

**Amended 2026-08-14 (confirmation round, §18.12).** The first two deferrals are discharged; the
third stands. Each is marked below rather than deleted, so a reader of the protocol round's text
can see where its remainder went.

- ~~**A client that did not declare elicitation** gets §8.5's refusal, unchanged. The modern
  revision's answer is `-32021` with `data.requiredCapabilities`, and that is the next round's,
  together with the published protocol page that shows the dialogue.~~ **Discharged.** `-32021`
  is emitted with the shape §22.3 now pins, and the dialogue is published at
  `docs/mcp-confirmation.md` -- the third of campaign decision 26's three surfaces, the other two
  being the declared feature name and the conformance cases that assert the declaration matches
  the behaviour. §8.5's refusal is now reachable only from the legacy era, and only from a legacy
  client that cannot be asked (§22.7).
- ~~**The legacy era** keeps the static consent param and no confirmation mechanism at all.~~
  **Discharged: §22.7.**
- **Expiry has no conformance case.** Tampering, forgery, the two bindings and reuse are all
  expressible over the wire; expiry is not, because reaching it would need either a five-minute
  test or an injectable clock, and the clock was rejected (decision 7). It is covered by unit
  tests in all three implementations, which drive the mint directly.

### 22.7 The legacy era's confirmation

Added 2026-08-14 at the **confirmation round** (§18.12). The modern era answers a question it
cannot ask synchronously by *ending the request* and letting the client come back (§22.5). The
legacy revision has no such pattern: a server that needs input **sends a request of its own** on
the same connection and waits for the client's response. The confirmation is therefore delivered
twice over, in the two shapes the two revisions define -- and decided once, by one piece of code.

**The handshake.** `initialize` answers with `protocolVersion: "2025-11-25"`, `capabilities`
carrying `tools` and an `experimental` entry naming the declared feature
(`dev.smmh.strictcli/consequential-confirmation`, the same name `server/discover` advertises), and
`serverInfo`. The client's own `params.capabilities` and `params.clientInfo` are kept for the
lifetime of the process: in this era they are the session, exactly as the per-request `_meta` is
in the modern one. This server speaks one legacy revision, so it always answers with it; a client
that cannot speak it disconnects, which is what the legacy negotiation rule says to do.

**The exchange.** An unconsented `tools/call` on a `consequential` command, from a legacy client
whose handshake declared a form elicitation:

1. The server mints a continuation (§22.4) over the same principal and the same request digest
   the modern era would use.
2. It writes a server-to-client request whose `method` is `elicitation/create` and whose `params`
   are **byte-identical to §22.5's** -- one vocabulary for one question, however it is delivered:

   ```json
   {"jsonrpc":"2.0","id":"<the continuation blob>","method":"elicitation/create",
    "params":{"mode":"form","message":"about to run consequential command '<path>'. Proceed?",
              "requestedSchema":{...}}}
   ```

3. **The continuation blob is the request id.** JSON-RPC obliges the client to echo an id back
   verbatim, which is exactly what the modern era obliges it to do with `requestState`, so the
   correlation needs no second mechanism and no counter. The server then verifies the echoed id
   through the same path -- MAC, expiry, principal, request digest, single use -- and a matching
   id that fails any of those checks confirms nothing.
4. The client's response is read as one `ElicitResult`: `{"action":"accept","content":{"proceed":
   true}}` consents, and **everything else aborts** -- `decline`, `cancel`, an acceptance that
   says no, an unreadable result, a JSON-RPC error response, or the stream ending before an
   answer arrives. The abort is the same tool-result content as everywhere else: `isError: true`
   with the text `aborted`. There is no re-ask in this era: the modern one re-asks because the
   client is free to come back without an answer, while here the server is holding the request
   open and a non-answer is a decision.
   **Every one of those exits consumes the blob** (corrected 2026-08-14, §18.13 item 134). Once
   the elicitation has been written the blob is on the wire, and §22.4's consumption is
   unconditional from that point: the abort spends it just as an acceptance does. An abort that
   left it live would be handing the client a still-valid `requestState` -- same principal, same
   request digest, five minutes of life -- to present on the modern path with an acceptance the
   client wrote itself, for the very call the abort refused.
5. Anything else the client sends while the server is waiting is **held, not dropped**: a
   response whose id is not the awaited one is discarded (this server sent no such request), and
   a request or notification is queued and served after the call it interrupted completes. The
   loop is still one-request-at-a-time; the queue only records that the client spoke early.

**A legacy client that cannot be asked** -- one whose handshake declared no elicitation, or only
URL mode -- reaches §8.5's seam unconsented and gets its refusal (`command '<path>' is
consequential: the call must carry confirmation`) as ordinary tool-result error content. It does
**not** get `-32021`: that code belongs to a revision this client is not speaking, and the
revision it *is* speaking reserves the range it sits in.

**The era boundary is unchanged.** `initialize` latches legacy for the process; a request that
carries the modern `_meta` is served statelessly whatever the latch says; a request with neither
is refused. One process therefore serves a legacy handshake, a legacy confirmation and a modern
confirmation in any order, and the continuation minted in either era is worthless in the other
request that did not mint it, because the binding is the same one either way.

---

## 23. The presence declaration

Added 2026-08-14 at the **presence round** (§18.14). Sections in this document are never
renumbered, so §23 sits physically after §22. It is normative exactly as §§1-17 are.

Every flag and every positional argument declares, at registration, **exactly one** of three facts
about itself: that a value must be supplied (**required**), that absence is legal and is delivered
as absence (**optional**), or a **default** value the framework supplies when nothing else does.
Declaring none of the three does not register. Declaring two does not register. Nothing about
presence is ever inferred from the shape of another declaration.

Nothing here is conditional on the effects regime. It is pinned in this document for the reason
§21 is: this is where cross-language spellings, registration-error texts and schema fields are
pinned, and the presence declaration joins `effect`, `consequential` and `dry_run_supported` as a
registration-level declaration the framework refuses to guess at.

**The evidence, measured across the fleet before the round.** Python collapsed `default=None` into
"required" while Go's `Default(nil)` and TypeScript's `default: null` delivered a real
not-provided, so between 140 and 182 Python flags were written expecting the Go/TS meaning and were
silently required instead -- with correct fetch-then-merge handler code sitting unreachable behind
them, and three "no fields specified" guards that could never fire. Between 214 and 375 flags used
`default=""` as an absence sentinel, which destroys `""` as a value. Nine sites wrote a tool-picked
value on absence. The dumped schema erased requiredness entirely, so schema parity passed by
erasure; the three MCP projections disagreed three ways about required bools; and optional-flag
absence had zero conformance coverage in any language. Every one of those is a consequence of the
same missing declaration.

### 23.1 The rule

- **Exactly one of the three**, on every flag at every level (command flags, flag-set flags,
  ~~mutex-group members~~ *(amended 2026-08-14, scoped-selector round, §18.15 item 178)* **member
  flags and scoped sub-flags at any depth (§24.1, §24.4)**, app global flags) and on every
  positional arg.
- **Zero** is a registration-time hard error naming all three choices (§12.12).
- **Two or more** is a registration-time hard error naming the two that were supplied (§12.12).
- **A null-valued default is not a spelling of optionality.** `default=None` / `Default(nil)` /
  `default: null` is a registration error that redirects to the optional spelling. This is the
  one-spelling-per-fact rule: optionality has exactly one way to be written, and the value-shaped
  way is refused rather than accepted as a synonym. `presence="optional"` is what delivers `None`.
- All of it is **registration-time**, in all three implementations, with the texts §12.12 pins.

The rule is stated as a positive requirement rather than as a lint over the old surface on purpose:
after this round there is no such thing as a flag whose presence is unstated, so nothing downstream
-- parse, help, schema, MCP, `ctx.provided` -- has an absence case to handle.

### 23.2 The spellings, per language

| Fact | Python | Go | TypeScript |
|------|--------|-----|-----------|
| required | `presence="required"` | `Required()` | `{ presence: "required" }` |
| optional | `presence="optional"` | `Optional()` | `{ presence: "optional" }` |
| default | `default=<value>` | `Default(<value>)` | `{ presence: "default", default: <value> }` |

**Python.** `presence=` joins `default=` on the `flag()` decorator and the `Flag` dataclass.
Supplying both is the two-declared error; supplying neither is the zero error, which is exactly the
`_MISSING`-sentinel path -- the sentinel stops resolving to `None` and starts refusing to register.

**Go.** Three sibling `FlagOption`s. `Default(v)` keeps its current shape and its unexported
`hasDefault`; `Required()` and `Optional()` set the same presence field it does. A `Flag` **struct
literal** that never passes through the option constructors declares no presence and therefore does
not register -- which closes a pre-existing trap as a side effect: an exported `Default` field set
directly on a struct literal left `hasDefault` false and was silently ignored at parse time. After
this round that flag does not register at all, so the value cannot be silently dropped.

**TypeScript.** `FlagOpts` becomes a **discriminated union on `presence`**, mirroring the
three-shape union `ArgOpts` has carried since the port:

```ts
| { presence: "required";  /* ...the common options... */ }
| { presence: "optional";  /* ... */ }
| { presence: "default"; default: Out; /* ... */ }
```

A `default` outside the `"default"` member does not type-check, and the `"default"` member's
`default` is not optional. `default: null` is still refused at **registration** rather than only by
the type system, because a widened option object can reach the factory at runtime with a `null` the
compiler never saw.

**The type-level consequence is part of the promise, not a side effect.** `infer.ts`'s
`FlagKeyIsOptional` reads `presence` instead of `opts extends { default: null }`, which fixes the
known unsoundness it had: a mutex member declared without a default was typed as an
always-present, non-nullable key, while the parser handed it `undefined` through the exemption
§23.4 deletes. ~~After this round the member declares `presence: "optional"` like anything else, and
the handler-args type follows the declaration by construction.~~ *(amended 2026-08-14,
scoped-selector round, §18.15 item 178)* After this round every flag declares its presence and the
handler-args type follows the declaration by construction. The **mutex member** itself no longer
exists: a member flag declares `required`, read as *required once this member is elected* (§24.4),
and a choice's scoped flags are reachable only through the tag that proves the scope was elected --
which is the structural fix §24.12 records for the same unsoundness this paragraph closed by
declaration.

### 23.3 Positional args

Args take the **same three facts and the same one-spelling rule**. The old arg surface --
Python's `required: bool = True`, Go's `ArgRequired(b bool)`, TypeScript's `required?: boolean` --
is **deleted**, not retained beside the new spellings.

| Fact | Python | Go | TypeScript |
|------|--------|-----|-----------|
| required | `presence="required"` | `ArgRequired()` | `{ presence: "required" }` |
| optional | `presence="optional"` | `ArgOptional()` | `{ presence: "optional" }` |
| default | `default=<value>` | `ArgDefault(<value>)` | `{ presence: "default", default: <value> }` |

Three reasons, each of which independently forces the deletion:

- `required=True` was an **implicit default** -- an arg that declared nothing was required by
  omission, which is the same derivation §23.1 removes from flags, one surface over.
- `required=False` **plus** `default=` spelled a defaulted arg, and `required=False` alone spelled
  an optional one, so the fact lived across two fields with a guard (`required arg cannot have a
  default`) holding the illegal corner shut. One field with three values needs no guard.
- Keeping `required=` beside `presence=` would be two spellings for one fact -- the exact thing the
  `default=None` redirect exists to prevent.

**Delivery.** An optional arg delivers **absence as a present key** (`None` / `nil` /
`undefined`), the same as an optional flag. It does **not** omit the kwarg, which is what all three
implementations did before. Key-absence delivery was considered and rejected for the whole round:
it fails at runtime, on the least-tested path, in the handler rather than at registration.
TypeScript's inferred args type keeps `?:` for an optional arg -- an optional property whose value
is `undefined` is what a reader of that type expects -- and the runtime object carries the property.

**Variadic args.** A variadic arg always delivers a list, so `required` means *at least one value*
and `optional` means *possibly none*, and a `default` on a variadic arg is a registration error
(§12.12). The empty case is `optional`, spelled once.

**The handler-parameter check (Python only).** A Python handler parameter bound to an optional flag
or an optional arg must itself default to `None`. Anything else -- `def h(ctx, target="")` bound to
an optional `--target` -- re-introduces at the handler boundary the sentinel the declaration just
removed, and the framework can see it at registration because Python handlers name their
parameters. It is a registration-time hard error (§12.12). Go and TypeScript have no such site:
their handlers receive one kwargs map / one args object and no per-parameter defaults exist to
check.

> **Amendment (2026-08-14, presence round -- implementation sweep): the check reads narrowly, and
> the narrow reading is the only implementable one.** It fires on exactly one shape: the bound
> parameter **has** a default and that default is **not** `None`. A **bare** parameter -- one
> declaring no default at all, `def h(ctx, target)` bound to an optional `--target` -- is legal
> and is not an error. The wide reading ("every parameter bound to an optional declaration must
> literally be written `=None`") is the natural first reading of the paragraph above, and it is
> refused for two independent reasons, either of which is sufficient on its own:
>
> - **The wide reading is unimplementable.** Python forbids a parameter without a default after
>   one that has it, so requiring `=None` on every optional-bound parameter would force handler
>   authors to reorder parameter lists that have nothing to do with presence. A rule satisfiable
>   only by rewriting unrelated parameter order is not a rule about re-sentinelization.
> - **A bare parameter is not a re-sentinelization site.** The framework passes every declared
>   value as a keyword argument on **every** dispatch -- that is this section's delivery rule,
>   absence as a present key -- so a bare parameter receives the framework's `None` and no second
>   value competes with it. The hazard the check exists for is a *written* sentinel, `target=""`,
>   and a bare parameter writes none.
>
> A `**kwargs` handler under guard v2's declared forwarding (§10.2) names no parameter at all and
> is likewise unaffected: the same absent site Go and TypeScript have everywhere.

### 23.4 What is deleted

Five mechanisms, all of them inferences, all of them removed rather than left unreachable:

| Deleted | Where | What replaces it |
|---------|-------|------------------|
| `default=None` collapses to required | Python's `_MISSING` resolution and its parse-time "no default and no value: required" branch | the declared presence |
| `hasDefault`-only inference | Go's `hasDefault` read as "optional iff a default was set" | the declared presence; `hasDefault` survives only as the storage for `Default(v)` |
| `default === undefined` means required | TypeScript's parse and help paths | the declared presence |
| the silent empty-collection default | all three: a repeatable/list flag with no declared default became `[]`, a dict flag `{}`, "never required" | `default=[]` / `default={}` declared explicitly, or `optional`, or `required` (§23.5) |
| the mutex-member presence exemption | Python's `mutex_flag_names` branch in the defaults step, Go's `parse.go` equivalent, TypeScript's `parse.ts` equivalent | the member's own `optional` declaration; the group enforces cardinality **on top of** presence, never instead of it |

The last one is the one with a second-order effect worth stating: the exemption existed because a
mutex member could not say "I may be absent", and its removal is a prerequisite for the constraint
system's by-name model. It also makes §21 read as it always should have -- a group decides *which*
member is chosen, and a member decides what its own absence means.

> **Amendment (2026-08-14, scoped-selector round, §18.15 item 178): the last row's *replacement*,
> and the paragraph above it, are superseded.** What this round deleted is unchanged -- the
> parse-time exemption is gone, and the table records it correctly. What no longer holds is what the
> row says replaces it, and the sentence built on that:
>
> - **"the member's own `optional` declaration"** is wrong twice over. `MutexGroup` is deleted
>   (§21's box, §24.4), so there is no group left to "enforce cardinality on top of presence"; and a
>   **member flag must declare requiredness**, read as *required once this member is elected*
>   (§12.13's `errMemberFlagPresence`, §23.5's own superseded-row box). The exemption's real
>   replacement is the **scope**: an unelected choice's flags are not resolved at all, and an
>   elected choice's flags declare and resolve presence exactly as any flag does (§24.1).
> - **The prerequisite clause is re-homed rather than withdrawn.** Exactly-one left the constraint
>   system entirely (§24.14, item 176), so the deletion is a prerequisite for the *selector
>   construct*; the by-name reference model survives for the co-occurrence families that remain.
> - **The closing sentence about §21** stands only as history: a group no longer decides anything,
>   because there is no group. Its live form is §24.1's -- the selector decides which choice is
>   elected, and each flag inside the elected scope decides what its own absence means.

### 23.5 Composition

Presence composes with every other declaration in the framework. Each cell below is pinned, and
none of them is new behaviour left implicit: where a row states today's behaviour, it is stated
because it was never written down and the round is what makes it a promise.

| Composed with | `required` | `default` | `optional` |
|---|---|---|---|
| **`choices`** | a supplied value must be in `choices` (unchanged) | the declared default **value** must be in `choices` at registration (unchanged text) | legal, and **nothing is checked at registration**: there is no value. Absence is never matched against `choices` at parse time; a supplied value is |
| **`bool`** | must be passed: `--x` or `--no-x` when negatable, `--x` when not (existing parse errors, unchanged) | `default=True` / `default=False` | **real tri-state**: `--x` is true, `--no-x` is false, absent is absent. This is what retires the string-pseudo-bool idiom |
| **repeatable / `list[T]`** | at least one occurrence must arrive from some source, else `flag '--x' is required` | `default=[]` is an explicit, legal declaration, as is a non-empty list | absent delivers **absence**, not `[]`. A handler that wants an empty list declares one |
| **`dict[K,V]`** | at least one key must arrive, else the same error | `default={}` legal, as is a non-empty map | absent delivers absence, not `{}` |
| **`env`** | an env-supplied value **satisfies requiredness**; there is no separate "must be typed" rule | env wins over the default (CLI > env > config > default, unchanged) | an env value makes the flag **provided** (§23.6), source `env`. Neither present leaves it absent |
| **`config`** | a config value satisfies requiredness | config wins over the default, loses to env and CLI | a config value makes the flag provided, source `config` |
| **`Implies` target** | the injected value **satisfies requiredness**, because implication resolves before defaults and before the required check. With the trigger absent, the required error fires normally | the injection is applied before defaults, so the default never applies; source `implied` | the injection makes it provided, source `implied`; without the trigger it stays absent |
| **`Implies` trigger** | fires whenever the flag is **provided** (§23.6) | **never fires from its own default** -- a defaulted trigger fires only when something actually supplies it | fires when provided |
| **`CoRequired`** | a required member is always provided, so the group then forces every other member to be provided in every invocation. Legal, and stated because it is a surprising shape to write by accident | a `default` member is **not** provided by its default, so it never counts as present for the group | the ordinary case: present iff provided |
| **`Requires`** | same predicate on both sides | a default on the depended-on flag does **not** satisfy the dependency | present iff provided |
| **mutex member** | **registration error** -- the group's own requirement is what makes the choice mandatory, and a member that must always be typed contradicts a group that permits exactly one (§12.12) | legal and unchanged: §21.3's unelected member delivers its declared default | the ordinary declaration for a member; election stays CLI-only (§21.3) |
| **`validate`** | runs on the supplied value | runs on a supplied value, never on the default | **never runs on absence**; runs on a supplied value |
| **`RelativeToRoot`** | n/a | the marker **is** a `default=` declaration: `presence` is `default`, the value resolves at parse time, the source label is `infra` | n/a |
| **URL-class flag (`connection_url`)** | requiredness is satisfied by the bound connection env's value, which is the `env` row; no extra guard | legal | legal |

~~Two~~ **Three** whole-table notes *(amended 2026-08-14, presence round -- implementation sweep:
the third is added below)*:

- **The default-in-choices check applies to declared VALUES only, never to absence.** That single
  sentence is what makes `choices` compose with `optional` in both directions, and it is the reason
  the check's existing text is unchanged: it never had anything to say about a flag that declares
  no value.
- **Requiredness is satisfied by any source that provides a value** -- CLI, env, config or an
  implication. It is not a "must be typed on the command line" rule. ~~The one exception is the
  mutex row, and it is §21.3's exception rather than this round's: env and config are not consulted
  for a mutex member at all.~~ *(amended 2026-08-14, scoped-selector round, §18.15 item 178: the
  mutex row is superseded, so the exception is restated over what replaced it)* The one exception is
  **member spelling**, and it is §21.3's exception carried over rather than this round's: env and
  config are not consulted for a member flag at all (§24.6). A **token**-spelled selector takes
  every source like any value flag, and a **scoped** flag's env or config binding is consulted
  exactly when its scope is elected and otherwise never consulted at all -- §24.6's conditional
  binding, which is a declaration property rather than a second exception.
- **The `validate` row's `default` cell SUPERSEDES shipped Python behaviour** *(added 2026-08-14,
  presence round -- implementation sweep)*. The cell reads *runs on a supplied value, never on the
  default*, and this section's preamble says a row stating today's behaviour is stated only
  because it was never written down. That preamble does not cover this cell: Python **ran a flag's
  `validate` callable on the declared default** when nothing supplied a value, and Go and
  TypeScript did not. The cell is the converged rule, all three now do it, and Python loses the
  shipped behaviour. The reasoning is the round's own: a default is the declaration's value, the
  author's to get right at registration, and validating it at parse time makes a declaration's
  legality depend on an invocation that never mentioned it -- surfacing as a parse error against a
  command line that supplied nothing wrong. It is recorded as a whole-table note rather than left
  inside the cell because a reader of the cell would otherwise take it for a restatement of what
  all three already did.

> **Amendment (2026-08-14, scoped-selector round, §18.15 item 178): the `mutex member` row is
> superseded, and presence composes with a scope instead.** The row's construct is deleted (§21's
> box), so all three of its cells describe a declaration that can no longer be written. What
> replaces each of them is stated rather than left to inference:
>
> | Struck cell | What replaces it |
> |---|---|
> | ~~`required` -> registration error~~ | a **member flag must** declare requiredness (§12.13's `errMemberFlagPresence`), read as *required once this member is elected*. The rule inverts because the declaration changed: the flag now belongs to the choice it elects, not to a group that permits exactly one of several |
> | ~~`default` -> legal, unelected member delivers it~~ | no cell at all: an unelected choice's scope is not delivered, so there is nothing for a per-member default to fill. A *selector* may carry a default (§24.5), and it names a complete selection rather than a member's value |
> | ~~`optional` -> the ordinary declaration for a member~~ | a member flag cannot be optional, per the first row. A **scoped sub-flag** may be optional, required or defaulted exactly as any flag is, resolved within its scope when that scope is elected (§24.1) |
>
> The rest of the table is untouched. Every other row composes with a scoped flag unchanged, one
> level down: `choices`, `bool`, the compounds, `validate` and `RelativeToRoot` mean inside a scope
> exactly what they mean at root scope, and `env` / `config` mean what §24.6 pins for a conditional
> binding.

### 23.6 `ctx.provided`

A dedicated boolean accessor, in all three languages, for the question the fleet was asking with
sentinels:

| Impl | Spelling |
|------|----------|
| Python | `ctx.provided(name) -> bool` |
| Go | `ctx.Provided(name) bool` |
| TypeScript | `ctx.provided(name): boolean` |

It accepts dashed or underscored names, underscore form tried first, exactly as `ctx.source` does.

**Semantics, defined over the existing source vocabulary** (`cli` | `env` | `config` | `default` |
`implied` | `infra` -- the framework's existing per-value source labels):

| Source | `provided` | Why |
|--------|-----------|-----|
| `cli` | **true** | the invocation supplied it |
| `env` | **true** | the invocation's environment supplied it; the framework did not invent it |
| `config` | **true** | the operator's own file supplied it; likewise not invented |
| `implied` | **true** | it exists **only** because the invocation contained the trigger. An implication is a consequence of what was typed, not a fallback |
| `default` | **false** | the declaration supplied it |
| `infra` | **false** | a `RelativeToRoot` default resolved through a declared root: still a declared default, with a distinct label so the operator can see *which* default it was |

One sentence covers it: **`provided` is true when the invocation caused the value and false when
the declaration did.** The same predicate is what `CoRequired`, `Requires` and `Implies` already
use to decide presence, so the framework has one definition of "was this supplied", not two.

> **Amendment (2026-08-14, presence round -- implementation sweep): the shared definition excludes
> `infra`, and enforcing that changes shipped Go and TypeScript behaviour.** The sentence above was
> written as a description of what the three already did, and it was true of two of them. The
> dependency predicate -- `is_present_for_deps` / `isPresentForDeps` and the `Implies`-trigger and
> `CoRequired` / `Requires` call sites that read it -- excluded `default` in all three, but
> **Python alone also excluded `infra`**. So a `RelativeToRoot`-defaulted flag sitting inside a
> `CoRequired` or `Requires` family **counted as present** in Go and TypeScript and did not in
> Python: two definitions of "supplied", invisible until this round because there was no
> `ctx.provided` for either to contradict.
>
> The pin: **the dependency predicate excludes both `default` and `infra`, in all three languages,
> and it is the same predicate `ctx.provided` reads.** One definition, one implementation of it,
> as the sentence above promises. Python is the reference here; Go and TypeScript change.
>
> The behaviour change is real and narrow, and it is the correct direction under §23.6's own
> dividing line: an infra default is a declared default whose label merely says *which* default it
> was, so the declaration caused the value and the invocation did not. After this round a
> `RelativeToRoot`-defaulted flag no longer satisfies a dependency on its own, and a `CoRequired`
> group whose members are all infra-defaulted is satisfied by nothing rather than by everything.

**An optional flag that received nothing** carries source `default` and `provided() == false`. It
has no declared default value; `default` is the label for "the declaration decided", and an
optional declaration deciding on absence is that. No new source label is minted for it -- adding a
seventh label would change `ctx.source`'s vocabulary for every existing consumer to express
something the sixth already covers.

**An unknown flag name behaves exactly as `ctx.source`'s does**, with the same message
(`errNoSourceInfo` / `no source info for flag "<name>"`): Python raises `KeyError`, Go panics,
TypeScript throws. `provided` reads the same per-parse store `source` reads, so a name that has no
source has no provision either, and giving the two accessors two texts for one condition would be
the two-spellings mistake again.

`ctx.source` is **not** superseded and is not deprecated. It answers a narrower question -- *which*
origin -- and remains the accessor for a handler that needs to distinguish env from config. What
changes is that no handler should be reconstructing a boolean out of it.

### 23.7 Schema and MCP

Both live in §13, where command-entry and flag-entry facts are pinned; see the presence-round
amendment box there. In summary: one canonical `presence` key on every flag and arg entry, always
emitted; `default` emitted exactly when `presence` is `"default"` and then always, including for
`[]`, `{}`, `""`, `false` and `0`; the arg entry's `required` key deleted; the three hand-written
MCP requiredness derivations collapsed onto the declared field, which puts required bools into the
Go and TypeScript tool schemas as they were already in Python's.

### 23.8 Help rendering

**Every flag and every arg renders exactly one presence part**, and it is the **last** bracketed
part of the line -- the position all three implementations already give it:

| Declared | Rendered |
|----------|----------|
| `required` | `[required]` |
| `optional` | `[optional]` |
| `default` | `[default: <value>]` |

This converges a live divergence. `[optional]` was **Go and TypeScript only** -- the `Default(nil)`
rendering -- and Python could not produce it at all, because Python had no way to express the
declaration behind it. Python gains it. Nothing else about the rendering moves: a bool default
still renders `[default: true]` / `[default: false]`, and the presence part still follows
`[list]` / `[dict]` / `[repeatable]` / `[unique]` / `[choices: ...]` / `[env: ...]`.

Two consequences of the invariant, both of which change bytes:

- **A declared empty collection default renders `[default: []]` or `[default: {}]`.** All three
  implementations previously rendered *nothing at all* for it, because the empty collection was the
  framework's own silent default and there was nothing to announce. It is now a declaration, and a
  declaration that renders as blank would leave the flag as the one line in the help output with no
  presence part. The literal empty-collection spellings are used rather than a new word, so the
  vocabulary does not grow.
- **A required positional arg renders `[required]`.** All three previously rendered no marker for
  it, and there is no usage line anywhere in the help output that showed requiredness some other
  way -- so a required positional was the one declaration in the framework whose presence was
  invisible to a reader. It is now rendered exactly as a required flag's is.

> **Amendment (2026-08-14, presence round -- implementation sweep): three renderings the invariant
> reached and this section had not pinned.**
>
> - **A bool default renders lowercase everywhere, positional args included.** `[default: true]` /
>   `[default: false]`, never the host language's own spelling of the literal. The paragraph above
>   already said so, but said it about flags: Python's **arg** side ran the value through its
>   generic formatter and rendered `[default: True]`, so one declared value rendered two ways in a
>   single help page depending on which surface carried it. The arg side converges onto the
>   lowercase form -- it is what the other two produce, and it is what a reader would type back on
>   the command line.
> - **A non-empty dict default renders as sorted `key=value` pairs**: `[default: a=1, b=2]`. Keys
>   sorted, `, ` between pairs, each value through the same error-message value formatter the rest
>   of the family uses. This closes a live divergence rather than restating agreement: **Go
>   rendered nothing at all** for a non-empty dict default, which left the flag's line with no
>   presence part -- precisely the hole the exactly-one-presence-part invariant exists to close.
>   The empty case stays `[default: {}]` per the first bullet above.
> - **The app-level `Global flags:` summary carries no bracketed metadata, and deliberately keeps
>   none.** App-level help lists each global flag as its spec plus its help text and nothing else.
>   The flag's full line -- type, compound, choices, env, and the one presence part -- is rendered
>   where the flag is *used*, at command level, which is where this section's invariant applies.
>   The summary is an index of what exists, not a statement of how each entry behaves, and giving
>   it a presence part would put the same fact on two lines of one help run. This is pinned
>   because "every flag and every arg renders exactly one presence part" would otherwise read as
>   reaching it, and a later reader would take the absent brackets for an omission.

> **Amendment (2026-08-14, presence round -- conformance sweep): an infra-rooted default renders as
> the declaration that produced it.**
>
> A flag or arg whose default is a `RelativeToRoot` marker renders
> **`[default: RelativeToRoot('<VAR>', '<part>', ...)]`** -- the marker's declaration, quoted the
> way Python's `repr` quotes a string: single quotes, switching to double quotes only when the
> value contains a single quote and no double quote, backslashes escaped, and the separator after
> the env var kept even when there are no parts at all (`RelativeToRoot('E', )`). The **resolved**
> path is deliberately never rendered: it is machine-specific, so printing it would make one
> declaration's help output differ between two machines running the same version.
>
> This closes a live divergence found by the cross-language sweep. Python and TypeScript already
> produced this form -- Python because the marker's `repr` is what its help formatter reaches, and
> TypeScript because its marker mirrors that `repr` deliberately. **Go leaked its own struct
> formatting** instead: the marker had no display form, so `fmt`'s `%v` rendered the fields, and
> Go's help line read `[default: {MYAPP_ROOT [store]}]` -- Go's internal shape, in a form no reader
> could type back and no other implementation produced. Go converges onto the majority form, which
> is also the only one of the three that names the declaration a reader wrote.

### 23.9 What this round does not touch

Stated so the boundary is a decision rather than an omission:

- **`ConfigField` requiredness.** A standalone config field still derives its requiredness from
  whether it declares a default. A config field is not a CLI declaration: it has no presence on a
  command line, no help marker, no MCP projection and no `ctx.provided` question, and the failure
  mode this round exists to remove -- a handler unable to tell absence from a value -- does not
  arise for it. A field that collides with a flag inherits the flag's handling, which is the
  declared one.
- **The constraint system.** ~~By-name constraint members, the at-least-one and all-or-none
  constructors, declared election selectors and the collapse of bool-only groups into required
  `choices` flags are a separate round with its own amendment.~~ *(amended 2026-08-14,
  scoped-selector round, §18.15 item 176)* By-name constraint members and the at-least-one and
  all-or-none constructors are a separate round with its own amendment. **Two items in the struck
  clause were re-homed rather than deferred**: exactly-one left the constraint system entirely and
  became the selector construct (§24, §24.14), and the collapse of bool-only groups into required
  `choices` flags is superseded by that construct plus the per-choice-help records §24.2 pins --
  which is what the collapse needed and could not have. "Declared election selectors" (a `when:`
  vocabulary on constraint members) survives for the families that remain. §23.4's deletion of the
  mutex-member exemption is still the prerequisite, and it is still all this round does about
  groups.
- **The update-command construct.** The mutating-default ban, `update_of=`, `write_mode=` and the
  `--unset-<prop>` vocabulary are a third round. This round makes the distinction they rest on --
  absent versus defaulted versus required -- expressible; it does not use it.
- **Consumer migration.** Retiring the `default=""` sentinel idiom is a per-repository judgement
  about which sites meant "absent" and which meant `""`, and no framework rule can make it. What
  the framework provides is that after this round both are sayable and they are not the same
  declaration.

---

## 24. The scoped-selector construct

Added 2026-08-14 at the **scoped-selector round** (§18.15). Sections in this document are never
renumbered, so §24 sits physically after §23. It is normative exactly as §§1-17 are.

**A choice is a declaration scope.** A *selector* is a flag that elects exactly one of its declared
*choices*, and each choice owns the flags that exist only while it is elected. `notify send --via
email --subject hi` parses; `notify send --via sms --subject hi` is a parse error the declaration
produces on its own, naming the flag, the choice that owns it and the choice that was elected --
never "unknown flag". Scoping by nesting replaces scoping by separate constraint objects: *`--subject`
belongs to `email`* is expressed by where the declaration sits.

Nothing here is conditional on the effects regime. It is pinned in this document for §21's and
§23's reason: this is where cross-language spellings, registration-error texts, message templates
and schema fields are pinned.

**The evidence.** Three prototypes -- one per language, all running, each with its own complete
challenge list -- were built before any ruling was taken, and they are the reference for every
spelling below. They established four things this section now pins as promises rather than as
findings: the construct subsumes plain constrained values, per-choice documentation and
payload-carrying alternatives at once; **member spelling reproduces §21's mutex sentences
byte-for-byte**, so migrating a group changes no user-visible text; recursion costs nothing because
the command is itself the root scope; and the handler code the construct deletes is real -- the
`unreachable: the mutex guarantees exactly one of these` branches in the fleet, and the
"required exactly when user-facing" rules that live in handler bodies today.

### 24.1 The construct

- **Election.** A selector elects **exactly one** of its choices per invocation. There is no
  at-most-one (an absent selection is a choice nobody named -- name it, ruling B2) and no
  multi-elect in this round (§24.13).
- **Scopes.** Each choice declares a scope: flags that are legal **only** while that choice is
  elected. A flag supplied outside its elected scope is a **distinct parse error** naming the flag,
  its owning choice, and the choice that was elected instead (§12.13). The command is the **root
  scope**, which is what makes every rule below uniform at every depth.
- **Order independence.** Nothing is interpreted until every token is collected: `--subject hi
  --via email` parses exactly as `--via email --subject hi` does. This is the framework's existing
  promise that flags are recognized anywhere in argv, and the construct does not weaken it.
- **Recursion.** A selector is a flag, so a selector may be declared inside a choice's scope, to
  **unlimited depth** (§24.7). "Required exactly when user-facing" stops being a rule a handler
  enforces and becomes where the declaration sits.
- **Delivery is one tagged value per selector.** The handler receives, under the selector's own
  key, the elected choice **plus that choice's fields**: a frozen dataclass instance consumed by
  `match` (Python), an `*Elected` carrying identity-checked choices consumed by `Match`/`When`
  (Go), a derived discriminated union consumed by `switch` (TypeScript). §24.12 pins the three.
- **Sub-flags are never top-level handler arguments**, at any depth. That is what keeps §23's
  delivery invariant untouched rather than merely compatible: every declared **top-level** key is
  still always present, because the only key a selector adds is its own. One level down, §23's rule
  applies again unchanged -- an optional sub-flag delivers absence as a present **field** of the
  record, never a missing one.
- **Sub-flags declare presence like everything else.** `required`, `optional` or a `default`
  (§23.1), resolved when their scope is elected, refused at registration when undeclared. A scope
  is not a presence declaration and never supplies one.

### 24.2 Two constructs, one machinery

`choices=` **survives** as the value-flag spelling. The two constructs are not alternatives to be
chosen by taste; the boundary is **structural**, and it is the single most important sentence in
this section:

> **Need a scope or member spelling -> selector. A plain constrained value -> choices flag.**
> The moment one choice needs a flag of its own, or one alternative needs to be spelled as its own
> flag, the declaration is a selector.

| | value flag (`choices=`) | selector (§24.12's constructors) |
|---|---|---|
| what an entry is | a **value**, with **optional** help | a **choice**: a name, **mandatory** help, and a scope |
| delivery | the bare scalar, unchanged | one tagged record (§24.1) |
| presence | all three, unchanged (§23.5) | `required` or a `default` only; `optional` is refused (§24.5) |
| sources | all sources, unchanged | token spelling: all sources. Member spelling: command line only (§24.6) |
| spelling | one flag, one value | a selector token, or the choices' own flags (§24.4) |
| help | one line, or a block once any entry carries help (§24.10) | always a block (choices carry mandatory help) |

**A `choices=` entry is always a record.** The bare-value entry (`choices=["head", "branches"]`) is
**deleted**: an entry that may carry help and an entry that carries none would otherwise be two
spellings of one fact, which is §23's one-spelling-per-fact rule applied one surface over. The
record's help is **optional** -- that is what keeps §24.10's one-line rendering reachable -- and,
when supplied, must be non-empty, like every other help string in the framework. Every existing
choices flag in the fleet is therefore a mechanical rewrite, which the campaign's own migration
already reaches.

**The graduation cost is stated, not hidden.** Moving a declaration from a value flag to a selector
changes the handler contract from a **scalar** to a **record**: every read of that value changes
shape, and the command's tests, its `call()` sites and its MCP arguments change with it. That cost
is the reason the two constructs both exist -- forcing every four-value enum through a selector
would make every simple flag pay it -- and it is the reason the boundary is drawn at what the
choices *carry* rather than at how many there are.

### 24.3 Parsing

Parsing is **phased**, and the phases are what make order independence, the distinct out-of-scope
error, and that error's priority over a missing required flag fall out instead of being
special-cased:

1. **Tokenize** every occurrence, without interpreting any of it.
2. **Resolve elections**, outermost first, then recursively inside each elected choice.
3. **Validate scope membership** of every supplied flag.
4. **Resolve values and presence** within the live scopes only.

**Error precedence is pinned by that order**, so a command line with several problems reports the
same error every time and never one that depends on declaration order:

> **election -> scope -> value -> presence.** An unknown choice or a double election is reported
> before a scope violation; a scope violation before a coercion or `validate` failure; and all of
> them before "flag `--x` is required". `--via sms --subject hi` says *`--subject` belongs to
> `email`*, never *`--phone-number` is required*: the spelling mistake is reported before its
> consequence.

One consequence of that order is worth stating, because it looks like an omission otherwise: a
**required selector that elected nothing** is reported as a scope error when a flag of one of its
scopes was supplied (`--subject hi` alone says *`--subject` is only valid under `--via email`, but
`--via` was not provided*), and as the ordinary required-flag error when nothing else was supplied.
Both statements are true; the precedence rule picks the one that names a token the reader typed.
Recording a missing required election and deferring its refusal until after scope validation is
therefore part of the election phase's contract, not an implementation detail.

**Tokenization cannot wait for an election.** Whether `--target` consumes the next argv element is
decided before any choice is elected, which is why sibling scopes may reuse a name only with an
identical type and arity (§24.7). The alternative -- deferring value binding until after election -- would
make the `--flag value` / `--flag` distinction depend on parse order, and is refused.

**Blame the outermost unsatisfied election.** A flag two levels down whose *outer* election is the
one that failed blames the outer election, not the dead selector directly above it: that is the
token the reader would have to change. §12.13 pins the sentence.

**Unaffected by the construct, and re-verified per surface:** the reserved quartet's and `--json`'s
position-independent pre-scan (it runs before the command's declaration is consulted), the bare `--`
boundary, passthrough commands (they declare nothing), `--hermetic`, `--config`, at-prefix
resolution on a scoped string flag when it is supplied, negation of a scoped bool, and repeatable
and dict sub-flags.

### 24.4 Member spelling

A choice may be spelled as **its own flag, carrying its own payload**: `--profile work` elects the
`profile` choice with the value `work`; `--all-profiles` elects a payload-less one. No selector
token is ever typed -- the selector's name exists as the handler key and as the noun help and errors
use.

**This is §21, restated as a scope tree.** The delivered value is the same kind of tagged record the
token spelling produces; only tokenization differs. Everything §21 pins about what a typed token
does to an election carries over verbatim -- a bool member elects only on **true**, `--no-<name>`
**declines** rather than choosing, a redundant negation beside a real election is a parse error, and
election is **command-line only** -- and §21's box records item by item what survives and what
retires with the group construct.

What member spelling adds, and a mutex group could not express:

- **A member may own a scope.** `--profile work --create-missing` parses and `--all-profiles
  --create-missing` is a scope error, where a mutex group could only leave the second silently
  ignored.
- **A member carries its payload in the alternative that owns it**, so the sentinel defaults a
  mutex member had to declare (`Default(nil)` / `default=False` on flags that mean nothing unless
  elected) disappear.
- **The refusal spelling cannot elect.** A member flag is elected by `--x` and declined by
  `--no-x`; the hazard that made `--no-only-tags` push everything and `--no-mangle` mangle
  everything has nowhere left to live -- not because a parser rule catches it, but because the
  declaration no longer produces a per-member value a handler can misread.

**The member flag's own presence is `required`**, read as *required once this member is elected*,
and anything else is refused at registration (§12.13). A member-spelled selector **cannot carry a
short** -- it is never typed -- and a short declared on a member is an ordinary flag short.

**A payload is exactly one value, delivered under the reserved name `value`** (§24.7), and only
under member spelling: a token-spelled choice is named by the token itself and has no payload to
carry, so declaring one is a registration error.

### 24.5 Presence on a selector

A selector declares `required` or a `default`. **`optional` is refused** at registration, with a
redirect that names the remedy (§12.13): an absent selection is a choice nobody named, and the
answer is to name it -- the `repl` command's new-session member, the `launch` command's default
launch, the `internal` visibility. This is ruling B2 made structural: there is no at-most-one
construct anywhere in the framework, and this is the one place a consumer would otherwise
reintroduce it.

**A defaulted selection is complete.** A selector's `default` is a **complete elected value** -- a
choice plus every field its scope needs -- so a defaulted selection with an unsatisfied required
sub-flag cannot exist. The semantic is pinned cross-language; the **mechanism differs by language,
and the divergence is the point**:

| | how completeness is guaranteed |
|---|---|
| Python | the default **is a choice instance** (`default=Sms(phone_number="+15550100")`). A frozen dataclass cannot be constructed without its required fields, so the incomplete state is **unconstructable** -- there is nothing to check and no error to raise |
| Go | the default **names a choice**, and a registration check refuses a choice whose scope declares a required sub-flag (§12.13's `errSelectorDefaultIncomplete`) |
| TypeScript | the default **names a choice**, typed `keyof C & string` so a name that is not a choice is a compile error, plus the same registration check |

The Go/TypeScript template is therefore **Python-excluded** in `check_error_parity.py`, for
§12.12's reason and with the same rationale recorded: Python has no input that could produce it.

**Electing a choice on the command line never borrows the default's values.** A default is one
complete selection; an election is another. A choice elected by a token satisfies its scope from
that invocation, and a required sub-flag of it is required.

**A defaulted member-spelled selector may only default to a payload-less member**, because a
value-carrying member's value is supplied by the token that elects it and a default has no token
(§12.13).

The selector's own key follows §23.6 unchanged: `ctx.provided("via")` is true when the invocation
elected, false when the declaration's default did, and `ctx.source("via")` reports which.

### 24.6 Sources, and conditional bindings

Three rules, and the third is the one that needed a decision rather than a derivation:

- **A token-spelled selector elects from any source.** It is an ordinary value flag whose value
  happens to name a choice, so CLI > env > config > default applies unchanged.
- **A member-spelled selector elects from the command line only** -- §21.3, carried over with its
  reason intact: the spelling exists to make the operator choose *in the invocation*, and an
  inherited environment is not that choice. Env and config are, as before, not consulted for a
  member flag at all, and §21.3's `config_conflict_mode` carve-out is untouched.
- **Ambient values for flags in non-elected scopes are conditional bindings by declaration.** An
  env var or a config key bound to a scoped flag is consulted **when its scope is elected**, and
  otherwise **never consulted** -- it is not an error, and it is not a value.

The third rule is a declaration property, not a runtime adaptation, and the distinction is what
keeps it inside the no-silent-degradation rule rather than beside it: the binding's condition is
written in the declaration (the flag sits in a scope), the framework evaluates the same condition
the same way every run, and the same command line plus the same environment always produces the
same values. What is refused is the *silent* part, and it is refused by surfacing:

**Every skipped binding is named under `--verbose`**, one line per binding, in declaration order,
at debug level -- so it is hidden by default, shown by `--verbose`, and carried in machine mode's
`diagnostics` at level `debug` (§19.2) whatever the human stream did:

```
not consulted: env var '<VAR>' binds flag '--<x>' under '<scope path>', which was not elected
not consulted: config key '<key>' binds flag '--<x>' under '<scope path>', which was not elected
```

`errAmbientBindingSkippedEnv(var, x, path)` / `errAmbientBindingSkippedConfig(key, x, path)`. All
three. They are **diagnostics, not errors**: no `error: ` prefix, stderr's debug channel, and the
run continues.

**An election from a non-CLI source names itself in every message it causes.** A required sub-flag
missing under a scope elected by an environment variable, or a typed flag refused because an
ambient election opened a different scope, would otherwise blame a command line that does not
contain the cause. §12.13's origin clauses (` from env var '<VAR>'`, ` from config key '<key>'`,
` by default`) are appended for exactly that reason.

### 24.7 Names, reserved keys, positionals and depth

- **Two reserved names inside every scope**: `choice` (the delivered record's tag) and `value` (a
  member-spelled choice's own payload). A sub-flag of either name is a registration error
  (§12.13). The **record's** own object form is flat -- `{"choice": "email", "subject": "hi"}`,
  which is literally what TypeScript delivers and what every nested encoding of an elected value
  carries -- and that flatness is what makes the pair reserved. The nesting-one-level-deeper
  alternative (`{"choice": ..., "fields": {...}}`) was refused because it costs a level on every
  encoded value for a collision that two reserved names already close. (§24.11's MCP projection
  flattens one level further still, into the command's own argument object; the reservation is the
  record's, and it holds whichever encoding a boundary uses.)
- **Every existing name rule re-runs at every depth.** The reserved quartet and `json`, the banned
  `yes`, bare `force`, the `no-` prefix, `approve_consequential`, the charset and the help
  requirement all apply to a flag declared three scopes down exactly as they do at root. A ban
  enforced only against a flat root list is the most likely correctness defect in this construct,
  and it is written here as a requirement.
- **Choice names use the flag-name charset** in both spellings and are unique within their
  selector. Under member spelling a choice name **is** a flag name and inherits every flag-name
  rule, including the bans above.
- **Root versus scoped is a collision**: a scoped flag may not reuse a command-level flag's name
  (it could never be reached) nor the name of the selector that owns it.
- **Sibling scopes may reuse a name only with an identical type and arity.** Two choices of one
  selector can never be elected together, so the name is unambiguous at delivery -- but
  tokenization precedes election (§24.3), so the token's arity may not depend on the outcome.
- **Simultaneously electable scopes may not reuse a name at all** -- two selectors declared on one
  command, or a scope and any of its own ancestors. The rule is written against *simultaneously
  electable* rather than against *sibling* deliberately: it is the formulation that still holds if
  multi-elect is ever adopted (§24.13).
- **Shorts are claimed across every simultaneously live scope**; sibling scopes may reuse one.
- **Positional args cannot be declared inside a scope** (§12.13). A positional's meaning would
  depend on an election that may be typed after it, which would make argv order-dependent in a way
  flags are not. Positionals stay command-level, with `choices=` on them unchanged (in the record
  spelling, §24.2).
- **Nesting depth is unlimited.** Every rule above is stated per level and none of them has a depth
  cap; the prototypes' four- and five-level tests are the evidence that the uniform statement is
  also the implementable one.

### 24.8 Constraints operate at root scope only

`Requires`, `Implies` and the co-occurrence families reference flags **by name**, and after this
round there is no single flat namespace for a name to resolve in. The rule is a refusal, not a
resolution: **a constraint naming a scoped flag is a registration error** (§12.13).

The reason is that the scope already **is** the constraint. A choice's scope says "these flags exist
together, exactly when this choice is elected", which is a co-requirement plus an exclusivity plus a
conditional requirement in one declaration -- and expressing the same fact twice, in two mechanisms,
is how the two disagree later. Constraints stay at root scope, where the flags they name are
unconditional.

**In-scope constraints are the sanctioned extension**, not a rejected idea: a constraint among one
choice's own fields is meaningful and is well-defined (the scope is elected or the constraint is
vacuous). It is deliberately not built here, because no fleet site needs it yet; when one appears,
it is added as a nested declaration inside the choice, never as a root-scope constraint that reaches
into a scope by name.

### 24.9 Provided-ness inside a record

**The delivered record answers provided-ness for its own fields**, and the context-level accessors
deliberately do not see scope interiors:

| Impl | Spelling |
|------|----------|
| Python | `strictcli.provided(via, "subject") -> bool` |
| Go | `e.Provided("subject") bool` on `*Elected` |
| TypeScript | `provided(args.via, "subject"): boolean` |

Two facts force the shape. First, a scoped name is **not unique command-wide** (sibling scopes may
reuse it), so `ctx.provided("subject")` has no single answer and must not invent one: a scoped flag
is not in the context's per-parse store at all, and asking for one raises the existing unknown-name
error (`no source info for flag "<name>"`, §23.6) rather than a second vocabulary. The selector's
own key **is** in the store, and answers as any flag does. Second, the record's fields are
**user-named**, so a `provided` *method* would occupy a name a scope might want; Python and
TypeScript therefore spell it as a function over the record, and only Go spells it as a method --
Go's fields live in a `Fields` map, where a method name cannot collide with a field name at all.
That is B9's divergence rule producing three shapes for one semantic, not three answers.

The semantic itself is §23.6's, unchanged and evaluated inside the scope: a field is provided when
the invocation caused its value (`cli`, `env`, `config`, `implied`) and not when the declaration did
(`default`, `infra`). TypeScript additionally answers part of the question at the type level -- an
optional sub-flag's key is optional in the derived union -- which does not replace the accessor,
because a *defaulted* field is present in both cases and only the accessor separates them.

### 24.10 Help rendering

**The rule**: a choice-carrying flag renders as an **indented block** iff any of its choices carries
help **or** a scope; otherwise it keeps today's one-line `[choices: a, b, c]` form.

A selector therefore always renders as a block -- its choices carry mandatory help -- and a value
flag renders as a block exactly when its entries were given help. The layout:

```
Flags:
  -v, --via <choice>          delivery channel [required]
    email                     deliver the notification as an email message
      --subject <str>         subject line of the message [required]
      --recipient <str>       destination email address [required]
    sms                       deliver the notification as a text message
      --phone-number <str>    destination number in E.164 form [required]
  --dry-run                   print what would be sent [default: false]
```

- a choice line indents **two columns** past its selector's line; a choice's scoped flags indent
  **two columns** past their choice; recursion adds two per level;
- **one alignment column** is computed across the whole command's flag block, deepest entry
  included, so help text starts in the same column everywhere on the page;
- **§23.8's presence invariant holds at every depth**: every flag line, scoped or not, ends with
  exactly one presence part, and every rule §23.8 pins about rendering a value applies unchanged;
- a **member-spelled** selector has no token to render, so its own line carries its help, the
  clause `(exactly one of the following)` and its presence part, with the member flags rendered as
  ordinary flag lines two columns beneath it;
- a **value flag's** entries in block form render the value where a choice name renders, followed
  by its help; an entry with no help renders the value alone.

### 24.11 Schema, MCP and the machine boundary

**The dumped schema's selector encoding is deliberately not pinned here.** A selector's value shape
is a variant, which the closed JSON Schema subset cannot express, and the encoding is authored by
the **schema-v2 amendment** together with the rest of that round's value-shape work. What this round
pins is what that encoding must carry, so the later amendment has a requirement rather than a blank
page: the nested choices and scopes, each choice's help, each scoped entry's `presence` and
`default` on §13's terms, and the spelling (token or member). A dump that flattens a selector away
is not a legal intermediate state -- the erasure §13's presence box exists to end is exactly what a
partial encoding would restore -- so the two amendments ship into one release.

**The MCP projection is flatten plus a description map.** One object schema per command:

- the selector contributes **one property named after the selector**, `{"type": "string", "enum":
  [<choice names>]}`, in the schema's `required` array iff the selector declares `required`;
- **every scoped flag contributes a top-level property**, and **never** appears in `required` --
  its requiredness is conditional, and the schema has no vocabulary for that;
- a member-spelled selector projects **identically** to a token-spelled one. Tokenization is a
  command-line fact and there are no tokens at this boundary; a member's payload flattens under the
  member's own flag name, which the framework already guarantees unique command-wide;
- wrong combinations are refused **at call time**, with the **same sentence the CLI parser gives**
  (§12.13), carried as the protocol's invalid-params error.

The scope structure survives in the **tool description**, appended as a deterministic block so that
an agent can read the constraint it cannot see in the schema:

```
Scoped parameters (enforced at call time):
  via=email: subject (required), recipient (required)
  via=sms: phone_number (required)
  via=webhook: url (required), retries (default: 3)
  visibility=user-facing type=feature: (no parameters)
```

One line per scope, at every depth, in declaration order. The key is the scope's path rendered as
`<selector>=<choice>` segments joined by a single space -- the machine-side spelling of §12.13's
scope path, using the property names the schema publishes rather than the flags a CLI user types.
Parameters are listed in declaration order with their presence in parentheses (`required`,
`optional`, or `default: <value>`); a nested selector appears as a parameter of its parent scope and
also opens lines of its own; an empty scope renders `(no parameters)`.

**The cost is stated rather than discovered.** An agent cannot see the scope rule before it calls;
it learns by being refused. That is the least-bad of three options, and the other two are recorded:
one tool per choice is schema-exact but multiplies (two three-choice selectors on one command are
nine tools) and breaks the one-command-one-tool identity the rest of the MCP surface relies on;
extending the subset with `oneOf` opens a door the closed subset was built to shut. **`oneOf` in the
tool schema is the recorded future upgrade**, behind a measurement of what real clients do with it
-- not a rejected idea.

**`call()` takes the elected record, pre-typed.** The programmatic front door's contract is
unchanged -- pre-typed values, no parsing -- so the value for a selector is the same record a
handler receives: a choice instance (Python), an `Elect(choice, Fields{...})` value (Go), the union
member object (TypeScript). The flat machine form above is converted into that record at the
protocol boundary, through the **same** election, scope and presence machinery the argv path uses,
which is what makes the two front doors agree by construction rather than by test.

### 24.12 The authored spellings, per language

Per B9, parity binds semantics and pinned sentences, never declaration surfaces. Each surface below
is the one its language's prototype validated, and each is the shape that language's existing
strictcli idiom already pointed at.

**Python -- `@choice`-decorated frozen dataclasses.** A scope is a set of named typed slots, and
Python has exactly one spelling for that:

```python
@choice("email", help="deliver the notification as an email message")
class Email:
    subject: str = sub_flag(help="subject line of the message", presence="required")
    recipient: str = sub_flag(help="destination email address", presence="required")


@app.command("send", help="send one notification through exactly one channel", effect="mutating")
@choice_flag("via", help="delivery channel", short="v", presence="required",
             elect_by="selector-token", choices=[Email, Sms, Webhook])
def send(ctx, via: Email | Sms | Webhook) -> int:
    match via:
        case Email(subject=subject, recipient=recipient): ...
        case Sms(phone_number=number): ...
        case Webhook(url=url): ...
        case _: assert_never(via)
```

- `@choice(name, help=...)` makes the class a **frozen, keyword-only dataclass**; the decorated
  class is both the declaration and the delivered type, with structural equality, a useful `repr`,
  no mutable-default hazard and no field-ordering rule leaking out of `dataclasses`.
- `sub_flag(...)` takes **no `name=`**: the field name **is** the flag name (`phone_number` ->
  `--phone-number`), which is the mapping the framework already uses in the other direction for
  handler parameters. `sub_choice_flag(...)` is the nested-selector twin.
- `elect_by="selector-token"` / `elect_by="member-flags"` is **mandatory, with no default** --
  Python declares closed vocabularies as keyword strings (`effect=`, `presence=`), and the spelling
  is a decision, never an inference.
- a member-spelled choice's payload is a field named `value`, declared `value: str =
  member_value(help=...)`; it takes no presence keyword, because electing the member supplies it.
- **the handler-annotation check is mandatory** (§12.13): the parameter bound to a selector must be
  annotated with exactly the declared union, `**kwargs` handlers are banned on selector-carrying
  commands, and annotations are resolved at registration through `typing.get_type_hints` against
  the handler's module globals plus the decorating frame's locals. A name importable only under
  `TYPE_CHECKING` is a registration error naming it, rather than a `NameError` at import time. The
  check is what makes `assert_never` **sound**: without it a developer could annotate `via: Email`
  and silently skip two branches with the type checker's blessing.

**Go -- choices as compile-checked identity values.**

```go
var ViaEmail = sc.Choice("email", "deliver the notification as an email message",
    sc.StringFlag("subject", "subject line of the message", sc.Required()),
)

sc.ChoiceFlag("via", "delivery channel", sc.Required(), sc.Short("v"), ViaEmail, ViaSMS, ViaWebhook)

via := sc.GetElected(kwargs, "via")
line := sc.Match(via,
    sc.When(ViaEmail, func(f sc.Fields) string { return sc.Get[string](f, "subject") }),
    sc.When(ViaSMS, func(f sc.Fields) string { return sc.Get[string](f, "phone_number") }),
    sc.When(ViaWebhook, func(f sc.Fields) string { return sc.Get[string](f, "url") }),
)
```

- `Choice(name, help, flags...)` returns a **value with identity**, referenced by both the
  declaration and every handler that switches on it: `e.Is(ViaEmail)` and `When(ViaEmail, ...)` are
  compile-checked references, so a typo does not compile and a renamed choice breaks every site
  that names it. This is the package-level-token idiom Go already uses, extended to something that
  carries a payload.
- `MemberChoiceFlag(name, help, opts...)` with `MemberChoice(memberFlag, help, scope...)` is the
  member-spelled twin. It is a **twin constructor rather than an option**, so the spelling is one
  declaration instead of two that must agree.
- delivery is `*Elected` -- the elected `*ChoiceDecl` plus `Fields` -- and `Match` is **exhaustive
  against the declaration**: it compares the cases to the selector's choice list and panics naming
  what is missing. Go has no sealed union, so the check is at dispatch rather than at compile time;
  it cannot be defeated by a typo (cases are references) and it cannot go stale (adding a choice
  breaks every `Match` that omits it, on the first call). §17's accepted-ceiling reading applies:
  this is a language ceiling, and the sibling that does better at compile time is not a reason to
  weaken either.
- **`FlagOption` becomes an interface** (ruling S12):
  ```go
  type FlagOption interface{ applyFlag(*Flag) }
  type flagOptFunc func(*Flag)
  func (fn flagOptFunc) applyFlag(f *Flag) { fn(f) }
  ```
  A func type cannot also be a struct carrying a name, a help string, a flag slice and an identity,
  and identity is precisely what removes stringly-typed switches from handler code. Every
  constructor's **signature is unchanged** (`func Required() FlagOption` still compiles at every
  call site); the only caller shape that breaks is a hand-written `strictcli.FlagOption` func
  literal, which can reach only `Flag`'s exported fields, can therefore not declare presence, and
  therefore already fails registration today (§23.2). Under the 0.x no-compat rule that is a
  delete, not a shim.
- `choices` stays **unexported** on `Flag`, so a struct literal cannot be a selector at all --
  §23.2's `presenceBits` guarantee, extended to the new construct.

**TypeScript -- the keyed map and the derived union.**

```ts
via: choiceFlag("via", {
    email: choice({ help: "deliver as an email message", flags: {
        subject: flag("subject", t.str, { help: "subject line", presence: "required" }),
    }}),
    sms: choice({ help: "deliver as a text message", flags: { /* ... */ } }),
}, { help: "delivery channel", short: "v", presence: "required" }),
```

- the choice map sits **where a carrier sits**: `flag(name, carrier, opts)` says "this flag's type
  is `t.str`", and `choiceFlag(name, choices, opts)` says "this flag's type is this set of choices"
  -- for a selector, the choices **are** the type.
- object-literal keys are literal types by default, so the delivered value is an **exact
  discriminated union** with no annotation anywhere; `switch (args.via.choice)` narrows, and
  `assertNever` in the default branch is checked by the compiler. A **computed** choice key would
  silently degrade the tag to `string` and make `assertNever` accept anything, so the choice map is
  constrained to literal keys and a computed one is a compile error naming itself.
- `memberChoiceFlag(...)` is the member-spelled twin factory (the `defineReadOnlyCommand` /
  `defineMutatingCommand` precedent), so the spelling is the factory's name and there is no option
  to forget. `choice({help, value, flags})` declares a member payload.
- presence stays a discriminated union on `presence`, and a selector's `default` is typed
  `keyof C & string`, so a default naming a choice that does not exist is a **compile** error
  before it is a registration error.
- this is the structural fix for `infer.ts`'s remaining unsoundness: a scope's flags are
  unreachable except through the tag that proves the scope was elected, so the handler-args type
  cannot lie about them. §23.2 fixed the mutex-member case by declaration; this makes the failure
  mode inexpressible.

**The value-flag record**, per §24.2, in the same three idioms:

| | spelling |
|---|---|
| Python | `choices=[Choice("head", help="push only the current HEAD branch"), Choice("tags")]` -- a frozen dataclass, `value` positional, `help` keyword-only and optional |
| Go | `Choices(Ch("head", "push only the current HEAD branch"), Ch("tags", ""))` -- `func Ch(value interface{}, help string) ChoiceValue`, and `Choices(vals ...ChoiceValue) FlagOption` |
| TypeScript | `choices: [{ value: "head", help: "push only the current HEAD branch" }, { value: "tags" }]` |

Go spells "no help" as the empty string because it has no optional parameters, and the spelling
cannot be mistaken for anything else: an empty help string is refused everywhere it is mandatory, so
it has no second meaning to destroy. Python's `Choice` and the selector's `@choice` are case
twins naming **different** constructs, which the rest of the framework's `flag`/`Flag`,
`arg`/`Arg` pairs do not do -- the cost is accepted, and it is contained by a Python-only
registration error that names the confusion outright when a choice class reaches `choices=`
(§12.13's `errChoicesEntryIsChoiceClass`), rather than by inventing a third noun.

### 24.13 Multi-elect is deferred, and the rules are written so it can arrive

Any-of (`--via email --via sms`) is **not** in this round. It is recorded as an extension, not a
rejection, and one registration rule is already written for it: §24.7's collision rules are stated
against **simultaneously electable scopes** rather than against siblings, precisely so that adopting
multi-elect narrows an existing rule instead of contradicting one.

What it would force, recorded so a later round starts from the analysis rather than from scratch:
sibling name reuse becomes illegal (two live scopes make the token genuinely ambiguous, so the same
declaration is legal at one cardinality and illegal at the other); delivery stops being one tagged
value and becomes a sequence of them; presence gets murky, because `optional` would have to mean
either absence or an empty sequence and §23 forbids the silent empty collection; a required sub-flag
would need a spelling for *which* election it belongs to, which does not exist; and duplicate
election needs the repeatable/unique vocabulary the framework already has -- which is the first
thing to reconcile, since inventing a second spelling for repetition would be a design error.

### 24.14 What the constraint system becomes

> **The exactly-one family leaves the constraint system entirely.** Every exactly-one shape in the
> fleet is a selector -- member-spelled where the alternatives are their own flags, token-spelled
> where they are values of one flag -- and there is no `MutexGroup`, no `ExactlyOne` constructor and
> no cardinality parameter that could reintroduce one.
>
> What the (still unbuilt) constraint round keeps is **pure co-occurrence**: **at-least-one** and
> **all-or-none**, with by-name members, operands generalized to flags, positional args and other
> named constraints, the declared election vocabulary on each member, and first-class rendering and
> encoding on every surface. There is still **no at-most-one**, at any cardinality, ever (B2).
>
> Two items of that round's plan are **not** deferred but **superseded**: the per-choice help that
> bool-only-group dissolution depended on is §24.2's record, and the dissolution itself is this
> construct. A later round must not rebuild either.
>
> The reason exactly-one leaves is that it was never a constraint over independent flags. It is a
> single decision with alternatives, and modelling it as a rule *about* flags is what produced the
> present-but-false hole, the hand-written "nothing was chosen" guards, the placeholder bools that
> existed only because a group could not reference a declared flag, and a type surface that said
> "four independent booleans" where the intent said "one of four".

### 24.15 What this round does not touch

Stated so the boundary is a decision rather than an omission:

- **The dumped schema's selector encoding**, which the schema-v2 amendment authors against §24.11's
  requirements.
- **The surviving constraint families**, which are the constraint round's (§24.14).
- **The update-command construct** -- the mutating-default ban, `update_of=`, `write_mode=` and the
  `--unset-<prop>` vocabulary -- which is a third round. This construct makes one of its shapes
  expressible (a property whose legality depends on a selection) and does not use it.
- **`ConfigField` and config-file layout.** A config file is hierarchical and a scoped flag has a
  natural nested home in it; this round consults config for a scoped flag only through §24.6's
  conditional binding, using the flat key the flag already has, and pins no nested config spelling.
- **`Requires` / `Implies` semantics**, which are unchanged at root scope; this round only refuses
  them a scoped operand (§24.8).
- **Consumer migration**, which is the campaign's own pass: every mutex group, every choices flag,
  and the handler code -- the unreachable mutex branches, the "nothing was chosen" guards, the
  "required exactly when user-facing" checks -- that this construct deletes.

---

## 25. The schema format, version 2

Added 2026-08-14 (schema-v2 round, §18.16). This is the third phase of the declaration-regime
campaign, and it is the **normative record of the whole v2 format**: everything `--dump-schema`
writes, how it is spelled, in what order, and in what bytes. §13 keeps pinning which command-entry
facts exist; this section pins the format they are published in, and the two boxes at the end of §13
mark exactly where v1's text stops applying.

The round implements ruling **S17** of the campaign's third-round decisions, together with the two
strictcli todos S17 folds into it (`todo/schema-v2-single-migration.md`,
`todo/schema-dump-canonical-encoding.md`), and it authors the selector encoding §24.11 deliberately
left to it.

### 25.1 One version, one migration

`schema_version` becomes **`2`**, emitted at both existing sites in every implementation -- the
top-level key and the copy inside the `defaults` block. There is no intermediate version and no
per-change bump.

**What the single version covers**, collapsed per the fleet's collapse-multi-pass rule:

| Strand | Where it came from |
|---|---|
| Real JSON Schema fragments, the arity rule, unified compound args, the 2^53 refusal, the selector encoding | S17 |
| Canonical serialization: one spelling per construct, declared key order, omit-empty everywhere | `schema-v2-single-migration.md`, problem 1 |
| Behavioral completeness: the config keys, `flag_sets`, `prefixed`, the rewritten `defaults` block, the phantom key | `schema-v2-single-migration.md`, problem 2 |
| The byte canon: escaping, separators, numbers, trailing newline | `schema-dump-canonical-encoding.md` |

**The globals redesign is not part of v2**, and this is a correction to the schema-v2 todo's own
premise. That todo listed three in-flight schema-format changes and named the globals redesign as
the third, possibly forcing a version bump on its own. It has since **shipped**: its todo sits in
`todo/.done/globals-redesign-design-a.md`, and the schema surface it named is on disk in all three
serializers today -- command-level `effect`, `consequential`, the dry-run pair, `grants`,
`forwarding` and app-level `proc_observe_allowlist`, all pinned by §13 and all emitted at
`schema_version: 1`. v2 therefore collapses **two** items, not three, and carries no globals work.

**Why one version rather than three.** Each bump ripples through three implementations, the
conformance corpus, the case schema, the parity checker and every consumer that reads a dumped
schema. Three bumps pay that cost three times and leave two intermediate formats that nothing will
ever read again. The rejected alternatives are recorded with the todo's reasons: three separate
bumps (tripled cost), and canonicalizing without extending (the blind spots become permanent
doctrine).

### 25.2 `value_schema`: a real fragment from a closed subset

**Every flag entry and every arg entry carries a `value_schema`** -- a JSON Schema fragment
describing the shape of the value the declaration delivers. It replaces the v1 `type` key, which
had three spellings for one fact:

| Implementation | v1 spelling of a `list[str]` flag |
|---|---|
| Python | `"type": {"type": "array", "items": {"type": "str"}}` -- JSON-Schema-shaped, but with strictcli's type names inside it |
| Go | `"type": "list[str]"` |
| TypeScript | `"type": "list[str]"` (and `"dict[str,str]"`, where Go writes `"dict[str]"`) |

Python's form was already most of the way there and wrong in the one way that stopped it being a
JSON Schema: `"str"` is not a JSON Schema type name. v2 finishes the job.

**The subset is closed at four keywords** -- `type`, `items`, `additionalProperties`, `enum` -- and
the type names are **JSON Schema's**: `string`, `boolean`, `integer`, `number`, `array`, `object`.
Nothing else may appear in a fragment. The subset is a strict subset of §19.5's declared-payload
subset, which is what makes §25.12's validation possible at all.

**The fragment table.** This is the authority; a carrier not in it has no fragment because it cannot
be declared.

| Carrier | `value_schema` |
|---|---|
| `str` scalar | `{"type": "string"}` |
| `bool` scalar | `{"type": "boolean"}` |
| `int` scalar | `{"type": "integer"}` |
| `float` scalar | `{"type": "number"}` |
| `list[T]` flag, and a repeatable scalar `T` flag | `{"type": "array", "items": {"type": "<T>"}}` |
| `dict[str, T]` flag | `{"type": "object", "additionalProperties": {"type": "<T>"}}` |
| variadic arg of element type `T`, in either spelling | `{"type": "array", "items": {"type": "<T>"}}` |
| any scalar carrier with `choices` | `{"type": "<T>", "enum": [<values>]}` |
| any array-shaped carrier with `choices` | `{"type": "array", "items": {"type": "<T>", "enum": [<values>]}}` |
| a config field (always scalar) | the matching scalar row |
| a **selector** flag | **none** -- the key is absent (§25.6) |

`<T>` is always the JSON Schema name of the element type, never strictcli's.

**Keys inside a fragment are emitted in the order `type`, `items`, `additionalProperties`, `enum`**,
which covers every row above without a second rule.

**A dict's keys are `string` structurally, in every implementation, and the fragment says so by
having nothing to say.** Python refuses any `dict[K, V]` whose `K` is not `str` at registration
(`dict key type must be str`); Go's dict carriers are `TypeDictStr` / `TypeDictInt` /
`TypeDictFloat`, whose name refers to the **value** type and whose key type is not a parameter at
all; TypeScript's dict carriers are `dict[str,str]` / `dict[str,int]` / `dict[str,float]`, the only
three that exist. A JSON object's keys are strings by definition, so `additionalProperties` carrying
the value type is a complete description -- there is no `propertyNames` in the subset and none is
needed.

**An optional flag emits the plain type. There is no `null` in any fragment**, and no type list.
Presence is the sole authority on absence (§23), and a fragment that added `null` would be a second
statement about the same fact -- the exact erasure-and-duplication pair §13's presence box ended.
The fragment describes the shape of a value when there is one; whether there is one is `presence`'s
question, and the reader that wants both reads both keys.

### 25.3 Arity is value shape

**`repeatable` is deleted from the flag entry.** A repeatable scalar flag delivers a list, so its
`value_schema` is the array fragment -- identical to the one a `list[T]` carrier produces. The two
declaration spellings converge on one published shape, which is what the ruling means by arity being
a property of the **value** rather than of the spelling.

This deletes the only remaining normalization layer in the parity checker.
`conformance/check_schema_parity.py`'s `_canonicalize_repeatable` existed precisely because Python
and Go published `{type: "T", repeatable: true, default: []}` where TypeScript published
`{type: "list[T]"}`; it rewrote one into the other before comparing, and its call site in
`_normalize_schema` is deleted with it. After v2, `_normalize_schema` removes `project_id` and
nothing else, and the comparison becomes **byte equality** (§25.8).

A normalization layer is not a neutral convenience: every rule in it is a place where a real
divergence can be absorbed as serialization noise. The presence round found one such erasure
already; this round removes the machinery that could hide the next.

**`variadic` survives on the arg entry**, and the asymmetry with `repeatable` is deliberate.
`repeatable` restated a value shape two other spellings also produced; `variadic` names a
**token-consumption rule** -- this arg takes every remaining positional token, and only the last arg
may -- which the value shape implies today only because list-typed args are required to be variadic.
The key that a consumer needs to render `<files>...` in a usage line stays.

### 25.4 Compound args, unified

The three implementations disagreed about how a positional arg that collects a typed list is
spelled, and the ruling's answer is to **unify rather than ban**. The published fragment is the
array row for every such arg, in every implementation, whichever spelling declared it. What each
language must add:

- **TypeScript gains `list[T]` variadic args.** Today `arg(...)` refuses a list carrier outright
  (`variadic args take a scalar element type, not a list type`) and requires the element carrier
  plus `variadic: true`. That refusal is deleted: both spellings register, both deliver the same
  `Out[]`, and both publish the same fragment. The element-carrier spelling stays legal and stays
  the idiomatic one -- this widens the surface, it does not replace it.
- **Go's `ArgType` validation is already on disk**, and the ruling's clause names work that exists:
  `NewArg` refuses a list type on a non-variadic arg, refuses a non-scalar list item type, refuses
  a dict type outright, and closes the scalar set. Verified rather than assumed; nothing is added to
  Go here except the fragment itself, plus the deletion below.
- **Go must delete `errArgChoicesIncompatibleListType`.** A Go variadic arg declared with a scalar
  type may carry `ArgChoices`; the same arg declared with the list-typed spelling may not. Once the
  two spellings are one declaration with one published shape, a ban that fires on one of them and
  not the other is two rules for one fact -- item 149's rule applies, and the template is deleted
  rather than reworded. Python and TypeScript already accept choices on both.
- **Python needs no registration change**; its list-typed arg already requires `variadic=True` and
  already restricts item types to the non-bool scalars.

Dict-typed args stay refused everywhere, unchanged. That refusal is not a spelling divergence: no
implementation has ever accepted one.

### 25.5 Choices: the enum in the fragment, the records in the sibling key

A value flag's `choices=` declaration now produces **two** keys, and each carries the half it is
good at:

- **`value_schema`** carries the values as an `enum`, in declaration order, **inside `items`** for
  an array-shaped carrier and at the fragment root for a scalar one (§25.2's last two rows). This is
  the machine-readable half: a validator can use it as-is.
- **`choices`** carries the value-plus-help records item 164 made the only entry spelling. This is
  the human-readable half, and JSON Schema has no vocabulary for it.

The sibling key **keeps the name `choices`** -- it is the same fact under the same name it has always
had, with the shape the record ruling gives it:

```json
"choices": [
  {"value": "head", "help": "the current commit only"},
  {"value": "branches"}
]
```

- entries in **declaration order**, one per declared choice;
- `value` is the declared value, emitted with its own type (a string, an integer or a float token
  per §25.8) -- never stringified;
- `help` is **omitted when the entry declares none**. Go spells "no help" as `""` for lack of
  optional parameters (item 164), and an empty string and an absent one must not produce different
  bytes for the same declaration, so the empty string is omitted rather than emitted.

A `bool` flag never has choices, and a `dict` flag is refused them at registration in every
implementation, so the array row applies to list carriers, repeatable scalars and variadic args
only.

### 25.6 The selector encoding

§24.11 stated the requirement and left the encoding to this round: the dump must carry the nested
choices and scopes, each choice's help, each scoped entry's `presence` and `default` on §13's terms,
and the spelling -- and a dump that flattens a selector away is an illegal intermediate state, not a
tolerable one.

**A selector flag has no `value_schema`, and its absence is the declaration.** A selector's value is
a **variant** -- one tagged record chosen from several, each with a different set of fields -- and
the closed four-keyword subset cannot express a variant. It could only be expressed by opening the
subset to `oneOf`, which is the door the closed subset was built to shut (§24.11 records that
`oneOf` in the *MCP tool schema* is a future upgrade behind a measurement; the fragment subset is a
separate closure and this round does not open it either). Publishing a **wrong** fragment -- the
selector's own token type, say -- would be worse than publishing none: a reader would validate
against it and be told a record is invalid.

So the selector entry carries a framework-native encoding **beside** the fragments its scopes'
entries carry, under two keys:

```json
{
  "name": "via",
  "help": "delivery channel",
  "short": "v",
  "presence": "required",
  "choices": [
    {
      "name": "email",
      "help": "deliver the notification as an email message",
      "flags": [
        {"name": "subject", "help": "subject line of the message",
         "value_schema": {"type": "string"}, "presence": "required"},
        {"name": "recipient", "help": "destination email address",
         "value_schema": {"type": "string"}, "presence": "required"}
      ]
    },
    {"name": "webhook", "help": "post the notification to a URL",
     "flags": [
       {"name": "retries", "help": "delivery attempts before giving up",
        "value_schema": {"type": "integer"}, "presence": "default", "default": 3}
     ]}
  ],
  "elect_by": "selector-token"
}
```

- **`choices`** is an array of choice objects in declaration order. A choice object's keys, in
  order: `name`, `help` (mandatory on a choice, so always emitted), `flags` (omitted when the scope
  is empty).
- **each scoped entry is a full flag entry**, with its own `value_schema`, `presence`, `default` and
  everything else this section pins. That is what makes the encoding satisfy §24.11 rather than
  merely gesture at it, and it is what makes recursion free: a **nested selector** is an entry
  inside a `flags` array carrying its own `choices` and `elect_by`, to any depth.
- **`elect_by`** marks the spelling, with §24.12's own two-value vocabulary: `"selector-token"` or
  `"member-flags"`. The dump reuses the strings the contract already pins rather than minting a
  second pair of names for one fact; Go and TypeScript spell the declaration as twin constructors
  rather than a keyword, but the *fact* the dump publishes is the same one Python's keyword names.
- **the presence of `elect_by` is the discriminator.** An entry with `elect_by` is a selector: it has
  no `value_schema`, and its `choices` entries are choice objects. An entry without it is an ordinary
  flag: it has a `value_schema`, and its `choices` entries (if any) are §25.5's value records. A
  reader never has to guess which shape it is holding.
- **a member-spelled choice's payload** appears as the first entry of that choice's `flags` array,
  under the reserved name `value`, with `"presence": "required"` -- the payload is supplied by
  electing the member (§24.12), and required-once-elected is exactly what the member flag's own
  presence means (item 161). This mirrors the delivery record's flat map `{"choice": ..., <fields>}`
  (item 169), where `value` sits beside the scoped fields under the same reserved name. A
  payload-less member has no `value` entry.
- **a selector's `default`** is published in that same flat map form: `{"choice": "<name>", "<field>":
  <value>, ...}`, the choice's name under the reserved key `choice` followed by each field that has
  a value in the default selection, in declaration order. A field with no value is omitted, which is
  unambiguous because `null` is not a declarable default anywhere in the framework (§12.12's
  redirect). This is the one encoding that spans item 167's two mechanisms: Python's default is a
  choice instance whose fields may carry values, Go's and TypeScript's names a choice whose scope
  can only be complete, and the flat map publishes both without either language needing the other's
  mechanism.

**A `selector` wrapper key was considered and rejected.** Nesting `{elect_by, choices}` under one
`selector` key would keep the `choices` key monomorphic and make the missing `value_schema` visually
obvious. It was rejected because it renames a fact that already has a name -- the alternatives a
flag offers are its choices in both constructs, and §24.2's whole point is that the two constructs
are one machinery -- and because the discriminator it would provide is one `elect_by` already
provides. Recorded because a future reader will have the same idea.

### 25.7 Config fields, check entries, and the constraint catalogue

**Config-field entries move to fragments.** The v1 `type` key (Python `cf.type.__name__`, Go
`flagTypeName[cf.Type]`, TypeScript `cf.schema` -- three spellings again) becomes `value_schema`,
carrying the matching scalar row from §25.2's table. Config fields are **scalar-only** in all three
implementations, verified: Python refuses anything but `str`/`bool`/`int`/`float`, Go's
`ConfigField` takes a scalar `FlagType`, TypeScript's `ConfigFieldSpec` takes a `ScalarSchema`
carrier. No config field can produce an array or object fragment today, and a fragment that could
would come from a declaration surface this round does not add.

The config-field entry's **`required` key stays**. It is not §23's presence declaration wearing
another name: a config field has no CLI surface, no three-way declaration and no `presence` key, and
`required` there means "the config file must contain it". The presence round deliberately did not
reach config fields, and this round does not either.

**Check entries carry no value shape, so nothing converts.** Verified against all three serializers:
a check entry is `tags`, `severity`, `fast`, `pure`, `needs_network`, `depends_on` and an optional
`scope` -- no key describes a value's type, and `severity`'s two-value vocabulary is a closed enum
of the framework's own, not a declared payload shape. What v2 does reach in the `checks` block is
its **purity**, which is a real defect:

> **The dumped `checks` block must be a function of the declaration alone.** TypeScript's serializer
> skips provider-sourced names explicitly (`app.checks.providerSourcedNames`); Python's and Go's
> iterate the whole registry (`app._check_defs`, `app.checkDefs`), which contains only TOML-declared
> checks *until a provider materializes into it*. Both implementations' own comments state that
> provider-sourced checks are excluded because providers materialize lazily per-cwd; the code does
> not enforce it. A dump taken after a check run in the same process therefore differs from a dump
> taken before it, in two of three implementations. v2 makes the exclusion structural in all three:
> the serializer filters provider-sourced names by name, as TypeScript already does.

**The constraint catalogue** is closed, and `mutex` is gone with `MutexGroup` (item 178):

| `type` | Keys, in order |
|---|---|
| `co_required` | `type`, `flags` |
| `requires` | `type`, `flag`, `depends_on` |
| `implies` | `type`, `flag`, `implies`, `value` |

The todo listed "constraint subtypes" among the `defaults` block's gaps. They are closed **here**
rather than there, because the `defaults` block is defined as the map of what an omitted key means
and a subtype catalogue is not an omission baseline. `conformance/schema.json`'s `$defs` carries the
same three and drops `$defs/mutex_group`.

### 25.8 The byte canon

The committed `.strictcli/schema.json` must be **dumper-independent**: a repository whose file is
written sometimes by a Go binary and sometimes by a Python one must see a diff exactly when
something changed. The float canon (SCF) is the precedent -- one form, defined once, implemented
three times, enforced by a conformance check -- and this extends it from one value type to the whole
document.

**Numbers.**

- Every float is written in the **strictcli canonical float form** already owned by the repo
  (`formatFloatCanonical` in Go's `float.go`, its Python and TypeScript twins, and the vectors at
  `conformance/float_vectors.json`).
- **Go's schema writer currently bypasses Go's own formatter**, and this is the concrete defect the
  ruling names. `writeSchema` marshals the whole document with `encoding/json`'s
  `json.MarshalIndent`, so every float in a dumped Go schema is `encoding/json`'s rendering, not
  SCF -- Go owns the canonical formatter and does not use it where the bytes are committed.
  TypeScript's writer already routes numbers through `formatFloatCanonical` (which is why it is a
  hand-written writer at all), and Python's `json.dumps` renders floats through `repr`, which
  coincides with SCF.
- Integers are bare integer tokens: no decimal point, no exponent, no separators. TypeScript's
  writer already emits `bigint` this way; the type-level distinction it needs to tell an integer
  from a float is a TypeScript concern the other two do not have.

**Escaping.** Escape exactly what JSON mandates and emit everything else literally -- the same
sentence §19.5 already pins for one string, applied to the whole document:

- `"` and `\` are escaped; control characters below U+0020 use JSON's short escapes
  (`\b`, `\f`, `\n`, `\r`, `\t`) where one exists and `\u00XX` otherwise;
- **non-ASCII is never escaped**: raw UTF-8, no `\uXXXX`. Python's writer must pass
  `ensure_ascii=False`, which it does not today;
- **HTML-significant characters are never escaped**: `<`, `>` and `&` are literal. Go's writer must
  disable `encoding/json`'s HTML escaping, which is on by default and is why a Go-written schema
  and a Python-written one churn against each other today;
- `/` is never escaped;
- a lone surrogate -- reachable only from a TypeScript string literal -- is escaped as `\uDXXX`.
  It is the one escape not mandated by the character itself, and the alternative is emitting invalid
  UTF-8.

**Layout.** Two-space indent; one member or element per line; `": "` between a key and its value;
`,` then a newline between siblings; empty containers as `{}` and `[]` on a single line; **exactly
one trailing newline** at end of file. This is `json.dumps(..., indent=2)`'s shape, which
TypeScript's writer already reproduces byte-for-byte and which Go's must now produce without a map
marshal.

**After v2, `schema-parity` compares bytes.** The structural comparator's tolerance and the
normalization layer are deleted, and the conformance corpus gains byte-identical-dump cases over a
shared fixture app on all three targets. The committed artifact becomes readable in a diff, fleet-
wide, and a serialization change can no longer hide inside a structural comparison.

### 25.9 Canonical key order

Object keys are emitted in a **declared order**, identical in all three implementations. No
implementation may sort them at serialization time; Go's map marshal (which sorts, and is why a
Go-emitted schema starts with `commands` while a Python-emitted one starts with `schema_version`)
is replaced by an ordered writer.

**The order is derived from Python's insertion order**, which is the format's dominant serializer:
TypeScript's writer already documents that it follows Python's key order deliberately, and Go pins
content rather than order, so Python is the only one of the three that has ever expressed an order
to follow. Two deviations from it are authored here and named as such: the value key moves to a
uniform position across the flag and arg entries, and the env-related keys are grouped.

**Top level:** `schema_version`, `defaults`, `project_id`, `name`, `version`, `help`, `env_prefix`,
`config`, `config_format`, `config_path`, `config_conflict_mode`, `proc_observe_allowlist`,
`global_flags`, `commands`, `groups`, `deprecated`, `tag_contracts`, `checks`, `config_fields`,
`infra`.

`project_id` stays immediately after `defaults`, where Python and TypeScript already place it, so
that removing it leaves the CWD-free core dict byte-identical.

**Flag entry:** `name`, `help`, `value_schema`, `short`, `presence`, `default`, `env`,
`env_separator`, `prefixed`, `choices`, `elect_by`, `unique`, `conflict_mode`, `negatable`.

**Arg entry:** `name`, `help`, `value_schema`, `presence`, `default`, `variadic`, `choices`.

**Choice object** (selector): `name`, `help`, `flags`. **Choice record** (value flag): `value`,
`help`.

**Command entry:** `name`, `help`, `effect`, `consequential`, `dry_run_supported`,
`dry_run_unsupported_reason`, `payload_schema`, `owns_stdout`, `passthrough`, `flags`, `flag_sets`,
`args`, `tags`, `constraints`, `hidden`, `interactive`, `config_fields`, `grants`, `forwarding`.

**Group entry:** `name`, `help`, `commands`, `groups`, `deprecated`, `tags`, `hidden`.

**Config-field entry:** `value_schema`, `help`, `required`, `default`, `bound_commands`.
**Check entry:** `tags`, `severity`, `fast`, `pure`, `needs_network`, `depends_on`, `scope`.
**Grant entry:** `name`, `reason`, `kind`. **Infra block:** `roots`, `handshakes`, `connections`;
each root is `env_var`, `default` and each handshake or connection is `env_var`, `help`.
**Constraint entries:** §25.7's table.

**Keyed objects -- the two rules, and why there are two.** `commands`, `groups` and `config_fields`
are emitted in **declaration order**, which all three implementations retain (Go's `cmdOrder`,
`groupOrder`, `configFieldOrder`). `checks`, `deprecated` and `tag_contracts` are emitted **sorted
ascending by key**, because Go retains no declaration order for `deprecated` or `tagContracts` and
its `checkOrder` is already sorted -- a canon that cannot be produced from what an implementation
holds is not a canon. Every key in those three positions is ASCII by registration rule (check names
are `[a-z][a-z0-9-]*`, command and tag names use the flag-name charset), so byte order, code-point
order and UTF-16 order coincide and the three languages' native comparisons agree without anyone
having to specify a collation.

**Array order** is always declaration order: flags, args, choices, grants, constraints, config-field
`bound_commands`, `proc_observe_allowlist` prefixes. `tags` remain sorted, as they are today. The one
element whose position is pinned rather than declared is a **member-spelled choice's payload**, which
§25.6 places **first** in that choice's `flags` array; the scope's own declared flags follow it, in
their declaration order.

### 25.10 The `defaults` block, rewritten

The block's contract is unchanged: it is the machine-readable map of **what an omitted key means**.
v2 makes it true.

**Deleted:**

- `flag.hidden` -- the phantom. No implementation has a flag-level `hidden` field, and no serializer
  has ever emitted one. Verified in all three.
- `flag.default` and `arg.default` -- leftovers the presence round did not sweep. `default` has had
  no baseline since presence became the authority: it is emitted exactly when `presence` is
  `"default"`, and then always, `[]` and `{}` and `""` and `false` and `0` included. A `null`
  baseline for it now states something false.
- `flag.repeatable` -- the key is gone (§25.3).
- `arg.type` -- `value_schema` is always emitted, so there is nothing to reconstruct.

**The v2 block:**

```json
{
  "schema_version": 2,
  "app": {
    "env_prefix": null, "config": false, "config_format": "json", "config_path": null,
    "config_conflict_mode": "cli-wins", "proc_observe_allowlist": [], "global_flags": [],
    "commands": {}, "groups": {}, "deprecated": {}, "tag_contracts": {}, "checks": {},
    "config_fields": {}, "infra": {}
  },
  "flag": {
    "short": null, "env": null, "env_separator": null, "prefixed": true, "choices": null,
    "elect_by": null, "unique": false, "conflict_mode": null, "negatable": null
  },
  "arg": { "variadic": false, "choices": null },
  "command": {
    "consequential": false, "dry_run_supported": true, "dry_run_unsupported_reason": null,
    "payload_schema": null, "owns_stdout": false, "passthrough": false, "flags": [],
    "flag_sets": [], "args": [], "tags": [], "constraints": [], "hidden": false,
    "interactive": false, "config_fields": [], "grants": [], "forwarding": null
  },
  "group": { "commands": {}, "groups": {}, "deprecated": {}, "tags": [], "hidden": false },
  "config_field": { "default": null, "bound_commands": [] },
  "check": { "scope": null },
  "infra": { "roots": [], "handshakes": [], "connections": [] }
}
```

Keys with **no** baseline are absent from the block on purpose, and the list is exactly the set of
always-emitted facts: `name`, `help`, `version`, `schema_version`, `project_id`, `effect`,
`presence`, `value_schema` **on every entry that has one**, a choice's `name` and `help`, a config
field's `help` and `required`, and a check's six mandatory fields. `default` on a flag or arg is
absent for the reason above: its emission is governed by another key, not by a baseline.

**`value_schema` is the one entry in that list with a stated exception, and the exception is not an
omission at a baseline.** A **selector** flag carries no fragment at all, and its absence *is* the
declaration (§25.2's last table row, §25.6): a variant is inexpressible in the closed subset, the
presence of `elect_by` is what tells a reader which shape it is holding, and §25.12's check asserts
the absence rather than tolerating it. So the block gains no `value_schema` baseline -- a baseline
would have to say what an absent fragment means, and every answer it could give is false for the one
entry that omits the key, which is exactly the kind of statement this section's rewrite removes.

**Two omission rules this block does not yet carry**, named here rather than left to inference: a
selector choice object's `flags`, omitted when the scope is empty (§25.6), and a value-flag choice
record's `help`, omitted when the entry declares none (§25.5). Both are omit-at-baseline keys on
entities the block has no entry for, so the block is not yet the complete omission map its own
contract claims. The entity keys it would need are deliberately **not** invented here: naming them
is a spelling decision, and it is recorded as an open one (§18.17 item 204).

### 25.11 Behavioral completeness

The v1 dump was blind to declarations that change what a user's installation does. Each key below
closes one blind spot, and each is omitted at its baseline so that a departure from the framework's
behavior is exactly what makes a key appear.

| Key | Where | Emission |
|---|---|---|
| `config_format` | app | omitted when `"json"` |
| `config_path` | app | omitted when the app declares none (absence means the framework's XDG path for this app name and format) |
| `config_conflict_mode` | app | omitted when `"cli-wins"` |
| `prefixed` | flag | omitted when `true` |
| `flag_sets` | command | omitted when empty |

**`config_path` publishes the declaration, never the resolution.** A declared literal path is
emitted as declared -- the same treatment an infra root's `default` already gets, and honest for the
same reason: it is a committed source-level declaration, not a property of the dumping machine. A
`RelativeToRoot` declaration is emitted in the machine-stable marker shape §13 already pins
(`{"relative_to_root": {"env_var": ..., "parts": [...]}}`). The **resolved** absolute path is never
emitted, which costs Python an implementation change: `App.__post_init__` resolves a
`RelativeToRoot` config path eagerly and overwrites the declaration with the resolved string, so the
declared form must be retained alongside it for the serializer to publish.

**`flag_sets`** records the grouping v1 discarded: a command's flag-set members are merged into its
flag list, and nothing published says which set they came from. The key is an array of
`{"name": <set>, "flags": [<flag name>, ...]}` in declaration order; the member flags keep their
ordinary entries in `flags`, so the key adds a grouping without duplicating a declaration. All three
implementations retain the sets on the command (Python's `Command.flag_sets`, Go's `cmd.flagSets`,
TypeScript's `flagSets`).

**Per-flag `conflict_mode` becomes resolvable.** Its absence has always meant "inherit the app
default", and until v2 the app default was not published at all -- so the resolution was
unreachable from the dump. With `config_conflict_mode` emitted and `conflict_mode: null` documented
in the `defaults` block as inheritance, a consumer can compute the effective mode for every flag.

### 25.12 Fragment validity: one conformance check

Every fragment in every dump must be a valid document of the closed subset, and the check that
proves it is **Python-side and singular**: one check reading all three targets' dumps, not three
implementations each asserting about themselves.

- **Name and home:** `schema-fragments`, implemented in `conformance/check_schema_fragments.py`,
  registered as `@app.error_check("schema-fragments")` in `conformance/conformance_tool/__init__.py`
  with a `[checks.schema-fragments]` entry carrying `tags = ["pre-release", "conformance",
  "parity"]`, `severity = "error"`, `fast = false`, `pure = false`, `needs_network = false`,
  `depends_on = []`. It produces the three dumps the same way `check_schema_parity.py` does.
- **What it asserts**, over every `value_schema` in every dump -- flag entries, arg entries, global
  flags, config fields, and every scoped entry at every depth inside a selector's `choices`:
  1. the fragment validates under the **in-house payload-schema validator**
     (`_validate_payload_schema`, the registration-time validator §19.5 already owns), which is
     sound only because the fragment subset is a strict subset of the payload subset;
  2. it uses **only** the four keywords, which is narrower than the payload validator's own closure
     and is therefore the check's own assertion;
  3. every entry that must carry a fragment does, and a selector entry carries none -- the same
     shape of assertion the parity checker's `presence` walk added, for the same reason: an
     agreed-upon absence must never read as agreement.
- **The 2^53 registration rule is what makes strict validation sound.** The payload validator scans
  every `enum` member with the magnitude guard, so an int choice above 2^53 produces a fragment the
  framework's own validator **rejects** -- the framework would be emitting a document it refuses to
  accept. §12.14's registration error is the closure of that gap, and this check is what would
  discover it if the error were ever removed.

### 25.13 The MCP projections' shared defect

The same root-placement bug exists in all three MCP projections, and v2 fixes it in the same pass
because it is the identical rule the fragments now state:

> When a parameter's schema is an **array**, `enum` belongs **inside `items`**, describing the
> element. All three place it at the property root today (Python `_build_json_schema`, Go
> `buildJSONSchema`, TypeScript `buildJSONSchema`), which says the *array* must equal one of the
> choices.

Two arity defects in the same projections go with it, and they are not symmetric -- which is
precisely the erasure-shaped divergence the round exists to end:

- **Python's projection ignores repeatability.** A repeatable scalar flag projects as its scalar
  type; Go's projection reads `IsListType(f.Type) || f.Repeatable` and projects an array.
- **Python's projection ignores variadic args.** A variadic scalar arg projects as its scalar type;
  Go reads `a.IsVariadic` and TypeScript reads `a.opts.variadic` and both project an array.

After this round, all three MCP projections derive the parameter schema from the **same arity rule**
the `value_schema` fragment states, so a flag's tool-schema shape and its dumped shape cannot
disagree.

### 25.14 Consumer ordering, and the release boundary

**One release.** This amendment and §24 ship together, which §24.11 and item 179 already pinned; the
reason is stated there and is not restated here.

**rlsbl is fixed before any fleet re-dump.** rlsbl re-serializes a dumped schema at release time:
`_run_strictcli_schema_dump` runs the tool's `--dump-schema`, then `_patch_schema_version`
(`rlsbl/commands/release/validate.py`) reads the file with `json.load` and rewrites it whole with
`json.dumps(data, indent=2) + "\n"`. That is Python's encoder with `ensure_ascii=True`, applied to a
file a Go or TypeScript binary may have written -- so every non-ASCII character in a Go-dumped
schema is re-escaped, and the byte canon holds only until the release that publishes it. The fix is
to patch the version **without re-encoding the document**, and it must be released **before** the
fleet re-dumps, or the fleet re-dump writes files the next release will churn.

**selfdoc updates in the consumer window** -- between the strictcli release and the fleet re-dump.
Two concrete sites in `selfdoc/strictcli_support.py`: `_flag_table` renders `fl.get("type", "str")`,
which under v2 finds no `type` key and silently labels every flag `str`; and `_arg_table` renders
`ar.get("required", True)`, a key the **presence round already deleted**, so it labels every
positional arg required today. Both read `value_schema` and `presence` after the update. That second
one is a live defect now, not a v2 consequence -- it is named here because the same pass fixes it.

**Ordering, stated once:** strictcli releases v2; rlsbl's re-serializer fix releases; selfdoc's
reader updates; then the fleet re-dumps. A consumer that reads a dumped schema and has not been
updated reads a v1 file until its project re-dumps, which is what the version key is for.

### 25.15 What v2 does not do

Stated so the boundary is a decision rather than an omission:

- **No `oneOf`, and no fifth keyword.** The fragment subset stays at four. A selector's variant is
  encoded natively (§25.6) rather than by opening the subset, and the MCP tool schema's `oneOf`
  remains §24.11's recorded future upgrade behind a measurement of client handling.
- **No v1 compatibility path.** There is no dual-reader, no shim and no negotiated fallback: a
  reader sees `schema_version` and knows which format it holds. Pre-stable projects do not carry
  compatibility surfaces (and a v1 file stays readable as exactly what it is -- a v1 file).
- **No new declaration surface.** Every fact v2 publishes is a fact some implementation already
  holds; the round adds keys and one registration guard, never a new way to declare something. The
  one widening is TypeScript's list-carrier variadic arg (§25.4), which the unification ruling
  requires.
- **Nothing about `presence` or `default`.** The presence round settled both and this round
  republishes them unchanged.
- **No config-field or check declaration changes.** Config fields keep `required` and their scalar-
  only surface; check entries keep their six mandatory fields. Only their serialization moves.
