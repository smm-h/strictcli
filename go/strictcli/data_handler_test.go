package strictcli

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
)

// --- DataCommand + Test() ---

func TestDataCommandTestReturnsData(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.DataCommand("info", "get info", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data: map[string]interface{}{
				"name":    kwargs["name"],
				"version": "2.0",
			},
			ExitCode: 0,
		}
	}, WithFlags(
		StringFlag("name", "thing name"),
	))

	r := app.Test([]string{"info", "--name", "widget"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil for DataCommand")
	}
	data, ok := r.Data.(map[string]interface{})
	if !ok {
		t.Fatalf("expected Data to be map[string]interface{}, got %T", r.Data)
	}
	if data["name"] != "widget" {
		t.Fatalf("expected name='widget', got %v", data["name"])
	}
	if data["version"] != "2.0" {
		t.Fatalf("expected version='2.0', got %v", data["version"])
	}
}

func TestDataCommandTestNilData(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.DataCommand("noop", "do nothing", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{Data: nil, ExitCode: 0}
	})

	r := app.Test([]string{"noop"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if r.Data != nil {
		t.Fatalf("expected Data to be nil, got %v", r.Data)
	}
}

func TestDataCommandTestExitCode(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.DataCommand("fail", "fail with data", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data:     map[string]string{"error": "something broke"},
			ExitCode: 2,
		}
	})

	r := app.Test([]string{"fail"})
	if r.ExitCode != 2 {
		t.Fatalf("expected exit 2, got %d", r.ExitCode)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil even with non-zero exit")
	}
}

// --- Old-style Command: Data is nil ---

func TestOldStyleCommandDataIsNil(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("greet", "say hi", func(kwargs map[string]interface{}) int {
		return 0
	})

	r := app.Test([]string{"greet"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if r.Data != nil {
		t.Fatalf("expected Data to be nil for old-style handler, got %v", r.Data)
	}
}

// --- Call() ---

func TestCallDataCommandReturnsData(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.DataCommand("lookup", "look up data", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data:     map[string]interface{}{"found": true, "id": kwargs["id"]},
			ExitCode: 0,
		}
	}, WithFlags(
		StringFlag("id", "item ID"),
	))

	result, err := app.Call("lookup", map[string]interface{}{"id": "abc123"})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	data, ok := result.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map[string]interface{}, got %T", result)
	}
	if data["found"] != true {
		t.Fatalf("expected found=true, got %v", data["found"])
	}
	if data["id"] != "abc123" {
		t.Fatalf("expected id='abc123', got %v", data["id"])
	}
}

func TestCallOldStyleCommandReturnsExitCode(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("ping", "ping", func(kwargs map[string]interface{}) int {
		return 42
	})

	result, err := app.Call("ping", map[string]interface{}{})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	exitCode, ok := result.(int)
	if !ok {
		t.Fatalf("expected int, got %T", result)
	}
	if exitCode != 42 {
		t.Fatalf("expected exit code 42, got %d", exitCode)
	}
}

func TestCallOldStyleCommandReturnsZero(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("ok", "ok", func(kwargs map[string]interface{}) int {
		return 0
	})

	result, err := app.Call("ok", map[string]interface{}{})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	exitCode, ok := result.(int)
	if !ok {
		t.Fatalf("expected int, got %T", result)
	}
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
}

// --- InvokeError ---

func TestCallInvokeErrorForUnknownCommand(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("greet", "say hi", func(kwargs map[string]interface{}) int { return 0 })

	_, err := app.Call("nonexistent", map[string]interface{}{})
	if err == nil {
		t.Fatal("expected error for unknown command")
	}
	var invokeErr *InvokeError
	if !errors.As(err, &invokeErr) {
		t.Fatalf("expected *InvokeError, got %T: %v", err, err)
	}
	if !strings.Contains(invokeErr.Message, "unknown command") {
		t.Fatalf("expected 'unknown command' in message, got %q", invokeErr.Message)
	}
}

func TestCallInvokeErrorForMissingRequiredFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(kwargs map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("target", "deploy target")),
	)

	_, err := app.Call("deploy", map[string]interface{}{})
	if err == nil {
		t.Fatal("expected error for missing required flag")
	}
	var invokeErr *InvokeError
	if !errors.As(err, &invokeErr) {
		t.Fatalf("expected *InvokeError, got %T: %v", err, err)
	}
	if !strings.Contains(invokeErr.Message, "required") {
		t.Fatalf("expected 'required' in message, got %q", invokeErr.Message)
	}
}

func TestCallInvokeErrorForMutexViolation(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("out", "output", func(kwargs map[string]interface{}) int { return 0 },
		WithMutex(MutexGroup{Flags: []Flag{
			StringFlag("json-out", "JSON output", Default(nil)),
			StringFlag("text-out", "text output", Default(nil)),
		}}),
	)

	_, err := app.Call("out", map[string]interface{}{"json_out": "data", "text_out": "data"})
	if err == nil {
		t.Fatal("expected error for mutex violation")
	}
	var invokeErr *InvokeError
	if !errors.As(err, &invokeErr) {
		t.Fatalf("expected *InvokeError, got %T: %v", err, err)
	}
	if !strings.Contains(invokeErr.Message, "mutually exclusive") {
		t.Fatalf("expected 'mutually exclusive' in message, got %q", invokeErr.Message)
	}
}

func TestCallInvokeErrorForUnknownParameter(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("greet", "say hi", func(kwargs map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("name", "who to greet")),
	)

	_, err := app.Call("greet", map[string]interface{}{
		"name":    "world",
		"unknown": "param",
	})
	if err == nil {
		t.Fatal("expected error for unknown parameter")
	}
	var invokeErr *InvokeError
	if !errors.As(err, &invokeErr) {
		t.Fatalf("expected *InvokeError, got %T: %v", err, err)
	}
	if !strings.Contains(invokeErr.Message, "unknown parameter") {
		t.Fatalf("expected 'unknown parameter' in message, got %q", invokeErr.Message)
	}
}

// --- Call() with nested commands ---

func TestCallNestedGroupCommand(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	dns := app.Group("dns", "DNS commands")
	zone := dns.Group("zone", "zone commands")
	zone.DataCommand("create", "create a zone", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data:     map[string]interface{}{"zone": kwargs["name"], "created": true},
			ExitCode: 0,
		}
	}, WithFlags(StringFlag("name", "zone name")))

	result, err := app.Call("dns.zone.create", map[string]interface{}{"name": "example.com"})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	data, ok := result.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map[string]interface{}, got %T", result)
	}
	if data["zone"] != "example.com" {
		t.Fatalf("expected zone='example.com', got %v", data["zone"])
	}
	if data["created"] != true {
		t.Fatalf("expected created=true, got %v", data["created"])
	}
}

func TestCallNestedOldStyleCommand(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	grp := app.Group("db", "database commands")
	grp.Command("migrate", "run migrations", func(kwargs map[string]interface{}) int {
		return 0
	}, WithFlags(BoolFlag("dry-run", "preview only", Default(false))))

	result, err := app.Call("db.migrate", map[string]interface{}{"dry_run": true})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	exitCode, ok := result.(int)
	if !ok {
		t.Fatalf("expected int, got %T", result)
	}
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d", exitCode)
	}
}

// --- Backward compatibility ---

func TestBackwardCompatExistingHandlersUnchanged(t *testing.T) {
	// Verify that existing handlers work exactly as before.
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy something", func(kwargs map[string]interface{}) int {
		captured = kwargs
		return 0
	}, WithFlags(
		StringFlag("target", "deploy target"),
		BoolFlag("dry-run", "dry run mode", Default(false)),
	))

	r := app.Test([]string{"deploy", "--target", "production", "--dry-run"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data != nil {
		t.Fatalf("expected Data to be nil for old-style handler, got %v", r.Data)
	}
	if captured["target"] != "production" {
		t.Fatalf("expected target='production', got %v", captured["target"])
	}
	if captured["dry_run"] != true {
		t.Fatalf("expected dry_run=true, got %v", captured["dry_run"])
	}
}

// --- DataCommand in groups ---

func TestGroupDataCommand(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	grp := app.Group("api", "API commands")
	grp.DataCommand("status", "get API status", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data:     map[string]string{"status": "healthy"},
			ExitCode: 0,
		}
	})

	r := app.Test([]string{"api", "status"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil for DataCommand in group")
	}
	data, ok := r.Data.(map[string]string)
	if !ok {
		t.Fatalf("expected map[string]string, got %T", r.Data)
	}
	if data["status"] != "healthy" {
		t.Fatalf("expected status='healthy', got %v", data["status"])
	}
}

// --- DataCommand + Call() consistency ---

func TestCallAndTestDataConsistency(t *testing.T) {
	makeApp := func() *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.DataCommand("info", "get info", func(kwargs map[string]interface{}) HandlerResult {
			return HandlerResult{
				Data:     map[string]interface{}{"name": kwargs["name"]},
				ExitCode: 0,
			}
		}, WithFlags(StringFlag("name", "the name")))
		return app
	}

	// Via Call
	app1 := makeApp()
	callResult, err := app1.Call("info", map[string]interface{}{"name": "test"})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}

	// Via Test
	app2 := makeApp()
	testResult := app2.Test([]string{"info", "--name", "test"})
	if testResult.ExitCode != 0 {
		t.Fatalf("Test failed: %s", testResult.Stderr)
	}

	// Both should return equivalent data
	callData, ok := callResult.(map[string]interface{})
	if !ok {
		t.Fatalf("Call result type: %T", callResult)
	}
	testData, ok := testResult.Data.(map[string]interface{})
	if !ok {
		t.Fatalf("Test Data type: %T", testResult.Data)
	}
	if !reflect.DeepEqual(callData, testData) {
		t.Fatalf("data mismatch:\nCall: %v\nTest: %v", callData, testData)
	}
}

// --- Run() with DataCommand prints JSON ---

func TestDataCommandRunPrintsJSON(t *testing.T) {
	// We can't test Run() directly (it calls os.Exit), but we can verify
	// that Test() with a DataCommand captures the handler's data correctly
	// and that the data would be serializable to JSON.
	app := NewApp("myapp", "1.0.0", "test app")
	app.DataCommand("export", "export data", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data: map[string]interface{}{
				"items": []string{"a", "b", "c"},
				"count": 3,
			},
			ExitCode: 0,
		}
	})

	r := app.Test([]string{"export"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	// Verify the data is JSON-serializable (as Run() would do)
	jsonBytes, err := json.Marshal(r.Data)
	if err != nil {
		t.Fatalf("Data not JSON-serializable: %v", err)
	}
	var decoded map[string]interface{}
	if err := json.Unmarshal(jsonBytes, &decoded); err != nil {
		t.Fatalf("JSON round-trip failed: %v", err)
	}
	if decoded["count"] != float64(3) { // JSON numbers are float64
		t.Fatalf("expected count=3, got %v", decoded["count"])
	}
}

// --- DataHandler with nil Data (data handler returns no data) ---

func TestCallDataCommandNilData(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.DataCommand("noop", "no operation", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{Data: nil, ExitCode: 0}
	})

	// When Data is nil, Call returns exit code (like old-style handler)
	result, err := app.Call("noop", map[string]interface{}{})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	// With nil data, Call returns exit code as int
	exitCode, ok := result.(int)
	if !ok {
		t.Fatalf("expected int (exit code) when Data is nil, got %T: %v", result, result)
	}
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d", exitCode)
	}
}

// --- Call with passthrough command ---

func TestCallPassthroughCommand(t *testing.T) {
	var capturedArgs []string
	app := NewApp("myapp", "1.0.0", "test app")
	app.Passthrough("exec", "execute", func(name string, args []string, globals map[string]interface{}) int {
		capturedArgs = args
		return 0
	})

	result, err := app.Call("exec", map[string]interface{}{
		"_args": []string{"ls", "-la"},
	})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	exitCode, ok := result.(int)
	if !ok {
		t.Fatalf("expected int, got %T", result)
	}
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d", exitCode)
	}
	if len(capturedArgs) != 2 || capturedArgs[0] != "ls" {
		t.Fatalf("unexpected args: %v", capturedArgs)
	}
}

// --- InvokeError implements error interface ---

func TestInvokeErrorInterface(t *testing.T) {
	err := &InvokeError{Message: "something went wrong"}
	if err.Error() != "something went wrong" {
		t.Fatalf("expected 'something went wrong', got %q", err.Error())
	}
	// Verify it satisfies the error interface
	var e error = err
	if e == nil {
		t.Fatal("InvokeError should satisfy error interface")
	}
}

// --- Call with global flags ---

func TestCallDataCommandWithGlobalFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("verbose", "verbose output", Default(false)))
	app.DataCommand("info", "get info", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data: map[string]interface{}{
				"verbose": kwargs["verbose"],
			},
			ExitCode: 0,
		}
	})

	result, err := app.Call("info", map[string]interface{}{"verbose": true})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	data, ok := result.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map, got %T", result)
	}
	if data["verbose"] != true {
		t.Fatalf("expected verbose=true, got %v", data["verbose"])
	}
}

// --- Mixed old and data commands in same app ---

func TestMixedCommandTypes(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")

	// Old-style
	app.Command("old", "old style", func(kwargs map[string]interface{}) int {
		return 0
	})

	// Data style
	app.DataCommand("new", "new style", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{Data: "hello", ExitCode: 0}
	})

	// Old-style via Test
	r1 := app.Test([]string{"old"})
	if r1.Data != nil {
		t.Fatalf("expected nil Data for old command, got %v", r1.Data)
	}

	// Data-style via Test
	r2 := app.Test([]string{"new"})
	if r2.Data != "hello" {
		t.Fatalf("expected Data='hello', got %v", r2.Data)
	}

	// Old-style via Call
	result1, err := app.Call("old", map[string]interface{}{})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	if _, ok := result1.(int); !ok {
		t.Fatalf("expected int from old command Call, got %T", result1)
	}

	// Data-style via Call
	result2, err := app.Call("new", map[string]interface{}{})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	if result2 != "hello" {
		t.Fatalf("expected 'hello' from data command Call, got %v", result2)
	}
}
