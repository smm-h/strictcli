#!/usr/bin/env bash
set -euo pipefail
# Project-specific pre-release checks.
# When this hook is customized (any change from the scaffold template),
# built-in tests and lint are skipped -- the hook is expected to handle them.
# Add custom validation here, e.g.:
#   - Run tests and lint with project-specific flags
#   - Check for uncommitted documentation
#   - Verify external service connectivity
#   - Run integration tests not covered by the test suite

# Run conformance checks before release
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/conformance"
conformance check --tag pre-release
