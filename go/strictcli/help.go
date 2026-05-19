package strictcli

import (
	"fmt"
	"strings"
)

func formatVersion(app *App) string {
	return fmt.Sprintf("%s %s", app.Name, app.Version)
}

func formatAppHelp(app *App) string {
	var lines []string
	lines = append(lines, fmt.Sprintf("%s v%s -- %s", app.Name, app.Version, app.Help))

	if len(app.cmdOrder) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Commands:")
		maxLen := 0
		for _, name := range app.cmdOrder {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range app.cmdOrder {
			cmd := app.commands[name]
			padding := maxLen - len(name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", name, strings.Repeat(" ", padding), cmd.Help))
		}
	}

	if len(app.groupOrder) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Groups:")
		maxLen := 0
		for _, name := range app.groupOrder {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range app.groupOrder {
			grp := app.groups[name]
			padding := maxLen - len(name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", name, strings.Repeat(" ", padding), grp.Help))
		}
	}

	if len(app.deprecated) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Deprecated:")
		maxLen := 0
		for _, d := range app.deprecated {
			if len(d.Name) > maxLen {
				maxLen = len(d.Name)
			}
		}
		for _, d := range app.deprecated {
			padding := maxLen - len(d.Name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", d.Name, strings.Repeat(" ", padding), d.Message))
		}
	}

	lines = append(lines, "")
	lines = append(lines, fmt.Sprintf("Use '%s <command> --help' for more information.", app.Name))

	return strings.Join(lines, "\n")
}

func formatGroupHelp(app *App, group *Group, path []string) string {
	var lines []string
	fullPath := strings.Join(path, " ")
	lines = append(lines, fmt.Sprintf("%s %s -- %s", app.Name, fullPath, group.Help))

	if len(group.order) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Commands:")
		maxLen := 0
		for _, name := range group.order {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range group.order {
			cmd := group.Commands[name]
			padding := maxLen - len(name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", name, strings.Repeat(" ", padding), cmd.Help))
		}
	}

	if len(group.groupOrder) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Groups:")
		maxLen := 0
		for _, name := range group.groupOrder {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range group.groupOrder {
			sub := group.Groups[name]
			padding := maxLen - len(name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", name, strings.Repeat(" ", padding), sub.Help))
		}
	}

	if len(group.deprecated) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Deprecated:")
		maxLen := 0
		for _, d := range group.deprecated {
			if len(d.Name) > maxLen {
				maxLen = len(d.Name)
			}
		}
		for _, d := range group.deprecated {
			padding := maxLen - len(d.Name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", d.Name, strings.Repeat(" ", padding), d.Message))
		}
	}

	lines = append(lines, "")
	lines = append(lines, fmt.Sprintf("Use '%s %s <command> --help' for more information.", app.Name, fullPath))

	return strings.Join(lines, "\n")
}

func formatCommandHelp(app *App, cmd *Command, prefix string) string {
	var lines []string
	lines = append(lines, fmt.Sprintf("%s %s%s -- %s", app.Name, prefix, cmd.Name, cmd.Help))

	// Passthrough commands: minimal help (no flags/args sections)
	if cmd.Passthrough {
		return strings.Join(lines, "\n")
	}

	if len(cmd.Args) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Arguments:")
		maxLen := 0
		for _, a := range cmd.Args {
			displayName := a.Name
			if a.IsVariadic {
				displayName = a.Name + "..."
			}
			if len(displayName) > maxLen {
				maxLen = len(displayName)
			}
		}
		for _, a := range cmd.Args {
			displayName := a.Name
			if a.IsVariadic {
				displayName = a.Name + "..."
			}
			padding := maxLen - len(displayName) + 4
			helpText := a.Help
			if !a.Required {
				if a.hasDefault {
					helpText += fmt.Sprintf(" [default: %v]", a.Default)
				} else {
					helpText += " (optional)"
				}
			}
			lines = append(lines, fmt.Sprintf("  %s%s%s", displayName, strings.Repeat(" ", padding), helpText))
		}
	}

	// Collect flag names that belong to mutex groups
	mutexFlagNames := make(map[string]bool)
	for _, mg := range cmd.Mutex {
		for _, f := range mg.Flags {
			mutexFlagNames[f.Name] = true
		}
	}

	// Regular flags (not in any mutex group)
	var regularFlags []Flag
	for _, f := range cmd.Flags {
		if !mutexFlagNames[f.Name] {
			regularFlags = append(regularFlags, f)
		}
	}

	if len(regularFlags) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Flags:")
		specs := make([]string, len(regularFlags))
		maxSpec := 0
		for i, f := range regularFlags {
			specs[i] = buildFlagSpec(f)
			if len(specs[i]) > maxSpec {
				maxSpec = len(specs[i])
			}
		}
		for i, f := range regularFlags {
			padding := maxSpec - len(specs[i]) + 4
			meta := buildFlagMeta(f)
			lines = append(lines, fmt.Sprintf("  %s%s%s%s", specs[i], strings.Repeat(" ", padding), f.Help, meta))
		}
	}

	// Mutex groups
	for _, mg := range cmd.Mutex {
		lines = append(lines, "")
		lines = append(lines, "Flags (mutually exclusive):")
		specs := make([]string, len(mg.Flags))
		maxSpec := 0
		for i, f := range mg.Flags {
			specs[i] = buildFlagSpec(f)
			if len(specs[i]) > maxSpec {
				maxSpec = len(specs[i])
			}
		}
		for i, f := range mg.Flags {
			padding := maxSpec - len(specs[i]) + 4
			meta := buildFlagMeta(f)
			lines = append(lines, fmt.Sprintf("  %s%s%s%s", specs[i], strings.Repeat(" ", padding), f.Help, meta))
		}
	}

	// Global flags section
	if len(app.globalFlags) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Global flags:")
		specs := make([]string, len(app.globalFlags))
		maxSpec := 0
		for i, f := range app.globalFlags {
			specs[i] = buildFlagSpec(f)
			if len(specs[i]) > maxSpec {
				maxSpec = len(specs[i])
			}
		}
		for i, f := range app.globalFlags {
			padding := maxSpec - len(specs[i]) + 4
			meta := buildFlagMeta(f)
			lines = append(lines, fmt.Sprintf("  %s%s%s%s", specs[i], strings.Repeat(" ", padding), f.Help, meta))
		}
	}

	return strings.Join(lines, "\n")
}

func buildFlagSpec(f Flag) string {
	var parts []string
	if f.Type == TypeBool && f.Negatable {
		parts = append(parts, fmt.Sprintf("--%s, --no-%s", f.Name, f.Name))
		if f.Short != "" {
			parts = append(parts, "-"+f.Short)
		}
	} else {
		parts = append(parts, "--"+f.Name)
		if f.Short != "" {
			parts = append(parts, "-"+f.Short)
		}
	}
	spec := strings.Join(parts, ", ")
	switch f.Type {
	case TypeStr:
		spec += " <str>"
	case TypeInt:
		spec += " <int>"
	case TypeFloat:
		spec += " <float>"
	}
	return spec
}

func buildFlagMeta(f Flag) string {
	var metaParts []string
	if f.Repeatable {
		metaParts = append(metaParts, "repeatable")
	}
	if f.Choices != nil {
		metaParts = append(metaParts, "choices: "+formatChoices(f.Choices))
	}
	if f.Env != "" {
		metaParts = append(metaParts, "env: "+f.Env)
	}
	if f.Type == TypeBool {
		if def, ok := f.Default.(bool); ok && def {
			metaParts = append(metaParts, "default: true")
		} else {
			metaParts = append(metaParts, "default: false")
		}
	} else if f.Repeatable {
		// Repeatable flags are never required; no default shown
	} else if f.hasDefault && f.Default != nil {
		metaParts = append(metaParts, fmt.Sprintf("default: %v", f.Default))
	} else if f.hasDefault {
		metaParts = append(metaParts, "optional")
	} else {
		metaParts = append(metaParts, "required")
	}

	var sb strings.Builder
	for i, part := range metaParts {
		if i > 0 {
			sb.WriteString(" ")
		}
		sb.WriteString("[")
		sb.WriteString(part)
		sb.WriteString("]")
	}
	return " " + sb.String()
}
