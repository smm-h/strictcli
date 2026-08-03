package strictcli

// The built-in effects-bypass check provider (stdlib go/ast).

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeGoFile(t *testing.T, dir, name, body string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestBypassLintFlagsDirectProcessCall(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "handler.go", `package app

import "os/exec"

func deploy(ctx *Ctx) int {
	ctx.Effects().Run([]interface{}{"make"})
	exec.Command("git", "push").Run()
	return 0
}
`)
	findings := scanEffectsBypasses(dir)
	if len(findings) != 1 {
		t.Fatalf("expected 1 finding, got %#v", findings)
	}
	if findings[0].target != "exec.Command" || findings[0].fn != "deploy" {
		t.Fatalf("unexpected finding %#v", findings[0])
	}
}

func TestBypassLintFlagsFilesystemAndNetwork(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "handler.go", `package app

import (
	"net/http"
	"os"
)

func publish(ctx *Ctx) int {
	ctx.Effects().Mkdir("d")
	os.WriteFile("x", nil, 0o644)
	os.RemoveAll("y")
	http.Post("https://x.test", "text/plain", nil)
	return 0
}
`)
	findings := scanEffectsBypasses(dir)
	targets := make([]string, 0, len(findings))
	for _, f := range findings {
		targets = append(targets, f.target)
	}
	want := []string{"os.WriteFile", "os.RemoveAll", "http.Post"}
	if len(targets) != len(want) {
		t.Fatalf("targets = %v want %v", targets, want)
	}
	for i := range want {
		if targets[i] != want[i] {
			t.Fatalf("targets = %v want %v", targets, want)
		}
	}
}

func TestBypassLintIgnoresFunctionsThatNeverOptIn(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "plain.go", `package app

import "os"

func housekeeping() {
	os.RemoveAll("scratch")
}
`)
	if findings := scanEffectsBypasses(dir); len(findings) != 0 {
		t.Fatalf("a function that never reaches for ctx.Effects() is not a finding: %#v", findings)
	}
}

func TestBypassLintDoesNotFlagTheEffectsHandleItself(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "clean.go", `package app

func deploy(ctx *Ctx) int {
	ctx.Effects().Remove("stale")
	ctx.Effects().Mkdir("build")
	ctx.Effects().Rename("a", "b")
	return 0
}
`)
	if findings := scanEffectsBypasses(dir); len(findings) != 0 {
		t.Fatalf("routing through the handle must be clean: %#v", findings)
	}
}

func TestBypassLintDoesNotFlagOrdinaryMapLookups(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "lookup.go", `package app

type store struct{}

func (s store) Get(k string) string { return k }

func deploy(ctx *Ctx, s store) int {
	ctx.Effects().Run([]interface{}{"make"})
	_ = s.Get("key")
	return 0
}
`)
	if findings := scanEffectsBypasses(dir); len(findings) != 0 {
		t.Fatalf("a plain .Get on a non-network receiver is not a finding: %#v", findings)
	}
}

func TestBypassLintSkipsUnparseableFilesAndSkipDirs(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "broken.go", "package app\nfunc (\n")
	writeGoFile(t, dir, filepath.Join("vendor", "dep.go"), `package dep

import "os"

func deploy(ctx *Ctx) int {
	ctx.Effects().Run(nil)
	os.RemoveAll("x")
	return 0
}
`)
	if findings := scanEffectsBypasses(dir); len(findings) != 0 {
		t.Fatalf("unparseable files and vendor/ are not evidence of a bypass: %#v", findings)
	}
}

func TestBypassLintMissingRootIsNotAFinding(t *testing.T) {
	if findings := scanEffectsBypasses(filepath.Join(t.TempDir(), "nope")); len(findings) != 0 {
		t.Fatalf("a missing root yields no findings, got %#v", findings)
	}
}

func TestBypassCheckRunsThroughTheProviderHook(t *testing.T) {
	dir := t.TempDir()
	writeGoFile(t, dir, "handler.go", `package app

import "os/exec"

func deploy(ctx *Ctx) int {
	ctx.Effects().Run(nil)
	exec.Command("git", "push").Run()
	return 0
}
`)
	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheckProvider(func() []CheckSpec { return nil })
	app.SetCheckContext(func() CheckContext { return &testCheckContext{root: dir} })

	r := app.Test([]string{"check", "--name", "effects-bypass"})
	if r.ExitCode == 0 {
		t.Fatalf("expected a failing check, got exit 0; stdout=%q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "route it through ctx.Effects()") {
		t.Fatalf("expected the bypass finding, got %q", r.Stdout)
	}
}

func TestBypassCheckMetadataMatchesTheContract(t *testing.T) {
	app := NewApp("testapp", "1.0.0", "test app")
	app.RegisterCheckProvider(func() []CheckSpec { return nil })
	specs := app.effectsBypassProvider()
	if len(specs) != 1 {
		t.Fatalf("expected exactly one spec, got %d", len(specs))
	}
	m := specs[0].meta
	if m.Name != "effects-bypass" || m.Severity != "error" || !m.Fast || !m.Pure || m.NeedsNetwork {
		t.Fatalf("metadata = %#v", m)
	}
	if len(m.Tags) != 2 || m.Tags[0] != "effects" || m.Tags[1] != "quality" {
		t.Fatalf("tags = %v", m.Tags)
	}
	if len(m.DependsOn) != 0 {
		t.Fatalf("depends_on = %v", m.DependsOn)
	}
}
