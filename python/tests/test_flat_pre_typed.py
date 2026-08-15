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


def test_a_scoped_value_and_a_root_one_are_ordered_by_the_declarations():
    """ONE sweep in the command's own declaration order, with the scope taking
    its position in it (§18.25 item 249): `count` is declared above `--via`,
    so it answers ahead of anything inside that selector's scope. The full
    rule, at every depth and from both doors, is in
    `test_value_sweep_order.py`."""
    assert _refusal(
        mode="all-profiles", via="email", retries="3", count="7",
    ) == "--count: expected integer, got str"


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


# ---------------------------------------------------------------------------
# A POSITIONAL's value (§23.3's declaration, item 240's rule)
#
# A positional is declared with the same closed set of four types and the same
# presence rule as a flag, so a pre-typed value is checked against it the same
# way -- and the boundary never turns a value into a token by stringifying it,
# which is what made `target=None` arrive as the four characters "None".
# ---------------------------------------------------------------------------


def _args_app(captured=None):
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag("need", type=str, help="a needed flag", presence="required")
    @strictcli.arg("target", help="the target", presence="required")
    @strictcli.arg("count", type=int, help="how many", presence="optional")
    def run(ctx, need, target, count):
        if captured is not None:
            captured.update(need=need, target=target, count=count)

    @app.command("many", effect="read_only", help="many of them")
    @strictcli.arg("names", help="the names", variadic=True, presence="optional")
    def many(ctx, names):
        if captured is not None:
            captured.update(names=names)

    @app.command("all", effect="read_only", help="all of them")
    @strictcli.arg("names", help="the names", variadic=True, presence="required")
    def all_of_them(ctx, names):
        if captured is not None:
            captured.update(names=names)

    @app.command("mixed", effect="read_only", help="one then many")
    @strictcli.arg("head", help="the first one", presence="optional")
    @strictcli.arg("rest", help="the others", variadic=True, presence="optional")
    def mixed(ctx, head, rest):
        if captured is not None:
            captured.update(head=head, rest=rest)

    return app


def _arg_refusal(command, **arguments):
    """The flat machine form, which carries positionals under their own names."""
    with pytest.raises(strictcli.InvokeError) as exc:
        _args_app()._call_with_kwargs(
            command, dict(arguments), approve_consequential=False, flat=True,
        )
    return str(exc.value)


def test_a_null_positional_is_refused():
    """It used to arrive as the string 'None' -- a value no command line could
    produce, since the caller never typed those four characters."""
    assert _arg_refusal("run", need="x", target=None) == (
        "argument 'target': expected string, got null"
    )


def test_an_optional_positional_refuses_an_explicit_null_too():
    """Optionality has one spelling here as well: the declaration plus an
    absent key, which is what delivers absence."""
    assert _arg_refusal("run", need="x", target="t", count=None) == (
        "argument 'count': expected integer, got null"
    )


def test_an_omitted_optional_positional_is_delivered_absent():
    captured: dict = {}
    _args_app(captured)._call_with_kwargs(
        "run", {"need": "x", "target": "t"}, approve_consequential=False,
        flat=True,
    )
    assert captured["count"] is None


def test_a_wrong_typed_positional_is_refused():
    """`target=5` used to reach the handler as the string '5'."""
    assert _arg_refusal("run", need="x", target=5) == (
        "argument 'target': expected string, got int"
    )


def test_a_bool_is_not_a_string_positional():
    assert _arg_refusal("run", need="x", target=True) == (
        "argument 'target': expected string, got bool"
    )


def test_an_int_positional_refuses_a_numeral_string():
    """Nothing re-parses a pre-typed value: the numeral's TEXT is not an
    integer, exactly as it is not one for a flag."""
    assert _arg_refusal("run", need="x", target="t", count="7") == (
        "argument 'count': expected integer, got str"
    )


def test_an_int_positional_refuses_a_float():
    assert _arg_refusal("run", need="x", target="t", count=1.5) == (
        "argument 'count': expected integer, got float"
    )


def test_a_well_typed_positional_reaches_the_handler_as_supplied():
    captured: dict = {}
    _args_app(captured)._call_with_kwargs(
        "run", {"need": "x", "target": "t", "count": 7},
        approve_consequential=False, flat=True,
    )
    assert captured["target"] == "t"
    assert captured["count"] == 7
    assert isinstance(captured["count"], int)


def test_a_variadic_positional_takes_an_array():
    captured: dict = {}
    _args_app(captured)._call_with_kwargs(
        "many", {"names": ["a", "b"]}, approve_consequential=False, flat=True,
    )
    assert captured["names"] == ["a", "b"]


def test_a_variadic_positional_refuses_a_wrong_typed_element():
    """Each element is one positional and is checked as one, so the sentence
    is the arg's own -- there is no collection type here to name."""
    assert _arg_refusal("many", names=["a", 2]) == (
        "argument 'names': expected string, got int"
    )


def test_a_variadic_positional_takes_a_scalar_as_its_one_element():
    """A variadic arg is a SEQUENCE of positionals: one value is the one
    positional a command line would have typed."""
    captured: dict = {}
    _args_app(captured)._call_with_kwargs(
        "many", {"names": "a"}, approve_consequential=False, flat=True,
    )
    assert captured["names"] == ["a"]


def test_a_variadic_positional_refuses_a_null_element():
    assert _arg_refusal("many", names=None) == (
        "argument 'names': expected string, got null"
    )


def test_an_omitted_optional_variadic_is_delivered_empty():
    captured: dict = {}
    _args_app(captured)._call_with_kwargs(
        "many", {}, approve_consequential=False, flat=True,
    )
    assert captured["names"] == []


def test_an_empty_array_does_not_satisfy_a_required_variadic():
    """An empty array is the flat spelling of no tokens at all, and no tokens
    is what the argv path refuses here."""
    assert _arg_refusal("all", names=[]) == (
        "missing required argument 'names'"
    )


def test_an_absent_required_positional_keeps_its_own_sentence():
    assert _arg_refusal("run", need="x") == (
        "missing required argument 'target'"
    )


def test_the_same_refusals_reach_the_record_front_door():
    """`call()` and the flat form are two spellings of one declaration, so a
    positional's value is decided the same way at both."""
    with pytest.raises(strictcli.InvokeError) as exc:
        _args_app().call("run", need="x", target=None)
    assert str(exc.value) == "argument 'target': expected string, got null"
    with pytest.raises(strictcli.InvokeError) as exc:
        _args_app().call("run", need="x", target=5)
    assert str(exc.value) == "argument 'target': expected string, got int"


def test_a_positional_value_refusal_keeps_the_command_lines_own_place():
    """The argv path reports a missing required FLAG before it parses a
    positional token, and the programmatic doors report the same order for the
    same state -- the step is unmoved, only what it does inside it changed."""
    r = _args_app().test(["run", "abc"])
    assert r.exit_code == 1
    assert "error: flag '--need' is required\n" in r.stderr
    with pytest.raises(strictcli.InvokeError) as exc:
        _args_app().call("run", target=5)
    assert str(exc.value) == "flag '--need' is required"


def test_the_command_line_still_parses_its_own_tokens():
    """Nothing about the argv path changed: a token IS text, and it is parsed
    into the declared type as it always was."""
    captured: dict = {}
    r = _args_app(captured).test(["run", "--need", "x", "t", "7"])
    assert r.exit_code == 0
    assert captured["target"] == "t"
    assert captured["count"] == 7


def test_each_positional_is_read_under_its_own_name():
    """A flat object has no positions, so the variadic's elements can never
    slide into a fixed arg the object did not name."""
    captured: dict = {}
    _args_app(captured)._call_with_kwargs(
        "mixed", {"rest": ["a", "b"]}, approve_consequential=False, flat=True,
    )
    assert captured["head"] is None
    assert captured["rest"] == ["a", "b"]


def test_a_variadic_element_is_refused_under_the_variadic_own_name():
    assert _arg_refusal("mixed", head="h", rest=["a", 2]) == (
        "argument 'rest': expected string, got int"
    )


# ---------------------------------------------------------------------------
# A DASH-SPELLED key names nothing (§18.24 item 242)
#
# The key namespace at this boundary is the underscored delivery-name space --
# the parameter name a handler receives, which is what the flat schema
# publishes. A flag's dashed spelling is its command-line token, and there are
# no tokens here, so a dashed key is an unknown property: a fact about the
# object's shape, reported ahead of every other problem in the same object.
# ---------------------------------------------------------------------------


@choice("sms", help="a text message")
class Sms:
    phone_number: str = sub_flag(help="where to text", presence="required")


def _dashed_app():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag(
        "keep-going", type=bool, help="keep going", default=False,
    )
    @choice_flag(
        "via", help="delivery channel", default=NoDelivery(),
        elect_by="selector-token", choices=[NoDelivery, Sms],
    )
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(
        ctx, keep_going, via: NoDelivery | Sms, mode: Profile | AllProfiles,
    ):
        pass

    return app


def _dashed_refusal(**arguments):
    with pytest.raises(strictcli.InvokeError) as exc:
        _dashed_app()._call_with_kwargs(
            "run", dict(arguments), approve_consequential=False, flat=True,
        )
    return str(exc.value)


def test_a_dash_spelled_member_key_names_nothing():
    assert _dashed_refusal(**{"all-profiles": False}) == (
        "unknown parameter 'all-profiles' for command 'run'"
    )


def test_a_dash_spelled_root_flag_key_names_nothing():
    assert _dashed_refusal(**{"keep-going": True, "all_profiles": True}) == (
        "unknown parameter 'keep-going' for command 'run'"
    )


def test_a_dash_spelled_scoped_key_names_nothing():
    """At every depth: the scoped parameter is published underscored too."""
    assert _dashed_refusal(
        **{"all_profiles": True, "via": "sms", "phone-number": "555"}
    ) == "unknown parameter 'phone-number' for command 'run'"


def test_a_dash_spelled_key_is_shape_and_outranks_an_election_refusal():
    assert _dashed_refusal(
        **{"mode": "profile", "profile": "work", "all-profiles": False}
    ) == "unknown parameter 'all-profiles' for command 'run'"


def test_the_underscored_spelling_is_the_one_that_works():
    """Which is what makes the dashed one a mistake worth a sentence rather
    than a second spelling of the same parameter."""
    app = _dashed_app()
    assert app._call_with_kwargs(
        "run",
        {"all_profiles": True, "keep_going": True, "via": "sms",
         "phone_number": "555"},
        approve_consequential=False, flat=True,
    ) is None


def test_the_record_door_refuses_a_dash_spelled_key_too():
    """Both programmatic doors read one namespace: a door that ran the token
    mapping over its keys before consulting the index would accept there what
    the other refuses."""
    with pytest.raises(strictcli.InvokeError) as exc:
        _dashed_app().call("run", **{"keep-going": True, "all_profiles": True})
    assert str(exc.value) == "unknown parameter 'keep-going' for command 'run'"


def test_the_dashed_spelling_is_the_command_lines_own():
    """The token spelling is not wrong -- it is just not a key."""
    r = _dashed_app().test(
        ["run", "--all-profiles", "--keep-going", "--via", "sms",
         "--phone-number", "555"],
    )
    assert r.exit_code == 0


# ---------------------------------------------------------------------------
# The RECORD door stages command-wide too (§18.24 item 243)
#
# The phase order is a property of the parser, not of the input, so it governs
# every programmatic door: a door converts every selector's record first and
# only then reports, with the stage deciding which refusal is heard -- shape,
# election, scope, value, presence -- and declaration order inside one stage.
# ---------------------------------------------------------------------------


def _two_selector_app():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag("count", type=int, help="a count", presence="optional")
    @choice_flag(
        "via", help="delivery channel", presence="required",
        elect_by="selector-token", choices=[NoDelivery, Email],
    )
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(ctx, count, via: NoDelivery | Email, mode: Profile | AllProfiles):
        pass

    return app


def _record_refusal(**kwargs):
    with pytest.raises(strictcli.InvokeError) as exc:
        _two_selector_app().call("run", **kwargs)
    return str(exc.value)


def test_a_record_naming_no_declared_choice_is_an_election_refusal():
    assert _record_refusal(via="email", mode=AllProfiles()) == (
        "parameter 'via' for command 'run' must be an instance of a declared "
        "choice of '--via' (NoDelivery | Email), got str"
    )


def test_a_record_of_a_foreign_choice_takes_the_same_refusal():
    assert _record_refusal(via=Profile(value="work"), mode=AllProfiles()) == (
        "parameter 'via' for command 'run' must be an instance of a declared "
        "choice of '--via' (NoDelivery | Email), got Profile"
    )


def test_declaration_order_decides_inside_one_stage():
    """Two records naming no declared choice in one call: the earlier
    declaration is heard, never whichever the walk happened to reach first."""
    assert _record_refusal(via="email", mode="all-profiles") == (
        "parameter 'via' for command 'run' must be an instance of a declared "
        "choice of '--via' (NoDelivery | Email), got str"
    )


def test_a_later_records_refusal_is_heard_before_a_missing_election():
    """A missing selector is the PRESENCE stage (§18.22 item 232), which is
    the last one: a later selector's record naming no declared choice is a
    fact about the object's shape and outranks it."""
    assert _record_refusal(mode=42) == (
        "parameter 'mode' for command 'run' must be an instance of a declared "
        "choice of '--mode' (Profile | AllProfiles), got int"
    )


def test_an_unknown_key_still_outranks_every_election_refusal():
    assert _record_refusal(via="email", nope=1) == (
        "unknown parameter 'nope' for command 'run'"
    )


def test_a_root_value_problem_outranks_a_selector_nobody_elected():
    """A selector nothing elected is a PRESENCE fact, and presence is the last
    stage: every value in the call is read before it is reported."""
    assert _record_refusal(mode=AllProfiles(), count="7") == (
        "--count: expected integer, got str"
    )


def test_the_missing_selector_is_what_is_left_when_the_values_check_out():
    assert _record_refusal(mode=AllProfiles(), count=7) == (
        "flag '--via' is required"
    )


def test_the_root_value_problem_is_reported_once_every_election_is_settled():
    assert _record_refusal(
        via=NoDelivery(), mode=AllProfiles(), count="7",
    ) == "--count: expected integer, got str"


# ---------------------------------------------------------------------------
# An integral number satisfies an `int` declaration (§18.25 item 247)
#
# JSON has one number type, and a document may write an integer as `7.0`. Go's
# decoder produces a float64 for every number and TypeScript's a number, so
# refusing an integral float at the machine boundary would refuse every integer
# that door can carry -- both already accommodate it. Python's decoder keeps the
# distinction, so the accommodation is the DOOR's rather than the decoder's: at
# the flat machine boundary an integral number satisfies an `int` declaration,
# for flags and positionals alike, and nowhere else. A fractional number is
# refused with the sentence it always had.
# ---------------------------------------------------------------------------


def _widening_app(captured=None):
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag("count", type=int, help="a count", presence="optional")
    @strictcli.flag("label", type=str, help="a label", presence="optional")
    @strictcli.flag("flip", type=bool, help="a switch", presence="optional")
    @strictcli.flag(
        "port", type=int, help="a port", repeatable=True, unique=False,
        default=[],
    )
    @strictcli.flag("limit", type=dict[str, int], help="limits", default={})
    @strictcli.arg("size", type=int, help="how big", presence="optional")
    def run(ctx, count, label, flip, port, limit, size):
        if captured is not None:
            captured.update(
                count=count, label=label, flip=flip, port=port, limit=limit,
                size=size,
            )

    return app


def _widened(**arguments):
    captured: dict = {}
    _widening_app(captured)._call_with_kwargs(
        "run", dict(arguments), approve_consequential=False, flat=True,
    )
    return captured


def _widening_refusal(**arguments):
    with pytest.raises(strictcli.InvokeError) as exc:
        _widening_app()._call_with_kwargs(
            "run", dict(arguments), approve_consequential=False, flat=True,
        )
    return str(exc.value)


def test_an_integral_float_satisfies_an_int_flag():
    captured = _widened(count=7.0)
    assert captured["count"] == 7
    assert isinstance(captured["count"], int)


def test_a_fractional_float_is_still_refused():
    assert _widening_refusal(count=7.5) == (
        "--count: expected integer, got float"
    )


def test_an_integral_float_satisfies_an_int_positional():
    captured = _widened(size=7.0)
    assert captured["size"] == 7
    assert isinstance(captured["size"], int)


def test_a_fractional_positional_is_still_refused():
    assert _widening_refusal(size=7.5) == (
        "argument 'size': expected integer, got float"
    )


def test_an_integral_float_satisfies_a_repeatable_int_element():
    captured = _widened(port=[80.0, 443])
    assert captured["port"] == [80, 443]
    assert all(isinstance(p, int) for p in captured["port"])


def test_a_fractional_element_is_still_refused():
    assert _widening_refusal(port=[80.5]) == (
        "--port: element 0: expected int, got float"
    )


def test_an_integral_float_satisfies_a_dict_int_value():
    captured = _widened(limit={"cpu": 2.0})
    assert captured["limit"] == {"cpu": 2}
    assert isinstance(captured["limit"]["cpu"], int)


def test_a_fractional_dict_value_is_still_refused():
    assert _widening_refusal(limit={"cpu": 2.5}) == (
        "--limit: key 'cpu': expected int, got float"
    )


def test_an_integral_float_satisfies_a_scoped_int():
    """Depth changes nothing: the boundary is the door, not the level."""
    captured: dict = {}
    _flat(_app(captured), mode="all-profiles", via="email", retries=7.0)
    assert captured["via"].retries == 7
    assert isinstance(captured["via"].retries, int)


def test_the_widening_reaches_only_an_int_declaration():
    """A float is not a string and not a boolean, and the type NAME a refusal
    quotes is Python's own reading of the value it was handed."""
    assert _widening_refusal(label=7.0) == "--label: expected string, got float"
    assert _widening_refusal(flip=1.0) == "--flip: expected boolean, got float"


def test_a_bool_is_still_not_an_integer():
    assert _widening_refusal(count=True) == "--count: expected integer, got bool"


def test_the_native_record_door_keeps_python_s_own_numeric_model():
    """The accommodation is the machine boundary's. `call()` takes Python's
    own values, and nothing in Python's numeric model makes a float an
    integer -- an acknowledged divergence from the two runtimes that cannot
    see that a number was written with a point."""
    with pytest.raises(strictcli.InvokeError) as exc:
        _widening_app().call("run", count=7.0)
    assert str(exc.value) == "--count: expected integer, got float"
    with pytest.raises(strictcli.InvokeError) as exc:
        _widening_app().call("run", size=7.0)
    assert str(exc.value) == "argument 'size': expected integer, got float"
