package strictcli

import (
	"bytes"
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

func TestNewContextWithNilWriters(t *testing.T) {
	// nil writers should not crash — they are replaced with io.Discard
	ctx := newContext(nil, nil, nil, nil)

	// These should not panic
	ctx.Info("info message")
	ctx.Warn("warn message")
	ctx.Debug("debug message")
	ctx.Error("error message")
}
