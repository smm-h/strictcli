# HTTP API projection: serve every strictcli app over HTTP

## Context

strictcli already projects the declared command model in several directions,
all derived from the same registration-time declarations:

- `--help` rendering
- `--dump-schema` (`_dump_schema_core`, `python/strictcli/__init__.py:11521`) —
  a declaration-complete JSON tree: commands, groups, flags, args, effects,
  `consequential`, `dry_run_supported`, payload schemas, checks, config fields
- MCP server mode — hand-rolled, zero-dependency, line-delimited JSON-RPC 2.0
  over stdio in all three legs (`python/strictcli/__init__.py:11835`,
  `go/strictcli/mcp.go:46`, `typescript/src/mcp.ts:161`), conformance-covered
  (`conformance/cases/protocol_script.json`,
  `conformance/cases/effects_call_consent.json`)
- The in-process embedding API: `App.call()` (`:8826`), `App.acall()` (`:8888`),
  `App.as_tools()` (`:8940`), `App.json_schema()` (`:8915`),
  `App.dump_schema_dict()` (`:6142`)

The missing projection is HTTP: a `serve-api` mode that turns any strictcli app
into an HTTP API server, implemented in-tree with each language's standard
library only (Python `http.server`-level, Go `net/http`, Node `node:http` plus
at most a minimal router), in all three legs, kept byte-identical by the
conformance suite — the same discipline as MCP mode. No new runtime
dependencies in any leg.

Line numbers above are as of 2026-08-13 (py 0.39.0 / go 0.31.0 / ts 0.38.0)
and will drift.

## Motivation

Two consumer classes, both real, that the existing projections cannot serve:

1. **Remote agents.** Shell and stdio MCP require the caller to spawn a process
   on the same machine. HTTP makes any strictcli CLI reachable across machines
   — an agent on one host driving tools on another without ssh-wrapping every
   call.
2. **Non-agent clients.** curl, scripts, other services, webhook-style
   triggering from CI or cron, and browsers. Because `--dump-schema` is
   declaration-complete, a single generic web frontend could render forms for
   *any* strictcli app — every CLI built on strictcli gets a usable GUI for
   free, from one frontend written once. That frontend is out of scope here;
   this projection is its foundation.

For local same-machine agents the projection adds nothing — they already have
shell and stdio MCP with schemas, effects, and consent. The value is entirely
in remote reach and the non-agent audience.

## Pros

- **Uniformity dividend.** Implemented once in the framework, inherited by
  every current and future strictcli CLI — the same leverage MCP mode had.
- **Remote access** with structured schemas, effects classification, and
  explicit consent — none of which survive ad-hoc ssh wrapping.
- **Foundation for a generic web UI** over the whole family of CLIs.
- **Webhook/automation surface** without per-tool server code.
- **Persistent process.** Long-lived server amortizes interpreter startup and
  can hold warm caches; stdio MCP spawns per client.
- **Effects regime maps cleanly onto HTTP.** `read_only` → GET, `mutating` →
  POST, `consequential` → require an explicit `approve_consequential` field,
  mirroring the MCP mapping (top-level param, never inside arguments,
  `python/strictcli/__init__.py:11792`).
- **Wire-testable parity.** Like argv/stdout behavior and unlike a
  programmatic API, HTTP behavior is observable on the wire, so the
  conformance suite can drive three real servers through identical scripted
  exchanges and assert byte-identical behavior.
- **Zero dependencies preserved.** Stdlib-only in all three legs keeps
  strictcli at the bottom of the dependency graph, same as the hand-rolled MCP
  loop.

## Cons / costs

- **Security surface.** stdio inherits process and user permissions naturally.
  An HTTP server exposing mutating and consequential commands is remote code
  execution by design. Bind address and auth must be settled in the spec
  before the first byte is served. The `approve_consequential` field is a
  confirmation mechanism, not authentication.
- **The working-directory problem.** Many strictcli CLIs are CWD-contextual
  ("operate on the project I am standing in"). A long-lived server has one
  CWD. Per-call directory selection is both a semantics and a security
  question; stdio avoids it because each spawn picks its directory.
- **Streaming.** Long-running commands emit progress for minutes. The current
  programmatic dispatch wires handler output to the real process
  stdout/stderr and returns only the payload
  (`python/strictcli/__init__.py:8722`), which is unusable under concurrent
  requests. Per-call stream capture is prerequisite work in all three legs,
  and progress streaming (SSE or chunked) is needed for long commands.
- **A permanent spec tax.** Route derivation, method mapping, error model,
  content types, contract versioning — a mini-spec kept byte-identical across
  three implementations plus conformance cases. Every future strictcli
  feature (new arg kinds, passthrough, interactive, `owns_stdout`) must define
  its HTTP behavior or be explicitly excluded, forever.
- **Marginal value for the dominant current consumer** (local agents) is zero;
  the feature is justified by the two audiences above, not by improving
  existing workflows.

## Alternatives considered (and why they lost)

1. **In-tree, stdlib-only, all three legs** — CHOSEN. Cheapest, most
   symmetric, no new dependencies, no new projects, parity scoped to what is
   wire-testable.
2. **Delegate serving to an external web framework as a dependency.**
   Production-grade serving for free in one leg, but: adds a heavyweight
   dependency to a deliberately dependency-free base, creates release-ordering
   friction whenever both sides need each other's new behavior, and reaches
   parity only after equivalent server counterparts exist for the other two
   legs. A framework-side "mount a strictcli App into a larger app" adapter
   remains possible on top of the public embedding API regardless, and needs
   nothing from this todo.
3. **Absorb a web framework into this monorepo as the serving leg.** One repo
   and coordinated releases, but the monorepo would carry a full framework's
   development and downstream consumers, and a framework's programmatic API
   can never join the byte-identical conformance contract — only the wire can.

Related but distinct option, deliberately in scope as a design question below:
**MCP streamable HTTP transport.** Adding an HTTP transport to the existing
MCP mode covers the remote-agent audience alone with a much smaller spec
surface (the tools/list–tools/call projection is already specified and
conformance-covered). Since the non-agent audience is also real, REST is
justified too — the open question is whether one server exposes both (e.g. an
`/mcp` endpoint beside REST routes) and whether the MCP transport ships first
as a stepping stone.

## Design questions to resolve before implementation

Per the planning discipline, all of these must be settled (ASKME rounds)
before any implementation plan exists. None may survive into a plan as an
open item.

1. **Auth and bind.** Loopback-only vs configurable bind; token auth or none;
   whether bind address/port are mandatory explicit flags (no implicit
   defaults — consistent with the framework's mandatory-flags philosophy and
   the fleet-wide ban on implicit defaults for security-relevant values).
2. **CWD semantics.** Server-fixed CWD vs per-call directory parameter; if
   per-call, how it is constrained.
3. **Entry point.** A reserved pre-scan flag like `--mcp`, a designated
   command, or a method like `serve_mcp` — and its name (the `mcp` name is
   pinned as reserved in `conformance/cases/reserved_global_flags.json:94`;
   the API equivalent needs the same treatment).
4. **Route derivation and method mapping.** Dotted paths → URL paths; the
   read_only→GET / mutating→POST mapping; where `approve_consequential`
   travels (body field vs header).
5. **Error model.** Status codes, error body shape, how `InvokeError` and
   consent refusals map.
6. **`--dry-run` reachability.** Programmatic dispatch hard-wires
   `dry_run=False` (`python/strictcli/__init__.py:8718-8724`). Decide whether
   the projection exposes dry-run previews, which requires a core change in
   all three legs.
7. **Stream capture and progress streaming.** Per-call capture in `_invoke`
   equivalents in all three legs; SSE or chunked transfer for long commands;
   what happens to `owns_stdout` commands.
8. **Excluded surfaces.** MCP mode skips `hidden` and `interactive` commands
   (`python/strictcli/__init__.py:11678`); decide the HTTP treatment of
   hidden, interactive, and passthrough commands.
9. **Schema endpoint.** e.g. GET `/schema` serving the dump-schema document;
   whether the JSON-Schema per-command form (`_build_json_schema`,
   `python/strictcli/__init__.py:9082`) is also exposed.
10. **Relationship to MCP streamable HTTP.** Same server exposing both MCP
    transport and REST routes, or separate modes; which ships first.
11. **Contract versioning.** How the wire contract is versioned so the
    generic-frontend consumer can detect incompatibility.
12. **Concurrency model.** Threaded (Python), goroutines (Go), event loop
    (TS); whether concurrent mutating calls to one app instance are allowed
    or serialized.

## Affected files

- `python/strictcli/__init__.py` — new server loop beside `_run_mcp_server`;
  stream capture in `_invoke`; possibly dry-run exposure in `call()`
- `go/strictcli/` — new file beside `mcp.go`; same core changes
- `typescript/src/` — new module beside `mcp.ts`; same core changes
- `conformance/` — new case family driving real HTTP servers (extending the
  `_run_protocol_script` approach, `conformance/run.py:787`); reserved-name
  pinning for the new entry point
- `docs/` — the wire-contract spec document, per-leg usage docs
- Release metadata for all three releasables when it ships

## Effort estimate

Large — a multi-session campaign:

- Spec + design resolution (ASKME rounds): 1 session
- Core prerequisite (stream capture in three legs, conformance for it): 1–2
  sessions
- Python leg + conformance cases: 1–2 sessions
- Go leg: 1 session (conformance already in place from the Python round)
- TS leg: 1 session
- Docs + polish: part of the above

The stream-capture prerequisite is independently useful to any embedder and
could ship in an earlier release than the projection itself.
