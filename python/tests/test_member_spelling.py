"""Member spelling: §21's election semantics, carried over by §24.4.

`MutexGroup` is subsumed and deleted (§21's amendment box, §24.14). What
survives it is member spelling: each choice is spelled as its own flag, no
selector token is ever typed, and the three §21.4 sentences are reused
BYTE-FOR-BYTE -- a migrated group changes no user-visible text. Every
assertion below that quotes a message is quoting the pre-round text.
"""

import pytest

import strictcli
from strictcli import choice, choice_flag, member_value, sub_flag


# ---------------------------------------------------------------------------
# The mixed group of §21.2: a payload-carrying member plus two payload-less
# ones (the old str + negatable bool + negatable bool group).
# ---------------------------------------------------------------------------


@choice("profile", help="a profile")
class Profile:
    value: str = member_value(help="the profile name")


@choice("all-profiles", help="every profile")
class AllProfiles:
    pass


@choice("current-profile", help="the current profile")
class CurrentProfile:
    pass


Mode = Profile | AllProfiles | CurrentProfile


def _election_app():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags",
        choices=[Profile, AllProfiles, CurrentProfile],
    )
    def run(ctx, mode: Mode):
        match mode:
            case Profile(value=v):
                print(f"profile={v}")
            case AllProfiles():
                print("all")
            case CurrentProfile():
                print("current")

    return app


def test_a1_declined_member_elects_nothing():
    """A1: `--no-<x>` on a payload-less member elects nothing (§21.2)."""
    r = _election_app().test(["run", "--no-all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_a1_payload_less_member_elects_on_presence():
    r = _election_app().test(["run", "--all-profiles"])
    assert r.exit_code == 0
    assert "all" in r.stdout


def test_a1_all_members_declined_is_unsatisfied():
    """A1/A3: the clause names the FIRST declined member, in declaration order."""
    r = _election_app().test(["run", "--no-current-profile", "--no-all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_a2_payload_member_elects_on_empty_string():
    """A2: every other type elects on presence with any value, including ''."""
    r = _election_app().test(["run", "--profile", ""])
    assert r.exit_code == 0
    assert "profile=\n" in r.stdout


def test_a3_clause_absent_when_nothing_was_declined():
    r = _election_app().test(["run"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required\n"
    ) in r.stderr


def test_a4_redundant_negation_beside_an_election_is_an_error():
    r = _election_app().test(["run", "--profile", "work", "--no-all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: --no-all-profiles cannot be combined with --profile "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_a4_multiple_declined_members_are_all_named():
    r = _election_app().test(
        ["run", "--profile", "work", "--no-current-profile", "--no-all-profiles"],
    )
    assert r.exit_code == 1
    assert (
        "error: --no-all-profiles and --no-current-profile cannot be combined "
        "with --profile "
        "(--no-all-profiles declines an option; it does not choose one)\n"
    ) in r.stderr


def test_two_elections_are_still_mutually_exclusive():
    r = _election_app().test(["run", "--profile", "work", "--all-profiles"])
    assert r.exit_code == 1
    assert (
        "error: --profile and --all-profiles are mutually exclusive\n"
    ) in r.stderr


# ---------------------------------------------------------------------------
# CLI-only election (§21.3, carried over by §24.6)
# ---------------------------------------------------------------------------


def test_member_election_is_command_line_only_env(monkeypatch):
    """Env neither elects nor supplies a member: it is not consulted at all."""
    monkeypatch.setenv("MYAPP_PROFILE", "work")
    r = _election_app().test(["run"])
    assert r.exit_code == 1
    assert (
        "error: one of --profile, --all-profiles, --current-profile is required\n"
    ) in r.stderr


def test_member_election_is_command_line_only_config(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"profile": "from-config"}\n')
    app = strictcli.App(
        name="myapp", version="1.0.0", help="test app", config=True,
    )

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(ctx, mode: Profile | AllProfiles):
        print(repr(mode))

    r = app.test(["--config", str(cfg), "run"])
    assert r.exit_code == 1
    assert "error: one of --profile, --all-profiles is required\n" in r.stderr


# ---------------------------------------------------------------------------
# What member spelling adds, and a mutex group could not express (§24.4)
# ---------------------------------------------------------------------------


@choice("work", help="the work profile")
class Work:
    value: str = member_value(help="the profile name")
    create_missing: bool = sub_flag(
        help="create the profile if it is absent", default=False,
    )


@choice("all", help="every profile")
class All:
    pass


def _scoped_member_app():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Work, All],
    )
    def run(ctx, mode: Work | All):
        print(repr(mode))

    return app


def test_a_member_may_own_a_scope():
    r = _scoped_member_app().test(["run", "--work", "w", "--create-missing"])
    assert r.exit_code == 0
    assert "Work(value='w', create_missing=True)" in r.stdout


def test_a_scoped_flag_under_the_wrong_member_is_a_scope_error():
    """Where a mutex group could only leave the flag silently ignored."""
    r = _scoped_member_app().test(["run", "--all", "--create-missing"])
    assert r.exit_code == 1
    assert (
        "error: flag '--create-missing' is only valid under '--work', but "
        "'--all' was elected\n"
    ) in r.stderr


def test_the_member_spelled_scope_path_names_the_member_flag():
    """A member-spelled segment is `--<choice>` -- the only token typed."""
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @choice("advanced", help="the advanced mode")
    class Advanced:
        tuning: str = sub_flag(help="tuning profile", presence="required")

    @choice("simple", help="the simple mode")
    class Simple:
        pass

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="member-flags", choices=[Advanced, Simple],
    )
    def run(ctx, mode: Advanced | Simple):
        return 0

    r = app.test(["run", "--advanced"])
    assert r.exit_code == 1
    assert "error: flag '--tuning' is required under '--advanced'\n" in r.stderr


# ---------------------------------------------------------------------------
# The programmatic front door (§24.11)
# ---------------------------------------------------------------------------


def test_call_takes_the_elected_record():
    app = _election_app()
    app.call("run", mode=AllProfiles())


def test_call_without_the_selector_is_the_required_error():
    app = _election_app()
    with pytest.raises(strictcli.InvokeError) as exc:
        app.call("run")
    assert "one of --profile, --all-profiles, --current-profile is required" in str(
        exc.value
    )


# ---------------------------------------------------------------------------
# Registration (§12.13)
# ---------------------------------------------------------------------------


def test_a_member_spelled_selector_cannot_carry_a_short():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "mode", help="the mode", presence="required", short="m",
            elect_by="member-flags", choices=[AllProfiles, CurrentProfile],
        )
    assert str(exc.value) == (
        'Flag "mode": a member-spelled choice flag is never typed, so it '
        "cannot carry a short: declare the short on a member"
    )


def test_a_defaulted_member_selector_may_only_elect_a_payload_less_member():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "mode", help="the mode", default=Profile(value="work"),
            elect_by="member-flags",
            choices=[Profile, AllProfiles],
        )
    assert str(exc.value) == (
        'Flag "mode": default= elects choice "profile", whose flag carries a '
        "value nothing supplies: only a payload-less member can be a default"
    )


def test_a_defaulted_member_selector_electing_a_payload_less_member_is_legal():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="which profiles", default=AllProfiles(),
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(ctx, mode: Profile | AllProfiles):
        print(f"{mode!r} source={ctx.source('mode')}")

    r = app.test(["run"])
    assert r.exit_code == 0
    assert "AllProfiles() source=default" in r.stdout
    r = app.test(["run", "--profile", "work"])
    assert r.exit_code == 0
    assert "Profile(value='work') source=cli" in r.stdout


def test_a_token_spelled_choice_cannot_carry_a_payload():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="selector-token", choices=[Profile, AllProfiles],
        )
    assert str(exc.value) == (
        'Choice "profile" of "mode": a token-spelled choice cannot carry a '
        "payload: the token names the choice, and a choice that carries its "
        "own value belongs to a member-spelled choice flag, declared with "
        'choice_flag(..., elect_by="member-flags")'
    )


def test_a_member_choice_name_inherits_every_flag_name_ban():
    """Under member spelling a choice name IS a flag name (§24.7)."""

    @choice("quiet", help="be quiet")
    class Quiet:
        pass

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="member-flags", choices=[Quiet, AllProfiles],
        )
    assert str(exc.value) == (
        "flag name 'quiet' is reserved by the framework "
        "(dry-run, approve-consequential, quiet, verbose)"
    )


# ---------------------------------------------------------------------------
# Help (§24.10)
# ---------------------------------------------------------------------------


def test_a_member_spelled_selector_renders_as_a_heading():
    """It has no token of its own, so its line carries the clause instead."""
    r = _scoped_member_app().test(["run", "--help"])
    assert r.exit_code == 0
    assert r.stdout == (
        "myapp run -- run it\n"
        "\n"
        "Flags:\n"
        "  mode                                         which profiles "
        "(exactly one of the following) [required]\n"
        "    --work <str>                               the work profile "
        "[required]\n"
        "      --create-missing, --no-create-missing    create the profile if "
        "it is absent [default: false]\n"
        "    --all                                      every profile "
        "[required]\n"
    )
