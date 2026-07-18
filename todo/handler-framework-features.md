# Handler framework features (successor to handler-redesign-remaining.md)

The parent todo's 7 items included Context (item 1) and Outcome (item 7), both
shipped in the v0.29.0 + v0.23.0 coordinated breaking release (2026-07-17). The
remaining 5 items are independent future features, none blocking anything:

## 1. Framework-owned global flags (--quiet, --verbose, --output)

Standardized global flags that all consumers get for free. --quiet suppresses
non-error output; --verbose enables detailed output; --output controls format
(text/json/table). These interact with Context's Info/Warn/Debug methods — quiet
suppresses Info, verbose enables Debug.

## 2. Subprocess control

A Context-mediated subprocess helper that inherits the framework's signal handling,
timeout, and env-var injection. Replaces ad-hoc subprocess.run calls in handlers
with a structured, testable wrapper.

## 3. Env var injection

Declared env vars that the framework sets before handler invocation (e.g.,
APP_VERSION, APP_CONFIG_DIR). Currently consumers derive these ad-hoc.

## 4. Pure parse mode

A mode that parses and validates argv without executing the handler — returns the
resolved command + kwargs. Useful for completion engines, documentation generators,
and dry-run implementations.

## 5. Typed handler inputs

Replace `map[string]interface{}` (Go) and `**kwargs` (Python) with typed structures
derived from flag/arg declarations. Go: struct-tag-based (the old RegisterHandler
mechanism, but as a parsing layer, not a registration style). Python: dataclass or
TypedDict generation. Subsumes Get[T]/GetOpt[T] for consumers who want compile-time
type safety.

## Effort

Each item is a small-to-medium independent feature. Items 1 and 4 are the most
requested by consumers.
