package strictcli

import (
	"fmt"
	"reflect"
	"strings"
	"testing"
)

// captureHandler returns a handler that records the kwargs it receives.
func captureHandler(captured *map[string]interface{}) func(map[string]interface{}) int {
	return func(kwargs map[string]interface{}) int {
		*captured = kwargs
		return 0
	}
}

// buildInvokeTestApp creates an app with various command types for invoke testing.
func buildInvokeTestApp(captured *map[string]interface{}) *App {
	app := NewApp("testapp", "1.0.0", "test application")

	app.Command("greet", "say hello", func(kwargs map[string]interface{}) int {
		*captured = kwargs
		return 0
	}, WithFlags(
		StringFlag("name", "who to greet"),
	))

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
				StringFlag("target", "deploy target"),
				BoolFlag("dry-run", "dry run mode", Default(false)),
				IntFlag("count", "instance count", Default(1)),
			),
		)
		return app
	}

	// Test via invoke
	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("deploy", map[string]interface{}{
		"target":  "production",
		"dry_run": true,
		"count":   3,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	// Test via Test (CLI parsing)
	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"deploy", "--target", "production", "--dry-run", "--count", "3"})
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
			BoolFlag("verbose", "verbose output", Default(false)),
			IntFlag("retries", "retry count", Default(3)),
		),
	)

	// Only provide non-default values
	ir := app.invoke("run", map[string]interface{}{
		"verbose": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["mode"] != "fast" {
		t.Fatalf("expected mode='fast', got %v", captured["mode"])
	}
	if captured["verbose"] != true {
		t.Fatalf("expected verbose=true, got %v", captured["verbose"])
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
				BoolFlag("verbose", "verbose output", Default(false)),
				IntFlag("retries", "retry count", Default(3)),
			),
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
			BoolFlag("dry-run", "preview only", Default(false)),
		),
	)

	ir := app.invoke("db.migrate", map[string]interface{}{
		"dry_run": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["dry_run"] != true {
		t.Fatalf("expected dry_run=true, got %v", captured["dry_run"])
	}
}

func TestInvokeNestedGroupCommand(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	dns := app.Group("dns", "DNS commands")
	zone := dns.Group("zone", "zone commands")
	zone.Command("create", "create a zone", captureHandler(&captured),
		WithFlags(
			StringFlag("name", "zone name"),
		),
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
				StringFlag("name", "zone name"),
				IntFlag("ttl", "time to live", Default(3600)),
			),
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
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
	app.Command("run", "run it", captureHandler(&captured))

	ir := app.invoke("run", map[string]interface{}{
		"verbose": true,
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["verbose"] != true {
		t.Fatalf("expected verbose=true, got %v", captured["verbose"])
	}
}

func TestInvokeGlobalFlagDefaults(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
	app.Command("run", "run it", captureHandler(&captured))

	// Don't provide the global flag -- should get default (false)
	ir := app.invoke("run", map[string]interface{}{})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["verbose"] != false {
		t.Fatalf("expected verbose=false, got %v", captured["verbose"])
	}
}

func TestInvokeGlobalFlagsMatchTest(t *testing.T) {
	var invokeKwargs, testKwargs map[string]interface{}

	makeApp := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app")
		app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
		app.GlobalFlag(StringFlag("format", "output format", Default("text")))
		app.Command("run", "run it", captureHandler(captured),
			WithFlags(
				StringFlag("target", "deploy target", Default("local")),
			),
		)
		return app
	}

	app1 := makeApp(&invokeKwargs)
	ir := app1.invoke("run", map[string]interface{}{
		"verbose": true,
		"format":  "json",
		"target":  "remote",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	app2 := makeApp(&testKwargs)
	r := app2.Test([]string{"--verbose", "--format", "json", "run", "--target", "remote"})
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
			NewArg("source", "source file"),
			NewArg("dest", "destination file"),
		),
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
				NewArg("source", "source file"),
				NewArg("dest", "destination file"),
			),
			WithFlags(
				BoolFlag("recursive", "copy recursively", Default(false)),
			),
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
			NewArg("files", "files to remove", Variadic()),
		),
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
				NewArg("files", "files to remove", Variadic()),
			),
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
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
	app.Passthrough("exec", "execute command", func(name string, args []string, globals map[string]interface{}) int {
		capturedName = name
		capturedArgs = args
		capturedGlobals = globals
		return 0
	})

	ir := app.invoke("exec", map[string]interface{}{
		"_args":   []string{"ls", "-la", "/tmp"},
		"verbose": true,
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
	if capturedGlobals["verbose"] != true {
		t.Fatalf("expected verbose=true in globals, got %v", capturedGlobals["verbose"])
	}
}

func TestInvokePassthroughUnknownKwargs(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
	app.Passthrough("exec", "execute command", func(name string, args []string, globals map[string]interface{}) int {
		return 0
	})

	ir := app.invoke("exec", map[string]interface{}{
		"_args":      []string{"ls"},
		"verbose":    true,
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
	app.GlobalFlag(StringFlag("token", "auth token"))
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
	app.Passthrough("exec", "execute command", func(name string, args []string, globals map[string]interface{}) int {
		return 0
	})

	// Don't provide "token" -- it's a required string global flag (no default)
	ir := app.invoke("exec", map[string]interface{}{
		"_args":   []string{"ls"},
		"verbose": true,
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
	// A required bool global flag: no Default, so it must be provided explicitly.
	app.GlobalFlag(BoolFlag("force-run", "force operation"))
	app.Passthrough("exec", "execute command", func(name string, args []string, globals map[string]interface{}) int {
		return 0
	})

	// Don't provide "force-run" -- it's a required bool global flag (no default)
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
	app.Command("greet", "say hello", func(kwargs map[string]interface{}) int { return 0 })

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
			StringFlag("name", "who to greet"),
		),
	)

	ir := app.invoke("greet", map[string]interface{}{
		"name":         "world",
		"nonexistent":  "value",
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
			StringFlag("target", "deploy target"),
		),
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
			StringFlag("mode", "operation mode", Choices("fast", "slow")),
		),
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
				StringFlag("json", "JSON output", Default(nil)),
				StringFlag("text", "text output", Default(nil)),
			}}),
		)
		return app
	}

	// Provide exactly one mutex flag
	app1 := makeApp()
	ir := app1.invoke("out", map[string]interface{}{"json": "data"})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}

	// Provide both (should error)
	app2 := makeApp()
	ir = app2.invoke("out", map[string]interface{}{"json": "data", "text": "data"})
	if ir.err == "" {
		t.Fatal("expected error for mutex violation")
	}
	if !strings.Contains(ir.err, "mutually exclusive") {
		t.Fatalf("expected 'mutually exclusive' in error, got %q", ir.err)
	}
}

func TestInvokeExitCode(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("fail", "always fails", func(kwargs map[string]interface{}) int {
		return 42
	})

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
				FloatFlag("factor", "scale factor"),
			),
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
	app.Command("ping", "ping", func(kwargs map[string]interface{}) int {
		called = true
		fmt.Print("pong")
		return 0
	})

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
			BoolFlag("dry-run", "preview mode", Default(false)),
			StringFlag("output-dir", "output directory", Default("/tmp")),
		),
	)

	ir := app.invoke("run", map[string]interface{}{
		"dry_run":    true,
		"output_dir": "/home/out",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	if captured["dry_run"] != true {
		t.Fatalf("expected dry_run=true, got %v", captured["dry_run"])
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
				NewArg("item", "item to show"),
				NewArg("detail", "detail level", ArgRequired(false), ArgDefault("summary")),
			),
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
				BoolFlag("verbose", "verbose output", Default(false)),
			),
			WithDependencies(
				Implies{Flag: "all", Implies: "verbose", Value: true},
			),
		)
		return app
	}

	// --all should imply --verbose
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

	if invokeKwargs["verbose"] != true {
		t.Fatalf("expected verbose=true (implied), got %v", invokeKwargs["verbose"])
	}
}
