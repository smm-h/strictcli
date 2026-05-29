# Comma-separated values for repeatable flags

## Feature request

When a flag is defined with `repeatable=True`, also accept comma-separated values in a single invocation. Both syntaxes should be interchangeable and produce the same flat list:

```bash
# Multiple invocations (already works)
--run-id 123 --run-id 456

# Comma-separated in a single invocation (requested)
--run-id 123,456
```

The flag's handler should receive the same flat list (`["123", "456"]`) regardless of which syntax was used. Mixed usage should also work:

```bash
--run-id 123,456 --run-id 789
# handler receives: ["123", "456", "789"]
```

## Motivation

Without this, consumers that want comma-separated convenience must manually split values after parsing, which is a hacky workaround that duplicates logic across every caller. Handling this at the framework level keeps the splitting consistent and removes boilerplate from downstream tools.

## Scope

- Applies to all repeatable flags regardless of value type
- For typed repeatables (e.g., `type=int`), the type conversion should apply to each comma-separated element individually
- No ambiguity concerns: commas are not valid in integers, SHAs, package names, or other typical repeatable flag values
