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
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        print(f"loud={loud} hushed={hushed}")

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "one of" in r.stderr
    assert "is required" in r.stderr


def test_bool_mutex_one_provided():
    """Two bool flags in mutex group, one provided -> OK."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        print(f"loud={loud} hushed={hushed}")

    r = app.test(["cmd", "--loud"])
    assert r.exit_code == 0
    assert "loud=True" in r.stdout
    assert "hushed=False" in r.stdout


def test_bool_mutex_both_provided_error():
    """Two bool flags in mutex group, both provided -> error naming both."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        pass

    r = app.test(["cmd", "--loud", "--hushed"])
    assert r.exit_code == 1
    assert "--loud" in r.stderr
    assert "--hushed" in r.stderr
    assert "mutually exclusive" in r.stderr


# ---------------------------------------------------------------------------
# Required mutex group
# ---------------------------------------------------------------------------


def test_required_mutex_none_provided_error():
    """Mutex group, none provided -> error (always required)."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        pass

    r = app.test(["cmd"])
    assert r.exit_code == 1
    assert "--loud" in r.stderr
    assert "--hushed" in r.stderr
    assert "required" in r.stderr


def test_required_mutex_one_provided_ok():
    """Mutex group, one provided -> OK."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        print(f"loud={loud} hushed={hushed}")

    r = app.test(["cmd", "--hushed"])
    assert r.exit_code == 0
    assert "loud=False" in r.stdout
    assert "hushed=True" in r.stdout


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

    @app.command("fetch", effect="read_only", help="fetch data", mutex=[mg])
    def fetch(ctx, file, url):
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

    @app.command("fetch", effect="read_only", help="fetch data", mutex=[mg])
    def fetch(ctx, file, url):
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

    @app.command("run", effect="read_only", help="run something", mutex=[mg])
    def run(ctx, interactive, script):
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
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    @strictcli.flag("name", help="your name", default="anon")
    def cmd(ctx, name, loud, hushed):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "Flags (mutually exclusive):" in r.stdout
    assert "--loud" in r.stdout
    assert "--hushed" in r.stdout
    # Regular flag should be under "Flags:"
    assert "Flags:" in r.stdout
    assert "--name" in r.stdout


def test_required_mutex_shown_in_help():
    """Mutex group shows 'mutually exclusive' in the help section header."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        pass

    r = app.test(["cmd", "--help"])
    assert r.exit_code == 0
    assert "Flags (mutually exclusive):" in r.stdout


# ---------------------------------------------------------------------------
# Env var interaction
# ---------------------------------------------------------------------------


def test_mutex_env_sets_one_cli_sets_another_ok(monkeypatch):
    """Env sets one member, CLI elects another: the env member is suppressed.

    Contract §21.3 -- env neither elects nor supplies a mutex member's value,
    so the CLI election stands alone and the env-named member delivers its
    declared default (None here) rather than the environment's value.
    """
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

    @app.command("fetch", effect="read_only", help="fetch data", mutex=[mg])
    def fetch(ctx, file, url):
        print(f"file={file} url={url} file_source={ctx.source('file')}")

    monkeypatch.setenv("TEST_FILE", "data.txt")
    r = app.test(["fetch", "--url", "http://example.com"])
    assert r.exit_code == 0
    assert "file=None url=http://example.com" in r.stdout
    assert "file_source=default" in r.stdout


def test_mutex_env_sets_one_only_is_error(monkeypatch):
    """Env sets one member and nothing is typed: the group is unsatisfied.

    Contract §21.3 -- election is CLI-only, so an env value satisfies nothing.
    """
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

    @app.command("fetch", effect="read_only", help="fetch data", mutex=[mg])
    def fetch(ctx, file, url):
        print(f"file={file} url={url}")

    monkeypatch.setenv("TEST_FILE2", "data.txt")
    r = app.test(["fetch"])
    assert r.exit_code == 1
    assert "error: one of --file, --url is required\n" in r.stderr


def test_mutex_config_value_does_not_elect(tmp_path, monkeypatch):
    """A config-file value on a mutex member elects nothing (§21.3)."""
    cfg = tmp_path / "config.json"
    cfg.write_text('{"file": "from-config.txt"}\n')
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="file", type=str, help="read from file", default=None),
            strictcli.Flag(name="url", type=str, help="read from URL", default=None),
        ],
    )
    app = strictcli.App(
        name="test", version="1.0.0", help="test app", config=True,
    )

    @app.command("fetch", effect="read_only", help="fetch data", mutex=[mg])
    def fetch(ctx, file, url):
        print(f"file={file} url={url}")

    r = app.test(["--config", str(cfg), "fetch"])
    assert r.exit_code == 1
    assert "error: one of --file, --url is required\n" in r.stderr

    # And beside a real election the config value is suppressed, not delivered.
    r = app.test(["--config", str(cfg), "fetch", "--url", "u"])
    assert r.exit_code == 0
    assert "file=None url=u" in r.stdout


# ---------------------------------------------------------------------------
# Election semantics (contract §21; campaign rulings A1-A5)
# ---------------------------------------------------------------------------


def _election_app():
    """App with one mixed mutex group: str + negatable bool + negatable bool."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="profile", type=str, help="a profile", default=None),
            strictcli.Flag(
                name="all-profiles", type=bool, negatable=True,
                help="every profile", default=None,
            ),
            strictcli.Flag(
                name="current-profile", type=bool, negatable=True,
                help="the current profile", default=None,
            ),
        ],
    )
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it", mutex=[mg])
    def run(ctx, profile, all_profiles, current_profile):
        print(f"profile={profile} all={all_profiles} current={current_profile}")

    return app


def test_a1_negated_bool_member_elects_nothing():
    """A1: --no-<x> on a bool member elects nothing; the group is unsatisfied."""
    app = _election_app()
    r = app.test(["run", "--no-all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_a1_negated_bool_beside_a_real_election_of_another_bool():
    """A1: a true bool elects; the declined one is not a second election."""
    app = _election_app()
    r = app.test(["run", "--all-profiles"])
    assert r.exit_code == 0
    assert "profile=None all=True current=None" in r.stdout


def test_a1_all_members_declined_is_unsatisfied():
    """A1/A3: every bool member declined -> required error, clause names the first."""
    app = _election_app()
    r = app.test(["run", "--no-current-profile", "--no-all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_a2_string_member_elects_on_empty_string():
    """A2: a string member elects on presence with any value, including ''."""
    app = _election_app()
    r = app.test(["run", "--profile", ""])
    assert r.exit_code == 0
    assert "profile= all=None current=None" in r.stdout


def test_a3_clause_absent_when_nothing_was_declined():
    """A3: the teaching clause appears only when a member was declined."""
    app = _election_app()
    r = app.test(["run"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required\n"
    ) in r.stderr


def test_a4_redundant_negation_beside_an_election_is_an_error():
    """A4: a declined member beside a real election is a parse error."""
    app = _election_app()
    r = app.test(["run", "--profile", "work", "--no-all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: --no-all-profiles cannot be combined with --profile "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_a4_multiple_declined_members_are_all_named():
    """A4: every declined member is listed, in group-declaration order."""
    app = _election_app()
    r = app.test(
        ["run", "--profile", "work", "--no-current-profile", "--no-all-profiles"],
    )
    assert r.exit_code == 1
    assert (
        "error: --no-all-profiles and --no-current-profile cannot be combined "
        "with --profile "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_two_elections_are_still_mutually_exclusive():
    """Two real elections keep the unchanged mutually-exclusive message."""
    app = _election_app()
    r = app.test(["run", "--profile", "work", "--all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: --profile and --all-profiles are mutually exclusive\n"
    ) in r.stderr


def test_a1_call_with_false_bool_declines():
    """A1 holds on the programmatic path: an explicit False declines."""
    app = _election_app()
    with pytest.raises(strictcli.InvokeError) as exc:
        app.call("run", all_profiles=False)
    assert "one of --profile, --all-profiles, --current-profile is required" in str(
        exc.value
    )
    assert "declines an option" in str(exc.value)


def test_bool_member_with_declared_default_still_defaults():
    """A declared default still applies to an unelected member (§18.10 item 118)."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
    def cmd(ctx, loud, hushed):
        print(f"loud={loud} hushed={hushed}")

    r = app.test(["cmd", "--loud"])
    assert r.exit_code == 0
    assert "loud=True hushed=False" in r.stdout


# ---------------------------------------------------------------------------
# Registration errors
# ---------------------------------------------------------------------------


def test_mutex_flags_overlap_with_regular_flags_error():
    """Mutex flags that overlap with regular flags -> registration error."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="duplicate flag name"):

        @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
        @strictcli.flag("loud", type=bool, default=False, help="loud output")
        def cmd(ctx, loud, hushed):
            pass


def test_mutex_group_fewer_than_2_flags_error():
    """Mutex group with fewer than 2 flags -> registration error."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="at least 2 flags"):

        @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
        def cmd(ctx, loud):
            pass


def test_mutex_group_empty_error():
    """Mutex group with zero flags -> registration error."""
    mg = strictcli.MutexGroup(flags=[])
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    with pytest.raises(ValueError, match="at least 2 flags"):

        @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
        def cmd(ctx):
            pass


# ---------------------------------------------------------------------------
# Two separate mutex groups on the same command
# ---------------------------------------------------------------------------


def test_two_separate_mutex_groups():
    """Two independent mutex groups on the same command, both valid."""
    mg1 = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    mg2 = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="as-json", type=bool, default=False, help="JSON output"),
            strictcli.Flag(name="csv", type=bool, default=False, help="CSV output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command", mutex=[mg1, mg2])
    def cmd(ctx, loud, hushed, as_json, csv):
        print(f"loud={loud} hushed={hushed} json={as_json} csv={csv}")

    # One from each group -> OK
    r = app.test(["cmd", "--loud", "--as-json"])
    assert r.exit_code == 0
    assert "loud=True" in r.stdout
    assert "json=True" in r.stdout

    # Two from same group -> error
    r = app.test(["cmd", "--loud", "--hushed"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr


# ---------------------------------------------------------------------------
# Overlapping mutex groups
# ---------------------------------------------------------------------------


def test_overlapping_mutex_groups_error():
    """A flag appearing in multiple mutex groups -> registration error."""
    shared_flag = strictcli.Flag(name="loud", type=bool, default=False, help="loud output")
    mg1 = strictcli.MutexGroup(
        flags=[
            shared_flag,
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
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

        @app.command("cmd", effect="read_only", help="a command", mutex=[mg1, mg2])
        def cmd(ctx, loud, hushed, debug):
            pass


# ---------------------------------------------------------------------------
# Group.command() with mutex
# ---------------------------------------------------------------------------


def test_group_command_with_mutex():
    """Mutex works when registered via Group.command()."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
            strictcli.Flag(name="hushed", type=bool, default=False, help="hushed output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")
    grp = app.group("config", help="configuration commands")

    @grp.command("show", effect="read_only", help="show config", mutex=[mg])
    def show(ctx, loud, hushed):
        print(f"loud={loud} hushed={hushed}")

    r = app.test(["config", "show", "--loud"])
    assert r.exit_code == 0
    assert "loud=True" in r.stdout

    r = app.test(["config", "show", "--loud", "--hushed"])
    assert r.exit_code == 1
    assert "mutually exclusive" in r.stderr
