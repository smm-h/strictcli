# Python: a member-spelled choice's member flag cannot declare a short

## Context

§24.4 says a member-spelled selector cannot carry a short, "and a short
declared on a member is an ordinary flag short". The refusal template says the
same thing in the imperative:

```
Flag "<sel>": a member-spelled choice flag is never typed, so it cannot carry a short: declare the short on a member
```

Go can obey that instruction. `MemberChoice(memberFlag Flag, help string, scope
...Flag)` takes the member flag as an ordinary `Flag`, so `sc.Short("c")` on it
is a normal flag option.

## Problem

**Python has no spelling for it.** A member is declared as
`@strictcli.choice("cont", help=...)` over a class whose payload field is
`member_value(*, help)`; neither takes `short`, and the payload `Flag` the
registration builds is constructed with `name`, `type`, `help` and
`presence` only (`python/strictcli/__init__.py`, in `_build_choice_spec`'s
payload branch). So `payload.short` is always `None` in Python.

The machinery downstream is already written for a short that Python cannot
produce, which is what makes this a gap rather than a design choice:

- the cross-scope short-claim table reads `site.choice.payload.short` when it
  walks member sites,
- help rendering appends `", -{payload.short}"` for a member flag,
- `errShortShapeMismatch` / `errShortOnAmbiguousElection` are stated over
  member scopes on purpose.

All of that is unreachable from the Python surface.

## Why it bites

A consumer converting an existing at-most-one group of flags into a
member-spelled selector -- the conversion §24.5 and the 0.41.0 changelog tell
consumers to make -- loses every short form those flags had. There is no
migration that keeps the argv: the members ARE the flags, and in Python they
cannot carry the shorts the flags carried. The result is a breaking CLI change
forced by an adoption the framework asks for, in one language only.

## What to do

Give Python a spelling for a member flag's short, and make the three surfaces
agree on the semantic they already share. Sketches, to be designed properly
rather than adopted as written:

- a `short=` keyword on `member_value(...)`, which is the payload-carrying
  member's own declaration; and
- something for a payload-LESS member, which has no `member_value` at all --
  a `short=` keyword on `@strictcli.choice(...)` (legal only for a choice
  claimed by a member-spelled selector, an error otherwise), or a marker field.

Whatever the spelling, the existing registration rules apply unchanged: the
short is claimed across simultaneously-live scopes, sibling scopes may reuse
one only when the declarations tokenize identically, and a short claimed by an
election token that a sibling scope also claims stays refused.

Add conformance coverage for a member short at the argv level (`-c` electing
the member `--cont` elects) and in help rendering, since the Go path can
already produce both and nothing compares them today.

## Effort

Small-to-medium: one declaration keyword plus its plumbing into the payload
`Flag`, the registration guards it must re-run, and conformance cases. The
downstream machinery exists.
