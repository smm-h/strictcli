---
title: TypeScript Quickstart
description: "Build TypeScript CLIs with strictcli: command factories, the presence-discriminated flag and arg options, typed flags, args, groups, payloads under --json, and consequential consent on CLI, call and MCP."
nav_group: "Guides"
nav_order: 0
---

# TypeScript Quickstart

strictcli is a strict CLI framework where you declare everything and infer nothing. Every flag, arg, command, and group requires explicit help text. Types are enforced at both compile time and runtime. This guide covers the TypeScript implementation, published on npm as `strictcli`.

## Installation

Requires Node >= 22. The TypeScript implementation is published on npm as
`strictcli` and ships as pure ESM with full type inference for handler arguments.
Install it as a dependency in your project:

```bash
npm install strictcli
```

## Creating an App

Every CLI starts with `createApp`, which takes the application name, version
string, and help text as required fields. Empty help text is a hard error.
Additional options like `envPrefix`, `config`, and `configFormat` are passed in
the same options object.

```typescript
import { createApp } from "strictcli";

const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "A tool that does useful things",
});
```

## Defining Commands

Commands are built with one of the **twin factories** and registered on the app
via `app.command()`. Every command requires a `help` string and a `handler`
function. The handler receives a fully typed `args` object whose shape is
inferred from the flag and arg declarations, plus a `Context` for structured
output.

There is no single `defineCommand`: classification is mandatory and has no
default, so the factory name *is* the classification.

| Factory | Classification | Handler `ctx` |
|---------|---------------|---------------|
| `defineReadOnlyCommand(...)` | `read_only` | `ReadOnlyContext` |
| `defineMutatingCommand(...)` | `mutating` | `MutatingContext` |

A `read_only` command changes nothing: it never prompts, cannot be declared
consequential, and its handler's `ctx` is narrowed so that
`ctx.effects.write(...)` is a **compile error**. A `mutating` command
participates in `--dry-run`, where its effects are recorded instead of
performed, and may call every member of the effects handle.

Classification answers one question -- "should a dry run record this rather than
perform it?" It is deliberately **not** the same question as "is this dangerous
enough to interrupt someone for?", which is what
[`consequential`](#consequential-commands-and-the-confirm-protocol) answers. A
mutating command does not prompt unless it also sets `consequential: true`.

Passthrough commands are classified through the same scheme, by the same
morphology: `readOnlyPassthrough(...)` and `mutatingPassthrough(...)`.

```typescript validate
import { createApp, defineReadOnlyCommand, t, flag } from "strictcli";

const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "A tool that does useful things",
});

app.command(
  defineReadOnlyCommand("greet", {
    help: "Greet someone by name",
    flags: {
      name: flag("name", t.str, { help: "Who to greet", presence: "required" }),
    },
    handler: (args, ctx) => {
      ctx.info(`Hello, ${args.name}!`);
    },
  }),
);

app.run();
```

Handlers receive two arguments:

- `args` -- a typed object with all flag and arg values. The type is inferred from the flag and arg declarations.
- `ctx` -- a `Context` with structured output methods: `ctx.info()`, `ctx.warn()`, `ctx.error()`, `ctx.debug()`.

### Handler return values

A handler can return one of three strictly validated types. Any other return
type is a hard error that terminates the program. The `outcome()` factory is the
only way to construct a branded result -- hand-forged objects are rejected at
runtime:

- `undefined` (or no return) -- exit code 0
- A `number` -- used as the exit code
- `outcome(exitCode)` -- a branded exit-code result

```typescript
import { outcome } from "strictcli";

handler: (args) => {
  return outcome(0);
}
```

### Machine payloads

Structured output does not ride the return value. A command declares its
payload's JSON Schema with `payloadSchema:`, and its handler supplies the value
through `ctx.payload(value)` -- at most once per dispatch, and only on a command
that declared a schema (calling it without one is a hard error at call time).
The payload is printed only under the framework-owned `--json`; `app.test()` and
`app.call()` capture it in either mode.

```typescript
defineReadOnlyCommand("status", {
  help: "Show status",
  payloadSchema: { type: "object" },
  handler: (args, ctx) => {
    ctx.payload({ count: 42, status: "done" });
    return outcome(0);
  },
});
```

```
$ mytool status --json
{"count":42,"status":"done"}
```

## Flag Types

strictcli supports four scalar types plus list and dict compound types. Each
type is represented by a carrier from the `t` namespace that carries both a
runtime type tag and a phantom TypeScript type, enabling full compile-time type
inference for handler arguments without manual annotations.

| Carrier | CLI syntax | TypeScript type | Notes |
|---------|-----------|----------------|-------|
| `t.str` | `--name value` | `string` | |
| `t.bool` | `--cache` / `--no-cache` | `boolean` | Negation via `--no-` prefix; `presence: "optional"` makes it a real tri-state |
| `t.int` | `--count 42` | `bigint` | Strict parsing: no leading zeros, 64-bit signed bounds |
| `t.float` | `--rate 3.14` | `number` | Rejects NaN and Inf |
| `t.list(t.str)` | `--tag a --tag b` | `string[]` | Repeat the flag for each element |
| `t.list(t.int)` | `--id 1 --id 2` | `bigint[]` | |
| `t.dict(t.str)` | `--header key=val` | `Map<string, string>` | Key=value pairs; keys are always strings |

## Presence: required, optional, or a default

`FlagOpts` is a **discriminated union on `presence`**, and `ArgOpts` is the same
union. Every flag and every positional arg declares exactly one of three facts
about itself, and nothing is inferred from the shape of another declaration:

| Fact | Spelling | The handler receives |
|------|----------|----------------------|
| **required** | `{ presence: "required" }` | the supplied value; the parse fails if nothing supplies one |
| **optional** | `{ presence: "optional" }` | the supplied value, or `undefined` when nothing supplied one |
| **default** | `{ presence: "default", default: <value> }` | the supplied value, or the declared default |

```typescript
flags: {
  target: flag("target", t.str, { help: "Deploy target", presence: "required" }),
  region: flag("region", t.str, {
    help: "AWS region",
    presence: "default",
    default: "us-east-1",
  }),
  tag: flag("tag", t.str, { help: "Release tag", presence: "optional" }),
}
```

A `default` outside the `"default"` member does not type-check, and the
`"default"` member's `default` is not optional. Declaring none of the three, or
more than one, throws at registration:

```
Flag "target": presence is undeclared: declare exactly one of presence: "required", presence: "optional", or presence: "default" with default: <value>
```

`default: null` is **not** a spelling of optionality. It fails the type check and
is refused at registration too, because a widened option object can reach the
factory with a `null` the compiler never saw:

```
Flag "tag": default: null does not declare optionality: use presence: "optional" (it delivers undefined when the flag is absent)
```

The type-level consequence is part of the promise. `FlagKeyIsOptional` reads
`presence`, so the inferred handler-args type follows the declaration by
construction -- which is what fixed the mutex-member key that used to be typed
as always-present while the parser handed it `undefined`.

Every flag and arg renders exactly one presence part in help output:
`[required]`, `[optional]`, or `[default: <value>]`. A declared empty collection
renders `[default: []]` / `[default: {}]`, and a required positional renders
`[required]`.

### `ctx.provided` -- was this supplied?

`ctx.provided(name)` answers whether the **invocation** caused a value, so no
handler reconstructs that boolean out of a sentinel:

| Source | `provided` |
|--------|-----------|
| `cli`, `env`, `config`, `implied` | **true** -- the invocation caused the value |
| `default`, `infra` | **false** -- the declaration caused it |

An optional flag that received nothing carries source `default` and reports
`false`. An unknown name throws exactly as `ctx.source` does. The same predicate
decides presence for `coRequired`, `requires` and `implies`, so a declared
default never satisfies a dependency.

### Boolean Flags

Bool flags declare presence like every other flag. A `presence: "required"` bool
must be answered (`--flag` or `--no-flag`); a `presence: "optional"` bool is a
real tri-state where `--flag` is `true`, `--no-flag` is `false`, and absence is
`undefined`. They support `--no-` negation by default, which can be disabled by
setting `negatable: false` for pure presence flags.

```typescript
flags: {
  cache: flag("cache", t.bool, {
    help: "Reuse the build cache",
    presence: "default",
    default: true,
  }),
  watch: flag("watch", t.bool, {
    help: "Watch mode",
    presence: "default",
    default: false,
    negatable: false, // disables --no-watch
  }),
  color: flag("color", t.bool, {
    help: "Colorize output",
    presence: "optional", // true, false, or absent
  }),
}
```

### Number Flags

Integers are `bigint` in TypeScript to preserve 64-bit signed integer precision
without floating-point truncation. Defaults must also be `bigint` literals
(e.g., `3n`). Strict parsing rejects leading zeros and enforces 64-bit signed
bounds.

```typescript
flags: {
  replicas: flag("replicas", t.int, {
    help: "Replica count",
    presence: "default",
    default: 3n,
  }),
  rate: flag("rate", t.float, {
    help: "Request rate",
    presence: "default",
    default: 1.0,
  }),
}
```

### Repeatable Flags (Lists)

Use `t.list(elem)` for repeatable flags where each `--flag value` occurrence
appends an element to the resulting array. A list flag declares presence like
every other flag -- there is no silent empty-array default. The element type
must be `t.str`, `t.int`, or `t.float` -- boolean elements are not supported.

```typescript
flags: {
  // An empty array when nothing is passed -- declared, not assumed
  tag: flag("tag", t.list(t.str), {
    help: "Tags to apply",
    presence: "default",
    default: [],
  }),
  // Absent when nothing is passed: undefined, not []
  port: flag("port", t.list(t.int), { help: "Ports to expose", presence: "optional" }),
}
```

Usage: `--tag alpha --tag beta` produces `["alpha", "beta"]`. With the
declaration above, zero occurrences gives `[]` for `tag` and `undefined` for
`port`.

### Dict Flags

Use `t.dict(elem)` for key=value pair flags where each occurrence adds a new
entry to the resulting `Map`. Keys are always strings and duplicate keys are
rejected. Dict flags cannot be combined with `repeatable`, `unique`, `choices`,
or `envSeparator`. The empty-map declaration is `default: new Map()`.

```typescript
flags: {
  header: flag("header", t.dict(t.str), {
    help: "HTTP headers",
    presence: "default",
    default: new Map(),
  }),
}
```

Usage: `--header content-type=text/html --header accept=application/json`

### Choices

Restrict a flag's values to a set of valid choices. Values not in the choices
list produce a parse error listing all allowed values. All choice values must
match the flag's declared type, and bool flags cannot have choices.

```typescript
flags: {
  format: flag("format", t.str, {
    help: "Output format",
    presence: "required",
    choices: ["text", "json", "csv"],
  }),
  level: flag("level", t.int, {
    help: "Log level",
    presence: "default",
    default: 0n,
    choices: [0n, 1n, 2n],
  }),
}
```

A declared `default` value must be in the choices list, checked at registration.
`presence: "optional"` declares no value, so nothing is checked at registration
and absence is never matched against `choices` at parse time.

### Short Aliases

Single-character short aliases for flags provide a concise alternative on the
command line. Short flags follow the same parsing rules as their long
counterparts, including type coercion and negation for boolean flags. They
appear alongside long flags in help output.

```typescript
flags: {
  recursive: flag("recursive", t.bool, {
    help: "Recurse into subdirectories",
    short: "r",
    presence: "default",
    default: false,
  }),
  output: flag("output", t.str, {
    help: "Output file",
    short: "o",
    presence: "required",
  }),
}
```

Usage: `-r`, `-o file.txt`

### Environment Variables

Bind a flag to an environment variable using the `env` option. Environment
variables sit between CLI tokens and config file values in the resolution
cascade (CLI > env > config > default) and are skipped entirely under
`--hermetic` mode. When an `envPrefix` is set on the app, flag env vars must
start with that prefix.

```typescript
const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "My tool",
  envPrefix: "MYTOOL",
});

app.command(
  defineMutatingCommand("deploy", {
    help: "Deploy the app",
    flags: {
      target: flag("target", t.str, {
        help: "Deploy target",
        env: "MYTOOL_TARGET",
        presence: "default",
        default: "staging",
      }),
    },
    handler: (args, ctx) => {
      ctx.info(`Deploying to ${args.target}`);
    },
  }),
);
```

Precedence: CLI flag > environment variable > config file > default. An env- or
config-supplied value satisfies a `presence: "required"` declaration and makes
the flag *provided*, so `ctx.provided("target")` is `true` with source `"env"` or
`"config"`.

For repeatable flags with env vars, an `envSeparator` is required so the single env string can be split into elements.

```typescript
flags: {
  tag: flag("tag", t.list(t.str), {
    help: "Tags",
    env: "MYTOOL_TAGS",
    envSeparator: ",",
    presence: "default",
    default: [],
  }),
}
```

## Positional Args

Positional args use scalar carriers and are declared separately from flags in
the `args` array of a command definition. They are consumed in declaration order
after all flags have been parsed. Each arg requires a name, type carrier, help
text, and the same three-way `presence` declaration a flag carries -- `ArgOpts`
is the same discriminated union as `FlagOpts`. There is no `required?: boolean`.

```typescript
import { arg } from "strictcli";

app.command(
  defineMutatingCommand("copy", {
    help: "Copy a file",
    args: [
      arg("src", t.str, { help: "Source file", presence: "required" }),
      arg("dst", t.str, { help: "Destination file", presence: "required" }),
    ],
    handler: (args, ctx) => {
      ctx.info(`Copying ${args.src} to ${args.dst}`);
    },
  }),
);
```

An optional arg delivers `undefined` and its inferred type keeps `?:`, while the
runtime args object carries the property -- absence is a present key, never an
omitted one.

```typescript
args: [
  arg("path", t.str, { help: "Project directory", presence: "optional" }),
  arg("mode", t.str, { help: "Run mode", presence: "default", default: "fast" }),
]
```

### Variadic Args

A variadic arg collects all remaining positional tokens into an array. It must
be the last arg in the command's declaration, and only one variadic arg is
allowed per command. Use a scalar carrier with `variadic: true`. Because it
always delivers a list, `presence: "required"` means *at least one value* and
`presence: "optional"` means *possibly none*; a default on a variadic arg is a
registration error.

```typescript
args: [
  arg("target", t.str, { help: "Deploy target", presence: "required" }),
  arg("files", t.str, {
    help: "Files to process",
    variadic: true,
    presence: "optional",
  }),
]
```

## Flag Sets

`flagSet` groups reusable flags that can be shared across commands. The flags
appear in the handler's `args` object alongside direct flags, fully typed. Each
command that uses a flag set receives all its flags as if they were declared
directly, including type checking, env var binding, and constraint validation.

```typescript
import { flagSet } from "strictcli";

const pagination = flagSet("pagination", {
  page: flag("page", t.int, { help: "Page number", presence: "default", default: 1n }),
  per_page: flag("per-page", t.int, {
    help: "Items per page",
    presence: "default",
    default: 20n,
  }),
});

app.command(
  defineReadOnlyCommand("list-users", {
    help: "List all users",
    flagSets: [pagination],
    handler: (args, ctx) => {
      // args.page and args.per_page are available here, fully typed
      ctx.info(`Page ${args.page}, ${args.per_page} per page`);
    },
  }),
);
```

## Mutex Groups

`mutexGroup` declares flags where at most one may have a value from an explicit
source (CLI, env, or config). If no flag in the group is elected, a "one of ...
is required" error is produced.

Each member declares its own presence: `presence: "optional"` is the ordinary
declaration and makes the handler key `undefined` when the member is not
elected, a `default` is legal (an unelected member delivers it), and
`presence: "required"` throws at registration -- the group's own requirement is
what makes the choice mandatory. The inferred handler-args type follows that
declaration, so an optional member's key is typed `| undefined` exactly as the
parser delivers it.

```typescript
import { mutexGroup } from "strictcli";

app.command(
  defineReadOnlyCommand("fetch", {
    help: "Fetch data from a source",
    mutex: [
      mutexGroup({
        file: flag("file", t.str, { help: "Read from file", presence: "optional" }),
        url: flag("url", t.str, { help: "Read from URL", presence: "optional" }),
      }),
    ],
    handler: (args, ctx) => {
      if (args.file !== undefined) {
        ctx.info(`Reading from file: ${args.file}`);
      } else {
        ctx.info(`Fetching from URL: ${args.url}`);
      }
    },
  }),
);
```

## Flag Dependencies

Declare relationships between flags using dependency descriptors. Three
dependency types are available: `requires` (one-way dependency), `coRequired`
(must appear together or not at all), and `implies` (automatically sets a target
flag when a trigger is provided).

```typescript
import { requires, coRequired, implies } from "strictcli";

app.command(
  defineMutatingCommand("deploy", {
    help: "Deploy the service",
    flags: {
      target: flag("target", t.str, { help: "Deploy target", presence: "optional" }),
      region: flag("region", t.str, { help: "AWS region", presence: "optional" }),
      canary: flag("canary", t.bool, {
        help: "Canary rollout first",
        presence: "default",
        default: false,
      }),
      wait: flag("wait", t.bool, {
        help: "Block until settled",
        presence: "default",
        default: false,
      }),
    },
    dependencies: [
      // --target requires --region to also be provided
      requires({ flag: "target", dependsOn: "region" }),
      // --target and --region must appear together
      coRequired(["target", "region"]),
      // When --canary is set, auto-set --wait to true
      implies({ flag: "canary", implies: "wait", value: true }),
    ],
    handler: (args, ctx) => {
      ctx.info(`Deploying to ${args.target} in ${args.region}`);
    },
  }),
);
```

All three read presence through the same predicate `ctx.provided` uses -- a flag
counts as present when the invocation caused its value. A declared default never
satisfies a `requires`, never completes a `coRequired` group, and never fires an
`implies` trigger. That includes a `relativeToRoot` default with the `infra`
source label: it is still the declaration deciding.

## Command Groups

Groups organize commands into namespaces, creating a hierarchical command
structure like `mytool dns zone create`. Groups nest to arbitrary depth, and
each group requires a name and help text. When a group is reached without a
subcommand, the group's help text is displayed.

```typescript
const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "Infrastructure management tool",
});

const dns = app.group("dns", { help: "Manage DNS records" });

dns.command(
  defineReadOnlyCommand("list", {
    help: "List all DNS records",
    handler: (args, ctx) => {
      ctx.info("Listing DNS records...");
    },
  }),
);

const zone = dns.group("zone", { help: "Manage DNS zones" });

zone.command(
  defineMutatingCommand("create", {
    help: "Create a new DNS zone",
    flags: {
      name: flag("name", t.str, { help: "Zone name", presence: "required" }),
    },
    handler: (args, ctx) => {
      ctx.info(`Creating zone: ${args.name}`);
    },
  }),
);
```

Usage: `mytool dns list`, `mytool dns zone create --name example.com`

### Group tags

Tags on a group are inherited by all commands in that group, merged with each
command's own tags. Tag contracts (`tagContract`) can declare that any command
with a given tag must have a specific flag, enforced across the entire command
tree at `run()` or `test()` time.

```typescript
const admin = app.group("admin", {
  help: "Admin commands",
  tags: ["admin"],
});
```

### Deprecated Commands

Register retired commands that print a deprecation message to stderr and exit
with code 1. Deprecated commands appear in help output under a `Deprecated:`
section, giving users visibility into the migration path.

```typescript
import { deprecated } from "strictcli";

app.deprecate(deprecated("old-deploy", "use 'deploy' instead"));
// Also works on groups:
dns.deprecate(deprecated("dump", "use 'list' instead"));
```

## Global Flags

Flags declared on the app apply to all commands and can appear before or after
the command name on the CLI. Global flag names cannot collide with reserved
framework names like `help`, `version`, `dump-schema`, `mcp`, `config`, or
`hermetic`. Global flag values are merged into each handler's `args` object.

```typescript
const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "My tool",
  flags: {
    color: flag("color", t.bool, {
      help: "Colorize output",
      presence: "default",
      default: true,
    }),
    settings: flag("settings", t.str, {
      help: "Settings file path",
      presence: "default",
      default: "/etc/mytool/config.json",
    }),
  },
});
```

Global flag values are merged into each command handler's `args`.

## Passthrough Commands

Passthrough commands bypass all flag and argument parsing and forward raw args
directly to the handler. They are useful for wrapping external tools where the
argument format is not known in advance. Passthrough commands cannot have flags,
args, flag sets, or mutex groups.

Passthroughs use the same twin morphology as commands -- there is no bare
`passthrough` factory:

```typescript
import { mutatingPassthrough } from "strictcli";

app.command(
  mutatingPassthrough("exec", {
    help: "Execute a command in the container",
    handler: (pt, ctx) => {
      ctx.info(`Running: ${pt.args.join(" ")}`);
      // pt.name is "exec"
      // pt.args is the raw argv after the command name
      // pt.globals has global flag values
    },
  }),
);
```

Usage: `mytool exec ls -la /tmp` -- all tokens after `exec` land in `pt.args`, so the handler receives `["ls", "-la", "/tmp"]`.

A passthrough may declare `consequential: true` like any other command; it is
not exempt from the prompt, because the framework knows *less* about what is
about to happen there, not more. Because its args are forwarded to the child
byte-for-byte, the reserved quartet is not scanned after the passthrough
command's name: `mytool exec deploy --dry-run` passes `--dry-run` to the child.

## Flag Naming Conventions

strictcli enforces flag naming rules at registration time. Violations throw an
error that prevents the app from starting. These rules prevent ambiguous flag
names, protect the negation namespace, and ensure consistent dash-to-underscore
conversion for handler args.

- **Bare `--force` is banned.** Use qualified names: `--force-overwrite`, `--force-delete`.
- **`--no-` prefix is reserved.** Flag names cannot start with `no-`. The `--no-` prefix is auto-generated for negatable boolean flags.
- **Dashes to underscores.** Flags with dashes (`--log-file`) become underscore keys in the handler args (`args.log_file`). The flag map key must also use the underscore form.
- **The reserved quartet is banned.** `dry-run`, `approve-consequential`, `quiet` and `verbose` cannot be declared at any level. So is `json`, which selects machine mode, on the same every-level tier. The name `yes` is banned outright -- the confirmation skip is `--approve-consequential`.

```typescript
// The flag map key is the underscore form of the flag name
flags: {
  log_file: flag("log-file", t.str, { help: "Log file path", presence: "optional" }),
  force_overwrite: flag("force-overwrite", t.bool, {
    help: "Force overwrite",
    presence: "default",
    default: false,
  }),
}
```

## The Reserved Flag Quartet

Four flag names are owned by the framework and cannot be declared at any level --
not as app global flags, not as command flags, not inside a flag set, not inside
a mutex group:

| Flag | Delivered as | Meaning |
|------|-------------|---------|
| `--dry-run` | `ctx.dryRun` | Record effects instead of performing them, then print the would-do log |
| `--approve-consequential` | `ctx.approveConsequential` | Answer the confirm prompt in advance |
| `--quiet` | `ctx.quiet` | Suppress `ctx.info()` output; warnings and errors still print |
| `--verbose` | `ctx.verbose` | Enable `ctx.debug()` output |

```typescript
// Every one of these throws at registration time:
flag("dry-run", t.bool, { help: "Simulate the run", presence: "default", default: false });
flag("verbose", t.bool, { help: "Be verbose", presence: "default", default: false });
flag("quiet", t.bool, { help: "Be quiet", presence: "default", default: false });
```

The message is `flag name 'dry-run' is reserved by the framework (dry-run,
approve-consequential, quiet, verbose)`.

All four are recognized anywhere in argv: `mytool deploy --dry-run` and
`mytool --dry-run deploy` are equivalent. Two boundaries stop the scan -- a bare
`--` (everything after it is data) and a passthrough command's name.

### Refusing `--dry-run` with `dryRunSupported`

`--dry-run` works on every mutating command by default: its effects are recorded
rather than performed. Some commands cannot honor that honestly -- their effects
escape the effects handle, or their later steps read state that their earlier
(recorded, therefore un-performed) steps would have written. Such a command sets
`dryRunSupported: false` with a mandatory `dryRunUnsupportedReason`:

```typescript
app.command(
  defineMutatingCommand("migrate", {
    help: "Run pending database migrations",
    dryRunSupported: false,
    dryRunUnsupportedReason:
      "each migration reads the schema the previous one wrote, " +
      "so a recorded run would report the wrong pending set",
    handler: (args, ctx) => {
      ctx.info("migrating");
    },
  }),
);
```

`--dry-run` is then refused at parse time rather than rendering a preview that
would lie:

```
$ mytool migrate --dry-run
error: --dry-run is not supported by command 'migrate': each migration reads the schema the previous one wrote, so a recorded run would report the wrong pending set
```

Three guardrails apply at registration time:

- `dryRunSupported: false` on a read-only command throws -- a command that changes nothing has no effects a preview could misrepresent.
- `dryRunSupported: false` without a non-empty reason throws -- say what a preview cannot honestly show.
- A `dryRunUnsupportedReason` without `dryRunSupported: false` throws -- there is nothing to explain while dry run is supported.

The reason also appears in the command's help under a `Dry run:` section, and in
`--dump-schema` output as the pair `dry_run_supported` / `dry_run_unsupported_reason`.
Both keys are emitted only when declared, so a schema entry without them means
dry run is supported. `--help` always beats the refusal.

## Consequential Commands and the Confirm Protocol

Classification says whether a dry run should record rather than perform.
`consequential` says something different: that these effects are worth
interrupting a human for. It is the **only** thing that makes the framework
prompt -- a plain mutating command never does.

```typescript
app.command(
  defineMutatingCommand("destroy", {
    help: "Destroy the cluster",
    consequential: true,
    args: [arg("cluster", t.str, { help: "Cluster to destroy", presence: "required" })],
    handler: (args, ctx) => {
      ctx.info(`Destroying ${args.cluster}`);
    },
  }),
);
```

Before dispatching, the framework prints the prompt to stderr and reads one line
from stdin:

```
$ mytool destroy prod
about to run consequential command 'destroy'. Proceed? [y/N]
```

Only `y` or `Y` proceeds. Anything else prints `aborted` to stderr and exits 1.

Two things skip the prompt, and neither disables anything else:

- `--approve-consequential` -- the operator answered in advance. This is what automation and CI pass.
- `--dry-run` -- nothing is being performed, so there is nothing to confirm.

When stdin is not a TTY and neither flag was passed, the framework refuses
rather than hanging or silently proceeding:

```
$ mytool destroy prod < /dev/null
error: stdin is not interactive; a consequential command must be confirmed at a terminal
```

The prompt never fires on the programmatic paths, which have no TTY contract.
`app.test()` behaves as if `--approve-consequential` were passed; `app.call()`
and the MCP server take the consent from the call instead and refuse a
consequential command without it:

```ts
// Throws InvokeError:
//   command 'destroy' is consequential: the call must carry confirmation
await app.call("destroy", { env: "prod" });

// Proceeds
await app.call("destroy", { env: "prod" }, { approveConsequential: true });
```

Over MCP the same consent is a top-level `tools/call` param, a sibling of
`name` and `arguments`, never a member of `arguments`:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"destroy","arguments":{"env":"prod"},"approve_consequential":true}}
```

This is not human approval and is not meant to be: it makes the caller state,
in the call, that it is proceeding without a human.
Over the current protocol revision the server does not have to take the
caller's word for it. A `tools/call` on a consequential command from a client
that declared elicitation support is answered with a confirmation request and
an opaque `requestState`; the client puts the question to a human, and the
retry that echoes the state back with an acceptance is what consents. The state
is integrity-protected, bound to that client and that exact request, expires in
five minutes and cannot be redeemed twice. The server declares the feature by
name (`dev.smmh.strictcli/consequential-confirmation`) in its `server/discover`
result. A client that did not declare elicitation is answered `-32021` naming the
capability it would need, and a client that opened with the `initialize`
handshake is asked over that era's server-initiated `elicitation/create` instead.
[Consequential confirmation over MCP](mcp-confirmation.md) has the full dialogue.

Tool descriptors and MCP
`tools/list` publish `effect` and `consequential` beside the argument schema so
a caller can see the requirement before it calls. There is no bypass flag:
`--approve-consequential` answers the prompt and does nothing else. Setting
`consequential: true` on `defineReadOnlyCommand` throws at registration time --
a command that changes nothing has nothing to confirm.

## Schema Dump

Every strictcli app has a built-in `--dump-schema` reserved flag. Running it
writes a JSON file describing the full CLI structure to
`.strictcli/schema.json` and prints the absolute path to stdout. The schema
includes all commands, flags, args, groups, constraints, and config field
declarations.

```bash
mytool --dump-schema
```

The location is declared, never discovered: `schemaPath: "build/cli-schema.json"`
or `schemaPath: relativeToRoot("MYTOOL_HOME", "schema.json")` in `createApp`.
With neither, the framework writes `.strictcli/schema.json` anchored at the
working directory the app was CONSTRUCTED in, so a later `chdir` cannot move the
file.

Programmatically, use `app.dumpSchemaDict()` to get the schema as an object without writing to disk.

```typescript
const schema = app.dumpSchemaDict();
console.log(JSON.stringify(schema, null, 2));
```

## Testing

`app.test(argv)` runs the CLI in-process and captures stdout, stderr, exit
code, and the machine payload without shelling out. This is the standard way
to test strictcli apps in TypeScript. The result object is fully typed and
includes the `data` field when the handler supplied a payload through
`ctx.payload()`, in either output mode.

```typescript
import { strict as assert } from "node:assert";
import { test } from "node:test";

test("greet command outputs the name", async () => {
  const r = await app.test(["greet", "--name", "world"]);
  assert.equal(r.stdout, "Hello, world!\n");
  assert.equal(r.stderr, "");
  assert.equal(r.exitCode, 0);
});
```

## Programmatic Invocation

`app.call(commandPath, kwargs)` invokes a command in-process with pre-typed
values, bypassing CLI parsing, env var resolution, and config file loading. The
command path uses dot-separated notation for nested commands (e.g.,
`"dns.zone.create"`). Failures throw `InvokeError`.

```typescript
// Dot-separated path for nested commands
const result = await app.call("dns.zone.create", { name: "example.com" });
```

Failures throw `InvokeError`.

A third `CallOptions` argument carries the caller's consent. A command declared
`consequential` is refused without it, because there is no terminal here to
prompt:

```typescript
// Throws: command 'destroy' is consequential: the call must carry confirmation
await app.call("destroy", { env: "prod" });

await app.call("destroy", { env: "prod" }, { approveConsequential: true });
```

`app.asTools()` publishes the same requirement on every descriptor, beside the
argument schema rather than inside it, so a caller can see it before it calls:

```typescript
const release = app.asTools().find((t) => t.name === "release");
release.effect; // "mutating"
release.consequential; // true
await release.execute({}, { approveConsequential: true });
```

## TypeScript Type Safety

The type system infers the exact shape of the handler's `args` parameter from
flag and arg declarations, so no manual type annotations are needed. The type
carriers (`t.str`, `t.int`, etc.) carry phantom types that flow through the
generic machinery in the twin factories, producing correct output types without
casts. Flags from `flagSets` and `mutexGroup` entries are also merged into the
handler args type.

```typescript
app.command(
  defineMutatingCommand("deploy", {
    help: "Deploy the service",
    flags: {
      target: flag("target", t.str, { help: "Deploy target", presence: "required" }),
      replicas: flag("replicas", t.int, { help: "Replica count", presence: "required" }),
      canary: flag("canary", t.bool, {
        help: "Canary first",
        presence: "default",
        default: false,
      }),
      tag: flag("tag", t.str, { help: "Tag", presence: "optional" }),
    },
    args: [arg("service", t.str, { help: "Service name", presence: "required" })],
    handler: (args) => {
      // TypeScript knows the exact type of args:
      //   args.target    -> string         (presence: "required")
      //   args.replicas  -> bigint         (presence: "required")
      //   args.canary    -> boolean        (presence: "default")
      //   args.tag       -> string | undefined  (presence: "optional")
      //   args.service   -> string         (positional arg, presence: "required")
    },
  }),
);
```

The type carriers (`t.str`, `t.int`, etc.) carry phantom types that flow through the generic machinery in the twin factories and `flag`/`arg`, so the output types are correct without casts. Flags from `flagSets` and `mutexGroup` entries are also merged into the handler args type.

Optionality in that type comes from the `presence` discriminant and nothing
else, so the type a handler sees and the value the parser hands it can no longer
disagree.

The classification also flows into the type system. Because
`defineReadOnlyCommand` narrows its handler's `ctx` to `ReadOnlyContext`, a
mutating effect inside a read-only command does not compile:

```typescript
defineReadOnlyCommand("status", {
  help: "Show status",
  handler: (args, ctx) => {
    ctx.effects.write("out.txt", "data"); // compile error: not on ReadOnlyContext
  },
});
```

## Complete Example

```typescript validate
import {
  createApp,
  defineMutatingCommand,
  defineReadOnlyCommand,
  deprecated,
  flag,
  flagSet,
  mutexGroup,
  arg,
  mutatingPassthrough,
  outcome,
  t,
} from "strictcli";

const app = createApp({
  name: "deploy",
  version: "0.1.0",
  help: "Deployment management tool",
  envPrefix: "DEPLOY",
  flags: {
    color: flag("color", t.bool, {
      help: "Colorize output",
      presence: "default",
      default: true,
    }),
  },
});

const common = flagSet("common", {
  region: flag("region", t.str, {
    help: "Cloud region",
    env: "DEPLOY_REGION",
    presence: "required",
    choices: ["us-east-1", "eu-west-1", "ap-south-1"],
  }),
});

app.command(
  defineMutatingCommand("run", {
    help: "Deploy a service",
    flags: {
      replicas: flag("replicas", t.int, {
        help: "Number of replicas",
        presence: "default",
        default: 1n,
      }),
      tag: flag("tag", t.list(t.str), {
        help: "Tags for the deployment",
        presence: "default",
        default: [],
      }),
    },
    flagSets: [common],
    args: [arg("service", t.str, { help: "Service to deploy", presence: "required" })],
    payloadSchema: { type: "object" },
    handler: (args, ctx) => {
      ctx.info(`Deploying ${args.service} to ${args.region}`);
      ctx.info(`Replicas: ${args.replicas}`);
      if (args.tag.length > 0) {
        ctx.info(`Tags: ${args.tag.join(", ")}`);
      }
      ctx.payload({ service: args.service, replicas: args.replicas });
      return outcome(0);
    },
  }),
);

const infra = app.group("infra", { help: "Infrastructure commands" });

infra.command(
  defineReadOnlyCommand("status", {
    help: "Show infrastructure status",
    flagSets: [common],
    handler: (args, ctx) => {
      ctx.info(`Status for region: ${args.region}`);
    },
  }),
);

infra.command(
  defineReadOnlyCommand("logs", {
    help: "View infrastructure logs",
    mutex: [
      mutexGroup({
        service: flag("service", t.str, {
          help: "Filter by service",
          presence: "optional",
        }),
        node: flag("node", t.str, { help: "Filter by node", presence: "optional" }),
      }),
    ],
    handler: (args, ctx) => {
      if (args.service !== undefined) {
        ctx.info(`Logs for service: ${args.service}`);
      } else {
        ctx.info(`Logs for node: ${args.node}`);
      }
    },
  }),
);

app.deprecate(deprecated("push", "use 'run' instead"));

app.command(
  mutatingPassthrough("exec", {
    help: "Execute a command on a service",
    handler: (pt, ctx) => {
      ctx.info(`Executing on ${pt.name}: ${pt.args.join(" ")}`);
    },
  }),
);

app.run();
```

Usage:

```
deploy run myservice --region us-east-1 --replicas 3 --tag v1 --tag prod
deploy infra status --region eu-west-1
deploy infra logs --service api
deploy exec -- ls -la
deploy --version
deploy --help
deploy --dump-schema
```

## Reserved Global Flags

Every strictcli app automatically has these 6 reserved flags that cannot be
overridden by user-defined global flags. Attempting to register a flag with any
of these names produces a registration-time error:

- `--help` / `-h` -- show help for the app, group, or command
- `--version` / `-v` -- print the app version
- `--dump-schema` -- write `.strictcli/schema.json` and print the path
- `--hermetic` -- skip env var and config file resolution (values come only from CLI tokens and defaults)
- `--config <path>` -- use a specific config file (when config is enabled)
- `--mcp` -- start an MCP JSON-RPC 2.0 server on stdin/stdout
