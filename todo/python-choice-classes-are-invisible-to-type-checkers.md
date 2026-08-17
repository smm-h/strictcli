# Python: `@strictcli.choice` classes are invisible to type checkers

## Context

`@strictcli.choice(name, help=...)` turns the decorated class into a frozen,
keyword-only dataclass whose fields (declared with `sub_flag`,
`sub_choice_flag`, `member_value`) are the scope's flags. That happens at
runtime, inside the decorator, via `dataclasses.dataclass(frozen=True,
kw_only=True)`.

## Problem

A type checker sees none of it. `choice(...)` is annotated as returning a
plain decorator over `type`, and the field declarations are ordinary class
attributes as far as static analysis is concerned, so the generated
`__init__` does not exist for mypy or pyright:

```
error: Unexpected keyword argument "value" for "Email"  [call-arg]
```

Every construction site is affected, and constructions are not rare:

- a selector's `default=` **must** be a choice instance (§24.5: "Python spells
  it as a choice instance"), so declaring a defaulted selector is itself a
  construction;
- `app.call()` takes the elected record pre-typed, so every programmatic call
  through a selector constructs one;
- tests that call a handler below the parser construct one per case.

A repo running mypy in strict mode has to either scatter
`# type: ignore[call-arg]` across all of them or funnel every construction
through a hand-written factory carrying one ignore. Both are noise the
declaration surface should not create, and both defeat the point of a
construct whose Python payoff is that "a frozen dataclass cannot be
constructed without its required fields" -- a guarantee a checker currently
cannot see either.

## What to do

Apply `typing.dataclass_transform` (PEP 681, `typing_extensions` for older
runtimes if needed) to `choice`, declaring the field specifiers so a checker
synthesizes the same `__init__` the decorator builds:

```python
@dataclass_transform(
    frozen_default=True,
    kw_only_default=True,
    field_specifiers=(sub_flag, sub_choice_flag, member_value),
)
def choice(name: str, *, help: str) -> Callable[[type[T]], type[T]]: ...
```

The field specifiers must then be annotated so a checker can read each one's
`default` / presence, which is what makes `presence="optional"` fields show up
as optional rather than required in the synthesized signature.

Worth checking at the same time whether the choice class's fields are visible
to a checker at the READ end too -- a handler that matches on the record and
reads `elected.value` should type as `str`, not `Any`.

Add a type-checking test (mypy over a fixture module asserting the expected
diagnostics, in the style the suite already uses for compile-fail fixtures) so
the transform cannot silently regress.

## Effort

Small: one decorator and its field-specifier annotations, plus the
type-checking fixture. No runtime behavior changes.
