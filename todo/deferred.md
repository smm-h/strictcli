# Deferred Features

Features discussed during initial design (2026-05-12) and explicitly deferred from v1.

## Command aliases

Per-command aliases (e.g. `init` -> `scaffold`). Shown in help as `scaffold (alias: init)`. API: `@app.command('scaffold', aliases=['init'], help='...')`.

## Colored help output

Color when stdout is a TTY, plain when piped. ANSI codes directly (no dependency). Auto-detect via `os.isatty`. Currently help is plain text only.

## Configurable error catching

`App(catch_errors=True)` wraps handler dispatch in try/except, prints clean error to stderr, exits 1. Default off (handler exceptions propagate). Useful for production CLIs that don't want tracebacks.
