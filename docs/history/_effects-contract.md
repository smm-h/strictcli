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
| **Resource token** | An opaque string naming what an effect produces. Compared by string equality only. |
| **Grant** | A per-command, per-effect-kind authorization with a mandatory human reason. |
| **Guard v2** | The tightened handler-signature validation that no longer exempts `**kwargs` handlers. |
| **Declared forwarding** | The registration-time declaration that a handler deliberately accepts and forwards `**kwargs`. |

Two rules govern the whole regime and override any local convenience:

- **Fail closed.** If the framework cannot prove an operation is safe to preview, it stops with a
  precise error instead of guessing.
- **Zero inference.** The framework never infers classification, never infers whether an argument
  is a path, never canonicalizes a resource token, never evaluates user predicates. Everything is
  declared.

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

### 1.2 Per-language spelling

| Impl | Spelling |
|------|----------|
| Python | `effect="mutating"` keyword on `app.command(...)` / `group.command(...)` / the `Command` dataclass, sitting beside the existing `interactive` field (`python/strictcli/__init__.py`, `Command` dataclass, adjacent to `interactive: bool = False`). |
| Go | `WithEffect(EffectMutating)` / `WithEffect(EffectReadOnly)` -- a `CmdOption`, registered in `go/strictcli/strictcli.go` alongside `WithInteractive()`. Constants `EffectReadOnly` and `EffectMutating` are exported. |
| TypeScript | Twin factories `defineReadOnlyCommand(...)` and `defineMutatingCommand(...)` alongside the existing `defineCommand` (`typescript/src/factories.ts`). |

`defineCommand` is **removed** from the TS public surface (`typescript/src/index.ts` re-export
dropped, `typescript/src/describe.ts` descriptor renamed). Pre-stable projects get no
compatibility shim; the twin factories are the only mint. The two factories differ in the
`Context` type they narrow the handler's `ctx` parameter to (§2.4).

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

- `resource=` -- optional opaque resource token (§5). Plain string.
- `skip_if_current=` -- optional resource token; conditional-effect declaration (§5.2).
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

---

## 3. Dry mode and the would-do log

### 3.1 Trigger

Dry mode is entered when the framework-owned `--dry-run` flag (§7) is present. In dry mode:

- No effect is executed. Every effect is recorded in order.
- Mutating effects return `Unsettled` carriers (§4).
- Observes issued *before* the first recorded mutation return real values.
- Observes issued *after* the first recorded mutation return `Unsettled` carriers with the
  `«stale: ...»` brand form.
- On successful completion the framework writes the would-do log to **stdout** and exits with
  the handler's exit code.

`--dry-run` on a `read_only` command is accepted and produces a would-do log containing only
whatever observes and (framework-blessed) cache writes occurred; in practice usually an empty
body. It never errors.

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

Verb prefixes, one per method:

| Verb | Method | Detail |
|------|--------|--------|
| `run:` | `run` (mutating) | the argv, shell-free, space-joined |
| `spawn:` | `spawn` | the argv, shell-free, space-joined |
| `write:` | `write` | `<path> (<n> bytes)` |
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

Carriers forwarded into an effect render inline in the detail, in their brand form (§4.2).

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

---

## 4. Unsettled carriers

The type is named `Unsettled` in all three implementations.

### 4.1 When a carrier is produced

- Every mutating effect recorded in dry mode returns one.
- Every post-mutation observe in dry mode returns one.
- Nothing else ever produces one. Outside dry mode, and for pre-mutation observes, callers get
  real values.

### 4.2 Brand forms

Two, and only two:

| Form | Produced by |
|------|-------------|
| `«step N output»` | the carrier returned by recorded mutation number `N` |
| `«stale: <descr>»` | the carrier returned by a post-mutation observe; `<descr>` is the observe's short description (for `run`, the space-joined argv) |

(The guillemets are U+00AB and U+00BB.)

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
__len__  __iter__  __contains__  __getitem__  __getattr__
__int__  __float__  __index__  __str__  __format__  __bytes__
__add__  __radd__  __mod__  __rmod__  __call__
```

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

## 5. Resource tokens and conditional effects

### 5.1 Tokens

A resource token is a **plain string**. The framework:

- compares tokens by **string equality only** -- no normalization, no case folding, no path
  canonicalization, no prefix matching;
- attaches no meaning to a token's shape; `remote:origin/main` and `gh-release:v1.2.3` are just
  strings that happen to read well;
- never invents a token. An effect without `resource=` simply has none.

Declared on any effect as `resource=<token>`.

### 5.2 Conditional effects

`skip_if_current=<token>` declares "this effect is unnecessary if `<token>` is already current".

The framework maintains a per-run **current set**, initially empty:

- Executing (real mode) or recording (dry mode) an effect that declares `resource=T` adds `T` to
  the current set.
- An effect declaring `skip_if_current=T`:
  - **real mode** -- is skipped entirely if `T` is in the current set at the moment of the call;
    otherwise it executes normally.
  - **dry mode** -- is always recorded, and its log line carries the conditional suffix (§3.2).
    Dry mode never claims to know whether the branch will be taken.
- The current set is per-run and per-process. Nothing is persisted. Nothing crosses a spawn.

An effect may declare both `resource=` and `skip_if_current=`, and they may name the same token
(an idempotent self-guard).

The point of the mechanism is that idempotency branches move **out of handler `if` statements and
into effect declarations**, where the preview can see them. A handler that branches on an observe
in order to decide whether to mutate hits the truncation error (§3.3); a handler that declares
`skip_if_current=` gets a complete, honest preview.

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
issuing a non-matching `run` is a hard error (§12.4).

Per-language spelling: Python `App(proc_observe_allowlist=[...])`; Go
`WithProcObserveAllowlist([][]string{...})` as an `AppOption`; TypeScript
`createApp({ procObserveAllowlist: [...] })`. Emitted in the schema (§13).

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

The four flags are extracted by the position-aware pre-scan that already handles `--dump-schema`,
`--mcp`, `--config` and `--hermetic` (Python `App._pre_scan_reserved_flags`; Go's equivalent in
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
- `dry_run` -> `ctx.dry_run` (or `ctx.DryRun()`); behavior unchanged (list which checks would run
  without executing them).

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

It never fires for `read_only` commands, for passthrough commands (which are classified like any
other command but whose args are opaque), or on the `test()` / `call()` / `_invoke` / MCP paths
(§8.4).

### 8.2 The prompt

Written to **stderr**, without a trailing newline:

```
about to run mutating command '<name>'. Proceed? [y/N] 
```

(Note the single trailing space. `<name>` is the dotted command path.)

The answer is read from stdin, one line. After stripping the trailing newline, exactly `y` or `Y`
proceeds. Anything else -- including empty input, `yes`, `n`, or EOF -- declines. On decline the
framework writes `aborted` to stderr and exits `1`.

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
and a prompt there would hang the caller. `--dry-run` is likewise not reachable through them
(they bypass argv parsing entirely); a programmatic caller that wants a preview constructs the
run through the CLI path.

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

---

## 11. Bypass lint as check providers

Each implementation ships a **built-in check provider** registering one check:

| Field | Value |
|-------|-------|
| name | `effects-bypass` |
| tags | `["effects", "quality"]` |
| severity | `error` |
| fast | `true` |
| pure | `true` |
| needs_network | `false` |
| depends_on | `[]` |

The check statically analyses the consumer's own sources and fails on any direct process,
filesystem-mutation or network call reachable from a registered command handler that does not go
through `ctx.effects`. It is registered through the existing provider hook
(`App.register_check_provider` / `(*App).RegisterCheckProvider` / the TS provider module), the
same mechanism the built-in `cli-test-coverage` check already uses, so a TOML-less app still gets
a working check.

Analyser per language, all **regular dependencies** (no optional imports, no soft degradation):

| Impl | Analyser |
|------|----------|
| Python | stdlib `ast` |
| Go | stdlib `go/ast` + `go/parser` |
| TypeScript | the TypeScript compiler API -- `typescript` moves from `devDependencies` to `dependencies` in `typescript/package.json`. This is a published-surface change and gets its own changelog line. |

Additionally, the TS check flags the two accepted Proxy ceilings (§4.4): a bare truthiness test or
a `===` comparison against a value the analyser can trace to an effects-handle return. These are
the only things the runtime seal cannot catch, so lint is the sole line of defence and the check
must name them explicitly.

---

## 12. Message templates

New templates land **identically in all three implementations**, in the three catalog files that
`conformance/check_error_parity.py` extracts from:

- Python -- `python/strictcli/__init__.py` (inline `raise ValueError(...)` / `_ParseError(...)`
  strings; the extractor reads the source)
- Go -- `go/strictcli/errors.go` (an `err*` function per template)
- TypeScript -- `typescript/src/errors.ts` (an `err*` function per template, one-to-one with Go,
  under the same Go-source-file section headers the extractor keys on)

The structural model for a registration-time ban is the existing `force` triple:
`errFlagForceReserved` (Go `errors.go`, panicked from `validateFlagConfig` in
`go/strictcli/strictcli.go`), `errFlagForceReserved()` (TS `errors.ts`, thrown from
`validateFlagConfig` in `typescript/src/factories.ts`), and the inline `ValueError` in Python's
`Flag.__post_init__`. Every new registration-time template below follows that shape.

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

The conformance case schema (`conformance/schema.json`) mirrors these under `$defs/command` and
`$defs/app`, with `effect` added to `$defs/command`'s `required` list.

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
explicit-null keys are equivalent. It is an ordinary expect key: a case may combine it with
`stdout_equals` (asserting the rendered log) and with `exit_code`.

### 14.2 `$defs/effect_record`

```json
{
  "type": "object",
  "required": ["seq", "kind", "verb", "detail"],
  "additionalProperties": false,
  "properties": {
    "seq":             { "type": "integer" },
    "kind":            { "enum": ["proc_mutate", "proc_spawn", "file_write", "net_mutate", "cache_write"] },
    "verb":            { "enum": ["run", "spawn", "write", "mkdir", "remove", "rename", "chmod", "net", "cache"] },
    "detail":          { "type": "string" },
    "bytes":           { "type": "integer" },
    "resource":        { "type": "string" },
    "skip_if_current": { "type": "string" },
    "grant":           { "type": "string" },
    "recorded":        { "type": "boolean" }
  }
}
```

`detail` is the same string the would-do log renders after the verb (so forwarded carriers appear
in brand form). `bytes` is present only for `write`. `recorded` is `true` in dry mode and `false`
when the effect actually executed.

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
the ordered records for the most recent dispatch. It sits beside the existing test-only surfaces
(`test()`, `_last_sources`) and is excluded from the api-surface catalog the same way.

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
indexed by position so `forward_from` / `extract_from` can reference it.

### 14.5 Fixture app and parity checks

- `RICH_APP` in `conformance/check_api_surface.py` gains a classified command set (at least one
  `read_only`, one `mutating`, one with grants, one with declared forwarding) so the descriptor
  comparison exercises the new fields.
- `check_error_parity.py` gains the §12 templates. Every parse-time template needs a covering
  conformance case (the extractor enforces it); registration-time templates need a
  `SIGNATURE_STATUS` entry only where an implementation legitimately lacks the message (§10.3).
- The cross-process cases that would have exercised an env-mode token are **not written**: A9
  deleted that mechanism (§16). What remains is in-process spawn-record assertions -- a `spawn`
  effect appearing in `effects_equals` with `recorded: true`.

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
- **Go**: extraction is a runtime panic, not a compile error. Non-comparability is the only
  compile-time protection available.
- **Go**: no compile-time ctx narrowing exists; the twin-factory affordance is TS-only.
- **Go/TS**: guard v2 has no enforcement surface (§10.3).
- **The go-scope-adapter** stays parked; this contract does not touch it.

---

## 18. Spelling-level pins made while authoring

Everything in §§1-17 that the ratified pin list did not already spell out is enumerated here, so a
reviewer can see exactly what was decided at authoring time versus ratified upstream. All of these
are mechanical/spelling decisions forced by the ratified semantics; none of them changes a
ruling.

1. **Log line layout** -- `  <N>. <verb>: <detail>`: two-space indent, unpadded 1-based number,
   `. ` after the number, `: ` after the verb. The pin fixed "numbered verb-prefixed lines"
   without fixing the punctuation.
2. **Four additional verbs** -- `mkdir:`, `remove:`, `rename:`, `chmod:`. The pin named the verbs
   for the four kinds whose spelling was in question (`run:`, `write:`, `net:`, `spawn:`); the
   remaining four `FILE_WRITE` methods need verbs of their own, and reusing `write:` for
   `mkdir` would read as nonsense. The **kind** set is unchanged.
3. **Detail spelling per verb** -- byte count as `<path> (<n> bytes)`, rename as `<from> -> <to>`,
   chmod mode as leading-zero octal, `http` as `<METHOD> <url>`.
4. **Suffix ordering** -- grant suffix before conditional suffix when both apply.
5. **Observes are not logged.** The log is what would *change*.
6. **Reserved-flag delivery is on the Context, not in kwargs** (§7.2), with the concrete accessor
   names per language. Forced by guard v2 tightening in the same release and by `Context` needing
   the values for its own gating; recorded here because the pin said "delivery" without a site.
7. **The four reserved flags have no short forms**, and the ban covers long flag names at every
   level but not arg names or short names.
8. **`check --dry-run` is subsumed alongside `--verbose`** (§7.5) -- forced by the unconditional
   name ban, and Go's check command must gain the candidate-filter that Python and TS already
   have.
9. **`--quiet` + `--verbose` together is silently quiet**, not an error and not a mutex.
10. **Confirm answer grammar** -- exactly `y`/`Y` proceeds; everything else including EOF
    declines; decline prints `aborted` to stderr and exits 1.
11. **Programmatic dispatch behaves as if `--yes`** (§8.4) -- the only non-hanging option for
    `test`/`call`/MCP.
12. **Go's TTY check uses `os.Stdin.Stat()` + `os.ModeCharDevice`**, keeping the Go package
    zero-dependency.
13. **Python's `__repr__` is the single non-poisoned dunder**, and `__class__` stays intact so
    `isinstance` works at the forwarding boundary; `__str__` and `__format__` ARE poisoned
    (stringifying a carrier in handler code is extraction, not forwarding).
14. **Go's `Unsettled` is made non-comparable via a `[0]func()` field**; brand read through an
    unexported `brandForm()`.
15. **TS Proxy exemptions are exactly three** -- the internal brand symbol,
    `Symbol.toStringTag`, and the Node inspect symbol.
16. **Conditional-effect evaluation model** (§5.2) -- a per-run current set fed by `resource=`,
    consulted by `skip_if_current=`; real mode skips, dry mode always records with the suffix.
17. **Grant `kind` is drawn from the effect-kind enum** and must match the effect it is used on;
    grant names match `[a-z][a-z0-9-]*`.
18. **`proc_observe_allowlist` matching is element-wise argv-prefix string equality.**
19. **`CACHE_WRITE` is unreachable from application code** and its site list is closed at three
    (§9.2); the five `config` subcommands' classifications are pinned in the same section.
20. **Declared forwarding mirrors `Passthrough`'s registration shape** and carries a mandatory
    `reason`.
21. **The bypass check is named `effects-bypass`** with the tag/severity/fast/pure/network values
    in §11.
22. **Error-template function names** (§12) follow the existing `err*` catalog convention, one
    function per template in Go and TS.
23. **Schema emission rules** (§13) -- `effect` always emitted (no default to omit against);
    `grants`, `forwarding` and `proc_observe_allowlist` omitted when empty.
24. **`effects_equals` compares a structured effect log**, whose record shape is `$defs/
    effect_record` (§14.2), delivered through the `CONFORMANCE_EFFECT_LOG` file handoff (§14.3)
    modelled on the existing `CONFORMANCE_APP_DEF` pattern, read via a test-only
    `App.effect_log()` accessor.
25. **`handler_effects` is the harness vocabulary extension** (§14.4), with `forward_from` and
    `extract_from` as 1-based back-references and `extract_from` terminal.
