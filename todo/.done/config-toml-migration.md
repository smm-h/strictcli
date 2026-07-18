# Migrate config files from JSON to TOML

## Context

Config file support (see config-file-support.md) initially uses JSON for reading and writing config files. This avoids third-party dependencies since both Python and Go have stdlib JSON support.

TOML is the better format for human-edited config files (comments, cleaner syntax, no trailing commas).

## Migration path

1. Add `tomlkit` as a dependency of strictcli (Python) -- zero-dep, pure Python, comment-preserving TOML library (used by Poetry, actively maintained, TOML 1.1.0 compliant)
2. Add `go-toml-edit` as a dependency of go-strictcli
3. Switch config file format from JSON to TOML
4. Read: use `tomlkit.load()` (Python) / `go-toml-edit` (Go)
5. Write: use `tomlkit.dump()` (Python) / `go-toml-edit` (Go) -- preserves comments and formatting
6. Add migration logic: if a JSON config exists, read it and write a TOML config on first use
7. `config set` writes via tomlkit/go-toml-edit to preserve existing comments

## Why tomlkit (not a custom py-toml-edit)

tomlkit checks every requirement: comment preservation, formatting preservation, individual value modification, TOML 1.1.0 compliance, pure Python, zero dependencies, Python 3.9-3.14, active maintenance. Building py-toml-edit would be reinventing it.

## Depends on

- tomlkit (PyPI, already published)
- go-toml-edit (already exists and is published)
