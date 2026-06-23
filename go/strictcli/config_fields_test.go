package strictcli

import (
	"strings"
	"testing"
)

// expectPanic runs fn and verifies it panics with a message containing substr.
func expectPanic(t *testing.T, substr string, fn func()) {
	t.Helper()
	defer func() {
		r := recover()
		if r == nil {
			t.Fatalf("expected panic containing %q, but no panic occurred", substr)
		}
		msg, ok := r.(string)
		if !ok {
			t.Fatalf("expected panic string, got %T: %v", r, r)
		}
		if !strings.Contains(msg, substr) {
			t.Fatalf("panic message %q does not contain %q", msg, substr)
		}
	}()
	fn()
}

// --- Basic registration ---

func TestConfigFieldBasicStr(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("name", ConfigFieldHelp("The user name"), ConfigFieldDefault("anonymous"))

	cf, ok := app.configFields["name"]
	if !ok {
		t.Fatal("config field 'name' not registered")
	}
	if cf.Type != TypeStr {
		t.Fatalf("expected TypeStr, got %d", cf.Type)
	}
	if cf.Help != "The user name" {
		t.Fatalf("expected help 'The user name', got %q", cf.Help)
	}
	if cf.Default != "anonymous" {
		t.Fatalf("expected default 'anonymous', got %v", cf.Default)
	}
	if !cf.HasDefault {
		t.Fatal("expected HasDefault to be true")
	}
	if cf.Required {
		t.Fatal("expected Required to be false (has default)")
	}
}

func TestConfigFieldBasicBool(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("verbose", ConfigFieldHelp("Enable verbose output"), ConfigFieldType(TypeBool), ConfigFieldDefault(false))

	cf := app.configFields["verbose"]
	if cf.Type != TypeBool {
		t.Fatalf("expected TypeBool, got %d", cf.Type)
	}
	if cf.Default != false {
		t.Fatalf("expected default false, got %v", cf.Default)
	}
}

func TestConfigFieldBasicInt(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("port", ConfigFieldHelp("Port number"), ConfigFieldType(TypeInt), ConfigFieldDefault(8080))

	cf := app.configFields["port"]
	if cf.Type != TypeInt {
		t.Fatalf("expected TypeInt, got %d", cf.Type)
	}
	if cf.Default != 8080 {
		t.Fatalf("expected default 8080, got %v", cf.Default)
	}
}

func TestConfigFieldBasicFloat(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("threshold", ConfigFieldHelp("Detection threshold"), ConfigFieldType(TypeFloat), ConfigFieldDefault(0.95))

	cf := app.configFields["threshold"]
	if cf.Type != TypeFloat {
		t.Fatalf("expected TypeFloat, got %d", cf.Type)
	}
	if cf.Default != 0.95 {
		t.Fatalf("expected default 0.95, got %v", cf.Default)
	}
}

// --- Dot names (TOML sections) ---

func TestConfigFieldDotName(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("server.host", ConfigFieldHelp("Server hostname"), ConfigFieldDefault("localhost"))
	app.ConfigField("server.port", ConfigFieldHelp("Server port"), ConfigFieldType(TypeInt), ConfigFieldDefault(443))
	app.ConfigField("database.primary.host", ConfigFieldHelp("Primary database host"))

	if _, ok := app.configFields["server.host"]; !ok {
		t.Fatal("config field 'server.host' not registered")
	}
	if _, ok := app.configFields["server.port"]; !ok {
		t.Fatal("config field 'server.port' not registered")
	}
	if _, ok := app.configFields["database.primary.host"]; !ok {
		t.Fatal("config field 'database.primary.host' not registered")
	}
}

// --- Required vs optional ---

func TestConfigFieldRequired(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("api-key", ConfigFieldHelp("The API key"))

	cf := app.configFields["api-key"]
	if !cf.Required {
		t.Fatal("expected Required to be true (no default)")
	}
	if cf.HasDefault {
		t.Fatal("expected HasDefault to be false")
	}
}

func TestConfigFieldOptionalNilDefault(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("label", ConfigFieldHelp("Optional label"), ConfigFieldDefault(nil))

	cf := app.configFields["label"]
	if cf.Required {
		t.Fatal("expected Required to be false (has nil default)")
	}
	if !cf.HasDefault {
		t.Fatal("expected HasDefault to be true")
	}
}

// --- Type mismatch in default (panic) ---

func TestConfigFieldDefaultTypeMismatchStrGotInt(t *testing.T) {
	expectPanic(t, "default value type mismatch", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("name", ConfigFieldHelp("Name"), ConfigFieldDefault(42))
	})
}

func TestConfigFieldDefaultTypeMismatchIntGotStr(t *testing.T) {
	expectPanic(t, "default value type mismatch", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("port", ConfigFieldHelp("Port"), ConfigFieldType(TypeInt), ConfigFieldDefault("8080"))
	})
}

func TestConfigFieldDefaultTypeMismatchBoolGotStr(t *testing.T) {
	expectPanic(t, "default value type mismatch", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("verbose", ConfigFieldHelp("Verbose"), ConfigFieldType(TypeBool), ConfigFieldDefault("true"))
	})
}

func TestConfigFieldDefaultTypeMismatchFloatGotInt(t *testing.T) {
	expectPanic(t, "default value type mismatch", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("rate", ConfigFieldHelp("Rate"), ConfigFieldType(TypeFloat), ConfigFieldDefault(42))
	})
}

// --- Duplicate name (panic) ---

func TestConfigFieldDuplicateName(t *testing.T) {
	expectPanic(t, "duplicate name", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("name", ConfigFieldHelp("First"))
		app.ConfigField("name", ConfigFieldHelp("Second"))
	})
}

// --- Underscore prefix reserved (panic) ---

func TestConfigFieldUnderscorePrefix(t *testing.T) {
	expectPanic(t, "reserved for framework use", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("_internal", ConfigFieldHelp("Should fail"))
	})
}

func TestConfigFieldUnderscorePrefixWithDot(t *testing.T) {
	expectPanic(t, "reserved for framework use", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("_schema.version", ConfigFieldHelp("Should fail"))
	})
}

// --- Invalid name format ---

func TestConfigFieldInvalidNameUppercase(t *testing.T) {
	expectPanic(t, "invalid name", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("MyField", ConfigFieldHelp("Bad name"))
	})
}

func TestConfigFieldInvalidNameStartsWithDigit(t *testing.T) {
	expectPanic(t, "invalid name", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("1field", ConfigFieldHelp("Bad name"))
	})
}

func TestConfigFieldInvalidNameEmpty(t *testing.T) {
	expectPanic(t, "invalid name", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("", ConfigFieldHelp("Bad name"))
	})
}

// --- Missing help text ---

func TestConfigFieldMissingHelp(t *testing.T) {
	expectPanic(t, "help text is required", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("name")
	})
}

func TestConfigFieldEmptyHelp(t *testing.T) {
	expectPanic(t, "help text is required", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.ConfigField("name", ConfigFieldHelp("   "))
	})
}

// --- Framework field registration ---

func TestFrameworkFieldRegistration(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.registerFrameworkField("_schema_version", TypeStr, "Schema version for migration")

	cf, ok := app.frameworkFields["_schema_version"]
	if !ok {
		t.Fatal("framework field '_schema_version' not registered")
	}
	if cf.Type != TypeStr {
		t.Fatalf("expected TypeStr, got %d", cf.Type)
	}
	if cf.Help != "Schema version for migration" {
		t.Fatalf("expected help text, got %q", cf.Help)
	}
	if !cf.Required {
		t.Fatal("expected Required to be true (framework fields have no default)")
	}
}

func TestFrameworkFieldAllTypes(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.registerFrameworkField("_version", TypeStr, "Version")
	app.registerFrameworkField("_enabled", TypeBool, "Enabled")
	app.registerFrameworkField("_count", TypeInt, "Count")
	app.registerFrameworkField("_rate", TypeFloat, "Rate")

	if app.frameworkFields["_version"].Type != TypeStr {
		t.Fatal("wrong type for _version")
	}
	if app.frameworkFields["_enabled"].Type != TypeBool {
		t.Fatal("wrong type for _enabled")
	}
	if app.frameworkFields["_count"].Type != TypeInt {
		t.Fatal("wrong type for _count")
	}
	if app.frameworkFields["_rate"].Type != TypeFloat {
		t.Fatal("wrong type for _rate")
	}
}

func TestFrameworkFieldNoUnderscorePrefix(t *testing.T) {
	expectPanic(t, "name must start with '_'", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.registerFrameworkField("schema_version", TypeStr, "Should fail")
	})
}

func TestFrameworkFieldDuplicate(t *testing.T) {
	expectPanic(t, "duplicate name", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.registerFrameworkField("_ver", TypeStr, "First")
		app.registerFrameworkField("_ver", TypeStr, "Second")
	})
}

func TestFrameworkFieldMissingHelp(t *testing.T) {
	expectPanic(t, "help text is required", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.registerFrameworkField("_ver", TypeStr, "")
	})
}

// --- Cross-namespace duplicate detection ---

func TestConfigFieldConflictsWithFrameworkField(t *testing.T) {
	// User field with _ prefix is blocked by the reservation check,
	// so we test the other direction: framework field conflicting with user field.
	// Framework fields require _ prefix while user fields forbid it, so in practice
	// the namespaces don't overlap. This test verifies the underscore reservation fires.
	expectPanic(t, "reserved for framework use", func() {
		app := NewApp("test", "1.0.0", "test app")
		app.registerFrameworkField("_ver", TypeStr, "Version")
		app.ConfigField("_ver", ConfigFieldHelp("Conflict"))
	})
}

// --- Order preservation ---

func TestConfigFieldOrderPreserved(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("zebra", ConfigFieldHelp("Z field"))
	app.ConfigField("alpha", ConfigFieldHelp("A field"))
	app.ConfigField("middle", ConfigFieldHelp("M field"))

	expected := []string{"zebra", "alpha", "middle"}
	if len(app.configFieldOrder) != len(expected) {
		t.Fatalf("expected %d fields, got %d", len(expected), len(app.configFieldOrder))
	}
	for i, name := range expected {
		if app.configFieldOrder[i] != name {
			t.Fatalf("order[%d]: expected %q, got %q", i, name, app.configFieldOrder[i])
		}
	}
}

func TestFrameworkFieldOrderPreserved(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.registerFrameworkField("_z", TypeStr, "Z")
	app.registerFrameworkField("_a", TypeStr, "A")
	app.registerFrameworkField("_m", TypeStr, "M")

	expected := []string{"_z", "_a", "_m"}
	if len(app.frameworkFieldOrder) != len(expected) {
		t.Fatalf("expected %d fields, got %d", len(expected), len(app.frameworkFieldOrder))
	}
	for i, name := range expected {
		if app.frameworkFieldOrder[i] != name {
			t.Fatalf("order[%d]: expected %q, got %q", i, name, app.frameworkFieldOrder[i])
		}
	}
}

// --- Name with hyphens and underscores ---

func TestConfigFieldNameWithHyphens(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	if _, ok := app.configFields["api-key"]; !ok {
		t.Fatal("config field 'api-key' not registered")
	}
}

func TestConfigFieldNameWithUnderscoresNonPrefix(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("api_key", ConfigFieldHelp("API key"))
	if _, ok := app.configFields["api_key"]; !ok {
		t.Fatal("config field 'api_key' not registered")
	}
}
