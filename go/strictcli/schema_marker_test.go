package strictcli

import (
	"encoding/json"
	"os"
	"reflect"
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
	app.Command("run", "run it", func(kwargs map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("db", "db path",
			Default(RelativeToRoot("MYAPP_HOME", "sub", "db.sqlite")))))

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
