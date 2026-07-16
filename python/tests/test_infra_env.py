"""Tests for the InfraEnv primitive: location roots, handshake vars, markers."""

import json
import os

import pytest

import strictcli
from strictcli import App, Context, RelativeToRoot


# --- Eager root resolution ---


def test_infra_root_env_set(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    assert app._infra_roots["MYAPP_HOME"] == "/opt/data"
    assert app._infra_root_from_env["MYAPP_HOME"] is True


def test_infra_root_unset(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    assert app._infra_roots["MYAPP_HOME"] == "/var/lib/myapp"
    assert app._infra_root_from_env["MYAPP_HOME"] is False


def test_infra_root_tilde_expansion(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "~/.myapp"})
    assert app._infra_roots["MYAPP_HOME"] == os.path.join(os.path.expanduser("~"), ".myapp")


def test_infra_root_tilde_expansion_from_env(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "~/data")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    assert app._infra_roots["MYAPP_HOME"] == os.path.join(os.path.expanduser("~"), "data")


# --- Flag-default marker + infra provenance ---


def _make_flag_app(monkeypatch):
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured = {}

    @app.command("run", help="run it")
    @strictcli.flag("db", help="db path", default=RelativeToRoot("MYAPP_HOME", "db.sqlite"))
    def run(db):
        captured["db"] = db
        return 0

    return app, captured


def test_flag_default_marker_infra_provenance(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_flag_app(monkeypatch)
    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["db"] == "/var/lib/myapp/db.sqlite"
    assert app._last_sources["db"] == "infra"


def test_flag_default_marker_hermetic_immune(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app, captured = _make_flag_app(monkeypatch)
    # Even under --hermetic, the root resolves (no argv dependency).
    r = app.test(["--hermetic", "run"])
    assert r.exit_code == 0, r.stderr
    assert captured["db"] == "/opt/data/db.sqlite"
    assert app._last_sources["db"] == "infra"


def test_cli_override_not_infra(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_flag_app(monkeypatch)
    r = app.test(["run", "--db", "/tmp/custom.db"])
    assert r.exit_code == 0, r.stderr
    assert captured["db"] == "/tmp/custom.db"
    assert app._last_sources["db"] == "cli"


# --- Config-path marker rewrite ---


def test_config_path_marker_rewrite(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app = App(name="myapp", version="1.0.0", help="t",
              config=True,
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              config_path=RelativeToRoot("MYAPP_HOME", "config.json"))
    assert app.config_path == "/opt/data/config.json"
    r = app.test(["config", "path"])
    assert "/opt/data/config.json" in r.stdout


# --- Undeclared root marker: registration hard error ---


def test_undeclared_root_marker_raises(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    with pytest.raises(ValueError, match="undeclared infra root"):
        @app.command("run", help="run it")
        @strictcli.flag("db", help="db path", default=RelativeToRoot("NOPE", "x"))
        def run(db):
            return 0


def test_config_path_marker_undeclared_raises():
    with pytest.raises(ValueError, match="undeclared infra root"):
        App(name="myapp", version="1.0.0", help="t",
            config=True,
            config_path=RelativeToRoot("NOPE", "config.json"))


# --- Handshake + accessor ---


def test_infra_value_root_and_handshake_live(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    monkeypatch.setenv("CI_TOKEN", "abc123")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})
    captured = {}

    @app.command("run", help="run it")
    def run(ctx: Context):
        captured["root"] = ctx.infra_value("MYAPP_HOME")
        captured["hs"] = ctx.infra_value("CI_TOKEN")
        return 0

    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["root"] == ("/opt/data", True)
    assert captured["hs"] == ("abc123", True)


def test_infra_value_handshake_unset(monkeypatch):
    monkeypatch.delenv("CI_TOKEN", raising=False)
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})
    captured = {}

    @app.command("run", help="run it")
    def run(ctx: Context):
        captured["hs"] = ctx.infra_value("CI_TOKEN")
        return 0

    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["hs"] == (None, False)


def test_infra_value_undeclared_raises(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured = {}

    @app.command("run", help="run it")
    def run(ctx: Context):
        try:
            ctx.infra_value("UNDECLARED_VAR")
        except KeyError:
            captured["raised"] = True
        return 0

    app.test(["run"])
    assert captured.get("raised") is True


def test_handshake_duplicate_root_raises():
    with pytest.raises(ValueError, match="already declared as an infra root"):
        App(name="myapp", version="1.0.0", help="t",
            infra_root={"SHARED": "/x"},
            handshake_env={"SHARED": "collides"})


def test_handshake_empty_help_raises():
    with pytest.raises(ValueError, match="help must be a non-empty string"):
        App(name="myapp", version="1.0.0", help="t",
            handshake_env={"CI_TOKEN": ""})


# --- Surfaces: schema, help, config show ---


def test_infra_schema_surface(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})
    schema = app.dump_schema_dict()
    assert "infra" in schema
    root0 = schema["infra"]["roots"][0]
    assert root0 == {"env_var": "MYAPP_HOME", "default": "/var/lib/myapp"}
    # Machine-stable: resolved value must NOT be present.
    assert "resolved" not in root0
    hs0 = schema["infra"]["handshakes"][0]
    assert hs0 == {"env_var": "CI_TOKEN", "help": "CI auth token"}


def test_infra_schema_absent_when_undeclared():
    app = App(name="myapp", version="1.0.0", help="t")
    assert "infra" not in app.dump_schema_dict()


def test_infra_help_surface(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})

    @app.command("run", help="run it")
    def run():
        return 0

    r = app.test(["--help"])
    assert "Infrastructure:" in r.stdout
    assert "MYAPP_HOME" in r.stdout
    assert "CI_TOKEN" in r.stdout


def test_infra_config_show_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    monkeypatch.delenv("CI_TOKEN", raising=False)
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    app = App(name="myapp", version="1.0.0", help="t",
              config=True, config_path=str(config_file),
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})

    r = app.test(["config", "show", "--plain"])
    assert "Infrastructure:" in r.stdout
    assert "MYAPP_HOME (root) = /opt/data" in r.stdout
    assert "source: env-set" in r.stdout
    assert "CI_TOKEN (handshake) = <unset>" in r.stdout

    rj = app.test(["config", "show", "--json"])
    result = json.loads(rj.stdout)
    infra = result["__infrastructure__"]
    assert infra["MYAPP_HOME"]["resolved"] == "/opt/data"
    assert infra["MYAPP_HOME"]["source"] == "env"
    assert infra["CI_TOKEN"]["set"] is False
