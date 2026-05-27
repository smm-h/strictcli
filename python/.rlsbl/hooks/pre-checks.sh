#!/usr/bin/env bash
set -euo pipefail
# This hook runs BEFORE built-in pre-release checks (tests, lint).
# Use it for setup tasks: starting services, setting env vars, etc.
# Built-in checks run after this hook. Custom validation goes in pre-release.sh.

# Ensure strictcli and conformance tool are installed (editable)
REPO_ROOT="$(git rev-parse --show-toplevel)"
pip install -e "$REPO_ROOT/python" --break-system-packages --quiet 2>/dev/null || true
pip install -e "$REPO_ROOT/conformance" --break-system-packages --quiet 2>/dev/null || true
