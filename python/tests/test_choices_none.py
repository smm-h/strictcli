"""Tests for choices/validate exemption of None values.

A None value only arises when a flag or arg was not passed (an unset mutex
flag, or an arg with default=None); a CLI-supplied value is never None.
Choices validation and custom validators must skip None instead of failing
with "invalid value 'None'".
"""

import pytest

import strictcli


# ---------------------------------------------------------------------------
# Optional flags inside a choice's scope: absence is delivered as absence
#
# The mutex-member cases this section used to cover are gone with the construct
# (§21's box): an unelected scope is not delivered at all, so there is no
# per-member value for choices or a validator to see. What survives is the same
# rule one level down -- an OPTIONAL sub-flag delivers None, and neither
# choices validation nor a custom validator runs on it (§24.1, §23.5).
# ---------------------------------------------------------------------------


def _scoped_choices_app(validator=None):
    @strictcli.choice("write", help="write the output")
    class Write:
        format: str = strictcli.sub_flag(
            help="output format", presence="optional",
            choices=[strictcli.Choice("text"), strictcli.Choice("json")],
            validate=validator,
        )

    @strictcli.choice("discard", help="discard the output")
    class Discard:
        pass

    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.choice_flag(
        "mode", help="what to do with the output", presence="required",
        elect_by="selector-token", choices=[Write, Discard],
    )
    def cmd(ctx, mode: Write | Discard):
        print(repr(mode))

    return app


def test_scoped_optional_choices_unset_not_validated():
    """Choices on an unset optional sub-flag must not fire."""
    r = _scoped_choices_app().test(["cmd", "--mode", "write"])
    assert r.exit_code == 0
    assert "Write(format=None)" in r.stdout


def test_scoped_optional_choices_passed_valid():
    r = _scoped_choices_app().test(["cmd", "--mode", "write", "--format", "json"])
    assert r.exit_code == 0
    assert "Write(format='json')" in r.stdout


def test_scoped_optional_choices_passed_invalid():
    r = _scoped_choices_app().test(["cmd", "--mode", "write", "--format", "xml"])
    assert r.exit_code == 1
    assert "--format: invalid value 'xml', must be one of: text, json" in r.stderr


# ---------------------------------------------------------------------------
# Args: default=None (or no default) resolves to None
# ---------------------------------------------------------------------------


def _arg_choices_app(**arg_kwargs):
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        effect="read_only", help="a command",
        args=[strictcli.Arg(
            name="env", help="target env",
            choices=[strictcli.Choice("dev"), strictcli.Choice("staging"), strictcli.Choice("prod")], **arg_kwargs,
        )],
    )
    def cmd(ctx, env=None):
        print(f"env={env}")

    return app


def test_arg_none_default_choices_not_passed():
    """Optional arg with choices, not passed -> succeeds."""
    app = _arg_choices_app(presence="optional")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "env=None" in r.stdout


def test_arg_optional_no_default_choices_not_passed():
    """The same declaration reached through the keyword, not passed."""
    app = _arg_choices_app(presence="optional")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "env=None" in r.stdout


def test_arg_none_default_choices_passed_valid():
    """A valid choice on the optional arg is still accepted."""
    app = _arg_choices_app(presence="optional")
    r = app.test(["cmd", "prod"])
    assert r.exit_code == 0
    assert "env=prod" in r.stdout


def test_arg_none_default_choices_passed_invalid():
    """An invalid choice on the optional arg is still rejected."""
    app = _arg_choices_app(presence="optional")
    r = app.test(["cmd", "local"])
    assert r.exit_code == 1
    assert (
        "argument 'env': invalid value 'local', must be one of: dev, staging, prod"
        in r.stderr
    )


# ---------------------------------------------------------------------------
# Custom validators: not run for None (not-passed) values
# ---------------------------------------------------------------------------


def _name_validator(val):
    if not isinstance(val, str):
        raise ValueError(f"validator received non-string value {val!r}")
    if val == "bad":
        raise ValueError("bad name")


def _scoped_validate_app():
    @strictcli.choice("named", help="address it by name")
    class Named:
        name: str = strictcli.sub_flag(
            help="a name", presence="optional", validate=_name_validator,
        )

    @strictcli.choice("numbered", help="address it by id")
    class Numbered:
        id: str = strictcli.sub_flag(help="an id", presence="optional")

    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.choice_flag(
        "by", help="how to address it", presence="required",
        elect_by="selector-token", choices=[Named, Numbered],
    )
    def cmd(ctx, by: Named | Numbered):
        print(repr(by))

    return app


def test_scoped_optional_validate_unset_not_called():
    """A custom validator must not run for an unset optional sub-flag."""
    r = _scoped_validate_app().test(["cmd", "--by", "named"])
    assert r.exit_code == 0
    assert "Named(name=None)" in r.stdout


def test_scoped_optional_validate_passed_still_runs():
    """A passed value is still validated."""
    r = _scoped_validate_app().test(["cmd", "--by", "named", "--name", "bad"])
    assert r.exit_code == 1
    assert "--name: bad name" in r.stderr
