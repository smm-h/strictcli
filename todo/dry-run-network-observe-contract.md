# Rule on dry-run and the network: may observes touch it?

## Context

Under the effects regime, `--dry-run` means recorded mutations are logged
instead of performed, while observes (allowlisted read subprocesses) execute
for real until the first recorded mutation. `HTTP` is handle-owned and its
mutations are recorded -- but a subprocess observe can touch the network
invisibly (an `ls-remote`-shaped read is just argv to the framework), so
today a dry run may perform real network reads with the framework unaware.

## Problem

There is no stated contract for what a dry run may do to the network, so
consumers invent their own stances per command: some deliberately preview
from local state only (documenting "no network contact"), sibling commands
in the same tool let a pre-mutation network observe run, and consumer docs
generalize one command's stance into tool-wide promises that other commands
break. A dry-run promise is a framework concept; per-consumer forks of its
meaning fragment it exactly the way hand-rolled confirmation seams fragment
the confirm protocol.

Concrete stakes either way:

- Network reads in a preview make it nondeterministic (same input, network
  state decides the output), non-functional offline, slower, rate-limited,
  and externally observable (the read lands in the remote's logs -- "no
  effect on the world" only in the narrow sense).
- Forbidding them makes previews compute from possibly-stale local
  knowledge and unable to name actual remote state.

## The constraint that shapes any ruling

**The framework sees argv, not sockets.** It cannot classify whether a
subprocess observe touches the network. Any enforcement must therefore be
declaration-based -- zero inference: e.g. observe-allowlist entries carry an
explicit `network` marker declared by the consumer, and the framework acts
on the marker, never on a guess.

## Ruling options

### A. Declare the current behavior as the contract

Observes may read the network in dry mode; document it as the framework's
dry-run semantics; consumers must not promise stronger in their own docs
(a consumer wanting a local-only preview implements it as an explicit code
path, and describes it as that command's behavior, never as a dry-run
guarantee).

- Pros: zero code; matches the existing observe model; previews may be
  maximally informative.
- Cons: dry-run keeps the nondeterminism/offline/observability costs; the
  contract is "it depends on the command", which is weaker than agents
  would like.

### B. No-network-in-dry-run, enforced by declaration

Observe-allowlist entries gain a `network` marker. In dry mode, marked
observes do not execute: they are refused (hard error naming the observe)
or recorded/unsettled like post-mutation observes. Unmarked observes that
do touch the network are a consumer declaration bug, not a framework
inference failure.

- Pros: dry runs become deterministic, offline-capable, and externally
  silent by contract, for every consumer at once; enforcement is mechanical
  where declared.
- Cons: previews lose access to remote state; the marker is one more
  declaration to keep honest; refuse-vs-unsettled needs its own sub-ruling
  (refusing makes some commands un-previewable; unsettled values truncate
  previews that try to extract them).

### C. Per-command offline-preview declaration

A command declares "offline preview" at registration; in its dry runs the
framework refuses/records marked observes; commands without the declaration
keep behavior A. The marker from B is still required.

- Pros: both preview styles remain expressible, and which style a command
  uses becomes a visible, schema-exposed declaration instead of an
  implementation accident.
- Cons: two dry-run flavors is a weaker universal contract; consumers must
  choose per command, and mixed tools remain possible (though now visibly
  declared).

## Affected areas

- Observe allowlist declaration surface + schema (`--dump-schema`) in all
  three language implementations, kept in lockstep
- The dry-mode observe execution path (marker handling, refuse vs
  unsettled)
- Docs: the effects-regime contract section (dry-run semantics)
- The `observe-allowlist-breadth` check family, if markers introduce new
  validity rules

## Effort estimate

A: docs only, small. B: medium -- marker plumbing, dry-mode handling,
tests, three implementations, plus the refuse-vs-unsettled sub-ruling.
C: B plus a registration flag; slightly more.
