"""Tests for the auto-registered 'check' command (Phase 6)."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

import strictcli
from conftest import pass_outcome, fail_outcome, warn_outcome


TWO_CHECKS_TOML = """\
app = "testapp"

[checks.version-check]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.lint-check]
tags = ["code", "fast"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""

THREE_CHECKS_WITH_DEP_TOML = """\
app = "testapp"

[checks.base-check]
tags = ["infra"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.version-check]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["base-check"]

[checks.lint-check]
tags = ["code", "fast"]
severity = "warn"
fast = true
pure = true
needs_network = false
depends_on = []
"""


@dataclass
class SimpleContext:
    project_root: Path


def _setup_checks_app(tmp_path, monkeypatch, toml_content, register_impls=True,
                       pass_results=None):
    """Create a temp dir with checks.toml, build an App, and register impls.

    pass_results: dict mapping check name to a minted outcome. If None, all return pass.
    """
    toml_file = tmp_path / "checks.toml"
    toml_file.write_text(toml_content)

    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app",
        checks_path=str(toml_file),
    )

    if register_impls:
        if pass_results is None:
            pass_results = {}
        for name in app._check_defs:
            if name in pass_results:
                result = pass_results[name]
                app._check_defs[name].impl = lambda ctx, r=result: r
            else:
                app._check_defs[name].impl = (
                    lambda ctx, n=name: pass_outcome(f"{n} OK")
                )

    app.set_check_context(lambda: SimpleContext(project_root=tmp_path))
    return app


class TestCheckCommandBasic:
    def test_no_flags_shows_help(self, tmp_path, monkeypatch):
        """check with no flags shows help and exits 0."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)
        result = app.test(["check"])
        assert result.exit_code == 0
        assert "check" in result.stdout.lower()

    def test_check_not_in_help_without_toml(self, tmp_path, monkeypatch):
        """check command should not appear in help when no TOML exists."""
        monkeypatch.chdir(tmp_path)
        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.command("hello", help="say hello")
        def hello(**kw):
            print("hello")

        result = app.test(["--help"])
        assert result.exit_code == 0
        # "check" should not appear as a command
        assert "check" not in result.stdout.lower() or "check" not in [
            line.strip().split()[0]
            for line in result.stdout.splitlines()
            if line.startswith("  ")
        ]

    def test_check_in_help_with_toml(self, tmp_path, monkeypatch):
        """check command appears in help when TOML exists."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)

        @app.command("hello", help="say hello")
        def hello(**kw):
            print("hello")

        result = app.test(["--help"])
        assert result.exit_code == 0
        assert "check" in result.stdout


class TestCheckList:
    def test_list_shows_checks(self, tmp_path, monkeypatch):
        """--list shows check names and tags."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)
        result = app.test(["check", "--list"])
        assert result.exit_code == 0
        assert "version-check" in result.stdout
        assert "lint-check" in result.stdout
        assert "release" in result.stdout
        assert "NAME" in result.stdout

    def test_list_json(self, tmp_path, monkeypatch):
        """--list --json produces valid JSON."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)
        result = app.test(["check", "--list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout.strip())
        assert isinstance(data, list)
        assert len(data) == 2
        names = {item["name"] for item in data}
        assert "version-check" in names
        assert "lint-check" in names
        for item in data:
            assert "tags" in item
            assert "severity" in item


class TestCheckExecution:
    def test_all_passing(self, tmp_path, monkeypatch):
        """--all runs all checks; all passing gives exit 0."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)
        result = app.test(["check", "--all"])
        assert result.exit_code == 0
        assert "PASS" in result.stdout

    def test_all_with_failure(self, tmp_path, monkeypatch):
        """--all with a failing check gives exit 1."""
        app = _setup_checks_app(
            tmp_path, monkeypatch, TWO_CHECKS_TOML,
            pass_results={
                "version-check": fail_outcome("version mismatch"),
            },
        )
        result = app.test(["check", "--all"])
        assert result.exit_code == 1
        assert "FAIL" in result.stdout
        assert "version mismatch" in result.stdout

    def test_filter_by_tag(self, tmp_path, monkeypatch):
        """--tag filters to checks with matching tags."""
        # Track which checks actually ran
        ran = []

        app = _setup_checks_app(
            tmp_path, monkeypatch, TWO_CHECKS_TOML, register_impls=False,
        )
        for name in app._check_defs:
            def make_impl(n):
                def impl(ctx):
                    ran.append(n)
                    return pass_outcome(f"{n} OK")
                return impl
            app._check_defs[name].impl = make_impl(name)

        result = app.test(["check", "--tag", "release"])
        assert result.exit_code == 0
        assert "version-check" in ran
        assert "lint-check" not in ran

    def test_filter_by_name_glob(self, tmp_path, monkeypatch):
        """--name filters by glob pattern."""
        ran = []

        app = _setup_checks_app(
            tmp_path, monkeypatch, TWO_CHECKS_TOML, register_impls=False,
        )
        for name in app._check_defs:
            def make_impl(n):
                def impl(ctx):
                    ran.append(n)
                    return pass_outcome(f"{n} OK")
                return impl
            app._check_defs[name].impl = make_impl(name)

        result = app.test(["check", "--name", "version-*"])
        assert result.exit_code == 0
        assert "version-check" in ran
        assert "lint-check" not in ran


class TestCheckDryRun:
    def test_dry_run_shows_plan(self, tmp_path, monkeypatch):
        """--all --dry-run shows plan without executing."""
        ran = []

        app = _setup_checks_app(
            tmp_path, monkeypatch, THREE_CHECKS_WITH_DEP_TOML,
            register_impls=False,
        )
        for name in app._check_defs:
            def make_impl(n):
                def impl(ctx):
                    ran.append(n)
                    return pass_outcome(f"{n} OK")
                return impl
            app._check_defs[name].impl = make_impl(name)

        result = app.test(["check", "--all", "--dry-run"])
        assert result.exit_code == 0
        assert "Would run" in result.stdout
        assert len(ran) == 0  # Nothing should have actually run
        assert "version-check" in result.stdout
        # version-check depends on base-check, so that dep should be shown
        assert "depends on" in result.stdout


class TestCheckJsonOutput:
    def test_json_output(self, tmp_path, monkeypatch):
        """--all --json produces valid JSON with results."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)
        result = app.test(["check", "--all", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout.strip())
        assert isinstance(data, list)
        assert len(data) == 2
        for item in data:
            assert "name" in item
            assert "status" in item
            assert "message" in item
            assert "problems" in item
            assert isinstance(item["problems"], list)


class TestCheckVerbose:
    def test_verbose_pass_has_no_problem_lines(self, tmp_path, monkeypatch):
        """A passing check carries no problems, so --verbose reveals nothing
        extra: the run shows PASS but emits no problem lines."""
        app = _setup_checks_app(
            tmp_path, monkeypatch, TWO_CHECKS_TOML,
            pass_results={
                "version-check": pass_outcome("All good"),
            },
        )
        result = app.test(["check", "--all", "--verbose"])
        assert result.exit_code == 0
        assert "PASS" in result.stdout
        assert "[error]" not in result.stdout
        assert "[warn]" not in result.stdout

    def test_non_verbose_pass_has_no_problem_lines(self, tmp_path, monkeypatch):
        """Without --verbose, a passing check shows no problem lines either."""
        app = _setup_checks_app(
            tmp_path, monkeypatch, TWO_CHECKS_TOML,
            pass_results={
                "version-check": pass_outcome("All good"),
            },
        )
        result = app.test(["check", "--all"])
        assert result.exit_code == 0
        assert "[error]" not in result.stdout
        assert "[warn]" not in result.stdout


class TestCheckIgnoreWarnings:
    def test_ignore_warnings(self, tmp_path, monkeypatch):
        """--ignore-warnings makes warn severity not cause exit 1."""
        app = _setup_checks_app(
            tmp_path, monkeypatch, THREE_CHECKS_WITH_DEP_TOML,
            pass_results={
                "lint-check": warn_outcome("minor issue"),
            },
        )
        result = app.test(["check", "--all", "--ignore-warnings"])
        assert result.exit_code == 0
        assert "WARN" in result.stdout

    def test_warn_without_ignore_causes_exit_1(self, tmp_path, monkeypatch):
        """Without --ignore-warnings, warn causes exit 1."""
        app = _setup_checks_app(
            tmp_path, monkeypatch, THREE_CHECKS_WITH_DEP_TOML,
            pass_results={
                "lint-check": warn_outcome("minor issue"),
            },
        )
        result = app.test(["check", "--all"])
        assert result.exit_code == 1


class TestCheckNoContextFactory:
    def test_no_context_factory_error(self, tmp_path):
        """Running checks without set_check_context produces error."""
        toml_file = tmp_path / "checks.toml"
        toml_file.write_text(TWO_CHECKS_TOML)

        app = strictcli.App(
            name="testapp", version="1.0.0", help="test app",
            checks_path=str(toml_file),
        )
        for name in app._check_defs:
            app._check_defs[name].impl = (
                lambda ctx, n=name: pass_outcome(f"{n} OK")
            )
        # Do NOT call set_check_context

        result = app.test(["check", "--all"])
        assert result.exit_code == 1
        assert "no check context configured" in result.stderr


class TestCheckFailDetails:
    def test_fail_details_shown(self, tmp_path, monkeypatch):
        """Failing check details are shown without --verbose."""
        app = _setup_checks_app(
            tmp_path, monkeypatch, TWO_CHECKS_TOML,
            pass_results={
                "version-check": fail_outcome("3 commits not covered", "a1b2c3d: fix typo", "e4f5g6h: add feature"),
            },
        )
        result = app.test(["check", "--all"])
        assert result.exit_code == 1
        assert "a1b2c3d: fix typo" in result.stdout
        assert "e4f5g6h: add feature" in result.stdout


class TestCheckNoMatchFilters:
    def test_no_matches(self, tmp_path, monkeypatch):
        """When filters match nothing, print message and exit 0."""
        app = _setup_checks_app(tmp_path, monkeypatch, TWO_CHECKS_TOML)
        result = app.test(["check", "--tag", "nonexistent"])
        assert result.exit_code == 0
        assert "No checks matched" in result.stdout
