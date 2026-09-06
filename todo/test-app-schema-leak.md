# Test-app schema leaks into python/.strictcli/schema.json

## Context

`--dump-schema` writes an app's schema to `.strictcli/schema.json` inside the
project it runs in. For the framework repo itself, `python/.strictcli/` is not
a real app's schema home -- strictcli is a library and ships no CLI of its own.

## Problem

A test-app schema (name `test`, project_id `testapp`, version `1.0.0`, one
command `cmd`) keeps appearing at `python/.strictcli/schema.json`:

- It was committed once by mistake and removed in commit `33da76ce` ("chore:
  drop the leaked test-app schema under python/"), and `python/.gitignore`
  now ignores `.strictcli/`.
- Yet the file exists on disk again, so something in the test or dev flow
  still writes a demo/test app's schema dump into the repo's real schema
  path instead of a temp directory.

Consequence: any tool that enumerates on-disk `.strictcli/schema.json` files
to answer "what CLIs does this repo define" misreads the repo as shipping a
CLI named `test`. The gitignore hides the symptom from git, not from the
filesystem.

## Solutions

1. Find the writer (a test fixture, doc example, or dev invocation running
   the schema dump with cwd under `python/`) and point it at a temp
   directory, then delete the stray file.
   Pros: fixes the class at the source; the gitignore entry may become
   removable afterwards.
   Cons: requires locating the writer.
2. Only delete the stray file.
   Pros: one command.
   Cons: it comes back.

## Affected files

- `python/.strictcli/schema.json` (the stray artifact)
- `python/.gitignore` (the `.strictcli/` ignore entry -- possibly removable
  once nothing writes there)
- whatever test/dev code invokes the schema dump under `python/`

## Effort

Small: locate the writer (grep for schema-dump invocations under `python/`),
redirect it to a temp directory, delete the artifact.
