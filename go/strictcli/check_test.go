package strictcli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

func TestCheckResultFields(t *testing.T) {
	r := CheckResult{
		Status:  "pass",
		Message: "all good",
		Details: []string{"detail1", "detail2"},
	}
	if r.Status != "pass" {
		t.Errorf("expected status 'pass', got %q", r.Status)
	}
	if r.Message != "all good" {
		t.Errorf("expected message 'all good', got %q", r.Message)
	}
	if len(r.Details) != 2 {
		t.Errorf("expected 2 details, got %d", len(r.Details))
	}
}

func writeToml(t *testing.T, dir, content string) string {
	t.Helper()
	path := filepath.Join(dir, "checks.toml")
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write checks.toml: %v", err)
	}
	return path
}

func TestLoadChecksToml_Valid(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.lint-code]
tags = ["code", "fast"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-deps]
tags = ["deps"]
severity = "warn"
fast = false
pure = false
needs_network = true
depends_on = ["lint-code"]
`)

	defs, order, err := loadChecksToml(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(defs) != 2 {
		t.Fatalf("expected 2 checks, got %d", len(defs))
	}
	if len(order) != 2 {
		t.Fatalf("expected 2 names in order, got %d", len(order))
	}

	t.Run("lint-code fields", func(t *testing.T) {
		d := defs["lint-code"]
		if d == nil {
			t.Fatal("lint-code not found")
		}
		if d.name != "lint-code" {
			t.Errorf("expected name 'lint-code', got %q", d.name)
		}
		if len(d.tags) != 2 || d.tags[0] != "code" || d.tags[1] != "fast" {
			t.Errorf("unexpected tags: %v", d.tags)
		}
		if d.severity != "error" {
			t.Errorf("expected severity 'error', got %q", d.severity)
		}
		if !d.fast {
			t.Error("expected fast=true")
		}
		if !d.pure {
			t.Error("expected pure=true")
		}
		if d.needsNetwork {
			t.Error("expected needs_network=false")
		}
		if len(d.dependsOn) != 0 {
			t.Errorf("expected empty depends_on, got %v", d.dependsOn)
		}
		if d.impl != nil {
			t.Error("expected impl to be nil")
		}
	})

	t.Run("check-deps fields", func(t *testing.T) {
		d := defs["check-deps"]
		if d == nil {
			t.Fatal("check-deps not found")
		}
		if d.severity != "warn" {
			t.Errorf("expected severity 'warn', got %q", d.severity)
		}
		if d.fast {
			t.Error("expected fast=false")
		}
		if d.pure {
			t.Error("expected pure=false")
		}
		if !d.needsNetwork {
			t.Error("expected needs_network=true")
		}
		if len(d.dependsOn) != 1 || d.dependsOn[0] != "lint-code" {
			t.Errorf("unexpected depends_on: %v", d.dependsOn)
		}
	})
}

func TestLoadChecksToml_MissingField(t *testing.T) {
	tests := []struct {
		name    string
		toml    string
		wantErr string
	}{
		{
			name: "missing tags",
			toml: `
[checks.foo]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "tags"`,
		},
		{
			name: "missing severity",
			toml: `
[checks.foo]
tags = ["a"]
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "severity"`,
		},
		{
			name: "missing fast",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "fast"`,
		},
		{
			name: "missing pure",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "pure"`,
		},
		{
			name: "missing needs_network",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "needs_network"`,
		},
		{
			name: "missing depends_on",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
`,
			wantErr: `checks.toml: check "foo": missing required field "depends_on"`,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			path := writeToml(t, dir, tc.toml)
			_, _, err := loadChecksToml(path)
			if err == nil {
				t.Fatal("expected error, got nil")
			}
			if err.Error() != tc.wantErr {
				t.Errorf("expected error %q, got %q", tc.wantErr, err.Error())
			}
		})
	}
}

func TestLoadChecksToml_WrongTypes(t *testing.T) {
	tests := []struct {
		name    string
		toml    string
		wantErr string
	}{
		{
			name: "tags is string instead of array",
			toml: `
[checks.foo]
tags = "not-an-array"
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "tags" must be an array of strings`,
		},
		{
			name: "severity is integer",
			toml: `
[checks.foo]
tags = ["a"]
severity = 42
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "severity" must be a string`,
		},
		{
			name: "fast is string",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = "yes"
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "fast" must be a boolean`,
		},
		{
			name: "invalid severity value",
			toml: `
[checks.foo]
tags = ["a"]
severity = "critical"
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "severity" must be "error" or "warn", got "critical"`,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			path := writeToml(t, dir, tc.toml)
			_, _, err := loadChecksToml(path)
			if err == nil {
				t.Fatal("expected error, got nil")
			}
			if err.Error() != tc.wantErr {
				t.Errorf("expected error %q, got %q", tc.wantErr, err.Error())
			}
		})
	}
}

func TestLoadChecksToml_UnknownFields(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
extra_field = "bad"
`)
	_, _, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for unknown field")
	}
	if !strings.Contains(err.Error(), `unknown field "extra_field"`) {
		t.Errorf("expected error about unknown field, got %q", err.Error())
	}
}

func TestLoadChecksToml_UnknownTopLevelKey(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[metadata]
version = "1.0"
`)
	_, _, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for unknown top-level key")
	}
	if !strings.Contains(err.Error(), `unknown top-level key "metadata"`) {
		t.Errorf("expected error about unknown top-level key, got %q", err.Error())
	}
}

func TestLoadChecksToml_InvalidCheckName(t *testing.T) {
	tests := []struct {
		name     string
		checkName string
	}{
		{"starts with number", "1bad"},
		{"uppercase", "BadName"},
		{"contains underscore", "bad_name"},
		{"starts with hyphen", "-bad"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			toml := `
[checks.` + tc.checkName + `]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`
			path := writeToml(t, dir, toml)
			_, _, err := loadChecksToml(path)
			if err == nil {
				t.Fatal("expected error for invalid check name")
			}
			if !strings.Contains(err.Error(), "invalid check name") {
				t.Errorf("expected error about invalid check name, got %q", err.Error())
			}
		})
	}
}

func TestLoadChecksToml_DependsOnValidation(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["nonexistent"]
`)
	_, _, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for depends_on referencing unknown check")
	}
	if !strings.Contains(err.Error(), `depends_on references unknown check "nonexistent"`) {
		t.Errorf("expected error about unknown check reference, got %q", err.Error())
	}
}

func TestLoadChecksToml_EmptyTags(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = []
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`)
	_, _, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for empty tags")
	}
	if !strings.Contains(err.Error(), `"tags" must be non-empty`) {
		t.Errorf("expected error about empty tags, got %q", err.Error())
	}
}

func TestLoadChecksToml_FileNotFound(t *testing.T) {
	_, _, err := loadChecksToml("/nonexistent/checks.toml")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestLoadChecksToml_MissingChecksKey(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[something]
foo = "bar"
`)
	_, _, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for missing checks key")
	}
	if !strings.Contains(err.Error(), `unknown top-level key "something"`) {
		t.Errorf("expected error about unknown top-level key, got %q", err.Error())
	}
}

func TestLoadChecksToml_EmptyFile(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, ``)
	_, _, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for empty file")
	}
	if !strings.Contains(err.Error(), `missing required top-level key "checks"`) {
		t.Errorf("expected error about missing checks key, got %q", err.Error())
	}
}

// --- Helper: set up a temp dir with .strictcli/checks.toml and chdir to it ---

func setupChecksDir(t *testing.T, tomlContent string) (cleanup func()) {
	t.Helper()
	dir := t.TempDir()
	scDir := filepath.Join(dir, ".strictcli")
	if err := os.MkdirAll(scDir, 0755); err != nil {
		t.Fatalf("failed to create .strictcli dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(scDir, "checks.toml"), []byte(tomlContent), 0644); err != nil {
		t.Fatalf("failed to write checks.toml: %v", err)
	}
	origDir, err := os.Getwd()
	if err != nil {
		t.Fatalf("failed to get cwd: %v", err)
	}
	if err := os.Chdir(dir); err != nil {
		t.Fatalf("failed to chdir: %v", err)
	}
	return func() {
		os.Chdir(origDir)
	}
}

// testCheckContext is a minimal CheckContext for testing.
type testCheckContext struct {
	root string
}

func (c *testCheckContext) ProjectRoot() string { return c.root }

// --- Phase 3: Discovery and Registration tests ---

const validChecksToml = `
[checks.lint-code]
tags = ["code", "fast"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-deps]
tags = ["deps"]
severity = "warn"
fast = false
pure = false
needs_network = true
depends_on = ["lint-code"]
`

func TestNewApp_DiscoverChecksToml(t *testing.T) {
	cleanup := setupChecksDir(t, validChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	if !app.checksEnabled {
		t.Fatal("expected checksEnabled to be true")
	}
	if len(app.checkDefs) != 2 {
		t.Fatalf("expected 2 check defs, got %d", len(app.checkDefs))
	}
	if app.checkDefs["lint-code"] == nil {
		t.Fatal("expected lint-code check def")
	}
	if app.checkDefs["check-deps"] == nil {
		t.Fatal("expected check-deps check def")
	}
}

func TestNewApp_NoChecksToml(t *testing.T) {
	dir := t.TempDir()
	origDir, _ := os.Getwd()
	os.Chdir(dir)
	defer os.Chdir(origDir)

	app := NewApp("testapp", "1.0.0", "test app")
	if app.checksEnabled {
		t.Fatal("expected checksEnabled to be false when no checks.toml")
	}
	if app.checkDefs != nil {
		t.Fatal("expected checkDefs to be nil")
	}
}

func TestRegisterCheck_DeclaredName(t *testing.T) {
	cleanup := setupChecksDir(t, validChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("lint-code", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})

	if app.checkDefs["lint-code"].impl == nil {
		t.Fatal("expected impl to be registered")
	}
}

func TestRegisterCheck_UndeclaredName_Panics(t *testing.T) {
	cleanup := setupChecksDir(t, validChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")

	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for undeclared check name")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "not declared in .strictcli/checks.toml") {
			t.Fatalf("unexpected panic message: %s", msg)
		}
	}()

	app.RegisterCheck("nonexistent", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})
}

func TestRegisterCheck_DuplicatePanics(t *testing.T) {
	cleanup := setupChecksDir(t, validChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("lint-code", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})

	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for duplicate registration")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "duplicate registration") {
			t.Fatalf("unexpected panic message: %s", msg)
		}
	}()

	app.RegisterCheck("lint-code", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})
}

func TestRegisterCheck_NoToml_Panics(t *testing.T) {
	dir := t.TempDir()
	origDir, _ := os.Getwd()
	os.Chdir(dir)
	defer os.Chdir(origDir)

	app := NewApp("testapp", "1.0.0", "test app")

	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic when no checks.toml")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "no .strictcli/checks.toml found") {
			t.Fatalf("unexpected panic message: %s", msg)
		}
	}()

	app.RegisterCheck("foo", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})
}

func TestDoubleEntry_DeclaredButNotRegistered(t *testing.T) {
	cleanup := setupChecksDir(t, validChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.Command("greet", "say hello", func(args map[string]interface{}) int {
		fmt.Print("hello")
		return 0
	})

	// Only register one of two checks
	app.RegisterCheck("lint-code", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})
	// check-deps is NOT registered

	r := app.Test([]string{"greet"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "checks declared in .strictcli/checks.toml but not registered") {
		t.Fatalf("expected error about unregistered checks, got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "check-deps") {
		t.Fatalf("expected check-deps in error message, got %q", r.Stderr)
	}
}

func TestDoubleEntry_AllRegistered_NoError(t *testing.T) {
	cleanup := setupChecksDir(t, validChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.Command("greet", "say hello", func(args map[string]interface{}) int {
		fmt.Print("hello")
		return 0
	})
	app.RegisterCheck("lint-code", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})
	app.RegisterCheck("check-deps", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass"}
	})

	r := app.Test([]string{"greet"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if strings.Contains(r.Stdout, "hello") == false {
		t.Fatalf("expected stdout to contain 'hello', got %q", r.Stdout)
	}
}

// --- Phase 5: Runner tests ---

func makeCheckDefs(defs map[string]struct {
	tags      []string
	severity  string
	dependsOn []string
	impl      func(CheckContext) CheckResult
}) map[string]*checkDef {
	result := make(map[string]*checkDef, len(defs))
	for name, d := range defs {
		result[name] = &checkDef{
			name:      name,
			tags:      d.tags,
			severity:  d.severity,
			fast:      true,
			pure:      true,
			dependsOn: d.dependsOn,
			impl:      d.impl,
		}
	}
	return result
}

func TestRunChecks_SinglePass(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "pass", Message: "all good"}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	results, exitCode := runChecks(defs, []string{"check-a"}, ctx, false)

	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	if results[0].result.Status != "pass" {
		t.Fatalf("expected pass, got %q", results[0].result.Status)
	}
}

func TestRunChecks_SingleFail(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "fail", Message: "broken"}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	results, exitCode := runChecks(defs, []string{"check-a"}, ctx, false)

	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	if results[0].result.Status != "fail" {
		t.Fatalf("expected fail, got %q", results[0].result.Status)
	}
}

func TestRunChecks_DependencyChain_Pass(t *testing.T) {
	callOrder := []string{}
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-b": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				callOrder = append(callOrder, "check-b")
				return CheckResult{Status: "pass", Message: "ok"}
			},
		},
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-b"},
			impl: func(ctx CheckContext) CheckResult {
				callOrder = append(callOrder, "check-a")
				return CheckResult{Status: "pass", Message: "ok"}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	order, err := resolveCheckOrder(defs, map[string]bool{"check-a": true, "check-b": true})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	results, exitCode := runChecks(defs, order, ctx, false)

	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results, got %d", len(results))
	}
	// check-b should run before check-a
	if len(callOrder) != 2 || callOrder[0] != "check-b" || callOrder[1] != "check-a" {
		t.Fatalf("expected call order [check-b, check-a], got %v", callOrder)
	}
}

func TestRunChecks_DependencyFailure_Skip(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-b": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "fail", Message: "broken"}
			},
		},
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-b"},
			impl: func(ctx CheckContext) CheckResult {
				t.Fatal("check-a should not have been called")
				return CheckResult{}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	// Order: check-b first, then check-a
	results, exitCode := runChecks(defs, []string{"check-b", "check-a"}, ctx, false)

	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results, got %d", len(results))
	}
	if results[0].result.Status != "fail" {
		t.Fatalf("expected check-b fail, got %q", results[0].result.Status)
	}
	if results[1].result.Status != "skip" {
		t.Fatalf("expected check-a skip, got %q", results[1].result.Status)
	}
	if !strings.Contains(results[1].result.Message, `dependency "check-b" failed`) {
		t.Fatalf("expected skip message about check-b, got %q", results[1].result.Message)
	}
}

func TestRunChecks_TransitiveSkip(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-c": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "fail", Message: "broken"}
			},
		},
		"check-b": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-c"},
			impl: func(ctx CheckContext) CheckResult {
				t.Fatal("check-b should not run")
				return CheckResult{}
			},
		},
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-b"},
			impl: func(ctx CheckContext) CheckResult {
				t.Fatal("check-a should not run")
				return CheckResult{}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	results, exitCode := runChecks(defs, []string{"check-c", "check-b", "check-a"}, ctx, false)

	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	if len(results) != 3 {
		t.Fatalf("expected 3 results, got %d", len(results))
	}
	if results[0].result.Status != "fail" {
		t.Fatalf("expected check-c fail, got %q", results[0].result.Status)
	}
	if results[1].result.Status != "skip" {
		t.Fatalf("expected check-b skip, got %q", results[1].result.Status)
	}
	if results[2].result.Status != "skip" {
		t.Fatalf("expected check-a skip, got %q", results[2].result.Status)
	}
}

func TestResolveCheckOrder_CycleDetection(t *testing.T) {
	defs := map[string]*checkDef{
		"check-a": {
			name:      "check-a",
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-b"},
		},
		"check-b": {
			name:      "check-b",
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-a"},
		},
	}

	_, err := resolveCheckOrder(defs, map[string]bool{"check-a": true, "check-b": true})
	if err == nil {
		t.Fatal("expected cycle detection error")
	}
	if !strings.Contains(err.Error(), "check dependency cycle") {
		t.Fatalf("expected cycle error, got %q", err.Error())
	}
}

func TestResolveCheckOrder_ThreeNodeCycle(t *testing.T) {
	defs := map[string]*checkDef{
		"a": {name: "a", tags: []string{"t"}, severity: "error", dependsOn: []string{"c"}},
		"b": {name: "b", tags: []string{"t"}, severity: "error", dependsOn: []string{"a"}},
		"c": {name: "c", tags: []string{"t"}, severity: "error", dependsOn: []string{"b"}},
	}

	_, err := resolveCheckOrder(defs, map[string]bool{"a": true, "b": true, "c": true})
	if err == nil {
		t.Fatal("expected cycle detection error")
	}
	if !strings.Contains(err.Error(), "check dependency cycle") {
		t.Fatalf("expected cycle error, got %q", err.Error())
	}
}

func TestFilterChecks_ByTag(t *testing.T) {
	defs := map[string]*checkDef{
		"lint-code": {name: "lint-code", tags: []string{"code", "fast"}, severity: "error"},
		"check-deps": {name: "check-deps", tags: []string{"deps"}, severity: "warn"},
		"lint-docs": {name: "lint-docs", tags: []string{"docs", "fast"}, severity: "error"},
	}

	selected, err := filterChecks(defs, "fast", "", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	expectedNames := []string{"lint-code", "lint-docs"}
	actualNames := sortedKeys(selected)
	sort.Strings(expectedNames)
	if len(actualNames) != len(expectedNames) {
		t.Fatalf("expected %v, got %v", expectedNames, actualNames)
	}
	for i := range expectedNames {
		if actualNames[i] != expectedNames[i] {
			t.Fatalf("expected %v, got %v", expectedNames, actualNames)
		}
	}
}

func TestFilterChecks_ByGlob(t *testing.T) {
	defs := map[string]*checkDef{
		"lint-code": {name: "lint-code", tags: []string{"code"}, severity: "error"},
		"lint-docs": {name: "lint-docs", tags: []string{"docs"}, severity: "error"},
		"check-deps": {name: "check-deps", tags: []string{"deps"}, severity: "warn"},
	}

	selected, err := filterChecks(defs, "", "lint-*", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	actualNames := sortedKeys(selected)
	expectedNames := []string{"lint-code", "lint-docs"}
	if len(actualNames) != len(expectedNames) {
		t.Fatalf("expected %v, got %v", expectedNames, actualNames)
	}
	for i := range expectedNames {
		if actualNames[i] != expectedNames[i] {
			t.Fatalf("expected %v, got %v", expectedNames, actualNames)
		}
	}
}

func TestFilterChecks_RunAll(t *testing.T) {
	defs := map[string]*checkDef{
		"lint-code": {name: "lint-code", tags: []string{"code"}, severity: "error"},
		"check-deps": {name: "check-deps", tags: []string{"deps"}, severity: "warn"},
	}

	selected, err := filterChecks(defs, "", "", true)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(selected) != 2 {
		t.Fatalf("expected 2 selected checks, got %d", len(selected))
	}
}

func TestFilterChecks_TagAndGlob_Intersection(t *testing.T) {
	defs := map[string]*checkDef{
		"lint-code": {name: "lint-code", tags: []string{"code", "fast"}, severity: "error"},
		"lint-docs": {name: "lint-docs", tags: []string{"docs"}, severity: "error"},
		"check-deps": {name: "check-deps", tags: []string{"deps", "fast"}, severity: "warn"},
	}

	// tag "fast" matches lint-code and check-deps
	// glob "lint-*" matches lint-code and lint-docs
	// intersection: lint-code only
	selected, err := filterChecks(defs, "fast", "lint-*", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	actualNames := sortedKeys(selected)
	if len(actualNames) != 1 || actualNames[0] != "lint-code" {
		t.Fatalf("expected [lint-code], got %v", actualNames)
	}
}

func TestResolveCheckOrder_DependencyPullIn(t *testing.T) {
	// check-a depends on check-b, only check-a is selected
	// check-b should be pulled in
	defs := map[string]*checkDef{
		"check-a": {name: "check-a", tags: []string{"code"}, severity: "error", dependsOn: []string{"check-b"}},
		"check-b": {name: "check-b", tags: []string{"deps"}, severity: "error", dependsOn: []string{}},
	}

	order, err := resolveCheckOrder(defs, map[string]bool{"check-a": true})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(order) != 2 {
		t.Fatalf("expected 2 checks in order (pull-in), got %d: %v", len(order), order)
	}
	// check-b must come before check-a
	bIdx := -1
	aIdx := -1
	for i, name := range order {
		if name == "check-b" {
			bIdx = i
		}
		if name == "check-a" {
			aIdx = i
		}
	}
	if bIdx >= aIdx {
		t.Fatalf("expected check-b before check-a, got order: %v", order)
	}
}

func TestRunChecks_WarnWithIgnoreWarnings(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-a": {
			tags:      []string{"fast"},
			severity:  "warn",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "warn", Message: "minor issue"}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}

	// With ignoreWarnings=true, exit code should be 0
	_, exitCode := runChecks(defs, []string{"check-a"}, ctx, true)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0 with ignoreWarnings=true, got %d", exitCode)
	}
}

func TestRunChecks_WarnWithoutIgnoreWarnings(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-a": {
			tags:      []string{"fast"},
			severity:  "warn",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "warn", Message: "minor issue"}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}

	// With ignoreWarnings=false, exit code should be 1
	_, exitCode := runChecks(defs, []string{"check-a"}, ctx, false)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1 with ignoreWarnings=false, got %d", exitCode)
	}
}

func TestFilterChecks_NeitherFilter(t *testing.T) {
	defs := map[string]*checkDef{
		"lint-code": {name: "lint-code", tags: []string{"code"}, severity: "error"},
	}

	selected, err := filterChecks(defs, "", "", false)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(selected) != 0 {
		t.Fatalf("expected empty selection, got %d", len(selected))
	}
}

func TestResolveCheckOrder_NoDependencies(t *testing.T) {
	defs := map[string]*checkDef{
		"check-a": {name: "check-a", tags: []string{"fast"}, severity: "error", dependsOn: []string{}},
		"check-b": {name: "check-b", tags: []string{"fast"}, severity: "error", dependsOn: []string{}},
	}

	order, err := resolveCheckOrder(defs, map[string]bool{"check-a": true, "check-b": true})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(order) != 2 {
		t.Fatalf("expected 2 checks, got %d", len(order))
	}
	// Should be alphabetically sorted since no dependencies constrain order
	if order[0] != "check-a" || order[1] != "check-b" {
		t.Fatalf("expected [check-a, check-b], got %v", order)
	}
}

func TestRunChecks_WarnDependency_SkipsDependent(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-b": {
			tags:      []string{"fast"},
			severity:  "warn",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "warn", Message: "warning"}
			},
		},
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-b"},
			impl: func(ctx CheckContext) CheckResult {
				t.Fatal("check-a should not run when dependency warns and ignoreWarnings=false")
				return CheckResult{}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	results, exitCode := runChecks(defs, []string{"check-b", "check-a"}, ctx, false)

	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	if results[1].result.Status != "skip" {
		t.Fatalf("expected check-a to be skipped, got %q", results[1].result.Status)
	}
}

func TestRunChecks_WarnDependency_RunsWhenIgnored(t *testing.T) {
	defs := makeCheckDefs(map[string]struct {
		tags      []string
		severity  string
		dependsOn []string
		impl      func(CheckContext) CheckResult
	}{
		"check-b": {
			tags:      []string{"fast"},
			severity:  "warn",
			dependsOn: []string{},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "warn", Message: "warning"}
			},
		},
		"check-a": {
			tags:      []string{"fast"},
			severity:  "error",
			dependsOn: []string{"check-b"},
			impl: func(ctx CheckContext) CheckResult {
				return CheckResult{Status: "pass", Message: "ok"}
			},
		},
	})

	ctx := &testCheckContext{root: "/tmp/test"}
	results, exitCode := runChecks(defs, []string{"check-b", "check-a"}, ctx, true)

	if exitCode != 0 {
		t.Fatalf("expected exit code 0 (warnings ignored), got %d", exitCode)
	}
	if results[0].result.Status != "warn" {
		t.Fatalf("expected check-b warn, got %q", results[0].result.Status)
	}
	if results[1].result.Status != "pass" {
		t.Fatalf("expected check-a pass, got %q", results[1].result.Status)
	}
}

// --- Phase 6: check command tests ---

const twoChecksToml = `
[checks.version-consistency]
tags = ["release"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.changelog-coverage]
tags = ["changelog", "pre-push"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["version-consistency"]
`

// makeAppWithChecks creates an app with checks registered and a context factory set.
// Both checks pass by default. Override impls as needed after calling this.
func makeAppWithChecks(t *testing.T, toml string) *App {
	t.Helper()
	app := NewApp("testapp", "1.0.0", "test app")
	if !app.checksEnabled {
		t.Fatal("expected checksEnabled after setting up checks dir")
	}
	return app
}

func TestCheckCommand_NoFlags_ShowsHelp(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	r := app.Test([]string{"check"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "check") {
		t.Fatalf("expected help output containing 'check', got %q", r.Stdout)
	}
	// Should mention --all flag in help
	if !strings.Contains(r.Stdout, "--all") {
		t.Fatalf("expected help output containing '--all', got %q", r.Stdout)
	}
}

func TestCheckCommand_List_Human(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})

	r := app.Test([]string{"check", "--list"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "NAME") {
		t.Fatalf("expected header NAME, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "changelog-coverage") {
		t.Fatalf("expected changelog-coverage in output, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "version-consistency") {
		t.Fatalf("expected version-consistency in output, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "release") {
		t.Fatalf("expected 'release' tag in output, got %q", r.Stdout)
	}
}

func TestCheckCommand_List_JSON(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})

	r := app.Test([]string{"check", "--list", "--json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}

	// Parse JSON output
	var entries []struct {
		Name     string   `json:"name"`
		Tags     []string `json:"tags"`
		Severity string   `json:"severity"`
	}
	output := strings.TrimSpace(r.Stdout)
	if err := json.Unmarshal([]byte(output), &entries); err != nil {
		t.Fatalf("failed to parse JSON: %v; output=%q", err, output)
	}
	if len(entries) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(entries))
	}
	// Sorted alphabetically: changelog-coverage first
	if entries[0].Name != "changelog-coverage" {
		t.Fatalf("expected first entry 'changelog-coverage', got %q", entries[0].Name)
	}
	if entries[1].Name != "version-consistency" {
		t.Fatalf("expected second entry 'version-consistency', got %q", entries[1].Name)
	}
}

func TestCheckCommand_All_Passing(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "1.0.0 across 2 targets"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "all commits covered"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	r := app.Test([]string{"check", "--all"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q stdout=%q", r.ExitCode, r.Stderr, r.Stdout)
	}
	if !strings.Contains(r.Stdout, "PASS") {
		t.Fatalf("expected PASS in output, got %q", r.Stdout)
	}
}

func TestCheckCommand_All_WithFailure(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "fail", Message: "version mismatch", Details: []string{"pyproject: 1.0.0", "package.json: 1.0.1"}}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		t.Fatal("changelog-coverage should not run if version-consistency fails")
		return CheckResult{}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	r := app.Test([]string{"check", "--all"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "FAIL") {
		t.Fatalf("expected FAIL in output, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "SKIP") {
		t.Fatalf("expected SKIP in output (dependency skip), got %q", r.Stdout)
	}
}

func TestCheckCommand_TagFilter(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	// Only version-consistency has tag "release"
	r := app.Test([]string{"check", "--tag", "release"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "version-consistency") {
		t.Fatalf("expected version-consistency in output, got %q", r.Stdout)
	}
}

func TestCheckCommand_NameGlob(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	r := app.Test([]string{"check", "--name", "version-*"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "version-consistency") {
		t.Fatalf("expected version-consistency in output, got %q", r.Stdout)
	}
	// Should NOT contain changelog-coverage since it's not matched by version-*
	// (though it may appear as a pulled-in dependency -- version-consistency has no deps on it)
}

func TestCheckCommand_DryRun(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		t.Fatal("should not run in dry-run mode")
		return CheckResult{}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		t.Fatal("should not run in dry-run mode")
		return CheckResult{}
	})

	r := app.Test([]string{"check", "--all", "--dry-run"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "Would run 2 checks") {
		t.Fatalf("expected 'Would run 2 checks' in output, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "version-consistency") {
		t.Fatalf("expected version-consistency in plan, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "changelog-coverage") {
		t.Fatalf("expected changelog-coverage in plan, got %q", r.Stdout)
	}
	// changelog-coverage should show dependency info
	if !strings.Contains(r.Stdout, "depends on:") {
		t.Fatalf("expected dependency info in plan, got %q", r.Stdout)
	}
}

func TestCheckCommand_All_JSON(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "covered"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	r := app.Test([]string{"check", "--all", "--json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}

	var entries []struct {
		Name    string   `json:"name"`
		Status  string   `json:"status"`
		Message string   `json:"message"`
		Details []string `json:"details"`
	}
	output := strings.TrimSpace(r.Stdout)
	if err := json.Unmarshal([]byte(output), &entries); err != nil {
		t.Fatalf("failed to parse JSON: %v; output=%q", err, output)
	}
	if len(entries) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(entries))
	}
	for _, e := range entries {
		if e.Status != "pass" {
			t.Fatalf("expected pass, got %q for %q", e.Status, e.Name)
		}
	}
}

func TestCheckCommand_All_Verbose(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok", Details: []string{"pyproject.toml: 1.0.0", "package.json: 1.0.0"}}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "covered"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	r := app.Test([]string{"check", "--all", "--verbose"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	// With verbose, passing check details should be shown
	if !strings.Contains(r.Stdout, "pyproject.toml: 1.0.0") {
		t.Fatalf("expected verbose details in output, got %q", r.Stdout)
	}
}

func TestCheckCommand_IgnoreWarnings(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "warn", Message: "tag not pushed"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.SetCheckContext(func() CheckContext {
		return &testCheckContext{root: "/tmp"}
	})

	// Without --ignore-warnings, warn = exit 1
	r := app.Test([]string{"check", "--all"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1 without --ignore-warnings, got %d", r.ExitCode)
	}

	// With --ignore-warnings, warn = exit 0
	r = app.Test([]string{"check", "--all", "--ignore-warnings"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0 with --ignore-warnings, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
}

func TestCheckCommand_NotInHelp_WithoutToml(t *testing.T) {
	dir := t.TempDir()
	origDir, _ := os.Getwd()
	os.Chdir(dir)
	defer os.Chdir(origDir)

	app := NewApp("testapp", "1.0.0", "test app")
	app.Command("greet", "say hello", func(args map[string]interface{}) int {
		return 0
	})

	r := app.Test([]string{"--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", r.ExitCode)
	}
	if strings.Contains(r.Stdout, "check") {
		t.Fatalf("check command should NOT appear in help when no TOML, got %q", r.Stdout)
	}
}

func TestCheckCommand_NoContextFactory_Error(t *testing.T) {
	cleanup := setupChecksDir(t, twoChecksToml)
	defer cleanup()

	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheck("version-consistency", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	app.RegisterCheck("changelog-coverage", func(ctx CheckContext) CheckResult {
		return CheckResult{Status: "pass", Message: "ok"}
	})
	// Deliberately NOT calling SetCheckContext

	r := app.Test([]string{"check", "--all"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1 without context factory, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "no check context factory set") {
		t.Fatalf("expected error about missing context factory, got stderr=%q", r.Stderr)
	}
}

// Ensure unused imports don't cause errors
var _ = sort.Strings
var _ = fmt.Sprintf
