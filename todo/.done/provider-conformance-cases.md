# Add cross-language conformance cases for check providers

The check-provider hook has 30 unit tests per language but zero cross-language conformance cases. Expressing providers in conformance needs generator vocabulary additions (~100 lines in ref_python.py + ref_go.py: a case-level `providers` key emitting registered provider functions returning specs).

## Scope

- ref_python.py: add generator vocabulary for `providers` key
- ref_go.py: add generator vocabulary for `providers` key
- New conformance case definitions exercising provider registration and execution across both languages

## Effort

Medium.
