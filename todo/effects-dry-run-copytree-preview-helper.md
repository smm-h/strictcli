# Shared dry-run copytree preview helper in the effects system

## Context

The effects regime makes strictcli the owner of dry-run semantics: mutating
commands record effects instead of performing them, and the framework renders
the preview. For directory-copy effects, consumer projects currently hand-roll
their own "preview a copytree" implementation: walk the source tree, read every
file, and record per-file copy effects, while live mode delegates to
`shutil.copytree`. The same hand-rolled walker has been copy-pasted across
consumer projects essentially byte-identically.

## Problem

Every copy of the hand-rolled walker shares the same defects, and fixing one
copy fixes nothing anywhere else:

- The walk calls `open()`/`read_bytes()` on every entry it finds without
  guarding against entries that cannot be read. A dangling symlink anywhere in
  the walked tree raises `FileNotFoundError` and crashes the entire dry run --
  observed live: a repository containing one dangling symlink makes a release
  dry-run crash with a raw traceback.
- The preview walk and the live `shutil.copytree` can disagree about symlink
  handling, so the preview does not faithfully predict the live operation.
- Each consumer re-decides (or fails to decide) the same questions: follow or
  skip symlinks, what to do on unreadable entries, how to report skipped
  entries.

The duplication is the finding: N hand-rolled copies of the same walker should
be one implementation with one tested answer to the dangling-symlink question.

## Proposed solution

Provide a copytree-preview helper as part of the effects handle, so a mutating
command can record a directory copy in dry-run mode through one shared,
symlink-safe implementation:

- Owned by strictcli's effects module, next to the existing effect-recording
  primitives.
- Explicit, documented symlink policy chosen to match what live
  `shutil.copytree` will actually do, so preview and execution cannot diverge.
- Unreadable or dangling entries produce a clean, named-path hard error (or a
  documented recorded-skip, whichever the effects semantics dictate) -- never
  an unhandled traceback.
- Red-green test coverage including a dangling-symlink fixture.

Consumers then delete their hand-rolled walkers and call the helper. Adoption
happens at each consumer's next visit; consumers' local crash fixes made in
the meantime become dead code to remove on adoption.

## Alternatives considered

- Patching each hand-rolled copy in place: performed as an interim measure in
  the consumers, but leaves N implementations to drift; this todo exists to
  reduce N to 1.
- A standalone shared package outside strictcli: rejected -- the effects
  regime already lives here, and a copytree preview is meaningless outside an
  effects-bearing command.

## Affected files

- strictcli's effects module (new helper + tests).
- Consumer adoption is out of scope for this todo; each consumer adopts on its
  own schedule.

## Effort

Small-to-medium: one helper function with a decided symlink policy, tests
including the dangling-symlink fixture, docs in the effects chapter.
