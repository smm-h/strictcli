package strictcli

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
)

// configPath returns the full path to the config file for an app.
func configPath(appName string) string {
	configHome := os.Getenv("XDG_CONFIG_HOME")
	if configHome == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			home = os.Getenv("HOME")
		}
		configHome = filepath.Join(home, ".config")
	}
	return filepath.Join(configHome, appName, "config.json")
}

// loadConfig reads the JSON config file for an app.
// Returns an empty map if the file doesn't exist or contains invalid JSON.
// Invalid JSON prints a warning to stderr.
func loadConfig(appName string) map[string]interface{} {
	path := configPath(appName)
	data, err := os.ReadFile(path)
	if err != nil {
		// File doesn't exist or can't be read -- silent
		return map[string]interface{}{}
	}
	var result map[string]interface{}
	if err := json.Unmarshal(data, &result); err != nil {
		fmt.Fprintf(os.Stderr, "warning: invalid JSON in config file '%s', ignoring\n", path)
		return map[string]interface{}{}
	}
	return result
}

// coerceConfigValue coerces a JSON-decoded value to the flag's type.
// Returns the coerced value and an error string (empty on success).
func coerceConfigValue(value interface{}, f *Flag) (interface{}, string) {
	switch f.Type {
	case TypeBool:
		if b, ok := value.(bool); ok {
			return b, ""
		}
		return nil, fmt.Sprintf("expected boolean, got %s", jsonTypeName(value))
	case TypeInt:
		// JSON numbers decode as float64; accept only whole numbers
		if fv, ok := value.(float64); ok {
			intVal := int(fv)
			if float64(intVal) == fv {
				return intVal, ""
			}
			return nil, "expected integer, got float"
		}
		return nil, fmt.Sprintf("expected integer, got %s", jsonTypeName(value))
	case TypeFloat:
		// Accept float64 (JSON numbers always decode as float64)
		if fv, ok := value.(float64); ok {
			return fv, ""
		}
		return nil, fmt.Sprintf("expected float, got %s", jsonTypeName(value))
	case TypeStr:
		if s, ok := value.(string); ok {
			return s, ""
		}
		return nil, fmt.Sprintf("expected string, got %s", jsonTypeName(value))
	}
	return nil, fmt.Sprintf("unsupported flag type %d", f.Type)
}

// jsonTypeName returns a human-readable type name for a JSON-decoded value.
func jsonTypeName(v interface{}) string {
	switch v.(type) {
	case bool:
		return "bool"
	case float64:
		return "float"
	case string:
		return "str"
	case nil:
		return "null"
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

// registerConfigGroup registers the auto-generated 'config' command group.
func (a *App) registerConfigGroup() {
	grp := a.Group("config", "Manage configuration")

	// config path
	grp.Command("path", "Print the config file path", func(args map[string]interface{}) int {
		fmt.Println(configPath(a.Name))
		return 0
	})

	// config show
	grp.Command("show", "Show all config values with source attribution", func(args map[string]interface{}) int {
		configData := loadConfig(a.Name)
		allFlags := a.collectAllFlags()
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
	})

	// config set
	grp.Command("set", "Set a config value", func(args map[string]interface{}) int {
		key := args["key"].(string)
		value := args["value"].(string)
		path := configPath(a.Name)
		dirPath := filepath.Dir(path)
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot create config directory: %s\n", err)
			return 1
		}
		// Read existing config
		existing := make(map[string]interface{})
		if data, err := os.ReadFile(path); err == nil {
			// Ignore JSON errors -- start fresh if invalid
			json.Unmarshal(data, &existing)
		}
		existing[key] = value
		data, err := json.MarshalIndent(existing, "", "  ")
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot marshal config: %s\n", err)
			return 1
		}
		if err := os.WriteFile(path, append(data, '\n'), 0o644); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot write config file: %s\n", err)
			return 1
		}
		return 0
	}, WithArgs(
		NewArg("key", "Config key to set"),
		NewArg("value", "Value to set"),
	))

	// config edit
	grp.Command("edit", "Open the config file in $EDITOR", func(args map[string]interface{}) int {
		path := configPath(a.Name)
		dirPath := filepath.Dir(path)
		if err := os.MkdirAll(dirPath, 0o755); err != nil {
			fmt.Fprintf(os.Stderr, "error: cannot create config directory: %s\n", err)
			return 1
		}
		if _, err := os.Stat(path); os.IsNotExist(err) {
			if err := os.WriteFile(path, []byte("{}\n"), 0o644); err != nil {
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
	case string:
		return val
	default:
		return fmt.Sprintf("%v", val)
	}
}
