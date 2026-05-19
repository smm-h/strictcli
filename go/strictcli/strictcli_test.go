package strictcli

import (
	"fmt"
	"os"
	"strings"
	"testing"
)

// helper to build a simple app with one command that prints a template
func simpleApp(cmdName, cmdHelp, handlerPrints string, opts ...CmdOption) *App {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command(cmdName, cmdHelp, func(args map[string]interface{}) int {
		out := handlerPrints
		for k, v := range args {
			out = strings.ReplaceAll(out, "{"+k+"}", formatValue(v))
		}
		fmt.Print(out)
		return 0
	}, opts...)
	return app
}

// formatValue formats a value the way conformance tests expect
func formatValue(v interface{}) string {
	if v == nil {
		return "None"
	}
	switch val := v.(type) {
	case bool:
		if val {
			return "true"
		}
		return "false"
	case []interface{}:
		parts := make([]string, len(val))
		for i, item := range val {
			parts[i] = fmt.Sprintf("%v", item)
		}
		return strings.Join(parts, ",")
	default:
		return fmt.Sprintf("%v", val)
	}
}

// --- Basic tests ---

func TestBasicDispatch(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello")
	r := app.Test([]string{"greet"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "hello") {
		t.Fatalf("stdout should contain 'hello', got %q", r.Stdout)
	}
}

func TestBasicUnknownCommand(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello")
	r := app.Test([]string{"deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown command") {
		t.Fatalf("stderr should contain 'unknown command', got %q", r.Stderr)
	}
}

func TestBasicNoArgs(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello")
	r := app.Test([]string{})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "myapp v1.0.0") {
		t.Fatalf("stdout should contain version, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "Commands:") {
		t.Fatalf("stdout should contain 'Commands:', got %q", r.Stdout)
	}
}

func TestVersionFlag(t *testing.T) {
	app := NewApp("myapp", "2.5.0", "test app")
	app.Command("greet", "say hello", func(args map[string]interface{}) int { return 0 }, )
	r := app.Test([]string{"--version"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "myapp 2.5.0") {
		t.Fatalf("stdout should contain 'myapp 2.5.0', got %q", r.Stdout)
	}
}

func TestShortVersionFlag(t *testing.T) {
	app := NewApp("myapp", "2.5.0", "test app")
	app.Command("greet", "say hello", func(args map[string]interface{}) int { return 0 }, )
	r := app.Test([]string{"-v"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "myapp 2.5.0") {
		t.Fatalf("stdout should contain 'myapp 2.5.0', got %q", r.Stdout)
	}
}

func TestHelpFlag(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello")
	r := app.Test([]string{"--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "myapp v1.0.0") {
		t.Fatalf("stdout should contain version, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "test app") {
		t.Fatalf("stdout should contain help text, got %q", r.Stdout)
	}
}

func TestShortHelpFlag(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello")
	r := app.Test([]string{"-h"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "myapp v1.0.0") {
		t.Fatalf("stdout should contain version, got %q", r.Stdout)
	}
}

func TestMultipleCommands(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("start", "start service", func(args map[string]interface{}) int {
		fmt.Print("started")
		return 0
	})
	app.Command("stop", "stop service", func(args map[string]interface{}) int {
		fmt.Print("stopped")
		return 0
	})
	r := app.Test([]string{"stop"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "stopped") {
		t.Fatalf("stdout should contain 'stopped', got %q", r.Stdout)
	}
}

// --- Flag tests ---

func TestStrFlagSpaceSyntax(t *testing.T) {
	app := simpleApp("cmd", "a command", "target={target}",
		WithFlags(StringFlag("target", "the target")))
	r := app.Test([]string{"cmd", "--target", "foo"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "target=foo") {
		t.Fatalf("stdout should contain 'target=foo', got %q", r.Stdout)
	}
}

func TestStrFlagEqualsSyntax(t *testing.T) {
	app := simpleApp("cmd", "a command", "target={target}",
		WithFlags(StringFlag("target", "the target")))
	r := app.Test([]string{"cmd", "--target=bar"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "target=bar") {
		t.Fatalf("stdout should contain 'target=bar', got %q", r.Stdout)
	}
}

func TestBoolFlagPresent(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose}",
		WithFlags(BoolFlag("verbose", "be verbose")))
	r := app.Test([]string{"cmd", "--verbose"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "verbose=true") {
		t.Fatalf("stdout should contain 'verbose=true', got %q", r.Stdout)
	}
}

func TestBoolFlagAbsent(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose}",
		WithFlags(BoolFlag("verbose", "be verbose")))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "verbose=false") {
		t.Fatalf("stdout should contain 'verbose=false', got %q", r.Stdout)
	}
}

func TestBoolFlagNegation(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose}",
		WithFlags(BoolFlag("verbose", "be verbose")))
	r := app.Test([]string{"cmd", "--no-verbose"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "verbose=false") {
		t.Fatalf("stdout should contain 'verbose=false', got %q", r.Stdout)
	}
}

func TestShortBoolFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose}",
		WithFlags(BoolFlag("verbose", "be verbose", Short("V"))))
	r := app.Test([]string{"cmd", "-V"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "verbose=true") {
		t.Fatalf("stdout should contain 'verbose=true', got %q", r.Stdout)
	}
}

func TestShortStrFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "target={target}",
		WithFlags(StringFlag("target", "the target", Short("t"))))
	r := app.Test([]string{"cmd", "-t", "foo"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "target=foo") {
		t.Fatalf("stdout should contain 'target=foo', got %q", r.Stdout)
	}
}

func TestStrFlagDefault(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Default("text"))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "format=text") {
		t.Fatalf("stdout should contain 'format=text', got %q", r.Stdout)
	}
}

func TestStrFlagDefaultOverride(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Default("text"))))
	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "format=json") {
		t.Fatalf("stdout should contain 'format=json', got %q", r.Stdout)
	}
}

func TestRequiredStrFlagMissing(t *testing.T) {
	app := simpleApp("cmd", "a command", "target={target}",
		WithFlags(StringFlag("target", "the target")))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "required") {
		t.Fatalf("stderr should contain 'required', got %q", r.Stderr)
	}
}

func TestBoolFlagEqualsSyntaxRejected(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose}",
		WithFlags(BoolFlag("verbose", "be verbose")))
	r := app.Test([]string{"cmd", "--verbose=true"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "boolean flag") {
		t.Fatalf("stderr should contain 'boolean flag', got %q", r.Stderr)
	}
}

// --- Arg tests ---

func TestSingleRequiredArg(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello {name}",
		WithArgs(NewArg("name", "who to greet")))
	r := app.Test([]string{"greet", "world"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "hello world") {
		t.Fatalf("stdout should contain 'hello world', got %q", r.Stdout)
	}
}

func TestMissingRequiredArg(t *testing.T) {
	app := simpleApp("greet", "say hello", "hello {name}",
		WithArgs(NewArg("name", "who to greet")))
	r := app.Test([]string{"greet"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "missing required argument") {
		t.Fatalf("stderr should contain 'missing required argument', got %q", r.Stderr)
	}
}

func TestTwoPositionalArgs(t *testing.T) {
	app := simpleApp("copy", "copy files", "{src}->{dst}",
		WithArgs(NewArg("src", "source file"), NewArg("dst", "destination file")))
	r := app.Test([]string{"copy", "a.txt", "b.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "a.txt->b.txt") {
		t.Fatalf("stdout should contain 'a.txt->b.txt', got %q", r.Stdout)
	}
}

func TestExtraPositionalArgRejected(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok")
	r := app.Test([]string{"cmd", "surprise"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unexpected argument") {
		t.Fatalf("stderr should contain 'unexpected argument', got %q", r.Stderr)
	}
}

func TestOptionalArgWithDefault(t *testing.T) {
	app := simpleApp("cmd", "a command", "path={path}",
		WithArgs(NewArg("path", "project dir", ArgRequired(false), ArgDefault("."))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "path=.") {
		t.Fatalf("stdout should contain 'path=.', got %q", r.Stdout)
	}
}

func TestOptionalArgProvided(t *testing.T) {
	app := simpleApp("cmd", "a command", "path={path}",
		WithArgs(NewArg("path", "project dir", ArgRequired(false), ArgDefault("."))))
	r := app.Test([]string{"cmd", "/tmp/foo"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "path=/tmp/foo") {
		t.Fatalf("stdout should contain 'path=/tmp/foo', got %q", r.Stdout)
	}
}

func TestOptionalArgNoDefault(t *testing.T) {
	app := simpleApp("cmd", "a command", "path={path}",
		WithArgs(NewArg("path", "project dir", ArgRequired(false))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "path=None") {
		t.Fatalf("stdout should contain 'path=None', got %q", r.Stdout)
	}
}

func TestDoubleDashStopsFlagParsing(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose} path={path}",
		WithFlags(BoolFlag("verbose", "be verbose")),
		WithArgs(NewArg("path", "a path")))
	r := app.Test([]string{"cmd", "--", "--not-a-flag"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "verbose=false") {
		t.Fatalf("stdout should contain 'verbose=false', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "path=--not-a-flag") {
		t.Fatalf("stdout should contain 'path=--not-a-flag', got %q", r.Stdout)
	}
}

// --- Int type tests ---

func TestIntFlagParses(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port")))
	r := app.Test([]string{"cmd", "--port", "8080"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "port=8080") {
		t.Fatalf("stdout should contain 'port=8080', got %q", r.Stdout)
	}
}

func TestIntFlagDefault(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port", Default(8000))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "port=8000") {
		t.Fatalf("stdout should contain 'port=8000', got %q", r.Stdout)
	}
}

func TestIntFlagBadValue(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port")))
	r := app.Test([]string{"cmd", "--port", "abc"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "expected integer") {
		t.Fatalf("stderr should contain 'expected integer', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "'abc'") {
		t.Fatalf("stderr should contain 'abc', got %q", r.Stderr)
	}
}

func TestIntFlagEqualsSyntax(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port")))
	r := app.Test([]string{"cmd", "--port=8080"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "port=8080") {
		t.Fatalf("stdout should contain 'port=8080', got %q", r.Stdout)
	}
}

func TestIntFlagShort(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port", Short("p"))))
	r := app.Test([]string{"cmd", "-p", "8080"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "port=8080") {
		t.Fatalf("stdout should contain 'port=8080', got %q", r.Stdout)
	}
}

func TestIntFlagRequired(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port")))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "required") {
		t.Fatalf("stderr should contain 'required', got %q", r.Stderr)
	}
}

// --- Env tests ---

func TestEnvStrFlag(t *testing.T) {
	os.Setenv("MYAPP_TARGET", "from-env")
	defer os.Unsetenv("MYAPP_TARGET")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("target=" + formatValue(args["target"]))
		return 0
	}, WithFlags(StringFlag("target", "the target", Default("fallback"), Env("MYAPP_TARGET"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "target=from-env") {
		t.Fatalf("stdout should contain 'target=from-env', got %q", r.Stdout)
	}
}

func TestEnvCLIOverrides(t *testing.T) {
	os.Setenv("MYAPP_TARGET", "from-env")
	defer os.Unsetenv("MYAPP_TARGET")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("target=" + formatValue(args["target"]))
		return 0
	}, WithFlags(StringFlag("target", "the target", Default("fallback"), Env("MYAPP_TARGET"))))

	r := app.Test([]string{"cmd", "--target", "from-cli"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "target=from-cli") {
		t.Fatalf("stdout should contain 'target=from-cli', got %q", r.Stdout)
	}
}

func TestEnvBoolTrue(t *testing.T) {
	for _, val := range []string{"true", "1", "yes"} {
		os.Setenv("MYAPP_VERBOSE", val)
		app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
		app.Command("cmd", "a command", func(args map[string]interface{}) int {
			fmt.Print("verbose=" + formatValue(args["verbose"]))
			return 0
		}, WithFlags(BoolFlag("verbose", "be verbose", Env("MYAPP_VERBOSE"))))

		r := app.Test([]string{"cmd"})
		if r.ExitCode != 0 {
			t.Fatalf("val=%q: expected exit 0, got %d", val, r.ExitCode)
		}
		if !strings.Contains(r.Stdout, "verbose=true") {
			t.Fatalf("val=%q: stdout should contain 'verbose=true', got %q", val, r.Stdout)
		}
		os.Unsetenv("MYAPP_VERBOSE")
	}
}

func TestEnvBoolFalse(t *testing.T) {
	for _, val := range []string{"false", "0", "no"} {
		os.Setenv("MYAPP_VERBOSE", val)
		app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
		app.Command("cmd", "a command", func(args map[string]interface{}) int {
			fmt.Print("verbose=" + formatValue(args["verbose"]))
			return 0
		}, WithFlags(BoolFlag("verbose", "be verbose", Env("MYAPP_VERBOSE"))))

		r := app.Test([]string{"cmd"})
		if r.ExitCode != 0 {
			t.Fatalf("val=%q: expected exit 0, got %d", val, r.ExitCode)
		}
		if !strings.Contains(r.Stdout, "verbose=false") {
			t.Fatalf("val=%q: stdout should contain 'verbose=false', got %q", val, r.Stdout)
		}
		os.Unsetenv("MYAPP_VERBOSE")
	}
}

func TestEnvBoolInvalid(t *testing.T) {
	os.Setenv("MYAPP_VERBOSE", "maybe")
	defer os.Unsetenv("MYAPP_VERBOSE")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(BoolFlag("verbose", "be verbose", Env("MYAPP_VERBOSE"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "invalid boolean value") {
		t.Fatalf("stderr should contain 'invalid boolean value', got %q", r.Stderr)
	}
}

func TestEnvIntFlag(t *testing.T) {
	os.Setenv("MYAPP_PORT", "9090")
	defer os.Unsetenv("MYAPP_PORT")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("port=" + formatValue(args["port"]))
		return 0
	}, WithFlags(IntFlag("port", "the port", Default(80), Env("MYAPP_PORT"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "port=9090") {
		t.Fatalf("stdout should contain 'port=9090', got %q", r.Stdout)
	}
}

func TestEnvIntBadValue(t *testing.T) {
	os.Setenv("MYAPP_PORT", "abc")
	defer os.Unsetenv("MYAPP_PORT")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(IntFlag("port", "the port", Default(80), Env("MYAPP_PORT"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "expected integer") {
		t.Fatalf("stderr should contain 'expected integer', got %q", r.Stderr)
	}
}

// --- Choices tests ---

func TestChoicesValidStr(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Choices("text", "json"))))
	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "format=json") {
		t.Fatalf("stdout should contain 'format=json', got %q", r.Stdout)
	}
}

func TestChoicesInvalidStr(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format}",
		WithFlags(StringFlag("format", "output format", Choices("text", "json"))))
	r := app.Test([]string{"cmd", "--format", "xml"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "invalid value") {
		t.Fatalf("stderr should contain 'invalid value', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "'xml'") {
		t.Fatalf("stderr should contain 'xml', got %q", r.Stderr)
	}
}

func TestChoicesValidInt(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port", Choices(80, 443, 8080))))
	r := app.Test([]string{"cmd", "--port", "443"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "port=443") {
		t.Fatalf("stdout should contain 'port=443', got %q", r.Stdout)
	}
}

func TestChoicesInvalidInt(t *testing.T) {
	app := simpleApp("cmd", "a command", "port={port}",
		WithFlags(IntFlag("port", "the port", Choices(80, 443, 8080))))
	r := app.Test([]string{"cmd", "--port", "9090"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "invalid value") {
		t.Fatalf("stderr should contain 'invalid value', got %q", r.Stderr)
	}
}

func TestChoicesInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(StringFlag("format", "output format", Default("text"), Choices("text", "json"))))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "choices: text, json") {
		t.Fatalf("stdout should contain 'choices: text, json', got %q", r.Stdout)
	}
}

// --- Error tests ---

func TestUnknownFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(BoolFlag("verbose", "be verbose")))
	r := app.Test([]string{"cmd", "--unknown"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown flag") {
		t.Fatalf("stderr should contain 'unknown flag', got %q", r.Stderr)
	}
}

func TestUnknownShortFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok")
	r := app.Test([]string{"cmd", "-x"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown flag") {
		t.Fatalf("stderr should contain 'unknown flag', got %q", r.Stderr)
	}
}

func TestFlagRequiresValue(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(StringFlag("target", "the target")))
	r := app.Test([]string{"cmd", "--target"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "requires a value") {
		t.Fatalf("stderr should contain 'requires a value', got %q", r.Stderr)
	}
}

func TestErrorIncludesTryHint(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok")
	r := app.Test([]string{"unknown"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown command") {
		t.Fatalf("stderr should contain 'unknown command', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "try 'myapp --help'") {
		t.Fatalf("stderr should contain try hint, got %q", r.Stderr)
	}
}

func TestBoolNegationWithValueRejected(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(BoolFlag("verbose", "be verbose")))
	r := app.Test([]string{"cmd", "--no-verbose=true"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "boolean negation") {
		t.Fatalf("stderr should contain 'boolean negation', got %q", r.Stderr)
	}
}

// --- Repeatable tests ---

func TestRepeatableSingle(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Repeatable())))
	r := app.Test([]string{"cmd", "--tag", "alpha"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=alpha") {
		t.Fatalf("stdout should contain 'tags=alpha', got %q", r.Stdout)
	}
}

func TestRepeatableMultiple(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Repeatable())))
	r := app.Test([]string{"cmd", "--tag", "alpha", "--tag", "beta", "--tag", "gamma"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=alpha,beta,gamma") {
		t.Fatalf("stdout should contain 'tags=alpha,beta,gamma', got %q", r.Stdout)
	}
}

func TestRepeatableZero(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Repeatable())))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=") {
		t.Fatalf("stdout should contain 'tags=', got %q", r.Stdout)
	}
}

func TestRepeatableInt(t *testing.T) {
	app := simpleApp("cmd", "a command", "ports={port}",
		WithFlags(IntFlag("port", "a port", Repeatable())))
	r := app.Test([]string{"cmd", "--port", "80", "--port", "443"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "ports=80,443") {
		t.Fatalf("stdout should contain 'ports=80,443', got %q", r.Stdout)
	}
}

func TestRepeatableWithChoicesValid(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Repeatable(), Choices("alpha", "beta", "gamma"))))
	r := app.Test([]string{"cmd", "--tag", "alpha", "--tag", "gamma"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=alpha,gamma") {
		t.Fatalf("stdout should contain 'tags=alpha,gamma', got %q", r.Stdout)
	}
}

func TestRepeatableWithChoicesInvalid(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Repeatable(), Choices("alpha", "beta"))))
	r := app.Test([]string{"cmd", "--tag", "alpha", "--tag", "delta"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "invalid value") {
		t.Fatalf("stderr should contain 'invalid value', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "'delta'") {
		t.Fatalf("stderr should contain 'delta', got %q", r.Stderr)
	}
}

func TestRepeatableEquals(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Repeatable())))
	r := app.Test([]string{"cmd", "--tag=alpha", "--tag=beta"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=alpha,beta") {
		t.Fatalf("stdout should contain 'tags=alpha,beta', got %q", r.Stdout)
	}
}

func TestRepeatableShortFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "tags={tag}",
		WithFlags(StringFlag("tag", "a tag", Short("t"), Repeatable())))
	r := app.Test([]string{"cmd", "-t", "alpha", "-t", "beta"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=alpha,beta") {
		t.Fatalf("stdout should contain 'tags=alpha,beta', got %q", r.Stdout)
	}
}

func TestRepeatableInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(StringFlag("tag", "a tag", Repeatable())))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "repeatable") {
		t.Fatalf("stdout should contain 'repeatable', got %q", r.Stdout)
	}
}

func TestRepeatableEnv(t *testing.T) {
	os.Setenv("MYAPP_TAG", "fromenv")
	defer os.Unsetenv("MYAPP_TAG")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("tags=" + formatValue(args["tag"]))
		return 0
	}, WithFlags(StringFlag("tag", "a tag", Repeatable(), Env("MYAPP_TAG"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "tags=fromenv") {
		t.Fatalf("stdout should contain 'tags=fromenv', got %q", r.Stdout)
	}
}

// --- Mutex tests ---

func TestMutexNeitherProvided(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose} quiet={quiet}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "one of") || !strings.Contains(r.Stderr, "is required") {
		t.Fatalf("stderr should contain 'one of' and 'is required', got %q", r.Stderr)
	}
}

func TestMutexOneProvided(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose} quiet={quiet}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd", "--verbose"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "verbose=true") {
		t.Fatalf("stdout should contain 'verbose=true', got %q", r.Stdout)
	}
}

func TestMutexBothProvidedError(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd", "--verbose", "--quiet"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "--verbose") || !strings.Contains(r.Stderr, "--quiet") {
		t.Fatalf("stderr should mention both flags, got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "mutually exclusive") {
		t.Fatalf("stderr should contain 'mutually exclusive', got %q", r.Stderr)
	}
}

func TestMutexRequiredNoneError(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "required") {
		t.Fatalf("stderr should contain 'required', got %q", r.Stderr)
	}
}

func TestMutexRequiredOneOk(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose} quiet={quiet}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd", "--quiet"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "quiet=true") {
		t.Fatalf("stdout should contain 'quiet=true', got %q", r.Stdout)
	}
}

func TestMutexStrFlags(t *testing.T) {
	app := simpleApp("fetch", "fetch data", "file={file} url={url}",
		WithMutex(MutexGroup{
			Flags: []Flag{
				StringFlag("file", "read from file", Default(nil)),
				StringFlag("url", "read from URL", Default(nil)),
			},
		}))
	r := app.Test([]string{"fetch", "--file", "data.txt"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "file=data.txt") {
		t.Fatalf("stdout should contain 'file=data.txt', got %q", r.Stdout)
	}
}

func TestMutexStrFlagsBothError(t *testing.T) {
	app := simpleApp("fetch", "fetch data", "ok",
		WithMutex(MutexGroup{
			Flags: []Flag{
				StringFlag("file", "read from file", Default(nil)),
				StringFlag("url", "read from URL", Default(nil)),
			},
		}))
	r := app.Test([]string{"fetch", "--file", "data.txt", "--url", "http://example.com"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "mutually exclusive") {
		t.Fatalf("stderr should contain 'mutually exclusive', got %q", r.Stderr)
	}
}

func TestMutexHelpSection(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(StringFlag("name", "your name", Default("anon"))),
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Flags (mutually exclusive):") {
		t.Fatalf("stdout should contain mutex section header, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "--verbose") || !strings.Contains(r.Stdout, "--quiet") {
		t.Fatalf("stdout should contain mutex flags, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "Flags:") || !strings.Contains(r.Stdout, "--name") {
		t.Fatalf("stdout should contain regular flags, got %q", r.Stdout)
	}
}

func TestMutexRequiredInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithMutex(MutexGroup{
			Flags: []Flag{
				BoolFlag("verbose", "verbose output"),
				BoolFlag("quiet", "quiet output"),
			},
		}))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Flags (mutually exclusive):") {
		t.Fatalf("stdout should contain required mutex header, got %q", r.Stdout)
	}
}

// --- Nesting (Group) tests ---

func TestGroupDispatch(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int {
		fmt.Print("showing config")
		return 0
	})
	r := app.Test([]string{"config", "show"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "showing config") {
		t.Fatalf("stdout should contain 'showing config', got %q", r.Stdout)
	}
}

func TestGroupCommandWithFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("set", "set a config value", func(args map[string]interface{}) int {
		fmt.Printf("%s=%s", args["key"], args["value"])
		return 0
	}, WithFlags(
		StringFlag("key", "config key"),
		StringFlag("value", "config value"),
	))
	r := app.Test([]string{"config", "set", "--key", "name", "--value", "strictcli"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "name=strictcli") {
		t.Fatalf("stdout should contain 'name=strictcli', got %q", r.Stdout)
	}
}

func TestGroupUnknownSubcommand(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	r := app.Test([]string{"config", "delete"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "unknown command") {
		t.Fatalf("stderr should contain 'unknown command', got %q", r.Stderr)
	}
}

func TestGroupHelp(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	g.Command("set", "set a config value", func(args map[string]interface{}) int { return 0 })
	r := app.Test([]string{"config", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "show") || !strings.Contains(r.Stdout, "set") {
		t.Fatalf("stdout should list subcommands, got %q", r.Stdout)
	}
}

func TestGroupNoSubcommandShowsHelp(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	r := app.Test([]string{"config"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "manage configuration") {
		t.Fatalf("stdout should contain group help, got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "show") {
		t.Fatalf("stdout should list subcommands, got %q", r.Stdout)
	}
}

func TestGroupCommandHelpShowsPrefix(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("set", "set a config value", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("key", "config key"), StringFlag("value", "config value")))
	r := app.Test([]string{"config", "set", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "config set") {
		t.Fatalf("stdout should contain 'config set', got %q", r.Stdout)
	}
}

func TestGroupUseHint(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	r := app.Test([]string{"config", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Use 'myapp config <command> --help' for more information.") {
		t.Fatalf("stdout should contain use hint, got %q", r.Stdout)
	}
}

func TestAppHelpShowsGroups(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	r := app.Test([]string{})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Groups:") {
		t.Fatalf("stdout should contain 'Groups:', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "config") {
		t.Fatalf("stdout should contain 'config', got %q", r.Stdout)
	}
}

// --- Tag tests ---

func TestTagSingleFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "verbose={verbose}",
		WithTags(Tag{
			Name: "verbose",
			Flags: []Flag{BoolFlag("verbose", "verbose output")},
		}))
	r := app.Test([]string{"cmd", "--verbose"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "verbose=true") {
		t.Fatalf("stdout should contain 'verbose=true', got %q", r.Stdout)
	}
}

func TestTagMultipleFlags(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format} color={color}",
		WithTags(Tag{
			Name: "output",
			Flags: []Flag{
				StringFlag("format", "output format", Default("text")),
				BoolFlag("color", "use color"),
			},
		}))
	r := app.Test([]string{"cmd", "--format", "json", "--color"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "format=json") {
		t.Fatalf("stdout should contain 'format=json', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "color=true") {
		t.Fatalf("stdout should contain 'color=true', got %q", r.Stdout)
	}
}

func TestTagFlagsWithDefaults(t *testing.T) {
	app := simpleApp("deploy", "deploy the app", "token={token} insecure={insecure}",
		WithTags(Tag{
			Name: "auth",
			Flags: []Flag{
				StringFlag("token", "auth token", Default("none")),
				BoolFlag("insecure", "skip TLS verification"),
			},
		}))
	r := app.Test([]string{"deploy"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "token=none") {
		t.Fatalf("stdout should contain 'token=none', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "insecure=false") {
		t.Fatalf("stdout should contain 'insecure=false', got %q", r.Stdout)
	}
}

func TestTagFlagsInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithTags(Tag{
			Name:  "debug",
			Flags: []Flag{BoolFlag("debug", "enable debug mode")},
		}))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "--debug") {
		t.Fatalf("stdout should contain '--debug', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "enable debug mode") {
		t.Fatalf("stdout should contain 'enable debug mode', got %q", r.Stdout)
	}
}

// --- Help format tests ---

func TestHelpShowsVersionAndCommands(t *testing.T) {
	app := NewApp("myapp", "3.0.0", "my cool app")
	app.Command("run", "run something", func(args map[string]interface{}) int { return 0 })
	app.Command("test", "run tests", func(args map[string]interface{}) int { return 0 })
	r := app.Test([]string{})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	for _, want := range []string{"myapp v3.0.0", "my cool app", "Commands:", "run", "test"} {
		if !strings.Contains(r.Stdout, want) {
			t.Fatalf("stdout should contain %q, got %q", want, r.Stdout)
		}
	}
}

func TestCommandHelpShowsFlagsAndArgs(t *testing.T) {
	app := simpleApp("deploy", "deploy the app", "{target}:{dry_run}",
		WithArgs(NewArg("target", "deploy target")),
		WithFlags(BoolFlag("dry-run", "preview changes")))
	r := app.Test([]string{"deploy", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	for _, want := range []string{"--dry-run", "--no-dry-run", "target", "deploy the app"} {
		if !strings.Contains(r.Stdout, want) {
			t.Fatalf("stdout should contain %q, got %q", want, r.Stdout)
		}
	}
}

func TestStrFlagShowsTypeInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(StringFlag("output", "output path", Default("out.txt"))))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "<str>") {
		t.Fatalf("stdout should contain '<str>', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "default: out.txt") {
		t.Fatalf("stdout should contain 'default: out.txt', got %q", r.Stdout)
	}
}

func TestIntShowsTypeInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(IntFlag("port", "the port", Default(8000))))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "<int>") {
		t.Fatalf("stdout should contain '<int>', got %q", r.Stdout)
	}
}

func TestRequiredFlagInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(StringFlag("target", "the target")))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "required") {
		t.Fatalf("stdout should contain 'required', got %q", r.Stdout)
	}
}

func TestOptionalArgDefaultInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithArgs(NewArg("path", "project dir", ArgRequired(false), ArgDefault("."))))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "[default: .]") {
		t.Fatalf("stdout should contain '[default: .]', got %q", r.Stdout)
	}
}

func TestOptionalArgNoDefaultInHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithArgs(NewArg("path", "project dir", ArgRequired(false))))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "(optional)") {
		t.Fatalf("stdout should contain '(optional)', got %q", r.Stdout)
	}
}

func TestUseHintInAppHelp(t *testing.T) {
	app := simpleApp("run", "run something", "ok")
	r := app.Test([]string{"--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Use 'myapp <command> --help' for more information.") {
		t.Fatalf("stdout should contain use hint, got %q", r.Stdout)
	}
}

func TestEnvInHelp(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("target", "the target", Default("x"), Env("MYAPP_TARGET"))))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "env: MYAPP_TARGET") {
		t.Fatalf("stdout should contain 'env: MYAPP_TARGET', got %q", r.Stdout)
	}
}

func TestPrefixedFalseEnvVar(t *testing.T) {
	os.Setenv("SPECIAL", "works")
	defer os.Unsetenv("SPECIAL")

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("target=" + formatValue(args["target"]))
		return 0
	}, WithFlags(StringFlag("target", "the target", Default("fallback"), Env("SPECIAL"), Prefixed(false))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "target=works") {
		t.Fatalf("stdout should contain 'target=works', got %q", r.Stdout)
	}
}

func TestEnvChoicesValid(t *testing.T) {
	os.Setenv("MYAPP_FORMAT", "json")
	defer os.Unsetenv("MYAPP_FORMAT")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("format=" + formatValue(args["format"]))
		return 0
	}, WithFlags(StringFlag("format", "output format", Default("text"), Env("MYAPP_FORMAT"), Choices("text", "json"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "format=json") {
		t.Fatalf("stdout should contain 'format=json', got %q", r.Stdout)
	}
}

func TestGroupCommandGlobalFlagCollisionPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for global flag collision in group command, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "collides with a global flag") || !strings.Contains(msg, "verbose") {
			t.Fatalf("panic message should mention flag 'verbose' collides with global, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("verbose", "global verbosity"))
	g := app.Group("config", "manage configuration")
	// This should panic: "verbose" collides with the global flag
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 },
		WithFlags(BoolFlag("verbose", "local verbosity")))
}

func TestEnvChoicesInvalid(t *testing.T) {
	os.Setenv("MYAPP_FORMAT", "xml")
	defer os.Unsetenv("MYAPP_FORMAT")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("format", "output format", Default("text"), Env("MYAPP_FORMAT"), Choices("text", "json"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "invalid value") {
		t.Fatalf("stderr should contain 'invalid value', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "'xml'") {
		t.Fatalf("stderr should contain 'xml', got %q", r.Stderr)
	}
}

// --- CoRequired tests ---

func TestCoRequiredBothProvided(t *testing.T) {
	app := simpleApp("cmd", "a command", "user={user} pass={pass}",
		WithFlags(
			StringFlag("user", "username", Default("none")),
			StringFlag("pass", "password", Default("none")),
		),
		WithDependencies(CoRequired{Flags: []string{"user", "pass"}}))
	r := app.Test([]string{"cmd", "--user", "admin", "--pass", "secret"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "user=admin") {
		t.Fatalf("stdout should contain 'user=admin', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "pass=secret") {
		t.Fatalf("stdout should contain 'pass=secret', got %q", r.Stdout)
	}
}

func TestCoRequiredNeitherProvided(t *testing.T) {
	app := simpleApp("cmd", "a command", "user={user} pass={pass}",
		WithFlags(
			StringFlag("user", "username", Default("none")),
			StringFlag("pass", "password", Default("none")),
		),
		WithDependencies(CoRequired{Flags: []string{"user", "pass"}}))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "user=none") {
		t.Fatalf("stdout should contain 'user=none', got %q", r.Stdout)
	}
}

func TestCoRequiredOneProvidedError(t *testing.T) {
	app := simpleApp("cmd", "a command", "user={user} pass={pass}",
		WithFlags(
			StringFlag("user", "username", Default("none")),
			StringFlag("pass", "password", Default("none")),
		),
		WithDependencies(CoRequired{Flags: []string{"user", "pass"}}))
	r := app.Test([]string{"cmd", "--user", "admin"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "must be used together") {
		t.Fatalf("stderr should contain 'must be used together', got %q", r.Stderr)
	}
}

// --- Requires tests ---

func TestRequiresFlagWithDependsOn(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format} output={output}",
		WithFlags(
			StringFlag("format", "output format", Default("text")),
			StringFlag("output", "output file", Default("out.txt")),
		),
		WithDependencies(Requires{Flag: "output", DependsOn: "format"}))
	r := app.Test([]string{"cmd", "--output", "file.txt", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "output=file.txt") {
		t.Fatalf("stdout should contain 'output=file.txt', got %q", r.Stdout)
	}
}

func TestRequiresFlagNotProvided(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format} output={output}",
		WithFlags(
			StringFlag("format", "output format", Default("text")),
			StringFlag("output", "output file", Default("out.txt")),
		),
		WithDependencies(Requires{Flag: "output", DependsOn: "format"}))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
}

func TestRequiresDependsOnWithoutFlag(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format} output={output}",
		WithFlags(
			StringFlag("format", "output format", Default("text")),
			StringFlag("output", "output file", Default("out.txt")),
		),
		WithDependencies(Requires{Flag: "output", DependsOn: "format"}))
	// Only --format provided (DependsOn), not --output (Flag) -- should be ok (unidirectional)
	r := app.Test([]string{"cmd", "--format", "json"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
}

func TestRequiresFlagWithoutDependsOnError(t *testing.T) {
	app := simpleApp("cmd", "a command", "format={format} output={output}",
		WithFlags(
			StringFlag("format", "output format", Default("text")),
			StringFlag("output", "output file", Default("out.txt")),
		),
		WithDependencies(Requires{Flag: "output", DependsOn: "format"}))
	r := app.Test([]string{"cmd", "--output", "file.txt"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "requires") {
		t.Fatalf("stderr should contain 'requires', got %q", r.Stderr)
	}
}

// --- Dependency registration panic tests ---

func TestCoRequiredLessThanTwoFlagsPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for CoRequired with <2 flags, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "CoRequired must have at least 2 flags") {
			t.Fatalf("panic message should mention at least 2 flags, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("user", "username", Default("none"))),
		WithDependencies(CoRequired{Flags: []string{"user"}}))
}

func TestCoRequiredUnknownFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for CoRequired with unknown flag, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "CoRequired references unknown flag") {
			t.Fatalf("panic message should mention unknown flag, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("user", "username", Default("none"))),
		WithDependencies(CoRequired{Flags: []string{"user", "nonexistent"}}))
}

func TestRequiresUnknownFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Requires with unknown flag, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "Requires references unknown flag") {
			t.Fatalf("panic message should mention unknown flag, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("user", "username", Default("none"))),
		WithDependencies(Requires{Flag: "user", DependsOn: "nonexistent"}))
}

func TestRequiresSelfDependencyPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Requires with self-dependency, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "cannot be the same") {
			t.Fatalf("panic message should mention self-dependency, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(StringFlag("user", "username", Default("none"))),
		WithDependencies(Requires{Flag: "user", DependsOn: "user"}))
}

func TestCoRequiredDuplicateFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for CoRequired with duplicate flags, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "duplicate") {
			t.Fatalf("panic message should mention duplicate, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(
			StringFlag("user", "username", Default("none")),
			StringFlag("pass", "password", Default("none")),
		),
		WithDependencies(CoRequired{Flags: []string{"user", "user"}}))
}

// --- Implies tests ---

func TestImpliesTriggerSetsTarget(t *testing.T) {
	app := simpleApp("cmd", "a command", "fast={fast} embeddings={embeddings}",
		WithFlags(
			BoolFlag("fast", "enable fast mode"),
			BoolFlag("embeddings", "enable embeddings"),
		),
		WithDependencies(Implies{Flag: "fast", Implies: "embeddings", Value: false}))
	r := app.Test([]string{"cmd", "--fast"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "fast=true") {
		t.Fatalf("stdout should contain 'fast=true', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "embeddings=false") {
		t.Fatalf("stdout should contain 'embeddings=false', got %q", r.Stdout)
	}
}

func TestImpliesTriggerNotSetTargetGetsDefault(t *testing.T) {
	app := simpleApp("cmd", "a command", "fast={fast} embeddings={embeddings}",
		WithFlags(
			BoolFlag("fast", "enable fast mode"),
			BoolFlag("embeddings", "enable embeddings"),
		),
		WithDependencies(Implies{Flag: "fast", Implies: "embeddings", Value: false}))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "fast=false") {
		t.Fatalf("stdout should contain 'fast=false', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "embeddings=false") {
		t.Fatalf("stdout should contain 'embeddings=false', got %q", r.Stdout)
	}
}

func TestImpliesExplicitConflictError(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(
			BoolFlag("fast", "enable fast mode"),
			BoolFlag("embeddings", "enable embeddings"),
		),
		WithDependencies(Implies{Flag: "fast", Implies: "embeddings", Value: false}))
	// --fast implies embeddings=false, but user explicitly sets --embeddings (true)
	r := app.Test([]string{"cmd", "--fast", "--embeddings"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "implies") {
		t.Fatalf("stderr should contain 'implies', got %q", r.Stderr)
	}
}

func TestImpliesExplicitAgreementNoError(t *testing.T) {
	app := simpleApp("cmd", "a command", "fast={fast} embeddings={embeddings}",
		WithFlags(
			BoolFlag("fast", "enable fast mode"),
			BoolFlag("embeddings", "enable embeddings"),
		),
		WithDependencies(Implies{Flag: "fast", Implies: "embeddings", Value: false}))
	// --fast implies embeddings=false, and user explicitly sets --no-embeddings (false) -- agreement
	r := app.Test([]string{"cmd", "--fast", "--no-embeddings"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "fast=true") {
		t.Fatalf("stdout should contain 'fast=true', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "embeddings=false") {
		t.Fatalf("stdout should contain 'embeddings=false', got %q", r.Stdout)
	}
}

func TestImpliesUnknownTriggerFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Implies with unknown trigger flag, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "Implies references unknown flag") || !strings.Contains(msg, "nonexistent") {
			t.Fatalf("panic message should mention unknown trigger flag, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(BoolFlag("embeddings", "enable embeddings")),
		WithDependencies(Implies{Flag: "nonexistent", Implies: "embeddings", Value: false}))
}

func TestImpliesUnknownTargetFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Implies with unknown target flag, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "Implies references unknown flag") || !strings.Contains(msg, "nonexistent") {
			t.Fatalf("panic message should mention unknown target flag, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(BoolFlag("fast", "enable fast mode")),
		WithDependencies(Implies{Flag: "fast", Implies: "nonexistent", Value: false}))
}

func TestImpliesSelfImplicationPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Implies with self-implication, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "cannot be the same") {
			t.Fatalf("panic message should mention self-implication, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(BoolFlag("fast", "enable fast mode")),
		WithDependencies(Implies{Flag: "fast", Implies: "fast", Value: false}))
}

func TestImpliesTriggerNotBoolFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Implies with non-bool trigger flag, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "must be a bool flag") || !strings.Contains(msg, "trigger") {
			t.Fatalf("panic message should mention trigger must be bool, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(
			StringFlag("mode", "the mode", Default("fast")),
			BoolFlag("embeddings", "enable embeddings"),
		),
		WithDependencies(Implies{Flag: "mode", Implies: "embeddings", Value: false}))
}

func TestImpliesTargetNotBoolFlagPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for Implies with non-bool target flag, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "must be a bool flag") || !strings.Contains(msg, "target") {
			t.Fatalf("panic message should mention target must be bool, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int { return 0 },
		WithFlags(
			BoolFlag("fast", "enable fast mode"),
			StringFlag("output", "output format", Default("text")),
		),
		WithDependencies(Implies{Flag: "fast", Implies: "output", Value: false}))
}

// --- Deprecated command tests ---

func TestDeprecatedCommandExitsWithError(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run something", func(args map[string]interface{}) int { return 0 })
	app.Deprecated("deploy", "use 'run' instead")
	r := app.Test([]string{"deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "deprecated") {
		t.Fatalf("stderr should contain 'deprecated', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "use 'run' instead") {
		t.Fatalf("stderr should contain deprecation message, got %q", r.Stderr)
	}
}

func TestDeprecatedCommandInAppHelp(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run something", func(args map[string]interface{}) int { return 0 })
	app.Deprecated("deploy", "use 'run' instead")
	r := app.Test([]string{"--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Deprecated:") {
		t.Fatalf("stdout should contain 'Deprecated:', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "deploy") {
		t.Fatalf("stdout should contain 'deploy', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "use 'run' instead") {
		t.Fatalf("stdout should contain deprecation message, got %q", r.Stdout)
	}
}

func TestDeprecatedSubcommandInGroupHelp(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	g.Deprecated("dump", "use 'show' instead")
	r := app.Test([]string{"config", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stdout, "Deprecated:") {
		t.Fatalf("stdout should contain 'Deprecated:', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "dump") {
		t.Fatalf("stdout should contain 'dump', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "use 'show' instead") {
		t.Fatalf("stdout should contain deprecation message, got %q", r.Stdout)
	}
}

func TestDeprecatedSubcommandExitsWithError(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	g := app.Group("config", "manage configuration")
	g.Command("show", "display config", func(args map[string]interface{}) int { return 0 })
	g.Deprecated("dump", "use 'show' instead")
	r := app.Test([]string{"config", "dump"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "deprecated") {
		t.Fatalf("stderr should contain 'deprecated', got %q", r.Stderr)
	}
	if !strings.Contains(r.Stderr, "use 'show' instead") {
		t.Fatalf("stderr should contain deprecation message, got %q", r.Stderr)
	}
}

func TestNormalAndDeprecatedCoexist(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run something", func(args map[string]interface{}) int {
		fmt.Print("running")
		return 0
	})
	app.Deprecated("deploy", "use 'run' instead")

	// Normal command still works
	r := app.Test([]string{"run"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "running") {
		t.Fatalf("stdout should contain 'running', got %q", r.Stdout)
	}

	// Deprecated command errors
	r = app.Test([]string{"deploy"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "deprecated") {
		t.Fatalf("stderr should contain 'deprecated', got %q", r.Stderr)
	}
}

func TestDeprecatedDuplicateNameWithCommandPanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for deprecated command with duplicate name, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "already used by a command") {
			t.Fatalf("panic message should mention name collision, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("run", "run something", func(args map[string]interface{}) int { return 0 })
	app.Deprecated("run", "this should panic")
}

func TestDeprecatedEmptyMessagePanics(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic for deprecated command with empty message, got none")
		}
		msg := fmt.Sprintf("%v", r)
		if !strings.Contains(msg, "message must not be empty") {
			t.Fatalf("panic message should mention empty message, got %q", msg)
		}
	}()

	app := NewApp("myapp", "1.0.0", "test app")
	app.Deprecated("deploy", "")
}

func TestImpliesEnvTrigger(t *testing.T) {
	os.Setenv("MYAPP_FAST", "true")
	defer os.Unsetenv("MYAPP_FAST")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("fast=" + formatValue(args["fast"]) + " embeddings=" + formatValue(args["embeddings"]))
		return 0
	}, WithFlags(
		BoolFlag("fast", "enable fast mode", Env("MYAPP_FAST")),
		BoolFlag("embeddings", "enable embeddings"),
	), WithDependencies(Implies{Flag: "fast", Implies: "embeddings", Value: false}))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "fast=true") {
		t.Fatalf("stdout should contain 'fast=true', got %q", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "embeddings=false") {
		t.Fatalf("stdout should contain 'embeddings=false', got %q", r.Stdout)
	}
}

func TestAppCommands(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	handler := func(args map[string]interface{}) int { return 0 }
	app.Command("build", "build the project", handler)
	app.Command("test", "run tests", handler)

	cmds := app.Commands()
	if len(cmds) != 2 {
		t.Fatalf("expected 2 commands, got %d", len(cmds))
	}
	if cmds["build"] == nil {
		t.Fatal("expected 'build' command to be present")
	}
	if cmds["test"] == nil {
		t.Fatal("expected 'test' command to be present")
	}
	if cmds["build"].Help != "build the project" {
		t.Fatalf("expected build help 'build the project', got %q", cmds["build"].Help)
	}
	if cmds["test"].Help != "run tests" {
		t.Fatalf("expected test help 'run tests', got %q", cmds["test"].Help)
	}
}

func TestAppGroups(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	handler := func(args map[string]interface{}) int { return 0 }

	grp := app.Group("config", "manage configuration")
	grp.Command("set", "set a value", handler)
	grp.Command("get", "get a value", handler)

	groups := app.Groups()
	if len(groups) != 1 {
		t.Fatalf("expected 1 group, got %d", len(groups))
	}
	g := groups["config"]
	if g == nil {
		t.Fatal("expected 'config' group to be present")
	}
	if g.Help != "manage configuration" {
		t.Fatalf("expected group help 'manage configuration', got %q", g.Help)
	}
	if len(g.Commands) != 2 {
		t.Fatalf("expected 2 subcommands, got %d", len(g.Commands))
	}
	if g.Commands["set"] == nil {
		t.Fatal("expected 'set' subcommand to be present")
	}
	if g.Commands["get"] == nil {
		t.Fatal("expected 'get' subcommand to be present")
	}
}

func TestAppGlobalFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("verbose", "enable verbose output"))
	app.GlobalFlag(StringFlag("output", "output format", Default("json")))

	flags := app.GlobalFlags()
	if len(flags) != 2 {
		t.Fatalf("expected 2 global flags, got %d", len(flags))
	}
	if flags[0].Name != "verbose" {
		t.Fatalf("expected first flag name 'verbose', got %q", flags[0].Name)
	}
	if flags[0].Type != TypeBool {
		t.Fatalf("expected first flag type TypeBool, got %v", flags[0].Type)
	}
	if flags[1].Name != "output" {
		t.Fatalf("expected second flag name 'output', got %q", flags[1].Name)
	}
	if flags[1].Type != TypeStr {
		t.Fatalf("expected second flag type TypeStr, got %v", flags[1].Type)
	}
}

func TestAppDeprecated(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Deprecated("deploy", "use 'release' instead")
	app.Deprecated("init", "use 'setup' instead")

	deprecated := app.DeprecatedCommands()
	if len(deprecated) != 2 {
		t.Fatalf("expected 2 deprecated commands, got %d", len(deprecated))
	}
	if deprecated["deploy"] != "use 'release' instead" {
		t.Fatalf("expected deploy message 'use 'release' instead', got %q", deprecated["deploy"])
	}
	if deprecated["init"] != "use 'setup' instead" {
		t.Fatalf("expected init message 'use 'setup' instead', got %q", deprecated["init"])
	}

	// Also test Group.DeprecatedCommands
	handler := func(args map[string]interface{}) int { return 0 }
	app.Command("run", "run something", handler)
	grp := app.Group("config", "manage configuration")
	grp.Command("set", "set a value", handler)
	grp.Deprecated("reset", "use 'set' with --default instead")

	grpDeprecated := grp.DeprecatedCommands()
	if len(grpDeprecated) != 1 {
		t.Fatalf("expected 1 deprecated group command, got %d", len(grpDeprecated))
	}
	if grpDeprecated["reset"] != "use 'set' with --default instead" {
		t.Fatalf("expected reset message, got %q", grpDeprecated["reset"])
	}
}

func TestDefaultNilDisplaysOptional(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		return 0
	}, WithFlags(StringFlag("name", "a name", Default(nil))))
	r := app.Test([]string{"cmd", "--help"})
	if !strings.Contains(r.Stdout, "[optional]") {
		t.Fatalf("expected [optional] in help output, got:\n%s", r.Stdout)
	}
	if strings.Contains(r.Stdout, "[required]") {
		t.Fatalf("expected no [required] in help output, got:\n%s", r.Stdout)
	}
}

func TestDefaultValueStillDisplays(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		return 0
	}, WithFlags(StringFlag("name", "a name", Default("foo"))))
	r := app.Test([]string{"cmd", "--help"})
	if !strings.Contains(r.Stdout, "[default: foo]") {
		t.Fatalf("expected [default: foo] in help output, got:\n%s", r.Stdout)
	}
}

func TestRequiredFlagStillDisplaysRequired(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		return 0
	}, WithFlags(StringFlag("name", "a name")))
	r := app.Test([]string{"cmd", "--help"})
	if !strings.Contains(r.Stdout, "[required]") {
		t.Fatalf("expected [required] in help output, got:\n%s", r.Stdout)
	}
}

func TestHelpAfterFlags(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		return 0
	}, WithFlags(BoolFlag("verbose", "enable verbose output")))
	r := app.Test([]string{"cmd", "--verbose", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "cmd") {
		t.Fatalf("expected help output containing 'cmd', got:\n%s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "--verbose") {
		t.Fatalf("expected help output containing '--verbose', got:\n%s", r.Stdout)
	}
}

func TestHelpNotAfterSeparator(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print(args["items"])
		return 0
	}, WithArgs(NewArg("items", "items to process", Variadic(), ArgRequired(false))))
	r := app.Test([]string{"cmd", "--", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	// Should NOT show help text -- --help after -- is a literal argument
	if strings.Contains(r.Stdout, "Flags:") {
		t.Fatalf("expected no help output, but got help text:\n%s", r.Stdout)
	}
}

// --- Float flag tests ---

func TestFloatFlagBasic(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate")))
	r := app.Test([]string{"cmd", "--rate", "3.14"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "rate=3.14") {
		t.Fatalf("stdout should contain 'rate=3.14', got %q", r.Stdout)
	}
}

func TestFloatFlagEquals(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate")))
	r := app.Test([]string{"cmd", "--rate=3.14"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "rate=3.14") {
		t.Fatalf("stdout should contain 'rate=3.14', got %q", r.Stdout)
	}
}

func TestFloatFlagShort(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate", Short("r"))))
	r := app.Test([]string{"cmd", "-r", "3.14"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "rate=3.14") {
		t.Fatalf("stdout should contain 'rate=3.14', got %q", r.Stdout)
	}
}

func TestFloatFlagEnv(t *testing.T) {
	os.Setenv("MYAPP_RATE", "2.718")
	defer os.Unsetenv("MYAPP_RATE")

	app := NewApp("myapp", "1.0.0", "test app", WithEnvPrefix("MYAPP"))
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("rate=" + formatValue(args["rate"]))
		return 0
	}, WithFlags(FloatFlag("rate", "the rate", Default(1.0), Env("MYAPP_RATE"))))

	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "rate=2.718") {
		t.Fatalf("stdout should contain 'rate=2.718', got %q", r.Stdout)
	}
}

func TestFloatFlagDefault(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate", Default(9.81))))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "rate=9.81") {
		t.Fatalf("stdout should contain 'rate=9.81', got %q", r.Stdout)
	}
}

func TestFloatFlagChoices(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate", Choices(1.0, 2.5, 3.14))))
	// Valid choice
	r := app.Test([]string{"cmd", "--rate", "2.5"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "rate=2.5") {
		t.Fatalf("stdout should contain 'rate=2.5', got %q", r.Stdout)
	}
	// Invalid choice
	r2 := app.Test([]string{"cmd", "--rate", "7.77"})
	if r2.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r2.ExitCode)
	}
	if !strings.Contains(r2.Stderr, "invalid value") {
		t.Fatalf("stderr should contain 'invalid value', got %q", r2.Stderr)
	}
}

func TestFloatFlagNegative(t *testing.T) {
	app := simpleApp("cmd", "a command", "temp={temp}",
		WithFlags(FloatFlag("temp", "temperature")))
	r := app.Test([]string{"cmd", "--temp", "-40.5"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "temp=-40.5") {
		t.Fatalf("stdout should contain 'temp=-40.5', got %q", r.Stdout)
	}
}

func TestFloatFlagRejectNaN(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate")))
	r := app.Test([]string{"cmd", "--rate", "NaN"})
	if r.ExitCode != 1 {
		t.Fatalf("expected exit 1, got %d", r.ExitCode)
	}
	if !strings.Contains(r.Stderr, "NaN is not allowed") {
		t.Fatalf("stderr should contain 'NaN is not allowed', got %q", r.Stderr)
	}
}

func TestFloatFlagRejectInf(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate")))
	for _, val := range []string{"Inf", "+Inf", "-Inf"} {
		r := app.Test([]string{"cmd", "--rate", val})
		if r.ExitCode != 1 {
			t.Fatalf("val=%q: expected exit 1, got %d", val, r.ExitCode)
		}
		if !strings.Contains(r.Stderr, "Inf is not allowed") {
			t.Fatalf("val=%q: stderr should contain 'Inf is not allowed', got %q", val, r.Stderr)
		}
	}
}

func TestFloatFlagRejectWhitespace(t *testing.T) {
	app := simpleApp("cmd", "a command", "rate={rate}",
		WithFlags(FloatFlag("rate", "the rate")))
	for _, val := range []string{" 3.14", "3.14 ", " 3.14 "} {
		r := app.Test([]string{"cmd", "--rate", val})
		if r.ExitCode != 1 {
			t.Fatalf("val=%q: expected exit 1, got %d", val, r.ExitCode)
		}
		if !strings.Contains(r.Stderr, "expected float") {
			t.Fatalf("val=%q: stderr should contain 'expected float', got %q", val, r.Stderr)
		}
	}
}

func TestFloatFlagRepeatable(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("vals=" + formatValue(args["val"]))
		return 0
	}, WithFlags(FloatFlag("val", "a value", Repeatable())))

	r := app.Test([]string{"cmd", "--val", "1.1", "--val", "2.2", "--val", "3.3"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "vals=1.1,2.2,3.3") {
		t.Fatalf("stdout should contain 'vals=1.1,2.2,3.3', got %q", r.Stdout)
	}
}

func TestFloatFlagHelp(t *testing.T) {
	app := simpleApp("cmd", "a command", "ok",
		WithFlags(FloatFlag("rate", "the rate")))
	r := app.Test([]string{"cmd", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if !strings.Contains(r.Stdout, "<float>") {
		t.Fatalf("help should contain '<float>', got:\n%s", r.Stdout)
	}
}
