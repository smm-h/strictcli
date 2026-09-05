# Framework-owned exit-code band (dry-run and consent signals)

## Context

strictcli owns `--dry-run` as a reserved flag but says nothing about exit
semantics, so consumers improvise per command: some previews exit 0
regardless of findings, others exit 1 when the previewed real run would
refuse — and callers cannot distinguish "the preview itself failed" from
"the preview rendered and the world has blocking findings" without
parsing output. The same ambiguity exists for consequential commands on
non-interactive stdin without `--approve-consequential`: today that
refusal is an undistinguished failure exit.

A dedicated "findings" code cannot simply be picked from the ordinary
range (a command may legitimately use it), and the space outside a byte
does not exist on the wire: POSIX exit codes are 0-255, negatives and
large numbers wrap. The upper stretch is conventionally taken (126/127
shell, 128+N signals, 255 out-of-range). The only workable mechanism is
to RESTRICT the range commands may legitimately return and reserve a
band for the framework.

## Design

- **Legitimate command exit codes: 0-99.** A handler exiting or
  returning anything >= 100 is a framework contract violation: the
  framework already wraps every handler, so it intercepts the value and
  converts it into a loud framework error (a hard seam, like the `--yes`
  registration refusal — not guidance).
- **Framework-reserved band: 100-125**, owned like the reserved flag
  quartet. Commands can never emit these themselves.
- **126-255 untouched** (shell and signal territory, claimed by neither
  side).
- Assign two codes now, reserve the rest:
  - **100 — previewed, real run would refuse.** The dry run rendered
    fully and reports that the corresponding real run would refuse
    (blocking findings). Distinct from 0 (previewed, would proceed) and
    from 1-99 (the command itself failed). Commands report the
    would-refuse condition through the effects layer; the framework maps
    it to 100 — no per-command convention.
  - **101 — consent unresolved.** A consequential command on
    non-interactive stdin without `--approve-consequential`. Lets
    automation distinguish "add the consent flag" from "the command
    failed".
- Mirrored across the Python, Go, and TS implementations, with
  conformance fixtures holding the three in lockstep.
- Documented beside the reserved quartet as a framework-owned surface.

## Consequences

- Breaking for any caller that gates on a preview's current exit 1 for
  findings; pre-stable, so callers update and the changelog entry is
  `breaking`. Consumers then delete their hand-rolled preview exit
  conventions and adopt the framework codes in lockstep.

## Effort

Medium (three implementations + conformance + docs), but the seam is
small: an exit-value intercept in the existing handler wrapper, one
effects-layer reporting hook, two mapped codes.
