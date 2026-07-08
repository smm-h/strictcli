# Public in-process accessor for the CLI schema dump

## Problem

The full CLI schema (the structure written to `.strictcli/schema.json`) can only
be obtained today by:

- the `--dump-schema` global flag, which does not return the dict — it raises an
  internal sentinel caught by an internal writer that writes
  `cwd/.strictcli/schema.json` (so a caller must chdir to a temp dir to avoid
  clobbering the committed file); or
- calling the private `_dump_schema`/`_write_schema` internals directly.

There is a public `App.json_schema(command_path)` method, but it returns a
per-command JSON Schema for input validation — not the full CLI dump structure
(the one with the command/group/flag catalog). So there is no clean public way to
get the dump as an in-process dict.

## Why this matters

Consumers that want to assert their committed `.strictcli/schema.json` is fresh
(equal to a freshly-generated dump, ignoring the version field) currently have to
either shell out to `--dump-schema` into a temp cwd or reach into private
internals. A freshness/drift test is exactly the kind of guard projects should
have (it catches "edited the CLI but forgot to re-dump" and version lag), but the
lack of a public accessor forces fragile coupling.

## Suggested fix

Add a public method that returns the full dump structure as a dict in-process,
e.g. `App.dump_schema_dict() -> dict` (the same structure `--dump-schema` writes),
without touching the filesystem or the cwd. Optionally also allow
`--dump-schema` to write to a caller-specified path rather than always `cwd`.

## Consumer benefit

A project's freshness test could then be:
`assert normalize(app.dump_schema_dict()) == normalize(committed_schema)` —
no subprocess, no temp-cwd dance, no private imports.

## Effort estimate

Small: expose the existing internal dump builder as a public method returning the
dict.
