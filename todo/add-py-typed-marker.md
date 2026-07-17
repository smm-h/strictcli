# Add py.typed marker to the Python package (PEP 561)

## Context

The Python package's source code is type-annotated, but the distribution does not ship a `py.typed` marker file. Under PEP 561, type checkers (mypy, pyright) treat installed packages without this marker as untyped: mypy reports `module is installed, but missing library stubs or py.typed marker` (`[import-not-found]` / `[import-untyped]`), and consumers must either suppress the import or lose all type information for the package's API.

This was discovered when a consumer project adopted mypy in strict mode and had to add an `ignore_missing_imports` override for this package — meaning every call into the package's API is typed as `Any` on the consumer side, so wrong-arity or wrong-type calls into the package go undetected by the consumer's type checker.

## Problem

- Consumers cannot type-check their usage of the package's public API despite the annotations already existing in the source.
- Each consumer must carry a permanent mypy/pyright suppression for the package.

## Solution

Add an empty `py.typed` file inside the package directory (next to `__init__.py`) and ensure the build backend includes it in wheels and sdists.

- With hatchling: package-dir files are included by default; verify with a built wheel.
- With setuptools: needs `[tool.setuptools.package-data]` (or `include_package_data` + MANIFEST) to ship the marker.

Verification: build the wheel, confirm `py.typed` is present in the archive, then in a scratch venv `pip install` the wheel and run `mypy -c "import <package>"` (or a small snippet calling a mis-typed API) to confirm mypy resolves the package's types.

Pros:
- One-line change; all consumers immediately get real types for the API.
- No maintenance burden — inline annotations are the stubs.

Cons / considerations:
- Once shipped, the public API's annotations become part of the consumer-visible contract; annotation errors in the package surface as consumer type errors. Worth a quick pass over public API signatures for obviously wrong annotations before shipping.

## Affected files

- `python/<package>/py.typed` (new, empty)
- `python/pyproject.toml` (only if the build backend does not include package data by default)

## Effort

Small: the marker itself is minutes; the optional public-API annotation sanity pass is the only variable cost. Release as a patch release.
