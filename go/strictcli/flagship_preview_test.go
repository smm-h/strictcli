package strictcli

// The three flagship preview shapes, asserted byte-for-byte.

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// --- (a) a multi-step preview with forwarding and inline brands -------------

func TestFlagshipPreviewIsCompleteAndByteExact(t *testing.T) {
	app := buildFlagshipApp()
	r := app.Test([]string{"--dry-run", "release", "run", "1.2.3"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	want := "DRY RUN — no changes were made. Would do:\n" +
		"  1. run: make build VERSION=1.2.3\n" +
		"  2. write: CHANGELOG.md («step 1 output»)\n" +
		"  3. run: git tag v1.2.3\n" +
		"  4. run: git push origin v1.2.3" +
		" (granted: push — release engine owns remote refs)\n" +
		"  5. net: POST https://api.github.test/repos/o/r/releases" +
		" [unless resource 'gh-release:v1.2.3' already current]\n" +
		"  6. run: gh release view «step 5 output»\n" +
		"  7. spawn: notify --release v1.2.3\n"
	if r.Stdout != want {
		t.Fatalf("preview mismatch:\n got: %q\nwant: %q", r.Stdout, want)
	}
	if r.Stderr != "" {
		t.Fatalf("expected empty stderr, got %q", r.Stderr)
	}
}

func TestFlagshipNothingExecuted(t *testing.T) {
	dir := t.TempDir()
	cwd, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(cwd)

	buildFlagshipApp().Test([]string{"--dry-run", "release", "run", "1.2.3"})
	if _, err := os.Stat(filepath.Join(dir, "CHANGELOG.md")); !os.IsNotExist(err) {
		t.Fatal("dry mode must not have written CHANGELOG.md")
	}
}

func TestFlagshipStructuredLogCarriesDeclaredMetadata(t *testing.T) {
	app := buildFlagshipApp()
	app.Test([]string{"--dry-run", "release", "run", "1.2.3"})
	want := []map[string]interface{}{
		{"seq": 1, "kind": "proc_mutate", "verb": "run",
			"detail": "make build VERSION=1.2.3", "recorded": true,
			"resource": "artifact:1.2.3"},
		{"seq": 2, "kind": "file_write", "verb": "write",
			"detail": "CHANGELOG.md («step 1 output»)", "recorded": true},
		{"seq": 3, "kind": "proc_mutate", "verb": "run",
			"detail": "git tag v1.2.3", "recorded": true,
			"resource": "tag:v1.2.3"},
		{"seq": 4, "kind": "proc_mutate", "verb": "run",
			"detail": "git push origin v1.2.3", "recorded": true,
			"resource": "remote:origin", "grant": "push"},
		{"seq": 5, "kind": "net_mutate", "verb": "net",
			"detail":   "POST https://api.github.test/repos/o/r/releases",
			"recorded": true, "resource": "gh-release:v1.2.3",
			"skip_if_current": "gh-release:v1.2.3"},
		{"seq": 6, "kind": "proc_mutate", "verb": "run",
			"detail": "gh release view «step 5 output»", "recorded": true},
		{"seq": 7, "kind": "proc_spawn", "verb": "spawn",
			"detail": "notify --release v1.2.3", "recorded": true},
	}
	got := app.EffectLog()
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("effect log mismatch:\n got: %#v\nwant: %#v", got, want)
	}
}

func TestFlagshipPreMutationObserveIsNeverLogged(t *testing.T) {
	app := buildFlagshipApp()
	r := app.Test([]string{"--dry-run", "release", "run", "1.2.3"})
	// The observe ran for real and its result was branched on, but a read is
	// not a change: it appears in neither the rendered nor the structured log.
	if strings.Contains(r.Stdout, echoTestName) {
		t.Fatalf("the observe leaked into the would-do log: %q", r.Stdout)
	}
	for _, rec := range app.EffectLog() {
		if strings.Contains(rec["detail"].(string), echoTestName) {
			t.Fatalf("the observe leaked into the structured log: %#v", rec)
		}
	}
}

// --- (b) branching on an unsettled value stops the preview ------------------

func TestFlagshipTruncationIsByteExact(t *testing.T) {
	app := buildFlagshipApp()
	r := app.Test([]string{"--dry-run", "release", "verify"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	wantOut := "DRY RUN — no changes were made. Would do:\n" +
		"  1. run: git tag v9\n" +
		"  2. run: git describe --tags\n"
	if r.Stdout != wantOut {
		t.Fatalf("stdout mismatch:\n got: %q\nwant: %q", r.Stdout, wantOut)
	}
	wantErr := "error: dry-run preview ends at step 3: release.verify branched on " +
		"unsettled value «step 2 output» — cannot preview past this point\n"
	if r.Stderr != wantErr {
		t.Fatalf("stderr mismatch:\n got: %q\nwant: %q", r.Stderr, wantErr)
	}
}

func TestFlagshipUnreachableStepWasNeverRecorded(t *testing.T) {
	app := buildFlagshipApp()
	app.Test([]string{"--dry-run", "release", "verify"})
	if got := len(app.EffectLog()); got != 2 {
		t.Fatalf("expected 2 records, got %d", got)
	}
}

// --- (c) a read_only command gets real values and an empty would-do body ----

func TestFlagshipReadOnlyBareValuesInLiveMode(t *testing.T) {
	r := buildFlagshipApp().Test([]string{"status"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	want := map[string]interface{}{"head": "a1b2c3d", "clean": true, "exit_code": 0}
	if !reflect.DeepEqual(r.Data, want) {
		t.Fatalf("data mismatch: got %#v want %#v", r.Data, want)
	}
}

func TestFlagshipReadOnlyBareValuesInDryModeToo(t *testing.T) {
	r := buildFlagshipApp().Test([]string{"--dry-run", "status"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	want := map[string]interface{}{"head": "a1b2c3d", "clean": true, "exit_code": 0}
	if !reflect.DeepEqual(r.Data, want) {
		t.Fatalf("data mismatch: got %#v want %#v", r.Data, want)
	}
}

func TestFlagshipReadOnlyWouldDoBodyIsEmpty(t *testing.T) {
	r := buildFlagshipApp().Test([]string{"--dry-run", "status"})
	if !strings.HasSuffix(r.Stdout, "DRY RUN — no changes were made. Would do:\n") {
		t.Fatalf("expected a header-only would-do log, got %q", r.Stdout)
	}
}

func TestFlagshipReadOnlyEffectLogIsEmpty(t *testing.T) {
	app := buildFlagshipApp()
	app.Test([]string{"--dry-run", "status"})
	if got := len(app.EffectLog()); got != 0 {
		t.Fatalf("expected an empty effect log, got %#v", app.EffectLog())
	}
}

func TestFlagshipQuietHidesInfoButNotTheHeader(t *testing.T) {
	r := buildFlagshipApp().Test([]string{"--quiet", "--dry-run", "status"})
	if strings.Contains(r.Stdout, "head: a1b2c3d") {
		t.Fatalf("--quiet must hide ctx.Info output, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "DRY RUN — no changes were made. Would do:") {
		t.Fatalf("--quiet must never suppress the would-do log, got %q", r.Stdout)
	}
}

// --- classification is visible in the schema --------------------------------

func TestFlagshipSchemaCarriesTheRegimeDeclarations(t *testing.T) {
	app := buildFlagshipApp()
	schema := dumpSchemaCore(app)
	commands := schema["commands"].(map[string]interface{})
	status := commands["status"].(map[string]interface{})
	if status["effect"] != EffectReadOnly {
		t.Fatalf("status effect = %v", status["effect"])
	}
	groups := schema["groups"].(map[string]interface{})
	release := groups["release"].(map[string]interface{})["commands"].(map[string]interface{})
	run := release["run"].(map[string]interface{})
	if run["effect"] != EffectMutating {
		t.Fatalf("release.run effect = %v", run["effect"])
	}
	grants := run["grants"].([]interface{})
	wantGrant := map[string]interface{}{
		"name": "push", "reason": "release engine owns remote refs", "kind": ProcMutate,
	}
	if len(grants) != 1 || !reflect.DeepEqual(grants[0], wantGrant) {
		t.Fatalf("grants = %#v", grants)
	}
	if release["verify"].(map[string]interface{})["effect"] != EffectMutating {
		t.Fatalf("release.verify effect missing")
	}
	if _, ok := schema["proc_observe_allowlist"]; !ok {
		t.Fatal("expected proc_observe_allowlist on the app entry")
	}
}
