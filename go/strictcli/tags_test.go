package strictcli

import (
	"reflect"
	"strings"
	"testing"
)

// --- Helper to assert panics ---

func assertPanics(t *testing.T, name string, wantSubstr string, fn func()) {
	t.Helper()
	defer func() {
		r := recover()
		if r == nil {
			t.Errorf("%s: expected panic, got none", name)
			return
		}
		msg, ok := r.(string)
		if !ok {
			t.Errorf("%s: panic value is not a string: %v", name, r)
			return
		}
		if !strings.Contains(msg, wantSubstr) {
			t.Errorf("%s: panic message %q does not contain %q", name, msg, wantSubstr)
		}
	}()
	fn()
}

// --- Scalar type tests ---

type ScalarStringFlags struct {
	Output string `cli:"output" help:"Output file path"`
}

func TestExtractFlags_ScalarString(t *testing.T) {
	flags, args := extractFlags(reflect.TypeOf(ScalarStringFlags{}))
	if len(args) != 0 {
		t.Fatalf("expected 0 args, got %d", len(args))
	}
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "output" {
		t.Errorf("Name = %q, want %q", f.Name, "output")
	}
	if f.Type != TypeStr {
		t.Errorf("Type = %d, want TypeStr", f.Type)
	}
	if f.Help != "Output file path" {
		t.Errorf("Help = %q, want %q", f.Help, "Output file path")
	}
	if f.hasDefault {
		t.Errorf("expected no default (required)")
	}
}

type ScalarBoolFlags struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output"`
}

func TestExtractFlags_ScalarBool(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ScalarBoolFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "verbose" {
		t.Errorf("Name = %q, want %q", f.Name, "verbose")
	}
	if f.Type != TypeBool {
		t.Errorf("Type = %d, want TypeBool", f.Type)
	}
	if f.hasDefault {
		t.Errorf("expected no default (required bool)")
	}
	if !f.Negatable {
		t.Errorf("expected Negatable=true for bool flag")
	}
}

type ScalarIntFlags struct {
	Count int `cli:"count" help:"Number of items"`
}

func TestExtractFlags_ScalarInt(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ScalarIntFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "count" {
		t.Errorf("Name = %q, want %q", f.Name, "count")
	}
	if f.Type != TypeInt {
		t.Errorf("Type = %d, want TypeInt", f.Type)
	}
	if f.hasDefault {
		t.Errorf("expected no default (required)")
	}
}

type ScalarFloatFlags struct {
	Rate float64 `cli:"rate" help:"Processing rate"`
}

func TestExtractFlags_ScalarFloat(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ScalarFloatFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "rate" {
		t.Errorf("Name = %q, want %q", f.Name, "rate")
	}
	if f.Type != TypeFloat {
		t.Errorf("Type = %d, want TypeFloat", f.Type)
	}
}

// --- Pointer type tests (optional with nil default) ---

type PointerStringFlags struct {
	Output *string `cli:"output" help:"Output file path"`
}

func TestExtractFlags_PointerString(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(PointerStringFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "output" {
		t.Errorf("Name = %q, want %q", f.Name, "output")
	}
	if f.Type != TypeStr {
		t.Errorf("Type = %d, want TypeStr", f.Type)
	}
	if !f.hasDefault {
		t.Errorf("expected hasDefault=true for pointer type")
	}
	if f.Default != nil {
		t.Errorf("expected Default=nil for pointer type, got %v", f.Default)
	}
}

type PointerBoolFlags struct {
	Verbose *bool `cli:"verbose" help:"Enable verbose output"`
}

func TestExtractFlags_PointerBool(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(PointerBoolFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeBool {
		t.Errorf("Type = %d, want TypeBool", f.Type)
	}
	if !f.hasDefault {
		t.Errorf("expected hasDefault=true for pointer type")
	}
	if f.Default != nil {
		t.Errorf("expected Default=nil, got %v", f.Default)
	}
}

type PointerIntFlags struct {
	Count *int `cli:"count" help:"Number of items"`
}

func TestExtractFlags_PointerInt(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(PointerIntFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeInt {
		t.Errorf("Type = %d, want TypeInt", f.Type)
	}
	if !f.hasDefault {
		t.Errorf("expected hasDefault=true")
	}
	if f.Default != nil {
		t.Errorf("expected Default=nil, got %v", f.Default)
	}
}

type PointerFloatFlags struct {
	Rate *float64 `cli:"rate" help:"Processing rate"`
}

func TestExtractFlags_PointerFloat(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(PointerFloatFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeFloat {
		t.Errorf("Type = %d, want TypeFloat", f.Type)
	}
	if !f.hasDefault {
		t.Errorf("expected hasDefault=true")
	}
}

// --- Compound types ---

type SliceStringFlags struct {
	Tags []string `cli:"tag" help:"Tags to apply" unique:"true" env:"TAGS" env_separator:","`
}

func TestExtractFlags_SliceString(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(SliceStringFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "tag" {
		t.Errorf("Name = %q, want %q", f.Name, "tag")
	}
	if f.Type != TypeListStr {
		t.Errorf("Type = %d, want TypeListStr (%d)", f.Type, TypeListStr)
	}
	if !f.Repeatable {
		t.Errorf("expected Repeatable=true for list flag")
	}
	if !f.Unique {
		t.Errorf("expected Unique=true")
	}
}

type SliceIntFlags struct {
	Ports []int `cli:"port" help:"Port numbers" unique:"false" env:"PORTS" env_separator:","`
}

func TestExtractFlags_SliceInt(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(SliceIntFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeListInt {
		t.Errorf("Type = %d, want TypeListInt (%d)", f.Type, TypeListInt)
	}
	if f.Unique {
		t.Errorf("expected Unique=false")
	}
}

type SliceFloatFlags struct {
	Weights []float64 `cli:"weight" help:"Weights" unique:"true" env:"WEIGHTS" env_separator:","`
}

func TestExtractFlags_SliceFloat(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(SliceFloatFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeListFloat {
		t.Errorf("Type = %d, want TypeListFloat (%d)", f.Type, TypeListFloat)
	}
}

type MapStringFlags struct {
	Labels map[string]string `cli:"label" help:"Labels to apply" unique:"true"`
}

func TestExtractFlags_MapStringString(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(MapStringFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeDictStr {
		t.Errorf("Type = %d, want TypeDictStr (%d)", f.Type, TypeDictStr)
	}
	if !f.Repeatable {
		t.Errorf("expected Repeatable=true for dict flag")
	}
}

type MapIntFlags struct {
	Counts map[string]int `cli:"count" help:"Counts by name" unique:"true"`
}

func TestExtractFlags_MapStringInt(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(MapIntFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeDictInt {
		t.Errorf("Type = %d, want TypeDictInt (%d)", f.Type, TypeDictInt)
	}
}

type MapFloatFlags struct {
	Rates map[string]float64 `cli:"rate" help:"Rates by name" unique:"true"`
}

func TestExtractFlags_MapStringFloat(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(MapFloatFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Type != TypeDictFloat {
		t.Errorf("Type = %d, want TypeDictFloat (%d)", f.Type, TypeDictFloat)
	}
}

// --- Embedded structs (FlagSets) ---

type CommonFlags struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output"`
	DryRun  bool `cli:"dry-run" help:"Dry run mode"`
}

type CommandWithEmbedded struct {
	CommonFlags
	Output string `cli:"output" help:"Output file"`
}

func TestExtractFlags_EmbeddedStruct(t *testing.T) {
	flags, args := extractFlags(reflect.TypeOf(CommandWithEmbedded{}))
	if len(args) != 0 {
		t.Fatalf("expected 0 args, got %d", len(args))
	}
	if len(flags) != 3 {
		t.Fatalf("expected 3 flags, got %d", len(flags))
	}
	names := make(map[string]bool)
	for _, f := range flags {
		names[f.Name] = true
	}
	for _, want := range []string{"verbose", "dry-run", "output"} {
		if !names[want] {
			t.Errorf("missing flag %q", want)
		}
	}
}

// --- Cycle detection ---

// Cycles in embedded structs can't be tested directly with Go struct types
// (Go compiler prevents them). But we can test the visited-tracking logic
// via a two-level nesting test.

type Level2Flags struct {
	Debug bool `cli:"debug" help:"Debug mode"`
}

type Level1Flags struct {
	Level2Flags
	Trace bool `cli:"trace" help:"Trace mode"`
}

type DeepEmbedded struct {
	Level1Flags
	Output string `cli:"output" help:"Output file"`
}

func TestExtractFlags_DeepEmbedded(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(DeepEmbedded{}))
	if len(flags) != 3 {
		t.Fatalf("expected 3 flags, got %d", len(flags))
	}
	names := make(map[string]bool)
	for _, f := range flags {
		names[f.Name] = true
	}
	for _, want := range []string{"debug", "trace", "output"} {
		if !names[want] {
			t.Errorf("missing flag %q", want)
		}
	}
}

// --- Missing help tag (panic) ---

type MissingHelpFlags struct {
	Output string `cli:"output"`
}

func TestExtractFlags_MissingHelp(t *testing.T) {
	assertPanics(t, "MissingHelp", "help tag is required", func() {
		extractFlags(reflect.TypeOf(MissingHelpFlags{}))
	})
}

// --- Both cli and arg tags (panic) ---

type BothCliAndArgFlags struct {
	Output string `cli:"output" arg:"output" help:"Output file"`
}

func TestExtractFlags_BothCliAndArg(t *testing.T) {
	assertPanics(t, "BothCliAndArg", "cannot have both cli and arg tags", func() {
		extractFlags(reflect.TypeOf(BothCliAndArgFlags{}))
	})
}

// --- Unknown tag key (panic) ---

type UnknownTagFlags struct {
	Output string `cli:"output" help:"Output file" bogus:"xyz"`
}

func TestExtractFlags_UnknownTagKey(t *testing.T) {
	assertPanics(t, "UnknownTagKey", "unknown tag key", func() {
		extractFlags(reflect.TypeOf(UnknownTagFlags{}))
	})
}

// --- Short form validation ---

type ShortFormFlags struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output" short:"v"`
}

func TestExtractFlags_ShortForm(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ShortFormFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	if flags[0].Short != "v" {
		t.Errorf("Short = %q, want %q", flags[0].Short, "v")
	}
}

type ShortFormTooLongFlags struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output" short:"vv"`
}

func TestExtractFlags_ShortFormTooLong(t *testing.T) {
	assertPanics(t, "ShortFormTooLong", "short tag must be exactly one character", func() {
		extractFlags(reflect.TypeOf(ShortFormTooLongFlags{}))
	})
}

// --- Default tag parsing ---

type DefaultStringFlags struct {
	Output string `cli:"output" help:"Output file" default:"stdout"`
}

func TestExtractFlags_DefaultString(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(DefaultStringFlags{}))
	f := flags[0]
	if !f.hasDefault {
		t.Fatal("expected hasDefault=true")
	}
	if f.Default != "stdout" {
		t.Errorf("Default = %v, want %q", f.Default, "stdout")
	}
}

type DefaultBoolFlags struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output" default:"false"`
}

func TestExtractFlags_DefaultBool(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(DefaultBoolFlags{}))
	f := flags[0]
	if !f.hasDefault {
		t.Fatal("expected hasDefault=true")
	}
	if f.Default != false {
		t.Errorf("Default = %v, want false", f.Default)
	}
}

type DefaultBoolTrueFlags struct {
	Verbose bool `cli:"verbose" help:"Enable verbose output" default:"true"`
}

func TestExtractFlags_DefaultBoolTrue(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(DefaultBoolTrueFlags{}))
	f := flags[0]
	if !f.hasDefault {
		t.Fatal("expected hasDefault=true")
	}
	if f.Default != true {
		t.Errorf("Default = %v, want true", f.Default)
	}
}

type DefaultIntFlags struct {
	Count int `cli:"count" help:"Number of items" default:"3"`
}

func TestExtractFlags_DefaultInt(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(DefaultIntFlags{}))
	f := flags[0]
	if !f.hasDefault {
		t.Fatal("expected hasDefault=true")
	}
	if f.Default != 3 {
		t.Errorf("Default = %v, want 3", f.Default)
	}
}

type DefaultFloatFlags struct {
	Rate float64 `cli:"rate" help:"Processing rate" default:"1.5"`
}

func TestExtractFlags_DefaultFloat(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(DefaultFloatFlags{}))
	f := flags[0]
	if !f.hasDefault {
		t.Fatal("expected hasDefault=true")
	}
	if f.Default != 1.5 {
		t.Errorf("Default = %v, want 1.5", f.Default)
	}
}

// --- Default + pointer type (panic) ---

type DefaultPointerFlags struct {
	Output *string `cli:"output" help:"Output file" default:"stdout"`
}

func TestExtractFlags_DefaultWithPointer(t *testing.T) {
	assertPanics(t, "DefaultWithPointer", "default tag is invalid on pointer types", func() {
		extractFlags(reflect.TypeOf(DefaultPointerFlags{}))
	})
}

// --- Arg fields ---

type SimpleArgFlags struct {
	Path string `arg:"path" help:"File path to process"`
}

func TestExtractFlags_SimpleArg(t *testing.T) {
	flags, args := extractFlags(reflect.TypeOf(SimpleArgFlags{}))
	if len(flags) != 0 {
		t.Fatalf("expected 0 flags, got %d", len(flags))
	}
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	a := args[0]
	if a.Name != "path" {
		t.Errorf("Name = %q, want %q", a.Name, "path")
	}
	if a.Type != TypeStr {
		t.Errorf("Type = %d, want TypeStr", a.Type)
	}
	if !a.Required {
		t.Errorf("expected Required=true for non-pointer arg")
	}
}

type OptionalArgFlags struct {
	Path *string `arg:"path" help:"File path to process"`
}

func TestExtractFlags_OptionalArg(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(OptionalArgFlags{}))
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	a := args[0]
	if a.Required {
		t.Errorf("expected Required=false for pointer arg")
	}
	if a.Default != nil {
		t.Errorf("expected Default=nil for pointer arg, got %v", a.Default)
	}
}

type ArgWithDefaultFlags struct {
	Format string `arg:"format" help:"Output format" default:"json"`
}

func TestExtractFlags_ArgWithDefault(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(ArgWithDefaultFlags{}))
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	a := args[0]
	if a.Required {
		t.Errorf("expected Required=false for arg with default")
	}
	if a.Default != "json" {
		t.Errorf("Default = %v, want %q", a.Default, "json")
	}
}

// --- Variadic arg ---

type VariadicArgFlags struct {
	Files []string `arg:"files" help:"Files to process" variadic:"true"`
}

func TestExtractFlags_VariadicArg(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(VariadicArgFlags{}))
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	a := args[0]
	if !a.IsVariadic {
		t.Errorf("expected IsVariadic=true")
	}
	if a.Type != TypeListStr {
		t.Errorf("Type = %d, want TypeListStr (%d)", a.Type, TypeListStr)
	}
}

type VariadicNonSliceFlags struct {
	File string `arg:"file" help:"File to process" variadic:"true"`
}

func TestExtractFlags_VariadicNonSlice(t *testing.T) {
	assertPanics(t, "VariadicNonSlice", "variadic requires a slice type", func() {
		extractFlags(reflect.TypeOf(VariadicNonSliceFlags{}))
	})
}

// --- Map type on arg (panic) ---

type MapArgFlags struct {
	Labels map[string]string `arg:"labels" help:"Labels"`
}

func TestExtractFlags_MapArg(t *testing.T) {
	assertPanics(t, "MapArg", "map types are not supported for positional arguments", func() {
		extractFlags(reflect.TypeOf(MapArgFlags{}))
	})
}

// --- No cli or arg tag (skipped) ---

type FieldsWithoutTags struct {
	Internal string
	Output   string `cli:"output" help:"Output file"`
}

func TestExtractFlags_SkipsUntaggedFields(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(FieldsWithoutTags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	if flags[0].Name != "output" {
		t.Errorf("Name = %q, want %q", flags[0].Name, "output")
	}
}

// --- Env and prefixed ---

type EnvFlags struct {
	Token string `cli:"token" help:"Auth token" env:"MY_TOKEN" prefixed:"false"`
}

func TestExtractFlags_EnvAndPrefixed(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(EnvFlags{}))
	f := flags[0]
	if f.Env != "MY_TOKEN" {
		t.Errorf("Env = %q, want %q", f.Env, "MY_TOKEN")
	}
	if f.Prefixed {
		t.Errorf("expected Prefixed=false")
	}
}

// --- Negatable ---

type NegatableFlags struct {
	Watch bool `cli:"watch" help:"Watch mode" negatable:"false"`
}

func TestExtractFlags_Negatable(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(NegatableFlags{}))
	f := flags[0]
	if f.Negatable {
		t.Errorf("expected Negatable=false")
	}
}

// --- Choices ---

type ChoicesFlags struct {
	Format string `cli:"format" help:"Output format" choices:"json,yaml,toml"`
}

func TestExtractFlags_Choices(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ChoicesFlags{}))
	f := flags[0]
	if len(f.Choices) != 3 {
		t.Fatalf("expected 3 choices, got %d", len(f.Choices))
	}
	want := []string{"json", "yaml", "toml"}
	for i, c := range f.Choices {
		if c.(string) != want[i] {
			t.Errorf("Choices[%d] = %v, want %q", i, c, want[i])
		}
	}
}

type IntChoicesFlags struct {
	Level int `cli:"level" help:"Level" choices:"1,2,3"`
}

func TestExtractFlags_IntChoices(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(IntChoicesFlags{}))
	f := flags[0]
	if len(f.Choices) != 3 {
		t.Fatalf("expected 3 choices, got %d", len(f.Choices))
	}
	want := []int{1, 2, 3}
	for i, c := range f.Choices {
		if c.(int) != want[i] {
			t.Errorf("Choices[%d] = %v, want %d", i, c, want[i])
		}
	}
}

// --- Args with choices ---

type ArgChoicesStruct struct {
	Format string `arg:"format" help:"Output format" choices:"json,yaml"`
}

func TestExtractFlags_ArgWithChoices(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(ArgChoicesStruct{}))
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	a := args[0]
	if len(a.Choices) != 2 {
		t.Fatalf("expected 2 choices, got %d", len(a.Choices))
	}
}

// --- Mixed flags and args ---

type MixedFlagsAndArgs struct {
	Verbose bool   `cli:"verbose" help:"Verbose output"`
	Path    string `arg:"path" help:"File path"`
}

func TestExtractFlags_MixedFlagsAndArgs(t *testing.T) {
	flags, args := extractFlags(reflect.TypeOf(MixedFlagsAndArgs{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	if flags[0].Name != "verbose" {
		t.Errorf("flag Name = %q, want %q", flags[0].Name, "verbose")
	}
	if args[0].Name != "path" {
		t.Errorf("arg Name = %q, want %q", args[0].Name, "path")
	}
}

// --- extractTagKeys unit tests ---

func TestExtractTagKeys(t *testing.T) {
	tests := []struct {
		name string
		tag  string
		want []string
	}{
		{
			name: "single key",
			tag:  `cli:"output"`,
			want: []string{"cli"},
		},
		{
			name: "multiple keys",
			tag:  `cli:"output" help:"description" short:"o"`,
			want: []string{"cli", "help", "short"},
		},
		{
			name: "with underscores in key",
			tag:  `cli:"output" env_separator:","`,
			want: []string{"cli", "env_separator"},
		},
		{
			name: "empty",
			tag:  ``,
			want: nil,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractTagKeys(tt.tag)
			if len(got) != len(tt.want) {
				t.Fatalf("extractTagKeys(%q) = %v, want %v", tt.tag, got, tt.want)
			}
			for i := range got {
				if got[i] != tt.want[i] {
					t.Errorf("extractTagKeys(%q)[%d] = %q, want %q", tt.tag, i, got[i], tt.want[i])
				}
			}
		})
	}
}

// --- Arg ordering matches field declaration order ---

type MultiArgFlags struct {
	Src  string `arg:"src" help:"Source path"`
	Dst  string `arg:"dst" help:"Destination path"`
	Mode string `arg:"mode" help:"Copy mode" default:"copy"`
}

func TestExtractFlags_ArgOrder(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(MultiArgFlags{}))
	if len(args) != 3 {
		t.Fatalf("expected 3 args, got %d", len(args))
	}
	wantNames := []string{"src", "dst", "mode"}
	for i, a := range args {
		if a.Name != wantNames[i] {
			t.Errorf("arg[%d].Name = %q, want %q", i, a.Name, wantNames[i])
		}
	}
}

// --- EnvSeparator ---

type EnvSepFlags struct {
	Paths []string `cli:"path" help:"Search paths" env:"SEARCH_PATHS" env_separator:":" unique:"true"`
}

func TestExtractFlags_EnvSeparator(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(EnvSepFlags{}))
	f := flags[0]
	if f.EnvSeparator != ":" {
		t.Errorf("EnvSeparator = %q, want %q", f.EnvSeparator, ":")
	}
}

// --- Unique defaults to true for list/dict when not specified ---

type UniqueDefaultListFlags struct {
	Tags []string `cli:"tag" help:"Tags" env:"TAGS" env_separator:","`
}

func TestExtractFlags_UniqueDefaultsToTrueForList(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(UniqueDefaultListFlags{}))
	f := flags[0]
	if !f.Unique {
		t.Errorf("expected Unique=true (default for list)")
	}
}

type UniqueDefaultDictFlags struct {
	Labels map[string]string `cli:"label" help:"Labels"`
}

func TestExtractFlags_UniqueDefaultsToTrueForDict(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(UniqueDefaultDictFlags{}))
	f := flags[0]
	if !f.Unique {
		t.Errorf("expected Unique=true (default for dict)")
	}
}

// --- Flag with all options ---

type FullFeaturedFlags struct {
	Format string `cli:"format" help:"Output format" short:"f" env:"MY_FORMAT" prefixed:"false" choices:"json,yaml" default:"json"`
}

func TestExtractFlags_FullFeatured(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(FullFeaturedFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	f := flags[0]
	if f.Name != "format" {
		t.Errorf("Name = %q", f.Name)
	}
	if f.Short != "f" {
		t.Errorf("Short = %q", f.Short)
	}
	if f.Env != "MY_FORMAT" {
		t.Errorf("Env = %q", f.Env)
	}
	if f.Prefixed {
		t.Errorf("expected Prefixed=false")
	}
	if len(f.Choices) != 2 {
		t.Fatalf("expected 2 choices, got %d", len(f.Choices))
	}
	if !f.hasDefault || f.Default != "json" {
		t.Errorf("Default = %v, want %q", f.Default, "json")
	}
}

// --- Non-struct type panics ---

func TestExtractFlags_NonStructPanics(t *testing.T) {
	assertPanics(t, "NonStruct", "expected struct type", func() {
		extractFlags(reflect.TypeOf(42))
	})
}

// --- Pointer to struct is unwrapped ---

func TestExtractFlags_PointerToStruct(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(&ScalarStringFlags{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
}

// --- Int arg ---

type IntArgFlags struct {
	Count int `arg:"count" help:"Number of items"`
}

func TestExtractFlags_IntArg(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(IntArgFlags{}))
	if len(args) != 1 {
		t.Fatalf("expected 1 arg, got %d", len(args))
	}
	a := args[0]
	if a.Type != TypeInt {
		t.Errorf("Type = %d, want TypeInt", a.Type)
	}
	if !a.Required {
		t.Errorf("expected Required=true")
	}
}

// --- Float arg ---

type FloatArgFlags struct {
	Rate float64 `arg:"rate" help:"Processing rate"`
}

func TestExtractFlags_FloatArg(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(FloatArgFlags{}))
	a := args[0]
	if a.Type != TypeFloat {
		t.Errorf("Type = %d, want TypeFloat", a.Type)
	}
}

// --- Bool arg ---

type BoolArgFlags struct {
	Force bool `arg:"force" help:"Force operation"`
}

func TestExtractFlags_BoolArg(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(BoolArgFlags{}))
	a := args[0]
	if a.Type != TypeBool {
		t.Errorf("Type = %d, want TypeBool", a.Type)
	}
}

// --- Default on int arg ---

type IntArgDefaultFlags struct {
	Count int `arg:"count" help:"Number" default:"5"`
}

func TestExtractFlags_IntArgDefault(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(IntArgDefaultFlags{}))
	a := args[0]
	if a.Required {
		t.Errorf("expected Required=false for arg with default")
	}
	if a.Default != 5 {
		t.Errorf("Default = %v, want 5", a.Default)
	}
}

// --- Default on pointer arg (panic) ---

type PointerArgDefaultFlags struct {
	Path *string `arg:"path" help:"File path" default:"foo"`
}

func TestExtractFlags_PointerArgDefault(t *testing.T) {
	assertPanics(t, "PointerArgDefault", "default tag is invalid on pointer types", func() {
		extractFlags(reflect.TypeOf(PointerArgDefaultFlags{}))
	})
}

// --- Variadic int args ---

type VariadicIntArgFlags struct {
	Nums []int `arg:"nums" help:"Numbers" variadic:"true"`
}

func TestExtractFlags_VariadicIntArg(t *testing.T) {
	_, args := extractFlags(reflect.TypeOf(VariadicIntArgFlags{}))
	a := args[0]
	if !a.IsVariadic {
		t.Errorf("expected IsVariadic=true")
	}
	if a.Type != TypeListInt {
		t.Errorf("Type = %d, want TypeListInt (%d)", a.Type, TypeListInt)
	}
}

// --- Invalid default values ---

type InvalidBoolDefaultFlags struct {
	Flag bool `cli:"flag" help:"A flag" default:"maybe"`
}

func TestExtractFlags_InvalidBoolDefault(t *testing.T) {
	assertPanics(t, "InvalidBoolDefault", "default tag for bool must be", func() {
		extractFlags(reflect.TypeOf(InvalidBoolDefaultFlags{}))
	})
}

type InvalidIntDefaultFlags struct {
	Count int `cli:"count" help:"Count" default:"abc"`
}

func TestExtractFlags_InvalidIntDefault(t *testing.T) {
	assertPanics(t, "InvalidIntDefault", "default tag for int is invalid", func() {
		extractFlags(reflect.TypeOf(InvalidIntDefaultFlags{}))
	})
}

type InvalidFloatDefaultFlags struct {
	Rate float64 `cli:"rate" help:"Rate" default:"xyz"`
}

func TestExtractFlags_InvalidFloatDefault(t *testing.T) {
	assertPanics(t, "InvalidFloatDefault", "default tag for float is invalid", func() {
		extractFlags(reflect.TypeOf(InvalidFloatDefaultFlags{}))
	})
}

// --- Short form empty string (not set via Lookup) ---

type ShortFormEmptyFlags struct {
	Verbose bool `cli:"verbose" help:"Verbose" short:""`
}

func TestExtractFlags_ShortFormEmpty(t *testing.T) {
	// Empty short tag means tag is present with empty value, which is 0 characters
	assertPanics(t, "ShortFormEmpty", "short tag must be exactly one character", func() {
		extractFlags(reflect.TypeOf(ShortFormEmptyFlags{}))
	})
}
