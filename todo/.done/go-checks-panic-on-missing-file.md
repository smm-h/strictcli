# strictcli Go panics when .strictcli/checks.toml is missing

## Problem

`strictcli.NewApp()` panics with `checks_path does not exist: .strictcli/checks.toml` when the file doesn't exist in the working directory. This happens in production when a Go binary using strictcli is deployed without its `.strictcli/` directory.

## Reproduction

1. Build a Go binary that uses strictcli (e.g., `gamehome/router`)
2. Deploy the binary to a server without copying `.strictcli/checks.toml`
3. Run the binary — panics immediately

## Expected behavior

If `.strictcli/checks.toml` doesn't exist, the app should either:
- Use an empty/default checks config (no checks registered)
- Log a warning and continue
- Accept a `--checks-path` flag to override the location

It should NOT panic. A missing config file is a deployment issue, not a crash-worthy error.

## Impact

Blocked the gamehome automated deploy pipeline. The router binary was correctly cross-compiled and deployed but panicked because `.strictcli/checks.toml` wasn't alongside it. Had to manually create the file on the server.

## Workaround

Copy the `.strictcli/checks.toml` from the source directory alongside the deployed binary, and ensure the systemd service has `WorkingDirectory` set to where the file lives.
