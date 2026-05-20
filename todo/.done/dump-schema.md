# --dump-schema flag and schema.json generation

Implemented. Both Python and Go auto-inject `--dump-schema` into every App. When triggered, serializes the full CLI structure (commands, groups, flags, args, tags, mutex, dependencies, passthrough, deprecated) to `.strictcli/schema.json`.

Work items completed:
- schema.json format designed and implemented (both languages produce the same structure)
- `--dump-schema` flag in Python App (auto-injected, writes .strictcli/schema.json)
- `--dump-schema` flag in Go App (same behavior, same format)
- Tests in both languages verify serialization correctness
