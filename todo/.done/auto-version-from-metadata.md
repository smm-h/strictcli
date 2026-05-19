# Auto-detect version from package metadata

## Problem
Every project using strictcli + rlsbl has to manually keep the `App(version="X.Y.Z")` string in sync with the version in pyproject.toml. rlsbl bumps pyproject.toml at release time, but the hardcoded version in the CLI source file gets stale.

Example from claudestream:
```python
app = strictcli.App(
    name="claudestream",
    version="0.1.0",  # stale after rlsbl bumps to 0.1.1
    help="Stream Claude Code's JSON protocol",
)
```

## Solution
Make `version` optional on `App`. When `None`, auto-read from `importlib.metadata.version(name)`:

```python
class App:
    def __init__(self, name, version=None, help="", ...):
        if version is None:
            import importlib.metadata
            try:
                version = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                version = "unknown"
        self.version = version
```

This way projects just write `App(name="claudestream", help="...")` and the version is always correct as long as the package is installed.

## Affected files
- `strictcli/__init__.py` (App class constructor)

## Effort
Trivial -- a few lines in the constructor.
