package strictcli

import (
	"testing"
)

// Machine mode: the reserved --json flag and the payload API.
//
// Contract §19.1 (the flag and its delivery), §19.4 (the payload API) and
// §7.1's 2026-08-13 amendment (the unconditional every-level name ban).

const jsonReservedMsg = "flag name 'json' is reserved by the framework"

// --- the name ban: unconditional, at every level ---------------------------

func TestJSONFlagNameIsReservedOnCommandFlags(t *testing.T) {
	expectPanicContaining(t, jsonReservedMsg, func() {
		BoolFlag("json", "output json", Default(false))
	})
}

func TestJSONFlagNameIsReservedOnGlobalFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	expectPanicContaining(t, jsonReservedMsg, func() {
		app.GlobalFlag(Flag{Name: "json", Help: "output json", Type: TypeBool})
	})
}

func TestArgNamedJSONIsUnaffected(t *testing.T) {
	// The ban covers the flag surface only: an arg has no `--` spelling.
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cat", "cat a file", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	}, WithArgs(NewArg("json", "a file named json")), WithEffect(EffectReadOnly))
	if r := app.Test([]string{"cat", "x"}); r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
}

// --- delivery: both argv regions, stripped, on the Context -----------------

func machineFlagApp() *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.Payload(map[string]interface{}{"json": ctx.JSON()})
		return Exit(0)
	}, WithEffect(EffectReadOnly), PayloadSchema(map[string]interface{}{}))
	return app
}

func TestJSONFlagDelivery(t *testing.T) {
	cases := []struct {
		name       string
		argv       []string
		wantStdout string
	}{
		{"absent", []string{"run"}, ""},
		{"before the command", []string{"--json", "run"}, "{\"json\":true}\n"},
		{"after the command", []string{"run", "--json"}, "{\"json\":true}\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := machineFlagApp().Test(tc.argv)
			if r.ExitCode != 0 {
				t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
			}
			if r.Stdout != tc.wantStdout {
				t.Fatalf("stdout = %q, want %q", r.Stdout, tc.wantStdout)
			}
		})
	}
}

func TestJSONFlagIsNeverAHandlerKwarg(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		if _, ok := kwargs["json"]; ok {
			t.Fatal("--json must not reach the handler as a kwarg")
		}
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	if r := app.Test([]string{"run", "--json"}); r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
}

// --- the payload API -------------------------------------------------------

func TestPayloadWithoutADeclaredSchemaPanics(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.Payload(map[string]interface{}{"k": 1})
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	expectPanicContaining(t, "requires a declared payload schema", func() {
		app.Test([]string{"run"})
	})
}

func TestPayloadTwicePanics(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.Payload(map[string]interface{}{"k": 1})
		ctx.Payload(map[string]interface{}{"k": 2})
		return Exit(0)
	}, WithEffect(EffectReadOnly), PayloadSchema(map[string]interface{}{}))
	expectPanicContaining(t, "was already called", func() {
		app.Test([]string{"run"})
	})
}

func TestQuietNeverReachesThePayload(t *testing.T) {
	r := machineFlagApp().Test([]string{"--quiet", "--json", "run"})
	if r.Stdout != "{\"json\":true}\n" {
		t.Fatalf("stdout = %q, want the payload under --quiet", r.Stdout)
	}
}

func TestPayloadEscapingIsPlainUTF8(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.Payload(map[string]interface{}{"text": "héllo <b>&</b> 日本語"})
		return Exit(0)
	}, WithEffect(EffectReadOnly), PayloadSchema(map[string]interface{}{}))
	r := app.Test([]string{"run", "--json"})
	want := "{\"text\":\"héllo <b>&</b> 日本語\"}\n"
	if r.Stdout != want {
		t.Fatalf("stdout = %q, want %q", r.Stdout, want)
	}
}
