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

	// The properties this command publishes at the flat boundary, each under
	// the PARAMETER spelling a handler receives (§24.11).
	props := buildFlatProps(a, cmd)

	// SHAPE precedes every phase. A key naming nothing the command declares is
	// a fact about the object's shape, and it outranks every election, scope,
	// value and presence problem the same object also contains -- exactly as an
	// unknown flag outranks all four on the command line wherever it sits in
	// argv (§24.11, §18.23 item 238). It therefore runs BEFORE the declaration
	// walk below, whose own refusals (an unelectable selector value, a record
	// naming a foreign choice) are phase facts.
	for paramName := range kwargs {
		if props.declares(paramName) {
			continue
		}
		return invokeResult{
			exitCode: 1,
			err:      errUnknownParameterForCommand(paramName, commandPath),
		}
	}

	// Populate sourcedStore from kwargs, mapping param names back to flag names.
	// Provided kwargs are marked SourceCLI; absent flags will get SourceDefault
	// when validateAndBuildKwargs applies defaults.
	store := newSourcedStore()
	positionals := map[string]interface{}{}

	// A selector's value on the programmatic front door is the same record a
	// handler receives -- Elect(<choice>, Fields{...}) -- or, at the machine
	// boundary, the flat form: the choice name under the selector's own key,
	// with every scoped parameter a top-level key. Both are converted here into
	// the SAME election and value input the argv path produces, so the two front
	// doors agree by construction rather than by test (contract §24.11).
	sup := newSuppliedElections()
	cliByFlag := make(map[*Flag]interface{})
	var scopedBinds []pendingBind
	if cmd.index != nil && cmd.index.hasSelectors {
		binds, errStr := collectInvokeElections(cmd, kwargs, sup, props.scoped)
		if errStr != "" {
			return invokeResult{exitCode: 1, err: errStr}
		}
		scopedBinds = binds
	}

	// Every value this call supplied, held until the election phase has run
	// command-wide. Checking where the value is read would let an earlier
	// scope's value problem outrank a later selector's election refusal, which
	// inverts the pinned phase order (§24.3, §24.11).
	rootValues := make(map[*Flag]interface{})
	globalValues := make(map[*Flag]interface{})
	for paramName, value := range kwargs {
		if f, ok := props.flags[paramName]; ok {
			if f.Type == TypeChoice {
				continue // already folded into the election input
			}
			rootValues[f] = value
			continue
		}
		if gf, ok := props.globals[paramName]; ok {
			globalValues[gf] = value
			continue
		}
		// A positional arg, or a scoped parameter supplied at the top level --
		// the latter legal at this boundary, where the schema is flat (§24.11),
		// and refused by the SAME scope machinery the CLI parser uses when the
		// combination is wrong. Both are read after the election phase.
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

	// Phase 4 begins here: election and scope are settled command-wide, so a
	// value may now be refused. A flat object has no order of its own, so the
	// sweep is DECLARATION order -- scoped values as the walk collected them,
	// then the command's own flags, its positionals, and the app's globals --
	// which is what §21.4 already uses wherever an order-free object has to be
	// reported in some order.
	for _, b := range scopedBinds {
		checked, errStr := checkPreTypedValue(b.flag, b.raw)
		if errStr != "" {
			return invokeResult{exitCode: 1, err: errStr}
		}
		cliByFlag[b.flag] = checked
	}
	for i := range cmd.flags {
		f := &cmd.flags[i]
		raw, ok := rootValues[f]
		if !ok {
			continue
		}
		checked, errStr := checkPreTypedValue(f, raw)
		if errStr != "" {
			return invokeResult{exitCode: 1, err: errStr}
		}
		store.set(f.Name, checked, SourceCLI)
	}

	// Collect the positionals this call supplied, under the arg names it
	// supplied them under. The values are handed on as supplied; the
	// declaration checks them where every other positional is resolved, and
	// binds each to the arg its key names (§24.11 item 244).
	for i := range cmd.args {
		arg := &cmd.args[i]
		if val, ok := kwargs[arg.Name]; ok {
			positionals[arg.Name] = val
		}
	}

	for i := range a.globalFlags {
		gf := &a.globalFlags[i]
		raw, ok := globalValues[gf]
		if !ok {
			continue
		}
		checked, errStr := checkPreTypedValue(gf, raw)
		if errStr != "" {
			return invokeResult{exitCode: 1, err: errStr}
		}
		store.set(gf.Name, checked, SourceCLI)
	}

	// Run validation and build final kwargs
	var noStdin *string
	validatedKwargs, postGlobalValues, sources, errStr := validateAndBuildKwargs(cmd, store, preTypedPositionals(positionals), props.globalNames, a.infraRoots, est, cliByFlag, amb, &noStdin)
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

// flatProps is every property a command publishes at the flat boundary, keyed
// by the PARAMETER spelling -- underscored, exactly as a handler receives it,
// and exactly as the schema publishes it (§24.11). A flag's own dashed spelling
// is therefore a key the command does not declare: the boundary reads the
// command line the flat object spells, but it is not the command line, and one
// property has one name.
type flatProps struct {
	// flags are the command's own root declarations, selectors included.
	flags map[string]*Flag
	// scoped is every declaration inside a scope, at every depth, including a
	// member's payload key -- each a property of the flat schema, so supplying
	// one is a scope question and never a shape one.
	scoped map[string]*Flag
	// globals are the app-level flags.
	globals map[string]*Flag
	// globalNames is the same set under the dashed spelling the parse pipeline
	// keys its store by.
	globalNames map[string]bool
	// args are the positional args, under their declared names.
	args map[string]bool
}

// declares reports whether one kwargs key names something this command has.
func (p *flatProps) declares(paramName string) bool {
	if _, ok := p.flags[paramName]; ok {
		return true
	}
	if _, ok := p.scoped[paramName]; ok {
		return true
	}
	if _, ok := p.globals[paramName]; ok {
		return true
	}
	return p.args[paramName]
}

// buildFlatProps indexes one command's flat properties.
func buildFlatProps(a *App, cmd *Command) *flatProps {
	p := &flatProps{
		flags:       make(map[string]*Flag, len(cmd.flags)),
		scoped:      map[string]*Flag{},
		globals:     make(map[string]*Flag, len(a.globalFlags)),
		globalNames: make(map[string]bool, len(a.globalFlags)),
		args:        make(map[string]bool, len(cmd.args)),
	}
	for i := range cmd.flags {
		p.flags[flagParamName(cmd.flags[i].Name)] = &cmd.flags[i]
	}
	if cmd.index != nil {
		for _, name := range cmd.index.order {
			for _, site := range cmd.index.sites[name] {
				if len(site.path) > 0 {
					p.scoped[flagParamName(name)] = site.flag
				}
			}
		}
	}
	for i := range a.globalFlags {
		p.globals[flagParamName(a.globalFlags[i].Name)] = &a.globalFlags[i]
		p.globalNames[a.globalFlags[i].Name] = true
	}
	for _, arg := range cmd.args {
		p.args[arg.Name] = true
	}
	return p
}

// checkPreTypedValue checks one PRE-TYPED value against the declaration it was
// supplied against, and returns it in the representation the parse pipeline
// carries (contract §24.11, §23.4, §18.23 item 240).
//
// The two programmatic doors hand the framework values that are already typed,
// so nothing parses them -- but the declaration still decides what they may be,
// exactly as it does for a token that has to be parsed first. *Pre-typed* means
// ALREADY OF THE DECLARED TYPE, never exempt from the declaration: the closed-set
// half of the declaration (Choices) is consulted on this path already, so the
// type half is consulted too. The check is the one the config reader runs over
// an already-typed document, because a flat object and a config document pose
// the identical question, and the sentences are therefore the ones that reader
// already prints.
//
// nil is a legal value for nothing. Optionality has ONE spelling (§23.4): a flag
// that may be absent declares Optional() and is delivered absent when its key is
// simply not there, so a null says nothing the declaration cannot already say --
// and on a required flag it would answer the presence rule with a value the
// declaration forbids.
func checkPreTypedValue(f *Flag, value interface{}) (interface{}, string) {
	if IsDictType(f.Type) {
		// A dict flag keeps its own SHAPE refusal, which names the Go type the
		// caller actually handed over; its entries are then checked like any
		// others.
		m, errStr := coerceInvokeDict(f, value)
		if errStr != "" {
			return nil, errStr
		}
		value = m
	}
	coerced, errStr := coerceConfigValue(normalizePreTyped(value), f)
	if errStr != "" {
		return nil, errFlagValueError(f.Name, errStr)
	}
	return coerced, ""
}

// checkPreTypedArgValue checks one PRE-TYPED positional value against its
// declaration, and delivers the value itself (contract §24.11 item 244).
//
// A positional is declared with the same presence spellings and the same four
// types a flag is (§23.3), so nothing about being a positional makes a supplied
// value exempt from its declaration: an int is not a string arg's value and a
// null is nothing's. Stringifying instead would not merely skip the check, it
// would MANUFACTURE an argv -- a token the caller never wrote, re-parsed into
// the right answer by luck where the types happen to line up, and into the text
// of a null where they do not. The wrapper is the arg side's own, never
// `--<name>`, because that is the prefix every arg-side value refusal uses.
//
// A variadic arg is a SEQUENCE of positionals rather than one value of a
// collection type, so an array spreads into one element per entry and each
// element is checked on its own -- and anything else is the single element it
// looks like, which is the one positional a command line would have typed.
func checkPreTypedArgValue(a *Arg, value interface{}) (interface{}, string) {
	if a.IsVariadic {
		items, ok := normalizePreTyped(value).([]interface{})
		if !ok {
			items = []interface{}{value}
		}
		vals := make([]interface{}, len(items))
		for i, item := range items {
			checked, errStr := checkPreTypedArgElement(a, item)
			if errStr != "" {
				return nil, errStr
			}
			vals[i] = checked
		}
		return vals, ""
	}
	return checkPreTypedArgElement(a, value)
}

// checkPreTypedArgElement checks one pre-typed value against the type its arg
// declares.
func checkPreTypedArgElement(a *Arg, value interface{}) (interface{}, string) {
	t := a.Type
	if IsListType(t) {
		t = ItemType(t)
	}
	coerced, errStr := coerceConfigScalar(normalizePreTyped(value), t, false)
	if errStr != "" {
		return nil, fmt.Sprintf("argument '%s': %s", a.Name, errStr)
	}
	return coerced, ""
}

// normalizePreTyped converts a Go-native value into the representation a decoded
// document has, which is what the config reader's check reads: int64 and float64
// for numbers, []interface{} and map[string]interface{} for the two compounds.
// It decides what the value IS -- the fact the refusal below it must name -- and
// never whether the declaration accepts it.
func normalizePreTyped(value interface{}) interface{} {
	switch v := value.(type) {
	case int:
		return int64(v)
	case int8:
		return int64(v)
	case int16:
		return int64(v)
	case int32:
		return int64(v)
	case float32:
		return float64(v)
	case []interface{}:
		out := make([]interface{}, len(v))
		for i, item := range v {
			out[i] = normalizePreTyped(item)
		}
		return out
	case []string:
		out := make([]interface{}, len(v))
		for i, item := range v {
			out[i] = item
		}
		return out
	case []int:
		out := make([]interface{}, len(v))
		for i, item := range v {
			out[i] = int64(item)
		}
		return out
	case []float64:
		out := make([]interface{}, len(v))
		for i, item := range v {
			out[i] = item
		}
		return out
	case map[string]interface{}:
		out := make(map[string]interface{}, len(v))
		for k, item := range v {
			out[k] = normalizePreTyped(item)
		}
		return out
	}
	return value
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

// pendingBind is one value an elected scope was given, held until the election
// phase has run command-wide. Collecting rather than coercing is what keeps a
// value refusal behind every selector's election refusal (§24.3, §24.11).
type pendingBind struct {
	flag *Flag
	raw  interface{}
}

// collectInvokeElections converts a programmatic call's selector arguments into
// the same election-and-value input the argv path produces (contract §24.11).
//
// Two spellings reach this boundary, and they are two FRONT DOORS rather than
// two spellings of one fact: App.Call takes the elected record pre-typed
// (Elect(<choice>, Fields{...})), while the machine boundary's flat object
// carries the choice name under the selector's own key and every scoped
// parameter as a top-level key.
//
// It returns the values the elected scopes were given, in declaration order,
// for the caller to coerce once every election is settled. Nothing here refuses
// a value: a walk over declarations is not a licence to refuse mid-walk.
func collectInvokeElections(cmd *Command, kwargs map[string]interface{}, sup *suppliedElections, scoped map[string]*Flag) ([]pendingBind, string) {
	// Every scoped parameter this call named is marked supplied, so a parameter
	// belonging to a scope that was NOT elected reaches scope validation and is
	// refused with the CLI's own sentence rather than silently ignored.
	for key := range kwargs {
		if f, ok := scoped[key]; ok {
			sup.suppliedNames[f.Name] = true
		}
	}

	var binds []pendingBind
	var walk func(flags []Flag, args map[string]interface{}) string
	walk = func(flags []Flag, args map[string]interface{}) string {
		for i := range flags {
			f := &flags[i]
			if f.Type != TypeChoice {
				continue
			}
			raw, named := args[flagParamName(f.Name)]
			if rec, isRecord := raw.(*Elected); named && isRecord {
				// The record front door, at either spelling: the caller handed
				// over the election already made.
				ch := findChoice(f, rec.decl.Name)
				if ch != rec.decl {
					return errElectNotAChoice(f.Name, rec.decl.Name)
				}
				sup.suppliedNames[f.Name] = true
				sup.preElected[f] = ch
				bindElectedFields(ch, rec.Fields, sup, &binds)
				if errStr := walk(ch.Flags, rec.Fields); errStr != "" {
					return errStr
				}
				continue
			}
			if f.memberSpelled {
				if errStr := collectFlatMemberElections(f, args, named, raw, sup, &binds, walk); errStr != "" {
					return errStr
				}
				continue
			}
			if !named {
				continue
			}
			v, isName := raw.(string)
			if !isName {
				return errSelectorValueNotElected(f.Name, raw)
			}
			ch := findChoice(f, v)
			if ch == nil {
				return errFlagInvalidChoice(f.Name, v, strings.Join(choiceNames(f), ", "))
			}
			sup.suppliedNames[f.Name] = true
			sup.preElected[f] = ch
			// The flat form's scoped parameters sit beside the selector, so
			// the same top-level object supplies the next level too.
			bindElectedFields(ch, Fields(args), sup, &binds)
			if errStr := walk(ch.Flags, args); errStr != "" {
				return errStr
			}
		}
		return ""
	}
	if errStr := walk(cmd.flags, kwargs); errStr != "" {
		return nil, errStr
	}
	return binds, ""
}

// collectFlatMemberElections reads a member-spelled selector's elections out of
// the flat machine object (contract §24.11, §21.4).
//
// Supplying a member's payload key IS electing that member, exactly as typing
// its token is: the flat form is the command line with the tokens removed, not
// a second election vocabulary. So an object naming one member under the
// selector's own key AND carrying another member's payload key has elected
// TWICE, and the refusal is the election phase's own -- §21.4's mutual-exclusion
// sentence, reached by handing both elections to the same machinery the argv
// path hands its tokens to, rather than by a second rule written here.
func collectFlatMemberElections(
	sel *Flag,
	args map[string]interface{},
	named bool,
	raw interface{},
	sup *suppliedElections,
	binds *[]pendingBind,
	walk func([]Flag, map[string]interface{}) string,
) string {
	elected := map[string]bool{}
	if named {
		v, isName := raw.(string)
		if !isName {
			return errSelectorValueNotElected(sel.Name, raw)
		}
		ch := findChoice(sel, v)
		if ch == nil {
			return errFlagInvalidChoice(sel.Name, v, strings.Join(choiceNames(sel), ", "))
		}
		sup.suppliedNames[sel.Name] = true
		elected[ch.Name] = true
	}
	for _, ch := range sel.choiceDecls {
		value, supplied := args[flagParamName(ch.Name)]
		if !supplied {
			continue
		}
		sup.suppliedNames[ch.Name] = true
		// A payload-less member elects on presence and DECLINES on the false its
		// `--no-<name>` token would have carried (§21.2), which is what keeps the
		// flat form and the command line one rule rather than two.
		if !choiceCarriesPayload(ch) {
			if b, isBool := value.(bool); isBool && !b {
				sup.memberElected[ch.Name] = false
				continue
			}
		}
		elected[ch.Name] = true
	}
	for name := range elected {
		sup.memberElected[name] = true
	}
	// Nothing elected, or several: the election phase is what says so, with the
	// sentence the command line would have produced.
	if len(elected) != 1 {
		return ""
	}
	var only *ChoiceDecl
	for _, ch := range sel.choiceDecls {
		if elected[ch.Name] {
			only = ch
		}
	}
	bindElectedFields(only, Fields(args), sup, binds)
	return walk(only.Flags, args)
}

// bindElectedFields records the values a scope's flags were given, keyed by the
// declaration and in declaration order, and marks every named flag as supplied
// so scope validation sees it. It refuses nothing: the values it collects are
// coerced once every election is settled (§24.3's phase order).
func bindElectedFields(ch *ChoiceDecl, fields Fields, sup *suppliedElections, binds *[]pendingBind) {
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
				*binds = append(*binds, pendingBind{flag: sub, raw: v})
				sup.suppliedNames[sub.Name] = true
				continue
			}
		}
		if v, ok := fields[key]; ok {
			if sub.Type == TypeChoice {
				continue // handled by the recursive walk
			}
			*binds = append(*binds, pendingBind{flag: sub, raw: v})
			sup.suppliedNames[sub.Name] = true
		}
	}
}
