package strictcli

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// parseCommand parses tokens against a resolved command's flags and args.
// globalFlags are also recognized in post-command tokens and returned separately
// in postGlobalValues so the caller can merge them with pre-command globals.
// Returns (kwargs, postGlobalValues, errorString).
func parseCommand(cmd *Command, tokens []string, globalFlags []Flag) (map[string]interface{}, map[string]interface{}, string) {
	// Build flag lookup maps
	longLookup := make(map[string]*Flag)    // --flag-name -> Flag
	shortLookup := make(map[string]*Flag)   // -x -> Flag
	negationLookup := make(map[string]*Flag) // --no-flag-name -> Flag

	for i := range cmd.Flags {
		f := &cmd.Flags[i]
		longLookup["--"+f.Name] = f
		if f.Short != "" {
			shortLookup["-"+f.Short] = f
		}
		if f.Type == TypeBool && f.Negatable {
			negationLookup["--no-"+f.Name] = f
		}
	}

	// Also include global flags in the lookup tables so they are recognized
	// when placed after the command name (matching Python's _parse_command)
	globalFlagNames := make(map[string]bool)
	for i := range globalFlags {
		f := &globalFlags[i]
		longLookup["--"+f.Name] = f
		if f.Short != "" {
			shortLookup["-"+f.Short] = f
		}
		if f.Type == TypeBool && f.Negatable {
			negationLookup["--no-"+f.Name] = f
		}
		globalFlagNames[f.Name] = true
	}

	// Track which flags were set by CLI args
	cliSet := make(map[string]interface{})
	var positionals []string

	storeValue := func(f *Flag, value interface{}) {
		if f.Repeatable {
			if existing, ok := cliSet[f.Name]; ok {
				cliSet[f.Name] = append(existing.([]interface{}), value)
			} else {
				cliSet[f.Name] = []interface{}{value}
			}
		} else {
			cliSet[f.Name] = value
		}
	}

	i := 0
	stopFlags := false

	for i < len(tokens) {
		tok := tokens[i]

		if stopFlags || !strings.HasPrefix(tok, "-") || tok == "-" {
			positionals = append(positionals, tok)
			i++
			continue
		}

		if tok == "--" {
			stopFlags = true
			i++
			continue
		}

		// --flag=value form
		if strings.HasPrefix(tok, "--") && strings.Contains(tok, "=") {
			eqPos := strings.Index(tok, "=")
			flagPart := tok[:eqPos]
			valuePart := tok[eqPos+1:]

			if f, ok := longLookup[flagPart]; ok {
				if f.Type == TypeBool {
					return nil, nil, fmt.Sprintf("flag '%s' is a boolean flag and does not take a value", flagPart)
				}
				if f.Type == TypeInt {
					intVal, err := strconv.Atoi(valuePart)
					if err != nil {
						return nil, nil, fmt.Sprintf("--%s: expected integer, got '%s'", f.Name, valuePart)
					}
					storeValue(f, intVal)
				} else {
					storeValue(f, valuePart)
				}
			} else if _, ok := negationLookup[flagPart]; ok {
				return nil, nil, fmt.Sprintf("flag '%s' is a boolean negation and does not take a value", flagPart)
			} else {
				return nil, nil, fmt.Sprintf("unknown flag '%s'", flagPart)
			}
			i++
			continue
		}

		// --no-flag negation
		if f, ok := negationLookup[tok]; ok {
			cliSet[f.Name] = false
			i++
			continue
		}

		// --flag (long form without =)
		if strings.HasPrefix(tok, "--") {
			f, ok := longLookup[tok]
			if !ok {
				return nil, nil, fmt.Sprintf("unknown flag '%s'", tok)
			}
			if f.Type == TypeBool {
				cliSet[f.Name] = true
				i++
			} else {
				if i+1 >= len(tokens) {
					return nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				raw := tokens[i+1]
				if f.Type == TypeInt {
					intVal, err := strconv.Atoi(raw)
					if err != nil {
						return nil, nil, fmt.Sprintf("--%s: expected integer, got '%s'", f.Name, raw)
					}
					storeValue(f, intVal)
				} else {
					storeValue(f, raw)
				}
				i += 2
			}
			continue
		}

		// -x (short form)
		if strings.HasPrefix(tok, "-") && len(tok) == 2 {
			f, ok := shortLookup[tok]
			if !ok {
				return nil, nil, fmt.Sprintf("unknown flag '%s'", tok)
			}
			if f.Type == TypeBool {
				cliSet[f.Name] = true
				i++
			} else {
				if i+1 >= len(tokens) {
					return nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				raw := tokens[i+1]
				if f.Type == TypeInt {
					intVal, err := strconv.Atoi(raw)
					if err != nil {
						return nil, nil, fmt.Sprintf("--%s: expected integer, got '%s'", f.Name, raw)
					}
					storeValue(f, intVal)
				} else {
					storeValue(f, raw)
				}
				i += 2
			}
			continue
		}

		// Unknown flag-like token
		return nil, nil, fmt.Sprintf("unknown flag '%s'", tok)
	}

	// Resolve env vars for flags not set by CLI
	for i := range cmd.Flags {
		f := &cmd.Flags[i]
		if _, ok := cliSet[f.Name]; ok {
			continue
		}
		if f.Env == "" {
			continue
		}
		envVal, ok := os.LookupEnv(f.Env)
		if !ok {
			continue
		}
		switch f.Type {
		case TypeBool:
			lower := strings.ToLower(envVal)
			switch lower {
			case "1", "true", "yes":
				cliSet[f.Name] = true
			case "0", "false", "no":
				cliSet[f.Name] = false
			default:
				return nil, nil, fmt.Sprintf(
					"invalid boolean value '%s' for env var '%s' (flag '--%s')",
					envVal, f.Env, f.Name,
				)
			}
		case TypeInt:
			intVal, err := strconv.Atoi(envVal)
			if err != nil {
				return nil, nil, fmt.Sprintf(
					"--%s: expected integer, got '%s' (from env var '%s')",
					f.Name, envVal, f.Env,
				)
			}
			if f.Repeatable {
				cliSet[f.Name] = []interface{}{intVal}
			} else {
				cliSet[f.Name] = intVal
			}
		default: // TypeStr
			if f.Repeatable {
				cliSet[f.Name] = []interface{}{envVal}
			} else {
				cliSet[f.Name] = envVal
			}
		}
	}

	// Enforce mutex group constraints (before defaults)
	for _, mg := range cmd.Mutex {
		var setFlags []string
		for _, f := range mg.Flags {
			if _, ok := cliSet[f.Name]; ok {
				setFlags = append(setFlags, "--"+f.Name)
			}
		}
		if len(setFlags) > 1 {
			return nil, nil, fmt.Sprintf("%s are mutually exclusive", strings.Join(setFlags, " and "))
		}
		if len(setFlags) == 0 {
			names := make([]string, len(mg.Flags))
			for j, f := range mg.Flags {
				names[j] = "--" + f.Name
			}
			return nil, nil, fmt.Sprintf("one of %s is required", strings.Join(names, ", "))
		}
	}

	// Build set of flag names belonging to mutex groups
	mutexFlagNames := make(map[string]bool)
	for _, mg := range cmd.Mutex {
		for _, f := range mg.Flags {
			mutexFlagNames[f.Name] = true
		}
	}

	// Apply defaults
	for i := range cmd.Flags {
		f := &cmd.Flags[i]
		if _, ok := cliSet[f.Name]; ok {
			continue
		}
		if f.Repeatable {
			cliSet[f.Name] = []interface{}{}
		} else if f.Type == TypeBool {
			cliSet[f.Name] = f.Default
		} else if f.hasDefault && f.Default != nil {
			cliSet[f.Name] = f.Default
		} else if f.hasDefault && f.Default == nil {
			// Explicit nil default (for mutex group str flags etc)
			cliSet[f.Name] = nil
		} else if mutexFlagNames[f.Name] {
			cliSet[f.Name] = nil
		} else {
			return nil, nil, fmt.Sprintf("flag '--%s' is required", f.Name)
		}
	}

	// Validate choices
	for i := range cmd.Flags {
		f := &cmd.Flags[i]
		if f.Choices == nil {
			continue
		}
		val, ok := cliSet[f.Name]
		if !ok {
			continue
		}
		if f.Repeatable {
			vals, ok := val.([]interface{})
			if !ok {
				continue
			}
			for _, v := range vals {
				if !inChoices(v, f.Choices) {
					return nil, nil, fmt.Sprintf(
						"--%s: invalid value '%v', must be one of: %s",
						f.Name, v, formatChoices(f.Choices),
					)
				}
			}
		} else {
			if !inChoices(val, f.Choices) {
				return nil, nil, fmt.Sprintf(
					"--%s: invalid value '%v', must be one of: %s",
					f.Name, val, formatChoices(f.Choices),
				)
			}
		}
	}

	// Custom validation
	for i := range cmd.Flags {
		f := &cmd.Flags[i]
		if f.Validate == nil {
			continue
		}
		val, ok := cliSet[f.Name]
		if !ok {
			continue
		}
		if f.Repeatable {
			vals, ok := val.([]interface{})
			if !ok {
				continue
			}
			for _, v := range vals {
				if err := f.Validate(v); err != nil {
					return nil, nil, fmt.Sprintf("--%s: %s", f.Name, err.Error())
				}
			}
		} else {
			if err := f.Validate(val); err != nil {
				return nil, nil, fmt.Sprintf("--%s: %s", f.Name, err.Error())
			}
		}
	}

	// Resolve positional args
	argValues := make(map[string]interface{})
	posIdx := 0
	for _, a := range cmd.Args {
		if a.IsVariadic {
			// Collect all remaining positionals
			remaining := positionals[posIdx:]
			if len(remaining) == 0 {
				if a.Required {
					return nil, nil, fmt.Sprintf("missing required argument '%s'", a.Name)
				}
				// Optional variadic with no values: empty list
				argValues[a.Name] = []interface{}{}
			} else {
				vals := make([]interface{}, len(remaining))
				for j, v := range remaining {
					vals[j] = v
				}
				argValues[a.Name] = vals
			}
			posIdx = len(positionals)
		} else if posIdx < len(positionals) {
			argValues[a.Name] = positionals[posIdx]
			posIdx++
		} else if a.Required {
			return nil, nil, fmt.Sprintf("missing required argument '%s'", a.Name)
		} else if a.hasDefault {
			argValues[a.Name] = a.Default
		} else {
			// Optional arg with no default: nil (printed as "None" for conformance)
			argValues[a.Name] = nil
		}
	}
	if posIdx < len(positionals) {
		return nil, nil, fmt.Sprintf("unexpected argument '%s'", positionals[posIdx])
	}

	// Build kwargs dict (command flags only)
	kwargs := make(map[string]interface{})
	for i := range cmd.Flags {
		f := &cmd.Flags[i]
		kwargs[flagParamName(f.Name)] = cliSet[f.Name]
	}
	for _, a := range cmd.Args {
		if v, ok := argValues[a.Name]; ok {
			kwargs[a.Name] = v
		}
	}

	// Separate out global flag values parsed from post-command tokens
	postGlobalValues := make(map[string]interface{})
	for name := range globalFlagNames {
		if v, ok := cliSet[name]; ok {
			postGlobalValues[flagParamName(name)] = v
		}
	}

	return kwargs, postGlobalValues, ""
}

func inChoices(val interface{}, choices []interface{}) bool {
	for _, c := range choices {
		if val == c {
			return true
		}
	}
	return false
}

func formatChoices(choices []interface{}) string {
	parts := make([]string, len(choices))
	for i, c := range choices {
		parts[i] = fmt.Sprintf("%v", c)
	}
	return strings.Join(parts, ", ")
}
