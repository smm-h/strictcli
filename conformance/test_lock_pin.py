#!/usr/bin/env python3
"""The conformance lockfile's editable-sibling pin must track python/'s version.

`conformance/pyproject.toml` resolves `strictcli` from the sibling checkout
(`[tool.uv.sources] strictcli = { path = "../python", editable = true }`), and
`uv.lock` records the version it saw when it was last resolved. Nothing refreshes
that automatically, so the recorded version drifts one release behind every time
python/ is released -- and a stale pin is not a harmless number: `uv sync
--frozen` (which the conformance-meta check itself runs) resolves against the
lock, so the suite can quietly run its Python target against a version the repo
no longer contains.

The fix is a refresh (`uv lock` in `conformance/`). This test is the guard that
makes the drift visible the moment it happens instead of at the next release.

Runnable under pytest (auto-discovered) or standalone
(`python3 test_lock_pin.py`).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

CONFORMANCE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CONFORMANCE_DIR.parent
LOCK_PATH = CONFORMANCE_DIR / "uv.lock"
SIBLING_MANIFEST = PROJECT_ROOT / "python" / "pyproject.toml"

# The dependency resolved from a sibling checkout rather than a registry, and
# the source string uv writes for it.
EDITABLE_PACKAGE = "strictcli"
EDITABLE_SOURCE = "../python"


def _locked_versions(package: str, editable_path: str) -> list[str]:
    """Every version the lock records for `package` from that editable source."""
    with open(LOCK_PATH, "rb") as fh:
        lock = tomllib.load(fh)
    return [
        entry["version"]
        for entry in lock.get("package", [])
        if entry.get("name") == package
        and entry.get("source", {}).get("editable") == editable_path
    ]


def _sibling_version(manifest: Path) -> str:
    with open(manifest, "rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_lock_records_exactly_one_editable_sibling_entry():
    versions = _locked_versions(EDITABLE_PACKAGE, EDITABLE_SOURCE)
    assert len(versions) == 1, (
        f"expected exactly one {EDITABLE_PACKAGE!r} entry sourced from "
        f"{EDITABLE_SOURCE!r} in {LOCK_PATH}, found {len(versions)}"
    )


def test_lock_pin_matches_the_sibling_source_version():
    locked = _locked_versions(EDITABLE_PACKAGE, EDITABLE_SOURCE)[0]
    declared = _sibling_version(SIBLING_MANIFEST)
    assert locked == declared, (
        f"{LOCK_PATH.name} pins {EDITABLE_PACKAGE} {locked}, but "
        f"{SIBLING_MANIFEST.relative_to(PROJECT_ROOT)} declares {declared}. "
        f"Refresh it: `uv lock` in {CONFORMANCE_DIR.name}/, then commit the lock."
    )


if __name__ == "__main__":
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print(f"PASS {_name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {_name}: {exc}")
    sys.exit(1 if failures else 0)
