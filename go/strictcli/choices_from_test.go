package strictcli

import (
	"reflect"
	"strings"
	"testing"
)

// --- choices_from: happy path (flag) ---

type ChoicesFromHandler struct {
	Format string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h *ChoicesFromHandler) FormatChoices() []string {
	return []string{"text", "json"}
}

func (h *ChoicesFromHandler) Run(ctx *Context) int {
	ctx.Info("format=" + h.Format)
	return 0
}

func newChoicesFromApp() *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "a command", func() Handler {
		return &ChoicesFromHandler{}
	})
	return app
}

func TestChoicesFrom_ValidValue(t *testing.T) {
	r := newChoicesFromApp().Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "format=json") {
		t.Fatalf("expected 'format=json', got %q", r.Stdout)
	}
}

func TestChoicesFrom_InvalidValueRejected(t *testing.T) {
	r := newChoicesFromApp().Test([]string{"cmd", "--format", "xml"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--format: invalid value 'xml', must be one of: text, json") {
		t.Fatalf("expected choices error, got %q", r.Stderr)
	}
}

func TestChoicesFrom_ListedInHelp(t *testing.T) {
	r := newChoicesFromApp().Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "choices: text, json") {
		t.Fatalf("expected help to list choices, got %q", r.Stdout)
	}
}

func TestChoicesFrom_ConcreteChoicesOnFlag(t *testing.T) {
	// The resolved Flag carries a concrete Choices list -- this is what schema
	// dump and MCP enum generation read.
	flags, _ := extractFlags(reflect.TypeOf(ChoicesFromHandler{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	want := []interface{}{"text", "json"}
	if !reflect.DeepEqual(flags[0].Choices, want) {
		t.Fatalf("Choices = %v, want %v", flags[0].Choices, want)
	}
}

// --- choices_from: value receiver method ---

type ChoicesFromValueRecvHandler struct {
	Format string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h ChoicesFromValueRecvHandler) FormatChoices() []string {
	return []string{"a", "b"}
}

func (h *ChoicesFromValueRecvHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_ValueReceiverMethod(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ChoicesFromValueRecvHandler{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	want := []interface{}{"a", "b"}
	if !reflect.DeepEqual(flags[0].Choices, want) {
		t.Fatalf("Choices = %v, want %v", flags[0].Choices, want)
	}
}

// --- choices_from: int flag (strings parsed like the choices tag) ---

type ChoicesFromIntHandler struct {
	Level int `cli:"level" help:"Level" choices_from:"LevelChoices"`
}

func (h *ChoicesFromIntHandler) LevelChoices() []string {
	return []string{"1", "2", "3"}
}

func (h *ChoicesFromIntHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_IntFlag(t *testing.T) {
	flags, _ := extractFlags(reflect.TypeOf(ChoicesFromIntHandler{}))
	if len(flags) != 1 {
		t.Fatalf("expected 1 flag, got %d", len(flags))
	}
	want := []interface{}{1, 2, 3}
	if !reflect.DeepEqual(flags[0].Choices, want) {
		t.Fatalf("Choices = %v, want %v", flags[0].Choices, want)
	}
}

type ChoicesFromBadIntHandler struct {
	Level int `cli:"level" help:"Level" choices_from:"LevelChoices"`
}

func (h *ChoicesFromBadIntHandler) LevelChoices() []string {
	return []string{"one", "two"}
}

func (h *ChoicesFromBadIntHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_IntFlagBadValuePanics(t *testing.T) {
	assertPanics(t, "IntFlagBadValue", "not a valid int", func() {
		extractFlags(reflect.TypeOf(ChoicesFromBadIntHandler{}))
	})
}

// --- choices_from: bool flag (choices don't apply, mirrors choices tag rules) ---

type ChoicesFromBoolHandler struct {
	Flagged bool `cli:"flagged" help:"Flagged" choices_from:"FlaggedChoices"`
}

func (h *ChoicesFromBoolHandler) FlaggedChoices() []string {
	return []string{"true", "false"}
}

func (h *ChoicesFromBoolHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_BoolFlagPanics(t *testing.T) {
	assertPanics(t, "BoolFlag", "choices not supported", func() {
		extractFlags(reflect.TypeOf(ChoicesFromBoolHandler{}))
	})
}

// --- choices_from: method missing ---

type ChoicesFromMissingMethodHandler struct {
	Format string `cli:"format" help:"Output format" choices_from:"NoSuchMethod"`
}

func (h *ChoicesFromMissingMethodHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_MethodMissingPanics(t *testing.T) {
	assertPanics(t, "MethodMissing", `choices_from method "NoSuchMethod" not found`, func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromMissingMethodHandler{}
		})
	})
}

// --- choices_from: wrong signature ---

type ChoicesFromWrongSigArgsHandler struct {
	Format string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h *ChoicesFromWrongSigArgsHandler) FormatChoices(prefix string) []string {
	return []string{prefix}
}

func (h *ChoicesFromWrongSigArgsHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_WrongSignatureArgsPanics(t *testing.T) {
	assertPanics(t, "WrongSigArgs", "must have signature func() []string", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromWrongSigArgsHandler{}
		})
	})
}

type ChoicesFromWrongSigReturnHandler struct {
	Format string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h *ChoicesFromWrongSigReturnHandler) FormatChoices() []int {
	return []int{1, 2}
}

func (h *ChoicesFromWrongSigReturnHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_WrongSignatureReturnPanics(t *testing.T) {
	assertPanics(t, "WrongSigReturn", "must have signature func() []string", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromWrongSigReturnHandler{}
		})
	})
}

// --- choices_from combined with choices ---

type ChoicesFromBothTagsHandler struct {
	Format string `cli:"format" help:"Output format" choices:"text,json" choices_from:"FormatChoices"`
}

func (h *ChoicesFromBothTagsHandler) FormatChoices() []string {
	return []string{"text", "json"}
}

func (h *ChoicesFromBothTagsHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_BothTagsPanics(t *testing.T) {
	assertPanics(t, "BothTags", "cannot have both choices and choices_from tags", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromBothTagsHandler{}
		})
	})
}

// --- choices_from: empty result ---

type ChoicesFromEmptyHandler struct {
	Format string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h *ChoicesFromEmptyHandler) FormatChoices() []string {
	return nil
}

func (h *ChoicesFromEmptyHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_EmptyResultPanics(t *testing.T) {
	assertPanics(t, "EmptyResult", "returned an empty list", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromEmptyHandler{}
		})
	})
}

// --- choices_from: pointer field (optional flag, nil exemption) ---

type ChoicesFromPointerHandler struct {
	Format *string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h *ChoicesFromPointerHandler) FormatChoices() []string {
	return []string{"text", "json"}
}

func (h *ChoicesFromPointerHandler) Run(ctx *Context) int {
	if h.Format == nil {
		ctx.Info("format=nil")
	} else {
		ctx.Info("format=" + *h.Format)
	}
	return 0
}

func newChoicesFromPointerApp() *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "a command", func() Handler {
		return &ChoicesFromPointerHandler{}
	})
	return app
}

func TestChoicesFrom_PointerFieldNotPassed(t *testing.T) {
	// Optional flag not passed: resolved value nil, choices must not fire.
	r := newChoicesFromPointerApp().Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "format=nil") {
		t.Fatalf("expected 'format=nil', got %q", r.Stdout)
	}
}

func TestChoicesFrom_PointerFieldPassedInvalid(t *testing.T) {
	r := newChoicesFromPointerApp().Test([]string{"cmd", "--format", "xml"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--format: invalid value 'xml', must be one of: text, json") {
		t.Fatalf("expected choices error, got %q", r.Stderr)
	}
}

// --- choices_from on args ---

type ChoicesFromArgHandler struct {
	Env string `arg:"env" help:"Target env" choices_from:"EnvChoices"`
}

func (h *ChoicesFromArgHandler) EnvChoices() []string {
	return []string{"dev", "staging", "prod"}
}

func (h *ChoicesFromArgHandler) Run(ctx *Context) int {
	ctx.Info("env=" + h.Env)
	return 0
}

func newChoicesFromArgApp() *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "a command", func() Handler {
		return &ChoicesFromArgHandler{}
	})
	return app
}

func TestChoicesFrom_ArgValidValue(t *testing.T) {
	r := newChoicesFromArgApp().Test([]string{"cmd", "prod"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "env=prod") {
		t.Fatalf("expected 'env=prod', got %q", r.Stdout)
	}
}

func TestChoicesFrom_ArgInvalidValueRejected(t *testing.T) {
	r := newChoicesFromArgApp().Test([]string{"cmd", "local"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "argument 'env': invalid value 'local', must be one of: dev, staging, prod") {
		t.Fatalf("expected choices error, got %q", r.Stderr)
	}
}

// --- choices_from on variadic args: banned, same panic as the choices tag ---

type ChoicesFromVariadicArgHandler struct {
	Envs []string `arg:"envs" help:"Target envs" variadic:"true" choices_from:"EnvChoices"`
}

func (h *ChoicesFromVariadicArgHandler) EnvChoices() []string {
	return []string{"dev", "staging", "prod"}
}

func (h *ChoicesFromVariadicArgHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_VariadicArgPanics(t *testing.T) {
	assertPanics(t, "VariadicArg", "choices is incompatible with list type", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromVariadicArgHandler{}
		})
	})
}

// --- choices_from: slice flag (choices don't apply to compound types) ---

type ChoicesFromSliceFlagHandler struct {
	Tags []string `cli:"tags" help:"Tags" choices_from:"TagChoices"`
}

func (h *ChoicesFromSliceFlagHandler) TagChoices() []string {
	return []string{"a", "b"}
}

func (h *ChoicesFromSliceFlagHandler) Run(ctx *Context) int { return 0 }

func TestChoicesFrom_SliceFlagPanics(t *testing.T) {
	assertPanics(t, "SliceFlag", "choices is incompatible with compound types", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &ChoicesFromSliceFlagHandler{}
		})
	})
}

// --- choices_from: method reads factory-injected state ---

type ChoicesFromInjectedHandler struct {
	allowed []string
	Format  string `cli:"format" help:"Output format" choices_from:"FormatChoices"`
}

func (h *ChoicesFromInjectedHandler) FormatChoices() []string {
	return h.allowed
}

func (h *ChoicesFromInjectedHandler) Run(ctx *Context) int {
	ctx.Info("format=" + h.Format)
	return 0
}

func TestChoicesFrom_MethodSeesFactoryState(t *testing.T) {
	// The registration-time invocation uses the factory-built instance, so
	// injected dependencies are visible to the choices method.
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "a command", func() Handler {
		return &ChoicesFromInjectedHandler{allowed: []string{"yaml", "toml"}}
	})
	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stderr, "must be one of: yaml, toml") {
		t.Fatalf("expected injected choices in error, got %q", r.Stderr)
	}
	r = app.Test([]string{"cmd", "--format", "toml"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
}
