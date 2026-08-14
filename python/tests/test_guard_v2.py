"""Tests for guard v2 (the closed **kwargs exemption) and declared forwarding."""

import pytest

import strictcli


class TestGuardV2:
    def test_var_keyword_without_forwarding_is_a_registration_error(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("run", help="run", effect="read_only")
            def _run(ctx, **kwargs):
                return 0
        assert str(exc.value) == (
            'command "run": handler accepts **kwargs but the command does not '
            'declare forwarding; add forwarding=Forwarding(reason=...) or name '
            'every parameter explicitly'
        )

    def test_var_keyword_in_a_group_is_also_guarded(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        grp = app.group("db", help="db")
        with pytest.raises(ValueError, match="does not declare forwarding"):
            @grp.command("migrate", help="migrate", effect="mutating")
            def _m(ctx, **kw):
                return 0

    def test_declared_forwarding_permits_var_keyword(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        seen = {}

        @app.command("run", help="run", effect="read_only",
                     forwarding=strictcli.Forwarding(reason="wraps another CLI"))
        @strictcli.flag("target", type=str, default="a", help="target")
        def _run(ctx, **kwargs):
            seen.update(kwargs)
            return 0

        r = app.test(["run", "--target", "b"])
        assert r.exit_code == 0
        assert seen == {"target": "b"}

    def test_forwarding_waives_only_the_signature_cross_check(self):
        """Flags are still fully declared and still fully parsed."""
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", help="run", effect="read_only",
                     forwarding=strictcli.Forwarding(reason="wrapper"))
        @strictcli.flag("count", type=int, help="count", presence="required")
        def _run(ctx, **kwargs):
            return 0

        r = app.test(["run"])
        assert r.exit_code == 1
        assert "--count" in r.stderr

    def test_explicit_parameters_still_work_without_forwarding(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", help="run", effect="read_only")
        @strictcli.flag("target", type=str, default="a", help="target")
        def _run(ctx, target):
            return 0

        assert app.test(["run"]).exit_code == 0

    def test_passthrough_handler_needs_no_forwarding(self):
        """A passthrough's signature is deliberately unpoliced already."""
        app = strictcli.App(name="app", version="1.0.0", help="app")
        pt = strictcli.Passthrough(handler=lambda ctx, name, args, globals: 0)

        @app.command("exec", help="exec", effect="read_only", passthrough=pt)
        def _e(ctx, **kw):
            return 0

        assert app._commands["exec"].passthrough is pt


class TestForwardingReason:
    @pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
    def test_empty_reason_is_a_registration_error(self, bad):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError) as exc:
            @app.command("run", help="run", effect="read_only",
                         forwarding=strictcli.Forwarding(reason=bad))
            def _run(ctx, **kw):
                return 0
        assert str(exc.value) == (
            'command "run": forwarding reason must be a non-empty string'
        )

    def test_non_string_reason_is_a_registration_error(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(ValueError, match="non-empty string"):
            @app.command("run", help="run", effect="read_only",
                         forwarding=strictcli.Forwarding(reason=None))
            def _run(ctx, **kw):
                return 0

    def test_reason_is_emitted_in_the_schema(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", help="run", effect="read_only",
                     forwarding=strictcli.Forwarding(reason="wraps git"))
        def _run(ctx, **kw):
            return 0

        schema = app.dump_schema_dict()
        assert schema["commands"]["run"]["forwarding"] == {"reason": "wraps git"}

    def test_forwarding_omitted_from_schema_when_absent(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            return 0

        assert "forwarding" not in app.dump_schema_dict()["commands"]["run"]


class TestFrameworkInternalMarker:
    """The private marker is unreachable from any public API and is verified."""

    def test_no_public_keyword_exposes_the_marker(self):
        app = strictcli.App(name="app", version="1.0.0", help="app")
        with pytest.raises(TypeError):
            @app.command("run", help="run", effect="read_only",
                         framework_internal=True)
            def _run(ctx):
                return 0

    def test_foreign_handler_carrying_the_marker_is_rejected(self):
        def foreign(ctx, **kw):
            return 0

        with pytest.raises(ValueError) as exc:
            strictcli._build_and_validate_command(
                "run",
                help="run",
                effect="read_only",
                handler=foreign,
                args=None, flag_sets=None,
                env_prefix=None,
                forwarding=strictcli.Forwarding(reason="x"),
                framework_internal=True,
            )
        assert str(exc.value) == (
            'command "run": handler is marked framework-internal but is not '
            'defined in the strictcli module'
        )

    def test_config_subcommands_carry_the_marker_and_fixed_reason(self):
        app = strictcli.App(name="app", version="1.0.0", help="app", config=True)
        for name in ("show", "path", "set", "init", "edit"):
            cmd = app._groups["config"].commands[name]
            assert cmd._framework_internal is True
            assert cmd.forwarding is not None
            assert cmd.forwarding.reason == (
                "framework-internal: absorbs app-defined global flag values"
            )

    def test_check_command_carries_the_marker_and_fixed_reason(self, tmp_path):
        toml = tmp_path / "checks.toml"
        toml.write_text('app = "app"\n')
        app = strictcli.App(name="app", version="1.0.0", help="app",
                            checks_path=str(toml))
        cmd = app._commands["check"]
        assert cmd._framework_internal is True
        assert cmd.forwarding.reason == (
            "framework-internal: absorbs app-defined global flag values"
        )

    def test_marker_is_not_emitted_in_the_schema(self):
        app = strictcli.App(name="app", version="1.0.0", help="app", config=True)
        schema = app.dump_schema_dict()
        entry = schema["groups"]["config"]["commands"]["set"]
        assert "_framework_internal" not in entry
        assert "framework_internal" not in entry
        # ... but the forwarding declaration IS visible to an audit gate.
        assert entry["forwarding"] == {
            "reason": "framework-internal: absorbs app-defined global flag values"
        }
