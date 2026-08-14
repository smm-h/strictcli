"""The `choices=` value record (contract §24.2, §24.10, §12.13).

A `choices=` entry is ALWAYS a record. The bare-value entry is DELETED: an
entry that may carry help and an entry that carries none would otherwise be two
spellings of one fact, which is §23's one-spelling-per-fact rule applied one
surface over. The record's help is optional -- that is what keeps §24.10's
one-line rendering reachable -- and non-empty when supplied.
"""

import pytest

import strictcli
from strictcli import Choice, choice, choice_flag, sub_flag


def _app():
    return strictcli.App(name="myapp", version="1.0.0", help="test app")


def _choices_app(entries, **flag_kwargs):
    kwargs = {"help": "output format", "presence": "required"}
    kwargs.update(flag_kwargs)
    app = _app()

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag("format", type=str, choices=entries, **kwargs)
    def cmd(ctx, format):
        print(f"format={format}")

    return app


# ---------------------------------------------------------------------------
# The record, and what it delivers
# ---------------------------------------------------------------------------


def test_a_value_flag_still_delivers_the_bare_scalar():
    """§24.2: delivery is the bare scalar, unchanged."""
    r = _choices_app([Choice("text"), Choice("json")]).test(["cmd", "--format", "json"])
    assert r.exit_code == 0
    assert "format=json" in r.stdout


def test_help_is_optional_on_an_entry():
    app = _choices_app([Choice("text"), Choice("json")])
    assert app.test(["cmd", "--format", "text"]).exit_code == 0


def test_an_entrys_help_must_be_non_empty_when_supplied():
    with pytest.raises(ValueError) as exc:
        Choice("text", help="")
    assert str(exc.value) == "Choice.help must be a non-empty string"


def test_the_value_positional_and_the_help_keyword_only():
    record = Choice("head", help="push only the current HEAD branch")
    assert record.value == "head"
    assert record.help == "push only the current HEAD branch"
    with pytest.raises(TypeError):
        Choice("head", "push only the current HEAD branch")


def test_an_invalid_value_reuses_the_existing_sentence():
    r = _choices_app([Choice("text"), Choice("json")]).test(["cmd", "--format", "xml"])
    assert r.exit_code == 1
    assert (
        "error: --format: invalid value 'xml', must be one of: text, json\n"
    ) in r.stderr


def test_records_work_on_positional_args():
    """§24.7: positionals stay command-level, with `choices=` in the record
    spelling."""
    app = _app()

    @app.command(
        "cmd", effect="read_only", help="a command",
        args=[strictcli.Arg(
            name="color", help="pick a color", presence="required",
            choices=[Choice("red", help="the warm one"), Choice("blue")],
        )],
    )
    def cmd(ctx, color):
        print(f"color={color}")

    assert app.test(["cmd", "red"]).exit_code == 0
    bad = app.test(["cmd", "green"])
    assert bad.exit_code == 1
    assert (
        "error: argument 'color': invalid value 'green', must be one of: "
        "red, blue\n"
    ) in bad.stderr


def test_records_work_on_a_repeatable_flag():
    app = _app()

    @app.command("cmd", effect="read_only", help="a command")
    @strictcli.flag(
        "tag", type=list[str], help="tags", default=[], unique=False,
        choices=[Choice("alpha"), Choice("beta", help="the second one")],
    )
    def cmd(ctx, tag):
        print(f"tag={tag}")

    assert app.test(["cmd", "--tag", "alpha", "--tag", "beta"]).exit_code == 0
    assert app.test(["cmd", "--tag", "gamma"]).exit_code == 1


def test_records_work_inside_a_choices_scope():
    @choice("write", help="write the output")
    class Write:
        format: str = sub_flag(
            help="output format", presence="required",
            choices=[Choice("text", help="plain text"), Choice("json")],
        )

    @choice("discard", help="discard the output")
    class Discard:
        pass

    app = _app()

    @app.command("cmd", effect="read_only", help="a command")
    @choice_flag(
        "mode", help="what to do", presence="required",
        elect_by="selector-token", choices=[Write, Discard],
    )
    def cmd(ctx, mode: Write | Discard):
        print(repr(mode))

    assert app.test(["cmd", "--mode", "write", "--format", "json"]).exit_code == 0
    bad = app.test(["cmd", "--mode", "write", "--format", "xml"])
    assert bad.exit_code == 1
    assert "--format: invalid value 'xml', must be one of: text, json" in bad.stderr


# ---------------------------------------------------------------------------
# §12.13 -- the two registration guards
# ---------------------------------------------------------------------------


def test_a_bare_value_entry_is_refused_on_a_flag():
    with pytest.raises(ValueError) as exc:
        strictcli.Flag(
            name="format", type=str, help="output format", presence="required",
            choices=["text", "json"],
        )
    assert str(exc.value) == (
        'Flag "format": choices entry 0 is a bare value: declare it as '
        "Choice(<value>, help=...)"
    )


def test_the_index_names_the_offending_entry():
    with pytest.raises(ValueError) as exc:
        strictcli.Flag(
            name="format", type=str, help="output format", presence="required",
            choices=[Choice("text"), "json"],
        )
    assert str(exc.value) == (
        'Flag "format": choices entry 1 is a bare value: declare it as '
        "Choice(<value>, help=...)"
    )


def test_a_bare_value_entry_is_refused_on_an_arg():
    with pytest.raises(ValueError) as exc:
        strictcli.Arg(
            name="color", help="pick a color", presence="required",
            choices=["red", "blue"],
        )
    assert str(exc.value) == (
        'Arg "color": choices entry 0 is a bare value: declare it as '
        "Choice(<value>, help=...)"
    )


def test_a_choice_class_reaching_choices_names_the_confusion_outright():
    """Python-only (§12.13): `Choice` and `@choice` are case twins naming
    DIFFERENT constructs, and the cost is contained by this message rather
    than by inventing a third noun."""
    @choice("email", help="deliver by email")
    class Email:
        pass

    with pytest.raises(ValueError) as exc:
        strictcli.Flag(
            name="via", type=str, help="delivery channel", presence="required",
            choices=[Email],
        )
    assert str(exc.value) == (
        'Flag "via": choices entry 0 is the choice class \'Email\', which '
        "declares a scope: a choice with a scope belongs to a choice flag, "
        "declared with choice_flag(...)"
    )


def test_an_empty_choices_list_is_still_refused():
    with pytest.raises(ValueError) as exc:
        strictcli.Flag(
            name="format", type=str, help="output format", presence="required",
            choices=[],
        )
    assert str(exc.value) == 'Flag "format": choices must be a non-empty list'


def test_a_records_value_is_still_type_checked():
    with pytest.raises(ValueError) as exc:
        strictcli.Flag(
            name="port", type=int, help="the port", presence="required",
            choices=[Choice(80), Choice("443")],
        )
    assert str(exc.value) == 'Flag "port": choice \'443\' is not of type int'


def test_a_default_must_still_be_one_of_the_declared_values():
    with pytest.raises(ValueError) as exc:
        strictcli.Flag(
            name="format", type=str, help="output format", default="xml",
            choices=[Choice("text"), Choice("json")],
        )
    assert str(exc.value) == (
        'Flag "format": default \'xml\' is not in choices [\'text\', \'json\']'
    )


# ---------------------------------------------------------------------------
# §24.10 -- one line, or a block once any entry carries help
# ---------------------------------------------------------------------------


def test_no_entry_carries_help_keeps_the_one_line_form():
    r = _choices_app([Choice("text"), Choice("json")]).test(["cmd", "--help"])
    assert r.exit_code == 0
    assert (
        "  --format <str>    output format [choices: text, json] [required]\n"
    ) in r.stdout


def test_one_entry_with_help_makes_the_whole_flag_a_block():
    r = _choices_app(
        [Choice("text", help="human-readable output"), Choice("json")],
    ).test(["cmd", "--help"])
    assert r.exit_code == 0
    assert r.stdout == (
        "myapp cmd -- a command\n"
        "\n"
        "Flags:\n"
        "  --format <str>    output format [required]\n"
        "    text            human-readable output\n"
        "    json\n"
    )


def test_the_one_line_choices_part_is_not_repeated_in_block_form():
    r = _choices_app(
        [Choice("text", help="human-readable output"), Choice("json")],
    ).test(["cmd", "--help"])
    assert "[choices:" not in r.stdout


def test_a_block_flags_presence_part_is_still_last_on_its_own_line():
    """§23.8's invariant holds: every flag line ends with exactly one presence
    part, and an entry line is not a flag line."""
    r = _choices_app(
        [Choice("text", help="human-readable output"), Choice("json")],
        default="text", presence=strictcli._MISSING,
    ).test(["cmd", "--help"])
    line = next(ln for ln in r.stdout.splitlines() if "--format" in ln)
    assert line.endswith("[default: text]")
    assert line.count("[default: text]") == 1
