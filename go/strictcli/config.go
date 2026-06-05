package strictcli

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	tomledit "github.com/smm-h/go-toml-edit"
)

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

// coerceConfigScalar coerces a single JSON-decoded value to the given flag type.
// Returns the coerced value and an error string (empty on success).
func coerceConfigScalar(value interface{}, flagType FlagType) (interface{}, string) {
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

// coerceConfigValue coerces a JSON-decoded value to the flag's type.
// Handles both scalar values and arrays (for repeatable flags).
// Returns the coerced value and an error string (empty on success).
func coerceConfigValue(value interface{}, f *Flag) (interface{}, string) {
	if arr, ok := value.([]interface{}); ok {
		if !f.Repeatable {
			return nil, "expected scalar, got array"
		}
		result := make([]interface{}, len(arr))
		for i, elem := range arr {
			coerced, errStr := coerceConfigScalar(elem, f.Type)
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
	return coerceConfigScalar(value, f.Type)
}

// typeName returns a human-readable type name for a config-decoded value.
func typeName(v interface{}) string {
	switch v.(type) {
	case bool:
		return "bool"
	case int64:
		return "int"
	case float64:
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
		for _, f := range cmd.Flags {
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
			for _, f := range cmd.Flags {
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
	grp := a.Group("config", "Manage configuration")

	// config path
	grp.Command("path", "Print the config file path", func(args map[string]interface{}) int {
		fmt.Println(configPath(a.Name, a.configPathOverride, a.configFormat))
		return 0
	})

	// config show
	grp.Command("show", "Show all config values with source attribution", func(args map[string]interface{}) int {
		usePlain := args["plain"].(bool)
		useJSON := args["json"].(bool)
		if !usePlain && !useJSON {
			fmt.Fprintln(os.Stderr, "config show: specify --plain or --json")
			return 1
		}
		configData := loadConfig(a.Name, a.configPathOverride, a.configFormat)
		allFlags := a.collectAllFlags()

		type entry struct {
			Source string      `json:"source"`
			Value  interface{} `json:"value"`
		}

		if useJSON {
			result := make(map[string]entry)
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
				result[param] = entry{Value: value, Source: source}
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
		return 0
	}, WithMutex(
		MutexGroup{Flags: []Flag{
			BoolFlag("plain", "Human-readable output"),
			BoolFlag("json", "JSON output"),
		}},
	))

	// config set
	grp.Command("set", "Set a config value", func(args map[string]interface{}) int {
		key := args["key"].(string)
		path := configPath(a.Name, a.configPathOverride, a.configFormat)
		dirPath := filepath.Dir(path)
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot create config directory: %s\n", err)
			return 1
		}
		// Read existing config
		existing := loadConfig(a.Name, a.configPathOverride, a.configFormat)

		// Look up the key against registered flags
		allFlags := a.collectAllFlags()
		var matchedFlag *Flag
		for i := range allFlags {
			if flagParamName(allFlags[i].Name) == key {
				matchedFlag = &allFlags[i]
				break
			}
		}
		if matchedFlag == nil {
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
			fmt.Fprintln(os.Stderr, "--clear and --default are mutually exclusive")
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
			if _, ok := existing[key]; !ok {
				fmt.Fprintf(os.Stderr, "config set: key '%s' not in config\n", key)
				return 1
			}
			delete(existing, key)
			return writeConfigFile(existing, path, a.configFormat)
		}

		// Coerce the string value to the flag's type
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
		NewArg("key", "Config key to set"),
		NewArg("value", "Value to set (comma-separated for repeatable flags)",
			ArgRequired(false)),
	), WithFlags(
		BoolFlag("clear", "Clear a repeatable flag (set to empty list)"),
		BoolFlag("default", "Reset a key to its default (remove from config)"),
	))

	// config edit
	grp.Command("edit", "Open the config file in $EDITOR", func(args map[string]interface{}) int {
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
	})
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
		data, err := json.Marshal(val)
		if err != nil {
			return fmt.Sprintf("%v", val)
		}
		return strings.ReplaceAll(string(data), ",", ", ")
	case string:
		return val
	default:
		return fmt.Sprintf("%v", val)
	}
}
