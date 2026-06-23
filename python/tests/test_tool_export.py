"""Tests for tool export: json_schema(), as_tools(), Tool, and router."""

import asyncio

import pytest

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


# ---------------------------------------------------------------------------
# json_schema() tests
# ---------------------------------------------------------------------------


class TestJsonSchemaBasicTypes:
    """json_schema produces correct JSON Schema types for str/int/float/bool."""

    def test_str_flag(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("name", type=str, help="a name")
        def cmd(name):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["name"]["type"] == "string"

    def test_int_flag(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("count", type=int, help="a count")
        def cmd(count):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["count"]["type"] == "integer"

    def test_float_flag(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("factor", type=float, help="a factor")
        def cmd(factor):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["factor"]["type"] == "number"

    def test_bool_flag(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("verbose", type=bool, help="verbose mode")
        def cmd(verbose):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["verbose"]["type"] == "boolean"

    def test_all_types_together(self):
        app = _build_app()

        @app.command("cmd", help="multi-type command")
        @strictcli.flag("name", type=str, help="string flag")
        @strictcli.flag("count", type=int, help="integer flag")
        @strictcli.flag("factor", type=float, help="number flag")
        @strictcli.flag("verbose", type=bool, help="boolean flag")
        def cmd(name, count, factor, verbose):
            pass

        schema = app.json_schema("cmd")
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["count"]["type"] == "integer"
        assert schema["properties"]["factor"]["type"] == "number"
        assert schema["properties"]["verbose"]["type"] == "boolean"


class TestJsonSchemaRequired:
    """json_schema correctly populates the 'required' array."""

    def test_required_str_flag(self):
        """Scalar str flag with no default is required."""
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("name", type=str, help="required name")
        def cmd(name):
            pass

        schema = app.json_schema("cmd")
        assert "name" in schema["required"]

    def test_optional_str_flag(self):
        """Scalar str flag with a default is optional."""
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("name", type=str, default="world", help="optional name")
        def cmd(name):
            pass

        schema = app.json_schema("cmd")
        assert "name" not in schema["required"]

    def test_bool_flag_never_required(self):
        """Bool flags always have a default (False), so never required."""
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("verbose", type=bool, help="verbose mode")
        def cmd(verbose):
            pass

        schema = app.json_schema("cmd")
        assert "verbose" not in schema["required"]

    def test_repeatable_flag_never_required(self):
        """Repeatable (list) flags have default [], so never required."""
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("items", type=list[int], help="item list", unique=False)
        def cmd(items):
            pass

        schema = app.json_schema("cmd")
        assert "items" not in schema["required"]

    def test_dict_flag_never_required(self):
        """Dict flags have default {}, so never required."""
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("labels", type=dict[str, str], help="label map")
        def cmd(labels):
            pass

        schema = app.json_schema("cmd")
        assert "labels" not in schema["required"]

    def test_required_arg(self):
        """A required positional arg appears in 'required'."""
        app = _build_app()

        @app.command("cmd", help="a command", args=[strictcli.Arg(name="target", help="the target")])
        def cmd(target):
            pass

        schema = app.json_schema("cmd")
        assert "target" in schema["required"]

    def test_optional_arg(self):
        """An optional positional arg does not appear in 'required'."""
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="target", help="the target", required=False),
        ])
        def cmd(target):
            pass

        schema = app.json_schema("cmd")
        assert "target" not in schema["required"]


class TestJsonSchemaChoices:
    """json_schema includes 'enum' for flags/args with choices."""

    def test_flag_choices(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("env", type=str, choices=["dev", "staging", "prod"], help="environment")
        def cmd(env):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["env"]["enum"] == ["dev", "staging", "prod"]

    def test_arg_choices(self):
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="level", help="log level", choices=["debug", "info", "warn"]),
        ])
        def cmd(level):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["level"]["enum"] == ["debug", "info", "warn"]

    def test_no_choices_no_enum(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("name", type=str, help="a name")
        def cmd(name):
            pass

        schema = app.json_schema("cmd")
        assert "enum" not in schema["properties"]["name"]


class TestJsonSchemaDescription:
    """json_schema includes 'description' from help text."""

    def test_flag_description(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("name", type=str, help="the person's name")
        def cmd(name):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["name"]["description"] == "the person's name"

    def test_arg_description(self):
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="target", help="deployment target"),
        ])
        def cmd(target):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["target"]["description"] == "deployment target"


class TestJsonSchemaPositionalArgs:
    """json_schema includes positional args as properties."""

    def test_single_arg(self):
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="filename", help="file to process"),
        ])
        def cmd(filename):
            pass

        schema = app.json_schema("cmd")
        assert "filename" in schema["properties"]
        assert schema["properties"]["filename"]["type"] == "string"

    def test_typed_arg(self):
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="port", help="port number", type=int),
        ])
        def cmd(port):
            pass

        schema = app.json_schema("cmd")
        assert schema["properties"]["port"]["type"] == "integer"

    def test_flags_and_args_combined(self):
        """Both flags and args appear in properties."""
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="target", help="the target"),
        ])
        @strictcli.flag("verbose", type=bool, help="verbose mode")
        def cmd(target, verbose):
            pass

        schema = app.json_schema("cmd")
        assert "target" in schema["properties"]
        assert "verbose" in schema["properties"]


class TestJsonSchemaListFlag:
    """json_schema produces array schema for list[T] flags."""

    def test_list_int(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("ids", type=list[int], help="list of ids", unique=False)
        def cmd(ids):
            pass

        schema = app.json_schema("cmd")
        prop = schema["properties"]["ids"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "integer"}

    def test_list_str(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("tags", type=list[str], help="tag list", unique=False)
        def cmd(tags):
            pass

        schema = app.json_schema("cmd")
        prop = schema["properties"]["tags"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}

    def test_list_float(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("weights", type=list[float], help="weight list", unique=False)
        def cmd(weights):
            pass

        schema = app.json_schema("cmd")
        prop = schema["properties"]["weights"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "number"}


class TestJsonSchemaDictFlag:
    """json_schema produces object schema for dict[str, T] flags."""

    def test_dict_str_str(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("labels", type=dict[str, str], help="label map")
        def cmd(labels):
            pass

        schema = app.json_schema("cmd")
        prop = schema["properties"]["labels"]
        assert prop["type"] == "object"
        assert prop["additionalProperties"] == {"type": "string"}

    def test_dict_str_int(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("counts", type=dict[str, int], help="count map")
        def cmd(counts):
            pass

        schema = app.json_schema("cmd")
        prop = schema["properties"]["counts"]
        assert prop["type"] == "object"
        assert prop["additionalProperties"] == {"type": "integer"}


class TestJsonSchemaNestedPath:
    """json_schema resolves nested command paths."""

    def test_group_command(self):
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        @strictcli.flag("dry-run", type=bool, help="dry run mode")
        def migrate(dry_run):
            pass

        schema = app.json_schema("db.migrate")
        assert "dry_run" in schema["properties"]
        assert schema["properties"]["dry_run"]["type"] == "boolean"

    def test_deeply_nested(self):
        app = _build_app()
        grp1 = app.group("cloud", help="cloud commands")
        grp2 = grp1.group("storage", help="storage commands")

        @grp2.command("upload", help="upload a file")
        @strictcli.flag("bucket", type=str, help="target bucket")
        def upload(bucket):
            pass

        schema = app.json_schema("cloud.storage.upload")
        assert "bucket" in schema["properties"]
        assert schema["properties"]["bucket"]["type"] == "string"


class TestJsonSchemaInvalidPath:
    """json_schema raises InvokeError for invalid command paths."""

    def test_unknown_command(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd():
            pass

        with pytest.raises(strictcli.InvokeError, match="unknown command"):
            app.json_schema("nonexistent")

    def test_group_path_without_command(self):
        """Resolving a group (not a leaf command) raises InvokeError."""
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        def migrate():
            pass

        with pytest.raises(strictcli.InvokeError, match="is a group"):
            app.json_schema("db")


class TestJsonSchemaFlagNameConversion:
    """Flags with dashes become underscore property names."""

    def test_dashed_flag(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("dry-run", type=bool, help="dry run mode")
        def cmd(dry_run):
            pass

        schema = app.json_schema("cmd")
        assert "dry_run" in schema["properties"]
        assert "dry-run" not in schema["properties"]


class TestJsonSchemaVariadicArg:
    """Variadic list args produce array schema."""

    def test_variadic_list_int(self):
        app = _build_app()

        @app.command("cmd", help="a command", args=[
            strictcli.Arg(name="numbers", help="numbers to sum", type=list[int], variadic=True),
        ])
        def cmd(numbers):
            pass

        schema = app.json_schema("cmd")
        prop = schema["properties"]["numbers"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "integer"}


class TestJsonSchemaStructure:
    """json_schema returns a well-formed JSON Schema object."""

    def test_top_level_keys(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        @strictcli.flag("name", type=str, help="a name")
        def cmd(name):
            pass

        schema = app.json_schema("cmd")
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        assert schema["additionalProperties"] is False

    def test_empty_command(self):
        """Command with no flags or args produces empty properties."""
        app = _build_app()

        @app.command("noop", help="does nothing")
        def noop():
            pass

        schema = app.json_schema("noop")
        assert schema["properties"] == {}
        assert schema["required"] == []


# ---------------------------------------------------------------------------
# as_tools() tests
# ---------------------------------------------------------------------------


class TestAsToolsCount:
    """as_tools returns the correct number of Tool objects."""

    def test_single_command(self):
        """One command produces 2 tools (1 command + 1 router)."""
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        assert len(tools) == 2

    def test_multiple_commands(self):
        """N commands produce N+1 tools."""
        app = _build_app()

        @app.command("deploy", help="deploy")
        def deploy():
            pass

        @app.command("status", help="show status")
        def status():
            pass

        @app.command("rollback", help="rollback")
        def rollback():
            pass

        tools = app.as_tools()
        assert len(tools) == 4  # 3 commands + 1 router

    def test_grouped_commands(self):
        """Commands in groups are counted as leaf commands."""
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        def migrate():
            pass

        @grp.command("seed", help="seed data")
        def seed():
            pass

        tools = app.as_tools()
        assert len(tools) == 3  # 2 commands + 1 router


class TestAsToolsHiddenExcluded:
    """Hidden commands are excluded from as_tools."""

    def test_hidden_command_excluded(self):
        app = _build_app()

        @app.command("visible", help="a visible command")
        def visible():
            pass

        @app.command("secret", help="a hidden command", hidden=True)
        def secret():
            pass

        tools = app.as_tools()
        tool_names = [t.name for t in tools]
        assert "visible" in tool_names
        assert "secret" not in tool_names

    def test_hidden_group_excluded(self):
        """All commands in a hidden group are excluded."""
        app = _build_app()

        @app.command("visible", help="a visible command")
        def visible():
            pass

        grp = app.group("internal", help="internal commands", hidden=True)

        @grp.command("debug", help="debug command")
        def debug():
            pass

        tools = app.as_tools()
        tool_names = [t.name for t in tools]
        assert "visible" in tool_names
        assert "internal.debug" not in tool_names


class TestAsToolsInteractiveExcluded:
    """Interactive commands are excluded from as_tools."""

    def test_interactive_command_excluded(self):
        app = _build_app()

        @app.command("batch", help="batch operation")
        def batch():
            pass

        @app.command("wizard", help="interactive wizard", interactive=True)
        def wizard():
            pass

        tools = app.as_tools()
        tool_names = [t.name for t in tools]
        assert "batch" in tool_names
        assert "wizard" not in tool_names


class TestAsToolsConfigCommands:
    """Config auto-commands: show/set/path/init included, edit excluded."""

    def test_config_edit_excluded_others_included(self):
        app = _build_app(config=True)

        @app.command("run", help="run the app")
        def run():
            pass

        tools = app.as_tools()
        tool_names = [t.name for t in tools]

        # Non-interactive config commands are included
        assert "config.show" in tool_names
        assert "config.set" in tool_names
        assert "config.path" in tool_names
        assert "config.init" in tool_names

        # Interactive config edit is excluded
        assert "config.edit" not in tool_names


class TestAsToolsToolAttributes:
    """Each Tool has the expected attributes."""

    def test_tool_has_name(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        assert deploy_tool.name == "deploy"

    def test_tool_has_description(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        assert deploy_tool.description == "deploy the app"

    def test_tool_has_parameters(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        @strictcli.flag("target", type=str, help="deploy target")
        def deploy(target):
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        assert deploy_tool.parameters["type"] == "object"
        assert "target" in deploy_tool.parameters["properties"]

    def test_tool_has_execute(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        assert callable(deploy_tool.execute)


class TestAsToolsExecuteIsAsync:
    """Tool.execute is an async callable."""

    def test_execute_is_coroutine_function(self):
        import asyncio
        import inspect

        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        assert inspect.iscoroutinefunction(deploy_tool.execute)


class TestAsToolsGroupedPaths:
    """Tools from groups have dot-separated paths as names."""

    def test_grouped_tool_name(self):
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        def migrate():
            pass

        tools = app.as_tools()
        tool_names = [t.name for t in tools]
        assert "db.migrate" in tool_names

    def test_deeply_nested_tool_name(self):
        app = _build_app()
        grp1 = app.group("cloud", help="cloud commands")
        grp2 = grp1.group("storage", help="storage commands")

        @grp2.command("upload", help="upload a file")
        def upload():
            pass

        tools = app.as_tools()
        tool_names = [t.name for t in tools]
        assert "cloud.storage.upload" in tool_names


# ---------------------------------------------------------------------------
# Router tool tests
# ---------------------------------------------------------------------------


class TestRouterTool:
    """The router tool lists commands and dispatches via execute."""

    def test_router_is_last(self):
        """Router tool is the last tool in the list."""
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        router = tools[-1]
        assert router.name == "myapp"

    def test_router_description(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        tools = app.as_tools()
        router = tools[-1]
        assert router.description == "Route to myapp commands"

    def test_router_lists_commands(self):
        """Router execute with no command returns the list of available commands."""
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        @app.command("status", help="show status")
        def status():
            pass

        tools = app.as_tools()
        router = tools[-1]
        result = asyncio.run(router.execute(command=None))
        assert isinstance(result, list)
        assert "deploy" in result
        assert "status" in result

    def test_router_dispatches(self):
        """Router execute with command dispatches to acall."""
        captured = {}
        app = _build_app()

        @app.command("greet", help="greet someone")
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(name):
            captured["name"] = name
            return {"greeting": f"hello {name}"}

        tools = app.as_tools()
        router = tools[-1]
        result = asyncio.run(router.execute(command="greet", name="Alice"))
        assert captured["name"] == "Alice"
        assert result == {"greeting": "hello Alice"}

    def test_router_parameters_schema(self):
        """Router has a well-formed parameters schema with command enum."""
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy():
            pass

        @app.command("status", help="show status")
        def status():
            pass

        tools = app.as_tools()
        router = tools[-1]
        params = router.parameters
        assert params["type"] == "object"
        assert "command" in params["properties"]
        assert params["properties"]["command"]["type"] == "string"
        assert set(params["properties"]["command"]["enum"]) == {"deploy", "status"}
        assert "command" in params["required"]
        assert params["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Tool.execute tests
# ---------------------------------------------------------------------------


class TestToolExecute:
    """Tool.execute wraps acall and returns structured data."""

    def test_execute_returns_handler_result(self):
        app = _build_app()

        @app.command("info", help="get info")
        def info():
            return {"version": "1.0.0", "status": "ok"}

        tools = app.as_tools()
        info_tool = next(t for t in tools if t.name == "info")
        result = asyncio.run(info_tool.execute())
        assert result == {"version": "1.0.0", "status": "ok"}

    def test_execute_with_kwargs(self):
        captured = {}
        app = _build_app()

        @app.command("deploy", help="deploy")
        @strictcli.flag("target", type=str, help="deploy target")
        @strictcli.flag("count", type=int, default=1, help="instance count")
        def deploy(target, count):
            captured.update({"target": target, "count": count})
            return {"deployed": target, "count": count}

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        result = asyncio.run(deploy_tool.execute(target="prod", count=3))
        assert captured["target"] == "prod"
        assert captured["count"] == 3
        assert result == {"deployed": "prod", "count": 3}

    def test_execute_returns_none(self):
        app = _build_app()

        @app.command("noop", help="does nothing")
        def noop():
            pass

        tools = app.as_tools()
        noop_tool = next(t for t in tools if t.name == "noop")
        result = asyncio.run(noop_tool.execute())
        assert result is None

    def test_execute_returns_int(self):
        app = _build_app()

        @app.command("count", help="count things")
        def count():
            return 42

        tools = app.as_tools()
        count_tool = next(t for t in tools if t.name == "count")
        result = asyncio.run(count_tool.execute())
        assert result == 42


class TestToolExecuteErrors:
    """Tool.execute raises InvokeError on validation failures."""

    def test_missing_required_flag(self):
        app = _build_app()

        @app.command("deploy", help="deploy")
        @strictcli.flag("target", type=str, help="deploy target")
        def deploy(target):
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        with pytest.raises(strictcli.InvokeError):
            asyncio.run(deploy_tool.execute())

    def test_unknown_kwarg(self):
        app = _build_app()

        @app.command("deploy", help="deploy")
        def deploy():
            pass

        tools = app.as_tools()
        deploy_tool = next(t for t in tools if t.name == "deploy")
        with pytest.raises(strictcli.InvokeError):
            asyncio.run(deploy_tool.execute(nonexistent="value"))

    def test_router_dispatch_unknown_command(self):
        app = _build_app()

        @app.command("deploy", help="deploy")
        def deploy():
            pass

        tools = app.as_tools()
        router = tools[-1]
        with pytest.raises(strictcli.InvokeError, match="unknown command"):
            asyncio.run(router.execute(command="nonexistent"))


class TestToolExecuteGroupedCommand:
    """Tool.execute works for commands inside groups."""

    def test_grouped_command_execute(self):
        captured = {}
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        @strictcli.flag("dry-run", type=bool, help="dry run mode")
        def migrate(dry_run):
            captured["dry_run"] = dry_run
            return {"migrated": True, "dry_run": dry_run}

        tools = app.as_tools()
        migrate_tool = next(t for t in tools if t.name == "db.migrate")
        result = asyncio.run(migrate_tool.execute(dry_run=True))
        assert captured["dry_run"] is True
        assert result == {"migrated": True, "dry_run": True}
