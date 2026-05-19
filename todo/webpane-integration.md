# webpane integration for auto-registered commands

## Context

webpane is a library with no CLI of its own. When a project uses both webpane and strictcli, strictcli should auto-detect the webpane dependency and register common commands so the user gets a working CLI for free without writing boilerplate.

## Proposed auto-registered commands

- `serve` -- start the app in headless mode (browser-based, no native window) via `webpane.serve()`
- `run` -- start the app in desktop mode (native window via pywebview) via `webpane.run()`
- `install-desktop` / `uninstall-desktop` -- create or remove platform-native desktop entries (`.desktop` files on Linux, app bundles on macOS) via `webpane.create_entry()` / `webpane.remove_entry()`

## Detection mechanism

Check if `webpane` is in the project's installed packages via `importlib.metadata`. If found, register the commands automatically. If not found, do nothing -- no error, no warning.

This keeps the dependency optional: strictcli never imports webpane at module level, only when the auto-registered command is actually invoked.

## Consumer tiers

Three levels of integration, each a superset of the previous:

1. **Just webpane** (no CLI): the project calls `webpane.serve()` or `webpane.run()` directly from its own code. No strictcli involvement.
2. **webpane + strictcli** (free commands): strictcli auto-detects webpane and registers `serve`, `run`, `install-desktop`, `uninstall-desktop`. The project gets a working CLI with zero command definitions.
3. **webpane + strictcli + custom commands**: the project defines its own strictcli commands alongside the auto-registered ones. Custom commands can override the defaults if needed.

## Effort

Medium. The detection and registration logic is straightforward. The main work is designing the interface between strictcli's command registration and webpane's API surface so the auto-registered commands accept the right flags (port, host, window size, etc.) without hardcoding assumptions about webpane's internals.
