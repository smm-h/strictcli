"""Red tests for config set bugs.

These tests document bugs in the config set command and are expected to
FAIL with the current code. They will turn green when the bugs are fixed.

Bug 0.4: config set stores raw strings instead of typed values.
Bug 0.6: config set accepts unknown keys without validation.
"""

import json

import strictcli


def test_config_set_writes_typed_values(tmp_path):
    """config set should write typed values (int, bool, float), not strings.

    Bug: _config_set_handler stores the raw string from argv without
    coercing it to the flag's declared type. So 'config set count 42'
    writes {"count": "42"} instead of {"count": 42}.
    """
    config_file = tmp_path / "config.json"

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    @strictcli.flag("count", type=int, help="how many", default=0)
    @strictcli.flag("verbose", type=bool, help="be verbose", default=False)
    @strictcli.flag("rate", type=float, help="the rate", default=0.0)
    def run(count, verbose, rate):
        pass

    r = app.test(["config", "set", "count", "42"])
    assert r.exit_code == 0

    r = app.test(["config", "set", "verbose", "true"])
    assert r.exit_code == 0

    r = app.test(["config", "set", "rate", "3.14"])
    assert r.exit_code == 0

    data = json.loads(config_file.read_text())
    assert isinstance(data["count"], int), f"expected int, got {type(data['count']).__name__}: {data['count']!r}"
    assert data["count"] == 42
    assert isinstance(data["verbose"], bool), f"expected bool, got {type(data['verbose']).__name__}: {data['verbose']!r}"
    assert data["verbose"] is True
    assert isinstance(data["rate"], float), f"expected float, got {type(data['rate']).__name__}: {data['rate']!r}"
    assert data["rate"] == 3.14


def test_config_set_rejects_unknown_key(tmp_path):
    """config set should reject keys that don't correspond to any registered flag.

    Bug: _config_set_handler accepts any key without checking if it
    matches a registered flag. 'config set nonexistent value' silently
    writes {"nonexistent": "value"} to the config file.
    """
    config_file = tmp_path / "config.json"

    app = strictcli.App(
        name="testapp",
        version="1.0.0",
        help="test app",
        config=True,
        config_path=str(config_file),
    )

    @app.command("run", help="run something")
    @strictcli.flag("name", type=str, help="the name", default="")
    def run(name):
        pass

    r = app.test(["config", "set", "nonexistent", "value"])
    assert r.exit_code != 0, f"expected nonzero exit code, got {r.exit_code}"
    assert "nonexistent" in r.stderr, f"expected error about unknown key in stderr, got: {r.stderr!r}"
