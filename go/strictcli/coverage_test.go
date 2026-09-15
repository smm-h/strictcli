package strictcli

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// testCheckCtx satisfies CheckContext for test-coverage check runs.
type testCheckCtx struct {
	root string
}

func (c *testCheckCtx) ProjectRoot() string { return c.root }

// declaredCoverageDir creates the directory an app declares through
// WithTestCoverageDir and returns its absolute path. The option takes effect
// only when the directory already exists at construction, which is what makes
// an installed distribution -- whose declared path is gone -- uninstrumented.
func declaredCoverageDir(t *testing.T, root string) string {
	t.Helper()
	dir := filepath.Join(root, ".strictcli")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	return dir
}

func makeTestCoverageApp(t *testing.T) *App {
	t.Helper()
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })
	app := NewApp("coverapp", "1.0.0", "coverage test app",
		WithTestCoverageDir(declaredCoverageDir(t, dir)))
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.Command("status", "show status", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.Command("build", "build the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.SetCheckContext(func() CheckContext { return &testCheckCtx{root: dir} })
	return app
}

func makeGroupedCoverageApp(t *testing.T) *App {
	t.Helper()
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })
	app := NewApp("grpapp", "1.0.0", "grouped coverage test",
		WithTestCoverageDir(declaredCoverageDir(t, dir)))
	grp := app.Group("infra", "infrastructure commands")
	grp.Command("deploy", "deploy infra", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	grp.Command("teardown", "tear down infra", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.Command("status", "show status", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.SetCheckContext(func() CheckContext { return &testCheckCtx{root: dir} })
	return app
}

// writeCoverageManifest writes a committed manifest under the declared
// .strictcli/ root, creating the directory when a caller has not already.
func writeCoverageManifest(t *testing.T, content []byte) {
	t.Helper()
	if err := os.MkdirAll(".strictcli", 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(".strictcli", "test-coverage.json"), content, 0o644); err != nil {
		t.Fatal(err)
	}
}

func readCoveredCommands(t *testing.T) map[string]bool {
	t.Helper()
	covered := make(map[string]bool)
	dir := ".strictcli/coverage"
	entries, err := os.ReadDir(dir)
	if err != nil {
		return covered
	}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".jsonl") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, entry.Name()))
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var record map[string]string
			if err := json.Unmarshal([]byte(line), &record); err != nil {
				continue
			}
			if cmd, ok := record["command"]; ok {
				covered[cmd] = true
			}
		}
	}
	return covered
}

func TestCoverageRecording_TestCreatesShard(t *testing.T) {
	app := makeTestCoverageApp(t)
	r := app.Test([]string{"deploy"})
	if r.ExitCode != 0 {
		t.Fatalf("deploy failed: %s", r.Stderr)
	}

	covered := readCoveredCommands(t)
	if !covered["deploy"] {
		t.Fatal("deploy not in coverage data")
	}

	// One shard per process, named "<pid>.jsonl" (no shard counter suffix).
	shards, _ := filepath.Glob(filepath.Join(".strictcli", "coverage", "*.jsonl"))
	want := fmt.Sprintf("%d.jsonl", os.Getpid())
	if len(shards) != 1 || filepath.Base(shards[0]) != want {
		t.Fatalf("expected single shard %q, got %v", want, shards)
	}
}

func TestCoverageRecording_CallRecords(t *testing.T) {
	app := makeTestCoverageApp(t)
	_, err := app.Call("status", nil)
	if err != nil {
		t.Fatal(err)
	}

	covered := readCoveredCommands(t)
	if !covered["status"] {
		t.Fatal("status not in coverage data")
	}
}

func TestCoverageRecording_MultipleAccumulate(t *testing.T) {
	app := makeTestCoverageApp(t)
	app.Test([]string{"deploy"})
	app.Test([]string{"status"})
	app.Call("build", nil)

	covered := readCoveredCommands(t)
	for _, cmd := range []string{"deploy", "status", "build"} {
		if !covered[cmd] {
			t.Fatalf("%s not in coverage data", cmd)
		}
	}
}

func TestCoverageRecording_GroupedDottedPath(t *testing.T) {
	app := makeGroupedCoverageApp(t)
	app.Test([]string{"infra", "deploy"})

	covered := readCoveredCommands(t)
	if !covered["infra.deploy"] {
		t.Fatal("infra.deploy not in coverage data")
	}
}

func TestCoverageCheck_PartialFails(t *testing.T) {
	app := makeTestCoverageApp(t)
	app.Test([]string{"deploy"})

	results, _, _, _ := app.RunChecks(
		&testCheckCtx{root: "."},
		RunChecksOptions{RunAll: true},
	)
	var cov *CheckRunResult
	for i := range results {
		if results[i].Name == "cli-test-coverage" {
			cov = &results[i]
			break
		}
	}
	if cov == nil {
		t.Fatal("cli-test-coverage check not found")
	}
	if cov.Status() != "fail" {
		t.Fatalf("expected fail, got %s", cov.Status())
	}
	// Should mention uncovered commands
	foundStatus := false
	foundBuild := false
	for _, p := range cov.Outcome.problems {
		if strings.Contains(p.text, "status") {
			foundStatus = true
		}
		if strings.Contains(p.text, "build") {
			foundBuild = true
		}
	}
	if !foundStatus || !foundBuild {
		t.Fatalf("expected uncovered status and build, problems: %+v", cov.Outcome.problems)
	}
}

func TestCoverageCheck_FullCoveragePasses(t *testing.T) {
	app := makeTestCoverageApp(t)
	app.Test([]string{"deploy"})
	app.Test([]string{"status"})
	app.Test([]string{"build"})

	results, _, _, _ := app.RunChecks(
		&testCheckCtx{root: "."},
		RunChecksOptions{RunAll: true},
	)
	var cov *CheckRunResult
	for i := range results {
		if results[i].Name == "cli-test-coverage" {
			cov = &results[i]
			break
		}
	}
	if cov == nil {
		t.Fatal("cli-test-coverage check not found")
	}
	if cov.Status() != "pass" {
		t.Fatalf("expected pass, got %s; message=%s", cov.Status(), cov.Outcome.message)
	}
}

func TestCoverageCheck_ZeroStateSkips(t *testing.T) {
	app := makeTestCoverageApp(t)
	constructionDir, _ := os.Getwd()
	// No Test()/Call() -- no shards, and no committed manifest.

	results, _, _, _ := app.RunChecks(
		&testCheckCtx{root: "."},
		RunChecksOptions{RunAll: true},
	)
	cov := findCoverageResult(t, results)
	if cov.Status() != "skip" {
		t.Fatalf("expected skip, got %s; msg=%s", cov.Status(), cov.Outcome.message)
	}
	if !strings.Contains(cov.Outcome.message, "development tree") {
		t.Fatalf("skip reason should mention the app's development tree, got %q", cov.Outcome.message)
	}
	// Reason names the declared .strictcli path.
	if !strings.Contains(cov.Outcome.message, filepath.Join(constructionDir, ".strictcli")) {
		t.Fatalf("skip reason should name the declared path, got %q", cov.Outcome.message)
	}
}

func TestCoverageCheck_EmptyManifestPresentFailsListingAll(t *testing.T) {
	app := makeTestCoverageApp(t)
	// An empty-manifest file present means "coverage configured but empty" ->
	// FAIL listing all, NOT a skip. The skip class triggers only when NEITHER a
	// manifest NOR any shards exist.
	writeCoverageManifest(t, []byte("[]\n"))

	results, _, _, _ := app.RunChecks(
		&testCheckCtx{root: "."},
		RunChecksOptions{RunAll: true},
	)
	cov := findCoverageResult(t, results)
	if cov.Status() != "fail" {
		t.Fatalf("expected fail, got %s", cov.Status())
	}
	foundStatus, foundBuild, foundDeploy := false, false, false
	for _, p := range cov.Outcome.problems {
		if strings.Contains(p.text, "status") {
			foundStatus = true
		}
		if strings.Contains(p.text, "build") {
			foundBuild = true
		}
		if strings.Contains(p.text, "deploy") {
			foundDeploy = true
		}
	}
	if !foundStatus || !foundBuild || !foundDeploy {
		t.Fatalf("expected all commands listed uncovered, problems: %+v", cov.Outcome.problems)
	}
}

func TestCoverageCheck_ManifestWritten(t *testing.T) {
	app := makeTestCoverageApp(t)
	app.Test([]string{"deploy"})
	app.Test([]string{"status"})
	app.Test([]string{"build"})

	app.RunChecks(
		&testCheckCtx{root: "."},
		RunChecksOptions{RunAll: true},
	)

	data, err := os.ReadFile(".strictcli/test-coverage.json")
	if err != nil {
		t.Fatal("manifest not written:", err)
	}
	var manifest []string
	if err := json.Unmarshal(data, &manifest); err != nil {
		t.Fatal("manifest invalid JSON:", err)
	}
	expected := []string{"build", "deploy", "status"}
	if len(manifest) != len(expected) {
		t.Fatalf("expected %v, got %v", expected, manifest)
	}
	for i, cmd := range expected {
		if manifest[i] != cmd {
			t.Fatalf("expected %v, got %v", expected, manifest)
		}
	}
}

func TestCoverageCheck_GroupedPasses(t *testing.T) {
	app := makeGroupedCoverageApp(t)
	app.Test([]string{"infra", "deploy"})
	app.Test([]string{"infra", "teardown"})
	app.Test([]string{"status"})

	results, _, _, _ := app.RunChecks(
		&testCheckCtx{root: "."},
		RunChecksOptions{RunAll: true},
	)
	var cov *CheckRunResult
	for i := range results {
		if results[i].Name == "cli-test-coverage" {
			cov = &results[i]
			break
		}
	}
	if cov == nil {
		t.Fatal("cli-test-coverage check not found")
	}
	if cov.Status() != "pass" {
		t.Fatalf("expected pass, got %s; message=%s", cov.Status(), cov.Outcome.message)
	}
}

func findCoverageResult(t *testing.T, results []CheckRunResult) *CheckRunResult {
	t.Helper()
	for i := range results {
		if results[i].Name == "cli-test-coverage" {
			return &results[i]
		}
	}
	t.Fatal("cli-test-coverage check not found")
	return nil
}

func TestCoverageRecording_AnchoredToDeclaredDir(t *testing.T) {
	app := makeTestCoverageApp(t) // declares <temp dir>/.strictcli
	declaredRoot, _ := os.Getwd()
	defer os.Chdir(declaredRoot)

	other := t.TempDir()
	if err := os.Chdir(other); err != nil {
		t.Fatal(err)
	}

	app.Test([]string{"deploy"})

	shards, _ := filepath.Glob(filepath.Join(declaredRoot, ".strictcli", "coverage", "*.jsonl"))
	if len(shards) == 0 {
		t.Fatal("shard must be written under the declared directory")
	}
	foreign, _ := filepath.Glob(filepath.Join(other, ".strictcli", "coverage", "*.jsonl"))
	if len(foreign) != 0 {
		t.Fatalf("must not record into the chdir'd cwd: %v", foreign)
	}
}

func TestCoverageCheck_ManifestOnlyDeterministicPass(t *testing.T) {
	app := makeTestCoverageApp(t)
	// No Test()/Call() -- no shards. Write a complete committed manifest.
	data, _ := json.MarshalIndent([]string{"build", "deploy", "status"}, "", "  ")
	writeCoverageManifest(t, append(data, '\n'))

	results, _, _, _ := app.RunChecks(&testCheckCtx{root: "."}, RunChecksOptions{RunAll: true})
	cov := findCoverageResult(t, results)
	if cov.Status() != "pass" {
		t.Fatalf("expected pass from committed manifest alone, got %s; msg=%s", cov.Status(), cov.Outcome.message)
	}
}

func TestCoverageCheck_ManifestUnionMonotonic(t *testing.T) {
	app := makeTestCoverageApp(t)
	data, _ := json.MarshalIndent([]string{"build", "deploy", "status"}, "", "  ")
	writeCoverageManifest(t, append(data, '\n'))
	// This run records only one command.
	app.Test([]string{"deploy"})

	app.RunChecks(&testCheckCtx{root: "."}, RunChecksOptions{RunAll: true})

	raw, err := os.ReadFile(".strictcli/test-coverage.json")
	if err != nil {
		t.Fatal(err)
	}
	var manifest []string
	if err := json.Unmarshal(raw, &manifest); err != nil {
		t.Fatal(err)
	}
	got := make(map[string]bool)
	for _, c := range manifest {
		got[c] = true
	}
	for _, want := range []string{"build", "deploy", "status"} {
		if !got[want] {
			t.Fatalf("union not monotonic: %q missing from %v", want, manifest)
		}
	}
}

func TestCoverageCheck_ManifestNotRewrittenWhenUnchanged(t *testing.T) {
	app := makeTestCoverageApp(t)
	app.Test([]string{"deploy"})
	app.Test([]string{"status"})
	app.Test([]string{"build"})
	app.RunChecks(&testCheckCtx{root: "."}, RunChecksOptions{RunAll: true})

	content1, _ := os.ReadFile(".strictcli/test-coverage.json")
	info1, err := os.Stat(".strictcli/test-coverage.json")
	if err != nil {
		t.Fatal(err)
	}

	app.RunChecks(&testCheckCtx{root: "."}, RunChecksOptions{RunAll: true})

	content2, _ := os.ReadFile(".strictcli/test-coverage.json")
	info2, _ := os.Stat(".strictcli/test-coverage.json")
	if string(content1) != string(content2) {
		t.Fatal("manifest content changed on identical re-run")
	}
	if !info1.ModTime().Equal(info2.ModTime()) {
		t.Fatal("pure check rewrote a byte-identical manifest")
	}
}

func TestCoverageDisabled_NoShardsCreated(t *testing.T) {
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })
	// No WithTestCoverageDir()
	app := NewApp("nocover", "1.0.0", "no coverage")
	app.Command("greet", "say hello", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.Test([]string{"greet"})

	if _, err := os.Stat(".strictcli/coverage"); !os.IsNotExist(err) {
		t.Fatal("coverage dir should not exist when disabled")
	}
}

// TestCoverageDirectoryIsLazy_ConstructionLeavesNoDirectory pins that enabling
// test coverage does not plant a coverage/ subdirectory inside the declared
// directory. A plain CLI invocation never records coverage, so it leaves no
// trace.
func TestCoverageDirectoryIsLazy_ConstructionLeavesNoDirectory(t *testing.T) {
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })

	app := NewApp("coverapp", "1.0.0", "coverage test app",
		WithTestCoverageDir(declaredCoverageDir(t, dir)))
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	if _, err := os.Stat(filepath.Join(dir, ".strictcli", "coverage")); !os.IsNotExist(err) {
		t.Fatal("construction must not create coverage/")
	}
}

// TestCoverageDirectoryIsLazy_RecordingCreatesDirectory pins that the recorder
// creates the coverage directory immediately before the first shard write.
func TestCoverageDirectoryIsLazy_RecordingCreatesDirectory(t *testing.T) {
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })

	app := NewApp("coverapp", "1.0.0", "coverage test app",
		WithTestCoverageDir(declaredCoverageDir(t, dir)))
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.Test([]string{"deploy"})

	shard := filepath.Join(dir, ".strictcli", "coverage", fmt.Sprintf("%d.jsonl", os.Getpid()))
	if _, err := os.Stat(shard); err != nil {
		t.Fatalf("shard file must exist after a recorded dispatch: %v", err)
	}
}

// TestCoverageDirectoryIsLazy_CheckSkipsWhenDirectoryAbsent pins that the
// provider tolerates a coverage/ subdirectory that was never created.
func TestCoverageDirectoryIsLazy_CheckSkipsWhenDirectoryAbsent(t *testing.T) {
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })

	app := NewApp("coverapp", "1.0.0", "coverage test app",
		WithTestCoverageDir(declaredCoverageDir(t, dir)))
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.SetCheckContext(func() CheckContext { return &testCheckCtx{root: dir} })

	if _, err := os.Stat(filepath.Join(dir, ".strictcli", "coverage")); !os.IsNotExist(err) {
		t.Fatal("construction must not create coverage/")
	}

	results, _, _, _ := app.RunChecks(
		&testCheckCtx{root: dir},
		RunChecksOptions{RunAll: true},
	)
	var cov *CheckRunResult
	for i := range results {
		if results[i].Name == "cli-test-coverage" {
			cov = &results[i]
			break
		}
	}
	if cov == nil {
		t.Fatal("cli-test-coverage check not found")
	}
	if cov.Status() != "skip" {
		t.Fatalf("expected skip with no coverage state, got %s", cov.Status())
	}
}

// TestCoverageDeclaredDirAbsent_RegistersNoCheck pins the installed
// distribution: the declared directory names a source checkout that is not
// present, so the app registers no cli-test-coverage check at all.
func TestCoverageDeclaredDirAbsent_RegistersNoCheck(t *testing.T) {
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })

	app := NewApp("coverapp", "1.0.0", "coverage test app",
		WithTestCoverageDir(filepath.Join(dir, "nowhere", ".strictcli")))
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))
	app.SetCheckContext(func() CheckContext { return &testCheckCtx{root: dir} })

	// The check system never turned on, so `check` is not a command either.
	r := app.Test([]string{"check", "--all"})
	if r.ExitCode != 1 {
		t.Fatalf("expected the check command to be unroutable, got exit %d", r.ExitCode)
	}
	if strings.Contains(r.Stdout, "cli-test-coverage") {
		t.Fatalf("cli-test-coverage must not be listed, got %q", r.Stdout)
	}
}

// TestCoverageDeclaredDirAbsent_CreatesNothing pins that a declared directory
// that does not exist leaves the filesystem untouched -- neither the declared
// path nor the working directory the CLI was started in.
func TestCoverageDeclaredDirAbsent_CreatesNothing(t *testing.T) {
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	foreign := filepath.Join(dir, "some-other-project")
	if err := os.MkdirAll(foreign, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(foreign); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })

	app := NewApp("coverapp", "1.0.0", "coverage test app",
		WithTestCoverageDir(filepath.Join(dir, "gone", ".strictcli")))
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	app.Test([]string{"deploy"})
	if _, err := app.Call("deploy", nil); err != nil {
		t.Fatal(err)
	}

	if _, err := os.Stat(filepath.Join(dir, "gone")); !os.IsNotExist(err) {
		t.Fatal("a declared directory that does not exist must not be created")
	}
	entries, err := os.ReadDir(foreign)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("the working directory must be untouched, found %v", entries)
	}
}

// TestCoverageRetiredBooleanRefused pins that the retired boolean option is a
// registration-time refusal naming the option that replaced it.
func TestCoverageRetiredBooleanRefused(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("WithTestCoverage must panic at registration")
		}
		want := "WithTestCoverage is not accepted; declare the directory " +
			"holding coverage/ and test-coverage.json with WithTestCoverageDir"
		if got, ok := r.(string); !ok || got != want {
			t.Fatalf("expected %q, got %v", want, r)
		}
	}()
	NewApp("coverapp", "1.0.0", "coverage test app", WithTestCoverage())
}
