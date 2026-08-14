"""The scoped-selector construct (contract §24) and its message family (§12.13).

A choice is a declaration scope. A selector is a flag that elects exactly one
of its declared choices, and each choice owns the flags that exist only while
it is elected. `notify send --via email --subject hi` parses; `notify send
--via sms --subject hi` is a parse error the declaration produces on its own,
naming the flag, the choice that owns it and the choice that was elected --
never "unknown flag".

Every assertion that quotes a message quotes a PINNED template. Where a
template's sentence carries a per-language spelling, the sentence is
byte-identical across the three implementations and only the spelling inside it
is Python's (§12.13, reusing §12.12's mechanism).
"""

import json

import pytest

import strictcli
from strictcli import (
    Choice, choice, choice_flag, member_value, sub_choice_flag, sub_flag,
)


# ---------------------------------------------------------------------------
# The reference declaration of §24.12
# ---------------------------------------------------------------------------


@choice("email", help="deliver the notification as an email message")
class Email:
    subject: str = sub_flag(help="subject line of the message", presence="required")
    recipient: str = sub_flag(help="destination email address", presence="required")


@choice("sms", help="deliver the notification as a text message")
class Sms:
    phone_number: str = sub_flag(
        help="destination number in E.164 form", presence="required",
    )


@choice("webhook", help="post the notification to a URL")
class Webhook:
    url: str = sub_flag(help="the endpoint", presence="required")
    retries: int = sub_flag(help="how many times to retry", default=3)


Via = Email | Sms | Webhook


def _notify(**selector_kwargs):
    kwargs = {
        "help": "delivery channel",
        "short": "v",
        "presence": "required",
        "elect_by": "selector-token",
        "choices": [Email, Sms, Webhook],
    }
    kwargs.update(selector_kwargs)
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    @app.command(
        "send", help="send one notification through exactly one channel",
        effect="mutating",
    )
    @choice_flag("via", **kwargs)
    @strictcli.flag("dry", type=bool, help="print what would be sent", default=False)
    def send(ctx, via: Via, dry):
        print(repr(via))
        return 0

    return app


# ---------------------------------------------------------------------------
# §24.1 -- election, scopes, delivery
# ---------------------------------------------------------------------------


def test_a_selector_delivers_one_tagged_record_under_its_own_key():
    r = _notify().test(
        ["send", "--via", "email", "--subject", "hi", "--recipient", "a@b"],
    )
    assert r.exit_code == 0
    assert "Email(subject='hi', recipient='a@b')" in r.stdout


def test_a_sub_flag_is_never_a_top_level_handler_argument():
    """§24.1: the only key a selector adds is its own."""
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    with pytest.raises(ValueError) as exc:

        @app.command("send", help="send one", effect="mutating")
        @choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Email, Sms, Webhook],
        )
        def send(ctx, via: Via, subject):
            pass

    assert str(exc.value) == (
        'command "send": handler has extra parameter "subject" not matching '
        "any flag or arg"
    )


def test_order_independence():
    """§24.1: nothing is interpreted until every token is collected."""
    a = _notify().test(
        ["send", "--via", "email", "--subject", "hi", "--recipient", "a@b"],
    )
    b = _notify().test(
        ["send", "--subject", "hi", "--recipient", "a@b", "--via", "email"],
    )
    assert a.exit_code == b.exit_code == 0
    assert a.stdout == b.stdout


def test_the_inline_value_form_elects():
    r = _notify().test(["send", "--via=sms", "--phone-number=+15550100"])
    assert r.exit_code == 0
    assert "Sms(phone_number='+15550100')" in r.stdout


def test_a_short_elects():
    r = _notify().test(["send", "-v", "sms", "--phone-number", "+15550100"])
    assert r.exit_code == 0


def test_a_scoped_default_is_delivered_as_a_present_field():
    r = _notify().test(["send", "--via", "webhook", "--url", "http://x"])
    assert r.exit_code == 0
    assert "Webhook(url='http://x', retries=3)" in r.stdout


# ---------------------------------------------------------------------------
# §24.3 -- the out-of-scope error, and its three "why" clauses (§12.13)
# ---------------------------------------------------------------------------


def test_out_of_scope_names_the_flag_its_owner_and_the_elected_choice():
    r = _notify().test(["send", "--via", "sms", "--subject", "hi"])
    assert r.exit_code == 1
    assert (
        "error: flag '--subject' is only valid under '--via email', but "
        "'--via email' was elected\n"
    ) not in r.stderr
    assert (
        "error: flag '--subject' is only valid under '--via email', but "
        "'--via sms' was elected\n"
    ) in r.stderr


def test_out_of_scope_when_a_required_selector_elected_nothing():
    """The precedence rule names the token the reader actually typed (§24.3)."""
    r = _notify().test(["send", "--subject", "hi"])
    assert r.exit_code == 1
    assert (
        "error: flag '--subject' is only valid under '--via email', but "
        "'--via' was not provided\n"
    ) in r.stderr


def test_out_of_scope_under_a_member_spelled_selector_that_elected_nothing():
    @choice("work", help="the work profile")
    class Work:
        create_missing: bool = sub_flag(help="create it", default=False)

    @choice("all-profiles", help="every profile")
    class AllProfiles:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Work, AllProfiles],
    )
    def run(ctx, mode: Work | AllProfiles):
        pass

    r = app.test(["run", "--create-missing"])
    assert r.exit_code == 1
    assert (
        "error: flag '--create-missing' is only valid under '--work', but "
        "none of --work, --all-profiles was elected\n"
    ) in r.stderr


def test_a_name_reused_by_sibling_scopes_names_both_owners():
    """`<owners>` is one or more scope paths in declaration order (§12.13)."""
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required")

    @choice("b", help="mode b")
    class B:
        target: str = sub_flag(help="the target", presence="required")

    @choice("c", help="mode c")
    class C:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B, C],
    )
    def run(ctx, mode: A | B | C):
        pass

    r = app.test(["run", "--mode", "c", "--target", "x"])
    assert r.exit_code == 1
    assert (
        "error: flag '--target' is only valid under '--mode a' or '--mode b', "
        "but '--mode c' was elected\n"
    ) in r.stderr


def test_the_precedence_rule_reports_scope_before_presence():
    """election -> scope -> value -> presence (§24.3).

    `--via sms --subject hi` says *--subject belongs to email*, never
    *--phone-number is required*: the spelling mistake is reported before its
    consequence.
    """
    r = _notify().test(["send", "--via", "sms", "--subject", "hi"])
    assert r.exit_code == 1
    assert "--phone-number" not in r.stderr
    assert "is only valid under" in r.stderr


def test_the_precedence_rule_reports_scope_before_a_coercion_failure():
    r = _notify().test(
        ["send", "--via", "email", "--url", "u", "--retries", "not-a-number",
         "--subject", "hi", "--recipient", "a@b"],
    )
    assert r.exit_code == 1
    assert "is only valid under" in r.stderr


def test_a_selector_elected_more_than_once_is_refused():
    """Last-wins is right for a plain flag and wrong for an election: it would
    discard a whole scope with the value (§12.13)."""
    r = _notify().test(["send", "--via", "email", "--via", "sms"])
    assert r.exit_code == 1
    assert (
        "error: --via: elected more than once, as 'email' and 'sms'\n"
    ) in r.stderr


def test_a_value_naming_no_declared_choice_reuses_the_existing_sentence():
    """No new template: a migrated declaration must not change the bytes a
    user reads for a condition that did not change (§12.13's reuse table)."""
    r = _notify().test(["send", "--via", "carrier-pigeon"])
    assert r.exit_code == 1
    assert (
        "error: --via: invalid value 'carrier-pigeon', must be one of: "
        "email, sms, webhook\n"
    ) in r.stderr


def test_a_required_selector_alone_reuses_the_required_flag_sentence():
    r = _notify().test(["send"])
    assert r.exit_code == 1
    assert "error: flag '--via' is required\n" in r.stderr


def test_a_required_sub_flag_carries_the_scope_suffix():
    r = _notify().test(["send", "--via", "sms"])
    assert r.exit_code == 1
    assert "error: flag '--phone-number' is required under '--via sms'\n" in r.stderr


# ---------------------------------------------------------------------------
# §24.1 -- recursion, to unlimited depth
# ---------------------------------------------------------------------------


@choice("feature", help="a user-facing feature")
class Feature:
    headline: str = sub_flag(help="the headline", presence="required")


@choice("fix", help="a user-facing fix")
class Fix:
    symptom: str = sub_flag(help="the visible symptom", presence="required")


@choice("user-facing", help="a change users read about")
class UserFacing:
    type: Feature | Fix = sub_choice_flag(
        help="the kind of change", presence="required",
        elect_by="selector-token", choices=[Feature, Fix],
    )


@choice("internal", help="a change nobody upgrades for")
class Internal:
    pass


def _changelog_app():
    app = strictcli.App(name="log", version="1.0.0", help="changelogs")

    @app.command("add", effect="mutating", help="add an entry")
    @choice_flag(
        "visibility", help="who the entry is for", presence="required",
        elect_by="selector-token", choices=[UserFacing, Internal],
    )
    def add(ctx, visibility: UserFacing | Internal):
        print(repr(visibility))

    return app


def test_recursion_delivers_a_nested_record():
    r = _changelog_app().test(
        ["add", "--visibility", "user-facing", "--type", "feature",
         "--headline", "selectors"],
    )
    assert r.exit_code == 0
    assert "UserFacing(type=Feature(headline='selectors'))" in r.stdout


def test_required_exactly_when_user_facing_is_where_the_declaration_sits():
    """§24.1: a rule a handler used to enforce becomes a scope."""
    r = _changelog_app().test(["add", "--visibility", "internal"])
    assert r.exit_code == 0
    assert "Internal()" in r.stdout


def test_the_scope_path_renders_every_segment_outermost_first():
    r = _changelog_app().test(
        ["add", "--visibility", "user-facing", "--type", "feature"],
    )
    assert r.exit_code == 1
    assert (
        "error: flag '--headline' is required under "
        "'--visibility user-facing --type feature'\n"
    ) in r.stderr


def test_blame_the_outermost_unsatisfied_election():
    """A flag two levels down whose OUTER election failed blames the outer one:
    that is the token the reader would have to change (§24.3)."""
    r = _changelog_app().test(["add", "--visibility", "internal", "--headline", "x"])
    assert r.exit_code == 1
    assert (
        "error: flag '--headline' is only valid under "
        "'--visibility user-facing --type feature', but "
        "'--visibility internal' was elected\n"
    ) in r.stderr


# ---------------------------------------------------------------------------
# §24.5 -- presence on a selector
# ---------------------------------------------------------------------------


def test_optional_is_refused_with_a_redirect_that_names_the_remedy():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="optional",
            elect_by="selector-token", choices=[Email, Sms],
        )
    assert str(exc.value) == (
        'Flag "via": a choice flag cannot declare presence="optional": an '
        "absent selection is a choice nobody named, so name it as a choice of "
        "its own"
    )


def test_a_defaulted_selection_is_complete_and_delivered_as_declared():
    app = _notify(presence=strictcli._MISSING, default=Sms(phone_number="+15550100"))
    r = app.test(["send"])
    assert r.exit_code == 0
    assert "Sms(phone_number='+15550100')" in r.stdout


def test_an_incomplete_defaulted_selection_is_unconstructable_in_python():
    """§24.5: a frozen dataclass cannot be constructed without its required
    fields, so there is nothing to check and no error to raise. This is why
    Go's and TypeScript's `errSelectorDefaultIncomplete` is Python-EXCLUDED."""
    with pytest.raises(TypeError):
        Sms()


def test_electing_on_the_command_line_never_borrows_the_defaults_values():
    app = _notify(presence=strictcli._MISSING, default=Sms(phone_number="+15550100"))
    r = app.test(["send", "--via", "sms"])
    assert r.exit_code == 1
    assert "error: flag '--phone-number' is required under '--via sms'\n" in r.stderr


def test_a_default_naming_no_declared_choice_is_refused():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", default="email",
            elect_by="selector-token", choices=[Email, Sms],
        )
    assert str(exc.value) == (
        'Flag "via": default=email names no declared choice: must be one '
        "of: email, sms"
    )


# ---------------------------------------------------------------------------
# §24.6 -- sources, conditional bindings, and the origin clauses
# ---------------------------------------------------------------------------


@choice("email", help="deliver by email")
class AmbientEmail:
    subject: str = sub_flag(
        help="the subject", presence="required", env="NOTIFY_SUBJECT",
        prefixed=False,
    )


@choice("sms", help="deliver by text")
class AmbientSms:
    phone_number: str = sub_flag(help="the number", presence="required")


def _ambient_app():
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    @app.command("send", effect="mutating", help="send one")
    @choice_flag(
        "via", help="delivery channel", presence="required",
        elect_by="selector-token", choices=[AmbientEmail, AmbientSms],
        env="NOTIFY_VIA",
    )
    def send(ctx, via: AmbientEmail | AmbientSms):
        print(repr(via))

    return app


def test_a_token_spelled_selector_elects_from_env(monkeypatch):
    monkeypatch.setenv("NOTIFY_VIA", "email")
    monkeypatch.setenv("NOTIFY_SUBJECT", "hi")
    r = _ambient_app().test(["send"])
    assert r.exit_code == 0
    assert "subject='hi'" in r.stdout


def test_an_ambient_election_names_itself_in_every_message_it_causes(monkeypatch):
    """§24.6: otherwise a refusal blames a command line that does not contain
    the cause. §12.13's origin suffix composes after the scope suffix."""
    monkeypatch.setenv("NOTIFY_VIA", "sms")
    r = _ambient_app().test(["send"])
    assert r.exit_code == 1
    assert (
        "error: flag '--phone-number' is required under '--via sms' "
        "(elected from env var 'NOTIFY_VIA')\n"
    ) in r.stderr


def test_an_ambient_election_names_itself_in_a_scope_error(monkeypatch):
    monkeypatch.setenv("NOTIFY_VIA", "sms")
    r = _ambient_app().test(["send", "--subject", "hi"])
    assert r.exit_code == 1
    assert (
        "error: flag '--subject' is only valid under '--via email', but "
        "'--via sms' was elected from env var 'NOTIFY_VIA'\n"
    ) in r.stderr


def test_a_command_line_election_produces_the_empty_origin_suffix():
    """§12.13 item 212: the wrapper exists exactly when the clause it wraps
    does -- never a bare `(elected)`."""
    r = _notify().test(["send", "--via", "sms"])
    assert "(elected" not in r.stderr


def test_a_default_election_names_itself():
    app = _notify(presence=strictcli._MISSING, default=Email(
        subject="hi", recipient="a@b",
    ))
    r = app.test(["send", "--phone-number", "+1"])
    assert r.exit_code == 1
    assert (
        "error: flag '--phone-number' is only valid under '--via sms', but "
        "'--via email' was elected by default\n"
    ) in r.stderr


def test_a_skipped_env_binding_is_named_under_verbose(monkeypatch):
    """§24.6: every skipped binding is named, one line per binding, at debug
    level -- hidden by default, shown by --verbose."""
    monkeypatch.setenv("NOTIFY_SUBJECT", "hi")
    r = _ambient_app().test(["send", "--via", "sms", "--phone-number", "+1"])
    assert r.exit_code == 0
    assert "not consulted" not in r.stdout

    r = _ambient_app().test(
        ["send", "--verbose", "--via", "sms", "--phone-number", "+1"],
    )
    assert r.exit_code == 0
    assert (
        "not consulted: env var 'NOTIFY_SUBJECT' binds flag '--subject' under "
        "'--via email', which was not elected\n"
    ) in r.stdout


def test_a_skipped_config_binding_is_named_under_verbose(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"subject": "from-config"}\n')

    @choice("email", help="deliver by email")
    class E:
        subject: str = sub_flag(help="the subject", presence="required")

    @choice("sms", help="deliver by text")
    class S:
        phone_number: str = sub_flag(help="the number", presence="required")

    app = strictcli.App(
        name="notify", version="1.0.0", help="notifier", config=True,
    )

    @app.command("send", effect="mutating", help="send one")
    @choice_flag(
        "via", help="delivery channel", presence="required",
        elect_by="selector-token", choices=[E, S],
    )
    def send(ctx, via: E | S):
        print(repr(via))

    r = app.test(
        ["--config", str(cfg), "send", "--verbose", "--via", "sms",
         "--phone-number", "+1"],
    )
    assert r.exit_code == 0
    assert (
        "not consulted: config key 'subject' binds flag '--subject' under "
        "'--via email', which was not elected\n"
    ) in r.stdout

    # And when the scope IS elected, the binding is consulted.
    r = app.test(["--config", str(cfg), "send", "--via", "email"])
    assert r.exit_code == 0
    assert "subject='from-config'" in r.stdout


def test_the_skipped_binding_lines_ride_machine_modes_diagnostics(monkeypatch):
    monkeypatch.setenv("NOTIFY_SUBJECT", "hi")
    r = _ambient_app().test(
        ["send", "--json", "--via", "sms", "--phone-number", "+1"],
    )
    envelope = json.loads(r.stdout.splitlines()[-1])
    assert {
        "level": "debug",
        "message": (
            "not consulted: env var 'NOTIFY_SUBJECT' binds flag '--subject' "
            "under '--via email', which was not elected"
        ),
    } in envelope["diagnostics"]


# ---------------------------------------------------------------------------
# §24.7 -- names, reserved keys, positionals and depth
# ---------------------------------------------------------------------------


def test_the_reserved_name_choice():
    @choice("email", help="deliver by email")
    class E:
        choice: str = sub_flag(help="nope", presence="required")

    @choice("sms", help="deliver by text")
    class S:
        pass

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[E, S],
        )
    assert str(exc.value) == (
        'Choice "email" of "via": flag name \'choice\' is reserved by the '
        "framework: it tags the delivered record"
    )


def test_the_reserved_name_value():
    @choice("email", help="deliver by email")
    class E:
        value: str = sub_flag(help="nope", presence="required")

    @choice("sms", help="deliver by text")
    class S:
        pass

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[E, S],
        )
    assert str(exc.value) == (
        'Choice "email" of "via": flag name \'value\' is reserved by the '
        "framework: it carries a member-spelled choice's own payload"
    )


def test_a_positional_cannot_be_declared_inside_a_scope():
    @choice("email", help="deliver by email")
    class E:
        target: str = strictcli.Arg(
            name="target", help="the target", presence="required",
        )

    @choice("sms", help="deliver by text")
    class S:
        pass

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[E, S],
        )
    assert str(exc.value) == (
        'Choice "email" of "via": positional args cannot be declared inside a '
        "choice scope: a positional's meaning would depend on an election that "
        "may be typed after it"
    )


def test_a_scoped_flag_may_not_reuse_a_command_level_flags_name():
    @choice("email", help="deliver by email")
    class E:
        dry: bool = sub_flag(help="nope", default=False)

    @choice("sms", help="deliver by text")
    class S:
        pass

    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    with pytest.raises(ValueError) as exc:

        @app.command("send", effect="mutating", help="send one")
        @choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[E, S],
        )
        @strictcli.flag("dry", type=bool, help="a dry run", default=False)
        def send(ctx, via: E | S, dry):
            pass

    assert str(exc.value) == (
        'Choice "email" of "via": flag \'--dry\' collides with a '
        "command-level flag of the same name: the scoped one could never be "
        "reached"
    )


def test_a_scoped_flag_may_not_reuse_the_selectors_own_name():
    @choice("email", help="deliver by email")
    class E:
        via: str = sub_flag(help="nope", presence="required")

    @choice("sms", help="deliver by text")
    class S:
        pass

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[E, S],
        )
    assert str(exc.value) == (
        'Choice "email" of "via": flag \'--via\' collides with the choice '
        "flag's own name"
    )


def test_sibling_scopes_may_reuse_a_name_with_an_identical_value_shape():
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required")

    @choice("b", help="mode b")
    class B:
        target: str = sub_flag(help="the target", default="x")

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B],
    )
    def run(ctx, mode: A | B):
        print(repr(mode))

    assert app.test(["run", "--mode", "a", "--target", "t"]).exit_code == 0
    assert app.test(["run", "--mode", "b"]).exit_code == 0


def test_sibling_scopes_reusing_a_name_with_a_different_value_shape():
    """Tokenizing '--x' cannot wait for an election (§24.3, §24.7)."""
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required")

    @choice("b", help="mode b")
    class B:
        target: bool = sub_flag(help="the target", default=False)

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="selector-token", choices=[A, B],
        )
    assert str(exc.value) == (
        'Flag "mode": flag \'--target\' is declared by choices "a" and "b" '
        "with different value shapes: sibling scopes may reuse a name only "
        "with an identical type and arity, because tokenizing '--target' "
        "cannot wait for an election"
    )


def test_sibling_scopes_reusing_a_name_with_a_different_arity():
    """The template is widened, not twinned (§18.18 item 208)."""
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required")

    @choice("b", help="mode b")
    class B:
        target: list[str] = sub_flag(help="the targets", default=[], unique=False)

    with pytest.raises(ValueError) as exc:
        choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="selector-token", choices=[A, B],
        )
    assert "with different value shapes" in str(exc.value)


def test_simultaneously_electable_scopes_may_not_reuse_a_name_at_all():
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required")

    @choice("b", help="mode b")
    class B:
        pass

    @choice("x", help="shape x")
    class X:
        target: str = sub_flag(help="the target", presence="required")

    @choice("y", help="shape y")
    class Y:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    with pytest.raises(ValueError) as exc:

        @app.command("run", effect="read_only", help="run it")
        @choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="selector-token", choices=[A, B],
        )
        @choice_flag(
            "shape", help="the shape", presence="required",
            elect_by="selector-token", choices=[X, Y],
        )
        def run(ctx, mode: A | B, shape: X | Y):
            pass

    assert str(exc.value) == (
        'command "run": flag \'--target\' is declared under \'--mode a\' and '
        "under '--shape x', which can be elected at the same time: "
        "simultaneously electable scopes may not reuse a flag name"
    )


def test_a_scope_may_not_reuse_a_name_declared_by_one_of_its_ancestors():
    @choice("inner-a", help="inner a")
    class InnerA:
        target: str = sub_flag(help="the target", presence="required")

    @choice("inner-b", help="inner b")
    class InnerB:
        pass

    @choice("outer", help="the outer choice")
    class Outer:
        target: str = sub_flag(help="the target", presence="required")
        nested: InnerA | InnerB = sub_choice_flag(
            help="the nested selector", presence="required",
            elect_by="selector-token", choices=[InnerA, InnerB],
        )

    @choice("other", help="the other choice")
    class Other:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    with pytest.raises(ValueError) as exc:

        @app.command("run", effect="read_only", help="run it")
        @choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="selector-token", choices=[Outer, Other],
        )
        def run(ctx, mode: Outer | Other):
            pass

    assert "which can be elected at the same time" in str(exc.value)


def test_shorts_are_claimed_across_every_simultaneously_live_scope():
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required", short="t")

    @choice("b", help="mode b")
    class B:
        pass

    @choice("x", help="shape x")
    class X:
        tail: str = sub_flag(help="the tail", presence="required", short="t")

    @choice("y", help="shape y")
    class Y:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    with pytest.raises(ValueError) as exc:

        @app.command("run", effect="read_only", help="run it")
        @choice_flag(
            "mode", help="the mode", presence="required",
            elect_by="selector-token", choices=[A, B],
        )
        @choice_flag(
            "shape", help="the shape", presence="required",
            elect_by="selector-token", choices=[X, Y],
        )
        def run(ctx, mode: A | B, shape: X | Y):
            pass

    assert str(exc.value) == (
        'command "run": short \'-t\' is claimed by \'--target\' and '
        "'--tail', which can be elected at the same time"
    )


def test_sibling_scopes_may_reuse_a_short():
    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required", short="t")

    @choice("b", help="mode b")
    class B:
        tail: str = sub_flag(help="the tail", presence="required", short="t")

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B],
    )
    def run(ctx, mode: A | B):
        print(repr(mode))

    assert app.test(["run", "--mode", "a", "-t", "x"]).exit_code == 0
    assert app.test(["run", "--mode", "b", "-t", "y"]).exit_code == 0


# ---------------------------------------------------------------------------
# §12.13 -- the remaining registration guards
# ---------------------------------------------------------------------------


def test_a_choice_flag_must_declare_at_least_two_choices():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Email],
        )
    assert str(exc.value) == (
        'Flag "via": a choice flag must declare at least two choices'
    )


def test_a_duplicate_choice_name_is_refused():
    Twin = choice("email", help="a twin")(type("Twin", (), {}))
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Email, Twin],
        )
    assert str(exc.value) == 'Flag "via": choice "email" is declared twice'


def test_a_choice_must_carry_help():
    Empty = choice("empty", help="")(type("Empty", (), {}))
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Empty, Sms],
        )
    assert str(exc.value) == 'Choice "empty" of "via": help text is required'


def test_elect_by_is_mandatory_with_no_default():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            choices=[Email, Sms],
        )
    assert str(exc.value) == (
        'Flag "via": elect_by is undeclared: declare '
        'elect_by="selector-token" or elect_by="member-flags"'
    )


def test_an_unknown_elect_by_is_refused():
    with pytest.raises(ValueError) as exc:
        choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="tokens", choices=[Email, Sms],
        )
    assert str(exc.value) == (
        'Flag "via": elect_by must be "selector-token" or "member-flags", '
        "got 'tokens'"
    )


# ---------------------------------------------------------------------------
# §12.13 / §24.12 -- the Python-only handler-annotation family
# ---------------------------------------------------------------------------


def test_the_handler_parameter_must_annotate_exactly_the_declared_union():
    """Without the check a developer could annotate one choice class and
    `assert_never` would pass the type checker while skipping branches."""
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    with pytest.raises(ValueError) as exc:

        @app.command("send", effect="mutating", help="send one")
        @choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Email, Sms],
        )
        def send(ctx, via: Email):
            pass

    assert str(exc.value) == (
        'command "send": handler parameter \'via\' is bound to choice flag '
        "'--via' and must be annotated Email | Sms, got Email"
    )


def test_an_unannotated_handler_parameter_is_refused():
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    with pytest.raises(ValueError) as exc:

        @app.command("send", effect="mutating", help="send one")
        @choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Email, Sms],
        )
        def send(ctx, via):
            pass

    assert str(exc.value) == (
        'command "send": handler parameter \'via\' is bound to choice flag '
        "'--via' and must be annotated Email | Sms, got nothing"
    )


def test_a_kwargs_handler_is_banned_on_a_selector_carrying_command():
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    with pytest.raises(ValueError) as exc:

        @app.command(
            "send", effect="mutating", help="send one",
            forwarding=strictcli.Forwarding(reason="a wrapper"),
        )
        @choice_flag(
            "via", help="delivery channel", presence="required",
            elect_by="selector-token", choices=[Email, Sms],
        )
        def send(ctx, **kwargs):
            pass

    assert str(exc.value) == (
        'command "send": a command declaring a choice flag cannot use a '
        "**kwargs handler: the elected value must reach a named, annotated "
        "parameter"
    )


def test_a_type_checking_only_annotation_is_a_registration_error():
    """A name importable only under TYPE_CHECKING is a registration error
    naming it, rather than a NameError at import time (§24.12)."""
    app = strictcli.App(name="notify", version="1.0.0", help="notifier")

    def send(ctx, via):
        pass

    send.__annotations__["via"] = "NotImportedAtRuntime | Sms"

    with pytest.raises(ValueError) as exc:
        app.command("send", effect="mutating", help="send one")(
            choice_flag(
                "via", help="delivery channel", presence="required",
                elect_by="selector-token", choices=[Email, Sms],
            )(send),
        )

    assert str(exc.value) == (
        'command "send": handler parameter \'via\' annotation '
        "NotImportedAtRuntime | Sms cannot be resolved at registration: a "
        "choice class must be importable at run time, not only under "
        "TYPE_CHECKING"
    )


# ---------------------------------------------------------------------------
# §24.10 -- help rendering
# ---------------------------------------------------------------------------


def test_the_selector_block_layout():
    r = _notify().test(["send", "--help"])
    assert r.exit_code == 0
    assert r.stdout == (
        "notify send -- send one notification through exactly one channel\n"
        "\n"
        "Flags:\n"
        "  --via, -v <choice>          delivery channel [required]\n"
        "    email                     deliver the notification as an email "
        "message\n"
        "      --subject <str>         subject line of the message [required]\n"
        "      --recipient <str>       destination email address [required]\n"
        "    sms                       deliver the notification as a text "
        "message\n"
        "      --phone-number <str>    destination number in E.164 form "
        "[required]\n"
        "    webhook                   post the notification to a URL\n"
        "      --url <str>             the endpoint [required]\n"
        "      --retries <int>         how many times to retry [default: 3]\n"
        "  --dry, --no-dry             print what would be sent [default: "
        "false]\n"
    )


def test_recursion_adds_two_columns_per_level():
    r = _changelog_app().test(["add", "--help"])
    assert r.exit_code == 0
    assert (
        "  --visibility <choice>       who the entry is for [required]\n"
        "    user-facing               a change users read about\n"
        "      --type <choice>         the kind of change [required]\n"
        "        feature               a user-facing feature\n"
        "          --headline <str>    the headline [required]\n"
        "        fix                   a user-facing fix\n"
        "          --symptom <str>     the visible symptom [required]\n"
        "    internal                  a change nobody upgrades for\n"
    ) in r.stdout


def test_a_defaulted_selector_renders_its_complete_elected_value():
    app = _notify(presence=strictcli._MISSING, default=Sms(phone_number="+15550100"))
    r = app.test(["send", "--help"])
    assert "[default: sms (phone-number=+15550100)]" in r.stdout


# ---------------------------------------------------------------------------
# §24.11 -- schema, MCP and the machine boundary
# ---------------------------------------------------------------------------


def test_the_mcp_projection_is_flatten_plus_a_description_map():
    app = _notify()
    schema = app.json_schema("send")
    assert schema["properties"]["via"] == {
        "type": "string",
        "enum": ["email", "sms", "webhook"],
        "description": "delivery channel",
    }
    # Every scoped flag is a top-level property, and NEVER in `required`.
    assert schema["properties"]["subject"]["type"] == "string"
    assert schema["properties"]["retries"]["type"] == "integer"
    assert schema["required"] == ["via"]


def test_the_scope_map_rides_the_tool_description():
    app = _notify()
    tool = next(t for t in app.as_tools() if t.name == "send")
    assert tool.description == (
        "send one notification through exactly one channel\n"
        "\n"
        "Scoped parameters (enforced at call time):\n"
        "  via=email: subject (required), recipient (required)\n"
        "  via=sms: phone_number (required)\n"
        "  via=webhook: url (required), retries (default: 3)"
    )


def test_an_empty_scope_renders_no_parameters():
    app = _changelog_app()
    tool = next(t for t in app.as_tools() if t.name == "add")
    assert (
        "  visibility=user-facing: type (required)\n"
        "  visibility=user-facing type=feature: headline (required)\n"
        "  visibility=user-facing type=fix: symptom (required)\n"
        "  visibility=internal: (no parameters)"
    ) in tool.description


def test_a_member_spelled_selector_projects_identically():
    """Tokenization is a command-line fact and there are no tokens at this
    boundary (§24.11)."""
    @choice("profile", help="one named profile")
    class Profile:
        value: str = member_value(help="the profile name")

    @choice("all-profiles", help="every profile")
    class AllProfiles:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="which profiles", presence="required",
        elect_by="member-flags", choices=[Profile, AllProfiles],
    )
    def run(ctx, mode: Profile | AllProfiles):
        print(repr(mode))

    schema = app.json_schema("run")
    assert schema["properties"]["mode"] == {
        "type": "string",
        "enum": ["profile", "all-profiles"],
        "description": "which profiles",
    }
    assert schema["properties"]["profile"] == {
        "type": "string",
        "description": "the profile name",
    }
    assert schema["required"] == ["mode"]


def test_the_flat_form_is_converted_through_the_same_machinery():
    app = _notify()
    result = app._call_with_kwargs(
        "send", {"via": "email", "subject": "hi", "recipient": "a@b"},
        approve_consequential=False, flat=True,
    )
    assert result == 0


def test_a_wrong_flat_combination_is_refused_with_the_clis_own_sentence():
    app = _notify()
    with pytest.raises(strictcli.InvokeError) as exc:
        app._call_with_kwargs(
            "send", {"via": "sms", "subject": "hi"},
            approve_consequential=False, flat=True,
        )
    assert str(exc.value) == (
        "flag '--subject' is only valid under '--via email', but "
        "'--via sms' was elected"
    )


def test_the_dumped_schema_publishes_the_selector_nested(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "testproject"\n')
    monkeypatch.chdir(tmp_path)
    _notify().test(["--dump-schema"])
    data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
    sel = data["commands"]["send"]["selectors"][0]
    assert sel["name"] == "via"
    assert sel["presence"] == "required"
    assert sel["elect_by"] == "selector-token"
    assert sel["short"] == "v"
    assert [c["name"] for c in sel["choices"]] == ["email", "sms", "webhook"]
    assert sel["choices"][2]["flags"][1] == {
        "name": "retries",
        "type": "int",
        "help": "how many times to retry",
        "presence": "default",
        "default": 3,
    }


# ---------------------------------------------------------------------------
# §24.3 -- what the construct does NOT weaken, re-verified per surface
# ---------------------------------------------------------------------------


def test_the_reserved_quartet_pre_scan_still_runs_anywhere_in_argv():
    r = _notify().test(
        ["send", "--via", "email", "--subject", "hi", "--recipient", "a@b",
         "--dry-run"],
    )
    assert r.exit_code == 0


def test_a_bare_double_dash_is_still_a_boundary():
    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @choice("a", help="mode a")
    class A:
        target: str = sub_flag(help="the target", presence="required")

    @choice("b", help="mode b")
    class B:
        pass

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B],
    )
    @strictcli.arg("rest", help="a positional", presence="optional")
    def run(ctx, mode: A | B, rest=None):
        print(f"{mode!r} rest={rest!r}")

    r = app.test(["run", "--mode", "b", "--", "--target"])
    assert r.exit_code == 0
    assert "rest='--target'" in r.stdout


def test_a_scoped_bool_negates():
    @choice("a", help="mode a")
    class A:
        loud: bool = sub_flag(help="be loud", default=True)

    @choice("b", help="mode b")
    class B:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B],
    )
    def run(ctx, mode: A | B):
        print(repr(mode))

    assert "A(loud=False)" in app.test(["run", "--mode", "a", "--no-loud"]).stdout
    assert "A(loud=True)" in app.test(["run", "--mode", "a"]).stdout


def test_a_repeatable_scoped_flag():
    @choice("a", help="mode a")
    class A:
        tag: list[str] = sub_flag(help="tags", default=[], unique=False)

    @choice("b", help="mode b")
    class B:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B],
    )
    def run(ctx, mode: A | B):
        print(repr(mode))

    r = app.test(["run", "--mode", "a", "--tag", "x", "--tag", "y"])
    assert r.exit_code == 0
    assert "A(tag=['x', 'y'])" in r.stdout


def test_an_at_prefix_resolves_on_a_scoped_string_flag(tmp_path):
    payload = tmp_path / "body.txt"
    payload.write_text("hello from a file")

    @choice("a", help="mode a")
    class A:
        body: str = sub_flag(help="the body", presence="required")

    @choice("b", help="mode b")
    class B:
        pass

    app = strictcli.App(name="myapp", version="1.0.0", help="test app")

    @app.command("run", effect="read_only", help="run it")
    @choice_flag(
        "mode", help="the mode", presence="required",
        elect_by="selector-token", choices=[A, B],
    )
    def run(ctx, mode: A | B):
        print(repr(mode))

    r = app.test(["run", "--mode", "a", "--body", f"@{payload}"])
    assert r.exit_code == 0
    assert "A(body='hello from a file')" in r.stdout


def test_hermetic_suppresses_a_scoped_env_binding(monkeypatch):
    monkeypatch.setenv("NOTIFY_SUBJECT", "hi")
    r = _ambient_app().test(["--hermetic", "send", "--via", "email"])
    assert r.exit_code == 1
    assert "error: flag '--subject' is required under '--via email'\n" in r.stderr
