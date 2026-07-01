"""Tests for MutexGroup (mutually exclusive flags)."""

import pytest

import strictcli


# ---------------------------------------------------------------------------
# Basic bool mutex: neither provided, one provided, both provided
# ---------------------------------------------------------------------------


def test_bool_mutex_neither_provided_error():
    """Two bool flags in mutex group, neither provided -> error (always required)."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(verbose, quiet):
        print(f"verbose={verbose} quiet={quiet}")

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "one of" in r.stderr
    assert "is required" in r.stderr


def test_bool_mutex_one_provided():
    """Two bool flags in mutex group, one provided -> OK."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(verbose, quiet):
        print(f"verbose={verbose} quiet={quiet}")

    r = app.test(["cmd", "--verbose"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout
    assert "quiet=False" in r.stdout


def test_bool_mutex_both_provided_error():
    """Two bool flags in mutex group, both provided -> error naming both."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(verbose, quiet):
        pass

    r = app.test(["cmd", "--verbose", "--quiet"])
    assert r.exit_code == 1
    assert "--verbose" in r.stderr
    assert "--quiet" in r.stderr
    assert "mutually exclusive" in r.stderr


# ---------------------------------------------------------------------------
# Required mutex group
# ---------------------------------------------------------------------------


def test_required_mutex_none_provided_error():
    """Mutex group, none provided -> error (always required)."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(verbose, quiet):
        pass

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--verbose" in r.stderr
    assert "--quiet" in r.stderr
    assert "required" in r.stderr


def test_required_mutex_one_provided_ok():
    """Mutex group, one provided -> OK."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(verbose, quiet):
        print(f"verbose={verbose} quiet={quiet}")

    r = app.test(["cmd", "--quiet"])
    assert r.exit_code == 0
    assert "verbose=False" in r.stdout
    assert "quiet=True" in r.stdout


# ---------------------------------------------------------------------------
# Str flags in mutex group
# ---------------------------------------------------------------------------


def test_str_mutex_one_provided_ok():
    """Mutex with str flags, one provided -> OK."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="file", type=str, help="read from file", default=None),
            strictcli.Flag(name="url", type=str, help="read from URL", default=None),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("fetch", help="fetch data", mutex=[mg])
    def fetch(file, url):
        print(f"file={file} url={url}")

    r = app.test(["fetch", "--file", "data.txt"])
    assert r.exit_code == 0
    assert "file=data.txt" in r.stdout


def test_str_mutex_both_provided_error():
    """Mutex with str flags, both provided -> error."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="file", type=str, help="read from file", default=None),
            strictcli.Flag(name="url", type=str, help="read from URL", default=None),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("fetch", help="fetch data", mutex=[mg])
    def fetch(file, url):
        pass

    r = app.test(["fetch", "--file", "data.txt", "--url", "http://example.com"])
    assert r.exit_code == 1
    assert "--file" in r.stderr
    assert "--url" in r.stderr
    assert "mutually exclusive" in r.stderr


# ---------------------------------------------------------------------------
# Mixed types in mutex group
# ---------------------------------------------------------------------------


def test_mixed_type_mutex():
    """Mutex with mixed types (bool + str)."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="interactive", type=bool, default=False, help="interactive mode"),
            strictcli.Flag(name="script", type=str, help="script file", default=None),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("run", help="run something", mutex=[mg])
    def run(interactive, script):
        print(f"interactive={interactive} script={script}")

    # One provided -> OK
    r = app.test(["run", "--interactive"])
    assert r.exit_code == 0
    assert "interactive=True" in r.stdout

    # Both provided -> error
    r = app.test(["run", "--interactive", "--script", "test.sh"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------


def test_mutex_shown_in_help():
    """Mutex group flags shown in help output under a distinct section."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    @strictcli.flag("name", help="your name", default="anon")
    def cmd(name, verbose, quiet):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "Flags (mutually exclusive):" in r.stdout
    assert "--verbose" in r.stdout
    assert "--quiet" in r.stdout
    # Regular flag should be under "Flags:"
    assert "Flags:" in r.stdout
    assert "--name" in r.stdout


def test_required_mutex_shown_in_help():
    """Mutex group shows 'mutually exclusive' in the help section header."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(verbose, quiet):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "Flags (mutually exclusive):" in r.stdout


# ---------------------------------------------------------------------------
# Env var interaction
# ---------------------------------------------------------------------------


def test_mutex_env_sets_one_cli_sets_another_error(monkeypatch):
    """Env sets one flag, CLI sets another in the same mutex group -> error."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(
                name="file", type=str, help="read from file", default=None,
                env="TEST_FILE", prefixed=False,
            ),
            strictcli.Flag(
                name="url", type=str, help="read from URL", default=None,
                env="TEST_URL", prefixed=False,
            ),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("fetch", help="fetch data", mutex=[mg])
    def fetch(file, url):
        pass

    monkeypatch.setenv("TEST_FILE", "data.txt")
    r = app.test(["fetch", "--url", "http://example.com"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr


def test_mutex_env_sets_one_only_ok(monkeypatch):
    """Env sets one flag in mutex group, nothing else -> OK."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(
                name="file", type=str, help="read from file", default=None,
                env="TEST_FILE2", prefixed=False,
            ),
            strictcli.Flag(
                name="url", type=str, help="read from URL", default=None,
                env="TEST_URL2", prefixed=False,
            ),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("fetch", help="fetch data", mutex=[mg])
    def fetch(file, url):
        print(f"file={file} url={url}")

    monkeypatch.setenv("TEST_FILE2", "data.txt")
    r = app.test(["fetch"])
    assert r.exit_code == 0
    assert "file=data.txt" in r.stdout


# ---------------------------------------------------------------------------
# Registration errors
# ---------------------------------------------------------------------------


def test_mutex_flags_overlap_with_regular_flags_error():
    """Mutex flags that overlap with regular flags -> registration error."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="duplicate flag name"):

        @app.command("cmd", help="a command", mutex=[mg])
        @strictcli.flag("verbose", type=bool, default=False, help="verbose output")
        def cmd(verbose, quiet):
            pass


def test_mutex_group_fewer_than_2_flags_error():
    """Mutex group with fewer than 2 flags -> registration error."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="at least 2 flags"):

        @app.command("cmd", help="a command", mutex=[mg])
        def cmd(verbose):
            pass


def test_mutex_group_empty_error():
    """Mutex group with zero flags -> registration error."""
    mg = strictcli.MutexGroup(flags=[])
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="at least 2 flags"):

        @app.command("cmd", help="a command", mutex=[mg])
        def cmd():
            pass


# ---------------------------------------------------------------------------
# Two separate mutex groups on the same command
# ---------------------------------------------------------------------------


def test_two_separate_mutex_groups():
    """Two independent mutex groups on the same command, both valid."""
    mg1 = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    mg2 = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=bool, default=False, help="JSON output"),
            strictcli.Flag(name="csv", type=bool, default=False, help="CSV output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg1, mg2])
    def cmd(verbose, quiet, json, csv):
        print(f"verbose={verbose} quiet={quiet} json={json} csv={csv}")

    # One from each group -> OK
    r = app.test(["cmd", "--verbose", "--json"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout
    assert "json=True" in r.stdout

    # Two from same group -> error
    r = app.test(["cmd", "--verbose", "--quiet"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr


# ---------------------------------------------------------------------------
# Overlapping mutex groups
# ---------------------------------------------------------------------------


def test_overlapping_mutex_groups_error():
    """A flag appearing in multiple mutex groups -> registration error."""
    shared_flag = strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output")
    mg1 = strictcli.MutexGroup(
        flags=[
            shared_flag,
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    mg2 = strictcli.MutexGroup(
        flags=[
            shared_flag,
            strictcli.Flag(name="debug", type=bool, default=False, help="debug output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="multiple mutex groups"):

        @app.command("cmd", help="a command", mutex=[mg1, mg2])
        def cmd(verbose, quiet, debug):
            pass


# ---------------------------------------------------------------------------
# Group.command() with mutex
# ---------------------------------------------------------------------------


def test_group_command_with_mutex():
    """Mutex works when registered via Group.command()."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="verbose", type=bool, default=False, help="verbose output"),
            strictcli.Flag(name="quiet", type=bool, default=False, help="quiet output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="configuration commands")

    @grp.command("show", help="show config", mutex=[mg])
    def show(verbose, quiet):
        print(f"verbose={verbose} quiet={quiet}")

    r = app.test(["config", "show", "--verbose"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout

    r = app.test(["config", "show", "--verbose", "--quiet"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr
