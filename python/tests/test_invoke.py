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

        @app.command("greet", help="greet someone")
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(name):
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

        @app.command("deploy", help="deploy")
        @strictcli.flag("dry-run", type=bool, help="dry run mode")
        def deploy(dry_run):
            captured["dry_run"] = dry_run

        app._invoke("deploy", {"dry_run": True})
        assert captured["dry_run"] is True

        captured.clear()
        app.test(["deploy", "--dry-run"])
        assert captured["dry_run"] is True

    def test_int_flag(self):
        """Int flag passed via _invoke matches CLI parsing."""
        captured = {}
        app = _build_app()

        @app.command("run", help="run")
        @strictcli.flag("count", type=int, help="number of runs")
        def run(count):
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

        @app.command("scale", help="scale")
        @strictcli.flag("factor", type=float, help="scale factor")
        def scale(factor):
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

        @app.command("deploy", help="deploy")
        @strictcli.flag("dry-run", type=bool, help="dry run mode")
        def deploy(dry_run):
            captured["dry_run"] = dry_run

        app._invoke("deploy", {})
        assert captured["dry_run"] is False


class TestInvokeWithDefaults:
    """_invoke correctly applies defaults for missing flags."""

    def test_str_flag_with_default(self):
        captured = {}
        app = _build_app()

        @app.command("greet", help="greet")
        @strictcli.flag("name", type=str, help="name", default="World")
        def greet(name):
            captured["name"] = name

        app._invoke("greet", {})
        assert captured["name"] == "World"

    def test_required_flag_missing_raises(self):
        """Missing required flag raises _ParseError."""
        app = _build_app()

        @app.command("greet", help="greet")
        @strictcli.flag("name", type=str, help="name")
        def greet(name):
            pass

        with pytest.raises(Exception, match="flag '--name' is required"):
            app._invoke("greet", {})


class TestInvokePositionalArgs:
    """_invoke handles positional arguments correctly."""

    def test_single_positional(self):
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target")],
        )
        def deploy(target):
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
            "deploy", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target")],
        )
        @strictcli.flag("dry-run", type=bool, help="dry run mode")
        def deploy(target, dry_run):
            captured.update({"target": target, "dry_run": dry_run})

        app._invoke("deploy", {"target": "staging", "dry_run": True})
        assert captured["target"] == "staging"
        assert captured["dry_run"] is True

        captured.clear()
        app.test(["deploy", "--dry-run", "staging"])
        assert captured["target"] == "staging"
        assert captured["dry_run"] is True

    def test_missing_required_positional_raises(self):
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target")],
        )
        def deploy(target):
            pass

        with pytest.raises(Exception, match="missing required argument 'target'"):
            app._invoke("deploy", {})

    def test_optional_positional_with_default(self):
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            args=[strictcli.Arg(name="target", help="deploy target", required=False, default="local")],
        )
        def deploy(target):
            captured["target"] = target

        app._invoke("deploy", {})
        assert captured["target"] == "local"


class TestInvokeNestedCommands:
    """_invoke resolves dot-separated paths for nested commands."""

    def test_group_command(self):
        captured = {}
        app = _build_app()
        grp = app.group("config", help="config management")

        @grp.command("show", help="show config")
        def show():
            captured["called"] = True

        app._invoke("config.show", {})
        assert captured["called"] is True

    def test_deeply_nested_command(self):
        captured = {}
        app = _build_app()
        g1 = app.group("infra", help="infrastructure")
        g2 = g1.group("dns", help="DNS management")

        @g2.command("list", help="list DNS records")
        def list_records():
            captured["called"] = True

        app._invoke("infra.dns.list", {})
        assert captured["called"] is True


class TestInvokeGlobalFlags:
    """_invoke handles global flags correctly."""

    def test_global_flag_passed(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="verbose", type=bool, help="verbose output")],
        )

        @app.command("run", help="run")
        def run(verbose):
            captured["verbose"] = verbose

        app._invoke("run", {"verbose": True})
        assert captured["verbose"] is True

    def test_global_flag_default(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="verbose", type=bool, help="verbose output")],
        )

        @app.command("run", help="run")
        def run(verbose):
            captured["verbose"] = verbose

        app._invoke("run", {})
        assert captured["verbose"] is False

    def test_global_str_flag(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="config", type=str, help="config path", default="default.toml")],
        )

        @app.command("run", help="run")
        def run(config):
            captured["config"] = config

        app._invoke("run", {"config": "custom.toml"})
        assert captured["config"] == "custom.toml"

    def test_global_str_flag_default(self):
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="config", type=str, help="config path", default="default.toml")],
        )

        @app.command("run", help="run")
        def run(config):
            captured["config"] = config

        app._invoke("run", {})
        assert captured["config"] == "default.toml"

    def test_global_and_command_flags_together(self):
        """Global flags and command flags both appear in handler kwargs."""
        captured = {}
        app = _build_app(
            flags=[strictcli.Flag(name="verbose", type=bool, help="verbose output")],
        )

        @app.command("deploy", help="deploy")
        @strictcli.flag("target", type=str, help="deploy target", default="staging")
        def deploy(target, verbose):
            captured.update({"target": target, "verbose": verbose})

        app._invoke("deploy", {"target": "prod", "verbose": True})
        assert captured["target"] == "prod"
        assert captured["verbose"] is True

        # Compare with CLI path
        captured.clear()
        app.test(["--verbose", "deploy", "--target", "prod"])
        assert captured["target"] == "prod"
        assert captured["verbose"] is True


class TestInvokePassthrough:
    """_invoke handles passthrough commands."""

    def test_passthrough_basic(self):
        captured = {}

        def pt_handler(name, args, globals):
            captured["name"] = name
            captured["args"] = args
            captured["globals"] = globals
            return 0

        app = _build_app()
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        result = app._invoke("exec", {"_args": ["--foo", "bar", "-v"]})
        assert result == 0
        assert captured["name"] == "exec"
        assert captured["args"] == ["--foo", "bar", "-v"]

    def test_passthrough_empty_args(self):
        captured = {}

        def pt_handler(name, args, globals):
            captured["name"] = name
            captured["args"] = args
            return 0

        app = _build_app()
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        result = app._invoke("exec", {})
        assert result == 0
        assert captured["args"] == []

    def test_passthrough_receives_global_flag_values(self):
        """Passthrough handler receives global flag values from kwargs."""
        captured = {}

        def pt_handler(name, args, globals):
            captured["globals"] = globals
            return 0

        app = _build_app(
            flags=[
                strictcli.Flag(name="verbose", type=bool, help="verbose output"),
                strictcli.Flag(name="config", type=str, help="config path", default="default.toml"),
            ],
        )
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        app._invoke("exec", {"_args": ["--foo"], "verbose": True, "config": "custom.toml"})
        assert captured["globals"]["verbose"] is True
        assert captured["globals"]["config"] == "custom.toml"

    def test_passthrough_global_flag_defaults(self):
        """Passthrough handler receives defaults for unprovided global flags."""
        captured = {}

        def pt_handler(name, args, globals):
            captured["globals"] = globals
            return 0

        app = _build_app(
            flags=[
                strictcli.Flag(name="verbose", type=bool, help="verbose output"),
                strictcli.Flag(name="config", type=str, help="config path", default="default.toml"),
            ],
        )
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        app._invoke("exec", {"_args": ["x"]})
        assert captured["globals"]["verbose"] is False
        assert captured["globals"]["config"] == "default.toml"

    def test_passthrough_unknown_kwarg_raises(self):
        """Unknown kwargs in passthrough invoke produce an error."""
        def pt_handler(name, args, globals):
            return 0

        app = _build_app()
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        with pytest.raises(Exception, match="unknown parameter 'bogus' for passthrough command 'exec'"):
            app._invoke("exec", {"_args": ["x"], "bogus": "value"})

    def test_passthrough_missing_required_global_flag_raises(self):
        """Missing required global flag in passthrough invoke produces an error."""
        def pt_handler(name, args, globals):
            return 0

        app = _build_app(
            flags=[
                strictcli.Flag(name="token", type=str, help="auth token"),
            ],
        )
        pt = strictcli.Passthrough(handler=pt_handler)

        @app.command("exec", help="execute", passthrough=pt)
        def exec_cmd():
            pass

        with pytest.raises(Exception, match="global flag '--token' is required"):
            app._invoke("exec", {"_args": ["x"]})


class TestInvokeReturnValue:
    """_invoke returns the handler's return value."""

    def test_returns_int(self):
        app = _build_app()

        @app.command("run", help="run")
        def run():
            return 42

        assert app._invoke("run", {}) == 42

    def test_returns_none(self):
        app = _build_app()

        @app.command("run", help="run")
        def run():
            pass

        assert app._invoke("run", {}) is None


class TestInvokeUnknownCommand:
    """_invoke raises on unknown command paths."""

    def test_unknown_command(self):
        app = _build_app()

        @app.command("run", help="run")
        def run():
            pass

        with pytest.raises(Exception, match="unknown command 'nonexistent'"):
            app._invoke("nonexistent", {})


class TestInvokeUnknownKwarg:
    """_invoke raises on unknown kwargs."""

    def test_unknown_kwarg(self):
        app = _build_app()

        @app.command("run", help="run")
        def run():
            pass

        with pytest.raises(Exception, match="unknown parameter 'bogus'"):
            app._invoke("run", {"bogus": "value"})


class TestInvokeMutex:
    """_invoke enforces mutex group constraints."""

    def test_mutex_both_provided(self):
        app = _build_app()

        @app.command(
            "fmt", help="format",
            mutex=[strictcli.MutexGroup(
                flags=[
                    strictcli.Flag(name="json", type=bool, help="JSON output"),
                    strictcli.Flag(name="yaml", type=bool, help="YAML output"),
                ],
            )],
        )
        def fmt(json, yaml):
            pass

        with pytest.raises(Exception, match="mutually exclusive"):
            app._invoke("fmt", {"json": True, "yaml": True})

    def test_mutex_one_provided(self):
        captured = {}
        app = _build_app()

        @app.command(
            "fmt", help="format",
            mutex=[strictcli.MutexGroup(
                flags=[
                    strictcli.Flag(name="json", type=bool, help="JSON output"),
                    strictcli.Flag(name="yaml", type=bool, help="YAML output"),
                ],
            )],
        )
        def fmt(json, yaml):
            captured.update({"json": json, "yaml": yaml})

        app._invoke("fmt", {"json": True})
        assert captured["json"] is True
        assert captured["yaml"] is False  # bool mutex non-selected gets default False


class TestInvokeDependencies:
    """_invoke enforces CoRequired and Requires dependencies."""

    def test_co_required_violation(self):
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            dependencies=[
                strictcli.CoRequired(flags=["host", "port"]),
            ],
        )
        @strictcli.flag("host", type=str, help="host", default=None)
        @strictcli.flag("port", type=int, help="port", default=None)
        def deploy(host, port):
            pass

        with pytest.raises(Exception, match="must be used together"):
            app._invoke("deploy", {"host": "localhost"})

    def test_requires_violation(self):
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            dependencies=[
                strictcli.Requires(flag="port", depends_on="host"),
            ],
        )
        @strictcli.flag("host", type=str, help="host", default=None)
        @strictcli.flag("port", type=int, help="port", default=None)
        def deploy(host, port):
            pass

        with pytest.raises(Exception, match="requires '--host'"):
            app._invoke("deploy", {"port": 8080})


class TestInvokeChoices:
    """_invoke enforces choices validation."""

    def test_invalid_choice(self):
        app = _build_app()

        @app.command("set-level", help="set level")
        @strictcli.flag("level", type=str, help="log level", choices=["debug", "info", "warn", "error"])
        def set_level(level):
            pass

        with pytest.raises(Exception, match="invalid value 'trace'"):
            app._invoke("set-level", {"level": "trace"})

    def test_valid_choice(self):
        captured = {}
        app = _build_app()

        @app.command("set-level", help="set level")
        @strictcli.flag("level", type=str, help="log level", choices=["debug", "info", "warn", "error"])
        def set_level(level):
            captured["level"] = level

        app._invoke("set-level", {"level": "debug"})
        assert captured["level"] == "debug"


class TestInvokeImplies:
    """_invoke handles Implies dependencies."""

    def test_implies_sets_flag(self):
        captured = {}
        app = _build_app()

        @app.command(
            "deploy", help="deploy",
            dependencies=[
                strictcli.Implies(flag="ci", implies="yes", value=True),
            ],
        )
        @strictcli.flag("ci", type=bool, help="CI mode")
        @strictcli.flag("yes", type=bool, help="non-interactive")
        def deploy(ci, yes):
            captured.update({"ci": ci, "yes": yes})

        app._invoke("deploy", {"ci": True})
        assert captured["ci"] is True
        assert captured["yes"] is True


class TestInvokeVariadicArgs:
    """_invoke handles variadic positional args."""

    def test_variadic_args(self):
        captured = {}
        app = _build_app()

        @app.command(
            "install", help="install packages",
            args=[strictcli.Arg(name="packages", help="packages to install", variadic=True)],
        )
        def install(packages):
            captured["packages"] = packages

        app._invoke("install", {"packages": ["foo", "bar", "baz"]})
        assert captured["packages"] == ["foo", "bar", "baz"]

        # Compare with CLI path
        captured.clear()
        app.test(["install", "foo", "bar", "baz"])
        assert captured["packages"] == ["foo", "bar", "baz"]
