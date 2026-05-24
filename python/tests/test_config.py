"""Tests for JSON config file support."""

import json
import os

import pytest

import strictcli


def _make_config_app(config=True, flags=None):
    """Helper: app with config support and a simple command."""
    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=config,
        flags=flags or [],
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    @strictcli.flag("count", type=int, help="how many", default=1)
    @strictcli.flag("verbose", type=bool, help="be verbose")
    def run(target, count, verbose):
        print(f"target={target} count={count} verbose={verbose}")

    return app


def _write_config(tmp_path, app_name, data):
    """Write a config JSON file and return its directory."""
    config_dir = tmp_path / app_name
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(data, indent=2) + "\n")
    return str(tmp_path)


# --- Test 1: config=False has no config subcommand ---

def test_no_config_group_when_disabled():
    """App with config=False has no config subcommand."""
    app = _make_config_app(config=False)
    r = app.test(["config", "path"])
    assert r.exit_code == 1
    assert "unknown command" in r.stderr


# --- Test 2: config=True has config group with subcommands ---

def test_config_group_exists():
    """App with config=True has config group with show/set/path/edit subcommands."""
    app = _make_config_app(config=True)
    r = app.test(["config", "--help"])
    assert r.exit_code == 0
    assert "show" in r.stdout
    assert "set" in r.stdout
    assert "path" in r.stdout
    assert "edit" in r.stdout


# --- Test 3: config values used when no CLI or env ---

def test_config_value_used(tmp_path, monkeypatch):
    """Config file values are used when no CLI or env value is provided."""
    config_home = _write_config(tmp_path, "testapp", {"target": "from-config"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    # Must create the app AFTER setting XDG_CONFIG_HOME so it loads the config
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=from-config" in r.stdout


# --- Test 4: CLI flag overrides config value ---

def test_cli_overrides_config(tmp_path, monkeypatch):
    """CLI flag overrides config value."""
    config_home = _write_config(tmp_path, "testapp", {"target": "from-config"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["run", "--target", "from-cli"])
    assert r.exit_code == 0
    assert "target=from-cli" in r.stdout


# --- Test 5: env var overrides config value ---

def test_env_overrides_config(tmp_path, monkeypatch):
    """Env var overrides config value."""
    config_home = _write_config(tmp_path, "testapp", {"target": "from-config"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        env_prefix="TESTAPP",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val",
                     env="TESTAPP_TARGET")
    def run(target):
        print(f"target={target}")

    monkeypatch.setenv("TESTAPP_TARGET", "from-env")
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=from-env" in r.stdout


# --- Test 6: config value overrides default ---

def test_config_overrides_default(tmp_path, monkeypatch):
    """Config value overrides code default."""
    config_home = _write_config(tmp_path, "testapp", {"count": 42})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "count=42" in r.stdout
    # Also verify default was NOT used
    assert "count=1" not in r.stdout


# --- Test 7: invalid JSON prints warning and falls back ---

def test_invalid_json_warning(tmp_path, monkeypatch):
    """Config with invalid JSON prints warning and falls back."""
    config_dir = tmp_path / "testapp"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config_file.write_text("{invalid json!!")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # App should still work, using defaults
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=default-val" in r.stdout


# --- Test 8: config set creates file and directory ---

def test_config_set_creates_file(tmp_path, monkeypatch):
    """Config set creates file and directory if needed."""
    config_home = str(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "set", "target", "new-value"])
    assert r.exit_code == 0

    # Verify the file was created
    config_file = tmp_path / "testapp" / "config.json"
    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["target"] == "new-value"


# --- Test 9: config path prints the correct path ---

def test_config_path(tmp_path, monkeypatch):
    """Config path prints the correct path."""
    config_home = str(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "path"])
    assert r.exit_code == 0
    expected = os.path.join(config_home, "testapp", "config.json")
    assert expected in r.stdout


# --- Test 10: config show displays values with source attribution ---

def test_config_show(tmp_path, monkeypatch):
    """Config show displays values with source attribution."""
    config_home = _write_config(tmp_path, "testapp", {"target": "from-config"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "show"])
    assert r.exit_code == 0
    assert "target = from-config  (source: config)" in r.stdout
    assert "count = 1  (source: default)" in r.stdout
    assert "verbose = False  (source: default)" in r.stdout


# --- Test 11: config respects XDG_CONFIG_HOME ---

def test_xdg_config_home(tmp_path, monkeypatch):
    """Config respects XDG_CONFIG_HOME env var."""
    custom_dir = tmp_path / "custom-config"
    config_home = _write_config(custom_dir, "testapp", {"target": "xdg-value"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=xdg-value" in r.stdout


# --- Additional: config with bool values ---

def test_config_bool_value(tmp_path, monkeypatch):
    """Config file with bool values works correctly."""
    config_home = _write_config(tmp_path, "testapp", {"verbose": True})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


# --- Additional: config with int values ---

def test_config_int_value(tmp_path, monkeypatch):
    """Config file with int values works correctly."""
    config_home = _write_config(tmp_path, "testapp", {"count": 99})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "count=99" in r.stdout


# --- Additional: config file does not exist returns empty dict ---

def test_config_missing_file(tmp_path, monkeypatch):
    """Missing config file results in defaults being used."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=default-val" in r.stdout
    assert "count=1" in r.stdout


# --- Additional: config with global flags ---

def test_config_with_global_flags(tmp_path, monkeypatch):
    """Config works with global flags too."""
    config_home = _write_config(tmp_path, "testapp", {"output": "json"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        flags=[strictcli.Flag(name="output", type=str, help="output format", default="text")],
    )

    @app.command("run", help="run something")
    def run(output):
        print(f"output={output}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "output=json" in r.stdout


# --- Additional: config set updates existing file ---

def test_config_set_updates_existing(tmp_path, monkeypatch):
    """Config set updates an existing config file without losing other keys."""
    config_home = _write_config(tmp_path, "testapp", {"target": "old", "count": 5})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "set", "target", "new"])
    assert r.exit_code == 0

    config_file = tmp_path / "testapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["target"] == "new"
    # Other keys should be preserved
    assert data["count"] == 5


# --- Additional: config with choices validation ---

def test_config_choices_validation(tmp_path, monkeypatch):
    """Config values are validated against choices."""
    config_home = _write_config(tmp_path, "testapp", {"format": "invalid"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("format", type=str, help="output format",
                     choices=["json", "yaml", "text"], default="text")
    def run(format):
        print(f"format={format}")

    r = app.test(["run"])
    assert r.exit_code == 1
    assert "invalid value" in r.stderr


# --- Additional: config with validate function ---

def test_config_validate_function(tmp_path, monkeypatch):
    """Config values are validated with custom validate function."""
    config_home = _write_config(tmp_path, "testapp", {"port": -1})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)

    def validate_port(v):
        if v < 1 or v > 65535:
            raise ValueError("port must be between 1 and 65535")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("port", type=int, help="port number", default=8080,
                     validate=validate_port)
    def run(port):
        print(f"port={port}")

    r = app.test(["run"])
    assert r.exit_code == 1
    assert "port must be between 1 and 65535" in r.stderr


# --- Additional: float config value ---

def test_config_float_value(tmp_path, monkeypatch):
    """Config file with float values works correctly."""
    config_home = _write_config(tmp_path, "testapp", {"ratio": 0.75})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("ratio", type=float, help="ratio value", default=1.0)
    def run(ratio):
        print(f"ratio={ratio}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "ratio=0.75" in r.stdout


# --- Additional: int promoted to float in config ---

def test_config_int_as_float(tmp_path, monkeypatch):
    """JSON integer in config is accepted for float flags."""
    config_home = _write_config(tmp_path, "testapp", {"ratio": 2})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("ratio", type=float, help="ratio value", default=1.0)
    def run(ratio):
        print(f"ratio={ratio}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "ratio=2.0" in r.stdout


# --- Custom config_path tests ---

def test_custom_config_path(tmp_path, monkeypatch):
    """Custom config_path is used instead of XDG-computed path."""
    config_file = tmp_path / "my-custom-config.json"
    config_file.write_text(json.dumps({"target": "custom-path-val"}) + "\n")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    def run(target):
        print(f"target={target}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=custom-path-val" in r.stdout


def test_custom_config_path_tilde_expansion(tmp_path, monkeypatch):
    """Custom config_path expands ~ correctly."""
    monkeypatch.setenv("HOME", str(tmp_path))
    config_dir = tmp_path / ".myapp"
    config_dir.mkdir()
    config_file = config_dir / "settings.json"
    config_file.write_text(json.dumps({"target": "tilde-val"}) + "\n")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path="~/.myapp/settings.json",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    def run(target):
        print(f"target={target}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=tilde-val" in r.stdout


def test_custom_config_path_config_path_command(tmp_path):
    """config path command prints the custom path."""
    config_file = tmp_path / "custom.json"
    config_file.write_text("{}")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    def run():
        pass

    r = app.test(["config", "path"])
    assert r.exit_code == 0
    assert str(config_file) in r.stdout


def test_custom_config_path_config_set(tmp_path):
    """config set writes to the custom path."""
    config_file = tmp_path / "custom.json"

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    def run(target):
        print(f"target={target}")

    r = app.test(["config", "set", "target", "written"])
    assert r.exit_code == 0
    assert config_file.exists()
    data = json.loads(config_file.read_text())
    assert data["target"] == "written"


# --- TOML config format tests ---

def test_toml_format_reads_correctly(tmp_path):
    """TOML format config reads values correctly."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('target = "toml-value"\ncount = 42\nverbose = true\n')

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    @strictcli.flag("count", type=int, help="how many", default=1)
    @strictcli.flag("verbose", type=bool, help="be verbose")
    def run(target, count, verbose):
        print(f"target={target} count={count} verbose={verbose}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=toml-value" in r.stdout
    assert "count=42" in r.stdout
    assert "verbose=True" in r.stdout


def test_toml_format_set_writes_correctly(tmp_path):
    """TOML format config set writes valid TOML."""
    config_file = tmp_path / "config.toml"

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    def run(target):
        print(f"target={target}")

    r = app.test(["config", "set", "target", "toml-written"])
    assert r.exit_code == 0
    assert config_file.exists()

    import tomllib
    with open(config_file, "rb") as f:
        data = tomllib.load(f)
    assert data["target"] == "toml-written"


def test_toml_format_set_preserves_existing(tmp_path):
    """TOML format config set preserves existing keys."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('existing = "keep-me"\n')

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    def run(target):
        print(f"target={target}")

    r = app.test(["config", "set", "target", "new-val"])
    assert r.exit_code == 0

    import tomllib
    with open(config_file, "rb") as f:
        data = tomllib.load(f)
    assert data["target"] == "new-val"
    assert data["existing"] == "keep-me"


def test_toml_format_config_path_command(tmp_path):
    """config path prints the custom path for TOML format."""
    config_file = tmp_path / "my-config.toml"
    config_file.write_text("")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    def run():
        pass

    r = app.test(["config", "path"])
    assert r.exit_code == 0
    assert str(config_file) in r.stdout


def test_toml_format_xdg_default_path(tmp_path, monkeypatch):
    """Without custom config_path, TOML format uses .toml extension in XDG path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_format="toml",
    )

    @app.command("run", help="run something")
    def run():
        pass

    r = app.test(["config", "path"])
    assert r.exit_code == 0
    expected = os.path.join(str(tmp_path), "testapp", "config.toml")
    assert expected in r.stdout


def test_invalid_toml_warning(tmp_path):
    """Invalid TOML file prints warning and falls back to defaults."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("this is = not [ valid toml")

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    def run(target):
        print(f"target={target}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=default-val" in r.stdout


def test_invalid_config_format():
    """Invalid config_format raises ValueError."""
    with pytest.raises(ValueError, match='config_format must be'):
        strictcli.App(
            name="testapp",
            version="1.0.0",
            help="test app",
            config=True,
            config_format="yaml",
        )


def test_default_json_unchanged(tmp_path, monkeypatch):
    """Default behavior (JSON, XDG path) is unchanged."""
    config_home = _write_config(tmp_path, "testapp", {"target": "json-default"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "target=json-default" in r.stdout


def test_toml_config_show(tmp_path):
    """config show works with TOML format."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('target = "toml-show-val"\n')

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="default-val")
    @strictcli.flag("count", type=int, help="how many", default=1)
    def run(target, count):
        pass

    r = app.test(["config", "show"])
    assert r.exit_code == 0
    assert "target = toml-show-val  (source: config)" in r.stdout
    assert "count = 1  (source: default)" in r.stdout


def test_toml_float_value(tmp_path):
    """TOML config with float values works correctly."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('ratio = 0.75\n')

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
        config_format="toml",
    )

    @app.command("run", help="run something")
    @strictcli.flag("ratio", type=float, help="ratio value", default=1.0)
    def run(ratio):
        print(f"ratio={ratio}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "ratio=0.75" in r.stdout
