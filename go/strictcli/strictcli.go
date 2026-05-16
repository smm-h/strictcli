// Package strictcli is a strict, zero-dependency CLI framework for Go.
package strictcli

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// FlagType represents the type of a flag value.
type FlagType int

const (
	TypeStr  FlagType = iota
	TypeBool FlagType = iota
	TypeInt  FlagType = iota
)

// Flag represents a --flag declaration.
type Flag struct {
	Name       string
	Type       FlagType
	Help       string
	Short      string
	Default    interface{} // nil means no default (required for str/int)
	Env        string
	Prefixed   bool
	Negatable  bool
	Choices    []interface{}
	Validate   func(interface{}) error
	Repeatable bool

	// hasDefault distinguishes between "default explicitly set to nil" and "no default"
	hasDefault bool
}

// Arg represents a positional argument.
type Arg struct {
	Name     string
	Help     string
	Required bool
	Default  interface{}
	IsVariadic bool

	hasDefault bool
}

// Tag is a reusable bundle of flags.
type Tag struct {
	Name  string
	Flags []Flag
}

// MutexGroup is a group of mutually exclusive flags.
type MutexGroup struct {
	Flags    []Flag
	Required bool
}

// PassthroughHandler is the handler type for passthrough commands.
type PassthroughHandler func(name string, args []string, globals map[string]interface{}) int

// Command is a leaf command with a handler.
type Command struct {
	Name               string
	Help               string
	Handler            func(map[string]interface{}) int
	Flags              []Flag
	Args               []Arg
	Tags               []Tag
	Mutex              []MutexGroup
	Passthrough        bool
	PassthroughHandler PassthroughHandler
}

// Group is a container for nested commands (one nesting level).
type Group struct {
	Name      string
	Help      string
	Commands  map[string]*Command
	envPrefix string

	// globalFlags is a reference to the app's global flags for collision checking
	globalFlags []Flag

	// order preserves insertion order for help display
	order []string
}

// Result is returned by App.Test().
type Result struct {
	Stdout   string
	Stderr   string
	ExitCode int
}

// App is the root CLI application.
type App struct {
	Name      string
	Version   string
	Help      string
	EnvPrefix string

	commands    map[string]*Command
	groups      map[string]*Group
	globalFlags []Flag

	// order preserves insertion order for help display
	cmdOrder   []string
	groupOrder []string
}

// --- Option types ---

// AppOption configures an App.
type AppOption func(*App)

// WithEnvPrefix sets the environment variable prefix for the app.
func WithEnvPrefix(prefix string) AppOption {
	return func(a *App) {
		a.EnvPrefix = prefix
	}
}

// FlagOption configures a Flag.
type FlagOption func(*Flag)

// Short sets the single-character short form for a flag.
func Short(s string) FlagOption {
	return func(f *Flag) {
		f.Short = s
	}
}

// Default sets the default value for a flag.
func Default(v interface{}) FlagOption {
	return func(f *Flag) {
		f.Default = v
		f.hasDefault = true
	}
}

// Env sets the environment variable name for a flag.
func Env(varName string) FlagOption {
	return func(f *Flag) {
		f.Env = varName
	}
}

// Prefixed controls whether env var prefix validation is applied.
func Prefixed(b bool) FlagOption {
	return func(f *Flag) {
		f.Prefixed = b
	}
}

// Choices sets the allowed values for a flag.
func Choices(vals ...interface{}) FlagOption {
	return func(f *Flag) {
		f.Choices = vals
	}
}

// Repeatable marks a flag as accepting multiple occurrences.
func Repeatable() FlagOption {
	return func(f *Flag) {
		f.Repeatable = true
	}
}

// ValidateFn sets a validation function for a flag.
func ValidateFn(fn func(interface{}) error) FlagOption {
	return func(f *Flag) {
		f.Validate = fn
	}
}

// Negatable controls whether a bool flag supports --no-X negation.
func NegatableOpt(b bool) FlagOption {
	return func(f *Flag) {
		f.Negatable = b
	}
}

// ArgOption configures an Arg.
type ArgOption func(*Arg)

// ArgRequired sets whether an arg is required.
func ArgRequired(b bool) ArgOption {
	return func(a *Arg) {
		a.Required = b
	}
}

// ArgDefault sets the default value for an arg.
func ArgDefault(v interface{}) ArgOption {
	return func(a *Arg) {
		a.Default = v
		a.hasDefault = true
	}
}

// Variadic marks a positional argument as variadic (collects remaining values).
func Variadic() ArgOption {
	return func(a *Arg) {
		a.IsVariadic = true
	}
}

// CmdOption configures a Command during registration.
type CmdOption func(*Command)

// WithArgs adds positional arguments to a command.
func WithArgs(args ...Arg) CmdOption {
	return func(c *Command) {
		c.Args = append(c.Args, args...)
	}
}

// WithFlags adds flags to a command.
func WithFlags(flags ...Flag) CmdOption {
	return func(c *Command) {
		c.Flags = append(c.Flags, flags...)
	}
}

// WithTags adds tags (flag bundles) to a command.
func WithTags(tags ...Tag) CmdOption {
	return func(c *Command) {
		c.Tags = append(c.Tags, tags...)
	}
}

// WithMutex adds mutex groups to a command.
func WithMutex(groups ...MutexGroup) CmdOption {
	return func(c *Command) {
		c.Mutex = append(c.Mutex, groups...)
	}
}

// WithPassthrough marks a command as passthrough (skips parsing, forwards raw args).
func WithPassthrough(handler PassthroughHandler) CmdOption {
	return func(c *Command) {
		c.Passthrough = true
		c.PassthroughHandler = handler
	}
}

// --- Flag constructors ---

// StringFlag creates a string-typed flag.
func StringFlag(name, help string, opts ...FlagOption) Flag {
	f := Flag{
		Name:     name,
		Type:     TypeStr,
		Help:     help,
		Prefixed: true,
	}
	for _, opt := range opts {
		opt(&f)
	}
	validateFlagConfig(&f)
	return f
}

// BoolFlag creates a boolean-typed flag.
func BoolFlag(name, help string, opts ...FlagOption) Flag {
	f := Flag{
		Name:      name,
		Type:      TypeBool,
		Help:      help,
		Prefixed:  true,
		Negatable: true,
	}
	for _, opt := range opts {
		opt(&f)
	}
	validateFlagConfig(&f)
	return f
}

// IntFlag creates an integer-typed flag.
func IntFlag(name, help string, opts ...FlagOption) Flag {
	f := Flag{
		Name:     name,
		Type:     TypeInt,
		Help:     help,
		Prefixed: true,
	}
	for _, opt := range opts {
		opt(&f)
	}
	validateFlagConfig(&f)
	return f
}

// NewArg creates a positional argument.
func NewArg(name, help string, opts ...ArgOption) Arg {
	if strings.TrimSpace(help) == "" {
		panic("Arg.help must be a non-empty string")
	}
	a := Arg{
		Name:     name,
		Help:     help,
		Required: true,
	}
	for _, opt := range opts {
		opt(&a)
	}
	if a.Required && a.hasDefault {
		panic("required arg cannot have a default")
	}
	return a
}

// validateFlagConfig panics on invalid flag configuration (programmer error).
func validateFlagConfig(f *Flag) {
	if strings.TrimSpace(f.Help) == "" {
		panic(fmt.Sprintf("Flag.help must be a non-empty string"))
	}
	if f.Repeatable && f.Type == TypeBool {
		panic(fmt.Sprintf("Flag %q: repeatable is incompatible with type=bool", f.Name))
	}
	if f.Choices != nil {
		if f.Type == TypeBool {
			panic(fmt.Sprintf("Flag %q: choices is incompatible with type=bool", f.Name))
		}
		if len(f.Choices) == 0 {
			panic(fmt.Sprintf("Flag %q: choices must be a non-empty list", f.Name))
		}
		// Validate each choice matches the flag type
		for _, c := range f.Choices {
			switch f.Type {
			case TypeStr:
				if _, ok := c.(string); !ok {
					panic(fmt.Sprintf("Flag %q: choice %v is not of type str", f.Name, c))
				}
			case TypeInt:
				if _, ok := c.(int); !ok {
					panic(fmt.Sprintf("Flag %q: choice %v is not of type int", f.Name, c))
				}
			}
		}
	}
	// Validate int default type
	if f.Type == TypeInt && f.hasDefault && f.Default != nil {
		if !f.Repeatable {
			if _, ok := f.Default.(int); !ok {
				panic(fmt.Sprintf("Flag %q: type=int requires an int default, got %T", f.Name, f.Default))
			}
		}
	}
	// For non-bool, non-repeatable: negatable is forced off
	if f.Type != TypeBool {
		f.Negatable = false
	}
	// Resolve defaults
	if !f.hasDefault {
		if f.Repeatable {
			// Repeatable defaults to empty slice
		} else if f.Type == TypeBool {
			f.Default = false
			f.hasDefault = true
		}
		// str/int with no default: required (nil Default)
	} else if f.Type == TypeBool && f.Default == nil {
		f.Default = false
	}
	// Validate default is in choices (after default resolution)
	if f.Choices != nil && f.hasDefault && f.Default != nil && !f.Repeatable {
		found := false
		for _, c := range f.Choices {
			if f.Default == c {
				found = true
				break
			}
		}
		if !found {
			panic(fmt.Sprintf("Flag %q: default %v is not in choices %v", f.Name, f.Default, f.Choices))
		}
	}
}

// --- App ---

// NewApp creates a new CLI application.
func NewApp(name, version, help string, opts ...AppOption) *App {
	if strings.TrimSpace(help) == "" {
		panic("App.help must be a non-empty string")
	}
	a := &App{
		Name:     name,
		Version:  version,
		Help:     help,
		commands: make(map[string]*Command),
		groups:   make(map[string]*Group),
	}
	for _, opt := range opts {
		opt(a)
	}
	return a
}

// Command registers a top-level command.
func (a *App) Command(name, help string, handler func(map[string]interface{}) int, opts ...CmdOption) {
	cmd := buildAndValidateCommand(name, help, handler, a.EnvPrefix, a.globalFlags, opts)
	a.commands[name] = cmd
	a.cmdOrder = append(a.cmdOrder, name)
}

// Passthrough registers a passthrough command (raw args, no parsing).
// Accepts CmdOptions for validation purposes (e.g., to detect invalid passthrough+flags).
func (a *App) Passthrough(name, help string, handler PassthroughHandler, opts ...CmdOption) {
	if strings.TrimSpace(help) == "" {
		panic(fmt.Sprintf("command %q: missing help text", name))
	}
	cmd := &Command{
		Name:               name,
		Help:               help,
		Passthrough:        true,
		PassthroughHandler: handler,
	}
	for _, opt := range opts {
		opt(cmd)
	}
	// Passthrough commands cannot have flags, args, tags, or mutex
	if len(cmd.Flags) > 0 || len(cmd.Args) > 0 || len(cmd.Tags) > 0 || len(cmd.Mutex) > 0 {
		var parts []string
		if len(cmd.Flags) > 0 {
			parts = append(parts, "flags")
		}
		if len(cmd.Args) > 0 {
			parts = append(parts, "args")
		}
		if len(cmd.Tags) > 0 {
			parts = append(parts, "tags")
		}
		if len(cmd.Mutex) > 0 {
			parts = append(parts, "mutex groups")
		}
		panic(fmt.Sprintf("command %q: passthrough commands cannot have %s", name, strings.Join(parts, ", ")))
	}
	a.commands[name] = cmd
	a.cmdOrder = append(a.cmdOrder, name)
}

// GlobalFlag registers a global flag on the app.
func (a *App) GlobalFlag(f Flag) {
	// Check for collisions with existing global flags
	for _, gf := range a.globalFlags {
		if gf.Name == f.Name {
			panic(fmt.Sprintf("duplicate global flag name %q", f.Name))
		}
	}
	a.globalFlags = append(a.globalFlags, f)
}

// Group creates and registers a command group.
func (a *App) Group(name, help string) *Group {
	if strings.TrimSpace(help) == "" {
		panic("Group.help must be a non-empty string")
	}
	grp := &Group{
		Name:        name,
		Help:        help,
		Commands:    make(map[string]*Command),
		envPrefix:   a.EnvPrefix,
		globalFlags: a.globalFlags,
	}
	a.groups[name] = grp
	a.groupOrder = append(a.groupOrder, name)
	return grp
}

// Command registers a command within a group.
func (g *Group) Command(name, help string, handler func(map[string]interface{}) int, opts ...CmdOption) {
	cmd := buildAndValidateCommand(name, help, handler, g.envPrefix, g.globalFlags, opts)
	g.Commands[name] = cmd
	g.order = append(g.order, name)
}

// Run executes the CLI, reading from os.Args.
func (a *App) Run() {
	argv := os.Args[1:]
	pr := a.doParse(argv)

	if pr.helpText != "" {
		fmt.Println(pr.helpText)
		os.Exit(0)
	}
	if pr.versionText != "" {
		fmt.Println(pr.versionText)
		os.Exit(0)
	}
	if pr.parseErr != "" {
		fmt.Fprintln(os.Stderr, "error: "+pr.parseErr)
		fmt.Fprintf(os.Stderr, "try '%s --help'\n", a.Name)
		os.Exit(1)
	}

	if pr.cmd.Passthrough {
		code := pr.cmd.PassthroughHandler(pr.cmd.Name, pr.passthroughArgs, pr.globalKwargs)
		os.Exit(code)
	}

	code := pr.cmd.Handler(pr.kwargs)
	os.Exit(code)
}

// Test runs the CLI with the given argv, capturing output and exit code.
func (a *App) Test(argv []string) Result {
	pr := a.doParse(argv)

	if pr.helpText != "" {
		return Result{Stdout: pr.helpText + "\n", ExitCode: 0}
	}
	if pr.versionText != "" {
		return Result{Stdout: pr.versionText + "\n", ExitCode: 0}
	}
	if pr.parseErr != "" {
		stderr := fmt.Sprintf("error: %s\ntry '%s --help'\n", pr.parseErr, a.Name)
		return Result{Stderr: stderr, ExitCode: 1}
	}

	// Capture stdout/stderr from handler
	oldStdout := os.Stdout
	oldStderr := os.Stderr

	stdoutR, stdoutW, _ := os.Pipe()
	stderrR, stderrW, _ := os.Pipe()
	os.Stdout = stdoutW
	os.Stderr = stderrW

	var exitCode int
	if pr.cmd.Passthrough {
		exitCode = pr.cmd.PassthroughHandler(pr.cmd.Name, pr.passthroughArgs, pr.globalKwargs)
	} else {
		exitCode = pr.cmd.Handler(pr.kwargs)
	}

	stdoutW.Close()
	stderrW.Close()

	var stdoutBuf, stderrBuf [64 * 1024]byte
	stdoutN, _ := stdoutR.Read(stdoutBuf[:])
	stderrN, _ := stderrR.Read(stderrBuf[:])
	stdoutR.Close()
	stderrR.Close()

	os.Stdout = oldStdout
	os.Stderr = oldStderr

	return Result{
		Stdout:   string(stdoutBuf[:stdoutN]),
		Stderr:   string(stderrBuf[:stderrN]),
		ExitCode: exitCode,
	}
}

// parseResult holds the output of doParse.
type parseResult struct {
	cmd             *Command
	kwargs          map[string]interface{}
	globalKwargs    map[string]interface{}
	passthroughArgs []string
	helpText        string
	versionText     string
	parseErr        string
}

// doParse parses argv and returns a parseResult.
// Exactly one of: (cmd+kwargs), helpText, versionText, or parseErr will be non-zero.
func (a *App) doParse(argv []string) parseResult {
	// App-level --help/-h and --version/-v (no global flags present)
	if len(argv) == 0 || (len(argv) == 1 && (argv[0] == "--help" || argv[0] == "-h")) {
		return parseResult{helpText: formatAppHelp(a)}
	}
	if len(argv) == 1 && (argv[0] == "--version" || argv[0] == "-v") {
		return parseResult{versionText: formatVersion(a)}
	}

	// Extract global flags from argv, leaving the rest for command routing.
	// Global flags can appear before the command name.
	globalValues, rest, globalErr := a.extractGlobalFlags(argv)
	if globalErr != "" {
		return parseResult{parseErr: globalErr}
	}

	// If global flag parsing stopped at --, strip it before routing
	if len(rest) > 0 && rest[0] == "--" {
		rest = rest[1:]
	}

	// After extracting globals, check for help/version again
	if len(rest) == 0 || (len(rest) == 1 && (rest[0] == "--help" || rest[0] == "-h")) {
		return parseResult{helpText: formatAppHelp(a)}
	}
	if len(rest) == 1 && (rest[0] == "--version" || rest[0] == "-v") {
		return parseResult{versionText: formatVersion(a)}
	}

	token := rest[0]
	cmdRest := rest[1:]

	// Check groups first
	if grp, ok := a.groups[token]; ok {
		if len(cmdRest) == 0 || (len(cmdRest) == 1 && (cmdRest[0] == "--help" || cmdRest[0] == "-h")) {
			return parseResult{helpText: formatGroupHelp(a, grp)}
		}
		subToken := cmdRest[0]
		cmdRest = cmdRest[1:]
		cmd, ok := grp.Commands[subToken]
		if !ok {
			return parseResult{parseErr: fmt.Sprintf("unknown command '%s'", subToken)}
		}
		// Check command-level --help
		if len(cmdRest) == 1 && (cmdRest[0] == "--help" || cmdRest[0] == "-h") {
			prefix := grp.Name + " "
			return parseResult{helpText: formatCommandHelp(a, cmd, prefix)}
		}
		// Passthrough: skip parsing, forward raw args
		if cmd.Passthrough {
			return parseResult{cmd: cmd, passthroughArgs: cmdRest, globalKwargs: globalValues}
		}
		kwargs, postGlobalValues, err := parseCommand(cmd, cmdRest, a.globalFlags)
		if err != "" {
			return parseResult{parseErr: err}
		}
		// Merge global values: post-command globals override pre-command ones
		for k, v := range postGlobalValues {
			globalValues[k] = v
		}
		for k, v := range globalValues {
			kwargs[k] = v
		}
		return parseResult{cmd: cmd, kwargs: kwargs, globalKwargs: globalValues}
	}

	// Check commands
	if cmd, ok := a.commands[token]; ok {
		// Passthrough: skip parsing, forward raw args
		if cmd.Passthrough {
			// Check for help in passthrough
			if len(cmdRest) == 1 && (cmdRest[0] == "--help" || cmdRest[0] == "-h") {
				return parseResult{helpText: formatCommandHelp(a, cmd, "")}
			}
			return parseResult{cmd: cmd, passthroughArgs: cmdRest, globalKwargs: globalValues}
		}
		// Check command-level --help
		if len(cmdRest) == 1 && (cmdRest[0] == "--help" || cmdRest[0] == "-h") {
			return parseResult{helpText: formatCommandHelp(a, cmd, "")}
		}
		kwargs, postGlobalValues, err := parseCommand(cmd, cmdRest, a.globalFlags)
		if err != "" {
			return parseResult{parseErr: err}
		}
		// Merge global values: post-command globals override pre-command ones
		for k, v := range postGlobalValues {
			globalValues[k] = v
		}
		for k, v := range globalValues {
			kwargs[k] = v
		}
		return parseResult{cmd: cmd, kwargs: kwargs, globalKwargs: globalValues}
	}

	return parseResult{parseErr: fmt.Sprintf("unknown command '%s'", token)}
}

// extractGlobalFlags scans argv for global flag tokens that appear before the
// command name.  It stops at the first non-flag token (the command name) or at
// "--", returning everything from that point onward as remaining tokens.
// This matches Python's _parse_global_flags behavior.  Global flags appearing
// after the command name are handled by parseCommand instead.
// Returns (globalValues map, remaining argv, error string).
func (a *App) extractGlobalFlags(argv []string) (map[string]interface{}, []string, string) {
	globalValues := make(map[string]interface{})
	if len(a.globalFlags) == 0 {
		return globalValues, argv, ""
	}

	// Build lookup maps for global flags
	longLookup := make(map[string]*Flag)
	shortLookup := make(map[string]*Flag)
	negationLookup := make(map[string]*Flag)
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		longLookup["--"+f.Name] = f
		if f.Short != "" {
			shortLookup["-"+f.Short] = f
		}
		if f.Type == TypeBool && f.Negatable {
			negationLookup["--no-"+f.Name] = f
		}
	}

	storeValue := func(f *Flag, value interface{}) {
		if f.Repeatable {
			if existing, ok := globalValues[f.Name]; ok {
				globalValues[f.Name] = append(existing.([]interface{}), value)
			} else {
				globalValues[f.Name] = []interface{}{value}
			}
		} else {
			globalValues[f.Name] = value
		}
	}

	i := 0
	for i < len(argv) {
		tok := argv[i]

		// -- stops global flag parsing; include it and the rest in remaining
		if tok == "--" {
			break
		}

		// Non-flag token (command name): stop and return the rest
		if !strings.HasPrefix(tok, "-") || tok == "-" {
			break
		}

		// --flag=value form for global flags
		if strings.HasPrefix(tok, "--") && strings.Contains(tok, "=") {
			eqPos := strings.Index(tok, "=")
			flagPart := tok[:eqPos]
			valuePart := tok[eqPos+1:]
			if f, ok := longLookup[flagPart]; ok {
				if f.Type == TypeBool {
					return nil, nil, fmt.Sprintf("flag '%s' is a boolean flag and does not take a value", flagPart)
				}
				val, err := parseGlobalFlagValue(f, valuePart)
				if err != "" {
					return nil, nil, err
				}
				storeValue(f, val)
				i++
				continue
			}
			// Not a global flag -- stop (command region)
			break
		}

		// --no-flag negation for global bool flags
		if f, ok := negationLookup[tok]; ok {
			globalValues[f.Name] = false
			i++
			continue
		}

		// --flag (long form)
		if f, ok := longLookup[tok]; ok {
			if f.Type == TypeBool {
				globalValues[f.Name] = true
				i++
			} else {
				if i+1 >= len(argv) {
					return nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				val, err := parseGlobalFlagValue(f, argv[i+1])
				if err != "" {
					return nil, nil, err
				}
				storeValue(f, val)
				i += 2
			}
			continue
		}

		// -x (short form)
		if f, ok := shortLookup[tok]; ok {
			if f.Type == TypeBool {
				globalValues[f.Name] = true
				i++
			} else {
				if i+1 >= len(argv) {
					return nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				val, err := parseGlobalFlagValue(f, argv[i+1])
				if err != "" {
					return nil, nil, err
				}
				storeValue(f, val)
				i += 2
			}
			continue
		}

		// Unknown flag-like token before command name: stop (let command parser handle it)
		break
	}

	remaining := argv[i:]

	// Resolve env vars for global flags not set by CLI
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		if _, ok := globalValues[f.Name]; ok {
			continue
		}
		if f.Env != "" {
			envVal, ok := os.LookupEnv(f.Env)
			if ok {
				switch f.Type {
				case TypeBool:
					lower := strings.ToLower(envVal)
					switch lower {
					case "1", "true", "yes":
						globalValues[f.Name] = true
					case "0", "false", "no":
						globalValues[f.Name] = false
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
						globalValues[f.Name] = []interface{}{intVal}
					} else {
						globalValues[f.Name] = intVal
					}
				default:
					if f.Repeatable {
						globalValues[f.Name] = []interface{}{envVal}
					} else {
						globalValues[f.Name] = envVal
					}
				}
				continue
			}
		}
	}

	// Apply defaults for global flags not set
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		if _, ok := globalValues[f.Name]; ok {
			continue
		}
		if f.Repeatable {
			globalValues[f.Name] = []interface{}{}
		} else if f.Type == TypeBool {
			if f.hasDefault {
				globalValues[f.Name] = f.Default
			} else {
				globalValues[f.Name] = false
			}
		} else if f.hasDefault && f.Default != nil {
			globalValues[f.Name] = f.Default
		} else if f.hasDefault {
			globalValues[f.Name] = nil
		} else {
			return nil, nil, fmt.Sprintf("global flag '--%s' is required", f.Name)
		}
	}

	// Convert to param-name keys
	result := make(map[string]interface{})
	for k, v := range globalValues {
		result[flagParamName(k)] = v
	}

	return result, remaining, ""
}

// parseGlobalFlagValue parses a string value for a global flag.
func parseGlobalFlagValue(f *Flag, raw string) (interface{}, string) {
	switch f.Type {
	case TypeInt:
		intVal, err := strconv.Atoi(raw)
		if err != nil {
			return nil, fmt.Sprintf("--%s: expected integer, got '%s'", f.Name, raw)
		}
		return intVal, ""
	default:
		return raw, ""
	}
}

// buildAndValidateCommand creates and validates a Command.
func buildAndValidateCommand(name, help string, handler func(map[string]interface{}) int, envPrefix string, globalFlags []Flag, opts []CmdOption) *Command {
	if strings.TrimSpace(help) == "" {
		panic(fmt.Sprintf("command %q: missing help text", name))
	}

	cmd := &Command{
		Name:    name,
		Help:    help,
		Handler: handler,
	}
	for _, opt := range opts {
		opt(cmd)
	}

	// Passthrough commands cannot have flags, args, tags, or mutex
	if cmd.Passthrough {
		if len(cmd.Flags) > 0 || len(cmd.Args) > 0 || len(cmd.Tags) > 0 || len(cmd.Mutex) > 0 {
			var parts []string
			if len(cmd.Flags) > 0 {
				parts = append(parts, "flags")
			}
			if len(cmd.Args) > 0 {
				parts = append(parts, "args")
			}
			if len(cmd.Tags) > 0 {
				parts = append(parts, "tags")
			}
			if len(cmd.Mutex) > 0 {
				parts = append(parts, "mutex groups")
			}
			panic(fmt.Sprintf("command %q: passthrough commands cannot have %s", name, strings.Join(parts, ", ")))
		}
		return cmd
	}

	// Merge tag flags and mutex flags into a unified all-flags list for validation
	allFlags := make([]Flag, 0, len(cmd.Flags))
	allFlags = append(allFlags, cmd.Flags...)
	for _, tag := range cmd.Tags {
		allFlags = append(allFlags, tag.Flags...)
	}

	// Validate mutex groups
	mutexFlagNames := make(map[string]bool)
	for _, mg := range cmd.Mutex {
		if len(mg.Flags) < 2 {
			panic(fmt.Sprintf("command %q: mutex group must have at least 2 flags, got %d", name, len(mg.Flags)))
		}
		for _, f := range mg.Flags {
			if mutexFlagNames[f.Name] {
				panic(fmt.Sprintf("command %q: flag %q appears in multiple mutex groups", name, f.Name))
			}
			mutexFlagNames[f.Name] = true
		}
		allFlags = append(allFlags, mg.Flags...)
	}

	// Check duplicate flag names and collisions with global flags
	globalFlagSet := make(map[string]bool)
	for _, gf := range globalFlags {
		globalFlagSet[gf.Name] = true
	}
	seenFlags := make(map[string]bool)
	for _, f := range allFlags {
		if globalFlagSet[f.Name] {
			panic(fmt.Sprintf("command %q: flag %q collides with a global flag", name, f.Name))
		}
		if seenFlags[f.Name] {
			panic(fmt.Sprintf("command %q: duplicate flag name %q", name, f.Name))
		}
		seenFlags[f.Name] = true
	}

	// Check duplicate arg names
	seenArgs := make(map[string]bool)
	for _, a := range cmd.Args {
		if seenArgs[a.Name] {
			panic(fmt.Sprintf("command %q: duplicate arg name %q", name, a.Name))
		}
		seenArgs[a.Name] = true
	}

	// Validate variadic args: first check count, then check position
	variadicCount := 0
	for _, a := range cmd.Args {
		if a.IsVariadic {
			variadicCount++
		}
	}
	if variadicCount > 1 {
		panic(fmt.Sprintf("command %q: at most one variadic arg is allowed", name))
	}
	for i, a := range cmd.Args {
		if a.IsVariadic && i != len(cmd.Args)-1 {
			panic(fmt.Sprintf("command %q: variadic arg %q must be the last arg", name, a.Name))
		}
	}

	// Validate flag help
	for _, f := range allFlags {
		if strings.TrimSpace(f.Help) == "" {
			panic(fmt.Sprintf("command %q: flag %q missing help text", name, f.Name))
		}
	}

	// Validate env prefix
	if envPrefix != "" {
		expectedPrefix := envPrefix + "_"
		for _, f := range allFlags {
			if f.Env != "" && f.Prefixed {
				if !strings.HasPrefix(f.Env, expectedPrefix) {
					panic(fmt.Sprintf(
						"command %q: env var %q for flag %q must start with %q (or set prefixed=false)",
						name, f.Env, f.Name, expectedPrefix,
					))
				}
			}
		}
	}

	// Store the resolved allFlags on the command for parsing
	cmd.Flags = allFlags

	return cmd
}

// flagParamName converts a flag name like "dry-run" to a parameter key "dry_run".
func flagParamName(name string) string {
	return strings.ReplaceAll(name, "-", "_")
}

// findCommandPrefix finds the group prefix for a command.
func (a *App) findCommandPrefix(cmd *Command) string {
	for _, grp := range a.groups {
		for _, c := range grp.Commands {
			if c == cmd {
				return grp.Name + " "
			}
		}
	}
	return ""
}
