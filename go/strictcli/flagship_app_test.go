package strictcli

// A permanent fixture app demonstrating the three flagship preview shapes.
//
// This is the reference the effects regime is judged against:
//
//	(a) `release run`    -- a complete multi-step data-flow preview: a real value
//	    from a pre-mutation observe, carriers forwarded into later effects with
//	    their brands rendered inline, a grant suffix, and a conditional suffix.
//	(b) `release verify` -- honest truncation: the handler branches on a value it
//	    cannot know, so the preview stops with the pinned error instead of
//	    inventing one.
//	(c) `status`         -- a read_only command: observes return bare, real values
//	    in both modes, and the would-do body is always empty.
//
// The observes re-invoke the test binary as a helper process rather than
// shelling out to git, so the fixture is hermetic (no repository, no git
// binary), but the shape is exactly the ratified idempotency idiom: branch on
// an allowlisted observe, which returns a real value even in dry mode.

import (
	"fmt"
	"os"
	"testing"
)

// The helper-process contract. STRICTCLI_ECHO_ACTIVE arms the helper;
// STRICTCLI_ECHO_OUT is what it prints; STRICTCLI_ECHO_CODE is its exit code.
const (
	echoActiveEnv = "STRICTCLI_ECHO_ACTIVE"
	echoOutEnv    = "STRICTCLI_ECHO_OUT"
	echoCodeEnv   = "STRICTCLI_ECHO_CODE"
	echoTestName  = "-test.run=^TestFlagshipEchoHelper$"
)

// TestFlagshipEchoHelper is the observe stand-in. It is a real test function so
// the test binary can re-invoke itself, and it exits before the testing package
// prints its own PASS line so the child's stdout is exactly the echoed text.
func TestFlagshipEchoHelper(t *testing.T) {
	if os.Getenv(echoActiveEnv) == "" {
		t.Skip("helper process; armed only when re-invoked by a fixture observe")
	}
	fmt.Println(os.Getenv(echoOutEnv))
	code := 0
	if os.Getenv(echoCodeEnv) == "1" {
		code = 1
	}
	os.Exit(code)
}

// echoArgv is the argv every fixture observe uses. The app-level
// proc_observe_allowlist carries exactly this prefix.
func echoArgv() []interface{} {
	return []interface{}{os.Args[0], echoTestName}
}

// echoPrefix is echoArgv as the allowlist declares it.
func echoPrefix() []string {
	return []string{os.Args[0], echoTestName}
}

func echoEnv(out string) EffectOption {
	return EffectEnv(map[string]string{echoActiveEnv: "1", echoOutEnv: out})
}

// buildFlagshipApp builds the fixture app.
func buildFlagshipApp() *App {
	app := NewApp("ship", "1.0.0", "A release tool demonstrating the effects regime",
		WithProcObserveAllowlist([][]string{echoPrefix()}))

	app.Command("status", "Show what a release would start from",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			// An observe returns a real value here in BOTH modes: read_only
			// commands never record anything, so nothing is ever unsettled.
			head, err := ctx.Effects().Run(echoArgv(), echoEnv("a1b2c3d"))
			if err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			dirty, err := ctx.Effects().Run(echoArgv(), echoEnv(""), Check(false))
			if err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			ctx.Info("head: " + head.Stdout())
			ctx.Payload(map[string]interface{}{
				"head":      head.Stdout(),
				"clean":     dirty.Stdout() == "",
				"exit_code": head.ExitCode(),
			})
			return Exit(0)
		}, WithEffect(EffectReadOnly), PayloadSchema(map[string]interface{}{}))

	release := app.Group("release", "Release commands")

	release.Command("run", "Cut a release",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			version := Get[string](kwargs, "version")
			// Real-mode idempotency lives in the handler and branches on an
			// allowlisted observe -- a real value, so the preview walks straight
			// through the `if` instead of truncating.
			head, err := ctx.Effects().Run(echoArgv(), echoEnv("a1b2c3d"), Check(false))
			if err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			if head.ExitCode() != 0 {
				ctx.Error("cannot determine HEAD")
				return Exit(1)
			}

			artifact, err := ctx.Effects().Run(
				[]interface{}{"make", "build", "VERSION=" + version},
				Resource("artifact:"+version))
			if err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			// Forwarding the carrier as CONTENT: there is no byte count to
			// report, so the brand renders in its place.
			if _, err := ctx.Effects().Write("CHANGELOG.md", artifact); err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			if _, err := ctx.Effects().Run(
				[]interface{}{"git", "tag", "v" + version},
				Resource("tag:v"+version)); err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			if _, err := ctx.Effects().Run(
				[]interface{}{"git", "push", "origin", "v" + version},
				UseGrant("push"), Resource("remote:origin")); err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			created, err := ctx.Effects().HTTP(
				"POST", "https://api.github.test/repos/o/r/releases",
				Resource("gh-release:v"+version),
				SkipIfCurrent("gh-release:v"+version))
			if err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			// Forwarding the http carrier into a later argv.
			if _, err := ctx.Effects().Run(
				[]interface{}{"gh", "release", "view", created}); err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			if _, err := ctx.Effects().Spawn(
				[]interface{}{"notify", "--release", "v" + version}); err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			return Exit(0)
		},
		WithEffect(EffectMutating),
		WithGrants(Grant{Name: "push", Reason: "release engine owns remote refs", Kind: ProcMutate}),
		WithArgs(NewArg("version", "The version to release")),
	)

	release.Command("verify", "Verify the last release",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			if _, err := ctx.Effects().Run([]interface{}{"git", "tag", "v9"}); err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			described, err := ctx.Effects().Run([]interface{}{"git", "describe", "--tags"})
			if err != nil {
				ctx.Error(err.Error())
				return Exit(1)
			}
			// Branching on a value nothing produced: the preview ends here.
			if described.ExitCode() == 0 {
				if _, err := ctx.Effects().Run([]interface{}{"echo", "unreachable"}); err != nil {
					ctx.Error(err.Error())
					return Exit(1)
				}
			}
			return Exit(0)
		}, WithEffect(EffectMutating))

	return app
}
