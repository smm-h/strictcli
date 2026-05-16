"""Tests for CoRequired and Requires flag dependencies."""

import pytest

import strictcli


# ---------------------------------------------------------------------------
# CoRequired: both provided -> ok
# ---------------------------------------------------------------------------


def test_corequired_both_provided_ok():
    """CoRequired flags both provided -> OK."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.CoRequired(flags=["output", "format"])],
    )
    @strictcli.flag("output", type=str, help="output path", default=None)
    @strictcli.flag("format", type=str, help="output format", default=None)
    def cmd(output, format):
        print(f"output={output} format={format}")

    r = app.test(["cmd", "--output", "file.txt", "--format", "json"])
    assert r.exit_code == 0
    assert "output=file.txt" in r.stdout
    assert "format=json" in r.stdout


# ---------------------------------------------------------------------------
# CoRequired: neither provided -> ok
# ---------------------------------------------------------------------------


def test_corequired_neither_provided_ok():
    """CoRequired flags neither provided -> OK (all or none)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.CoRequired(flags=["output", "format"])],
    )
    @strictcli.flag("output", type=str, help="output path", default="")
    @strictcli.flag("format", type=str, help="output format", default="")
    def cmd(output, format):
        print(f"output={output} format={format}")

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "output=" in r.stdout
    assert "format=" in r.stdout


# ---------------------------------------------------------------------------
# CoRequired: one provided but not other -> error
# ---------------------------------------------------------------------------


def test_corequired_one_provided_error():
    """CoRequired flags: one provided without the other -> error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.CoRequired(flags=["output", "format"])],
    )
    @strictcli.flag("output", type=str, help="output path", default=None)
    @strictcli.flag("format", type=str, help="output format", default=None)
    def cmd(output, format):
        pass

    r = app.test(["cmd", "--output", "file.txt"])
    assert r.exit_code == 1
    assert "must be used together" in r.stderr
    assert "--output" in r.stderr
    assert "--format" in r.stderr


def test_corequired_second_provided_without_first_error():
    """CoRequired flags: second provided without the first -> error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.CoRequired(flags=["output", "format"])],
    )
    @strictcli.flag("output", type=str, help="output path", default=None)
    @strictcli.flag("format", type=str, help="output format", default=None)
    def cmd(output, format):
        pass

    r = app.test(["cmd", "--format", "json"])
    assert r.exit_code == 1
    assert "must be used together" in r.stderr


# ---------------------------------------------------------------------------
# CoRequired: works with env vars
# ---------------------------------------------------------------------------


def test_corequired_env_sets_one_cli_sets_another_ok(monkeypatch):
    """CoRequired: env sets one, CLI sets the other -> OK (both present)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.CoRequired(flags=["output", "format"])],
    )
    @strictcli.flag("output", type=str, help="output path", default=None,
                    env="TEST_DEP_OUTPUT", prefixed=False)
    @strictcli.flag("format", type=str, help="output format", default=None,
                    env="TEST_DEP_FORMAT", prefixed=False)
    def cmd(output, format):
        print(f"output={output} format={format}")

    monkeypatch.setenv("TEST_DEP_OUTPUT", "env_file.txt")
    r = app.test(["cmd", "--format", "json"])
    assert r.exit_code == 0
    assert "output=env_file.txt" in r.stdout
    assert "format=json" in r.stdout


def test_corequired_env_sets_one_not_other_error(monkeypatch):
    """CoRequired: env sets one flag but not the other -> error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.CoRequired(flags=["output", "format"])],
    )
    @strictcli.flag("output", type=str, help="output path", default=None,
                    env="TEST_DEP_OUTPUT2", prefixed=False)
    @strictcli.flag("format", type=str, help="output format", default=None,
                    env="TEST_DEP_FORMAT2", prefixed=False)
    def cmd(output, format):
        pass

    monkeypatch.setenv("TEST_DEP_OUTPUT2", "env_file.txt")
    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "must be used together" in r.stderr


# ---------------------------------------------------------------------------
# Requires: flag provided with depends_on -> ok
# ---------------------------------------------------------------------------


def test_requires_both_provided_ok():
    """Requires: flag and depends_on both provided -> OK."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.Requires(flag="format", depends_on="output")],
    )
    @strictcli.flag("output", type=str, help="output path", default=None)
    @strictcli.flag("format", type=str, help="output format", default=None)
    def cmd(output, format):
        print(f"output={output} format={format}")

    r = app.test(["cmd", "--output", "file.txt", "--format", "json"])
    assert r.exit_code == 0
    assert "output=file.txt" in r.stdout
    assert "format=json" in r.stdout


# ---------------------------------------------------------------------------
# Requires: flag not provided -> ok (no constraint triggered)
# ---------------------------------------------------------------------------


def test_requires_flag_not_provided_ok():
    """Requires: flag not provided -> OK (constraint not triggered)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.Requires(flag="format", depends_on="output")],
    )
    @strictcli.flag("output", type=str, help="output path", default="")
    @strictcli.flag("format", type=str, help="output format", default="")
    def cmd(output, format):
        print(f"output={output} format={format}")

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "output=" in r.stdout
    assert "format=" in r.stdout


# ---------------------------------------------------------------------------
# Requires: depends_on provided without flag -> ok (unidirectional)
# ---------------------------------------------------------------------------


def test_requires_depends_on_alone_ok():
    """Requires: depends_on provided without the flag -> OK (unidirectional)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.Requires(flag="format", depends_on="output")],
    )
    @strictcli.flag("output", type=str, help="output path", default="")
    @strictcli.flag("format", type=str, help="output format", default="")
    def cmd(output, format):
        print(f"output={output} format={format}")

    r = app.test(["cmd", "--output", "file.txt"])
    assert r.exit_code == 0
    assert "output=file.txt" in r.stdout
    assert "format=" in r.stdout


# ---------------------------------------------------------------------------
# Requires: flag provided without depends_on -> error
# ---------------------------------------------------------------------------


def test_requires_flag_without_depends_on_error():
    """Requires: flag provided without depends_on -> error."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd", help="a command",
        dependencies=[strictcli.Requires(flag="format", depends_on="output")],
    )
    @strictcli.flag("output", type=str, help="output path", default=None)
    @strictcli.flag("format", type=str, help="output format", default=None)
    def cmd(output, format):
        pass

    r = app.test(["cmd", "--format", "json"])
    assert r.exit_code == 1
    assert "requires" in r.stderr
    assert "--format" in r.stderr
    assert "--output" in r.stderr


# ---------------------------------------------------------------------------
# Registration error: CoRequired with <2 flags
# ---------------------------------------------------------------------------


def test_corequired_fewer_than_2_flags_error():
    """CoRequired with fewer than 2 flags -> ValueError at registration."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="at least 2 flags"):

        @app.command(
            "cmd", help="a command",
            dependencies=[strictcli.CoRequired(flags=["output"])],
        )
        @strictcli.flag("output", type=str, help="output path", default=None)
        def cmd(output):
            pass


# ---------------------------------------------------------------------------
# Registration error: CoRequired references non-existent flag
# ---------------------------------------------------------------------------


def test_corequired_unknown_flag_error():
    """CoRequired referencing a non-existent flag -> ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="unknown flag"):

        @app.command(
            "cmd", help="a command",
            dependencies=[strictcli.CoRequired(flags=["output", "nonexistent"])],
        )
        @strictcli.flag("output", type=str, help="output path", default=None)
        def cmd(output):
            pass


# ---------------------------------------------------------------------------
# Registration error: Requires references non-existent flag
# ---------------------------------------------------------------------------


def test_requires_unknown_flag_error():
    """Requires referencing a non-existent flag -> ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="unknown flag"):

        @app.command(
            "cmd", help="a command",
            dependencies=[strictcli.Requires(flag="format", depends_on="nonexistent")],
        )
        @strictcli.flag("format", type=str, help="output format", default=None)
        def cmd(format):
            pass


def test_requires_unknown_depends_on_error():
    """Requires with unknown depends_on flag -> ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="unknown flag"):

        @app.command(
            "cmd", help="a command",
            dependencies=[strictcli.Requires(flag="nonexistent", depends_on="format")],
        )
        @strictcli.flag("format", type=str, help="output format", default=None)
        def cmd(format):
            pass


# ---------------------------------------------------------------------------
# Registration error: Requires flag == depends_on
# ---------------------------------------------------------------------------


def test_requires_same_flag_error():
    """Requires where flag == depends_on -> ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="cannot be the same"):

        @app.command(
            "cmd", help="a command",
            dependencies=[strictcli.Requires(flag="output", depends_on="output")],
        )
        @strictcli.flag("output", type=str, help="output path", default=None)
        def cmd(output):
            pass


# ---------------------------------------------------------------------------
# Interaction with mutex: a flag can be in both a mutex group and a dependency
# ---------------------------------------------------------------------------


def test_dependency_with_mutex_interaction():
    """A flag can participate in both a mutex group and a dependency."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=bool, help="JSON output"),
            strictcli.Flag(name="csv", type=bool, help="CSV output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    # --output requires that one of the format flags is set (tested via
    # Requires on --json). The mutex ensures only one format flag is used.
    @app.command(
        "cmd", help="a command",
        mutex=[mg],
        dependencies=[strictcli.Requires(flag="output", depends_on="json")],
    )
    @strictcli.flag("output", type=str, help="output path", default="")
    def cmd(output, json, csv):
        print(f"output={output} json={json} csv={csv}")

    # --json alone -> ok
    r = app.test(["cmd", "--json"])
    assert r.exit_code == 0

    # --output with --json -> ok
    r = app.test(["cmd", "--output", "file.txt", "--json"])
    assert r.exit_code == 0
    assert "output=file.txt" in r.stdout
    assert "json=True" in r.stdout

    # --output without --json -> error (requires)
    r = app.test(["cmd", "--output", "file.txt", "--csv"])
    assert r.exit_code == 1
    assert "requires" in r.stderr
    assert "--output" in r.stderr
    assert "--json" in r.stderr


# ---------------------------------------------------------------------------
# CoRequired with duplicate flag names
# ---------------------------------------------------------------------------


def test_corequired_duplicate_flag_error():
    """CoRequired with duplicate flag names -> ValueError."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="duplicate flag"):

        @app.command(
            "cmd", help="a command",
            dependencies=[strictcli.CoRequired(flags=["output", "output"])],
        )
        @strictcli.flag("output", type=str, help="output path", default=None)
        def cmd(output):
            pass
