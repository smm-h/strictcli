package strictcli

import (
	"strings"
	"testing"
)

// --- Exit / ExitData via Test and Call ---

func TestExitOutcomeSetsExitCodeNoData(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(3)
	})
	r := app.Test([]string{"run"})
	if r.ExitCode != 3 {
		t.Fatalf("exit = %d, want 3", r.ExitCode)
	}
	if r.Data != nil {
		t.Fatalf("Data = %v, want nil", r.Data)
	}
	if r.Stdout != "" {
		t.Fatalf("Stdout = %q, want empty", r.Stdout)
	}
}

func TestExitDataPrintsJSONAndCaptures(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("info", "get info", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return ExitData(0, map[string]interface{}{"name": "widget", "count": 42})
	})
	r := app.Test([]string{"info"})
	if r.ExitCode != 0 {
		t.Fatalf("exit = %d: %s", r.ExitCode, r.Stderr)
	}
	// Data captured for programmatic callers.
	data, ok := r.Data.(map[string]interface{})
	if !ok {
		t.Fatalf("Data type = %T, want map", r.Data)
	}
	if data["name"] != "widget" {
		t.Fatalf("Data[name] = %v, want widget", data["name"])
	}
	// JSON printed to stdout (mirrors Run behavior).
	if !strings.Contains(r.Stdout, `"name":"widget"`) {
		t.Fatalf("Stdout = %q, want JSON with name", r.Stdout)
	}
}

func TestExitDataNilDataDoesNotPrint(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("info", "get info", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return ExitData(0, nil)
	})
	r := app.Test([]string{"info"})
	if r.Stdout != "" {
		t.Fatalf("Stdout = %q, want empty for nil data", r.Stdout)
	}
	if r.Data != nil {
		t.Fatalf("Data = %v, want nil", r.Data)
	}
}

func TestExitDataReturnedViaCall(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("store", "store data", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return ExitData(0, map[string]interface{}{Get[string](kwargs, "key"): Get[string](kwargs, "value")})
	}, WithFlags(
		StringFlag("key", "data key"),
		StringFlag("value", "data value"),
	))
	result, err := app.Call("store", map[string]interface{}{"key": "status", "value": "active"})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	data, ok := result.(map[string]interface{})
	if !ok {
		t.Fatalf("result type = %T, want map", result)
	}
	if data["status"] != "active" {
		t.Fatalf("data[status] = %v, want active", data["status"])
	}
}

// --- Get ---

func TestGetReturnsTypedValue(t *testing.T) {
	kwargs := map[string]interface{}{"name": "x", "count": 7, "on": true}
	if got := Get[string](kwargs, "name"); got != "x" {
		t.Fatalf("Get string = %q", got)
	}
	if got := Get[int](kwargs, "count"); got != 7 {
		t.Fatalf("Get int = %d", got)
	}
	if got := Get[bool](kwargs, "on"); got != true {
		t.Fatalf("Get bool = %v", got)
	}
}

func TestGetPanicsOnAbsentKey(t *testing.T) {
	expectPanic(t, "no such key", func() { Get[string](map[string]interface{}{}, "missing") })
}

func TestGetPanicsOnNilValue(t *testing.T) {
	expectPanic(t, "is nil", func() { Get[string](map[string]interface{}{"k": nil}, "k") })
}

func TestGetPanicsOnWrongType(t *testing.T) {
	expectPanic(t, "dynamic type", func() { Get[string](map[string]interface{}{"k": 5}, "k") })
}

// --- GetOpt ---

func TestGetOptPresent(t *testing.T) {
	v, ok := GetOpt[string](map[string]interface{}{"k": "v"}, "k")
	if !ok || v != "v" {
		t.Fatalf("GetOpt = (%q,%v), want (v,true)", v, ok)
	}
}

func TestGetOptNilReturnsFalse(t *testing.T) {
	v, ok := GetOpt[string](map[string]interface{}{"k": nil}, "k")
	if ok || v != "" {
		t.Fatalf("GetOpt = (%q,%v), want (\"\",false)", v, ok)
	}
}

func TestGetOptPanicsOnAbsentKey(t *testing.T) {
	expectPanic(t, "no such key", func() { GetOpt[string](map[string]interface{}{}, "missing") })
}

func TestGetOptPanicsOnWrongType(t *testing.T) {
	expectPanic(t, "dynamic type", func() { GetOpt[int](map[string]interface{}{"k": "s"}, "k") })
}

// --- Passthrough receives a Context ---

func TestPassthroughReceivesContext(t *testing.T) {
	var gotCtx bool
	app := NewApp("myapp", "1.0.0", "test app")
	app.Passthrough("exec", "execute", func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
		gotCtx = ctx != nil
		ctx.Warn("passthrough ran")
		return 7
	})
	r := app.Test([]string{"exec", "a", "b"})
	if !gotCtx {
		t.Fatal("passthrough did not receive a non-nil Context")
	}
	if r.ExitCode != 7 {
		t.Fatalf("exit = %d, want 7", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "passthrough ran") {
		t.Fatalf("Stderr = %q, want warning", r.Stderr)
	}
}

// --- Globals are merged into the handler kwargs ---

func TestGlobalsMergedIntoKwargs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("verbose", "verbose", Default(false)))
	var captured bool
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		captured = Get[bool](kwargs, "verbose")
		return Exit(0)
	})
	r := app.Test([]string{"--verbose", "run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit = %d: %s", r.ExitCode, r.Stderr)
	}
	if !captured {
		t.Fatal("global flag 'verbose' not visible in handler kwargs")
	}
}

// TestTestCaptureLargeOutputNotTruncated verifies Test() captures handler
// output larger than the OS pipe buffer (~64KB) without truncation or
// deadlock. Regression for phase 8.3go: fixed 64KB read buffers truncated
// output and a single non-draining read could block the writing handler.
func TestTestCaptureLargeOutputNotTruncated(t *testing.T) {
	const n = 500 * 1024 // 500KB, well beyond a 64KB pipe buffer
	payload := strings.Repeat("a", n)

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("emit", "emit a large payload", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.Info(payload)  // stdout
		ctx.Error(payload) // stderr
		return Exit(0)
	})

	r := app.Test([]string{"emit"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d, stderr len %d", r.ExitCode, len(r.Stderr))
	}
	// Info/Error append a trailing newline.
	if len(r.Stdout) != n+1 {
		t.Fatalf("stdout truncated: expected %d bytes, got %d", n+1, len(r.Stdout))
	}
	if len(r.Stderr) != n+1 {
		t.Fatalf("stderr truncated: expected %d bytes, got %d", n+1, len(r.Stderr))
	}
	if strings.TrimRight(r.Stdout, "\n") != payload {
		t.Fatal("stdout content corrupted")
	}
	if strings.TrimRight(r.Stderr, "\n") != payload {
		t.Fatal("stderr content corrupted")
	}
}
