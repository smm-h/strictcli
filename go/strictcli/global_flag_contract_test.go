package strictcli

import (
	"fmt"
	"strings"
	"testing"
)

func TestTagContractSatisfiedByGlobalFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("json", "output json", Default(false)))
	app.TagContract("json", "json")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("ok")
		return 0
	}, WithTags("json"))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0 (global flag satisfies contract), got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "ok" {
		t.Fatalf("expected stdout %q, got %q", "ok", r.Stdout)
	}
}

// RegisterHandler + TagContract: struct handler tagged "json" with a global --json flag
// satisfying the tag contract should register without error and execute correctly.
type TagContractHandler struct {
	Name string `cli:"name" help:"Who to greet"`
}

func (h *TagContractHandler) Run(ctx *Context) int {
	g := Globals[TagContractGlobals](ctx)
	if g.JSON {
		ctx.Emit(map[string]interface{}{"greeting": "Hello, " + h.Name + "!"})
	} else {
		ctx.Info("Hello, " + h.Name + "!")
	}
	return 0
}

type TagContractGlobals struct {
	JSON bool `cli:"json" help:"Output as JSON" default:"false"`
}

func TestRegisterHandler_TagContractSatisfiedByGlobalFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[TagContractGlobals](app)
	app.TagContract("json", "json")
	app.RegisterHandler("greet", "greet someone", func() Handler {
		return &TagContractHandler{}
	}, WithTags("json"))

	// Should register without panic (contract is satisfied by global flag).
	// Execute with --json flag to verify full integration.
	r := app.Test([]string{"--json", "greet", "--name", "world"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil when --json is set")
	}
	data := r.Data.(map[string]interface{})
	if data["greeting"] != "Hello, world!" {
		t.Errorf("greeting = %v, want 'Hello, world!'", data["greeting"])
	}

	// Execute without --json flag to verify text mode.
	r = app.Test([]string{"greet", "--name", "world"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "Hello, world!") {
		t.Fatalf("expected 'Hello, world!' in stdout, got %q", r.Stdout)
	}
}

// Emit data return + Call(): RegisterHandler command that calls ctx.Emit(data),
// invoked via Call() returns the Emit'd data.
type EmitCallHandler struct {
	Key   string `cli:"key" help:"Data key"`
	Value string `cli:"value" help:"Data value"`
}

func (h *EmitCallHandler) Run(ctx *Context) int {
	ctx.Emit(map[string]interface{}{
		h.Key: h.Value,
	})
	return 0
}

func TestRegisterHandler_EmitReturnedViaCall(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("store", "store data", func() Handler {
		return &EmitCallHandler{}
	})

	result, err := app.Call("store", map[string]interface{}{
		"key":   "status",
		"value": "active",
	})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	data, ok := result.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map[string]interface{}, got %T: %v", result, result)
	}
	if data["status"] != "active" {
		t.Errorf("status = %v, want 'active'", data["status"])
	}
}
