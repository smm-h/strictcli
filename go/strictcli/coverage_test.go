package strictcli

import (
	"encoding/json"
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

func makeTestCoverageApp(t *testing.T) *App {
	t.Helper()
	origDir, _ := os.Getwd()
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(origDir) })
	app := NewApp("coverapp", "1.0.0", "coverage test app", WithTestCoverage())
	app.Command("deploy", "deploy the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
	app.Command("status", "show status", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
	app.Command("build", "build the app", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
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
	app := NewApp("grpapp", "1.0.0", "grouped coverage test", WithTestCoverage())
	grp := app.Group("infra", "infrastructure commands")
	grp.Command("deploy", "deploy infra", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
	grp.Command("teardown", "tear down infra", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
	app.Command("status", "show status", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
	app.SetCheckContext(func() CheckContext { return &testCheckCtx{root: dir} })
	return app
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

func TestCoverageCheck_EmptyIsHardError(t *testing.T) {
	app := makeTestCoverageApp(t)
	// No test() or call() -- no shards

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

func TestCoverageRecording_AnchoredToConstructionCwd(t *testing.T) {
	app := makeTestCoverageApp(t) // constructs with cwd == its temp dir
	constructionDir, _ := os.Getwd()
	defer os.Chdir(constructionDir)

	other := t.TempDir()
	if err := os.Chdir(other); err != nil {
		t.Fatal(err)
	}

	app.Test([]string{"deploy"})

	shards, _ := filepath.Glob(filepath.Join(constructionDir, ".strictcli", "coverage", "*.jsonl"))
	if len(shards) == 0 {
		t.Fatal("shard must land under the construction cwd")
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
	if err := os.WriteFile(".strictcli/test-coverage.json", append(data, '\n'), 0o644); err != nil {
		t.Fatal(err)
	}

	results, _, _, _ := app.RunChecks(&testCheckCtx{root: "."}, RunChecksOptions{RunAll: true})
	cov := findCoverageResult(t, results)
	if cov.Status() != "pass" {
		t.Fatalf("expected pass from committed manifest alone, got %s; msg=%s", cov.Status(), cov.Outcome.message)
	}
}

func TestCoverageCheck_ManifestUnionMonotonic(t *testing.T) {
	app := makeTestCoverageApp(t)
	data, _ := json.MarshalIndent([]string{"build", "deploy", "status"}, "", "  ")
	os.WriteFile(".strictcli/test-coverage.json", append(data, '\n'), 0o644)
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
	// No WithTestCoverage()
	app := NewApp("nocover", "1.0.0", "no coverage")
	app.Command("greet", "say hello", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	})
	app.Test([]string{"greet"})

	if _, err := os.Stat(".strictcli/coverage"); !os.IsNotExist(err) {
		t.Fatal("coverage dir should not exist when disabled")
	}
}
