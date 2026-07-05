package strictcli

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestContextInfoWritesToStdout(t *testing.T) {
	var stdout, stderr bytes.Buffer
	ctx := newContext(&stdout, &stderr, nil, nil)

	ctx.Info("hello world")

	if got := stdout.String(); got != "hello world\n" {
		t.Fatalf("expected stdout 'hello world\\n', got %q", got)
	}
	if stderr.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", stderr.String())
	}
}

func TestContextWarnWritesToStderr(t *testing.T) {
	var stdout, stderr bytes.Buffer
	ctx := newContext(&stdout, &stderr, nil, nil)

	ctx.Warn("something is off")

	if stderr.String() != "something is off\n" {
		t.Fatalf("expected stderr 'something is off\\n', got %q", stderr.String())
	}
	if stdout.Len() != 0 {
		t.Fatalf("expected empty stdout, got %q", stdout.String())
	}
}

func TestContextDebugWritesToStdout(t *testing.T) {
	var stdout, stderr bytes.Buffer
	ctx := newContext(&stdout, &stderr, nil, nil)

	ctx.Debug("trace info")

	if got := stdout.String(); got != "trace info\n" {
		t.Fatalf("expected stdout 'trace info\\n', got %q", got)
	}
	if stderr.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", stderr.String())
	}
}

func TestContextErrorWritesToStderr(t *testing.T) {
	var stdout, stderr bytes.Buffer
	ctx := newContext(&stdout, &stderr, nil, nil)

	ctx.Error("something broke")

	if stderr.String() != "something broke\n" {
		t.Fatalf("expected stderr 'something broke\\n', got %q", stderr.String())
	}
	if stdout.Len() != 0 {
		t.Fatalf("expected empty stdout, got %q", stdout.String())
	}
}

func TestContextEmitWritesJSONAndStoresData(t *testing.T) {
	var stdout, stderr bytes.Buffer
	ctx := newContext(&stdout, &stderr, nil, nil)

	data := map[string]interface{}{
		"name":  "widget",
		"count": float64(42),
	}
	ctx.Emit(data)

	// Verify JSON was written to stdout
	output := strings.TrimSpace(stdout.String())
	var decoded map[string]interface{}
	if err := json.Unmarshal([]byte(output), &decoded); err != nil {
		t.Fatalf("Emit output is not valid JSON: %v\nOutput: %q", err, output)
	}
	if decoded["name"] != "widget" {
		t.Fatalf("expected name='widget', got %v", decoded["name"])
	}
	if decoded["count"] != float64(42) {
		t.Fatalf("expected count=42, got %v", decoded["count"])
	}

	// Verify stored data via emitResult
	stored := ctx.emitResult()
	storedMap, ok := stored.(map[string]interface{})
	if !ok {
		t.Fatalf("expected emitResult to be map[string]interface{}, got %T", stored)
	}
	if storedMap["name"] != "widget" {
		t.Fatalf("expected stored name='widget', got %v", storedMap["name"])
	}

	// Verify nothing went to stderr
	if stderr.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", stderr.String())
	}
}

func TestContextEmitCalledTwicePanics(t *testing.T) {
	var stdout bytes.Buffer
	ctx := newContext(&stdout, &stdout, nil, nil)

	ctx.Emit("first")

	defer func() {
		r := recover()
		if r == nil {
			t.Fatal("expected panic on second Emit call")
		}
		msg, ok := r.(string)
		if !ok {
			t.Fatalf("expected string panic, got %T: %v", r, r)
		}
		if !strings.Contains(msg, "Emit called more than once") {
			t.Fatalf("unexpected panic message: %q", msg)
		}
	}()

	ctx.Emit("second")
}

func TestNewContextWithNilWriters(t *testing.T) {
	// nil writers should not crash — they are replaced with io.Discard
	ctx := newContext(nil, nil, nil, nil)

	// These should not panic
	ctx.Info("info message")
	ctx.Warn("warn message")
	ctx.Debug("debug message")
	ctx.Error("error message")
	ctx.Emit("data")

	// Verify emitResult still works
	if ctx.emitResult() != "data" {
		t.Fatalf("expected emitResult='data', got %v", ctx.emitResult())
	}
}
