// Package strictcli is a strict, zero-dependency CLI framework for Go.
package strictcli

import (
	"fmt"
	"os"
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

// Command is a leaf command with a handler.
type Command struct {
	Name    string
	Help    string
	Handler func(map[string]interface{})
	Flags   []Flag
	Args    []Arg
	Tags    []Tag
	Mutex   []MutexGroup
}

// Group is a container for nested commands (one nesting level).
type Group struct {
	Name      string
	Help      string
	Commands  map[string]*Command
	envPrefix string

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

	commands map[string]*Command
	groups   map[string]*Group

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
func (a *App) Command(name, help string, handler func(map[string]interface{}), opts ...CmdOption) {
	cmd := buildAndValidateCommand(name, help, handler, a.EnvPrefix, opts)
	a.commands[name] = cmd
	a.cmdOrder = append(a.cmdOrder, name)
}

// Group creates and registers a command group.
func (a *App) Group(name, help string) *Group {
	if strings.TrimSpace(help) == "" {
		panic("Group.help must be a non-empty string")
	}
	grp := &Group{
		Name:      name,
		Help:      help,
		Commands:  make(map[string]*Command),
		envPrefix: a.EnvPrefix,
	}
	a.groups[name] = grp
	a.groupOrder = append(a.groupOrder, name)
	return grp
}

// Command registers a command within a group.
func (g *Group) Command(name, help string, handler func(map[string]interface{}), opts ...CmdOption) {
	cmd := buildAndValidateCommand(name, help, handler, g.envPrefix, opts)
	g.Commands[name] = cmd
	g.order = append(g.order, name)
}

// Run executes the CLI, reading from os.Args.
func (a *App) Run() {
	argv := os.Args[1:]
	cmd, kwargs, helpText, versionText, parseErr := a.doParse(argv)

	if helpText != "" {
		fmt.Println(helpText)
		os.Exit(0)
	}
	if versionText != "" {
		fmt.Println(versionText)
		os.Exit(0)
	}
	if parseErr != "" {
		fmt.Fprintln(os.Stderr, "error: "+parseErr)
		fmt.Fprintf(os.Stderr, "try '%s --help'\n", a.Name)
		os.Exit(1)
	}

	cmd.Handler(kwargs)
	os.Exit(0)
}

// Test runs the CLI with the given argv, capturing output and exit code.
func (a *App) Test(argv []string) Result {
	cmd, kwargs, helpText, versionText, parseErr := a.doParse(argv)

	if helpText != "" {
		return Result{Stdout: helpText + "\n", ExitCode: 0}
	}
	if versionText != "" {
		return Result{Stdout: versionText + "\n", ExitCode: 0}
	}
	if parseErr != "" {
		stderr := fmt.Sprintf("error: %s\ntry '%s --help'\n", parseErr, a.Name)
		return Result{Stderr: stderr, ExitCode: 1}
	}

	// Capture stdout/stderr from handler
	oldStdout := os.Stdout
	oldStderr := os.Stderr

	stdoutR, stdoutW, _ := os.Pipe()
	stderrR, stderrW, _ := os.Pipe()
	os.Stdout = stdoutW
	os.Stderr = stderrW

	cmd.Handler(kwargs)

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
		ExitCode: 0,
	}
}

// doParse parses argv and returns one of: (cmd, kwargs), helpText, versionText, or parseErr.
// Exactly one of the return groups will be non-zero.
func (a *App) doParse(argv []string) (*Command, map[string]interface{}, string, string, string) {
	// App-level --help/-h and --version/-v
	if len(argv) == 0 || (len(argv) == 1 && (argv[0] == "--help" || argv[0] == "-h")) {
		return nil, nil, formatAppHelp(a), "", ""
	}
	if len(argv) == 1 && (argv[0] == "--version" || argv[0] == "-v") {
		return nil, nil, "", formatVersion(a), ""
	}

	token := argv[0]
	rest := argv[1:]

	// Check groups first
	if grp, ok := a.groups[token]; ok {
		if len(rest) == 0 || (len(rest) == 1 && (rest[0] == "--help" || rest[0] == "-h")) {
			return nil, nil, formatGroupHelp(a, grp), "", ""
		}
		subToken := rest[0]
		rest = rest[1:]
		cmd, ok := grp.Commands[subToken]
		if !ok {
			return nil, nil, "", "", fmt.Sprintf("unknown command '%s'", subToken)
		}
		// Check command-level --help
		if len(rest) == 1 && (rest[0] == "--help" || rest[0] == "-h") {
			prefix := grp.Name + " "
			return nil, nil, formatCommandHelp(a, cmd, prefix), "", ""
		}
		kwargs, err := parseCommand(cmd, rest)
		if err != "" {
			return nil, nil, "", "", err
		}
		return cmd, kwargs, "", "", ""
	}

	// Check commands
	if cmd, ok := a.commands[token]; ok {
		if len(rest) == 1 && (rest[0] == "--help" || rest[0] == "-h") {
			return nil, nil, formatCommandHelp(a, cmd, ""), "", ""
		}
		kwargs, err := parseCommand(cmd, rest)
		if err != "" {
			return nil, nil, "", "", err
		}
		return cmd, kwargs, "", "", ""
	}

	return nil, nil, "", "", fmt.Sprintf("unknown command '%s'", token)
}

// buildAndValidateCommand creates and validates a Command.
func buildAndValidateCommand(name, help string, handler func(map[string]interface{}), envPrefix string, opts []CmdOption) *Command {
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

	// Check duplicate flag names
	seenFlags := make(map[string]bool)
	for _, f := range allFlags {
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
