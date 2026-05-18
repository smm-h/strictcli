# Framework-level configuration file support

## Context

Multiple strictcli-based projects (ClaudeTimeline, rlsbl) need persistent configuration beyond CLI flags and env vars. Currently each project must implement its own TOML loading, precedence chain, and config management subcommands.

## Problem

Settings like host, port, model names, batch sizes are set-once-and-forget -- CLI flags are repetitive, env vars are invisible. A config file is the natural middle layer.

## Proposed feature

- TOML config file support with XDG-compliant paths (`~/.config/{app_name}/config.toml`)
- Auto-generated config schema from registered flags (strictcli already knows every flag's name, type, default, and env var)
- Precedence chain: CLI flag > env var > config file > code default
- Auto-generated subcommands: `config show` (with source attribution like `git config --show-origin`), `config set key value`, `config edit` (opens $EDITOR), `config path`
- Config validation using flag types and choices

## Pros

- Solves a universal need across all strictcli projects
- strictcli has all the metadata needed to auto-generate config schema
- Users get config management for free just by using strictcli

## Cons

- Adds TOML dependency (stdlib `tomllib` for reading since Python 3.11, `tomli_w` for writing)
- Introduces persistent state (currently stateless)
- Opinionated about file location, format, and precedence
- Consumes one of the 2 nesting levels for the `config` group

## Effort estimate

Medium -- the reading side is straightforward, writing/editing adds complexity, auto-generation from flag metadata requires careful design.
