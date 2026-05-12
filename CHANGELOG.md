# Changelog

## 0.2.0

- npm thin wrapper: `npm install excli` installs the Python package via uv/pip

## 0.1.0

- Decorator-based command registration with `@app.command` and `@excli.flag`/`@excli.arg`
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
