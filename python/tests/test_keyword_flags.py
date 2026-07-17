"""Tests for Python keyword collision handling in flag parameter names."""

import json
import os

import strictcli
from strictcli import _flag_param_name


# --- Unit tests for _flag_param_name ---


def test_non_keyword_unchanged():
    """Non-keyword flag names convert normally (dashes to underscores)."""
    assert _flag_param_name("--dry-run") == "dry_run"


def test_keyword_global():
    """'global' is a Python keyword, should get trailing underscore."""
    assert _flag_param_name("--global") == "global_"


def test_keyword_class():
    """'class' is a Python keyword, should get trailing underscore."""
    assert _flag_param_name("--class") == "class_"


def test_keyword_import():
    """'import' is a Python keyword, should get trailing underscore."""
    assert _flag_param_name("--import") == "import_"


def test_keyword_for():
    """'for' is a Python keyword, should get trailing underscore."""
    assert _flag_param_name("--for") == "for_"


def test_keyword_in():
    """'in' is a Python keyword, should get trailing underscore."""
    assert _flag_param_name("--in") == "in_"


def test_non_keyword_globally():
    """'globally' is NOT a keyword, should NOT get trailing underscore."""
    assert _flag_param_name("--globally") == "globally"


# --- Integration test: command with --global flag ---


def test_command_with_global_flag():
    """A command with a --global bool flag works end-to-end."""
    app = strictcli.App(name="testapp", version="1.0.0", help="test app")
    received = {}

    @app.command("cmd", help="a command")
    @strictcli.flag("global", type=bool, default=False, help="apply globally")
    def cmd(ctx, **kwargs):
        received.update(kwargs)

    r = app.test(["cmd", "--global"])
    assert r.exit_code == 0
    assert received["global_"] is True


def test_command_with_global_flag_default():
    """When --global is not passed, its default (False) uses the global_ key."""
    app = strictcli.App(name="testapp", version="1.0.0", help="test app")
    received = {}

    @app.command("cmd", help="a command")
    @strictcli.flag("global", type=bool, default=False, help="apply globally")
    def cmd(ctx, **kwargs):
        received.update(kwargs)

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert received["global_"] is False


# --- Integration test: config with keyword flag ---


def test_config_key_uses_suffixed_name(tmp_path):
    """Config keys for keyword flags use the suffixed name (global_)."""
    # Write a config file with the suffixed key
    config_dir = tmp_path / "kwtest"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"global_": True}) + "\n")

    # Set XDG_CONFIG_HOME BEFORE creating the app, since config is loaded
    # during App.__init__
    old_xdg = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    try:
        app = strictcli.App(
            name="kwtest",
            version="1.0.0",
            help="test app",
            config=True,
        )
        received = {}

        @app.command("cmd", help="a command")
        @strictcli.flag("global", type=bool, default=False, help="apply globally")
        def cmd(ctx, **kwargs):
            received.update(kwargs)

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert received["global_"] is True
    finally:
        if old_xdg is None:
            del os.environ["XDG_CONFIG_HOME"]
        else:
            os.environ["XDG_CONFIG_HOME"] = old_xdg
