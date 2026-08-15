package strictcli

import (
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// The positional stage is the PIPELINE's own (§24.11 item 248, item 244)
//
// A pre-typed positional is read where every positional is read: after implies
// and dependency resolution, after flag presence and defaults, after the
// choices and custom-validation sweeps. So a missing required FLAG outranks a
// bad positional at the programmatic doors exactly as it does on the command
// line, and neither door reorders the other's refusals.
// ---------------------------------------------------------------------------

// positionalStageApp declares one problem per pipeline stage above the
// positional one, so each can be raced against a positional that will not
// satisfy its declaration.
func positionalStageApp(captured *map[string]interface{}) *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(captured),
		WithFlags(
			StringFlag("name", "a name", Required()),
			StringFlag("mode", "the mode", Optional(),
				Choices(Ch("fast", "quick"), Ch("slow", "steady"))),
			StringFlag("token", "a token", Optional(), ValidateFn(func(v interface{}) error {
				if v.(string) == "bad" {
					return errBadToken
				}
				return nil
			})),
			StringFlag("alpha", "one half", Optional()),
			StringFlag("beta", "the other half", Optional()),
			ChoiceFlag("via", "delivery channel", Required(),
				Choice("email", "an email message", IntFlag("retries", "how many", Required())),
				Choice("sms", "a text message", StringFlag("phone-number", "destination", Required())),
			),
		),
		WithConstraints(AllOrNone("halves", Member("alpha"), Member("beta"))),
		WithArgs(NewArg("count", "how many", ArgType(TypeInt), ArgRequired())),
		WithEffect(EffectReadOnly))
	return app
}

var errBadToken = errString("token must not be 'bad'")

// errString is a minimal error carrying its own text.
type errString string

func (e errString) Error() string { return string(e) }

// The positional is wrong in every case below, and never the refusal: each
// stage above it decides first, at the flat door, at the record door and on the
// command line alike.
func TestPositionalStageLosesToEveryStageAboveIt(t *testing.T) {
	cases := []struct {
		name   string
		kwargs map[string]interface{}
		argv   []string
		want   string
	}{
		{
			"a missing required flag",
			map[string]interface{}{"via": "email", "retries": 1, "count": "7"},
			[]string{"run", "--via", "email", "--retries", "1", "notanint"},
			"flag '--name' is required",
		},
		{
			"an unsatisfied selector",
			map[string]interface{}{"name": "n", "count": "7"},
			[]string{"run", "--name", "n", "notanint"},
			"flag '--via' is required",
		},
		{
			"a missing required flag inside a scope",
			map[string]interface{}{"name": "n", "via": "email", "count": "7"},
			[]string{"run", "--name", "n", "--via", "email", "notanint"},
			"flag '--retries' is required under '--via email'",
		},
		{
			"a dependency violation",
			map[string]interface{}{"name": "n", "via": "email", "retries": 1, "alpha": "a", "count": "7"},
			[]string{"run", "--name", "n", "--via", "email", "--retries", "1", "--alpha", "a", "notanint"},
			`constraint "halves": --alpha, --beta must be used together`,
		},
		{
			"a choices violation",
			map[string]interface{}{"name": "n", "via": "email", "retries": 1, "mode": "nope", "count": "7"},
			[]string{"run", "--name", "n", "--via", "email", "--retries", "1", "--mode", "nope", "notanint"},
			"--mode: invalid value 'nope', must be one of: fast, slow",
		},
		{
			"a custom validator's refusal",
			map[string]interface{}{"name": "n", "via": "email", "retries": 1, "token": "bad", "count": "7"},
			[]string{"run", "--name", "n", "--via", "email", "--retries", "1", "--token", "bad", "notanint"},
			"--token: token must not be 'bad'",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var captured map[string]interface{}
			if ir := positionalStageApp(&captured).invoke("run", c.kwargs); ir.err != c.want {
				t.Fatalf("flat error = %q, want %q", ir.err, c.want)
			}
			r := positionalStageApp(&captured).Test(c.argv)
			if !strings.Contains(r.Stderr, "error: "+c.want+"\n") {
				t.Fatalf("cli stderr = %q, want it to contain %q", r.Stderr, c.want)
			}
		})
	}
}

// And with every stage above it satisfied, the positional's own declaration is
// what refuses -- so the loss above is staging and not silence.
func TestPositionalStageRefusesOnceTheStagesAboveItPass(t *testing.T) {
	var captured map[string]interface{}
	ir := positionalStageApp(&captured).invoke("run", map[string]interface{}{
		"name": "n", "via": "email", "retries": 1, "count": "7",
	})
	wantRefusal(t, ir.err, "argument 'count': expected integer, got str")
}
