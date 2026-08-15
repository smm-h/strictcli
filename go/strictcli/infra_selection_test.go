package strictcli

import (
	"os"
	"testing"
)

// --- A defaulted selection's RelativeToRoot field (contract §24.5, §23.5,
// §18.23 item 237, §18.26 item 256) ---
//
// §24.5 says a defaulted selection is COMPLETE and delivered as declared, and
// that means the declaration's SEMANTICS rather than its raw objects: a marker
// sitting inside the selection a selector's own default names is the same
// declared default one frame further in. So it resolves to the path through the
// declared root, with `provided` false, at every door and at every depth --
// exactly what the identical declaration under an ELECTED choice delivers.
//
// Go's selector default names a choice, so nothing holds a pre-built instance:
// the scope is rebuilt from its declarations and each field takes the ordinary
// default path (applyFlagDefault, whose marker branch answers SourceInfra).
// These tests pin that seam at all three doors, so a rewrite that materializes
// a defaulted selection some other way cannot hand a handler the marker object.

const selInfraRoot = "SELDEFAULT_ROOT"

// selInfraApp declares a defaulted selection whose scope carries a marker
// default at two depths: `cfg` in the elected choice, and `store` inside a
// nested selector that is itself defaulted.
func selInfraApp(captured *map[string]interface{}) (*App, *ChoiceDecl, *ChoiceDecl) {
	os.Unsetenv(selInfraRoot)
	smtp := Choice("smtp", "over SMTP",
		StringFlag("store", "the queue directory", Default(RelativeToRoot(selInfraRoot, "queue"))),
	)
	api := Choice("api", "over the vendor API", StringFlag("url", "the endpoint", Default("https://x")))
	email := Choice("email", "as an email message",
		ChoiceFlag("transport", "how it is sent", smtp, api, Default("smtp")),
		StringFlag("cfg", "the config file", Default(RelativeToRoot(selInfraRoot, "cfg", "x.toml"))),
	)
	sms := Choice("sms", "as a text message", StringFlag("phone-number", "destination", Default("+1")))
	app := NewApp("myapp", "1.0.0", "test app", WithInfraRoot(selInfraRoot, "/var/lib/myapp"))
	app.Command("send", "send it", captureHandler(captured),
		WithFlags(ChoiceFlag("via", "delivery channel", email, sms, Default("email"))),
		WithEffect(EffectReadOnly))
	return app, email, smtp
}

// assertSelInfraResolved checks the resolved path and the provided answer at
// both depths of the record selInfraApp delivers.
func assertSelInfraResolved(t *testing.T, kwargs map[string]interface{}) {
	t.Helper()
	e := GetElected(kwargs, "via")
	if e.Name() != "email" {
		t.Fatalf("elected %q, want email", e.Name())
	}
	if got := e.Fields["cfg"]; got != "/var/lib/myapp/cfg/x.toml" {
		t.Fatalf("cfg = %#v, want the resolved path /var/lib/myapp/cfg/x.toml", got)
	}
	if e.Provided("cfg") {
		t.Fatal("an infra default is still a declared default: provided must be false")
	}
	inner, ok := e.Fields["transport"].(*Elected)
	if !ok {
		t.Fatalf("transport = %#v, want a nested elected record", e.Fields["transport"])
	}
	if got := inner.Fields["store"]; got != "/var/lib/myapp/queue" {
		t.Fatalf("store = %#v, want the resolved path /var/lib/myapp/queue", got)
	}
	if inner.Provided("store") {
		t.Fatal("a nested infra default is still a declared default: provided must be false")
	}
}

// The command line elects nothing: the selector's own default decides, at both
// depths, and the marker reaches the handler resolved.
func TestDefaultedSelectionMarkerResolvesOnTheCommandLine(t *testing.T) {
	var captured map[string]interface{}
	app, _, _ := selInfraApp(&captured)
	r := app.Test([]string{"send"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	assertSelInfraResolved(t, captured)
}

// The flat door with the selector key omitted is the same state, and the flat
// door is the command line with the tokens removed (§24.11).
func TestDefaultedSelectionMarkerResolvesAtTheFlatDoor(t *testing.T) {
	var captured map[string]interface{}
	app, _, _ := selInfraApp(&captured)
	if ir := app.invoke("send", map[string]interface{}{}); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	assertSelInfraResolved(t, captured)
}

// The record door hands over the elected choice with an empty scope, so every
// field is the declaration's -- including the two markers.
func TestDefaultedSelectionMarkerResolvesAtTheRecordDoor(t *testing.T) {
	var captured map[string]interface{}
	app, email, _ := selInfraApp(&captured)
	if ir := app.invoke("send", map[string]interface{}{"via": Elect(email, Fields{})}); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	assertSelInfraResolved(t, captured)
}

// A record whose nested selector is supplied as its own record reaches the same
// answer: depth is not a door.
func TestDefaultedSelectionMarkerResolvesInsideANestedRecord(t *testing.T) {
	var captured map[string]interface{}
	app, email, smtp := selInfraApp(&captured)
	kwargs := map[string]interface{}{"via": Elect(email, Fields{"transport": Elect(smtp, Fields{})})}
	if ir := app.invoke("send", kwargs); ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
	assertSelInfraResolved(t, captured)
}

// One presence apart, one answer: electing the same choice explicitly delivers
// the same resolved path the selector's default delivers. An implementation
// that disagrees with itself here is item 256's defect.
func TestElectedAndDefaultedSelectionsAgreeOnTheMarker(t *testing.T) {
	var defaulted, elected map[string]interface{}
	appA, _, _ := selInfraApp(&defaulted)
	if r := appA.Test([]string{"send"}); r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	appB, _, _ := selInfraApp(&elected)
	if r := appB.Test([]string{"send", "--via", "email", "--transport", "smtp"}); r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	assertSelInfraResolved(t, elected)
	a := GetElected(defaulted, "via")
	b := GetElected(elected, "via")
	if a.Fields["cfg"] != b.Fields["cfg"] {
		t.Fatalf("defaulted cfg = %#v, elected cfg = %#v: one declaration, two answers", a.Fields["cfg"], b.Fields["cfg"])
	}
	if a.Provided("cfg") != b.Provided("cfg") {
		t.Fatalf("defaulted provided = %v, elected provided = %v", a.Provided("cfg"), b.Provided("cfg"))
	}
}

// A member-spelled selector's default elects a payload-less member, and its
// scope's marker resolves exactly as a token-spelled scope's does.
func TestDefaultedMemberSelectionMarkerResolves(t *testing.T) {
	os.Unsetenv(selInfraRoot)
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app", WithInfraRoot(selInfraRoot, "/var/lib/myapp"))
	app.Command("run", "run it", captureHandler(&captured),
		WithFlags(MemberChoiceFlag("target", "which profiles", Default("all-profiles"),
			MemberChoice(StringFlag("profile", "a profile", Required()), "one named profile"),
			MemberChoice(BoolFlag("all-profiles", "every profile", Required(), NegatableOpt(false)), "every profile",
				StringFlag("state", "the state directory", Default(RelativeToRoot(selInfraRoot, "state")))),
		)), WithEffect(EffectReadOnly))
	r := app.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	e := GetElected(captured, "target")
	if got := e.Fields["state"]; got != "/var/lib/myapp/state" {
		t.Fatalf("state = %#v, want the resolved path /var/lib/myapp/state", got)
	}
	if e.Provided("state") {
		t.Fatal("an infra default inside a member scope is still a declared default")
	}
}

// The delivered record is built for the run: the declaration keeps its marker,
// so a second run resolves it again rather than reading a rewritten default.
func TestDefaultedSelectionDeliveryLeavesTheDeclarationIntact(t *testing.T) {
	var captured map[string]interface{}
	app, email, _ := selInfraApp(&captured)
	if r := app.Test([]string{"send"}); r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	assertSelInfraResolved(t, captured)
	var scoped *Flag
	for i := range email.Flags {
		if email.Flags[i].Name == "cfg" {
			scoped = &email.Flags[i]
		}
	}
	if _, stillMarker := scoped.Default.(InfraRootPath); !stillMarker {
		t.Fatalf("the declaration's default is %#v, want the RelativeToRoot marker it was declared with", scoped.Default)
	}
	// The same app, a second run: a declaration rewritten in place would show
	// up here as the first run's resolution masquerading as the declaration.
	if r := app.Test([]string{"send"}); r.ExitCode != 0 {
		t.Fatalf("second run: exit %d: %s", r.ExitCode, r.Stderr)
	}
	assertSelInfraResolved(t, captured)
}

// Registration never looks inside a scope, so a marker naming an undeclared
// root is refused where it resolves -- with §12.13's scope suffix and the
// origin clause that says the selection was the declaration's (§24.3).
func TestDefaultedSelectionUndeclaredRootRefusalCarriesTheScopeSuffix(t *testing.T) {
	os.Unsetenv(selInfraRoot)
	want := `RelativeToRoot references undeclared infra root "NOPE"; declare it as an infra root under '--via email' (elected by default)`
	build := func(captured *map[string]interface{}) *App {
		app := NewApp("myapp", "1.0.0", "test app", WithInfraRoot(selInfraRoot, "/var/lib/myapp"))
		app.Command("send", "send it", captureHandler(captured),
			WithFlags(ChoiceFlag("via", "delivery channel",
				Choice("email", "as an email message", StringFlag("cfg", "the config file", Default(RelativeToRoot("NOPE", "x")))),
				Choice("sms", "as a text message", StringFlag("phone-number", "destination", Default("+1"))),
				Default("email"))),
			WithEffect(EffectReadOnly))
		return app
	}
	var captured map[string]interface{}
	r := build(&captured).Test([]string{"send"})
	if r.ExitCode != 1 {
		t.Fatalf("exit = %d, want 1", r.ExitCode)
	}
	if r.Stderr != "error: "+want+"\ntry 'myapp send --help'\n" {
		t.Fatalf("stderr = %q, want the refusal %q", r.Stderr, want)
	}
	if ir := build(&captured).invoke("send", map[string]interface{}{}); ir.err != want {
		t.Fatalf("flat error = %q, want %q", ir.err, want)
	}
}
