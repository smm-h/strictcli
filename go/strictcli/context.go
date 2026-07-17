package strictcli

import (
	"fmt"
	"io"
	"os"
	"strings"
)

// Context provides structured output and provenance for command handlers.
// It is constructed unconditionally for every dispatch and passed to the handler.
// Each output method writes to the appropriate stream (stdout or stderr).
type Context struct {
	stdout  io.Writer
	stderr  io.Writer
	sources map[string]string // flag param name -> source label (cli/env/config/default/implied/infra)
	infra   *infraAccess      // resolved infra roots + declared handshake vars (nil if none)
}

// infraAccess carries a Context's view of infrastructure env vars: resolved root
// values (captured at construction) and the set of declared handshake env vars
// (read live at access time).
type infraAccess struct {
	roots      map[string]string // env var -> resolved path
	handshakes map[string]bool   // env var -> declared
}

// newContext creates a new Context with the given writers and provenance sources.
func newContext(stdout, stderr io.Writer, sources map[string]string, infra *infraAccess) *Context {
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
		sources: sources,
		infra:   infra,
	}
}

// InfraValue returns the value of a declared infrastructure env var.
//
// For a declared location root (WithInfraRoot), it returns the value resolved
// eagerly at construction (env var if set, else the declared default) and true.
// The resolved value is always available, so the boolean is always true for
// roots.
//
// For a declared handshake var (WithHandshakeEnv), it reads the environment LIVE
// at call time (handshakes are set by the invoking process and carry no
// construction-time value), returning (value, isSet).
//
// Panics if envVar is neither a declared root nor a declared handshake var --
// declare everything.
func (c *Context) InfraValue(envVar string) (string, bool) {
	if c.infra != nil {
		if v, ok := c.infra.roots[envVar]; ok {
			return v, true
		}
		if c.infra.handshakes[envVar] {
			return os.LookupEnv(envVar)
		}
	}
	panic(fmt.Sprintf("InfraValue: %q is not a declared infra root or handshake env var", envVar))
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
// Returns one of: "cli", "env", "config", "default", "implied", "infra".
// ("infra" indicates the value came from a RelativeToRoot default resolved
// through a declared infrastructure root.)
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
	"hermetic":    true,
}
