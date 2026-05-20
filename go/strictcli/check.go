package strictcli

import (
	"fmt"
	"os"
	"regexp"
	"sort"

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
	impl         interface{} // registered implementation function, nil initially
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

// loadChecksToml parses a checks.toml file and returns validated check definitions.
func loadChecksToml(path string) (map[string]*checkDef, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	// Unmarshal into a generic map for strict validation
	var raw map[string]interface{}
	if err := tomledit.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("checks.toml: %s", err)
	}

	// Validate only "checks" as a top-level key
	for key := range raw {
		if key != "checks" {
			return nil, fmt.Errorf("checks.toml: unknown top-level key %q", key)
		}
	}

	checksRaw, ok := raw["checks"]
	if !ok {
		return nil, fmt.Errorf("checks.toml: missing required top-level key \"checks\"")
	}

	checksMap, ok := checksRaw.(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("checks.toml: \"checks\" must be a table")
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
			return nil, fmt.Errorf("checks.toml: invalid check name %q (must match [a-z][a-z0-9-]*)", name)
		}

		fields, ok := val.(map[string]interface{})
		if !ok {
			return nil, fmt.Errorf("checks.toml: check %q must be a table", name)
		}

		// Reject unknown fields
		for field := range fields {
			if !knownCheckFields[field] {
				return nil, fmt.Errorf("checks.toml: check %q: unknown field %q", name, field)
			}
		}

		def := &checkDef{name: name}

		// Parse tags (required, non-empty []string)
		if err := parseCheckTags(name, fields, def); err != nil {
			return nil, err
		}

		// Parse severity (required, "error" or "warn")
		if err := parseCheckSeverity(name, fields, def); err != nil {
			return nil, err
		}

		// Parse fast (required, bool)
		if err := parseCheckBool(name, fields, "fast", &def.fast); err != nil {
			return nil, err
		}

		// Parse pure (required, bool)
		if err := parseCheckBool(name, fields, "pure", &def.pure); err != nil {
			return nil, err
		}

		// Parse needs_network (required, bool)
		if err := parseCheckBool(name, fields, "needs_network", &def.needsNetwork); err != nil {
			return nil, err
		}

		// Parse depends_on (required, []string, can be empty)
		if err := parseCheckDependsOn(name, fields, def); err != nil {
			return nil, err
		}

		result[name] = def
	}

	// Validate depends_on references
	for _, name := range names {
		def := result[name]
		for _, dep := range def.dependsOn {
			if _, ok := result[dep]; !ok {
				return nil, fmt.Errorf("checks.toml: check %q: depends_on references unknown check %q", name, dep)
			}
		}
	}

	return result, nil
}

// parseCheckTags extracts and validates the "tags" field.
func parseCheckTags(name string, fields map[string]interface{}, def *checkDef) error {
	raw, ok := fields["tags"]
	if !ok {
		return fmt.Errorf("checks.toml: check %q: missing required field \"tags\"", name)
	}
	arr, ok := raw.([]interface{})
	if !ok {
		return fmt.Errorf("checks.toml: check %q: \"tags\" must be an array of strings", name)
	}
	if len(arr) == 0 {
		return fmt.Errorf("checks.toml: check %q: \"tags\" must be non-empty", name)
	}
	tags := make([]string, len(arr))
	for i, v := range arr {
		s, ok := v.(string)
		if !ok {
			return fmt.Errorf("checks.toml: check %q: \"tags\" must be an array of strings", name)
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
		return fmt.Errorf("checks.toml: check %q: missing required field \"severity\"", name)
	}
	s, ok := raw.(string)
	if !ok {
		return fmt.Errorf("checks.toml: check %q: \"severity\" must be a string", name)
	}
	if s != "error" && s != "warn" {
		return fmt.Errorf("checks.toml: check %q: \"severity\" must be \"error\" or \"warn\", got %q", name, s)
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
		return fmt.Errorf("checks.toml: check %q: %q must be a boolean", name, field)
	}
	*target = b
	return nil
}

// parseCheckDependsOn extracts and validates the "depends_on" field.
func parseCheckDependsOn(name string, fields map[string]interface{}, def *checkDef) error {
	raw, ok := fields["depends_on"]
	if !ok {
		return fmt.Errorf("checks.toml: check %q: missing required field \"depends_on\"", name)
	}
	arr, ok := raw.([]interface{})
	if !ok {
		return fmt.Errorf("checks.toml: check %q: \"depends_on\" must be an array of strings", name)
	}
	deps := make([]string, len(arr))
	for i, v := range arr {
		s, ok := v.(string)
		if !ok {
			return fmt.Errorf("checks.toml: check %q: \"depends_on\" must be an array of strings", name)
		}
		deps[i] = s
	}
	def.dependsOn = deps
	return nil
}
