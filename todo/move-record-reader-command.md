# A reader command for declared file-move records

## Context

A consumer project has built a declared file-move record system: moves
are recorded as structured commit-message trailers (`Moved: <id> old ->
new`, with C-quoted paths, subtree forms, and `Moved-Retract: <id>`
corrections), written by its commit pipeline and its `mv` command. The
read layer exists as a library API: a forward projection that follows a
path across records, validates each claim against the actual trees
(trees are the arbiter), folds retractions, resolves longest-prefix
subtree matches, and classifies malformed record lines. The API is
property-tested and correct — and consumed by nothing: no command
answers "where did this path come from?" or "where did it go?", and a
malformed record in history is invisible to operators.

## Problem

A record system nobody can read delivers none of its value, and the
projection API sits in the built-but-unwired state the fleet's dead-code
policy exists to prevent. A reader command is the missing consumer.

## The ask

Design and deliver the query command: e.g. `moves <path>` answering the
path's history across records — the chain of old/new answers with the
commit and record id at each hop, subtree attributions marked, retracted
claims folded, and any malformed record lines in the walked range
surfaced loudly. Design points to settle: a direction selector
(where-from vs where-to), a range selector consistent with the project's
existing history-range flags, and a `--json` payload with a declared
schema.

Alternatives considered and rejected in prior discussion: a minimal
malformed-records reporter only (half an answer — the forward projection
stays unconsumed); deleting the projection and rebuilding later
(discards correct, property-tested machinery whose subtleties — merge
arbitration, longest-prefix, retraction folding — would have to be
re-derived).

## Effort

Medium — one design round for the query/output shape, then a
straightforward implementation over the existing tested API.
