"""Tests for --dump-schema flag and schema serialization."""

from __future__ import annotations

import json
import os

import strictcli


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
        def greet():
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
        def greet():
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
        def noop():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["name"] == "myapp"
        assert data["version"] == "2.3.4"
        assert data["help"] == "My great app"

    def test_env_prefix_null_when_none(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("noop", help="Does nothing")
        def noop():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["env_prefix"] is None

    def test_env_prefix_when_set(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app(env_prefix="MYAPP")

        @app.command("noop", help="Does nothing")
        def noop():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["env_prefix"] == "MYAPP"

    def test_config_field(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app_no_config = _make_app(config=False)

        @app_no_config.command("noop", help="Does nothing")
        def noop():
            pass

        app_no_config.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        assert data["config"] is False


class TestSchemaCommands:
    """Schema contains commands with their flags and args."""

    def test_command_with_flags(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("deploy", help="Deploy the app")
        @strictcli.flag("target", type=str, help="Deploy target", short="t",
                        choices=["prod", "staging"])
        @strictcli.flag("force", type=bool, help="Force deploy")
        def deploy(target, force):
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
        assert target_flag["hidden"] is False

        force_flag = cmd["flags"][1]
        assert force_flag["name"] == "force"
        assert force_flag["type"] == "bool"
        assert force_flag["negatable"] is True
        assert force_flag["default"] is False

    def test_command_with_args(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Greet someone",
                     args=[strictcli.Arg(name="name", help="Who to greet")])
        def greet(name):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["greet"]
        assert len(cmd["args"]) == 1
        arg = cmd["args"][0]
        assert arg["name"] == "name"
        assert arg["help"] == "Who to greet"
        assert arg["required"] is True
        assert arg["variadic"] is False

    def test_passthrough_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("run", help="Run a command",
                     passthrough=strictcli.Passthrough(
                         handler=lambda name, args, globals: 0))
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
        def greet():
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        cmd = data["commands"]["greet"]
        assert cmd["passthrough"] is False


class TestSchemaGroups:
    """Schema contains groups (including nested groups)."""

    def test_group_with_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()
        dns = app.group("dns", help="DNS management")

        @dns.command("list", help="List DNS records")
        def dns_list():
            pass

        @dns.command("add", help="Add a DNS record")
        @strictcli.flag("type", type=str, help="Record type")
        def dns_add(type):
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
        def zone_list():
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
        def dns_list():
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
                strictcli.Flag(name="verbose", type=bool, help="Verbose output", short="V"),
                strictcli.Flag(name="output", type=str, help="Output format",
                               default="text", choices=["text", "json"]),
            ]
        )

        @app.command("noop", help="Does nothing")
        def noop(verbose, output):
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
        assert output["negatable"] is None  # non-bool flag


class TestSchemaDeprecated:
    """Schema contains deprecated commands."""

    def test_deprecated_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("new-cmd", help="The new command")
        def new_cmd():
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
        def noop():
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
        def noop():
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
        assert data["commands"] == {}
        assert data["groups"] == {}
        assert data["global_flags"] == []
        assert data["deprecated"] == {}


class TestSchemaFlagTypes:
    """Schema correctly serializes all flag types."""

    def test_int_flag(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("count", type=int, help="How many", default=5)
        def cmd(count):
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
        def cmd(ratio):
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
        @strictcli.flag("tag", type=str, help="A tag", repeatable=True)
        def cmd(tag):
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
        def cmd(token):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["env"] == "MYAPP_TOKEN"

    def test_bool_non_negatable(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("cmd", help="A command")
        @strictcli.flag("force", type=bool, help="Force it", negatable=False)
        def cmd(force):
            pass

        app.test(["--dump-schema"])
        data = json.loads((tmp_path / ".strictcli" / "schema.json").read_text())
        flag = data["commands"]["cmd"]["flags"][0]
        assert flag["negatable"] is False


class TestDumpSchemaWithOtherArgs:
    """--dump-schema is detected even when mixed with other args."""

    def test_dump_schema_with_command_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _make_app()

        @app.command("greet", help="Say hello")
        def greet():
            pass

        result = app.test(["greet", "--dump-schema"])
        assert result.exit_code == 0
        assert (tmp_path / ".strictcli" / "schema.json").exists()
