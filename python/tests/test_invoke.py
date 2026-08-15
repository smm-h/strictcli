"""Tests for App._invoke() -- programmatic command invocation pipeline."""

import pytest

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


class TestInvokeBasicFlags:
    """_invoke produces the same handler kwargs as app.test for simple flag cases."""

    def test_str_flag(self):
        """String flag passed via _invoke matches CLI parsing."""
        captured = {}
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet someone")
        @strictcli.flag("name", type=str, help="person to greet", presence="required")
        def greet(ctx, name):
            captured["name"] = name

        app._invoke("greet", {"name": "Alice"})
        assert captured["name"] == "Alice"

        # Compare with CLI path
        captured.clear()
        app.test(["greet", "--name", "Alice"])
        assert captured["name"] == "Alice"

    def test_bool_flag(self):
        """Bool flag passed via _invoke matches CLI parsing."""
        captured = {}
        app = _build_app()

        @app.command("deploy", effect="read_only", help="deploy")
        @strictcli.flag("sim-run", type=bool, default=False, help="dry run mode")
        def deploy(ctx, sim_run):
            captured["sim_run"] = sim_run

        app._invoke("deploy", {"sim_run": True})
        assert captured["sim_run"] is True

        captured.clear()
        app.test(["deploy", "--sim-run"])
        assert captured["sim_run"] is True

    def test_int_flag(self):
        """Int flag passed via _invoke matches CLI parsing."""
        captured = {}
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        @strictcli.flag("count", type=int, help="number of runs", presence="required")
        def run(ctx, count):
            captured["count"] = count

        app._invoke("run", {"count": 5})
        assert captured["count"] == 5

        captured.clear()
        app.test(["run", "--count", "5"])
        assert captured["count"] == 5

    def test_float_flag(self):
        """Float flag passed via _invoke matches CLI parsing."""
        captured = {}
        app = _build_app()

        @app.command("scale", effect="read_only", help="scale")
        @strictcli.flag("factor", type=float, help="scale factor", presence="required")
        def scale(ctx, factor):
            captured["factor"] = factor

        app._invoke("scale", {"factor": 2.5})
        assert captured["factor"] == 2.5

        captured.clear()
        app.test(["scale", "--factor", "2.5"])
        assert captured["factor"] == 2.5

    def test_bool_flag_default_false(self):
        """Bool flag defaults to False when not provided via _invoke."""
        captured = {}
        app = _build_app()

        @app.command("deploy", effect="read_only", help="deploy")
        @strictcli.flag("sim-run", type=bool, default=False, help="dry run mode")
        def deploy(ctx, sim_run):
            captured["sim_run"] = sim_run

        app._invoke("deploy", {})
        assert captured["sim_run"] is False


class TestInvokeWithDefaults:
    """_invoke correctly applies defaults for missing flags."""

    def test_str_flag_with_default(self):
        captured = {}
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet")
        @strictcli.flag("name", type=str, help="name", default="World")
        def greet(ctx, name):
            captured["name"] = name

        app._invoke("greet", {})
        assert captured["name"] == "World"

    def test_required_flag_missing_raises(self):
        """Missing required flag raises _ParseError."""
        app = _build_app()

        @app.command("greet", effect="read_only", help="greet")
        @strictcli.flag("name", type=str, help="name", presence="required")
        def greet(ctx, name):
            pass

        with pytest.raises(Exception, match="flag '--name' is required"):
            app._invoke("greet", {})


class TestInvokePositionalArgs:
    """_invoke handles positional arguments correctly."""

    def test_single_positional(self):
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target", presence="required")],
        )
        def deploy(ctx, target):
            captured["target"] = target

        app._invoke("deploy", {"target": "production"})
        assert captured["target"] == "production"

        # Compare with CLI path
        captured.clear()
        app.test(["deploy", "production"])
        assert captured["target"] == "production"

    def test_positional_and_flags(self):
        """Positional args and flags work together."""
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target", presence="required")],
        )
        @strictcli.flag("sim-run", type=bool, default=False, help="dry run mode")
        def deploy(ctx, target, sim_run):
            captured.update({"target": target, "sim_run": sim_run})

        app._invoke("deploy", {"target": "staging", "sim_run": True})
        assert captured["target"] == "staging"
        assert captured["sim_run"] is True

        captured.clear()
        app.test(["deploy", "--sim-run", "staging"])
        assert captured["target"] == "staging"
        assert captured["sim_run"] is True

    def test_missing_required_positional_raises(self):
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target", presence="required")],
        )
        def deploy(ctx, target):
            pass

        with pytest.raises(Exception, match="missing required argument 'target'"):
            app._invoke("deploy", {})

    def test_optional_positional_with_default(self):
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target", default="local")],
        )
        def deploy(ctx, target):
            captured["target"] = target

        app._invoke("deploy", {})
        assert captured["target"] == "local"


class TestInvokeNestedCommands:
    """_invoke resolves dot-separated paths for nested commands."""

    def test_group_command(self):
        captured = {}
        app = _build_app()
        grp = app.group("config", help="config management")

        @grp.command("show", effect="read_only", help="show config")
        def show(ctx):
            captured["called"] = True

        app._invoke("config.show", {})
        assert captured["called"] is True

    def test_deeply_nested_command(self):
        captured = {}
        app = _build_app()
        g1 = app.group("infra", help="infrastructure")
        g2 = g1.group("dns", help="DNS management")

        @g2.command("list", effect="read_only", help="list DNS records")
        def list_records(ctx):
            captured["called"] = True

        app._invoke("infra.dns.list", {})
        assert captured["called"] is True


class TestInvokeGlobalFlags:
    """_invoke handles global flags correctly."""

    def test_global_flag_passed(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="loud", type=bool, default=False, help="loud output")],
        )

        @app.command("run", effect="read_only", help="run")
        def run(ctx, loud):
            captured["loud"] = loud

        app._invoke("run", {"loud": True})
        assert captured["loud"] is True

    def test_global_flag_default(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="loud", type=bool, default=False, help="loud output")],
        )

        @app.command("run", effect="read_only", help="run")
        def run(ctx, loud):
            captured["loud"] = loud

        app._invoke("run", {})
        assert captured["loud"] is False

    def test_global_str_flag(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="settings", type=str, help="settings path", default="default.toml")],
        )

        @app.command("run", effect="read_only", help="run")
        def run(ctx, settings):
            captured["settings"] = settings

        app._invoke("run", {"settings": "custom.toml"})
        assert captured["settings"] == "custom.toml"

    def test_global_str_flag_default(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="settings", type=str, help="settings path", default="default.toml")],
        )

        @app.command("run", effect="read_only", help="run")
        def run(ctx, settings):
            captured["settings"] = settings

        app._invoke("run", {})
        assert captured["settings"] == "default.toml"

    def test_global_and_command_flags_together(self):
        """Global flags and command flags both appear in handler kwargs."""
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="loud", type=bool, default=False, help="loud output")],
        )

        @app.command("deploy", effect="read_only", help="deploy")
        @strictcli.flag("target", type=str, help="deploy target", default="staging")
        def deploy(ctx, target, loud):
            captured.update({"target": target, "loud": loud})

        app._invoke("deploy", {"target": "prod", "loud": True})
        assert captured["target"] == "prod"
        assert captured["loud"] is True

        # Compare with CLI path
        captured.clear()
        app.test(["--loud", "deploy", "--target", "prod"])
        assert captured["target"] == "prod"
        assert captured["loud"] is True


class TestInvokePassthrough:
    """_invoke handles passthrough commands."""

    def test_passthrough_basic(self):
        captured = {}

        def pt_handler(ctx, name, args, globals):
            captured["name"] = name
            captured["args"] = args
            captured["globals"] = globals
            return 0

        app = _build_app()
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", effect="read_only", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        result = app._invoke("exec", {"_args": ["--foo", "bar", "-v"]})
        assert result == 0
        assert captured["name"] == "exec"
        assert captured["args"] == ["--foo", "bar", "-v"]

    def test_passthrough_empty_args(self):
        captured = {}

        def pt_handler(ctx, name, args, globals):
            captured["name"] = name
            captured["args"] = args
            return 0

        app = _build_app()
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", effect="read_only", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        result = app._invoke("exec", {})
        assert result == 0
        assert captured["args"] == []

    def test_passthrough_receives_global_flag_values(self):
        """Passthrough handler receives global flag values from kwargs."""
        captured = {}

        def pt_handler(ctx, name, args, globals):
            captured["globals"] = globals
            return 0

        app = _build_app(
            flags=[
                strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
                strictcli.Flag(name="settings", type=str, help="settings path", default="default.toml"),
            ],
        )
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", effect="read_only", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        app._invoke("exec", {"_args": ["--foo"], "loud": True, "settings": "custom.toml"})
        assert captured["globals"]["loud"] is True
        assert captured["globals"]["settings"] == "custom.toml"

    def test_passthrough_global_flag_defaults(self):
        """Passthrough handler receives defaults for unprovided global flags."""
        captured = {}

        def pt_handler(ctx, name, args, globals):
            captured["globals"] = globals
            return 0

        app = _build_app(
            flags=[
                strictcli.Flag(name="loud", type=bool, default=False, help="loud output"),
                strictcli.Flag(name="settings", type=str, help="settings path", default="default.toml"),
            ],
        )
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", effect="read_only", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        app._invoke("exec", {"_args": ["x"]})
        assert captured["globals"]["loud"] is False
        assert captured["globals"]["settings"] == "default.toml"

    def test_passthrough_unknown_kwarg_raises(self):
        """Unknown kwargs in passthrough invoke produce an error."""
        def pt_handler(ctx, name, args, globals):
            return 0

        app = _build_app()
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", effect="read_only", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        with pytest.raises(Exception, match="unknown parameter 'bogus' for passthrough command 'exec'"):
            app._invoke("exec", {"_args": ["x"], "bogus": "value"})

    def test_passthrough_missing_required_global_flag_raises(self):
        """Missing required global flag in passthrough invoke produces an error."""
        def pt_handler(ctx, name, args, globals):
            return 0

        app = _build_app(
            flags=[
                strictcli.Flag(name="token", type=str, help="auth token", presence="required"),
            ],
        )
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", effect="read_only", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        with pytest.raises(Exception, match="global flag '--token' is required"):
            app._invoke("exec", {"_args": ["x"]})


class TestInvokeReturnValue:
    """_invoke returns the handler's return value."""

    def test_returns_int(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            return 42

        assert app._invoke("run", {}) == 42

    def test_returns_none(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        assert app._invoke("run", {}) is None


class TestInvokeUnknownCommand:
    """_invoke raises on unknown command paths."""

    def test_unknown_command(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        with pytest.raises(Exception, match="unknown command 'nonexistent'"):
            app._invoke("nonexistent", {})


class TestInvokeUnknownKwarg:
    """_invoke raises on unknown kwargs."""

    def test_unknown_kwarg(self):
        app = _build_app()

        @app.command("run", effect="read_only", help="run")
        def run(ctx):
            pass

        with pytest.raises(Exception, match="unknown parameter 'bogus'"):
            app._invoke("run", {"bogus": "value"})


class TestInvokeSelectors:
    """_invoke takes the elected record, pre-typed (§24.11)."""

    def test_a_non_record_value_is_refused(self):
        app = _build_app()

        @strictcli.choice("as-json", help="JSON output")
        class AsJson:
            pass

        @strictcli.choice("yaml", help="YAML output")
        class Yaml:
            pass

        @app.command("fmt", effect="read_only", help="format")
        @strictcli.choice_flag(
            "format", help="the output format", presence="required",
            elect_by="member-flags", choices=[AsJson, Yaml],
        )
        def fmt(ctx, format: AsJson | Yaml):
            pass

        with pytest.raises(
            Exception, match="must be an instance of a declared choice",
        ):
            app._invoke("fmt", {"format": True})

    def test_the_record_reaches_the_handler_as_the_declaration_describes_it(self):
        """The delivered record carries the caller's values, checked against
        the declarations they were supplied against (§24.11 item 240).

        It is the framework's record rather than the caller's own object: a
        checked value can differ from the supplied one (an integer widens to
        the float its declaration names, a `RelativeToRoot` default resolves to
        a path), so the door builds the record it delivers and leaves the
        object the caller built alone.
        """
        captured = {}
        app = _build_app()

        @strictcli.choice("as-json", help="JSON output")
        class AsJson:
            indent: int = strictcli.sub_flag(help="indent width", default=2)

        @strictcli.choice("yaml", help="YAML output")
        class Yaml:
            pass

        @app.command("fmt", effect="read_only", help="format")
        @strictcli.choice_flag(
            "format", help="the output format", presence="required",
            elect_by="member-flags", choices=[AsJson, Yaml],
        )
        def fmt(ctx, format: AsJson | Yaml):
            captured["format"] = format

        value = AsJson(indent=4)
        app._invoke("fmt", {"format": value})
        assert captured["format"] == value
        assert type(captured["format"]) is AsJson
        assert captured["format"].indent == 4


class TestInvokeDependencies:
    """_invoke enforces the co-occurrence families and Requires (§26)."""

    def test_all_or_none_violation(self):
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            constraints=[
                strictcli.AllOrNone("host-port", [
                    strictcli.Member("host"), strictcli.Member("port"),
                ]),
            ],
        )
        @strictcli.flag("host", type=str, help="host", presence="optional")
        @strictcli.flag("port", type=int, help="port", presence="optional")
        def deploy(ctx, host, port):
            pass

        with pytest.raises(Exception, match="must be used together"):
            app._invoke("deploy", {"host": "localhost"})

    def test_requires_violation(self):
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            constraints=[
                strictcli.Requires("port-needs-host", flag="port", depends_on="host"),
            ],
        )
        @strictcli.flag("host", type=str, help="host", presence="optional")
        @strictcli.flag("port", type=int, help="port", presence="optional")
        def deploy(ctx, host, port):
            pass

        with pytest.raises(Exception, match="requires '--host'"):
            app._invoke("deploy", {"port": 8080})


class TestInvokeChoices:
    """_invoke enforces choices validation."""

    def test_invalid_choice(self):
        app = _build_app()

        @app.command("set-level", effect="read_only", help="set level")
        @strictcli.flag("level", type=str, help="log level", choices=[strictcli.Choice("debug"), strictcli.Choice("info"), strictcli.Choice("warn"), strictcli.Choice("error")], presence="required")
        def set_level(ctx, level):
            pass

        with pytest.raises(Exception, match="invalid value 'trace'"):
            app._invoke("set-level", {"level": "trace"})

    def test_valid_choice(self):
        captured = {}
        app = _build_app()

        @app.command("set-level", effect="read_only", help="set level")
        @strictcli.flag("level", type=str, help="log level", choices=[strictcli.Choice("debug"), strictcli.Choice("info"), strictcli.Choice("warn"), strictcli.Choice("error")], presence="required")
        def set_level(ctx, level):
            captured["level"] = level

        app._invoke("set-level", {"level": "debug"})
        assert captured["level"] == "debug"


class TestInvokeImplies:
    """_invoke handles Implies dependencies."""

    def test_implies_sets_flag(self):
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", effect="read_only", help="deploy",
            constraints=[
                strictcli.Implies("ci-implies-agree", flag="ci", implies="agree", value=True),
            ],
        )
        @strictcli.flag("ci", type=bool, default=False, help="CI mode")
        @strictcli.flag("agree", type=bool, default=False, help="non-interactive")
        def deploy(ctx, ci, agree):
            captured.update({"ci": ci, "agree": agree})

        app._invoke("deploy", {"ci": True})
        assert captured["ci"] is True
        assert captured["agree"] is True


class TestInvokeVariadicArgs:
    """_invoke handles variadic positional args."""

    def test_variadic_args(self):
        captured = {}
        app = _build_app()

        @app.command(
            "install", effect="read_only", help="install packages",
            args=[strictcli.Arg(name="packages", help="packages to install", variadic=True, presence="required")],
        )
        def install(ctx, packages):
            captured["packages"] = packages

        app._invoke("install", {"packages": ["foo", "bar", "baz"]})
        assert captured["packages"] == ["foo", "bar", "baz"]

        # Compare with CLI path
        captured.clear()
        app.test(["install", "foo", "bar", "baz"])
        assert captured["packages"] == ["foo", "bar", "baz"]
