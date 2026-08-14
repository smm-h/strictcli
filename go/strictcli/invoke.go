package strictcli

import (
	"fmt"
	"io"
	"sort"
	"strings"
)

// invokeResult holds the outcome of an invoke call.
type invokeResult struct {
	exitCode int
	data     interface{} // the machine payload the handler supplied (nil otherwise)
	err      string      // non-empty if invocation failed
}

// InvokeError is returned by App.Call() when invocation fails
// (unknown command, missing flags, mutex violations, etc.).
type InvokeError struct {
	Message string
}

// Error returns the error message describing the invocation failure.
func (e *InvokeError) Error() string {
	return e.Message
}

// paramToFlagName converts a parameter name like "dry_run" back to a flag name "dry-run".
// This is the reverse of flagParamName.
func paramToFlagName(param string) string {
	return strings.ReplaceAll(param, "_", "-")
}

// callOptions carries the per-call state that is NOT a handler kwarg.
type callOptions struct {
	approveConsequential bool
}

// CallOption configures one App.Call. Go's Call takes its kwargs as a map, so
// consent cannot ride in them the way Python's keyword-only argument does --
// it is a variadic option instead, which is this package's existing shape for
// "a declaration that is not data".
type CallOption func(*callOptions)

// WithApproveConsequential is the caller's explicit consent on the
// programmatic path, the counterpart of the CLI's --approve-consequential. A
// command that declares itself consequential is refused without it; read-only
// and plain mutating commands are unaffected.
func WithApproveConsequential() CallOption {
	return func(o *callOptions) { o.approveConsequential = true }
}

// buildCallOptions folds the variadic options into a value.
func buildCallOptions(opts []CallOption) callOptions {
	var o callOptions
	for _, opt := range opts {
		if opt != nil {
			opt(&o)
		}
	}
	return o
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
//
// opts carries the caller's consent: a consequential command is refused
// without WithApproveConsequential().
func (a *App) invoke(commandPath string, kwargs map[string]interface{}, opts ...CallOption) invokeResult {
	co := buildCallOptions(opts)

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

	// The consent check (contract §8.5). There is no terminal here, so the
	// confirm protocol's PROMPT cannot fire -- the caller must have said so in
	// the call. Checked before anything is dispatched or recorded.
	if cmd.Consequential && !co.approveConsequential {
		return invokeResult{exitCode: 1, err: errCallConsequentialUnconsented(commandPath)}
	}

	// Programmatic dispatch: --dry-run is not reachable (argv parsing is
	// bypassed entirely) and the confirm protocol's prompt never fires -- these
	// paths have no TTY contract and a prompt there would hang the caller. The
	// requirement itself is honoured above, and the caller's consent is
	// delivered to the handler on the Context.
	a.beginDispatch()

	// Record test-coverage hit (command-level only).
	if a.testCoverage {
		a.recordCoverage(commandPath)
	}

	// Handle passthrough commands
	if cmd.Passthrough {
		var args []string
		if rawArgs, ok := kwargs["_args"]; ok {
			if typedArgs, ok := rawArgs.([]string); ok {
				args = typedArgs
			} else {
				return invokeResult{exitCode: 1, err: errPassthroughArgsNotStringSlice}
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
				return invokeResult{exitCode: 1, err: errUnknownParameterForPassthroughCommand(key, commandPath)}
			}
		}

		// Build global kwargs from the remaining kwargs entries
		globalKwargs := make(map[string]interface{})
		for _, gf := range a.globalFlags {
			paramName := flagParamName(gf.Name)
			if v, ok := kwargs[paramName]; ok {
				globalKwargs[paramName] = v
			} else {
				val, _, errMsg := applyFlagDefault(&gf, "global ", a.infraRoots)
				if errMsg != "" {
					return invokeResult{exitCode: 1, err: errMsg}
				}
				globalKwargs[paramName] = val
			}
		}
		ctx := newContext(io.Discard, io.Discard, nil, a.infraAccess(false),
			reservedFlags{approveConsequential: co.approveConsequential},
			a.armEffects(cmd, commandPath, false, nil))
		code, truncErr := a.invokeSealed(func() int {
			return cmd.PassthroughHandler(ctx, cmd.Name, args, globalKwargs)
		})
		if truncErr != "" {
			return invokeResult{exitCode: 1, err: truncErr}
		}
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

	// A selector's value on the programmatic front door is the same record a
	// handler receives -- Elect(<choice>, Fields{...}) -- or, at the machine
	// boundary, the flat form: the choice name under the selector's own key,
	// with every scoped parameter a top-level key. Both are converted here into
	// the SAME election and value input the argv path produces, so the two front
	// doors agree by construction rather than by test (contract §24.11).
	sup := newSuppliedElections()
	cliByFlag := make(map[*Flag]interface{})
	scopedNames := make(map[string]*Flag)
	if cmd.index != nil && cmd.index.hasSelectors {
		if errStr := collectInvokeElections(cmd, kwargs, sup, cliByFlag, scopedNames); errStr != "" {
			return invokeResult{exitCode: 1, err: errStr}
		}
	}

	for paramName, value := range kwargs {
		flagName := paramToFlagName(paramName)

		// Check if it's a command flag
		if f, ok := flagByName[flagName]; ok {
			if f.Type == TypeChoice {
				continue // already folded into the election input
			}
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

		// A scoped parameter supplied at the top level: legal at this boundary,
		// where the schema is flat (§24.11), and refused by the SAME scope
		// machinery the CLI parser uses when the combination is wrong.
		if _, ok := scopedNames[flagName]; ok {
			continue
		}

		return invokeResult{
			exitCode: 1,
			err:      errUnknownParameterForCommand(paramName, commandPath),
		}
	}

	amb := ambientSource{hermetic: true}
	est, electErr := elect(cmd, sup, amb)
	if electErr != "" {
		return invokeResult{exitCode: 1, err: electErr}
	}
	var suppliedOrder []string
	for name := range sup.suppliedNames {
		suppliedOrder = append(suppliedOrder, name)
	}
	sort.Strings(suppliedOrder)
	if errStr := est.checkScope(suppliedOrder); errStr != "" {
		return invokeResult{exitCode: 1, err: errStr}
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
	var noStdin *string
	validatedKwargs, postGlobalValues, sources, errStr := validateAndBuildKwargs(cmd, store, positionals, globalFlagNames, a.infraRoots, est, cliByFlag, amb, &noStdin)
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
		val, src, errMsg := applyFlagDefault(gf, "global ", a.infraRoots)
		if errMsg != "" {
			return invokeResult{exitCode: 1, err: errMsg}
		}
		validatedKwargs[paramName] = val
		if sources != nil {
			sources[paramName] = sourceLabelString(src)
		}
	}

	// Context is constructed unconditionally. For invoke, stdout/stderr are
	// discarded -- the machine payload flows back through the Context, not
	// stdout.
	ctx := newContext(io.Discard, io.Discard, sources, a.infraAccess(false),
		reservedFlags{approveConsequential: co.approveConsequential},
		a.armEffects(cmd, commandPath, false, nil))
	ctx.commandName = cmd.Name
	ctx.payloadSchema = cmd.PayloadSchema

	// Call the handler under the runtime seal.
	var outcome Outcome
	_, truncErr := a.invokeSealed(func() int {
		outcome = cmd.Handler(ctx, validatedKwargs)
		return outcome.code
	})
	if truncErr != "" {
		return invokeResult{exitCode: 1, err: truncErr}
	}
	// The programmatic surface keeps its capture: it returns the payload the
	// handler supplied (contract §19.4).
	return invokeResult{exitCode: outcome.code, data: ctx.payload}
}

// invokeSealed runs a handler on the programmatic path under the runtime seal.
// A carrier extraction surfaces as an InvokeError carrying the pinned
// truncation text; any other panic is re-raised untouched.
func (a *App) invokeSealed(fn func() int) (code int, truncErr string) {
	defer func() {
		r := recover()
		if r == nil {
			return
		}
		t, ok := r.(dryRunTruncation)
		if !ok {
			panic(r)
		}
		code = 1
		truncErr = t.message
	}()
	return fn(), ""
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
		return nil, errDictFlagExpectedMapType(f.Name, value)
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
//   - For handlers that supplied a payload through ctx.Payload: the payload
//   - For handlers that return Exit without a payload: the exit code (int)
//   - For passthrough handlers: the exit code (int)
//
// Returns an InvokeError if invocation fails (unknown command, missing
// required flags, mutex violations, dependency errors, etc.).
func (a *App) Call(commandPath string, kwargs map[string]interface{}, opts ...CallOption) (interface{}, error) {
	ir := a.invoke(commandPath, kwargs, opts...)
	if ir.err != "" {
		return nil, &InvokeError{Message: ir.err}
	}
	if ir.data != nil {
		return ir.data, nil
	}
	return ir.exitCode, nil
}

// collectInvokeElections converts a programmatic call's selector arguments into
// the same election-and-value input the argv path produces (contract §24.11).
//
// Two spellings reach this boundary, and they are two FRONT DOORS rather than
// two spellings of one fact: App.Call takes the elected record pre-typed
// (Elect(<choice>, Fields{...})), while the machine boundary's flat object
// carries the choice name under the selector's own key and every scoped
// parameter as a top-level key.
func collectInvokeElections(cmd *Command, kwargs map[string]interface{}, sup *suppliedElections, cliByFlag map[*Flag]interface{}, scopedNames map[string]*Flag) string {
	// Every scoped name, so a top-level scoped parameter is recognized rather
	// than refused as unknown -- and so a parameter belonging to a scope that
	// was NOT elected reaches scope validation and is refused with the CLI's own
	// sentence rather than silently ignored.
	for _, name := range cmd.index.order {
		for _, site := range cmd.index.sites[name] {
			if len(site.path) > 0 {
				scopedNames[name] = site.flag
			}
		}
	}
	for key := range kwargs {
		if _, ok := scopedNames[paramToFlagName(key)]; ok {
			sup.suppliedNames[paramToFlagName(key)] = true
		}
	}

	var walk func(flags []Flag, args map[string]interface{}) string
	walk = func(flags []Flag, args map[string]interface{}) string {
		for i := range flags {
			f := &flags[i]
			if f.Type != TypeChoice {
				continue
			}
			raw, ok := args[flagParamName(f.Name)]
			if !ok {
				continue
			}
			sup.suppliedNames[f.Name] = true
			switch v := raw.(type) {
			case *Elected:
				ch := findChoice(f, v.decl.Name)
				if ch != v.decl {
					return errElectNotAChoice(f.Name, v.decl.Name)
				}
				sup.preElected[f] = ch
				if errStr := bindElectedFields(f, ch, v.Fields, sup, cliByFlag); errStr != "" {
					return errStr
				}
				if errStr := walk(ch.Flags, v.Fields); errStr != "" {
					return errStr
				}
			case string:
				ch := findChoice(f, v)
				if ch == nil {
					return errFlagInvalidChoice(f.Name, v, strings.Join(choiceNames(f), ", "))
				}
				sup.preElected[f] = ch
				// The flat form's scoped parameters sit beside the selector, so
				// the same top-level object supplies the next level too.
				if errStr := bindElectedFields(f, ch, Fields(args), sup, cliByFlag); errStr != "" {
					return errStr
				}
				if errStr := walk(ch.Flags, args); errStr != "" {
					return errStr
				}
			default:
				return errSelectorValueNotElected(f.Name, raw)
			}
		}
		return ""
	}
	return walk(cmd.flags, kwargs)
}

// bindElectedFields records the values a scope's flags were given, keyed by the
// declaration, and marks every named flag as supplied so scope validation sees
// it.
func bindElectedFields(sel *Flag, ch *ChoiceDecl, fields Fields, sup *suppliedElections, cliByFlag map[*Flag]interface{}) string {
	for i := range ch.Flags {
		sub := &ch.Flags[i]
		key := flagParamName(sub.Name)
		isMember := ch.member && i == 0
		if isMember {
			if !choiceCarriesPayload(ch) {
				continue
			}
			// A member-spelled choice's payload arrives under the reserved name
			// "value" in a record, and under the member's OWN flag name in the
			// flat machine form -- which is the property name §24.11 publishes.
			if v, ok := fields["value"]; ok {
				cliByFlag[sub] = v
				sup.suppliedNames[sub.Name] = true
				continue
			}
		}
		if v, ok := fields[key]; ok {
			if sub.Type == TypeChoice {
				continue // handled by the recursive walk
			}
			coerced, errStr := coerceInvokeValue(sub, v)
			if errStr != "" {
				return errStr
			}
			cliByFlag[sub] = coerced
			sup.suppliedNames[sub.Name] = true
		}
	}
	return ""
}
