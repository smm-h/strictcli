# Integrate migrable into strictcli's config system

## Problem

strictcli has a config loader (reads TOML/JSON, validates types, generates `config show/set/path/edit` commands). migrable has config schema versioning and migration (version tracking, migration discovery, atomic writes). They're separate — rlsbl bridges them manually by shelling out to `migrable` CLI.

Every strictcli consumer that needs versioned config (rlsbl, veliu-dev, potentially others) must wire up migrable themselves. This should be built into strictcli.

## Desired behavior

When strictcli loads a config file:

1. Read the file
2. Check `_schema_version` field
3. If version is behind the app's current schema version, run pending migrations (via migrable's engine)
4. Validate the migrated config against registered flags
5. Proceed with the (now up-to-date) config

Apps declare their schema version and provide migration files. strictcli + migrable handle the rest.

## Also needed: "required, no default" enforcement

strictcli currently defaults missing flags to None/False/[]. For security-sensitive config (encryption keys, API credentials, DB connection strings), a missing value should be a hard error, not a silent default. This is needed alongside migrations.

## Also needed: bootstrap validation

On first run, if no config file exists, strictcli should either:
- Error with a clear message listing required fields
- Run an interactive setup (`vd config init`) that prompts for required values
- Generate a template config with comments explaining each field

## Consumers that would benefit

- rlsbl (currently shells out to migrable manually)
- veliu-dev (needs versioned config + required fields)
- Any future strictcli app with evolving config

## Scope

This touches both Python and Go implementations (must stay in sync via conformance tests).
