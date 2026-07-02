package strictcli

import (
	"fmt"
	"strings"
	"testing"
)

// A flag registered with Default(nil) + Choices(...) means "optional; if
// passed, must be one of the choices". When the flag is NOT passed, its
// resolved value is nil and choices validation must be skipped -- nil only
// arises from Default(nil)/ArgDefault(nil)/unset mutex flags; a CLI-supplied
// value is never nil.

func TestFlagNilDefaultChoicesNotPassed(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Default(nil), Choices("text", "json"))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "format=None" {
		t.Fatalf("expected 'format=None', got %q", r.Stdout)
	}
}

func TestFlagNilDefaultChoicesPassedValid(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Default(nil), Choices("text", "json"))))
	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "format=json" {
		t.Fatalf("expected 'format=json', got %q", r.Stdout)
	}
}

func TestFlagNilDefaultChoicesPassedInvalid(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Default(nil), Choices("text", "json"))))
	r := app.Test([]string{"cmd", "--format", "xml"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--format: invalid value 'xml', must be one of: text, json") {
		t.Fatalf("expected choices error, got %q", r.Stderr)
	}
}

func TestArgNilDefaultChoicesNotPassed(t *testing.T) {
	app := simpleApp("cmd", "a command", "env={env}",
		WithArgs(NewArg("env", "target env", ArgRequired(false), ArgDefault(nil),
			ArgChoices("dev", "staging", "prod"))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "env=None" {
		t.Fatalf("expected 'env=None', got %q", r.Stdout)
	}
}

func TestArgOptionalNoDefaultChoicesNotPassed(t *testing.T) {
	// Optional arg with no default resolves to nil -- choices must not fire.
	app := simpleApp("cmd", "a command", "env={env}",
		WithArgs(NewArg("env", "target env", ArgRequired(false),
			ArgChoices("dev", "staging", "prod"))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "env=None" {
		t.Fatalf("expected 'env=None', got %q", r.Stdout)
	}
}

func TestArgNilDefaultChoicesPassedValid(t *testing.T) {
	app := simpleApp("cmd", "a command", "env={env}",
		WithArgs(NewArg("env", "target env", ArgRequired(false), ArgDefault(nil),
			ArgChoices("dev", "staging", "prod"))))
	r := app.Test([]string{"cmd", "prod"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "env=prod" {
		t.Fatalf("expected 'env=prod', got %q", r.Stdout)
	}
}

func TestArgNilDefaultChoicesPassedInvalid(t *testing.T) {
	app := simpleApp("cmd", "a command", "env={env}",
		WithArgs(NewArg("env", "target env", ArgRequired(false), ArgDefault(nil),
			ArgChoices("dev", "staging", "prod"))))
	r := app.Test([]string{"cmd", "local"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "argument 'env': invalid value 'local', must be one of: dev, staging, prod") {
		t.Fatalf("expected choices error, got %q", r.Stderr)
	}
}

func TestGlobalFlagNilDefaultChoicesNotPassed(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok")
	app.GlobalFlag(StringFlag("format", "output format", Default(nil), Choices("text", "json")))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
}

func TestGlobalFlagNilDefaultChoicesPassedInvalid(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok")
	app.GlobalFlag(StringFlag("format", "output format", Default(nil), Choices("text", "json")))
	r := app.Test([]string{"--format", "xml", "cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--format: invalid value 'xml', must be one of: text, json") {
		t.Fatalf("expected choices error, got %q", r.Stderr)
	}
}

func TestMutexFlagChoicesUnsetNotValidated(t *testing.T) {
	// An unset flag inside a mutex group resolves to nil; its choices must
	// not fire when the other group member is passed.
	app := simpleApp("cmd", "a command", "format={format} output={output}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				StringFlag("format", "output format", Default(nil), Choices("text", "json")),
				StringFlag("output", "output path", Default(nil)),
			},
		}))
	r := app.Test([]string{"cmd", "--output", "out.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "format=None output=out.txt" {
		t.Fatalf("expected 'format=None output=out.txt', got %q", r.Stdout)
	}
}

func TestFlagNilDefaultValidateNotCalled(t *testing.T) {
	// A custom validator must not run for a flag that was not passed
	// (resolved value nil) -- there is no value to validate.
	app := simpleApp("cmd", "a command", "name={name}",
		WithFlags(StringFlag("name", "a name", Default(nil),
			ValidateFn(func(v interface{}) error {
				s, ok := v.(string)
				if !ok {
					return fmt.Errorf("validator received non-string value %v", v)
				}
				if s == "bad" {
					return fmt.Errorf("bad name")
				}
				return nil
			}))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d; stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "name=None" {
		t.Fatalf("expected 'name=None', got %q", r.Stdout)
	}
	// Passed value still validated.
	r = app.Test([]string{"cmd", "--name", "bad"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1 for invalid value, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--name: bad name") {
		t.Fatalf("expected validator error, got %q", r.Stderr)
	}
}
