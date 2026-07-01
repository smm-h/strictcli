"""Tests for JSON config file support."""

import json
import os
import tomllib

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
    @strictcli.flag("verbose", type=bool, default=False, help="be verbose")
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
    r = app.test(["config", "show", "--plain"])
    assert r.exit_code == 0
    assert "target = from-config  (source: config)" in r.stdout
    assert "count = 1  (source: default)" in r.stdout
    assert "verbose = false  (source: default)" in r.stdout


# --- Test 10b: config show formats bools as lowercase (Go parity) ---

def test_config_show_lowercase_bools(tmp_path, monkeypatch):
    """Config show formats bools as lowercase true/false, matching Go output."""
    config_home = _write_config(tmp_path, "testapp", {"verbose": True})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "show", "--plain"])
    assert r.exit_code == 0
    # Bool from config must be lowercase
    assert "verbose = true  (source: config)" in r.stdout
    # None (no default for bool) must show as <nil>
    assert "verbose = True" not in r.stdout
    assert "verbose = False" not in r.stdout


def test_config_show_bool_false_default_lowercase(tmp_path, monkeypatch):
    """Config show formats default False bool as lowercase false."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_app(config=True)
    r = app.test(["config", "show", "--plain"])
    assert r.exit_code == 0
    # verbose has no explicit default, defaults to False -- must be lowercase
    assert "verbose = false  (source: default)" in r.stdout
    assert "verbose = False" not in r.stdout


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
    @strictcli.flag("verbose", type=bool, default=False, help="be verbose")
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

    r = app.test(["config", "show", "--plain"])
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


# --- config show --json output ---

def test_config_show_json(tmp_path, monkeypatch):
    """config show --json produces JSON output with sorted keys."""
    config_home = _write_config(tmp_path, "testapp", {"target": "from-config"})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "show", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["target"] == {"value": "from-config", "source": "config"}
    assert data["count"] == {"value": 1, "source": "default"}
    assert data["verbose"] == {"value": False, "source": "default"}
    # Keys must be sorted
    keys = list(data.keys())
    assert keys == sorted(keys)


def test_config_show_json_bool_values(tmp_path, monkeypatch):
    """config show --json preserves typed values (bools, ints)."""
    config_home = _write_config(tmp_path, "testapp", {"verbose": True, "count": 42})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_app(config=True)
    r = app.test(["config", "show", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["verbose"]["value"] is True
    assert data["verbose"]["source"] == "config"
    assert data["count"]["value"] == 42
    assert data["count"]["source"] == "config"


# --- config show no-flags error ---

def test_config_show_no_flags_error(tmp_path, monkeypatch):
    """config show without --plain or --json errors."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_app(config=True)
    r = app.test(["config", "show"])
    assert r.exit_code == 1
    assert "one of --plain, --json is required" in r.stderr


# --- config show both-flags error ---

def test_config_show_both_flags_error(tmp_path, monkeypatch):
    """config show with both --plain and --json errors (mutex)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_app(config=True)
    r = app.test(["config", "show", "--plain", "--json"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr


# --- config array coercion for repeatable flags ---


def _make_repeatable_config_app(tmp_path, monkeypatch, config_data,
                                flag_type=str, flag_name="tags"):
    """Helper: app with config and a repeatable flag."""
    config_home = _write_config(tmp_path, "repapp", config_data)
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = strictcli.App(
        name="repapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag(flag_name, type=flag_type, help="the flag",
                     repeatable=True, unique=False)
    def run(**kwargs):
        val = kwargs[flag_name.replace("-", "_")]
        print(f"val={val}")

    return app


def test_config_array_for_repeatable_string(tmp_path, monkeypatch):
    """Config array for repeatable str flag is coerced correctly."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"tags": ["a", "b", "c"]})
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "val=['a', 'b', 'c']" in r.stdout


def test_config_array_for_repeatable_int(tmp_path, monkeypatch):
    """Config array for repeatable int flag is coerced correctly."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"nums": [1, 2, 3]},
                                       flag_type=int, flag_name="nums")
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "val=[1, 2, 3]" in r.stdout


def test_config_array_for_repeatable_float(tmp_path, monkeypatch):
    """Config array for repeatable float flag is coerced correctly."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"rates": [1.5, 2.5]},
                                       flag_type=float, flag_name="rates")
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "val=[1.5, 2.5]" in r.stdout


def test_config_array_for_non_repeatable_error(tmp_path, monkeypatch):
    """Array value for non-repeatable flag errors."""
    config_home = _write_config(tmp_path, "scalarapp", {"target": ["a", "b"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = strictcli.App(
        name="scalarapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("target", type=str, help="the target", default="x")
    def run(target):
        print(f"target={target}")

    r = app.test(["run"])
    assert r.exit_code == 1
    assert "expected scalar, got array" in r.stderr


def test_config_scalar_for_repeatable_error(tmp_path, monkeypatch):
    """Scalar value for repeatable flag errors."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"tags": "single"})
    r = app.test(["run"])
    assert r.exit_code == 1
    assert "expected array for repeatable flag" in r.stderr


def test_config_array_bad_element_type(tmp_path, monkeypatch):
    """Array with wrong element type errors with element index."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"tags": ["a", 123]})
    r = app.test(["run"])
    assert r.exit_code == 1
    assert "element 1: expected str, got int" in r.stderr


def test_config_empty_array(tmp_path, monkeypatch):
    """Empty array for repeatable flag gives empty list."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"tags": []})
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "val=[]" in r.stdout


def test_config_single_element_array(tmp_path, monkeypatch):
    """Single-element array for repeatable flag works."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"tags": ["a"]})
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "val=['a']" in r.stdout


def test_config_array_precedence_cli_wins(tmp_path, monkeypatch):
    """CLI values override config array entirely."""
    app = _make_repeatable_config_app(tmp_path, monkeypatch,
                                       {"tags": ["a", "b", "c"]})
    r = app.test(["run", "--tags", "x", "--tags", "y"])
    assert r.exit_code == 0
    assert "val=['x', 'y']" in r.stdout


# --- config array unique enforcement ---


def _make_unique_config_app(tmp_path, monkeypatch, config_data,
                            flag_type=str, flag_name="tags",
                            unique=True):
    """Helper: app with config and a unique repeatable flag."""
    config_home = _write_config(tmp_path, "uniqcfgapp", config_data)
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = strictcli.App(
        name="uniqcfgapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag(flag_name, type=flag_type, help="the flag",
                     repeatable=True, unique=unique)
    def run(**kwargs):
        val = kwargs[flag_name.replace("-", "_")]
        print(f"val={val}")

    return app


def test_config_unique_enforcement(tmp_path, monkeypatch):
    """Config array with duplicates for unique flag errors."""
    app = _make_unique_config_app(tmp_path, monkeypatch,
                                  {"tags": ["a", "b", "a"]}, unique=True)
    r = app.test(["run"])
    assert r.exit_code == 1
    assert "duplicate value 'a'" in r.stderr
    assert "config value error" in r.stderr


def test_config_unique_no_duplicates(tmp_path, monkeypatch):
    """Config array without duplicates for unique flag succeeds."""
    app = _make_unique_config_app(tmp_path, monkeypatch,
                                  {"tags": ["a", "b", "c"]}, unique=True)
    r = app.test(["run"])
    assert r.exit_code == 0
    assert "val=['a', 'b', 'c']" in r.stdout


def test_config_show_plain_array(tmp_path, monkeypatch):
    """Config show --plain displays arrays as JSON array syntax."""
    config_home = _write_config(tmp_path, "showcfgapp", {"tags": ["a", "b", "c"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = strictcli.App(
        name="showcfgapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("tags", type=str, help="the tags",
                     repeatable=True, unique=False)
    def run(**kwargs):
        pass

    r = app.test(["config", "show", "--plain"])
    assert r.exit_code == 0
    assert 'tags = ["a", "b", "c"]  (source: config)' in r.stdout


def test_config_show_json_array(tmp_path, monkeypatch):
    """Config show --json includes array values correctly."""
    config_home = _write_config(tmp_path, "jsonshowapp",
                                {"tags": ["x", "y"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = strictcli.App(
        name="jsonshowapp",
        version="1.0.0",
        help="test app",
        config=True,
    )

    @app.command("run", help="run something")
    @strictcli.flag("tags", type=str, help="the tags",
                     repeatable=True, unique=False)
    def run(**kwargs):
        pass

    r = app.test(["config", "show", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["tags"]["value"] == ["x", "y"]
    assert data["tags"]["source"] == "config"


def test_config_unique_enforcement_global_flag(tmp_path, monkeypatch):
    """Global flag unique enforcement from config works."""
    config_home = _write_config(tmp_path, "globuniqapp",
                                {"tags": ["a", "b", "a"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = strictcli.App(
        name="globuniqapp",
        version="1.0.0",
        help="test app",
        config=True,
        flags=[
            strictcli.Flag(
                name="tags", type=str, help="the tags",
                repeatable=True, unique=True,
            ),
        ],
    )

    @app.command("run", help="run something")
    def run(**kwargs):
        print(f"tags={kwargs['tags']}")

    r = app.test(["run"])
    assert r.exit_code == 1
    assert "duplicate value 'a'" in r.stderr
    assert "config value error" in r.stderr


# --- TOML array write round-trip tests ---


def test_toml_write_string_array(tmp_path):
    """_write_toml_flat writes string arrays and they round-trip."""
    path = str(tmp_path / "config.toml")
    strictcli._write_toml_flat({"tags": ["a", "b"]}, path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert data["tags"] == ["a", "b"]


def test_toml_write_int_array(tmp_path):
    """_write_toml_flat writes int arrays and they round-trip."""
    path = str(tmp_path / "config.toml")
    strictcli._write_toml_flat({"nums": [1, 2, 3]}, path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert data["nums"] == [1, 2, 3]


def test_toml_write_float_array(tmp_path):
    """_write_toml_flat writes float arrays and they round-trip."""
    path = str(tmp_path / "config.toml")
    strictcli._write_toml_flat({"rates": [1.5, 2.5]}, path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert data["rates"] == [1.5, 2.5]


def test_toml_write_empty_array(tmp_path):
    """_write_toml_flat writes empty arrays and they round-trip."""
    path = str(tmp_path / "config.toml")
    strictcli._write_toml_flat({"items": []}, path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert data["items"] == []


def test_toml_write_mixed_scalars_and_arrays(tmp_path):
    """_write_toml_flat writes mixed scalar and array values correctly."""
    path = str(tmp_path / "config.toml")
    strictcli._write_toml_flat({
        "name": "test",
        "count": 42,
        "rate": 3.14,
        "debug": True,
        "tags": ["a", "b", "c"],
        "nums": [1, 2],
    }, path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert data["name"] == "test"
    assert data["count"] == 42
    assert data["rate"] == 3.14
    assert data["debug"] is True
    assert data["tags"] == ["a", "b", "c"]
    assert data["nums"] == [1, 2]


def test_toml_write_array_with_special_chars(tmp_path):
    """_write_toml_flat writes string arrays with special chars correctly."""
    path = str(tmp_path / "config.toml")
    strictcli._write_toml_flat({
        "paths": ['C:\\Users\\me', 'say "hello"', "back\\slash"],
    }, path)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert data["paths"] == ['C:\\Users\\me', 'say "hello"', "back\\slash"]


# --- Config set: repeatable flag support ---


def _make_config_set_app(config_path=None, config_format="json"):
    """Helper: app with config support and repeatable flags for config set tests."""
    kwargs = {"config": True}
    if config_path is not None:
        kwargs["config_path"] = config_path
    if config_format != "json":
        kwargs["config_format"] = config_format
    app = strictcli.App(
        name="repapp",
        version="1.0.0",
        help="test app with repeatable flags",
        **kwargs,
    )

    @app.command("run", help="run something")
    @strictcli.flag("tags", type=str, help="tags", repeatable=True, unique=False)
    @strictcli.flag("counts", type=int, help="counts", repeatable=True,
                    unique=False)
    @strictcli.flag("rates", type=float, help="rates", repeatable=True,
                    unique=False)
    @strictcli.flag("ids", type=int, help="unique ids", repeatable=True,
                    unique=True)
    @strictcli.flag("name", type=str, help="name", default="default")
    def run(tags, counts, rates, ids, name):
        print(f"tags={tags} counts={counts} rates={rates} ids={ids} name={name}")

    return app


def test_config_set_repeatable_string(tmp_path, monkeypatch):
    """Config set writes a string array for a repeatable flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "tags", "a,b,c"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["tags"] == ["a", "b", "c"]


def test_config_set_repeatable_int(tmp_path, monkeypatch):
    """Config set writes an int array for a repeatable flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "counts", "1,2,3"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["counts"] == [1, 2, 3]


def test_config_set_repeatable_float(tmp_path, monkeypatch):
    """Config set writes a float array for a repeatable flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "rates", "1.5,2.5,3.0"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["rates"] == [1.5, 2.5, 3.0]


def test_config_set_escaped_comma(tmp_path, monkeypatch):
    r"""Config set handles escaped commas: a\,b,c -> ["a,b", "c"]."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "tags", "a\\,b,c"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["tags"] == ["a,b", "c"]


def test_config_set_repeatable_unique_valid(tmp_path, monkeypatch):
    """Config set accepts distinct values for a unique repeatable flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "ids", "1,2,3"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["ids"] == [1, 2, 3]


def test_config_set_repeatable_unique_duplicate(tmp_path, monkeypatch):
    """Config set rejects duplicate values for a unique repeatable flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "ids", "1,2,1"])
    assert r.exit_code == 1
    assert "config set: key 'ids': duplicate value '1'" in r.stderr


def test_config_set_round_trip_json(tmp_path, monkeypatch):
    """Config set then show --json round-trips an array correctly."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "tags", "x,y"])
    assert r.exit_code == 0

    r = app.test(["config", "show", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["tags"]["value"] == ["x", "y"]
    assert data["tags"]["source"] == "config"


def test_config_set_round_trip_toml(tmp_path):
    """Config set then show --plain round-trips an array with TOML format."""
    config_file = tmp_path / "config.toml"
    app = _make_config_set_app(
        config_path=str(config_file), config_format="toml",
    )
    r = app.test(["config", "set", "tags", "a,b"])
    assert r.exit_code == 0
    assert config_file.exists()

    r = app.test(["config", "show", "--plain"])
    assert r.exit_code == 0
    assert 'tags = ["a", "b"]  (source: config)' in r.stdout


# --- Config set: --clear and --default ---


def test_config_set_clear_repeatable(tmp_path, monkeypatch):
    """--clear writes [] for a repeatable flag."""
    config_home = _write_config(tmp_path, "repapp", {"tags": ["a", "b"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_set_app()
    r = app.test(["config", "set", "tags", "--clear"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert data["tags"] == []


def test_config_set_clear_scalar_error(tmp_path, monkeypatch):
    """--clear errors on a scalar (non-repeatable) flag."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "name", "--clear"])
    assert r.exit_code == 1
    assert "config set: --clear is only for repeatable flags" in r.stderr


def test_config_set_default_removes_key(tmp_path, monkeypatch):
    """--default removes the key from config."""
    config_home = _write_config(tmp_path, "repapp", {"name": "alice", "tags": ["x"]})
    monkeypatch.setenv("XDG_CONFIG_HOME", config_home)
    app = _make_config_set_app()
    r = app.test(["config", "set", "name", "--default"])
    assert r.exit_code == 0

    config_file = tmp_path / "repapp" / "config.json"
    data = json.loads(config_file.read_text())
    assert "name" not in data
    # Other keys preserved
    assert data["tags"] == ["x"]


def test_config_set_default_nonexistent_key_error(tmp_path, monkeypatch):
    """--default errors when the key is not in config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "name", "--default"])
    assert r.exit_code == 1
    assert "config set: key 'name' not in config" in r.stderr


def test_config_set_no_args_error(tmp_path, monkeypatch):
    """No value, no --clear, no --default gives an error."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "name"])
    assert r.exit_code == 1
    assert "config set: provide a value, --clear, or --default" in r.stderr


def test_config_set_value_with_clear_error(tmp_path, monkeypatch):
    """Providing value + --clear is an error."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "tags", "a,b", "--clear"])
    assert r.exit_code == 1
    assert "config set: cannot provide a value with --clear" in r.stderr


def test_config_set_value_with_default_error(tmp_path, monkeypatch):
    """Providing value + --default is an error."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "name", "alice", "--default"])
    assert r.exit_code == 1
    assert "config set: cannot provide a value with --default" in r.stderr


def test_config_set_clear_and_default_error(tmp_path, monkeypatch):
    """--clear and --default together is an error."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = _make_config_set_app()
    r = app.test(["config", "set", "tags", "--clear", "--default"])
    assert r.exit_code == 1
    assert "config set: --clear and --default are mutually exclusive" in r.stderr
