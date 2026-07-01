package strictcli

import (
	"encoding/json"
	"fmt"
	"io"
)

// Context provides structured output methods for command handlers.
// Each method writes to the appropriate stream (stdout or stderr).
// Emit writes JSON to stdout and stores the data for programmatic retrieval.
type Context struct {
	stdout     io.Writer
	stderr     io.Writer
	globals    map[string]interface{} // keyed by flag name (dashes, not underscores)
	emitData   interface{}            // stores last Emit'd value
	emitCalled bool                   // enforces single Emit
}

// newContext creates a new Context with the given writers and global flag values.
func newContext(stdout, stderr io.Writer, globals map[string]interface{}) *Context {
	if stdout == nil {
		stdout = io.Discard
	}
	if stderr == nil {
		stderr = io.Discard
	}
	return &Context{
		stdout:  stdout,
		stderr:  stderr,
		globals: globals,
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
