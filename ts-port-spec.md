# TypeScript port specification

Durable design constants for the strictcli TypeScript implementation. This file is the
committed home for decisions that must not live only in session memory.

Placement note: this file lives at the repo root, NOT in `docs/`, because selfdoc walks
`docs/` and treats every `.md` file there as a published docs-site page (see
`resolve_all_docs` in selfdoc: it os.walks the docs dir with no managed-file allowlist).
An internal port spec must not become a public docs page, so `docs/` is not safe for
unmanaged files in this repo.

## npm deprecation notice (approved text)

Versions <=0.30.1 were an npm wrapper that installed the Python package via pip. From 0.31.0, strictcli on npm is a native TypeScript implementation. Python users: install strictcli from PyPI instead.

## Naming registry

| Item | Name |
|------|------|
| Conformance target name | `typescript` |
| Conformance check name | `conformance-typescript` |
| rlsbl releasable | `ts-strictcli` |
| npm package | `strictcli` |
| First TS version | `0.31.0` |
| Directory | `typescript/` |
| License | MIT |

## TOML acceptance gate - the six TOML-1.1-only constructs the TS parser layer must reject

- backslash-e escape in basic strings
- backslash-x hex escapes in basic strings
- newlines inside inline tables
- trailing commas in inline tables
- times without seconds
- datetimes without seconds

## SCF float battery

The 15 canonical values and their expected formatted strings:

| Input value | Expected string |
|-------------|-----------------|
| 1.0 | `1.0` |
| -1.0 | `-1.0` |
| 0.5 | `0.5` |
| -0.0 | `-0.0` |
| 100.0 | `100.0` |
| 1e15 | `1000000000000000.0` |
| 1e16 | `10000000000000000.0` |
| 1e20 | `100000000000000000000.0` |
| 1e21 | `1e+21` |
| 1e-4 | `0.0001` |
| 1e-5 | `0.00001` |
| 1e-7 | `1e-7` |
| 0.1 | `0.1` |
| 9007199254740992 (2^53) | `9007199254740992.0` |
| 1.5e300 | `1.5e+300` |

## Type-machinery reference (from the verified spike)

Source: verified spike files `sol10.ts`, `sol10_danger.ts`, `sol10_errors.ts`,
`sol10_scale.ts` (Solution 10: nominally-branded composable carriers + flag/arg
factories where the schema string and the output type are computed by ONE generic,
so they cannot drift).

### Carrier pattern

Types are values ("carriers") that pair a phantom output type with a literal schema
string and the runtime parse function. A nominal brand (unique symbol) prevents
hand-forged object literals from masquerading as carriers.

```ts
type ScalarSchema = 'str' | 'bool' | 'int' | 'float';
type ElemSchema = 'str' | 'int' | 'float'; // no bool elements

declare const CarrierBrand: unique symbol;

interface Carrier<Out, S extends string> {
  readonly [CarrierBrand]: true;
  readonly _out?: Out;      // phantom output type
  readonly schema: S;       // wire/schema string, literal
  parse(raw: string): Out;  // runtime parse logic lives on the carrier
}

function mkScalar<Out, S extends ScalarSchema>(schema: S, parse: (r: string) => Out): Carrier<Out, S> {
  return { schema, parse } as unknown as Carrier<Out, S>;
}

const t = {
  str: mkScalar<string, 'str'>('str', (r) => r),
  bool: mkScalar<boolean, 'bool'>('bool', (r) => r === 'true' || r === '1' || r === 'yes'),
  int: mkScalar<bigint, 'int'>('int', (r) => BigInt(r)),
  float: mkScalar<number, 'float'>('float', (r) => Number(r)),
  // ONE generic each: Out and schema both derive from the element carrier's params.
  list<Out, S extends ElemSchema>(el: Carrier<Out, S>): Carrier<Out[], `list[${S}]`> { /* ... */ },
  dict<Out, S extends ElemSchema>(el: Carrier<Out, S>): Carrier<Map<string, Out>, `dict[str,${S}]`> { /* ... */ },
};
```

### Factory pattern (flag/arg) and inference machinery

Factories capture the literal flag name, the carrier's output type, the literal schema
string, and the exact options object type via `const` type parameters:

```ts
type FlagOpts<Out> = { help: string; required?: boolean; default?: Out; env?: string };

interface FlagDef<N extends string, Out, S extends string, O extends FlagOpts<Out>> {
  kind: 'flag'; name: N; schema: S; _out: Out; _opts: O;
}

function flag<const N extends string, Out, S extends string, const O extends FlagOpts<Out>>(
  name: N, type: Carrier<Out, S>, opts: O,
): FlagDef<N, Out, S, O>;

type ArgOpts = { help: string; required?: boolean; variadic?: boolean };
function arg<const N extends string, Out, S extends string, const O extends ArgOpts>(
  name: N, type: Carrier<Out, S>, opts: O,
): ArgDef<N, Out, S, O>;
```

Inference: dash-to-underscore key mapping via a recursive template-literal type
(`Underscore<'dry-run'> = 'dry_run'`); optionality computed per flag (a flag key is
optional iff scalar AND not required AND no default); required and optional keys are
extracted into two separate mapped types and intersected, then flattened:

```ts
type RequiredFlagKeys<F extends readonly AnyFlag[]> = {
  [K in F[number] as FlagIsOptional<K['schema'], K['_opts']> extends true
    ? never : Underscore<K['name']>]: NonNullable<K['_out']>;
};
type OptionalFlagKeys<F extends readonly AnyFlag[]> = {
  [K in F[number] as FlagIsOptional<K['schema'], K['_opts']> extends true
    ? Underscore<K['name']> : never]?: NonNullable<K['_out']>;
};
type Prettify<T> = { [K in keyof T]: T[K] } & {};
type InferHandlerArgs<F extends readonly AnyFlag[], A extends readonly AnyArg[]> = Prettify<
  RequiredFlagKeys<F> & OptionalFlagKeys<F> & RequiredArgKeys<A> & OptionalArgKeys<A>
>;
```

`command()` takes `const F extends readonly AnyFlag[], const A extends readonly AnyArg[]`
so array literals keep their per-element literal types without `as const`.

### Equals type-assertion technique

Exact type equality (distinguishing true optional keys `?:` from `| undefined`, and
catching excess/missing keys) is asserted with the conditional-generic-signature trick:

```ts
type Equals<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Assert<T extends true> = T;

type _T1 = Assert<Equals<BuildArgs, Expected>>;
// Negative control: assert that a deliberately wrong shape does NOT equal:
type _T2 = Assert<Equals<Equals<BuildArgs, WrongUndefined>, false>>;
```

### Canonical 5-member example command

```ts
const build = command('build', {
  help: 'Build the project',
  flags: [
    flag('dry-run', t.bool, { help: 'Dry run', default: true }),
    flag('count', t.int, { help: 'How many', required: true }),
    flag('tag', t.list(t.str), { help: 'Tags' }),
    flag('meta', t.dict(t.int), { help: 'Metadata' }),
  ],
  args: [arg('values', t.float, { help: 'Values', variadic: true })],
  handler: (args, ctx) => {
    const a: boolean = args.dry_run;
    const b: bigint = args.count;
    const c: string[] = args.tag;
    const d: Map<string, bigint> = args.meta;
    const e: number[] = args.values;
    return 0;
  },
});
```

Exact expected inferred handler-args type (verified with `Assert<Equals<...>>`):

```ts
type Expected = {
  dry_run: boolean;
  count: bigint;
  tag: string[];
  meta: Map<string, bigint>;
  values: number[];
};
```

### Verified facts

- **No `as const` needed for factory tuples.** With `const` type parameters on
  `flag()`/`arg()`/`command()`, literal flag names and options survive inference
  (`flag('my-flag', ...)` infers `{ my_flag: string }` without `as const`).
- **True optional-key modifiers** (`name?: string`, not `name: string | undefined`)
  are achieved via the required/optional block intersection above, proven by the
  Equals negative control against the `| undefined` shape.
- **Option-key typos are NOT caught statically** (e.g., `defalt:` instead of
  `default:` compiles). Runtime double-entry validation catches them.
- **`.map()`-built flag arrays silently widen.** Building flags dynamically
  (`names.map((n) => flag(n, t.str, {...}))`) collapses literal names and the
  inferred handler-args type degrades. Flag arrays must be written as literals.

Additional spike results retained for context: bool list elements are rejected at the
type level (`ElemSchema` excludes `bool`); wrong-typed defaults (e.g., `default: 5` on
an int flag whose Out is `bigint`) are compile errors; forged un-branded carriers are
rejected; the computed dict schema literal is `dict[str,int]` (no space).

## TS module layout

```
typescript/
  src/
    types.ts
    infer.ts
    factories.ts
    errors.ts
    values.ts
    float.ts
    atprefix.ts
    env.ts
    parse.ts
    routing.ts
    sources.ts
    infra.ts
    help.ts
    context.ts
    outcome.ts
    app.ts
    invoke.ts
    config.ts
    toml.ts
    schema.ts
    mcp.ts
    tool.ts
    describe.ts
    index.ts
    checks/
      framework.ts
      runner.ts
      cmd.ts
      provider.ts
      coverage.ts
      tagdsl.ts
  tests/   # mirrors src/
```

Layout addition (subphase 4.5): `sources.ts` holds the per-parse provenance
store (SourcedStore) mapping resolved flag names to their source labels
(`cli`/`env`/`config`/`default`/`implied`/`infra`), with the source-filtered
presence queries used by mutex and dependency evaluation.

Layout addition (subphase 5.6): `describe.ts` holds the dev-only public-surface
self-dump: a hand-maintained SURFACE registry (single source of truth for the
exported API, shape-aligned with conformance/describe_go/main.go's JSON output)
plus `describeSurface()`/`describeSurfaceJson()` and a bin-style main guard
(`node dist/describe.js`). It is deliberately NOT exported through index.ts
(dev tooling, not public API). tests/describe.test.ts enforces registry
accuracy in both directions: compile-time keyof equality assertions plus
runtime typeof/prototype/Object.keys checks (forward), and a parse of
src/index.ts asserting the registry universe EQUALS the index export set
(reverse). No other module diverged from the planned layout.

Layout addition (subphase 5.1): `infra.ts` holds the infrastructure env-var
machinery: the branded `relativeToRoot()` marker (`InfraRootPath`), tilde
expansion, marker resolution against the eagerly-resolved roots map,
registration-time marker validation (flag-scoped and command-scoped
messages), and the `buildInfraAccess` snapshot consumed by `Context`.
Root resolution itself stays in `app.ts` (the Go NewApp shape); handshake
vars are read live in `context.ts`.

## Curated example set for end-to-end byte-parity demos

Twelve scenarios drawn from the conformance suite. Each is an argv + expected-output
pair the TS implementation must reproduce byte-for-byte. Case names refer to
`conformance/cases/<file>.json`.

| # | Category | Case (file: name) | argv | Expected |
|---|----------|-------------------|------|----------|
| 1 | Help output | help.json: "help: app help shows version and commands" | `[]` | exit 0; stdout equals `myapp v3.0.0 -- my cool app\n\nCommands:\n  run     run something\n  test    run tests\n\nUse 'myapp <command> --help' for more information.` |
| 2 | Flag parse success | flags.json: "flags: str flag with space syntax" | `["cmd", "--target", "foo"]` | exit 0; stdout equals `target=foo` |
| 3 | Parse error with try-help trailer | errors.json: "errors: unknown flag" | `["cmd", "--unknown"]` | exit 1; stderr equals `error: unknown flag '--unknown'\ntry 'myapp cmd --help'` |
| 4 | Choices error | choices.json: "choices: invalid str choice rejected" | `["cmd", "--format", "xml"]` | exit 1; stderr equals `error: --format: invalid value 'xml', must be one of: text, json\ntry 'myapp cmd --help'` |
| 5 | Required-flag error | flags.json: "flags: required str flag missing produces error" | `["cmd"]` | exit 1; stderr equals `error: flag '--target' is required\ntry 'myapp cmd --help'` |
| 6 | Negation | flags.json: "flags: bool flag --no-X negation" | `["cmd", "--no-verbose"]` | exit 0; stdout equals `verbose=false` |
| 7 | Env resolution | env.json: "env: str flag from env var" | `["cmd"]` with env `MYAPP_TARGET=from-env` | exit 0; stdout equals `target=from-env` |
| 8 | Unknown command | basic.json: "basic: unknown command error" | `["deploy"]` | exit 1; stderr equals `error: unknown command 'deploy'\ntry 'myapp --help'` |
| 9 | Deprecated command | deprecated.json: "deprecated: invoke deprecated command prints message and exits 1" | `["old-cmd"]` | exit 1; stderr contains `command 'old-cmd' is deprecated: use 'new-cmd' instead` |
| 10 | Passthrough | passthrough.json: "passthrough: receives raw args" | `["checkout", "-b", "feature"]` | exit 0; stdout equals `checkout:-b,feature` |
| 11 | Version | basic.json: "basic: --version flag" | `["--version"]` | exit 0; stdout equals `myapp 2.5.0` |
| 12 | Data-outcome JSON line | outcome_contract.json: "outcome: data-only return prints one compact JSON line (byte-identical across languages)" | `["run"]` | exit 0; stdout equals `{"count":3,"name":"strictcli"}` |

Sourcing note: help/flag-success/try-help-trailer/required-flag/negation/unknown-command/
version scenarios come from the four instructed files (basic.json, help.json, flags.json,
errors.json). Those files contain no choices, env, deprecated, passthrough, or
data-outcome cases, so scenarios 4, 7, 9, 10, and 12 were drawn from their dedicated
case files (choices.json, env.json, deprecated.json, passthrough.json,
outcome_contract.json).

## Baseline (filled by task 0.3)

Recorded 2026-07-19, all green.

### Conformance gate (`uv run conformance check --tag pre-release`, 7 checks)

| Check | Status |
|-------|--------|
| api-surface | PASS |
| conformance-go | PASS |
| conformance-python | PASS |
| error-parity | PASS |
| float-fuzz | PASS |
| schema-parity | PASS |
| conformance-parity | PASS |

### Unit suites

- Python (`cd python && uv run pytest -q`): 3120 passed, 0 failed (1.88s).
- Go (`cd go && go test ./...`): `ok github.com/smm-h/strictcli/go/strictcli` (0.538s), all packages pass.

### Conformance case counts (`conformance/run.py`)

- `--target python`: 543/543 passed, 0 failed.
- `--target go`: 542/542 passed, 0 failed.

### Pre-push exemption fact (rlsbl source, verified)

The `prepush-changelog-coverage` check attributes pushed commits to workspace
projects by file path/watch-glob matching, then skips non-releasable projects
entirely:

- `rlsbl/checks/prepush.py:64-66` (explicit-releasable mode) and `:85-87`
  (implicit mode): `if not project_is_releasable(proj): continue` -- affected
  projects that are not releasable require no changelog coverage.
- `rlsbl/workspace_types.py:246-247`: `project_is_releasable` returns `False`
  when the project has `dev_node = true`. Hence commits touching only
  `conformance/` (a dev_node) are exempt from pre-push changelog coverage.
- `rlsbl/git_util.py:81-110` (`filter_commits_for_releasable`) and `:228-240`
  (`affected_projects`): commits whose changed files match no project's path
  prefix or watch globs are attributed to no releasable, so commits touching
  only repo-root files (docs/, README.md, CLAUDE.md, workflows, this spec)
  require no changelog entry. If a push touches no project at all, the check
  passes with "no affected projects" (`rlsbl/checks/prepush.py:51-52`).

## Decision ledger (agents append at phase boundaries)

The conversation-level decision ledger is authoritative. This section carries durable
design constants only -- append entries here at phase boundaries when a decision must
survive beyond session memory.

- 2026-07-19 (subphase 5.6): `ParseError` and `RegistrationError` stay internal --
  removed from index.ts exports (they had drifted into the public surface alongside
  `InvokeError`). Sibling parity is the argument: Python's `__all__` and Go export
  only `InvokeError`; registration failures are Go panics / Python ValueError, and
  parse failures print to stderr and exit 1, so neither sibling exposes an error
  class for them. The classes remain in src/errors.ts; tests import them by module
  path. `InvokeError` stays public in all three implementations.
- 2026-07-22 (task 6.1): TS conformance harness (`conformance/harness_ts/main.js`)
  import mechanism and build step. The harness is plain Node ESM JavaScript (no
  tsconfig, no npm install, no build of its own) that imports the built dist by
  direct relative path (`../../typescript/dist/index.js`, plus `float.js` for
  canonical float rendering and `errors.js` for the catalog messages it replays).
  Rationale: relative-path ESM imports bypass the package `exports` map (needed for
  the non-public float/errors modules), need zero install in `conformance/`, and the
  dist's own bare specifiers (smol-toml) resolve through `typescript/node_modules`
  via Node's walk-up because the imported files live under `typescript/`. The only
  prerequisite is `cd typescript && npm run build`; run.py invokes
  `node conformance/harness_ts/main.js <argv...>` with `CONFORMANCE_APP_DEF` set.
  Vocabulary notes: (a) case defs with scalar type + `repeatable: true` map to
  list carriers (in TS, list carriers ARE the repeatable flags; bool + repeatable
  keeps the scalar carrier so the framework mints its incompatibility error);
  (b) two framework guards that the TS factory API makes inexpressible from JSON
  are replayed in the harness with the framework's own errors.ts catalog builders:
  passthrough-with-flags/args/flag-sets/mutex (`errCommandPassthroughCannotHave`)
  and same-name duplicates inside one flag list, which a keyed FlagMap would
  silently collapse (`errCommandDuplicateFlag` / `errDuplicateGlobalFlag`);
  (c) check registration form (errorCheck vs warnCheck) is read back from
  `app.checks.defs` severities after createApp parses the embedded TOML (fallback
  to error-form for undeclared names, same as the Go harness's fallback);
  (d) `handler_returns.kind: "bad"` returns a non-outcome (ref_python parity; Go
  cannot express it and maps it to Exit(0)). Smoke oracle:
  `conformance/harness_ts/smoke_test.py` compares TS vs Go harness output
  byte-for-byte over a 99-case representative slice, accepting divergence only
  when both outputs independently satisfy the case's own expect block (2 pinned
  wording divergences: dict parse error and provider severity-mismatch builder
  names, both matching Python's shape).
