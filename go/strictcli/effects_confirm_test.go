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

// TestConfirmRunHelper is the child process: it builds a two-command app and
// dispatches through the real CLI path.
func TestConfirmRunHelper(t *testing.T) {
	argv, armed := os.LookupEnv(confirmArgvEnv)
	if !armed {
		t.Skip("helper process; armed only when re-invoked by a confirm test")
	}
	app := NewApp("app", "1.0.0", "confirm fixture")
	app.Command("deploy", "a mutating command",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("deployed")
			return Exit(0)
		}, WithEffect(EffectMutating))
	app.Command("status", "a read_only command",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Info("status ok")
			return Exit(0)
		}, WithEffect(EffectReadOnly))
	app.Passthrough("wrap", "a mutating passthrough",
		func(ctx *Context, name string, args []string, globals map[string]interface{}) int {
			ctx.Info("wrapped")
			return 0
		}, WithEffect(EffectMutating))

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
	if stderr != "error: stdin is not interactive; pass --yes to confirm\n" {
		t.Fatalf("stderr=%q", stderr)
	}
	if strings.Contains(stdout, "deployed") {
		t.Fatal("the handler must not have run")
	}
}

func TestConfirmYesSkipsThePrompt(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "--yes deploy")
	if code != 0 {
		t.Fatalf("expected exit 0, got %d (stderr=%q)", code, stderr)
	}
	if !strings.Contains(stdout, "deployed") {
		t.Fatalf("the handler must have run, stdout=%q", stdout)
	}
	if strings.Contains(stderr, "Proceed?") || strings.Contains(stderr, "not interactive") {
		t.Fatalf("--yes must suppress both the prompt and the non-TTY error, stderr=%q", stderr)
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

func TestConfirmFiresForAMutatingPassthrough(t *testing.T) {
	stdout, stderr, code := runConfirmHelper(t, "wrap --anything")
	if code != 1 {
		t.Fatalf("expected exit 1, got %d (stdout=%q stderr=%q)", code, stdout, stderr)
	}
	if stderr != "error: stdin is not interactive; pass --yes to confirm\n" {
		t.Fatalf("a mutating passthrough is not exempt, stderr=%q", stderr)
	}
	if strings.Contains(stdout, "wrapped") {
		t.Fatal("the passthrough handler must not have run")
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
