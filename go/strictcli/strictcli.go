// Package strictcli is a strict, zero-dependency CLI framework for Go.
package strictcli

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"reflect"
	"sort"
	"strings"
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
	Repeatable   bool
	Unique       bool
	EnvSeparator string

	// hasDefault distinguishes between "default explicitly set to nil" and "no default"
	hasDefault bool
	hasUnique  bool
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

// PassthroughHandler is the handler type for passthrough commands.
type PassthroughHandler func(name string, args []string, globals map[string]interface{}) int

// DataHandler is a handler that returns structured data alongside an exit code.
type DataHandler func(map[string]interface{}) HandlerResult

// HandlerResult is the return type for DataHandler functions.
type HandlerResult struct {
	Data     interface{}
	ExitCode int
}

// Command is a leaf command with a handler.
type Command struct {
	Name               string
	Help               string
	Handler            func(map[string]interface{}) int
	dataHandler        DataHandler
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

	// Struct handler fields (set by RegisterHandler)
	handlerFactory func() Handler            // creates a fresh handler instance per dispatch
	handlerType    reflect.Type              // the concrete struct type behind the Handler
	paramToFlag    map[string]string          // reverse map: param name (underscores) -> flag name (dashes)
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

	// app is a reference to the root App (needed for RegisterHandler dispatch context)
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
	globalsType reflect.Type // set by RegisterGlobals[T], used for validation

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

	checksEnabled       bool
	checksPath          string
	checksEmbed         []byte
	checkDefs           map[string]*checkDef
	checkOrder          []string // sorted check names for deterministic listing
	checkContextFactory func() CheckContext

	stdinConsumedBy *string // tracks which flag consumed stdin via @-
	tagContracts    map[string]string // tag name -> required flag name

	currentDispatch *dispatchCtx // set before handler dispatch, cleared after
}

// dispatchCtx carries per-dispatch state to struct handler wrappers.
// Set on the App before calling the handler, cleared after return.
type dispatchCtx struct {
	stdout   io.Writer
	stderr   io.Writer
	globals  map[string]interface{} // keyed by flag name (dashes)
	emitData interface{}            // set by handler wrapper if ctx.Emit was called
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
	if a.hasDefault && a.Default != nil {
		switch a.Type {
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
	// Default config format to "json" if not set
	if a.configFormat == "" {
		a.configFormat = "json"
	}
	if a.configFormat != "json" && a.configFormat != "toml" {
		fmt.Fprintf(os.Stderr, "App.config_format must be \"json\" or \"toml\", got %q\n", a.configFormat)
		os.Exit(1)
	}
	if a.configEnabled {
		a.configData = loadConfig(a.Name, a.configPathOverride, a.configFormat)
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
		a.checkDefs = defs
		a.checkOrder = order
		a.checksEnabled = true
		a.registerCheckCommand()
	} else if len(a.checksEmbed) > 0 {
		appName, defs, order, err := parseChecksToml(a.checksEmbed)
		if err != nil {
			panic(err.Error())
		}
		if appName != a.Name {
			panic(fmt.Sprintf("checks.toml: app %q does not match app name %q", appName, a.Name))
		}
		a.checkDefs = defs
		a.checkOrder = order
		a.checksEnabled = true
		a.registerCheckCommand()
	}
	return a
}

// RegisterCheck registers a check implementation for a check declared in checks.toml.
// Panics if no checks.toml was discovered, if the name is not declared, or if it's a duplicate.
func (a *App) RegisterCheck(name string, fn func(CheckContext) CheckResult) {
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
	def.impl = fn
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
func (a *App) Command(name, help string, handler func(map[string]interface{}) int, opts ...CmdOption) {
	cmd := buildAndValidateCommand(name, help, handler, a.EnvPrefix, a.globalFlags, nil, opts)
	a.commands[name] = cmd
	a.cmdOrder = append(a.cmdOrder, name)
}

// DataCommand registers a top-level command with a DataHandler that returns structured data.
func (a *App) DataCommand(name, help string, handler DataHandler, opts ...CmdOption) {
	// Wrap the data handler as a regular handler for buildAndValidateCommand
	wrapper := func(kwargs map[string]interface{}) int {
		result := handler(kwargs)
		return result.ExitCode
	}
	cmd := buildAndValidateCommand(name, help, wrapper, a.EnvPrefix, a.globalFlags, nil, opts)
	cmd.dataHandler = handler
	a.commands[name] = cmd
	a.cmdOrder = append(a.cmdOrder, name)
}

// RegisterHandler registers a struct-based command handler on the app.
// The factory function creates fresh handler instances for each invocation.
// Flags and args are extracted from the handler struct's cli:/arg: tags.
// Additional CmdOptions (e.g., WithMutex, WithDependencies) can be passed.
func (a *App) RegisterHandler(name, help string, factory func() Handler, opts ...CmdOption) {
	cmd := buildHandlerCommand(name, help, factory, a, a.EnvPrefix, a.globalFlags, nil, opts)
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
	// Check for collisions with existing global flags
	for _, gf := range a.globalFlags {
		if gf.Name == f.Name {
			panic(fmt.Sprintf("duplicate global flag name %q", f.Name))
		}
	}
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
func (g *Group) Command(name, help string, handler func(map[string]interface{}) int, opts ...CmdOption) {
	if _, ok := g.Groups[name]; ok {
		panic(fmt.Sprintf("command %q collides with an existing group", name))
	}
	cmd := buildAndValidateCommand(name, help, handler, g.envPrefix, g.globalFlags, g.accumulatedTags, opts)
	g.Commands[name] = cmd
	g.order = append(g.order, name)
}

// DataCommand registers a command within a group with a DataHandler that returns structured data.
func (g *Group) DataCommand(name, help string, handler DataHandler, opts ...CmdOption) {
	if _, ok := g.Groups[name]; ok {
		panic(fmt.Sprintf("command %q collides with an existing group", name))
	}
	wrapper := func(kwargs map[string]interface{}) int {
		result := handler(kwargs)
		return result.ExitCode
	}
	cmd := buildAndValidateCommand(name, help, wrapper, g.envPrefix, g.globalFlags, g.accumulatedTags, opts)
	cmd.dataHandler = handler
	g.Commands[name] = cmd
	g.order = append(g.order, name)
}

// RegisterHandler registers a struct-based command handler within a group.
func (g *Group) RegisterHandler(name, help string, factory func() Handler, opts ...CmdOption) {
	if _, ok := g.Groups[name]; ok {
		panic(fmt.Sprintf("command %q collides with an existing group", name))
	}
	cmd := buildHandlerCommand(name, help, factory, g.app, g.envPrefix, g.globalFlags, g.accumulatedTags, opts)
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
		code := pr.cmd.PassthroughHandler(pr.cmd.Name, pr.passthroughArgs, pr.globalKwargs)
		os.Exit(code)
	}

	// Set dispatch context for struct handler wrappers
	if pr.cmd.handlerFactory != nil {
		a.currentDispatch = &dispatchCtx{
			stdout:  os.Stdout,
			stderr:  os.Stderr,
			globals: paramKwargsToFlagNames(pr.globalKwargs),
		}
		defer func() { a.currentDispatch = nil }()
	}

	if pr.cmd.dataHandler != nil {
		result := pr.cmd.dataHandler(pr.kwargs)
		if result.Data != nil {
			data, err := json.Marshal(result.Data)
			if err != nil {
				fmt.Fprintf(os.Stderr, "error: failed to marshal result data: %s\n", err)
				os.Exit(1)
			}
			fmt.Println(string(data))
		}
		os.Exit(result.ExitCode)
	}

	code := pr.cmd.Handler(pr.kwargs)
	os.Exit(code)
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

	// Capture stdout/stderr from handler
	oldStdout := os.Stdout
	oldStderr := os.Stderr

	stdoutR, stdoutW, _ := os.Pipe()
	stderrR, stderrW, _ := os.Pipe()
	os.Stdout = stdoutW
	os.Stderr = stderrW

	// Set dispatch context for struct handler wrappers (uses pipe writers)
	var dc *dispatchCtx
	if pr.cmd.handlerFactory != nil {
		dc = &dispatchCtx{
			stdout:  stdoutW,
			stderr:  stderrW,
			globals: paramKwargsToFlagNames(pr.globalKwargs),
		}
		a.currentDispatch = dc
		defer func() { a.currentDispatch = nil }()
	}

	var exitCode int
	var resultData interface{}
	if pr.cmd.Passthrough {
		exitCode = pr.cmd.PassthroughHandler(pr.cmd.Name, pr.passthroughArgs, pr.globalKwargs)
	} else if pr.cmd.dataHandler != nil {
		hr := pr.cmd.dataHandler(pr.kwargs)
		exitCode = hr.ExitCode
		resultData = hr.Data
	} else {
		exitCode = pr.cmd.Handler(pr.kwargs)
	}

	// Capture emit data from struct handlers
	if dc != nil && dc.emitData != nil {
		resultData = dc.emitData
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
		Data:     resultData,
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
	commandPrefix   string
	dumpSchema      bool
	serveMCP        bool
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

	// --dump-schema: detected anywhere in argv, before any other parsing
	for _, tok := range argv {
		if tok == "--dump-schema" {
			return parseResult{dumpSchema: true}
		}
	}

	// --mcp: detected anywhere in argv, before any other parsing
	for _, tok := range argv {
		if tok == "--mcp" {
			return parseResult{serveMCP: true}
		}
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
		return parseResult{cmd: cmd, passthroughArgs: cmdRest, globalKwargs: globalValues}
	}

	// Validate config fields for non-config subcommands
	isConfigSubcommand := a.configEnabled && len(path) > 0 && path[0] == "config"
	if a.configEnabled && !isConfigSubcommand {
		configData := loadConfig(a.Name, a.configPathOverride, a.configFormat)
		if len(cmd.configFields) > 0 {
			if errMsg := a.validateBoundConfigFields(cmd, configData); errMsg != "" {
				return parseResult{parseErr: errMsg}
			}
		}
		if len(a.configFields) > 0 {
			if errMsg := a.validateUnknownConfigKeys(configData); errMsg != "" {
				return parseResult{parseErr: errMsg}
			}
		}
	}

	kwargs, postGlobalValues, err := parseCommand(cmd, cmdRest, a.globalFlags, a.configData, &a.stdinConsumedBy)
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
	return parseResult{cmd: cmd, kwargs: kwargs, globalKwargs: globalValues}
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
					return nil, nil, fmt.Sprintf("flag '%s' is a boolean flag and does not take a value", flagPart)
				}
				if errStr := parseFlagRawValue(f, valuePart, globalValues, &a.stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, errStr
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
					return nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				if errStr := parseFlagRawValue(f, argv[i+1], globalValues, &a.stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, errStr
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
					return nil, nil, fmt.Sprintf("flag '%s' requires a value", tok)
				}
				if errStr := parseFlagRawValue(f, argv[i+1], globalValues, &a.stdinConsumedBy, storeValue); errStr != "" {
					return nil, nil, errStr
				}
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
				// Compound types: dict parses JSON from env, list uses env_separator
				if IsDictType(f.Type) {
					entries, errStr := parseDictEnvValue(f.Name, envVal, ItemType(f.Type))
					if errStr != "" {
						return nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
					}
					globalValues[f.Name] = entries
					continue
				}
				if IsListType(f.Type) {
					if f.EnvSeparator == "" {
						return nil, nil, fmt.Sprintf("--%s: list flag with env requires env_separator", f.Name)
					}
					parts := splitEscaped(envVal, f.EnvSeparator[0])
					elemType := ItemType(f.Type)
					coercedList := make([]interface{}, 0, len(parts))
					for _, element := range parts {
						val, errStr := coerceToScalar(f.Name, element, elemType, nil)
						if errStr != "" {
							return nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
						}
						coercedList = append(coercedList, val)
					}
					if f.Unique {
						if dup := findDuplicate(coercedList); dup != nil {
							return nil, nil, fmt.Sprintf(
								"--%s: duplicate value '%s' (from env var '%s')",
								f.Name, formatValueForError(dup), f.Env,
							)
						}
					}
					globalValues[f.Name] = coercedList
					continue
				}
				switch f.Type {
				case TypeBool:
					boolVal, err := parseBoolStrict(envVal)
					if err != nil {
						return nil, nil, fmt.Sprintf(
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
								return nil, nil, fmt.Sprintf(
									"--%s: %s (from env var '%s')",
									f.Name, err.Error(), f.Env,
								)
							}
							coercedList = append(coercedList, intVal)
						}
						if f.Unique {
							if dup := findDuplicate(coercedList); dup != nil {
								return nil, nil, fmt.Sprintf(
									"--%s: duplicate value '%s' (from env var '%s')",
									f.Name, formatValueForError(dup), f.Env,
								)
							}
						}
						globalValues[f.Name] = coercedList
					} else {
						intVal, err := parseIntStrict(envVal)
						if err != nil {
							return nil, nil, fmt.Sprintf(
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
								return nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
							}
							coercedList = append(coercedList, floatVal)
						}
						if f.Unique {
							if dup := findDuplicate(coercedList); dup != nil {
								return nil, nil, fmt.Sprintf(
									"--%s: duplicate value '%s' (from env var '%s')",
									f.Name, formatValueForError(dup), f.Env,
								)
							}
						}
						globalValues[f.Name] = coercedList
					} else {
						floatVal, errStr := parseFloatStrict(f.Name, envVal)
						if errStr != "" {
							return nil, nil, fmt.Sprintf("%s (from env var '%s')", errStr, f.Env)
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
								return nil, nil, errStr
							}
							coercedList = append(coercedList, resolved)
						}
						if f.Unique {
							if dup := findDuplicate(coercedList); dup != nil {
								return nil, nil, fmt.Sprintf(
									"--%s: duplicate value '%s' (from env var '%s')",
									f.Name, formatValueForError(dup), f.Env,
								)
							}
						}
						globalValues[f.Name] = coercedList
					} else {
						resolved, errStr := resolveAtPrefix(f.Name, envVal, &a.stdinConsumedBy)
						if errStr != "" {
							return nil, nil, errStr
						}
						if f.Repeatable {
							globalValues[f.Name] = []interface{}{resolved}
						} else {
							globalValues[f.Name] = resolved
						}
					}
				}
				continue
			}
		}
	}

	// Resolve config values for global flags not set by CLI or env
	if a.configData != nil {
		for i := range a.globalFlags {
			f := &a.globalFlags[i]
			if _, ok := globalValues[f.Name]; ok {
				continue
			}
			param := flagParamName(f.Name)
			if v, ok := a.configData[param]; ok {
				coerced, errStr := coerceConfigValue(v, f)
				if errStr != "" {
					return nil, nil, fmt.Sprintf("--%s: config value error: %s", f.Name, errStr)
				}
				if f.Unique {
					if arr, ok := coerced.([]interface{}); ok {
						if dup := findDuplicate(arr); dup != nil {
							return nil, nil, fmt.Sprintf("--%s: config value error: duplicate value '%s'", f.Name, formatValueForError(dup))
						}
					}
				}
				globalValues[f.Name] = coerced
			}
		}
	}

	// Apply defaults for global flags not set
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		if _, ok := globalValues[f.Name]; ok {
			continue
		}
		val, errMsg := applyFlagDefault(f, nil, "global ")
		if errMsg != "" {
			return nil, nil, errMsg
		}
		globalValues[f.Name] = val
	}

	// Validate choices for global flags
	for i := range a.globalFlags {
		f := &a.globalFlags[i]
		if f.Choices == nil {
			continue
		}
		val, ok := globalValues[f.Name]
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

	// Convert to param-name keys
	result := make(map[string]interface{})
	for k, v := range globalValues {
		result[flagParamName(k)] = v
	}

	return result, remaining, ""
}

// buildAndValidateCommand creates and validates a Command.
func buildAndValidateCommand(name, help string, handler func(map[string]interface{}) int, envPrefix string, globalFlags []Flag, inheritedTags []string, opts []CmdOption) *Command {
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

// buildHandlerCommand creates a Command from a struct-based Handler factory.
// It extracts flags/args from the handler struct, builds a reverse param-to-flag
// map, and wraps the handler in a func(map[string]interface{}) int that performs
// struct binding at dispatch time.
func buildHandlerCommand(name, help string, factory func() Handler, app *App, envPrefix string, globalFlags []Flag, inheritedTags []string, opts []CmdOption) *Command {
	sample := factory()
	structType := reflect.TypeOf(sample)
	if structType.Kind() == reflect.Ptr {
		structType = structType.Elem()
	}

	flags, args := extractFlags(structType)

	// Build reverse map: param name (underscores) -> flag name (dashes)
	paramToFlagMap := make(map[string]string, len(flags))
	for _, f := range flags {
		paramToFlagMap[flagParamName(f.Name)] = f.Name
	}

	// Build the CmdOption list from extracted flags/args, prepended before user opts
	var extractedOpts []CmdOption
	if len(flags) > 0 {
		extractedOpts = append(extractedOpts, WithFlags(flags...))
	}
	if len(args) > 0 {
		extractedOpts = append(extractedOpts, WithArgs(args...))
	}
	mergedOpts := append(extractedOpts, opts...)

	// The wrapper handler: called at dispatch time with kwargs from the parse pipeline
	wrapper := func(kwargs map[string]interface{}) int {
		handler := factory()

		// Build values map keyed by flag name (dashes) for bindValues
		flagValues := make(map[string]interface{}, len(kwargs))
		for paramName, val := range kwargs {
			if flagName, ok := paramToFlagMap[paramName]; ok {
				flagValues[flagName] = val
			}
			// Arg values: keep as-is (arg names don't have dashes)
			// They'll be matched by the arg: tag in bindValues
		}
		// Also add arg values by their arg names
		for _, a := range args {
			if val, ok := kwargs[a.Name]; ok {
				flagValues[a.Name] = val
			}
		}

		if err := bindValues(handler, flagValues); err != nil {
			panic("strictcli: handler binding: " + err.Error())
		}

		// Construct Context from the app's current dispatch context
		dc := app.currentDispatch
		var stdout, stderr io.Writer
		var globals map[string]interface{}
		if dc != nil {
			stdout = dc.stdout
			stderr = dc.stderr
			globals = dc.globals
		}
		ctx := newContext(stdout, stderr, globals)
		code := handler.Run(ctx)

		// If the handler emitted data, it needs to be available to the caller.
		// Store the emit result on the dispatch context if present (for Test/invoke paths).
		if dc != nil && ctx.emitData != nil {
			dc.emitData = ctx.emitData
		}

		return code
	}

	cmd := buildAndValidateCommand(name, help, wrapper, envPrefix, globalFlags, inheritedTags, mergedOpts)
	cmd.handlerFactory = factory
	cmd.handlerType = structType
	cmd.paramToFlag = paramToFlagMap
	return cmd
}

// paramKwargsToFlagNames converts a map keyed by param names (underscores)
// to flag names (dashes). Used to prepare globals for Context in dispatch.
func paramKwargsToFlagNames(kwargs map[string]interface{}) map[string]interface{} {
	if kwargs == nil {
		return nil
	}
	result := make(map[string]interface{}, len(kwargs))
	for k, v := range kwargs {
		result[paramToFlagName(k)] = v
	}
	return result
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
