// Package strictcli is a strict, zero-dependency CLI framework for Go with mandatory help text, type-safe flags, groups, and schema export.
package strictcli

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
)

// FlagType represents the type of a flag value.
// Scalar types: TypeStr, TypeBool, TypeInt, TypeFloat.
// Compound types encode the item/value type in the upper bits:
// list types = 0x100 | scalar, dict types = 0x200 | scalar.
type FlagType int

const (
	TypeStr   FlagType = iota
	TypeBool  FlagType = iota
	TypeInt   FlagType = iota
	TypeFloat FlagType = iota

	// Compound type bit flags
	listBit FlagType = 0x100
	dictBit FlagType = 0x200

	// List types: a repeatable flag whose items are coerced to the element type.
	TypeListStr   FlagType = listBit | TypeStr
	TypeListInt   FlagType = listBit | TypeInt
	TypeListFloat FlagType = listBit | TypeFloat

	// Dict types: a repeatable key=value flag whose values are coerced to the value type.
	TypeDictStr   FlagType = listBit | dictBit | TypeStr
	TypeDictInt   FlagType = listBit | dictBit | TypeInt
	TypeDictFloat FlagType = listBit | dictBit | TypeFloat
)

// IsScalarType returns true for the four primitive types.
func IsScalarType(t FlagType) bool {
	return t == TypeStr || t == TypeBool || t == TypeInt || t == TypeFloat
}

// IsListType returns true for list compound types.
func IsListType(t FlagType) bool {
	return t&listBit != 0 && t&dictBit == 0
}

// IsDictType returns true for dict compound types.
func IsDictType(t FlagType) bool {
	return t&dictBit != 0
}

// IsCompoundType returns true for any compound type (list or dict).
func IsCompoundType(t FlagType) bool {
	return IsListType(t) || IsDictType(t)
}

// ItemType returns the scalar element type for a compound type.
// For scalar types, returns the type itself.
func ItemType(t FlagType) FlagType {
	return t & 0x0F
}

// ListOf creates a list type from a scalar item type.
// Panics if the item type is not one of TypeStr, TypeInt, TypeFloat.
func ListOf(itemType FlagType) FlagType {
	switch itemType {
	case TypeStr, TypeInt, TypeFloat:
		return listBit | itemType
	default:
		panic(fmt.Sprintf("ListOf: item type must be str, int, or float, got %d", itemType))
	}
}

// DictOf creates a dict type from a scalar value type.
// Panics if the value type is not one of TypeStr, TypeInt, TypeFloat.
func DictOf(valueType FlagType) FlagType {
	switch valueType {
	case TypeStr, TypeInt, TypeFloat:
		return listBit | dictBit | valueType
	default:
		panic(fmt.Sprintf("DictOf: value type must be str, int, or float, got %d", valueType))
	}
}

// Flag represents a --flag declaration.
type Flag struct {
	Name         string
	Type         FlagType
	Help         string
	Short        string
	Default      interface{} // nil means no default (required for str/int)
	Env          string
	Prefixed     bool
	Negatable    bool
	Choices      []interface{}
	Validate     func(interface{}) error
	Repeatable   bool
	Unique       bool
	EnvSeparator string

	// ConflictMode is the per-flag override of the app config conflict mode.
	// Empty string (with hasConflictMode false) means "inherit the app default".
	// When set, must be "cli-wins" or "error". Applies to flags only:
	// standalone ConfigFields have no CLI/env conflict surface, and a
	// flag-colliding ConfigField inherits the flag's handling.
	ConflictMode string

	// hasDefault distinguishes between "default explicitly set to nil" and "no default"
	hasDefault      bool
	hasUnique       bool
	hasConflictMode bool
}

// Arg represents a positional argument.
type Arg struct {
	Name       string
	Help       string
	Required   bool
	Default    interface{}
	IsVariadic bool
	Type       FlagType
	Choices    []interface{}

	hasDefault bool
}

// FlagSet is a reusable bundle of flags.
type FlagSet struct {
	Name  string
	Flags []Flag
}

// MutexGroup is a group of mutually exclusive flags. Exactly one must be provided.
type MutexGroup struct {
	Flags []Flag
}

// CoRequired declares flags that must all appear together or none.
type CoRequired struct {
	Flags []string
}

// Requires declares that one flag depends on another being present.
type Requires struct {
	Flag      string
	DependsOn string
}

// Implies declares that providing one bool flag automatically sets another bool flag to a value.
// If the user explicitly provides a contradicting value for the target, it is a parse error.
type Implies struct {
	Flag    string
	Implies string
	Value   bool
}

// Dependency is either a CoRequired, Requires, or Implies constraint.
type Dependency interface {
	isDependency()
}

func (CoRequired) isDependency() {}
func (Requires) isDependency()   {}
func (Implies) isDependency()    {}

// InfraRootPath is an opaque marker produced by RelativeToRoot. It represents a
// filesystem path built from a declared infrastructure root (identified by its
// env var name) joined with zero or more path parts. Config-path markers resolve
// eagerly at construction; flag-default markers resolve when defaults are applied
// at parse time. A marker referencing an undeclared root is a registration-time
// hard error.
type InfraRootPath struct {
	envVar string
	parts  []string
}

// RelativeToRoot returns a marker representing a path relative to a declared
// infrastructure root. envVar names the root (declared via WithInfraRoot); parts
// are joined onto the resolved root path. Accepted by flag Default(...) and
// WithConfigPathRelativeToRoot.
func RelativeToRoot(envVar string, parts ...string) InfraRootPath {
	return InfraRootPath{envVar: envVar, parts: append([]string{}, parts...)}
}

// infraRootDecl is a raw WithInfraRoot declaration, collected during the options
// loop and resolved eagerly after the loop completes in NewApp.
type infraRootDecl struct {
	envVar      string
	defaultPath string
}

// PassthroughHandler is the handler type for passthrough commands.
type PassthroughHandler func(ctx *Context, name string, args []string, globals map[string]interface{}) int

// Command is a leaf command with a handler.
type Command struct {
	Name               string
	Help               string
	Handler            func(ctx *Context, kwargs map[string]interface{}) Outcome
	flags              []Flag
	args               []Arg
	flagSets           []FlagSet
	mutex              []MutexGroup
	dependencies       []Dependency
	tags               []string
	configFields       []string // bound config field names
	Passthrough        bool
	PassthroughHandler PassthroughHandler
	Hidden             bool
	Interactive        bool
}

// deprecatedCmd is a declaration-only command that prints a message and exits 1.
type deprecatedCmd struct {
	Name    string
	Message string
}

// Group is a container for nested commands and subgroups (arbitrary depth).
type Group struct {
	Name            string
	Help            string
	Commands        map[string]*Command
	Groups          map[string]*Group
	tags            []string
	accumulatedTags []string // own tags union all ancestor tags; passed as inheritedTags to children
	envPrefix       string

	// app is a reference to the root App (needed for collision/infra validation)
	app *App

	// globalFlags is a reference to the app's global flags for collision checking
	globalFlags []Flag

	// order preserves insertion order for help display
	order      []string
	groupOrder []string

	deprecated    []deprecatedCmd
	deprecatedMap map[string]string

	Hidden bool
}

// Result is returned by App.Test().
type Result struct {
	Stdout   string
	Stderr   string
	ExitCode int
	Data     interface{}
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

	deprecated    []deprecatedCmd
	deprecatedMap map[string]string

	configEnabled       bool
	configPathOverride  string
	configFormat        string
	configData          map[string]interface{}
	configFields        map[string]*ConfigField
	configFieldOrder    []string
	frameworkFields     map[string]*ConfigField
	frameworkFieldOrder []string
	noDefaultConfigPath bool

	checksEnabled       bool
	checksPath          string
	checksEmbed         []byte
	checkDefs           map[string]*checkDef
	checkOrder          []string // sorted check names for deterministic listing
	checkContextFactory func() CheckContext

	// Check-provider hook state. Providers populate the registry lazily at the
	// first registry read (materialization), memoized per cwd. See
	// check_provider.go for the mechanics.
	checkProviders          []func() []CheckSpec
	providerMaterialized    bool            // true once providers ran for providerMaterializedCwd
	providerMaterializedCwd string          // os.Getwd() at last materialization
	providerSourcedNames    map[string]bool // def names added by providers (dropped on re-materialization)

	stdinConsumedBy *string           // tracks which flag consumed stdin via @-
	tagContracts    map[string]string // tag name -> required flag name

	// configParseErr stores a config parse error for config show to pick up.
	// Set when a config subcommand is routed and the config file was malformed.
	configParseErr string

	// configConflictMode controls whether config+cli and config+env overlaps
	// are hard errors. Valid values: "cli-wins" (default), "error".
	configConflictMode string

	// Infrastructure env vars (location roots + handshake signals).
	// infraRootDecls holds raw WithInfraRoot declarations; they are resolved
	// eagerly in NewApp (post-options) into infraRoots. Resolution never
	// consults the hermetic flag: infra vars have no argv dependency, which is
	// WHY eager construction-time resolution is sound (and hermetic-immune).
	infraRootDecls   []infraRootDecl
	infraRoots       map[string]string // env var -> resolved absolute path
	infraRootOrder   []string          // env var names in declaration order
	infraRootFromEnv map[string]bool   // env var -> value came from the env var (vs default)
	configPathRef    *InfraRootPath    // set by WithConfigPathRelativeToRoot

	// Handshake env vars: cross-tool protocol signals. No default, no eager
	// resolution -- read live via os.LookupEnv at access time.
	handshakeEnvs  map[string]string // env var -> help
	handshakeOrder []string          // env var names in declaration order

	// Test-coverage instrumentation. When enabled, every Test() and Call()
	// invocation records the resolved command path to per-process shard files
	// so a check can verify that every command in the surface has been exercised.
	testCoverage     bool
	coverageShardFmt string // ".strictcli/coverage/<pid>-{n}.jsonl"
	coverageCounter  int
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

// WithConfig enables config file support.
func WithConfig() AppOption {
	return func(a *App) {
		a.configEnabled = true
	}
}

// WithConfigPath overrides the default config file path.
func WithConfigPath(path string) AppOption {
	return func(a *App) {
		a.configPathOverride = path
	}
}

// WithConfigFormat sets the config file format ("json" or "toml").
func WithConfigFormat(format string) AppOption {
	return func(a *App) {
		a.configFormat = format
	}
}

// WithNoDefaultConfigPath makes the app load NO config file unless
// --config is explicitly passed on the command line. Without this
// option (the default), the app loads from the XDG default path.
func WithNoDefaultConfigPath() AppOption {
	return func(a *App) {
		a.noDefaultConfigPath = true
	}
}

// WithConfigConflictMode sets the conflict resolution mode for config values.
// Valid values: "cli-wins" (default) and "error".
// In "error" mode, a flag set by both config AND cli (or config AND env)
// is a hard error. Implied sources are excluded from conflict checks.
func WithConfigConflictMode(mode string) AppOption {
	return func(a *App) {
		if mode != "cli-wins" && mode != "error" {
			panic(fmt.Sprintf("WithConfigConflictMode: mode must be \"cli-wins\" or \"error\", got %q", mode))
		}
		a.configConflictMode = mode
	}
}

// WithInfraRoot declares an infrastructure location root: an env var that, when
// set, overrides defaultPath as the base directory for the tool's data. Multiple
// roots are allowed (keyed by env var name). Roots are resolved eagerly at
// construction and are immune to --hermetic (hermetic suppresses config and
// behavioral env, never location). A leading ~ in the value or default is
// expanded to the user's home directory.
func WithInfraRoot(envVar, defaultPath string) AppOption {
	return func(a *App) {
		a.infraRootDecls = append(a.infraRootDecls, infraRootDecl{envVar: envVar, defaultPath: defaultPath})
	}
}

// WithHandshakeEnv declares a handshake env var: a cross-tool protocol signal set
// by the invoking process. It has no default and no resolution semantics beyond
// "read live at access time" via ctx.InfraValue.
func WithHandshakeEnv(envVar, help string) AppOption {
	return func(a *App) {
		if strings.TrimSpace(help) == "" {
			panic(fmt.Sprintf("handshake env var %q: help must be a non-empty string", envVar))
		}
		if a.handshakeEnvs == nil {
			a.handshakeEnvs = make(map[string]string)
		}
		if _, dup := a.handshakeEnvs[envVar]; dup {
			panic(fmt.Sprintf("duplicate handshake env var %q", envVar))
		}
		a.handshakeEnvs[envVar] = help
		a.handshakeOrder = append(a.handshakeOrder, envVar)
	}
}

// WithConfigPathRelativeToRoot overrides the config file path with a location
// relative to a declared infrastructure root. The marker is resolved eagerly at
// construction into the absolute config path override.
func WithConfigPathRelativeToRoot(envVar string, parts ...string) AppOption {
	return func(a *App) {
		ref := RelativeToRoot(envVar, parts...)
		a.configPathRef = &ref
	}
}

// WithChecks enables the check system with an explicit path to checks.toml.
func WithChecks(path string) AppOption {
	return func(a *App) {
		a.checksPath = path
	}
}

// WithChecksEmbed enables the check system with inline TOML data (e.g., from //go:embed).
func WithChecksEmbed(data []byte) AppOption {
	return func(a *App) {
		a.checksEmbed = data
	}
}

// WithTestCoverage enables CLI test-coverage instrumentation. Every Test() and
// Call() invocation records the resolved command path to per-process shard files
// (.strictcli/coverage/<pid>-<n>.jsonl). A built-in cli-test-coverage check
// (auto-registered via the provider mechanism) merges shards and hard-FAILs
// listing every command with zero coverage.
func WithTestCoverage() AppOption {
	return func(a *App) {
		a.testCoverage = true
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
		if vals == nil {
			f.Choices = []interface{}{}
		} else {
			f.Choices = vals
		}
	}
}

// Repeatable marks a flag as accepting multiple occurrences.
func Repeatable() FlagOption {
	return func(f *Flag) {
		f.Repeatable = true
	}
}

// Unique controls whether a repeatable flag rejects duplicate values.
func Unique(b bool) FlagOption {
	return func(f *Flag) {
		f.Unique = b
		f.hasUnique = true
	}
}

// ConflictMode sets the per-flag config conflict mode, overriding the app-level
// default (WithConfigConflictMode). Must be "cli-wins" or "error". This applies
// only to flags; standalone ConfigFields have no CLI/env conflict surface, and a
// flag-colliding ConfigField inherits the flag's handling.
func ConflictMode(mode string) FlagOption {
	return func(f *Flag) {
		if mode != "cli-wins" && mode != "error" {
			panic(fmt.Sprintf("ConflictMode: mode must be \"cli-wins\" or \"error\", got %q", mode))
		}
		f.ConflictMode = mode
		f.hasConflictMode = true
	}
}

// EnvSeparator sets the character used to split an env var value into multiple
// values for a repeatable flag (e.g., "," to split "a,b,c" into ["a","b","c"]).
func EnvSeparator(sep string) FlagOption {
	return func(f *Flag) {
		f.EnvSeparator = sep
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

// ArgType sets the type for a positional argument.
func ArgType(t FlagType) ArgOption {
	return func(a *Arg) {
		a.Type = t
	}
}

// ArgChoices sets the allowed values for a positional argument.
func ArgChoices(vals ...interface{}) ArgOption {
	return func(a *Arg) {
		if vals == nil {
			a.Choices = []interface{}{}
		} else {
			a.Choices = vals
		}
	}
}

// CmdOption configures a Command during registration.
type CmdOption func(*Command)

// WithArgs adds positional arguments to a command.
func WithArgs(args ...Arg) CmdOption {
	return func(c *Command) {
		c.args = append(c.args, args...)
	}
}

// WithFlags adds flags to a command.
func WithFlags(flags ...Flag) CmdOption {
	return func(c *Command) {
		c.flags = append(c.flags, flags...)
	}
}

// WithFlagSets adds flag sets (reusable flag bundles) to a command.
func WithFlagSets(flagSets ...FlagSet) CmdOption {
	return func(c *Command) {
		c.flagSets = append(c.flagSets, flagSets...)
	}
}

// WithMutex adds mutex groups to a command.
func WithMutex(groups ...MutexGroup) CmdOption {
	return func(c *Command) {
		c.mutex = append(c.mutex, groups...)
	}
}

// WithDependencies adds dependency constraints to a command.
func WithDependencies(deps ...Dependency) CmdOption {
	return func(c *Command) {
		c.dependencies = append(c.dependencies, deps...)
	}
}

// WithPassthrough marks a command as passthrough (skips parsing, forwards raw args).
func WithPassthrough(handler PassthroughHandler) CmdOption {
	return func(c *Command) {
		c.Passthrough = true
		c.PassthroughHandler = handler
	}
}

// WithHidden marks a command as hidden (excluded from help but still routable).
func WithHidden() CmdOption {
	return func(c *Command) {
		c.Hidden = true
	}
}

// WithInteractive marks a command as interactive (visible in help but excluded from tool export).
func WithInteractive() CmdOption {
	return func(c *Command) {
		c.Interactive = true
	}
}

// WithConfigFields binds config fields to a command. At startup, bound required
// config fields are validated to be present with correct types in the config file.
// Each field name must exist in app.configFields (validated at Run/Test time).
func WithConfigFields(fields ...string) CmdOption {
	return func(c *Command) {
		c.configFields = append(c.configFields, fields...)
	}
}

// WithTags adds tags to a command.
func WithTags(tags ...string) CmdOption {
	return func(c *Command) {
		seen := make(map[string]bool)
		for _, t := range tags {
			if !identifierRe.MatchString(t) {
				panic(fmt.Sprintf("invalid tag name %q: must match [a-z][a-z0-9-]*", t))
			}
			if !seen[t] {
				c.tags = append(c.tags, t)
				seen[t] = true
			}
		}
	}
}

// validateAndDedup validates tag names and removes duplicates, preserving order.
func validateAndDedup(tags []string) []string {
	if len(tags) == 0 {
		return nil
	}
	seen := make(map[string]bool)
	result := make([]string, 0, len(tags))
	for _, t := range tags {
		if !identifierRe.MatchString(t) {
			panic(fmt.Sprintf("invalid tag name %q: must match [a-z][a-z0-9-]*", t))
		}
		if !seen[t] {
			result = append(result, t)
			seen[t] = true
		}
	}
	return result
}

// mergeTags merges two tag slices, deduplicates, and sorts.
func mergeTags(a, b []string) []string {
	seen := make(map[string]bool)
	for _, t := range a {
		seen[t] = true
	}
	for _, t := range b {
		seen[t] = true
	}
	if len(seen) == 0 {
		return nil
	}
	result := make([]string, 0, len(seen))
	for t := range seen {
		result = append(result, t)
	}
	sort.Strings(result)
	return result
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

// FloatFlag creates a float-typed flag.
func FloatFlag(name, help string, opts ...FlagOption) Flag {
	f := Flag{
		Name:     name,
		Type:     TypeFloat,
		Help:     help,
		Prefixed: true,
	}
	for _, opt := range opts {
		opt(&f)
	}
	validateFlagConfig(&f)
	return f
}

// ListFlag creates a list-typed flag. itemType must be TypeStr, TypeInt, or TypeFloat.
// List flags are automatically repeatable. The Unique option is supported.
// CLI usage: --flag val1 --flag val2 (each value coerced to itemType).
func ListFlag(itemType FlagType, name, help string, opts ...FlagOption) Flag {
	lt := ListOf(itemType) // panics on bad itemType
	f := Flag{
		Name:       name,
		Type:       lt,
		Help:       help,
		Prefixed:   true,
		Repeatable: true,
	}
	for _, opt := range opts {
		opt(&f)
	}
	// List flags are always repeatable; override any explicit Repeatable(false)
	f.Repeatable = true
	validateFlagConfig(&f)
	return f
}

// DictFlag creates a dict-typed flag. valueType must be TypeStr, TypeInt, or TypeFloat.
// Dict flags are automatically repeatable (multiple key=value pairs).
// CLI usage: --flag key=value --flag key2=value2
// Also accepts JSON: --flag '{"key": "value"}'
func DictFlag(valueType FlagType, name, help string, opts ...FlagOption) Flag {
	dt := DictOf(valueType) // panics on bad valueType
	f := Flag{
		Name:       name,
		Type:       dt,
		Help:       help,
		Prefixed:   true,
		Repeatable: true,
	}
	for _, opt := range opts {
		opt(&f)
	}
	// Dict flags are always repeatable
	f.Repeatable = true
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
		Type:     TypeStr,
	}
	for _, opt := range opts {
		opt(&a)
	}
	if a.Required && a.hasDefault {
		panic("required arg cannot have a default")
	}
	// Validate type: scalar types always allowed; list types only on variadic args
	if IsListType(a.Type) {
		if !a.IsVariadic {
			panic(fmt.Sprintf("Arg %q: list type requires variadic=true", a.Name))
		}
		// Item type must be scalar
		item := ItemType(a.Type)
		switch item {
		case TypeStr, TypeInt, TypeFloat:
			// ok
		default:
			panic(fmt.Sprintf("Arg %q: list item type must be str, int, or float", a.Name))
		}
	} else if IsDictType(a.Type) {
		panic(fmt.Sprintf("Arg %q: dict type is not supported on positional arguments", a.Name))
	} else {
		switch a.Type {
		case TypeStr, TypeBool, TypeInt, TypeFloat:
			// ok
		default:
			panic(fmt.Sprintf("Arg.type must be str, bool, int, or float, got %d", a.Type))
		}
	}
	// Validate choices
	if a.Choices != nil {
		if IsListType(a.Type) {
			panic(fmt.Sprintf("Arg %q: choices is incompatible with list type", a.Name))
		}
		if a.Type == TypeBool {
			panic(fmt.Sprintf("Arg %q: choices is incompatible with type=bool", a.Name))
		}
		if len(a.Choices) == 0 {
			panic(fmt.Sprintf("Arg %q: choices must be a non-empty list", a.Name))
		}
		for _, c := range a.Choices {
			switch a.Type {
			case TypeStr:
				if _, ok := c.(string); !ok {
					panic(fmt.Sprintf("Arg %q: choice %v is not of type str", a.Name, c))
				}
			case TypeInt:
				if _, ok := c.(int); !ok {
					panic(fmt.Sprintf("Arg %q: choice %v is not of type int", a.Name, c))
				}
			case TypeFloat:
				if _, ok := c.(float64); !ok {
					panic(fmt.Sprintf("Arg %q: choice %v is not of type float", a.Name, c))
				}
			}
		}
	}
	// Validate default type matches declared type
	if a.hasDefault && a.Default != nil && IsListType(a.Type) {
		slice, ok := a.Default.([]interface{})
		if !ok {
			panic(fmt.Sprintf("Arg %q: list arg default must be a list", a.Name))
		}
		if len(slice) == 0 {
			panic(fmt.Sprintf("Arg %q: explicit empty default is redundant for list args, omit the default", a.Name))
		}
		elemType := ItemType(a.Type)
		typeName := map[FlagType]string{TypeStr: "str", TypeInt: "int", TypeFloat: "float"}[elemType]
		for i, elem := range slice {
			valid := false
			switch elemType {
			case TypeStr:
				_, valid = elem.(string)
			case TypeInt:
				_, valid = elem.(int)
			case TypeFloat:
				if intVal, isInt := elem.(int); isInt {
					// Auto-coerce int to float64, mirroring list flag defaults
					slice[i] = float64(intVal)
					valid = true
				} else {
					_, valid = elem.(float64)
				}
			}
			if !valid {
				panic(fmt.Sprintf("Arg %q: default element %d is not of type %s", a.Name, i, typeName))
			}
		}
	} else if a.hasDefault && a.Default != nil {
		switch a.Type {
		case TypeStr:
			if _, ok := a.Default.(string); !ok {
				var gotType string
				switch a.Default.(type) {
				case bool:
					gotType = "bool"
				case int:
					gotType = "int"
				default:
					gotType = fmt.Sprintf("%T", a.Default)
				}
				panic(fmt.Sprintf("Arg %q: type=str requires a str default, got '%s'", a.Name, gotType))
			}
		case TypeInt:
			if _, ok := a.Default.(int); !ok {
				var gotType string
				switch a.Default.(type) {
				case string:
					gotType = "str"
				case bool:
					gotType = "bool"
				default:
					gotType = fmt.Sprintf("%T", a.Default)
				}
				panic(fmt.Sprintf("Arg %q: type=int requires an int default, got '%s'", a.Name, gotType))
			}
		case TypeFloat:
			if _, ok := a.Default.(float64); !ok {
				var gotType string
				switch a.Default.(type) {
				case string:
					gotType = "str"
				case bool:
					gotType = "bool"
				case int:
					gotType = "int"
				default:
					gotType = fmt.Sprintf("%T", a.Default)
				}
				panic(fmt.Sprintf("Arg %q: type=float requires a float default, got '%s'", a.Name, gotType))
			}
		case TypeBool:
			if _, ok := a.Default.(bool); !ok {
				var gotType string
				switch a.Default.(type) {
				case string:
					gotType = "str"
				case int:
					gotType = "int"
				default:
					gotType = fmt.Sprintf("%T", a.Default)
				}
				panic(fmt.Sprintf("Arg %q: type=bool requires a bool default, got '%s'", a.Name, gotType))
			}
		}
	}
	// Validate default is in choices
	if a.Choices != nil && a.hasDefault && a.Default != nil {
		found := false
		for _, c := range a.Choices {
			if a.Default == c {
				found = true
				break
			}
		}
		if !found {
			choiceParts := make([]string, len(a.Choices))
			for i, c := range a.Choices {
				choiceParts[i] = fmt.Sprintf("'%v'", c)
			}
			panic(fmt.Sprintf("Arg %q: default '%v' is not in choices [%s]", a.Name, a.Default, strings.Join(choiceParts, ", ")))
		}
	}
	return a
}

// validateFlagConfig panics on invalid flag configuration (programmer error).
func validateFlagConfig(f *Flag) {
	if strings.TrimSpace(f.Help) == "" {
		panic(fmt.Sprintf("Flag.help must be a non-empty string"))
	}
	if f.Name == "force" {
		panic(fmt.Sprintf("flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'"))
	}
	if strings.HasPrefix(f.Name, "no-") {
		panic(fmt.Sprintf("flag '%s': names starting with 'no-' are reserved for the negation system; use a positive name instead", f.Name))
	}
	if f.Repeatable && f.Type == TypeBool {
		panic(fmt.Sprintf("Flag %q: repeatable is incompatible with type=bool", f.Name))
	}
	// Compound types: choices not supported
	if IsCompoundType(f.Type) && f.Choices != nil {
		panic(fmt.Sprintf("Flag %q: choices is incompatible with compound types (list/dict)", f.Name))
	}
	// Unique requires repeatable; repeatable requires explicit unique
	if f.Repeatable && !f.hasUnique {
		panic(fmt.Sprintf("Flag %q: repeatable requires explicit unique (unique=True or unique=False)", f.Name))
	}
	if f.hasUnique && !f.Repeatable {
		panic(fmt.Sprintf("Flag %q: unique requires repeatable=True", f.Name))
	}
	// Dict flags: env_separator for dicts means JSON parse from env (env_separator not used
	// for splitting). For list types, env_separator works as before.
	// EnvSeparator validations
	if f.EnvSeparator != "" && !f.Repeatable {
		panic(fmt.Sprintf("Flag %q: env_separator requires repeatable=True", f.Name))
	}
	if f.EnvSeparator != "" && f.Env == "" {
		panic(fmt.Sprintf("Flag %q: env_separator requires env", f.Name))
	}
	if f.Repeatable && f.Env != "" && f.EnvSeparator == "" && !IsDictType(f.Type) {
		panic(fmt.Sprintf("Flag %q: repeatable flag with env requires env_separator", f.Name))
	}
	if f.EnvSeparator != "" && len(f.EnvSeparator) != 1 {
		panic(fmt.Sprintf("Flag %q: env_separator must be a single character", f.Name))
	}
	if f.EnvSeparator == "\\" {
		panic(fmt.Sprintf("Flag %q: env_separator cannot be a backslash", f.Name))
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
			case TypeFloat:
				if _, ok := c.(float64); !ok {
					panic(fmt.Sprintf("Flag %q: choice %v is not of type float", f.Name, c))
				}
			}
		}
	}
	// Validate int default type
	if f.Type == TypeInt && f.hasDefault && f.Default != nil {
		if !f.Repeatable {
			if _, ok := f.Default.(int); !ok {
				var gotType string
				switch f.Default.(type) {
				case string:
					gotType = "str"
				case bool:
					gotType = "bool"
				default:
					gotType = fmt.Sprintf("%T", f.Default)
				}
				panic(fmt.Sprintf("Flag %q: type=int requires an int default, got '%s'", f.Name, gotType))
			}
		}
	}
	// Validate float default type
	if f.Type == TypeFloat && f.hasDefault && f.Default != nil {
		if !f.Repeatable {
			if _, ok := f.Default.(float64); !ok {
				var gotType string
				switch f.Default.(type) {
				case string:
					gotType = "str"
				case bool:
					gotType = "bool"
				case int:
					gotType = "int"
				default:
					gotType = fmt.Sprintf("%T", f.Default)
				}
				panic(fmt.Sprintf("Flag %q: type=float requires a float default, got '%s'", f.Name, gotType))
			}
		}
	}
	// Validate dict flag defaults: must be map[string]interface{} with correct value types
	if IsDictType(f.Type) && f.hasDefault && f.Default != nil {
		m, ok := f.Default.(map[string]interface{})
		if !ok {
			panic(fmt.Sprintf("Flag %q: dict flag default must be a map[string]interface{}", f.Name))
		}
		if len(m) == 0 {
			panic(fmt.Sprintf("Flag %q: explicit empty default is redundant for dict flags, omit the default", f.Name))
		}
		valType := ItemType(f.Type)
		for k, v := range m {
			if errStr := validateScalarType(v, valType); errStr != "" {
				panic(fmt.Sprintf("Flag %q: default value for key %q: %s", f.Name, k, errStr))
			}
		}
	} else if IsListType(f.Type) && f.hasDefault && f.Default != nil {
		// List flag defaults: must be []interface{} with correct item types
		slice, ok := f.Default.([]interface{})
		if !ok {
			panic(fmt.Sprintf("Flag %q: list flag default must be a []interface{}", f.Name))
		}
		if len(slice) == 0 {
			panic(fmt.Sprintf("Flag %q: explicit empty default is redundant for list flags, omit the default", f.Name))
		}
		elemType := ItemType(f.Type)
		for i, elem := range slice {
			if errStr := validateScalarType(elem, elemType); errStr != "" {
				panic(fmt.Sprintf("Flag %q: default element %d: %s", f.Name, i, errStr))
			}
			// Auto-coerce int to float64 for float list defaults
			if elemType == TypeFloat {
				if intVal, ok := elem.(int); ok {
					slice[i] = float64(intVal)
				}
			}
		}
	} else if f.Repeatable && !IsCompoundType(f.Type) && f.hasDefault && f.Default != nil {
		// Validate repeatable scalar flag defaults
		slice, ok := f.Default.([]interface{})
		if !ok {
			panic(fmt.Sprintf("Flag %q: repeatable flag default must be a list", f.Name))
		}
		if len(slice) == 0 {
			panic(fmt.Sprintf("Flag %q: explicit empty default is redundant for repeatable flags, omit the default", f.Name))
		}
		for i, elem := range slice {
			switch f.Type {
			case TypeStr:
				if _, ok := elem.(string); !ok {
					panic(fmt.Sprintf("Flag %q: default element %d is not of type str", f.Name, i))
				}
			case TypeInt:
				if _, ok := elem.(int); !ok {
					panic(fmt.Sprintf("Flag %q: default element %d is not of type int", f.Name, i))
				}
			case TypeFloat:
				if intVal, ok := elem.(int); ok {
					slice[i] = float64(intVal)
				} else if _, ok := elem.(float64); !ok {
					panic(fmt.Sprintf("Flag %q: default element %d is not of type float", f.Name, i))
				}
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
			// Repeatable/list/dict defaults to empty (slice or map)
		}
		// No default: required (nil Default) — same for all types including bool
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
			choiceParts := make([]string, len(f.Choices))
			for i, c := range f.Choices {
				choiceParts[i] = fmt.Sprintf("'%v'", c)
			}
			panic(fmt.Sprintf("Flag %q: default '%v' is not in choices [%s]", f.Name, f.Default, strings.Join(choiceParts, ", ")))
		}
	}
}

// validateScalarType checks if a value matches a scalar FlagType.
// Returns an error message or empty string on success.
func validateScalarType(v interface{}, t FlagType) string {
	switch t {
	case TypeStr:
		if _, ok := v.(string); !ok {
			return fmt.Sprintf("expected str, got %s", describeGoType(v))
		}
	case TypeInt:
		if _, ok := v.(int); !ok {
			return fmt.Sprintf("expected int, got %s", describeGoType(v))
		}
	case TypeFloat:
		if _, ok := v.(float64); ok {
			return ""
		}
		if _, ok := v.(int); ok {
			return "" // int is acceptable for float
		}
		return fmt.Sprintf("expected float, got %s", describeGoType(v))
	case TypeBool:
		if _, ok := v.(bool); !ok {
			return fmt.Sprintf("expected bool, got %s", describeGoType(v))
		}
	}
	return ""
}

// --- App ---

// NewApp creates a new CLI application.
func NewApp(name, version, help string, opts ...AppOption) *App {
	if strings.TrimSpace(help) == "" {
		panic("App.help must be a non-empty string")
	}
	a := &App{
		Name:          name,
		Version:       version,
		Help:          help,
		commands:      make(map[string]*Command),
		groups:        make(map[string]*Group),
		deprecatedMap: make(map[string]string),
	}
	for _, opt := range opts {
		opt(a)
	}

	// Resolve infrastructure roots eagerly, immediately after options are
	// applied. Infra vars have no argv dependency, so their resolution is sound
	// at construction time -- and this is precisely WHY it is hermetic-immune:
	// there is no argv yet to consult, so --hermetic (which only suppresses
	// argv-derived config/env behavior) can never affect location roots.
	a.infraRoots = make(map[string]string)
	a.infraRootFromEnv = make(map[string]bool)
	for _, decl := range a.infraRootDecls {
		if _, dup := a.infraRoots[decl.envVar]; dup {
			panic(fmt.Sprintf("duplicate infra root env var %q", decl.envVar))
		}
		if val, ok := os.LookupEnv(decl.envVar); ok {
			a.infraRoots[decl.envVar] = expandTilde(val)
			a.infraRootFromEnv[decl.envVar] = true
		} else {
			a.infraRoots[decl.envVar] = expandTilde(decl.defaultPath)
			a.infraRootFromEnv[decl.envVar] = false
		}
		a.infraRootOrder = append(a.infraRootOrder, decl.envVar)
	}
	// Handshake env vars must not collide with declared roots.
	for _, ev := range a.handshakeOrder {
		if _, isRoot := a.infraRoots[ev]; isRoot {
			panic(fmt.Sprintf("handshake env var %q is already declared as an infra root", ev))
		}
	}
	// Resolve the config-path marker (if any) now that roots exist.
	if a.configPathRef != nil {
		resolved, err := a.resolveInfraPath(*a.configPathRef)
		if err != nil {
			panic(err.Error())
		}
		a.configPathOverride = resolved
	}

	// Default config format to "json" if not set
	if a.configFormat == "" {
		a.configFormat = "json"
	}
	if a.configFormat != "json" && a.configFormat != "toml" {
		fmt.Fprintf(os.Stderr, "App.config_format must be \"json\" or \"toml\", got %q\n", a.configFormat)
		os.Exit(1)
	}
	if a.configEnabled {
		a.registerConfigGroup()
	}
	// Enable check system when WithChecks(path) or WithChecksEmbed(data) was provided
	if a.checksPath != "" && len(a.checksEmbed) > 0 {
		panic("cannot use both WithChecks and WithChecksEmbed")
	}
	if a.checksPath != "" {
		if _, err := os.Stat(a.checksPath); err != nil {
			panic(fmt.Sprintf("checks_path does not exist: %s", a.checksPath))
		}
		appName, defs, order, err := loadChecksToml(a.checksPath)
		if err != nil {
			panic(err.Error())
		}
		if appName != a.Name {
			panic(fmt.Sprintf("checks.toml: app %q does not match app name %q", appName, a.Name))
		}
		a.enableChecks()
		for _, name := range order {
			if err := a.addCheckDef(defs[name]); err != nil {
				panic(err.Error())
			}
		}
	} else if len(a.checksEmbed) > 0 {
		appName, defs, order, err := parseChecksToml(a.checksEmbed)
		if err != nil {
			panic(err.Error())
		}
		if appName != a.Name {
			panic(fmt.Sprintf("checks.toml: app %q does not match app name %q", appName, a.Name))
		}
		a.enableChecks()
		for _, name := range order {
			if err := a.addCheckDef(defs[name]); err != nil {
				panic(err.Error())
			}
		}
	}
	// Test-coverage instrumentation: register built-in provider.
	if a.testCoverage {
		a.coverageShardFmt = fmt.Sprintf(".strictcli/coverage/%d-%%d.jsonl", os.Getpid())
		if err := os.MkdirAll(".strictcli/coverage", 0o755); err != nil {
			panic(fmt.Sprintf("test-coverage: cannot create .strictcli/coverage/: %s", err))
		}
		a.RegisterCheckProvider(a.testCoverageProvider)
	}
	return a
}

// RegisterErrorCheck registers an error-severity check implementation for a
// check declared with severity = "error" in checks.toml. The impl receives an
// *ErrorReporter (which can mint both error- and warn-severity problems) and
// must return a CheckOutcome obtained from that reporter.
//
// Panics if checks are not enabled, the name is not declared, it is already
// registered, or the declared severity is not "error" (see registerCheckImpl).
func (a *App) RegisterErrorCheck(name string, fn func(CheckContext, *ErrorReporter) CheckOutcome) {
	a.registerCheckImpl(name, "error", func(ctx CheckContext) CheckOutcome {
		r := &ErrorReporter{}
		return fn(ctx, r)
	})
}

// RegisterWarnCheck registers a warn-severity check implementation for a check
// declared with severity = "warn" in checks.toml. The impl receives a
// *WarnReporter, which structurally lacks error-minting: a warn check cannot
// produce an error-severity problem, so it can never cascade.
//
// Panics under the same conditions as RegisterErrorCheck, with the severity
// cross-check requiring the declared severity to be "warn".
func (a *App) RegisterWarnCheck(name string, fn func(CheckContext, *WarnReporter) CheckOutcome) {
	a.registerCheckImpl(name, "warn", func(ctx CheckContext) CheckOutcome {
		r := &WarnReporter{}
		return fn(ctx, r)
	})
}

// registerCheckImpl is the single registration chokepoint shared by
// RegisterErrorCheck and RegisterWarnCheck. It enforces the double-entry
// contract (declared vs registered) and cross-checks the registration FORM
// against the TOML-declared severity so that, e.g., calling RegisterErrorCheck
// on a severity="warn" definition is a hard error.
func (a *App) registerCheckImpl(name, form string, run func(CheckContext) CheckOutcome) {
	if !a.checksEnabled {
		panic(fmt.Sprintf("cannot register check %q: checks not enabled", name))
	}
	def, ok := a.checkDefs[name]
	if !ok {
		panic(fmt.Sprintf("cannot register check %q: not declared in checks.toml", name))
	}
	if def.impl != nil {
		panic(fmt.Sprintf("check %q: duplicate registration", name))
	}
	if def.severity != form {
		used, want := "RegisterErrorCheck", "RegisterWarnCheck"
		if form == "warn" {
			used, want = "RegisterWarnCheck", "RegisterErrorCheck"
		}
		panic(fmt.Sprintf(
			"check %q: declared severity %q in checks.toml but registered via %s; use %s",
			name, def.severity, used, want,
		))
	}
	def.impl = run
	def.implForm = form
}

// SetCheckContext sets the factory function that provides CheckContext to check implementations.
func (a *App) SetCheckContext(factory func() CheckContext) {
	a.checkContextFactory = factory
}

// TagContract declares that any command tagged with the given tag must have a flag
// with the given name. Validated at Run/Test time.
func (a *App) TagContract(tag, requiresFlag string) {
	if !identifierRe.MatchString(tag) {
		panic(fmt.Sprintf("invalid tag name %q: must match [a-z][a-z0-9-]*", tag))
	}
	if a.tagContracts == nil {
		a.tagContracts = make(map[string]string)
	}
	a.tagContracts[tag] = requiresFlag
}

// validateCheckRegistrations checks that all declared checks have been registered.
// Returns an error message listing unregistered checks, or empty string if all are registered.
func (a *App) validateCheckRegistrations() string {
	if !a.checksEnabled {
		return ""
	}
	var missing []string
	for name, def := range a.checkDefs {
		if def.impl == nil {
			missing = append(missing, name)
		}
	}
	if len(missing) == 0 {
		return ""
	}
	sort.Strings(missing)
	return fmt.Sprintf("checks declared in checks.toml but not registered: %s", strings.Join(missing, ", "))
}

// validateConfigFieldBindings checks that all WithConfigFields references point to
// declared config fields. Returns an error message listing violations, or empty
// string if all bindings are valid.
func (a *App) validateConfigFieldBindings() string {
	var violations []string
	// Check top-level commands
	for _, name := range a.cmdOrder {
		cmd := a.commands[name]
		for _, field := range cmd.configFields {
			if a.configFields == nil || a.configFields[field] == nil {
				violations = append(violations, fmt.Sprintf("command %q: config_fields references unknown config field %q", cmd.Name, field))
			}
		}
	}
	// Check commands in groups recursively
	var checkGroup func(g *Group, path string)
	checkGroup = func(g *Group, path string) {
		for _, name := range g.order {
			cmd := g.Commands[name]
			for _, field := range cmd.configFields {
				if a.configFields == nil || a.configFields[field] == nil {
					violations = append(violations, fmt.Sprintf("command %q: config_fields references unknown config field %q", cmd.Name, field))
				}
			}
		}
		for _, name := range g.groupOrder {
			checkGroup(g.Groups[name], path+name+" ")
		}
	}
	for _, name := range a.groupOrder {
		checkGroup(a.groups[name], name+" ")
	}
	if len(violations) == 0 {
		return ""
	}
	sort.Strings(violations)
	return strings.Join(violations, "; ")
}

// validateTagContracts checks that commands with a given tag have the required flag.
// Returns an error message listing violations, or empty string if all contracts are satisfied.
func (a *App) validateTagContracts() string {
	if len(a.tagContracts) == 0 {
		return ""
	}
	var violations []string
	// Check top-level commands
	for _, cmd := range a.commands {
		if v := checkCommandTagContract(cmd, a.tagContracts, a.globalFlags); v != "" {
			violations = append(violations, v)
		}
	}
	// Check commands in groups recursively
	for _, g := range a.groups {
		violations = append(violations, checkGroupTagContracts(g, a.tagContracts, a.globalFlags)...)
	}
	if len(violations) == 0 {
		return ""
	}
	sort.Strings(violations)
	return strings.Join(violations, "; ")
}

func checkCommandTagContract(cmd *Command, contracts map[string]string, globalFlags []Flag) string {
	if cmd.Passthrough {
		return ""
	}
	for _, tag := range cmd.tags {
		requiredFlag, ok := contracts[tag]
		if !ok {
			continue
		}
		found := false
		for _, f := range cmd.flags {
			if f.Name == requiredFlag {
				found = true
				break
			}
		}
		if !found {
			for _, f := range globalFlags {
				if f.Name == requiredFlag {
					found = true
					break
				}
			}
		}
		if !found {
			return fmt.Sprintf("command %q: tag %q requires flag \"--%s\"", cmd.Name, tag, requiredFlag)
		}
	}
	return ""
}

func checkGroupTagContracts(g *Group, contracts map[string]string, globalFlags []Flag) []string {
	var violations []string
	for _, cmd := range g.Commands {
		if v := checkCommandTagContract(cmd, contracts, globalFlags); v != "" {
			violations = append(violations, v)
		}
	}
	for _, sub := range g.Groups {
		violations = append(violations, checkGroupTagContracts(sub, contracts, globalFlags)...)
	}
	return violations
}

// Command registers a top-level command.
// checkFlagConfigFieldDefault panics when a colliding flag and config field have
// conflicting explicit defaults.
//
// A ConfigField whose name equals a flag's param name is a validation-only
// declaration that annotates the flag. Their defaults must agree. The matrix:
// both absent OK; equal OK; both present unequal = error; one absent OK (the
// flag's default wins for rendering). A nil flag default means "no default".
func checkFlagConfigFieldDefault(flagName string, flagDefault interface{}, cf *ConfigField) {
	flagHasDefault := flagDefault != nil
	cfHasDefault := cf.HasDefault && cf.Default != nil
	if flagHasDefault && cfHasDefault && !reflect.DeepEqual(flagDefault, cf.Default) {
		panic(fmt.Sprintf(
			"config field %q collides with flag %q but their defaults disagree (%v vs %v); remove one default or make them equal",
			cf.Name, flagName, cf.Default, flagDefault,
		))
	}
}

// checkCmdFieldCollisions panics if any of the command's flags collides with a
// registered config field whose default disagrees. Config fields registered
// after this command are checked from the App.ConfigField() side instead.
func (a *App) checkCmdFieldCollisions(cmd *Command) {
	if len(a.configFields) == 0 {
		return
	}
	for i := range cmd.flags {
		f := &cmd.flags[i]
		if cf, ok := a.configFields[flagParamName(f.Name)]; ok {
			checkFlagConfigFieldDefault(f.Name, f.Default, cf)
		}
	}
}

// expandTilde expands a leading ~ (as ~ or ~/...) to the user's home directory.
func expandTilde(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			home = os.Getenv("HOME")
		}
		if p == "~" {
			return home
		}
		return filepath.Join(home, p[2:])
	}
	return p
}

// resolveInfraRootPath resolves an InfraRootPath marker against a roots map.
// Returns an error if the marker references an undeclared root.
func resolveInfraRootPath(ref InfraRootPath, roots map[string]string) (string, error) {
	root, ok := roots[ref.envVar]
	if !ok {
		return "", fmt.Errorf("RelativeToRoot references undeclared infra root %q; declare it as an infra root", ref.envVar)
	}
	return filepath.Join(append([]string{root}, ref.parts...)...), nil
}

// resolveInfraPath resolves an InfraRootPath marker against the declared roots.
// Returns an error if the marker references an undeclared root.
func (a *App) resolveInfraPath(ref InfraRootPath) (string, error) {
	return resolveInfraRootPath(ref, a.infraRoots)
}

// validateFlagInfraMarker panics if a flag's Default is an InfraRootPath marker
// that references an undeclared root. Called at registration time so that a
// dangling marker is a construction-time hard error.
func (a *App) validateFlagInfraMarker(f *Flag) {
	if ref, ok := f.Default.(InfraRootPath); ok {
		if _, declared := a.infraRoots[ref.envVar]; !declared {
			panic(fmt.Sprintf("flag %q: RelativeToRoot references undeclared infra root %q; declare it as an infra root", f.Name, ref.envVar))
		}
	}
}

// validateCmdInfraMarkers validates every flag on a command at registration.
func (a *App) validateCmdInfraMarkers(cmd *Command) {
	for i := range cmd.flags {
		a.validateFlagInfraMarker(&cmd.flags[i])
	}
}

// infraAccess snapshots the app's infra data for a Context: resolved roots
// (captured value) plus the set of declared handshake env vars (read live).
func (a *App) infraAccess() *infraAccess {
	if len(a.infraRoots) == 0 && len(a.handshakeEnvs) == 0 {
		return nil
	}
	roots := make(map[string]string, len(a.infraRoots))
	for k, v := range a.infraRoots {
		roots[k] = v
	}
	handshakes := make(map[string]bool, len(a.handshakeEnvs))
	for k := range a.handshakeEnvs {
		handshakes[k] = true
	}
	return &infraAccess{roots: roots, handshakes: handshakes}
}

func (a *App) Command(name, help string, handler func(ctx *Context, kwargs map[string]interface{}) Outcome, opts ...CmdOption) {
	cmd := buildAndValidateCommand(name, help, handler, a.EnvPrefix, a.globalFlags, nil, opts)
	a.checkCmdFieldCollisions(cmd)
	a.validateCmdInfraMarkers(cmd)
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
	// Passthrough commands cannot have flags, args, flag sets, or mutex
	if len(cmd.flags) > 0 || len(cmd.args) > 0 || len(cmd.flagSets) > 0 || len(cmd.mutex) > 0 {
		var parts []string
		if len(cmd.flags) > 0 {
			parts = append(parts, "flags")
		}
		if len(cmd.args) > 0 {
			parts = append(parts, "args")
		}
		if len(cmd.flagSets) > 0 {
			parts = append(parts, "flag sets")
		}
		if len(cmd.mutex) > 0 {
			parts = append(parts, "mutex groups")
		}
		panic(fmt.Sprintf("command %q: passthrough commands cannot have %s", name, strings.Join(parts, ", ")))
	}
	cmd.tags = mergeTags(nil, cmd.tags)
	a.commands[name] = cmd
	a.cmdOrder = append(a.cmdOrder, name)
}

// GlobalFlag registers a global flag on the app.
func (a *App) GlobalFlag(f Flag) {
	// Check reserved names
	if reservedGlobalFlagNames[f.Name] {
		panic(fmt.Sprintf("global flag name %q is reserved", f.Name))
	}
	if f.Short != "" && reservedGlobalFlagNames[f.Short] {
		panic(fmt.Sprintf("global short flag %q is reserved", f.Short))
	}
	// Check for collisions with existing global flags
	for _, gf := range a.globalFlags {
		if gf.Name == f.Name {
			panic(fmt.Sprintf("duplicate global flag name %q", f.Name))
		}
	}
	a.validateFlagInfraMarker(&f)
	a.globalFlags = append(a.globalFlags, f)
}

// Group creates and registers a command group.
func (a *App) Group(name, help string, tags ...string) *Group {
	if strings.TrimSpace(help) == "" {
		panic("Group.help must be a non-empty string")
	}
	validTags := validateAndDedup(tags)
	grp := &Group{
		Name:            name,
		Help:            help,
		Commands:        make(map[string]*Command),
		Groups:          make(map[string]*Group),
		tags:            validTags,
		accumulatedTags: validTags,
		envPrefix:       a.EnvPrefix,
		app:             a,
		globalFlags:     a.globalFlags,
		deprecatedMap:   make(map[string]string),
	}
	a.groups[name] = grp
	a.groupOrder = append(a.groupOrder, name)
	return grp
}

// Group creates and registers a child subgroup.
func (g *Group) Group(name, help string, tags ...string) *Group {
	if strings.TrimSpace(help) == "" {
		panic("Group.help must be a non-empty string")
	}
	if _, ok := g.Commands[name]; ok {
		panic(fmt.Sprintf("group %q collides with an existing command", name))
	}
	if _, ok := g.Groups[name]; ok {
		panic(fmt.Sprintf("group %q is already registered", name))
	}
	validTags := validateAndDedup(tags)
	accumulated := mergeTags(g.accumulatedTags, validTags)
	sub := &Group{
		Name:            name,
		Help:            help,
		Commands:        make(map[string]*Command),
		Groups:          make(map[string]*Group),
		tags:            validTags,
		accumulatedTags: accumulated,
		envPrefix:       g.envPrefix,
		app:             g.app,
		globalFlags:     g.globalFlags,
		deprecatedMap:   make(map[string]string),
	}
	g.Groups[name] = sub
	g.groupOrder = append(g.groupOrder, name)
	return sub
}

// Command registers a command within a group.
func (g *Group) Command(name, help string, handler func(ctx *Context, kwargs map[string]interface{}) Outcome, opts ...CmdOption) {
	if _, ok := g.Groups[name]; ok {
		panic(fmt.Sprintf("command %q collides with an existing group", name))
	}
	cmd := buildAndValidateCommand(name, help, handler, g.envPrefix, g.globalFlags, g.accumulatedTags, opts)
	if g.app != nil {
		g.app.checkCmdFieldCollisions(cmd)
		g.app.validateCmdInfraMarkers(cmd)
	}
	g.Commands[name] = cmd
	g.order = append(g.order, name)
}

// Deprecated registers a deprecated command on the app.
// Invoking a deprecated command prints the message to stderr and exits 1.
func (a *App) Deprecated(name, message string) {
	if strings.TrimSpace(name) == "" {
		panic("deprecated command name must be a non-empty string")
	}
	if strings.TrimSpace(message) == "" {
		panic(fmt.Sprintf("deprecated command %q: message must not be empty", name))
	}
	if _, ok := a.commands[name]; ok {
		panic(fmt.Sprintf("deprecated command %q collides with an existing command", name))
	}
	if _, ok := a.groups[name]; ok {
		panic(fmt.Sprintf("deprecated command %q collides with an existing group", name))
	}
	if _, ok := a.deprecatedMap[name]; ok {
		panic(fmt.Sprintf("deprecated command %q is already registered", name))
	}
	a.deprecated = append(a.deprecated, deprecatedCmd{Name: name, Message: message})
	a.deprecatedMap[name] = message
}

// Deprecated registers a deprecated subcommand on the group.
// Invoking a deprecated subcommand prints the message to stderr and exits 1.
func (g *Group) Deprecated(name, message string) {
	if strings.TrimSpace(name) == "" {
		panic("deprecated command name must be a non-empty string")
	}
	if strings.TrimSpace(message) == "" {
		panic(fmt.Sprintf("deprecated command %q: message must not be empty", name))
	}
	if _, ok := g.Commands[name]; ok {
		panic(fmt.Sprintf("deprecated command %q collides with an existing command", name))
	}
	if _, ok := g.Groups[name]; ok {
		panic(fmt.Sprintf("deprecated command %q collides with an existing group", name))
	}
	if _, ok := g.deprecatedMap[name]; ok {
		panic(fmt.Sprintf("deprecated command %q is already registered", name))
	}
	g.deprecated = append(g.deprecated, deprecatedCmd{Name: name, Message: message})
	g.deprecatedMap[name] = message
}

// Commands returns the registered top-level commands.
func (a *App) Commands() map[string]*Command {
	return a.commands
}

// Groups returns the registered command groups.
func (a *App) Groups() map[string]*Group {
	return a.groups
}

// GlobalFlags returns the registered global flags.
func (a *App) GlobalFlags() []Flag {
	return a.globalFlags
}

// DeprecatedCommands returns the deprecated command map (name -> message).
func (a *App) DeprecatedCommands() map[string]string {
	return a.deprecatedMap
}

// DeprecatedCommands returns the deprecated subcommand map (name -> message).
func (g *Group) DeprecatedCommands() map[string]string {
	return g.deprecatedMap
}

// Run executes the CLI, reading from os.Args.
func (a *App) Run() {
	if errMsg := a.validateCheckRegistrations(); errMsg != "" {
		fmt.Fprintln(os.Stderr, "error: "+errMsg)
		os.Exit(1)
	}
	if errMsg := a.validateTagContracts(); errMsg != "" {
		fmt.Fprintln(os.Stderr, "error: "+errMsg)
		os.Exit(1)
	}
	if errMsg := a.validateConfigFieldBindings(); errMsg != "" {
		fmt.Fprintln(os.Stderr, "error: "+errMsg)
		os.Exit(1)
	}
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
	if pr.dumpSchema {
		path, err := writeSchema(a)
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %s\n", err)
			os.Exit(1)
		}
		fmt.Println(path)
		os.Exit(0)
	}
	if pr.serveMCP {
		a.ServeMCP()
		os.Exit(0)
	}
	if pr.parseErr != "" {
		fmt.Fprintln(os.Stderr, "error: "+pr.parseErr)
		prefix := pr.commandPrefix
		if prefix == "" {
			prefix = a.Name
		}
		fmt.Fprintf(os.Stderr, "try '%s --help'\n", prefix)
		os.Exit(1)
	}

	if pr.cmd.Passthrough {
		ctx := newContext(os.Stdout, os.Stderr, pr.sources, a.infraAccess())
		code := pr.cmd.PassthroughHandler(ctx, pr.cmd.Name, pr.passthroughArgs, pr.globalKwargs)
		os.Exit(code)
	}

	ctx := newContext(os.Stdout, os.Stderr, pr.sources, a.infraAccess())
	outcome := pr.cmd.Handler(ctx, pr.kwargs)
	if outcome.data != nil {
		data, err := json.Marshal(outcome.data)
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: failed to marshal result data: %s\n", err)
			os.Exit(1)
		}
		fmt.Println(string(data))
	}
	os.Exit(outcome.code)
}

// Test runs the CLI with the given argv, capturing output and exit code.
func (a *App) Test(argv []string) Result {
	if errMsg := a.validateCheckRegistrations(); errMsg != "" {
		return Result{Stderr: "error: " + errMsg + "\n", ExitCode: 1}
	}
	if errMsg := a.validateTagContracts(); errMsg != "" {
		return Result{Stderr: "error: " + errMsg + "\n", ExitCode: 1}
	}
	if errMsg := a.validateConfigFieldBindings(); errMsg != "" {
		return Result{Stderr: "error: " + errMsg + "\n", ExitCode: 1}
	}
	pr := a.doParse(argv)

	if pr.helpText != "" {
		return Result{Stdout: pr.helpText + "\n", ExitCode: 0}
	}
	if pr.versionText != "" {
		return Result{Stdout: pr.versionText + "\n", ExitCode: 0}
	}
	if pr.dumpSchema {
		path, err := writeSchema(a)
		if err != nil {
			return Result{Stderr: fmt.Sprintf("error: %s\n", err), ExitCode: 1}
		}
		return Result{Stdout: path + "\n", ExitCode: 0}
	}
	if pr.serveMCP {
		// In Test mode, MCP mode cannot be exercised (it requires stdin/stdout).
		// Use serveMCPIO directly for testing.
		return Result{Stderr: "error: --mcp cannot be used with Test(); use serveMCPIO directly\n", ExitCode: 1}
	}
	if pr.parseErr != "" {
		prefix := pr.commandPrefix
		if prefix == "" {
			prefix = a.Name
		}
		stderr := fmt.Sprintf("error: %s\ntry '%s --help'\n", pr.parseErr, prefix)
		return Result{Stderr: stderr, ExitCode: 1}
	}

	// Record test-coverage hit (command-level only).
	if a.testCoverage && pr.cmdPath != "" {
		a.recordCoverage(pr.cmdPath)
	}

	// Capture stdout/stderr from handler
	oldStdout := os.Stdout
	oldStderr := os.Stderr

	stdoutR, stdoutW, _ := os.Pipe()
	stderrR, stderrW, _ := os.Pipe()
	os.Stdout = stdoutW
	os.Stderr = stderrW

	// Drain both pipes concurrently while the handler runs. A handler that
	// emits more than the OS pipe buffer (~64KB) would otherwise block on write
	// (nothing reading) or have its output truncated by a fixed-size read. Using
	// unbounded io.Copy into bytes.Buffer captures arbitrarily large output.
	var stdoutBuf, stderrBuf bytes.Buffer
	var drainWG sync.WaitGroup
	drainWG.Add(2)
	go func() { defer drainWG.Done(); io.Copy(&stdoutBuf, stdoutR) }()
	go func() { defer drainWG.Done(); io.Copy(&stderrBuf, stderrR) }()

	// Context is constructed unconditionally for every dispatch, writing to the
	// capture pipes.
	ctx := newContext(stdoutW, stderrW, pr.sources, a.infraAccess())

	var exitCode int
	var resultData interface{}
	if pr.cmd.Passthrough {
		exitCode = pr.cmd.PassthroughHandler(ctx, pr.cmd.Name, pr.passthroughArgs, pr.globalKwargs)
	} else {
		outcome := pr.cmd.Handler(ctx, pr.kwargs)
		exitCode = outcome.code
		resultData = outcome.data
		if outcome.data != nil {
			data, err := json.Marshal(outcome.data)
			if err != nil {
				fmt.Fprintf(stderrW, "error: failed to marshal result data: %s\n", err)
			} else {
				fmt.Fprintln(stdoutW, string(data))
			}
		}
	}

	stdoutW.Close()
	stderrW.Close()

	// Wait for both drain goroutines to finish consuming the pipes, then close
	// the read ends.
	drainWG.Wait()
	stdoutR.Close()
	stderrR.Close()

	os.Stdout = oldStdout
	os.Stderr = oldStderr

	return Result{
		Stdout:   stdoutBuf.String(),
		Stderr:   stderrBuf.String(),
		ExitCode: exitCode,
		Data:     resultData,
	}
}

// parseResult holds the output of doParse.
type parseResult struct {
	cmd             *Command
	cmdPath         string // dot-separated command path (e.g. "infra.deploy")
	kwargs          map[string]interface{}
	globalKwargs    map[string]interface{}
	sources         map[string]string // flag param name -> source label
	passthroughArgs []string
	helpText        string
	versionText     string
	parseErr        string
	commandPrefix   string
	dumpSchema      bool
	serveMCP        bool
}

// preScanResult holds the results of the position-aware pre-scan for
// reserved flags (--dump-schema, --mcp, --config, --hermetic).
type preScanResult struct {
	dumpSchema  bool
	serveMCP    bool
	hermetic    bool     // --hermetic: skip config loading and env var resolution
	configPath  string   // value from --config <path> or --config=<path>
	err         string   // non-empty on error (e.g. missing value, config on disabled app)
	cleanedArgv []string // argv with --config/--config=value/--hermetic stripped out
}

// preScanReservedFlags scans argv for --dump-schema, --mcp, and --config
// in the pre-command region only. The pre-command region ends at:
//   - the first non-flag token (the command name)
//   - a "--" terminator
//
// Within the pre-command region, known global flags and their values are
// skipped so that a global flag value that happens to look like a command
// name is not treated as one. After the pre-command region, these reserved
// flags are NOT intercepted (they become unknown-flag errors in the normal
// parse flow).
func (a *App) preScanReservedFlags(argv []string) preScanResult {
	// Build a set of known global flag long-names and short-names,
	// along with whether they take a value (non-bool).
	type flagInfo struct {
		takesValue bool
	}
	knownFlags := make(map[string]*flagInfo)
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		knownFlags["--"+f.Name] = &flagInfo{takesValue: f.Type != TypeBool}
		if f.Short != "" {
			knownFlags["-"+f.Short] = &flagInfo{takesValue: f.Type != TypeBool}
		}
		if f.Type == TypeBool && f.Negatable {
			knownFlags["--no-"+f.Name] = &flagInfo{takesValue: false}
		}
	}

	var result preScanResult
	// Track indices to exclude from cleanedArgv (--config tokens)
	excludeIndices := make(map[int]bool)
	i := 0
	for i < len(argv) {
		tok := argv[i]

		// -- terminates the pre-command region
		if tok == "--" {
			break
		}

		// Non-flag token = command name: stop scanning
		if !strings.HasPrefix(tok, "-") || tok == "-" {
			break
		}

		// --dump-schema
		if tok == "--dump-schema" {
			result.dumpSchema = true
			return result
		}

		// --mcp
		if tok == "--mcp" {
			result.serveMCP = true
			return result
		}

		// --hermetic (boolean, no value)
		if tok == "--hermetic" {
			result.hermetic = true
			excludeIndices[i] = true
			i++
			continue
		}

		// --config=<value>
		if strings.HasPrefix(tok, "--config=") {
			if !a.configEnabled {
				result.err = "--config is not available: this app does not use config files"
				return result
			}
			val := tok[len("--config="):]
			if val == "" {
				result.err = "flag '--config' requires a value"
				return result
			}
			result.configPath = val
			excludeIndices[i] = true
			i++
			continue
		}

		// --config <value>
		if tok == "--config" {
			if !a.configEnabled {
				result.err = "--config is not available: this app does not use config files"
				return result
			}
			if i+1 >= len(argv) {
				result.err = "flag '--config' requires a value"
				return result
			}
			result.configPath = argv[i+1]
			excludeIndices[i] = true
			excludeIndices[i+1] = true
			i += 2
			continue
		}

		// Known global flag with --flag=value form: skip
		if strings.HasPrefix(tok, "--") && strings.Contains(tok, "=") {
			eqPos := strings.Index(tok, "=")
			flagPart := tok[:eqPos]
			if _, ok := knownFlags[flagPart]; ok {
				i++
				continue
			}
			// Unknown flag-like token before command name: stop
			break
		}

		// Known global flag: skip it (and its value if non-bool)
		if info, ok := knownFlags[tok]; ok {
			if info.takesValue {
				i += 2
			} else {
				i++
			}
			continue
		}

		// Unknown flag-like token before command name: stop
		break
	}

	// Build cleaned argv with --config tokens stripped
	if len(excludeIndices) > 0 {
		cleaned := make([]string, 0, len(argv)-len(excludeIndices))
		for j, tok := range argv {
			if !excludeIndices[j] {
				cleaned = append(cleaned, tok)
			}
		}
		result.cleanedArgv = cleaned
	} else {
		result.cleanedArgv = argv
	}

	return result
}

// doParse parses argv and returns a parseResult.
// Exactly one of: (cmd+kwargs), helpText, versionText, or parseErr will be non-zero.
func (a *App) doParse(argv []string) parseResult {
	// Reset stdin tracking for each parse invocation
	a.stdinConsumedBy = nil

	// App-level --help/-h and --version/-v (no global flags present)
	if len(argv) == 0 || (len(argv) == 1 && (argv[0] == "--help" || argv[0] == "-h")) {
		return parseResult{helpText: formatAppHelp(a)}
	}
	if len(argv) == 1 && (argv[0] == "--version" || argv[0] == "-v") {
		return parseResult{versionText: formatVersion(a)}
	}

	// Position-aware pre-scan: intercept --dump-schema, --mcp, --config, --hermetic
	// in the pre-command region only (before the first non-flag token, before --).
	// This replaces the old naive scans that checked ALL of argv.
	preScan := a.preScanReservedFlags(argv)
	if preScan.dumpSchema {
		return parseResult{dumpSchema: true}
	}
	if preScan.serveMCP {
		return parseResult{serveMCP: true}
	}
	if preScan.err != "" {
		return parseResult{parseErr: preScan.err}
	}

	// --hermetic + --config mutual exclusion
	if preScan.hermetic && preScan.configPath != "" {
		return parseResult{parseErr: "--hermetic and --config are mutually exclusive"}
	}

	// Load config data once at parse time.
	// When hermetic is active, skip config loading entirely (even XDG defaults).
	// Capture any parse error to handle config subcommand exemption later.
	var configLoadErr string
	if a.configEnabled && !preScan.hermetic {
		runtimeOverride := preScan.configPath
		hermetic := a.noDefaultConfigPath && runtimeOverride == ""
		isRuntimeFlag := runtimeOverride != ""
		result := a.resolveConfigData(runtimeOverride, hermetic, isRuntimeFlag)
		if result.parseErr != "" {
			configLoadErr = result.parseErr
			a.configData = map[string]interface{}{}
		} else {
			a.configData = result.data
		}
	} else if preScan.hermetic {
		// Hermetic mode: no config data at all
		a.configData = nil
	}

	// Extract global flags from cleaned argv (--config/--hermetic stripped), leaving
	// the rest for command routing. Pass hermetic flag to skip env resolution.
	globalValues, globalSourceMap, rest, globalErr := a.extractGlobalFlags(preScan.cleanedArgv, preScan.hermetic)
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

	// Route through the group/command tree
	route := a.resolveCommand(rest)

	// Handle routing errors (deprecated, unknown, no command)
	if route.err != "" {
		return parseResult{parseErr: route.err, commandPrefix: route.commandPrefix}
	}

	// Handle help at group level
	if route.helpAtGroup {
		return parseResult{helpText: formatGroupHelp(a, route.lastGroup, route.path)}
	}

	// Command was resolved — handle help, passthrough, and parsing
	cmd := route.cmd
	cmdRest := route.rest
	path := route.path

	// Build dotted command path for coverage and other instrumentation
	resolvedCmdPath := strings.Join(append(path, cmd.Name), ".")

	// Check command-level --help anywhere in remaining tokens
	if tokensContainHelp(cmdRest) {
		prefix := ""
		if len(path) > 0 {
			prefix = strings.Join(path, " ") + " "
		}
		return parseResult{helpText: formatCommandHelp(a, cmd, prefix)}
	}
	// Passthrough: skip parsing, forward raw args
	if cmd.Passthrough {
		return parseResult{cmd: cmd, cmdPath: resolvedCmdPath, passthroughArgs: cmdRest, globalKwargs: globalValues}
	}

	// Config subcommand exemption: config edit, config path, config set
	// are exempt from config load errors (self-lock prevention).
	// config show handles the error specially (shows it as output).
	isConfigSubcommand := a.configEnabled && len(path) > 0 && path[0] == "config"

	// --hermetic + config subcommand = hard error
	if preScan.hermetic && isConfigSubcommand {
		return parseResult{parseErr: "--hermetic cannot be used with config commands"}
	}

	if configLoadErr != "" {
		if !isConfigSubcommand {
			// Non-config command: hard error
			return parseResult{parseErr: configLoadErr}
		}
		// Config subcommand: only config show needs special handling.
		// edit, path, set, init are exempt (they work on broken configs).
		// config show is handled by the config show handler itself,
		// which calls resolveConfigData independently. We store the
		// error on the app for config show to pick up.
		a.configParseErr = configLoadErr
	}

	// Validate config fields for non-config subcommands
	if a.configEnabled && !isConfigSubcommand {
		if len(cmd.configFields) > 0 {
			if errMsg := a.validateBoundConfigFields(cmd, a.configData); errMsg != "" {
				return parseResult{parseErr: errMsg}
			}
		}
		if len(a.configFields) > 0 {
			if errMsg := a.validateUnknownConfigKeys(a.configData); errMsg != "" {
				return parseResult{parseErr: errMsg}
			}
		}
	}

	kwargs, postGlobalValues, cmdSources, err := parseCommand(cmd, cmdRest, a.globalFlags, a.configData, &a.stdinConsumedBy, a.configConflictMode, preScan.hermetic, a.infraRoots)
	if err != "" {
		parts := append([]string{a.Name}, path...)
		parts = append(parts, cmd.Name)
		return parseResult{parseErr: err, commandPrefix: strings.Join(parts, " ")}
	}
	// Merge global values: post-command globals override pre-command ones
	for k, v := range postGlobalValues {
		globalValues[k] = v
	}
	for k, v := range globalValues {
		kwargs[k] = v
	}
	// Merge global sources into command sources. This mirrors the VALUE merge
	// above: for a global set post-command, parseCommand already placed the
	// correct (cli) source into cmdSources, so the pre-command source label
	// (typically "default") must NOT overwrite it.
	for k, v := range globalSourceMap {
		if _, isPost := postGlobalValues[k]; isPost {
			continue // post-command position wins
		}
		cmdSources[k] = v
	}
	return parseResult{cmd: cmd, cmdPath: resolvedCmdPath, kwargs: kwargs, globalKwargs: globalValues, sources: cmdSources}
}

// tokensContainHelp checks if --help or -h appears in tokens before any "--"
// separator. Tokens after "--" are literal arguments and should not trigger help.
func tokensContainHelp(tokens []string) bool {
	for _, tok := range tokens {
		if tok == "--" {
			return false
		}
		if tok == "--help" || tok == "-h" {
			return true
		}
	}
	return false
}

// extractGlobalFlags scans argv for global flag tokens that appear before the
// command name.  It stops at the first non-flag token (the command name) or at
// "--", returning everything from that point onward as remaining tokens.
// This matches Python's _parse_global_flags behavior.  Global flags appearing
// after the command name are handled by parseCommand instead.
// When hermetic is true, env var and config resolution are skipped entirely.
// Returns (globalValues map, globalSources map, remaining argv, error string).
func (a *App) extractGlobalFlags(argv []string, hermetic bool) (map[string]interface{}, map[string]string, []string, string) {
	globalValues := make(map[string]interface{})
	globalSources := make(map[string]string)
	if len(a.globalFlags) == 0 {
		return globalValues, globalSources, argv, ""
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

	storeValue := func(f *Flag, value interface{}) string {
		if f.Repeatable {
			if existing, ok := globalValues[f.Name]; ok {
				globalValues[f.Name] = append(existing.([]interface{}), value)
			} else {
				globalValues[f.Name] = []interface{}{value}
			}
			if f.Unique {
				if dup := findDuplicate(globalValues[f.Name].([]interface{})); dup != nil {
					return fmt.Sprintf("--%s: duplicate value '%s'", f.Name, formatValueForError(dup))
				}
			}
		} else {
			globalValues[f.Name] = value
		}
		return ""
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
					return nil, nil, nil, fmt.Sprintf("flag '%s' is a boolean flag and does not take a value", flagPart)
				}
				if errStr := parseFlagRawValue(f, valuePart, globalValues, &a.stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, nil, errStr
				}
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
					return nil, nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				if errStr := parseFlagRawValue(f, argv[i+1], globalValues, &a.stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, nil, errStr
				}
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
					return nil, nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				if errStr := parseFlagRawValue(f, argv[i+1], globalValues, &a.stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, nil, errStr
				}
				i += 2
			}
			continue
		}

		// Unknown flag-like token before command name: stop (let command parser handle it)
		break
	}

	remaining := argv[i:]

	// All values set in the CLI loop above are SourceCLI.
	// Mark them now before env/config/default layers add more.
	for k := range globalValues {
		globalSources[flagParamName(k)] = "cli"
	}

	// Resolve env vars for global flags not set by CLI (skipped under --hermetic)
	if !hermetic {
		for i := range a.globalFlags {
			f := &a.globalFlags[i]
			if _, ok := globalValues[f.Name]; ok {
				continue
			}
			if f.Env != "" {
				envVal, ok := os.LookupEnv(f.Env)
				if ok {
					// Compound types: dict parses JSON from env, list uses env_separator
					if IsDictType(f.Type) {
						entries, errStr := parseDictEnvValue(f.Name, envVal, ItemType(f.Type))
						if errStr != "" {
							return nil, nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
						}
						globalValues[f.Name] = entries
						globalSources[flagParamName(f.Name)] = "env"
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
						globalValues[f.Name] = coercedList
						globalSources[flagParamName(f.Name)] = "env"
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
						globalValues[f.Name] = boolVal
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
							globalValues[f.Name] = coercedList
						} else {
							intVal, err := parseIntStrict(envVal)
							if err != nil {
								return nil, nil, nil, fmt.Sprintf(
									"--%s: %s (from env var '%s')",
									f.Name, err.Error(), f.Env,
								)
							}
							if f.Repeatable {
								globalValues[f.Name] = []interface{}{intVal}
							} else {
								globalValues[f.Name] = intVal
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
							globalValues[f.Name] = coercedList
						} else {
							floatVal, errStr := parseFloatStrict(f.Name, envVal)
							if errStr != "" {
								return nil, nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
							}
							if f.Repeatable {
								globalValues[f.Name] = []interface{}{floatVal}
							} else {
								globalValues[f.Name] = floatVal
							}
						}
					default:
						if f.Repeatable && f.EnvSeparator != "" {
							parts := splitEscaped(envVal, f.EnvSeparator[0])
							coercedList := make([]interface{}, 0, len(parts))
							for _, element := range parts {
								resolved, errStr := resolveAtPrefix(f.Name, element, &a.stdinConsumedBy)
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
							globalValues[f.Name] = coercedList
						} else {
							resolved, errStr := resolveAtPrefix(f.Name, envVal, &a.stdinConsumedBy)
							if errStr != "" {
								return nil, nil, nil, errStr
							}
							if f.Repeatable {
								globalValues[f.Name] = []interface{}{resolved}
							} else {
								globalValues[f.Name] = resolved
							}
						}
					}
					globalSources[flagParamName(f.Name)] = "env"
					continue
				}
			}
		}

		// Resolve config values for global flags not set by CLI or env.
		// In conflict mode "error", detect when config would set a flag
		// already set by CLI or env.
		if a.configData != nil {
			for i := range a.globalFlags {
				f := &a.globalFlags[i]
				param := flagParamName(f.Name)
				configVal, hasConfig := a.configData[param]
				if !hasConfig {
					continue
				}
				// Effective mode: per-flag override if set, else the app default.
				effectiveMode := a.configConflictMode
				if f.hasConflictMode {
					effectiveMode = f.ConflictMode
				}
				if existing, alreadySet := globalValues[f.Name]; alreadySet {
					// Conflict ONLY when config diverges from the CLI/env value.
					if effectiveMode == "error" {
						coerced, errStr := coerceConfigValue(configVal, f)
						if errStr != "" {
							return nil, nil, nil, fmt.Sprintf("--%s: config value error: %s", f.Name, errStr)
						}
						if !valuesEqualForConflict(existing, coerced, f) {
							existingSource := globalSources[param]
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
				globalValues[f.Name] = coerced
				globalSources[flagParamName(f.Name)] = "config"
			}
		}
	} // end if !hermetic

	// Apply defaults for global flags not set
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		if _, ok := globalValues[f.Name]; ok {
			continue
		}
		val, src, errMsg := applyFlagDefault(f, nil, "global ", a.infraRoots)
		if errMsg != "" {
			return nil, nil, nil, errMsg
		}
		globalValues[f.Name] = val
		globalSources[flagParamName(f.Name)] = sourceLabelString(src)
	}

	// Validate choices for global flags
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		val, ok := globalValues[f.Name]
		if !ok {
			continue
		}
		if errMsg := validateChoices(f.Name, val, f.Repeatable, f.Choices, false); errMsg != "" {
			return nil, nil, nil, errMsg
		}
	}

	// Convert to param-name keys
	result := make(map[string]interface{})
	for k, v := range globalValues {
		result[flagParamName(k)] = v
	}

	return result, globalSources, remaining, ""
}

// buildAndValidateCommand creates and validates a Command.
func buildAndValidateCommand(name, help string, handler func(ctx *Context, kwargs map[string]interface{}) Outcome, envPrefix string, globalFlags []Flag, inheritedTags []string, opts []CmdOption) *Command {
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

	// Passthrough commands cannot have flags, args, flag sets, or mutex
	if cmd.Passthrough {
		if len(cmd.flags) > 0 || len(cmd.args) > 0 || len(cmd.flagSets) > 0 || len(cmd.mutex) > 0 {
			var parts []string
			if len(cmd.flags) > 0 {
				parts = append(parts, "flags")
			}
			if len(cmd.args) > 0 {
				parts = append(parts, "args")
			}
			if len(cmd.flagSets) > 0 {
				parts = append(parts, "flag sets")
			}
			if len(cmd.mutex) > 0 {
				parts = append(parts, "mutex groups")
			}
			panic(fmt.Sprintf("command %q: passthrough commands cannot have %s", name, strings.Join(parts, ", ")))
		}
		cmd.tags = mergeTags(inheritedTags, cmd.tags)
		return cmd
	}

	// Merge flag set flags and mutex flags into a unified all-flags list for validation
	allFlags := make([]Flag, 0, len(cmd.flags))
	allFlags = append(allFlags, cmd.flags...)
	for _, fs := range cmd.flagSets {
		allFlags = append(allFlags, fs.Flags...)
	}

	// Validate mutex groups
	mutexFlagNames := make(map[string]bool)
	for _, mg := range cmd.mutex {
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
	for _, a := range cmd.args {
		if seenArgs[a.Name] {
			panic(fmt.Sprintf("command %q: duplicate arg name %q", name, a.Name))
		}
		seenArgs[a.Name] = true
	}

	// Validate variadic args: first check count, then check position
	variadicCount := 0
	for _, a := range cmd.args {
		if a.IsVariadic {
			variadicCount++
		}
	}
	if variadicCount > 1 {
		panic(fmt.Sprintf("command %q: at most one variadic arg is allowed", name))
	}
	for i, a := range cmd.args {
		if a.IsVariadic && i != len(cmd.args)-1 {
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

	// Validate dependencies
	for _, dep := range cmd.dependencies {
		switch d := dep.(type) {
		case CoRequired:
			if len(d.Flags) < 2 {
				panic(fmt.Sprintf("command %q: CoRequired must have at least 2 flags, got %d", name, len(d.Flags)))
			}
			seen := make(map[string]bool)
			for _, flagName := range d.Flags {
				if !seenFlags[flagName] {
					panic(fmt.Sprintf("command %q: CoRequired references unknown flag %q", name, flagName))
				}
				if seen[flagName] {
					panic(fmt.Sprintf("command %q: CoRequired has duplicate flag %q", name, flagName))
				}
				seen[flagName] = true
			}
		case Requires:
			if d.Flag == d.DependsOn {
				panic(fmt.Sprintf("command %q: Requires flag and depends_on cannot be the same (%q)", name, d.Flag))
			}
			if !seenFlags[d.Flag] {
				panic(fmt.Sprintf("command %q: Requires references unknown flag %q", name, d.Flag))
			}
			if !seenFlags[d.DependsOn] {
				panic(fmt.Sprintf("command %q: Requires references unknown flag %q", name, d.DependsOn))
			}
		case Implies:
			if d.Flag == d.Implies {
				panic(fmt.Sprintf("command %q: Implies flag and implies cannot be the same (%q)", name, d.Flag))
			}
			if !seenFlags[d.Flag] {
				panic(fmt.Sprintf("command %q: Implies references unknown flag %q", name, d.Flag))
			}
			if !seenFlags[d.Implies] {
				panic(fmt.Sprintf("command %q: Implies references unknown flag %q", name, d.Implies))
			}
			// Both flags must be BoolFlag
			var triggerType, targetType FlagType
			for _, f := range allFlags {
				if f.Name == d.Flag {
					triggerType = f.Type
				}
				if f.Name == d.Implies {
					targetType = f.Type
				}
			}
			if triggerType != TypeBool {
				panic(fmt.Sprintf("command %q: Implies trigger flag %q must be a bool flag", name, d.Flag))
			}
			if targetType != TypeBool {
				panic(fmt.Sprintf("command %q: Implies target flag %q must be a bool flag", name, d.Implies))
			}
		}
	}

	// Store the resolved allFlags on the command for parsing
	cmd.flags = allFlags

	cmd.tags = mergeTags(inheritedTags, cmd.tags)

	return cmd
}

// flagParamName converts a flag name like "dry-run" to a parameter key "dry_run".
func flagParamName(name string) string {
	return strings.ReplaceAll(name, "-", "_")
}

// findCommandPrefix finds the group prefix for a command.
// Traverses the group tree recursively to find the full path.
func (a *App) findCommandPrefix(cmd *Command) string {
	result := searchGroupsForCommand(a.groups, cmd, nil)
	if result != "" {
		return result
	}
	return ""
}

// searchGroupsForCommand recursively searches groups for a command and returns
// the full path as a prefix string (e.g. "dns zone ").
func searchGroupsForCommand(groups map[string]*Group, cmd *Command, path []string) string {
	for _, grp := range groups {
		for _, c := range grp.Commands {
			if c == cmd {
				return strings.Join(append(path, grp.Name), " ") + " "
			}
		}
		result := searchGroupsForCommand(grp.Groups, cmd, append(path, grp.Name))
		if result != "" {
			return result
		}
	}
	return ""
}
