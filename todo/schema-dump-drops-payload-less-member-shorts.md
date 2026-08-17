# `--dump-schema` drops the short form of a payload-less selection member

## Context

Member shorts (contract §18.36, items 330-332) are declared two different ways
depending on whether the member carries a payload:

- payload-less member: `@strictcli.choice("cont", help="...", short="c")`
- payload-carrying member: `strictcli.member_value(help="...", short="r")`

Both work at parse time. `-c` elects the payload-less member and `-r <value>`
elects the payload-carrying one, exactly as the conformance cases in
`conformance/cases/selector_member_short.json` describe. The rendered `--help`
shows both:

```
  session                       which session this launch starts in (exactly one of the following) [default: new-session]
    --cont, -c                  continue the most recent conversation ... [required]
    --resume, -r <str>          resume one specific session [required]
    --print-prompt, -p <str>    run one prompt in non-interactive print mode and exit [required]
```

## Problem

The schema dump does not agree with the help renderer. For the same app, the
payload-carrying members carry their short into the dump and the payload-less
one does not:

```json
{
  "name": "session",
  "elect_by": "member-flags",
  "choices": [
    { "name": "cont", "help": "continue the most recent conversation ..." },
    { "name": "resume", "help": "resume one specific session",
      "flags": [ { "name": "value", "short": "r", "presence": "required", ... } ] },
    { "name": "print-prompt", "help": "run one prompt ...",
      "flags": [ { "name": "value", "short": "p", "presence": "required", ... } ] },
    { "name": "picker", "help": "browse this profile's sessions ..." },
    { "name": "new-session", "help": "start a new session ..." }
  ]
}
```

`"cont"` has no `"short": "c"` anywhere, even though `-c` is a real accepted
spelling and the help prints it. The `defaults` block of the dump declares
`"choice": {"flags": []}` and `"choice_record": {"help": null}` -- neither
mentions a short, so a reader cannot even tell the key is omissible.

Consequences for a consumer of the dump:

- A docs generator built on the schema renders an empty "Short" column for a
  member whose short exists. The generated CLI reference then contradicts
  `--help`, and a user reading only the docs never learns the spelling.
- Any argv-contract check driven by the dump (comparing the accepted spellings
  of two versions) cannot see a member short appearing or disappearing on a
  payload-less member. A regression there is invisible.
- The asymmetry is silent: nothing at registration time or dump time says the
  short was recorded but not exported.

## How to reproduce

1. Declare a selector with `elect_by="member-flags"` holding one payload-less
   member with `short=` and one payload-carrying member whose `member_value`
   carries `short=`.
2. Run the app's `--help` -- both shorts render.
3. Run the app's `--dump-schema` -- only the payload-carrying member's short is
   present.

## Solutions

### A. Emit `short` on the choice record (recommended)

Add the key to the dumped choice record whenever the member declares one, and
add its default (`null`) to the `defaults.choice_record` block so the omission
is declared rather than implied.

- Pro: the dump becomes a complete description of the accepted argv, which is
  what every downstream consumer assumes it already is.
- Pro: symmetric with the payload-carrying case, which already exports it.
- Con: consumers pinning a normalized copy of a dump see a one-time diff.

### B. Leave the dump alone, document the omission

State in the schema documentation that member shorts are not exported for
payload-less members.

- Pro: no format change.
- Con: leaves a documented hole that every consumer must special-case, and
  leaves the docs-vs-help contradiction in place. Not recommended.

### C. Move the short off the payload-carrying member's value flag

Export both forms in one place on the choice record, so a consumer reads one
key regardless of payload.

- Pro: one shape to read.
- Con: the value flag's short genuinely belongs to the value flag (it consumes
  the next argument); relocating it in the dump would misdescribe it. Worth
  considering only if the record also keeps the flag-level key.

## Affected areas

- the schema dump writer (the `elect_by="member-flags"` choice-record path)
- the `defaults` block emitted at the top of every dump
- the conformance suite: a case asserting the dumped shape of a payload-less
  member's short, alongside the existing parse-time cases

## Effort

Small: one key in the dump writer, one default entry, one or two conformance
cases.
