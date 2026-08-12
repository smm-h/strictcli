package strictcli

// End-to-end coverage of the confirm protocol on the real CLI path.
//
// (*App).Run exits the process, so these tests re-invoke the test binary as a
// helper and assert on the child's streams and exit code. Stdin is a pipe there,
// which is precisely the non-interactive case the protocol pins.

import (
	"os"
	"os/exec"
	"strings"
	"testing"
)

const confirmArgvEnv = "STRICTCLI_CONFIRM_ARGV"

// confirmSeamEnv arms the child to install SetConfirmIO, the test-only seam
// that says the answer channel is interactive while leaving the answer itself
// coming from the child's real (piped) stdin. Without it the interactive branch
// is unreachable from a subprocess: a pipe is not a TTY.
const confirmSeamEnv = "STRICTCLI_CONFIRM_SEAM"

// TestConfirmRunHelper is the child process: it builds a two-command app and
// dispatches through the real CLI path.
func TestConfirmRunHelper(t *testing.T) {
	argv, armed := os.LookupEnv(confirmArgvEnv)
	if !armed {
		t.Skip("helper process; armed only when re-invoked by a confirm test")
	}
	app := NewApp("app", "1.0.0", "confirm fixture")
	app.Command("deploy", "a consequential command",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("deployed")
			return Exit(0)
		}, WithEffect(EffectMutating), WithConsequential())
	app.Command("build", "a mutating command that is not consequential",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("built")
			return Exit(0)
		}, WithEffect(EffectMutating))
	app.Command("status", "a read_only command",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("status ok")
			return Exit(0)
		}, WithEffect(EffectReadOnly))
	app.Passthrough("wrap", "a consequential passthrough",
		func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
			ctx.Info("wrapped")
			return 0
		}, WithEffect(EffectMutating), WithConsequential())
	app.Passthrough("thru", "a mutating passthrough that is not consequential",
		func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
			ctx.Info("forwarded")
			return 0
		}, WithEffect(EffectMutating))

	if _, seam := os.LookupEnv(confirmSeamEnv); seam {
		app.SetConfirmIO(&ConfirmIO{
			IsInteractive: func() bool { return true },
			In:            os.Stdin,
		})
	}

	os.Args = append([]string{"app"}, strings.Fields(argv)...)
	app.Run()
}

// runConfirmHelper re-invokes the test binary with the given argv and an empty
// piped stdin.
func runConfirmHelper(t *testing.T, argv string) (stdout, stderr string, code int) {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestConfirmRunHelper$")
	cmd.Env = append(os.Environ(), confirmArgvEnv+"="+argv)
	cmd.Stdin = strings.NewReader("")
	var out, errb strings.Builder
	cmd.Stdout = &out
	cmd.Stderr = &errb
	err := cmd.Run()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			code = exitErr.ExitCode()
		} else {
			t.Fatalf("helper failed: %v", err)
		}
	}
	return out.String(), errb.String(), code
}

func TestConfirmNonInteractiveStdinIsAHardError(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "deploy")
	if code != 1 {
		t.Fatalf("expected exit 1, got %d (stdout=%q stderr=%q)", code, stdout, stderr)
	}
	if stderr != "error: stdin is not interactive; pass --approve-consequential to confirm\n" {
		t.Fatalf("stderr=%q", stderr)
	}
	if strings.Contains(stdout, "deployed") {
		t.Fatal("the handler must not have run")
	}
}

func TestConfirmApprovalSkipsThePrompt(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "--approve-consequential deploy")
	if code != 0 {
		t.Fatalf("expected exit 0, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stdout, "deployed") {
		t.Fatalf("the handler must have run, stdout=%q", stdout)
	}
	if strings.Contains(stderr, "Proceed?") || strings.Contains(stderr, "not interactive") {
		t.Fatalf("--approve-consequential must suppress both the prompt and the non-TTY error, stderr=%q", stderr)
	}
}

// The headline of the redesign: `mutating` alone never prompts. Two thirds of
// the commands in a real fleet classify mutating; the genuinely dangerous ones
// are a small fraction of that.
func TestConfirmNeverFiresForAMutatingCommandThatIsNotConsequential(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "build")
	if code != 0 {
		t.Fatalf("expected exit 0, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stdout, "built") {
		t.Fatalf("the handler must have run, stdout=%q", stdout)
	}
	if stderr != "" {
		t.Fatalf("a mutating command that is not consequential never prompts, stderr=%q", stderr)
	}
}

// `yes` owns no framework flag any more.
func TestYesIsNoLongerARecognizedToken(t *testing.T) {
	_, stderr, code := runConfirmHelper(t, "--yes build")
	if code != 1 {
		t.Fatalf("expected exit 1, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stderr, "--yes") {
		t.Fatalf("expected an unknown-token error naming --yes, stderr=%q", stderr)
	}
}

func TestConfirmDryRunSkipsThePrompt(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "--dry-run deploy")
	if code != 0 {
		t.Fatalf("expected exit 0, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stdout, "DRY RUN — no changes were made. Would do:") {
		t.Fatalf("expected the would-do header, stdout=%q", stdout)
	}
	if strings.Contains(stderr, "not interactive") {
		t.Fatalf("--dry-run must skip the confirm protocol, stderr=%q", stderr)
	}
}

func TestConfirmNeverFiresForReadOnly(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "status")
	if code != 0 {
		t.Fatalf("expected exit 0, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stdout, "status ok") {
		t.Fatalf("stdout=%q", stdout)
	}
	if stderr != "" {
		t.Fatalf("a read_only command never prompts, stderr=%q", stderr)
	}
}

func TestConfirmFiresForAConsequentialPassthrough(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "wrap --anything")
	if code != 1 {
		t.Fatalf("expected exit 1, got %d (stdout=%q stderr=%q)", code, stdout, stderr)
	}
	if stderr != "error: stdin is not interactive; pass --approve-consequential to confirm\n" {
		t.Fatalf("a consequential passthrough is not exempt, stderr=%q", stderr)
	}
	if strings.Contains(stdout, "wrapped") {
		t.Fatal("the passthrough handler must not have run")
	}
}

func TestConfirmNeverFiresForAMutatingPassthroughThatIsNotConsequential(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "thru --anything")
	if code != 0 {
		t.Fatalf("expected exit 0, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stdout, "forwarded") {
		t.Fatalf("the passthrough handler must have run, stdout=%q", stdout)
	}
}

// The confirm answer's line terminator is exactly one "\n" and then exactly one
// "\r" (§8.2). The carriage return matters because a human at a Windows console
// types the same 'y' as everyone else and their terminal terminates the line
// CRLF; declining there would refuse an answer that was plainly given. Only the
// terminator is stripped, never whitespace, so "  y" stays a decline.
func TestConfirmLineTerminatorStripping(t *testing.T) {
	cases := []struct {
		raw  string
		want string
	}{
		{"y\n", "y"},
		{"Y\r\n", "Y"},
		{"y\r", "y"},
		{"y\r\r\n", "y\r"},
		{"y\n\n", "y"},
		{"  y\n", "  y"},
		{"", ""},
	}
	for _, tc := range cases {
		got, _ := readConfirmLine(strings.NewReader(tc.raw))
		if got != tc.want {
			t.Fatalf("readConfirmLine(%q) = %q, want %q", tc.raw, got, tc.want)
		}
	}
}

// runConfirmHelperInteractive re-invokes the test binary with the confirm seam
// installed and the given answer on stdin.
func runConfirmHelperInteractive(t *testing.T, argv, answer string) (stdout, stderr string, code int) {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^TestConfirmRunHelper$")
	cmd.Env = append(os.Environ(), confirmArgvEnv+"="+argv, confirmSeamEnv+"=1")
	cmd.Stdin = strings.NewReader(answer)
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

// The interactive branch end to end, through SetConfirmIO. The seam changes
// WHERE the answer comes from, never WHETHER the protocol runs -- so the prompt
// is still written, an empty answer still declines, and a leading space is
// still a decline.
func TestConfirmIOSeamDrivesTheInteractiveBranch(t *testing.T) {
	const prompt = "about to run consequential command 'deploy'. Proceed? [y/N] "
	cases := []struct {
		answer   string
		wantCode int
		wantErr  string
		ran      bool
	}{
		{"y\n", 0, prompt, true},
		{"Y\n", 0, prompt, true},
		{"y\r\n", 0, prompt, true},
		{"n\n", 1, prompt + "aborted\n", false},
		{"\n", 1, prompt + "aborted\n", false},
		{"  y\n", 1, prompt + "aborted\n", false},
	}
	for _, tc := range cases {
		stdout, stderr, code := runConfirmHelperInteractive(t, "deploy", tc.answer)
		if code != tc.wantCode {
			t.Fatalf("answer %q: exit %d, want %d (stderr=%q)", tc.answer, code, tc.wantCode, stderr)
		}
		if stderr != tc.wantErr {
			t.Fatalf("answer %q: stderr=%q, want %q", tc.answer, stderr, tc.wantErr)
		}
		if got := strings.Contains(stdout, "deployed"); got != tc.ran {
			t.Fatalf("answer %q: handler ran=%v, want %v", tc.answer, got, tc.ran)
		}
	}
}

// nil restores the real stdin reader, so a piped stdin is non-interactive again.
func TestConfirmIOSeamNilRestoresTheRealReader(t *testing.T) {
	app := NewApp("app", "1.0.0", "app")
	app.SetConfirmIO(&ConfirmIO{IsInteractive: func() bool { return true }, In: strings.NewReader("y\n")})
	if app.confirmIO == nil {
		t.Fatal("the seam must be installed")
	}
	app.SetConfirmIO(nil)
	if app.confirmIO != nil {
		t.Fatal("nil must restore the real stdin reader")
	}
}
