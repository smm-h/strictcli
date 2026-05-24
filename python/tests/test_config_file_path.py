"""Tests for App.config_file_path property."""

import os

import strictcli


def test_default_xdg_path_json(tmp_path, monkeypatch):
    """Default config_file_path uses XDG_CONFIG_HOME with .json extension."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = strictcli.App(name="testapp", version="1.0.0", help="test app")
    expected = os.path.join(str(tmp_path), "testapp", "config.json")
    assert app.config_file_path == expected


def test_default_xdg_path_toml(tmp_path, monkeypatch):
    """config_file_path uses .toml extension when config_format='toml'."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app", config_format="toml",
    )
    expected = os.path.join(str(tmp_path), "testapp", "config.toml")
    assert app.config_file_path == expected


def test_custom_config_path_override(tmp_path):
    """config_file_path returns the override path when config_path is set."""
    custom = str(tmp_path / "custom" / "settings.json")
    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app",
        config_path=custom,
    )
    assert app.config_file_path == custom


def test_tilde_expansion(tmp_path, monkeypatch):
    """config_file_path expands ~ in config_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app",
        config_path="~/.myapp/config.json",
    )
    expected = os.path.join(str(tmp_path), ".myapp", "config.json")
    assert app.config_file_path == expected


def test_matches_config_path_command(tmp_path, monkeypatch):
    """config_file_path matches what 'config path' command prints."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app", config=True,
    )

    @app.command("run", help="run something")
    def run():
        pass

    r = app.test(["config", "path"])
    assert r.exit_code == 0
    assert app.config_file_path in r.stdout
