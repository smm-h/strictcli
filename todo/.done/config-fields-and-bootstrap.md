# Config fields, required enforcement, and bootstrap validation

Split from `integrate-migrable-config.md`. These parts are now implemented.

## "Required, no default" enforcement

strictcli now has first-class `ConfigField` declarations with required/optional semantics. Fields without a default are required -- a missing value is a hard error at startup, not a silent default. Both Python and Go implementations.

## Bootstrap validation

`config init` generates a template config file with documented fields. TOML format includes help text as comments and REQUIRED markers. JSON format uses null for required fields and defaults for optional ones. Errors if config file already exists.

## Config field system

- `app.config_field(name, type, help, default=...)` declaration API
- Per-command config field binding (`config_fields=[...]`)
- Startup validation: missing required, unknown keys, type mismatch
- Config subcommand exemption from validation
- `config show` and `config set` support config fields
- Schema serialization includes config fields
- Dot-names for TOML section namespacing
