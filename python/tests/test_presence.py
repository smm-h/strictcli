"""The presence declaration (contract §23).

Every flag and every positional arg declares exactly one of
``presence="required"``, ``presence="optional"`` and ``default=<value>``.
Nothing about presence is inferred from the shape of another declaration, so
these tests cover the registration errors byte-exactly, what each declaration
delivers at parse time, how presence composes with every other declaration,
``ctx.provided``, the schema keys, the help markers and the MCP projection.
"""

import json

import pytest

import strictcli


def _app(**kwargs):
    return strictcli.App(name="test", version="1.0.0", help="test app", **kwargs)


# ---------------------------------------------------------------------------
# §23.1 / §12.12 -- the registration errors, byte-exact
# ---------------------------------------------------------------------------


class TestUndeclaredPresence:
    def test_flag_declaring_nothing_does_not_register(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(name="target", type=str, help="the target")
        assert str(exc.value) == (
            'Flag "target": presence is undeclared: declare exactly one of '
            'presence="required", presence="optional", or default=<value>'
        )

    def test_flag_decorator_declaring_nothing_does_not_register(self):
        app = _app()
        with pytest.raises(ValueError) as exc:

            @app.command("cmd", effect="read_only", help="a command")
            @strictcli.flag("target", type=str, help="the target")
            def cmd(ctx, target):
                pass

        assert str(exc.value) == (
            'Flag "target": presence is undeclared: declare exactly one of '
            'presence="required", presence="optional", or default=<value>'
        )

    def test_arg_declaring_nothing_does_not_register(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Arg(name="path", help="the path")
        assert str(exc.value) == (
            'Arg "path": presence is undeclared: declare exactly one of '
            'presence="required", presence="optional", or default=<value>'
        )

    def test_compound_flags_have_no_exemption(self):
        """The silent forced-[] / forced-{} was a derivation and is deleted."""
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="tags", type=list[str], help="tags", unique=False,
            )
        assert "presence is undeclared" in str(exc.value)
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(name="headers", type=dict[str, str], help="headers")
        assert "presence is undeclared" in str(exc.value)


class TestPresenceDeclaredTwice:
    def test_flag_required_plus_default(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="port", type=int, help="the port",
                presence="required", default=8080,
            )
        assert str(exc.value) == (
            'Flag "port": presence is declared twice: presence="required" and '
            "default=8080 cannot be combined; declare exactly one"
        )

    def test_flag_optional_plus_default(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="target", type=str, help="the target",
                presence="optional", default="prod",
            )
        assert str(exc.value) == (
            'Flag "target": presence is declared twice: presence="optional" and '
            "default=prod cannot be combined; declare exactly one"
        )

    def test_flag_default_value_uses_the_error_value_formatter(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="loud", type=bool, help="be loud",
                presence="required", default=False,
            )
        assert str(exc.value) == (
            'Flag "loud": presence is declared twice: presence="required" and '
            "default=false cannot be combined; declare exactly one"
        )

    def test_arg_optional_plus_default(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Arg(
                name="path", help="the path",
                presence="optional", default=".",
            )
        assert str(exc.value) == (
            'Arg "path": presence is declared twice: presence="optional" and '
            "default=. cannot be combined; declare exactly one"
        )

    def test_the_two_are_named_in_canonical_order_not_written_order(self):
        """Canonical order is required, optional, default -- always.

        Python spells presence with one keyword carrying one of two words, so
        `presence=` and `default=` are the only pair that can co-occur and all
        three at once is unwritable: the required/optional pair Go can be
        handed does not exist here. What remains to pin is that writing the
        default first does not put it first in the message.
        """
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="port", type=int, help="the port",
                default=8080, presence="required",
            )
        assert str(exc.value) == (
            'Flag "port": presence is declared twice: presence="required" and '
            "default=8080 cannot be combined; declare exactly one"
        )
        with pytest.raises(ValueError) as exc:
            strictcli.Arg(
                name="path", help="the path",
                default=".", presence="required",
            )
        assert str(exc.value) == (
            'Arg "path": presence is declared twice: presence="required" and '
            "default=. cannot be combined; declare exactly one"
        )


class TestNullValuedDefault:
    def test_flag_default_none_redirects_to_optional(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(name="target", type=str, help="the target", default=None)
        assert str(exc.value) == (
            'Flag "target": default=None does not declare optionality: use '
            'presence="optional" (it delivers None when the flag is absent)'
        )

    def test_arg_default_none_redirects_to_optional(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Arg(name="path", help="the path", default=None)
        assert str(exc.value) == (
            'Arg "path": default=None does not declare optionality: use '
            'presence="optional" (it delivers None when the arg is absent)'
        )

    def test_the_two_declared_error_wins_over_the_redirect(self):
        """The count check runs first (§12.12's implementation-sweep box,
        ledger item 154).

        A null default written BESIDE a presence declaration is a combination
        error, and the message names both spellings -- including the one that
        was actually written, `default=None`. The redirect teaches the old
        idiom of writing `default=None` alone; an author who wrote `presence=`
        already knows the keyword and gets the neutral combination error.
        """
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="target", type=str, help="the target",
                presence="optional", default=None,
            )
        assert str(exc.value) == (
            'Flag "target": presence is declared twice: presence="optional" '
            "and default=None cannot be combined; declare exactly one"
        )
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="target", type=str, help="the target",
                presence="required", default=None,
            )
        assert str(exc.value) == (
            'Flag "target": presence is declared twice: presence="required" '
            "and default=None cannot be combined; declare exactly one"
        )

    def test_the_two_declared_error_wins_over_the_redirect_on_an_arg(self):
        """The arg twin of the rule above: `Arg`, the arg spellings, and the
        same canonical order (ledger item 154)."""
        with pytest.raises(ValueError) as exc:
            strictcli.Arg(
                name="path", help="the path",
                presence="optional", default=None,
            )
        assert str(exc.value) == (
            'Arg "path": presence is declared twice: presence="optional" '
            "and default=None cannot be combined; declare exactly one"
        )
        with pytest.raises(ValueError) as exc:
            strictcli.Arg(
                name="path", help="the path",
                presence="required", default=None,
            )
        assert str(exc.value) == (
            'Arg "path": presence is declared twice: presence="required" '
            "and default=None cannot be combined; declare exactly one"
        )


class TestPresenceValueInvalid:
    def test_presence_default_is_not_a_python_spelling(self):
        with pytest.raises(ValueError) as exc:
            strictcli.Flag(
                name="target", type=str, help="the target", presence="default",
            )
        assert str(exc.value) == (
            'Flag "target": presence must be "required" or "optional", got '
            "'default'; a default value is declared with default=<value>"
        )


class TestMutexMemberRequired:
    def test_a_mutex_member_cannot_declare_requiredness(self):
        app = _app()
        mg = strictcli.MutexGroup(flags=[
            strictcli.Flag(name="json-out", type=bool, help="json", presence="required"),
            strictcli.Flag(name="yaml-out", type=bool, help="yaml", presence="optional"),
        ])
        with pytest.raises(ValueError) as exc:

            @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
            def cmd(ctx, json_out, yaml_out=None):
                pass

        assert str(exc.value) == (
            'Flag "json-out": a mutex member cannot declare presence="required": '
            "the group's own requirement is what makes the choice mandatory"
        )

    def test_a_mutex_member_may_declare_a_default(self):
        app = _app()
        mg = strictcli.MutexGroup(flags=[
            strictcli.Flag(name="fast", type=bool, help="fast", default=False),
            strictcli.Flag(name="slow", type=bool, help="slow", presence="optional"),
        ])

        @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
        def cmd(ctx, fast, slow=None):
            print(f"fast={fast} slow={slow}")

        r = app.test(["cmd", "--slow"])
        assert r.exit_code == 0
        assert "fast=False slow=True" in r.stdout


class TestHandlerParameterCheck:
    def test_optional_flag_bound_to_a_sentinel_default_is_refused(self):
        app = _app()
        with pytest.raises(ValueError) as exc:

            @app.command("cmd", effect="read_only", help="a command")
            @strictcli.flag("target", type=str, help="the target", presence="optional")
            def cmd(ctx, target=""):
                pass

        assert str(exc.value) == (
            "command \"cmd\": handler parameter 'target' is bound to optional "
            "flag '--target' and must default to None"
        )

    def test_optional_arg_bound_to_a_sentinel_default_is_refused(self):
        app = _app()
        with pytest.raises(ValueError) as exc:

            @app.command("cmd", effect="read_only", help="a command")
            @strictcli.arg("path", help="the path", presence="optional")
            def cmd(ctx, path=""):
                pass

        assert str(exc.value) == (
            "command \"cmd\": handler parameter 'path' is bound to optional "
            "arg 'path' and must default to None"
        )

    def test_a_none_default_is_accepted(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", presence="optional")
        def cmd(ctx, target=None):
            print(f"target={target}")

        assert app.test(["cmd"]).exit_code == 0

    def test_a_parameter_with_no_default_is_accepted(self):
        """There is no per-parameter default to re-sentinelize with."""
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", presence="optional")
        def cmd(ctx, target):
            print(f"target={target}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "target=None" in r.stdout

    def test_a_defaulted_flag_may_bind_any_parameter_default(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", default="prod")
        def cmd(ctx, target=""):
            print(f"target={target}")

        assert app.test(["cmd"]).exit_code == 0


# ---------------------------------------------------------------------------
# §23.1 / §23.5 -- what each declaration delivers
# ---------------------------------------------------------------------------


class TestOptionalDelivery:
    def test_optional_scalar_delivers_none(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", presence="optional")
        def cmd(ctx, target=None):
            print(f"target={target!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "target=None" in r.stdout

    def test_empty_string_is_a_value_again(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", presence="optional")
        def cmd(ctx, target=None):
            print(f"target={target!r}")

        r = app.test(["cmd", "--target", ""])
        assert r.exit_code == 0
        assert "target=''" in r.stdout

    def test_optional_bool_is_real_tri_state(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("loud", type=bool, help="be loud", presence="optional")
        def cmd(ctx, loud=None):
            print(f"loud={loud!r}")

        assert "loud=True" in app.test(["cmd", "--loud"]).stdout
        assert "loud=False" in app.test(["cmd", "--no-loud"]).stdout
        assert "loud=None" in app.test(["cmd"]).stdout

    def test_optional_repeatable_delivers_absence_not_an_empty_list(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "tag", type=list[str], help="a tag", presence="optional", unique=False,
        )
        def cmd(ctx, tag=None):
            print(f"tag={tag!r}")

        assert "tag=None" in app.test(["cmd"]).stdout
        assert "tag=['a']" in app.test(["cmd", "--tag", "a"]).stdout

    def test_optional_dict_delivers_absence_not_an_empty_dict(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "header", type=dict[str, str], help="a header", presence="optional",
        )
        def cmd(ctx, header=None):
            print(f"header={header!r}")

        assert "header=None" in app.test(["cmd"]).stdout

    def test_declared_empty_collections_deliver_themselves(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "tag", type=list[str], help="a tag", default=[], unique=False,
        )
        @strictcli.flag(
            "header", type=dict[str, str], help="a header", default={},
        )
        def cmd(ctx, tag, header):
            print(f"tag={tag!r} header={header!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "tag=[] header={}" in r.stdout


class TestRequiredDelivery:
    def test_required_repeatable_needs_at_least_one_occurrence(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "tag", type=list[str], help="a tag", presence="required", unique=False,
        )
        def cmd(ctx, tag):
            print(f"tag={tag!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 1
        assert "flag '--tag' is required" in r.stderr
        assert "tag=['a']" in app.test(["cmd", "--tag", "a"]).stdout

    def test_required_dict_needs_at_least_one_key(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "header", type=dict[str, str], help="a header", presence="required",
        )
        def cmd(ctx, header):
            pass

        r = app.test(["cmd"])
        assert r.exit_code == 1
        assert "flag '--header' is required" in r.stderr

    def test_required_bool_must_be_passed(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("loud", type=bool, help="be loud", presence="required")
        def cmd(ctx, loud):
            print(f"loud={loud}")

        r = app.test(["cmd"])
        assert r.exit_code == 1
        assert "flag '--loud' must be passed as --loud or --no-loud" in r.stderr
        assert "loud=False" in app.test(["cmd", "--no-loud"]).stdout


class TestArgDelivery:
    def test_optional_arg_delivers_a_present_key_holding_none(self):
        """Absence arrives as a present kwarg, never as a missing one."""
        seen = {}
        app = _app()

        @app.command(
            "cmd", effect="read_only", help="a command",
            forwarding=strictcli.Forwarding(reason="captures the kwargs verbatim"),
        )
        @strictcli.arg("path", help="the path", presence="optional")
        def cmd(ctx, **kw):
            seen.update(kw)

        assert app.test(["cmd"]).exit_code == 0
        assert "path" in seen
        assert seen["path"] is None

    def test_required_variadic_needs_at_least_one_value(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.arg(
            "files", help="the files", variadic=True, presence="required",
        )
        def cmd(ctx, files):
            print(f"files={files!r}")

        assert app.test(["cmd"]).exit_code == 1
        assert "files=['a']" in app.test(["cmd", "a"]).stdout

    def test_optional_variadic_delivers_an_empty_list(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.arg(
            "files", help="the files", variadic=True, presence="optional",
        )
        def cmd(ctx, files=None):
            print(f"files={files!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "files=[]" in r.stdout


# ---------------------------------------------------------------------------
# §23.5 -- composition
# ---------------------------------------------------------------------------


class TestComposition:
    def test_env_satisfies_requiredness(self, monkeypatch):
        app = _app(env_prefix="MYAPP")

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "target", type=str, help="the target", presence="required",
            env="MYAPP_TARGET",
        )
        def cmd(ctx, target):
            print(f"target={target}")

        monkeypatch.setenv("MYAPP_TARGET", "prod")
        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "target=prod" in r.stdout

    def test_an_implication_satisfies_requiredness(self):
        app = _app()

        @app.command(
            "cmd", effect="read_only", help="a command",
            dependencies=[strictcli.Implies(
                flag="release", implies="signed", value=True,
            )],
        )
        @strictcli.flag("release", type=bool, help="release", default=False)
        @strictcli.flag("signed", type=bool, help="signed", presence="required")
        def cmd(ctx, release, signed):
            print(f"signed={signed}")

        r = app.test(["cmd", "--release"])
        assert r.exit_code == 0
        assert "signed=True" in r.stdout

    def test_an_implies_trigger_never_fires_from_its_own_default(self):
        app = _app()

        @app.command(
            "cmd", effect="read_only", help="a command",
            dependencies=[strictcli.Implies(
                flag="release", implies="signed", value=True,
            )],
        )
        @strictcli.flag("release", type=bool, help="release", default=True)
        @strictcli.flag("signed", type=bool, help="signed", presence="optional")
        def cmd(ctx, release, signed=None):
            print(f"signed={signed!r}")

        r = app.test(["cmd"])
        assert r.exit_code == 0
        assert "signed=None" in r.stdout

    def test_a_default_does_not_satisfy_a_dependency(self):
        app = _app()

        @app.command(
            "cmd", effect="read_only", help="a command",
            dependencies=[strictcli.Requires(
                flag="sign", depends_on="key",
            )],
        )
        @strictcli.flag("sign", type=bool, help="sign", default=False)
        @strictcli.flag("key", type=str, help="the key", default="builtin")
        def cmd(ctx, sign, key):
            pass

        r = app.test(["cmd", "--sign"])
        assert r.exit_code == 1
        assert "flag '--sign' requires '--key'" in r.stderr

    def test_co_required_with_a_required_member(self):
        # §23.5's CoRequired row: a required member is always provided, so the
        # group then forces every other member to be provided in every
        # invocation. The shape is legal; the errors are the two it can reach.
        def app():
            a = _app()

            @a.command(
                "cmd", effect="read_only", help="a command",
                dependencies=[strictcli.CoRequired(flags=["cert", "key"])],
            )
            @strictcli.flag("cert", type=str, help="the certificate", presence="required")
            @strictcli.flag("key", type=str, help="the private key", presence="optional")
            def cmd(ctx, cert, key=None):
                print(f"cert={cert} key={key}")

            return a

        both = app().test(["cmd", "--cert", "c.pem", "--key", "k.pem"])
        assert both.exit_code == 0, both.stderr
        assert both.stdout == "cert=c.pem key=k.pem\n"

        # Only the required member: the group is violated, because a required
        # member cannot be absent to make the group vacuously satisfied.
        only_required = app().test(["cmd", "--cert", "c.pem"])
        assert only_required.exit_code == 1
        assert only_required.stderr == (
            "error: flags --cert, --key must be used together\n"
            "try 'test cmd --help'\n"
        )

        # Neither: the dependency check sees an empty group (vacuously fine)
        # and the required check is what fires.
        neither = app().test(["cmd"])
        assert neither.exit_code == 1
        assert neither.stderr == (
            "error: flag '--cert' is required\ntry 'test cmd --help'\n"
        )

    def test_choices_compose_with_optional_in_both_directions(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "format", type=str, help="format", presence="optional",
            choices=["text", "json"],
        )
        def cmd(ctx, format=None):
            print(f"format={format!r}")

        assert "format=None" in app.test(["cmd"]).stdout
        assert "format='json'" in app.test(["cmd", "--format", "json"]).stdout
        bad = app.test(["cmd", "--format", "xml"])
        assert bad.exit_code == 1
        assert "--format: invalid value 'xml'" in bad.stderr

    def test_an_unelected_mutex_member_delivers_its_own_declaration(self):
        app = _app()
        mg = strictcli.MutexGroup(flags=[
            strictcli.Flag(name="output", type=str, help="output", presence="optional"),
            strictcli.Flag(name="target", type=str, help="target", default="prod"),
        ])

        @app.command("cmd", effect="read_only", help="a command", mutex=[mg])
        def cmd(ctx, output=None, target=None):
            print(f"output={output!r} target={target!r}")

        r = app.test(["cmd", "--output", "out.txt"])
        assert r.exit_code == 0
        assert "output='out.txt' target='prod'" in r.stdout


# ---------------------------------------------------------------------------
# §23.6 -- ctx.provided
# ---------------------------------------------------------------------------


class TestProvided:
    def _probe_app(self, **flag_kwargs):
        app = _app(env_prefix="MYAPP")

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", **flag_kwargs)
        def cmd(ctx, target=None):
            print(f"provided={ctx.provided('target')} source={ctx.source('target')}")

        return app

    def test_a_cli_value_is_provided(self):
        app = self._probe_app(presence="optional")
        r = app.test(["cmd", "--target", "prod"])
        assert "provided=True source=cli" in r.stdout

    def test_an_env_value_is_provided(self, monkeypatch):
        app = self._probe_app(presence="optional", env="MYAPP_TARGET")
        monkeypatch.setenv("MYAPP_TARGET", "prod")
        r = app.test(["cmd"])
        assert "provided=True source=env" in r.stdout

    def test_a_declared_default_is_not_provided(self):
        app = self._probe_app(default="prod")
        r = app.test(["cmd"])
        assert "provided=False source=default" in r.stdout

    def test_an_optional_flag_that_received_nothing_is_not_provided(self):
        """It carries source `default`: an optional declaration deciding on
        absence IS the declaration deciding. No seventh label is minted."""
        app = self._probe_app(presence="optional")
        r = app.test(["cmd"])
        assert "provided=False source=default" in r.stdout

    def test_an_implied_value_is_provided(self):
        app = _app()

        @app.command(
            "cmd", effect="read_only", help="a command",
            dependencies=[strictcli.Implies(
                flag="release", implies="signed", value=True,
            )],
        )
        @strictcli.flag("release", type=bool, help="release", default=False)
        @strictcli.flag("signed", type=bool, help="signed", presence="optional")
        def cmd(ctx, release, signed=None):
            print(f"provided={ctx.provided('signed')} source={ctx.source('signed')}")

        r = app.test(["cmd", "--release"])
        assert "provided=True source=implied" in r.stdout

    def test_an_infra_default_is_not_provided(self, monkeypatch):
        app = _app(infra_root={"MYAPP_HOME": "~/.myapp"})

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "state", type=str, help="the state dir",
            default=strictcli.RelativeToRoot("MYAPP_HOME", "state"),
        )
        def cmd(ctx, state):
            print(f"provided={ctx.provided('state')} source={ctx.source('state')}")

        r = app.test(["cmd"])
        assert "provided=False source=infra" in r.stdout

    def test_a_dashed_name_is_accepted(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("dry-mode", type=bool, help="dry", presence="optional")
        def cmd(ctx, dry_mode=None):
            print(f"provided={ctx.provided('dry-mode')}")

        assert "provided=True" in app.test(["cmd", "--dry-mode"]).stdout

    def test_an_unknown_name_raises_the_source_error(self):
        seen = {}
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", presence="optional")
        def cmd(ctx, target=None):
            try:
                ctx.provided("nope")
            except KeyError as e:
                seen["msg"] = e.args[0]

        app.test(["cmd"])
        assert seen["msg"] == "no source info for flag 'nope'"''


# ---------------------------------------------------------------------------
# §13's amendment -- the dumped schema
# ---------------------------------------------------------------------------


class TestSchemaPresence:
    def _dump(self, build, tmp_path, monkeypatch):
        """Build the app INSIDE tmp_path: the schema path is resolved when the
        App is constructed, so a chdir afterwards comes too late."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "testapp"\nversion = "1.0.0"\n'
        )
        monkeypatch.chdir(tmp_path)
        app = build()
        r = app.test(["--dump-schema"])
        assert r.exit_code == 0, r.stderr
        return json.loads((tmp_path / ".strictcli" / "schema.json").read_text())

    def test_every_flag_and_arg_entry_carries_presence(self, tmp_path, monkeypatch):
        def build():
            app = _app()

            @app.command("cmd", effect="read_only", help="a command")
            @strictcli.flag("a", type=str, help="a", presence="required")
            @strictcli.flag("b", type=str, help="b", presence="optional")
            @strictcli.flag("c", type=str, help="c", default="x")
            @strictcli.arg("p", help="p", presence="required")
            def cmd(ctx, a, b, c, p):
                pass

            return app

        data = self._dump(build, tmp_path, monkeypatch)
        flags = {f["name"]: f for f in data["commands"]["cmd"]["flags"]}
        assert flags["a"]["presence"] == "required"
        assert "default" not in flags["a"]
        assert flags["b"]["presence"] == "optional"
        assert "default" not in flags["b"]
        assert flags["c"]["presence"] == "default"
        assert flags["c"]["default"] == "x"
        arg = data["commands"]["cmd"]["args"][0]
        assert arg["presence"] == "required"
        assert "required" not in arg

    def test_empty_and_falsey_defaults_are_emitted(self, tmp_path, monkeypatch):
        def build():
            app = _app()

            @app.command("cmd", effect="read_only", help="a command")
            @strictcli.flag("tag", type=list[str], help="tags", default=[], unique=False)
            @strictcli.flag("header", type=dict[str, str], help="headers", default={})
            @strictcli.flag("name", type=str, help="name", default="")
            @strictcli.flag("count", type=int, help="count", default=0)
            @strictcli.flag("loud", type=bool, help="loud", default=False)
            def cmd(ctx, tag, header, name, count, loud):
                pass

            return app

        data = self._dump(build, tmp_path, monkeypatch)
        flags = {f["name"]: f for f in data["commands"]["cmd"]["flags"]}
        assert flags["tag"]["default"] == []
        assert flags["header"]["default"] == {}
        assert flags["name"]["default"] == ""
        assert flags["count"]["default"] == 0
        assert flags["loud"]["default"] is False
        for f in flags.values():
            assert f["presence"] == "default"


# ---------------------------------------------------------------------------
# §23.8 -- help rendering
# ---------------------------------------------------------------------------


class TestHelpMarkers:
    def _help(self, app):
        r = app.test(["cmd", "--help"])
        assert r.exit_code == 0
        return r.stdout

    def test_one_marker_per_flag_line_and_it_is_last(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "format", type=str, help="the format", presence="optional",
            choices=["text", "json"], env="FMT", prefixed=False,
        )
        def cmd(ctx, format=None):
            pass

        line = next(
            ln for ln in self._help(app).splitlines() if "--format" in ln
        )
        assert line.endswith("[optional]")
        assert line.count("[optional]") == 1
        assert "[required]" not in line
        assert "[default" not in line

    def test_python_gains_the_optional_marker(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("target", type=str, help="the target", presence="optional")
        def cmd(ctx, target=None):
            pass

        assert "[optional]" in self._help(app)

    def test_declared_empty_collections_render_their_literal(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("tag", type=list[str], help="tags", default=[], unique=False)
        @strictcli.flag("header", type=dict[str, str], help="headers", default={})
        def cmd(ctx, tag, header):
            pass

        out = self._help(app)
        assert "[default: []]" in out
        assert "[default: {}]" in out

    def test_a_required_positional_renders_required(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.arg("path", help="the path", presence="required")
        def cmd(ctx, path):
            pass

        line = next(ln for ln in self._help(app).splitlines() if "path" in ln)
        assert line.endswith("[required]")

    def test_an_optional_positional_renders_optional(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.arg("path", help="the path", presence="optional")
        def cmd(ctx, path=None):
            pass

        assert "[optional]" in self._help(app)

    @pytest.mark.parametrize(
        "declared_type,value,rendered",
        [
            (bool, True, "true"),
            (bool, False, "false"),
            (int, 7, "7"),
            (float, 1.5, "1.5"),
            (float, 1e-7, "1e-7"),
            (float, 2.0, "2.0"),
            (str, "prod", "prod"),
        ],
    )
    def test_the_same_default_renders_the_same_on_an_arg_and_a_flag(
        self, declared_type, value, rendered,
    ):
        """One value, one rendering, whichever surface declared it (§23.8).

        The positional side used to render a bool default through ``str()``,
        so `[default: True]` faced a flag's `[default: true]` on the same
        help page.
        """
        app = _app()

        @app.command(
            "cmd", effect="read_only", help="a command",
            args=[
                strictcli.Arg(
                    name="pos", help="the positional",
                    type=declared_type, default=value,
                ),
            ],
        )
        @strictcli.flag(
            "opt", type=declared_type, help="the flag", default=value,
        )
        def cmd(ctx, pos, opt):
            pass

        lines = self._help(app).splitlines()
        arg_line = next(ln for ln in lines if ln.strip().startswith("pos "))
        flag_line = next(ln for ln in lines if "--opt" in ln)
        assert arg_line.endswith(f"[default: {rendered}]")
        assert flag_line.endswith(f"[default: {rendered}]")

    def test_a_dict_default_renders_sorted_pairs_inside_the_marker(self):
        """The whole bracketed part, not just the pairs (§23.8)."""
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "header", type=dict[str, int], help="headers",
            default={"zebra": 3, "apple": 1, "mango": 2},
        )
        def cmd(ctx, header):
            pass

        line = next(
            ln for ln in self._help(app).splitlines() if "--header" in ln
        )
        assert line.endswith("[default: apple=1, mango=2, zebra=3]")

    def test_a_list_default_renders_its_elements_inside_the_marker(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "tag", type=list[str], help="tags", default=["x", "y"], unique=False,
        )
        def cmd(ctx, tag):
            pass

        line = next(ln for ln in self._help(app).splitlines() if "--tag" in ln)
        assert line.endswith("[default: x, y]")

    def test_declared_empty_collections_render_the_whole_marker(self):
        """`[default: []]` / `[default: {}]`, brackets included (§23.8)."""
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("tag", type=list[str], help="tags", default=[], unique=False)
        @strictcli.flag("header", type=dict[str, str], help="headers", default={})
        def cmd(ctx, tag, header):
            pass

        lines = self._help(app).splitlines()
        assert next(
            ln for ln in lines if "--tag" in ln
        ).endswith("[default: []]")
        assert next(
            ln for ln in lines if "--header" in ln
        ).endswith("[default: {}]")


# ---------------------------------------------------------------------------
# §23.7 -- the MCP / tool projection
# ---------------------------------------------------------------------------


class TestToolSchemaRequiredness:
    def test_requiredness_is_read_off_the_declaration(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("a", type=str, help="a", presence="required")
        @strictcli.flag("b", type=str, help="b", presence="optional")
        @strictcli.flag("c", type=str, help="c", default="x")
        @strictcli.arg("p", help="p", presence="required")
        @strictcli.arg("q", help="q", presence="optional")
        def cmd(ctx, a, b, c, p, q=None):
            pass

        schema = app.json_schema("cmd")
        assert schema["required"] == ["a", "p"]

    def test_a_required_bool_is_in_the_required_array(self):
        """Bools were excluded on the reasoning that they always have a
        default, which the presence declaration makes false."""
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag("loud", type=bool, help="be loud", presence="required")
        @strictcli.flag("quiet-mode", type=bool, help="quiet", default=False)
        def cmd(ctx, loud, quiet_mode):
            pass

        schema = app.json_schema("cmd")
        assert schema["required"] == ["loud"]

    def test_a_required_compound_flag_is_in_the_required_array(self):
        app = _app()

        @app.command("cmd", effect="read_only", help="a command")
        @strictcli.flag(
            "tag", type=list[str], help="tags", presence="required", unique=False,
        )
        def cmd(ctx, tag):
            pass

        schema = app.json_schema("cmd")
        assert schema["required"] == ["tag"]
