"""Tests for mandatory command classification (effect="read_only"|"mutating")."""

import pytest

import strictcli


class TestClassificationRequired:
    def test_missing_effect_is_a_registration_error(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("run", help="run")
            def _run(ctx):
                return 0
        assert str(exc.value) == (
            'command "run": effect classification is required '
            '(effect="read_only" or effect="mutating")'
        )

    def test_missing_effect_in_a_group(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        grp = app.group("db", help="db")
        with pytest.raises(ValueError) as exc:
            @grp.command("migrate", help="migrate")
            def _m(ctx):
                return 0
        assert "effect classification is required" in str(exc.value)

    def test_missing_effect_on_a_passthrough_command(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        pt = strictcli.Passthrough(handler=lambda ctx, name, args, globals: 0)
        with pytest.raises(ValueError) as exc:
            @app.command("exec", help="exec", passthrough=pt)
            def _e(ctx, **kw):
                return 0
        assert "effect classification is required" in str(exc.value)

    @pytest.mark.parametrize("bad", ["readonly", "READ_ONLY", "mutate", "", "none"])
    def test_invalid_effect_value(self, bad):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("run", help="run", effect=bad)
            def _run(ctx):
                return 0
        assert str(exc.value) == (
            f'command "run": invalid effect "{bad}": '
            f'must be "read_only" or "mutating"'
        )

    @pytest.mark.parametrize("value", ["read_only", "mutating"])
    def test_valid_effect_values(self, value):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", help="run", effect=value)
        def _run(ctx):
            return 0

        assert app._commands["run"].effect == value


class TestDeprecatedExemption:
    def test_deprecated_needs_no_effect(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        app.deprecate("old", message="use new instead")
        assert "old" in app._deprecated

    def test_deprecated_rejects_effect(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            app.deprecate("old", message="gone", effect="read_only")
        assert str(exc.value) == (
            'deprecated command "old": effect classification does not apply '
            '(a deprecated command has no handler)'
        )

    def test_group_deprecated_rejects_effect(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        grp = app.group("db", help="db")
        with pytest.raises(ValueError) as exc:
            grp.deprecate("old", message="gone", effect="mutating")
        assert "effect classification does not apply" in str(exc.value)


class TestFrameworkInternalClassification:
    """The six framework-internal commands carry the pinned classifications."""

    def test_check_command_is_read_only(self, tmp_path):
        toml = tmp_path / "checks.toml"
        toml.write_text('app = "app"\n')
        app = strictcli.App(name="app", version="1.0.0", help="app",
                            checks_path=str(toml))
        assert app._commands["check"].effect == "read_only"

    @pytest.mark.parametrize("name,expected", [
        ("show", "read_only"),
        ("path", "read_only"),
        ("set", "mutating"),
        ("init", "mutating"),
        ("edit", "mutating"),
    ])
    def test_config_subcommand_classification(self, name, expected):
        app = strictcli.App(name="app", version="1.0.0", help="app", config=True)
        assert app._groups["config"].commands[name].effect == expected

    def test_config_edit_stays_interactive(self):
        app = strictcli.App(name="app", version="1.0.0", help="app", config=True)
        assert app._groups["config"].commands["edit"].interactive is True

    def test_config_commands_go_through_the_validated_path(self):
        """The direct-Command-construction bypass is closed: the config
        subcommands are now subject to the same flag validation as any other
        command, so a global flag colliding with one of their flags is a
        registration-time hard error instead of a silent shadow."""
        with pytest.raises(ValueError, match='collides with a global flag'):
            strictcli.App(
                name="app", version="1.0.0", help="app", config=True,
                flags=[strictcli.Flag(name="plain", type=bool, default=False,
                                      help="plain output")],
            )

    def test_config_set_still_parses_its_args_and_flags(self, tmp_path):
        cfg = tmp_path / "config.json"
        app = strictcli.App(name="app", version="1.0.0", help="app",
                            config=True, config_path=str(cfg))

        @app.command("run", help="run", effect="read_only")
        @strictcli.flag("target", type=str, default="a", help="target")
        def _run(ctx, target):
            return 0

        r = app.test(["config", "set", "target", "--value", "b"])
        assert r.exit_code == 0
        assert '"target": "b"' in cfg.read_text()


class TestSchemaEmission:
    def test_effect_is_always_emitted(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("ro", help="read", effect="read_only")
        def _ro(ctx):
            return 0

        @app.command("mu", help="mutate", effect="mutating")
        def _mu(ctx):
            return 0

        schema = app.dump_schema_dict()
        assert schema["commands"]["ro"]["effect"] == "read_only"
        assert schema["commands"]["mu"]["effect"] == "mutating"

    def test_group_commands_emit_effect(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        grp = app.group("db", help="db")

        @grp.command("migrate", help="migrate", effect="mutating")
        def _m(ctx):
            return 0

        schema = app.dump_schema_dict()
        assert schema["groups"]["db"]["commands"]["migrate"]["effect"] == "mutating"

    def test_deprecated_entries_carry_no_effect(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        app.deprecate("old", message="gone")
        schema = app.dump_schema_dict()
        assert schema["deprecated"] == {"old": "gone"}
