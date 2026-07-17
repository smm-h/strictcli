"""Tests for choices/validate exemption of None values.

A None value only arises when a flag or arg was not passed (an unset mutex
flag, or an arg with default=None); a CLI-supplied value is never None.
Choices validation and custom validators must skip None instead of failing
with "invalid value 'None'".
"""

import pytest

import strictcli


# ---------------------------------------------------------------------------
# Mutex flags: the unset member resolves to None
# ---------------------------------------------------------------------------


def _mutex_choices_app():
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(
                name="format", type=str, help="output format",
                default=None, choices=["text", "json"],
            ),
            strictcli.Flag(name="output", type=str, help="output path", default=None),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(ctx, format, output):
        print(f"format={format} output={output}")

    return app


def test_mutex_flag_choices_unset_not_validated():
    """Choices on an unset mutex flag must not fire when the other member is passed."""
    app = _mutex_choices_app()
    r = app.test(["cmd", "--output", "out.txt"])
    assert r.exit_code == 0
    assert "format=None output=out.txt" in r.stdout


def test_mutex_flag_choices_passed_valid():
    """A valid choice on the mutex flag is still accepted."""
    app = _mutex_choices_app()
    r = app.test(["cmd", "--format", "json"])
    assert r.exit_code == 0
    assert "format=json output=None" in r.stdout


def test_mutex_flag_choices_passed_invalid():
    """An invalid choice on the mutex flag is still rejected."""
    app = _mutex_choices_app()
    r = app.test(["cmd", "--format", "xml"])
    assert r.exit_code == 1
    assert "--format: invalid value 'xml', must be one of: text, json" in r.stderr


# ---------------------------------------------------------------------------
# Args: default=None (or no default) resolves to None
# ---------------------------------------------------------------------------


def _arg_choices_app(**arg_kwargs):
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(
            name="env", help="target env", required=False,
            choices=["dev", "staging", "prod"], **arg_kwargs,
        )],
    )
    def cmd(ctx, env=None):
        print(f"env={env}")

    return app


def test_arg_none_default_choices_not_passed():
    """Optional arg with default=None and choices, not passed -> succeeds."""
    app = _arg_choices_app(default=None)
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "env=None" in r.stdout


def test_arg_optional_no_default_choices_not_passed():
    """Optional arg with no default and choices, not passed -> succeeds."""
    app = _arg_choices_app()
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "env=None" in r.stdout


def test_arg_none_default_choices_passed_valid():
    """A valid choice on the optional arg is still accepted."""
    app = _arg_choices_app(default=None)
    r = app.test(["cmd", "prod"])
    assert r.exit_code == 0
    assert "env=prod" in r.stdout


def test_arg_none_default_choices_passed_invalid():
    """An invalid choice on the optional arg is still rejected."""
    app = _arg_choices_app(default=None)
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


def _mutex_validate_app():
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(
                name="name", type=str, help="a name",
                default=None, validate=_name_validator,
            ),
            strictcli.Flag(name="id", type=str, help="an id", default=None),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command", mutex=[mg])
    def cmd(ctx, name, id):
        print(f"name={name} id={id}")

    return app


def test_mutex_flag_validate_unset_not_called():
    """A custom validator must not run for an unset mutex flag (value None)."""
    app = _mutex_validate_app()
    r = app.test(["cmd", "--id", "42"])
    assert r.exit_code == 0
    assert "name=None id=42" in r.stdout


def test_mutex_flag_validate_passed_still_runs():
    """A passed value is still validated."""
    app = _mutex_validate_app()
    r = app.test(["cmd", "--name", "bad"])
    assert r.exit_code == 1
    assert "--name: bad name" in r.stderr
