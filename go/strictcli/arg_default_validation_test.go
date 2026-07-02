package strictcli

import (
	"fmt"
	"strings"
	"testing"
)

// Registration-time validation of arg defaults: str args must reject
// non-string defaults, and list (variadic) args must validate their default
// as a list with correctly-typed elements.

func expectPanicContaining(t *testing.T, substr string, fn func()) {
	t.Helper()
	defer func() {
		r := recover()
		if r == nil {
			t.Fatalf("expected panic containing %q, got no panic", substr)
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, substr) {
			t.Fatalf("expected panic containing %q, got %q", substr, msg)
		}
	}()
	fn()
}

func TestArgStrDefaultTypeMismatchPanics(t *testing.T) {
	expectPanicContaining(t, "type=str requires a str default, got 'int'", func() {
		NewArg("name", "the name", ArgRequired(false), ArgDefault(42))
	})
}

func TestArgStrDefaultTypeMismatchBoolPanics(t *testing.T) {
	expectPanicContaining(t, "type=str requires a str default, got 'bool'", func() {
		NewArg("name", "the name", ArgRequired(false), ArgDefault(true))
	})
}

func TestArgListDefaultNotSlicePanics(t *testing.T) {
	expectPanicContaining(t, "list arg default must be a list", func() {
		NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(),
			ArgRequired(false), ArgDefault("nope"))
	})
}

func TestArgListDefaultEmptyPanics(t *testing.T) {
	expectPanicContaining(t, "explicit empty default is redundant for list args, omit the default", func() {
		NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(),
			ArgRequired(false), ArgDefault([]interface{}{}))
	})
}

func TestArgListDefaultElementTypeMismatchPanics(t *testing.T) {
	expectPanicContaining(t, "default element 1 is not of type str", func() {
		NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(),
			ArgRequired(false), ArgDefault([]interface{}{"a", 2}))
	})
}

func TestArgListDefaultIntElementTypeMismatchPanics(t *testing.T) {
	expectPanicContaining(t, "default element 0 is not of type int", func() {
		NewArg("nums", "the numbers", ArgType(ListOf(TypeInt)), Variadic(),
			ArgRequired(false), ArgDefault([]interface{}{"1"}))
	})
}

func TestArgListDefaultValidStr(t *testing.T) {
	a := NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(),
		ArgRequired(false), ArgDefault([]interface{}{"a", "b"}))
	if len(a.Default.([]interface{})) != 2 {
		t.Fatalf("expected default of 2 elements, got %v", a.Default)
	}
}

func TestArgListDefaultFloatCoercesInt(t *testing.T) {
	// Int elements in a float list default are coerced to float64,
	// mirroring list flag default handling.
	a := NewArg("ratios", "the ratios", ArgType(ListOf(TypeFloat)), Variadic(),
		ArgRequired(false), ArgDefault([]interface{}{1, 2.5}))
	slice := a.Default.([]interface{})
	if v, ok := slice[0].(float64); !ok || v != 1.0 {
		t.Fatalf("expected element 0 coerced to float64(1.0), got %T(%v)", slice[0], slice[0])
	}
}
