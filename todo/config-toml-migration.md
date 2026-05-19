# Migrate config files from JSON to TOML

## Context

Config file support (see config-file-support.md) initially uses JSON for reading and writing config files. This avoids third-party dependencies since both Python and Go have stdlib JSON support.

TOML is the better format for human-edited config files (comments, cleaner syntax, no trailing commas). Once a comment-preserving Python TOML library exists (see go-toml-edit/todo/python-sibling.md), config files should migrate from JSON to TOML.

## Migration path

1. Build py-toml-edit (Python sibling of go-toml-edit) in a shared monorepo with conformance tests
2. Add py-toml-edit as a dependency of strictcli (Python)
3. Add go-toml-edit as a dependency of go-strictcli
4. Switch config file format from JSON to TOML
5. Add migration logic: if a JSON config exists, read it and write a TOML config on first use

## Depends on

- py-toml-edit being built and published
- go-toml-edit already exists and is published
