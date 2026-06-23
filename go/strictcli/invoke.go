package strictcli

import (
	"fmt"
	"strings"
)

// invokeResult holds the outcome of an invoke call.
type invokeResult struct {
	exitCode int
	err      string // non-empty if invocation failed
}

// paramToFlagName converts a parameter name like "dry_run" back to a flag name "dry-run".
// This is the reverse of flagParamName.
func paramToFlagName(param string) string {
	return strings.ReplaceAll(param, "_", "-")
}

// invoke executes a command programmatically by path and pre-typed kwargs,
// bypassing CLI parsing, env var resolution, and config loading. The caller
// provides fully-typed values for all non-defaultable parameters.
//
// commandPath uses dot-separated segments: "deploy", "dns.zone.create".
// kwargs keys use underscored parameter names (e.g., "dry_run", not "--dry-run").
//
// For passthrough commands, the special key "_args" must contain a []string
// of raw arguments to forward to the handler.
func (a *App) invoke(commandPath string, kwargs map[string]interface{}) invokeResult {
	// Validate registrations
	if errMsg := a.validateCheckRegistrations(); errMsg != "" {
		return invokeResult{exitCode: 1, err: errMsg}
	}
	if errMsg := a.validateTagContracts(); errMsg != "" {
		return invokeResult{exitCode: 1, err: errMsg}
	}

	// Split command path into route segments
	segments := strings.Split(commandPath, ".")

	// Resolve the command
	route := a.resolveCommand(segments)
	if route.err != "" {
		return invokeResult{exitCode: 1, err: route.err}
	}
	if route.cmd == nil {
		return invokeResult{exitCode: 1, err: "no command resolved from path: " + commandPath}
	}

	cmd := route.cmd

	// Handle passthrough commands
	if cmd.Passthrough {
		var args []string
		if rawArgs, ok := kwargs["_args"]; ok {
			if typedArgs, ok := rawArgs.([]string); ok {
				args = typedArgs
			} else {
				return invokeResult{exitCode: 1, err: "passthrough command: _args must be []string"}
			}
		}

		// Build set of known global flag param names
		globalParamNames := make(map[string]bool)
		for _, gf := range a.globalFlags {
			globalParamNames[flagParamName(gf.Name)] = true
		}

		// Validate that all kwargs keys are either "_args" or known global flags
		for key := range kwargs {
			if key == "_args" {
				continue
			}
			if !globalParamNames[key] {
				return invokeResult{exitCode: 1, err: fmt.Sprintf("unknown parameter %q for passthrough command %q", key, commandPath)}
			}
		}

		// Build global kwargs from the remaining kwargs entries
		globalKwargs := make(map[string]interface{})
		for _, gf := range a.globalFlags {
			paramName := flagParamName(gf.Name)
			if v, ok := kwargs[paramName]; ok {
				globalKwargs[paramName] = v
			} else if gf.Type == TypeBool {
				globalKwargs[paramName] = gf.Default
			} else if gf.hasDefault {
				globalKwargs[paramName] = gf.Default
			} else {
				// Required global flag not provided
				return invokeResult{exitCode: 1, err: fmt.Sprintf("global flag '--%s' is required", gf.Name)}
			}
		}
		code := cmd.PassthroughHandler(cmd.Name, args, globalKwargs)
		return invokeResult{exitCode: code}
	}

	// Build reverse mapping: flag name (with dashes) -> flag definition
	flagByName := make(map[string]*Flag)
	for i := range cmd.flags {
		flagByName[cmd.flags[i].Name] = &cmd.flags[i]
	}

	// Build global flag name set and global flag lookup
	globalFlagNames := make(map[string]bool)
	globalFlagByName := make(map[string]*Flag)
	for i := range a.globalFlags {
		globalFlagNames[a.globalFlags[i].Name] = true
		globalFlagByName[a.globalFlags[i].Name] = &a.globalFlags[i]
	}

	// Build arg name set for separating positional args from flags
	argNames := make(map[string]bool)
	for _, arg := range cmd.args {
		argNames[arg.Name] = true
	}

	// Populate cliSet from kwargs, mapping param names back to flag names
	cliSet := make(map[string]interface{})
	var positionals []string

	for paramName, value := range kwargs {
		flagName := paramToFlagName(paramName)

		// Check if it's a command flag
		if _, ok := flagByName[flagName]; ok {
			cliSet[flagName] = value
			continue
		}

		// Check if it's a global flag
		if globalFlagNames[flagName] {
			cliSet[flagName] = value
			continue
		}

		// Check if it's a positional arg -- will be handled after this loop
		if argNames[paramName] {
			continue
		}

		return invokeResult{
			exitCode: 1,
			err:      fmt.Sprintf("unknown parameter %q for command %q", paramName, commandPath),
		}
	}

	// Build positionals list from kwargs in arg declaration order
	for _, arg := range cmd.args {
		val, ok := kwargs[arg.Name]
		if !ok {
			continue
		}
		if arg.IsVariadic {
			// Variadic args: value should be []string or []interface{}
			switch v := val.(type) {
			case []string:
				for _, s := range v {
					positionals = append(positionals, s)
				}
			case []interface{}:
				for _, item := range v {
					if s, ok := item.(string); ok {
						positionals = append(positionals, s)
					} else {
						positionals = append(positionals, fmt.Sprintf("%v", item))
					}
				}
			default:
				positionals = append(positionals, fmt.Sprintf("%v", val))
			}
		} else {
			if s, ok := val.(string); ok {
				positionals = append(positionals, s)
			} else {
				positionals = append(positionals, fmt.Sprintf("%v", val))
			}
		}
	}

	// Run validation and build final kwargs
	validatedKwargs, postGlobalValues, errStr := validateAndBuildKwargs(cmd, cliSet, positionals, globalFlagNames)
	if errStr != "" {
		return invokeResult{exitCode: 1, err: errStr}
	}

	// Merge global values into kwargs (same as doParse)
	for k, v := range postGlobalValues {
		validatedKwargs[k] = v
	}

	// Apply global flag defaults for globals not provided in kwargs
	for i := range a.globalFlags {
		gf := &a.globalFlags[i]
		paramName := flagParamName(gf.Name)
		if _, ok := validatedKwargs[paramName]; ok {
			continue
		}
		// Use value from cliSet if provided
		if v, ok := cliSet[gf.Name]; ok {
			validatedKwargs[paramName] = v
			continue
		}
		// Apply defaults
		if gf.Repeatable {
			if gf.hasDefault && gf.Default != nil {
				src := gf.Default.([]interface{})
				validatedKwargs[paramName] = append([]interface{}{}, src...)
			} else {
				validatedKwargs[paramName] = []interface{}{}
			}
		} else if gf.Type == TypeBool {
			if gf.hasDefault {
				validatedKwargs[paramName] = gf.Default
			} else {
				validatedKwargs[paramName] = false
			}
		} else if gf.hasDefault && gf.Default != nil {
			validatedKwargs[paramName] = gf.Default
		} else if gf.hasDefault {
			validatedKwargs[paramName] = nil
		} else {
			// Required global flag not provided
			return invokeResult{exitCode: 1, err: fmt.Sprintf("global flag '--%s' is required", gf.Name)}
		}
	}

	// Call the handler
	code := cmd.Handler(validatedKwargs)
	return invokeResult{exitCode: code}
}
