package strictcli

import (
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"

	tomledit "github.com/smm-h/go-toml-edit"
)

// CheckResult holds the outcome of a single check execution.
type CheckResult struct {
	Status  string   // "pass", "fail", "warn", "skip"
	Message string   // one-line summary
	Details []string // specific findings
}

// CheckContext provides project context to check implementations.
type CheckContext interface {
	ProjectRoot() string
}

// checkDef holds the definition of a single check loaded from checks.toml.
type checkDef struct {
	name         string
	tags         []string
	severity     string // "error" or "warn"
	fast         bool
	pure         bool
	needsNetwork bool
	dependsOn    []string
	impl         func(CheckContext) CheckResult // registered implementation, nil initially
}

// checkNameRe validates check names: lowercase letter followed by lowercase letters, digits, or hyphens.
var checkNameRe = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)

// knownCheckFields enumerates the allowed fields in a check definition table.
var knownCheckFields = map[string]bool{
	"tags":          true,
	"severity":      true,
	"fast":          true,
	"pure":          true,
	"needs_network": true,
	"depends_on":    true,
}

// loadChecksToml parses a checks.toml file and returns validated check definitions
// along with check names in sorted order (for deterministic listing).
func loadChecksToml(path string) (map[string]*checkDef, []string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, err
	}

	// Unmarshal into a generic map for strict validation
	var raw map[string]interface{}
	if err := tomledit.Unmarshal(data, &raw); err != nil {
		return nil, nil, fmt.Errorf("checks.toml: %s", err)
	}

	// Validate only "checks" as a top-level key
	for key := range raw {
		if key != "checks" {
			return nil, nil, fmt.Errorf("checks.toml: unknown top-level key %q", key)
		}
	}

	checksRaw, ok := raw["checks"]
	if !ok {
		return nil, nil, fmt.Errorf("checks.toml: missing required top-level key \"checks\"")
	}

	checksMap, ok := checksRaw.(map[string]interface{})
	if !ok {
		return nil, nil, fmt.Errorf("checks.toml: [checks] must be a table")
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
		if !checkNameRe.MatchString(name) {
			return nil, nil, fmt.Errorf("checks.toml: invalid check name %q (must match [a-z][a-z0-9-]*)", name)
		}

		fields, ok := val.(map[string]interface{})
		if !ok {
			return nil, nil, fmt.Errorf("checks.toml: check %q must be a table", name)
		}

		// Reject unknown fields
		for field := range fields {
			if !knownCheckFields[field] {
				return nil, nil, fmt.Errorf("checks.toml: check %q: unknown field %q", name, field)
			}
		}

		def := &checkDef{name: name}

		// Parse tags (required, []string — may be empty)
		if err := parseCheckTags(name, fields, def); err != nil {
			return nil, nil, err
		}

		// Parse severity (required, "error" or "warn")
		if err := parseCheckSeverity(name, fields, def); err != nil {
			return nil, nil, err
		}

		// Parse fast (required, bool)
		if err := parseCheckBool(name, fields, "fast", &def.fast); err != nil {
			return nil, nil, err
		}

		// Parse pure (required, bool)
		if err := parseCheckBool(name, fields, "pure", &def.pure); err != nil {
			return nil, nil, err
		}

		// Parse needs_network (required, bool)
		if err := parseCheckBool(name, fields, "needs_network", &def.needsNetwork); err != nil {
			return nil, nil, err
		}

		// Parse depends_on (required, []string, can be empty)
		if err := parseCheckDependsOn(name, fields, def); err != nil {
			return nil, nil, err
		}

		result[name] = def
	}

	// Validate depends_on references
	for _, name := range names {
		def := result[name]
		for _, dep := range def.dependsOn {
			if _, ok := result[dep]; !ok {
				return nil, nil, fmt.Errorf("checks.toml: check %q: depends_on references unknown check %q", name, dep)
			}
		}
	}

	return result, names, nil
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
