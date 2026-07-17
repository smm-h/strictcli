package strictcli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// --- Eager root resolution ---

func TestInfraRoot_EnvSet(t *testing.T) {
	os.Setenv("MYAPP_HOME", "/opt/data")
	defer os.Unsetenv("MYAPP_HOME")

	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	if got := app.infraRoots["MYAPP_HOME"]; got != "/opt/data" {
		t.Fatalf("root = %q, want /opt/data", got)
	}
	if !app.infraRootFromEnv["MYAPP_HOME"] {
		t.Fatalf("expected fromEnv true")
	}
}

func TestInfraRoot_Unset(t *testing.T) {
	os.Unsetenv("MYAPP_HOME")
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	if got := app.infraRoots["MYAPP_HOME"]; got != "/var/lib/myapp" {
		t.Fatalf("root = %q, want /var/lib/myapp", got)
	}
	if app.infraRootFromEnv["MYAPP_HOME"] {
		t.Fatalf("expected fromEnv false")
	}
}

func TestInfraRoot_TildeExpansion(t *testing.T) {
	os.Unsetenv("MYAPP_HOME")
	home, _ := os.UserHomeDir()
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "~/.myapp"))
	want := filepath.Join(home, ".myapp")
	if got := app.infraRoots["MYAPP_HOME"]; got != want {
		t.Fatalf("root = %q, want %q", got, want)
	}
}

func TestInfraRoot_TildeExpansionFromEnv(t *testing.T) {
	os.Setenv("MYAPP_HOME", "~/data")
	defer os.Unsetenv("MYAPP_HOME")
	home, _ := os.UserHomeDir()
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	want := filepath.Join(home, "data")
	if got := app.infraRoots["MYAPP_HOME"]; got != want {
		t.Fatalf("root = %q, want %q", got, want)
	}
}

// --- Flag-default marker + infra provenance ---

func newInfraFlagApp(t *testing.T) (*App, *map[string]string, *map[string]interface{}) {
	sources := map[string]string{}
	kw := map[string]interface{}{}
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		sources = app.LastSources
		kw = kwargs
		return Exit(0)
	}, WithFlags(
		StringFlag("db", "db path", Default(RelativeToRoot("MYAPP_HOME", "db.sqlite"))),
	))
	return app, &sources, &kw
}

func TestFlagDefaultMarker_InfraProvenance(t *testing.T) {
	os.Unsetenv("MYAPP_HOME")
	app, sourcesP, kwP := newInfraFlagApp(t)
	r := app.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if got := (*kwP)["db"]; got != "/var/lib/myapp/db.sqlite" {
		t.Fatalf("db = %v, want /var/lib/myapp/db.sqlite", got)
	}
	if (*sourcesP)["db"] != "infra" {
		t.Fatalf("source = %q, want infra", (*sourcesP)["db"])
	}
}

func TestFlagDefaultMarker_HermeticImmune(t *testing.T) {
	os.Setenv("MYAPP_HOME", "/opt/data")
	defer os.Unsetenv("MYAPP_HOME")
	app, sourcesP, kwP := newInfraFlagApp(t)
	// Even under --hermetic, the root resolves (it has no argv dependency).
	r := app.Test([]string{"--hermetic", "run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if got := (*kwP)["db"]; got != "/opt/data/db.sqlite" {
		t.Fatalf("db = %v, want /opt/data/db.sqlite", got)
	}
	if (*sourcesP)["db"] != "infra" {
		t.Fatalf("source = %q, want infra", (*sourcesP)["db"])
	}
}

func TestCliOverride_NotInfra(t *testing.T) {
	os.Unsetenv("MYAPP_HOME")
	app, sourcesP, kwP := newInfraFlagApp(t)
	r := app.Test([]string{"run", "--db", "/tmp/custom.db"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if got := (*kwP)["db"]; got != "/tmp/custom.db" {
		t.Fatalf("db = %v, want /tmp/custom.db", got)
	}
	if (*sourcesP)["db"] != "cli" {
		t.Fatalf("source = %q, want cli", (*sourcesP)["db"])
	}
}

// --- Config-path marker rewrite ---

func TestConfigPathMarkerRewrite(t *testing.T) {
	os.Setenv("MYAPP_HOME", "/opt/data")
	defer os.Unsetenv("MYAPP_HOME")
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"),
		WithConfig(),
		WithConfigPathRelativeToRoot("MYAPP_HOME", "config.json"))
	if app.configPathOverride != "/opt/data/config.json" {
		t.Fatalf("configPathOverride = %q, want /opt/data/config.json", app.configPathOverride)
	}
	r := app.Test([]string{"config", "path"})
	if !strings.Contains(r.Stdout, "/opt/data/config.json") {
		t.Fatalf("config path output = %q", r.Stdout)
	}
}

// --- Undeclared root marker: registration hard error ---

func TestUndeclaredRootMarker_Panics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for undeclared root marker")
		}
	}()
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithFlags(StringFlag("db", "db path", Default(RelativeToRoot("NOPE", "x")))))
}

func TestConfigPathMarker_UndeclaredPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for undeclared config-path root marker")
		}
	}()
	NewApp("myapp", "1.0.0", "test app",
		WithConfig(),
		WithConfigPathRelativeToRoot("NOPE", "config.json"))
}

// --- Handshake + accessor ---

type infraHandler struct {
	rootVal   string
	rootOK    bool
	hsVal     string
	hsOK      bool
	panicked  bool
	testUndef bool
}

func (h *infraHandler) command() func(ctx *Context, kwargs map[string]interface{}) Outcome {
	return func(ctx *Context, kwargs map[string]interface{}) Outcome {
		if h.testUndef {
			defer func() {
				if recover() != nil {
					h.panicked = true
				}
			}()
			ctx.InfraValue("UNDECLARED_VAR")
			return Exit(0)
		}
		h.rootVal, h.rootOK = ctx.InfraValue("MYAPP_HOME")
		h.hsVal, h.hsOK = ctx.InfraValue("CI_TOKEN")
		return Exit(0)
	}
}

func TestInfraValue_RootAndHandshakeLiveRead(t *testing.T) {
	os.Setenv("MYAPP_HOME", "/opt/data")
	defer os.Unsetenv("MYAPP_HOME")
	os.Setenv("CI_TOKEN", "abc123")
	defer os.Unsetenv("CI_TOKEN")

	h := &infraHandler{}
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"),
		WithHandshakeEnv("CI_TOKEN", "CI auth token"))
	app.Command("run", "run it", h.command())
	r := app.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if h.rootVal != "/opt/data" || !h.rootOK {
		t.Fatalf("root = (%q,%v), want (/opt/data,true)", h.rootVal, h.rootOK)
	}
	if h.hsVal != "abc123" || !h.hsOK {
		t.Fatalf("handshake = (%q,%v), want (abc123,true)", h.hsVal, h.hsOK)
	}
}

func TestInfraValue_HandshakeUnsetLiveRead(t *testing.T) {
	os.Unsetenv("CI_TOKEN")
	os.Unsetenv("MYAPP_HOME")
	h := &infraHandler{}
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"),
		WithHandshakeEnv("CI_TOKEN", "CI auth token"))
	app.Command("run", "run it", h.command())
	r := app.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if h.hsOK {
		t.Fatalf("expected handshake unset (ok=false), got val=%q", h.hsVal)
	}
}

func TestInfraValue_UndeclaredPanics(t *testing.T) {
	h := &infraHandler{testUndef: true}
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"))
	app.Command("run", "run it", h.command())
	app.Test([]string{"run"})
	if !h.panicked {
		t.Fatalf("expected InfraValue on undeclared var to panic")
	}
}

func TestHandshake_DuplicateRootPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for handshake colliding with root")
		}
	}()
	NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("SHARED", "/x"),
		WithHandshakeEnv("SHARED", "collides"))
}

// --- Surfaces: schema, help, config show ---

func TestInfraSchemaSurface(t *testing.T) {
	os.Setenv("MYAPP_HOME", "/opt/data")
	defer os.Unsetenv("MYAPP_HOME")
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"),
		WithHandshakeEnv("CI_TOKEN", "CI auth token"))
	schema := app.DumpSchemaDict()
	infra, ok := schema["infra"].(map[string]interface{})
	if !ok {
		t.Fatalf("no infra section in schema: %v", schema["infra"])
	}
	roots := infra["roots"].([]interface{})
	root0 := roots[0].(map[string]interface{})
	if root0["env_var"] != "MYAPP_HOME" || root0["default"] != "/var/lib/myapp" {
		t.Fatalf("root0 = %v", root0)
	}
	// Machine-stable: resolved value must NOT be present.
	if _, present := root0["resolved"]; present {
		t.Fatalf("schema must not include resolved root value")
	}
	hs := infra["handshakes"].([]interface{})
	hs0 := hs[0].(map[string]interface{})
	if hs0["env_var"] != "CI_TOKEN" || hs0["help"] != "CI auth token" {
		t.Fatalf("hs0 = %v", hs0)
	}
}

func TestInfraSchemaAbsentWhenUndeclared(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	if _, present := app.DumpSchemaDict()["infra"]; present {
		t.Fatalf("infra section must be absent when nothing declared")
	}
}

func TestInfraHelpSurface(t *testing.T) {
	os.Unsetenv("MYAPP_HOME")
	app := NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"),
		WithHandshakeEnv("CI_TOKEN", "CI auth token"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) })
	r := app.Test([]string{"--help"})
	if !strings.Contains(r.Stdout, "Infrastructure:") {
		t.Fatalf("help missing Infrastructure section: %s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "MYAPP_HOME") || !strings.Contains(r.Stdout, "CI_TOKEN") {
		t.Fatalf("help missing infra vars: %s", r.Stdout)
	}
}

func TestInfraConfigShowSurface(t *testing.T) {
	os.Setenv("MYAPP_HOME", "/opt/data")
	defer os.Unsetenv("MYAPP_HOME")
	os.Unsetenv("CI_TOKEN")
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.json")
	os.WriteFile(configFile, []byte(`{}`), 0o644)
	app := NewApp("myapp", "1.0.0", "test app",
		WithConfig(), WithConfigPath(configFile),
		WithInfraRoot("MYAPP_HOME", "/var/lib/myapp"),
		WithHandshakeEnv("CI_TOKEN", "CI auth token"))
	r := app.Test([]string{"config", "show", "--plain"})
	if !strings.Contains(r.Stdout, "Infrastructure:") {
		t.Fatalf("config show missing Infrastructure: %s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "MYAPP_HOME (root) = /opt/data") {
		t.Fatalf("config show root wrong: %s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "source: env-set") {
		t.Fatalf("config show root source wrong: %s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "CI_TOKEN (handshake) = <unset>") {
		t.Fatalf("config show handshake wrong: %s", r.Stdout)
	}

	// JSON mode
	rj := app.Test([]string{"config", "show", "--json"})
	var result map[string]interface{}
	if err := json.Unmarshal([]byte(rj.Stdout), &result); err != nil {
		t.Fatalf("json parse: %s\n%s", err, rj.Stdout)
	}
	infra, ok := result["__infrastructure__"].(map[string]interface{})
	if !ok {
		t.Fatalf("no __infrastructure__ in json: %v", result)
	}
	root := infra["MYAPP_HOME"].(map[string]interface{})
	if root["resolved"] != "/opt/data" || root["source"] != "env" {
		t.Fatalf("json root = %v", root)
	}
}
