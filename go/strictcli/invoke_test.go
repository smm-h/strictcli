package strictcli

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// captureHandler returns a handler that records the kwargs it receives.
func captureHandler(captured *map[string]interface{}) func(ctx *Context, kwargs map[string]interface{}) Outcome {
	return func(ctx *Context, kwargs map[string]interface{}) Outcome {
		*captured = kwargs
		return Exit(0)
	}
}

// buildInvokeTestApp creates an app with various command types for invoke testing.
func buildInvokeTestApp(captured *map[string]interface{}) *App {
	app := NewApp("testapp", "1.0.0", "test application")

	app.Command("greet", "say hello", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		*captured = kwargs
		return Exit(0)
	}, WithFlags(
		StringFlag("name", "who to greet", Required()),
	), WithEffect(EffectReadOnly))

	return app
}

func TestInvokeBasicCommand(t *testing.T) {
	var captured map[string]interface{}
	app := buildInvokeTestApp(&captured)

	result := app.invoke("greet", map[string]interface{}{
		"name": "world",
	})
	if result.err != "" {
		t.Fatalf("invoke error: %s", result.err)
	}
	if result.exitCode != 0 {
		t.Fatalf("expected exit 0, got %d", result.exitCode)
	}
	if captured["name"] != "world" {
		t.Fatalf("expected name='world', got %v", captured["name"])
	}
}

func TestInvokeMatchesTest(t *testing.T) {
	// Verify invoke produces the same kwargs as Test for equivalent inputs.
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("deploy", "deploy something", captureHandler(captured),
			WithFlags(
				StringFlag("target", "deploy target", Required()),
				BoolFlag("sim-run", "dry run mode", Default(false)),
				IntFlag("count", "instance count", Default(1)),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	// Test via invoke
	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("deploy", map[string]interface{}{
		"target":  "production",
		"sim_run": true,
		"count":   3,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	// Test via Test (CLI parsing)
	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"deploy", "--target", "production", "--sim-run", "--count", "3"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	// Compare kwargs
	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeWithDefaults(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run something", captureHandler(&captured),
		WithFlags(
			StringFlag("mode", "operation mode", Default("fast")),
			BoolFlag("loud", "loud output", Default(false)),
			IntFlag("retries", "retry count", Default(3)),
		), WithEffect(EffectReadOnly),
	)

	// Only provide non-default values
	ir := app.invoke("run", map[string]interface{}{
		"loud": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["mode"] != "fast" {
		t.Fatalf("expected mode='fast', got %v", captured["mode"])
	}
	if captured["loud"] != true {
		t.Fatalf("expected loud=true, got %v", captured["loud"])
	}
	if captured["retries"] != 3 {
		t.Fatalf("expected retries=3, got %v", captured["retries"])
	}
}

func TestInvokeDefaultsMatchTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("run", "run it", captureHandler(captured),
			WithFlags(
				StringFlag("mode", "operation mode", Default("fast")),
				BoolFlag("loud", "loud output", Default(false)),
				IntFlag("retries", "retry count", Default(3)),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	// invoke with no overrides
	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("run", map[string]interface{}{})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	// Test with no flags (all defaults)
	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeGroupCommand(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	grp := app.Group("db", "database commands")
	grp.Command("migrate", "run migrations", captureHandler(&captured),
		WithFlags(
			BoolFlag("sim-run", "preview only", Default(false)),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("db.migrate", map[string]interface{}{
		"sim_run": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["sim_run"] != true {
		t.Fatalf("expected sim_run=true, got %v", captured["sim_run"])
	}
}

func TestInvokeNestedGroupCommand(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	dns := app.Group("dns", "DNS commands")
	zone := dns.Group("zone", "zone commands")
	zone.Command("create", "create a zone", captureHandler(&captured),
		WithFlags(
			StringFlag("name", "zone name", Required()),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("dns.zone.create", map[string]interface{}{
		"name": "example.com",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["name"] != "example.com" {
		t.Fatalf("expected name='example.com', got %v", captured["name"])
	}
}

func TestInvokeNestedGroupMatchesTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		dns := app.Group("dns", "DNS commands")
		zone := dns.Group("zone", "zone commands")
		zone.Command("create", "create a zone", captureHandler(captured),
			WithFlags(
				StringFlag("name", "zone name", Required()),
				IntFlag("ttl", "time to live", Default(3600)),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("dns.zone.create", map[string]interface{}{
		"name": "example.com",
		"ttl":  7200,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"dns", "zone", "create", "--name", "example.com", "--ttl", "7200"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeWithGlobalFlags(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("loud", "enable loud output", Default(false)))
	app.Command("run", "run it", captureHandler(&captured), WithEffect(EffectReadOnly))

	ir := app.invoke("run", map[string]interface{}{
		"loud": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["loud"] != true {
		t.Fatalf("expected loud=true, got %v", captured["loud"])
	}
}

func TestInvokeGlobalFlagDefaults(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("loud", "enable loud output", Default(false)))
	app.Command("run", "run it", captureHandler(&captured), WithEffect(EffectReadOnly))

	// Don't provide the global flag -- should get default (false)
	ir := app.invoke("run", map[string]interface{}{})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["loud"] != false {
		t.Fatalf("expected loud=false, got %v", captured["loud"])
	}
}

func TestInvokeGlobalFlagsMatchTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.GlobalFlag(BoolFlag("loud", "enable loud output", Default(false)))
		app.GlobalFlag(StringFlag("format", "output format", Default("text")))
		app.Command("run", "run it", captureHandler(captured),
			WithFlags(
				StringFlag("target", "deploy target", Default("local")),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("run", map[string]interface{}{
		"loud":   true,
		"format": "json",
		"target": "remote",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"--loud", "--format", "json", "run", "--target", "remote"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeWithPositionalArgs(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cp", "copy files", captureHandler(&captured),
		WithArgs(
			NewArg("source", "source file", ArgRequired()),
			NewArg("dest", "destination file", ArgRequired()),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("cp", map[string]interface{}{
		"source": "a.txt",
		"dest":   "b.txt",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["source"] != "a.txt" {
		t.Fatalf("expected source='a.txt', got %v", captured["source"])
	}
	if captured["dest"] != "b.txt" {
		t.Fatalf("expected dest='b.txt', got %v", captured["dest"])
	}
}

func TestInvokePositionalArgsMatchTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("cp", "copy files", captureHandler(captured),
			WithArgs(
				NewArg("source", "source file", ArgRequired()),
				NewArg("dest", "destination file", ArgRequired()),
			),
			WithFlags(
				BoolFlag("recursive", "copy recursively", Default(false)),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("cp", map[string]interface{}{
		"source":    "a.txt",
		"dest":      "b.txt",
		"recursive": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"cp", "--recursive", "a.txt", "b.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeVariadicArgs(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("rm", "remove files", captureHandler(&captured),
		WithArgs(
			NewArg("files", "files to remove", Variadic(), ArgRequired()),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("rm", map[string]interface{}{
		"files": []string{"a.txt", "b.txt", "c.txt"},
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	files := captured["files"].([]interface{})
	if len(files) != 3 {
		t.Fatalf("expected 3 files, got %d", len(files))
	}
	if files[0] != "a.txt" || files[1] != "b.txt" || files[2] != "c.txt" {
		t.Fatalf("unexpected files: %v", files)
	}
}

func TestInvokeVariadicArgsMatchTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("rm", "remove files", captureHandler(captured),
			WithFlags(
				BoolFlag("force-removal", "force removal", Default(false)),
			),
			WithArgs(
				NewArg("files", "files to remove", Variadic(), ArgRequired()),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("rm", map[string]interface{}{
		"force_removal": true,
		"files":         []string{"a.txt", "b.txt"},
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"rm", "--force-removal", "a.txt", "b.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokePassthroughCommand(t *testing.T) {
	var capturedName string
	var capturedArgs []string
	var capturedGlobals map[string]interface{}

	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("loud", "enable loud output", Default(false)))
	app.Passthrough("exec", "execute command", func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
		capturedName = name
		capturedArgs = args
		capturedGlobals = globals
		return 0
	}, WithEffect(EffectReadOnly))

	ir := app.invoke("exec", map[string]interface{}{
		"_args": []string{"ls", "-la", "/tmp"},
		"loud":  true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if capturedName != "exec" {
		t.Fatalf("expected name='exec', got %q", capturedName)
	}
	if len(capturedArgs) != 3 || capturedArgs[0] != "ls" {
		t.Fatalf("unexpected args: %v", capturedArgs)
	}
	if capturedGlobals["loud"] != true {
		t.Fatalf("expected loud=true in globals, got %v", capturedGlobals["loud"])
	}
}

func TestInvokePassthroughUnknownKwargs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("loud", "enable loud output", Default(false)))
	app.Passthrough("exec", "execute command", func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
		return 0
	}, WithEffect(EffectReadOnly))

	ir := app.invoke("exec", map[string]interface{}{
		"_args":      []string{"ls"},
		"loud":       true,
		"bogus_flag": "should fail",
	})
	if ir.err == "" {
		t.Fatal("expected error for unknown kwarg in passthrough command")
	}
	if !strings.Contains(ir.err, "unknown parameter") {
		t.Fatalf("expected 'unknown parameter' in error, got %q", ir.err)
	}
	if !strings.Contains(ir.err, "bogus_flag") {
		t.Fatalf("expected 'bogus_flag' in error, got %q", ir.err)
	}
}

func TestInvokePassthroughMissingRequiredGlobalFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(StringFlag("token", "auth token", Required()))
	app.GlobalFlag(BoolFlag("loud", "enable loud output", Default(false)))
	app.Passthrough("exec", "execute command", func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
		return 0
	}, WithEffect(EffectReadOnly))

	// Don't provide "token" -- the global string flag declares Required()
	ir := app.invoke("exec", map[string]interface{}{
		"_args": []string{"ls"},
		"loud":  true,
	})
	if ir.err == "" {
		t.Fatal("expected error for missing required global flag in passthrough command")
	}
	if !strings.Contains(ir.err, "required") {
		t.Fatalf("expected 'required' in error, got %q", ir.err)
	}
	if !strings.Contains(ir.err, "token") {
		t.Fatalf("expected 'token' in error, got %q", ir.err)
	}
}

func TestInvokePassthroughMissingRequiredBoolGlobalFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	// A bool global flag declaring Required(): it must be provided explicitly.
	app.GlobalFlag(BoolFlag("force-run", "force operation", Required()))
	app.Passthrough("exec", "execute command", func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
		return 0
	}, WithEffect(EffectReadOnly))

	// Don't provide "force-run" -- the global bool flag declares Required()
	ir := app.invoke("exec", map[string]interface{}{
		"_args": []string{"ls"},
	})
	if ir.err == "" {
		t.Fatal("expected error for missing required bool global flag in passthrough command")
	}
	if !strings.Contains(ir.err, "force-run") {
		t.Fatalf("expected 'force-run' in error, got %q", ir.err)
	}
	if !strings.Contains(ir.err, "must be passed") {
		t.Fatalf("expected 'must be passed' in error, got %q", ir.err)
	}
}

func TestInvokeUnknownCommand(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("greet", "say hello", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) }, WithEffect(EffectReadOnly))

	ir := app.invoke("nonexistent", map[string]interface{}{})
	if ir.err == "" {
		t.Fatal("expected error for unknown command")
	}
	if !strings.Contains(ir.err, "unknown command") {
		t.Fatalf("expected 'unknown command' in error, got %q", ir.err)
	}
}

func TestInvokeUnknownParameter(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("greet", "say hello", captureHandler(&captured),
		WithFlags(
			StringFlag("name", "who to greet", Required()),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("greet", map[string]interface{}{
		"name":        "world",
		"nonexistent": "value",
	})
	if ir.err == "" {
		t.Fatal("expected error for unknown parameter")
	}
	if !strings.Contains(ir.err, "unknown parameter") {
		t.Fatalf("expected 'unknown parameter' in error, got %q", ir.err)
	}
}

func TestInvokeMissingRequiredFlag(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy it", captureHandler(&captured),
		WithFlags(
			StringFlag("target", "deploy target", Required()),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("deploy", map[string]interface{}{})
	if ir.err == "" {
		t.Fatal("expected error for missing required flag")
	}
	if !strings.Contains(ir.err, "required") {
		t.Fatalf("expected 'required' in error, got %q", ir.err)
	}
}

func TestInvokeChoicesValidation(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(&captured),
		WithFlags(
			StringFlag("mode", "operation mode", Choices("fast", "slow"), Required()),
		), WithEffect(EffectReadOnly),
	)

	// Valid choice
	ir := app.invoke("run", map[string]interface{}{"mode": "fast"})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	// Invalid choice
	ir = app.invoke("run", map[string]interface{}{"mode": "medium"})
	if ir.err == "" {
		t.Fatal("expected error for invalid choice")
	}
	if !strings.Contains(ir.err, "invalid value") {
		t.Fatalf("expected 'invalid value' in error, got %q", ir.err)
	}
}

func TestInvokeMutexGroup(t *testing.T) {
	var captured map[string]interface{}

	makeApp := func() *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("out", "output command", captureHandler(&captured),
			WithMutex(MutexGroup{Flags: []Flag{
				StringFlag("as-json", "JSON output", Optional()),
				StringFlag("text", "text output", Optional()),
			}}), WithEffect(EffectReadOnly),
		)
		return app
	}

	// Provide exactly one mutex flag
	app1 := makeApp()
	ir := app1.invoke("out", map[string]interface{}{"as_json": "data"})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	// Provide both (should error)
	app2 := makeApp()
	ir = app2.invoke("out", map[string]interface{}{"as_json": "data", "text": "data"})
	if ir.err == "" {
		t.Fatal("expected error for mutex violation")
	}
	if !strings.Contains(ir.err, "mutually exclusive") {
		t.Fatalf("expected 'mutually exclusive' in error, got %q", ir.err)
	}
}

func TestInvokeExitCode(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("fail", "always fails", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(42)
	}, WithEffect(EffectReadOnly))

	ir := app.invoke("fail", map[string]interface{}{})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if ir.exitCode != 42 {
		t.Fatalf("expected exit code 42, got %d", ir.exitCode)
	}
}

func TestInvokeFloatFlag(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("scale", "scale it", captureHandler(captured),
			WithFlags(
				FloatFlag("factor", "scale factor", Required()),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("scale", map[string]interface{}{
		"factor": 2.5,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"scale", "--factor", "2.5"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeHandlerReceivesOutput(t *testing.T) {
	// Verify that invoke actually calls the handler and it can produce output.
	app := NewApp("myapp", "1.0.0", "test app")
	var called bool
	app.Command("ping", "ping", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		called = true
		fmt.Print("pong")
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	ir := app.invoke("ping", map[string]interface{}{})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if !called {
		t.Fatal("handler was not called")
	}
}

func TestInvokeDashFlagName(t *testing.T) {
	// Verify flags with dashes in names work correctly via invoke.
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(&captured),
		WithFlags(
			BoolFlag("sim-run", "preview mode", Default(false)),
			StringFlag("output-dir", "output directory", Default("/tmp")),
		), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("run", map[string]interface{}{
		"sim_run":    true,
		"output_dir": "/home/out",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["sim_run"] != true {
		t.Fatalf("expected sim_run=true, got %v", captured["sim_run"])
	}
	if captured["output_dir"] != "/home/out" {
		t.Fatalf("expected output_dir='/home/out', got %v", captured["output_dir"])
	}
}

func TestInvokeOptionalArgMatchesTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("show", "show something", captureHandler(captured),
			WithArgs(
				NewArg("item", "item to show", ArgRequired()),
				NewArg("detail", "detail level", ArgDefault("summary")),
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	// With optional arg provided
	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("show", map[string]interface{}{
		"item":   "report",
		"detail": "full",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"show", "report", "full"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}

	// Without optional arg (should use default)
	app3 := makeApp(&invokeKwargs)
	ir = app3.invoke("show", map[string]interface{}{
		"item": "report",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app4 := makeApp(&testKwargs)
	r = app4.Test([]string{"show", "report"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}
}

func TestInvokeImpliesDependency(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.Command("run", "run it", captureHandler(captured),
			WithFlags(
				BoolFlag("all", "do everything", Default(false)),
				BoolFlag("loud", "loud output", Default(false)),
			),
			WithDependencies(
				Implies{Flag: "all", Implies: "loud", Value: true},
			), WithEffect(EffectReadOnly),
		)
		return app
	}

	// --all should imply --loud
	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("run", map[string]interface{}{
		"all": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"run", "--all"})
	if r.ExitCode != 0 {
		t.Fatalf("Test failed: %s", r.Stderr)
	}

	if !reflect.DeepEqual(invokeKwargs, testKwargs) {
		t.Fatalf("kwargs mismatch:\ninvoke: %v\nTest:   %v", invokeKwargs, testKwargs)
	}

	if invokeKwargs["loud"] != true {
		t.Fatalf("expected loud=true (implied), got %v", invokeKwargs["loud"])
	}
}

var capturedSources = map[string]string{}

func TestCallHandlerSourceProvenance(t *testing.T) {
	// Reset captured sources
	capturedSources = map[string]string{}

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("greet", "greet someone", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		// Store the sources in a package-level variable so the test can inspect them
		capturedSources["name"] = ctx.Source("name")
		capturedSources["loud"] = ctx.Source("loud")
		return Exit(0)
	}, WithFlags(
		StringFlag("name", "who to greet", Required()),
		BoolFlag("loud", "loud output", Default(false)),
	), WithEffect(EffectReadOnly))

	// Call with "name" provided, "loud" absent (should get default)
	result, err := app.Call("greet", map[string]interface{}{
		"name": "world",
	})
	if err != nil {
		t.Fatalf("Call error: %v", err)
	}
	if result.(int) != 0 {
		t.Fatalf("expected exit code 0, got %v", result)
	}

	// Provided kwarg should have source "cli"
	if capturedSources["name"] != "cli" {
		t.Fatalf("expected source 'cli' for name, got %q", capturedSources["name"])
	}
	// Absent kwarg with default should have source "default"
	if capturedSources["loud"] != "default" {
		t.Fatalf("expected source 'default' for loud, got %q", capturedSources["loud"])
	}
}
