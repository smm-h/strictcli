package strictcli

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

// --- Basic struct handler ---

type GreetHandler struct {
	Name string `cli:"name" help:"Who to greet"`
}

func (h *GreetHandler) Run(ctx *Context) int {
	ctx.Info("Hello, " + h.Name + "!")
	return 0
}

func TestRegisterHandler_BasicTest(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("greet", "greet someone", func() Handler {
		return &GreetHandler{}
	})

	r := app.Test([]string{"greet", "--name", "world"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "Hello, world!") {
		t.Fatalf("expected stdout to contain 'Hello, world!', got %q", r.Stdout)
	}
}

// --- All scalar types ---

type AllScalarsHandler struct {
	Name    string  `cli:"name" help:"Name"`
	Verbose bool    `cli:"verbose" help:"Verbose" default:"false"`
	Count   int     `cli:"count" help:"Count"`
	Rate    float64 `cli:"rate" help:"Rate"`
}

func (h *AllScalarsHandler) Run(ctx *Context) int {
	ctx.Emit(map[string]interface{}{
		"name":    h.Name,
		"verbose": h.Verbose,
		"count":   h.Count,
		"rate":    h.Rate,
	})
	return 0
}

func TestRegisterHandler_AllScalarTypes(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("test", "test all types", func() Handler {
		return &AllScalarsHandler{}
	})

	r := app.Test([]string{"test", "--name", "foo", "--verbose", "--count", "42", "--rate", "3.14"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil")
	}
	data := r.Data.(map[string]interface{})
	if data["name"] != "foo" {
		t.Errorf("name = %v, want 'foo'", data["name"])
	}
	if data["verbose"] != true {
		t.Errorf("verbose = %v, want true", data["verbose"])
	}
	if data["count"] != 42 {
		t.Errorf("count = %v, want 42", data["count"])
	}
	if data["rate"] != 3.14 {
		t.Errorf("rate = %v, want 3.14", data["rate"])
	}
}

// --- Pointer types ---

type PointerHandler struct {
	Output *string `cli:"output" help:"Output file"`
}

func (h *PointerHandler) Run(ctx *Context) int {
	if h.Output == nil {
		ctx.Info("no output")
	} else {
		ctx.Info("output=" + *h.Output)
	}
	return 0
}

func TestRegisterHandler_PointerNilWhenNotPassed(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test pointers", func() Handler {
		return &PointerHandler{}
	})

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "no output") {
		t.Fatalf("expected 'no output', got %q", r.Stdout)
	}
}

func TestRegisterHandler_PointerSetWhenPassed(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test pointers", func() Handler {
		return &PointerHandler{}
	})

	r := app.Test([]string{"cmd", "--output", "file.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "output=file.txt") {
		t.Fatalf("expected 'output=file.txt', got %q", r.Stdout)
	}
}

// --- Required bool (no default) ---

type RequiredBoolHandler struct {
	DryRun bool `cli:"dry-run" help:"Dry run mode"`
}

func (h *RequiredBoolHandler) Run(ctx *Context) int {
	if h.DryRun {
		ctx.Info("dry run")
	} else {
		ctx.Info("live run")
	}
	return 0
}

func TestRegisterHandler_RequiredBoolError(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test required bool", func() Handler {
		return &RequiredBoolHandler{}
	})

	r := app.Test([]string{"cmd"})
	if r.ExitCode == 0 {
		t.Fatalf("expected non-zero exit for missing required bool")
	}
	if !strings.Contains(r.Stderr, "must be passed as") {
		t.Fatalf("expected 'must be passed as' in stderr, got %q", r.Stderr)
	}
}

func TestRegisterHandler_RequiredBoolTrue(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test required bool", func() Handler {
		return &RequiredBoolHandler{}
	})

	r := app.Test([]string{"cmd", "--dry-run"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "dry run") {
		t.Fatalf("expected 'dry run', got %q", r.Stdout)
	}
}

func TestRegisterHandler_RequiredBoolFalse(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test required bool", func() Handler {
		return &RequiredBoolHandler{}
	})

	r := app.Test([]string{"cmd", "--no-dry-run"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "live run") {
		t.Fatalf("expected 'live run', got %q", r.Stdout)
	}
}

// --- Dash-to-underscore flag names ---

type DashFlagHandler struct {
	DryRun bool `cli:"dry-run" help:"Dry run" default:"false"`
}

func (h *DashFlagHandler) Run(ctx *Context) int {
	if h.DryRun {
		ctx.Info("dry")
	} else {
		ctx.Info("live")
	}
	return 0
}

func TestRegisterHandler_DashFlagNames(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "dash flags", func() Handler {
		return &DashFlagHandler{}
	})

	r := app.Test([]string{"cmd", "--dry-run"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "dry") {
		t.Fatalf("expected 'dry', got %q", r.Stdout)
	}
}

// --- Compound types: []string list ---

type ListHandler struct {
	Tags []string `cli:"tag" help:"Tags" unique:"true" env:"TAGS" env_separator:","`
}

func (h *ListHandler) Run(ctx *Context) int {
	ctx.Emit(h.Tags)
	return 0
}

func TestRegisterHandler_ListFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "list flags", func() Handler {
		return &ListHandler{}
	})

	r := app.Test([]string{"cmd", "--tag", "a", "--tag", "b", "--tag", "c"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil")
	}
	tags := r.Data.([]string)
	if len(tags) != 3 || tags[0] != "a" || tags[1] != "b" || tags[2] != "c" {
		t.Fatalf("expected [a b c], got %v", tags)
	}
}

// --- Compound types: map[string]string dict ---

type DictHandler struct {
	Labels map[string]string `cli:"label" help:"Labels" unique:"true"`
}

func (h *DictHandler) Run(ctx *Context) int {
	ctx.Emit(h.Labels)
	return 0
}

func TestRegisterHandler_DictFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "dict flags", func() Handler {
		return &DictHandler{}
	})

	r := app.Test([]string{"cmd", "--label", "env=prod", "--label", "team=core"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil")
	}
	labels := r.Data.(map[string]string)
	if labels["env"] != "prod" {
		t.Errorf("labels[env] = %q, want 'prod'", labels["env"])
	}
	if labels["team"] != "core" {
		t.Errorf("labels[team] = %q, want 'core'", labels["team"])
	}
}

// --- Variadic args ---

type VariadicHandler struct {
	Files []string `arg:"files" help:"Files to process" variadic:"true"`
}

func (h *VariadicHandler) Run(ctx *Context) int {
	ctx.Emit(h.Files)
	return 0
}

func TestRegisterHandler_VariadicArgs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "variadic args", func() Handler {
		return &VariadicHandler{}
	})

	r := app.Test([]string{"cmd", "a.txt", "b.txt", "c.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil")
	}
	files := r.Data.([]string)
	if len(files) != 3 || files[0] != "a.txt" {
		t.Fatalf("expected [a.txt b.txt c.txt], got %v", files)
	}
}

// --- Embedded structs (FlagSets) ---

type HandlerCommonFlags struct {
	Verbose bool `cli:"verbose" help:"Verbose output" default:"false"`
}

type EmbeddedHandler struct {
	HandlerCommonFlags
	Name string `cli:"name" help:"Name"`
}

func (h *EmbeddedHandler) Run(ctx *Context) int {
	ctx.Emit(map[string]interface{}{
		"verbose": h.Verbose,
		"name":    h.Name,
	})
	return 0
}

func TestRegisterHandler_EmbeddedStructs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "embedded structs", func() Handler {
		return &EmbeddedHandler{}
	})

	r := app.Test([]string{"cmd", "--verbose", "--name", "test"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	data := r.Data.(map[string]interface{})
	if data["verbose"] != true {
		t.Errorf("verbose = %v, want true", data["verbose"])
	}
	if data["name"] != "test" {
		t.Errorf("name = %v, want 'test'", data["name"])
	}
}

// --- CmdOptions: WithMutex alongside struct handler ---

type MutexHandler struct {
	JSON bool `cli:"json" help:"JSON output" default:"false"`
	Text bool `cli:"text" help:"Text output" default:"false"`
}

func (h *MutexHandler) Run(ctx *Context) int {
	return 0
}

func TestRegisterHandler_WithMutex(t *testing.T) {
	// WithMutex cannot be used with struct handlers because the flags come
	// from the struct, not from WithFlags. But WithDependencies can reference
	// the struct flags by name. Let me test WithDependencies + CoRequired.
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "mutex test", func() Handler {
		return &MutexHandler{}
	}, WithDependencies(
		CoRequired{Flags: []string{"json", "text"}},
	))

	// Providing both should work (co-required means all or none)
	r := app.Test([]string{"cmd", "--json", "--text"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0 with both, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}

	// Providing just one should fail
	r = app.Test([]string{"cmd", "--json"})
	if r.ExitCode == 0 {
		t.Fatal("expected error when providing only --json with CoRequired")
	}
}

// --- CmdOptions: WithDependencies (Requires) ---

type DepsHandler struct {
	Output string `cli:"output" help:"Output file"`
	Format string `cli:"format" help:"Output format" default:"text"`
}

func (h *DepsHandler) Run(ctx *Context) int {
	ctx.Info(h.Format + ":" + h.Output)
	return 0
}

func TestRegisterHandler_WithDependencies(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "deps test", func() Handler {
		return &DepsHandler{}
	}, WithDependencies(
		Requires{Flag: "format", DependsOn: "output"},
	))

	// --format without --output should fail
	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode == 0 {
		t.Fatal("expected error: --format requires --output")
	}
	if !strings.Contains(r.Stderr, "requires") {
		t.Fatalf("expected 'requires' in stderr, got %q", r.Stderr)
	}

	// --output with --format should work
	r = app.Test([]string{"cmd", "--output", "file.txt", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
}

// --- ctx.Info/Warn/Debug/Error routing ---

type OutputRoutingHandler struct {
	Msg string `cli:"msg" help:"Message" default:"test"`
}

func (h *OutputRoutingHandler) Run(ctx *Context) int {
	ctx.Info("info:" + h.Msg)
	ctx.Warn("warn:" + h.Msg)
	ctx.Debug("debug:" + h.Msg)
	ctx.Error("error:" + h.Msg)
	return 0
}

func TestRegisterHandler_OutputRouting(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "output routing", func() Handler {
		return &OutputRoutingHandler{}
	})

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	// Info and Debug go to stdout
	if !strings.Contains(r.Stdout, "info:test") {
		t.Errorf("expected 'info:test' in stdout, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "debug:test") {
		t.Errorf("expected 'debug:test' in stdout, got %q", r.Stdout)
	}
	// Warn and Error go to stderr
	if !strings.Contains(r.Stderr, "warn:test") {
		t.Errorf("expected 'warn:test' in stderr, got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "error:test") {
		t.Errorf("expected 'error:test' in stderr, got %q", r.Stderr)
	}
}

// --- ctx.Emit captured by Test (in result.Data) ---

type EmitHandler struct {
	Value string `cli:"value" help:"Value to emit"`
}

func (h *EmitHandler) Run(ctx *Context) int {
	ctx.Emit(map[string]interface{}{
		"result": h.Value,
	})
	return 0
}

func TestRegisterHandler_EmitCapturedByTest(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "emit test", func() Handler {
		return &EmitHandler{}
	})

	r := app.Test([]string{"cmd", "--value", "hello"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if r.Data == nil {
		t.Fatal("expected Data to be non-nil")
	}
	data, ok := r.Data.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map[string]interface{}, got %T", r.Data)
	}
	if data["result"] != "hello" {
		t.Errorf("result = %v, want 'hello'", data["result"])
	}

	// Also verify JSON was written to stdout
	var decoded map[string]interface{}
	if err := json.Unmarshal([]byte(strings.TrimSpace(r.Stdout)), &decoded); err != nil {
		t.Fatalf("stdout is not valid JSON: %v; stdout: %q", err, r.Stdout)
	}
	if decoded["result"] != "hello" {
		t.Errorf("decoded[result] = %v, want 'hello'", decoded["result"])
	}
}

// --- Call() on RegisterHandler command ---

func TestRegisterHandler_CallReturnsExitCode(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("greet", "greet", func() Handler {
		return &GreetHandler{}
	})

	result, err := app.Call("greet", map[string]interface{}{"name": "world"})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	exitCode, ok := result.(int)
	if !ok {
		t.Fatalf("expected int, got %T: %v", result, result)
	}
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d", exitCode)
	}
}

// --- Call() with Emit ---

func TestRegisterHandler_CallWithEmit(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "emit via call", func() Handler {
		return &EmitHandler{}
	})

	result, err := app.Call("cmd", map[string]interface{}{"value": "hello"})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	data, ok := result.(map[string]interface{})
	if !ok {
		t.Fatalf("expected map[string]interface{}, got %T: %v", result, result)
	}
	if data["result"] != "hello" {
		t.Errorf("result = %v, want 'hello'", data["result"])
	}
}

// --- Groups: group.RegisterHandler ---

type GroupHandler struct {
	Target string `cli:"target" help:"Deploy target"`
}

func (h *GroupHandler) Run(ctx *Context) int {
	ctx.Info("deploying to " + h.Target)
	return 0
}

func TestRegisterHandler_InGroup(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	grp := app.Group("deploy", "deployment commands")
	grp.RegisterHandler("run", "run deployment", func() Handler {
		return &GroupHandler{}
	})

	r := app.Test([]string{"deploy", "run", "--target", "production"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "deploying to production") {
		t.Fatalf("expected 'deploying to production', got %q", r.Stdout)
	}
}

func TestRegisterHandler_InGroupViaCall(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	grp := app.Group("deploy", "deployment commands")
	grp.RegisterHandler("run", "run deployment", func() Handler {
		return &GroupHandler{}
	})

	result, err := app.Call("deploy.run", map[string]interface{}{"target": "staging"})
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

// --- Nested groups ---

func TestRegisterHandler_NestedGroup(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	dns := app.Group("dns", "DNS commands")
	zone := dns.Group("zone", "zone commands")
	zone.RegisterHandler("create", "create zone", func() Handler {
		return &GreetHandler{}
	})

	r := app.Test([]string{"dns", "zone", "create", "--name", "example.com"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "Hello, example.com!") {
		t.Fatalf("expected greeting, got %q", r.Stdout)
	}
}

// --- Coexistence: old-style Command and RegisterHandler in same app ---

func TestRegisterHandler_CoexistenceWithOldStyle(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")

	// Old-style command
	var oldCaptured string
	app.Command("old", "old style", func(kwargs map[string]interface{}) int {
		oldCaptured = kwargs["name"].(string)
		return 0
	}, WithFlags(StringFlag("name", "name")))

	// Struct handler
	app.RegisterHandler("new", "new style", func() Handler {
		return &GreetHandler{}
	})

	// Test old-style
	r1 := app.Test([]string{"old", "--name", "alice"})
	if r1.ExitCode != 0 {
		t.Fatalf("old: expected exit 0, got %d; stderr: %s", r1.ExitCode, r1.Stderr)
	}
	if oldCaptured != "alice" {
		t.Errorf("old: name = %q, want 'alice'", oldCaptured)
	}
	if r1.Data != nil {
		t.Errorf("old: expected nil Data, got %v", r1.Data)
	}

	// Test new-style
	r2 := app.Test([]string{"new", "--name", "bob"})
	if r2.ExitCode != 0 {
		t.Fatalf("new: expected exit 0, got %d; stderr: %s", r2.ExitCode, r2.Stderr)
	}
	if !strings.Contains(r2.Stdout, "Hello, bob!") {
		t.Fatalf("new: expected 'Hello, bob!', got %q", r2.Stdout)
	}
}

// --- Global flags via Globals[T](ctx) in a RegisterHandler handler ---

type AppGlobals struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output" default:"false"`
}

type GlobalsAccessHandler struct {
	Name string `cli:"name" help:"Name"`
}

func (h *GlobalsAccessHandler) Run(ctx *Context) int {
	g := Globals[AppGlobals](ctx)
	if g.Verbose {
		ctx.Info("verbose: greeting " + h.Name)
	}
	ctx.Info("Hello, " + h.Name + "!")
	return 0
}

func TestRegisterHandler_GlobalsAccess(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[AppGlobals](app)
	app.RegisterHandler("greet", "greet with globals", func() Handler {
		return &GlobalsAccessHandler{}
	})

	r := app.Test([]string{"--verbose", "greet", "--name", "world"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "verbose: greeting world") {
		t.Fatalf("expected verbose message, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "Hello, world!") {
		t.Fatalf("expected greeting, got %q", r.Stdout)
	}
}

func TestRegisterHandler_GlobalsDefault(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[AppGlobals](app)
	app.RegisterHandler("greet", "greet with globals", func() Handler {
		return &GlobalsAccessHandler{}
	})

	r := app.Test([]string{"greet", "--name", "world"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	// Should NOT contain verbose message
	if strings.Contains(r.Stdout, "verbose:") {
		t.Fatalf("expected no verbose message, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "Hello, world!") {
		t.Fatalf("expected greeting, got %q", r.Stdout)
	}
}

// --- Non-zero exit code ---

type FailHandler struct {
	Code int `cli:"code" help:"Exit code"`
}

func (h *FailHandler) Run(ctx *Context) int {
	return h.Code
}

func TestRegisterHandler_NonZeroExitCode(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("fail", "fail with code", func() Handler {
		return &FailHandler{}
	})

	r := app.Test([]string{"fail", "--code", "42"})
	if r.ExitCode != 42 {
		t.Fatalf("expected exit 42, got %d", r.ExitCode)
	}
}

// --- Help shows struct-extracted flags ---

func TestRegisterHandler_HelpShowsFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test command", func() Handler {
		return &AllScalarsHandler{}
	})

	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	for _, flag := range []string{"--name", "--verbose", "--count", "--rate"} {
		if !strings.Contains(r.Stdout, flag) {
			t.Errorf("help should contain %s, got:\n%s", flag, r.Stdout)
		}
	}
}

// --- Fresh handler per invocation ---

type StatefulHandler struct {
	Name string `cli:"name" help:"Name" default:"default"`
	runs int
}

func (h *StatefulHandler) Run(ctx *Context) int {
	h.runs++
	ctx.Info(h.Name)
	return 0
}

func TestRegisterHandler_FreshInstancePerInvocation(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test", func() Handler {
		return &StatefulHandler{}
	})

	r1 := app.Test([]string{"cmd", "--name", "first"})
	if r1.ExitCode != 0 {
		t.Fatalf("first: exit %d; stderr: %s", r1.ExitCode, r1.Stderr)
	}
	if !strings.Contains(r1.Stdout, "first") {
		t.Fatalf("expected 'first', got %q", r1.Stdout)
	}

	r2 := app.Test([]string{"cmd", "--name", "second"})
	if r2.ExitCode != 0 {
		t.Fatalf("second: exit %d; stderr: %s", r2.ExitCode, r2.Stderr)
	}
	if !strings.Contains(r2.Stdout, "second") {
		t.Fatalf("expected 'second', got %q", r2.Stdout)
	}
}

// --- Positional args (non-variadic) ---

type PositionalHandler struct {
	Source string `arg:"source" help:"Source file"`
	Dest   string `arg:"dest" help:"Destination file"`
}

func (h *PositionalHandler) Run(ctx *Context) int {
	ctx.Info(h.Source + " -> " + h.Dest)
	return 0
}

func TestRegisterHandler_PositionalArgs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("copy", "copy files", func() Handler {
		return &PositionalHandler{}
	})

	r := app.Test([]string{"copy", "input.txt", "output.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "input.txt -> output.txt") {
		t.Fatalf("expected 'input.txt -> output.txt', got %q", r.Stdout)
	}
}

// --- Mixed flags and args ---

type MixedHandler struct {
	Source  string `arg:"source" help:"Source file"`
	Verbose bool   `cli:"verbose" help:"Verbose output" default:"false"`
}

func (h *MixedHandler) Run(ctx *Context) int {
	if h.Verbose {
		ctx.Info("verbose: " + h.Source)
	}
	ctx.Info(h.Source)
	return 0
}

func TestRegisterHandler_MixedFlagsAndArgs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "mixed", func() Handler {
		return &MixedHandler{}
	})

	r := app.Test([]string{"cmd", "--verbose", "input.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "verbose: input.txt") {
		t.Fatalf("expected 'verbose: input.txt', got %q", r.Stdout)
	}
}

// --- Call with missing required flag returns InvokeError ---

func TestRegisterHandler_CallMissingRequired(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("greet", "greet", func() Handler {
		return &GreetHandler{}
	})

	_, err := app.Call("greet", map[string]interface{}{})
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

// --- Handler with WithHidden ---

func TestRegisterHandler_WithHidden(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("secret", "hidden command", func() Handler {
		return &GreetHandler{}
	}, WithHidden())

	// Should work when invoked directly
	r := app.Test([]string{"secret", "--name", "hidden"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}

	// Should not appear in app help
	helpR := app.Test([]string{"--help"})
	if strings.Contains(helpR.Stdout, "secret") {
		t.Fatalf("hidden command should not appear in help, got:\n%s", helpR.Stdout)
	}
}

// --- Handler with short flags ---

type ShortFlagHandler struct {
	Verbose bool `cli:"verbose" help:"Verbose" short:"V" default:"false"`
}

func (h *ShortFlagHandler) Run(ctx *Context) int {
	if h.Verbose {
		ctx.Info("verbose")
	} else {
		ctx.Info("quiet")
	}
	return 0
}

func TestRegisterHandler_ShortFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "short flags", func() Handler {
		return &ShortFlagHandler{}
	})

	r := app.Test([]string{"cmd", "-V"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "verbose") {
		t.Fatalf("expected 'verbose', got %q", r.Stdout)
	}
}

// --- Handler with default values ---

type DefaultsHandler struct {
	Name   string `cli:"name" help:"Name" default:"stranger"`
	Count  int    `cli:"count" help:"Count" default:"1"`
	Loud   bool   `cli:"loud" help:"Loud" default:"false"`
}

func (h *DefaultsHandler) Run(ctx *Context) int {
	ctx.Emit(map[string]interface{}{
		"name":  h.Name,
		"count": h.Count,
		"loud":  h.Loud,
	})
	return 0
}

func TestRegisterHandler_Defaults(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "defaults test", func() Handler {
		return &DefaultsHandler{}
	})

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
	data := r.Data.(map[string]interface{})
	if data["name"] != "stranger" {
		t.Errorf("name = %v, want 'stranger'", data["name"])
	}
	if data["count"] != 1 {
		t.Errorf("count = %v, want 1", data["count"])
	}
	if data["loud"] != false {
		t.Errorf("loud = %v, want false", data["loud"])
	}
}

// --- Handler with choices ---

type ChoicesHandler struct {
	Format string `cli:"format" help:"Output format" choices:"json,text,yaml"`
}

func (h *ChoicesHandler) Run(ctx *Context) int {
	ctx.Info(h.Format)
	return 0
}

func TestRegisterHandler_Choices(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "choices test", func() Handler {
		return &ChoicesHandler{}
	})

	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}

	// Invalid choice
	r = app.Test([]string{"cmd", "--format", "xml"})
	if r.ExitCode == 0 {
		t.Fatal("expected error for invalid choice")
	}
	if !strings.Contains(r.Stderr, "must be one of") {
		t.Fatalf("expected 'must be one of' in stderr, got %q", r.Stderr)
	}
}

// --- Call with unknown parameter returns error ---

func TestRegisterHandler_CallUnknownParam(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "test", func() Handler {
		return &GreetHandler{}
	})

	_, err := app.Call("cmd", map[string]interface{}{
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

// --- Mixed old-style and RegisterHandler via Call ---

func TestRegisterHandler_MixedCallOldAndNew(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("old", "old style", func(kwargs map[string]interface{}) int {
		return 7
	})
	app.RegisterHandler("new", "new style", func() Handler {
		return &GreetHandler{}
	})

	// Call old-style
	result, err := app.Call("old", map[string]interface{}{})
	if err != nil {
		t.Fatalf("Call old error: %v", err)
	}
	if result.(int) != 7 {
		t.Fatalf("expected exit 7, got %v", result)
	}

	// Call new-style
	result, err = app.Call("new", map[string]interface{}{"name": "test"})
	if err != nil {
		t.Fatalf("Call new error: %v", err)
	}
	if result.(int) != 0 {
		t.Fatalf("expected exit 0, got %v", result)
	}
}

// --- WithTags on RegisterHandler ---

func TestRegisterHandler_WithTags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "tagged command", func() Handler {
		return &GreetHandler{}
	}, WithTags("release", "deploy"))

	r := app.Test([]string{"cmd", "--name", "test"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr: %s", r.ExitCode, r.Stderr)
	}
}
