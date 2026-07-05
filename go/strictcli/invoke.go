package strictcli

import (
	"bytes"
	"fmt"
	"io"
	"strings"
)

// invokeResult holds the outcome of an invoke call.
type invokeResult struct {
	exitCode int
	data     interface{} // structured data from DataHandler (nil for regular handlers)
	err      string      // non-empty if invocation failed
}

// InvokeError is returned by App.Call() when invocation fails
// (unknown command, missing flags, mutex violations, etc.).
type InvokeError struct {
	Message string
}

func (e *InvokeError) Error() string {
	return e.Message
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
			} else {
				val, errMsg := applyFlagDefault(&gf, nil, "global ")
				if errMsg != "" {
					return invokeResult{exitCode: 1, err: errMsg}
				}
				globalKwargs[paramName] = val
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

	// Populate sourcedStore from kwargs, mapping param names back to flag names.
	// Provided kwargs are marked SourceCLI; absent flags will get SourceDefault
	// when validateAndBuildKwargs applies defaults.
	store := newSourcedStore()
	var positionals []string

	for paramName, value := range kwargs {
		flagName := paramToFlagName(paramName)

		// Check if it's a command flag
		if f, ok := flagByName[flagName]; ok {
			coerced, errStr := coerceInvokeValue(f, value)
			if errStr != "" {
				return invokeResult{exitCode: 1, err: errStr}
			}
			store.set(flagName, coerced, SourceCLI)
			continue
		}

		// Check if it's a global flag
		if globalFlagNames[flagName] {
			store.set(flagName, value, SourceCLI)
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
	validatedKwargs, postGlobalValues, errStr := validateAndBuildKwargs(cmd, store, positionals, globalFlagNames)
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
		// Use value from store if provided
		if v, ok := store.get(gf.Name); ok {
			validatedKwargs[paramName] = v
			continue
		}
		// Apply defaults
		val, errMsg := applyFlagDefault(gf, nil, "global ")
		if errMsg != "" {
			return invokeResult{exitCode: 1, err: errMsg}
		}
		validatedKwargs[paramName] = val
	}

	// Set dispatch context for struct handler wrappers
	var dc *dispatchCtx
	if cmd.handlerFactory != nil {
		// For invoke: stdout captures Emit output, stderr is discarded
		var buf bytes.Buffer
		dc = &dispatchCtx{
			stdout:  &buf,
			stderr:  io.Discard,
			globals: paramKwargsToFlagNames(validatedKwargs),
		}
		a.currentDispatch = dc
		defer func() { a.currentDispatch = nil }()
	}

	// Call the handler
	if cmd.dataHandler != nil {
		hr := cmd.dataHandler(validatedKwargs)
		return invokeResult{exitCode: hr.ExitCode, data: hr.Data}
	}
	code := cmd.Handler(validatedKwargs)

	// Capture emit data from struct handlers
	var data interface{}
	if dc != nil && dc.emitData != nil {
		data = dc.emitData
	}

	return invokeResult{exitCode: code, data: data}
}

// coerceInvokeValue converts a Go-native value to the internal representation
// expected by the parsing/validation pipeline. For compound types, this converts
// typed Go slices ([]int, []string, etc.) to []interface{}, and typed Go maps
// (map[string]int, etc.) to map[string]interface{}. For scalar types, the value
// is passed through as-is.
func coerceInvokeValue(f *Flag, value interface{}) (interface{}, string) {
	if IsDictType(f.Type) {
		return coerceInvokeDict(f, value)
	}
	if IsListType(f.Type) || f.Repeatable {
		return coerceInvokeList(f, value)
	}
	return value, ""
}

// coerceInvokeList converts various Go slice types to []interface{}.
func coerceInvokeList(f *Flag, value interface{}) (interface{}, string) {
	switch v := value.(type) {
	case []interface{}:
		return v, ""
	case []string:
		result := make([]interface{}, len(v))
		for i, s := range v {
			result[i] = s
		}
		return result, ""
	case []int:
		result := make([]interface{}, len(v))
		for i, n := range v {
			result[i] = n
		}
		return result, ""
	case []float64:
		result := make([]interface{}, len(v))
		for i, n := range v {
			result[i] = n
		}
		return result, ""
	default:
		return value, ""
	}
}

// coerceInvokeDict converts various Go map types to map[string]interface{}.
func coerceInvokeDict(f *Flag, value interface{}) (interface{}, string) {
	switch v := value.(type) {
	case map[string]interface{}:
		return v, ""
	case map[string]string:
		result := make(map[string]interface{}, len(v))
		for k, s := range v {
			result[k] = s
		}
		return result, ""
	case map[string]int:
		result := make(map[string]interface{}, len(v))
		for k, n := range v {
			result[k] = n
		}
		return result, ""
	case map[string]float64:
		result := make(map[string]interface{}, len(v))
		for k, n := range v {
			result[k] = n
		}
		return result, ""
	default:
		return nil, fmt.Sprintf("dict flag %q: expected map type, got %T", f.Name, value)
	}
}

// Call invokes a command programmatically and returns its result.
//
// Unlike invoke(), this is the public API. It returns an InvokeError for
// parse/validation errors instead of os.Exit, making it safe for
// programmatic use.
//
// commandPath uses dot-separated segments: "deploy", "dns.zone.create".
// kwargs keys use underscored parameter names (e.g., "dry_run", not "--dry-run").
//
// For passthrough commands, the special key "_args" must contain a []string
// of raw arguments to forward to the handler.
//
// Returns:
//   - For DataHandler commands: the HandlerResult.Data value
//   - For regular handlers: the exit code (int)
//   - For passthrough handlers: the exit code (int)
//
// Returns an InvokeError if invocation fails (unknown command, missing
// required flags, mutex violations, dependency errors, etc.).
func (a *App) Call(commandPath string, kwargs map[string]interface{}) (interface{}, error) {
	ir := a.invoke(commandPath, kwargs)
	if ir.err != "" {
		return nil, &InvokeError{Message: ir.err}
	}
	if ir.data != nil {
		return ir.data, nil
	}
	return ir.exitCode, nil
}
