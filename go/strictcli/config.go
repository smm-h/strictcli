package strictcli

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"

	tomledit "github.com/smm-h/go-toml-edit"
)

// nestedGet looks up a dot-separated key in a nested map.
// Returns (value, true) if found, (nil, false) if any intermediate
// segment is missing or not a map.
func nestedGet(data map[string]interface{}, dotPath string) (interface{}, bool) {
	parts := strings.Split(dotPath, ".")
	var current interface{} = data
	for _, part := range parts[:len(parts)-1] {
		m, ok := current.(map[string]interface{})
		if !ok {
			return nil, false
		}
		current, ok = m[part]
		if !ok {
			return nil, false
		}
	}
	m, ok := current.(map[string]interface{})
	if !ok {
		return nil, false
	}
	val, ok := m[parts[len(parts)-1]]
	return val, ok
}

// nestedSet sets a dot-separated key in a nested map, creating
// intermediate maps as needed.
func nestedSet(data map[string]interface{}, dotPath string, value interface{}) {
	parts := strings.Split(dotPath, ".")
	current := data
	for _, part := range parts[:len(parts)-1] {
		if sub, ok := current[part]; ok {
			if subMap, ok := sub.(map[string]interface{}); ok {
				current = subMap
			} else {
				subMap := make(map[string]interface{})
				current[part] = subMap
				current = subMap
			}
		} else {
			subMap := make(map[string]interface{})
			current[part] = subMap
			current = subMap
		}
	}
	current[parts[len(parts)-1]] = value
}

// nestedDelete deletes a dot-separated key from a nested map.
// Returns true if the key was found and deleted, false otherwise.
// Cleans up empty intermediate maps.
func nestedDelete(data map[string]interface{}, dotPath string) bool {
	parts := strings.Split(dotPath, ".")
	type parentEntry struct {
		m   map[string]interface{}
		key string
	}
	var parents []parentEntry
	current := data
	for _, part := range parts[:len(parts)-1] {
		sub, ok := current[part]
		if !ok {
			return false
		}
		subMap, ok := sub.(map[string]interface{})
		if !ok {
			return false
		}
		parents = append(parents, parentEntry{m: current, key: part})
		current = subMap
	}
	lastKey := parts[len(parts)-1]
	if _, ok := current[lastKey]; !ok {
		return false
	}
	delete(current, lastKey)
	// Clean up empty intermediate maps
	for i := len(parents) - 1; i >= 0; i-- {
		p := parents[i]
		child := p.m[p.key].(map[string]interface{})
		if len(child) == 0 {
			delete(p.m, p.key)
		}
	}
	return true
}

// collectNestedKeys flattens a nested map to dot-separated leaf key paths.
// Non-map values are leaves; map values are recursed into.
func collectNestedKeys(data map[string]interface{}, prefix string) []string {
	var keys []string
	for k, v := range data {
		fullKey := k
		if prefix != "" {
			fullKey = prefix + "." + k
		}
		if subMap, ok := v.(map[string]interface{}); ok {
			keys = append(keys, collectNestedKeys(subMap, fullKey)...)
		} else {
			keys = append(keys, fullKey)
		}
	}
	return keys
}

// ConfigField describes a declared config file field.
type ConfigField struct {
	Name       string
	Type       FlagType
	Help       string
	Default    interface{}
	HasDefault bool
	Required   bool // computed: !HasDefault
}

// ConfigFieldOption configures a ConfigField.
type ConfigFieldOption func(*ConfigField)

// ConfigFieldType sets the type for a config field (default: TypeStr).
func ConfigFieldType(t FlagType) ConfigFieldOption {
	return func(cf *ConfigField) {
		cf.Type = t
	}
}

// ConfigFieldHelp sets the help text for a config field (required).
func ConfigFieldHelp(help string) ConfigFieldOption {
	return func(cf *ConfigField) {
		cf.Help = help
	}
}

// ConfigFieldDefault sets the default value for a config field.
func ConfigFieldDefault(v interface{}) ConfigFieldOption {
	return func(cf *ConfigField) {
		cf.Default = v
		cf.HasDefault = true
	}
}

// configFieldNameRe validates config field names: optional underscore prefix
// (reserved for framework), then a letter followed by lowercase letters,
// digits, and underscores. Dots separate segments, each starting with a letter.
// Matches Python's _CONFIG_FIELD_NAME_RE.
var configFieldNameRe = regexp.MustCompile(`^_?[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`)

// ConfigField declares a config field on the app.
// Panics on invalid configuration (programmer error).
func (a *App) ConfigField(name string, opts ...ConfigFieldOption) {
	cf := &ConfigField{
		Name: name,
		Type: TypeStr, // default type
	}
	for _, opt := range opts {
		opt(cf)
	}
	cf.Required = !cf.HasDefault

	// Validate name format
	if !configFieldNameRe.MatchString(name) {
		panic(fmt.Sprintf("ConfigField name %q is invalid: must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)", name))
	}

	// Names starting with _ are reserved for framework fields
	if strings.HasPrefix(name, "_") {
		panic(fmt.Sprintf("config field name %q is reserved: names starting with underscore are reserved for framework fields", name))
	}

	// Validate help is non-empty
	if strings.TrimSpace(cf.Help) == "" {
		panic(fmt.Sprintf("config field %q: help text is required", name))
	}

	// Validate type
	switch cf.Type {
	case TypeStr, TypeBool, TypeInt, TypeFloat:
		// ok
	default:
		panic(fmt.Sprintf("ConfigField.type must be str, bool, int, or float, got %d", cf.Type))
	}

	// Validate default matches type
	if cf.HasDefault && cf.Default != nil {
		validateConfigFieldDefault(name, cf.Type, cf.Default)
	}

	// Check for duplicate names (user fields and framework fields)
	if a.configFields == nil {
		a.configFields = make(map[string]*ConfigField)
	}
	if _, ok := a.configFields[name]; ok {
		panic(fmt.Sprintf("duplicate config field name %q", name))
	}
	if a.frameworkFields != nil {
		if _, ok := a.frameworkFields[name]; ok {
			panic(fmt.Sprintf("config field name %q conflicts with framework field", name))
		}
	}

	a.configFields[name] = cf
	a.configFieldOrder = append(a.configFieldOrder, name)
}

// registerFrameworkField declares an internal framework config field.
// Framework fields use underscore-prefixed names and are not exposed to users.
func (a *App) registerFrameworkField(name string, fieldType FlagType, help string) {
	if !strings.HasPrefix(name, "_") {
		panic(fmt.Sprintf("framework field name %q must start with underscore", name))
	}

	if !configFieldNameRe.MatchString(name) {
		panic(fmt.Sprintf("framework field %q: invalid name, must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)", name))
	}

	if strings.TrimSpace(help) == "" {
		panic(fmt.Sprintf("framework field %q: help text is required", name))
	}

	switch fieldType {
	case TypeStr, TypeBool, TypeInt, TypeFloat:
		// ok
	default:
		panic(fmt.Sprintf("ConfigField.type must be str, bool, int, or float, got %d", fieldType))
	}

	if a.frameworkFields == nil {
		a.frameworkFields = make(map[string]*ConfigField)
	}
	if _, ok := a.frameworkFields[name]; ok {
		panic(fmt.Sprintf("duplicate framework field name %q", name))
	}
	if a.configFields != nil {
		if _, ok := a.configFields[name]; ok {
			panic(fmt.Sprintf("framework field name %q conflicts with user config field", name))
		}
	}

	cf := &ConfigField{
		Name:     name,
		Type:     fieldType,
		Help:     help,
		Required: true, // framework fields have no default
	}

	a.frameworkFields[name] = cf
	a.frameworkFieldOrder = append(a.frameworkFieldOrder, name)
}

// validateConfigFieldDefault panics if the default value doesn't match the declared type.
func validateConfigFieldDefault(name string, fieldType FlagType, value interface{}) {
	switch fieldType {
	case TypeStr:
		if _, ok := value.(string); !ok {
			panic(fmt.Sprintf("ConfigField %q: default value %v does not match type %s", name, value, "str"))
		}
	case TypeBool:
		if _, ok := value.(bool); !ok {
			panic(fmt.Sprintf("ConfigField %q: default value %v does not match type %s", name, value, "bool"))
		}
	case TypeInt:
		if _, ok := value.(int); !ok {
			panic(fmt.Sprintf("ConfigField %q: default value %v does not match type %s", name, value, "int"))
		}
	case TypeFloat:
		if _, ok := value.(float64); !ok {
			panic(fmt.Sprintf("ConfigField %q: default value %v does not match type %s", name, value, "float"))
		}
	}
}

// describeGoType returns a human-readable type name for a Go value,
// using strictcli type names (str, bool, int, float).
func describeGoType(v interface{}) string {
	switch v.(type) {
	case string:
		return "str"
	case bool:
		return "bool"
	case int:
		return "int"
	case float64:
		return "float"
	default:
		return fmt.Sprintf("%T", v)
	}
}

// configPath returns the full path to the config file for an app.
// If override is non-empty, it is returned as-is.
// format should be "json" or "toml" and determines the file extension.
func configPath(appName string, override string, format string) string {
	if override != "" {
		return override
	}
	configHome := os.Getenv("XDG_CONFIG_HOME")
	if configHome == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			home = os.Getenv("HOME")
		}
		configHome = filepath.Join(home, ".config")
	}
	ext := "json"
	if format == "toml" {
		ext = "toml"
	}
	return filepath.Join(configHome, appName, "config."+ext)
}

// loadConfig reads the config file for an app.
// Returns an empty map if the file doesn't exist or contains invalid data.
// Invalid content prints a warning to stderr.
func loadConfig(appName string, pathOverride string, format string) map[string]interface{} {
	path := configPath(appName, pathOverride, format)
	data, err := os.ReadFile(path)
	if err != nil {
		// File doesn't exist or can't be read -- silent
		return map[string]interface{}{}
	}
	var result map[string]interface{}
	switch format {
	case "toml":
		if err := tomledit.Unmarshal(data, &result); err != nil {
			fmt.Fprintf(os.Stderr, "warning: invalid TOML in config file '%s', ignoring\n", path)
			return map[string]interface{}{}
		}
	default:
		if err := json.Unmarshal(data, &result); err != nil {
			fmt.Fprintf(os.Stderr, "warning: invalid JSON in config file '%s', ignoring\n", path)
			return map[string]interface{}{}
		}
	}
	return result
}

// resolveConfigData loads config data for the app. This is the single
// entry point for all config loading. The runtimePathOverride and hermetic
// parameters are plumbed for future use (Phase 1) but currently inert.
func (a *App) resolveConfigData(runtimePathOverride string, hermetic bool) map[string]interface{} {
	if hermetic {
		return map[string]interface{}{}
	}
	override := a.configPathOverride
	if runtimePathOverride != "" {
		override = runtimePathOverride
	}
	return loadConfig(a.Name, override, a.configFormat)
}

// coerceConfigScalar coerces a single JSON-decoded value to the given flag type.
// Returns the coerced value and an error string (empty on success).
// When shortNames is true (config field validation path), uses short type names
// ("bool", "int", "str", "float") to match Python's _check_config_field_type.
// When shortNames is false (flag coercion path), uses long type names
// ("boolean", "integer", "string", "float") to match Python's _coerce_config_scalar.
func coerceConfigScalar(value interface{}, flagType FlagType, shortNames bool) (interface{}, string) {
	if shortNames {
		return coerceConfigScalarShort(value, flagType)
	}
	return coerceConfigScalarLong(value, flagType)
}

// coerceConfigScalarLong uses long type names for the flag coercion path.
func coerceConfigScalarLong(value interface{}, flagType FlagType) (interface{}, string) {
	switch flagType {
	case TypeBool:
		if b, ok := value.(bool); ok {
			return b, ""
		}
		return nil, fmt.Sprintf("expected boolean, got %s", typeName(value))
	case TypeInt:
		// TOML integers decode as int64; JSON numbers decode as float64
		if val, ok := value.(int64); ok {
			return int(val), ""
		}
		if fv, ok := value.(float64); ok {
			intVal := int(fv)
			if float64(intVal) == fv {
				return intVal, ""
			}
			return nil, "expected integer, got float"
		}
		return nil, fmt.Sprintf("expected integer, got %s", typeName(value))
	case TypeFloat:
		// TOML integers decode as int64; JSON numbers decode as float64
		if val, ok := value.(int64); ok {
			return float64(val), ""
		}
		if fv, ok := value.(float64); ok {
			return fv, ""
		}
		return nil, fmt.Sprintf("expected float, got %s", typeName(value))
	case TypeStr:
		if s, ok := value.(string); ok {
			return s, ""
		}
		return nil, fmt.Sprintf("expected string, got %s", typeName(value))
	}
	return nil, fmt.Sprintf("unsupported flag type %d", flagType)
}

// coerceConfigScalarShort uses short type names for the config field validation path.
func coerceConfigScalarShort(value interface{}, flagType FlagType) (interface{}, string) {
	switch flagType {
	case TypeBool:
		if b, ok := value.(bool); ok {
			return b, ""
		}
		return nil, fmt.Sprintf("expected bool, got %s", typeName(value))
	case TypeInt:
		// TOML integers decode as int64; JSON numbers decode as float64
		if val, ok := value.(int64); ok {
			return int(val), ""
		}
		if fv, ok := value.(float64); ok {
			intVal := int(fv)
			if float64(intVal) == fv {
				return intVal, ""
			}
			return nil, "expected int, got float"
		}
		return nil, fmt.Sprintf("expected int, got %s", typeName(value))
	case TypeFloat:
		// TOML integers decode as int64; JSON numbers decode as float64
		if val, ok := value.(int64); ok {
			return float64(val), ""
		}
		if fv, ok := value.(float64); ok {
			return fv, ""
		}
		return nil, fmt.Sprintf("expected float, got %s", typeName(value))
	case TypeStr:
		if s, ok := value.(string); ok {
			return s, ""
		}
		return nil, fmt.Sprintf("expected str, got %s", typeName(value))
	}
	return nil, fmt.Sprintf("unsupported flag type %d", flagType)
}

// coerceConfigValue coerces a JSON-decoded value to the flag's type.
// Handles scalar values, arrays (for repeatable/list flags), and objects (for dict flags).
// Returns the coerced value and an error string (empty on success).
func coerceConfigValue(value interface{}, f *Flag) (interface{}, string) {
	// Dict flags: expect a JSON object in config
	if IsDictType(f.Type) {
		m, ok := value.(map[string]interface{})
		if !ok {
			return nil, fmt.Sprintf("expected object for dict flag, got %s", typeName(value))
		}
		valType := ItemType(f.Type)
		result := make(map[string]interface{}, len(m))
		for k, v := range m {
			coerced, errStr := coerceConfigScalar(v, valType, false)
			if errStr != "" {
				return nil, fmt.Sprintf("key %q: expected %s, got %s", k, flagTypeName[valType], typeName(v))
			}
			result[k] = coerced
		}
		return result, ""
	}
	// List flags: expect a JSON array in config
	if IsListType(f.Type) {
		arr, ok := value.([]interface{})
		if !ok {
			return nil, fmt.Sprintf("expected array for list flag, got %s", typeName(value))
		}
		elemType := ItemType(f.Type)
		result := make([]interface{}, len(arr))
		for i, elem := range arr {
			coerced, errStr := coerceConfigScalar(elem, elemType, false)
			if errStr != "" {
				return nil, fmt.Sprintf("element %d: expected %s, got %s", i, flagTypeName[elemType], typeName(elem))
			}
			result[i] = coerced
		}
		return result, ""
	}
	if arr, ok := value.([]interface{}); ok {
		if !f.Repeatable {
			return nil, "expected scalar, got array"
		}
		result := make([]interface{}, len(arr))
		for i, elem := range arr {
			coerced, errStr := coerceConfigScalar(elem, f.Type, false)
			if errStr != "" {
				return nil, fmt.Sprintf("element %d: expected %s, got %s", i, flagTypeName[f.Type], typeName(elem))
			}
			result[i] = coerced
		}
		return result, ""
	}
	if f.Repeatable {
		return nil, fmt.Sprintf("expected array for repeatable flag, got %s", typeName(value))
	}
	return coerceConfigScalar(value, f.Type, false)
}

// typeName returns a human-readable type name for a config-decoded value.
func typeName(v interface{}) string {
	switch v.(type) {
	case bool:
		return "bool"
	case int64:
		return "int"
	case float64:
		fv := v.(float64)
		if math.Floor(fv) == fv && !math.IsInf(fv, 0) && !math.IsNaN(fv) {
			return "int"
		}
		return "float"
	case string:
		return "str"
	case nil:
		return "null"
	case []interface{}:
		return "array"
	default:
		return fmt.Sprintf("%T", v)
	}
}

// collectAllFlags collects all flags (global + all commands in all groups) for config show.
func (a *App) collectAllFlags() []Flag {
	var flags []Flag
	seen := make(map[string]bool)
	for _, f := range a.globalFlags {
		flags = append(flags, f)
		seen[f.Name] = true
	}
	for _, name := range a.cmdOrder {
		cmd := a.commands[name]
		for _, f := range cmd.flags {
			if !seen[f.Name] {
				flags = append(flags, f)
				seen[f.Name] = true
			}
		}
	}
	var collectFromGroup func(grp *Group)
	collectFromGroup = func(grp *Group) {
		for _, name := range grp.order {
			cmd := grp.Commands[name]
			for _, f := range cmd.flags {
				if !seen[f.Name] {
					flags = append(flags, f)
					seen[f.Name] = true
				}
			}
		}
		for _, name := range grp.groupOrder {
			collectFromGroup(grp.Groups[name])
		}
	}
	for _, name := range a.groupOrder {
		if name == "config" {
			continue // skip auto-generated config group
		}
		collectFromGroup(a.groups[name])
	}
	return flags
}

// writeConfigFile marshals the config map and writes it to disk.
func writeConfigFile(data map[string]interface{}, path string, format string) int {
	var raw []byte
	var err error
	switch format {
	case "toml":
		raw, err = tomledit.Marshal(data)
	default:
		raw, err = json.MarshalIndent(data, "", "  ")
		if err == nil {
			raw = append(raw, '\n')
		}
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: cannot marshal config: %s\n", err)
		return 1
	}
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "error: cannot write config file: %s\n", err)
		return 1
	}
	return 0
}

// registerConfigGroup registers the auto-generated 'config' command group.
func (a *App) registerConfigGroup() {
	grp := a.Group("config", "Manage persistent configuration values stored in the config file")

	// config path
	grp.Command("path", "Print the absolute path to the config file for this application", func(args map[string]interface{}) int {
		fmt.Println(configPath(a.Name, a.configPathOverride, a.configFormat))
		return 0
	})

	// config show
	grp.Command("show", "Show all config values with their sources (config file, env, or default)", func(args map[string]interface{}) int {
		useJSON := args["json"].(bool)
		configData := a.resolveConfigData("", false)
		allFlags := a.collectAllFlags()

		if useJSON {
			result := make(map[string]interface{})
			for _, f := range allFlags {
				param := flagParamName(f.Name)
				var value interface{}
				var source string
				if v, ok := configData[param]; ok {
					value = v
					source = "config"
				} else if f.hasDefault && f.Default != nil {
					value = f.Default
					source = "default"
				} else {
					value = nil
					source = "default"
				}
				result[param] = map[string]interface{}{
					"value":  value,
					"source": source,
				}
			}
			// Include config fields
			for _, name := range a.configFieldOrder {
				cf := a.configFields[name]
				var value interface{}
				var source string
				if v, ok := nestedGet(configData, name); ok {
					value = v
					source = "config"
				} else if cf.HasDefault {
					value = cf.Default
					source = "default"
				} else {
					value = nil
					source = "not set"
				}
				cfEntry := map[string]interface{}{
					"value":    value,
					"source":   source,
					"type":     flagTypeName[cf.Type],
					"required": cf.Required,
					"help":     cf.Help,
				}
				if cf.HasDefault {
					cfEntry["default"] = cf.Default
				}
				result[name] = cfEntry
			}
			data, err := json.MarshalIndent(result, "", "  ")
			if err != nil {
				fmt.Fprintf(os.Stderr, "error: %s\n", err)
				return 1
			}
			fmt.Println(string(data))
			return 0
		}

		// --plain
		for _, f := range allFlags {
			param := flagParamName(f.Name)
			var value interface{}
			var source string
			if v, ok := configData[param]; ok {
				value = v
				source = "config"
			} else if f.hasDefault && f.Default != nil {
				value = f.Default
				source = "default"
			} else {
				value = nil
				source = "default"
			}
			fmt.Printf("%s = %v  (source: %s)\n", param, formatConfigValue(value), source)
		}
		// Include config fields
		if len(a.configFieldOrder) > 0 {
			fmt.Println()
			fmt.Println("Config fields:")
			for _, name := range a.configFieldOrder {
				cf := a.configFields[name]
				var value interface{}
				var source string
				if v, ok := nestedGet(configData, name); ok {
					value = v
					source = "config"
				} else if cf.HasDefault {
					value = cf.Default
					source = "default"
				} else {
					value = nil
					source = "not set"
				}
				reqStr := "required"
				if !cf.Required {
					reqStr = "optional"
				}
				fmt.Printf("  %s (%s, %s) = %v  (source: %s)  -- %s\n",
					name, flagTypeName[cf.Type], reqStr, formatConfigValue(value), source, cf.Help)
			}
		}
		return 0
	}, WithMutex(
		MutexGroup{Flags: []Flag{
			BoolFlag("plain", "Display config values in a human-readable table format", Default(false)),
			BoolFlag("json", "Display config values as a JSON object with source metadata", Default(false)),
		}},
	))

	// config set
	grp.Command("set", "Set a persistent config value that overrides the default for a flag", func(args map[string]interface{}) int {
		key := args["key"].(string)
		path := configPath(a.Name, a.configPathOverride, a.configFormat)
		dirPath := filepath.Dir(path)
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot create config directory: %s\n", err)
			return 1
		}
		// Read existing config
		existing := a.resolveConfigData("", false)

		// Look up the key against registered flags and config fields
		allFlags := a.collectAllFlags()
		var matchedFlag *Flag
		var matchedConfigField *ConfigField
		for i := range allFlags {
			if flagParamName(allFlags[i].Name) == key {
				matchedFlag = &allFlags[i]
				break
			}
		}
		if matchedFlag == nil && a.configFields != nil {
			matchedConfigField = a.configFields[key]
		}
		if matchedFlag == nil && matchedConfigField == nil {
			fmt.Fprintf(os.Stderr, "config set: unknown key '%s'\n", key)
			return 1
		}

		useClear := args["clear"].(bool)
		useDefault := args["default"].(bool)

		// Validate: exactly one of (value, --clear, --default)
		hasValue := args["value"] != nil
		var value string
		if hasValue {
			value = args["value"].(string)
		}
		if useClear && useDefault {
			fmt.Fprintln(os.Stderr, "config set: --clear and --default are mutually exclusive")
			return 1
		}
		if hasValue && useClear {
			fmt.Fprintln(os.Stderr, "config set: cannot provide a value with --clear")
			return 1
		}
		if hasValue && useDefault {
			fmt.Fprintln(os.Stderr, "config set: cannot provide a value with --default")
			return 1
		}
		if !hasValue && !useClear && !useDefault {
			fmt.Fprintln(os.Stderr, "config set: provide a value, --clear, or --default")
			return 1
		}

		// Config fields do not support --clear (not repeatable)
		if matchedConfigField != nil && useClear {
			fmt.Fprintln(os.Stderr, "config set: --clear is only for repeatable flags")
			return 1
		}

		// --clear: repeatable flags only, writes []
		if useClear {
			if !matchedFlag.Repeatable {
				fmt.Fprintln(os.Stderr, "config set: --clear is only for repeatable flags")
				return 1
			}
			existing[key] = []interface{}{}
			return writeConfigFile(existing, path, a.configFormat)
		}

		// --default: remove the key from config
		if useDefault {
			if _, ok := nestedGet(existing, key); !ok {
				fmt.Fprintf(os.Stderr, "config set: key '%s' not in config\n", key)
				return 1
			}
			nestedDelete(existing, key)
			return writeConfigFile(existing, path, a.configFormat)
		}

		// Config field: coerce to config field type
		if matchedConfigField != nil {
			var typedValue interface{}
			switch matchedConfigField.Type {
			case TypeBool:
				v, err := parseBoolStrict(value)
				if err != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
					return 1
				}
				typedValue = v
			case TypeInt:
				v, err := parseIntStrict(value)
				if err != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
					return 1
				}
				typedValue = v
			case TypeFloat:
				v, err := parseFloatStrictValue(value)
				if err != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
					return 1
				}
				typedValue = v
			case TypeStr:
				typedValue = value
			}
			nestedSet(existing, key, typedValue)
			return writeConfigFile(existing, path, a.configFormat)
		}

		// Flag: coerce the string value to the flag's type
		var typedValue interface{}
		if matchedFlag.Repeatable {
			// Split on comma, coerce each element
			parts := splitEscaped(value, ',')
			coerced := make([]interface{}, len(parts))
			switch matchedFlag.Type {
			case TypeInt:
				for i, p := range parts {
					v, err := parseIntStrict(p)
					if err != nil {
						fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
						return 1
					}
					coerced[i] = v
				}
			case TypeFloat:
				for i, p := range parts {
					v, err := parseFloatStrictValue(p)
					if err != nil {
						fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
						return 1
					}
					coerced[i] = v
				}
			case TypeStr:
				for i, p := range parts {
					coerced[i] = p
				}
			}
			// Unique enforcement
			if matchedFlag.Unique {
				if dup := findDuplicate(coerced); dup != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': duplicate value '%s'\n",
						key, formatValueForError(dup))
					return 1
				}
			}
			typedValue = coerced
		} else {
			switch matchedFlag.Type {
			case TypeBool:
				v, err := parseBoolStrict(value)
				if err != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
					return 1
				}
				typedValue = v
			case TypeInt:
				v, err := parseIntStrict(value)
				if err != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
					return 1
				}
				typedValue = v
			case TypeFloat:
				v, err := parseFloatStrictValue(value)
				if err != nil {
					fmt.Fprintf(os.Stderr, "config set: key '%s': %s\n", key, err.Error())
					return 1
				}
				typedValue = v
			case TypeStr:
				typedValue = value
			}
		}

		existing[key] = typedValue
		return writeConfigFile(existing, path, a.configFormat)
	}, WithArgs(
		NewArg("key", "The config key to set, matching a registered flag name"),
		NewArg("value", "Value to set (comma-separated for repeatable flags, use backslash to escape commas)",
			ArgRequired(false)),
	), WithFlags(
		BoolFlag("clear", "Clear a repeatable flag by setting its value to an empty list", Default(false)),
		BoolFlag("default", "Reset a key to its default value by removing it from the config file", Default(false)),
	))

	// config edit
	grp.Command("edit", "Open the config file for manual editing in $EDITOR (creates if missing)", func(args map[string]interface{}) int {
		path := configPath(a.Name, a.configPathOverride, a.configFormat)
		dirPath := filepath.Dir(path)
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot create config directory: %s\n", err)
			return 1
		}
		if _, err := os.Stat(path); os.IsNotExist(err) {
			emptyContent := "{}\n"
			if a.configFormat == "toml" {
				emptyContent = ""
			}
			if err := os.WriteFile(path, []byte(emptyContent), 0o644); err != nil {
				fmt.Fprintf(os.Stderr, "error: cannot create config file: %s\n", err)
				return 1
			}
		}
		editor := os.Getenv("EDITOR")
		if editor == "" {
			editor = "vi"
		}
		cmd := exec.Command(editor, path)
		cmd.Stdin = os.Stdin
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			fmt.Fprintf(os.Stderr, "error: editor failed: %s\n", err)
			return 1
		}
		return 0
	}, WithInteractive())

	// config init
	grp.Command("init", "Generate a template config file with documented fields and defaults", func(args map[string]interface{}) int {
		path := configPath(a.Name, a.configPathOverride, a.configFormat)
		if _, err := os.Stat(path); err == nil {
			fmt.Fprintf(os.Stderr, "error: config file already exists: %s\n", path)
			return 1
		}
		dirPath := filepath.Dir(path)
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot create config directory: %s\n", err)
			return 1
		}

		allFlags := a.collectAllFlags()

		if a.configFormat == "toml" {
			content := a.generateTomlTemplate(allFlags)
			if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
				fmt.Fprintf(os.Stderr, "error: cannot write config file: %s\n", err)
				return 1
			}
		} else {
			content := a.generateJSONTemplate(allFlags)
			if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
				fmt.Fprintf(os.Stderr, "error: cannot write config file: %s\n", err)
				return 1
			}
		}
		fmt.Println(path)
		return 0
	})
}

// validateBoundConfigFields validates that bound config fields for a command
// are present and have correct types in the config data.
// Returns an error message or empty string on success.
func (a *App) validateBoundConfigFields(cmd *Command, configData map[string]interface{}) string {
	for _, fieldName := range cmd.configFields {
		cf, ok := a.configFields[fieldName]
		if !ok {
			// Should not happen — validated by validateConfigFieldBindings
			continue
		}
		val, exists := nestedGet(configData, fieldName)
		if !exists {
			if cf.Required {
				return fmt.Sprintf("required config field \"%s\" is missing from config file", fieldName)
			}
			continue
		}
		// Validate type
		if _, errStr := coerceConfigScalar(val, cf.Type, true); errStr != "" {
			return fmt.Sprintf("config field \"%s\": %s", fieldName, errStr)
		}
	}
	return ""
}

// validateUnknownConfigKeys validates that all keys in the config file are known
// (match a flag, config field, or framework field).
// Returns an error message or empty string on success.
func (a *App) validateUnknownConfigKeys(configData map[string]interface{}) string {
	if len(configData) == 0 {
		return ""
	}
	// Build set of all known keys: flags (using param names), config fields, framework fields
	knownKeys := make(map[string]bool)
	allFlags := a.collectAllFlags()
	for _, f := range allFlags {
		knownKeys[flagParamName(f.Name)] = true
	}
	for name := range a.configFields {
		knownKeys[name] = true
	}
	if a.frameworkFields != nil {
		for name := range a.frameworkFields {
			knownKeys[name] = true
		}
	}
	for _, key := range collectNestedKeys(configData, "") {
		if !knownKeys[key] {
			return fmt.Sprintf("unknown key \"%s\" in config file", key)
		}
	}
	return ""
}

// generateTomlTemplate generates a TOML template config file with comments.
// Config fields with dot-names are organized into TOML sections.
// Required fields are left empty, optional fields get their defaults.
func (a *App) generateTomlTemplate(allFlags []Flag) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("# Configuration for %s\n\n", a.Name))

	// Write flags as top-level keys
	for _, f := range allFlags {
		param := flagParamName(f.Name)
		sb.WriteString(fmt.Sprintf("# %s (type: %s)\n", f.Help, flagTypeName[f.Type]))
		if f.hasDefault && f.Default != nil {
			sb.WriteString(fmt.Sprintf("%s = %s\n", param, formatTomlValue(f.Default)))
		} else {
			sb.WriteString(fmt.Sprintf("# %s = \n", param))
		}
		sb.WriteString("\n")
	}

	// Write config fields, grouping dot-names into TOML sections
	type sectionEntry struct {
		key  string
		cf   *ConfigField
	}
	sections := make(map[string][]sectionEntry) // section -> entries
	var topLevel []*ConfigField                  // non-dotted fields
	var sectionOrder []string

	for _, name := range a.configFieldOrder {
		cf := a.configFields[name]
		if idx := strings.LastIndex(name, "."); idx != -1 {
			section := name[:idx]
			key := name[idx+1:]
			if _, ok := sections[section]; !ok {
				sectionOrder = append(sectionOrder, section)
			}
			sections[section] = append(sections[section], sectionEntry{key: key, cf: cf})
		} else {
			topLevel = append(topLevel, cf)
		}
	}

	// Write non-dotted config fields
	for _, cf := range topLevel {
		sb.WriteString(fmt.Sprintf("# %s (type: %s)\n", cf.Help, flagTypeName[cf.Type]))
		if cf.HasDefault && cf.Default != nil {
			sb.WriteString(fmt.Sprintf("%s = %s\n", cf.Name, formatTomlValue(cf.Default)))
		} else if cf.Required {
			sb.WriteString(fmt.Sprintf("# %s =  # REQUIRED\n", cf.Name))
		} else {
			sb.WriteString(fmt.Sprintf("# %s = \n", cf.Name))
		}
		sb.WriteString("\n")
	}

	// Write sectioned config fields
	for _, section := range sectionOrder {
		entries := sections[section]
		sb.WriteString(fmt.Sprintf("[%s]\n", section))
		for _, e := range entries {
			sb.WriteString(fmt.Sprintf("# %s (type: %s)\n", e.cf.Help, flagTypeName[e.cf.Type]))
			if e.cf.HasDefault && e.cf.Default != nil {
				sb.WriteString(fmt.Sprintf("%s = %s\n", e.key, formatTomlValue(e.cf.Default)))
			} else if e.cf.Required {
				sb.WriteString(fmt.Sprintf("# %s =  # REQUIRED\n", e.key))
			} else {
				sb.WriteString(fmt.Sprintf("# %s = \n", e.key))
			}
		}
		sb.WriteString("\n")
	}

	return sb.String()
}

// generateJSONTemplate generates a JSON template config file.
// Config fields with dot-names are nested into objects.
// Required fields are left empty (null), optional fields get their defaults.
func (a *App) generateJSONTemplate(allFlags []Flag) string {
	result := make(map[string]interface{})

	// Add flags
	for _, f := range allFlags {
		param := flagParamName(f.Name)
		if f.hasDefault && f.Default != nil {
			result[param] = f.Default
		} else {
			result[param] = nil
		}
	}

	// Add config fields, nesting dot-names into objects via nestedSet
	for _, name := range a.configFieldOrder {
		cf := a.configFields[name]
		if cf.HasDefault && cf.Default != nil {
			nestedSet(result, name, cf.Default)
		} else {
			nestedSet(result, name, nil)
		}
	}

	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return "{}\n"
	}
	return string(data) + "\n"
}

// formatTomlValue formats a Go value as a TOML value string.
func formatTomlValue(v interface{}) string {
	switch val := v.(type) {
	case string:
		return fmt.Sprintf("%q", val)
	case bool:
		if val {
			return "true"
		}
		return "false"
	case int:
		return fmt.Sprintf("%d", val)
	case float64:
		s := fmt.Sprintf("%v", val)
		if !strings.Contains(s, ".") {
			s += ".0"
		}
		return s
	default:
		return fmt.Sprintf("%v", val)
	}
}

// formatConfigValue formats a value for config show output.
func formatConfigValue(v interface{}) string {
	if v == nil {
		return "<nil>"
	}
	switch val := v.(type) {
	case bool:
		if val {
			return "true"
		}
		return "false"
	case []interface{}:
		parts := make([]string, len(val))
		for i, v := range val {
			b, _ := json.Marshal(v)
			parts[i] = string(b)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case string:
		return val
	default:
		return fmt.Sprintf("%v", val)
	}
}
