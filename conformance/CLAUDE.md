# conformance

Cross-language conformance suite for strictcli (Python and Go implementations).

## Development

- Run the suite from this directory: `python run.py --target python` and
  `python run.py --target go` (requires both implementations).
- API surface parity: `python check_api_surface.py`. Error message parity:
  `python check_error_parity.py`.
- CI (`ci-router.yml` at the repo root) runs the conformance checks on every
  push touching `conformance/**`, `python/**`, or `go/**`.

## Release status: dev_node

This project is marked `dev_node = true` in the monorepo's `workspace.toml`.
It is never released independently, has no changelog (no JSONL entries, no
CHANGELOG.md), and `rlsbl release run` / `rlsbl changelog add` are hard errors
here. It exists solely as test infrastructure at the edge of the dependency
graph.
