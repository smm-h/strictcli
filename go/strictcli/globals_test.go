package strictcli

import (
	"bytes"
	"reflect"
	"strings"
	"testing"
)

// --- bindValues tests ---

type SimpleBindTarget struct {
	Name    string `cli:"name" help:"Name"`
	Verbose bool   `cli:"verbose" help:"Verbose"`
}

func TestBindValues_ScalarStringAndBool(t *testing.T) {
	var target SimpleBindTarget
	values := map[string]interface{}{
		"name":    "hello",
		"verbose": true,
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Name != "hello" {
		t.Errorf("Name = %q, want %q", target.Name, "hello")
	}
	if !target.Verbose {
		t.Error("Verbose = false, want true")
	}
}

type IntFloatBindTarget struct {
	Count int     `cli:"count" help:"Count"`
	Rate  float64 `cli:"rate" help:"Rate"`
}

func TestBindValues_IntAndFloat(t *testing.T) {
	var target IntFloatBindTarget
	values := map[string]interface{}{
		"count": 42,
		"rate":  3.14,
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Count != 42 {
		t.Errorf("Count = %d, want 42", target.Count)
	}
	if target.Rate != 3.14 {
		t.Errorf("Rate = %f, want 3.14", target.Rate)
	}
}

type PointerBindTarget struct {
	Output *string `cli:"output" help:"Output"`
}

func TestBindValues_PointerSet(t *testing.T) {
	var target PointerBindTarget
	values := map[string]interface{}{
		"output": "file.txt",
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Output == nil {
		t.Fatal("Output is nil, want non-nil")
	}
	if *target.Output != "file.txt" {
		t.Errorf("*Output = %q, want %q", *target.Output, "file.txt")
	}
}

func TestBindValues_PointerNil(t *testing.T) {
	var target PointerBindTarget
	values := map[string]interface{}{
		"output": nil,
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Output != nil {
		t.Errorf("Output = %v, want nil", target.Output)
	}
}

func TestBindValues_PointerMissing(t *testing.T) {
	var target PointerBindTarget
	values := map[string]interface{}{}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Output != nil {
		t.Errorf("Output = %v, want nil", target.Output)
	}
}

type SliceBindTarget struct {
	Tags []string `cli:"tag" help:"Tags" unique:"true" env:"TAGS" env_separator:","`
}

func TestBindValues_Slice(t *testing.T) {
	var target SliceBindTarget
	values := map[string]interface{}{
		"tag": []interface{}{"a", "b", "c"},
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if len(target.Tags) != 3 {
		t.Fatalf("Tags len = %d, want 3", len(target.Tags))
	}
	want := []string{"a", "b", "c"}
	for i, v := range target.Tags {
		if v != want[i] {
			t.Errorf("Tags[%d] = %q, want %q", i, v, want[i])
		}
	}
}

type MapBindTarget struct {
	Labels map[string]string `cli:"label" help:"Labels" unique:"true"`
}

func TestBindValues_Map(t *testing.T) {
	var target MapBindTarget
	values := map[string]interface{}{
		"label": map[string]interface{}{"env": "prod", "team": "core"},
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if len(target.Labels) != 2 {
		t.Fatalf("Labels len = %d, want 2", len(target.Labels))
	}
	if target.Labels["env"] != "prod" {
		t.Errorf("Labels[env] = %q, want %q", target.Labels["env"], "prod")
	}
	if target.Labels["team"] != "core" {
		t.Errorf("Labels[team] = %q, want %q", target.Labels["team"], "core")
	}
}

type EmbeddedCommon struct {
	Verbose bool `cli:"verbose" help:"Verbose"`
}

type EmbeddedBindTarget struct {
	EmbeddedCommon
	Name string `cli:"name" help:"Name"`
}

func TestBindValues_EmbeddedStruct(t *testing.T) {
	var target EmbeddedBindTarget
	values := map[string]interface{}{
		"verbose": true,
		"name":    "test",
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if !target.Verbose {
		t.Error("Verbose = false, want true")
	}
	if target.Name != "test" {
		t.Errorf("Name = %q, want %q", target.Name, "test")
	}
}

func TestBindValues_TypeMismatchReturnsError(t *testing.T) {
	var target SimpleBindTarget
	values := map[string]interface{}{
		"name": 42, // wrong type: int instead of string
	}
	err := bindValues(&target, values)
	if err == nil {
		t.Fatal("expected error for type mismatch, got nil")
	}
	if !strings.Contains(err.Error(), "expected string") {
		t.Errorf("error = %q, want it to contain 'expected string'", err.Error())
	}
}

func TestBindValues_NonPointerTargetReturnsError(t *testing.T) {
	var target SimpleBindTarget
	err := bindValues(target, nil)
	if err == nil {
		t.Fatal("expected error for non-pointer target, got nil")
	}
}

func TestBindValues_IntFromFloat64(t *testing.T) {
	// JSON unmarshaling produces float64 for numbers; coercion should handle it
	var target IntFloatBindTarget
	values := map[string]interface{}{
		"count": float64(5),
		"rate":  float64(2.5),
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Count != 5 {
		t.Errorf("Count = %d, want 5", target.Count)
	}
}

func TestBindValues_FloatFromInt(t *testing.T) {
	var target IntFloatBindTarget
	values := map[string]interface{}{
		"count": 7,
		"rate":  3, // int where float64 is expected
	}
	if err := bindValues(&target, values); err != nil {
		t.Fatal(err)
	}
	if target.Rate != 3.0 {
		t.Errorf("Rate = %f, want 3.0", target.Rate)
	}
}

// --- RegisterGlobals tests ---

type TestGlobals struct {
	Verbose bool   `cli:"verbose" help:"Enable verbose output" default:"false"`
	Output  string `cli:"output" help:"Output format" default:"text"`
}

func TestRegisterGlobals_RegistersFlags(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test app")
	RegisterGlobals[TestGlobals](app)

	flags := app.GlobalFlags()
	if len(flags) != 2 {
		t.Fatalf("expected 2 global flags, got %d", len(flags))
	}

	names := make(map[string]bool)
	for _, f := range flags {
		names[f.Name] = true
	}
	if !names["verbose"] {
		t.Error("missing global flag 'verbose'")
	}
	if !names["output"] {
		t.Error("missing global flag 'output'")
	}
}

func TestRegisterGlobals_StoresType(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test app")
	RegisterGlobals[TestGlobals](app)

	if app.globalsType == nil {
		t.Fatal("expected globalsType to be set")
	}
	if app.globalsType != reflect.TypeOf(TestGlobals{}) {
		t.Errorf("globalsType = %v, want %v", app.globalsType, reflect.TypeOf(TestGlobals{}))
	}
}

// Reserved name tests

type ReservedHelpGlobals struct {
	Help bool `cli:"help" help:"Help flag"`
}

func TestRegisterGlobals_ReservedHelp(t *testing.T) {
	assertPanics(t, "ReservedHelp", "reserved", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[ReservedHelpGlobals](app)
	})
}

type ReservedVersionGlobals struct {
	Version bool `cli:"version" help:"Version flag"`
}

func TestRegisterGlobals_ReservedVersion(t *testing.T) {
	assertPanics(t, "ReservedVersion", "reserved", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[ReservedVersionGlobals](app)
	})
}

type ReservedDumpSchemaGlobals struct {
	DumpSchema bool `cli:"dump-schema" help:"Dump schema"`
}

func TestRegisterGlobals_ReservedDumpSchema(t *testing.T) {
	assertPanics(t, "ReservedDumpSchema", "reserved", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[ReservedDumpSchemaGlobals](app)
	})
}

type ReservedMcpGlobals struct {
	Mcp bool `cli:"mcp" help:"MCP mode"`
}

func TestRegisterGlobals_ReservedMcp(t *testing.T) {
	assertPanics(t, "ReservedMcp", "reserved", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[ReservedMcpGlobals](app)
	})
}

type ReservedShortHGlobals struct {
	Verbose bool `cli:"verbose" help:"Verbose" short:"h"`
}

func TestRegisterGlobals_ReservedShortH(t *testing.T) {
	assertPanics(t, "ReservedShortH", "reserved", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[ReservedShortHGlobals](app)
	})
}

type ReservedShortVGlobals struct {
	Quiet bool `cli:"quiet" help:"Quiet" short:"v"`
}

func TestRegisterGlobals_ReservedShortV(t *testing.T) {
	assertPanics(t, "ReservedShortV", "reserved", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[ReservedShortVGlobals](app)
	})
}

// Arg-tagged field in globals struct

type GlobalsWithArg struct {
	Verbose bool   `cli:"verbose" help:"Verbose" default:"false"`
	Path    string `arg:"path" help:"File path"`
}

func TestRegisterGlobals_WithArgPanics(t *testing.T) {
	assertPanics(t, "GlobalsWithArg", "must not have arg:-tagged fields", func() {
		app := NewApp("testapp", "1.0.0", "test app")
		RegisterGlobals[GlobalsWithArg](app)
	})
}

// --- Globals[T] accessor tests ---

type SimpleGlobals struct {
	Verbose bool `cli:"verbose" help:"Verbose"`
}

func TestGlobals_PopulatesFromContext(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{
		"verbose": true,
	})

	g := Globals[SimpleGlobals](ctx)
	if !g.Verbose {
		t.Error("Verbose = false, want true")
	}
}

func TestGlobals_BoolDefaultFalse(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{
		"verbose": false,
	})

	g := Globals[SimpleGlobals](ctx)
	if g.Verbose {
		t.Error("Verbose = true, want false")
	}
}

type OptionalGlobals struct {
	Output *string `cli:"output" help:"Output file"`
}

func TestGlobals_OptionalNotSet(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{})

	g := Globals[OptionalGlobals](ctx)
	if g.Output != nil {
		t.Errorf("Output = %v, want nil", g.Output)
	}
}

func TestGlobals_OptionalSet(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{
		"output": "file.txt",
	})

	g := Globals[OptionalGlobals](ctx)
	if g.Output == nil {
		t.Fatal("Output is nil, want non-nil")
	}
	if *g.Output != "file.txt" {
		t.Errorf("*Output = %q, want %q", *g.Output, "file.txt")
	}
}

func TestGlobals_CachedOnSecondCall(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{
		"verbose": true,
	})

	g1 := Globals[SimpleGlobals](ctx)
	g2 := Globals[SimpleGlobals](ctx)

	// Both should be identical (same cached value)
	if g1 != g2 {
		t.Error("expected Globals to return cached value on second call")
	}

	// Verify cache is set
	if ctx.globalsCache == nil {
		t.Error("expected globalsCache to be set after first call")
	}
}

func TestGlobals_NilGlobalsMap(t *testing.T) {
	ctx := newContext(nil, nil, nil)

	g := Globals[SimpleGlobals](ctx)
	if g.Verbose {
		t.Error("Verbose = true, want false (zero value)")
	}
}

// --- Integration tests: RegisterGlobals + App.Test ---

type IntegrationGlobals struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output" default:"false"`
}

func TestRegisterGlobals_Integration_HelpShowsFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[IntegrationGlobals](app)
	app.Command("cmd", "a command", func(kwargs map[string]interface{}) int {
		return 0
	})

	// Global flags appear in command-level help, not app-level help
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "--verbose") {
		t.Errorf("command help output should contain --verbose, got:\n%s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "Global flags:") {
		t.Errorf("command help output should contain 'Global flags:', got:\n%s", r.Stdout)
	}
}

func TestRegisterGlobals_Integration_FlagParsed(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[IntegrationGlobals](app)

	var captured bool
	app.Command("cmd", "a command", func(kwargs map[string]interface{}) int {
		captured = kwargs["verbose"].(bool)
		return 0
	})

	r := app.Test([]string{"--verbose", "cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !captured {
		t.Error("expected verbose=true in handler kwargs")
	}
}

func TestRegisterGlobals_Integration_DefaultValue(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[IntegrationGlobals](app)

	var captured bool
	app.Command("cmd", "a command", func(kwargs map[string]interface{}) int {
		captured = kwargs["verbose"].(bool)
		return 0
	})

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if captured {
		t.Error("expected verbose=false (default) in handler kwargs")
	}
}

type MultiTypeGlobals struct {
	Verbose bool   `cli:"verbose" help:"Verbose" default:"false"`
	Format  string `cli:"format" help:"Output format" default:"text"`
	Level   int    `cli:"level" help:"Log level" default:"0"`
}

func TestRegisterGlobals_Integration_MultipleTypes(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	RegisterGlobals[MultiTypeGlobals](app)

	var gotVerbose bool
	var gotFormat string
	var gotLevel int
	app.Command("cmd", "a command", func(kwargs map[string]interface{}) int {
		gotVerbose = kwargs["verbose"].(bool)
		gotFormat = kwargs["format"].(string)
		gotLevel = kwargs["level"].(int)
		return 0
	})

	r := app.Test([]string{"--verbose", "--format", "json", "--level", "3", "cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !gotVerbose {
		t.Error("expected verbose=true")
	}
	if gotFormat != "json" {
		t.Errorf("format = %q, want %q", gotFormat, "json")
	}
	if gotLevel != 3 {
		t.Errorf("level = %d, want 3", gotLevel)
	}
}

// Full integration: RegisterGlobals + Globals[T] accessor via Context

func TestGlobals_FullIntegration(t *testing.T) {
	// Create a Context with globals that would come from parsed CLI args
	var stdout, stderr bytes.Buffer
	ctx := newContext(&stdout, &stderr, map[string]interface{}{
		"verbose": true,
		"format":  "json",
		"level":   3,
	})

	g := Globals[MultiTypeGlobals](ctx)

	if !g.Verbose {
		t.Error("Verbose = false, want true")
	}
	if g.Format != "json" {
		t.Errorf("Format = %q, want %q", g.Format, "json")
	}
	if g.Level != 3 {
		t.Errorf("Level = %d, want 3", g.Level)
	}

	// Second call returns cached
	g2 := Globals[MultiTypeGlobals](ctx)
	if g != g2 {
		t.Error("expected second Globals call to return cached value")
	}
}

// DashToUnderscore test: globals with dashes in cli tag

type DashGlobals struct {
	DryRun bool `cli:"dry-run" help:"Dry run mode" default:"false"`
}

func TestGlobals_DashInFlagName(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{
		"dry-run": true,
	})

	g := Globals[DashGlobals](ctx)
	if !g.DryRun {
		t.Error("DryRun = false, want true")
	}
}

// Pointer fields in Globals

type PointerGlobals struct {
	Output *string `cli:"output" help:"Output file"`
	Debug  *bool   `cli:"debug" help:"Debug mode"`
}

func TestGlobals_PointerFieldSet(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{
		"output": "result.txt",
		"debug":  true,
	})

	g := Globals[PointerGlobals](ctx)
	if g.Output == nil {
		t.Fatal("Output is nil")
	}
	if *g.Output != "result.txt" {
		t.Errorf("*Output = %q, want %q", *g.Output, "result.txt")
	}
	if g.Debug == nil {
		t.Fatal("Debug is nil")
	}
	if !*g.Debug {
		t.Error("*Debug = false, want true")
	}
}

func TestGlobals_PointerFieldNilWhenMissing(t *testing.T) {
	ctx := newContext(nil, nil, map[string]interface{}{})

	g := Globals[PointerGlobals](ctx)
	if g.Output != nil {
		t.Errorf("Output = %v, want nil", g.Output)
	}
	if g.Debug != nil {
		t.Errorf("Debug = %v, want nil", g.Debug)
	}
}
