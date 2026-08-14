"""Tests for MCP projection: serve_mcp(), --mcp flag, JSON-RPC protocol."""

import io
import json

import pytest

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


#: The metadata every modern-era request carries (protocol 2026-07-28). The
#: helpers below splice it into any request that does not bring its own, so a
#: test that is not about the metadata itself reads as it always did.
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _as_modern(req):
    """Return `req` with the modern request metadata spliced in."""
    if req.get("method") == "initialize" or "method" not in req:
        return req
    params = dict(req.get("params") or {})
    if "_meta" in params:
        return req
    params["_meta"] = dict(MODERN_META)
    out = dict(req)
    out["params"] = params
    return out


def _send_request(app, *requests, era="modern"):
    """Send JSON-RPC requests to serve_mcp and return parsed responses.

    `era="modern"` splices the per-request metadata into every request that
    does not carry its own; `era="legacy"` sends them exactly as written, which
    is what a handshake-era client does.
    """
    lines = []
    for req in requests:
        if era == "modern":
            req = _as_modern(req)
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


def _send_one(app, request, era="modern"):
    """Send a single JSON-RPC request and return the single response."""
    responses = _send_request(app, request, era=era)
    assert len(responses) == 1
    return responses[0]


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestMcpInitialize:
    """The initialize method returns protocol info and server info."""

    def test_basic_initialize(self):
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
        })
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == "2025-11-25"
        assert result["capabilities"] == {
            "tools": {},
            "experimental": {"dev.smmh.strictcli/consequential-confirmation": {}},
        }
        assert result["serverInfo"]["name"] == "myapp"
        assert result["serverInfo"]["version"] == "1.0.0"

    def test_initialize_preserves_id(self):
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": "abc-123", "method": "initialize",
            "params": {},
        })
        assert resp["id"] == "abc-123"

    def test_initialize_reflects_app_name_and_version(self):
        app = strictcli.App(name="mytool", version="2.5.0", help="my tool")

        @app.command("run", effect="read_only", help="run something")
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

        @app.command("deploy", effect="read_only", help="deploy the app")
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

        @app.command("deploy", effect="read_only", help="deploy the app")
        def deploy(ctx):
            pass

        @app.command("status", effect="read_only", help="show status")
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

        @grp.command("migrate", effect="read_only", help="run migrations")
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

        @app.command("visible", effect="read_only", help="visible command")
        def visible(ctx):
            pass

        @app.command("secret", effect="read_only", help="hidden command", hidden=True)
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

        @app.command("batch", effect="read_only", help="batch operation")
        def batch(ctx):
            pass

        @app.command("wizard", effect="read_only", help="interactive wizard", interactive=True)
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

        @app.command("deploy", effect="read_only", help="deploy the app")
        @strictcli.flag("target", type=str, help="deploy target")
        @strictcli.flag("count", type=int, default=1, help="instance count")
        @strictcli.flag("loud", type=bool, default=False, help="loud mode")
        def deploy(ctx, target, count, loud):
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

        @app.command("info", effect="read_only", help="get info", payload_schema={})
        def info(ctx):
            ctx.payload({"version": "1.0.0", "status": "ok"})
            return strictcli.outcome()

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

        @app.command("deploy", effect="read_only", help="deploy", payload_schema={})
        @strictcli.flag("target", type=str, help="deploy target")
        @strictcli.flag("count", type=int, default=1, help="instance count")
        def deploy(ctx, target, count):
            captured.update({"target": target, "count": count})
            ctx.payload({"deployed": target, "count": count})
            return strictcli.outcome()

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

        @app.command("noop", effect="read_only", help="does nothing")
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

        @app.command("count", effect="read_only", help="count things")
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

        @grp.command("migrate", effect="read_only", help="run migrations", payload_schema={})
        @strictcli.flag("sim-run", type=bool, default=False, help="dry run mode")
        def migrate(ctx, sim_run):
            ctx.payload({"migrated": True, "sim_run": sim_run})
            return strictcli.outcome()

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 14, "method": "tools/call",
            "params": {"name": "db.migrate", "arguments": {"sim_run": True}},
        })
        content = resp["result"]["content"]
        parsed = json.loads(content[0]["text"])
        assert parsed == {"migrated": True, "sim_run": True}

    def test_call_unknown_tool(self):
        """Unknown tools surface as tool-result errors (isError), not -32602.

        Matches Go: the name is passed to Call, whose invocation error
        becomes error content in the result.
        """
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 15, "method": "tools/call",
            "params": {"name": "nonexistent", "arguments": {}},
        })
        assert "error" not in resp
        assert resp["result"]["isError"] is True
        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "unknown command 'nonexistent'"

    def test_call_missing_required_flag(self):
        app = _build_app()

        @app.command("deploy", effect="read_only", help="deploy")
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

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 17, "method": "tools/call",
            "params": {"arguments": {}},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "missing required parameter: name"

    def test_call_non_string_name(self):
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 19, "method": "tools/call",
            "params": {"name": 42, "arguments": {}},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "parameter 'name' must be a string"

    def test_call_non_object_arguments(self):
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 20, "method": "tools/call",
            "params": {"name": "cmd", "arguments": ["not", "an", "object"]},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "parameter 'arguments' must be an object"

    def test_call_no_arguments_key(self):
        """When 'arguments' is omitted, defaults to empty dict."""
        app = _build_app()

        @app.command("noop", effect="read_only", help="does nothing", payload_schema={})
        def noop(ctx):
            ctx.payload("ok")
            return strictcli.outcome()

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

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        responses = _send_request(app, {
            "jsonrpc": "2.0", "method": "notifications/initialized",
        })
        assert responses == []

    def test_notification_mixed_with_requests(self):
        """Notifications are silently consumed; requests get responses."""
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
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

        @app.command("cmd", effect="read_only", help="a command")
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

        @app.command("cmd", effect="read_only", help="a command")
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

        @app.command("cmd", effect="read_only", help="a command")
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

        @app.command("cmd", effect="read_only", help="a command")
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

        @app.command("greet", effect="read_only", help="greet someone", payload_schema={})
        @strictcli.flag("name", type=str, help="person to greet")
        def greet(ctx, name):
            captured["name"] = name
            ctx.payload({"greeting": f"hello {name}"})
            return strictcli.outcome()

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

        @app.command("cmd", effect="read_only", help="a command")
        def cmd(ctx):
            pass

        result = app.test(["--mcp"])
        assert result.exit_code == 1
        assert "--mcp" in result.stderr

    def test_mcp_flag_anywhere_in_argv(self):
        """--mcp is detected regardless of position in argv."""
        app = _build_app()

        @app.command("cmd", effect="read_only", help="a command")
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

        @grp2.command("upload", effect="read_only", help="upload a file", payload_schema={})
        @strictcli.flag("bucket", type=str, help="target bucket")
        def upload(ctx, bucket):
            ctx.payload({"uploaded_to": bucket})
            return strictcli.outcome()

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

        @app.command("fail", effect="read_only", help="always fails")
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

        @app.command("run", effect="read_only", help="run the app")
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

        @app.command("ok", effect="read_only", help="always succeeds", payload_schema={})
        def ok(ctx):
            ctx.payload("success")
            return strictcli.outcome()

        resp = _send_one(app, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "ok", "arguments": {}},
        })
        assert "isError" not in resp["result"]


# ---------------------------------------------------------------------------
# Effects classification and programmatic consent over MCP
# ---------------------------------------------------------------------------


def _consent_app():
    app = _build_app()

    @app.command("look", effect="read_only", help="look at things", payload_schema={})
    def look(ctx):
        ctx.payload({"looked": True})
        return strictcli.outcome()

    @app.command("release", effect="mutating", consequential=True,
                 help="release things", payload_schema={})
    def release(ctx):
        ctx.payload({"released": True})
        return strictcli.outcome()

    return app


def _call(app, name, **params):
    return _send_one(app, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, **params},
    })


class TestMcpToolsListClassification:
    """tools/list publishes the classification beside inputSchema."""

    def test_effect_and_consequential_are_published(self):
        resp = _send_one(_consent_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert tools["look"]["effect"] == "read_only"
        assert tools["release"]["effect"] == "mutating"
        assert tools["release"]["consequential"] is True

    def test_consequential_is_omitted_when_false(self):
        resp = _send_one(_consent_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert "consequential" not in tools["look"]

    def test_classification_is_not_in_the_input_schema(self):
        resp = _send_one(_consent_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        schema = tools["release"]["inputSchema"]
        assert "effect" not in schema["properties"]
        assert "consequential" not in schema["properties"]
        assert "approve_consequential" not in schema["properties"]


class TestMcpToolsCallConsent:
    """tools/call honours the confirmation requirement."""

    def test_unconsented_call_is_refused(self):
        # These clients declare no capabilities at all, so the modern answer is
        # the capability error rather than the seam's refusal, which is only
        # reachable from the legacy era now.
        resp = _call(_consent_app(), "release")
        assert resp["error"]["code"] == -32021

    def test_explicit_false_is_refused(self):
        resp = _call(_consent_app(), "release", approve_consequential=False)
        assert resp["error"]["code"] == -32021

    def test_consented_call_proceeds(self):
        resp = _call(_consent_app(), "release", approve_consequential=True)
        result = resp["result"]
        assert "isError" not in result
        assert json.loads(result["content"][0]["text"]) == {"released": True}

    def test_read_only_call_needs_no_consent(self):
        resp = _call(_consent_app(), "look")
        result = resp["result"]
        assert "isError" not in result
        assert json.loads(result["content"][0]["text"]) == {"looked": True}

    def test_non_boolean_consent_is_a_protocol_error(self):
        resp = _call(_consent_app(), "release", approve_consequential="yes")
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "parameter 'approve_consequential' must be a boolean"
        )

    def test_consent_inside_arguments_does_not_consent(self):
        """The command's argument namespace is not a consent channel."""
        resp = _send_one(_consent_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "release",
                "arguments": {"approve_consequential": True},
            },
        })
        # The consent never registered, so the command was still unconfirmed
        # and the call never reached it.
        assert resp["error"]["code"] == -32021


# ---------------------------------------------------------------------------
# The modern era (protocol 2026-07-28)
# ---------------------------------------------------------------------------


def _meta(**overrides):
    """The modern metadata block, with per-test overrides."""
    block = dict(MODERN_META)
    block.update(overrides)
    return block


def _modern_app():
    app = _build_app()

    @app.command("status", effect="read_only", help="show status")
    def status(ctx):
        return strictcli.outcome(0)

    return app


class TestMcpDiscover:
    """server/discover is the modern era's mandatory discovery call."""

    def test_discover_advertises_versions_capabilities_and_identity(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {},
        })
        result = resp["result"]
        assert result["resultType"] == "complete"
        assert result["supportedVersions"] == ["2026-07-28"]
        assert result["capabilities"]["tools"] == {}
        assert result["instructions"] == "test app"
        assert result["ttlMs"] == 3600000
        assert result["cacheScope"] == "public"
        assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
            "name": "myapp", "version": "1.0.0",
        }

    def test_discover_declares_the_confirmation_feature_by_name(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {},
        })
        assert resp["result"]["capabilities"]["extensions"] == {
            "dev.smmh.strictcli/consequential-confirmation": {},
        }


class TestMcpResultType:
    """Every modern result carries a resultType; legacy results carry none."""

    def test_tools_list_result_is_complete(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        assert resp["result"]["resultType"] == "complete"
        assert resp["result"]["ttlMs"] == 3600000
        assert resp["result"]["cacheScope"] == "public"

    def test_tools_call_result_is_complete(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "status", "arguments": {}},
        })
        assert resp["result"]["resultType"] == "complete"
        assert resp["result"]["_meta"]["io.modelcontextprotocol/serverInfo"][
            "name"
        ] == "myapp"

    def test_tool_error_result_is_complete_and_flagged(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        })
        assert resp["result"]["resultType"] == "complete"
        assert resp["result"]["isError"] is True


class TestMcpRequestMetadata:
    """Per-request metadata is validated, never inferred."""

    def test_a_request_without_metadata_is_refused(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        }, era="legacy")
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "missing required request metadata: "
            "_meta['io.modelcontextprotocol/protocolVersion']"
        )

    def test_meta_must_be_an_object(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": []},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "parameter '_meta' must be an object"

    def test_protocol_version_must_be_a_string(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{
                "io.modelcontextprotocol/protocolVersion": 2026,
            })},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "_meta['io.modelcontextprotocol/protocolVersion'] must be a string"
        )

    def test_client_capabilities_are_required(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            }},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "missing required request metadata: "
            "_meta['io.modelcontextprotocol/clientCapabilities']"
        )

    def test_client_capabilities_must_be_an_object(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{
                "io.modelcontextprotocol/clientCapabilities": "yes",
            })},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "_meta['io.modelcontextprotocol/clientCapabilities'] must be an object"
        )

    def test_client_info_must_be_an_object_when_present(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{
                "io.modelcontextprotocol/clientInfo": "ExampleClient",
            })},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "_meta['io.modelcontextprotocol/clientInfo'] must be an object"
        )

    def test_a_malformed_key_name_is_refused(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{"-bad./key": 1})},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "invalid _meta key name: '-bad./key'"

    def test_an_unknown_reserved_key_is_refused(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{"io.modelcontextprotocol/whatever": 1})},
        })
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == (
            "unrecognized reserved _meta key: "
            "'io.modelcontextprotocol/whatever'"
        )

    def test_a_vendor_key_is_carried_without_complaint(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{
                "com.example.mcp/thing": 1,
                "traceparent": "00-0af7651916cd43dd8448eb211c80319c"
                               "-00f067aa0ba902b7-01",
                "progressToken": 7,
            })},
        })
        assert resp["result"]["resultType"] == "complete"

    def test_client_info_and_log_level_are_accepted(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{
                "io.modelcontextprotocol/clientInfo": {
                    "name": "ExampleClient", "version": "1.0.0",
                },
                "io.modelcontextprotocol/logLevel": "debug",
            })},
        })
        assert resp["result"]["resultType"] == "complete"


class TestMcpVersionNegotiation:
    """A version this server does not speak is named, with what it does speak."""

    def test_unsupported_version_is_refused_with_the_supported_list(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"_meta": _meta(**{
                "io.modelcontextprotocol/protocolVersion": "1900-01-01",
            })},
        })
        assert resp["error"]["code"] == -32022
        assert resp["error"]["message"] == "Unsupported protocol version"
        assert resp["error"]["data"] == {
            "supported": ["2026-07-28"], "requested": "1900-01-01",
        }

    def test_an_unknown_modern_method_is_method_not_found(self):
        resp = _send_one(_modern_app(), {
            "jsonrpc": "2.0", "id": 1, "method": "resources/list", "params": {},
        })
        assert resp["error"]["code"] == -32601
        assert resp["error"]["message"] == "Method not found: resources/list"


class TestMcpEraSelection:
    """One process serves both eras; `initialize` selects the legacy one."""

    def test_initialize_latches_the_legacy_era_for_later_requests(self):
        responses = _send_request(
            _modern_app(),
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            era="legacy",
        )
        assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
        legacy_list = responses[1]["result"]
        assert "resultType" not in legacy_list
        assert "ttlMs" not in legacy_list
        assert [t["name"] for t in legacy_list["tools"]] == ["status"]

    def test_a_modern_request_is_served_modern_after_a_handshake(self):
        responses = _send_request(
            _modern_app(),
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list",
             "params": {"_meta": dict(MODERN_META)}},
            era="legacy",
        )
        assert responses[1]["result"]["resultType"] == "complete"

    def test_discover_is_not_reachable_from_the_legacy_era(self):
        responses = _send_request(
            _modern_app(),
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "server/discover",
             "params": {}},
            era="legacy",
        )
        assert responses[1]["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# The confirmation round-trip and its continuation state
# ---------------------------------------------------------------------------


class _Session:
    """A live MCP session in which a request may depend on an earlier reply.

    The continuation key and its spent-id set live in the server process, so a
    round-trip has to be driven through ONE serve_mcp call: a second call is a
    second server, and its state is deliberately worthless to the first.
    """

    def __init__(self, app):
        self.app = app
        self.out = io.StringIO()
        self.responses = []
        self._read = 0

    def run(self, *steps):
        def lines():
            for step in steps:
                request = step(self.responses) if callable(step) else step
                yield json.dumps(request) + "\n"
                self._drain()

        self.app.serve_mcp(input=lines(), output=self.out)
        self._drain()
        return self.responses

    def _drain(self):
        text = self.out.getvalue()[self._read:]
        self._read += len(text)
        for line in text.splitlines():
            if line.strip():
                self.responses.append(json.loads(line))


def _confirming_app():
    app = _build_app()

    @app.command(
        "release", effect="mutating", consequential=True, help="release it",
        payload_schema={},
    )
    def release(ctx):
        ctx.payload({"released": True})
        return strictcli.outcome()

    @app.command("look", effect="read_only", help="look around",
                 payload_schema={})
    def look(ctx):
        ctx.payload({"looked": True})
        return strictcli.outcome()

    return app


#: A client that can render a form elicitation, and one that cannot.
_ELICITING = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}},
    "io.modelcontextprotocol/clientInfo": {"name": "cli", "version": "1.0.0"},
}


def _call_request(req_id, **params):
    params.setdefault("_meta", dict(_ELICITING))
    return {
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": params,
    }


def _accept(proceed=True):
    return {
        "consequential-confirmation": {
            "action": "accept", "content": {"proceed": proceed},
        },
    }


def _state_of(response):
    return response["result"]["requestState"]


def _drive_confirmation(app, answers, *, tool="release", arguments=None, meta=None):
    """Ask, then answer: the two halves of one confirmation, in one session."""
    args = {} if arguments is None else arguments
    extra = {"_meta": meta} if meta is not None else {}
    return _Session(app).run(
        _call_request(1, name=tool, arguments=args, **extra),
        lambda seen: _call_request(
            2, name=tool, arguments=args,
            requestState=_state_of(seen[0]), inputResponses=answers, **extra,
        ),
    )


class TestMcpConfirmationRoundTrip:
    """A consequential tool asks, through the client, before it runs."""

    def test_an_unconsented_call_asks_for_confirmation(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={},
        ))
        result = resp["result"]
        assert result["resultType"] == "input_required"
        request = result["inputRequests"]["consequential-confirmation"]
        assert request["method"] == "elicitation/create"
        assert request["params"]["mode"] == "form"
        assert request["params"]["message"] == (
            "about to run consequential command 'release'. Proceed?"
        )
        assert request["params"]["requestedSchema"]["required"] == ["proceed"]
        assert isinstance(result["requestState"], str)
        assert result["requestState"] != ""

    def test_a_retry_carrying_acceptance_proceeds(self):
        responses = _drive_confirmation(_confirming_app(), _accept())
        result = responses[1]["result"]
        assert result["resultType"] == "complete"
        assert "isError" not in result
        assert json.loads(result["content"][0]["text"]) == {"released": True}

    def test_a_declined_confirmation_aborts(self):
        responses = _drive_confirmation(
            _confirming_app(),
            {"consequential-confirmation": {"action": "decline"}},
        )
        result = responses[1]["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "aborted"

    def test_a_cancelled_confirmation_aborts(self):
        responses = _drive_confirmation(
            _confirming_app(),
            {"consequential-confirmation": {"action": "cancel"}},
        )
        assert responses[1]["result"]["isError"] is True

    def test_an_acceptance_that_says_no_aborts(self):
        responses = _drive_confirmation(_confirming_app(), _accept(proceed=False))
        assert responses[1]["result"]["isError"] is True

    def test_a_missing_answer_asks_again_with_fresh_state(self):
        responses = _drive_confirmation(_confirming_app(), {})
        second = responses[1]["result"]
        assert second["resultType"] == "input_required"
        assert second["requestState"] != _state_of(responses[0])

    def test_a_read_only_tool_is_never_asked_about(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="look", arguments={},
        ))
        assert resp["result"]["resultType"] == "complete"

    def test_a_stated_consent_still_proceeds_without_the_round_trip(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={}, approve_consequential=True,
        ))
        assert resp["result"]["resultType"] == "complete"
        assert "isError" not in resp["result"]

    def test_a_client_without_elicitation_gets_the_capability_error(self):
        # The revision forbids sending an input request the client never said
        # it could fulfil, and assigns the code for saying so.
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={}, _meta=dict(MODERN_META),
        ))
        assert "result" not in resp
        assert resp["error"]["code"] == -32021
        assert resp["error"]["message"] == (
            "Server requires the elicitation capability for this request"
        )
        assert resp["error"]["data"] == {
            "requiredCapabilities": {"elicitation": {"form": {}}},
        }

    def test_a_url_only_client_gets_the_capability_error(self):
        meta = dict(MODERN_META)
        meta["io.modelcontextprotocol/clientCapabilities"] = {
            "elicitation": {"url": {}},
        }
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={}, _meta=meta,
        ))
        assert resp["error"]["code"] == -32021

    def test_a_read_only_tool_needs_no_declared_capability(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="look", arguments={}, _meta=dict(MODERN_META),
        ))
        assert resp["result"]["resultType"] == "complete"

    def test_a_stated_consent_needs_no_declared_capability(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={}, approve_consequential=True,
            _meta=dict(MODERN_META),
        ))
        assert resp["result"]["resultType"] == "complete"
        assert "isError" not in resp["result"]


def _handshake(*, elicitation=True, name="cli", version="1.0.0"):
    """The legacy opener: in that era the handshake IS the client's declaration."""
    caps = {"elicitation": {"form": {}}} if elicitation else {}
    return {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "capabilities": caps,
            "clientInfo": {"name": name, "version": version},
        },
    }


def _legacy_call(req_id, tool="release", **params):
    """A legacy tools/call: no per-request metadata, because that era has none."""
    params.setdefault("arguments", {})
    params["name"] = tool
    return {
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": params,
    }


def _answer(seen, result):
    """Answer the elicitation the server just sent, echoing its id."""
    return {"jsonrpc": "2.0", "id": seen[-1]["id"], "result": result}


class TestMcpLegacyConfirmation:
    """The handshake era asks with a request of its own, and shares the state."""

    def test_a_consequential_call_is_asked_over_a_server_request(self):
        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            lambda seen: _answer(
                seen, {"action": "accept", "content": {"proceed": True}},
            ),
        )
        ask = responses[1]
        assert ask["method"] == "elicitation/create"
        assert ask["params"]["mode"] == "form"
        assert ask["params"]["message"] == (
            "about to run consequential command 'release'. Proceed?"
        )
        assert ask["params"]["requestedSchema"]["required"] == ["proceed"]
        # The correlation id IS the continuation blob: one mint-and-verify path,
        # two delivery vehicles.
        assert isinstance(ask["id"], str) and "." in ask["id"]
        result = responses[2]["result"]
        assert "resultType" not in result
        assert "isError" not in result
        assert json.loads(result["content"][0]["text"]) == {"released": True}

    @pytest.mark.parametrize("answer", [
        {"action": "decline"},
        {"action": "cancel"},
        {"action": "accept", "content": {"proceed": False}},
        {"action": "accept"},
        "not an elicitation result",
    ])
    def test_anything_but_an_acceptance_aborts(self, answer):
        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            lambda seen: _answer(seen, answer),
        )
        result = responses[2]["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "aborted"

    def test_an_error_response_aborts(self):
        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            lambda seen: {
                "jsonrpc": "2.0", "id": seen[-1]["id"],
                "error": {"code": -32601, "message": "Method not found"},
            },
        )
        assert responses[2]["result"]["isError"] is True

    def test_an_answer_under_an_id_the_server_never_minted_confirms_nothing(self):
        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            lambda seen: {
                "jsonrpc": "2.0", "id": "not-the-blob",
                "result": {"action": "accept", "content": {"proceed": True}},
            },
        )
        # The stray response is discarded; the stream then ends without an
        # answer, which aborts.
        assert responses[2]["result"]["isError"] is True
        assert responses[2]["result"]["content"][0]["text"] == "aborted"

    def test_a_client_that_cannot_be_asked_gets_the_seams_refusal(self):
        responses = _Session(_confirming_app()).run(
            _handshake(elicitation=False),
            _legacy_call(2),
        )
        result = responses[1]["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == (
            "command 'release' is consequential: the call must carry confirmation"
        )

    def test_a_read_only_call_is_never_asked_about(self):
        responses = _Session(_confirming_app()).run(
            _handshake(), _legacy_call(2, tool="look"),
        )
        assert len(responses) == 2
        assert json.loads(
            responses[1]["result"]["content"][0]["text"]) == {"looked": True}

    def test_a_stated_consent_proceeds_without_asking(self):
        responses = _Session(_confirming_app()).run(
            _handshake(), _legacy_call(2, approve_consequential=True),
        )
        assert len(responses) == 2
        assert "isError" not in responses[1]["result"]

    def test_traffic_arriving_mid_exchange_is_held_not_dropped(self):
        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            lambda seen: _answer(
                seen, {"action": "accept", "content": {"proceed": True}},
            ),
        )
        # handshake, the elicitation, the tool result, and the interrupted
        # tools/list -- served after the call it interrupted, never dropped.
        assert [r.get("id") for r in responses][0] == 1
        assert responses[1]["method"] == "elicitation/create"
        assert responses[2]["id"] == 2
        assert responses[3]["id"] == 3
        assert [t["name"] for t in responses[3]["result"]["tools"]] == [
            "release", "look",
        ]

    def test_an_aborted_exchange_consumes_its_state(self):
        """Every legacy exit spends the blob -- an abort is not a free replay.

        The blob binds the same principal and the same request digest the modern
        era mints, and stays live for five minutes. An exchange that ended
        without consuming it therefore hands the client a `requestState` it can
        answer itself, on the modern path, for the very call it just aborted.
        """
        def replay(seen):
            ask = next(r for r in seen if r.get("method") == "elicitation/create")
            return _call_request(
                3, name="release", arguments={},
                requestState=ask["id"], inputResponses=_accept(),
            )

        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            # A JSON-RPC error answers the elicitation: the exchange aborts.
            lambda seen: {
                "jsonrpc": "2.0", "id": seen[-1]["id"],
                "error": {"code": -32601, "message": "Method not found"},
            },
            replay,
        )
        assert responses[2]["result"]["isError"] is True
        assert "error" in responses[3], (
            f"the aborted blob was replayed and ran the command: {responses[3]}"
        )
        assert responses[3]["error"]["message"] == "requestState has already been used"

    def test_an_exchange_that_ends_unanswered_consumes_its_state(self):
        """The stream ending is an exit too, and it spends the blob as well."""
        def replay(seen):
            return _call_request(
                3, name="release", arguments={},
                requestState=seen[-1]["id"], inputResponses=_accept(),
            )

        responses = _Session(_confirming_app()).run(
            _handshake(),
            _legacy_call(2),
            # Held while the server waits; the stream then ends without an
            # answer, which aborts, and the held request is served afterwards.
            replay,
        )
        assert responses[2]["result"]["isError"] is True
        assert "error" in responses[3], (
            f"the aborted blob was replayed and ran the command: {responses[3]}"
        )
        assert responses[3]["error"]["message"] == "requestState has already been used"

    def test_a_modern_call_is_still_asked_the_modern_way_after_a_handshake(self):
        responses = _Session(_confirming_app()).run(
            _handshake(),
            _call_request(2, name="release", arguments={}),
        )
        assert responses[1]["result"]["resultType"] == "input_required"


class TestMcpContinuationState:
    """The state is attacker-controlled input, and is checked as such."""

    def test_a_tampered_state_is_refused(self):
        def tamper(seen):
            # The FIRST character: base64 decoders ignore the trailing bits of
            # a final character that does not fill a byte, so changing the last
            # character of the blob can decode to the identical bytes.
            state = _state_of(seen[0])
            broken = ("A" if state[0] != "A" else "B") + state[1:]
            return _call_request(
                2, name="release", arguments={},
                requestState=broken, inputResponses=_accept(),
            )

        responses = _Session(_confirming_app()).run(
            _call_request(1, name="release", arguments={}), tamper,
        )
        assert responses[1]["error"]["code"] == -32602
        assert responses[1]["error"]["message"] == (
            "requestState failed verification"
        )

    def test_a_forged_state_is_refused(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={},
            requestState="not-a-state", inputResponses=_accept(),
        ))
        assert resp["error"]["message"] == "requestState failed verification"

    def test_a_state_is_single_use(self):
        def retry(seen):
            return _call_request(
                2, name="release", arguments={},
                requestState=_state_of(seen[0]), inputResponses=_accept(),
            )

        def replay(seen):
            return _call_request(
                3, name="release", arguments={},
                requestState=_state_of(seen[0]), inputResponses=_accept(),
            )

        responses = _Session(_confirming_app()).run(
            _call_request(1, name="release", arguments={}), retry, replay,
        )
        assert responses[1]["result"]["resultType"] == "complete"
        assert responses[2]["error"]["message"] == (
            "requestState has already been used"
        )

    def test_a_state_does_not_travel_to_another_request(self):
        responses = _Session(_confirming_app()).run(
            _call_request(1, name="release", arguments={}),
            lambda seen: _call_request(
                2, name="release", arguments={"unexpected": 1},
                requestState=_state_of(seen[0]), inputResponses=_accept(),
            ),
        )
        assert responses[1]["error"]["message"] == (
            "requestState does not match this request"
        )

    def test_a_state_does_not_travel_to_another_client(self):
        other = dict(_ELICITING)
        other["io.modelcontextprotocol/clientInfo"] = {
            "name": "someone-else", "version": "1.0.0",
        }
        responses = _Session(_confirming_app()).run(
            _call_request(1, name="release", arguments={}),
            lambda seen: _call_request(
                2, name="release", arguments={}, _meta=other,
                requestState=_state_of(seen[0]), inputResponses=_accept(),
            ),
        )
        assert responses[1]["error"]["message"] == (
            "requestState was issued to a different client"
        )

    def test_an_answer_without_its_state_is_refused(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={}, inputResponses=_accept(),
        ))
        assert resp["error"]["message"] == (
            "parameter 'inputResponses' requires the requestState it was "
            "issued with"
        )

    def test_a_non_string_state_is_a_protocol_error(self):
        resp = _send_one(_confirming_app(), _call_request(
            1, name="release", arguments={}, requestState=7,
        ))
        assert resp["error"]["message"] == (
            "parameter 'requestState' must be a string"
        )

    def test_a_malformed_answer_is_a_protocol_error(self):
        responses = _Session(_confirming_app()).run(
            _call_request(1, name="release", arguments={}),
            lambda seen: _call_request(
                2, name="release", arguments={},
                requestState=_state_of(seen[0]),
                inputResponses={
                    "consequential-confirmation": {"action": "shrug"},
                },
            ),
        )
        assert responses[1]["error"]["message"] == (
            "inputResponses['consequential-confirmation'] is not an "
            "elicitation result"
        )

    def test_an_expired_state_is_refused(self):
        """No clock reaches the wire, so expiry is driven at the mint."""
        continuation = strictcli._MCPContinuation()
        now = 1_000_000.0
        ttl = strictcli._MCP_CONTINUATION_TTL_SECONDS
        state = continuation.mint("cli/1.0.0", "digest", now=now)
        assert continuation.verify(
            state, "cli/1.0.0", "digest", now=now + ttl - 1,
        ) is None
        fresh = continuation.mint("cli/1.0.0", "digest", now=now)
        assert continuation.verify(
            fresh, "cli/1.0.0", "digest", now=now + ttl + 1,
        ) == "requestState has expired"

    def test_a_state_is_worthless_to_another_process(self):
        one = strictcli._MCPContinuation()
        other = strictcli._MCPContinuation()
        state = one.mint("cli/1.0.0", "digest")
        assert other.verify(state, "cli/1.0.0", "digest") == (
            "requestState failed verification"
        )
