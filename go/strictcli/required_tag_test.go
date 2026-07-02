package strictcli

import (
	"strings"
	"testing"
)

// --- required:"false" on a variadic slice arg: zero positionals allowed ---

type OptionalVariadicHandler struct {
	Files []string `arg:"files" help:"Files to process" variadic:"true" required:"false"`
}

func (h *OptionalVariadicHandler) Run(ctx *Context) int {
	if h.Files == nil {
		ctx.Info("files=<nil>")
		return 0
	}
	ctx.Info("files=[" + strings.Join(h.Files, ",") + "]")
	return 0
}

func newOptionalVariadicApp() *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "a command", func() Handler {
		return &OptionalVariadicHandler{}
	})
	return app
}

func TestRequiredFalse_ZeroArgsEmptySlice(t *testing.T) {
	r := newOptionalVariadicApp().Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "files=[]") {
		t.Fatalf("expected empty (non-nil) slice, got %q", r.Stdout)
	}
}

func TestRequiredFalse_ArgsProvidedBound(t *testing.T) {
	r := newOptionalVariadicApp().Test([]string{"cmd", "a.txt", "b.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "files=[a.txt,b.txt]") {
		t.Fatalf("expected bound slice, got %q", r.Stdout)
	}
}

// --- misuse panics ---

type RequiredOnFlagHandler struct {
	Name string `cli:"name" help:"Name" required:"false"`
}

func (h *RequiredOnFlagHandler) Run(ctx *Context) int { return 0 }

func TestRequiredTag_OnFlagPanics(t *testing.T) {
	assertPanics(t, "RequiredOnFlag", "required tag is only valid on variadic slice args", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &RequiredOnFlagHandler{}
		})
	})
}

type RequiredOnScalarArgHandler struct {
	Env string `arg:"env" help:"Target env" required:"false"`
}

func (h *RequiredOnScalarArgHandler) Run(ctx *Context) int { return 0 }

func TestRequiredTag_OnNonVariadicArgPanics(t *testing.T) {
	assertPanics(t, "RequiredOnScalarArg", "required tag is only valid on variadic slice args", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &RequiredOnScalarArgHandler{}
		})
	})
}

type RequiredTrueVariadicHandler struct {
	Files []string `arg:"files" help:"Files" variadic:"true" required:"true"`
}

func (h *RequiredTrueVariadicHandler) Run(ctx *Context) int { return 0 }

func TestRequiredTag_TrueValuePanics(t *testing.T) {
	assertPanics(t, "RequiredTrue", `only required:"false" on a variadic slice arg is meaningful`, func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &RequiredTrueVariadicHandler{}
		})
	})
}

type RequiredBogusHandler struct {
	Files []string `arg:"files" help:"Files" variadic:"true" required:"maybe"`
}

func (h *RequiredBogusHandler) Run(ctx *Context) int { return 0 }

func TestRequiredTag_BogusValuePanics(t *testing.T) {
	assertPanics(t, "RequiredBogus", `required tag must be "true" or "false"`, func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &RequiredBogusHandler{}
		})
	})
}

// --- variadic without required:"false" stays required ---

type RequiredVariadicHandler struct {
	Files []string `arg:"files" help:"Files" variadic:"true"`
}

func (h *RequiredVariadicHandler) Run(ctx *Context) int { return 0 }

func TestVariadicWithoutRequiredFalse_StillRequired(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.RegisterHandler("cmd", "a command", func() Handler {
		return &RequiredVariadicHandler{}
	})
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "missing required argument 'files'") {
		t.Fatalf("expected missing-argument error, got %q", r.Stderr)
	}
}
