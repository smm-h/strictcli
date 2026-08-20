# MCP projection: open decisions after the 2026-07-28 stable-spec review

## Context

The MCP revision this framework implements (2026-07-28) shipped as the stable
release, and a review of the projection against the stable text found it
conformant on every structural point: the six `_meta` keys match verbatim,
`server/discover`, `resultType`, and the MRTR confirmation shape are as
specified, `tools/list` already emits the now-required `ttlMs`/`cacheScope`
(with a test pinning both), tool ordering is insertion-order (satisfying the
deterministic-ordering SHOULD), the `extensions` field is used for the
consequential-confirmation feature declaration, and encoding the confirmation
continuation in `requestState` is now the spec's explicitly documented
pattern for cross-retry correlation. The features the stable spec deprecates
(Roots, Sampling, Logging, HTTP+SSE) were never implemented here;
`subscriptions/listen`, the Tasks extension, and MCP Apps were assessed and
are correctly absent (a CLI's tool list never changes mid-process, commands
are synchronous, and no remote deployment exists) — do not re-litigate those
absences without a new use case.

Three decisions remain genuinely open. None is ruled; each needs the owner's
word before any implementation.

## Decision 1 [open]: project payload schemas as `outputSchema` + `structuredContent`

Every machine-mode command already declares a validated, emission-enforced,
cross-language byte-compared JSON Schema for its payload — and the stable
spec allows full JSON Schema 2020-12 in a tool's `outputSchema` (the
framework's closed subset is a valid subset) and structured values in
`structuredContent` on call results. Neither is projected today (zero
`outputSchema` occurrences in any implementation), so an MCP caller gets
less typed information than a `--json` caller — backwards, given the
declarations already exist.

Options:

- **Project both**: `payload_schema` becomes the tool descriptor's
  `outputSchema`; the payload rides `structuredContent` on the result.
  Pros: typed results for agent callers derived entirely from existing
  enforced declarations; no new validation surface (emission validation
  already runs). Cons: descriptor size grows; behavior for commands with no
  payload schema must be pinned (omit the field, never emit an empty
  schema); three implementations must emit byte-identical descriptors, so
  conformance cases are required (the existing MCP parity case family is
  the model).
- **Project `outputSchema` only**: advertises the shape without changing
  results. Pros: smaller change. Cons: callers still parse text, so the
  asymmetry mostly stands — halfway for little saved effort.
- **Status quo**: nothing changes; the asymmetry is accepted and recorded.

Affected: the tool-export modules in all three implementations, the MCP
call-result emission path, and new conformance cases. Effort: small-medium —
the schemas and their validation exist; this is projection plus cases.

## Decision 2 [open]: the confirmation key's lifetime vs statelessness

The consequential-confirmation continuation is HMAC-signed under a
per-process key (five-minute TTL, single-use). This is the projection's only
stateful commitment and it is deliberate: for stdio servers whose lifetime
the client owns, a key that dies with the process makes an exfiltrated blob
worthless. It also makes spawn-per-request operation and any future
stateless/HTTP deployment impossible for consequential flows specifically —
everything else in the modern era is already per-request stateless.

Options:

- **Keep per-process** (status quo): right for stdio; strongest key
  hygiene; the limitation is theoretical until a stateless deployment need
  exists.
- **Persisted key** (a key file under the user state directory, restrictive
  mode): enables stateless and HTTP deployment; reopens the forgeability
  window (whoever reads the file can mint valid continuations) and adds a
  rotation question.
- **Redesign the continuation** so no server-held key is needed: a larger
  design round with its own security analysis.

Do not decide speculatively — this decision only exists when a
stateless/spawn-per-request or HTTP deployment need actually appears.

## Decision 3 [open]: the Streamable HTTP transport

Not implemented; stdio only. Correctly absent for local agent-driven tools.
If a remote or serverless use case ever appears, adopting it brings the
authorization surface with it (note: the stable spec deprecates OAuth
Dynamic Client Registration in favor of Client ID Metadata Documents, so any
future adoption targets the latter). Decide only against a concrete need;
adding it speculatively would violate the attribute-admission principle.

## Effort summary

Decision 1 is the only near-term candidate (small-medium, rides whatever
release next touches the MCP surface, subject to the standing release hold).
Decisions 2 and 3 are recorded so they are decided deliberately when their
triggering need appears, not rediscovered.
