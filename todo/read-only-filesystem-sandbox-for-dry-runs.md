# A kernel-enforced read-only filesystem for dry runs

## Context

A dry run performs every read, local or remote, and withholds every write.
The line is drawn by the effects handle: mutating verbs record instead of
perform, observations (allowlisted subprocess runs, and http observations once
they exist) are performed because a preview needs real reads to know what it
would do. Dryness is enforced at two layers: the handle itself, which cannot
be bypassed by code that uses it, and the effects-bypass check, which scans
the consumer's own source for direct filesystem, subprocess and network calls
in handler-reachable code and refuses them.

One step remains trusted rather than enforced. The scanner sees the consumer's
source, not the libraries it calls. A handler that imports a library which
writes a cache file, rewrites a lock file, or touches a state directory
performs that write during a dry run, and neither layer sees it. The
TypeScript scanner additionally stops at file boundaries, a recorded limit, and
a consumer that never enables the check system never runs the scanner at all.

## Problem

A preview that says "would do X" while a library quietly did Y is a preview
that lies, and the framework cannot currently detect the lie. The trust
boundary is at third-party code, which is where a consumer has the least
visibility.

## Solutions

### Option A: run dry mode under a kernel-enforced read-only filesystem view

When `--dry-run` is present, the framework executes the dispatch inside a
sandbox in which every filesystem write fails at the kernel: Landlock on
Linux, with a bubblewrap-style wrapper as the fallback where Landlock is
unavailable, and per-platform equivalents where they exist. A bypassing write
then surfaces as an error the dispatch reports, instead of happening
silently. The handle's own recorded writes are unaffected, since in dry mode
they never reach the kernel.

What this closes: the filesystem half of the trust boundary.

What this cannot close: the network half. A dry run performs remote reads
(an allowlisted `ls-remote`, an http observation), and the kernel cannot tell
a remote read from a remote write, so the network is left open and a
bypassing library's network write stays unguarded. Blocking the network
entirely would break every honest observation.

Pros: the strongest statement the framework can make about dryness, and the
only mechanism that reaches code the scanner cannot read. Cons: platform
specific, with three runtimes to cover; the Go, Python and Node processes
each need their own way to enter the sandbox before dispatch, or a re-exec of
the process under a wrapper; a runtime or platform without a mechanism must
say so loudly rather than run unsandboxed and claim dryness; temp-directory
writes that libraries perform legitimately (compiled bytecode caches, tool
caches) need a declared writable allowlist, which is a new declaration
surface.

### Option B: a filesystem watch during dry runs

Instead of preventing writes, observe them: snapshot the tree (or watch it)
across the dispatch and report any change not recorded by the handle as a
bypass finding.

Pros: portable, no kernel mechanism. Cons: the write has already happened by
the time it is reported, so the preview lied and the run merely admits it
afterwards; races on a live tree; cannot see writes outside the watched
roots.

### Option C: leave the boundary trusted

Document that dryness is enforced through the handle and the scanner and
trusted at libraries.

Pros: nothing to build. Cons: the trust boundary stays where visibility is
lowest.

## Affected files

- The dispatch entry in each implementation, where `--dry-run` is known
  before the handler runs (`python/strictcli/__init__.py`,
  `go/strictcli/strictcli.go`, `typescript/src/app.ts`).
- A per-runtime sandbox module, and the declaration surface for a writable
  allowlist if Option A is taken.
- The effects contract's dry-run sections, which today state the two
  enforcement layers and must state the third and its network limit.
- Conformance cases that exercise a bypassing write under `--dry-run`, which
  require a fixture library the scanner cannot see.

## Effort

Large. Option A is a design round of its own: mechanism per platform,
behavior where no mechanism exists, the writable allowlist, and the
re-exec question. It is outside the machine-mode and effects campaign.
