package strictcli

// Outcome is the opaque, branded result of a command handler. It is constructed
// only via Exit and carries an exit code and nothing else: the bare-JSON-print
// data channel was deleted (contract §19.4) and machine payloads are supplied
// through Context.Payload.
type Outcome struct {
	code int
}

// Exit returns an Outcome that terminates the command with the given exit code.
func Exit(code int) Outcome {
	return Outcome{code: code}
}

// Get returns the value stored under name in kwargs, typed as T.
//
// It PANICS if the key is absent, if the value is nil, or if the value's dynamic
// type is not T. A nil value never silently zeroes: nil means "not provided", so
// callers that expect an optional value must use GetOpt instead.
func Get[T any](kwargs map[string]interface{}, name string) T {
	v, ok := kwargs[name]
	if !ok {
		panic(errGetNoSuchKey(name))
	}
	if v == nil {
		panic(errGetKeyNil(name))
	}
	t, ok := v.(T)
	if !ok {
		var zero T
		panic(errGetTypeMismatch(name, v, zero))
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
		panic(errGetOptNoSuchKey(name))
	}
	if v == nil {
		var zero T
		return zero, false
	}
	t, ok := v.(T)
	if !ok {
		var zero T
		panic(errGetOptTypeMismatch(name, v, zero))
	}
	return t, true
}
