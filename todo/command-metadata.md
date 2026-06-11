# Command metadata for capability tagging

## Problem

strictcli's `Command` struct has no extensible metadata field. The `Tag` type is for reusable flag bundles, not arbitrary annotations. There's no way to tag a command with capabilities like "supports --json output" that can be checked at runtime.

safegit has a global `--json` flag but only some commands (scrub match, scrub file, rewrite-author) produce JSON output. Without metadata tagging, there's no clean way to error when `--json` is passed to a command that doesn't support it. Currently non-JSON commands produce silence on stdout, which is confusing for consumers.

## Expected behavior

Commands should be taggable with arbitrary key-value metadata:

```go
app.Command("scrub match", "...", handler,
    strictcli.WithMetadata("json", "true"),
    strictcli.WithFlags(...),
)
```

At runtime, the handler (or a global middleware) can check:

```go
if globals["json"].(bool) && !cmd.Metadata["json"] {
    die("this command does not support --json")
}
```

## Implementation

Add to `Command` struct:
- `Metadata map[string]string` field

Add `CmdOption`:
- `WithMetadata(key, value string) CmdOption`

The metadata is purely informational — strictcli doesn't interpret it. Consumers (like safegit) define their own keys and check them in handlers or global wrappers.

## Effort

Small. One struct field, one option function, no parsing changes.
