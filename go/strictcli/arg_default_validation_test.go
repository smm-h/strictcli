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
		NewArg("name", "the name", ArgDefault(42))
	})
}

func TestArgStrDefaultTypeMismatchBoolPanics(t *testing.T) {
	expectPanicContaining(t, "type=str requires a str default, got 'bool'", func() {
		NewArg("name", "the name", ArgDefault(true))
	})
}

// A variadic arg always delivers a list, so a default on one has nothing to
// mean: the declaration is refused at registration (contract §23.3, §12.12).
// A list-typed arg must be variadic, so this refusal covers every list default
// an arg could once carry.

func TestArgVariadicDefaultPanics(t *testing.T) {
	expectPanicContaining(t, `Arg "items": a variadic arg cannot declare ArgDefault(): it always delivers a list, so declare ArgRequired() for at least one value or ArgOptional() for possibly none`, func() {
		NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(),
			ArgDefault([]interface{}{"a", "b"}))
	})
}

func TestArgVariadicEmptyDefaultPanics(t *testing.T) {
	expectPanicContaining(t, "a variadic arg cannot declare ArgDefault()", func() {
		NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(),
			ArgDefault([]interface{}{}))
	})
}

func TestArgVariadicScalarDefaultPanics(t *testing.T) {
	// The refusal is about the SPELLING being inapplicable, so it does not
	// depend on the default's shape.
	expectPanicContaining(t, "a variadic arg cannot declare ArgDefault()", func() {
		NewArg("items", "the items", Variadic(), ArgDefault("nope"))
	})
}

func TestArgVariadicPresenceDeclarations(t *testing.T) {
	// The two legal declarations for a variadic arg.
	if a := (NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(), ArgRequired())); a.presence != presenceRequired {
		t.Fatalf("expected required presence, got %v", a.presence)
	}
	if a := (NewArg("items", "the items", ArgType(ListOf(TypeStr)), Variadic(), ArgOptional())); a.presence != presenceOptional {
		t.Fatalf("expected optional presence, got %v", a.presence)
	}
}
