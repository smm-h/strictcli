package strictcli

import (
	"fmt"
	"os"
	"testing"
)

// The RECORD door's three aligned answers (contract §24.11, §18.26 items 252,
// 253, 254).
//
// A record has no way to omit a key the way a flat object does -- a scope class
// cannot be constructed without naming every field -- so an explicit nil on an
// OPTIONAL scoped field IS that omission: it is legal, and it delivers absence,
// exactly as the omitted key does. The carve-out is this door's alone and stops
// at optionality: a required or defaulted field still refuses a nil, and at the
// flat door, where absence has its own spelling, a nil stays legal for nothing.
//
// Every field a caller's record supplies reports source `default`, so Provided
// answers false for all of them: a scope class fills a declared default at
// construction, so a field holding its declared default cannot be told from one
// the caller wrote, and `provided` asks whether the invocation caused the value
// rather than whether it differs from the declaration. The one exception is
// pinned -- a RelativeToRoot default resolved at this door still reports
// `infra` and still resolves to the path through the declared root. The pin is
// the record door's: the flat door and the command line are untouched.
//
// And this door runs the TYPE check and nothing else. The closed set (Choices)
// and the custom validation (ValidateFn) are deferred, because a door that
// cannot tell a supplied field from a declared one would run validate on values
// the declaration decided, which §23.4 forbids. The argv and flat doors keep
// both checks exactly as they were.

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

// ---------------------------------------------------------------------------
// Item 253: every field a record supplies reports `default`
// ---------------------------------------------------------------------------

func TestRecordDoorSuppliedFieldIsNotProvided(t *testing.T) {
	e := recordDoorDelivered(t, recordDoorEmail(Fields{"strict": true}))
	for _, key := range []string{"retries", "note", "strict", "fmt", "checked", "cache", "speed"} {
		if e.Provided(key) {
			t.Fatalf("%s: the record door labels every field it delivers default", key)
		}
	}
	if e.Fields["retries"] != 1 || e.Fields["strict"] != true {
		t.Fatalf("the values themselves are unchanged: %#v", e.Fields)
	}
}

func TestRecordDoorMemberPayloadIsNotProvided(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	kwargs := map[string]interface{}{
		"via":  Elect(recordDoorChoice(app, "via", "email"), recordDoorEmail(Fields{})),
		"mode": Elect(recordDoorChoice(app, "mode", "profile"), Fields{"value": "work"}),
	}
	if ir := app.invoke("run", kwargs); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	mode := GetElected(captured, "mode")
	if mode.Fields["value"] != "work" {
		t.Fatalf("value = %#v, want work", mode.Fields["value"])
	}
	if mode.Provided("value") {
		t.Fatal("a member payload supplied in a record is a field like any other")
	}
}

func TestRecordDoorNestedSelectionIsNotProvided(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	kwargs := map[string]interface{}{
		"via": Elect(recordDoorChoice(app, "via", "email"), recordDoorEmail(Fields{
			"speed": Elect(recordDoorChoice(app, "speed", "slow"), Fields{"patience": 9}),
		})),
		"mode": Elect(recordDoorChoice(app, "mode", "all-profiles"), Fields{}),
	}
	if ir := app.invoke("run", kwargs); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	e := GetElected(captured, "via")
	if e.Provided("speed") {
		t.Fatal("a nested selection a record supplies is a field of that record")
	}
	inner := e.Fields["speed"].(*Elected)
	if inner.Provided("patience") {
		t.Fatal("depth is not a door: a nested record's fields are labelled default too")
	}
}

func TestRecordDoorResolvedMarkerKeepsItsInfraAnswer(t *testing.T) {
	// The pinned exception: a RelativeToRoot default resolved at this door is
	// still the resolved path, and still not provided.
	e := recordDoorDelivered(t, recordDoorEmail(Fields{}))
	if got := e.Fields["cache"]; got != "/var/lib/myapp/cache/e.db" {
		t.Fatalf("cache = %#v, want the resolved path", got)
	}
	if e.Provided("cache") {
		t.Fatal("an infra default is a declared default: provided must be false")
	}
}

func TestFlatDoorScopedValueStaysProvided(t *testing.T) {
	// The pin is the RECORD door's. The flat door keeps the answer it has.
	captured, errStr := flatDoorCall(t, nil)
	if errStr != "" {
		t.Fatalf("invoke error: %s", errStr)
	}
	e := GetElected(captured, "via")
	if !e.Provided("retries") {
		t.Fatal("a value supplied at the flat door is caused by the invocation")
	}
	if e.Provided("cache") {
		t.Fatal("a declared default is not provided at any door")
	}
}

func TestCommandLineScopedValueStaysProvided(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	r := app.Test([]string{"run", "--via", "email", "--retries", "1", "--fmt", "text",
		"--checked", "x", "--all-profiles"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	e := GetElected(captured, "via")
	if !e.Provided("retries") {
		t.Fatal("a typed token is the invocation causing the value")
	}
}

// ---------------------------------------------------------------------------
// Item 254: the type check, and only the type check
// ---------------------------------------------------------------------------

func TestRecordDoorDeliversAValueOutsideTheClosedSet(t *testing.T) {
	e := recordDoorDelivered(t, recordDoorEmail(Fields{"fmt": "xml"}))
	if e.Fields["fmt"] != "xml" {
		t.Fatalf("fmt = %#v, want the value the record supplied", e.Fields["fmt"])
	}
}

func TestRecordDoorNeverRunsTheCustomValidation(t *testing.T) {
	e := recordDoorDelivered(t, recordDoorEmail(Fields{"checked": "anything"}))
	if e.Fields["checked"] != "anything" {
		t.Fatalf("checked = %#v, want the value the record supplied", e.Fields["checked"])
	}
}

func TestRecordDoorNestedClosedSetIsDeferredToo(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	kwargs := map[string]interface{}{
		"via": Elect(recordDoorChoice(app, "via", "email"), recordDoorEmail(Fields{
			"fmt":   "xml",
			"speed": Elect(recordDoorChoice(app, "speed", "slow"), Fields{"patience": 9}),
		})),
		"mode": Elect(recordDoorChoice(app, "mode", "all-profiles"), Fields{}),
	}
	if ir := app.invoke("run", kwargs); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
}

func TestRecordDoorStillChecksTheType(t *testing.T) {
	got := recordDoorRefusal(t, recordDoorEmail(Fields{"retries": "3"}))
	wantRefusal(t, got, "--retries: expected integer, got str")
}

func TestFlatDoorKeepsTheClosedSetCheck(t *testing.T) {
	_, errStr := flatDoorCall(t, map[string]interface{}{"fmt": "xml"})
	wantRefusal(t, errStr, "--fmt: invalid value 'xml', must be one of: text, json")
}

func TestFlatDoorKeepsTheCustomValidation(t *testing.T) {
	_, errStr := flatDoorCall(t, map[string]interface{}{"checked": "anything"})
	wantRefusal(t, errStr, "--checked: nope: anything")
}

func TestCommandLineKeepsTheClosedSetCheck(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	r := app.Test([]string{"run", "--via", "email", "--retries", "1", "--fmt", "xml",
		"--checked", "x", "--all-profiles"})
	if r.ExitCode == 0 {
		t.Fatal("the command line keeps the closed-set check")
	}
	want := "error: --fmt: invalid value 'xml', must be one of: text, json\ntry 'myapp run --help'\n"
	if got := r.Stderr; got != want {
		t.Fatalf("stderr = %q", got)
	}
}

func TestCommandLineKeepsTheCustomValidation(t *testing.T) {
	var captured map[string]interface{}
	app := recordDoorApp(&captured)
	r := app.Test([]string{"run", "--via", "email", "--retries", "1", "--fmt", "text",
		"--checked", "anything", "--all-profiles"})
	if r.ExitCode == 0 {
		t.Fatal("the command line keeps the custom validation")
	}
	want := "error: --checked: nope: anything\ntry 'myapp run --help'\n"
	if got := r.Stderr; got != want {
		t.Fatalf("stderr = %q", got)
	}
}
