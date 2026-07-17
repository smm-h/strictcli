package strictcli

import (
	"math"
	"math/rand"
	"strconv"
	"testing"
)

// TestFormatFloatCanonicalBattery verifies the canonical float form (SCF)
// against the agreed battery of representative values.
func TestFormatFloatCanonicalBattery(t *testing.T) {
	cases := []struct {
		in   float64
		want string
	}{
		{1.0, "1.0"},
		{-1.0, "-1.0"},
		{0.5, "0.5"},
		{math.Copysign(0, -1), "-0.0"}, // -0.0
		{0.0, "0.0"},
		{100.0, "100.0"},
		{1e15, "1000000000000000.0"},
		{1e16, "10000000000000000.0"},
		{1e20, "100000000000000000000.0"},
		{1e21, "1e+21"},
		{1e-4, "0.0001"},
		{1e-5, "0.00001"},
		{1e-7, "1e-7"},
		{0.1, "0.1"},
		{9007199254740992.0, "9007199254740992.0"},
		{1.5e300, "1.5e+300"},
	}
	for _, c := range cases {
		got := formatFloatCanonical(c.in)
		if got != c.want {
			t.Errorf("formatFloatCanonical(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

// TestFormatFloatCanonicalNegZeroSign ensures -0.0 is distinguished from 0.0
// purely by the sign bit, not by value comparison.
func TestFormatFloatCanonicalNegZeroSign(t *testing.T) {
	if got := formatFloatCanonical(math.Copysign(0, -1)); got != "-0.0" {
		t.Errorf("negative zero = %q, want %q", got, "-0.0")
	}
	if got := formatFloatCanonical(0.0); got != "0.0" {
		t.Errorf("positive zero = %q, want %q", got, "0.0")
	}
}

// TestFormatFloatCanonicalRoundTrip is a property test: for a large sample of
// random bit patterns, the canonical string must parse back to the identical
// IEEE-754 double (bit-for-bit). NaN and Inf are excluded (rejected upstream).
func TestFormatFloatCanonicalRoundTrip(t *testing.T) {
	rng := rand.New(rand.NewSource(0xC0FFEE))
	for i := 0; i < 2_000_000; i++ {
		bits := rng.Uint64()
		x := math.Float64frombits(bits)
		if math.IsNaN(x) || math.IsInf(x, 0) {
			continue
		}
		s := formatFloatCanonical(x)
		back, err := strconv.ParseFloat(s, 64)
		if err != nil {
			t.Fatalf("ParseFloat(%q) failed for input bits %#016x: %v", s, bits, err)
		}
		if math.Float64bits(back) != bits {
			t.Fatalf("round-trip mismatch: input bits %#016x formatted as %q parsed back to bits %#016x",
				bits, s, math.Float64bits(back))
		}
	}
}
