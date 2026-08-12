# Schema dumps need one canonical JSON encoding across all three languages

## Problem

The three implementations emit `--dump-schema` JSON with different encoder
behavior: the Python dumper and the Go dumper disagree on HTML escaping
(`<`/`>`/`&`), non-ASCII escaping (`\uXXXX` vs raw UTF-8), and separator
spacing. A repository whose committed schema file is dumped sometimes by one
implementation and sometimes by another churns the entire file on every dump
even when nothing changed semantically.

Observed live: a consumer repo's committed schema was last written by a
Python-shaped encoder (HTML unescaped, unicode escaped); its own Go binary
produces the opposite on every fresh dump, so the file rewrites wholesale each
release with zero semantic delta.

## Proposal

Pin one canonical schema-file encoding in the conformance contract — the float
canon precedent applies: define the byte-level rules once (escaping policy,
separator policy, key ordering is already pinned, trailing newline), implement
in all three languages, and add a conformance case asserting byte-identical
dump output for a shared fixture app across all targets. The schema-parity
checker already compares structure; this extends the guarantee to bytes so the
committed artifact is dumper-independent.

## Affected

- `--dump-schema` serialization in python/, go/, typescript/.
- The conformance schema-parity machinery (gains a byte-level case).
- Consumer repos' committed `.strictcli/schema.json` files (one final
  whole-file churn when the canon lands, then stability).

## Effort

Small-medium: encoder settings per language plus one conformance case; the
key-ordering half is already done.
