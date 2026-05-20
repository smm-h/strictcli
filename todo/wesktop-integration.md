# wesktop integration for auto-registered commands

## Context

wesktop is a library with no CLI of its own. When a project uses both wesktop and strictcli, strictcli should auto-detect the wesktop dependency and register common commands so the user gets a working CLI for free without writing boilerplate.

## Proposed auto-registered commands

- `serve` -- start the app in headless mode (browser-based, no native window) via `wesktop.serve()`
- `run` -- start the app in desktop mode (native window via pywebview) via `wesktop.run()`
- `install-desktop` / `uninstall-desktop` -- create or remove platform-native desktop entries (`.desktop` files on Linux, app bundles on macOS) via `wesktop.create_entry()` / `wesktop.remove_entry()`

## Detection mechanism

Check if `wesktop` is in the project's installed packages via `importlib.metadata`. If found, register the commands automatically. If not found, do nothing -- no error, no warning.

This keeps the dependency optional: strictcli never imports wesktop at module level, only when the auto-registered command is actually invoked.

## Consumer tiers

Three levels of integration, each a superset of the previous:

1. **Just wesktop** (no CLI): the project calls `wesktop.serve()` or `wesktop.run()` directly from its own code. No strictcli involvement.
2. **wesktop + strictcli** (free commands): strictcli auto-detects wesktop and registers `serve`, `run`, `install-desktop`, `uninstall-desktop`. The project gets a working CLI with zero command definitions.
3. **wesktop + strictcli + custom commands**: the project defines its own strictcli commands alongside the auto-registered ones. Custom commands can override the defaults if needed.

## Effort

Medium. The detection and registration logic is straightforward. The main work is designing the interface between strictcli's command registration and wesktop's API surface so the auto-registered commands accept the right flags (port, host, window size, etc.) without hardcoding assumptions about wesktop's internals.
