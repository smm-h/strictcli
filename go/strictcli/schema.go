package strictcli

import (
	"encoding/json"
	"os"
	"path/filepath"
)

// flagTypeName maps FlagType to its string representation for schema output.
var flagTypeName = map[FlagType]string{
	TypeStr:   "str",
	TypeBool:  "bool",
	TypeInt:   "int",
	TypeFloat: "float",
}

// serializeFlag converts a Flag to a JSON-serializable map matching the Python format.
func serializeFlag(f Flag) map[string]interface{} {
	m := map[string]interface{}{
		"name":       f.Name,
		"type":       flagTypeName[f.Type],
		"help":       f.Help,
		"short":      nilIfEmpty(f.Short),
		"default":    f.Default,
		"env":        nilIfEmpty(f.Env),
		"choices":    nil,
		"repeatable": f.Repeatable,
		"negatable":  nil,
		"hidden":     false,
	}
	if f.Choices != nil {
		m["choices"] = f.Choices
	}
	if f.Type == TypeBool {
		m["negatable"] = f.Negatable
	}
	// Repeatable flags with no explicit default serialize as empty list
	if f.Repeatable && f.Default == nil && !f.hasDefault {
		m["default"] = []interface{}{}
	}
	return m
}

// nilIfEmpty returns nil if s is empty, otherwise s.
func nilIfEmpty(s string) interface{} {
	if s == "" {
		return nil
	}
	return s
}

// serializeArg converts an Arg to a JSON-serializable map.
func serializeArg(a Arg) map[string]interface{} {
	return map[string]interface{}{
		"name":     a.Name,
		"help":     a.Help,
		"required": a.Required,
		"variadic": a.IsVariadic,
	}
}

// serializeCommand converts a Command to a JSON-serializable map.
func serializeCommand(cmd *Command) map[string]interface{} {
	flags := make([]interface{}, 0, len(cmd.Flags))
	for _, f := range cmd.Flags {
		flags = append(flags, serializeFlag(f))
	}
	args := make([]interface{}, 0, len(cmd.Args))
	for _, a := range cmd.Args {
		args = append(args, serializeArg(a))
	}
	return map[string]interface{}{
		"name":        cmd.Name,
		"help":        cmd.Help,
		"flags":       flags,
		"args":        args,
		"passthrough": cmd.Passthrough,
	}
}

// serializeGroup converts a Group to a JSON-serializable map (recursive).
func serializeGroup(grp *Group) map[string]interface{} {
	commands := make(map[string]interface{})
	for name, cmd := range grp.Commands {
		commands[name] = serializeCommand(cmd)
	}
	groups := make(map[string]interface{})
	for name, sub := range grp.Groups {
		groups[name] = serializeGroup(sub)
	}
	deprecated := make(map[string]interface{})
	for name, msg := range grp.deprecatedMap {
		deprecated[name] = msg
	}
	return map[string]interface{}{
		"name":       grp.Name,
		"help":       grp.Help,
		"commands":   commands,
		"groups":     groups,
		"deprecated": deprecated,
	}
}

// dumpSchema produces a JSON-serializable map representing the app's command tree.
func dumpSchema(app *App) map[string]interface{} {
	globalFlags := make([]interface{}, 0, len(app.globalFlags))
	for _, f := range app.globalFlags {
		globalFlags = append(globalFlags, serializeFlag(f))
	}

	commands := make(map[string]interface{})
	for name, cmd := range app.commands {
		commands[name] = serializeCommand(cmd)
	}

	groups := make(map[string]interface{})
	for name, grp := range app.groups {
		groups[name] = serializeGroup(grp)
	}

	deprecated := make(map[string]interface{})
	for name, msg := range app.deprecatedMap {
		deprecated[name] = msg
	}

	var envPrefix interface{}
	if app.EnvPrefix == "" {
		envPrefix = nil
	} else {
		envPrefix = app.EnvPrefix
	}

	return map[string]interface{}{
		"name":         app.Name,
		"version":      app.Version,
		"help":         app.Help,
		"env_prefix":   envPrefix,
		"config":       app.configEnabled,
		"global_flags": globalFlags,
		"commands":     commands,
		"groups":       groups,
		"deprecated":   deprecated,
	}
}

// writeSchema writes the schema to .strictcli/schema.json and returns the path.
func writeSchema(app *App) (string, error) {
	schema := dumpSchema(app)
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
