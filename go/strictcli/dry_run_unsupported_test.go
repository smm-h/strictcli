package strictcli

// Coverage of the `dry_run_supported=false` command declaration: the two
// registration-time guards (read_only prohibition, mandatory reason), the
// parse-time refusal on both the Test() and the real Run() argv path, --help
// precedence over the refusal, the `Dry run:` help section, and the
// emit-when-declared schema pair.

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

const dryRunReason = "the engine re-reads what its earlier steps wrote, so a preview lies"

// newDryRunApp builds the fixture: one refusing command, one ordinary mutating
// command, one refusing command inside a group, and one refusing passthrough.
func newDryRunApp() *App {
	app := NewApp("app", "1.0.0", "dry-run refusal fixture")
	app.Command("run", "run the release",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("ran")
			return Exit(0)
		}, WithEffect(EffectMutating), WithDryRunUnsupported(dryRunReason))
	app.Command("plan", "plan the release",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("planned")
			return Exit(0)
		}, WithEffect(EffectMutating))
	rel := app.Group("rel", "release group")
	rel.Command("run", "run the release",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("ran")
			return Exit(0)
		}, WithEffect(EffectMutating), WithDryRunUnsupported(dryRunReason))
	app.Passthrough("wrap", "forward to a child",
		func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
			ctx.Info("wrapped")
			return 0
		}, WithEffect(EffectMutating), WithDryRunUnsupported(dryRunReason))
	return app
}

// --- registration validation ---

func TestDryRunUnsupportedIsIllegalOnAReadOnlyCommand(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected a panic")
		}
		want := `command "show": a read_only command cannot declare dry_run_supported=false (a command that changes nothing has no effects a preview could misrepresent)`
		if got, _ := r.(string); got != want {
			t.Fatalf("panic = %q, want %q", got, want)
		}
	}()
	app := NewApp("app", "1.0.0", "app")
	app.Command("show", "show",
		func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithEffect(EffectReadOnly), WithDryRunUnsupported(dryRunReason))
}

func TestDryRunUnsupportedIsIllegalOnAReadOnlyPassthrough(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatal("expected a panic")
		}
	}()
	app := NewApp("app", "1.0.0", "app")
	app.Passthrough("show", "show",
		func(ctx *Context, name string, args []string, globals map[string]interface{}) int { return 0 },
		WithEffect(EffectReadOnly), WithDryRunUnsupported(dryRunReason))
}

func TestDryRunUnsupportedRequiresANonEmptyReason(t *testing.T) {
	for _, reason := range []string{"", "   "} {
		func() {
			defer func() {
				r := recover()
				if r == nil {
					t.Fatalf("expected a panic for reason %q", reason)
				}
				want := `command "run": dry_run_supported=false requires a non-empty dry_run_unsupported_reason (say what a preview cannot honestly show)`
				if got, _ := r.(string); got != want {
					t.Fatalf("panic = %q, want %q", got, want)
				}
			}()
			app := NewApp("app", "1.0.0", "app")
			app.Command("run", "run",
				func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
				WithEffect(EffectMutating), WithDryRunUnsupported(reason))
		}()
	}
}

// The orphan state: a reason with no declaration. WithDryRunUnsupported always
// sets both fields, but Command's fields are exported and CmdOption is a plain
// func(*Command), so a caller can reach it -- and used to reach it silently,
// with --dry-run honored while the author believed it refused.
func TestDryRunReasonWithoutTheDeclarationIsRejected(t *testing.T) {
	for _, name := range []string{"run", "shell"} {
		func() {
			defer func() {
				r := recover()
				if r == nil {
					t.Fatalf("expected a panic for %q", name)
				}
				want := `command "` + name + `": dry_run_unsupported_reason requires dry_run_supported=false (there is nothing to explain while dry run is supported)`
				if got, _ := r.(string); got != want {
					t.Fatalf("panic = %q, want %q", got, want)
				}
			}()
			orphan := func(c *Command) { c.DryRunUnsupportedReason = dryRunReason }
			app := NewApp("app", "1.0.0", "app")
			if name == "shell" {
				app.Passthrough(name, "raw",
					func(ctx *Context, n string, args []string, globals map[string]interface{}) int { return 0 },
					WithEffect(EffectMutating), orphan)
				return
			}
			app.Command(name, "run",
				func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
				WithEffect(EffectMutating), orphan)
		}()
	}
}

func TestDryRunIsSupportedByDefault(t *testing.T) {
	app := newDryRunApp()
	if !app.commands["plan"].DryRunSupported {
		t.Fatal("an undeclared command must support dry run")
	}
	if app.commands["plan"].DryRunUnsupportedReason != "" {
		t.Fatal("an undeclared command must carry no reason")
	}
	if app.commands["run"].DryRunSupported {
		t.Fatal("a declaring command must not support dry run")
	}
}

// --- parse-time refusal (Test() path) ---

func TestDryRunRefusalOnBothFlagPositions(t *testing.T) {
	for _, argv := range [][]string{
		{"--dry-run", "run"},
		{"run", "--dry-run"},
	} {
		res := newDryRunApp().Test(argv)
		if res.ExitCode != 1 {
			t.Fatalf("argv=%v: exit=%d, want 1", argv, res.ExitCode)
		}
		want := "error: --dry-run is not supported by command 'run': " + dryRunReason + "\ntry 'app --help'\n"
		if res.Stderr != want {
			t.Fatalf("argv=%v: stderr=%q, want %q", argv, res.Stderr, want)
		}
		if res.Stdout != "" {
			t.Fatalf("argv=%v: the handler must not have run, stdout=%q", argv, res.Stdout)
		}
	}
}

func TestDryRunRefusalNamesTheDottedPathInAGroup(t *testing.T) {
	res := newDryRunApp().Test([]string{"rel", "run", "--dry-run"})
	if res.ExitCode != 1 {
		t.Fatalf("exit=%d, want 1", res.ExitCode)
	}
	want := "error: --dry-run is not supported by command 'rel.run': " + dryRunReason
	if !strings.Contains(res.Stderr, want) {
		t.Fatalf("stderr=%q, want it to contain %q", res.Stderr, want)
	}
}

func TestDryRunRefusalAppliesToAPassthroughCommand(t *testing.T) {
	// Pre-command position only: after a passthrough command's name the
	// quartet belongs to the child process and is never scanned.
	res := newDryRunApp().Test([]string{"--dry-run", "wrap"})
	if res.ExitCode != 1 {
		t.Fatalf("exit=%d, want 1 (stderr=%q)", res.ExitCode, res.Stderr)
	}
	if !strings.Contains(res.Stderr, "--dry-run is not supported by command 'wrap'") {
		t.Fatalf("stderr=%q", res.Stderr)
	}
}

func TestDryRunPassthroughAsymmetryLeavesATrailingFlagToTheChild(t *testing.T) {
	res := newDryRunApp().Test([]string{"wrap", "--dry-run"})
	if res.ExitCode != 0 {
		t.Fatalf("exit=%d, want 0 (stderr=%q)", res.ExitCode, res.Stderr)
	}
	if !strings.Contains(res.Stdout, "wrapped") {
		t.Fatalf("the handler must have run, stdout=%q", res.Stdout)
	}
}

func TestDryRunBareDoubleDashTerminatesTheScan(t *testing.T) {
	// After `--` the token is positional data, not the quartet: the command
	// takes no positionals, so it fails as an unexpected argument rather than
	// as a dry-run refusal.
	res := newDryRunApp().Test([]string{"run", "--", "--dry-run"})
	if !strings.HasPrefix(res.Stderr, "error: unexpected argument '--dry-run'") {
		t.Fatalf("stderr=%q", res.Stderr)
	}
	if strings.Contains(res.Stderr, "is not supported by command") {
		t.Fatalf("stderr=%q", res.Stderr)
	}
}

func TestDryRunStillWorksForASupportingCommand(t *testing.T) {
	res := newDryRunApp().Test([]string{"plan", "--dry-run"})
	if res.ExitCode != 0 {
		t.Fatalf("exit=%d, want 0 (stderr=%q)", res.ExitCode, res.Stderr)
	}
	if !strings.Contains(res.Stdout, "planned") {
		t.Fatalf("stdout=%q", res.Stdout)
	}
}

func TestWithoutDryRunTheRefusingCommandRuns(t *testing.T) {
	res := newDryRunApp().Test([]string{"run"})
	if res.ExitCode != 0 {
		t.Fatalf("exit=%d, want 0 (stderr=%q)", res.ExitCode, res.Stderr)
	}
	if !strings.Contains(res.Stdout, "ran") {
		t.Fatalf("stdout=%q", res.Stdout)
	}
}

// --- parse-time refusal (real Run() path) ---

const dryRunArgvEnv = "STRICTCLI_DRY_RUN_ARGV"

// TestDryRunRunHelper is the child process: it dispatches the fixture through
// the real CLI path, which exits the process.
func TestDryRunRunHelper(t *testing.T) {
	argv, armed := os.LookupEnv(dryRunArgvEnv)
	if !armed {
		t.Skip("helper process; armed only when re-invoked by a dry-run test")
	}
	app := newDryRunApp()
	os.Args = append([]string{"app"}, strings.Fields(argv)...)
	app.Run()
}

func runDryRunHelper(t *testing.T, argv string) (stdout, stderr string, code int) {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestDryRunRunHelper$")
	cmd.Env = append(os.Environ(), dryRunArgvEnv+"="+argv)
	cmd.Stdin = strings.NewReader("")
	var out, errb strings.Builder
	cmd.Stdout = &out
	cmd.Stderr = &errb
	if err := cmd.Run(); err != nil {
		exitErr, ok := err.(*exec.ExitError)
		if !ok {
			t.Fatalf("helper failed: %v", err)
		}
		code = exitErr.ExitCode()
	}
	return out.String(), errb.String(), code
}

func TestDryRunRefusalOnTheRealArgvPath(t *testing.T) {
	stdout, stderr, code := runDryRunHelper(t, "run --dry-run")
	if code != 1 {
		t.Fatalf("exit=%d, want 1 (stdout=%q stderr=%q)", code, stdout, stderr)
	}
	want := "error: --dry-run is not supported by command 'run': " + dryRunReason
	if !strings.Contains(stderr, want) {
		t.Fatalf("stderr=%q, want it to contain %q", stderr, want)
	}
	if strings.Contains(stdout, "ran") {
		t.Fatal("the handler must not have run")
	}
}

// --- --help precedence ---

func TestHelpBeatsTheDryRunRefusal(t *testing.T) {
	for _, argv := range [][]string{
		{"run", "--dry-run", "--help"},
		{"run", "--help", "--dry-run"},
		{"--dry-run", "run", "-h"},
	} {
		res := newDryRunApp().Test(argv)
		if res.ExitCode != 0 {
			t.Fatalf("argv=%v: exit=%d, want 0 (stderr=%q)", argv, res.ExitCode, res.Stderr)
		}
		if !strings.HasPrefix(res.Stdout, "app run -- run the release") {
			t.Fatalf("argv=%v: stdout=%q", argv, res.Stdout)
		}
		if strings.Contains(res.Stderr, "is not supported by command") {
			t.Fatalf("argv=%v: stderr=%q", argv, res.Stderr)
		}
	}
}

// --- help rendering ---

func TestDryRunHelpSection(t *testing.T) {
	res := newDryRunApp().Test([]string{"run", "--help"})
	want := "app run -- run the release\n\nDry run:\n  --dry-run is not supported: " + dryRunReason + "\n"
	if res.Stdout != want {
		t.Fatalf("stdout=%q, want %q", res.Stdout, want)
	}
}

func TestDryRunHelpSectionOnAPassthroughCommand(t *testing.T) {
	res := newDryRunApp().Test([]string{"wrap", "--help"})
	want := "app wrap -- forward to a child\n\nDry run:\n  --dry-run is not supported: " + dryRunReason + "\n"
	if res.Stdout != want {
		t.Fatalf("stdout=%q, want %q", res.Stdout, want)
	}
}

func TestNoDryRunHelpSectionOnASupportingCommand(t *testing.T) {
	res := newDryRunApp().Test([]string{"plan", "--help"})
	if strings.Contains(res.Stdout, "Dry run:") {
		t.Fatalf("stdout=%q", res.Stdout)
	}
}

// --- schema emission ---

func TestDryRunSchemaEmitsOnlyWhenDeclared(t *testing.T) {
	schema := newDryRunApp().DumpSchemaDict()
	commands, ok := schema["commands"].(map[string]interface{})
	if !ok {
		t.Fatalf("commands is %T", schema["commands"])
	}
	run := commands["run"].(map[string]interface{})
	if run["dry_run_supported"] != false {
		t.Fatalf("run.dry_run_supported = %v, want false", run["dry_run_supported"])
	}
	if run["dry_run_unsupported_reason"] != dryRunReason {
		t.Fatalf("run.dry_run_unsupported_reason = %v", run["dry_run_unsupported_reason"])
	}
	plan := commands["plan"].(map[string]interface{})
	if _, present := plan["dry_run_supported"]; present {
		t.Fatal("an undeclared command must not emit dry_run_supported")
	}
	if _, present := plan["dry_run_unsupported_reason"]; present {
		t.Fatal("an undeclared command must not emit dry_run_unsupported_reason")
	}
}
