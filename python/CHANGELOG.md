# Changelog

## 0.2.0

- Integer flags: `type=int` on flags for automatic coercion and validation
- Choices: `choices=` on flags to restrict values to a predefined set
- Custom validation: `validate=` on flags for user-defined validation callbacks
- Repeatable flags: `repeatable=True` to collect multiple occurrences into a list
- Default values for positional arguments: `Arg` now accepts `default=` for optional positionals
- `MutexGroup`: declare mutually exclusive flag groups that error if more than one is provided

## 0.1.1

- Fix: str flag values starting with hyphen (e.g. `--offset -5`) no longer rejected

## 0.1.0

- Decorator-based command registration with `@app.command` and `@strictcli.flag`/`@strictcli.arg`
- npm thin wrapper: `npm install strictcli` installs the Python package via uv/pip
- Two-level command nesting via `app.group()` with `@group.command`
- First-class environment variable support with prefix enforcement and `prefixed=False` opt-out
- Tags: reusable flag bundles applied to commands
- Plain-text help generation at app, group, and command levels
- Automatic `--help`/`-h` and `--version`/`-v` handling
- `--no-X` negation for boolean flags with opt-out
- Short flag aliases (`-v`, `-t`, etc.)
- Mandatory help text on all elements (commands, groups, flags, args, env vars)
- Handler signature validation at registration time
- `app.run()` full lifecycle and `app.test(argv)` for testing
- `--` separator to stop flag parsing
