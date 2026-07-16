# Implement Go runtime scope adapter

Go has the `scope` TOML field parsed and schema-dumped but no runtime execution (no SetScopeAdapter). Python has set_scope_adapter with context-projection + SkipCheck semantics. This is a deliberate asymmetry; build trigger is a first Go consumer needing runtime scope filtering.

## Scope

- Mirror Python's adapter contract in Go (SetScopeAdapter equivalent)
- Context-projection semantics
- SkipCheck semantics
- Add conformance cases covering scope adapter behavior

## Effort

Medium (mirror Python's adapter contract in Go + conformance cases).
