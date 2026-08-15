package strictcli

import (
	"fmt"
	"os"
	"testing"
)

// The RECORD door's own reading of an explicit nil (contract §24.11, §18.26
// item 252).
//
// A record has no way to omit a key the way a flat object does -- a scope class
// cannot be constructed without naming every field -- so an explicit nil on an
// OPTIONAL scoped field IS that omission: it is legal, and it delivers absence,
// exactly as the omitted key does. The carve-out is this door's alone and stops
// at optionality: a required or defaulted field still refuses a nil, and at the
// flat door, where absence has its own spelling, a nil stays legal for nothing.

const recordDoorRoot = "RECORDDOOR_ROOT"

// recordDoorApp declares one scope carrying every half of a declaration: a
// required field, an optional field, a defaulted field, a field with a closed
// set, a field with a custom validation callback, a marker default, and a
// nested selector.
func recordDoorApp(captured *map[string]interface{}) *App {
	os.Unsetenv(recordDoorRoot)
	app := NewApp("myapp", "1.0.0", "test app", WithInfraRoot(recordDoorRoot, "/var/lib/myapp"))
	app.Command("run", "run it", captureHandler(captured),
		WithFlags(
			ChoiceFlag("via", "delivery channel", Required(),
				Choice("none", "no delivery"),
				Choice("email", "an email message",
					IntFlag("retries", "how many", Required()),
					StringFlag("note", "a note", Optional()),
					BoolFlag("strict", "fail on a soft bounce", Default(false)),
					StringFlag("fmt", "the wire format", Required(),
						Choices(Ch("text", "plain text"), Ch("json", "JSON"))),
					StringFlag("checked", "a validated value", Required(),
						ValidateFn(func(v interface{}) error {
							if v == "x" {
								return nil
							}
							return fmt.Errorf("nope: %v", v)
						})),
					StringFlag("cache", "where the queue lives",
						Default(RelativeToRoot(recordDoorRoot, "cache", "e.db"))),
					ChoiceFlag("speed", "how fast", Default("fast"),
						Choice("fast", "quickly"),
						Choice("slow", "safely", IntFlag("patience", "how long to wait", Required())),
					),
				),
			),
			MemberChoiceFlag("mode", "which profiles", Required(),
				MemberChoice(StringFlag("profile", "a profile", Required()), "one named profile"),
				MemberChoice(BoolFlag("all-profiles", "every profile", Required()), "every profile"),
			),
		),
		WithEffect(EffectReadOnly))
	return app
}

// recordDoorChoice finds one declared choice at any depth of recordDoorApp.
func recordDoorChoice(app *App, selName, chName string) *ChoiceDecl {
	var walk func(flags []Flag) *ChoiceDecl
	walk = func(flags []Flag) *ChoiceDecl {
		for i := range flags {
			f := &flags[i]
			if f.Type != TypeChoice {
				continue
			}
			if f.Name == selName {
				if ch := findChoice(f, chName); ch != nil {
					return ch
				}
			}
			for _, ch := range f.choiceDecls {
				if found := walk(ch.Flags); found != nil {
					return found
				}
			}
		}
		return nil
	}
	found := walk(app.commands["run"].flags)
	if found == nil {
		panic("no choice " + chName + " on " + selName)
	}
	return found
}

// recordDoorEmail is the email scope's fields with every required one named,
// merged over by the overrides one test cares about.
func recordDoorEmail(overrides Fields) Fields {
	fields := Fields{"retries": 1, "fmt": "text", "checked": "x"}
	for k, v := range overrides {
		fields[k] = v
	}
	return fields
}

// recordDoorCall runs one call through the RECORD door and returns the kwargs
// the handler received, or the refusal.
func recordDoorCall(t *testing.T, fields Fields) (map[string]interface{}, string) {
	t.Helper()
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	kwargs := map[string]interface{}{
		"via":  Elect(recordDoorChoice(app, "via", "email"), fields),
		"mode": Elect(recordDoorChoice(app, "mode", "all-profiles"), Fields{}),
	}
	ir := app.invoke("run", kwargs)
	return captured, ir.err
}

// recordDoorDelivered runs one call that must be accepted and returns the
// elected record the handler received.
func recordDoorDelivered(t *testing.T, fields Fields) *Elected {
	t.Helper()
	captured, errStr := recordDoorCall(t, fields)
	if errStr != "" {
		t.Fatalf("the call was refused with %q", errStr)
	}
	return GetElected(captured, "via")
}

// recordDoorRefusal runs one call that must be refused and returns its sentence.
func recordDoorRefusal(t *testing.T, fields Fields) string {
	t.Helper()
	_, errStr := recordDoorCall(t, fields)
	if errStr == "" {
		t.Fatal("the call was accepted; want a refusal")
	}
	return errStr
}

// flatDoorCall runs the same command through the FLAT door: the choice name
// under the selector's own key, every scoped parameter a top-level key.
func flatDoorCall(t *testing.T, extra map[string]interface{}) (map[string]interface{}, string) {
	t.Helper()
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	kwargs := map[string]interface{}{
		"via":          "email",
		"all_profiles": true,
		"retries":      1,
		"fmt":          "text",
		"checked":      "x",
	}
	for k, v := range extra {
		kwargs[k] = v
	}
	ir := app.invoke("run", kwargs)
	return captured, ir.err
}

// ---------------------------------------------------------------------------
// Item 252: an explicit nil on an optional scoped field is absence
// ---------------------------------------------------------------------------

func TestRecordDoorOptionalFieldTakesAnExplicitNil(t *testing.T) {
	e := recordDoorDelivered(t, recordDoorEmail(Fields{"note": nil}))
	if got, ok := e.Fields["note"]; !ok || got != nil {
		t.Fatalf("note = %#v (present %v), want a present key holding nothing", got, ok)
	}
	if e.Provided("note") {
		t.Fatal("an absent optional field is the declaration's answer: provided must be false")
	}
}

func TestRecordDoorOmittedOptionalFieldIsTheSameAbsence(t *testing.T) {
	withNil := recordDoorDelivered(t, recordDoorEmail(Fields{"note": nil}))
	omitted := recordDoorDelivered(t, recordDoorEmail(Fields{}))
	if withNil.Fields["note"] != omitted.Fields["note"] {
		t.Fatalf("explicit nil = %#v, omitted = %#v: one absence, one answer",
			withNil.Fields["note"], omitted.Fields["note"])
	}
	if withNil.Provided("note") != omitted.Provided("note") {
		t.Fatal("explicit nil and an omitted key must agree about provided")
	}
}

func TestRecordDoorDefaultedFieldStillRefusesAnExplicitNil(t *testing.T) {
	got := recordDoorRefusal(t, recordDoorEmail(Fields{"strict": nil}))
	wantRefusal(t, got, "--strict: expected boolean, got null")
}

func TestRecordDoorRequiredFieldStillRefusesAnExplicitNil(t *testing.T) {
	got := recordDoorRefusal(t, recordDoorEmail(Fields{"retries": nil}))
	wantRefusal(t, got, "--retries: expected integer, got null")
}

func TestRecordDoorNestedOptionalFieldTakesAnExplicitNilToo(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	// The carve-out is the door's, not the depth's: a nested record answers the
	// same way its parent does.
	kwargs := map[string]interface{}{
		"via": Elect(recordDoorChoice(app, "via", "email"), recordDoorEmail(Fields{
			"note":  nil,
			"speed": Elect(recordDoorChoice(app, "speed", "slow"), Fields{"patience": 9}),
		})),
		"mode": Elect(recordDoorChoice(app, "mode", "all-profiles"), Fields{}),
	}
	if ir := app.invoke("run", kwargs); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	e := GetElected(captured, "via")
	if e.Fields["note"] != nil {
		t.Fatalf("note = %#v, want absence", e.Fields["note"])
	}
	inner, ok := e.Fields["speed"].(*Elected)
	if !ok {
		t.Fatalf("speed = %#v, want a nested elected record", e.Fields["speed"])
	}
	if inner.Fields["patience"] != 9 {
		t.Fatalf("patience = %#v, want 9", inner.Fields["patience"])
	}
}

func TestFlatDoorOptionalScopedFieldStillRefusesAnExplicitNil(t *testing.T) {
	// The flat door spells absence by omitting the key, so a nil there would be
	// a SECOND spelling of one fact: it stays refused.
	_, errStr := flatDoorCall(t, map[string]interface{}{"note": nil})
	wantRefusal(t, errStr, "--note: expected string, got null")
}
