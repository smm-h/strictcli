# Check command help text is not customizable by consumers

## Problem

strictcli auto-generates the `check` command and its flags (`--all`, `--tag`, `--name`, `--list`, `--json`, `--verbose`, `--dry-run`, `--ignore-warnings`) when a consumer uses the check framework. The help text for these is hardcoded in `check_cmd.go`. Consumers cannot customize it.

This caused a real problem: a consumer's documentation tool (selfdoc) enforces a 50-character minimum on CLI help text. The consumer was blocked from releasing because strictcli's auto-generated help text was too short. The consumer could not fix it — the strings are not configurable. The fix had to be made in strictcli and the consumer had to wait for a release.

## What should change

1. The auto-generated check command help text should meet reasonable length minimums out of the box (commit 4105555 already does this).
2. Consumers should be able to override help text for the check command and its flags, e.g., via options passed to the check framework registration. This way consumers with specific documentation requirements are not blocked on strictcli releases for cosmetic text changes.
