package strictcli

import (
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
	))
	app.Command("status", "check status", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	})
	app.Command("secret", "hidden command", nopHandler, WithHidden())
	app.Command("wizard", "interactive wizard", nopHandler, WithInteractive())

	dns := app.Group("dns", "manage DNS")
	dns.Command("list", "list DNS records", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithFlags(
		StringFlag("zone", "DNS zone"),
	))

	return app
}

// sendMCPRequest sends a JSON-RPC request and reads the response.
func sendMCPRequest(app *App, method string, id interface{}, params map[string]interface{}) (map[string]interface{}, error) {
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

	if result["protocolVersion"] != "2024-11-05" {
		t.Errorf("expected protocolVersion '2024-11-05', got %v", result["protocolVersion"])
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

	capabilities, ok := result["capabilities"].(map[string]interface{})
	if !ok {
		t.Fatalf("expected capabilities object, got %T", result["capabilities"])
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

	// Should have: greet, status, dns_list (hidden/interactive excluded)
	if len(tools) != 3 {
		t.Fatalf("expected 3 tools, got %d: %v", len(tools), toolNames(tools))
	}

	nameSet := make(map[string]bool)
	for _, tool := range tools {
		toolMap := tool.(map[string]interface{})
		nameSet[toolMap["name"].(string)] = true
	}

	expectedNames := []string{"greet", "status", "dns_list"}
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
	))

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
	))

	resp, err := sendMCPRequest(app, "tools/call", 5, map[string]interface{}{
		"name": "dns_list",
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
	))

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
	})

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
		return ExitData(0, map[string]interface{}{"status": "ok", "count": 42})
	})

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
	))

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
	))

	// MCP name would be "dns_zone_list" -- should resolve to "dns.zone-list"
	// not "dns.zone.list" (which doesn't exist)
	resp, err := sendMCPRequest(app, "tools/call", 1, map[string]interface{}{
		"name":      "dns_zone_list",
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

func TestMCPNameResolutionNestedGroup(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("testapp", "1.0.0", "test application")
	dns := app.Group("dns", "manage DNS")
	zone := dns.Group("zone", "manage zones")
	zone.Command("create", "create a zone", captureHandler(&captured), WithFlags(
		StringFlag("name", "zone name"),
	))

	// MCP name "dns_zone_create" -> should resolve to "dns.zone.create"
	resp, err := sendMCPRequest(app, "tools/call", 1, map[string]interface{}{
		"name": "dns_zone_create",
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
	))

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
