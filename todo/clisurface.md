# clisurface: new monorepo member — CLI surface diff, classify, certify, inspect, scan

Filed 2026-08-03. All decisions below were made deliberately in a design session; open items are marked.

## Context

Every strictcli app dumps a complete machine-readable surface schema (`.strictcli/schema.json`). Diffing these schemas between released versions yields an exact, computable "what changed / what breaks" feed for the CLI surface. Nothing consumes that potential today: the conformance suite's differ (`conformance/check_schema_parity.py:656-720`) compares *languages* at one point in time, not versions, and matches flag lists positionally.

clisurface is a new, fourth releasable member of this monorepo that owns the version axis. It is deliberately NOT part of `python/`, `go/`, or `typescript/` — the trio must stay exactly symmetric, and this tool is a *consumer* of the schema format, not part of the framework.

## Identity (decided)

- Directory, releasable name, and binary: `clisurface` (availability verified 2026-08-03: npm free, PyPI free, no GitHub repos of that name).
- Implementation: Go, as its own module in this repo, importing the Go implementation's schema internals so format knowledge ships in lockstep with a format definer.
- Distribution: GitHub Release binaries + `go install`. Registry presence: claim `clisurface` on npm and PyPI NOW via placeholder/wrapper packages released through the sanctioned pipeline (prerequisites: PyPI pending publisher for project `clisurface` on this repo's publish workflow; npm token secret if not already present from the TS releasable). Placeholder content: stub that points to this repo and exits nonzero.

## Charter (decided)

1. **Diff**: structural delta between two schema files. Baseline acquisition is the caller's concern; the canonical source is git tags (`git show <tag>:.strictcli/schema.json`). A per-version schema archive was considered and **rejected** — tags are immutable and sufficient.
2. **Inspect/query**: list commands/flags, search a surface, pretty-print.
3. **Validate/canonicalize**: lint schema files, materialize defaults into fully-expanded form, normalize format v1 to future v2.
4. **Scan + fix plans**: scan a consumer repo for invocations of a given CLI, validate them against its schema, and emit a fix PLAN (site list, suggested edits, template-level fixes flagged). **The tool never writes to consumer repos.** Full auto-rewriting was assessed empirically and rejected: the mechanically-safe subset is ~6-8% of real occurrences and the harmful drift lives in prose.

## Diff engine design points (decided)

- Flag matching is name-keyed (scoped: global vs per-command). Arg matching stays positional — arg order IS the CLI contract.
- Constraint entries need synthesized identity keys (type + sorted member set; `mutex` has only an unordered flag set).
- Normalization before diffing: the cross-language asymmetries (`"default": []` emitted by Go where Python omits; compound-type spelling) must be normalized with the same definition the parity checker uses — with a recorded caveat that normalization can absorb a genuine cross-language reimplementation between versions. This layer shrinks to nothing once the v2 canonical-serialization migration lands (see `todo/schema-v2-single-migration.md`).
- Materialize each side against its OWN `defaults` block before comparing (omission encodes "at default"; a naive diff cannot distinguish a breaking default-removal from a benign respelling). Note the `defaults` block is incomplete in v1 — the materializer hardcodes the gaps.
- Normalize out `version` (stamped every release, guaranteed diff) and branch explicitly on `schema_version` mismatch.
- Must read format v1 forever (diffing old versions is the job), v2 when it lands.

## Classifier (decided)

Grades in the release-orchestration taxonomy: `breaking` / `feature` / `fix`.

- **Breaking**: removed command/flag/enum value; type change; a flag or arg becoming required; negatability removal; new constraint edges (mutex/requires/co_required); env-var rename; arg arity/order change; **changed default value** (silent behavior change for every omitting invocation).
- **Feature**: additive surface — new command, new flag, widened choices. Policy: additive requires a minor bump; only pure fixes ride patches.
- Rename detection: exact only via declared deprecation bridges (see `todo/deprecated-flags.md`); a fingerprint heuristic (help+type+env+short match) may exist only as an advisory note, never as a verdict.
- Blind spots (config format/path, conflict-mode inheritance, flag_sets — not serialized in v1) are documented loudly in the certificate until v2 serializes them.
- Output: a JSON certificate (graded findings with evidence), consumed by the release gate and rendered into changelogs by the orchestrator's generic contribution protocol. One artifact, two consumers.

## Scan scope limits (decided, from the 2026-08-03 fleet viability assessment)

- Error-grade findings only from: fenced code blocks with shell info-strings, shell scripts/hooks, source-code argv literals (head prefix). Measured precision there: 89-95%.
- Inline code spans and bare prose: advisory tier only (35% false-positive rate on prose; headings parse as commands).
- Unlabeled fences: unreliable (directory listings parse as invocations); advisory.
- Parsing needs: strip `exec`/`env`/`command`/runner prefixes; handle global flags before the command path; handle line continuations (real shell parsing, e.g. tree-sitter-bash — not line-oriented regex).
- Fix-plan exclusion classes (sites listed but marked do-not-edit): changelogs and immutable history dirs (stale references there are correct history), read-only generated root files (plan points at the source template instead), scaffold merge bases.

## Affected files

- `.rlsbl-monorepo/workspace.toml` — new releasable.
- New `clisurface/` directory (Go module, cmd, tests).
- `conformance/` — a check that clisurface's normalization agrees with the parity checker's definition (two copies of normalization logic must not drift).

## Dependencies and ordering

- Tiers 1-3 can start immediately on git-tag baselines.
- Classifier rename-soundness depends on deprecated-flag declarations (`todo/deprecated-flags.md`).
- Blind-spot-free classification depends on the v2 migration (`todo/schema-v2-single-migration.md`).
- Trustworthy historical baselines depend on the orchestrator-side stamping fix (filed in that project).

## Effort

L overall, phased: diff+classify core M; certificate + inspect/validate S each; scan+fix-plans M-L (parser work dominates).
