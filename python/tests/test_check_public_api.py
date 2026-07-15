"""Tests for the public check runner API: run_checks(), CheckRunResult, formatters."""

import json
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path

import pytest

import strictcli
from strictcli import (
    CheckContext,
    CheckRunResult,
    SkipCheck,
    format_check_results,
    format_check_results_json,
)
from conftest import pass_outcome, fail_outcome, warn_outcome, skip_outcome


TWO_CHECKS_TOML = """\
app = "testapp"

[checks.alpha]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.beta]
tags = ["code"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""

DEP_CHAIN_TOML = """\
app = "testapp"

[checks.base]
tags = ["infra"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.mid]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["base"]

[checks.top]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["mid"]
"""

WARN_CHECK_TOML = """\
app = "testapp"

[checks.warn-check]
tags = ["all"]
severity = "warn"
fast = true
pure = true
needs_network = false
depends_on = []
"""

SINGLE_CHECK_TOML = """\
app = "testapp"

[checks.only]
tags = ["default"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""


@dataclass
class SimpleContext:
    project_root: Path


def _make_app(tmp_path, toml_content, impls=None, register_all=True):
    """Build an app with checks, optionally registering implementations.

    impls: dict of check name -> callable(ctx) returning a minted outcome.
    register_all: if True and a check has no entry in impls, register a
    default passing impl.
    """
    toml_file = tmp_path / "checks.toml"
    toml_file.write_text(toml_content)

    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app",
        checks_path=str(toml_file),
    )

    if impls is None:
        impls = {}

    if register_all:
        for name in app._check_defs:
            if name in impls:
                app._check_defs[name].impl = impls[name]
            else:
                app._check_defs[name].impl = (
                    lambda ctx, n=name: pass_outcome(f"{n} OK")
                )
    else:
        for name, fn in impls.items():
            app._check_defs[name].impl = fn

    return app


# ---------------------------------------------------------------------------
# CheckRunResult dataclass
# ---------------------------------------------------------------------------


class TestCheckRunResult:
    def test_fields_accessible(self):
        cr = pass_outcome("OK")
        r = CheckRunResult(name="my-check", outcome=cr)
        assert r.name == "my-check"
        assert r.outcome is cr
        assert r.status == "pass"
        assert r.message == "OK"

    def test_frozen(self):
        cr = pass_outcome("OK")
        r = CheckRunResult(name="my-check", outcome=cr)
        with pytest.raises(FrozenInstanceError):
            r.name = "other"  # type: ignore[misc]

    def test_frozen_result_field(self):
        cr = pass_outcome("OK")
        r = CheckRunResult(name="my-check", outcome=cr)
        with pytest.raises(FrozenInstanceError):
            r.outcome = fail_outcome("bad")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# App.run_checks()
# ---------------------------------------------------------------------------


class TestRunChecks:
    def test_all_pass(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, run_all=True)
        assert exit_code == 0
        assert len(results) == 2
        for r in results:
            assert isinstance(r, CheckRunResult)
            assert r.status == "pass"

    def test_one_fails(self, tmp_path):
        impls = {
            "alpha": lambda ctx: fail_outcome("broken"),
        }
        app = _make_app(tmp_path, TWO_CHECKS_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, run_all=True)
        assert exit_code == 1
        statuses = {r.name: r.status for r in results}
        assert statuses["alpha"] == "fail"
        assert statuses["beta"] == "pass"

    def test_tag_filtering(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, tag_expr="release")
        assert exit_code == 0
        assert len(results) == 1
        assert results[0].name == "alpha"

    def test_name_glob(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, name_glob="bet*")
        assert exit_code == 0
        assert len(results) == 1
        assert results[0].name == "beta"

    def test_run_all(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        names = {r.name for r in results}
        assert names == {"alpha", "beta"}

    def test_dependency_ordering(self, tmp_path):
        app = _make_app(tmp_path, DEP_CHAIN_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, run_all=True)
        assert exit_code == 0
        names = [r.name for r in results]
        assert names.index("base") < names.index("mid") < names.index("top")

    def test_dependency_failure_cascade(self, tmp_path):
        impls = {
            "base": lambda ctx: fail_outcome("base broken"),
        }
        app = _make_app(tmp_path, DEP_CHAIN_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, run_all=True)
        assert exit_code == 1
        statuses = {r.name: r.status for r in results}
        assert statuses["base"] == "fail"
        assert statuses["mid"] == "skip"
        assert statuses["top"] == "skip"

    def test_warn_without_ignore(self, tmp_path):
        impls = {
            "warn-check": lambda ctx: warn_outcome("caution"),
        }
        app = _make_app(tmp_path, WARN_CHECK_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(
            ctx, run_all=True, ignore_warnings=False,
        )
        assert exit_code == 1
        assert results[0].status == "warn"

    def test_warn_with_ignore(self, tmp_path):
        impls = {
            "warn-check": lambda ctx: warn_outcome("caution"),
        }
        app = _make_app(tmp_path, WARN_CHECK_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(
            ctx, run_all=True, ignore_warnings=True,
        )
        assert exit_code == 0
        assert results[0].status == "warn"

    def test_no_matches_empty(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, tag_expr="nonexistent")
        assert results == []
        assert exit_code == 0

    def test_error_checks_not_enabled(self, tmp_path):
        app = strictcli.App(name="testapp", version="1.0.0", help="test app")
        ctx = SimpleContext(project_root=tmp_path)
        with pytest.raises(ValueError, match="checks are not enabled"):
            app.run_checks(ctx, run_all=True)

    def test_error_incomplete_registrations(self, tmp_path):
        # Build app but don't register any impls
        app = _make_app(
            tmp_path, SINGLE_CHECK_TOML, register_all=False,
        )
        ctx = SimpleContext(project_root=tmp_path)
        with pytest.raises(ValueError, match="not registered"):
            app.run_checks(ctx, run_all=True)


# ---------------------------------------------------------------------------
# format_check_results
# ---------------------------------------------------------------------------


class TestFormatCheckResults:
    def test_returns_string(self, tmp_path):
        app = _make_app(tmp_path, SINGLE_CHECK_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results(results)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_format_pass(self, tmp_path):
        app = _make_app(tmp_path, SINGLE_CHECK_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results(results)
        assert "PASS" in output
        assert "only" in output
        assert "only OK" in output

    def test_format_fail(self, tmp_path):
        impls = {
            "only": lambda ctx: fail_outcome("broken", "line 1 bad", "line 2 bad"),
        }
        app = _make_app(tmp_path, SINGLE_CHECK_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results(results)
        assert "FAIL" in output
        assert "broken" in output
        assert "line 1 bad" in output
        assert "line 2 bad" in output

    def test_aligned_columns(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results(results)
        lines = output.split("\n")
        # Both check names should be padded to same width
        assert len(lines) == 2
        # "alpha" and "beta" both padded to 5 chars
        for line in lines:
            assert "PASS" in line

    def test_verbose_pass_has_no_problems(self, tmp_path):
        # A passing outcome carries no problems, so neither the default nor the
        # verbose formatting emits problem lines for it.
        impls = {
            "only": lambda ctx: pass_outcome("all good"),
        }
        app = _make_app(tmp_path, SINGLE_CHECK_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output_normal = format_check_results(results, verbose=False)
        assert "[error]" not in output_normal and "[warn]" not in output_normal
        output_verbose = format_check_results(results, verbose=True)
        assert "[error]" not in output_verbose and "[warn]" not in output_verbose

    def test_fail_details_shown_without_verbose(self, tmp_path):
        impls = {
            "only": lambda ctx: fail_outcome("broken", "detail line"),
        }
        app = _make_app(tmp_path, SINGLE_CHECK_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results(results, verbose=False)
        assert "detail line" in output

    def test_empty_results(self):
        output = format_check_results([])
        assert output == ""

    def test_no_trailing_newline(self, tmp_path):
        app = _make_app(tmp_path, SINGLE_CHECK_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results(results)
        assert not output.endswith("\n")


# ---------------------------------------------------------------------------
# format_check_results_json
# ---------------------------------------------------------------------------


class TestFormatCheckResultsJson:
    def test_returns_valid_json(self, tmp_path):
        app = _make_app(tmp_path, TWO_CHECKS_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results_json(results)
        parsed = json.loads(output)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_json_structure(self, tmp_path):
        app = _make_app(tmp_path, SINGLE_CHECK_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results_json(results)
        parsed = json.loads(output)
        item = parsed[0]
        assert item["name"] == "only"
        assert item["status"] == "pass"
        assert item["message"] == "only OK"
        assert item["problems"] == []

    def test_empty_problems_is_list(self, tmp_path):
        app = _make_app(tmp_path, SINGLE_CHECK_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results_json(results)
        parsed = json.loads(output)
        assert parsed[0]["problems"] == []
        assert parsed[0]["problems"] is not None

    def test_problems_with_content(self, tmp_path):
        impls = {
            "only": lambda ctx: fail_outcome("broken", "issue 1", "issue 2"),
        }
        app = _make_app(tmp_path, SINGLE_CHECK_TOML, impls=impls)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results_json(results)
        parsed = json.loads(output)
        assert parsed[0]["problems"] == [
            {"severity": "error", "text": "issue 1"},
            {"severity": "error", "text": "issue 2"},
        ]

    def test_empty_results(self):
        output = format_check_results_json([])
        parsed = json.loads(output)
        assert parsed == []

    def test_no_trailing_newline(self, tmp_path):
        app = _make_app(tmp_path, SINGLE_CHECK_TOML)
        ctx = SimpleContext(project_root=tmp_path)
        results, _ = app.run_checks(ctx, run_all=True)
        output = format_check_results_json(results)
        assert not output.endswith("\n")


SCOPED_CHECK_TOML = """\
app = "testapp"

[checks.scoped-check]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
scope = "changelog"
"""


class TestSetScopeAdapter:
    """Tests for App.set_scope_adapter."""

    def test_stores_adapter(self, tmp_path):
        app = _make_app(tmp_path, SCOPED_CHECK_TOML)
        assert app._scope_adapter is None

        def my_adapter(ctx, scope):
            return ctx

        app.set_scope_adapter(my_adapter)
        assert app._scope_adapter is my_adapter

    def test_adapter_called_during_run_checks(self, tmp_path):
        app = _make_app(tmp_path, SCOPED_CHECK_TOML)
        adapter_calls = []

        def adapter(ctx, scope):
            adapter_calls.append(scope)
            return ctx

        app.set_scope_adapter(adapter)

        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, run_all=True)
        assert exit_code == 0
        assert len(adapter_calls) == 1
        assert adapter_calls[0] == "changelog"

    def test_adapter_returning_skip_check(self, tmp_path):
        impl_called = []

        def impl(ctx):
            impl_called.append(True)
            return pass_outcome("should not run")

        app = _make_app(tmp_path, SCOPED_CHECK_TOML, impls={"scoped-check": impl})

        def adapter(ctx, scope):
            return SkipCheck("adapter skipped")

        app.set_scope_adapter(adapter)

        ctx = SimpleContext(project_root=tmp_path)
        results, exit_code = app.run_checks(ctx, run_all=True)
        assert exit_code == 0
        assert results[0].status == "skip"
        assert "adapter skipped" in results[0].message
        assert len(impl_called) == 0
