package strictcli

import (
	"encoding/json"
	"fmt"
	"io"
	"reflect"
	"strings"
)

// Handler is the interface for struct-based command handlers.
// Implementations define flags/args as struct fields with cli:/arg: tags,
// and implement Run to execute the command logic.
type Handler interface {
	Run(ctx *Context) int
}

// Context provides structured output methods for command handlers.
// Each method writes to the appropriate stream (stdout or stderr).
// Emit writes JSON to stdout and stores the data for programmatic retrieval.
type Context struct {
	stdout       io.Writer
	stderr       io.Writer
	globals      map[string]interface{} // keyed by flag name (dashes, not underscores)
	globalsCache interface{}            // cached result of Globals[T], set on first access
	emitData     interface{}            // stores last Emit'd value
	emitCalled   bool                   // enforces single Emit
	sources      map[string]string      // flag param name -> source label (cli/env/config/default/implied)
}

// newContext creates a new Context with the given writers and global flag values.
func newContext(stdout, stderr io.Writer, globals map[string]interface{}, sources map[string]string) *Context {
	if stdout == nil {
		stdout = io.Discard
	}
	if stderr == nil {
		stderr = io.Discard
	}
	if sources == nil {
		sources = make(map[string]string)
	}
	return &Context{
		stdout:  stdout,
		stderr:  stderr,
		globals: globals,
		sources: sources,
	}
}

// Info writes an informational message to stdout.
func (c *Context) Info(msg string) {
	fmt.Fprintln(c.stdout, msg)
}

// Warn writes a warning message to stderr.
func (c *Context) Warn(msg string) {
	fmt.Fprintln(c.stderr, msg)
}

// Debug writes a debug message to stdout.
// Future: will be gated by a verbose flag.
func (c *Context) Debug(msg string) {
	fmt.Fprintln(c.stdout, msg)
}

// Error writes an error message to stderr.
func (c *Context) Error(msg string) {
	fmt.Fprintln(c.stderr, msg)
}

// Source returns the provenance source label for a flag.
// Returns one of: "cli", "env", "config", "default", "implied".
// Panics if the flag name is not found.
func (c *Context) Source(name string) string {
	// Try param name (underscores)
	key := strings.ReplaceAll(name, "-", "_")
	if s, ok := c.sources[key]; ok {
		return s
	}
	// Try original name (dashes)
	if s, ok := c.sources[name]; ok {
		return s
	}
	panic(fmt.Sprintf("no source info for flag %q", name))
}

// Emit JSON-marshals data to stdout and stores it for programmatic retrieval.
// Panics if called more than once — bundle data into a single value.
func (c *Context) Emit(data interface{}) {
	if c.emitCalled {
		panic("Emit called more than once; bundle data into a single value")
	}
	c.emitCalled = true
	c.emitData = data

	b, err := json.Marshal(data)
	if err != nil {
		panic(fmt.Sprintf("Emit: failed to marshal data: %v", err))
	}
	fmt.Fprintln(c.stdout, string(b))
}

// emitResult returns the stored emitData (used internally by Call/Test).
func (c *Context) emitResult() interface{} {
	return c.emitData
}

// reservedGlobalFlagNames are names that cannot be used for user-defined global flags
// because they are reserved by the framework.
var reservedGlobalFlagNames = map[string]bool{
	"help":        true,
	"h":           true,
	"version":     true,
	"v":           true,
	"dump-schema": true,
	"mcp":         true,
	"config":      true,
}

// RegisterGlobals extracts global flags from a struct type T and registers them
// on the app. T must be a struct whose fields use cli: tags (not arg: tags).
// Panics if any extracted flag name collides with a reserved name (help, h,
// version, v, dump-schema, mcp), or if T contains positional arg fields.
func RegisterGlobals[T any](app *App) {
	var zero T
	structType := reflect.TypeOf(zero)
	if structType.Kind() == reflect.Ptr {
		structType = structType.Elem()
	}

	flags, args := extractFlags(structType)

	// Globals cannot have positional args
	if len(args) > 0 {
		panic(fmt.Sprintf("RegisterGlobals[%s]: globals struct must not have arg:-tagged fields", structType.Name()))
	}

	// Validate against reserved names
	for _, f := range flags {
		if reservedGlobalFlagNames[f.Name] {
			panic(fmt.Sprintf("RegisterGlobals[%s]: flag name %q is reserved", structType.Name(), f.Name))
		}
		// Also check short names
		if f.Short != "" && reservedGlobalFlagNames[f.Short] {
			panic(fmt.Sprintf("RegisterGlobals[%s]: short flag %q is reserved", structType.Name(), f.Short))
		}
	}

	// Register each flag as a global flag
	for _, f := range flags {
		app.GlobalFlag(f)
	}

	// Store the globals type on the app for validation
	app.globalsType = structType
}

// Globals returns the global flags as a populated instance of T. On the first
// call, it creates a zero T, binds values from ctx.globals, caches the result,
// and returns it. Subsequent calls return the cached instance.
func Globals[T any](ctx *Context) T {
	// Return cached value if available
	if ctx.globalsCache != nil {
		return ctx.globalsCache.(T)
	}

	var t T
	if ctx.globals != nil {
		if err := bindValues(&t, ctx.globals); err != nil {
			panic(fmt.Sprintf("Globals[%T]: %v", t, err))
		}
	}
	ctx.globalsCache = t
	return t
}
