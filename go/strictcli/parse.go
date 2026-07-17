package strictcli

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"reflect"
	"sort"
	"strconv"
	"strings"
)

// Source represents where a flag value came from.
type Source int

const (
	SourceCLI     Source = iota // explicitly passed on the command line
	SourceEnv     Source = iota // from an environment variable
	SourceConfig  Source = iota // from a config file
	SourceDefault Source = iota // from the flag's default value
	SourceImplied Source = iota // injected by an Implies dependency
	SourceInfra   Source = iota // default resolved through a RelativeToRoot infra root
)

// sourceLabelString maps a Source to its provenance label string.
func sourceLabelString(src Source) string {
	switch src {
	case SourceCLI:
		return "cli"
	case SourceEnv:
		return "env"
	case SourceConfig:
		return "config"
	case SourceDefault:
		return "default"
	case SourceImplied:
		return "implied"
	case SourceInfra:
		return "infra"
	}
	return "default"
}

// sourcedEntry stores a value alongside its provenance.
type sourcedEntry struct {
	value  interface{}
	source Source
}

// sourcedStore wraps a map of flag-name to sourcedEntry, providing
// source-filtered presence queries for mutex and dependency evaluation.
type sourcedStore struct {
	entries map[string]sourcedEntry
}

func newSourcedStore() *sourcedStore {
	return &sourcedStore{entries: make(map[string]sourcedEntry)}
}

// set stores a value with its source.
func (s *sourcedStore) set(name string, value interface{}, src Source) {
	s.entries[name] = sourcedEntry{value: value, source: src}
}

// get returns the value and whether the key exists (ignoring source).
func (s *sourcedStore) get(name string) (interface{}, bool) {
	e, ok := s.entries[name]
	if !ok {
		return nil, false
	}
	return e.value, true
}

// getEntry returns the full sourcedEntry and whether the key exists.
func (s *sourcedStore) getEntry(name string) (sourcedEntry, bool) {
	e, ok := s.entries[name]
	return e, ok
}

// has returns true if the key exists regardless of source.
func (s *sourcedStore) has(name string) bool {
	_, ok := s.entries[name]
	return ok
}

// isPresentForMutex returns true if the flag is "present" for mutex
// evaluation. Only cli, env, and config sources count. Default and
// implied values do NOT trigger mutex violations.
func (s *sourcedStore) isPresentForMutex(name string) bool {
	e, ok := s.entries[name]
	if !ok {
		return false
	}
	return e.source == SourceCLI || e.source == SourceEnv || e.source == SourceConfig
}

// isPresentForDeps returns true if the flag is "present" for dependency
// checks (CoRequired, Requires). CLI, env, config, and implied sources
// count. Default values do NOT count.
func (s *sourcedStore) isPresentForDeps(name string) bool {
	e, ok := s.entries[name]
	if !ok {
		return false
	}
	return e.source != SourceDefault
}

// toMap returns a plain map of name -> value (dropping source info).
func (s *sourcedStore) toMap() map[string]interface{} {
	m := make(map[string]interface{}, len(s.entries))
	for k, e := range s.entries {
		m[k] = e.value
	}
	return m
}

// sourceMap returns a map of flag name -> source label string.
func (s *sourcedStore) sourceMap() map[string]string {
	m := make(map[string]string, len(s.entries))
	for k, e := range s.entries {
		m[k] = sourceLabelString(e.source)
	}
	return m
}

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
// conflictMode is "cli-wins" (default) or "error" (config+cli/env overlap is an error).
// When hermetic is true, env var and config resolution are skipped entirely.
// Returns (kwargs, postGlobalValues, sources, errorString).
func parseCommand(cmd *Command, tokens []string, globalFlags []Flag, configData map[string]interface{}, stdinConsumedBy **string, conflictMode string, hermetic bool, infraRoots map[string]string) (map[string]interface{}, map[string]interface{}, map[string]string, string) {
	// Build flag lookup maps
	longLookup := make(map[string]*Flag)    // --flag-name -> Flag
	shortLookup := make(map[string]*Flag)   // -x -> Flag
	negationLookup := make(map[string]*Flag) // --no-flag-name -> Flag

	for i := range cmd.flags {
		f := &cmd.flags[i]
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

	storeValue := func(f *Flag, value interface{}) string {
		if f.Repeatable {
			if existing, ok := cliSet[f.Name]; ok {
				cliSet[f.Name] = append(existing.([]interface{}), value)
			} else {
				cliSet[f.Name] = []interface{}{value}
			}
			if f.Unique {
				if dup := findDuplicate(cliSet[f.Name].([]interface{})); dup != nil {
					return fmt.Sprintf("--%s: duplicate value '%s'", f.Name, formatValueForError(dup))
				}
			}
		} else {
			cliSet[f.Name] = value
		}
		return ""
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
					return nil, nil, nil, fmt.Sprintf("flag '%s' is a boolean flag and does not take a value", flagPart)
				}
				if errStr := parseFlagRawValue(f, valuePart, cliSet, stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, nil, errStr
				}
			} else if _, ok := negationLookup[flagPart]; ok {
				return nil, nil, nil, fmt.Sprintf("flag '%s' is a boolean negation and does not take a value", flagPart)
			} else {
				return nil, nil, nil, fmt.Sprintf("unknown flag '%s'", flagPart)
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
				return nil, nil, nil, fmt.Sprintf("unknown flag '%s'", tok)
			}
			if f.Type == TypeBool {
				cliSet[f.Name] = true
				i++
			} else {
				if i+1 >= len(tokens) {
					return nil, nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				raw := tokens[i+1]
				if errStr := parseFlagRawValue(f, raw, cliSet, stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, nil, errStr
				}
				i += 2
			}
			continue
		}

		// -x (short form)
		if strings.HasPrefix(tok, "-") && len(tok) == 2 {
			if f, ok := shortLookup[tok]; ok {
				if f.Type == TypeBool {
					cliSet[f.Name] = true
					i++
				} else {
					if i+1 >= len(tokens) {
						return nil, nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
					}
					raw := tokens[i+1]
					if errStr := parseFlagRawValue(f, raw, cliSet, stdinConsumedBy, storeValue); errStr != "" {
						return nil, nil, nil, errStr
					}
					i += 2
				}
				continue
			}
		}

		// Token starts with "-" but doesn't match any known flag;
		// treat as a positional arg (e.g. negative numbers like -7, -3.14)
		positionals = append(positionals, tok)
		i++
	}

	// Track which flag names are set by env vs config (for source attribution).
	envNames := make(map[string]bool)
	configNames := make(map[string]bool)

	// Resolve env vars for flags not set by CLI (skipped under --hermetic)
	if !hermetic {
	for i := range cmd.flags {
		f := &cmd.flags[i]
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
		// Compound types: dict parses JSON from env, list uses env_separator
		if IsDictType(f.Type) {
			entries, errStr := parseDictEnvValue(f.Name, envVal, ItemType(f.Type))
			if errStr != "" {
				return nil, nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
			}
			cliSet[f.Name] = entries
			envNames[f.Name] = true
			continue
		}
		if IsListType(f.Type) {
			if f.EnvSeparator == "" {
				return nil, nil, nil, fmt.Sprintf("--%s: list flag with env requires env_separator", f.Name)
			}
			parts := splitEscaped(envVal, f.EnvSeparator[0])
			elemType := ItemType(f.Type)
			coercedList := make([]interface{}, 0, len(parts))
			for _, element := range parts {
				val, errStr := coerceToScalar(f.Name, element, elemType, nil)
				if errStr != "" {
					return nil, nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
				}
				coercedList = append(coercedList, val)
			}
			if f.Unique {
				if dup := findDuplicate(coercedList); dup != nil {
					return nil, nil, nil, fmt.Sprintf(
						"--%s: duplicate value '%s' (from env var '%s')",
						f.Name, formatValueForError(dup), f.Env,
					)
				}
			}
			cliSet[f.Name] = coercedList
			envNames[f.Name] = true
			continue
		}
		switch f.Type {
		case TypeBool:
			boolVal, err := parseBoolStrict(envVal)
			if err != nil {
				return nil, nil, nil, fmt.Sprintf(
					"invalid boolean value '%s' for env var '%s' (flag '--%s')",
					envVal, f.Env, f.Name,
				)
			}
			cliSet[f.Name] = boolVal
		case TypeInt:
			if f.Repeatable && f.EnvSeparator != "" {
				parts := splitEscaped(envVal, f.EnvSeparator[0])
				coercedList := make([]interface{}, 0, len(parts))
				for _, element := range parts {
					intVal, err := parseIntStrict(element)
					if err != nil {
						return nil, nil, nil, fmt.Sprintf(
							"--%s: %s (from env var '%s')",
							f.Name, err.Error(), f.Env,
						)
					}
					coercedList = append(coercedList, intVal)
				}
				if f.Unique {
					if dup := findDuplicate(coercedList); dup != nil {
						return nil, nil, nil, fmt.Sprintf(
							"--%s: duplicate value '%s' (from env var '%s')",
							f.Name, formatValueForError(dup), f.Env,
						)
					}
				}
				cliSet[f.Name] = coercedList
			} else {
				intVal, err := parseIntStrict(envVal)
				if err != nil {
					return nil, nil, nil, fmt.Sprintf(
						"--%s: %s (from env var '%s')",
						f.Name, err.Error(), f.Env,
					)
				}
				if f.Repeatable {
					cliSet[f.Name] = []interface{}{intVal}
				} else {
					cliSet[f.Name] = intVal
				}
			}
		case TypeFloat:
			if f.Repeatable && f.EnvSeparator != "" {
				parts := splitEscaped(envVal, f.EnvSeparator[0])
				coercedList := make([]interface{}, 0, len(parts))
				for _, element := range parts {
					floatVal, errStr := parseFloatStrict(f.Name, element)
					if errStr != "" {
						return nil, nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
					}
					coercedList = append(coercedList, floatVal)
				}
				if f.Unique {
					if dup := findDuplicate(coercedList); dup != nil {
						return nil, nil, nil, fmt.Sprintf(
							"--%s: duplicate value '%s' (from env var '%s')",
							f.Name, formatValueForError(dup), f.Env,
						)
					}
				}
				cliSet[f.Name] = coercedList
			} else {
				floatVal, errStr := parseFloatStrict(f.Name, envVal)
				if errStr != "" {
					return nil, nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
				}
				if f.Repeatable {
					cliSet[f.Name] = []interface{}{floatVal}
				} else {
					cliSet[f.Name] = floatVal
				}
			}
		default: // TypeStr
			if f.Repeatable && f.EnvSeparator != "" {
				parts := splitEscaped(envVal, f.EnvSeparator[0])
				coercedList := make([]interface{}, 0, len(parts))
				for _, element := range parts {
					resolved, errStr := resolveAtPrefix(f.Name, element, stdinConsumedBy)
					if errStr != "" {
						return nil, nil, nil, errStr
					}
					coercedList = append(coercedList, resolved)
				}
				if f.Unique {
					if dup := findDuplicate(coercedList); dup != nil {
						return nil, nil, nil, fmt.Sprintf(
							"--%s: duplicate value '%s' (from env var '%s')",
							f.Name, formatValueForError(dup), f.Env,
						)
					}
				}
				cliSet[f.Name] = coercedList
			} else {
				resolved, errStr := resolveAtPrefix(f.Name, envVal, stdinConsumedBy)
				if errStr != "" {
					return nil, nil, nil, errStr
				}
				if f.Repeatable {
					cliSet[f.Name] = []interface{}{resolved}
				} else {
					cliSet[f.Name] = resolved
				}
			}
		}
		envNames[f.Name] = true
	}

	// Resolve config values for flags not set by CLI or env.
	// In conflict mode "error", detect when config would set a flag
	// already set by CLI or env.
	if configData != nil {
		for i := range cmd.flags {
			f := &cmd.flags[i]
			param := flagParamName(f.Name)
			configVal, hasConfig := configData[param]
			if !hasConfig {
				continue
			}
			// Effective mode: per-flag override if set, else the app default.
			effectiveMode := conflictMode
			if f.hasConflictMode {
				effectiveMode = f.ConflictMode
			}
			if existing, alreadySet := cliSet[f.Name]; alreadySet {
				// Flag set by CLI or env, config also has a value. This is a
				// conflict ONLY when the values diverge; identical values agree.
				if effectiveMode == "error" {
					coerced, errStr := coerceConfigValue(configVal, f)
					if errStr != "" {
						return nil, nil, nil, fmt.Sprintf("--%s: config value error: %s", f.Name, errStr)
					}
					if !valuesEqualForConflict(existing, coerced, f) {
						existingSource := "cli"
						if envNames[f.Name] {
							existingSource = "env"
						}
						return nil, nil, nil, fmt.Sprintf(
							"flag '%s' set in both %s and config; remove one",
							f.Name, existingSource,
						)
					}
				}
				continue // cli-wins, or error mode with matching values
			}
			coerced, errStr := coerceConfigValue(configVal, f)
			if errStr != "" {
				return nil, nil, nil, fmt.Sprintf("--%s: config value error: %s", f.Name, errStr)
			}
			if f.Unique {
				if arr, ok := coerced.([]interface{}); ok {
					if dup := findDuplicate(arr); dup != nil {
						return nil, nil, nil, fmt.Sprintf("--%s: config value error: duplicate value '%s'", f.Name, formatValueForError(dup))
					}
				}
			}
			cliSet[f.Name] = coerced
			configNames[f.Name] = true
		}

		// Config-conflict detection for GLOBAL flags parsed AFTER the command
		// name (`tool cmd --global X`). This is CONFLICT-DETECTION ONLY: config
		// values for globals were already APPLIED during the pre-command
		// global-flag pass (extractGlobalFlags), so applying them again here
		// would be a second application site -- wrong even if idempotent. We
		// must never write a config value into cliSet for a global here.
		// Globals that reach cliSet at this point are purely CLI-parsed
		// (post-command env for globals is never resolved here), so the
		// divergence source is always "cli".
		for i := range globalFlags {
			f := &globalFlags[i]
			existing, alreadySet := cliSet[f.Name]
			if !alreadySet {
				continue
			}
			param := flagParamName(f.Name)
			configVal, hasConfig := configData[param]
			if !hasConfig {
				continue
			}
			effectiveMode := conflictMode
			if f.hasConflictMode {
				effectiveMode = f.ConflictMode
			}
			if effectiveMode != "error" {
				continue
			}
			coerced, errStr := coerceConfigValue(configVal, f)
			if errStr != "" {
				return nil, nil, nil, fmt.Sprintf("--%s: config value error: %s", f.Name, errStr)
			}
			if !valuesEqualForConflict(existing, coerced, f) {
				return nil, nil, nil, fmt.Sprintf(
					"flag '%s' set in both cli and config; remove one", f.Name,
				)
			}
		}
	}
	} // end if !hermetic

	// Wrap cliSet into a sourcedStore with proper source attribution.
	// CLI-parsed values are SourceCLI, env-resolved values are SourceEnv,
	// and config-resolved values are SourceConfig.
	store := newSourcedStore()
	for k, v := range cliSet {
		if envNames[k] {
			store.set(k, v, SourceEnv)
		} else if configNames[k] {
			store.set(k, v, SourceConfig)
		} else {
			store.set(k, v, SourceCLI)
		}
	}

	return validateAndBuildKwargs(cmd, store, positionals, globalFlagNames, infraRoots)
}

// applyFlagDefault resolves the default value for a flag that was not provided
// on the command line. Returns (value, errorMsg). If errorMsg is non-empty, the
// flag is required and was not provided. The prefix is prepended to error
// messages (e.g. "global " for global flags, "" for command flags).
func applyFlagDefault(f *Flag, mutexFlagNames map[string]bool, prefix string, roots map[string]string) (interface{}, Source, string) {
	if IsDictType(f.Type) {
		if f.hasDefault && f.Default != nil {
			src := f.Default.(map[string]interface{})
			m := make(map[string]interface{}, len(src))
			for k, v := range src {
				m[k] = v
			}
			return m, SourceDefault, ""
		}
		return map[string]interface{}{}, SourceDefault, ""
	}
	if f.Repeatable {
		if f.hasDefault && f.Default != nil {
			src := f.Default.([]interface{})
			return append([]interface{}{}, src...), SourceDefault, ""
		}
		return []interface{}{}, SourceDefault, ""
	}
	if f.hasDefault && f.Default != nil {
		// A RelativeToRoot marker resolves through the declared infra roots and
		// reports source "infra" (distinguishable from a plain default).
		if ref, ok := f.Default.(InfraRootPath); ok {
			resolved, err := resolveInfraRootPath(ref, roots)
			if err != nil {
				// Should be unreachable: markers are validated at registration.
				return nil, SourceDefault, fmt.Sprintf("%s%s", prefix, err.Error())
			}
			return resolved, SourceInfra, ""
		}
		return f.Default, SourceDefault, ""
	}
	if f.hasDefault && f.Default == nil {
		return nil, SourceDefault, ""
	}
	if mutexFlagNames != nil && mutexFlagNames[f.Name] {
		return nil, SourceDefault, ""
	}
	if f.Type == TypeBool && f.Negatable {
		return nil, SourceDefault, fmt.Sprintf("%sflag '--%s' must be passed as --%s or --no-%s", prefix, f.Name, f.Name, f.Name)
	}
	if f.Type == TypeBool && !f.Negatable {
		return nil, SourceDefault, fmt.Sprintf("%sflag '--%s' must be passed as --%s", prefix, f.Name, f.Name)
	}
	return nil, SourceDefault, fmt.Sprintf("%sflag '--%s' is required", prefix, f.Name)
}

// validateAndBuildKwargs performs pure validation and kwargs assembly on the
// already-parsed sourced values. It enforces mutex constraints (using
// source-filtered presence), resolves implies dependencies, checks
// co-required/requires dependencies, applies defaults, validates choices,
// runs custom validation, resolves positional args, and builds the final
// kwargs map.
// Returns (kwargs, postGlobalValues, errorString).
func validateAndBuildKwargs(cmd *Command, store *sourcedStore, positionals []string, globalFlagNames map[string]bool, infraRoots map[string]string) (map[string]interface{}, map[string]interface{}, map[string]string, string) {
	// Enforce mutex group constraints (before defaults).
	// Only cli/env/config sources count as "present" for mutex evaluation.
	// Default and implied sources do NOT trigger mutex violations.
	for _, mg := range cmd.mutex {
		var setFlags []string
		for _, f := range mg.Flags {
			if store.isPresentForMutex(f.Name) {
				setFlags = append(setFlags, "--"+f.Name)
			}
		}
		if len(setFlags) > 1 {
			return nil, nil, nil, fmt.Sprintf("%s are mutually exclusive", strings.Join(setFlags, " and "))
		}
		if len(setFlags) == 0 {
			names := make([]string, len(mg.Flags))
			for j, f := range mg.Flags {
				names[j] = "--" + f.Name
			}
			return nil, nil, nil, fmt.Sprintf("one of %s is required", strings.Join(names, ", "))
		}
	}

	// Resolve Implies dependencies (before general dependency validation).
	// Implied values are stored with SourceImplied.
	for _, dep := range cmd.dependencies {
		if d, ok := dep.(Implies); ok {
			if store.isPresentForDeps(d.Flag) {
				if targetVal, targetSet := store.get(d.Implies); targetSet {
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
						return nil, nil, nil, fmt.Sprintf(
							"flag '--%s' implies '--%s%s', but '--%s%s' was explicitly provided",
							d.Flag, neg, d.Implies, explicitNeg, d.Implies,
						)
					}
				} else {
					// Target not set -- inject the implied value
					store.set(d.Implies, d.Value, SourceImplied)
				}
			}
		}
	}

	// Enforce dependency constraints.
	// isPresentForDeps: cli, env, config, implied count. Default does NOT.
	for _, dep := range cmd.dependencies {
		switch d := dep.(type) {
		case CoRequired:
			var setFlags []string
			var unsetFlags []string
			for _, flagName := range d.Flags {
				if store.isPresentForDeps(flagName) {
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
				return nil, nil, nil, fmt.Sprintf("flags %s must be used together", strings.Join(names, ", "))
			}
		case Requires:
			if store.isPresentForDeps(d.Flag) {
				if !store.isPresentForDeps(d.DependsOn) {
					return nil, nil, nil, fmt.Sprintf("flag '--%s' requires '--%s'", d.Flag, d.DependsOn)
				}
			}
		}
	}

	// Build set of flag names belonging to mutex groups
	mutexFlagNames := make(map[string]bool)
	for _, mg := range cmd.mutex {
		for _, f := range mg.Flags {
			mutexFlagNames[f.Name] = true
		}
	}

	// Apply defaults (SourceDefault)
	for i := range cmd.flags {
		f := &cmd.flags[i]
		if store.has(f.Name) {
			continue
		}
		val, src, errMsg := applyFlagDefault(f, mutexFlagNames, "", infraRoots)
		if errMsg != "" {
			return nil, nil, nil, errMsg
		}
		store.set(f.Name, val, src)
	}

	// Validate choices
	for i := range cmd.flags {
		f := &cmd.flags[i]
		val, ok := store.get(f.Name)
		if !ok {
			continue
		}
		if errMsg := validateChoices(f.Name, val, f.Repeatable, f.Choices, false); errMsg != "" {
			return nil, nil, nil, errMsg
		}
	}

	// Custom validation
	for i := range cmd.flags {
		f := &cmd.flags[i]
		if f.Validate == nil {
			continue
		}
		val, ok := store.get(f.Name)
		if !ok || val == nil {
			// nil means the flag was not passed (Default(nil) or an unset
			// mutex flag) -- there is no value to validate.
			continue
		}
		if f.Repeatable {
			vals, ok := val.([]interface{})
			if !ok {
				continue
			}
			for _, v := range vals {
				if err := f.Validate(v); err != nil {
					return nil, nil, nil, fmt.Sprintf("--%s: %s", f.Name, err.Error())
				}
			}
		} else {
			if err := f.Validate(val); err != nil {
				return nil, nil, nil, fmt.Sprintf("--%s: %s", f.Name, err.Error())
			}
		}
	}

	// Resolve positional args
	argValues := make(map[string]interface{})
	posIdx := 0
	for i := range cmd.args {
		a := &cmd.args[i]
		if a.IsVariadic {
			// Collect all remaining positionals
			remaining := positionals[posIdx:]
			if len(remaining) == 0 {
				if a.Required {
					return nil, nil, nil, fmt.Sprintf("missing required argument '%s'", a.Name)
				}
				// Optional variadic with no values: empty list
				argValues[a.Name] = []interface{}{}
			} else {
				vals := make([]interface{}, len(remaining))
				for j, v := range remaining {
					coerced, errStr := coerceArgValue(a, v)
					if errStr != "" {
						return nil, nil, nil, errStr
					}
					vals[j] = coerced
				}
				argValues[a.Name] = vals
			}
			posIdx = len(positionals)
		} else if posIdx < len(positionals) {
			coerced, errStr := coerceArgValue(a, positionals[posIdx])
			if errStr != "" {
				return nil, nil, nil, errStr
			}
			argValues[a.Name] = coerced
			posIdx++
		} else if a.Required {
			return nil, nil, nil, fmt.Sprintf("missing required argument '%s'", a.Name)
		} else if a.hasDefault {
			argValues[a.Name] = a.Default
		} else {
			// Optional arg with no default: nil (printed as "None" for conformance)
			argValues[a.Name] = nil
		}
	}
	if posIdx < len(positionals) {
		return nil, nil, nil, fmt.Sprintf("unexpected argument '%s'", positionals[posIdx])
	}

	// Validate arg choices (after type coercion)
	for i := range cmd.args {
		a := &cmd.args[i]
		val, ok := argValues[a.Name]
		if !ok {
			continue
		}
		if errMsg := validateChoices(a.Name, val, a.IsVariadic, a.Choices, true); errMsg != "" {
			return nil, nil, nil, errMsg
		}
	}

	// Build kwargs dict (command flags only)
	kwargs := make(map[string]interface{})
	for i := range cmd.flags {
		f := &cmd.flags[i]
		if val, ok := store.get(f.Name); ok {
			kwargs[flagParamName(f.Name)] = val
		}
	}
	for _, a := range cmd.args {
		if v, ok := argValues[a.Name]; ok {
			kwargs[a.Name] = v
		}
	}

	// Separate out global flag values parsed from post-command tokens
	postGlobalValues := make(map[string]interface{})
	for name := range globalFlagNames {
		if val, ok := store.get(name); ok {
			postGlobalValues[flagParamName(name)] = val
		}
	}

	// Build source map: param-name -> source label (for Context.Source())
	rawSources := store.sourceMap()
	sources := make(map[string]string)
	for i := range cmd.flags {
		f := &cmd.flags[i]
		if s, ok := rawSources[f.Name]; ok {
			sources[flagParamName(f.Name)] = s
		}
	}
	// Global flags parsed post-command emit their source label too (always
	// "cli" here; env/config for globals resolve in the pre-command pass).
	// Without this, `tool cmd --global X` reports source "default" for it.
	for name := range globalFlagNames {
		if s, ok := rawSources[name]; ok {
			sources[flagParamName(name)] = s
		}
	}

	return kwargs, postGlobalValues, sources, ""
}

// validateChoices checks a resolved flag or arg value against its choices
// list, returning an error message or "" if valid. isArg selects the message
// prefix ("argument 'name':" instead of "--name:"); the two format strings
// are kept as full literals so conformance/check_error_parity.py can extract
// them. A nil val is exempt from validation: nil only arises from
// Default(nil)/ArgDefault(nil) or an unset mutex flag, all meaning "not
// passed" -- a CLI-supplied value is never nil.
func validateChoices(name string, val interface{}, repeatable bool, choices []interface{}, isArg bool) string {
	if choices == nil || val == nil {
		return ""
	}
	check := func(v interface{}) string {
		if inChoices(v, choices) {
			return ""
		}
		if isArg {
			return fmt.Sprintf(
				"argument '%s': invalid value '%v', must be one of: %s",
				name, formatValueForError(v), formatChoices(choices),
			)
		}
		return fmt.Sprintf(
			"--%s: invalid value '%v', must be one of: %s",
			name, formatValueForError(v), formatChoices(choices),
		)
	}
	if repeatable {
		vals, ok := val.([]interface{})
		if !ok {
			return ""
		}
		for _, v := range vals {
			if errMsg := check(v); errMsg != "" {
				return errMsg
			}
		}
		return ""
	}
	return check(val)
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
		parts[i] = formatValueForError(c)
	}
	return strings.Join(parts, ", ")
}

// parseBoolStrict parses a string as a boolean with strict validation.
// Accepts: 1, true, yes (case-insensitive) -> true
// Accepts: 0, false, no (case-insensitive) -> false
// Everything else returns an error.
func parseBoolStrict(s string) (bool, error) {
	switch strings.ToLower(s) {
	case "1", "true", "yes":
		return true, nil
	case "0", "false", "no":
		return false, nil
	default:
		return false, fmt.Errorf("expected boolean, got '%s'", s)
	}
}

// parseIntStrict parses a string as an integer with strict validation.
// Uses strconv.Atoi which rejects leading/trailing whitespace.
func parseIntStrict(s string) (int, error) {
	intVal, err := strconv.Atoi(s)
	if err != nil {
		return 0, fmt.Errorf("expected integer, got '%s'", s)
	}
	return intVal, nil
}

// parseFloatStrictValue parses a string as float64 with strict validation:
// rejects leading/trailing whitespace, NaN, and +/-Inf.
func parseFloatStrictValue(s string) (float64, error) {
	if s != strings.TrimSpace(s) {
		return 0, fmt.Errorf("expected float, got '%s'", s)
	}
	floatVal, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0, fmt.Errorf("expected float, got '%s'", s)
	}
	if math.IsNaN(floatVal) {
		return 0, fmt.Errorf("NaN is not allowed")
	}
	if math.IsInf(floatVal, 0) {
		return 0, fmt.Errorf("Inf is not allowed")
	}
	return floatVal, nil
}

// parseFloatStrict parses a string as float64 with strict validation,
// returning flag-contextualized error messages.
func parseFloatStrict(flagName, raw string) (interface{}, string) {
	floatVal, err := parseFloatStrictValue(raw)
	if err != nil {
		msg := err.Error()
		if msg == "NaN is not allowed" || msg == "Inf is not allowed" {
			return nil, fmt.Sprintf("--%s: %s", flagName, msg)
		}
		return nil, fmt.Sprintf("--%s: expected float, got '%s'", flagName, raw)
	}
	return floatVal, ""
}

// coerceArgValue coerces a raw positional arg string to the declared type.
// Uses the same strict parsing functions as flags. Error messages use
// "argument '<name>': ..." prefix for parity with Python.
// For list types, coerces using the item type.
func coerceArgValue(a *Arg, raw string) (interface{}, string) {
	t := a.Type
	// For list-typed variadic args, coerce each element to the item type
	if IsListType(t) {
		t = ItemType(t)
	}
	switch t {
	case TypeStr:
		return raw, ""
	case TypeInt:
		intVal, err := parseIntStrict(raw)
		if err != nil {
			return nil, fmt.Sprintf("argument '%s': %s", a.Name, err.Error())
		}
		return intVal, ""
	case TypeFloat:
		floatVal, err := parseFloatStrictValue(raw)
		if err != nil {
			msg := err.Error()
			if msg == "NaN is not allowed" || msg == "Inf is not allowed" {
				return nil, fmt.Sprintf("argument '%s': %s", a.Name, msg)
			}
			return nil, fmt.Sprintf("argument '%s': expected float, got '%s'", a.Name, raw)
		}
		return floatVal, ""
	case TypeBool:
		boolVal, err := parseBoolStrict(raw)
		if err != nil {
			return nil, fmt.Sprintf("argument '%s': %s", a.Name, err.Error())
		}
		return boolVal, ""
	default:
		return raw, ""
	}
}

// splitEscaped splits value on sep, treating backslash as escape character.
// Escaped sep becomes literal sep. Escaped backslash becomes literal backslash.
// Trailing backslash with nothing to escape becomes literal backslash.
func splitEscaped(value string, sep byte) []string {
	var parts []string
	var current []byte
	i := 0
	for i < len(value) {
		if value[i] == '\\' {
			if i+1 < len(value) {
				next := value[i+1]
				if next == sep {
					current = append(current, sep)
					i += 2
				} else if next == '\\' {
					current = append(current, '\\', '\\')
					i += 2
				} else {
					current = append(current, '\\', next)
					i += 2
				}
			} else {
				// Trailing backslash
				current = append(current, '\\', '\\')
				i++
			}
		} else if value[i] == sep {
			parts = append(parts, string(current))
			current = current[:0]
			i++
		} else {
			current = append(current, value[i])
			i++
		}
	}
	parts = append(parts, string(current))
	return parts
}

// valuesEqualForConflict compares a CLI/env value and a config value for
// conflict-mode equality. Equality semantics (pinned):
//   - scalars: exact equality.
//   - plain repeatable lists: order-sensitive exact equality.
//   - Unique flags: order-insensitive multiset equality.
//
// When the two values are equal, config+CLI/env co-presence is NOT a conflict.
func valuesEqualForConflict(cliVal, configVal interface{}, f *Flag) bool {
	if f.Unique {
		cliArr, ok1 := cliVal.([]interface{})
		cfgArr, ok2 := configVal.([]interface{})
		if ok1 && ok2 {
			return multisetEqual(cliArr, cfgArr)
		}
	}
	return reflect.DeepEqual(cliVal, configVal)
}

// multisetEqual reports whether two slices contain the same elements regardless
// of order (order-insensitive multiset comparison).
func multisetEqual(a, b []interface{}) bool {
	if len(a) != len(b) {
		return false
	}
	counts := make(map[string]int, len(a))
	for _, v := range a {
		counts[fmt.Sprintf("%T:%v", v, v)]++
	}
	for _, v := range b {
		counts[fmt.Sprintf("%T:%v", v, v)]--
	}
	for _, c := range counts {
		if c != 0 {
			return false
		}
	}
	return true
}

// findDuplicate returns the first duplicate value in the slice, or nil if all unique.
func findDuplicate(values []interface{}) interface{} {
	seen := make(map[interface{}]bool, len(values))
	for _, v := range values {
		if seen[v] {
			return v
		}
		seen[v] = true
	}
	return nil
}

// formatValueForError formats a value for inclusion in error messages (without quotes).
// Floats always include a decimal point. Bools are lowercase.
func formatValueForError(value interface{}) string {
	switch v := value.(type) {
	case bool:
		if v {
			return "true"
		}
		return "false"
	case float64:
		return formatFloatCanonical(v)
	case int:
		return strconv.Itoa(v)
	case string:
		return v
	case map[string]interface{}:
		return formatDictForDisplay(v)
	default:
		return fmt.Sprintf("%v", v)
	}
}

// formatDictForDisplay renders a dict flag value as canonical, deterministic
// text for errors and help: keys sorted ascending, each rendered as
// "key=value" (mirroring the CLI input syntax), values formatted via
// formatValueForError, joined by ", ". Go's fmt "%v" also sorts map keys, but
// its "map[k:v]" form is a Go-ism that does not match the input syntax; this
// makes the canonical form explicit and guaranteed stable.
func formatDictForDisplay(m map[string]interface{}) string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, len(keys))
	for i, k := range keys {
		parts[i] = k + "=" + formatValueForError(m[k])
	}
	return strings.Join(parts, ", ")
}

// coerceToScalar coerces a raw string to a scalar FlagType.
// For TypeStr, resolves @-prefix. For TypeInt/TypeFloat, does strict parsing.
// Returns (coerced value, error string).
func coerceToScalar(flagName, raw string, scalarType FlagType, stdinConsumedBy **string) (interface{}, string) {
	switch scalarType {
	case TypeInt:
		intVal, err := parseIntStrict(raw)
		if err != nil {
			return nil, fmt.Sprintf("--%s: %s", flagName, err.Error())
		}
		return intVal, ""
	case TypeFloat:
		return parseFloatStrict(flagName, raw)
	case TypeStr:
		if stdinConsumedBy != nil {
			return resolveAtPrefix(flagName, raw, stdinConsumedBy)
		}
		return raw, ""
	default:
		return raw, ""
	}
}

// parseDictValue parses a single dict flag value from the CLI.
// Accepts either "key=value" format or a JSON string starting with '{'.
// Returns (parsed map entries, error string).
func parseDictValue(flagName, raw string, valueType FlagType) (map[string]interface{}, string) {
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "{") {
		// JSON object input
		var jsonMap map[string]interface{}
		if err := json.Unmarshal([]byte(raw), &jsonMap); err != nil {
			return nil, fmt.Sprintf("--%s: invalid JSON: %s", flagName, err.Error())
		}
		// Coerce all values to the declared value type
		result := make(map[string]interface{}, len(jsonMap))
		for k, v := range jsonMap {
			coerced, errStr := coerceJSONValueToScalar(v, valueType)
			if errStr != "" {
				return nil, fmt.Sprintf("--%s: JSON key %q: %s", flagName, k, errStr)
			}
			result[k] = coerced
		}
		return result, ""
	}
	// key=value format: split on first '='
	eqIdx := strings.Index(raw, "=")
	if eqIdx < 0 {
		return nil, fmt.Sprintf("--%s: expected key=value, got '%s'", flagName, raw)
	}
	key := raw[:eqIdx]
	valStr := raw[eqIdx+1:]
	if key == "" {
		return nil, fmt.Sprintf("--%s: empty key in key=value pair", flagName)
	}
	// Coerce the value
	var coerced interface{}
	switch valueType {
	case TypeInt:
		intVal, err := parseIntStrict(valStr)
		if err != nil {
			return nil, fmt.Sprintf("--%s: value for key %q: %s", flagName, key, err.Error())
		}
		coerced = intVal
	case TypeFloat:
		floatVal, err := parseFloatStrictValue(valStr)
		if err != nil {
			return nil, fmt.Sprintf("--%s: value for key %q: %s", flagName, key, err.Error())
		}
		coerced = floatVal
	default:
		coerced = valStr
	}
	return map[string]interface{}{key: coerced}, ""
}

// parseDictEnvValue parses a JSON string from an env var for a dict flag.
// Returns (parsed map, error string).
func parseDictEnvValue(flagName, envVal string, valueType FlagType) (map[string]interface{}, string) {
	var jsonMap map[string]interface{}
	if err := json.Unmarshal([]byte(envVal), &jsonMap); err != nil {
		return nil, fmt.Sprintf("--%s: expected JSON object in env var, got invalid JSON", flagName)
	}
	result := make(map[string]interface{}, len(jsonMap))
	for k, v := range jsonMap {
		coerced, errStr := coerceJSONValueToScalar(v, valueType)
		if errStr != "" {
			return nil, fmt.Sprintf("--%s: env var JSON key %q: %s", flagName, k, errStr)
		}
		result[k] = coerced
	}
	return result, ""
}

// coerceJSONValueToScalar coerces a JSON-decoded value to a scalar FlagType.
// JSON numbers are float64 by default; this handles int coercion.
func coerceJSONValueToScalar(value interface{}, scalarType FlagType) (interface{}, string) {
	switch scalarType {
	case TypeStr:
		if s, ok := value.(string); ok {
			return s, ""
		}
		return nil, fmt.Sprintf("expected string, got %s", typeName(value))
	case TypeInt:
		if fv, ok := value.(float64); ok {
			intVal := int(fv)
			if float64(intVal) == fv {
				return intVal, ""
			}
			return nil, "expected integer, got float"
		}
		return nil, fmt.Sprintf("expected integer, got %s", typeName(value))
	case TypeFloat:
		if fv, ok := value.(float64); ok {
			return fv, ""
		}
		return nil, fmt.Sprintf("expected float, got %s", typeName(value))
	}
	return value, ""
}

// storeDictValue merges dict entries into the cliSet map for a dict flag.
// Returns an error string (empty on success).
func storeDictValue(cliSet map[string]interface{}, f *Flag, entries map[string]interface{}) string {
	if existing, ok := cliSet[f.Name]; ok {
		m := existing.(map[string]interface{})
		for k, v := range entries {
			m[k] = v
		}
	} else {
		m := make(map[string]interface{}, len(entries))
		for k, v := range entries {
			m[k] = v
		}
		cliSet[f.Name] = m
	}
	return ""
}

// parseFlagRawValue parses a raw string value for a flag, handling scalar,
// list, and dict types. For dict flags, it modifies cliSet directly.
// For scalar and list flags, it returns the coerced value via storeValue.
// Returns error string (empty on success).
func parseFlagRawValue(f *Flag, raw string, cliSet map[string]interface{}, stdinConsumedBy **string, storeValue func(*Flag, interface{}) string) string {
	if IsDictType(f.Type) {
		entries, errStr := parseDictValue(f.Name, raw, ItemType(f.Type))
		if errStr != "" {
			return errStr
		}
		return storeDictValue(cliSet, f, entries)
	}
	// For list flags, coerce using the item type
	scalarType := f.Type
	if IsListType(f.Type) {
		scalarType = ItemType(f.Type)
	}
	val, errStr := coerceToScalar(f.Name, raw, scalarType, stdinConsumedBy)
	if errStr != "" {
		return errStr
	}
	return storeValue(f, val)
}
