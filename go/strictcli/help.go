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

	// Filter hidden commands
	var visibleCmds []string
	for _, name := range app.cmdOrder {
		if !app.commands[name].Hidden {
			visibleCmds = append(visibleCmds, name)
		}
	}
	if len(visibleCmds) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Commands:")
		maxLen := 0
		for _, name := range visibleCmds {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range visibleCmds {
			cmd := app.commands[name]
			padding := maxLen - len(name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", name, strings.Repeat(" ", padding), cmd.Help))
		}
	}

	// Filter hidden groups
	var visibleGroups []string
	for _, name := range app.groupOrder {
		if !app.groups[name].Hidden {
			visibleGroups = append(visibleGroups, name)
		}
	}
	if len(visibleGroups) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Groups:")
		maxLen := 0
		for _, name := range visibleGroups {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range visibleGroups {
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

	if len(app.infraRootOrder) > 0 || len(app.handshakeOrder) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Infrastructure:")
		lines = append(lines, "  (location/handshake env vars; not suppressed by --hermetic)")
		maxLen := 0
		for _, ev := range app.infraRootOrder {
			if len(ev) > maxLen {
				maxLen = len(ev)
			}
		}
		for _, ev := range app.handshakeOrder {
			if len(ev) > maxLen {
				maxLen = len(ev)
			}
		}
		for _, ev := range app.infraRootOrder {
			padding := maxLen - len(ev) + 4
			var def string
			for _, d := range app.infraRootDecls {
				if d.envVar == ev {
					def = d.defaultPath
					break
				}
			}
			lines = append(lines, fmt.Sprintf("  %s%sroot (default: %s)", ev, strings.Repeat(" ", padding), def))
		}
		for _, ev := range app.handshakeOrder {
			padding := maxLen - len(ev) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", ev, strings.Repeat(" ", padding), app.handshakeEnvs[ev]))
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

	// Filter hidden commands
	var visibleCmds []string
	for _, name := range group.order {
		if !group.Commands[name].Hidden {
			visibleCmds = append(visibleCmds, name)
		}
	}
	if len(visibleCmds) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Commands:")
		maxLen := 0
		for _, name := range visibleCmds {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range visibleCmds {
			cmd := group.Commands[name]
			padding := maxLen - len(name) + 4
			lines = append(lines, fmt.Sprintf("  %s%s%s", name, strings.Repeat(" ", padding), cmd.Help))
		}
	}

	// Filter hidden groups
	var visibleGroups []string
	for _, name := range group.groupOrder {
		if !group.Groups[name].Hidden {
			visibleGroups = append(visibleGroups, name)
		}
	}
	if len(visibleGroups) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Groups:")
		maxLen := 0
		for _, name := range visibleGroups {
			if len(name) > maxLen {
				maxLen = len(name)
			}
		}
		for _, name := range visibleGroups {
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

	if len(cmd.args) > 0 {
		lines = append(lines, "")
		lines = append(lines, "Arguments:")
		maxLen := 0
		for _, a := range cmd.args {
			displayName := a.Name
			if a.IsVariadic {
				displayName = a.Name + "..."
			}
			if len(displayName) > maxLen {
				maxLen = len(displayName)
			}
		}
		for _, a := range cmd.args {
			displayName := a.Name
			if a.IsVariadic {
				displayName = a.Name + "..."
			}
			padding := maxLen - len(displayName) + 4
			helpText := a.Help
			var metaParts []string
			if a.Type != TypeStr {
				metaParts = append(metaParts, fmt.Sprintf("type: %s", flagTypeName[a.Type]))
			}
			if a.Choices != nil {
				metaParts = append(metaParts, fmt.Sprintf("choices: %s", formatChoices(a.Choices)))
			}
			if !a.Required {
				if a.hasDefault {
					metaParts = append(metaParts, fmt.Sprintf("default: %v", a.Default))
				} else {
					metaParts = append(metaParts, "optional")
				}
			}
			meta := ""
			if len(metaParts) > 0 {
				var sb strings.Builder
				for i, part := range metaParts {
					if i > 0 {
						sb.WriteString(" ")
					}
					sb.WriteString("[")
					sb.WriteString(part)
					sb.WriteString("]")
				}
				meta = " " + sb.String()
			}
			lines = append(lines, fmt.Sprintf("  %s%s%s%s", displayName, strings.Repeat(" ", padding), helpText, meta))
		}
	}

	// Collect flag names that belong to mutex groups
	mutexFlagNames := make(map[string]bool)
	for _, mg := range cmd.mutex {
		for _, f := range mg.Flags {
			mutexFlagNames[f.Name] = true
		}
	}

	// Regular flags (not in any mutex group)
	var regularFlags []Flag
	for _, f := range cmd.flags {
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
	for _, mg := range cmd.mutex {
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
	if IsDictType(f.Type) {
		valTypeName := flagTypeName[ItemType(f.Type)]
		spec += fmt.Sprintf(" <key=%s>", valTypeName)
	} else if IsListType(f.Type) {
		itemTypeName := flagTypeName[ItemType(f.Type)]
		spec += fmt.Sprintf(" <%s>", itemTypeName)
	} else {
		switch f.Type {
		case TypeStr:
			spec += " <str>"
		case TypeInt:
			spec += " <int>"
		case TypeFloat:
			spec += " <float>"
		}
	}
	return spec
}

func buildFlagMeta(f Flag) string {
	var metaParts []string
	if IsDictType(f.Type) {
		metaParts = append(metaParts, "dict")
	} else if IsListType(f.Type) {
		metaParts = append(metaParts, "list")
	} else if f.Repeatable {
		metaParts = append(metaParts, "repeatable")
	}
	if f.Unique {
		metaParts = append(metaParts, "unique")
	}
	if f.Choices != nil {
		metaParts = append(metaParts, "choices: "+formatChoices(f.Choices))
	}
	if f.Env != "" {
		if f.EnvSeparator != "" {
			metaParts = append(metaParts, fmt.Sprintf("env: %s (sep: %s)", f.Env, f.EnvSeparator))
		} else {
			metaParts = append(metaParts, "env: "+f.Env)
		}
	}
	if f.Type == TypeBool && f.hasDefault && f.Default != nil {
		if def, ok := f.Default.(bool); ok && def {
			metaParts = append(metaParts, "default: true")
		} else {
			metaParts = append(metaParts, "default: false")
		}
	} else if f.Repeatable {
		// Repeatable flags are never required; show default only if non-empty
		if f.hasDefault && f.Default != nil {
			if items, ok := f.Default.([]interface{}); ok && len(items) > 0 {
				parts := make([]string, len(items))
				for i, elem := range items {
					parts[i] = formatValueForError(elem)
				}
				metaParts = append(metaParts, fmt.Sprintf("default: %s", strings.Join(parts, ", ")))
			}
		}
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
