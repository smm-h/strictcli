// Package noncomparable is a compile-FAIL fixture package. It is never built
// by the ordinary test run -- the go tool ignores directories named `testdata`
// when matching `./...` -- and is compiled on purpose by
// carrier_noncomparable_test.go, which asserts that each `compare_*.go` file
// below produces exactly one diagnostic naming the `[0]func()` field.
//
// Each of the four Unsettled-family carriers (Unsettled, Completed, Spawned,
// Response) carries a leading `_ [0]func()` field whose ONLY job is to make the
// struct non-comparable, so that `a == b` on a carrier is a compile error
// rather than a silent wrong answer (§17). Nothing else in the suite observes
// those fields: deleting them changes no runtime behavior, so this package plus
// its driver test is the pin that keeps them alive.
//
// Note on Response: its `body []byte` and `headers map[string]string` fields
// are non-comparable in their own right, so dropping its `[0]func()` would
// still fail to compile -- but with a DIFFERENT message. The driver test
// asserts the exact `[0]func()` wording, which is what pins the field itself.
package noncomparable
