"""Tests for MCP projection: serve_mcp(), --mcp flag, JSON-RPC protocol."""

import io
import json

import pytest

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


def _send_request(app, *requests):
    """Send JSON-RPC requests to serve_mcp and return parsed responses."""
    lines = []
    for req in requests:
        lines.append(json.dumps(req))
    input_buf = io.StringIO("\n".join(lines) + "\n")
    output_buf = io.StringIO()
    app.serve_mcp(input=input_buf, output=output_buf)
    output_buf.seek(0)
    responses = []
    for line in output_buf:
        line = line.strip()
        if line:
            responses.append(json.loads(line))
    return responses


def _send_one(app, request):
    """Send a single JSON-RPC request and return the single response."""
    responses = _send_request(app, request)
    assert len(responses) == 1
    return responses[0]


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestMcpInitialize:
    """The initialize method returns protocol info and server info."""

    def test_basic_initialize(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
        })
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert result["capabilities"] == {"tools": {}}
        assert result["serverInfo"]["name"] == "myapp"
        assert result["serverInfo"]["version"] == "1.0.0"

    def test_initialize_preserves_id(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": "abc-123", "method": "initialize",
            "params": {},
        })
        assert resp["id"] == "abc-123"

    def test_initialize_reflects_app_name_and_version(self):
        app = strictcli.App(name="mytool", version="2.5.0", help="my tool")

        @app.command("run", help="run something")
        def run(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
        })
        assert resp["result"]["serverInfo"]["name"] == "mytool"
        assert resp["result"]["serverInfo"]["version"] == "2.5.0"


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


class TestMcpToolsList:
    """The tools/list method returns tool definitions for all eligible commands."""

    def test_single_command(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        @strictcli.flag("target", type=str, help="deploy target")
        def deploy(ctx, target):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        tools = resp["result"]["tools"]
        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "deploy"
        assert tool["description"] == "deploy the app"
        assert tool["inputSchema"]["type"] == "object"
        assert "target" in tool["inputSchema"]["properties"]

    def test_multiple_commands(self):
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        def deploy(ctx):
            pass

        @app.command("status", help="show status")
        def status(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {},
        })
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "deploy" in names
        assert "status" in names

    def test_grouped_commands(self):
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        def migrate(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {},
        })
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "db.migrate" in names

    def test_hidden_commands_excluded(self):
        app = _build_app()

        @app.command("visible", help="visible command")
        def visible(ctx):
            pass

        @app.command("secret", help="hidden command", hidden=True)
        def secret(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {},
        })
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "visible" in names
        assert "secret" not in names

    def test_interactive_commands_excluded(self):
        app = _build_app()

        @app.command("batch", help="batch operation")
        def batch(ctx):
            pass

        @app.command("wizard", help="interactive wizard", interactive=True)
        def wizard(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 6, "method": "tools/list", "params": {},
        })
        tools = resp["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "batch" in names
        assert "wizard" not in names

    def test_tool_input_schema_matches_json_schema(self):
        """The inputSchema in tools/list matches json_schema() output."""
        app = _build_app()

        @app.command("deploy", help="deploy the app")
        @strictcli.flag("target", type=str, help="deploy target")
        @strictcli.flag("count", type=int, default=1, help="instance count")
        @strictcli.flag("verbose", type=bool, default=False, help="verbose mode")
        def deploy(ctx, target, count, verbose):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {},
        })
        tool = resp["result"]["tools"][0]
        expected_schema = app.json_schema("deploy")
        assert tool["inputSchema"] == expected_schema


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------


class TestMcpToolsCall:
    """The tools/call method invokes commands and returns results."""

    def test_call_returns_result(self):
        app = _build_app()

        @app.command("info", help="get info")
        def info(ctx):
            return strictcli.outcome(data={"version": "1.0.0", "status": "ok"})

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": "info", "arguments": {}},
        })
        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        parsed = json.loads(content[0]["text"])
        assert parsed == {"version": "1.0.0", "status": "ok"}

    def test_call_with_arguments(self):
        captured = {}
        app = _build_app()

        @app.command("deploy", help="deploy")
        @strictcli.flag("target", type=str, help="deploy target")
        @strictcli.flag("count", type=int, default=1, help="instance count")
        def deploy(ctx, target, count):
            captured.update({"target": target, "count": count})
            return strictcli.outcome(data={"deployed": target, "count": count})

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": "deploy", "arguments": {"target": "prod", "count": 3}},
        })
        assert captured["target"] == "prod"
        assert captured["count"] == 3
        content = resp["result"]["content"]
        parsed = json.loads(content[0]["text"])
        assert parsed == {"deployed": "prod", "count": 3}

    def test_call_returns_none(self):
        app = _build_app()

        @app.command("noop", help="does nothing")
        def noop(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 12, "method": "tools/call",
            "params": {"name": "noop", "arguments": {}},
        })
        content = resp["result"]["content"]
        assert json.loads(content[0]["text"]) is None

    def test_call_returns_int(self):
        app = _build_app()

        @app.command("count", help="count things")
        def count(ctx):
            return 42

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 13, "method": "tools/call",
            "params": {"name": "count", "arguments": {}},
        })
        content = resp["result"]["content"]
        assert json.loads(content[0]["text"]) == 42

    def test_call_grouped_command(self):
        app = _build_app()
        grp = app.group("db", help="database commands")

        @grp.command("migrate", help="run migrations")
        @strictcli.flag("dry-run", type=bool, default=False, help="dry run mode")
        def migrate(ctx, dry_run):
            return strictcli.outcome(data={"migrated": True, "dry_run": dry_run})

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 14, "method": "tools/call",
            "params": {"name": "db.migrate", "arguments": {"dry_run": True}},
        })
        content = resp["result"]["content"]
        parsed = json.loads(content[0]["text"])
        assert parsed == {"migrated": True, "dry_run": True}

    def test_call_unknown_tool(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 15, "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        })
        assert resp["error"]["code"] == -32602
        assert "unknown tool" in resp["error"]["message"]

    def test_call_missing_required_flag(self):
        app = _build_app()

        @app.command("deploy", help="deploy")
        @strictcli.flag("target", type=str, help="deploy target")
        def deploy(ctx, target):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 16, "method": "tools/call",
            "params": {"name": "deploy", "arguments": {}},
        })
        # InvokeError results in isError content, not a JSON-RPC error
        assert resp["result"]["isError"] is True
        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"

    def test_call_missing_name(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 17, "method": "tools/call",
            "params": {"arguments": {}},
        })
        assert resp["error"]["code"] == -32602

    def test_call_no_arguments_key(self):
        """When 'arguments' is omitted, defaults to empty dict."""
        app = _build_app()

        @app.command("noop", help="does nothing")
        def noop(ctx):
            return strictcli.outcome(data="ok")

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 18, "method": "tools/call",
            "params": {"name": "noop"},
        })
        content = resp["result"]["content"]
        assert json.loads(content[0]["text"]) == "ok"


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestMcpNotifications:
    """Notifications (no 'id') produce no response."""

    def test_initialized_notification_no_response(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        responses = _send_request(app, {
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert responses == []

    def test_notification_mixed_with_requests(self):
        """Notifications are silently consumed; requests get responses."""
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        responses = _send_request(
            app,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert len(responses) == 1
        assert responses[0]["id"] == 1


# ---------------------------------------------------------------------------
# Protocol errors
# ---------------------------------------------------------------------------


class TestMcpProtocolErrors:
    """JSON-RPC protocol error handling."""

    def test_malformed_json(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        input_buf = io.StringIO("not valid json\n")
        output_buf = io.StringIO()
        app.serve_mcp(input=input_buf, output=output_buf)
        output_buf.seek(0)
        resp = json.loads(output_buf.readline())
        assert resp["error"]["code"] == -32700
        # Go-parity: message casing is "Parse error".
        assert resp["error"]["message"] == "Parse error"
        assert resp["id"] is None

    def test_unknown_method(self):
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 99, "method": "bogus/method", "params": {},
        })
        assert resp["error"]["code"] == -32601
        # Go-parity: message casing is "Method not found".
        assert "Method not found" in resp["error"]["message"]

    def test_non_object_json(self):
        """A non-object JSON line is a parse error (-32700), matching Go.

        Go unmarshals directly into a struct, so a bare array/number/string is a
        parse error. Python must redirect the (retained) non-dict guard to the
        same -32700 'Parse error' response rather than emitting -32600.
        """
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        input_buf = io.StringIO("[1, 2, 3]\n")
        output_buf = io.StringIO()
        app.serve_mcp(input=input_buf, output=output_buf)
        output_buf.seek(0)
        resp = json.loads(output_buf.readline())
        assert resp["error"]["code"] == -32700
        assert resp["error"]["message"] == "Parse error"

    def test_empty_lines_ignored(self):
        """Blank lines are silently skipped."""
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        input_buf = io.StringIO(
            "\n\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            + "\n\n"
        )
        output_buf = io.StringIO()
        app.serve_mcp(input=input_buf, output=output_buf)
        output_buf.seek(0)
        lines = [l.strip() for l in output_buf if l.strip()]
        assert len(lines) == 1
        resp = json.loads(lines[0])
        assert resp["id"] == 1


# ---------------------------------------------------------------------------
# Multi-request conversation
# ---------------------------------------------------------------------------


class TestMcpConversation:
    """A full MCP conversation: initialize, list, call."""

    def test_full_conversation(self):
        captured = {}
        app = _build_app()

        @app.command("greet", help="greet someone")
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(ctx, name):
            captured["name"] = name
            return strictcli.outcome(data={"greeting": f"hello {name}"})

        responses = _send_request(
            app,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "greet", "arguments": {"name": "Alice"}}},
        )
        assert len(responses) == 3

        # initialize response
        assert responses[0]["id"] == 1
        assert responses[0]["result"]["serverInfo"]["name"] == "myapp"

        # tools/list response
        assert responses[1]["id"] == 2
        tools = responses[1]["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "greet"

        # tools/call response
        assert responses[2]["id"] == 3
        parsed = json.loads(responses[2]["result"]["content"][0]["text"])
        assert parsed == {"greeting": "hello Alice"}
        assert captured["name"] == "Alice"


# ---------------------------------------------------------------------------
# --mcp flag interception
# ---------------------------------------------------------------------------


class TestMcpFlag:
    """The --mcp flag triggers MCP mode."""

    def test_mcp_flag_intercepted_in_test(self):
        """test(['--mcp']) returns an error since test mode can't do MCP."""
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        result = app.test(["--mcp"])
        assert result.exit_code == 1
        assert "--mcp" in result.stderr

    def test_mcp_flag_anywhere_in_argv(self):
        """--mcp is detected regardless of position in argv."""
        app = _build_app()

        @app.command("cmd", help="a command")
        def cmd(ctx):
            pass

        result = app.test(["cmd", "--mcp"])
        assert result.exit_code == 1
        assert "--mcp" in result.stderr


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestMcpEdgeCases:
    """Edge cases for the MCP server."""

    def test_deeply_nested_command(self):
        app = _build_app()
        grp1 = app.group("cloud", help="cloud commands")
        grp2 = grp1.group("storage", help="storage commands")

        @grp2.command("upload", help="upload a file")
        @strictcli.flag("bucket", type=str, help="target bucket")
        def upload(ctx, bucket):
            return strictcli.outcome(data={"uploaded_to": bucket})

        # tools/list includes deeply nested commands
        list_resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        names = [t["name"] for t in list_resp["result"]["tools"]]
        assert "cloud.storage.upload" in names

        # tools/call works for deeply nested commands
        call_resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "cloud.storage.upload",
                "arguments": {"bucket": "my-bucket"},
            },
        })
        parsed = json.loads(call_resp["result"]["content"][0]["text"])
        assert parsed == {"uploaded_to": "my-bucket"}

    def test_handler_exception_returns_error_content(self):
        """If a handler raises, tools/call returns isError content."""
        app = _build_app()

        @app.command("fail", help="always fails")
        def fail(ctx):
            raise RuntimeError("something broke")

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "fail", "arguments": {}},
        })
        assert resp["result"]["isError"] is True
        assert "something broke" in resp["result"]["content"][0]["text"]

    def test_config_commands_exposed(self):
        """Non-interactive config subcommands appear in tools/list."""
        app = _build_app(config=True)

        @app.command("run", help="run the app")
        def run(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        names = [t["name"] for t in resp["result"]["tools"]]
        assert "config.show" in names
        assert "config.set" in names
        assert "config.path" in names
        assert "config.init" in names
        # config.edit is interactive, should be excluded
        assert "config.edit" not in names

    def test_no_is_error_on_success(self):
        """Successful calls do not have isError in the result."""
        app = _build_app()

        @app.command("ok", help="always succeeds")
        def ok(ctx):
            return strictcli.outcome(data="success")

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "ok", "arguments": {}},
        })
        assert "isError" not in resp["result"]
