package strictcli

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"

	tomledit "github.com/smm-h/go-toml-edit"
)

// CheckContext provides project context to check implementations.
type CheckContext interface {
	ProjectRoot() string
}

// checkProblem is a single minted finding: text plus severity. It is
// unexported and has no public constructor -- problems are minted only via
// reporter methods (Warn/Error).
type checkProblem struct {
	text     string
	severity string // "error" or "warn"
}

// CheckOutcome is the ceiling-typed result of a check implementation. Its
// fields are unexported so callers cannot forge one: a valid CheckOutcome is
// obtained ONLY through reporter methods (Passed/Skipped/Found). The zero value
// has minted=false and is rejected by the runner (belt-and-braces against an
// impl that returns something a reporter did not mint).
type CheckOutcome struct {
	minted   bool           // proves this value came from a reporter
	kind     string         // "passed", "skipped", "found"
	message  string         // pass/found message or skip reason
	problems []checkProblem // accumulated problems (only for kind == "found")
}

// orderedProblems returns the outcome's problems grouped by severity: all
// error-severity problems first, then all warn-severity problems. Insertion
// order is preserved within each group.
func (o CheckOutcome) orderedProblems() []checkProblem {
	var errs, warns []checkProblem
	for _, p := range o.problems {
		if p.severity == "error" {
			errs = append(errs, p)
		} else {
			warns = append(warns, p)
		}
	}
	return append(errs, warns...)
}

// reporterCore holds the problem accumulator and the shared minting methods
// (Warn/Passed/Skipped/Found) promoted into both reporter types. Error-minting
// lives ONLY on ErrorReporter, so WarnReporter structurally lacks it (calling
// Error on a *WarnReporter is a compile error).
type reporterCore struct {
	problems []checkProblem
}

// Warn mints a warn-severity problem. Non-empty text is required.
//
// Reporter validation messages are worded identically to the Python
// implementation (method-agnostic phrasing, no "Warn:"/"warn:" prefix) so the
// two implementations are byte-for-byte in parity -- see conformance/
// check_error_parity.py, which scans these panics.
func (r *reporterCore) Warn(text string) {
	if strings.TrimSpace(text) == "" {
		panic("problem text must be a non-empty string")
	}
	r.problems = append(r.problems, checkProblem{text: text, severity: "warn"})
}

// Passed finalizes a terminal PASS outcome. It hard-errors if any problems were
// accumulated (an impl that found problems cannot claim it passed -- use Found).
func (r *reporterCore) Passed(message string) CheckOutcome {
	if strings.TrimSpace(message) == "" {
		panic("outcome message must be a non-empty string")
	}
	if len(r.problems) > 0 {
		panic("problems were reported; a check that found problems cannot pass -- use found instead")
	}
	return CheckOutcome{minted: true, kind: "passed", message: message}
}

// Skipped finalizes a terminal SKIP outcome. It hard-errors if any problems were
// accumulated.
func (r *reporterCore) Skipped(reason string) CheckOutcome {
	if strings.TrimSpace(reason) == "" {
		panic("skip reason must be a non-empty string")
	}
	if len(r.problems) > 0 {
		panic("problems were reported; a check that found problems cannot skip")
	}
	return CheckOutcome{minted: true, kind: "skipped", message: reason}
}

// Found finalizes an outcome carrying the accumulated problems. It hard-errors
// when no problems were accumulated (nothing found means the check passed -- say
// so explicitly with Passed).
func (r *reporterCore) Found(message string) CheckOutcome {
	if strings.TrimSpace(message) == "" {
		panic("outcome message must be a non-empty string")
	}
	if len(r.problems) == 0 {
		panic("no problems were reported; nothing found means pass -- use passed instead")
	}
	return CheckOutcome{
		minted:   true,
		kind:     "found",
		message:  message,
		problems: append([]checkProblem(nil), r.problems...),
	}
}

// WarnReporter is handed to warn-severity check impls. It can mint warn-severity
// problems and terminal outcomes but structurally LACKS error-minting: there is
// no Error method in its method set, so an attempt to raise an error-severity
// problem from a warn check fails to compile.
type WarnReporter struct {
	reporterCore
}

// ErrorReporter is handed to error-severity check impls. It has everything
// WarnReporter has PLUS Error (mints an error-severity problem).
type ErrorReporter struct {
	reporterCore
}

// Error mints an error-severity problem. Non-empty text is required. This method
// exists only on ErrorReporter -- see the WarnReporter doc comment.
func (r *ErrorReporter) Error(text string) {
	if strings.TrimSpace(text) == "" {
		panic("problem text must be a non-empty string")
	}
	r.problems = append(r.problems, checkProblem{text: text, severity: "error"})
}

// deriveStatus maps a minted CheckOutcome to a display/verdict label.
// found + any error-severity problem => "fail"; found + only warns => "warn";
// passed => "pass"; skipped => "skip".
func deriveStatus(o CheckOutcome) string {
	switch o.kind {
	case "passed":
		return "pass"
	case "skipped":
		return "skip"
	case "found":
		for _, p := range o.problems {
			if p.severity == "error" {
				return "fail"
			}
		}
		return "warn"
	default:
		panic(fmt.Sprintf("unknown check outcome kind %q", o.kind))
	}
}

// Scope adapter asymmetry (deliberate, documented): Python exposes a
// set_scope_adapter hook that projects a check's context or skips it. Go has no
// scope adapter yet -- no Go consumer needs scoped checks. When the first Go
// scope consumer appears, add SetScopeAdapter here with the same contract as
// Python's (returns a replacement context OR a skip directive; it can no longer
// mint arbitrary outcomes), and wire it into runChecks alongside the cascade
// logic. Until then, checkDef.scope is parsed and carried but never consulted at
// run time on the Go side.

// checkDef holds the definition of a single check loaded from checks.toml.
type checkDef struct {
	name         string
	tags         []string
	severity     string // "error" or "warn"
	fast         bool
	pure         bool
	needsNetwork bool
	dependsOn    []string
	scope        string // optional, defaults to ""
	// impl is the wrapped runner installed at registration time. It constructs
	// the appropriate reporter and invokes the user's function. nil until
	// registered via RegisterErrorCheck/RegisterWarnCheck.
	impl     func(CheckContext) CheckOutcome
	implForm string // "error" or "warn" -- the registration form, for the severity cross-check
}

// identifierRe validates identifier names (check names, tag names): lowercase letter followed by lowercase letters, digits, or hyphens.
var identifierRe = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)

// knownCheckFields enumerates the allowed fields in a check definition table.
var knownCheckFields = map[string]bool{
	"tags":          true,
	"severity":      true,
	"fast":          true,
	"pure":          true,
	"needs_network": true,
	"depends_on":    true,
	"scope":         true,
}

// addCheckDef inserts a check definition into the registry, rejecting
// duplicate names as a hard error. It maintains checkOrder in sorted order so
// that dynamic additions keep deterministic listing. This is the single
// internal insertion point for check definitions (TOML loading routes through
// it; future provider-sourced defs will too).
func (a *App) addCheckDef(def *checkDef) error {
	if a.checkDefs == nil {
		a.checkDefs = make(map[string]*checkDef)
	}
	if _, exists := a.checkDefs[def.name]; exists {
		return fmt.Errorf("duplicate check definition %q", def.name)
	}
	a.checkDefs[def.name] = def
	a.checkOrder = append(a.checkOrder, def.name)
	a.resortCheckOrder()
	return nil
}

// resortCheckOrder re-sorts checkOrder so that additions made after the initial
// parse remain in deterministic (sorted) order.
func (a *App) resortCheckOrder() {
	sort.Strings(a.checkOrder)
}

// loadChecksToml reads a checks.toml file from disk and parses it.
func loadChecksToml(path string) (string, map[string]*checkDef, []string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", nil, nil, err
	}
	return parseChecksToml(data)
}

// parseChecksToml parses TOML bytes and returns the app name, validated check definitions,
// and check names in sorted order (for deterministic listing).
func parseChecksToml(data []byte) (string, map[string]*checkDef, []string, error) {
	// Unmarshal into a generic map for strict validation
	var raw map[string]interface{}
	if err := tomledit.Unmarshal(data, &raw); err != nil {
		return "", nil, nil, fmt.Errorf("checks.toml: %s", err)
	}

	// Validate top-level keys: only "app" and "checks" are allowed
	for key := range raw {
		if key != "checks" && key != "app" {
			return "", nil, nil, fmt.Errorf("checks.toml: unknown top-level key %q", key)
		}
	}

	// Validate required "app" field
	appRaw, ok := raw["app"]
	if !ok {
		return "", nil, nil, fmt.Errorf("checks.toml: missing required top-level key \"app\"")
	}
	appName, ok := appRaw.(string)
	if !ok || appName == "" {
		return "", nil, nil, fmt.Errorf("checks.toml: \"app\" must be a non-empty string")
	}

	// Handle missing [checks] section gracefully — a file with just app = "x" is valid
	checksRaw, ok := raw["checks"]
	if !ok {
		return appName, make(map[string]*checkDef), nil, nil
	}

	checksMap, ok := checksRaw.(map[string]interface{})
	if !ok {
		return "", nil, nil, fmt.Errorf("checks.toml: [checks] must be a table")
	}

	result := make(map[string]*checkDef, len(checksMap))

	// Sort check names for deterministic error ordering
	names := make([]string, 0, len(checksMap))
	for name := range checksMap {
		names = append(names, name)
	}
	sort.Strings(names)

	for _, name := range names {
		val := checksMap[name]

		// Validate check name
		if !identifierRe.MatchString(name) {
			return "", nil, nil, fmt.Errorf("checks.toml: invalid check name %q (must match [a-z][a-z0-9-]*)", name)
		}

		fields, ok := val.(map[string]interface{})
		if !ok {
			return "", nil, nil, fmt.Errorf("checks.toml: check %q must be a table", name)
		}

		// Reject unknown fields
		for field := range fields {
			if !knownCheckFields[field] {
				return "", nil, nil, fmt.Errorf("checks.toml: check %q: unknown field %q", name, field)
			}
		}

		def := &checkDef{name: name}

		// Parse tags (required, []string — may be empty)
		if err := parseCheckTags(name, fields, def); err != nil {
			return "", nil, nil, err
		}

		// Parse severity (required, "error" or "warn")
		if err := parseCheckSeverity(name, fields, def); err != nil {
			return "", nil, nil, err
		}

		// Parse fast (required, bool)
		if err := parseCheckBool(name, fields, "fast", &def.fast); err != nil {
			return "", nil, nil, err
		}

		// Parse pure (required, bool)
		if err := parseCheckBool(name, fields, "pure", &def.pure); err != nil {
			return "", nil, nil, err
		}

		// Parse needs_network (required, bool)
		if err := parseCheckBool(name, fields, "needs_network", &def.needsNetwork); err != nil {
			return "", nil, nil, err
		}

		// Parse depends_on (required, []string, can be empty)
		if err := parseCheckDependsOn(name, fields, def); err != nil {
			return "", nil, nil, err
		}

		// Parse scope (optional, string, default "")
		if scopeRaw, ok := fields["scope"]; ok {
			scopeStr, ok := scopeRaw.(string)
			if !ok {
				return "", nil, nil, fmt.Errorf("checks.toml: check %q: \"scope\" must be a string, got %s", name, tomlTypeName(scopeRaw))
			}
			def.scope = scopeStr
		}

		result[name] = def
	}

	// Validate depends_on references
	for _, name := range names {
		def := result[name]
		for _, dep := range def.dependsOn {
			if _, ok := result[dep]; !ok {
				return "", nil, nil, fmt.Errorf("checks.toml: check %q: depends_on references unknown check %q", name, dep)
			}
		}
	}

	return appName, result, names, nil
}

// parseCheckTags extracts and validates the "tags" field.
func parseCheckTags(name string, fields map[string]interface{}, def *checkDef) error {
	raw, ok := fields["tags"]
	if !ok {
		return fmt.Errorf("checks.toml: check %q: missing required field %q", name, "tags")
	}
	arr, ok := raw.([]interface{})
	if !ok {
		return fmt.Errorf("checks.toml: check %q: \"tags\" must be a list of strings", name)
	}
	tags := make([]string, len(arr))
	for i, v := range arr {
		s, ok := v.(string)
		if !ok || strings.TrimSpace(s) == "" {
			return fmt.Errorf("checks.toml: check %q: \"tags\" entries must be non-empty strings", name)
		}
		tags[i] = s
	}
	def.tags = tags
	return nil
}

// parseCheckSeverity extracts and validates the "severity" field.
func parseCheckSeverity(name string, fields map[string]interface{}, def *checkDef) error {
	raw, ok := fields["severity"]
	if !ok {
		return fmt.Errorf("checks.toml: check %q: missing required field %q", name, "severity")
	}
	s, ok := raw.(string)
	if !ok || (s != "error" && s != "warn") {
		return fmt.Errorf("checks.toml: check %q: \"severity\" must be \"error\" or \"warn\", got %q", name, raw)
	}
	def.severity = s
	return nil
}

// parseCheckBool extracts and validates a required boolean field.
func parseCheckBool(name string, fields map[string]interface{}, field string, target *bool) error {
	raw, ok := fields[field]
	if !ok {
		return fmt.Errorf("checks.toml: check %q: missing required field %q", name, field)
	}
	b, ok := raw.(bool)
	if !ok {
		return fmt.Errorf("checks.toml: check %q: %q must be a boolean, got %s", name, field, tomlTypeName(raw))
	}
	*target = b
	return nil
}

// parseCheckDependsOn extracts and validates the "depends_on" field.
func parseCheckDependsOn(name string, fields map[string]interface{}, def *checkDef) error {
	raw, ok := fields["depends_on"]
	if !ok {
		return fmt.Errorf("checks.toml: check %q: missing required field %q", name, "depends_on")
	}
	arr, ok := raw.([]interface{})
	if !ok {
		return fmt.Errorf("checks.toml: check %q: \"depends_on\" must be a list of strings", name)
	}
	deps := make([]string, len(arr))
	for i, v := range arr {
		s, ok := v.(string)
		if !ok {
			return fmt.Errorf("checks.toml: check %q: \"depends_on\" entries must be strings", name)
		}
		deps[i] = s
	}
	def.dependsOn = deps
	return nil
}

// tomlTypeName returns a Python-compatible type name for a TOML-decoded value.
// Matches Python's type(val).__name__ output for cross-language error parity.
func tomlTypeName(v interface{}) string {
	switch v.(type) {
	case bool:
		return "bool"
	case int64:
		return "int"
	case float64:
		return "float"
	case string:
		return "str"
	case []interface{}:
		return "list"
	case map[string]interface{}:
		return "dict"
	case nil:
		return "NoneType"
	default:
		return fmt.Sprintf("%T", v)
	}
}
