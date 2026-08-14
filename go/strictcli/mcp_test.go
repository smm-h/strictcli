package strictcli

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"testing"
)

// mcpTestApp creates a standard test app with commands for MCP testing.
func mcpTestApp() *App {
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("greet", "greet someone", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		fmt.Printf("Hello, %s!", kwargs["name"])
		return Exit(0)
	}, WithFlags(
		StringFlag("name", "who to greet"),
	), WithEffect(EffectReadOnly))
	app.Command("status", "check status", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.Command("secret", "hidden command", nopHandler, WithHidden(), WithEffect(EffectReadOnly))
	app.Command("wizard", "interactive wizard", nopHandler, WithInteractive(), WithEffect(EffectReadOnly))

	dns := app.Group("dns", "manage DNS")
	dns.Command("list", "list DNS records", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithFlags(
		StringFlag("zone", "DNS zone"),
	), WithEffect(EffectReadOnly))

	return app
}

// modernMeta is the metadata every modern-era request carries (protocol
// 2026-07-28). The helpers below splice it into any request that does not bring
// its own, so a test that is not about the metadata itself reads as it always
// did.
func modernMeta() map[string]interface{} {
	return map[string]interface{}{
		mcpMetaProtocolVersion:    mcpProtocolVersion,
		mcpMetaClientCapabilities: map[string]interface{}{},
	}
}

// asModern returns params carrying the modern request metadata.
func asModern(params map[string]interface{}) map[string]interface{} {
	out := map[string]interface{}{}
	for k, v := range params {
		out[k] = v
	}
	if _, ok := out["_meta"]; !ok {
		out["_meta"] = modernMeta()
	}
	return out
}

// sendMCPRequest sends a modern-era JSON-RPC request and reads the response.
func sendMCPRequest(app *App, method string, id interface{}, params map[string]interface{}) (map[string]interface{}, error) {
	if method != "initialize" {
		params = asModern(params)
	}
	return sendMCPRequestRaw(app, method, id, params)
}

// sendMCPRequestRaw sends a JSON-RPC request exactly as written -- no metadata
// is spliced in, which is what a handshake-era client sends.
func sendMCPRequestRaw(app *App, method string, id interface{}, params map[string]interface{}) (map[string]interface{}, error) {
	req := map[string]interface{}{
		"jsonrpc": "2.0",
		"method":  method,
	}
	if id != nil {
		req["id"] = id
	}
	if params != nil {
		req["params"] = params
	}

	reqData, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}

	in := strings.NewReader(string(reqData) + "\n")
	var out bytes.Buffer

	app.serveMCPIO(in, &out)

	// If this was a notification (no id), there should be no response
	if id == nil {
		if out.Len() > 0 {
			return nil, fmt.Errorf("expected no response for notification, got: %s", out.String())
		}
		return nil, nil
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w (raw: %s)", err, out.String())
	}
	return resp, nil
}

// sendMCPMulti sends multiple JSON-RPC lines and collects all responses.
func sendMCPMulti(app *App, lines []string) ([]map[string]interface{}, error) {
	in := strings.NewReader(strings.Join(lines, "\n") + "\n")
	var out bytes.Buffer

	app.serveMCPIO(in, &out)

	var responses []map[string]interface{}
	for _, line := range strings.Split(strings.TrimSpace(out.String()), "\n") {
		if line == "" {
			continue
		}
		var resp map[string]interface{}
		if err := json.Unmarshal([]byte(line), &resp); err != nil {
			return nil, fmt.Errorf("failed to unmarshal response line: %w (raw: %s)", err, line)
		}
		responses = append(responses, resp)
	}
	return responses, nil
}

// --- Initialize tests ---

func TestMCPInitialize(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "initialize", 1, nil)
	if err != nil {
		t.Fatalf("initialize error: %v", err)
	}

	if resp["jsonrpc"] != "2.0" {
		t.Errorf("expected jsonrpc '2.0', got %v", resp["jsonrpc"])
	}
	if resp["id"] != float64(1) {
		t.Errorf("expected id 1, got %v", resp["id"])
	}

	result, ok := resp["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected result object, got %T", resp["result"])
	}

	if result["protocolVersion"] != "2025-11-25" {
		t.Errorf("expected protocolVersion '2025-11-25', got %v", result["protocolVersion"])
	}

	capabilities, ok := result["capabilities"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected capabilities object, got %T", result["capabilities"])
	}
	experimental, ok := capabilities["experimental"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected experimental capabilities, got %v", capabilities)
	}
	if _, ok := experimental[mcpFeatureConsequentialConfirmation].(map[string]interface{}); !ok {
		t.Errorf("the handshake must declare the feature by name, got %v", experimental)
	}

	serverInfo, ok := result["serverInfo"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected serverInfo object, got %T", result["serverInfo"])
	}
	if serverInfo["name"] != "testapp" {
		t.Errorf("expected name 'testapp', got %v", serverInfo["name"])
	}
	if serverInfo["version"] != "1.0.0" {
		t.Errorf("expected version '1.0.0', got %v", serverInfo["version"])
	}

	if _, ok := capabilities["tools"]; !ok {
		t.Error("expected 'tools' in capabilities")
	}
}

func TestMCPInitializeStringID(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "initialize", "init-1", nil)
	if err != nil {
		t.Fatalf("initialize error: %v", err)
	}
	if resp["id"] != "init-1" {
		t.Errorf("expected id 'init-1', got %v", resp["id"])
	}
}

// --- tools/list tests ---

func TestMCPToolsList(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "tools/list", 2, nil)
	if err != nil {
		t.Fatalf("tools/list error: %v", err)
	}

	result, ok := resp["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected result object, got %T", resp["result"])
	}

	tools, ok := result["tools"].([]interface{})
	if !ok {
		t.Fatalf("expected tools array, got %T", result["tools"])
	}

	// Should have: greet, status, dns.list (hidden/interactive excluded)
	if len(tools) != 3 {
		t.Fatalf("expected 3 tools, got %d: %v", len(tools), toolNames(tools))
	}

	nameSet := make(map[string]bool)
	for _, tool := range tools {
		toolMap := tool.(map[string]interface{})
		nameSet[toolMap["name"].(string)] = true
	}

	expectedNames := []string{"greet", "status", "dns.list"}
	for _, name := range expectedNames {
		if !nameSet[name] {
			t.Errorf("expected tool %q in tools/list", name)
		}
	}

	// Hidden and interactive commands should not appear
	if nameSet["secret"] {
		t.Error("hidden command 'secret' should not appear in tools/list")
	}
	if nameSet["wizard"] {
		t.Error("interactive command 'wizard' should not appear in tools/list")
	}
}

// An app with no exportable command must publish an empty tools LIST, never
// JSON null -- the sibling of the empty-required rule in buildJSONSchema.
func TestMCPToolsListEmptyIsAList(t *testing.T) {
	app := NewApp("empty", "1.0.0", "an app with no commands")
	resp, err := sendMCPRequest(app, "tools/list", 2, nil)
	if err != nil {
		t.Fatalf("tools/list error: %v", err)
	}
	result := resp["result"].(map[string]interface{})
	tools, ok := result["tools"].([]interface{})
	if !ok {
		t.Fatalf("tools: want an array, got %#v", result["tools"])
	}
	if len(tools) != 0 {
		t.Fatalf("tools: want empty, got %v", tools)
	}
}

func TestMCPToolsListSchema(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "tools/list", 3, nil)
	if err != nil {
		t.Fatalf("tools/list error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	tools := result["tools"].([]interface{})

	// Find the greet tool and check its schema
	for _, tool := range tools {
		toolMap := tool.(map[string]interface{})
		if toolMap["name"] != "greet" {
			continue
		}

		if toolMap["description"] != "greet someone" {
			t.Errorf("expected description 'greet someone', got %v", toolMap["description"])
		}

		inputSchema, ok := toolMap["inputSchema"].(map[string]interface{})
		if !ok {
			t.Fatalf("expected inputSchema object, got %T", toolMap["inputSchema"])
		}

		if inputSchema["type"] != "object" {
			t.Errorf("expected type 'object', got %v", inputSchema["type"])
		}

		props, ok := inputSchema["properties"].(map[string]interface{})
		if !ok {
			t.Fatalf("expected properties object, got %T", inputSchema["properties"])
		}

		nameProp, ok := props["name"].(map[string]interface{})
		if !ok {
			t.Fatal("expected 'name' property in greet tool schema")
		}
		if nameProp["type"] != "string" {
			t.Errorf("expected name type 'string', got %v", nameProp["type"])
		}

		return
	}
	t.Fatal("greet tool not found in tools/list")
}

// --- tools/call tests ---

func TestMCPToolsCallSuccess(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("greet", "greet someone", captureHandler(&captured), WithFlags(
		StringFlag("name", "who to greet"),
		BoolFlag("loud", "shout greeting", Default(false)),
	), WithEffect(EffectReadOnly))

	resp, err := sendMCPRequest(app, "tools/call", 4, map[string]interface{}{
		"name": "greet",
		"arguments": map[string]interface{}{
			"name": "world",
			"loud": true,
		},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result, ok := resp["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected result object, got %T", resp["result"])
	}

	content, ok := result["content"].([]interface{})
	if !ok {
		t.Fatalf("expected content array, got %T", result["content"])
	}
	if len(content) != 1 {
		t.Fatalf("expected 1 content item, got %d", len(content))
	}

	item := content[0].(map[string]interface{})
	if item["type"] != "text" {
		t.Errorf("expected content type 'text', got %v", item["type"])
	}

	// Verify handler was called with correct args
	if captured["name"] != "world" {
		t.Errorf("expected name='world', got %v", captured["name"])
	}
	if captured["loud"] != true {
		t.Errorf("expected loud=true, got %v", captured["loud"])
	}
}

func TestMCPToolsCallGroupedCommand(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	dns := app.Group("dns", "manage DNS")
	dns.Command("list", "list records", captureHandler(&captured), WithFlags(
		StringFlag("zone", "DNS zone"),
	), WithEffect(EffectReadOnly))

	resp, err := sendMCPRequest(app, "tools/call", 5, map[string]interface{}{
		"name": "dns.list",
		"arguments": map[string]interface{}{
			"zone": "example.com",
		},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	if _, ok := result["isError"]; ok {
		content := result["content"].([]interface{})
		item := content[0].(map[string]interface{})
		t.Fatalf("unexpected error: %v", item["text"])
	}

	if captured["zone"] != "example.com" {
		t.Errorf("expected zone='example.com', got %v", captured["zone"])
	}
}

func TestMCPToolsCallMissingRequired(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("greet", "greet someone", nopHandler, WithFlags(
		StringFlag("name", "who to greet"),
	), WithEffect(EffectReadOnly))

	resp, err := sendMCPRequest(app, "tools/call", 6, map[string]interface{}{
		"name":      "greet",
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	isError, ok := result["isError"]
	if !ok || isError != true {
		t.Error("expected isError=true for missing required flag")
	}

	content := result["content"].([]interface{})
	item := content[0].(map[string]interface{})
	if item["type"] != "text" {
		t.Errorf("expected content type 'text', got %v", item["type"])
	}
	errText := item["text"].(string)
	if errText == "" {
		t.Error("expected non-empty error text")
	}
}

func TestMCPToolsCallMissingName(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "tools/call", 7, map[string]interface{}{
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	if resp["error"] == nil {
		t.Fatal("expected error for missing name parameter")
	}
	errObj := resp["error"].(map[string]interface{})
	if errObj["code"] != float64(mcpErrInvalidParams) {
		t.Errorf("expected error code %d, got %v", mcpErrInvalidParams, errObj["code"])
	}
	if errObj["message"] != "missing required parameter: name" {
		t.Errorf("expected message %q, got %v", "missing required parameter: name", errObj["message"])
	}
}

func TestMCPToolsCallNonStringName(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "tools/call", 7, map[string]interface{}{
		"name":      42,
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	if resp["error"] == nil {
		t.Fatal("expected error for non-string name parameter")
	}
	errObj := resp["error"].(map[string]interface{})
	if errObj["code"] != float64(mcpErrInvalidParams) {
		t.Errorf("expected error code %d, got %v", mcpErrInvalidParams, errObj["code"])
	}
	if errObj["message"] != "parameter 'name' must be a string" {
		t.Errorf("expected message %q, got %v", "parameter 'name' must be a string", errObj["message"])
	}
}

func TestMCPToolsCallNonObjectArguments(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "tools/call", 7, map[string]interface{}{
		"name":      "status",
		"arguments": []interface{}{"not", "an", "object"},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	if resp["error"] == nil {
		t.Fatal("expected error for non-object arguments parameter")
	}
	errObj := resp["error"].(map[string]interface{})
	if errObj["code"] != float64(mcpErrInvalidParams) {
		t.Errorf("expected error code %d, got %v", mcpErrInvalidParams, errObj["code"])
	}
	if errObj["message"] != "parameter 'arguments' must be an object" {
		t.Errorf("expected message %q, got %v", "parameter 'arguments' must be an object", errObj["message"])
	}
}

func TestMCPToolsCallUnknownTool(t *testing.T) {
	// Unknown tools are NOT a -32602 protocol error: the name is passed to
	// Call, whose invocation error surfaces as tool-result error content.
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "tools/call", 7, map[string]interface{}{
		"name":      "nonexistent",
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	if resp["error"] != nil {
		t.Fatalf("expected no protocol error for unknown tool, got: %v", resp["error"])
	}
	result := resp["result"].(map[string]interface{})
	if result["isError"] != true {
		t.Error("expected isError=true for unknown tool")
	}
	content := result["content"].([]interface{})
	if len(content) != 1 {
		t.Fatalf("expected 1 content item, got %d", len(content))
	}
	item := content[0].(map[string]interface{})
	if item["type"] != "text" {
		t.Errorf("expected content type 'text', got %v", item["type"])
	}
	if item["text"] != "unknown command 'nonexistent'" {
		t.Errorf("expected text %q, got %v", "unknown command 'nonexistent'", item["text"])
	}
}

func TestMCPToolsCallNoArguments(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("status", "check status", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	resp, err := sendMCPRequest(app, "tools/call", 8, map[string]interface{}{
		"name": "status",
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	if _, ok := result["isError"]; ok {
		t.Error("expected success for command with no required flags")
	}
}

func TestMCPToolsCallDataHandler(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("info", "get info", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.Payload(map[string]interface{}{"status": "ok", "count": 42})
		return Exit(0)
	}, WithEffect(EffectReadOnly), PayloadSchema(map[string]interface{}{}))

	resp, err := sendMCPRequest(app, "tools/call", 9, map[string]interface{}{
		"name": "info",
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	content := result["content"].([]interface{})
	item := content[0].(map[string]interface{})
	text := item["text"].(string)

	// Parse the JSON text to verify the data
	var data map[string]interface{}
	if err := json.Unmarshal([]byte(text), &data); err != nil {
		t.Fatalf("failed to parse result text as JSON: %v", err)
	}
	if data["status"] != "ok" {
		t.Errorf("expected status='ok', got %v", data["status"])
	}
	if data["count"] != float64(42) {
		t.Errorf("expected count=42, got %v", data["count"])
	}
}

// --- Notification tests ---

func TestMCPNotificationIgnored(t *testing.T) {
	app := mcpTestApp()
	// Notification has no id
	resp, err := sendMCPRequest(app, "notifications/initialized", nil, nil)
	if err != nil {
		t.Fatalf("notification error: %v", err)
	}
	if resp != nil {
		t.Errorf("expected no response for notification, got %v", resp)
	}
}

// --- Unknown method tests ---

func TestMCPUnknownMethod(t *testing.T) {
	app := mcpTestApp()
	resp, err := sendMCPRequest(app, "unknown/method", 10, nil)
	if err != nil {
		t.Fatalf("unknown method error: %v", err)
	}

	if resp["error"] == nil {
		t.Fatal("expected error for unknown method")
	}
	errObj := resp["error"].(map[string]interface{})
	if errObj["code"] != float64(mcpErrMethodNotFound) {
		t.Errorf("expected error code %d, got %v", mcpErrMethodNotFound, errObj["code"])
	}
}

// --- Multi-message session tests ---

func TestMCPMultiMessageSession(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("greet", "greet someone", captureHandler(&captured), WithFlags(
		StringFlag("name", "who to greet"),
	), WithEffect(EffectReadOnly))

	// Build a multi-line session: initialize, notification, tools/list, tools/call
	lines := []string{
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "method": "notifications/initialized"}),
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
		mustJSON(map[string]interface{}{
			"jsonrpc": "2.0",
			"id":      3,
			"method":  "tools/call",
			"params": map[string]interface{}{
				"name":      "greet",
				"arguments": map[string]interface{}{"name": "world"},
			},
		}),
	}

	responses, err := sendMCPMulti(app, lines)
	if err != nil {
		t.Fatalf("multi-message error: %v", err)
	}

	// 3 responses (initialize, tools/list, tools/call; notification has no response)
	if len(responses) != 3 {
		t.Fatalf("expected 3 responses, got %d", len(responses))
	}

	// Verify IDs match
	if responses[0]["id"] != float64(1) {
		t.Errorf("first response id: expected 1, got %v", responses[0]["id"])
	}
	if responses[1]["id"] != float64(2) {
		t.Errorf("second response id: expected 2, got %v", responses[1]["id"])
	}
	if responses[2]["id"] != float64(3) {
		t.Errorf("third response id: expected 3, got %v", responses[2]["id"])
	}
}

// --- --mcp flag detection tests ---

func TestMCPFlagDetection(t *testing.T) {
	app := mcpTestApp()

	// Test that --mcp is detected in argv
	result := app.Test([]string{"--mcp"})
	if result.ExitCode != 1 {
		t.Errorf("expected exit code 1, got %d", result.ExitCode)
	}
	if !strings.Contains(result.Stderr, "--mcp cannot be used with Test()") {
		t.Errorf("expected stderr about --mcp and Test(), got: %s", result.Stderr)
	}
}

func TestMCPFlagDetectionPreCommandOnly(t *testing.T) {
	app := mcpTestApp()

	// --mcp before a command is detected
	result := app.Test([]string{"--mcp"})
	if !strings.Contains(result.Stderr, "--mcp cannot be used with Test()") {
		t.Errorf("expected --mcp detection before command, got: %s", result.Stderr)
	}

	// --mcp after a command name is NOT intercepted (unknown flag error)
	result2 := app.Test([]string{"greet", "--mcp"})
	if result2.ExitCode != 1 {
		t.Errorf("expected exit 1 for --mcp after command, got %d", result2.ExitCode)
	}
	if !strings.Contains(result2.Stderr, "unknown flag") {
		t.Errorf("expected unknown flag error for --mcp after command, got: %s", result2.Stderr)
	}

	// --mcp after -- is NOT intercepted
	result3 := app.Test([]string{"--", "--mcp"})
	// After --, --mcp is treated as a command name (unknown command error)
	if result3.ExitCode != 1 {
		t.Errorf("expected exit 1 for --mcp after --, got %d", result3.ExitCode)
	}
}

// --- Invalid JSON tests ---

func TestMCPInvalidJSON(t *testing.T) {
	app := mcpTestApp()
	in := strings.NewReader("not valid json\n")
	var out bytes.Buffer

	app.serveMCPIO(in, &out)

	var resp map[string]interface{}
	if err := json.Unmarshal(out.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal error response: %v (raw: %s)", err, out.String())
	}

	if resp["error"] == nil {
		t.Fatal("expected error for invalid JSON")
	}
	errObj := resp["error"].(map[string]interface{})
	if errObj["code"] != float64(-32700) {
		t.Errorf("expected parse error code -32700, got %v", errObj["code"])
	}
}

// --- Empty lines tests ---

func TestMCPEmptyLinesIgnored(t *testing.T) {
	app := mcpTestApp()

	lines := []string{
		"",
		"  ",
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
		"",
	}

	responses, err := sendMCPMulti(app, lines)
	if err != nil {
		t.Fatalf("error: %v", err)
	}

	if len(responses) != 1 {
		t.Fatalf("expected 1 response, got %d", len(responses))
	}
}

// --- EOF handling test ---

func TestMCPEOFGraceful(t *testing.T) {
	app := mcpTestApp()
	// Empty reader simulates immediate EOF
	in := strings.NewReader("")
	var out bytes.Buffer

	// Should not panic
	app.serveMCPIO(in, &out)

	if out.Len() != 0 {
		t.Errorf("expected no output on EOF, got: %s", out.String())
	}
}

// --- Name resolution tests ---

func TestMCPNameResolutionDashedCommand(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	dns := app.Group("dns", "manage DNS")
	dns.Command("zone-list", "list DNS zones", captureHandler(&captured), WithFlags(
		StringFlag("filter", "filter zones", Default("all")),
	), WithEffect(EffectReadOnly))

	// The tool name IS the command path: a dash inside a command name and a
	// dot between path segments mean what they say, with nothing to guess at.
	resp, err := sendMCPRequest(app, "tools/call", 1, map[string]interface{}{
		"name":      "dns.zone-list",
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	if _, ok := result["isError"]; ok {
		content := result["content"].([]interface{})
		item := content[0].(map[string]interface{})
		t.Fatalf("unexpected error: %v", item["text"])
	}
}

// TestMCPUnderscoreNameIsNotResolved pins the deletion of the reverse lookup
// and its silent fallback: an underscored name is no longer guessed back into
// a command path, and the failure is reported under the name the caller sent
// rather than under a rewritten guess.
func TestMCPUnderscoreNameIsNotResolved(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	dns := app.Group("dns", "manage DNS")
	dns.Command("zone-list", "list DNS zones", captureHandler(&captured), WithFlags(
		StringFlag("filter", "filter zones", Default("all")),
	), WithEffect(EffectReadOnly))

	resp, err := sendMCPRequest(app, "tools/call", 1, map[string]interface{}{
		"name":      "dns_zone_list",
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	if _, ok := result["isError"]; !ok {
		t.Fatalf("expected a tool-result error, got %v", result)
	}
	content := result["content"].([]interface{})
	item := content[0].(map[string]interface{})
	if item["text"] != "unknown command 'dns_zone_list'" {
		t.Fatalf("error text = %v, want it to name the sent name", item["text"])
	}
}

func TestMCPNameResolutionNestedGroup(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	dns := app.Group("dns", "manage DNS")
	zone := dns.Group("zone", "manage zones")
	zone.Command("create", "create a zone", captureHandler(&captured), WithFlags(
		StringFlag("name", "zone name"),
	), WithEffect(EffectReadOnly))

	// The dotted command path is the tool name, at any nesting depth.
	resp, err := sendMCPRequest(app, "tools/call", 1, map[string]interface{}{
		"name": "dns.zone.create",
		"arguments": map[string]interface{}{
			"name": "example.com",
		},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}

	result := resp["result"].(map[string]interface{})
	if _, ok := result["isError"]; ok {
		content := result["content"].([]interface{})
		item := content[0].(map[string]interface{})
		t.Fatalf("unexpected error: %v", item["text"])
	}

	if captured["name"] != "example.com" {
		t.Errorf("expected name='example.com', got %v", captured["name"])
	}
}

// --- Pipe-based test (like exec.Command but in-process) ---

func TestMCPViaPipe(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test application")
	app.Command("echo", "echo back", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithFlags(
		StringFlag("msg", "message to echo"),
	), WithEffect(EffectReadOnly))

	// Use os.Pipe to simulate stdin/stdout
	inReader, inWriter := io.Pipe()
	outReader, outWriter := io.Pipe()

	done := make(chan struct{})
	go func() {
		app.serveMCPIO(inReader, outWriter)
		outWriter.Close()
		close(done)
	}()

	// Read output concurrently to avoid pipe deadlock
	var outBuf bytes.Buffer
	readDone := make(chan struct{})
	go func() {
		io.Copy(&outBuf, outReader)
		close(readDone)
	}()

	// Send initialize
	initReq := mustJSON(map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
	})
	fmt.Fprintf(inWriter, "%s\n", initReq)

	// Send tools/call
	callReq := mustJSON(map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      2,
		"method":  "tools/call",
		"params": map[string]interface{}{
			"name":      "echo",
			"arguments": map[string]interface{}{"msg": "hello"},
		},
	})
	fmt.Fprintf(inWriter, "%s\n", callReq)

	// Close input to signal EOF
	inWriter.Close()

	<-done
	<-readDone

	lines := strings.Split(strings.TrimSpace(outBuf.String()), "\n")
	if len(lines) != 2 {
		t.Fatalf("expected 2 response lines, got %d: %v", len(lines), lines)
	}

	// Verify first response is initialize
	var resp1 map[string]interface{}
	if err := json.Unmarshal([]byte(lines[0]), &resp1); err != nil {
		t.Fatalf("failed to unmarshal response 1: %v", err)
	}
	if resp1["id"] != float64(1) {
		t.Errorf("first response id: expected 1, got %v", resp1["id"])
	}

	// Verify second response is tools/call result
	var resp2 map[string]interface{}
	if err := json.Unmarshal([]byte(lines[1]), &resp2); err != nil {
		t.Fatalf("failed to unmarshal response 2: %v", err)
	}
	if resp2["id"] != float64(2) {
		t.Errorf("second response id: expected 2, got %v", resp2["id"])
	}
	result := resp2["result"].(map[string]interface{})
	if _, ok := result["isError"]; ok {
		t.Error("expected success, got error")
	}
}

// --- Helpers ---

func toolNames(tools []interface{}) []string {
	var names []string
	for _, tool := range tools {
		toolMap := tool.(map[string]interface{})
		names = append(names, toolMap["name"].(string))
	}
	return names
}

func mustJSON(v interface{}) string {
	data, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return string(data)
}

// ---------------------------------------------------------------------------
// Effects classification and programmatic consent over MCP
// ---------------------------------------------------------------------------

func mcpToolDefsByName(t *testing.T, app *App) map[string]map[string]interface{} {
	t.Helper()
	resp, err := sendMCPRequest(app, "tools/list", 1, map[string]interface{}{})
	if err != nil {
		t.Fatalf("tools/list failed: %v", err)
	}
	result := resp["result"].(map[string]interface{})
	defs := map[string]map[string]interface{}{}
	for _, raw := range result["tools"].([]interface{}) {
		def := raw.(map[string]interface{})
		defs[def["name"].(string)] = def
	}
	return defs
}

func mcpCall(t *testing.T, app *App, params map[string]interface{}) map[string]interface{} {
	t.Helper()
	resp, err := sendMCPRequest(app, "tools/call", 1, params)
	if err != nil {
		t.Fatalf("tools/call failed: %v", err)
	}
	return resp
}

func TestMCPToolsListPublishesClassification(t *testing.T) {
	defs := mcpToolDefsByName(t, consentToolApp())
	if got := defs["look"]["effect"]; got != EffectReadOnly {
		t.Errorf("look effect: got %v want %q", got, EffectReadOnly)
	}
	if got := defs["release"]["effect"]; got != EffectMutating {
		t.Errorf("release effect: got %v want %q", got, EffectMutating)
	}
	if got := defs["release"]["consequential"]; got != true {
		t.Errorf("release consequential: got %v want true", got)
	}
	// Absence means "not consequential", exactly as in the schema dump.
	if _, ok := defs["look"]["consequential"]; ok {
		t.Error("consequential must be omitted when false")
	}
	// The classification describes the tool, not one of its arguments.
	schema := defs["release"]["inputSchema"].(map[string]interface{})
	props := schema["properties"].(map[string]interface{})
	for _, banned := range []string{"effect", "consequential", "approve_consequential"} {
		if _, ok := props[banned]; ok {
			t.Errorf("%q must not appear in inputSchema", banned)
		}
	}
}

func TestMCPToolsCallRefusesWithoutConsent(t *testing.T) {
	// These clients declare no capabilities at all, so the modern answer is the
	// capability error rather than the seam's refusal, which is only reachable
	// from the legacy era now.
	resp := mcpCall(t, consentToolApp(), map[string]interface{}{"name": "release"})
	errObj := mcpErrorOf(t, resp)
	if errObj["code"] != float64(mcpErrMissingClientCapability) {
		t.Fatalf("code: got %v want %d", errObj["code"], mcpErrMissingClientCapability)
	}
}

func TestMCPToolsCallProceedsWithConsent(t *testing.T) {
	resp := mcpCall(t, consentToolApp(), map[string]interface{}{
		"name": "release", "approve_consequential": true,
	})
	result := resp["result"].(map[string]interface{})
	if _, isErr := result["isError"]; isErr {
		t.Fatalf("unexpected error result: %#v", result)
	}
	content := result["content"].([]interface{})[0].(map[string]interface{})
	if content["text"] != `{"released":true}` {
		t.Fatalf("unexpected content: %v", content["text"])
	}
}

func TestMCPToolsCallExplicitFalseIsRefused(t *testing.T) {
	resp := mcpCall(t, consentToolApp(), map[string]interface{}{
		"name": "release", "approve_consequential": false,
	})
	if code := mcpErrorOf(t, resp)["code"]; code != float64(mcpErrMissingClientCapability) {
		t.Fatalf("code: got %v want %d", code, mcpErrMissingClientCapability)
	}
}

func TestMCPToolsCallReadOnlyNeedsNoConsent(t *testing.T) {
	resp := mcpCall(t, consentToolApp(), map[string]interface{}{"name": "look"})
	result := resp["result"].(map[string]interface{})
	if _, isErr := result["isError"]; isErr {
		t.Fatalf("unexpected error result: %#v", result)
	}
}

func TestMCPToolsCallNonBooleanConsentIsAProtocolError(t *testing.T) {
	resp := mcpCall(t, consentToolApp(), map[string]interface{}{
		"name": "release", "approve_consequential": "yes",
	})
	errObj, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected a JSON-RPC error, got %#v", resp)
	}
	if errObj["code"] != float64(mcpErrInvalidParams) {
		t.Errorf("code: got %v want %d", errObj["code"], mcpErrInvalidParams)
	}
	want := "parameter 'approve_consequential' must be a boolean"
	if errObj["message"] != want {
		t.Errorf("got %q want %q", errObj["message"], want)
	}
}

func TestMCPConsentInsideArgumentsDoesNotConsent(t *testing.T) {
	// The command's argument namespace is not a consent channel: no command
	// can declare the reserved name, so it surfaces as an unknown parameter.
	resp := mcpCall(t, consentToolApp(), map[string]interface{}{
		"name":      "release",
		"arguments": map[string]interface{}{"approve_consequential": true},
	})
	// The consent never registered, so the command was still unconfirmed and
	// the call never reached it.
	if code := mcpErrorOf(t, resp)["code"]; code != float64(mcpErrMissingClientCapability) {
		t.Fatalf("code: got %v want %d", code, mcpErrMissingClientCapability)
	}
}

// --- The modern era (protocol 2026-07-28) ---

// metaWith returns the modern metadata block with per-test overrides applied.
func metaWith(overrides map[string]interface{}) map[string]interface{} {
	meta := modernMeta()
	for k, v := range overrides {
		meta[k] = v
	}
	return meta
}

// mcpErrorOf returns a response's error object, failing the test when the
// response carries a result instead.
func mcpErrorOf(t *testing.T, resp map[string]interface{}) map[string]interface{} {
	t.Helper()
	errObj, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected an error response, got %v", resp)
	}
	return errObj
}

// mcpResultOf returns a response's result object, failing the test when the
// response carries an error instead.
func mcpResultOf(t *testing.T, resp map[string]interface{}) map[string]interface{} {
	t.Helper()
	result, ok := resp["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected a result response, got %v", resp)
	}
	return result
}

func TestMCPDiscoverAdvertisesVersionsCapabilitiesAndIdentity(t *testing.T) {
	resp, err := sendMCPRequest(mcpTestApp(), "server/discover", 1, nil)
	if err != nil {
		t.Fatalf("discover error: %v", err)
	}
	result := mcpResultOf(t, resp)
	if result["resultType"] != "complete" {
		t.Errorf("resultType: got %v", result["resultType"])
	}
	versions, _ := result["supportedVersions"].([]interface{})
	if len(versions) != 1 || versions[0] != mcpProtocolVersion {
		t.Errorf("supportedVersions: got %v", result["supportedVersions"])
	}
	if result["instructions"] != "test application" {
		t.Errorf("instructions: got %v", result["instructions"])
	}
	if result["ttlMs"] != float64(mcpCacheTTLMs) || result["cacheScope"] != mcpCacheScope {
		t.Errorf("cacheability: got %v / %v", result["ttlMs"], result["cacheScope"])
	}
	meta, _ := result["_meta"].(map[string]interface{})
	info, _ := meta[mcpMetaServerInfo].(map[string]interface{})
	if info["name"] != "testapp" || info["version"] != "1.0.0" {
		t.Errorf("serverInfo: got %v", meta[mcpMetaServerInfo])
	}
}

func TestMCPDiscoverDeclaresTheConfirmationFeatureByName(t *testing.T) {
	resp, err := sendMCPRequest(mcpTestApp(), "server/discover", 1, nil)
	if err != nil {
		t.Fatalf("discover error: %v", err)
	}
	caps, _ := mcpResultOf(t, resp)["capabilities"].(map[string]interface{})
	exts, _ := caps["extensions"].(map[string]interface{})
	if _, ok := exts[mcpFeatureConsequentialConfirmation]; !ok {
		t.Errorf("expected the %s feature, got %v", mcpFeatureConsequentialConfirmation, exts)
	}
}

func TestMCPModernResultsCarryTheirResultType(t *testing.T) {
	app := mcpTestApp()

	list, err := sendMCPRequest(app, "tools/list", 1, nil)
	if err != nil {
		t.Fatalf("tools/list error: %v", err)
	}
	result := mcpResultOf(t, list)
	if result["resultType"] != "complete" {
		t.Errorf("tools/list resultType: got %v", result["resultType"])
	}
	if result["ttlMs"] != float64(mcpCacheTTLMs) || result["cacheScope"] != mcpCacheScope {
		t.Errorf("tools/list cacheability: got %v / %v", result["ttlMs"], result["cacheScope"])
	}

	call, err := sendMCPRequest(app, "tools/call", 2, map[string]interface{}{
		"name":      "status",
		"arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("tools/call error: %v", err)
	}
	if mcpResultOf(t, call)["resultType"] != "complete" {
		t.Errorf("tools/call resultType: got %v", mcpResultOf(t, call)["resultType"])
	}
}

func TestMCPRequestMetadataIsValidated(t *testing.T) {
	cases := []struct {
		name    string
		params  map[string]interface{}
		message string
	}{
		{
			name:    "meta must be an object",
			params:  map[string]interface{}{"_meta": []interface{}{}},
			message: "parameter '_meta' must be an object",
		},
		{
			name: "protocol version must be a string",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				mcpMetaProtocolVersion: 2026,
			})},
			message: "_meta['io.modelcontextprotocol/protocolVersion'] must be a string",
		},
		{
			name: "client capabilities are required",
			params: map[string]interface{}{"_meta": map[string]interface{}{
				mcpMetaProtocolVersion: mcpProtocolVersion,
			}},
			message: "missing required request metadata: _meta['io.modelcontextprotocol/clientCapabilities']",
		},
		{
			name: "client capabilities must be an object",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				mcpMetaClientCapabilities: "yes",
			})},
			message: "_meta['io.modelcontextprotocol/clientCapabilities'] must be an object",
		},
		{
			name: "client info must be an object",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				mcpMetaClientInfo: "ExampleClient",
			})},
			message: "_meta['io.modelcontextprotocol/clientInfo'] must be an object",
		},
		{
			name: "a malformed key name is refused",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				"-bad./key": 1,
			})},
			message: "invalid _meta key name: '-bad./key'",
		},
		{
			name: "an unknown reserved key is refused",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				"io.modelcontextprotocol/whatever": 1,
			})},
			message: "unrecognized reserved _meta key: 'io.modelcontextprotocol/whatever'",
		},
		// More than one offending key names the lexically first, in every
		// implementation: Go sorts because its map iteration is randomized
		// (§22.2), and Python and TypeScript sort so the verdict is the same
		// one rather than their document's own order.
		{
			name: "more than one offending key names the first in sorted order",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				"z!bad": 1, "a!bad": 1,
			})},
			message: "invalid _meta key name: 'a!bad'",
		},
		{
			name: "the sorted order spans both key rules",
			params: map[string]interface{}{"_meta": metaWith(map[string]interface{}{
				"z!bad": 1, "io.mcp/whatever": 1,
			})},
			message: "unrecognized reserved _meta key: 'io.mcp/whatever'",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			resp, err := sendMCPRequestRaw(mcpTestApp(), "tools/list", 1, tc.params)
			if err != nil {
				t.Fatalf("error: %v", err)
			}
			errObj := mcpErrorOf(t, resp)
			if errObj["code"] != float64(mcpErrInvalidParams) {
				t.Errorf("code: got %v", errObj["code"])
			}
			if errObj["message"] != tc.message {
				t.Errorf("message: got %q, want %q", errObj["message"], tc.message)
			}
		})
	}
}

func TestMCPRequestWithoutMetadataIsRefused(t *testing.T) {
	resp, err := sendMCPRequestRaw(mcpTestApp(), "tools/list", 1, nil)
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	errObj := mcpErrorOf(t, resp)
	if errObj["code"] != float64(mcpErrInvalidParams) {
		t.Errorf("code: got %v", errObj["code"])
	}
	want := "missing required request metadata: _meta['io.modelcontextprotocol/protocolVersion']"
	if errObj["message"] != want {
		t.Errorf("message: got %q, want %q", errObj["message"], want)
	}
}

func TestMCPVendorAndOptionalMetaKeysAreAccepted(t *testing.T) {
	resp, err := sendMCPRequestRaw(mcpTestApp(), "tools/list", 1, map[string]interface{}{
		"_meta": metaWith(map[string]interface{}{
			"com.example.mcp/thing": 1,
			"traceparent":           "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01",
			"progressToken":         7,
			mcpMetaClientInfo:       map[string]interface{}{"name": "ExampleClient", "version": "1.0.0"},
			mcpMetaLogLevel:         "debug",
		}),
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	if mcpResultOf(t, resp)["resultType"] != "complete" {
		t.Errorf("expected a complete result, got %v", resp)
	}
}

func TestMCPUnsupportedProtocolVersionIsRefused(t *testing.T) {
	resp, err := sendMCPRequestRaw(mcpTestApp(), "tools/list", 1, map[string]interface{}{
		"_meta": metaWith(map[string]interface{}{
			mcpMetaProtocolVersion: "1900-01-01",
		}),
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	errObj := mcpErrorOf(t, resp)
	if errObj["code"] != float64(mcpErrUnsupportedProtocolVersion) {
		t.Errorf("code: got %v", errObj["code"])
	}
	if errObj["message"] != "Unsupported protocol version" {
		t.Errorf("message: got %v", errObj["message"])
	}
	data, _ := errObj["data"].(map[string]interface{})
	supported, _ := data["supported"].([]interface{})
	if len(supported) != 1 || supported[0] != mcpProtocolVersion || data["requested"] != "1900-01-01" {
		t.Errorf("data: got %v", data)
	}
}

func TestMCPEraSelection(t *testing.T) {
	app := mcpTestApp()
	lines := []string{
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
		mustJSON(map[string]interface{}{
			"jsonrpc": "2.0", "id": 3, "method": "tools/list",
			"params": map[string]interface{}{"_meta": modernMeta()},
		}),
		mustJSON(map[string]interface{}{"jsonrpc": "2.0", "id": 4, "method": "server/discover"}),
	}
	responses, err := sendMCPMulti(app, lines)
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	if len(responses) != 4 {
		t.Fatalf("expected 4 responses, got %d", len(responses))
	}
	if mcpResultOf(t, responses[0])["protocolVersion"] != mcpLegacyProtocolVersion {
		t.Errorf("handshake version: got %v", mcpResultOf(t, responses[0])["protocolVersion"])
	}
	legacyList := mcpResultOf(t, responses[1])
	if _, ok := legacyList["resultType"]; ok {
		t.Errorf("legacy result carries a resultType: %v", legacyList)
	}
	if _, ok := legacyList["ttlMs"]; ok {
		t.Errorf("legacy result carries cacheability: %v", legacyList)
	}
	if mcpResultOf(t, responses[2])["resultType"] != "complete" {
		t.Errorf("modern request after a handshake: got %v", responses[2])
	}
	if mcpErrorOf(t, responses[3])["code"] != float64(mcpErrMethodNotFound) {
		t.Errorf("discover from the legacy era: got %v", responses[3])
	}
}

// --- The confirmation round-trip and its continuation state ---

// mcpSession is a live MCP session in which a request may depend on an earlier
// reply.
//
// The continuation key and its spent-id set live in the server process, so a
// round-trip has to be driven through ONE serveMCPIO call: a second call is a
// second server, and its state is deliberately worthless to the first.
type mcpSession struct {
	app       *App
	responses []map[string]interface{}
}

// sessionStep builds one request, given the replies seen so far.
type sessionStep func(seen []map[string]interface{}) map[string]interface{}

// scriptStep is one line to send, and whether a reply is expected before the
// next one goes out. The legacy exchange holds a request open while it waits
// for an answer, so some lines have to be sent without reading first.
type scriptStep struct {
	build sessionStep
	reply bool
}

// sends builds a step whose reply comes later, if at all.
func sends(build sessionStep) scriptStep { return scriptStep{build: build, reply: false} }

// run drives the steps through one server, feeding each request only after the
// previous reply has been parsed.
func (s *mcpSession) run(t *testing.T, steps ...sessionStep) []map[string]interface{} {
	t.Helper()
	script := make([]scriptStep, 0, len(steps))
	for _, step := range steps {
		script = append(script, scriptStep{build: step, reply: true})
	}
	return s.runScript(t, script...)
}

// runScript is run with per-step control over whether a reply is awaited; every
// line still unread when the script ends is drained before the server exits.
func (s *mcpSession) runScript(t *testing.T, steps ...scriptStep) []map[string]interface{} {
	t.Helper()
	inReader, inWriter := io.Pipe()
	outReader, outWriter := io.Pipe()
	done := make(chan struct{})
	go func() {
		s.app.serveMCPIO(inReader, outWriter)
		outWriter.Close()
		close(done)
	}()

	replies := bufio.NewReader(outReader)
	record := func(text string) {
		var resp map[string]interface{}
		if err := json.Unmarshal([]byte(text), &resp); err != nil {
			t.Fatalf("unmarshal reply: %v (raw %s)", err, text)
		}
		s.responses = append(s.responses, resp)
	}
	for _, step := range steps {
		request := step.build(s.responses)
		line, err := json.Marshal(request)
		if err != nil {
			t.Fatalf("marshal: %v", err)
		}
		if _, err := inWriter.Write(append(line, '\n')); err != nil {
			t.Fatalf("write: %v", err)
		}
		if !step.reply {
			continue
		}
		text, err := replies.ReadString('\n')
		if err != nil {
			t.Fatalf("read reply: %v", err)
		}
		record(text)
	}
	inWriter.Close()
	// Drain whatever the server still has to say. io.Pipe writes block until
	// they are read, so this has to happen before waiting for the server to
	// exit -- and it is where a reply held during an exchange shows up.
	for {
		text, err := replies.ReadString('\n')
		if strings.TrimSpace(text) != "" {
			record(text)
		}
		if err != nil {
			break
		}
	}
	<-done
	outReader.Close()
	return s.responses
}

// confirmingApp exports one consequential tool and one read-only one.
func confirmingApp() *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("release", "release it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectMutating), WithConsequential())
	app.Command("look", "look around", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	return app
}

// elicitingMeta is a client that can render a form elicitation.
func elicitingMeta() map[string]interface{} {
	return map[string]interface{}{
		mcpMetaProtocolVersion:    mcpProtocolVersion,
		mcpMetaClientCapabilities: map[string]interface{}{"elicitation": map[string]interface{}{"form": map[string]interface{}{}}},
		mcpMetaClientInfo:         map[string]interface{}{"name": "cli", "version": "1.0.0"},
	}
}

func callRequest(id interface{}, params map[string]interface{}) map[string]interface{} {
	if _, ok := params["_meta"]; !ok {
		params["_meta"] = elicitingMeta()
	}
	return map[string]interface{}{
		"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": params,
	}
}

func acceptance(proceed bool) map[string]interface{} {
	return map[string]interface{}{
		mcpConfirmationKey: map[string]interface{}{
			"action":  "accept",
			"content": map[string]interface{}{"proceed": proceed},
		},
	}
}

func stateOf(t *testing.T, resp map[string]interface{}) string {
	t.Helper()
	state, ok := mcpResultOf(t, resp)["requestState"].(string)
	if !ok {
		t.Fatalf("no requestState in %v", resp)
	}
	return state
}

// driveConfirmation asks, then answers: the two halves of one confirmation.
func driveConfirmation(t *testing.T, app *App, answers map[string]interface{}) []map[string]interface{} {
	t.Helper()
	session := &mcpSession{app: app}
	return session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return callRequest(1, map[string]interface{}{"name": "release", "arguments": map[string]interface{}{}})
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return callRequest(2, map[string]interface{}{
				"name": "release", "arguments": map[string]interface{}{},
				"requestState": stateOf(t, seen[0]), "inputResponses": answers,
			})
		},
	)
}

func TestMCPUnconsentedCallAsksForConfirmation(t *testing.T) {
	resp, err := sendMCPRequestRaw(confirmingApp(), "tools/call", 1, map[string]interface{}{
		"_meta": elicitingMeta(), "name": "release", "arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	result := mcpResultOf(t, resp)
	if result["resultType"] != "input_required" {
		t.Fatalf("resultType: got %v", result["resultType"])
	}
	requests, _ := result["inputRequests"].(map[string]interface{})
	request, _ := requests[mcpConfirmationKey].(map[string]interface{})
	if request["method"] != "elicitation/create" {
		t.Errorf("method: got %v", request["method"])
	}
	params, _ := request["params"].(map[string]interface{})
	if params["mode"] != "form" {
		t.Errorf("mode: got %v", params["mode"])
	}
	want := "about to run consequential command 'release'. Proceed?"
	if params["message"] != want {
		t.Errorf("message: got %q, want %q", params["message"], want)
	}
	if state, ok := result["requestState"].(string); !ok || state == "" {
		t.Errorf("requestState: got %v", result["requestState"])
	}
}

func TestMCPRetryCarryingAcceptanceProceeds(t *testing.T) {
	responses := driveConfirmation(t, confirmingApp(), acceptance(true))
	result := mcpResultOf(t, responses[1])
	if result["resultType"] != "complete" {
		t.Fatalf("resultType: got %v", result["resultType"])
	}
	if _, isError := result["isError"]; isError {
		t.Errorf("expected the call to proceed, got %v", result)
	}
}

func TestMCPDeclineAndCancelAbort(t *testing.T) {
	for _, action := range []string{"decline", "cancel"} {
		t.Run(action, func(t *testing.T) {
			responses := driveConfirmation(t, confirmingApp(), map[string]interface{}{
				mcpConfirmationKey: map[string]interface{}{"action": action},
			})
			result := mcpResultOf(t, responses[1])
			if result["isError"] != true {
				t.Fatalf("expected an aborted result, got %v", result)
			}
			content, _ := result["content"].([]interface{})
			first, _ := content[0].(map[string]interface{})
			if first["text"] != errConfirmDeclined {
				t.Errorf("text: got %v", first["text"])
			}
		})
	}
}

func TestMCPAcceptanceThatSaysNoAborts(t *testing.T) {
	responses := driveConfirmation(t, confirmingApp(), acceptance(false))
	if mcpResultOf(t, responses[1])["isError"] != true {
		t.Errorf("expected an aborted result, got %v", responses[1])
	}
}

func TestMCPMissingAnswerAsksAgainWithFreshState(t *testing.T) {
	responses := driveConfirmation(t, confirmingApp(), map[string]interface{}{})
	second := mcpResultOf(t, responses[1])
	if second["resultType"] != "input_required" {
		t.Fatalf("resultType: got %v", second["resultType"])
	}
	if second["requestState"] == stateOf(t, responses[0]) {
		t.Errorf("the re-ask reused the spent state")
	}
}

func TestMCPReadOnlyToolIsNeverAskedAbout(t *testing.T) {
	resp, err := sendMCPRequestRaw(confirmingApp(), "tools/call", 1, map[string]interface{}{
		"_meta": elicitingMeta(), "name": "look", "arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	if mcpResultOf(t, resp)["resultType"] != "complete" {
		t.Errorf("expected a complete result, got %v", resp)
	}
}

// TestMCPClientWithoutElicitationGetsTheCapabilityError pins the revision's own
// answer: a server may not send an input request the client never said it could
// fulfil, and -32021 is the code for saying so.
func TestMCPClientWithoutElicitationGetsTheCapabilityError(t *testing.T) {
	resp, err := sendMCPRequestRaw(confirmingApp(), "tools/call", 1, map[string]interface{}{
		"_meta": modernMeta(), "name": "release", "arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	errObj := mcpErrorOf(t, resp)
	if errObj["code"] != float64(mcpErrMissingClientCapability) {
		t.Fatalf("code: got %v want %d", errObj["code"], mcpErrMissingClientCapability)
	}
	if errObj["message"] != mcpMsgMissingElicitation {
		t.Errorf("message: got %q, want %q", errObj["message"], mcpMsgMissingElicitation)
	}
	data, _ := errObj["data"].(map[string]interface{})
	required, _ := data["requiredCapabilities"].(map[string]interface{})
	elicitation, ok := required["elicitation"].(map[string]interface{})
	if !ok {
		t.Fatalf("requiredCapabilities: got %v", data["requiredCapabilities"])
	}
	if _, ok := elicitation["form"].(map[string]interface{}); !ok {
		t.Errorf("requiredCapabilities names form mode: got %v", elicitation)
	}
}

// TestMCPURLOnlyClientGetsTheCapabilityError: a client that can only open a URL
// cannot render this question either.
func TestMCPURLOnlyClientGetsTheCapabilityError(t *testing.T) {
	meta := metaWith(map[string]interface{}{
		mcpMetaClientCapabilities: map[string]interface{}{
			"elicitation": map[string]interface{}{"url": map[string]interface{}{}},
		},
	})
	resp, err := sendMCPRequestRaw(confirmingApp(), "tools/call", 1, map[string]interface{}{
		"_meta": meta, "name": "release", "arguments": map[string]interface{}{},
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	if code := mcpErrorOf(t, resp)["code"]; code != float64(mcpErrMissingClientCapability) {
		t.Fatalf("code: got %v want %d", code, mcpErrMissingClientCapability)
	}
}

func TestMCPStatedConsentNeedsNoDeclaredCapability(t *testing.T) {
	resp, err := sendMCPRequestRaw(confirmingApp(), "tools/call", 1, map[string]interface{}{
		"_meta": modernMeta(), "name": "release", "arguments": map[string]interface{}{},
		"approve_consequential": true,
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	result := mcpResultOf(t, resp)
	if result["resultType"] != "complete" {
		t.Fatalf("resultType: got %v", result["resultType"])
	}
	if _, isError := result["isError"]; isError {
		t.Errorf("expected the call to proceed, got %v", result)
	}
}

// --- The legacy era's confirmation (contract §22.7) ---

// handshakeRequest is the legacy opener: in that era the handshake IS the
// client's declaration.
func handshakeRequest(elicitation bool) map[string]interface{} {
	caps := map[string]interface{}{}
	if elicitation {
		caps["elicitation"] = map[string]interface{}{"form": map[string]interface{}{}}
	}
	return map[string]interface{}{
		"jsonrpc": "2.0", "id": 1, "method": "initialize",
		"params": map[string]interface{}{
			"capabilities": caps,
			"clientInfo":   map[string]interface{}{"name": "cli", "version": "1.0.0"},
		},
	}
}

// legacyCall is a legacy tools/call: no per-request metadata, because that era
// has none.
func legacyCall(id interface{}, toolName string, params map[string]interface{}) map[string]interface{} {
	if params == nil {
		params = map[string]interface{}{}
	}
	params["name"] = toolName
	if _, ok := params["arguments"]; !ok {
		params["arguments"] = map[string]interface{}{}
	}
	return map[string]interface{}{
		"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": params,
	}
}

// answerElicitation echoes the id of the elicitation the server just sent.
func answerElicitation(t *testing.T, seen []map[string]interface{}, result interface{}) map[string]interface{} {
	t.Helper()
	ask := seen[len(seen)-1]
	return map[string]interface{}{
		"jsonrpc": "2.0", "id": ask["id"], "result": result,
	}
}

func TestMCPLegacyConsequentialCallIsAskedOverAServerRequest(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(true)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(2, "release", nil)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return answerElicitation(t, seen, map[string]interface{}{
				"action": "accept", "content": map[string]interface{}{"proceed": true},
			})
		},
	)
	ask := responses[1]
	if ask["method"] != "elicitation/create" {
		t.Fatalf("expected a server-initiated elicitation, got %v", ask)
	}
	params, _ := ask["params"].(map[string]interface{})
	if params["mode"] != "form" {
		t.Errorf("mode: got %v", params["mode"])
	}
	want := "about to run consequential command 'release'. Proceed?"
	if params["message"] != want {
		t.Errorf("message: got %q, want %q", params["message"], want)
	}
	// The correlation id IS the continuation blob: one mint-and-verify path,
	// two delivery vehicles.
	id, ok := ask["id"].(string)
	if !ok || !strings.Contains(id, ".") {
		t.Errorf("the elicitation id must be the continuation blob, got %v", ask["id"])
	}
	result := mcpResultOf(t, responses[2])
	if _, isError := result["isError"]; isError {
		t.Errorf("expected the call to proceed, got %v", result)
	}
	if _, ok := result["resultType"]; ok {
		t.Errorf("a legacy result carries no resultType: %v", result)
	}
}

func TestMCPLegacyAnythingButAnAcceptanceAborts(t *testing.T) {
	answers := map[string]interface{}{
		"decline":    map[string]interface{}{"action": "decline"},
		"cancel":     map[string]interface{}{"action": "cancel"},
		"proceedNo":  map[string]interface{}{"action": "accept", "content": map[string]interface{}{"proceed": false}},
		"noContent":  map[string]interface{}{"action": "accept"},
		"notAResult": "not an elicitation result",
	}
	for name, answer := range answers {
		t.Run(name, func(t *testing.T) {
			session := &mcpSession{app: confirmingApp()}
			responses := session.run(t,
				func(seen []map[string]interface{}) map[string]interface{} {
					return handshakeRequest(true)
				},
				func(seen []map[string]interface{}) map[string]interface{} {
					return legacyCall(2, "release", nil)
				},
				func(seen []map[string]interface{}) map[string]interface{} {
					return answerElicitation(t, seen, answer)
				},
			)
			result := mcpResultOf(t, responses[2])
			if result["isError"] != true {
				t.Fatalf("expected an aborted result, got %v", result)
			}
			content, _ := result["content"].([]interface{})
			first, _ := content[0].(map[string]interface{})
			if first["text"] != errConfirmDeclined {
				t.Errorf("text: got %v", first["text"])
			}
		})
	}
}

func TestMCPLegacyErrorResponseAborts(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(true)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(2, "release", nil)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			ask := seen[len(seen)-1]
			return map[string]interface{}{
				"jsonrpc": "2.0", "id": ask["id"],
				"error": map[string]interface{}{"code": -32601, "message": "Method not found"},
			}
		},
	)
	if mcpResultOf(t, responses[2])["isError"] != true {
		t.Errorf("expected an aborted result, got %v", responses[2])
	}
}

func TestMCPLegacyAnswerUnderAnUnmintedIDConfirmsNothing(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.runScript(t,
		scriptStep{reply: true, build: func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(true)
		}},
		scriptStep{reply: true, build: func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(2, "release", nil)
		}},
		sends(func(seen []map[string]interface{}) map[string]interface{} {
			return map[string]interface{}{
				"jsonrpc": "2.0", "id": "not-the-blob",
				"result": map[string]interface{}{
					"action": "accept", "content": map[string]interface{}{"proceed": true},
				},
			}
		}),
	)
	// The stray response is discarded; the stream then ends without an answer,
	// which aborts.
	result := mcpResultOf(t, responses[2])
	if result["isError"] != true {
		t.Fatalf("expected an aborted result, got %v", result)
	}
}

func TestMCPLegacyClientThatCannotBeAskedGetsTheSeamsRefusal(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(false)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(2, "release", nil)
		},
	)
	result := mcpResultOf(t, responses[1])
	if result["isError"] != true {
		t.Fatalf("expected the refusal, got %v", result)
	}
	content, _ := result["content"].([]interface{})
	first, _ := content[0].(map[string]interface{})
	want := errCallConsequentialUnconsented("release")
	if first["text"] != want {
		t.Errorf("text: got %q, want %q", first["text"], want)
	}
}

func TestMCPLegacyReadOnlyAndConsentedCallsAreNeverAsked(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(true)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(2, "look", nil)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(3, "release", map[string]interface{}{
				"approve_consequential": true,
			})
		},
	)
	for _, resp := range responses[1:] {
		result := mcpResultOf(t, resp)
		if _, isError := result["isError"]; isError {
			t.Errorf("expected the call to proceed, got %v", result)
		}
	}
}

func TestMCPLegacyTrafficArrivingMidExchangeIsHeldNotDropped(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.runScript(t,
		scriptStep{reply: true, build: func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(true)
		}},
		scriptStep{reply: true, build: func(seen []map[string]interface{}) map[string]interface{} {
			return legacyCall(2, "release", nil)
		}},
		sends(func(seen []map[string]interface{}) map[string]interface{} {
			// Sent while the server is waiting for the answer.
			return map[string]interface{}{"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
		}),
		sends(func(seen []map[string]interface{}) map[string]interface{} {
			ask := seen[1]
			return map[string]interface{}{
				"jsonrpc": "2.0", "id": ask["id"],
				"result": map[string]interface{}{
					"action": "accept", "content": map[string]interface{}{"proceed": true},
				},
			}
		}),
	)
	if responses[1]["method"] != "elicitation/create" {
		t.Fatalf("expected the elicitation second, got %v", responses[1])
	}
	if responses[2]["id"] != float64(2) {
		t.Errorf("expected the tool result third, got %v", responses[2])
	}
	// Served after the call it interrupted, never dropped.
	if responses[3]["id"] != float64(3) {
		t.Errorf("expected the held tools/list fourth, got %v", responses[3])
	}
}

// TestMCPLegacyAbortedExchangeConsumesItsState pins that every legacy exit
// spends the blob: an abort is not a free replay.
//
// The blob binds the same principal and the same request digest the modern era
// mints, and stays live for five minutes. An exchange that ended without
// consuming it therefore hands the client a `requestState` it can answer
// itself, on the modern path, for the very call it just aborted.
func TestMCPLegacyAbortedExchangeConsumesItsState(t *testing.T) {
	replay := func(seen []map[string]interface{}) map[string]interface{} {
		var blob interface{}
		for _, resp := range seen {
			if resp["method"] == "elicitation/create" {
				blob = resp["id"]
			}
		}
		return callRequest(3, map[string]interface{}{
			"name": "release", "arguments": map[string]interface{}{},
			"requestState": blob, "inputResponses": acceptance(true),
		})
	}
	t.Run("errorResponse", func(t *testing.T) {
		session := &mcpSession{app: confirmingApp()}
		responses := session.run(t,
			func(seen []map[string]interface{}) map[string]interface{} {
				return handshakeRequest(true)
			},
			func(seen []map[string]interface{}) map[string]interface{} {
				return legacyCall(2, "release", nil)
			},
			// A JSON-RPC error answers the elicitation: the exchange aborts.
			func(seen []map[string]interface{}) map[string]interface{} {
				ask := seen[len(seen)-1]
				return map[string]interface{}{
					"jsonrpc": "2.0", "id": ask["id"],
					"error": map[string]interface{}{"code": -32601, "message": "Method not found"},
				}
			},
			replay,
		)
		assertReplayRefused(t, responses[3])
	})
	// The exits that always consumed still do, after the reordering.
	refusals := map[string]interface{}{
		"decline":   map[string]interface{}{"action": "decline"},
		"cancel":    map[string]interface{}{"action": "cancel"},
		"proceedNo": map[string]interface{}{"action": "accept", "content": map[string]interface{}{"proceed": false}},
	}
	for name, answer := range refusals {
		t.Run(name, func(t *testing.T) {
			session := &mcpSession{app: confirmingApp()}
			responses := session.run(t,
				func(seen []map[string]interface{}) map[string]interface{} {
					return handshakeRequest(true)
				},
				func(seen []map[string]interface{}) map[string]interface{} {
					return legacyCall(2, "release", nil)
				},
				func(seen []map[string]interface{}) map[string]interface{} {
					return answerElicitation(t, seen, answer)
				},
				replay,
			)
			assertReplayRefused(t, responses[3])
		})
	}
	t.Run("streamEndsUnanswered", func(t *testing.T) {
		session := &mcpSession{app: confirmingApp()}
		responses := session.runScript(t,
			scriptStep{reply: true, build: func(seen []map[string]interface{}) map[string]interface{} {
				return handshakeRequest(true)
			}},
			scriptStep{reply: true, build: func(seen []map[string]interface{}) map[string]interface{} {
				return legacyCall(2, "release", nil)
			}},
			// Held while the server waits; the stream then ends without an
			// answer, which aborts, and the held request is served afterwards.
			sends(replay),
		)
		assertReplayRefused(t, responses[3])
	})
}

// assertReplayRefused fails unless the modern replay of a spent blob was
// refused as already used rather than running the command.
func assertReplayRefused(t *testing.T, resp map[string]interface{}) {
	t.Helper()
	errBody, ok := resp["error"].(map[string]interface{})
	if !ok {
		t.Fatalf("the aborted blob was replayed and ran the command: %v", resp)
	}
	if errBody["message"] != mcpErrStateReused {
		t.Errorf("message: got %v, want %q", errBody["message"], mcpErrStateReused)
	}
}

func TestMCPModernCallIsStillAskedTheModernWayAfterAHandshake(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return handshakeRequest(true)
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			return callRequest(2, map[string]interface{}{
				"name": "release", "arguments": map[string]interface{}{},
			})
		},
	)
	if mcpResultOf(t, responses[1])["resultType"] != "input_required" {
		t.Errorf("expected the modern round-trip, got %v", responses[1])
	}
}

func TestMCPTamperedStateIsRefused(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return callRequest(1, map[string]interface{}{"name": "release", "arguments": map[string]interface{}{}})
		},
		func(seen []map[string]interface{}) map[string]interface{} {
			// The FIRST character: base64 decoders ignore the trailing bits
			// of a final character that does not fill a byte, so changing the
			// last character of the blob can decode to the identical bytes.
			state := stateOf(t, seen[0])
			broken := "A" + state[1:]
			if strings.HasPrefix(state, "A") {
				broken = "B" + state[1:]
			}
			return callRequest(2, map[string]interface{}{
				"name": "release", "arguments": map[string]interface{}{},
				"requestState": broken, "inputResponses": acceptance(true),
			})
		},
	)
	errObj := mcpErrorOf(t, responses[1])
	if errObj["code"] != float64(mcpErrInvalidParams) || errObj["message"] != mcpErrStateVerification {
		t.Errorf("got %v", errObj)
	}
}

func TestMCPStateIsSingleUse(t *testing.T) {
	session := &mcpSession{app: confirmingApp()}
	retry := func(id interface{}) sessionStep {
		return func(seen []map[string]interface{}) map[string]interface{} {
			return callRequest(id, map[string]interface{}{
				"name": "release", "arguments": map[string]interface{}{},
				"requestState": stateOf(t, seen[0]), "inputResponses": acceptance(true),
			})
		}
	}
	responses := session.run(t,
		func(seen []map[string]interface{}) map[string]interface{} {
			return callRequest(1, map[string]interface{}{"name": "release", "arguments": map[string]interface{}{}})
		},
		retry(2), retry(3),
	)
	if mcpResultOf(t, responses[1])["resultType"] != "complete" {
		t.Fatalf("the first redemption failed: %v", responses[1])
	}
	if mcpErrorOf(t, responses[2])["message"] != mcpErrStateReused {
		t.Errorf("got %v", responses[2])
	}
}

func TestMCPStateDoesNotTravel(t *testing.T) {
	t.Run("to another request", func(t *testing.T) {
		session := &mcpSession{app: confirmingApp()}
		responses := session.run(t,
			func(seen []map[string]interface{}) map[string]interface{} {
				return callRequest(1, map[string]interface{}{"name": "release", "arguments": map[string]interface{}{}})
			},
			func(seen []map[string]interface{}) map[string]interface{} {
				return callRequest(2, map[string]interface{}{
					"name": "release", "arguments": map[string]interface{}{"unexpected": 1},
					"requestState": stateOf(t, seen[0]), "inputResponses": acceptance(true),
				})
			},
		)
		if mcpErrorOf(t, responses[1])["message"] != mcpErrStateWrongRequest {
			t.Errorf("got %v", responses[1])
		}
	})

	t.Run("to another client", func(t *testing.T) {
		session := &mcpSession{app: confirmingApp()}
		responses := session.run(t,
			func(seen []map[string]interface{}) map[string]interface{} {
				return callRequest(1, map[string]interface{}{"name": "release", "arguments": map[string]interface{}{}})
			},
			func(seen []map[string]interface{}) map[string]interface{} {
				other := elicitingMeta()
				other[mcpMetaClientInfo] = map[string]interface{}{"name": "someone-else", "version": "1.0.0"}
				return callRequest(2, map[string]interface{}{
					"_meta": other,
					"name":  "release", "arguments": map[string]interface{}{},
					"requestState": stateOf(t, seen[0]), "inputResponses": acceptance(true),
				})
			},
		)
		if mcpErrorOf(t, responses[1])["message"] != mcpErrStateWrongClient {
			t.Errorf("got %v", responses[1])
		}
	})
}

func TestMCPAnswerWithoutItsStateIsRefused(t *testing.T) {
	resp, err := sendMCPRequestRaw(confirmingApp(), "tools/call", 1, map[string]interface{}{
		"_meta": elicitingMeta(), "name": "release",
		"arguments": map[string]interface{}{}, "inputResponses": acceptance(true),
	})
	if err != nil {
		t.Fatalf("error: %v", err)
	}
	want := "parameter 'inputResponses' requires the requestState it was issued with"
	if mcpErrorOf(t, resp)["message"] != want {
		t.Errorf("got %v", resp)
	}
}

func TestMCPMalformedAnswerIsAProtocolError(t *testing.T) {
	responses := driveConfirmation(t, confirmingApp(), map[string]interface{}{
		mcpConfirmationKey: map[string]interface{}{"action": "shrug"},
	})
	want := fmt.Sprintf("inputResponses['%s'] is not an elicitation result", mcpConfirmationKey)
	if mcpErrorOf(t, responses[1])["message"] != want {
		t.Errorf("got %v", responses[1])
	}
}

// TestMCPContinuationAcceptsOnlyCanonicalBase64URL pins that §22.4's blob is
// unpadded base64url and no other spelling of it.
//
// Left to themselves the three languages' decoders disagree: Python's accepts
// padding and Node's ignores anything outside the alphabet, while Go's refuses
// both -- and all three ignore a newline or the trailing bits of a final
// character that does not fill a byte. The blob is attacker-controlled input,
// so the spelling is checked before any decoder sees it, identically
// everywhere.
func TestMCPContinuationAcceptsOnlyCanonicalBase64URL(t *testing.T) {
	const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
	continuation := newMCPContinuation()
	var now int64 = 1000000
	good := continuation.mint("cli/1.0.0", "digest", now)
	head, mac, _ := strings.Cut(good, ".")
	// The same data bits with a flipped ignored trailing bit: a lax decoder
	// yields the identical MAC bytes and accepts the blob.
	noisy := mac[:len(mac)-1] + string(alphabet[strings.IndexByte(alphabet, mac[len(mac)-1])^1])
	spellings := map[string]string{
		"padding":      good + "=",
		"outside":      good + "*",
		"newline":      head[:5] + "\n" + head[5:] + "." + mac,
		"trailingBits": head + "." + noisy,
	}
	for name, spelling := range spellings {
		t.Run(name, func(t *testing.T) {
			if refusal := continuation.verify(spelling, "cli/1.0.0", "digest", now); refusal != mcpErrStateVerification {
				t.Errorf("accepted a non-canonical spelling (%q): %q", spelling, refusal)
			}
		})
	}
	// The canonical spelling still verifies, and is consumed doing so.
	if refusal := continuation.verify(good, "cli/1.0.0", "digest", now); refusal != "" {
		t.Errorf("the canonical spelling was refused: %q", refusal)
	}
}

func TestMCPContinuationExpiryAndIsolation(t *testing.T) {
	// No clock reaches the wire, so expiry is driven at the mint.
	continuation := newMCPContinuation()
	var now int64 = 1000000
	state := continuation.mint("cli/1.0.0", "digest", now)
	if refusal := continuation.verify(state, "cli/1.0.0", "digest", now+mcpContinuationTTLSeconds-1); refusal != "" {
		t.Fatalf("a state inside its window was refused: %s", refusal)
	}
	fresh := continuation.mint("cli/1.0.0", "digest", now)
	if refusal := continuation.verify(fresh, "cli/1.0.0", "digest", now+mcpContinuationTTLSeconds+1); refusal != mcpErrStateExpired {
		t.Errorf("expiry: got %q", refusal)
	}

	other := newMCPContinuation()
	if refusal := other.verify(state, "cli/1.0.0", "digest", now); refusal != mcpErrStateVerification {
		t.Errorf("another process accepted the blob: %q", refusal)
	}
}
