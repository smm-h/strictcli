package strictcli

import (
	"os"
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

// === 5c: Per-command config field binding ===

func TestWithConfigFieldsStoresOnCommand(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))

	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("api-key", "region"))

	cmd := app.commands["deploy"]
	if len(cmd.configFields) != 2 {
		t.Fatalf("expected 2 config fields, got %d", len(cmd.configFields))
	}
	if cmd.configFields[0] != "api-key" || cmd.configFields[1] != "region" {
		t.Fatalf("unexpected config fields: %v", cmd.configFields)
	}
}

func TestWithConfigFieldsValidationAtRunTime(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	// Bind a config field that doesn't exist — should fail at Test() time
	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("nonexistent"))

	r := app.Test([]string{"deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "config field \"nonexistent\" is not declared") {
		t.Fatalf("expected undeclared config field error, got: %s", r.Stderr)
	}
}

func TestWithConfigFieldsValidBinding(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))
	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("region"))

	// Should succeed since "region" is declared and has a default
	r := app.Test([]string{"deploy"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}
}

func TestWithConfigFieldsInGroup(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("api-key", ConfigFieldHelp("API key"), ConfigFieldDefault("default-key"))

	grp := app.Group("infra", "Infrastructure commands")
	grp.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("api-key"))

	// Should validate correctly
	r := app.Test([]string{"infra", "deploy"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}
}

func TestWithConfigFieldsInGroupUnknownField(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")

	grp := app.Group("infra", "Infrastructure commands")
	grp.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("ghost-field"))

	r := app.Test([]string{"infra", "deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "config field \"ghost-field\" is not declared") {
		t.Fatalf("expected undeclared config field error, got: %s", r.Stderr)
	}
}

// === 5d: Config field validation at startup ===

func TestConfigFieldValidationRequiredFieldMissing(t *testing.T) {
	// Create a temp config file with no api-key
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("api-key"))

	r := app.Test([]string{"deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "config field 'api-key' is required but not set") {
		t.Fatalf("expected required field error, got: %s", r.Stderr)
	}
}

func TestConfigFieldValidationRequiredFieldPresent(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"api-key": "my-secret"}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("api-key"))

	r := app.Test([]string{"deploy"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}
}

func TestConfigFieldValidationTypeMismatch(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"port": "not-a-number"}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("port", ConfigFieldHelp("Port number"), ConfigFieldType(TypeInt))
	app.Command("serve", "Start server", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("port"))

	r := app.Test([]string{"serve"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "config field 'port'") {
		t.Fatalf("expected type mismatch error, got: %s", r.Stderr)
	}
}

func TestConfigFieldValidationOptionalFieldMissing(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))
	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("region"))

	r := app.Test([]string{"deploy"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0 (optional field), got %d. stderr: %s", r.ExitCode, r.Stderr)
	}
}

func TestConfigFieldValidationUnknownKeyInConfig(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"api-key": "secret", "bogus_key": "value"}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("api-key"))

	r := app.Test([]string{"deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown key 'bogus_key'") {
		t.Fatalf("expected unknown key error, got: %s", r.Stderr)
	}
}

func TestConfigFieldValidationConfigSubcommandExempt(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	// No config file exists — config subcommands should still work
	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("api-key", ConfigFieldHelp("API key")) // required, not set

	r := app.Test([]string{"config", "path"})
	if r.ExitCode != 0 {
		t.Fatalf("config subcommand should be exempt from validation, got exit %d. stderr: %s", r.ExitCode, r.Stderr)
	}
}

func TestConfigFieldValidationNoConfigFieldsSkipsValidation(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"random_key": true}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	// Command has no config fields bound — validation should not run
	app.Command("status", "Show status", func(args map[string]interface{}) int {
		return 0
	})

	r := app.Test([]string{"status"})
	if r.ExitCode != 0 {
		t.Fatalf("no config fields bound — should skip validation, got exit %d. stderr: %s", r.ExitCode, r.Stderr)
	}
}

// === 5e: Config show and config set with config fields ===

func TestConfigShowIncludesConfigFields(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"region": "eu-west-1"}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))

	r := app.Test([]string{"config", "show", "--plain"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "region = eu-west-1") {
		t.Fatalf("expected region in output, got: %s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "source: config") {
		t.Fatalf("expected source: config, got: %s", r.Stdout)
	}
	// api-key should show as nil/default since it's not in the file
	if !strings.Contains(r.Stdout, "api-key") {
		t.Fatalf("expected api-key in output, got: %s", r.Stdout)
	}
}

func TestConfigShowJSONIncludesConfigFields(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"region": "eu-west-1"}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))

	r := app.Test([]string{"config", "show", "--json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, `"region"`) {
		t.Fatalf("expected region in JSON output, got: %s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, `"eu-west-1"`) {
		t.Fatalf("expected eu-west-1 in JSON output, got: %s", r.Stdout)
	}
}

func TestConfigSetConfigField(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))

	r := app.Test([]string{"config", "set", "region", "eu-west-1"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	// Verify it was written
	data, _ := os.ReadFile(configFile)
	if !strings.Contains(string(data), `"eu-west-1"`) {
		t.Fatalf("expected eu-west-1 in config file, got: %s", string(data))
	}
}

func TestConfigSetConfigFieldTypeBool(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("verbose", ConfigFieldHelp("Verbose output"), ConfigFieldType(TypeBool), ConfigFieldDefault(false))

	r := app.Test([]string{"config", "set", "verbose", "true"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, _ := os.ReadFile(configFile)
	if !strings.Contains(string(data), "true") {
		t.Fatalf("expected true in config file, got: %s", string(data))
	}
}

func TestConfigSetConfigFieldTypeInt(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("port", ConfigFieldHelp("Port number"), ConfigFieldType(TypeInt), ConfigFieldDefault(8080))

	r := app.Test([]string{"config", "set", "port", "9090"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, _ := os.ReadFile(configFile)
	if !strings.Contains(string(data), "9090") {
		t.Fatalf("expected 9090 in config file, got: %s", string(data))
	}
}

func TestConfigSetConfigFieldTypeFloat(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("threshold", ConfigFieldHelp("Detection threshold"), ConfigFieldType(TypeFloat), ConfigFieldDefault(0.5))

	r := app.Test([]string{"config", "set", "threshold", "0.95"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, _ := os.ReadFile(configFile)
	if !strings.Contains(string(data), "0.95") {
		t.Fatalf("expected 0.95 in config file, got: %s", string(data))
	}
}

func TestConfigSetConfigFieldInvalidType(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("port", ConfigFieldHelp("Port number"), ConfigFieldType(TypeInt))

	r := app.Test([]string{"config", "set", "port", "not-a-number"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "expected integer") {
		t.Fatalf("expected type error, got: %s", r.Stderr)
	}
}

func TestConfigSetUnknownKey(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))

	r := app.Test([]string{"config", "set", "nonexistent", "value"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown key") {
		t.Fatalf("expected unknown key error, got: %s", r.Stderr)
	}
}

func TestConfigSetConfigFieldClearNotAllowed(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))

	r := app.Test([]string{"config", "set", "region", "--clear"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--clear is only for repeatable flags") {
		t.Fatalf("expected clear error, got: %s", r.Stderr)
	}
}

func TestConfigSetConfigFieldDefault(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{"region": "eu-west-1"}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))

	r := app.Test([]string{"config", "set", "region", "--default"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, _ := os.ReadFile(configFile)
	if strings.Contains(string(data), "region") {
		t.Fatalf("expected region to be removed from config, got: %s", string(data))
	}
}

// === 5f: config init ===

func TestConfigInitJSON(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	app.ConfigField("port", ConfigFieldHelp("Port number"), ConfigFieldType(TypeInt), ConfigFieldDefault(8080))
	app.Command("deploy", "Deploy", func(args map[string]interface{}) int { return 0 })

	r := app.Test([]string{"config", "init"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, err := os.ReadFile(configFile)
	if err != nil {
		t.Fatalf("config file not created: %v", err)
	}
	content := string(data)
	if !strings.Contains(content, "us-east-1") {
		t.Fatalf("expected default region in template, got: %s", content)
	}
	if !strings.Contains(content, "8080") {
		t.Fatalf("expected default port in template, got: %s", content)
	}
}

func TestConfigInitTOML(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.toml"

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile), WithConfigFormat("toml"))
	app.ConfigField("region", ConfigFieldHelp("Region"), ConfigFieldDefault("us-east-1"))
	app.ConfigField("server.host", ConfigFieldHelp("Server hostname"), ConfigFieldDefault("localhost"))
	app.ConfigField("server.port", ConfigFieldHelp("Server port"), ConfigFieldType(TypeInt), ConfigFieldDefault(443))
	app.ConfigField("api-key", ConfigFieldHelp("API key"))
	app.Command("deploy", "Deploy", func(args map[string]interface{}) int { return 0 })

	r := app.Test([]string{"config", "init"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, err := os.ReadFile(configFile)
	if err != nil {
		t.Fatalf("config file not created: %v", err)
	}
	content := string(data)
	if !strings.Contains(content, "[server]") {
		t.Fatalf("expected [server] section in TOML template, got: %s", content)
	}
	if !strings.Contains(content, "us-east-1") {
		t.Fatalf("expected default region in TOML template, got: %s", content)
	}
	if !strings.Contains(content, "REQUIRED") {
		t.Fatalf("expected REQUIRED marker for api-key, got: %s", content)
	}
}

func TestConfigInitErrorIfExists(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"
	os.WriteFile(configFile, []byte(`{}`), 0o644)

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.Command("deploy", "Deploy", func(args map[string]interface{}) int { return 0 })

	r := app.Test([]string{"config", "init"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit code 1 (file exists), got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "already exists") {
		t.Fatalf("expected already exists error, got: %s", r.Stderr)
	}
}

func TestConfigInitJSONNested(t *testing.T) {
	dir := t.TempDir()
	configFile := dir + "/config.json"

	app := NewApp("test", "1.0.0", "test app", WithConfig(), WithConfigPath(configFile))
	app.ConfigField("db.host", ConfigFieldHelp("Database host"), ConfigFieldDefault("localhost"))
	app.ConfigField("db.port", ConfigFieldHelp("Database port"), ConfigFieldType(TypeInt), ConfigFieldDefault(5432))
	app.Command("serve", "Serve", func(args map[string]interface{}) int { return 0 })

	r := app.Test([]string{"config", "init"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit code 0, got %d. stderr: %s", r.ExitCode, r.Stderr)
	}

	data, _ := os.ReadFile(configFile)
	content := string(data)
	// Should have nested structure
	if !strings.Contains(content, "localhost") {
		t.Fatalf("expected localhost in nested JSON, got: %s", content)
	}
	if !strings.Contains(content, "5432") {
		t.Fatalf("expected 5432 in nested JSON, got: %s", content)
	}
}

// === 5g: Schema serialization ===

func TestSchemaIncludesConfigFields(t *testing.T) {
	chdirTemp(t)
	app := NewApp("test", "1.0.0", "test app")
	app.ConfigField("region", ConfigFieldHelp("AWS region"), ConfigFieldDefault("us-east-1"))
	app.ConfigField("port", ConfigFieldHelp("Port number"), ConfigFieldType(TypeInt))

	app.Command("deploy", "Deploy the app", func(args map[string]interface{}) int {
		return 0
	}, WithConfigFields("region", "port"))

	schema, err := dumpSchema(app)
	if err != nil {
		t.Fatalf("dumpSchema error: %v", err)
	}

	cfFields, ok := schema["config_fields"]
	if !ok {
		t.Fatal("expected config_fields in schema")
	}
	fieldList, ok := cfFields.([]interface{})
	if !ok {
		t.Fatalf("expected config_fields to be a slice, got %T", cfFields)
	}
	if len(fieldList) != 2 {
		t.Fatalf("expected 2 config fields in schema, got %d", len(fieldList))
	}

	// Check first field (region)
	field0 := fieldList[0].(map[string]interface{})
	if field0["name"] != "region" {
		t.Fatalf("expected first field name 'region', got %v", field0["name"])
	}
	if field0["type"] != "str" {
		t.Fatalf("expected first field type 'str', got %v", field0["type"])
	}
	if field0["help"] != "AWS region" {
		t.Fatalf("expected first field help 'AWS region', got %v", field0["help"])
	}
	if field0["required"] != false {
		t.Fatalf("expected first field required false, got %v", field0["required"])
	}
	if field0["default"] != "us-east-1" {
		t.Fatalf("expected first field default 'us-east-1', got %v", field0["default"])
	}
	// Check commands binding
	cmds0, ok := field0["commands"]
	if !ok {
		t.Fatal("expected commands key for region")
	}
	cmdList0 := cmds0.([]interface{})
	if len(cmdList0) != 1 || cmdList0[0] != "deploy" {
		t.Fatalf("expected commands ['deploy'], got %v", cmdList0)
	}

	// Check second field (port)
	field1 := fieldList[1].(map[string]interface{})
	if field1["name"] != "port" {
		t.Fatalf("expected second field name 'port', got %v", field1["name"])
	}
	if field1["type"] != "int" {
		t.Fatalf("expected second field type 'int', got %v", field1["type"])
	}
	if field1["required"] != true {
		t.Fatalf("expected second field required true, got %v", field1["required"])
	}
}

func TestSchemaNoConfigFieldsWhenNoneDeclared(t *testing.T) {
	chdirTemp(t)
	app := NewApp("test", "1.0.0", "test app")
	app.Command("hello", "Say hello", func(args map[string]interface{}) int {
		return 0
	})

	schema, err := dumpSchema(app)
	if err != nil {
		t.Fatalf("dumpSchema error: %v", err)
	}

	if _, ok := schema["config_fields"]; ok {
		t.Fatal("expected no config_fields key when none are declared")
	}
}
