---
title: TypeScript Quickstart
description: "Get started with strictcli in TypeScript: install, create an app, define commands with typed flags and args, organize with groups, and dump the schema."
nav_group: "Guides"
nav_order: 0
---

# TypeScript Quickstart

strictcli is a strict CLI framework where you declare everything and infer nothing. Every flag, arg, command, and group requires explicit help text. Types are enforced at both compile time and runtime. This guide covers the TypeScript implementation, published on npm as `strictcli`.

## Installation

Requires Node >= 22.

```bash
npm install strictcli
```

## Creating an App

Every CLI starts with `createApp`. The `name`, `version`, and `help` fields are all required.

```typescript
import { createApp } from "strictcli";

const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "A tool that does useful things",
});
```

## Defining Commands

Commands are built with `defineCommand` and registered on the app. Every command requires a `help` string and a `handler` function.

```typescript
import { createApp, defineCommand, t, flag } from "strictcli";

const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "A tool that does useful things",
});

app.command(
  defineCommand("greet", {
    help: "Greet someone by name",
    flags: {
      name: flag("name", t.str, { help: "Who to greet" }),
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

A handler can return:

- `undefined` (or no return) -- exit code 0
- A `number` -- used as the exit code
- `outcome(exitCode, data)` -- structured data emitted as one compact JSON line to stdout

```typescript
import { outcome } from "strictcli";

handler: (args) => {
  return outcome(0, { count: 42, status: "done" });
}
```

## Flag Types

strictcli supports four scalar types, plus list and dict compound types. Each type is represented by a carrier from the `t` namespace.

| Carrier | CLI syntax | TypeScript type | Notes |
|---------|-----------|----------------|-------|
| `t.str` | `--name value` | `string` | |
| `t.bool` | `--verbose` / `--no-verbose` | `boolean` | Requires a default; negation via `--no-` prefix |
| `t.int` | `--count 42` | `bigint` | Strict parsing: no leading zeros, 64-bit signed bounds |
| `t.float` | `--rate 3.14` | `number` | Rejects NaN and Inf |
| `t.list(t.str)` | `--tag a --tag b` | `string[]` | Repeat the flag for each element |
| `t.list(t.int)` | `--id 1 --id 2` | `bigint[]` | |
| `t.dict(t.str)` | `--header key=val` | `Map<string, string>` | Key=value pairs; keys are always strings |

### Boolean Flags

Bool flags must have a `default`. They support `--no-` negation by default. Set `negatable: false` to disable negation.

```typescript
flags: {
  verbose: flag("verbose", t.bool, {
    help: "Enable verbose output",
    default: false,
  }),
  watch: flag("watch", t.bool, {
    help: "Watch mode",
    default: false,
    negatable: false, // disables --no-watch
  }),
}
```

### String Flags

A flag without a `default` is required. Provide a default to make it optional. Set `default: null` for an explicitly-optional flag (the handler key becomes `?:` in the type).

```typescript
flags: {
  target: flag("target", t.str, { help: "Deploy target" }), // required
  region: flag("region", t.str, { help: "AWS region", default: "us-east-1" }),
  tag: flag("tag", t.str, { help: "Release tag", default: null }), // optional, may be absent
}
```

### Number Flags

Integers are `bigint` in TypeScript. Defaults must also be `bigint`.

```typescript
flags: {
  replicas: flag("replicas", t.int, { help: "Replica count", default: 3n }),
  rate: flag("rate", t.float, { help: "Request rate", default: 1.0 }),
}
```

### Repeatable Flags (Lists)

Use `t.list(elem)` for repeatable flags. Each `--flag value` occurrence appends an element.

```typescript
flags: {
  tag: flag("tag", t.list(t.str), { help: "Tags to apply" }),
  port: flag("port", t.list(t.int), { help: "Ports to expose" }),
}
```

Usage: `--tag alpha --tag beta` produces `["alpha", "beta"]`. Zero occurrences gives an empty array.

### Dict Flags

Use `t.dict(elem)` for key=value pair flags. Keys are always strings.

```typescript
flags: {
  header: flag("header", t.dict(t.str), { help: "HTTP headers" }),
}
```

Usage: `--header content-type=text/html --header accept=application/json`

### Choices

Restrict a flag's values to a set of valid choices.

```typescript
flags: {
  format: flag("format", t.str, {
    help: "Output format",
    choices: ["text", "json", "csv"],
  }),
  level: flag("level", t.int, {
    help: "Log level",
    choices: [0n, 1n, 2n],
  }),
}
```

### Short Aliases

Single-character short aliases for flags.

```typescript
flags: {
  verbose: flag("verbose", t.bool, {
    help: "Verbose output",
    short: "v",
    default: false,
  }),
  output: flag("output", t.str, {
    help: "Output file",
    short: "o",
  }),
}
```

Usage: `-v`, `-o file.txt`

### Environment Variables

Bind a flag to an environment variable. When an `envPrefix` is set on the app, flag env vars must start with that prefix.

```typescript
const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "My tool",
  envPrefix: "MYTOOL",
});

app.command(
  defineCommand("deploy", {
    help: "Deploy the app",
    flags: {
      target: flag("target", t.str, {
        help: "Deploy target",
        env: "MYTOOL_TARGET",
        default: "staging",
      }),
    },
    handler: (args, ctx) => {
      ctx.info(`Deploying to ${args.target}`);
    },
  }),
);
```

Precedence: CLI flag > environment variable > config file > default.

For repeatable flags with env vars, an `envSeparator` is required so the single env string can be split into elements.

```typescript
flags: {
  tag: flag("tag", t.list(t.str), {
    help: "Tags",
    env: "MYTOOL_TAGS",
    envSeparator: ",",
  }),
}
```

## Positional Args

Positional args use scalar carriers and are declared separately from flags.

```typescript
import { arg } from "strictcli";

app.command(
  defineCommand("copy", {
    help: "Copy a file",
    args: [
      arg("src", t.str, { help: "Source file" }),
      arg("dst", t.str, { help: "Destination file" }),
    ],
    handler: (args, ctx) => {
      ctx.info(`Copying ${args.src} to ${args.dst}`);
    },
  }),
);
```

Args are required by default. Set `required: false` to make an arg optional (it can then have a `default`).

```typescript
args: [
  arg("path", t.str, { help: "Project directory", required: false }),
]
```

### Variadic Args

A variadic arg collects all remaining positional tokens into an array. It must be the last arg, and uses a scalar carrier with `variadic: true`.

```typescript
args: [
  arg("target", t.str, { help: "Deploy target" }),
  arg("files", t.str, { help: "Files to process", variadic: true }),
]
```

## Flag Sets

`flagSet` groups reusable flags that can be shared across commands. The flags appear in the handler args alongside direct flags.

```typescript
import { flagSet } from "strictcli";

const pagination = flagSet("pagination", {
  page: flag("page", t.int, { help: "Page number", default: 1n }),
  per_page: flag("per-page", t.int, { help: "Items per page", default: 20n }),
});

app.command(
  defineCommand("list-users", {
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

`mutexGroup` declares flags where exactly one must be provided. Providing none or more than one is an error. Unset members are absent from the handler args.

```typescript
import { mutexGroup } from "strictcli";

app.command(
  defineCommand("fetch", {
    help: "Fetch data from a source",
    mutex: [
      mutexGroup({
        file: flag("file", t.str, { help: "Read from file", default: null }),
        url: flag("url", t.str, { help: "Read from URL", default: null }),
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

Declare relationships between flags.

```typescript
import { requires, coRequired, implies } from "strictcli";

app.command(
  defineCommand("deploy", {
    help: "Deploy the service",
    flags: {
      target: flag("target", t.str, { help: "Deploy target" }),
      region: flag("region", t.str, { help: "AWS region" }),
      dry_run: flag("dry-run", t.bool, { help: "Dry run mode", default: false }),
      confirm: flag("confirm", t.bool, { help: "Confirm deploy", default: false }),
    },
    dependencies: [
      // --target requires --region to also be provided
      requires({ flag: "target", dependsOn: "region" }),
      // --target and --region must appear together
      coRequired(["target", "region"]),
      // When --dry-run is set, auto-set --confirm to true
      implies({ flag: "dry-run", implies: "confirm", value: true }),
    ],
    handler: (args, ctx) => {
      ctx.info(`Deploying to ${args.target} in ${args.region}`);
    },
  }),
);
```

## Command Groups

Groups organize commands into namespaces. Groups nest to arbitrary depth.

```typescript
const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "Infrastructure management tool",
});

const dns = app.group("dns", { help: "Manage DNS records" });

dns.command(
  defineCommand("list", {
    help: "List all DNS records",
    handler: (args, ctx) => {
      ctx.info("Listing DNS records...");
    },
  }),
);

const zone = dns.group("zone", { help: "Manage DNS zones" });

zone.command(
  defineCommand("create", {
    help: "Create a new DNS zone",
    flags: {
      name: flag("name", t.str, { help: "Zone name" }),
    },
    handler: (args, ctx) => {
      ctx.info(`Creating zone: ${args.name}`);
    },
  }),
);
```

Usage: `mytool dns list`, `mytool dns zone create --name example.com`

### Group tags

Tags on a group are inherited by all commands in that group (merged with each command's own tags).

```typescript
const admin = app.group("admin", {
  help: "Admin commands",
  tags: ["admin"],
});
```

### Deprecated Commands

Register retired commands that print a message and exit 1.

```typescript
import { deprecated } from "strictcli";

app.deprecate(deprecated("old-deploy", "use 'deploy' instead"));
// Also works on groups:
dns.deprecate(deprecated("dump", "use 'list' instead"));
```

## Global Flags

Flags declared on the app apply to all commands. They can appear before or after the command name on the CLI.

```typescript
const app = createApp({
  name: "mytool",
  version: "0.1.0",
  help: "My tool",
  flags: {
    verbose: flag("verbose", t.bool, {
      help: "Enable verbose output",
      default: false,
    }),
    settings: flag("settings", t.str, {
      help: "Settings file path",
      default: "/etc/mytool/config.json",
    }),
  },
});
```

Global flag values are merged into each command handler's `args`.

## Passthrough Commands

Passthrough commands bypass all parsing. The handler receives raw args.

```typescript
import { passthrough } from "strictcli";

app.command(
  passthrough("exec", {
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

Usage: `mytool exec ls -la /tmp` -- the handler receives `["-la", "/tmp"]` (note: `ls` is consumed as part of the routing to `exec`; all tokens after the passthrough command name are raw args -- correction: all tokens after `exec` are in `pt.args`, so `["ls", "-la", "/tmp"]`).

## Flag Naming Conventions

strictcli enforces flag naming rules at registration time.

- **Bare `--force` is banned.** Use qualified names: `--force-overwrite`, `--force-delete`.
- **`--no-` prefix is reserved.** Flag names cannot start with `no-`. The `--no-` prefix is auto-generated for negatable boolean flags.
- **Dashes to underscores.** Flags with dashes (`--dry-run`) become underscore keys in the handler args (`args.dry_run`). The flag map key must also use the underscore form.

```typescript
// The flag map key is the underscore form of the flag name
flags: {
  dry_run: flag("dry-run", t.bool, { help: "Dry run mode", default: false }),
  force_overwrite: flag("force-overwrite", t.bool, { help: "Force overwrite", default: false }),
}
```

## Schema Dump

Every strictcli app has a built-in `--dump-schema` flag. Running it writes the full CLI structure to `.strictcli/schema.json`.

```bash
mytool --dump-schema
```

Programmatically, use `app.dumpSchemaDict()` to get the schema as an object without writing to disk.

```typescript
const schema = app.dumpSchemaDict();
console.log(JSON.stringify(schema, null, 2));
```

## Testing

`app.test(argv)` runs the CLI in-process and captures stdout, stderr, exit code, and structured outcome data.

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

`app.call(commandPath, kwargs)` invokes a command in-process with pre-typed values, bypassing CLI parsing.

```typescript
// Dot-separated path for nested commands
const result = await app.call("dns.zone.create", { name: "example.com" });
```

Failures throw `InvokeError`.

## TypeScript Type Safety

The type system infers the exact shape of the handler's `args` parameter from flag and arg declarations. No manual type annotations are needed.

```typescript
app.command(
  defineCommand("deploy", {
    help: "Deploy the service",
    flags: {
      target: flag("target", t.str, { help: "Deploy target" }),
      replicas: flag("replicas", t.int, { help: "Replica count" }),
      verbose: flag("verbose", t.bool, { help: "Verbose", default: false }),
      tag: flag("tag", t.str, { help: "Tag", default: null }),
    },
    args: [arg("service", t.str, { help: "Service name" })],
    handler: (args) => {
      // TypeScript knows the exact type of args:
      //   args.target    -> string         (required)
      //   args.replicas  -> bigint         (required)
      //   args.verbose   -> boolean        (has default)
      //   args.tag       -> string | undefined  (default: null = optional)
      //   args.service   -> string         (positional arg)
    },
  }),
);
```

The type carriers (`t.str`, `t.int`, etc.) carry phantom types that flow through the generic machinery in `defineCommand` and `flag`/`arg`, so the output types are correct without casts. Flags from `flagSets` and `mutexGroup` entries are also merged into the handler args type.

## Complete Example

```typescript
import {
  createApp,
  defineCommand,
  deprecated,
  flag,
  flagSet,
  mutexGroup,
  arg,
  outcome,
  passthrough,
  t,
} from "strictcli";

const app = createApp({
  name: "deploy",
  version: "0.1.0",
  help: "Deployment management tool",
  envPrefix: "DEPLOY",
  flags: {
    verbose: flag("verbose", t.bool, {
      help: "Enable verbose logging",
      default: false,
    }),
  },
});

const common = flagSet("common", {
  region: flag("region", t.str, {
    help: "Cloud region",
    env: "DEPLOY_REGION",
    choices: ["us-east-1", "eu-west-1", "ap-south-1"],
  }),
});

app.command(
  defineCommand("run", {
    help: "Deploy a service",
    flags: {
      replicas: flag("replicas", t.int, { help: "Number of replicas", default: 1n }),
      tag: flag("tag", t.list(t.str), { help: "Tags for the deployment" }),
    },
    flagSets: [common],
    args: [arg("service", t.str, { help: "Service to deploy" })],
    handler: (args, ctx) => {
      ctx.info(`Deploying ${args.service} to ${args.region}`);
      ctx.info(`Replicas: ${args.replicas}`);
      if (args.tag.length > 0) {
        ctx.info(`Tags: ${args.tag.join(", ")}`);
      }
      return outcome(0, { service: args.service, replicas: args.replicas });
    },
  }),
);

const infra = app.group("infra", { help: "Infrastructure commands" });

infra.command(
  defineCommand("status", {
    help: "Show infrastructure status",
    flagSets: [common],
    handler: (args, ctx) => {
      ctx.info(`Status for region: ${args.region}`);
    },
  }),
);

infra.command(
  defineCommand("logs", {
    help: "View infrastructure logs",
    mutex: [
      mutexGroup({
        service: flag("service", t.str, { help: "Filter by service", default: null }),
        node: flag("node", t.str, { help: "Filter by node", default: null }),
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
  passthrough("exec", {
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

Every strictcli app automatically has these reserved flags (you cannot register them yourself):

- `--help` / `-h` -- show help for the app, group, or command
- `--version` / `-v` -- print the app version
- `--dump-schema` -- write `.strictcli/schema.json` and print the path
- `--hermetic` -- skip env var and config file resolution (values come only from CLI tokens and defaults)
- `--config <path>` -- use a specific config file (when config is enabled)
- `--mcp` -- start an MCP JSON-RPC 2.0 server on stdin/stdout
