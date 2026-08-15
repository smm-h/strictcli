"""The flat machine boundary's SHAPE and VALUE staging (§24.11, §24.3).

Two facts about the flat form the MCP server and the programmatic front doors
take, neither of which the argv path can express:

- **§18.23 item 238**: a key naming nothing the command declares is a fact
  about the object's SHAPE, and shape is decided before any election, scope,
  value or presence problem is reported -- exactly as an unknown flag outranks
  all four on the command line, wherever it sits in argv.
- **§18.23 item 240**: a value arrives already typed, so nothing parses it --
  but *pre-typed* means ALREADY OF THE DECLARED TYPE, never exempt from the
  declaration. Every supplied value is checked against the type its
  declaration names, and `null` is not a legal value for anything: optionality
  has one spelling (§23.4), which is the declaration plus an absent key.
  Everything the boundary can carry is covered here -- a member's payload, a
  scoped flag, and the command's own root flags.
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
# A member's payload (§24.11): the value under the member's own key
# ---------------------------------------------------------------------------


def test_a_null_member_payload_is_refused():
    """An elected member whose payload key holds `null` is NOT the elected
    member with nothing supplied: the key is there and its value is wrong."""
    assert _refusal(mode="profile", profile=None) == (
        "--profile: expected string, got null"
    )


def test_a_null_member_payload_is_not_the_missing_payload_refusal():
    """The absent key keeps its own sentence, so the two states stay apart."""
    assert _refusal(mode="profile") == "flag '--profile' requires a value"


def test_a_wrong_typed_member_payload_is_refused():
    assert _refusal(profile=42) == "--profile: expected string, got int"


def test_a_bool_is_not_a_string_payload():
    assert _refusal(profile=True) == "--profile: expected string, got bool"


# ---------------------------------------------------------------------------
# A scoped flag (§24.3's value phase, running over pre-typed values)
# ---------------------------------------------------------------------------


def test_a_null_scoped_flag_is_refused():
    assert _refusal(mode="all-profiles", via="email", retries=None) == (
        "--retries: expected integer, got null"
    )


def test_a_wrong_typed_scoped_flag_is_refused():
    """The flat form carries an int as an int: the numeral's TEXT is not an
    integer here, and nothing re-parses it into one."""
    assert _refusal(mode="all-profiles", via="email", retries="3") == (
        "--retries: expected integer, got str"
    )


def test_a_scoped_bool_refuses_a_truthy_int():
    assert _refusal(
        mode="all-profiles", via="email", retries=1, strict=1,
    ) == "--strict: expected boolean, got int"


def test_a_scoped_float_takes_an_int_and_widens_it():
    """The one widening the declaration allows: an integer IS a float value,
    and it reaches the handler as one."""
    captured: dict = {}
    _flat(_app(captured), mode="all-profiles", via="email", retries=1, ratio=2)
    assert captured["via"].ratio == 2.0
    assert isinstance(captured["via"].ratio, float)


def test_a_scoped_int_refuses_a_float():
    assert _refusal(
        mode="all-profiles", via="email", retries=1.5,
    ) == "--retries: expected integer, got float"


# ---------------------------------------------------------------------------
# The command's own root flags
# ---------------------------------------------------------------------------


def test_a_null_root_flag_is_refused_where_the_declaration_is_not_optional():
    """`tag` declares a default, which is not the same as declaring optional:
    only an optional declaration says absence is a value."""
    assert _refusal(mode="all-profiles", tag=None) == (
        "--tag: expected array for repeatable flag, got null"
    )


def test_an_optional_root_flag_refuses_an_explicit_null_too():
    """Optionality has one spelling: the declaration plus an absent key. A
    null carries nothing that spelling cannot already say, so it is refused
    wherever it appears rather than being read as a second spelling of it."""
    assert _refusal(mode="all-profiles", name=None) == (
        "--name: expected string, got null"
    )


def test_an_omitted_optional_root_flag_is_delivered_absent():
    """Which is what the caller who wanted to send a null was reaching for."""
    captured: dict = {}
    _flat(_app(captured), mode="all-profiles")
    assert captured["name"] is None


def test_a_wrong_typed_root_flag_is_refused():
    assert _refusal(mode="all-profiles", count="7") == (
        "--count: expected integer, got str"
    )


def test_a_bool_is_not_an_integer():
    assert _refusal(mode="all-profiles", count=True) == (
        "--count: expected integer, got bool"
    )


def test_a_root_float_takes_an_int_and_widens_it():
    captured: dict = {}
    _flat(_app(captured), mode="all-profiles", weight=3)
    assert captured["weight"] == 3.0
    assert isinstance(captured["weight"], float)


def test_a_repeatable_root_flag_refuses_a_scalar():
    assert _refusal(mode="all-profiles", tag="one") == (
        "--tag: expected array for repeatable flag, got str"
    )


def test_a_repeatable_root_flag_refuses_a_wrong_typed_element():
    assert _refusal(mode="all-profiles", tag=["one", 2]) == (
        "--tag: element 1: expected str, got int"
    )


def test_a_dict_root_flag_refuses_a_scalar():
    assert _refusal(mode="all-profiles", header="k=v") == (
        "--header: expected object for dict flag, got str"
    )


def test_a_dict_root_flag_refuses_a_wrong_typed_value():
    assert _refusal(mode="all-profiles", header={"k": 2}) == (
        "--header: key 'k': expected str, got int"
    )


def test_the_same_refusal_reaches_the_record_front_door():
    """`call()` takes the elected record rather than the flat object, but a
    root flag's value is pre-typed at both doors and the declaration decides
    the same way at both."""
    with pytest.raises(strictcli.InvokeError) as exc:
        _app().call("run", mode=AllProfiles(), count="7")
    assert str(exc.value) == "--count: expected integer, got str"


# ---------------------------------------------------------------------------
# Where a value refusal sits among the phases (§24.3, staging)
# ---------------------------------------------------------------------------


def test_an_election_refusal_outranks_a_value_refusal():
    """Election is resolved command-wide before any value is refused, so the
    double election is the sentence even though a root value is also wrong."""
    assert _refusal(profile="work", all_profiles=True, count="7") == (
        "--profile and --all-profiles are mutually exclusive"
    )


def test_a_scoped_value_refusal_outranks_a_root_one():
    """Declaration order: the scopes the walk collected, then the command's
    own flags."""
    assert _refusal(
        mode="all-profiles", via="email", retries="3", count="7",
    ) == "--retries: expected integer, got str"


def test_a_value_refusal_outranks_a_missing_required_flag():
    """Value precedes presence: the wrong scoped value is named rather than
    the required scoped flag nothing supplied."""
    assert _refusal(mode="all-profiles", via="email", strict="yes") == (
        "--strict: expected boolean, got str"
    )


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
