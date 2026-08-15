"""ONE declaration-ordered value sweep at the programmatic doors (§18.25 item 249).

Item 243 closed its stage table with "declaration order within one stage",
which does not say WHOSE declaration order decides when one stage holds a root
flag's value and a scoped one at the same time. It is the COMMAND's own, walked
once: each declaration in the order it was written, a selector taking its
position in that walk, and the values of its elected record read at that
position, at every depth -- root flags and selectors interleaved, never
partitioned into scoped-first and root-second. The app's globals follow the
command's own declarations, and presence is strictly after every value.

Both programmatic doors are the same sweep: the flat machine form and the
elected record are two spellings of one declaration, and an object has no order
of its own, so the order the caller happened to write its keys in decides
nothing. TypeScript is the reference implementation for this order.
"""

import pytest

import strictcli
from strictcli import (
    choice,
    choice_flag,
    member_value,
    sub_choice_flag,
    sub_flag,
)


@choice("profile", help="one named profile")
class Profile:
    value: str = member_value(help="the profile name")


@choice("all-profiles", help="every profile")
class AllProfiles:
    pass


@choice("plain", help="plain text")
class Plain:
    pass


@choice("rich", help="rich text")
class Rich:
    width: int = sub_flag(help="how wide", presence="required")


@choice("none", help="no delivery")
class NoDelivery:
    pass


@choice("email", help="an email message")
class Email:
    retries: int = sub_flag(help="how many", presence="required")
    body: Plain | Rich = sub_choice_flag(
        help="the body format", default=Plain(), elect_by="selector-token",
        choices=[Plain, Rich],
    )
    tail: int = sub_flag(help="how many lines", presence="optional")


def _email(**overrides):
    """An `Email` record with every field the caller did not name declared."""
    fields = dict(retries=1, tail=None)
    fields.update(overrides)
    return Email(**fields)


def _app(captured=None, *, via_required=False):
    """`before` is declared BEFORE the selector, `after` AFTER it."""
    app = strictcli.App(
        name="myapp", version="1.0.0", help="test app",
        flags=[strictcli.Flag(name="jobs", type=int, help="how many", default=1)],
    )
    via = (
        dict(presence="required") if via_required else dict(default=NoDelivery())
    )

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag("before", type=int, help="a count", presence="optional")
    @choice_flag(
        "via", help="delivery channel", elect_by="selector-token",
        choices=[NoDelivery, Email], **via,
    )
    @strictcli.flag("after", type=int, help="a count", presence="optional")
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(
        ctx, before, via: NoDelivery | Email, after,
        mode: Profile | AllProfiles, jobs,
    ):
        if captured is not None:
            captured.update(
                before=before, via=via, after=after, mode=mode, jobs=jobs,
            )

    return app


def _flat_refusal(*, via_required=False, **arguments):
    with pytest.raises(strictcli.InvokeError) as exc:
        _app(via_required=via_required)._call_with_kwargs(
            "run", dict(arguments), approve_consequential=False, flat=True,
        )
    return str(exc.value)


def _record_refusal(*, via_required=False, **kwargs):
    with pytest.raises(strictcli.InvokeError) as exc:
        _app(via_required=via_required).call("run", **kwargs)
    return str(exc.value)


# ---------------------------------------------------------------------------
# A scope is a POSITION in the sweep, not a group before it
# ---------------------------------------------------------------------------


def test_a_root_flag_declared_before_the_selector_is_swept_first():
    """The sweep is the command's own declaration order, so the flag written
    above the selector answers ahead of anything inside that selector's
    scope."""
    assert _flat_refusal(
        before="nope", via="email", retries="nope", all_profiles=True,
    ) == "--before: expected integer, got str"


def test_a_root_flag_declared_after_the_selector_is_swept_after_the_scope():
    """The same rule read the other way: the scope holds its position, so a
    flag declared below it answers second."""
    assert _flat_refusal(
        after="nope", via="email", retries="nope", all_profiles=True,
    ) == "--retries: expected integer, got str"


def test_the_record_door_sweeps_the_same_way():
    assert _record_refusal(
        before="nope", via=_email(retries="nope"), mode=AllProfiles(),
    ) == "--before: expected integer, got str"
    assert _record_refusal(
        after="nope", via=_email(retries="nope"), mode=AllProfiles(),
    ) == "--retries: expected integer, got str"


def test_the_caller_s_own_key_order_decides_nothing():
    """A JSON object and a keyword-argument list have no order of their own,
    so writing the same call the other way round changes no answer."""
    want = "--before: expected integer, got str"
    assert _flat_refusal(
        via="email", retries="nope", before="nope", all_profiles=True,
    ) == want
    assert _record_refusal(
        mode=AllProfiles(), via=_email(retries="nope"), before="nope",
    ) == want


def test_two_root_flags_either_side_of_the_selector_keep_their_order():
    assert _flat_refusal(
        before="nope", after="nope", all_profiles=True,
    ) == "--before: expected integer, got str"


# ---------------------------------------------------------------------------
# Depth: a nested selector's values sit where the nested selector is declared
# ---------------------------------------------------------------------------


def test_a_nested_scope_holds_its_own_position_in_the_scope_above_it():
    """`retries` is declared before the nested selector, `tail` after it."""
    assert _flat_refusal(
        via="email", retries="nope", body="rich", width="nope",
        all_profiles=True,
    ) == "--retries: expected integer, got str"
    assert _flat_refusal(
        via="email", retries=1, body="rich", width="nope", tail="nope",
        all_profiles=True,
    ) == "--width: expected integer, got str"


def test_the_record_door_reads_the_same_depth_the_same_way():
    assert _record_refusal(
        via=_email(retries="nope", body=Rich(width="nope")), mode=AllProfiles(),
    ) == "--retries: expected integer, got str"
    assert _record_refusal(
        via=_email(body=Rich(width="nope"), tail="nope"), mode=AllProfiles(),
    ) == "--width: expected integer, got str"


# ---------------------------------------------------------------------------
# The app's globals follow the command's own declarations
# ---------------------------------------------------------------------------


def test_a_global_flag_is_swept_after_every_declaration_of_the_command():
    assert _flat_refusal(
        jobs="nope", after="nope", all_profiles=True,
    ) == "--after: expected integer, got str"
    assert _flat_refusal(
        jobs="nope", via="email", retries="nope", all_profiles=True,
    ) == "--retries: expected integer, got str"


def test_a_global_flag_still_answers_when_nothing_else_is_wrong():
    assert _flat_refusal(jobs="nope", all_profiles=True) == (
        "--jobs: expected integer, got str"
    )


# ---------------------------------------------------------------------------
# PRESENCE is strictly after every value, wherever the missing thing lives
# ---------------------------------------------------------------------------


def test_a_root_value_refusal_outranks_a_scoped_presence_refusal():
    """The stage table itself: every value in the call is interpreted before
    any missing required flag is reported, at any depth."""
    assert _flat_refusal(
        before="nope", via="email", all_profiles=True,
    ) == "--before: expected integer, got str"


def test_a_root_value_refusal_outranks_a_missing_selector():
    """A selector nobody elected is a presence fact too."""
    assert _flat_refusal(
        via_required=True, before="nope", all_profiles=True,
    ) == "--before: expected integer, got str"
    assert _record_refusal(
        via_required=True, before="nope", mode=AllProfiles(),
    ) == "--before: expected integer, got str"


def test_a_missing_selector_is_what_is_left_when_every_value_checks_out():
    assert _flat_refusal(via_required=True, before=1, all_profiles=True) == (
        "flag '--via' is required"
    )


def test_an_election_refusal_still_outranks_every_value():
    """Election is settled command-wide before the value sweep begins."""
    assert _flat_refusal(before="nope", mode="nonsense") == (
        "--mode: invalid value 'nonsense', must be one of: profile, all-profiles"
    )


def test_a_scoped_presence_refusal_outranks_a_missing_required_root_flag():
    """Both are presence: the scopes are decided where they always were, and
    the command's own surface after them."""
    assert _flat_refusal(via_required=True, via="email") == (
        "flag '--retries' is required under '--via email'"
    )


# ---------------------------------------------------------------------------
# The command line answers with the order it was TYPED in
# ---------------------------------------------------------------------------


def test_the_command_line_reads_its_own_tokens_in_its_own_order():
    """The argv path is NOT a party to the sweep above (§18.27 item 257).

    §24.3 pins command-line order within a phase, and the value phase is one
    phase whether a token names a root flag or a scoped one: the first token
    that will not coerce is the one reported, whatever the declaration says.
    """
    r = _app().test([
        "run", "--via", "email", "--retries", "nope", "--after", "nope",
        "--all-profiles",
    ])
    assert r.exit_code == 1
    assert "error: --retries: expected integer, got 'nope'\n" in r.stderr


def test_the_command_line_reports_the_root_token_when_the_root_token_is_first():
    """The same two mistakes the other way round: the same rule, the other
    answer. Nothing about a declaration decides which of the two is printed."""
    r = _app().test([
        "run", "--via", "email", "--after", "nope", "--retries", "nope",
        "--all-profiles",
    ])
    assert r.exit_code == 1
    assert "error: --after: expected integer, got 'nope'\n" in r.stderr


def test_a_well_formed_call_reaches_the_handler_at_every_depth():
    captured: dict = {}
    _app(captured)._call_with_kwargs(
        "run",
        {"before": 1, "via": "email", "retries": 2, "body": "rich",
         "width": 3, "after": 4, "all_profiles": True, "jobs": 5},
        approve_consequential=False, flat=True,
    )
    assert captured["before"] == 1
    assert captured["after"] == 4
    assert captured["jobs"] == 5
    assert captured["via"].retries == 2
    assert captured["via"].body == Rich(width=3)
    assert captured["mode"] == AllProfiles()
