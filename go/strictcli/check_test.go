package strictcli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCheckResultFields(t *testing.T) {
	r := CheckResult{
		Status:  "pass",
		Message: "all good",
		Details: []string{"detail1", "detail2"},
	}
	if r.Status != "pass" {
		t.Errorf("expected status 'pass', got %q", r.Status)
	}
	if r.Message != "all good" {
		t.Errorf("expected message 'all good', got %q", r.Message)
	}
	if len(r.Details) != 2 {
		t.Errorf("expected 2 details, got %d", len(r.Details))
	}
}

func writeToml(t *testing.T, dir, content string) string {
	t.Helper()
	path := filepath.Join(dir, "checks.toml")
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write checks.toml: %v", err)
	}
	return path
}

func TestLoadChecksToml_Valid(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.lint-code]
tags = ["code", "fast"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-deps]
tags = ["deps"]
severity = "warn"
fast = false
pure = false
needs_network = true
depends_on = ["lint-code"]
`)

	defs, err := loadChecksToml(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(defs) != 2 {
		t.Fatalf("expected 2 checks, got %d", len(defs))
	}

	t.Run("lint-code fields", func(t *testing.T) {
		d := defs["lint-code"]
		if d == nil {
			t.Fatal("lint-code not found")
		}
		if d.name != "lint-code" {
			t.Errorf("expected name 'lint-code', got %q", d.name)
		}
		if len(d.tags) != 2 || d.tags[0] != "code" || d.tags[1] != "fast" {
			t.Errorf("unexpected tags: %v", d.tags)
		}
		if d.severity != "error" {
			t.Errorf("expected severity 'error', got %q", d.severity)
		}
		if !d.fast {
			t.Error("expected fast=true")
		}
		if !d.pure {
			t.Error("expected pure=true")
		}
		if d.needsNetwork {
			t.Error("expected needs_network=false")
		}
		if len(d.dependsOn) != 0 {
			t.Errorf("expected empty depends_on, got %v", d.dependsOn)
		}
		if d.impl != nil {
			t.Error("expected impl to be nil")
		}
	})

	t.Run("check-deps fields", func(t *testing.T) {
		d := defs["check-deps"]
		if d == nil {
			t.Fatal("check-deps not found")
		}
		if d.severity != "warn" {
			t.Errorf("expected severity 'warn', got %q", d.severity)
		}
		if d.fast {
			t.Error("expected fast=false")
		}
		if d.pure {
			t.Error("expected pure=false")
		}
		if !d.needsNetwork {
			t.Error("expected needs_network=true")
		}
		if len(d.dependsOn) != 1 || d.dependsOn[0] != "lint-code" {
			t.Errorf("unexpected depends_on: %v", d.dependsOn)
		}
	})
}

func TestLoadChecksToml_MissingField(t *testing.T) {
	tests := []struct {
		name    string
		toml    string
		wantErr string
	}{
		{
			name: "missing tags",
			toml: `
[checks.foo]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "tags"`,
		},
		{
			name: "missing severity",
			toml: `
[checks.foo]
tags = ["a"]
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "severity"`,
		},
		{
			name: "missing fast",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "fast"`,
		},
		{
			name: "missing pure",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "pure"`,
		},
		{
			name: "missing needs_network",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
depends_on = []
`,
			wantErr: `checks.toml: check "foo": missing required field "needs_network"`,
		},
		{
			name: "missing depends_on",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
`,
			wantErr: `checks.toml: check "foo": missing required field "depends_on"`,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			path := writeToml(t, dir, tc.toml)
			_, err := loadChecksToml(path)
			if err == nil {
				t.Fatal("expected error, got nil")
			}
			if err.Error() != tc.wantErr {
				t.Errorf("expected error %q, got %q", tc.wantErr, err.Error())
			}
		})
	}
}

func TestLoadChecksToml_WrongTypes(t *testing.T) {
	tests := []struct {
		name    string
		toml    string
		wantErr string
	}{
		{
			name: "tags is string instead of array",
			toml: `
[checks.foo]
tags = "not-an-array"
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "tags" must be an array of strings`,
		},
		{
			name: "severity is integer",
			toml: `
[checks.foo]
tags = ["a"]
severity = 42
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "severity" must be a string`,
		},
		{
			name: "fast is string",
			toml: `
[checks.foo]
tags = ["a"]
severity = "error"
fast = "yes"
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "fast" must be a boolean`,
		},
		{
			name: "invalid severity value",
			toml: `
[checks.foo]
tags = ["a"]
severity = "critical"
fast = true
pure = true
needs_network = false
depends_on = []
`,
			wantErr: `checks.toml: check "foo": "severity" must be "error" or "warn", got "critical"`,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			path := writeToml(t, dir, tc.toml)
			_, err := loadChecksToml(path)
			if err == nil {
				t.Fatal("expected error, got nil")
			}
			if err.Error() != tc.wantErr {
				t.Errorf("expected error %q, got %q", tc.wantErr, err.Error())
			}
		})
	}
}

func TestLoadChecksToml_UnknownFields(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
extra_field = "bad"
`)
	_, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for unknown field")
	}
	if !strings.Contains(err.Error(), `unknown field "extra_field"`) {
		t.Errorf("expected error about unknown field, got %q", err.Error())
	}
}

func TestLoadChecksToml_UnknownTopLevelKey(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[metadata]
version = "1.0"
`)
	_, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for unknown top-level key")
	}
	if !strings.Contains(err.Error(), `unknown top-level key "metadata"`) {
		t.Errorf("expected error about unknown top-level key, got %q", err.Error())
	}
}

func TestLoadChecksToml_InvalidCheckName(t *testing.T) {
	tests := []struct {
		name     string
		checkName string
	}{
		{"starts with number", "1bad"},
		{"uppercase", "BadName"},
		{"contains underscore", "bad_name"},
		{"starts with hyphen", "-bad"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			toml := `
[checks.` + tc.checkName + `]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`
			path := writeToml(t, dir, toml)
			_, err := loadChecksToml(path)
			if err == nil {
				t.Fatal("expected error for invalid check name")
			}
			if !strings.Contains(err.Error(), "invalid check name") {
				t.Errorf("expected error about invalid check name, got %q", err.Error())
			}
		})
	}
}

func TestLoadChecksToml_DependsOnValidation(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["nonexistent"]
`)
	_, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for depends_on referencing unknown check")
	}
	if !strings.Contains(err.Error(), `depends_on references unknown check "nonexistent"`) {
		t.Errorf("expected error about unknown check reference, got %q", err.Error())
	}
}

func TestLoadChecksToml_EmptyTags(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[checks.foo]
tags = []
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
`)
	_, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for empty tags")
	}
	if !strings.Contains(err.Error(), `"tags" must be non-empty`) {
		t.Errorf("expected error about empty tags, got %q", err.Error())
	}
}

func TestLoadChecksToml_FileNotFound(t *testing.T) {
	_, err := loadChecksToml("/nonexistent/checks.toml")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestLoadChecksToml_MissingChecksKey(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, `
[something]
foo = "bar"
`)
	_, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for missing checks key")
	}
	if !strings.Contains(err.Error(), `unknown top-level key "something"`) {
		t.Errorf("expected error about unknown top-level key, got %q", err.Error())
	}
}

func TestLoadChecksToml_EmptyFile(t *testing.T) {
	dir := t.TempDir()
	path := writeToml(t, dir, ``)
	_, err := loadChecksToml(path)
	if err == nil {
		t.Fatal("expected error for empty file")
	}
	if !strings.Contains(err.Error(), `missing required top-level key "checks"`) {
		t.Errorf("expected error about missing checks key, got %q", err.Error())
	}
}
