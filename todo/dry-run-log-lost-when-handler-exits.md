# A handler that raises `SystemExit` loses its would-do log

Found while migrating a consumer onto the effects regime.

## Problem

The would-do log is rendered only on the normal return path. In the Python
implementation both dispatch sites do:

```python
exit_code, out_data = _interpret_handler_return(result)
...
if self._last_dry_run:
    print(self._effect_log.render())
```

A handler that raises `SystemExit` never reaches that line. In `App.run` the
exception propagates straight out of the interpreter; in `App.test` it is
caught to produce the exit code, but after the render call, not before.

So a dry run of a command whose handler calls `sys.exit(1)` on an error path
prints **nothing at all** — no header, no recorded lines — even though the
effects were recorded correctly.

Minimal reproduction:

```python
app = strictcli.App(name="probe", version="0", help="probe app")

@app.command("go", help="...", effect="mutating")
def _go(ctx):
    ctx.effects.write("/tmp/whatever.txt", "x")
    sys.exit(1)

r = app.test(["go", "--dry-run"])
# r.exit_code == 1
# r.stdout    == ''      <-- the recorded write is gone
```

The safety property holds (nothing was executed), but the *preview* property
does not. The regime's whole promise is that a dry run tells you what would
happen; here it silently tells you nothing, and the silence is
indistinguishable from "this command would do nothing".

## Why it bites in practice

`sys.exit(...)` is the ordinary way a Python CLI handler reports a failing
condition, and it is extremely common on the *validation* paths that run after
work has already been recorded — "wrote the report, then exited 1 because the
check found errors". Exactly those runs are the ones where a reader most wants
to see the preview. In the consumer that surfaced this, a documentation `check`
command records a baseline write and then exits 1 when lints fail: under
`--dry-run` the write it would perform is invisible.

Telling every consumer to stop using `sys.exit` is not a real fix. It is a
large refactor per consumer, it has to be re-litigated on every new handler,
and the framework already knows everything it needs to render correctly.

## Suggested resolution

Render the recorded log for a dry run on the `SystemExit` path too — the effect
log is complete at that point by construction, since the handler is unwinding.
The natural shape is to move the dry-run render into a `finally`, or to catch
`SystemExit`, render, and re-raise. `App.run` and `App.test` both need it, and
the same gap should be checked in the Go and TypeScript ports (their equivalent
"handler aborted the run" paths: a Go handler cannot `os.Exit` without skipping
everything, which is arguably its own instance of this).

Worth deciding at the same time whether the truncation path and the
`SystemExit` path should agree on ordering — truncation already prints the
partial log before its stderr message, which is the behavior this is asking for.

A conformance case pinning "dry run + handler exits nonzero still prints the
log" would keep all three implementations honest.

## Affected files

- `python/strictcli/__init__.py` — the two dry-run render sites in `App.run`
  and `App.test`
- the Go and TS equivalents
- a new conformance case

## Effort

Small in Python; the parity work across three implementations plus a
conformance case is the bulk of it.
