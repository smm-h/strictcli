"""The flat machine boundary's SHAPE staging (§24.11, §24.3).

**§18.23 item 238**: a key naming nothing the command declares is a fact about
the object's SHAPE, and shape is decided before any election, scope, value or
presence problem is reported -- exactly as an unknown flag outranks all four
on the command line, wherever it sits in argv.
"""

import pytest

import strictcli
from strictcli import choice, choice_flag, member_value, sub_flag


@choice("profile", help="a profile")
class Profile:
    value: str = member_value(help="the profile name")


@choice("all-profiles", help="every profile")
class AllProfiles:
    pass


@choice("none", help="no delivery")
class NoDelivery:
    pass


@choice("email", help="an email message")
class Email:
    retries: int = sub_flag(help="how many", presence="required")
    strict: bool = sub_flag(help="fail on a soft bounce", default=False)
    ratio: float = sub_flag(help="the sampling ratio", default=1.0)


def _app(captured=None):
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag("name", type=str, help="a name", presence="optional")
    @strictcli.flag("count", type=int, help="a count", presence="optional")
    @strictcli.flag("weight", type=float, help="a weight", presence="optional")
    @strictcli.flag(
        "tag", type=str, help="a tag", repeatable=True, unique=False, default=[],
    )
    @strictcli.flag(
        "header", type=dict[str, str], help="a header", default={},
    )
    @choice_flag(
        "via", help="delivery channel", default=NoDelivery(),
        elect_by="selector-token", choices=[NoDelivery, Email],
    )
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(
        ctx, name, count, weight, tag, header,
        via: NoDelivery | Email, mode: Profile | AllProfiles,
    ):
        if captured is not None:
            captured.update(
                name=name, count=count, weight=weight, tag=tag,
                header=header, via=via, mode=mode,
            )

    return app


def _flat(app, **arguments):
    """Call `run` through the flat machine form the MCP boundary uses."""
    return app._call_with_kwargs(
        "run", dict(arguments), approve_consequential=False, flat=True,
    )


def _refusal(**arguments):
    with pytest.raises(strictcli.InvokeError) as exc:
        _flat(_app(), **arguments)
    return str(exc.value)


# ---------------------------------------------------------------------------
# An unknown key is SHAPE (§24.3's phase order, item 224's reason)
#
# On the command line an unknown flag outranks every election, scope, value and
# presence problem wherever it sits in argv. The flat object's unknown key is
# the same fact about the same command, so it reports first there too.
# ---------------------------------------------------------------------------


def test_an_unknown_key_is_refused():
    assert _refusal(mode="all-profiles", nope=1) == (
        "unknown parameter 'nope' for command 'run'"
    )


def test_an_unknown_key_outranks_a_missing_election():
    assert _refusal(nope=1) == "unknown parameter 'nope' for command 'run'"


def test_an_unknown_key_outranks_a_double_election():
    assert _refusal(profile="work", all_profiles=True, nope=1) == (
        "unknown parameter 'nope' for command 'run'"
    )


def test_an_unknown_key_outranks_a_scope_violation():
    assert _refusal(mode="all-profiles", retries=3, nope=1) == (
        "unknown parameter 'nope' for command 'run'"
    )


def test_an_unknown_key_outranks_a_missing_member_payload():
    assert _refusal(mode="profile", nope=1) == (
        "unknown parameter 'nope' for command 'run'"
    )


def test_an_unknown_key_outranks_a_value_refusal():
    assert _refusal(mode="all-profiles", count="7", nope=1) == (
        "unknown parameter 'nope' for command 'run'"
    )


def test_the_command_line_stages_an_unknown_flag_the_same_way():
    """The claim is about the parser, not about one door: every state above
    reports the unknown token on the command line too."""
    for argv in (
        ["run", "--nope", "--all-profiles"],
        ["run", "--nope", "--profile", "work", "--all-profiles"],
        ["run", "--nope", "--all-profiles", "--retries", "3"],
        ["run", "--nope", "--profile"],
        ["run", "--all-profiles", "--count", "abc", "--nope"],
    ):
        r = _app().test(argv)
        assert r.exit_code == 1
        assert "error: unknown flag '--nope'\n" in r.stderr, argv


def test_an_unknown_key_is_still_refused_at_the_record_front_door():
    with pytest.raises(strictcli.InvokeError) as exc:
        _app().call("run", mode=AllProfiles(), nope=1)
    assert str(exc.value) == "unknown parameter 'nope' for command 'run'"


def test_a_scoped_flags_own_key_is_not_unknown_at_the_flat_boundary():
    """Every scoped name at every depth is a property of the flat schema, so
    supplying one is a scope question and never a shape one."""
    assert _refusal(mode="all-profiles", retries=3) == (
        "flag '--retries' is only valid under '--via email', but "
        "'--via none' was elected by default"
    )
