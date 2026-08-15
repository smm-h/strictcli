package strictcli

// The framework's own mutating commands honour --dry-run (§9.2, §3.1).
//
// `config set`, `config init` and `config edit` are classified mutating, so
// every mutation they make must ride ctx.Effects(): under --dry-run they are
// RECORDED and rendered, never performed. A framework command that printed
// "DRY RUN — no changes were made." while rewriting the user's config file (or
// launching their editor) would be the loudest possible counterexample to the
// regime it ships.

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const dryHeader = "DRY RUN — no changes were made. Would do:\n"

func dryConfigApp(name string, opts ...AppOption) *App {
	app := NewApp(name, "1.0.0", "test app", append([]AppOption{WithConfig()}, opts...)...)
	app.Command("run", "run something", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithFlags(StringFlag("opt", "an option", Default(""))), WithEffect(EffectReadOnly))
	return app
}

func TestConfigSetDryRunChangesNothing(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	path := filepath.Join(tmpDir, "dryset", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	before := "{\n  \"opt\": \"before\"\n}\n"
	if err := os.WriteFile(path, []byte(before), 0o644); err != nil {
		t.Fatal(err)
	}

	app := dryConfigApp("dryset")
	r := app.Test([]string{"--dry-run", "config", "set", "opt", "--value", "after"})
	if r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	want := dryHeader + "  1. write: " + path + " (21 bytes)\n"
	if r.Stdout != want {
		t.Fatalf("stdout = %q, want %q", r.Stdout, want)
	}
	got, err := os.ReadFile(path)
	if err != nil || string(got) != before {
		t.Fatalf("config file was modified by a dry run: %q (err=%v)", string(got), err)
	}
}

func TestConfigSetDryRunPreviewsTheMissingDirectory(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	dir := filepath.Join(tmpDir, "drymk")
	path := filepath.Join(dir, "config.json")

	app := dryConfigApp("drymk")
	r := app.Test([]string{"--dry-run", "config", "set", "opt", "--value", "v"})
	if r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	prefix := dryHeader + "  1. mkdir: " + dir + "\n  2. write: " + path + " ("
	if !strings.HasPrefix(r.Stdout, prefix) {
		t.Fatalf("stdout = %q, want prefix %q", r.Stdout, prefix)
	}
	if _, err := os.Stat(dir); err == nil {
		t.Fatal("a dry run created the config directory")
	}
}

func TestConfigSetTomlDryRunChangesNothing(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	path := filepath.Join(tmpDir, "drytoml", "config.toml")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	before := "# a comment\nopt = \"before\"\n"
	if err := os.WriteFile(path, []byte(before), 0o644); err != nil {
		t.Fatal(err)
	}

	app := dryConfigApp("drytoml", WithConfigFormat("toml"))
	r := app.Test([]string{"--dry-run", "config", "set", "opt", "--value", "after"})
	if r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "1. write: "+path) {
		t.Fatalf("stdout = %q", r.Stdout)
	}
	got, _ := os.ReadFile(path)
	if string(got) != before {
		t.Fatalf("config file was modified by a dry run: %q", string(got))
	}
}

func TestConfigInitDryRunWritesNothing(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	path := filepath.Join(tmpDir, "dryinit", "config.json")

	app := dryConfigApp("dryinit")
	r := app.Test([]string{"--dry-run", "config", "init"})
	if r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "2. write: "+path+" (") {
		t.Fatalf("stdout = %q", r.Stdout)
	}
	if _, err := os.Stat(path); err == nil {
		t.Fatal("a dry run created the config file")
	}
}

// The sharpest form of the bug: a dry run must not open $EDITOR.
func TestConfigEditDryRunDoesNotLaunchTheEditor(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	path := filepath.Join(tmpDir, "dryedit", "config.json")
	marker := filepath.Join(tmpDir, "editor-ran")
	editor := filepath.Join(tmpDir, "fake-editor")
	if err := os.WriteFile(editor, []byte("#!/bin/sh\ntouch "+marker+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("EDITOR", editor)

	app := dryConfigApp("dryedit")
	r := app.Test([]string{"--dry-run", "config", "edit"})
	if r.ExitCode != 0 {
		t.Fatalf("exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	want := dryHeader +
		"  1. mkdir: " + filepath.Dir(path) + "\n" +
		"  2. write: " + path + " (3 bytes)\n" +
		"  3. run: " + editor + " " + path + "\n"
	if r.Stdout != want {
		t.Fatalf("stdout = %q, want %q", r.Stdout, want)
	}
	if _, err := os.Stat(marker); err == nil {
		t.Fatal("a dry run launched the editor")
	}
	if _, err := os.Stat(path); err == nil {
		t.Fatal("a dry run created the config file")
	}
}

func TestConfigCommandsStillMutateInLiveMode(t *testing.T) {
	tmpDir, cleanup := configTestSetup(t)
	defer cleanup()
	path := filepath.Join(tmpDir, "livecfg", "config.json")

	app := dryConfigApp("livecfg")
	if r := app.Test([]string{"config", "init"}); r.ExitCode != 0 {
		t.Fatalf("config init: exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("config init did not write the file: %v", err)
	}
	if r := app.Test([]string{"config", "set", "opt", "--value", "v"}); r.ExitCode != 0 {
		t.Fatalf("config set: exit=%d stderr=%q", r.ExitCode, r.Stderr)
	}
	data, _ := os.ReadFile(path)
	if !strings.Contains(string(data), "\"opt\"") {
		t.Fatalf("config set did not persist: %q", string(data))
	}
	log := app.EffectLog()
	if len(log) != 1 || log[0]["verb"] != "write" || log[0]["recorded"] != false {
		t.Fatalf("expected one performed write in the live effect log, got %#v", log)
	}
}
