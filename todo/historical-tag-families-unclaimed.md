# Decide the disposition of the historical tag families no current scope claims

## Context

The rlsbl anchor backfill (rlsbl >= 0.118's release ledger) ran here during
the fleet migration. It anchored every archived release it could attribute,
and reported the remaining tags as "foreign": tags that parse under a
recognized scheme but match no version any current releasable's scope
claims. It deliberately refuses to guess what they belong to, and it exits
nonzero in this repository until they are addressed, so the backfill is not
a clean-exit check here.

The unclaimed families:

- `strictcli@v*` — the release line from before the per-language split.
- `go/v*` — the old Go module path-scheme tags.
- `conformance@v*` — the conformance suite's former release line.
- bare `v0.1.x` — pre-monorepo history.

All are real history; most predate the current releasable layout.

## Options

**A — claim them as history via lineage records.** For each family, record
boundary-alias / identity-transition lineage events mapping the family to
its successor releasable (rlsbl's `lineage.jsonl` in the releasable state
directory). The ledger and the reconciler then explain those tags instead
of reporting them foreign, and the backfill exits clean. This is tag
archaeology: each family needs a maintainer to say which current line (if
any) continues it.

**B — accept them as unclaimed pre-model history.** Leave the tags as they
are; document (e.g. in this repo's own notes) that the backfill's nonzero
exit here is a known permanent state. Cheapest, but every future backfill
or reconcile run re-reports the same residue.

**C — some mix**: claim the families with a clear successor (e.g. the
pre-split line), accept the rest.

## Effort

B is zero. A is hours of history reading per family plus the lineage
records; the mapping judgment is the real work.
