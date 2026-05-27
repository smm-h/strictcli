#!/usr/bin/env bash
set -euo pipefail
# Project-specific pre-release checks.
# Built-in checks (tests, lint) run automatically before this hook.
# Add custom validation here, e.g.:
#   - Check for uncommitted documentation
#   - Verify external service connectivity
#   - Run integration tests not covered by the test suite

# Run conformance checks before release
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/conformance"
conformance check --tag pre-release
