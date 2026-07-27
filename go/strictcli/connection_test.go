package strictcli

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

// --- Declaration + help + schema surfacing ---

func TestConnectionEnv_Declaration(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "Postgres connection string"))
	if app.connectionEnvs["DATABASE_URL"] != "Postgres connection string" {
		t.Fatalf("connection env help = %q", app.connectionEnvs["DATABASE_URL"])
	}
	if len(app.connectionOrder) != 1 || app.connectionOrder[0] != "DATABASE_URL" {
		t.Fatalf("connectionOrder = %v", app.connectionOrder)
	}
}

func TestConnectionEnv_HelpRendering(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "Postgres connection string"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) })
	r := app.Test([]string{"--help"})
	if !strings.Contains(r.Stdout, "Infrastructure:") {
		t.Fatalf("help missing Infrastructure section: %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "DATABASE_URL") ||
		!strings.Contains(r.Stdout, "connection URL, suppressed by --hermetic (Postgres connection string)") {
		t.Fatalf("help missing connection env line: %q", r.Stdout)
	}
}

func TestConnectionEnv_SchemaDump(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "Postgres connection string"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) })
	schema := dumpSchemaCore(app)
	infra, ok := schema["infra"].(map[string]interface{})
	if !ok {
		t.Fatalf("schema missing infra: %v", schema)
	}
	conns, ok := infra["connections"].([]interface{})
	if !ok || len(conns) != 1 {
		t.Fatalf("infra.connections = %v", infra["connections"])
	}
	entry := conns[0].(map[string]interface{})
	if entry["env_var"] != "DATABASE_URL" || entry["help"] != "Postgres connection string" {
		t.Fatalf("connection entry = %v", entry)
	}
	// round-trip through JSON to ensure it marshals
	if _, err := json.Marshal(schema); err != nil {
		t.Fatalf("schema marshal: %v", err)
	}
}

// --- Lazy read + precedence (cli > env) ---

func newConnApp(t *testing.T) (*App, *map[string]interface{}, *map[string]string) {
	t.Helper()
	kw := map[string]interface{}{}
	src := map[string]string{}
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "Postgres connection string"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		kw = kwargs
		src = map[string]string{"dsn": ctx.Source("dsn")}
		return Exit(0)
	}, WithFlags(
		StringFlag("dsn", "connection string", Default(nil), ConnectionURLFlag("DATABASE_URL")),
	))
	return app, &kw, &src
}

func TestConnectionEnv_LazyReadFromEnv(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://from-env/db")
	defer os.Unsetenv("DATABASE_URL")
	app, kwP, srcP := newConnApp(t)
	r := app.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if (*kwP)["dsn"] != "postgres://from-env/db" {
		t.Fatalf("dsn = %v, want from-env", (*kwP)["dsn"])
	}
	if (*srcP)["dsn"] != "env" {
		t.Fatalf("source = %q, want env", (*srcP)["dsn"])
	}
}

func TestConnectionEnv_CliBeatsEnv(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://from-env/db")
	defer os.Unsetenv("DATABASE_URL")
	app, kwP, srcP := newConnApp(t)
	r := app.Test([]string{"run", "--dsn", "postgres://from-cli/db"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if (*kwP)["dsn"] != "postgres://from-cli/db" {
		t.Fatalf("dsn = %v, want from-cli", (*kwP)["dsn"])
	}
	if (*srcP)["dsn"] != "cli" {
		t.Fatalf("source = %q, want cli", (*srcP)["dsn"])
	}
}

func TestConnectionEnv_HermeticSuppressesFlagResolution(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://from-env/db")
	defer os.Unsetenv("DATABASE_URL")
	app, kwP, srcP := newConnApp(t)
	r := app.Test([]string{"--hermetic", "run"})
	if r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	if (*kwP)["dsn"] == "postgres://from-env/db" {
		t.Fatalf("hermetic must suppress connection env; got %v", (*kwP)["dsn"])
	}
	if (*srcP)["dsn"] == "env" {
		t.Fatalf("hermetic source must not be env, got %q", (*srcP)["dsn"])
	}
}

// --- Handler-side InfraValue / ConnectionEnvValue ---

func TestConnectionEnv_InfraValueLive(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://live/db")
	defer os.Unsetenv("DATABASE_URL")
	var got string
	var present bool
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		got, present = ctx.ConnectionEnvValue("DATABASE_URL")
		return Exit(0)
	})
	app.Test([]string{"run"})
	if !present || got != "postgres://live/db" {
		t.Fatalf("ConnectionEnvValue = (%q, %v)", got, present)
	}
	// InfraValue resolves it too.
	app.Command("run2", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		got, present = ctx.InfraValue("DATABASE_URL")
		return Exit(0)
	})
	app.Test([]string{"run2"})
	if !present || got != "postgres://live/db" {
		t.Fatalf("InfraValue = (%q, %v)", got, present)
	}
}

func TestConnectionEnv_HermeticSuppressesInfraValue(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://live/db")
	defer os.Unsetenv("DATABASE_URL")
	var present bool
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		_, present = ctx.ConnectionEnvValue("DATABASE_URL")
		return Exit(0)
	})
	app.Test([]string{"--hermetic", "run"})
	if present {
		t.Fatalf("hermetic must make ConnectionEnvValue absent")
	}
}

func TestConnectionEnv_UndeclaredValuePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic reading undeclared connection env")
		}
	}()
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome {
		ctx.ConnectionEnvValue("NOPE")
		return Exit(0)
	})
	app.Test([]string{"run"})
}

// --- Check-side access via ConnectionEnvReader ---

const connChecksToml = `
app = "myapp"

[checks.db-reachable]
tags = ["db"]
severity = "error"
fast = true
pure = false
needs_network = true
depends_on = []
`

func newConnCheckApp(t *testing.T) *App {
	t.Helper()
	path := writeChecksFile(t, connChecksToml)
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"),
		WithChecks(path))
	app.RegisterErrorCheck("db-reachable", func(ctx CheckContext, rep *ErrorReporter) CheckOutcome {
		r, ok := ctx.(ConnectionEnvReader)
		if !ok {
			return rep.Skipped("no connection reader")
		}
		dsn, present := r.ConnectionEnvValue("DATABASE_URL")
		if !present {
			return rep.Skipped("DATABASE_URL absent (hermetic or unset)")
		}
		rep.Note("dsn=" + dsn)
		return rep.Passed("connection env visible")
	})
	app.SetCheckContext(func() CheckContext { return &testCheckContext{root: "/tmp"} })
	return app
}

func TestConnectionEnv_CheckSideAccess(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://check/db")
	defer os.Unsetenv("DATABASE_URL")
	app := newConnCheckApp(t)
	r := app.Test([]string{"check", "--tag", "db", "--verbose"})
	if !strings.Contains(r.Stdout, "dsn=postgres://check/db") {
		t.Fatalf("check did not see connection env: %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "PASS") {
		t.Fatalf("expected PASS: %q", r.Stdout)
	}
}

func TestConnectionEnv_CheckSideHermeticSkips(t *testing.T) {
	os.Setenv("DATABASE_URL", "postgres://check/db")
	defer os.Unsetenv("DATABASE_URL")
	app := newConnCheckApp(t)
	r := app.Test([]string{"--hermetic", "check", "--tag", "db"})
	if !strings.Contains(r.Stdout, "SKIP") {
		t.Fatalf("expected SKIP under hermetic: %q (stderr=%q)", r.Stdout, r.Stderr)
	}
	if strings.Contains(r.Stdout, "dsn=") {
		t.Fatalf("hermetic must hide the connection value: %q", r.Stdout)
	}
}

// --- Registration-time enforcement ---

func TestConnectionURLFlag_UnboundPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for URL-class flag with no binding")
		}
	}()
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	// URL-class flag with no ConnectionEnv binding -- the bug class the
	// framework refuses at registration.
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithFlags(Flag{Name: "dsn", Type: TypeStr, Help: "dsn", ConnectionURL: true, hasDefault: true}))
}

func TestConnectionURLFlag_UndeclaredBindingPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic binding to undeclared connection env")
		}
	}()
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithFlags(StringFlag("dsn", "dsn", Default(nil), ConnectionURLFlag("OTHER_URL"))))
}

func TestConnectionEnv_BindingWithoutURLMarkerPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for ConnectionEnv without URL marker")
		}
	}()
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithFlags(Flag{Name: "dsn", Type: TypeStr, Help: "dsn", ConnectionEnv: "DATABASE_URL", hasDefault: true}))
}

func TestConnectionEnv_BindingPlusPerFlagEnvPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic combining ConnectionEnv with per-flag Env")
		}
	}()
	app := NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "conn"))
	app.Command("run", "run it", func(ctx *Context, kwargs map[string]interface{}) Outcome { return Exit(0) },
		WithFlags(StringFlag("dsn", "dsn", Default(nil), Env("SOMETHING_ELSE"), ConnectionURLFlag("DATABASE_URL"))))
}

func TestConnectionEnv_EmptyHelpPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for empty help")
		}
	}()
	NewApp("myapp", "1.0.0", "test app", WithConnectionEnv("DATABASE_URL", ""))
}

func TestConnectionEnv_DuplicatePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for duplicate connection env")
		}
	}()
	NewApp("myapp", "1.0.0", "test app",
		WithConnectionEnv("DATABASE_URL", "a"),
		WithConnectionEnv("DATABASE_URL", "b"))
}

func TestConnectionEnv_CollidesWithRootPanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for connection env colliding with root")
		}
	}()
	NewApp("myapp", "1.0.0", "test app",
		WithInfraRoot("SHARED", "/var/lib"),
		WithConnectionEnv("SHARED", "conn"))
}

func TestConnectionEnv_CollidesWithHandshakePanics(t *testing.T) {
	defer func() {
		if recover() == nil {
			t.Fatalf("expected panic for connection env colliding with handshake")
		}
	}()
	NewApp("myapp", "1.0.0", "test app",
		WithHandshakeEnv("SHARED", "handshake"),
		WithConnectionEnv("SHARED", "conn"))
}
