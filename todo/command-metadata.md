# Command tags for capability labeling

## Problem

strictcli has no way to annotate commands with capability labels. safegit has a global `--json` flag but only 3 of ~20+ commands produce JSON output. Without tags, there's no clean way to error when `--json` is passed to a command that doesn't support it — non-JSON commands produce silence on stdout, confusing consumers.

## Design

### Tags are string labels, not key-value pairs

Commands get a `tags` parameter accepting `set[str]`. No values — just labels.

```python
@app.command("scrub match", help="...", tags={"json", "destructive"})
```

```go
app.Command("scrub match", "...", handler,
    WithTags("json", "destructive"),
)
```

Tag names: restricted to `[a-z][a-z0-9_-]*` (same pattern as check names). Validated at registration time.

### Group inheritance

Tags on groups propagate to all commands under that group. A command's effective tags are its own tags plus all ancestor group tags.

```python
g = app.group("admin", help="...", tags={"admin"})
g.command("reset", help="...", tags={"destructive"})
# "reset" has effective tags: {"admin", "destructive"}
```

### Tag contracts (registration-time enforcement)

Consumers can register tag contracts — structural rules that are validated at registration time.

A tag contract declares that any command with a given tag must satisfy certain conditions:
- **requires_flag_set**: the command must include a specific FlagSet
- **requires_flag**: the command must have a specific flag name

Example: the "json" tag means the command must have the `--json` flag (from a FlagSet):

```python
app.tag_contract("json", requires_flag="json")
```

If a command is tagged "json" but doesn't have a `--json` flag, registration fails with a clear error. This catches configuration mistakes at startup, not runtime.

No runtime enforcement — strictcli does not intercept handler output.

### Schema

Tags appear in `--dump-schema` output:

```json
{"name": "scrub match", "help": "...", "tags": ["destructive", "json"], "flags": [...]}
```

Effective tags (including inherited from groups) are serialized.

## Affected surfaces

- Python: `@app.command()` and `group.command()` get `tags=` parameter, `app.tag_contract()` method
- Go: `WithTags(tags ...string)` option function (on both Command and Group), `app.TagContract()` method
- Conformance: schema update, code generators, harness, test cases
- `--dump-schema`: includes `tags` array on commands

## Effort

Medium. Tag storage and inheritance are small. Tag contracts add validation logic to `_build_and_validate_command` / the Go equivalent. Conformance and cross-language parity are the bulk of the work.
