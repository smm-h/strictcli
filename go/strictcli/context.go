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

	// The framework-owned reserved quartet, delivered here and never as handler
	// kwargs.
	reserved reservedFlags
	// effects is the per-dispatch effects handle (the runtime seal). nil for a
	// Context constructed outside a command dispatch.
	effects *Effects
}

// reservedFlags carries the values of the framework-owned reserved quartet for
// one dispatch.
type reservedFlags struct {
	dryRun               bool
	approveConsequential bool
	quiet                bool
	verbose              bool
}

// infraAccess carries a Context's view of infrastructure env vars: resolved root
// values (captured at construction), the set of declared handshake env vars
// (read live at access time), and the set of declared connection env vars (read
// live, but suppressed under --hermetic).
type infraAccess struct {
	roots       map[string]string // env var -> resolved path
	handshakes  map[string]bool   // env var -> declared
	connections map[string]bool   // env var -> declared (connection URL kind)
	hermetic    bool              // when true, connection env vars resolve as absent
}

// newContext creates a new Context with the given writers and provenance
// sources. It is the single arming point for the runtime seal: every dispatch
// site funnels through here and passes the reserved-flag state and the
// per-dispatch effects handle in.
func newContext(stdout, stderr io.Writer, sources map[string]string, infra *infraAccess, reserved reservedFlags, effects *Effects) *Context {
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
		stdout:   stdout,
		stderr:   stderr,
		sources:  sources,
		infra:    infra,
		reserved: reserved,
		effects:  effects,
	}
}

// DryRun reports whether the framework-owned --dry-run flag was passed.
func (c *Context) DryRun() bool { return c.reserved.dryRun }

// ApproveConsequential reports whether the framework-owned
// --approve-consequential flag was passed.
func (c *Context) ApproveConsequential() bool {
	return c.reserved.approveConsequential
}

// Quiet reports whether the framework-owned --quiet flag was passed.
func (c *Context) Quiet() bool { return c.reserved.quiet }

// Verbose reports whether the framework-owned --verbose flag was passed.
func (c *Context) Verbose() bool { return c.reserved.verbose }

// Effects returns the effects handle for this run. Panics when the Context was
// constructed outside a command dispatch.
func (c *Context) Effects() *Effects {
	if c.effects == nil {
		panic(errEffectsUnavailable)
	}
	return c.effects
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
// For a declared connection env (WithConnectionEnv), it reads the environment
// LIVE at call time and returns (value, isSet) -- EXCEPT under --hermetic, where
// it resolves as absent ("", false) so connection-dependent behavior skips
// visibly instead of connecting.
//
// Panics if envVar is not a declared root, handshake, or connection var --
// declare everything.
func (c *Context) InfraValue(envVar string) (string, bool) {
	if c.infra != nil {
		if v, ok := c.infra.roots[envVar]; ok {
			return v, true
		}
		if c.infra.handshakes[envVar] {
			return os.LookupEnv(envVar)
		}
		if c.infra.connections[envVar] {
			if c.infra.hermetic {
				return "", false
			}
			return os.LookupEnv(envVar)
		}
	}
	panic(errInfraValueUndeclared(envVar))
}

// ConnectionEnvValue returns the value of a declared connection env
// (WithConnectionEnv), read LIVE at call time -- EXCEPT under --hermetic, where
// it resolves as absent ("", false). Panics if envVar is not a declared
// connection env. This is the check-side and handler-side accessor for the
// connection-URL kind; see also InfraValue, which resolves all three kinds.
func (c *Context) ConnectionEnvValue(envVar string) (string, bool) {
	if c.infra != nil && c.infra.connections[envVar] {
		if c.infra.hermetic {
			return "", false
		}
		return os.LookupEnv(envVar)
	}
	panic(errConnectionValueUndeclared(envVar))
}

// Info writes an informational message to stdout (hidden under --quiet).
func (c *Context) Info(msg string) {
	if c.reserved.quiet {
		return
	}
	fmt.Fprintln(c.stdout, msg)
}

// Warn writes a warning message to stderr (never suppressed).
func (c *Context) Warn(msg string) {
	fmt.Fprintln(c.stderr, msg)
}

// Debug writes a debug message to stdout (shown only under --verbose).
// --quiet DOMINATES --verbose: passing both hides debug output.
func (c *Context) Debug(msg string) {
	if c.reserved.quiet || !c.reserved.verbose {
		return
	}
	fmt.Fprintln(c.stdout, msg)
}

// Error writes an error message to stderr (never suppressed).
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
	panic(errNoSourceInfo(name))
}

// reservedFrameworkFlagNames is the effects-regime quartet. The ban on these
// four LONG flag names is unconditional and applies at every level -- command
// flags, flag-set flags, mutex-group flags and app global flags. The four have
// no short forms, and short-flag names are unaffected by this ban.
var reservedFrameworkFlagNames = map[string]bool{
	"dry-run":               true,
	"approve-consequential": true,
	"quiet":                 true,
	"verbose":               true,
}

// bannedFlagNames are names the framework refuses outright without owning a
// flag of that name. `yes` is here because --approve-consequential replaced
// --yes (contract §7.1) and a private --yes would restate it in a spelling
// that IS muscle memory -- exactly what the rename removed.
var bannedFlagNames = map[string]bool{
	"yes": true,
}

// reservedGlobalShortNames are the pre-existing reserved names; they are also
// what a SHORT flag name is checked against.
var reservedGlobalShortNames = map[string]bool{
	"help":        true,
	"h":           true,
	"version":     true,
	"v":           true,
	"dump-schema": true,
	"mcp":         true,
	"config":      true,
	"hermetic":    true,
}

// reservedGlobalFlagNames are names that cannot be used for user-defined global flags
// because they are reserved by the framework.
var reservedGlobalFlagNames = func() map[string]bool {
	m := make(map[string]bool, len(reservedGlobalShortNames)+len(reservedFrameworkFlagNames))
	for k := range reservedGlobalShortNames {
		m[k] = true
	}
	for k := range reservedFrameworkFlagNames {
		m[k] = true
	}
	return m
}()
