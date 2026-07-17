package strictcli

import "fmt"

// Outcome is the opaque, branded result of a command handler. It is constructed
// only via Exit or ExitData and carries an exit code plus, optionally, structured
// data. When data is present, the framework JSON-prints it to stdout as one
// compact line and makes it available to Test and Call.
type Outcome struct {
	code int
	data interface{}
}

// Exit returns an Outcome that terminates the command with the given exit code
// and emits no data.
func Exit(code int) Outcome {
	return Outcome{code: code}
}

// ExitData returns an Outcome that terminates the command with the given exit
// code and emits data. The framework JSON-marshals data to stdout and captures
// it for programmatic callers (Test/Call). Data emission is possible ONLY through
// this constructor.
func ExitData(code int, data interface{}) Outcome {
	return Outcome{code: code, data: data}
}

// Get returns the value stored under name in kwargs, typed as T.
//
// It PANICS if the key is absent, if the value is nil, or if the value's dynamic
// type is not T. A nil value never silently zeroes: nil means "not provided", so
// callers that expect an optional value must use GetOpt instead.
func Get[T any](kwargs map[string]interface{}, name string) T {
	v, ok := kwargs[name]
	if !ok {
		panic(fmt.Sprintf("strictcli.Get: no such key %q", name))
	}
	if v == nil {
		panic(fmt.Sprintf("strictcli.Get: key %q is nil (not provided); use GetOpt for optional values", name))
	}
	t, ok := v.(T)
	if !ok {
		var zero T
		panic(fmt.Sprintf("strictcli.Get: key %q has dynamic type %T, want %T", name, v, zero))
	}
	return t
}

// GetOpt returns the value stored under name in kwargs, typed as T, along with a
// boolean reporting whether a value was provided.
//
// It returns (zero, false) when the value is present but nil (not provided). It
// PANICS if the key is absent or the value's dynamic type is not T.
func GetOpt[T any](kwargs map[string]interface{}, name string) (T, bool) {
	v, ok := kwargs[name]
	if !ok {
		panic(fmt.Sprintf("strictcli.GetOpt: no such key %q", name))
	}
	if v == nil {
		var zero T
		return zero, false
	}
	t, ok := v.(T)
	if !ok {
		var zero T
		panic(fmt.Sprintf("strictcli.GetOpt: key %q has dynamic type %T, want %T", name, v, zero))
	}
	return t, true
}
