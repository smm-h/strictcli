# Check command --verbose flag inert for PASS outcomes

The check command's --verbose flag is now effectively inert for PASS outcomes (the sealed reporter model forbids problems on passed()). Options:

1. Add verbose-specific output (reporter call traces, timing, check-count)
2. Document the new invariant
3. Remove the flag

## Context

The sealed reporter model prevents adding problems to passed checks, which means --verbose has nothing extra to show when all checks pass.

## Effort

Small design decision + small implementation.
