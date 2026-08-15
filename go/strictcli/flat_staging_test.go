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

// --- The value stage is ONE declaration-ordered sweep (contract §24.3, §24.11) ---
//
// A flat object and an elected record have no order of their own, so the order
// the caller happened to write their keys in decides nothing, and neither does
// the order the implementation happens to walk its own structures in. The value
// stage is one sweep over the command's DECLARATIONS, at every depth: the
// command's own flags and the values inside each elected scope interleave
// exactly where the declarations sit, and a nested selector's values sit where
// the nested selector is declared. Reading every scope first would let a value
// problem one level down outrank one on a flag declared above the selector.
//
// The command line's own order is the order of TYPING, so an argv written in
// declaration order is the baseline these doors reproduce.

// sweepOrderApp declares a root flag BEFORE its selector, a second root flag
// AFTER it, and -- inside the elected scope -- a nested selector between two
// scoped flags, so both the root/scope race and the depth race have an answer
// the declarations decide.
func sweepOrderApp(captured *map[string]interface{}) *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(IntFlag("timeout", "seconds to wait", Default(30)))
	app.Command("run", "run it", captureHandler(captured),
		WithFlags(
			IntFlag("count", "how many", Optional()),
			ChoiceFlag("via", "delivery channel", Required(),
				Choice("email", "an email message",
					IntFlag("retries", "how many", Required()),
					ChoiceFlag("format", "the body format", Default("plain"),
						Choice("plain", "plain text"),
						Choice("rich", "rich text", IntFlag("width", "columns", Required())),
					),
					IntFlag("delay", "seconds between tries", Optional()),
				),
				Choice("sms", "a text message", StringFlag("phone-number", "destination", Required())),
			),
			IntFlag("zcount", "how many more", Optional()),
		), WithEffect(EffectReadOnly))
	return app
}

// sweptRefusal asserts one flat call, its record-door twin and their argv twin
// all refuse over the SAME declaration. build supplies the record door's
// kwargs, which cannot be written without the app the choices belong to; argv
// is written in declaration order, which is the order of typing that reproduces
// a declaration-ordered sweep. The two doors name the value's TYPE where the
// command line names the token it read, so the argv baseline carries its own
// sentence.
func sweptRefusal(t *testing.T, kwargs map[string]interface{}, build func(app *App) map[string]interface{}, argv []string, want string, wantCLI string) {
	t.Helper()
	var captured map[string]interface{}
	if ir := sweepOrderApp(&captured).invoke("run", kwargs); ir.err != want {
		t.Fatalf("flat error = %q, want %q", ir.err, want)
	}
	app := sweepOrderApp(&captured)
	if ir := app.invoke("run", build(app)); ir.err != want {
		t.Fatalf("record error = %q, want %q", ir.err, want)
	}
	r := sweepOrderApp(&captured).Test(argv)
	if !strings.Contains(r.Stderr, "error: "+wantCLI+"\n") {
		t.Fatalf("cli stderr = %q, want it to contain %q", r.Stderr, wantCLI)
	}
}

// sweepChoice finds one choice of one selector on sweepOrderApp's command.
func sweepChoice(app *App, selName, chName string) *ChoiceDecl {
	cmd := app.commands["run"]
	for i := range cmd.flags {
		if cmd.flags[i].Name == selName {
			return findChoice(&cmd.flags[i], chName)
		}
	}
	panic("no selector " + selName)
}

// nestedChoice finds one choice of a selector declared INSIDE another choice's
// scope.
func nestedChoice(outer *ChoiceDecl, selName, chName string) *ChoiceDecl {
	for i := range outer.Flags {
		if outer.Flags[i].Name == selName {
			return findChoice(&outer.Flags[i], chName)
		}
	}
	panic("no nested selector " + selName)
}

// A root flag declared BEFORE the selector reports its value problem first: the
// sweep reaches the declaration that comes first, and a scope is not a place
// the sweep visits early.
func TestValueSweepRootFlagDeclaredBeforeASelector(t *testing.T) {
	sweptRefusal(t,
		map[string]interface{}{"count": "nope", "via": "email", "retries": "nope"},
		func(app *App) map[string]interface{} {
			return map[string]interface{}{
				"count": "nope",
				"via":   Elect(sweepChoice(app, "via", "email"), Fields{"retries": "nope"}),
			}
		},
		[]string{"run", "--count", "nope", "--via", "email", "--retries", "nope"},
		"--count: expected integer, got str",
		"--count: expected integer, got 'nope'")
}

// And a root flag declared AFTER the selector loses to a value inside it, for
// the same reason read the other way.
func TestValueSweepRootFlagDeclaredAfterASelector(t *testing.T) {
	sweptRefusal(t,
		map[string]interface{}{"count": 1, "via": "email", "retries": "nope", "zcount": "nope"},
		func(app *App) map[string]interface{} {
			return map[string]interface{}{
				"count":  1,
				"zcount": "nope",
				"via":    Elect(sweepChoice(app, "via", "email"), Fields{"retries": "nope"}),
			}
		},
		[]string{"run", "--count", "1", "--via", "email", "--retries", "nope", "--zcount", "nope"},
		"--retries: expected integer, got str",
		"--retries: expected integer, got 'nope'")
}

// The sweep is declaration-ordered at EVERY depth: a nested selector's values
// sit where the nested selector is declared, so they precede a scoped flag
// declared after it.
func TestValueSweepNestedSelectorDeclaredBeforeAScopedFlag(t *testing.T) {
	sweptRefusal(t,
		map[string]interface{}{
			"via": "email", "retries": 1, "format": "rich", "width": "nope", "delay": "nope",
		},
		func(app *App) map[string]interface{} {
			return map[string]interface{}{
				"via": Elect(sweepChoice(app, "via", "email"), Fields{
					"retries": 1,
					"format":  Elect(nestedChoice(sweepChoice(app, "via", "email"), "format", "rich"), Fields{"width": "nope"}),
					"delay":   "nope",
				}),
			}
		},
		[]string{
			"run", "--via", "email", "--retries", "1",
			"--format", "rich", "--width", "nope", "--delay", "nope",
		},
		"--width: expected integer, got str",
		"--width: expected integer, got 'nope'")
}

// A root flag declared before the selector still wins over a value nested two
// scopes down.
func TestValueSweepRootFlagBeatsANestedScopedValue(t *testing.T) {
	sweptRefusal(t,
		map[string]interface{}{
			"count": "nope", "via": "email", "retries": 1, "format": "rich", "width": "nope",
		},
		func(app *App) map[string]interface{} {
			return map[string]interface{}{
				"count": "nope",
				"via": Elect(sweepChoice(app, "via", "email"), Fields{
					"retries": 1,
					"format":  Elect(nestedChoice(sweepChoice(app, "via", "email"), "format", "rich"), Fields{"width": "nope"}),
				}),
			}
		},
		[]string{
			"run", "--count", "nope", "--via", "email", "--retries", "1",
			"--format", "rich", "--width", "nope",
		},
		"--count: expected integer, got str",
		"--count: expected integer, got 'nope'")
}

// An app-level global is swept after the command's own declarations, so a value
// problem on one loses to every declaration the command itself makes.
func TestValueSweepGlobalIsSweptAfterTheCommandsOwnDeclarations(t *testing.T) {
	var captured map[string]interface{}
	ir := sweepOrderApp(&captured).invoke("run", map[string]interface{}{
		"timeout": "nope", "via": "email", "retries": "nope",
	})
	if ir.err != "--retries: expected integer, got str" {
		t.Fatalf("flat error = %q, want the scoped value refusal", ir.err)
	}
	ir = sweepOrderApp(&captured).invoke("run", map[string]interface{}{
		"timeout": "nope", "via": "email", "retries": 1,
	})
	if ir.err != "--timeout: expected integer, got str" {
		t.Fatalf("flat error = %q, want the global's own value refusal", ir.err)
	}
}
