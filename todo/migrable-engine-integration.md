# Integrate migrable's migration engine into strictcli's config system

## Problem

strictcli now has first-class config fields with required enforcement and template generation. The missing piece is automatic schema migration: when an app's config schema evolves between versions, the config file should be migrated to match.

## What's needed

1. Auto-register `_schema_version` as a framework-owned config field
2. Check `_schema_version` at startup, before config field validation
3. If version is behind, print actionable error: "Config schema version X.Y.Z is behind expected A.B.C. Run `myapp config migrate` to upgrade." Exit 1.
4. Add `config migrate` subcommand that runs the migration engine
5. Define `ConfigMigrator` interface (Python Protocol / Go interface) that migrable implements
6. Apps wire migrable via constructor: `App(..., migrator=MigrableAdapter(migrations_path))`

## Blocked on

migrable becoming a dual-language project (Python port alongside Go engine). Currently migrable is Go-only with a thin Python CLI wrapper.

## Consumers that would benefit

- rlsbl (currently shells out to migrable CLI)
- howmuchleft (currently uses migrable Go library directly)
- Any future strictcli app with evolving config
