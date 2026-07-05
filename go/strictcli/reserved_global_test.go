package strictcli

import (
	"strings"
	"testing"
)

// TestGlobalFlagReservedNames verifies that App.GlobalFlag panics when
// registering a flag whose name collides with a reserved global name.
func TestGlobalFlagReservedNames(t *testing.T) {
	reserved := []string{"help", "version", "dump-schema", "mcp", "config"}
	for _, name := range reserved {
		t.Run(name, func(t *testing.T) {
			defer func() {
				r := recover()
				if r == nil {
					t.Fatalf("expected panic when registering global flag %q", name)
				}
				msg, ok := r.(string)
				if !ok {
					t.Fatalf("expected string panic, got %T: %v", r, r)
				}
				if !strings.Contains(msg, "reserved") {
					t.Fatalf("expected panic message to contain 'reserved', got %q", msg)
				}
			}()
			app := NewApp("testapp", "1.0.0", "test")
			app.GlobalFlag(StringFlag(name, "test flag"))
		})
	}
}

// TestGlobalFlagReservedShortNames verifies that short flag names "h" and "v"
// are rejected.
func TestGlobalFlagReservedShortNames(t *testing.T) {
	shorts := []struct {
		name  string
		short string
	}{
		{"foo", "h"},
		{"bar", "v"},
	}
	for _, tc := range shorts {
		t.Run(tc.short, func(t *testing.T) {
			defer func() {
				r := recover()
				if r == nil {
					t.Fatalf("expected panic for short flag %q", tc.short)
				}
				msg, ok := r.(string)
				if !ok {
					t.Fatalf("expected string panic, got %T: %v", r, r)
				}
				if !strings.Contains(msg, "reserved") {
					t.Fatalf("expected 'reserved' in panic, got %q", msg)
				}
			}()
			app := NewApp("testapp", "1.0.0", "test")
			app.GlobalFlag(StringFlag(tc.name, "test flag", Short(tc.short)))
		})
	}
}

// TestGlobalFlagNonReservedAllowed verifies that non-reserved names register
// without panic.
func TestGlobalFlagNonReservedAllowed(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test")
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output", Default(false)))
	app.GlobalFlag(StringFlag("output", "output file"))
	// No panic means success.
}

// TestRegisterGlobalsReservedName verifies that RegisterGlobals also rejects
// reserved names (existing behavior, regression test).
func TestRegisterGlobalsReservedName(t *testing.T) {
	type BadGlobals struct {
		Help string `cli:"help" help:"bad"`
	}
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for RegisterGlobals with reserved name 'help'")
		}
		msg, ok := r.(string)
		if !ok {
			t.Fatalf("expected string panic, got %T: %v", r, r)
		}
		if !strings.Contains(msg, "reserved") {
			t.Fatalf("expected 'reserved' in panic, got %q", msg)
		}
	}()
	app := NewApp("testapp", "1.0.0", "test")
	RegisterGlobals[BadGlobals](app)
}
