# strictcli

Strict CLI framework for TypeScript — declare everything, infer nothing.

strictcli takes the opposite stance from convention-over-configuration CLI
libraries: every command, flag, argument, type, default, and help string is
declared explicitly, and anything left unstated is a hard error at registration
time. No implicit defaults, no guessed types, no silently ignored input. The
result is a CLI whose behavior is fully determined by its declaration.

This package is the **native TypeScript implementation**: pure ESM, Node >= 22,
with full static type inference from flag declarations all the way to handler
arguments — declare `flag("count", t.int, { required: true })` and your
handler's `args.count` is a `bigint`, checked by the compiler.

## Install

```sh
npm install strictcli
```

## Usage

Types are carriers (`t.str`, `t.bool`, `t.int`, `t.float`, plus `t.list(...)`
and `t.dict(...)`) that bind the schema, the runtime parser, and the inferred
TypeScript type in one value, so they cannot drift apart:

```ts
import { arg, command, createApp, flag, t } from "strictcli";

const build = command("build", {
	help: "Build the project",
	flags: [
		flag("dry-run", t.bool, { help: "Print actions without running", default: true }),
		flag("count", t.int, { help: "How many times to build", required: true }),
	],
	args: [arg("values", t.float, { help: "Input values", variadic: true })],
	handler: (args, ctx) => {
		// Inferred: args.dry_run is boolean, args.count is bigint, args.values is number[]
		ctx.info(`building ${args.count} time(s), dry-run=${args.dry_run}`);
		return 0;
	},
});

const app = createApp("myapp", {
	version: "1.0.0",
	help: "my cool app",
	commands: [build],
});

app.run(process.argv.slice(2));
```

## Features

- **Strict four-type system** — `str`, `bool`, `int`, `float`, with `int` backed
  by `bigint` for full 64-bit signed integer range and strict parsing (no
  whitespace, no overflow wraparound).
- **Static handler-arg inference** — dash-named flags (`--dry-run`) arrive as
  underscore keys (`dry_run`) with exact types and true optional-key modifiers,
  derived entirely from the declarations.
- **Mandatory help everywhere** — missing help text on any app, group, command,
  flag, or argument is a registration-time error.
- **Env var and JSON config file resolution** — explicit precedence:
  CLI > env > config > default, with auto-registered `config show/set/path/edit`
  subcommands.
- **First-class check system** — TOML-declared checks with double-entry
  registration, tag DSL selection, DAG-ordered execution.
- **MCP server integration** — expose commands as Model Context Protocol tools.
- **Schema dump** — every app answers `--dump-schema` with a machine-readable
  JSON description of its full structure.
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
