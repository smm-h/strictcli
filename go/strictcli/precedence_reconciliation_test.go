package strictcli

import (
	"strings"
	"testing"
)

// The corrections and spellings the three scoped-selector implementations
// forced (effects contract §18.19, items 213-224). Each test names the item it
// pins; the sentences and rendered forms are the contract's, not Go's.

// --- Item 222: the description map renders choice names AS DECLARED ---

func TestMCPDescriptionRendersChoiceNamesAsDeclared(t *testing.T) {
	app := simpleApp("add", "add an entry", "ok",
		WithFlags(ChoiceFlag("visibility", "who the entry is for", Required(),
			Choice("user-facing", "shown to users",
				StringFlag("headline", "the headline", Required())),
			Choice("internal", "not shown to users"),
		)))
	var tool *Tool
	tools := app.AsTools()
	for i := range tools {
		if tools[i].Name == "add" {
			tool = &tools[i]
		}
	}
	if tool == nil {
		t.Fatal("no 'add' tool")
	}
	if !strings.Contains(tool.Description, "visibility=user-facing: headline (required)") {
		t.Fatalf("the choice name was not rendered as declared:\n%s", tool.Description)
	}
	if strings.Contains(tool.Description, "user_facing") {
		t.Fatalf("a choice name was underscored:\n%s", tool.Description)
	}
}

// --- Item 224: a structural problem is reported ahead of a value problem ---

// The phase order is a property of the PARSER, not of the declaration: it holds
// on a command that declares no selector at all.
func TestStructuralProblemBeatsCoercionOnASelectorFreeCommand(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(IntFlag("count", "how many", Optional())))
	r := app.Test([]string{"cmd", "--count", "abc", "--unknown"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "error: unknown flag '--unknown'\n") {
		t.Fatalf("stderr = %q, want the unknown-flag error", r.Stderr)
	}
	if strings.Contains(r.Stderr, "expected integer") {
		t.Fatalf("the value error beat the structural one: %q", r.Stderr)
	}
}

// The answer does not depend on which token came first.
func TestStructuralProblemBeatsCoercionWhateverTheArgvOrder(t *testing.T) {
	a := simpleApp("cmd", "a command", "ok",
		WithFlags(IntFlag("count", "how many", Optional()))).
		Test([]string{"cmd", "--unknown", "--count", "abc"})
	b := simpleApp("cmd", "a command", "ok",
		WithFlags(IntFlag("count", "how many", Optional()))).
		Test([]string{"cmd", "--count", "abc", "--unknown"})
	if a.Stderr != b.Stderr {
		t.Fatalf("argv order changed the refusal: %q vs %q", a.Stderr, b.Stderr)
	}
}

// An election and a scope violation are structural too, and both are decided
// before any token's text is interpreted -- including a ROOT-scope value that
// will not coerce, which is the full reading of the phase order.
func precedenceApp() *App {
	return simpleApp("send", "send it", "ok",
		WithFlags(
			IntFlag("count", "how many", Optional()),
			ChoiceFlag("via", "delivery channel", Required(),
				Choice("email", "by email", StringFlag("subject", "the subject", Required())),
				Choice("sms", "by text", IntFlag("retries", "how many retries", Optional())),
			)))
}

func TestScopeValidationBeatsRootValueCoercion(t *testing.T) {
	r := precedenceApp().Test([]string{"send", "--count", "abc", "--via", "sms", "--subject", "hi"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	want := "error: flag '--subject' is only valid under '--via email', but '--via sms' was elected\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want %q", r.Stderr, want)
	}
}

func TestAnUnknownChoiceBeatsRootValueCoercion(t *testing.T) {
	r := precedenceApp().Test([]string{"send", "--count", "abc", "--via", "carrier-pigeon"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--via: invalid value 'carrier-pigeon'") {
		t.Fatalf("stderr = %q, want the unknown-choice refusal", r.Stderr)
	}
	if strings.Contains(r.Stderr, "expected integer") {
		t.Fatalf("the value error beat the election: %q", r.Stderr)
	}
}

func TestScopeValidationBeatsScopedValueCoercion(t *testing.T) {
	r := precedenceApp().Test([]string{"send", "--via", "sms", "--retries", "abc", "--subject", "hi"})
	want := "error: flag '--subject' is only valid under '--via email', but '--via sms' was elected\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want %q", r.Stderr, want)
	}
}
