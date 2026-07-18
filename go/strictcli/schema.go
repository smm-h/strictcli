package strictcli

import (
	"bufio"
	"encoding/json"
	"os"
	"sort"
	"path/filepath"
	"strings"
)

// flagTypeName maps FlagType to its string representation for schema output.
var flagTypeName = map[FlagType]string{
	TypeStr:       "str",
	TypeBool:      "bool",
	TypeInt:       "int",
	TypeFloat:     "float",
	TypeListStr:   "list[str]",
	TypeListInt:   "list[int]",
	TypeListFloat: "list[float]",
	TypeDictStr:   "dict[str]",
	TypeDictInt:   "dict[int]",
	TypeDictFloat: "dict[float]",
}

// serializeDefault converts a default value to a JSON-serializable form. A
// RelativeToRoot marker (InfraRootPath) has unexported fields that would marshal
// to an empty object; instead it is serialized machine-stably as
// {"relative_to_root": {"env_var": ..., "parts": [...]}} -- only the declared env
// var and path parts, never a resolved machine-specific path. This shape is
// identical to the Python implementation so the schema cross-language byte-compares.
// All other values pass through unchanged.
func serializeDefault(v interface{}) interface{} {
	m, ok := v.(InfraRootPath)
	if !ok {
		return v
	}
	parts := make([]interface{}, len(m.parts))
	for i, p := range m.parts {
		parts[i] = p
	}
	return map[string]interface{}{
		"relative_to_root": map[string]interface{}{
			"env_var": m.envVar,
			"parts":   parts,
		},
	}
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
		m["default"] = serializeDefault(dflt)
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

	// conflict_mode: serialized only when explicitly set (omitted when
	// inheriting the app default). Additive; schema_version stays 1, so
	// consumers must treat absence as "inherit the app config_conflict_mode".
	if f.hasConflictMode {
		m["conflict_mode"] = f.ConflictMode
	}

	// env_separator: default "" (omit when empty)
	if f.EnvSeparator != "" {
		m["env_separator"] = f.EnvSeparator
	}

	// negatable: default nil (omit when nil, i.e. non-bool flags)
	// For bool flags, always emit negatable
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
	// type: default "str" (omit when str)
	if a.Type != TypeStr {
		m["type"] = flagTypeName[a.Type]
	}
	// required: default true (omit when true)
	if !a.Required {
		m["required"] = false
	}
	// variadic: default false (omit when false)
	if a.IsVariadic {
		m["variadic"] = true
	}
	// default: default nil (omit when nil / no default set)
	if a.hasDefault {
		m["default"] = a.Default
	}
	// choices: default nil (omit when nil)
	if a.Choices != nil {
		m["choices"] = a.Choices
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
	if len(cmd.flags) > 0 {
		flags := make([]interface{}, 0, len(cmd.flags))
		for _, f := range cmd.flags {
			flags = append(flags, serializeFlag(f))
		}
		m["flags"] = flags
	}
	// args: default [] (omit when empty)
	if len(cmd.args) > 0 {
		args := make([]interface{}, 0, len(cmd.args))
		for _, a := range cmd.args {
			args = append(args, serializeArg(a))
		}
		m["args"] = args
	}
	// tags: default [] (omit when empty)
	if len(cmd.tags) > 0 {
		sorted := make([]string, len(cmd.tags))
		copy(sorted, cmd.tags)
		sort.Strings(sorted)
		tags := make([]interface{}, len(sorted))
		for i, t := range sorted {
			tags[i] = t
		}
		m["tags"] = tags
	}
	// constraints: default [] (omit when empty)
	constraints := serializeConstraints(cmd)
	if len(constraints) > 0 {
		m["constraints"] = constraints
	}
	// hidden: default false (omit when false)
	if cmd.Hidden {
		m["hidden"] = true
	}
	// interactive: default false (omit when false)
	if cmd.Interactive {
		m["interactive"] = true
	}
	// config_fields: default [] (omit when empty)
	if len(cmd.configFields) > 0 {
		cfList := make([]interface{}, len(cmd.configFields))
		for i, f := range cmd.configFields {
			cfList[i] = f
		}
		m["config_fields"] = cfList
	}
	return m
}

// serializeConstraints builds the constraints array from a command's mutex groups and dependencies.
func serializeConstraints(cmd *Command) []interface{} {
	var constraints []interface{}
	// Mutex groups
	for _, mg := range cmd.mutex {
		flags := make([]interface{}, len(mg.Flags))
		for i, f := range mg.Flags {
			flags[i] = f.Name
		}
		constraints = append(constraints, map[string]interface{}{
			"type":  "mutex",
			"flags": flags,
		})
	}
	// Dependencies
	for _, dep := range cmd.dependencies {
		switch d := dep.(type) {
		case CoRequired:
			flags := make([]interface{}, len(d.Flags))
			for i, name := range d.Flags {
				flags[i] = name
			}
			constraints = append(constraints, map[string]interface{}{
				"type":  "co_required",
				"flags": flags,
			})
		case Requires:
			constraints = append(constraints, map[string]interface{}{
				"type":       "requires",
				"flag":       d.Flag,
				"depends_on": d.DependsOn,
			})
		case Implies:
			constraints = append(constraints, map[string]interface{}{
				"type":    "implies",
				"flag":    d.Flag,
				"implies": d.Implies,
				"value":   d.Value,
			})
		}
	}
	return constraints
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
	// tags: default [] (omit when empty) — own tags only, not accumulated
	if len(grp.tags) > 0 {
		sorted := make([]string, len(grp.tags))
		copy(sorted, grp.tags)
		sort.Strings(sorted)
		tags := make([]interface{}, len(sorted))
		for i, t := range sorted {
			tags[i] = t
		}
		m["tags"] = tags
	}
	// hidden: default false (omit when false)
	if grp.Hidden {
		m["hidden"] = true
	}
	return m
}

// buildSchemaDefaults returns the canonical defaults object for the schema.
// Consumers use this to reconstruct omitted fields.
func buildSchemaDefaults() map[string]interface{} {
	return map[string]interface{}{
		"schema_version": 1,
		"app": map[string]interface{}{
			"env_prefix":     nil,
			"config":         false,
			"global_flags":   []interface{}{},
			"commands":       map[string]interface{}{},
			"groups":         map[string]interface{}{},
			"deprecated":     map[string]interface{}{},
			"tag_contracts":  map[string]interface{}{},
		},
		"flag": map[string]interface{}{
			"short":         nil,
			"default":       nil,
			"env":           nil,
			"choices":       nil,
			"repeatable":    false,
			"unique":        false,
			"env_separator": nil,
			"negatable":     nil,
			"hidden":        false,
		},
		"arg": map[string]interface{}{
			"type":     "str",
			"required": true,
			"default":  nil,
			"variadic": false,
			"choices":  nil,
		},
		"command": map[string]interface{}{
			"passthrough": false,
			"flags":       []interface{}{},
			"args":        []interface{}{},
			"tags":        []interface{}{},
			"constraints": []interface{}{},
			"hidden":      false,
			"interactive": false,
		},
		"group": map[string]interface{}{
			"commands":   map[string]interface{}{},
			"groups":     map[string]interface{}{},
			"deprecated": map[string]interface{}{},
			"tags":       []interface{}{},
			"hidden":     false,
		},
	}
}

// readProjectID reads the module path from go.mod in the current working directory.
func readProjectID() (string, error) {
	f, err := os.Open("go.mod")
	if err != nil {
		return "", errCannotDetermineProjectIDNoGoMod()
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
		return "", errCannotDetermineProjectIDReadError(err)
	}
	return "", errCannotDetermineProjectIDNoModule()
}

// dumpSchemaCore builds the full schema map, excluding project_id.
//
// This is the CWD-free, filesystem-free core of schema production. It reads
// only the in-memory App (name, version, help, flags, commands, groups, etc.).
// project_id is the only field that requires reading go.mod from the CWD, so it
// is added later by the file-writer path (dumpSchema). This function cannot
// fail. Fields matching their defaults are omitted; see buildSchemaDefaults().
func dumpSchemaCore(app *App) map[string]interface{} {
	schema := map[string]interface{}{
		"schema_version": 1,
		"name":           app.Name,
		"version":        app.Version,
		"help":           app.Help,
		"defaults":       buildSchemaDefaults(),
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

	// tag_contracts: default {} (omit when empty)
	if len(app.tagContracts) > 0 {
		tagContracts := make(map[string]interface{})
		for tag, flag := range app.tagContracts {
			tagContracts[tag] = flag
		}
		schema["tag_contracts"] = tagContracts
	}

	// config_fields: only present when config fields are declared
	if len(app.configFields) > 0 {
		cfSchema := make(map[string]interface{})
		for _, name := range app.configFieldOrder {
			cf := app.configFields[name]
			entry := map[string]interface{}{
				"type":     flagTypeName[cf.Type],
				"help":     cf.Help,
				"required": cf.Required,
			}
			if cf.HasDefault {
				entry["default"] = cf.Default
			}
			// Find which commands bind this field
			var boundCommands []string
			for _, cmdName := range app.cmdOrder {
				cmd := app.commands[cmdName]
				for _, f := range cmd.configFields {
					if f == name {
						boundCommands = append(boundCommands, cmdName)
						break
					}
				}
			}
			// Search groups recursively
			var searchGroup func(g *Group, prefix string)
			searchGroup = func(g *Group, prefix string) {
				for _, cmdName := range g.order {
					cmd := g.Commands[cmdName]
					for _, f := range cmd.configFields {
						if f == name {
							boundCommands = append(boundCommands, prefix+cmdName)
							break
						}
					}
				}
				for _, grpName := range g.groupOrder {
					searchGroup(g.Groups[grpName], prefix+grpName+" ")
				}
			}
			for _, grpName := range app.groupOrder {
				searchGroup(app.groups[grpName], grpName+" ")
			}
			if len(boundCommands) > 0 {
				cmds := make([]interface{}, len(boundCommands))
				for i, c := range boundCommands {
					cmds[i] = c
				}
				entry["bound_commands"] = cmds
			}
			cfSchema[name] = entry
		}
		schema["config_fields"] = cfSchema
	}

	// checks: only present when checks are enabled (not a default-omission case).
	// Only TOML-declared checks appear here. Provider-sourced checks
	// (RegisterCheckProvider) are deliberately EXCLUDED: providers materialize
	// lazily per-cwd at check-run time, so they are not part of the static,
	// committed schema. The schema describes the declared surface, not the
	// dynamically-materialized one.
	if app.checksEnabled {
		checksMap := make(map[string]interface{})
		for name, def := range app.checkDefs {
			entry := map[string]interface{}{
				"tags":          def.tags,
				"severity":      def.severity,
				"fast":          def.fast,
				"pure":          def.pure,
				"needs_network": def.needsNetwork,
				"depends_on":    def.dependsOn,
			}
			if def.scope != "" {
				entry["scope"] = def.scope
			}
			checksMap[name] = entry
		}
		schema["checks"] = checksMap
	}

	// infra: only present when infrastructure roots or handshake vars are
	// declared. Resolved root values are intentionally EXCLUDED -- the schema
	// must be machine-stable (not machine-specific). Only the declared env var
	// and default path (both stable declarations) are emitted for roots.
	if len(app.infraRootOrder) > 0 || len(app.handshakeOrder) > 0 {
		infra := make(map[string]interface{})
		if len(app.infraRootOrder) > 0 {
			roots := make([]interface{}, 0, len(app.infraRootOrder))
			for _, ev := range app.infraRootOrder {
				var def string
				for _, d := range app.infraRootDecls {
					if d.envVar == ev {
						def = d.defaultPath
						break
					}
				}
				roots = append(roots, map[string]interface{}{
					"env_var": ev,
					"default": def,
				})
			}
			infra["roots"] = roots
		}
		if len(app.handshakeOrder) > 0 {
			handshakes := make([]interface{}, 0, len(app.handshakeOrder))
			for _, ev := range app.handshakeOrder {
				handshakes = append(handshakes, map[string]interface{}{
					"env_var": ev,
					"help":    app.handshakeEnvs[ev],
				})
			}
			infra["handshakes"] = handshakes
		}
		schema["infra"] = infra
	}
	return schema
}

// dumpSchema produces the full schema map including project_id (reads the CWD).
// It delegates to dumpSchemaCore and adds project_id (read from go.mod).
func dumpSchema(app *App) (map[string]interface{}, error) {
	projectID, err := readProjectID()
	if err != nil {
		return nil, err
	}
	schema := dumpSchemaCore(app)
	schema["project_id"] = projectID
	return schema, nil
}

// DumpSchemaDict returns the app's full schema as a map, excluding project_id.
//
// This is the public, CWD-free accessor for the schema. Unlike the
// --dump-schema flag (which writes .strictcli/schema.json and derives
// project_id from go.mod in the current working directory), this method reads
// only the in-memory App and performs no filesystem or CWD access, and cannot
// fail. The returned map is equivalent to the written schema file with the
// project_id field removed.
func (a *App) DumpSchemaDict() map[string]interface{} {
	return dumpSchemaCore(a)
}

// checkSchemaProjectID verifies that an existing schema file belongs to the
// same project. Returns an error on mismatch. Silently passes on: missing
// file, unreadable file, JSON without project_id field, or matching project_id.
func checkSchemaProjectID(filePath string, newProjectID string) error {
	raw, err := os.ReadFile(filePath)
	if err != nil {
		return nil
	}
	var existing map[string]interface{}
	if err := json.Unmarshal(raw, &existing); err != nil {
		return nil
	}
	existingID, ok := existing["project_id"]
	if !ok {
		return nil
	}
	existingIDStr, ok := existingID.(string)
	if !ok {
		return nil
	}
	if existingIDStr != newProjectID {
		return errSchemaMismatch(existingIDStr, newProjectID)
	}
	return nil
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
	newProjectID, _ := schema["project_id"].(string)
	if err := checkSchemaProjectID(filePath, newProjectID); err != nil {
		return "", err
	}
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
