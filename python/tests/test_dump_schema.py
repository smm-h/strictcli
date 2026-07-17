"""Tests for --dump-schema flag and schema serialization."""

from __future__ import annotations

import json
import os

import pytest
import strictcli

_PYPROJECT_TOML = '[project]\nname = "testproject"\n'


@pytest.fixture(autouse=True)
def _pyproject_in_tmp(tmp_path):
    """Ensure every test that uses tmp_path has a pyproject.toml for project_id."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_TOML)


def _make_app(**kwargs):
    """Create a minimal app for testing."""
    defaults = dict(name="testapp", help="A test app", version="1.0.0")
    defaults.update(kwargs)
    return strictcli.App(**defaults)


class TestDumpSchemaBasic:
    """--dump-schema writes .strictcli/schema.json and exits 0."""

    def test_writes_file_and_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        schema_path = tmp_path / ".strictcli" / "schema.json"
        assert schema_path.exists()
        # stdout should contain the path
        assert str(schema_path) in result.stdout

    def test_schema_is_valid_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        app.test(["--dump-schema"])
        schema_path = tmp_path / ".strictcli" / "schema.json"
        data = json.loads(schema_path.read_text())
        assert isinstance(data, dict)


class TestSchemaContent:
    """Schema contains correct app name, version, help."""

    def test_app_metadata(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app(name="myapp", version="2.3.4", help="My great app")

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["name"] == "myapp"
        assert data["version"] == "2.3.4"
        assert data["help"] == "My great app"

    def test_env_prefix_omitted_when_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "env_prefix" not in data

    def test_env_prefix_when_set(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app(env_prefix="MYAPP")

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["env_prefix"] == "MYAPP"

    def test_config_omitted_when_false(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app_no_config = _make_app(config=False)

        @app_no_config.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app_no_config.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "config" not in data


class TestSchemaCommands:
    """Schema contains commands with their flags and args."""

    def test_command_with_flags(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("deploy", help="Deploy the app")
        @strictcli.flag("target", type=str, help="Deploy target", short="t",
                        choices=["prod", "staging"])
        @strictcli.flag("force-deploy", type=bool, default=False, help="Force deploy")
        def deploy(ctx, target, force_deploy):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "deploy" in data["commands"]
        cmd = data["commands"]["deploy"]
        assert cmd["name"] == "deploy"
        assert cmd["help"] == "Deploy the app"
        assert len(cmd["flags"]) == 2

        # Check flag serialization
        target_flag = cmd["flags"][0]
        assert target_flag["name"] == "target"
        assert target_flag["type"] == "str"
        assert target_flag["short"] == "t"
        assert target_flag["choices"] == ["prod", "staging"]
        assert "hidden" not in target_flag  # hidden=False is the default, omitted

        force_flag = cmd["flags"][1]
        assert force_flag["name"] == "force-deploy"
        assert force_flag["type"] == "bool"
        assert force_flag["negatable"] is True
        assert force_flag["default"] is False

    def test_command_with_args(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Greet someone",
                     args=[strictcli.Arg(name="name", help="Who to greet")])
        def greet(ctx, name):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["greet"]
        assert len(cmd["args"]) == 1
        arg = cmd["args"][0]
        assert arg["name"] == "name"
        assert arg["help"] == "Who to greet"
        assert "required" not in arg  # required=True is the default, omitted
        assert "variadic" not in arg  # variadic=False is the default, omitted

    def test_passthrough_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("run", help="Run a command",
                     passthrough=strictcli.Passthrough(
                         handler=lambda ctx, name, args, globals: 0))
        def run():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["run"]
        assert cmd["passthrough"] is True

    def test_non_passthrough_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["greet"]
        assert "passthrough" not in cmd  # passthrough=False is the default, omitted


class TestSchemaGroups:
    """Schema contains groups (including nested groups)."""

    def test_group_with_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        dns = app.group("dns", help="DNS management")

        @dns.command("list", help="List DNS records")
        def dns_list(ctx):
            pass

        @dns.command("add", help="Add a DNS record")
        @strictcli.flag("type", type=str, help="Record type")
        def dns_add(ctx, type):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "dns" in data["groups"]
        grp = data["groups"]["dns"]
        assert grp["name"] == "dns"
        assert grp["help"] == "DNS management"
        assert "list" in grp["commands"]
        assert "add" in grp["commands"]
        assert grp["commands"]["add"]["flags"][0]["name"] == "type"

    def test_nested_groups(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        dns = app.group("dns", help="DNS management")
        zone = dns.group("zone", help="Zone management")

        @zone.command("list", help="List zones")
        def zone_list(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "dns" in data["groups"]
        assert "zone" in data["groups"]["dns"]["groups"]
        nested = data["groups"]["dns"]["groups"]["zone"]
        assert nested["name"] == "zone"
        assert nested["help"] == "Zone management"
        assert "list" in nested["commands"]

    def test_group_deprecated_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        dns = app.group("dns", help="DNS management")

        @dns.command("list", help="List DNS records")
        def dns_list(ctx):
            pass

        dns.deprecate("old-cmd", message="Use 'list' instead")

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        grp = data["groups"]["dns"]
        assert "old-cmd" in grp["deprecated"]
        assert grp["deprecated"]["old-cmd"] == "Use 'list' instead"


class TestSchemaGlobalFlags:
    """Schema contains global flags."""

    def test_global_flags_serialized(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app(
            flags=[
                strictcli.Flag(name="verbose", type=bool, default=False, help="Verbose output", short="V"),
                strictcli.Flag(name="output", type=str, help="Output format",
                               default="text", choices=["text", "json"]),
            ]
        )

        @app.command("noop", help="Does nothing")
        def noop(ctx, verbose, output):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert len(data["global_flags"]) == 2
        verbose = data["global_flags"][0]
        assert verbose["name"] == "verbose"
        assert verbose["type"] == "bool"
        assert verbose["short"] == "V"
        assert verbose["negatable"] is True

        output = data["global_flags"][1]
        assert output["name"] == "output"
        assert output["type"] == "str"
        assert output["default"] == "text"
        assert output["choices"] == ["text", "json"]
        assert "negatable" not in output  # non-bool flag, null is the default, omitted


class TestSchemaDeprecated:
    """Schema contains deprecated commands."""

    def test_deprecated_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("new-cmd", help="The new command")
        def new_cmd(ctx):
            pass

        app.deprecate("old-cmd", message="Use 'new-cmd' instead")

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "old-cmd" in data["deprecated"]
        assert data["deprecated"]["old-cmd"] == "Use 'new-cmd' instead"


class TestSchemaDirectoryCreation:
    """--dump-schema creates the directory if missing."""

    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / ".strictcli").exists()
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        assert (tmp_path / ".strictcli").is_dir()
        assert (tmp_path / ".strictcli" / "schema.json").is_file()

    def test_overwrites_existing_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        schema_dir = tmp_path / ".strictcli"
        schema_dir.mkdir()
        (schema_dir / "schema.json").write_text("{}")

        app = _make_app(version="3.0.0")

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((schema_dir / "schema.json").read_text())
        assert data["version"] == "3.0.0"


class TestSchemaEmptyApp:
    """App without commands still produces valid schema."""

    def test_empty_app(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["name"] == "testapp"
        assert "commands" not in data  # empty dict is the default, omitted
        assert "groups" not in data  # empty dict is the default, omitted
        assert "global_flags" not in data  # empty list is the default, omitted
        assert "deprecated" not in data  # empty dict is the default, omitted


class TestSchemaFlagTypes:
    """Schema correctly serializes all flag types."""

    def test_int_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("count", type=int, help="How many", default=5)
        def cmd(ctx, count):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["type"] == "int"
        assert flag["default"] == 5

    def test_float_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("ratio", type=float, help="The ratio", default=0.5)
        def cmd(ctx, ratio):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["type"] == "float"
        assert flag["default"] == 0.5

    def test_repeatable_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("tag", type=str, help="A tag", repeatable=True, unique=False)
        def cmd(ctx, tag):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["repeatable"] is True
        assert flag["default"] == []

    def test_env_on_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app(env_prefix="MYAPP")

        @app.command("cmd", help="A command")
        @strictcli.flag("token", type=str, help="Auth token", env="MYAPP_TOKEN")
        def cmd(ctx, token):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["env"] == "MYAPP_TOKEN"

    def test_bool_non_negatable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("force-it", type=bool, default=False, help="Force it", negatable=False)
        def cmd(ctx, force_it):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["negatable"] is False


class TestDumpSchemaWithOtherArgs:
    """--dump-schema is only detected in the pre-command region."""

    def test_dump_schema_before_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        assert (tmp_path / ".strictcli" / "schema.json").exists()

    def test_dump_schema_after_command_is_unknown_flag(self, tmp_path, monkeypatch):
        """--dump-schema after a command name is NOT intercepted."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        result = app.test(["greet", "--dump-schema"])
        assert result.exit_code == 1
        assert "unknown flag" in result.stderr

    def test_dump_schema_after_double_dash_is_not_intercepted(self, tmp_path, monkeypatch):
        """--dump-schema after -- is NOT intercepted."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        result = app.test(["--", "--dump-schema"])
        # After --, --dump-schema is treated as a command name (unknown command error)
        assert result.exit_code == 1


class TestSchemaDefaults:
    """Schema includes a top-level 'defaults' key documenting what missing fields mean."""

    def test_defaults_key_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "defaults" in data
        assert isinstance(data["defaults"], dict)

    def test_defaults_structure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        defaults = data["defaults"]

        # Schema version default
        assert defaults["schema_version"] == 1

        # App defaults
        assert defaults["app"]["env_prefix"] is None
        assert defaults["app"]["config"] is False
        assert defaults["app"]["global_flags"] == []
        assert defaults["app"]["commands"] == {}
        assert defaults["app"]["groups"] == {}
        assert defaults["app"]["deprecated"] == {}
        assert defaults["app"]["tag_contracts"] == {}

        # Flag defaults
        assert defaults["flag"]["short"] is None
        assert defaults["flag"]["default"] is None
        assert defaults["flag"]["env"] is None
        assert defaults["flag"]["choices"] is None
        assert defaults["flag"]["repeatable"] is False
        assert defaults["flag"]["negatable"] is None
        assert defaults["flag"]["hidden"] is False

        # Arg defaults
        assert defaults["arg"]["required"] is True
        assert defaults["arg"]["default"] is None
        assert defaults["arg"]["variadic"] is False

        # Command defaults
        assert defaults["command"]["passthrough"] is False
        assert defaults["command"]["flags"] == []
        assert defaults["command"]["args"] == []
        assert defaults["command"]["constraints"] == []

        # Group defaults
        assert defaults["group"]["commands"] == {}
        assert defaults["group"]["groups"] == {}
        assert defaults["group"]["deprecated"] == {}


class TestSchemaOmitsDefaults:
    """Fields matching their defaults are omitted from the schema output."""

    def test_flag_null_fields_omitted(self, tmp_path, monkeypatch):
        """A flag with all-default optional fields should only have name/type/help."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("name", type=str, help="A name")
        def cmd(ctx, name):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["name"] == "name"
        assert flag["type"] == "str"
        assert flag["help"] == "A name"
        # All optional fields should be absent (they match defaults)
        assert "short" not in flag
        assert "default" not in flag
        assert "env" not in flag
        assert "choices" not in flag
        assert "repeatable" not in flag
        assert "negatable" not in flag
        assert "hidden" not in flag

    def test_command_empty_flags_and_args_omitted(self, tmp_path, monkeypatch):
        """A command with no flags/args should omit those lists."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["noop"]
        assert "flags" not in cmd
        assert "args" not in cmd
        assert "passthrough" not in cmd

    def test_group_empty_subgroups_and_deprecated_omitted(self, tmp_path, monkeypatch):
        """A group with no subgroups or deprecated commands omits those."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        grp = app.group("stuff", help="Stuff management")

        @grp.command("do", help="Do stuff")
        def do_stuff(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        group_data = data["groups"]["stuff"]
        assert "commands" in group_data  # has commands, so present
        assert "groups" not in group_data  # empty, omitted
        assert "deprecated" not in group_data  # empty, omitted

    def test_arg_defaults_omitted(self, tmp_path, monkeypatch):
        """An arg with required=True and variadic=False omits both."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command",
                     args=[strictcli.Arg(name="target", help="The target")])
        def cmd(ctx, target):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        arg = data["commands"]["cmd"]["args"][0]
        assert arg["name"] == "target"
        assert arg["help"] == "The target"
        assert "required" not in arg
        assert "variadic" not in arg


class TestSchemaNonDefaultValues:
    """Non-default values are present in the schema output."""

    def test_arg_required_false_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command",
                     args=[strictcli.Arg(name="target", help="The target",
                                         required=False)])
        def cmd(ctx, target):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        arg = data["commands"]["cmd"]["args"][0]
        assert arg["required"] is False

    def test_arg_variadic_true_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command",
                     args=[strictcli.Arg(name="files", help="Files to process",
                                         variadic=True)])
        def cmd(ctx, files):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        arg = data["commands"]["cmd"]["args"][0]
        assert arg["variadic"] is True

    def test_passthrough_true_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("run", help="Run a command",
                     passthrough=strictcli.Passthrough(
                         handler=lambda ctx, name, args, globals: 0))
        def run():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["run"]
        assert cmd["passthrough"] is True

    def test_flag_with_all_non_default_values(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("level", type=int, help="Level", short="l",
                        default=3, env="MY_LEVEL", choices=[1, 2, 3])
        def cmd(ctx, level):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["short"] == "l"
        assert flag["default"] == 3
        assert flag["env"] == "MY_LEVEL"
        assert flag["choices"] == [1, 2, 3]

    def test_config_true_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app(config=True)

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["config"] is True


class TestSchemaProjectId:
    """Schema contains project_id from pyproject.toml."""

    def test_project_id_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["project_id"] == "testproject"

    def test_project_id_custom_name(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "my-custom-tool"\n'
        )
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["project_id"] == "my-custom-tool"

    def test_project_id_error_no_pyproject(self, tmp_path, monkeypatch):
        os.remove(tmp_path / "pyproject.toml")
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code != 0
        assert "project_id" in result.stderr

    def test_project_id_error_no_project_name(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text("[tool.something]\nkey = 1\n")
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code != 0
        assert "project_id" in result.stderr


class TestSchemaVersion:
    """Schema includes schema_version field."""

    def test_schema_version_present(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["schema_version"] == 1

    def test_schema_version_is_first_key(self, tmp_path, monkeypatch):
        """schema_version should appear before other keys in the JSON."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        keys = list(data.keys())
        assert keys[0] == "schema_version"


class TestSchemaConstraints:
    """Schema serializes command constraints (mutex, co_required, requires, implies)."""

    def test_no_constraints_omitted(self, tmp_path, monkeypatch):
        """Commands without constraints omit the constraints field."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "constraints" not in data["commands"]["noop"]

    def test_mutex_group(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        json_flag = strictcli.Flag(name="json", type=bool, default=False, help="JSON output")
        text_flag = strictcli.Flag(name="text", type=bool, default=False, help="Text output")

        @app.command("show", help="Show data",
                     mutex=[strictcli.MutexGroup(flags=[json_flag, text_flag])])
        def show(ctx, json, text):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["show"]
        assert "constraints" in cmd
        assert len(cmd["constraints"]) == 1
        c = cmd["constraints"][0]
        assert c["type"] == "mutex"
        assert c["flags"] == ["json", "text"]

    def test_co_required(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("deploy", help="Deploy",
                     dependencies=[strictcli.CoRequired(flags=["host", "port"])])
        @strictcli.flag("host", type=str, help="Hostname")
        @strictcli.flag("port", type=int, help="Port number")
        def deploy(ctx, host, port):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["deploy"]
        assert len(cmd["constraints"]) == 1
        c = cmd["constraints"][0]
        assert c["type"] == "co_required"
        assert c["flags"] == ["host", "port"]

    def test_requires(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("deploy", help="Deploy",
                     dependencies=[strictcli.Requires(flag="port", depends_on="host")])
        @strictcli.flag("host", type=str, help="Hostname")
        @strictcli.flag("port", type=int, help="Port number")
        def deploy(ctx, host, port):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["deploy"]
        assert len(cmd["constraints"]) == 1
        c = cmd["constraints"][0]
        assert c["type"] == "requires"
        assert c["flag"] == "port"
        assert c["depends_on"] == "host"

    def test_implies(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("deploy", help="Deploy",
                     dependencies=[strictcli.Implies(
                         flag="force-deploy", implies="yes", value=True)])
        @strictcli.flag("force-deploy", type=bool, default=False, help="Force deploy")
        @strictcli.flag("yes", type=bool, default=False, help="Skip confirmation")
        def deploy(ctx, force_deploy, yes):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["deploy"]
        assert len(cmd["constraints"]) == 1
        c = cmd["constraints"][0]
        assert c["type"] == "implies"
        assert c["flag"] == "force-deploy"
        assert c["implies"] == "yes"
        assert c["value"] is True

    def test_multiple_constraints(self, tmp_path, monkeypatch):
        """Multiple constraint types on the same command."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        json_flag = strictcli.Flag(name="json", type=bool, default=False, help="JSON output")
        text_flag = strictcli.Flag(name="text", type=bool, default=False, help="Text output")

        @app.command("deploy", help="Deploy",
                     mutex=[strictcli.MutexGroup(flags=[json_flag, text_flag])],
                     dependencies=[
                         strictcli.CoRequired(flags=["host", "port"]),
                         strictcli.Requires(flag="port", depends_on="host"),
                     ])
        @strictcli.flag("host", type=str, help="Hostname")
        @strictcli.flag("port", type=int, help="Port number")
        def deploy(ctx, json, text, host, port):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["deploy"]
        assert len(cmd["constraints"]) == 3
        types = [c["type"] for c in cmd["constraints"]]
        assert types == ["mutex", "co_required", "requires"]

    def test_constraint_flag_names_use_dashes(self, tmp_path, monkeypatch):
        """Constraint flag names should use dashes (flag names), not underscores."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("deploy", help="Deploy",
                     dependencies=[strictcli.CoRequired(
                         flags=["dry-run", "skip-confirm"])])
        @strictcli.flag("dry-run", type=bool, default=False, help="Dry run")
        @strictcli.flag("skip-confirm", type=bool, default=False, help="Skip confirmation")
        def deploy(ctx, dry_run, skip_confirm):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["deploy"]
        c = cmd["constraints"][0]
        assert c["flags"] == ["dry-run", "skip-confirm"]


class TestSchemaTagContracts:
    """Schema serializes tag contracts at app level."""

    def test_no_tag_contracts_omitted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "tag_contracts" not in data

    def test_tag_contracts_serialized(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        app.tag_contract("dangerous", requires_flag="force-deploy")

        @app.command("deploy", help="Deploy", tags=["dangerous"])
        @strictcli.flag("force-deploy", type=bool, default=False, help="Force it")
        def deploy(ctx, force_deploy):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert "tag_contracts" in data
        assert data["tag_contracts"] == {"dangerous": "force-deploy"}

    def test_multiple_tag_contracts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        app.tag_contract("dangerous", requires_flag="force-deploy")
        app.tag_contract("slow", requires_flag="timeout")

        @app.command("deploy", help="Deploy", tags=["dangerous", "slow"])
        @strictcli.flag("force-deploy", type=bool, default=False, help="Force it")
        @strictcli.flag("timeout", type=int, help="Timeout", default=30)
        def deploy(ctx, force_deploy, timeout):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["tag_contracts"] == {
            "dangerous": "force-deploy",
            "slow": "timeout",
        }


class TestSchemaArgDefaults:
    """Schema serializes arg defaults when present."""

    def test_arg_default_omitted_when_missing(self, tmp_path, monkeypatch):
        """Required args with no default omit the default field."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command",
                     args=[strictcli.Arg(name="target", help="The target")])
        def cmd(ctx, target):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        arg = data["commands"]["cmd"]["args"][0]
        assert "default" not in arg

    def test_arg_default_string(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command",
                     args=[strictcli.Arg(name="target", help="The target",
                                         required=False, default="localhost")])
        def cmd(ctx, target):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        arg = data["commands"]["cmd"]["args"][0]
        assert arg["default"] == "localhost"

    def test_arg_default_none(self, tmp_path, monkeypatch):
        """An optional arg with default=None should serialize the default."""
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command",
                     args=[strictcli.Arg(name="target", help="The target",
                                         required=False, default=None)])
        def cmd(ctx, target):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        arg = data["commands"]["cmd"]["args"][0]
        assert arg["default"] is None


class TestSchemaProjectIdMismatch:
    """Schema dump refuses to overwrite a schema belonging to a different project."""

    def test_mismatch_raises_error(self, tmp_path, monkeypatch):
        """Existing schema with a different project_id causes an error."""
        monkeypatch.chdir(tmp_path)
        schema_dir = tmp_path / ".strictcli"
        schema_dir.mkdir()
        (schema_dir / "schema.json").write_text(
            json.dumps({"project_id": "other-project"})
        )
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code != 0
        assert "Schema mismatch" in result.stderr
        assert "other-project" in result.stderr
        assert "testproject" in result.stderr

    def test_match_no_error(self, tmp_path, monkeypatch):
        """Existing schema with the same project_id succeeds."""
        monkeypatch.chdir(tmp_path)
        schema_dir = tmp_path / ".strictcli"
        schema_dir.mkdir()
        (schema_dir / "schema.json").write_text(
            json.dumps({"project_id": "testproject"})
        )
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0

    def test_missing_file_no_error(self, tmp_path, monkeypatch):
        """No existing schema file passes through without error."""
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / ".strictcli" / "schema.json").exists()
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0

    def test_corrupt_file_no_error(self, tmp_path, monkeypatch):
        """Corrupt (non-JSON) schema file passes through without error."""
        monkeypatch.chdir(tmp_path)
        schema_dir = tmp_path / ".strictcli"
        schema_dir.mkdir()
        (schema_dir / "schema.json").write_text("not valid json {{{")
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop(ctx):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0


class TestDumpSchemaDict:
    """App.dump_schema_dict() returns the CWD-free schema core dict."""

    def test_returns_version_without_project_id(self, tmp_path, monkeypatch):
        # Run from a directory with NO pyproject.toml to prove no CWD access.
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet(ctx):
            pass

        d = app.dump_schema_dict()
        assert d["schema_version"] == 1
        assert d["version"] == "1.0.0"
        assert d["name"] == "testapp"
        assert "project_id" not in d
        assert "commands" in d

    def test_no_pyproject_does_not_raise(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty2"
        empty.mkdir()
        monkeypatch.chdir(empty)
        assert not (empty / "pyproject.toml").exists()
        app = _make_app()
        # Must not raise even though _read_project_id() would.
        d = app.dump_schema_dict()
        assert isinstance(d, dict)

    def test_equals_file_writer_minus_project_id(self, tmp_path, monkeypatch):
        # tmp_path has a pyproject.toml (autouse fixture), so the file writer works.
        monkeypatch.chdir(tmp_path)
        app = _make_app(env_prefix="TESTAPP")

        @app.command("greet", help="Say hello")
        @strictcli.flag("loud", type=bool, help="be loud", default=False)
        def greet(ctx, loud):
            pass

        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        written = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        method = app.dump_schema_dict()

        # File-writer output minus project_id must equal the method output.
        written_minus = {k: v for k, v in written.items() if k != "project_id"}
        assert written_minus == method

        # Byte-identical by construction: serializing the method output equals
        # serializing the file output with the project_id key removed.
        assert json.dumps(method, indent=2) == json.dumps(written_minus, indent=2)


class TestSchemaMarkerDefault:
    """A RelativeToRoot marker default serializes machine-stably.

    Regression: previously the raw marker was assigned to d["default"] and
    json.dumps crashed with TypeError. The marker must serialize as
    {"relative_to_root": {"env_var": ..., "parts": [...]}} -- only the declared
    env var and path parts, never a resolved machine-specific path -- and
    identically across the Python and Go implementations.
    """

    def test_command_and_global_flag_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("MYAPP_HOME", raising=False)
        app = _make_app(
            infra_root={"MYAPP_HOME": "/var/lib/myapp"},
            flags=[
                strictcli.Flag(
                    name="global-db",
                    type=str,
                    help="global db path",
                    default=strictcli.RelativeToRoot("MYAPP_HOME", "global.sqlite"),
                )
            ],
        )

        @app.command("run", help="run it")
        @strictcli.flag(
            "db",
            help="db path",
            default=strictcli.RelativeToRoot("MYAPP_HOME", "sub", "db.sqlite"),
        )
        def run(ctx, db):
            return 0

        # The full --dump-schema round-trip must not crash and must write the
        # machine-stable marker shape.
        result = app.test(["--dump-schema"])
        assert result.exit_code == 0
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())

        want_global = {
            "relative_to_root": {"env_var": "MYAPP_HOME", "parts": ["global.sqlite"]}
        }
        assert data["global_flags"][0]["default"] == want_global

        cmd_flag = data["commands"]["run"]["flags"][0]
        want_cmd = {
            "relative_to_root": {
                "env_var": "MYAPP_HOME",
                "parts": ["sub", "db.sqlite"],
            }
        }
        assert cmd_flag["default"] == want_cmd

        # No resolved/machine-specific joined path leaks into the schema. The
        # infra roots section legitimately carries the declared default root,
        # but the marker must never emit the root joined with its parts.
        dumped = json.dumps(data)
        assert "/var/lib/myapp/global.sqlite" not in dumped
        assert "/var/lib/myapp/sub/db.sqlite" not in dumped
