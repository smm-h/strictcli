package strictcli

import (
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
)

const atPrefixMaxSize = 1024 * 1024 // 1 MB

// resolveAtPrefix resolves @-prefix for string flag values.
// @path reads from file, @- reads from stdin, @@literal strips leading @.
// Returns (resolved value, error message). Error message is "" on success.
// stdinConsumedBy is a pointer to a *string tracking which flag consumed stdin.
func resolveAtPrefix(flagName, raw string, stdinConsumedBy **string) (string, string) {
	if !strings.HasPrefix(raw, "@") {
		return raw, ""
	}
	if strings.HasPrefix(raw, "@@") {
		return raw[1:], "" // strip leading @
	}
	if raw == "@-" {
		if *stdinConsumedBy != nil {
			return "", fmt.Sprintf("--%s: stdin (@-) can only be used once per invocation", flagName)
		}
		data, err := io.ReadAll(io.LimitReader(os.Stdin, int64(atPrefixMaxSize+1)))
		if err != nil {
			return "", fmt.Sprintf("--%s: cannot read stdin", flagName)
		}
		if len(data) > atPrefixMaxSize {
			return "", fmt.Sprintf("--%s: file exceeds 1 MB limit", flagName)
		}
		consumed := flagName
		*stdinConsumedBy = &consumed
		return strings.TrimRight(string(data), " \t\n\r"), ""
	}
	// @path
	path := raw[1:]
	info, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return "", fmt.Sprintf("--%s: file not found: %s", flagName, path)
		}
		return "", fmt.Sprintf("--%s: cannot read file: %s", flagName, path)
	}
	if info.IsDir() {
		return "", fmt.Sprintf("--%s: cannot read file: %s", flagName, path)
	}
	if info.Size() > int64(atPrefixMaxSize) {
		return "", fmt.Sprintf("--%s: file exceeds 1 MB limit", flagName)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Sprintf("--%s: cannot read file: %s", flagName, path)
	}
	return strings.TrimRight(string(data), " \t\n\r"), ""
}

// parseCommand parses tokens against a resolved command's flags and args.
// globalFlags are also recognized in post-command tokens and returned separately
// in postGlobalValues so the caller can merge them with pre-command globals.
// configData is an optional map of config values (may be nil).
// Returns (kwargs, postGlobalValues, errorString).
func parseCommand(cmd *Command, tokens []string, globalFlags []Flag, configData map[string]interface{}, stdinConsumedBy **string) (map[string]interface{}, map[string]interface{}, string) {
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
				} else if f.Type == TypeFloat {
					floatVal, errStr := parseFloatStrict(f.Name, valuePart)
					if errStr != "" {
						return nil, nil, errStr
					}
					storeValue(f, floatVal)
				} else {
					resolved, errStr := resolveAtPrefix(f.Name, valuePart, stdinConsumedBy)
					if errStr != "" {
						return nil, nil, errStr
					}
					storeValue(f, resolved)
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
				} else if f.Type == TypeFloat {
					floatVal, errStr := parseFloatStrict(f.Name, raw)
					if errStr != "" {
						return nil, nil, errStr
					}
					storeValue(f, floatVal)
				} else {
					resolved, errStr := resolveAtPrefix(f.Name, raw, stdinConsumedBy)
					if errStr != "" {
						return nil, nil, errStr
					}
					storeValue(f, resolved)
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
				} else if f.Type == TypeFloat {
					floatVal, errStr := parseFloatStrict(f.Name, raw)
					if errStr != "" {
						return nil, nil, errStr
					}
					storeValue(f, floatVal)
				} else {
					resolved, errStr := resolveAtPrefix(f.Name, raw, stdinConsumedBy)
					if errStr != "" {
						return nil, nil, errStr
					}
					storeValue(f, resolved)
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
		case TypeFloat:
			floatVal, errStr := parseFloatStrict(f.Name, envVal)
			if errStr != "" {
				return nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
			}
			if f.Repeatable {
				cliSet[f.Name] = []interface{}{floatVal}
			} else {
				cliSet[f.Name] = floatVal
			}
		default: // TypeStr
			resolved, errStr := resolveAtPrefix(f.Name, envVal, stdinConsumedBy)
			if errStr != "" {
				return nil, nil, errStr
			}
			if f.Repeatable {
				cliSet[f.Name] = []interface{}{resolved}
			} else {
				cliSet[f.Name] = resolved
			}
		}
	}

	// Resolve config values for flags not set by CLI or env
	if configData != nil {
		for i := range cmd.Flags {
			f := &cmd.Flags[i]
			if _, ok := cliSet[f.Name]; ok {
				continue
			}
			param := flagParamName(f.Name)
			if v, ok := configData[param]; ok {
				coerced, errStr := coerceConfigValue(v, f)
				if errStr != "" {
					return nil, nil, fmt.Sprintf("--%s: config value error: %s", f.Name, errStr)
				}
				cliSet[f.Name] = coerced
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

	// Resolve Implies dependencies (before general dependency validation)
	for _, dep := range cmd.Dependencies {
		if d, ok := dep.(Implies); ok {
			if _, triggerSet := cliSet[d.Flag]; triggerSet {
				if targetVal, targetSet := cliSet[d.Implies]; targetSet {
					// Target was explicitly set -- check for conflict
					if targetVal.(bool) != d.Value {
						neg := ""
						if !d.Value {
							neg = "no-"
						}
						explicitNeg := ""
						if d.Value {
							explicitNeg = "no-"
						}
						return nil, nil, fmt.Sprintf(
							"flag '--%s' implies '--%s%s', but '--%s%s' was explicitly provided",
							d.Flag, neg, d.Implies, explicitNeg, d.Implies,
						)
					}
				} else {
					// Target not set -- inject the implied value
					cliSet[d.Implies] = d.Value
				}
			}
		}
	}

	// Enforce dependency constraints
	for _, dep := range cmd.Dependencies {
		switch d := dep.(type) {
		case CoRequired:
			var setFlags []string
			var unsetFlags []string
			for _, flagName := range d.Flags {
				if _, ok := cliSet[flagName]; ok {
					setFlags = append(setFlags, "--"+flagName)
				} else {
					unsetFlags = append(unsetFlags, "--"+flagName)
				}
			}
			if len(setFlags) > 0 && len(unsetFlags) > 0 {
				names := make([]string, len(d.Flags))
				for j, flagName := range d.Flags {
					names[j] = "--" + flagName
				}
				return nil, nil, fmt.Sprintf("flags %s must be used together", strings.Join(names, ", "))
			}
		case Requires:
			if _, flagSet := cliSet[d.Flag]; flagSet {
				if _, depSet := cliSet[d.DependsOn]; !depSet {
					return nil, nil, fmt.Sprintf("flag '--%s' requires '--%s'", d.Flag, d.DependsOn)
				}
			}
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

// parseFloatStrict parses a string as float64 with strict validation:
// rejects leading/trailing whitespace, NaN, and +/-Inf.
func parseFloatStrict(flagName, raw string) (interface{}, string) {
	if raw != strings.TrimSpace(raw) {
		return nil, fmt.Sprintf("--%s: expected float, got '%s'", flagName, raw)
	}
	floatVal, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return nil, fmt.Sprintf("--%s: expected float, got '%s'", flagName, raw)
	}
	if math.IsNaN(floatVal) {
		return nil, fmt.Sprintf("--%s: NaN is not allowed", flagName)
	}
	if math.IsInf(floatVal, 0) {
		return nil, fmt.Sprintf("--%s: Inf is not allowed", flagName)
	}
	return floatVal, ""
}
