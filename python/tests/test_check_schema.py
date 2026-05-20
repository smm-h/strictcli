"""Tests for check metadata in --dump-schema output (Phase 7)."""

import json

import strictcli


CHECKS_TOML = """\
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


class TestSchemaWithChecks:
    """--dump-schema includes checks key when checks are enabled."""

    def test_checks_key_present(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(CHECKS_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.check("lint-code")
        def lint_impl(ctx):
            return strictcli.CheckResult(status="pass", message="ok")

        @app.check("check-deps")
        def deps_impl(ctx):
            return strictcli.CheckResult(status="pass", message="ok")

        @app.command("noop", help="Does nothing")
        def noop():
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "checks" in data
        assert isinstance(data["checks"], dict)
        assert len(data["checks"]) == 2

    def test_check_metadata_correct(self, tmp_path, monkeypatch):
        (tmp_path / ".strictcli").mkdir()
        (tmp_path / ".strictcli" / "checks.toml").write_text(CHECKS_TOML)
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.check("lint-code")
        def lint_impl(ctx):
            return strictcli.CheckResult(status="pass", message="ok")

        @app.check("check-deps")
        def deps_impl(ctx):
            return strictcli.CheckResult(status="pass", message="ok")

        @app.command("noop", help="Does nothing")
        def noop():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())

        lint = data["checks"]["lint-code"]
        assert lint["tags"] == ["code", "fast"]
        assert lint["severity"] == "error"
        assert lint["fast"] is True
        assert lint["pure"] is True
        assert lint["needs_network"] is False
        assert lint["depends_on"] == []

        deps = data["checks"]["check-deps"]
        assert deps["tags"] == ["deps"]
        assert deps["severity"] == "warn"
        assert deps["fast"] is False
        assert deps["pure"] is False
        assert deps["needs_network"] is True
        assert deps["depends_on"] == ["lint-code"]


class TestSchemaWithoutChecks:
    """--dump-schema omits checks key when checks are not enabled."""

    def test_no_checks_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        app = strictcli.App(name="testapp", version="1.0.0", help="test app")

        @app.command("noop", help="Does nothing")
        def noop():
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "checks" not in data
