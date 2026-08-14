# strictcli

Strict CLI framework for TypeScript — declare everything, infer nothing.

strictcli takes the opposite stance from convention-over-configuration CLI
libraries: every command, flag, argument, type, default, and help string is
declared explicitly, and anything left unstated is a hard error at registration
time. No implicit defaults, no guessed types, no silently ignored input. The
result is a CLI whose behavior is fully determined by its declaration.

This package is the **native TypeScript implementation**: pure ESM, Node >= 22,
with full static type inference from flag declarations all the way to handler
arguments — declare `flag("count", t.int, { help: "...", presence: "required" })`
and your handler's `args.count` is a `bigint`, checked by the compiler.

There are Python and Go implementations too, and this one is not a port of
either. The surface here is TypeScript's own — flag and arg options are a
discriminated union on `presence`, so a `default` written beside
`presence: "required"` does not compile and a `presence: "default"` without a
`default` does not either, and the twin command factories narrow the handler's
`ctx`, making a `.write()` inside a read-only command a compile error. That
share of the enforcement reaching the compiler is TypeScript's alone; the
runtime checks every implementation carries are still there underneath. What the
three hold identical is behavior: the same semantics, the same help bytes, the
same schema, and the same error sentence with TypeScript's spellings inside it.

## Install

```sh
npm install strictcli
```

## Usage

Types are carriers (`t.str`, `t.bool`, `t.int`, `t.float`, plus `t.list(...)`
and `t.dict(...)`) that bind the schema, the runtime parser, and the inferred
TypeScript type in one value, so they cannot drift apart:

```ts validate
import { arg, createApp, defineMutatingCommand, flag, t } from "strictcli";

const app = createApp({
	name: "myapp",
	version: "1.0.0",
	help: "my cool app",
});

app.command(
	defineMutatingCommand("build", {
		help: "Build the project",
		flags: {
			count: flag("count", t.int, {
				help: "How many times to build",
				presence: "required",
			}),
			label: flag("label", t.str, {
				help: "Build label",
				presence: "default",
				default: "dev",
			}),
		},
		args: [
			arg("values", t.float, {
				help: "Input values",
				variadic: true,
				presence: "required",
			}),
		],
		handler: (args, ctx) => {
			// Inferred: args.count is bigint, args.label is string, args.values is number[]
			ctx.info(`building ${args.count} time(s) as ${args.label}`);
			if (ctx.dryRun) {
				ctx.info("(preview only)");
			}
			return 0;
		},
	}),
);

app.run(process.argv.slice(2));
```

Commands are registered through the **twin factories**: `defineReadOnlyCommand`
for commands that change nothing, `defineMutatingCommand` for commands that do.
Classification is mandatory and has no default, so the factory name *is* the
classification, and a read-only command's handler `ctx` is narrowed such that
calling a mutating effect on it is a compile error.

Every flag and every arg declares **exactly one** of three facts about itself:
`presence: "required"` (a value must be supplied), `presence: "optional"`
(absence is legal and arrives as `undefined`), or `presence: "default"` with a
`default` value the framework supplies when nothing else does. Declaring none
of the three, or two of them, is a registration-time hard error, and nothing
about presence is inferred from the shape of another declaration. An optional
declaration is what makes a key optional in the inferred handler-args type, and
`ctx.provided(name)` answers whether the invocation — CLI, env, config or an
implication — supplied the value, rather than the declaration.

Note that `--dry-run`, `--approve-consequential`, `--quiet` and `--verbose` are
framework-owned names. You never declare them; their values arrive on the
context as `ctx.dryRun`, `ctx.approveConsequential`, `ctx.quiet` and
`ctx.verbose`.

## Features

- **Strict four-type system** — `str`, `bool`, `int`, `float`, with `int` backed
  by `bigint` for full 64-bit signed integer range and strict parsing (no
  whitespace, no overflow wraparound).
- **Static handler-arg inference** — dash-named flags (`--dry-run`) arrive as
  underscore keys (`dry_run`) with exact types and true optional-key modifiers,
  derived entirely from the declarations.
- **Mandatory help everywhere** — missing help text on any app, group, command,
  flag, or argument is a registration-time error.
- **Mandatory effect classification** — every command is registered through
  `defineReadOnlyCommand` or `defineMutatingCommand` (and passthroughs through
  `readOnlyPassthrough` / `mutatingPassthrough`). There is no default and no
  inference from names, tags, or handler bodies.
- **Honest dry runs** — `ctx.effects` mints eight recorded operations (`run`,
  `spawn`, `write`, `mkdir`, `remove`, `rename`, `chmod`, `http`). Under
  `--dry-run` they are recorded rather than performed and rendered as a would-do
  log. A command whose preview would lie declares `dryRunSupported: false` with
  a mandatory reason, and `--dry-run` is refused at parse time instead.
- **A confirm protocol you opt into** — `consequential: true` is the only thing
  that makes the framework prompt before dispatch; `--approve-consequential`
  answers it in advance, and a non-interactive stdin without it is a hard error
  rather than a hang.
- **Env var and JSON config file resolution** — explicit precedence:
  CLI > env > config > default, with auto-registered `config show/set/path/edit`
  subcommands.
- **First-class check system** — TOML-declared checks with double-entry
  registration, tag DSL selection, DAG-ordered execution.
- **MCP server integration** — expose commands as Model Context Protocol tools.
- **Schema dump** — every app answers `--dump-schema` with a machine-readable
  JSON description of its full structure, at `schema_version: 2`. Every flag and
  arg entry carries a `value_schema`: a real JSON Schema fragment from a closed
  subset of `type`, `items`, `additionalProperties` and `enum`, using JSON
  Schema's own type names. Arity is part of the value's shape, so a `t.list(...)`
  flag and a variadic arg publish the identical array fragment. A choice flag
  carries no fragment — its value is a variant the subset cannot express — and
  publishes its nested `choices` and scopes instead, each scoped entry a full
  flag entry, with `elect_by` marking the spelling. Keys are emitted in a
  declared order at every depth and the document is written in one canonical
  encoding, so a schema file written by this implementation and one written by
  the Python or Go implementation for the same declaration are byte-identical.
- **Groups, passthrough commands, deprecation notices, mutex/co-required/implies
  dependencies** — the complete strictcli surface.

## Sibling implementations

strictcli is developed in the [smm-h/strictcli](https://github.com/smm-h/strictcli)
monorepo alongside first-class **Python** (PyPI: `strictcli`) and **Go**
implementations. All implementations are kept byte-identical in behavior — same
error messages, same help output, same parsing rules — enforced by a shared
cross-language conformance suite.

## License

MIT
