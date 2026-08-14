package strictcli

import (
	"fmt"
	"strings"
	"testing"
)

// Mutex election semantics (effects contract §21; campaign rulings A1-A5).
//
// A bool member elects only when its typed token resolves to true, every
// other type elects on presence with any value, election is command-line
// only, and the two decline-shaped errors carry the teaching clause.

// electionApp builds one mixed group: str + two negatable bools.
func electionApp() *App {
	return simpleApp("run", "run it",
		"profile={profile} all={all_profiles} current={current_profile}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				StringFlag("profile", "a profile", Optional()),
				BoolFlag("all-profiles", "every profile", Optional()),
				BoolFlag("current-profile", "the current profile", Optional()),
			},
		}))
}

func TestMutexA1NegatedBoolElectsNothing(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run", "--no-all-profiles"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d: stdout=%q", r.ExitCode, r.Stdout)
	}
	want := "error: one of --profile, --all-profiles, --current-profile is required " +
		"(--no-all-profiles declines an option; it does not choose one)\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

func TestMutexA1TrueBoolStillElects(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run", "--all-profiles"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "profile=None all=true current=None") {
		t.Fatalf("stdout = %q", r.Stdout)
	}
}

func TestMutexA1AllMembersDeclined(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run", "--no-current-profile", "--no-all-profiles"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	want := "error: one of --profile, --all-profiles, --current-profile is required " +
		"(--no-all-profiles declines an option; it does not choose one)\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

func TestMutexA2StringElectsOnEmptyString(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run", "--profile", ""})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "profile= all=None current=None") {
		t.Fatalf("stdout = %q", r.Stdout)
	}
}

func TestMutexA3ClauseAbsentWhenNothingDeclined(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	want := "error: one of --profile, --all-profiles, --current-profile is required\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

func TestMutexA4RedundantNegation(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run", "--profile", "work", "--no-all-profiles"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	want := "error: --no-all-profiles cannot be combined with --profile " +
		"(--no-all-profiles declines an option; it does not choose one)\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

func TestMutexA4MultipleDeclinedMembers(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{
		"run", "--profile", "work", "--no-current-profile", "--no-all-profiles",
	})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	want := "error: --no-all-profiles and --no-current-profile cannot be combined " +
		"with --profile (--no-all-profiles declines an option; it does not choose one)\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

func TestMutexTwoElectionsStillMutuallyExclusive(t *testing.T) {
	app := electionApp()
	r := app.Test([]string{"run", "--profile", "work", "--all-profiles"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	want := "error: --profile and --all-profiles are mutually exclusive\n"
	if !strings.Contains(r.Stderr, want) {
		t.Fatalf("stderr = %q, want it to contain %q", r.Stderr, want)
	}
}

func TestMutexA5EnvDoesNotElect(t *testing.T) {
	t.Setenv("TEST_FILE_A5", "data.txt")
	app := simpleApp("fetch", "fetch data", "file={file} url={url}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				StringFlag("file", "read from file", Optional(),
					Env("TEST_FILE_A5"), Prefixed(false)),
				StringFlag("url", "read from URL", Optional()),
			},
		}))
	r := app.Test([]string{"fetch"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d: stdout=%q", r.ExitCode, r.Stdout)
	}
	if !strings.Contains(r.Stderr, "error: one of --file, --url is required\n") {
		t.Fatalf("stderr = %q", r.Stderr)
	}
}

func TestMutexA5EnvValueSuppressedBesideAnElection(t *testing.T) {
	t.Setenv("TEST_FILE_A5B", "data.txt")
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("fetch", "fetch data", func(ctx *Context, args map[string]interface{}) Outcome {
		fmt.Print("file=" + formatValue(args["file"]) +
			" url=" + formatValue(args["url"]) +
			" file_source=" + ctx.Source("file"))
		return Exit(0)
	}, WithEffect(EffectReadOnly), WithMutex(MutexGroup{
		Flags: []Flag{
			StringFlag("file", "read from file", Optional(),
				Env("TEST_FILE_A5B"), Prefixed(false)),
			StringFlag("url", "read from URL", Optional()),
		},
	}))
	r := app.Test([]string{"fetch", "--url", "http://example.com"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	want := "file=None url=http://example.com file_source=default"
	if !strings.Contains(r.Stdout, want) {
		t.Fatalf("stdout = %q, want it to contain %q", r.Stdout, want)
	}
}

func TestMutexA5ConfigDoesNotElect(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	writeConfig(t, tmpDir, "testapp", map[string]interface{}{"file": "from-config.txt"})

	makeApp := func() *App {
		app := NewApp("testapp", "1.0.0", "test app", WithConfig())
		app.Command("fetch", "fetch data", func(ctx *Context, args map[string]interface{}) Outcome {
			fmt.Print("file=" + formatValue(args["file"]) +
				" url=" + formatValue(args["url"]))
			return Exit(0)
		}, WithMutex(MutexGroup{
			Flags: []Flag{
				StringFlag("file", "read from file", Optional()),
				StringFlag("url", "read from URL", Optional()),
			},
		}), WithEffect(EffectReadOnly))
		return app
	}

	// A config value elects nothing, so the group is unsatisfied.
	r := makeApp().Test([]string{"fetch"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d: stdout=%q", r.ExitCode, r.Stdout)
	}
	if !strings.Contains(r.Stderr, "error: one of --file, --url is required\n") {
		t.Fatalf("stderr = %q", r.Stderr)
	}

	// Beside a real election the config value is suppressed, not delivered.
	r = makeApp().Test([]string{"fetch", "--url", "u"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "file=None url=u") {
		t.Fatalf("stdout = %q", r.Stdout)
	}
}

func TestMutexA1CallWithFalseBoolDeclines(t *testing.T) {
	app := electionApp()
	_, err := app.Call("run", map[string]interface{}{"all_profiles": false})
	if err == nil {
		t.Fatal("expected an error from Call, got nil")
	}
	if !strings.Contains(
		err.Error(),
		"one of --profile, --all-profiles, --current-profile is required",
	) {
		t.Fatalf("error = %q", err.Error())
	}
	if !strings.Contains(err.Error(), "declines an option") {
		t.Fatalf("error = %q, want the teaching clause", err.Error())
	}
}

func TestMutexDeclaredDefaultStillApplies(t *testing.T) {
	app := simpleApp("cmd", "a command", "loud={loud} hushed={hushed}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("loud", "loud output", Default(false)),
				BoolFlag("hushed", "hushed output", Default(false)),
			},
		}))
	r := app.Test([]string{"cmd", "--loud"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "loud=true hushed=false") {
		t.Fatalf("stdout = %q", r.Stdout)
	}
}
