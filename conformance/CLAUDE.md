# conformance

Cross-language conformance suite for strictcli (Python and Go implementations).

## Development

- Run the suite from this directory: `python run.py --target python` and
  `python run.py --target go` (requires both implementations).
- API surface parity: `python check_api_surface.py`. Error message parity:
  `python check_error_parity.py`.
- Differential argv fuzzing: `python fuzz.py --iterations N [--seed S]`. It
  generates random argv, runs it against all three implementations (Python via
  `ref_python.py` codegen, Go and TypeScript via the `run.py` runtime harnesses),
  and reports any N-way divergence with the odd one out identified by majority.
  The old `ref_go.py` codegen path it once used has been deleted.
- CI (`ci-router.yml` at the repo root) runs the conformance checks on every
  push touching `conformance/**`, `python/**`, or `go/**`.

## Release status: dev_node

This project is marked `dev_node = true` in the monorepo's `workspace.toml`.
It is never released independently, has no changelog (no JSONL entries, no
CHANGELOG.md), and `rlsbl release run` / `rlsbl changelog add` are hard errors
here. It exists solely as test infrastructure at the edge of the dependency
graph.
