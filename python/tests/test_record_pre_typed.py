"""The RECORD door's value stage, at every depth (§24.11, §24.3).

`call()` takes the elected record -- a choice instance, pre-typed -- and *pre-
typed* means ALREADY OF THE DECLARED TYPE, never exempt from the declaration
(§18.23 item 240). A record's fields are the scope's flags, so every value one
carries is checked against the declaration it was supplied against, exactly as
the flat door checks the same value under the same declaration.

The phase order is the parser's, so it governs this door too (§18.24 item 243):
the record's shape is decided over the whole command before any value is read,
the value sweep runs in DECLARATION order rather than the order the caller
happened to write the keyword arguments, and presence is last.

Two facts belong to Python's record surface and to no other door:

- A record is COMPLETE by construction. `@choice`'s frozen dataclass refuses a
  missing field and an unknown field at construction, so the scope and presence
  problems the flat door can spell inside a record cannot be reached here.
- An `optional` scoped field has no dataclass default, so the caller writes
  ``note=None`` to say what an absent key says at the flat door. `None` on an
  optional field is therefore absence, not a value the declaration forbids.
"""

import pytest

import strictcli
from strictcli import (
    RelativeToRoot,
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


@choice("fast", help="quickly")
class Fast:
    pass


@choice("slow", help="safely")
class Slow:
    patience: int = sub_flag(help="how long to wait", presence="required")


@choice("none", help="no delivery")
class NoDelivery:
    pass


@choice("email", help="an email message")
class Email:
    retries: int = sub_flag(help="how many", presence="required")
    strict: bool = sub_flag(help="fail on a soft bounce", default=False)
    ratio: float = sub_flag(help="the sampling ratio", default=1.0)
    note: str = sub_flag(help="a note", presence="optional")
    cache: str = sub_flag(
        help="where the queue lives",
        default=RelativeToRoot("MYAPP_HOME", "cache", "e.db"),
    )
    speed: Fast | Slow = sub_choice_flag(
        help="how fast", default=Fast(), elect_by="selector-token",
        choices=[Fast, Slow],
    )


def _email(**overrides):
    """An `Email` record with every field the caller did not name declared."""
    fields = dict(retries=1, note=None)
    fields.update(overrides)
    return Email(**fields)


def _app(captured=None):
    app = strictcli.App(
        name="myapp", version="1.0.0", help="test app",
        infra_root={"MYAPP_HOME": "/var/lib/myapp"},
    )

    # `via` is declared FIRST, which is what decides a tie inside one stage.
    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "via", help="delivery channel", presence="required",
        elect_by="selector-token", choices=[NoDelivery, Email],
    )
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(ctx, via: NoDelivery | Email, mode: Profile | AllProfiles):
        if captured is not None:
            captured.update(via=via, mode=mode)

    return app


def _call(app, **kwargs):
    return app.call("run", **kwargs)


def _refusal(**kwargs):
    with pytest.raises(strictcli.InvokeError) as exc:
        _call(_app(), **kwargs)
    return str(exc.value)


def _delivered(**kwargs):
    captured: dict = {}
    _call(_app(captured), **kwargs)
    return captured


# ---------------------------------------------------------------------------
# A scoped flag's value, checked exactly as the flat door checks it
# ---------------------------------------------------------------------------


def test_a_wrong_typed_scoped_field_is_refused():
    """The record carries an int as an int: the numeral's TEXT is not an
    integer here, and nothing re-parses it into one."""
    assert _refusal(via=_email(retries="3"), mode=AllProfiles()) == (
        "--retries: expected integer, got str"
    )


def test_a_null_scoped_field_is_refused():
    """`null` is not a legal value for anything: a required field's presence
    rule would otherwise be answered by a value the declaration forbids."""
    assert _refusal(via=_email(retries=None), mode=AllProfiles()) == (
        "--retries: expected integer, got null"
    )


def test_a_scoped_int_refuses_a_float():
    assert _refusal(via=_email(retries=1.5), mode=AllProfiles()) == (
        "--retries: expected integer, got float"
    )


def test_a_scoped_int_refuses_a_bool():
    """A bool is not a narrow int here, whatever Python's own hierarchy says."""
    assert _refusal(via=_email(retries=True), mode=AllProfiles()) == (
        "--retries: expected integer, got bool"
    )


def test_a_scoped_bool_refuses_a_truthy_int():
    assert _refusal(via=_email(strict=1), mode=AllProfiles()) == (
        "--strict: expected boolean, got int"
    )


def test_a_defaulted_scoped_field_refuses_an_explicit_null():
    """Declaring a default is not declaring optional: only an optional
    declaration says absence is a value."""
    assert _refusal(via=_email(strict=None), mode=AllProfiles()) == (
        "--strict: expected boolean, got null"
    )


def test_a_scoped_float_takes_an_int_and_widens_it():
    """The one widening the declaration allows: an integer IS a float value,
    and it reaches the handler as one."""
    captured = _delivered(via=_email(ratio=2), mode=AllProfiles())
    assert captured["via"].ratio == 2.0
    assert isinstance(captured["via"].ratio, float)


def test_the_caller_s_own_record_is_not_rewritten():
    """The handler receives the record the declaration describes; the object
    the caller built is theirs and is left as they built it."""
    record = _email(ratio=2)
    captured = _delivered(via=record, mode=AllProfiles())
    assert captured["via"].ratio == 2.0
    assert record.ratio == 2
    assert isinstance(record.ratio, int)


# ---------------------------------------------------------------------------
# A member's payload -- the record's `value` field (§24.4, §24.7)
# ---------------------------------------------------------------------------


def test_a_wrong_typed_member_payload_is_refused():
    assert _refusal(via=NoDelivery(), mode=Profile(value=42)) == (
        "--profile: expected string, got int"
    )


def test_a_null_member_payload_is_refused():
    assert _refusal(via=NoDelivery(), mode=Profile(value=None)) == (
        "--profile: expected string, got null"
    )


def test_a_bool_is_not_a_string_payload():
    assert _refusal(via=NoDelivery(), mode=Profile(value=True)) == (
        "--profile: expected string, got bool"
    )


# ---------------------------------------------------------------------------
# Depth: a nested selector's own record is read the same way
# ---------------------------------------------------------------------------


def test_a_nested_scoped_field_is_checked_too():
    assert _refusal(
        via=_email(speed=Slow(patience="soon")), mode=AllProfiles(),
    ) == "--patience: expected integer, got str"


def test_a_nested_record_is_delivered_when_it_checks_out():
    captured = _delivered(via=_email(speed=Slow(patience=2)), mode=AllProfiles())
    assert captured["via"].speed == Slow(patience=2)


def test_a_non_record_where_a_nested_selector_stands_is_refused():
    """A field bound to a nested selector holds an elected record or nothing
    the declaration recognizes -- the same shape refusal the selector's own
    parameter takes at this door."""
    assert _refusal(via=_email(speed=42), mode=AllProfiles()) == (
        "parameter 'speed' for command 'run' must be an instance of a "
        "declared choice of '--speed' (Fast | Slow), got int"
    )


def test_a_record_of_another_selector_is_not_a_choice_of_this_one():
    assert _refusal(via=_email(speed=AllProfiles()), mode=AllProfiles()) == (
        "parameter 'speed' for command 'run' must be an instance of a "
        "declared choice of '--speed' (Fast | Slow), got AllProfiles"
    )


# ---------------------------------------------------------------------------
# The declared defaults a record carries resolve as they do at every door
# ---------------------------------------------------------------------------


def test_an_optional_scoped_field_delivers_absence():
    """An optional field has no dataclass default, so `None` is how a complete
    record spells the absent key the flat door omits."""
    captured = _delivered(via=_email(), mode=AllProfiles())
    assert captured["via"].note is None


def test_a_scoped_relative_to_root_default_resolves(monkeypatch):
    """§18.23 item 237: the marker means inside a scope exactly what it means
    at root scope, and a record door is not a second declaration language."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    captured = _delivered(via=_email(), mode=AllProfiles())
    assert captured["via"].cache == "/var/lib/myapp/cache/e.db"


def test_a_resolved_marker_reports_infra_and_is_not_provided(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    captured = _delivered(via=_email(), mode=AllProfiles())
    sources = getattr(captured["via"], strictcli._RECORD_SOURCES_ATTR)
    assert sources["cache"] == "infra"
    assert strictcli.provided(captured["via"], "cache") is False


def test_a_scoped_marker_reads_the_env_root(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    captured = _delivered(via=_email(), mode=AllProfiles())
    assert captured["via"].cache == "/opt/data/cache/e.db"


def test_a_declared_default_record_is_delivered_as_declared():
    """§24.5: a nested selection nobody elected is complete by declaration, so
    the walk stops at it and it is delivered as the declaration built it."""
    captured = _delivered(via=_email(), mode=AllProfiles())
    assert captured["via"].speed is Email.speed


# ---------------------------------------------------------------------------
# The stage table, over the whole command (§24.3, §18.24 item 243)
# ---------------------------------------------------------------------------


def test_a_later_record_s_shape_outranks_an_earlier_record_s_value():
    """Shape is decided before any value is read, and it is decided over the
    WHOLE command -- not selector by selector."""
    assert _refusal(via=_email(retries="3"), mode="profile") == (
        "parameter 'mode' for command 'run' must be an instance of a "
        "declared choice of '--mode' (Profile | AllProfiles), got str"
    )


def test_a_value_refusal_outranks_a_missing_election():
    """The value phase runs ahead of presence, so a wrong-typed field is what
    the caller hears rather than the selector nobody elected."""
    assert _refusal(via=_email(retries="3")) == (
        "--retries: expected integer, got str"
    )


def test_a_missing_election_is_what_is_left_when_nothing_else_is_wrong():
    assert _refusal(via=_email()) == "one of --profile, --all-profiles is required"


def test_the_value_sweep_runs_in_declaration_order():
    """A keyword argument list has no order of its own: `via` is declared
    first, so its record's refusal is the one reported either way."""
    want = "--retries: expected integer, got str"
    assert _refusal(
        via=_email(retries="3"), mode=Profile(value=42),
    ) == want
    assert _refusal(
        mode=Profile(value=42), via=_email(retries="3"),
    ) == want


def test_a_nested_shape_problem_outranks_a_value_beside_it():
    """Depth does not change the stage: the nested record's shape is still a
    shape fact, so it outranks the wrong-typed field one level up."""
    assert _refusal(via=_email(retries="3", speed=42), mode=AllProfiles()) == (
        "parameter 'speed' for command 'run' must be an instance of a "
        "declared choice of '--speed' (Fast | Slow), got int"
    )
