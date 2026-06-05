package strictcli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// flagTypeName maps FlagType to its string representation for schema output.
var flagTypeName = map[FlagType]string{
	TypeStr:   "str",
	TypeBool:  "bool",
	TypeInt:   "int",
	TypeFloat: "float",
}

// serializeFlag converts a Flag to a JSON-serializable map matching the Python format.
// Fields matching their defaults are omitted; see buildSchemaDefaults().
func serializeFlag(f Flag) map[string]interface{} {
	m := map[string]interface{}{
		"name": f.Name,
		"type": flagTypeName[f.Type],
		"help": f.Help,
	}

	// short: default nil (omit when empty string -> nil)
	if f.Short != "" {
		m["short"] = f.Short
	}

	// default: default nil (omit when nil, unless repeatable with no explicit default)
	dflt := f.Default
	if f.Repeatable && f.Default == nil && !f.hasDefault {
		dflt = []interface{}{}
	}
	if dflt != nil {
		m["default"] = dflt
	}

	// env: default nil (omit when empty string -> nil)
	if f.Env != "" {
		m["env"] = f.Env
	}

	// choices: default nil (omit when nil)
	if f.Choices != nil {
		m["choices"] = f.Choices
	}

	// repeatable: default false (omit when false)
	if f.Repeatable {
		m["repeatable"] = true
	}

	// unique: default false (omit when false)
	if f.Unique {
		m["unique"] = true
	}

	// env_separator: default "" (omit when empty)
	if f.EnvSeparator != "" {
		m["env_separator"] = f.EnvSeparator
	}

	// negatable: default nil (omit when nil, i.e. non-bool flags)
	// For bool flags, only omit when nil (which doesn't happen since BoolFlag sets it)
	if f.Type == TypeBool {
		m["negatable"] = f.Negatable
	}

	// hidden: default false (always false in current impl, so always omitted)
	// If hidden were ever true, we'd emit it here.

	return m
}

// serializeArg converts an Arg to a JSON-serializable map.
// Fields matching their defaults are omitted; see buildSchemaDefaults().
func serializeArg(a Arg) map[string]interface{} {
	m := map[string]interface{}{
		"name": a.Name,
		"help": a.Help,
	}
	// required: default true (omit when true)
	if !a.Required {
		m["required"] = false
	}
	// variadic: default false (omit when false)
	if a.IsVariadic {
		m["variadic"] = true
	}
	return m
}

// serializeCommand converts a Command to a JSON-serializable map.
// Fields matching their defaults are omitted; see buildSchemaDefaults().
func serializeCommand(cmd *Command) map[string]interface{} {
	m := map[string]interface{}{
		"name": cmd.Name,
		"help": cmd.Help,
	}
	// passthrough: default false (omit when false)
	if cmd.Passthrough {
		m["passthrough"] = true
	}
	// flags: default [] (omit when empty)
	if len(cmd.Flags) > 0 {
		flags := make([]interface{}, 0, len(cmd.Flags))
		for _, f := range cmd.Flags {
			flags = append(flags, serializeFlag(f))
		}
		m["flags"] = flags
	}
	// args: default [] (omit when empty)
	if len(cmd.Args) > 0 {
		args := make([]interface{}, 0, len(cmd.Args))
		for _, a := range cmd.Args {
			args = append(args, serializeArg(a))
		}
		m["args"] = args
	}
	return m
}

// serializeGroup converts a Group to a JSON-serializable map (recursive).
// Fields matching their defaults are omitted; see buildSchemaDefaults().
func serializeGroup(grp *Group) map[string]interface{} {
	m := map[string]interface{}{
		"name": grp.Name,
		"help": grp.Help,
	}
	// commands: default {} (omit when empty)
	if len(grp.Commands) > 0 {
		commands := make(map[string]interface{})
		for name, cmd := range grp.Commands {
			commands[name] = serializeCommand(cmd)
		}
		m["commands"] = commands
	}
	// groups: default {} (omit when empty)
	if len(grp.Groups) > 0 {
		groups := make(map[string]interface{})
		for name, sub := range grp.Groups {
			groups[name] = serializeGroup(sub)
		}
		m["groups"] = groups
	}
	// deprecated: default {} (omit when empty)
	if len(grp.deprecatedMap) > 0 {
		deprecated := make(map[string]interface{})
		for name, msg := range grp.deprecatedMap {
			deprecated[name] = msg
		}
		m["deprecated"] = deprecated
	}
	return m
}

// buildSchemaDefaults returns the canonical defaults object for the schema.
// Consumers use this to reconstruct omitted fields.
func buildSchemaDefaults() map[string]interface{} {
	return map[string]interface{}{
		"app": map[string]interface{}{
			"env_prefix":   nil,
			"config":       false,
			"global_flags": []interface{}{},
			"commands":     map[string]interface{}{},
			"groups":       map[string]interface{}{},
			"deprecated":   map[string]interface{}{},
		},
		"flag": map[string]interface{}{
			"short":      nil,
			"default":    nil,
			"env":        nil,
			"choices":    nil,
			"repeatable": false,
			"negatable":  nil,
			"hidden":     false,
		},
		"arg": map[string]interface{}{
			"required": true,
			"variadic": false,
		},
		"command": map[string]interface{}{
			"passthrough": false,
			"flags":       []interface{}{},
			"args":        []interface{}{},
		},
		"group": map[string]interface{}{
			"commands":   map[string]interface{}{},
			"groups":     map[string]interface{}{},
			"deprecated": map[string]interface{}{},
		},
	}
}

// readProjectID reads the module path from go.mod in the current working directory.
func readProjectID() (string, error) {
	f, err := os.Open("go.mod")
	if err != nil {
		return "", fmt.Errorf("Cannot determine project_id: go.mod not found")
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if strings.HasPrefix(line, "module ") {
			return strings.TrimSpace(strings.TrimPrefix(line, "module ")), nil
		}
	}
	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("Cannot determine project_id: error reading go.mod: %w", err)
	}
	return "", fmt.Errorf("Cannot determine project_id: no module directive in go.mod")
}

// dumpSchema produces a JSON-serializable map representing the app's command tree.
// Fields matching their defaults are omitted; see buildSchemaDefaults().
func dumpSchema(app *App) (map[string]interface{}, error) {
	projectID, err := readProjectID()
	if err != nil {
		return nil, err
	}
	schema := map[string]interface{}{
		"project_id": projectID,
		"name":       app.Name,
		"version":    app.Version,
		"help":       app.Help,
		"defaults":   buildSchemaDefaults(),
	}

	// env_prefix: default nil (omit when empty -> nil)
	if app.EnvPrefix != "" {
		schema["env_prefix"] = app.EnvPrefix
	}

	// config: default false (omit when false)
	if app.configEnabled {
		schema["config"] = true
	}

	// global_flags: default [] (omit when empty)
	if len(app.globalFlags) > 0 {
		globalFlags := make([]interface{}, 0, len(app.globalFlags))
		for _, f := range app.globalFlags {
			globalFlags = append(globalFlags, serializeFlag(f))
		}
		schema["global_flags"] = globalFlags
	}

	// commands: default {} (omit when empty)
	if len(app.commands) > 0 {
		commands := make(map[string]interface{})
		for name, cmd := range app.commands {
			commands[name] = serializeCommand(cmd)
		}
		schema["commands"] = commands
	}

	// groups: default {} (omit when empty)
	if len(app.groups) > 0 {
		groups := make(map[string]interface{})
		for name, grp := range app.groups {
			groups[name] = serializeGroup(grp)
		}
		schema["groups"] = groups
	}

	// deprecated: default {} (omit when empty)
	if len(app.deprecatedMap) > 0 {
		deprecated := make(map[string]interface{})
		for name, msg := range app.deprecatedMap {
			deprecated[name] = msg
		}
		schema["deprecated"] = deprecated
	}

	// checks: only present when checks are enabled (not a default-omission case)
	if app.checksEnabled {
		checksMap := make(map[string]interface{})
		for name, def := range app.checkDefs {
			checksMap[name] = map[string]interface{}{
				"tags":          def.tags,
				"severity":      def.severity,
				"fast":          def.fast,
				"pure":          def.pure,
				"needs_network": def.needsNetwork,
				"depends_on":    def.dependsOn,
			}
		}
		schema["checks"] = checksMap
	}
	return schema, nil
}

// writeSchema writes the schema to .strictcli/schema.json and returns the path.
func writeSchema(app *App) (string, error) {
	schema, err := dumpSchema(app)
	if err != nil {
		return "", err
	}
	data, err := json.MarshalIndent(schema, "", "  ")
	if err != nil {
		return "", err
	}
	dirPath := filepath.Join(".", ".strictcli")
	if err := os.MkdirAll(dirPath, 0o755); err != nil {
		return "", err
	}
	filePath := filepath.Join(dirPath, "schema.json")
	if err := os.WriteFile(filePath, append(data, '\n'), 0o644); err != nil {
		return "", err
	}
	// Return absolute path for output
	absPath, err := filepath.Abs(filePath)
	if err != nil {
		return filePath, nil
	}
	return absPath, nil
}
