# Customizable help text for auto-generated commands

## Problem

strictcli auto-generates the check command (9 help strings) and config group (12 help strings) with hardcoded help text. Consumers cannot override this text. A consumer with specific documentation requirements (e.g., minimum help text length) is blocked on strictcli releases for cosmetic text changes.

## Deferred because

The immediate fix (commit 4105555 + parity alignment) makes the defaults good enough (50+ chars, cross-language parity). No consumer has requested customization beyond length requirements. If a real use case emerges, implement a bundle-based override mechanism: WithChecks(path, help={"--all": "custom"}) / checks_path=path, check_help={"--all": "custom"}.

## Scope

Applies to both check command (9 strings) and config group (12 strings). The mechanism should be the same for both. Both Python and Go implementations.
