package strictcli

import (
	"reflect"
	"sort"
	"testing"
)

// nopHandler is a handler that does nothing and returns 0.
func nopHandler(kwargs map[string]interface{}) int {
	return 0
}

// --- JsonSchema tests ---

func TestJsonSchemaAllScalarTypes(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run something", nopHandler, WithFlags(
		StringFlag("name", "a string flag"),
		IntFlag("count", "an integer flag"),
		FloatFlag("ratio", "a float flag"),
		BoolFlag("verbose", "a bool flag"),
	))

	schema := app.JsonSchema("run")

	props, ok := schema["properties"].(map[string]interface{})
	if !ok {
		t.Fatal("missing or wrong-typed 'properties'")
	}

	cases := []struct {
		param    string
		jsonType string
	}{
		{"name", "string"},
		{"count", "integer"},
		{"ratio", "number"},
		{"verbose", "boolean"},
	}

	for _, tc := range cases {
		prop, ok := props[tc.param].(map[string]interface{})
		if !ok {
			t.Fatalf("missing property %q", tc.param)
		}
		if prop["type"] != tc.jsonType {
			t.Errorf("%s: expected type %q, got %q", tc.param, tc.jsonType, prop["type"])
		}
	}
}

func TestJsonSchemaRequiredFlags(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("deploy", "deploy something", nopHandler, WithFlags(
		StringFlag("target", "deploy target"),               // required (no default)
		IntFlag("replicas", "replica count"),                 // required (no default)
		StringFlag("region", "region", Default("us-east-1")), // optional (has default)
		BoolFlag("dry-run", "dry run mode"),                  // optional (bool always defaults to false)
		FloatFlag("threshold", "threshold", Default(0.5)),    // optional (has default)
	))

	schema := app.JsonSchema("deploy")

	required, ok := schema["required"].([]interface{})
	if !ok {
		t.Fatal("missing or wrong-typed 'required'")
	}

	// Convert to string slice and sort for stable comparison
	var reqStrs []string
	for _, r := range required {
		reqStrs = append(reqStrs, r.(string))
	}
	sort.Strings(reqStrs)

	expected := []string{"replicas", "target"}
	if !reflect.DeepEqual(reqStrs, expected) {
		t.Errorf("required: expected %v, got %v", expected, reqStrs)
	}
}

func TestJsonSchemaOptionalFlagNotInRequired(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run something", nopHandler, WithFlags(
		StringFlag("mode", "mode", Default("fast")),
		BoolFlag("verbose", "verbosity"),
	))

	schema := app.JsonSchema("run")

	// No required flags (both have defaults / are bool)
	required := schema["required"]
	if required != nil {
		if reqSlice, ok := required.([]interface{}); ok && len(reqSlice) > 0 {
			t.Errorf("expected no required flags, got %v", reqSlice)
		}
	}
}

func TestJsonSchemaChoicesAsEnum(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("deploy", "deploy", nopHandler, WithFlags(
		StringFlag("env", "environment", Choices("dev", "staging", "prod")),
	))

	schema := app.JsonSchema("deploy")
	props := schema["properties"].(map[string]interface{})
	envProp := props["env"].(map[string]interface{})

	enumVals, ok := envProp["enum"].([]interface{})
	if !ok {
		t.Fatal("missing 'enum' on choices flag")
	}

	expected := []interface{}{"dev", "staging", "prod"}
	if !reflect.DeepEqual(enumVals, expected) {
		t.Errorf("enum: expected %v, got %v", expected, enumVals)
	}
}

func TestJsonSchemaListType(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler, WithFlags(
		ListFlag(TypeStr, "tags", "tag list", Unique(false)),
		ListFlag(TypeInt, "ports", "port list", Unique(false)),
		ListFlag(TypeFloat, "weights", "weight list", Unique(false)),
	))

	schema := app.JsonSchema("run")
	props := schema["properties"].(map[string]interface{})

	cases := []struct {
		param    string
		itemType string
	}{
		{"tags", "string"},
		{"ports", "integer"},
		{"weights", "number"},
	}

	for _, tc := range cases {
		prop := props[tc.param].(map[string]interface{})
		if prop["type"] != "array" {
			t.Errorf("%s: expected type 'array', got %q", tc.param, prop["type"])
		}
		items := prop["items"].(map[string]interface{})
		if items["type"] != tc.itemType {
			t.Errorf("%s items: expected type %q, got %q", tc.param, tc.itemType, items["type"])
		}
	}
}

func TestJsonSchemaDictType(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler, WithFlags(
		DictFlag(TypeStr, "labels", "label map", Unique(false)),
		DictFlag(TypeInt, "counts", "count map", Unique(false)),
	))

	schema := app.JsonSchema("run")
	props := schema["properties"].(map[string]interface{})

	cases := []struct {
		param    string
		valType  string
	}{
		{"labels", "string"},
		{"counts", "integer"},
	}

	for _, tc := range cases {
		prop := props[tc.param].(map[string]interface{})
		if prop["type"] != "object" {
			t.Errorf("%s: expected type 'object', got %q", tc.param, prop["type"])
		}
		addProps := prop["additionalProperties"].(map[string]interface{})
		if addProps["type"] != tc.valType {
			t.Errorf("%s additionalProperties: expected type %q, got %q", tc.param, tc.valType, addProps["type"])
		}
	}
}

func TestJsonSchemaHelpAsDescription(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler, WithFlags(
		StringFlag("name", "the user name"),
	))

	schema := app.JsonSchema("run")
	props := schema["properties"].(map[string]interface{})
	nameProp := props["name"].(map[string]interface{})

	if nameProp["description"] != "the user name" {
		t.Errorf("description: expected %q, got %q", "the user name", nameProp["description"])
	}
}

func TestJsonSchemaPositionalArg(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("greet", "greet someone", nopHandler,
		WithArgs(NewArg("person", "who to greet")),
	)

	schema := app.JsonSchema("greet")
	props := schema["properties"].(map[string]interface{})

	personProp, ok := props["person"].(map[string]interface{})
	if !ok {
		t.Fatal("missing property 'person' for positional arg")
	}
	if personProp["type"] != "string" {
		t.Errorf("expected type 'string', got %q", personProp["type"])
	}

	// Required positional arg should be in required array
	required := schema["required"].([]interface{})
	found := false
	for _, r := range required {
		if r.(string) == "person" {
			found = true
			break
		}
	}
	if !found {
		t.Error("positional arg 'person' should be in required")
	}
}

func TestJsonSchemaArgChoices(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("set-level", "set level", nopHandler,
		WithArgs(NewArg("level", "log level", ArgChoices("debug", "info", "warn", "error"))),
	)

	schema := app.JsonSchema("set-level")
	props := schema["properties"].(map[string]interface{})
	levelProp := props["level"].(map[string]interface{})

	enumVals, ok := levelProp["enum"].([]interface{})
	if !ok {
		t.Fatal("missing 'enum' on choices arg")
	}
	expected := []interface{}{"debug", "info", "warn", "error"}
	if !reflect.DeepEqual(enumVals, expected) {
		t.Errorf("enum: expected %v, got %v", expected, enumVals)
	}
}

func TestJsonSchemaVariadicArg(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler,
		WithArgs(NewArg("files", "files to process", ArgRequired(false), Variadic())),
	)

	schema := app.JsonSchema("run")
	props := schema["properties"].(map[string]interface{})
	filesProp := props["files"].(map[string]interface{})

	if filesProp["type"] != "array" {
		t.Errorf("expected type 'array' for variadic arg, got %q", filesProp["type"])
	}
	items := filesProp["items"].(map[string]interface{})
	if items["type"] != "string" {
		t.Errorf("expected items type 'string', got %q", items["type"])
	}
}

func TestJsonSchemaAdditionalPropertiesFalse(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler)

	schema := app.JsonSchema("run")
	if schema["additionalProperties"] != false {
		t.Error("expected additionalProperties to be false")
	}
	if schema["type"] != "object" {
		t.Errorf("expected top-level type 'object', got %q", schema["type"])
	}
}

func TestJsonSchemaDashedFlagBecomesUnderscored(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler, WithFlags(
		BoolFlag("dry-run", "dry run mode"),
	))

	schema := app.JsonSchema("run")
	props := schema["properties"].(map[string]interface{})

	if _, ok := props["dry_run"]; !ok {
		t.Error("expected dashed flag 'dry-run' to appear as 'dry_run' in schema")
	}
	if _, ok := props["dry-run"]; ok {
		t.Error("dashed flag name should not appear in schema")
	}
}

func TestJsonSchemaGroupedCommand(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	g := app.Group("dns", "manage DNS")
	g.Command("list", "list DNS records", nopHandler, WithFlags(
		StringFlag("zone", "DNS zone"),
	))

	schema := app.JsonSchema("dns.list")
	props := schema["properties"].(map[string]interface{})
	if _, ok := props["zone"]; !ok {
		t.Error("expected 'zone' property for grouped command")
	}
}

func TestJsonSchemaPanicsOnInvalidPath(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler)

	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for invalid path")
		}
	}()
	app.JsonSchema("nonexistent")
}

func TestJsonSchemaPanicsOnGroup(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	g := app.Group("dns", "manage DNS")
	g.Command("list", "list", nopHandler)

	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic when path resolves to group")
		}
	}()
	app.JsonSchema("dns")
}

// --- AsTools tests ---

func TestAsToolsCount(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy something", nopHandler)
	app.Command("status", "check status", nopHandler)
	app.Command("rollback", "rollback deploy", nopHandler)

	tools := app.AsTools()

	// 3 commands + 1 router = 4
	if len(tools) != 4 {
		t.Fatalf("expected 4 tools (3 commands + router), got %d", len(tools))
	}
}

func TestAsToolsHiddenExclusion(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy something", nopHandler)
	app.Command("internal", "internal command", nopHandler, WithHidden())

	tools := app.AsTools()

	// 1 visible + 1 router = 2
	if len(tools) != 2 {
		t.Fatalf("expected 2 tools (1 visible + router), got %d", len(tools))
	}

	// Verify hidden command is not among tools
	for _, tool := range tools {
		if tool.Name == "internal" {
			t.Error("hidden command should not appear in AsTools")
		}
	}
}

func TestAsToolsInteractiveExclusion(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy something", nopHandler)
	app.Command("wizard", "interactive wizard", nopHandler, WithInteractive())

	tools := app.AsTools()

	// 1 visible non-interactive + 1 router = 2
	if len(tools) != 2 {
		t.Fatalf("expected 2 tools (1 non-interactive + router), got %d", len(tools))
	}

	for _, tool := range tools {
		if tool.Name == "wizard" {
			t.Error("interactive command should not appear in AsTools")
		}
	}
}

func TestAsToolsHiddenGroupExclusion(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy something", nopHandler)

	g := app.Group("secret", "secret commands")
	g.Hidden = true
	g.Command("internal", "internal command", nopHandler)

	tools := app.AsTools()

	// 1 visible + 1 router = 2 (hidden group's commands excluded)
	if len(tools) != 2 {
		t.Fatalf("expected 2 tools (1 visible + router), got %d", len(tools))
	}

	for _, tool := range tools {
		if tool.Name == "secret.internal" {
			t.Error("command in hidden group should not appear in AsTools")
		}
	}
}

func TestAsToolsGroupedCommands(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("status", "check status", nopHandler)

	dns := app.Group("dns", "manage DNS")
	dns.Command("list", "list records", nopHandler)
	dns.Command("create", "create record", nopHandler)

	zone := dns.Group("zone", "manage zones")
	zone.Command("delete", "delete zone", nopHandler)

	tools := app.AsTools()

	// 1 top-level + 2 dns commands + 1 nested zone command + 1 router = 5
	if len(tools) != 5 {
		t.Fatalf("expected 5 tools, got %d", len(tools))
	}

	// Verify dot-separated paths
	nameSet := make(map[string]bool)
	for _, tool := range tools {
		nameSet[tool.Name] = true
	}

	expectedNames := []string{"status", "dns.list", "dns.create", "dns.zone.delete", "myapp"}
	for _, name := range expectedNames {
		if !nameSet[name] {
			t.Errorf("expected tool %q in AsTools output", name)
		}
	}
}

func TestAsToolsToolDescription(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy the application", nopHandler)

	tools := app.AsTools()

	// Find the deploy tool
	for _, tool := range tools {
		if tool.Name == "deploy" {
			if tool.Description != "deploy the application" {
				t.Errorf("expected description %q, got %q", "deploy the application", tool.Description)
			}
			return
		}
	}
	t.Fatal("deploy tool not found")
}

func TestAsToolsToolParameters(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler, WithFlags(
		StringFlag("target", "deploy target"),
		BoolFlag("dry-run", "dry run"),
	))

	tools := app.AsTools()

	for _, tool := range tools {
		if tool.Name == "deploy" {
			if tool.Parameters == nil {
				t.Fatal("tool parameters should not be nil")
			}
			props := tool.Parameters["properties"].(map[string]interface{})
			if _, ok := props["target"]; !ok {
				t.Error("missing 'target' in tool parameters")
			}
			if _, ok := props["dry_run"]; !ok {
				t.Error("missing 'dry_run' in tool parameters")
			}
			return
		}
	}
	t.Fatal("deploy tool not found")
}

// --- Router tool tests ---

func TestRouterToolName(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler)
	app.Command("status", "status", nopHandler)

	tools := app.AsTools()

	// Router tool should be last and named after the app
	router := tools[len(tools)-1]
	if router.Name != "myapp" {
		t.Errorf("router tool name: expected %q, got %q", "myapp", router.Name)
	}
}

func TestRouterToolDescription(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler)

	tools := app.AsTools()
	router := tools[len(tools)-1]

	if router.Description != "Route to myapp commands" {
		t.Errorf("router description: expected %q, got %q", "Route to myapp commands", router.Description)
	}
}

func TestRouterToolCommandEnum(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler)
	app.Command("status", "status", nopHandler)

	tools := app.AsTools()
	router := tools[len(tools)-1]

	params := router.Parameters
	props := params["properties"].(map[string]interface{})
	cmdProp := props["command"].(map[string]interface{})
	enumVals := cmdProp["enum"].([]interface{})

	expected := []interface{}{"deploy", "status"}
	if !reflect.DeepEqual(enumVals, expected) {
		t.Errorf("router enum: expected %v, got %v", expected, enumVals)
	}
}

func TestRouterToolCommandRequired(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler)

	tools := app.AsTools()
	router := tools[len(tools)-1]

	required := router.Parameters["required"].([]interface{})
	if len(required) != 1 || required[0] != "command" {
		t.Errorf("router required: expected [\"command\"], got %v", required)
	}
}

func TestRouterToolListsCommandsWithoutArg(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler)
	app.Command("status", "status", nopHandler)

	tools := app.AsTools()
	router := tools[len(tools)-1]

	// Call without "command" kwarg -- should return list of commands
	result, err := router.Execute(map[string]interface{}{})
	if err != nil {
		t.Fatalf("router execute error: %v", err)
	}

	cmdList, ok := result.([]string)
	if !ok {
		t.Fatalf("expected []string, got %T", result)
	}

	expected := []string{"deploy", "status"}
	if !reflect.DeepEqual(cmdList, expected) {
		t.Errorf("router list: expected %v, got %v", expected, cmdList)
	}
}

// --- Execute tests ---

func TestExecuteViaTool(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("greet", "greet someone", captureHandler(&captured), WithFlags(
		StringFlag("name", "who to greet"),
	))

	tools := app.AsTools()

	// Find the greet tool
	var greetTool *Tool
	for i := range tools {
		if tools[i].Name == "greet" {
			greetTool = &tools[i]
			break
		}
	}
	if greetTool == nil {
		t.Fatal("greet tool not found")
	}

	result, err := greetTool.Execute(map[string]interface{}{
		"name": "world",
	})
	if err != nil {
		t.Fatalf("execute error: %v", err)
	}

	// Regular handler returns exit code
	if result != 0 {
		t.Errorf("expected exit code 0, got %v", result)
	}
	if captured["name"] != "world" {
		t.Errorf("expected name='world', got %v", captured["name"])
	}
}

func TestExecuteViaRouterTool(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", captureHandler(&captured), WithFlags(
		StringFlag("target", "deploy target"),
	))

	tools := app.AsTools()
	router := tools[len(tools)-1]

	result, err := router.Execute(map[string]interface{}{
		"command": "deploy",
		"target":  "production",
	})
	if err != nil {
		t.Fatalf("router execute error: %v", err)
	}

	if result != 0 {
		t.Errorf("expected exit code 0, got %v", result)
	}
	if captured["target"] != "production" {
		t.Errorf("expected target='production', got %v", captured["target"])
	}
}

func TestExecuteGroupedCommandViaTool(t *testing.T) {
	var captured map[string]interface{}
	app := NewApp("myapp", "1.0.0", "my application")

	dns := app.Group("dns", "manage DNS")
	dns.Command("list", "list records", captureHandler(&captured), WithFlags(
		StringFlag("zone", "DNS zone"),
	))

	tools := app.AsTools()

	var listTool *Tool
	for i := range tools {
		if tools[i].Name == "dns.list" {
			listTool = &tools[i]
			break
		}
	}
	if listTool == nil {
		t.Fatal("dns.list tool not found")
	}

	result, err := listTool.Execute(map[string]interface{}{
		"zone": "example.com",
	})
	if err != nil {
		t.Fatalf("execute error: %v", err)
	}

	if result != 0 {
		t.Errorf("expected exit code 0, got %v", result)
	}
	if captured["zone"] != "example.com" {
		t.Errorf("expected zone='example.com', got %v", captured["zone"])
	}
}

func TestExecuteReturnsError(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler, WithFlags(
		StringFlag("target", "deploy target"),
	))

	tools := app.AsTools()

	var deployTool *Tool
	for i := range tools {
		if tools[i].Name == "deploy" {
			deployTool = &tools[i]
			break
		}
	}
	if deployTool == nil {
		t.Fatal("deploy tool not found")
	}

	// Call without required flag -- should return error
	_, err := deployTool.Execute(map[string]interface{}{})
	if err == nil {
		t.Fatal("expected error for missing required flag")
	}

	invokeErr, ok := err.(*InvokeError)
	if !ok {
		t.Fatalf("expected *InvokeError, got %T", err)
	}
	if invokeErr.Message == "" {
		t.Error("expected non-empty error message")
	}
}

func TestExecuteDataHandler(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.DataCommand("info", "get info", func(kwargs map[string]interface{}) HandlerResult {
		return HandlerResult{
			Data:     map[string]string{"version": "1.0.0"},
			ExitCode: 0,
		}
	})

	tools := app.AsTools()

	var infoTool *Tool
	for i := range tools {
		if tools[i].Name == "info" {
			infoTool = &tools[i]
			break
		}
	}
	if infoTool == nil {
		t.Fatal("info tool not found")
	}

	result, err := infoTool.Execute(map[string]interface{}{})
	if err != nil {
		t.Fatalf("execute error: %v", err)
	}

	data, ok := result.(map[string]string)
	if !ok {
		t.Fatalf("expected map[string]string, got %T", result)
	}
	if data["version"] != "1.0.0" {
		t.Errorf("expected version='1.0.0', got %v", data["version"])
	}
}

func TestRouterToolInvalidCommandType(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("deploy", "deploy", nopHandler)

	tools := app.AsTools()
	router := tools[len(tools)-1]

	// Pass non-string command
	_, err := router.Execute(map[string]interface{}{
		"command": 42,
	})
	if err == nil {
		t.Fatal("expected error for non-string command")
	}
}

func TestAsToolsRepeatableFlagNotRequired(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")
	app.Command("run", "run", nopHandler, WithFlags(
		StringFlag("tag", "a tag", Repeatable(), Unique(false)),
	))

	schema := app.JsonSchema("run")

	// Repeatable flags should not be required (they default to empty)
	required := schema["required"]
	if required != nil {
		if reqSlice, ok := required.([]interface{}); ok {
			for _, r := range reqSlice {
				if r == "tag" {
					t.Error("repeatable flag should not be required")
				}
			}
		}
	}
}

func TestAsToolsEmptyApp(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "my application")

	tools := app.AsTools()

	// Just the router tool
	if len(tools) != 1 {
		t.Fatalf("expected 1 tool (router only), got %d", len(tools))
	}
	if tools[0].Name != "myapp" {
		t.Errorf("expected router tool name 'myapp', got %q", tools[0].Name)
	}
}

func TestJsonSchemaNoCommandFlags(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("noop", "does nothing", nopHandler)

	schema := app.JsonSchema("noop")

	props := schema["properties"].(map[string]interface{})
	if len(props) != 0 {
		t.Errorf("expected empty properties for command with no flags, got %v", props)
	}
}

func TestJsonSchemaDefaultNilOptional(t *testing.T) {
	app := NewApp("test", "1.0.0", "test app")
	app.Command("run", "run", nopHandler, WithFlags(
		StringFlag("config", "config path", Default(nil)),
	))

	schema := app.JsonSchema("run")

	// Default(nil) means optional -- should not be in required
	required := schema["required"]
	if required != nil {
		if reqSlice, ok := required.([]interface{}); ok {
			for _, r := range reqSlice {
				if r == "config" {
					t.Error("flag with Default(nil) should not be required")
				}
			}
		}
	}
}
