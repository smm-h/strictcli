package strictcli

import (
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Five-way presence semantics for source-filtered queries
// ---------------------------------------------------------------------------

// Test 1: A mutex group where one flag has source=default should NOT trigger
// mutex violation. A flag whose value came from Default() is not "present"
// for mutex evaluation.
func TestMutexDefaultSourceNotPresent(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("out", "output", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithMutex(MutexGroup{Flags: []Flag{
			BoolFlag("json", "JSON output", Default(false)),
			BoolFlag("text", "text output", Default(false)),
		}}),
	)

	// Provide only --json via CLI. --text has Default(false), so it will get
	// source=default. The mutex check should see only --json as "present"
	// and NOT fire a mutex violation.
	r := app.Test([]string{"out", "--json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected success, got exit code %d: %s", r.ExitCode, r.Stderr)
	}

	// Also test via invoke: provide only "json". "text" is absent and will
	// be defaulted. Mutex should not fire.
	app2 := NewApp("myapp", "1.0.0", "test app")
	app2.Command("out", "output", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithMutex(MutexGroup{Flags: []Flag{
			BoolFlag("json", "JSON output", Default(false)),
			BoolFlag("text", "text output", Default(false)),
		}}),
	)
	ir := app2.invoke("out", map[string]interface{}{"json": true})
	if ir.err != "" {
		t.Fatalf("invoke: expected success, got error: %s", ir.err)
	}
}

// Test 2: A mutex group where one flag has source=implied should NOT trigger
// mutex violation. Implied values do not count as "present" for mutex.
func TestMutexImpliedSourceNotPresent(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("out", "output", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithMutex(MutexGroup{Flags: []Flag{
			BoolFlag("json", "JSON output", Default(nil)),
			BoolFlag("text", "text output", Default(nil)),
		}}),
		WithDependencies(
			// Providing --verbose implies --text=true
			Implies{Flag: "verbose", Implies: "text", Value: true},
		),
		WithFlags(
			BoolFlag("verbose", "verbose mode", Default(false)),
		),
	)

	// Provide --json and --verbose. --verbose implies --text=true (source=implied).
	// The mutex group contains both json and text, but text is implied, so
	// the mutex should see only json as "present" and NOT fire a violation.
	r := app.Test([]string{"out", "--json", "--verbose"})
	if r.ExitCode != 0 {
		t.Fatalf("expected success, got exit code %d: %s", r.ExitCode, r.Stderr)
	}
}

// Test 3: A mutex group where one flag is cli + another is config -- SHOULD
// trigger mutex violation. But since config is temporarily marked as SourceCLI
// (Phase 2a will give it SourceConfig), this test passes trivially because
// both flags will be seen as "present" (SourceCLI). The test documents the
// intended behavior and will become meaningful after Phase 2a.
func TestMutexCliAndConfigBothPresent(t *testing.T) {
	// We cannot easily test config source right now because parseCommand
	// temporarily marks config values as SourceCLI. This test verifies the
	// intended end-state behavior: when both cli and config values are
	// present in a mutex group, it should error.
	//
	// For now, we test via invoke with two values provided (both SourceCLI),
	// which is the equivalent scenario.
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("out", "output", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithMutex(MutexGroup{Flags: []Flag{
			StringFlag("json", "JSON output", Default(nil)),
			StringFlag("text", "text output", Default(nil)),
		}}),
	)

	ir := app.invoke("out", map[string]interface{}{"json": "data", "text": "data"})
	if ir.err == "" {
		t.Fatal("expected mutex violation error")
	}
	if !strings.Contains(ir.err, "mutually exclusive") {
		t.Fatalf("expected 'mutually exclusive' error, got: %s", ir.err)
	}
}

// Test 4: A dependency (Requires) where the required flag has source=implied
// should PASS. Implied values count as "present" for dependency checks.
func TestRequiresImpliedSourceCountsAsPresent(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithFlags(
			BoolFlag("all", "deploy all", Default(false)),
			BoolFlag("verbose", "verbose mode", Default(false)),
			StringFlag("target", "deploy target"),
		),
		WithDependencies(
			// --all implies --verbose=true
			Implies{Flag: "all", Implies: "verbose", Value: true},
			// --target requires --verbose
			Requires{Flag: "target", DependsOn: "verbose"},
		),
	)

	// Provide --all and --target. --all implies --verbose (source=implied).
	// --target requires --verbose. Since implied counts for deps, this
	// should succeed.
	r := app.Test([]string{"deploy", "--all", "--target", "prod"})
	if r.ExitCode != 0 {
		t.Fatalf("expected success, got exit code %d: %s", r.ExitCode, r.Stderr)
	}
}

// Test 5: A dependency (Requires) where the required flag has source=default
// should FAIL. Default values do NOT count as "present" for dependency checks.
func TestRequiresDefaultSourceNotPresent(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithFlags(
			StringFlag("target", "deploy target"),
			BoolFlag("verbose", "verbose mode", Default(false)),
		),
		WithDependencies(
			// --target requires --verbose
			Requires{Flag: "target", DependsOn: "verbose"},
		),
	)

	// Provide --target but NOT --verbose. --verbose has Default(false), so
	// it will get source=default. Since default does NOT count as "present"
	// for deps, this should fail with "requires" error.
	r := app.Test([]string{"deploy", "--target", "prod"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "requires") {
		t.Fatalf("expected 'requires' error, got: %s", r.Stderr)
	}
}

// ---------------------------------------------------------------------------
// Invoke path: verify that invoke correctly marks kwargs as SourceCLI
// and absent-then-defaulted flags as SourceDefault.
// ---------------------------------------------------------------------------

// Test that invoke with a provided kwarg treats it as SourceCLI for mutex.
func TestInvokeMutexProvidedKwargIsCliSource(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("out", "output", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithMutex(MutexGroup{Flags: []Flag{
			StringFlag("json", "JSON output", Default(nil)),
			StringFlag("text", "text output", Default(nil)),
		}}),
	)

	// Provide exactly one mutex flag via invoke -- should succeed.
	ir := app.invoke("out", map[string]interface{}{"json": "data"})
	if ir.err != "" {
		t.Fatalf("invoke: expected success, got error: %s", ir.err)
	}
}

// Test that invoke with an absent kwarg that gets defaulted does NOT count
// as present for Requires.
func TestInvokeDefaultedNotPresentForRequires(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(kwargs map[string]interface{}) int {
		return 0
	},
		WithFlags(
			StringFlag("target", "deploy target"),
			BoolFlag("verbose", "verbose mode", Default(false)),
		),
		WithDependencies(
			Requires{Flag: "target", DependsOn: "verbose"},
		),
	)

	// Provide target but not verbose. verbose will be defaulted.
	// Default does not count as present for Requires, so this should fail.
	ir := app.invoke("deploy", map[string]interface{}{"target": "prod"})
	if ir.err == "" {
		t.Fatal("invoke: expected 'requires' error")
	}
	if !strings.Contains(ir.err, "requires") {
		t.Fatalf("invoke: expected 'requires' error, got: %s", ir.err)
	}
}
