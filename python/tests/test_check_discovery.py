"""Tests for check discovery and double-entry registration (Phase 3)."""

import os

import pytest

import strictcli


VALID_TOML = """\
[checks.lint-code]
tags = ["code", "fast"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-deps]
tags = ["deps"]
severity = "warn"
fast = false
pure = false
needs_network = true
depends_on = ["lint-code"]
"""

INVALID_TOML = """\
[checks.BadName]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""


class TestDiscovery:
    def test_discovers_checks_toml_in_cwd(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(VALID_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")
        assert app._checks_enabled is True
        assert "lint-code" in app._check_defs
        assert "check-deps" in app._check_defs

    def test_no_toml_sets_checks_disabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")
        assert app._checks_enabled is False
        assert app._check_defs == {}

    def test_invalid_toml_raises_valueerror(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(INVALID_TOML)
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError, match='invalid check name "BadName"'):
            strictcli.App(name="testapp", version="1.0.0", help="test app")


class TestCheckDecorator:
    def test_registers_implementation(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(VALID_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.check("lint-code")
        def lint_impl(ctx):
            return strictcli.CheckResult(status="pass", message="OK")

        assert app._check_defs["lint-code"].impl is lint_impl

    def test_undeclared_name_raises(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(VALID_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        with pytest.raises(ValueError, match='cannot register check "nonexistent"'):
            @app.check("nonexistent")
            def bad_impl(ctx):
                pass

    def test_duplicate_registration_raises(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(VALID_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.check("lint-code")
        def first(ctx):
            pass

        with pytest.raises(ValueError, match='check "lint-code": duplicate registration'):
            @app.check("lint-code")
            def second(ctx):
                pass

    def test_no_toml_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        with pytest.raises(ValueError, match="no .strictcli/checks.toml found"):
            @app.check("anything")
            def bad(ctx):
                pass


class TestDoubleEntryValidation:
    def test_missing_impl_error_in_test(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(VALID_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        # Register a dummy command so the app has something to run
        @app.command("hello", help="say hello")
        def hello(**kw):
            print("hello")

        # Only register one of the two checks
        @app.check("lint-code")
        def lint_impl(ctx):
            return strictcli.CheckResult(status="pass", message="OK")

        # check-deps is not registered -- should fail validation
        result = app.test(["hello"])
        assert result.exit_code == 1
        assert "checks declared in .strictcli/checks.toml but not registered" in result.stderr
        assert "check-deps" in result.stderr

    def test_all_registered_passes_validation(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(VALID_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.command("hello", help="say hello")
        def hello(**kw):
            print("hello")

        @app.check("lint-code")
        def lint_impl(ctx):
            return strictcli.CheckResult(status="pass", message="OK")

        @app.check("check-deps")
        def deps_impl(ctx):
            return strictcli.CheckResult(status="pass", message="OK")

        result = app.test(["hello"])
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_no_checks_skips_validation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.command("hello", help="say hello")
        def hello(**kw):
            print("hello")

        result = app.test(["hello"])
        assert result.exit_code == 0
        assert "hello" in result.stdout
