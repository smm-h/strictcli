package strictcli

import (
	"strings"
	"testing"
)

// The flat machine boundary's SHAPE and VALUE staging, and the two doors'
// agreement about both (contract §24.11, §24.3, §23.4).
//
//   - A value arrives already typed, so nothing parses it -- but PRE-TYPED means
//     ALREADY OF THE DECLARED TYPE, never exempt from the declaration. Every
//     supplied value is checked against the type its declaration names, and null
//     is a legal value for nothing: optionality has ONE spelling (§23.4), which
//     is the declaration plus an absent key.
//   - A key naming nothing the command declares is a fact about the object's
//     SHAPE, and shape is decided ahead of every election, scope, value and
//     presence problem -- exactly as an unknown flag outranks all four on the
//     command line wherever it sits in argv. A key spelled with dashes where the
//     boundary publishes an underscored parameter names nothing.
//   - Both doors are one parser: App.Call takes the elected record, the flat
//     machine form takes the choice name and the scoped keys, and the phases run
//     in the same order for each.

// preTypedApp declares one of everything the boundary can carry: a member's
// payload, a payload-less member, a token-spelled selector with scoped flags of
// three types, the command's own scalar/list/dict flags, an app-level global,
// and two positional args.
func preTypedApp(captured *map[string]interface{}) *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(IntFlag("timeout", "seconds to wait", Default(30)))
	app.Command("run", "run it", captureHandler(captured),
		WithFlags(
			StringFlag("name", "a name", Optional()),
			IntFlag("count", "a count", Optional()),
			FloatFlag("weight", "a weight", Optional()),
			StringFlag("keep-going", "carry on", Optional()),
			ListFlag(TypeStr, "tag", "a tag", Unique(false), Default([]interface{}{})),
			DictFlag(TypeStr, "header", "a header", Unique(false), Default(map[string]interface{}{})),
			ChoiceFlag("via", "delivery channel", Default("none"),
				Choice("none", "no delivery"),
				Choice("email", "an email message",
					IntFlag("retries", "how many", Required()),
					BoolFlag("strict", "fail on a soft bounce", Default(false)),
					FloatFlag("ratio", "the sampling ratio", Default(1.0)),
				),
			),
			MemberChoiceFlag("mode", "which profiles", Required(),
				MemberChoice(StringFlag("profile", "a profile", Required()), "one named profile"),
				MemberChoice(BoolFlag("all-profiles", "every profile", Required()), "every profile"),
			),
		),
		WithArgs(
			NewArg("target", "what to run", ArgType(TypeStr), ArgRequired()),
			NewArg("amount", "how many", ArgType(TypeInt), ArgOptional()),
		),
		WithEffect(EffectReadOnly))
	return app
}

// flatRefusal runs one flat call and returns its refusal.
func flatRefusal(t *testing.T, kwargs map[string]interface{}) string {
	t.Helper()
	var captured map[string]interface{}
	ir := preTypedApp(&captured).invoke("run", kwargs)
	if ir.err == "" {
		t.Fatalf("kwargs %v were accepted; want a refusal", kwargs)
	}
	return ir.err
}

// flatAccepted runs one flat call that must succeed and returns the kwargs the
// handler received.
func flatAccepted(t *testing.T, kwargs map[string]interface{}) map[string]interface{} {
	t.Helper()
	var captured map[string]interface{}
	ir := preTypedApp(&captured).invoke("run", kwargs)
	if ir.err != "" {
		t.Fatalf("kwargs %v were refused with %q", kwargs, ir.err)
	}
	return captured
}

func wantRefusal(t *testing.T, got, want string) {
	t.Helper()
	if got != want {
		t.Fatalf("error = %q, want %q", got, want)
	}
}

// base is every key a call needs before the one under test is added.
func base(extra map[string]interface{}) map[string]interface{} {
	kwargs := map[string]interface{}{"target": "t", "all_profiles": true}
	for k, v := range extra {
		kwargs[k] = v
	}
	return kwargs
}

// ---------------------------------------------------------------------------
// A member's payload (§24.11): the value under the member's own key
// ---------------------------------------------------------------------------

func TestPreTypedNullMemberPayloadIsRefused(t *testing.T) {
	kwargs := map[string]interface{}{"target": "t", "mode": "profile", "profile": nil}
	wantRefusal(t, flatRefusal(t, kwargs), "--profile: expected string, got null")
}

func TestPreTypedAbsentMemberPayloadKeepsItsOwnSentence(t *testing.T) {
	kwargs := map[string]interface{}{"target": "t", "mode": "profile"}
	wantRefusal(t, flatRefusal(t, kwargs), "flag '--profile' requires a value")
}

func TestPreTypedWrongTypedMemberPayloadIsRefused(t *testing.T) {
	kwargs := map[string]interface{}{"target": "t", "profile": 42}
	wantRefusal(t, flatRefusal(t, kwargs), "--profile: expected string, got int")
}

func TestPreTypedBoolIsNotAStringPayload(t *testing.T) {
	kwargs := map[string]interface{}{"target": "t", "profile": true}
	wantRefusal(t, flatRefusal(t, kwargs), "--profile: expected string, got bool")
}

// ---------------------------------------------------------------------------
// A scoped flag (§24.3's value phase, running over pre-typed values)
// ---------------------------------------------------------------------------

func TestPreTypedNullScopedFlagIsRefused(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"via": "email", "retries": nil,
	})), "--retries: expected integer, got null")
}

func TestPreTypedWrongTypedScopedFlagIsRefused(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"via": "email", "retries": "3",
	})), "--retries: expected integer, got str")
}

func TestPreTypedScopedBoolRefusesATruthyInt(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"via": "email", "retries": 1, "strict": 1,
	})), "--strict: expected boolean, got int")
}

func TestPreTypedScopedFloatTakesAnIntAndWidensIt(t *testing.T) {
	captured := flatAccepted(t, base(map[string]interface{}{
		"via": "email", "retries": 1, "ratio": 2,
	}))
	el, ok := captured["via"].(*Elected)
	if !ok {
		t.Fatalf("via = %T, want *Elected", captured["via"])
	}
	if got, ok := el.Fields["ratio"].(float64); !ok || got != 2.0 {
		t.Fatalf("ratio = %#v, want float64(2)", el.Fields["ratio"])
	}
}

func TestPreTypedScopedIntRefusesAFloat(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"via": "email", "retries": 1.5,
	})), "--retries: expected integer, got float")
}

// ---------------------------------------------------------------------------
// The command's own root flags
// ---------------------------------------------------------------------------

func TestPreTypedNullRootFlagIsRefusedWhereTheDeclarationIsNotOptional(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"tag": nil})),
		"--tag: expected array for list flag, got null")
}

func TestPreTypedOptionalRootFlagRefusesAnExplicitNullToo(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"name": nil})),
		"--name: expected string, got null")
}

func TestPreTypedOmittedOptionalRootFlagIsDeliveredAbsent(t *testing.T) {
	captured := flatAccepted(t, base(nil))
	if v, ok := captured["name"]; !ok || v != nil {
		t.Fatalf("name = %#v (present=%v), want a present nil", v, ok)
	}
}

func TestPreTypedWrongTypedRootFlagIsRefused(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"count": "7"})),
		"--count: expected integer, got str")
}

func TestPreTypedBoolIsNotAnInteger(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"count": true})),
		"--count: expected integer, got bool")
}

func TestPreTypedRootFloatTakesAnIntAndWidensIt(t *testing.T) {
	captured := flatAccepted(t, base(map[string]interface{}{"weight": 3}))
	if got, ok := captured["weight"].(float64); !ok || got != 3.0 {
		t.Fatalf("weight = %#v, want float64(3)", captured["weight"])
	}
}

func TestPreTypedListRootFlagRefusesAScalar(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"tag": "one"})),
		"--tag: expected array for list flag, got str")
}

func TestPreTypedListRootFlagRefusesAWrongTypedElement(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"tag": []interface{}{"one", 2},
	})), "--tag: element 1: expected str, got int")
}

func TestPreTypedDictRootFlagRefusesAScalar(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"header": "k=v"})),
		`dict flag "header": expected map type, got string`)
}

func TestPreTypedDictRootFlagRefusesAWrongTypedValue(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"header": map[string]interface{}{"k": 2},
	})), `--header: key "k": expected str, got int`)
}

// A typed Go map is the same declaration seen through Go's own idiom, and the
// declaration decides the same way for it.
func TestPreTypedDictRootFlagTakesATypedGoMap(t *testing.T) {
	captured := flatAccepted(t, base(map[string]interface{}{
		"header": map[string]string{"k": "v"},
	}))
	got, ok := captured["header"].(map[string]interface{})
	if !ok || got["k"] != "v" {
		t.Fatalf("header = %#v, want map[k:v]", captured["header"])
	}
}

func TestPreTypedListRootFlagTakesATypedGoSlice(t *testing.T) {
	captured := flatAccepted(t, base(map[string]interface{}{
		"tag": []string{"one", "two"},
	}))
	got, ok := captured["tag"].([]interface{})
	if !ok || len(got) != 2 || got[0] != "one" {
		t.Fatalf("tag = %#v, want [one two]", captured["tag"])
	}
}

// ---------------------------------------------------------------------------
// An app-level global is a declaration like any other (§24.11)
// ---------------------------------------------------------------------------

func TestPreTypedGlobalFlagIsCheckedToo(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"timeout": "30"})),
		"--timeout: expected integer, got str")
}

func TestPreTypedNullGlobalFlagIsRefused(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"timeout": nil})),
		"--timeout: expected integer, got null")
}

// ---------------------------------------------------------------------------
// Positional args are declarations too (no stringification)
// ---------------------------------------------------------------------------

func TestPreTypedPositionalRefusesAnIntForAStringArg(t *testing.T) {
	kwargs := map[string]interface{}{"target": 5, "all_profiles": true}
	wantRefusal(t, flatRefusal(t, kwargs), "argument 'target': expected string, got int")
}

func TestPreTypedPositionalRefusesANull(t *testing.T) {
	kwargs := map[string]interface{}{"target": nil, "all_profiles": true}
	wantRefusal(t, flatRefusal(t, kwargs), "argument 'target': expected string, got null")
}

func TestPreTypedPositionalRefusesANumeralsText(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"amount": "7"})),
		"argument 'amount': expected integer, got str")
}

func TestPreTypedPositionalRefusesABoolForAnIntArg(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"amount": true})),
		"argument 'amount': expected integer, got bool")
}

func TestPreTypedPositionalTakesTheDeclaredType(t *testing.T) {
	captured := flatAccepted(t, base(map[string]interface{}{"amount": 3}))
	if captured["amount"] != 3 {
		t.Fatalf("amount = %#v, want 3", captured["amount"])
	}
}

func TestPreTypedOmittedOptionalPositionalIsDeliveredAbsent(t *testing.T) {
	captured := flatAccepted(t, base(nil))
	if v, ok := captured["amount"]; !ok || v != nil {
		t.Fatalf("amount = %#v (present=%v), want a present nil", v, ok)
	}
}

// A key names the arg it names: supplying the second positional and omitting
// the first leaves the first ABSENT, rather than sliding the second into its
// place and refusing the value the caller never supplied for it.
func TestPreTypedPositionalBindsByNameNotByPosition(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"amount": 3, "all_profiles": true,
	}), "missing required argument 'target'")
}

// A variadic arg's elements are checked one by one, in the order they were
// given, which is the one order an array has.
func TestPreTypedVariadicPositionalChecksEveryElement(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(&captured),
		WithArgs(NewArg("nums", "some numbers", ArgType(TypeListInt), Variadic(), ArgOptional())),
		WithEffect(EffectReadOnly))
	ir := app.invoke("run", map[string]interface{}{"nums": []interface{}{1, "2"}})
	wantRefusal(t, ir.err, "argument 'nums': expected integer, got str")
}

// ---------------------------------------------------------------------------
// Where a value refusal sits among the phases (§24.3, staging)
// ---------------------------------------------------------------------------

func TestPreTypedElectionRefusalOutranksAValueRefusal(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"target": "t", "profile": "work", "all_profiles": true, "count": "7",
	}), flatDoubleElection)
}

func TestPreTypedScopedValueRefusalOutranksARootOne(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"via": "email", "retries": "3", "count": "7",
	})), "--retries: expected integer, got str")
}

func TestPreTypedValueRefusalOutranksAMissingRequiredFlag(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"via": "email", "strict": "yes",
	})), "--strict: expected boolean, got str")
}

// ---------------------------------------------------------------------------
// An unknown key is SHAPE, and shape precedes every phase (§24.3, §24.11)
//
// On the command line an unknown flag outranks every election, scope, value and
// presence problem wherever it sits in argv. The flat object's unknown key is
// the same fact about the same command, so it reports first there too -- and a
// selector property naming no declared choice is refused inside the declaration
// walk, which is a PHASE, so it loses to the shape fact beside it.
// ---------------------------------------------------------------------------

const preTypedUnknownBogus = `unknown parameter "bogus" for command "run"`

func TestPreTypedUnknownKeyOutranksAnInvalidSelectorValue(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"target": "t", "mode": "nope", "bogus": 1,
	}), preTypedUnknownBogus)
}

func TestPreTypedInvalidSelectorValueKeepsItsOwnSentenceAlone(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{"target": "t", "mode": "nope"}),
		"--mode: invalid value 'nope', must be one of: profile, all-profiles")
}

func TestPreTypedUnknownKeyOutranksAMissingElection(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{"target": "t", "bogus": 1}),
		preTypedUnknownBogus)
}

func TestPreTypedUnknownKeyOutranksADoubleElection(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"target": "t", "profile": "work", "all_profiles": true, "bogus": 1,
	}), preTypedUnknownBogus)
}

func TestPreTypedUnknownKeyOutranksAScopeViolation(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"retries": 3, "bogus": 1,
	})), preTypedUnknownBogus)
}

func TestPreTypedUnknownKeyOutranksAMissingMemberPayload(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"target": "t", "mode": "profile", "bogus": 1,
	}), preTypedUnknownBogus)
}

func TestPreTypedUnknownKeyOutranksAValueRefusal(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"count": "7", "bogus": 1,
	})), preTypedUnknownBogus)
}

// The claim is about the parser rather than one door: the same states report
// the unknown token on the command line too.
func TestPreTypedCommandLineStagesAnUnknownFlagTheSameWay(t *testing.T) {
	var captured map[string]interface{}
	for _, argv := range [][]string{
		{"run", "--nope", "t", "--all-profiles"},
		{"run", "--nope", "t", "--profile", "work", "--all-profiles"},
		{"run", "--nope", "t", "--all-profiles", "--retries", "3"},
		{"run", "--nope", "t", "--profile"},
		{"run", "--all-profiles", "t", "--count", "abc", "--nope"},
	} {
		r := preTypedApp(&captured).Test(argv)
		if r.ExitCode != 1 {
			t.Fatalf("argv %v exit = %d, want 1", argv, r.ExitCode)
		}
		if want := "error: unknown flag '--nope'\n"; !strings.Contains(r.Stderr, want) {
			t.Fatalf("argv %v stderr = %q, want it to contain %q", argv, r.Stderr, want)
		}
	}
}

// A scoped flag's own key is a property of the flat schema at every depth, so
// supplying one is a SCOPE question and never a shape one.
func TestPreTypedScopedKeyIsNotUnknownAtTheFlatBoundary(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{"retries": 3})),
		"flag '--retries' is only valid under '--via email', but '--via none' was elected by default")
}

// ---------------------------------------------------------------------------
// A dash-spelled key names nothing (§24.11: the boundary publishes parameters)
//
// The flat schema's property for a flag is its PARAMETER name -- underscored,
// exactly as a handler receives it -- so the flag's own dashed spelling is a
// key the command does not declare, and it is refused rather than silently
// dropped.
// ---------------------------------------------------------------------------

func TestPreTypedDashSpelledMemberKeyIsUnknown(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"target": "t", "all-profiles": false,
	}), `unknown parameter "all-profiles" for command "run"`)
}

func TestPreTypedDashSpelledElectingMemberKeyIsUnknown(t *testing.T) {
	wantRefusal(t, flatRefusal(t, map[string]interface{}{
		"target": "t", "all-profiles": true,
	}), `unknown parameter "all-profiles" for command "run"`)
}

func TestPreTypedDashSpelledRootFlagKeyIsUnknown(t *testing.T) {
	wantRefusal(t, flatRefusal(t, base(map[string]interface{}{
		"keep-going": "yes",
	})), `unknown parameter "keep-going" for command "run"`)
}

func TestPreTypedUnderscoredRootFlagKeyIsTheOneThatWorks(t *testing.T) {
	captured := flatAccepted(t, base(map[string]interface{}{"keep_going": "yes"}))
	if captured["keep_going"] != "yes" {
		t.Fatalf("keep_going = %#v, want \"yes\"", captured["keep_going"])
	}
}

func TestPreTypedDashSpelledScopedKeyIsUnknown(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "sms", "target": "all-profiles", "phone-number": "555",
	})
	wantRefusal(t, ir.err, `unknown parameter "phone-number" for command "run"`)
}

// A dash-spelled scoped key under a scope that was NOT elected is the same
// shape fact: the key names nothing, so it never reaches scope validation.
func TestPreTypedDashSpelledScopedKeyIsUnknownUnderAnotherScopeToo(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "email", "retries": 3, "target": "all-profiles", "phone-number": "555",
	})
	wantRefusal(t, ir.err, `unknown parameter "phone-number" for command "run"`)
}

func TestPreTypedUnderscoredScopedKeyIsTheOneThatWorks(t *testing.T) {
	var captured map[string]interface{}
	ir := flatTwoSelectorApp(&captured).invoke("run", map[string]interface{}{
		"via": "sms", "target": "all-profiles", "phone_number": "555",
	})
	if ir.err != "" {
		t.Fatalf("invoke error: %s", ir.err)
	}
}

// ---------------------------------------------------------------------------
// The record door answers the same way (§24.11: two doors, one parser)
// ---------------------------------------------------------------------------

func TestPreTypedRecordDoorRefusesAnUnknownKeyFirst(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		return map[string]interface{}{
			"target": "t",
			"mode":   Elect(choiceDeclOf(app, "mode", "profile"), Fields{}),
			"bogus":  1,
		}
	})
	wantRefusal(t, got, preTypedUnknownBogus)
}

func TestPreTypedRecordDoorUnknownKeyOutranksAForeignChoice(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		other := NewApp("other", "1.0.0", "other app")
		other.Command("run", "run it", captureHandler(new(map[string]interface{})),
			WithFlags(MemberChoiceFlag("mode", "which profiles", Required(),
				MemberChoice(StringFlag("profile", "a profile", Required()), "one named profile"),
				MemberChoice(BoolFlag("all-profiles", "every profile", Required()), "every profile"),
			)), WithEffect(EffectReadOnly))
		return map[string]interface{}{
			"target": "t",
			"mode":   Elect(choiceDeclOf(other, "mode", "profile"), Fields{"value": "work"}),
			"bogus":  1,
		}
	})
	wantRefusal(t, got, preTypedUnknownBogus)
}

func TestPreTypedRecordDoorScopeViolationLosesToAnUnknownKey(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		return map[string]interface{}{
			"target":  "t",
			"mode":    Elect(choiceDeclOf(app, "mode", "all-profiles"), Fields{}),
			"retries": 3,
			"bogus":   1,
		}
	})
	wantRefusal(t, got, preTypedUnknownBogus)
}

// ---------------------------------------------------------------------------
// The phase order is the PARSER's, so the record door takes it too
// (§24.11, §24.3, §18.22 item 232)
//
// A door converts every selector's record before it reports anything, so a
// second selector's election refusal is heard over the first record's value,
// presence or scope problem. The command declares a token-spelled selector
// first, so a problem in its record would win any race the phase order did not
// already decide.
// ---------------------------------------------------------------------------

// foreignChoice is a choice declared by another app's identically-shaped
// selector: a record naming it is a record naming no choice THIS selector
// declares, which is an election refusal.
func foreignChoice(t *testing.T) *ChoiceDecl {
	t.Helper()
	other := NewApp("other", "1.0.0", "other app")
	var captured map[string]interface{}
	other.Command("run", "run it", captureHandler(&captured),
		WithFlags(MemberChoiceFlag("target", "which profiles", Required(),
			MemberChoice(StringFlag("other", "another profile", Required()), "one named profile"),
			MemberChoice(BoolFlag("all-profiles", "every profile", Required()), "every profile"),
		)), WithEffect(EffectReadOnly))
	return findChoice(&other.commands["run"].flags[0], "other")
}

const recordForeignChoice = `--target: elected value names choice "other", which is not declared by this choice flag`

// recordDoorStaged runs one record-door call on the two-selector app.
func recordDoorStaged(t *testing.T, viaFields Fields) string {
	t.Helper()
	var captured map[string]interface{}
	app := flatTwoSelectorApp(&captured)
	email := findChoice(&app.commands["run"].flags[1], "email")
	ir := app.invoke("run", map[string]interface{}{
		"via":    Elect(email, viaFields),
		"target": Elect(foreignChoice(t), Fields{"value": "work"}),
	})
	return ir.err
}

func TestRecordDoorElectionOutranksAValueInAnEarlierRecord(t *testing.T) {
	wantRefusal(t, recordDoorStaged(t, Fields{"retries": "nope"}), recordForeignChoice)
}

func TestRecordDoorElectionOutranksAPresenceProblemInAnEarlierRecord(t *testing.T) {
	wantRefusal(t, recordDoorStaged(t, Fields{}), recordForeignChoice)
}

func TestRecordDoorElectionOutranksAScopeProblemInAnEarlierRecord(t *testing.T) {
	wantRefusal(t, recordDoorStaged(t, Fields{"retries": 1, "phone_number": "x"}), recordForeignChoice)
}

// ---------------------------------------------------------------------------
// A required negatable bool inside a scope (§12.13, §18.23 item 239)
//
// The sentence is the ROOT one plus the scope suffix, in that order: the suffix
// names where the requirement lives and follows a complete sentence.
// ---------------------------------------------------------------------------

func TestPreTypedRequiredNegatableBoolInsideAScope(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(&captured),
		WithFlags(
			BoolFlag("strict", "fail hard", Required()),
			ChoiceFlag("via", "delivery channel", Required(),
				Choice("email", "an email message",
					BoolFlag("verify", "verify the address", Required()),
				),
				Choice("sms", "a text message"),
			),
		), WithEffect(EffectReadOnly))
	want := "flag '--verify' must be passed as --verify or --no-verify under '--via email'"
	r := app.Test([]string{"run", "--strict", "--via", "email"})
	if !strings.Contains(r.Stderr, "error: "+want+"\n") {
		t.Fatalf("cli stderr = %q, want it to contain %q", r.Stderr, want)
	}
	ir := app.invoke("run", map[string]interface{}{"strict": true, "via": "email"})
	if ir.err != want {
		t.Fatalf("flat error = %q, want %q", ir.err, want)
	}
	// The root sentence the suffix is appended to, on its own.
	rootWant := "flag '--strict' must be passed as --strict or --no-strict"
	r = app.Test([]string{"run", "--via", "email", "--verify"})
	if !strings.Contains(r.Stderr, "error: "+rootWant+"\n") {
		t.Fatalf("cli stderr = %q, want it to contain %q", r.Stderr, rootWant)
	}
}

// And the origin suffix follows the scope suffix on the same sentence, in item
// 239's order, when the scope was elected by something the reader cannot see.
func TestPreTypedRequiredNegatableBoolInsideAnAmbientlyElectedScope(t *testing.T) {
	t.Setenv("NOTIFY_VIA", "email")
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(&captured),
		WithFlags(
			ChoiceFlag("via", "delivery channel", Required(), Env("NOTIFY_VIA"),
				Choice("email", "an email message",
					BoolFlag("verify", "verify the address", Required()),
				),
				Choice("sms", "a text message"),
			),
		), WithEffect(EffectReadOnly))
	want := "flag '--verify' must be passed as --verify or --no-verify under '--via email' " +
		"(elected from env var 'NOTIFY_VIA')"
	r := app.Test([]string{"run"})
	if !strings.Contains(r.Stderr, "error: "+want+"\n") {
		t.Fatalf("cli stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

// ---------------------------------------------------------------------------
// A variadic arg's absence (§23.3, §24.11 item 244)
// ---------------------------------------------------------------------------

func TestPreTypedEmptyArrayForARequiredVariadicIsTheMissingArgument(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run it", captureHandler(&captured),
		WithArgs(NewArg("nums", "some numbers", ArgType(TypeListInt), Variadic(), ArgRequired())),
		WithEffect(EffectReadOnly))
	ir := app.invoke("run", map[string]interface{}{"nums": []interface{}{}})
	wantRefusal(t, ir.err, "missing required argument 'nums'")
}

// choiceDeclOf finds one declared choice of one selector on the "run" command.
func choiceDeclOf(app *App, selName, chName string) *ChoiceDecl {
	cmd := app.commands["run"]
	for i := range cmd.flags {
		if cmd.flags[i].Name == selName {
			ch := findChoice(&cmd.flags[i], chName)
			if ch == nil {
				panic("no choice " + chName + " on " + selName)
			}
			return ch
		}
	}
	panic("no selector " + selName)
}

// recordRefusal runs one record-door call and returns its refusal. extra is
// merged over the elected record every call needs.
func recordRefusal(t *testing.T, build func(app *App) map[string]interface{}) string {
	t.Helper()
	var captured map[string]interface{}
	app := preTypedApp(&captured)
	ir := app.invoke("run", build(app))
	if ir.err == "" {
		t.Fatalf("the call was accepted; want a refusal")
	}
	return ir.err
}

func TestPreTypedRecordDoorChecksARootValue(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		return map[string]interface{}{
			"target": "t",
			"mode":   Elect(choiceDeclOf(app, "mode", "all-profiles"), Fields{}),
			"count":  "7",
		}
	})
	wantRefusal(t, got, "--count: expected integer, got str")
}

func TestPreTypedRecordDoorChecksAScopedValue(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		return map[string]interface{}{
			"target": "t",
			"mode":   Elect(choiceDeclOf(app, "mode", "all-profiles"), Fields{}),
			"via":    Elect(choiceDeclOf(app, "via", "email"), Fields{"retries": "3"}),
		}
	})
	wantRefusal(t, got, "--retries: expected integer, got str")
}

func TestPreTypedRecordDoorChecksAMemberPayload(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		return map[string]interface{}{
			"target": "t",
			"mode":   Elect(choiceDeclOf(app, "mode", "profile"), Fields{"value": 42}),
		}
	})
	wantRefusal(t, got, "--profile: expected string, got int")
}

func TestPreTypedRecordDoorChecksAPositional(t *testing.T) {
	got := recordRefusal(t, func(app *App) map[string]interface{} {
		return map[string]interface{}{
			"target": 5,
			"mode":   Elect(choiceDeclOf(app, "mode", "all-profiles"), Fields{}),
		}
	})
	wantRefusal(t, got, "argument 'target': expected string, got int")
}
