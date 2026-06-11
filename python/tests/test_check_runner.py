"""Tests for check runner: DAG resolution, execution, and filtering (Phase 5)."""

from dataclasses import dataclass
from pathlib import Path

import pytest

import strictcli
from strictcli import (
    CheckContext,
    CheckResult,
    _CheckDef,
    _filter_checks,
    _match_tag_expr,
    _resolve_check_order,
    _run_checks,
)


@dataclass
class SimpleContext:
    project_root: Path


def _make_check_def(
    name: str,
    tags: list[str] | None = None,
    severity: str = "error",
    depends_on: list[str] | None = None,
    impl=None,
) -> _CheckDef:
    return _CheckDef(
        name=name,
        tags=tags or ["default"],
        severity=severity,
        fast=True,
        pure=True,
        needs_network=False,
        depends_on=depends_on or [],
        impl=impl,
    )


class TestResolveCheckOrder:
    def test_single_check_no_deps(self):
        defs = {"a": _make_check_def("a")}
        order = _resolve_check_order(defs, {"a"})
        assert order == ["a"]

    def test_dependency_chain(self):
        defs = {
            "a": _make_check_def("a", depends_on=["b"]),
            "b": _make_check_def("b", depends_on=["c"]),
            "c": _make_check_def("c"),
        }
        order = _resolve_check_order(defs, {"a", "b", "c"})
        assert order.index("c") < order.index("b") < order.index("a")

    def test_dependency_pull_in(self):
        defs = {
            "a": _make_check_def("a", depends_on=["b"]),
            "b": _make_check_def("b"),
        }
        # Only select "a" -- "b" should be pulled in
        order = _resolve_check_order(defs, {"a"})
        assert "b" in order
        assert "a" in order
        assert order.index("b") < order.index("a")

    def test_cycle_detection(self):
        defs = {
            "a": _make_check_def("a", depends_on=["b"]),
            "b": _make_check_def("b", depends_on=["a"]),
        }
        with pytest.raises(ValueError, match="check dependency cycle"):
            _resolve_check_order(defs, {"a", "b"})

    def test_three_node_cycle(self):
        defs = {
            "a": _make_check_def("a", depends_on=["b"]),
            "b": _make_check_def("b", depends_on=["c"]),
            "c": _make_check_def("c", depends_on=["a"]),
        }
        with pytest.raises(ValueError, match="check dependency cycle"):
            _resolve_check_order(defs, {"a", "b", "c"})

    def test_independent_checks_all_returned(self):
        defs = {
            "a": _make_check_def("a"),
            "b": _make_check_def("b"),
            "c": _make_check_def("c"),
        }
        order = _resolve_check_order(defs, {"a", "b", "c"})
        assert set(order) == {"a", "b", "c"}

    def test_diamond_dependency(self):
        # d depends on b and c, both depend on a
        defs = {
            "a": _make_check_def("a"),
            "b": _make_check_def("b", depends_on=["a"]),
            "c": _make_check_def("c", depends_on=["a"]),
            "d": _make_check_def("d", depends_on=["b", "c"]),
        }
        order = _resolve_check_order(defs, {"d"})
        assert set(order) == {"a", "b", "c", "d"}
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")


class TestRunChecks:
    def _make_app_with_checks(self, check_defs, tmp_path, monkeypatch):
        """Build an App with pre-populated check definitions."""
        # Write a minimal TOML so the app discovers checks
        toml_lines = ['app = "testapp"', ""]
        for name, cdef in check_defs.items():
            tags_str = ", ".join(f'"{t}"' for t in cdef.tags)
            deps_str = ", ".join(f'"{d}"' for d in cdef.depends_on)
            toml_lines.append(f"[checks.{name}]")
            toml_lines.append(f"tags = [{tags_str}]")
            toml_lines.append(f'severity = "{cdef.severity}"')
            toml_lines.append(f"fast = {'true' if cdef.fast else 'false'}")
            toml_lines.append(f"pure = {'true' if cdef.pure else 'false'}")
            toml_lines.append(f"needs_network = {'true' if cdef.needs_network else 'false'}")
            toml_lines.append(f"depends_on = [{deps_str}]")
            toml_lines.append("")

        toml_file = tmp_path / "checks.toml"
        toml_file.write_text("\n".join(toml_lines))

        app = strictcli.App(
            name="testapp", version="1.0.0", help="test app",
            checks_path=str(toml_file),
        )
        # Inject the impl functions from our check_defs
        for name, cdef in check_defs.items():
            if cdef.impl is not None:
                app._check_defs[name].impl = cdef.impl
        return app

    def test_single_passing_check(self, tmp_path, monkeypatch):
        defs = {
            "a": _make_check_def(
                "a",
                impl=lambda ctx: CheckResult(status="pass", message="All good"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = _run_checks(app._check_defs, ["a"], ctx, ignore_warnings=False)
        assert exit_code == 0
        assert len(results) == 1
        assert results[0][0] == "a"
        assert results[0][1].status == "pass"

    def test_single_failing_check(self, tmp_path, monkeypatch):
        defs = {
            "a": _make_check_def(
                "a",
                impl=lambda ctx: CheckResult(status="fail", message="Broken"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = _run_checks(app._check_defs, ["a"], ctx, ignore_warnings=False)
        assert exit_code == 1
        assert results[0][1].status == "fail"

    def test_dependency_chain_passes(self, tmp_path, monkeypatch):
        defs = {
            "b": _make_check_def(
                "b",
                impl=lambda ctx: CheckResult(status="pass", message="B OK"),
            ),
            "a": _make_check_def(
                "a",
                depends_on=["b"],
                impl=lambda ctx: CheckResult(status="pass", message="A OK"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        order = _resolve_check_order(app._check_defs, {"a", "b"})
        results, exit_code = _run_checks(app._check_defs, order, ctx, ignore_warnings=False)
        assert exit_code == 0
        statuses = {name: r.status for name, r in results}
        assert statuses["a"] == "pass"
        assert statuses["b"] == "pass"

    def test_dependency_failure_skips_dependent(self, tmp_path, monkeypatch):
        defs = {
            "b": _make_check_def(
                "b",
                impl=lambda ctx: CheckResult(status="fail", message="B failed"),
            ),
            "a": _make_check_def(
                "a",
                depends_on=["b"],
                impl=lambda ctx: CheckResult(status="pass", message="A OK"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        order = _resolve_check_order(app._check_defs, {"a", "b"})
        results, exit_code = _run_checks(app._check_defs, order, ctx, ignore_warnings=False)
        assert exit_code == 1
        statuses = {name: r.status for name, r in results}
        assert statuses["b"] == "fail"
        assert statuses["a"] == "skip"
        # Verify skip message references the failed dependency
        skip_result = dict(results)["a"]
        assert 'dependency "b" failed' in skip_result.message

    def test_transitive_skip(self, tmp_path, monkeypatch):
        defs = {
            "c": _make_check_def(
                "c",
                impl=lambda ctx: CheckResult(status="fail", message="C failed"),
            ),
            "b": _make_check_def(
                "b",
                depends_on=["c"],
                impl=lambda ctx: CheckResult(status="pass", message="B OK"),
            ),
            "a": _make_check_def(
                "a",
                depends_on=["b"],
                impl=lambda ctx: CheckResult(status="pass", message="A OK"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        order = _resolve_check_order(app._check_defs, {"a", "b", "c"})
        results, exit_code = _run_checks(app._check_defs, order, ctx, ignore_warnings=False)
        assert exit_code == 1
        statuses = {name: r.status for name, r in results}
        assert statuses["c"] == "fail"
        assert statuses["b"] == "skip"
        assert statuses["a"] == "skip"

    def test_warn_with_ignore_warnings_true(self, tmp_path, monkeypatch):
        defs = {
            "a": _make_check_def(
                "a",
                severity="warn",
                impl=lambda ctx: CheckResult(status="warn", message="Watch out"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = _run_checks(app._check_defs, ["a"], ctx, ignore_warnings=True)
        assert exit_code == 0
        assert results[0][1].status == "warn"

    def test_warn_with_ignore_warnings_false(self, tmp_path, monkeypatch):
        defs = {
            "a": _make_check_def(
                "a",
                severity="warn",
                impl=lambda ctx: CheckResult(status="warn", message="Watch out"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = _run_checks(app._check_defs, ["a"], ctx, ignore_warnings=False)
        assert exit_code == 1
        assert results[0][1].status == "warn"

    def test_warn_cascades_skip_when_not_ignored(self, tmp_path, monkeypatch):
        defs = {
            "b": _make_check_def(
                "b",
                impl=lambda ctx: CheckResult(status="warn", message="Warning"),
            ),
            "a": _make_check_def(
                "a",
                depends_on=["b"],
                impl=lambda ctx: CheckResult(status="pass", message="A OK"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        order = _resolve_check_order(app._check_defs, {"a", "b"})
        results, exit_code = _run_checks(app._check_defs, order, ctx, ignore_warnings=False)
        assert exit_code == 1
        statuses = {name: r.status for name, r in results}
        assert statuses["b"] == "warn"
        assert statuses["a"] == "skip"

    def test_warn_does_not_cascade_when_ignored(self, tmp_path, monkeypatch):
        defs = {
            "b": _make_check_def(
                "b",
                impl=lambda ctx: CheckResult(status="warn", message="Warning"),
            ),
            "a": _make_check_def(
                "a",
                depends_on=["b"],
                impl=lambda ctx: CheckResult(status="pass", message="A OK"),
            ),
        }
        app = self._make_app_with_checks(defs, tmp_path, monkeypatch)
        ctx = SimpleContext(project_root=tmp_path)
        order = _resolve_check_order(app._check_defs, {"a", "b"})
        results, exit_code = _run_checks(app._check_defs, order, ctx, ignore_warnings=True)
        assert exit_code == 0
        statuses = {name: r.status for name, r in results}
        assert statuses["b"] == "warn"
        assert statuses["a"] == "pass"


class TestFilterChecks:
    def setup_method(self):
        self.defs = {
            "lint-code": _make_check_def("lint-code", tags=["code", "fast"]),
            "lint-docs": _make_check_def("lint-docs", tags=["docs", "fast"]),
            "check-deps": _make_check_def("check-deps", tags=["deps", "release"]),
            "check-changelog": _make_check_def("check-changelog", tags=["release"]),
        }

    def test_run_all(self):
        result = _filter_checks(self.defs, tag_expr=None, name_glob=None, run_all=True)
        assert result == set(self.defs.keys())

    def test_filter_by_tag(self):
        result = _filter_checks(self.defs, tag_expr="release", name_glob=None, run_all=False)
        assert result == {"check-deps", "check-changelog"}

    def test_filter_by_tag_complex(self):
        result = _filter_checks(self.defs, tag_expr="fast & code", name_glob=None, run_all=False)
        assert result == {"lint-code"}

    def test_filter_by_name_glob(self):
        result = _filter_checks(self.defs, tag_expr=None, name_glob="lint-*", run_all=False)
        assert result == {"lint-code", "lint-docs"}

    def test_filter_by_name_glob_exact(self):
        result = _filter_checks(self.defs, tag_expr=None, name_glob="lint-code", run_all=False)
        assert result == {"lint-code"}

    def test_filter_combined_intersection(self):
        # "fast" matches lint-code, lint-docs; "lint-*" matches lint-code, lint-docs
        # Intersection: lint-code, lint-docs
        result = _filter_checks(self.defs, tag_expr="fast", name_glob="lint-*", run_all=False)
        assert result == {"lint-code", "lint-docs"}

    def test_filter_combined_narrow(self):
        # "code" matches lint-code; "lint-*" matches lint-code, lint-docs
        # Intersection: lint-code only
        result = _filter_checks(self.defs, tag_expr="code", name_glob="lint-*", run_all=False)
        assert result == {"lint-code"}

    def test_no_filters_returns_empty(self):
        result = _filter_checks(self.defs, tag_expr=None, name_glob=None, run_all=False)
        assert result == set()

    def test_filter_no_matches(self):
        result = _filter_checks(self.defs, tag_expr="nonexistent", name_glob=None, run_all=False)
        assert result == set()

    def test_dependency_pull_in_with_filter(self):
        """Test that dependency pull-in works with filtered checks.

        If "a" tagged "release" depends on "b" (not tagged "release"),
        filtering by "release" selects "a", and _resolve_check_order
        pulls "b" in.
        """
        defs = {
            "a": _make_check_def("a", tags=["release"], depends_on=["b"]),
            "b": _make_check_def("b", tags=["infra"]),
        }
        selected = _filter_checks(defs, tag_expr="release", name_glob=None, run_all=False)
        assert selected == {"a"}

        order = _resolve_check_order(defs, selected)
        assert "b" in order
        assert "a" in order
        assert order.index("b") < order.index("a")
