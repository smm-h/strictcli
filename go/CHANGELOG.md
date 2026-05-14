# Changelog

## 0.1.0

- Decorator-style command registration with App.Command()
- String, bool, and int flag types with short aliases
- Positional arguments (required and optional with defaults)
- Two-level command nesting via App.Group()
- Environment variable support with prefix enforcement
- Tags: reusable flag bundles
- Mutex groups for mutually exclusive flags
- Choices validation for flags
- Custom validation callbacks
- Repeatable flags
- App-level global flags (parsed before and after command name)
- Variadic positional args
- Passthrough commands for wrapper CLIs
- Handler returns int as exit code
- Auto-generated help at app, group, and command levels
- app.Test() for in-process testing
- Zero external dependencies

## 0.0.0

- Initial release
