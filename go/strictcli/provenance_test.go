package strictcli

import (
	"strings"
	"testing"
)

// ---------------------------------------------------------------------------
// Five-way presence semantics for source-filtered queries
// ---------------------------------------------------------------------------

// Tests 1-3 stood here and are DELETED with MutexGroup (contract §21's
// supersession box). Each asserted how a source label interacted with a group's
// cardinality check, and the construct removed the interaction rather than
// changing it:
//
//   - "a defaulted member is not present for the group" -- a member flag must
//     now declare Required() (§12.13's errMemberFlagPresence), so a defaulted
//     member cannot be written at all.
//   - "an implied member is not present for the group" -- a dependency naming a
//     scoped flag is a registration error (§24.8), so the shape is refused.
//   - "two provided members are mutually exclusive on the programmatic path" --
//     the programmatic value is ONE elected record (§24.11), so electing two is
//     inexpressible rather than refused. The CLI-side sentence is asserted in
//     member_election_test.go.
//
// What survives is the source semantics themselves, which the tests below and
// the dependency tests still cover, plus the election's own source label
// (TestSelectorSourceFollowsElection in selector_test.go).

// Test 4: A dependency (Requires) where the required flag has source=implied
// should PASS. Implied values count as "present" for dependency checks.
func TestRequiresImpliedSourceCountsAsPresent(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	},
		WithFlags(
			BoolFlag("all", "deploy all", Default(false)),
			BoolFlag("loud", "loud mode", Default(false)),
			StringFlag("target", "deploy target", Required()),
		),
		WithConstraints(
			// --all implies --loud=true
			Implies("all-is-loud", "all", "loud", true),
			// --target requires --loud
			Requires("target-needs-loud", "target", "loud"),
		), WithEffect(EffectReadOnly),
	)

	// Provide --all and --target. --all implies --loud (source=implied).
	// --target requires --loud. Since implied counts for deps, this
	// should succeed.
	r := app.Test([]string{"deploy", "--all", "--target", "prod"})
	if r.ExitCode != 0 {
		t.Fatalf("expected success, got exit code %d: %s", r.ExitCode, r.Stderr)
	}
}

// Test 5: A dependency (Requires) where the required flag has source=default
// should FAIL. Default values do NOT count as "present" for dependency checks.
func TestRequiresDefaultSourceNotPresent(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	},
		WithFlags(
			StringFlag("target", "deploy target", Required()),
			BoolFlag("loud", "loud mode", Default(false)),
		),
		WithConstraints(
			// --target requires --loud
			Requires("target-needs-loud", "target", "loud"),
		), WithEffect(EffectReadOnly),
	)

	// Provide --target but NOT --loud. --loud has Default(false), so
	// it will get source=default. Since default does NOT count as "present"
	// for deps, this should fail with "requires" error.
	r := app.Test([]string{"deploy", "--target", "prod"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "requires") {
		t.Fatalf("expected 'requires' error, got: %s", r.Stderr)
	}
}

// ---------------------------------------------------------------------------
// Invoke path: verify that invoke correctly marks kwargs as SourceCLI
// and absent-then-defaulted flags as SourceDefault.
// ---------------------------------------------------------------------------

// Test that invoke's elected record satisfies a member-spelled selector, and
// that the selector's own key carries source "cli" on that path.
func TestInvokeElectedRecordIsCliSource(t *testing.T) {
	jsonChoice := MemberChoice(StringFlag("as-json", "JSON output", Required()), "JSON output")
	var gotSource string
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("out", "output", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		gotSource = ctx.Source("fmt")
		return Exit(0)
	},
		WithFlags(MemberChoiceFlag("fmt", "output format", Required(),
			jsonChoice,
			MemberChoice(StringFlag("text", "text output", Required()), "text output"),
		)), WithEffect(EffectReadOnly),
	)

	ir := app.invoke("out", map[string]interface{}{"fmt": Elect(jsonChoice, Fields{"value": "data"})})
	if ir.err != "" {
		t.Fatalf("invoke: expected success, got error: %s", ir.err)
	}
	if gotSource != "cli" {
		t.Fatalf("source = %q, want \"cli\"", gotSource)
	}
}

// Test that invoke with an absent kwarg that gets defaulted does NOT count
// as present for Requires.
func TestInvokeDefaultedNotPresentForRequires(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("deploy", "deploy", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		return Exit(0)
	},
		WithFlags(
			StringFlag("target", "deploy target", Required()),
			BoolFlag("loud", "loud mode", Default(false)),
		),
		WithConstraints(
			Requires("target-needs-loud", "target", "loud"),
		), WithEffect(EffectReadOnly),
	)

	// Provide target but not loud. loud will be defaulted.
	// Default does not count as present for Requires, so this should fail.
	ir := app.invoke("deploy", map[string]interface{}{"target": "prod"})
	if ir.err == "" {
		t.Fatal("invoke: expected 'requires' error")
	}
	if !strings.Contains(ir.err, "requires") {
		t.Fatalf("invoke: expected 'requires' error, got: %s", ir.err)
	}
}
