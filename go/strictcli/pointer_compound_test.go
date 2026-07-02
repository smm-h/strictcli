package strictcli

import (
	"testing"
)

// Pointer-to-slice and pointer-to-map handler fields used to register fine and
// then panic at dispatch (bind) time on every invocation. They are now a
// registration-time hard error: optional-with-nil semantics are unimplementable
// for repeatable flags (missing repeatable flags always resolve to an empty
// list/map, never nil).

type PointerSliceFlagHandler struct {
	Tags *[]string `cli:"tags" help:"Tags"`
}

func (h *PointerSliceFlagHandler) Run(ctx *Context) int { return 0 }

func TestPointerSliceFlag_RegistrationPanics(t *testing.T) {
	assertPanics(t, "PointerSliceFlag", "pointer-to-slice and pointer-to-map field types are unsupported", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &PointerSliceFlagHandler{}
		})
	})
}

type PointerMapFlagHandler struct {
	Labels *map[string]string `cli:"labels" help:"Labels"`
}

func (h *PointerMapFlagHandler) Run(ctx *Context) int { return 0 }

func TestPointerMapFlag_RegistrationPanics(t *testing.T) {
	assertPanics(t, "PointerMapFlag", "pointer-to-slice and pointer-to-map field types are unsupported", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &PointerMapFlagHandler{}
		})
	})
}

func TestPointerSliceFlag_MessagePointsToAlternatives(t *testing.T) {
	assertPanics(t, "PointerSliceFlagMessage", `required:"false"`, func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &PointerSliceFlagHandler{}
		})
	})
}

type PointerSliceArgHandler struct {
	Files *[]string `arg:"files" help:"Files" variadic:"true"`
}

func (h *PointerSliceArgHandler) Run(ctx *Context) int { return 0 }

func TestPointerSliceArg_RegistrationPanics(t *testing.T) {
	assertPanics(t, "PointerSliceArg", "pointer-to-slice and pointer-to-map field types are unsupported", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &PointerSliceArgHandler{}
		})
	})
}

type PointerMapArgHandler struct {
	Labels *map[string]string `arg:"labels" help:"Labels"`
}

func (h *PointerMapArgHandler) Run(ctx *Context) int { return 0 }

func TestPointerMapArg_RegistrationPanics(t *testing.T) {
	// Maps were already banned on positional args; the pointer wrapper must
	// not change that.
	assertPanics(t, "PointerMapArg", "map types are not supported for positional arguments", func() {
		app := NewApp("myapp", "1.0.0", "test app")
		app.RegisterHandler("cmd", "a command", func() Handler {
			return &PointerMapArgHandler{}
		})
	})
}
