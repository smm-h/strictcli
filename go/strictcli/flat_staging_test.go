package strictcli

import (
	"strings"
	"testing"
)

// --- Cross-selector staging at the flat boundary (contract §24.3, §24.11) ---
//
// The phase order is a property of the PARSER, not of one selector: the flat
// boundary resolves every selector's election before it reports any scope,
// value or presence problem, exactly as the argv path does. A command line
// whose first selector is unsatisfied and whose second is elected twice
// therefore says the same thing at both front doors, and it says the election's
// sentence.

// flatTwoSelectorApp declares a token-spelled selector FIRST and a
// member-spelled one second, so a problem on the first would win any
// declaration-order race that survived the phase order.
func flatTwoSelectorApp(captured *map[string]interface{}) *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(captured),
		WithFlags(
			DictFlag(TypeStr, "label", "extra labels", Unique(false), Optional()),
			ChoiceFlag("via", "delivery channel", Required(),
				Choice("email", "an email message",
					IntFlag("retries", "how many", Required()),
					StringFlag("format", "the body format", Default("json"),
						Choices(Ch("json", "JSON"), Ch("yaml", "YAML"))),
					DictFlag(TypeStr, "header", "extra headers", Unique(false), Optional()),
				),
				Choice("sms", "a text message", StringFlag("phone-number", "destination", Required())),
			),
			MemberChoiceFlag("target", "which profiles", Required(),
				MemberChoice(StringFlag("profile", "a profile", Required()), "one named profile"),
				MemberChoice(BoolFlag("all-profiles", "every profile", Required()), "every profile"),
			),
		), WithEffect(EffectReadOnly))
	return app
}

// stagedRefusal asserts that one flat call and its argv twin both refuse with
// want, so the staging claim is about the parser rather than about one door.
func stagedRefusal(t *testing.T, kwargs map[string]interface{}, argv []string, want string) {
	t.Helper()
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", kwargs)
	if ir.err != want {
		t.Fatalf("flat error = %q, want %q", ir.err, want)
	}
	r := flatTwoSelectorApp(&captured).Test(argv)
	if r.ExitCode != 1 {
		t.Fatalf("cli exit = %d, want 1", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "error: "+want+"\n") {
		t.Fatalf("cli stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

// The first selector is required and elected nothing; the second is elected
// twice. Election runs for the WHOLE command before presence runs for any of
// it, so the double election is the sentence.
func TestFlatStagingDoubleElectionBeatsAnUnsatisfiedRequiredSelector(t *testing.T) {
	var captured map[string]interface{}
	// The unsatisfied selector is a real refusal on its own.
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{"profile": "work"})
	if ir.err != "flag '--via' is required" {
		t.Fatalf("isolated error = %q, want the required-selector refusal", ir.err)
	}
	stagedRefusal(t,
		map[string]interface{}{"target": "all-profiles", "profile": "work"},
		[]string{"run", "--all-profiles", "--profile", "work"},
		flatDoubleElection)
}

// A scope violation caused by the first selector's absent election loses to the
// second selector's double election: election precedes scope (§24.3).
func TestFlatStagingDoubleElectionBeatsAScopeViolation(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"retries": 3, "profile": "work",
	})
	want := "flag '--retries' is only valid under '--via email', but '--via' was not provided"
	if ir.err != want {
		t.Fatalf("isolated error = %q, want %q", ir.err, want)
	}
	stagedRefusal(t,
		map[string]interface{}{"retries": 3, "target": "all-profiles", "profile": "work"},
		[]string{"run", "--retries", "3", "--all-profiles", "--profile", "work"},
		flatDoubleElection)
}

// A value refusal inside the first selector's ELECTED scope loses too:
// election precedes value.
func TestFlatStagingDoubleElectionBeatsAValueRefusal(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "retries": 3, "format": "xml", "profile": "work",
	})
	want := "--format: invalid value 'xml', must be one of: json, yaml"
	if ir.err != want {
		t.Fatalf("isolated error = %q, want %q", ir.err, want)
	}
	stagedRefusal(t,
		map[string]interface{}{
			"via": "email", "retries": 3, "format": "xml",
			"target": "all-profiles", "profile": "work",
		},
		[]string{
			"run", "--via", "email", "--retries", "3", "--format", "xml",
			"--all-profiles", "--profile", "work",
		},
		flatDoubleElection)
}

// The values an elected scope was given are collected during the walk and
// coerced only once every election is settled, so a scoped value the caller
// typed wrong cannot outrank a later selector's double election.
func TestFlatStagingDoubleElectionBeatsAScopedValueTypeRefusal(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "retries": 3, "header": "not-a-map", "profile": "work",
	})
	want := `dict flag "header": expected map type, got string`
	if ir.err != want {
		t.Fatalf("isolated error = %q, want %q", ir.err, want)
	}
	ir = flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "retries": 3, "header": "not-a-map",
		"target": "all-profiles", "profile": "work",
	})
	if ir.err != flatDoubleElection {
		t.Fatalf("error = %q, want %q", ir.err, flatDoubleElection)
	}
}

// The same for a value supplied to one of the command's OWN flags: the whole
// value phase sits behind the whole election phase.
func TestFlatStagingDoubleElectionBeatsARootValueTypeRefusal(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "retries": 3, "label": "not-a-map", "profile": "work",
	})
	want := `dict flag "label": expected map type, got string`
	if ir.err != want {
		t.Fatalf("isolated error = %q, want %q", ir.err, want)
	}
	ir = flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "retries": 3, "label": "not-a-map",
		"target": "all-profiles", "profile": "work",
	})
	if ir.err != flatDoubleElection {
		t.Fatalf("error = %q, want %q", ir.err, flatDoubleElection)
	}
}

// A missing required flag inside the first selector's elected scope loses:
// election precedes presence.
func TestFlatStagingDoubleElectionBeatsAMissingRequiredScopedFlag(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "profile": "work",
	})
	if ir.err != "flag '--retries' is required under '--via email'" {
		t.Fatalf("isolated error = %q, want the scoped presence refusal", ir.err)
	}
	stagedRefusal(t,
		map[string]interface{}{"via": "email", "target": "all-profiles", "profile": "work"},
		[]string{"run", "--via", "email", "--all-profiles", "--profile", "work"},
		flatDoubleElection)
}
