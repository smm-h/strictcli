package strictcli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// Red-green regression: a flag whose Default is a RelativeToRoot marker must
// serialize machine-stably in --dump-schema as
// {"relative_to_root": {"env_var": ..., "parts": [...]}} -- never as an empty
// object (which is what marshaling the unexported InfraRootPath fields would
// produce). The shape is identical to the Python implementation. Covers both a
// command flag and a global flag.
func TestSchemaMarkerDefault_CommandAndGlobalFlag(t *testing.T) {
	os.Unsetenv("MYAPP_HOME")
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	app.GlobalFlag(StringFlag("global-db", "global db path",
		Default(RelativeToRoot("MYAPP_HOME", "global.sqlite"))))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithFlags(StringFlag("db", "db path",
			Default(RelativeToRoot("MYAPP_HOME", "sub", "db.sqlite")))), WithEffect(EffectReadOnly))

	schema := app.DumpSchemaDict()

	// Round-trip through JSON to prove the marker is serializable and lossless.
	raw, err := json.Marshal(schema)
	if err != nil {
		t.Fatalf("marshal schema: %v", err)
	}
	var got map[string]interface{}
	if err := json.Unmarshal(raw, &got); err != nil {
		t.Fatalf("unmarshal schema: %v", err)
	}

	gf := got["global_flags"].([]interface{})[0].(map[string]interface{})
	wantGlobal := map[string]interface{}{
		"relative_to_root": map[string]interface{}{
			"env_var": "MYAPP_HOME",
			"parts":   []interface{}{"global.sqlite"},
		},
	}
	if !reflect.DeepEqual(gf["default"], wantGlobal) {
		t.Fatalf("global flag default = %#v, want %#v", gf["default"], wantGlobal)
	}

	cmd := got["commands"].(map[string]interface{})["run"].(map[string]interface{})
	cf := cmd["flags"].([]interface{})[0].(map[string]interface{})
	wantCmd := map[string]interface{}{
		"relative_to_root": map[string]interface{}{
			"env_var": "MYAPP_HOME",
			"parts":   []interface{}{"sub", "db.sqlite"},
		},
	}
	if !reflect.DeepEqual(cf["default"], wantCmd) {
		t.Fatalf("command flag default = %#v, want %#v", cf["default"], wantCmd)
	}
}

// --- Declared --dump-schema location ---

// The schema dump writes where the App declared, not where the caller stands.

func TestDumpSchemaDeclaredRelativePath(t *testing.T) {
	tmpDir := chdirTemp(t)
	app := NewApp("testapp", "1.0.0", "A test app",
		WithSchemaPath(filepath.Join("build", "cli-schema.json")))
	app.Command("greet", "Say hello", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	r := app.Test([]string{"--dump-schema"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	want := filepath.Join(tmpDir, "build", "cli-schema.json")
	if _, err := os.Stat(want); err != nil {
		t.Fatalf("schema not written to the declared path: %v", err)
	}
	if !strings.Contains(r.Stdout, want) {
		t.Fatalf("stdout = %q, want the declared path", r.Stdout)
	}
	if _, err := os.Stat(filepath.Join(tmpDir, ".strictcli")); err == nil {
		t.Fatalf("the framework's default location was written too")
	}
}

func TestDumpSchemaDeclaredRelativeToRoot(t *testing.T) {
	tmpDir := chdirTemp(t)
	root := filepath.Join(tmpDir, "root")
	t.Setenv("TESTAPP_HOME", root)
	app := NewApp("testapp", "1.0.0", "A test app",
		WithInfraRoot("TESTAPP_HOME", root),
		WithSchemaPathRelativeToRoot("TESTAPP_HOME", "schema.json"))
	app.Command("greet", "Say hello", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	if r := app.Test([]string{"--dump-schema"}); r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if _, err := os.Stat(filepath.Join(root, "schema.json")); err != nil {
		t.Fatalf("schema not written under the declared root: %v", err)
	}
}

func TestDumpSchemaDefaultIsAnchoredAtConstruction(t *testing.T) {
	tmpDir := chdirTemp(t)
	app := NewApp("testapp", "1.0.0", "A test app")
	app.Command("greet", "Say hello", func(ctx *Context, args map[string]interface{}) Outcome {
		return Exit(0)
	}, WithEffect(EffectReadOnly))

	elsewhere := t.TempDir()
	// project_id is read from the cwd at dump time -- a separate cwd
	// dependency this test is not about, so both directories carry a go.mod.
	if err := os.WriteFile(filepath.Join(elsewhere, "go.mod"),
		[]byte("module example.com/testproject\n"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(elsewhere); err != nil {
		t.Fatal(err)
	}
	if r := app.Test([]string{"--dump-schema"}); r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if _, err := os.Stat(filepath.Join(tmpDir, ".strictcli", "schema.json")); err != nil {
		t.Fatalf("schema not written at the construction anchor: %v", err)
	}
	if _, err := os.Stat(filepath.Join(elsewhere, ".strictcli")); err == nil {
		t.Fatalf("schema followed the caller's cwd")
	}
}
