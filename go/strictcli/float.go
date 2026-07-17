package strictcli

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// formatDefaultValue renders a default value for help text. float64 values are
// routed through the canonical formatter; all other types keep their prior
// fmt "%v" rendering byte-for-byte.
func formatDefaultValue(v interface{}) string {
	if f, ok := v.(float64); ok {
		return formatFloatCanonical(f)
	}
	return fmt.Sprintf("%v", v)
}

// formatFloatCanonical formats a float64 using the strictcli canonical float
// form (SCF), shared byte-for-byte with the Python implementation.
//
// Rules:
//  1. The digit source is strconv.FormatFloat with precision -1 (shortest
//     string that round-trips to the identical IEEE-754 double). We never
//     trust FormatFloat's own notation switching -- notation is chosen here.
//  2. Integer-valued floats in fixed notation always carry a trailing ".0".
//  3. -0.0 is preserved as "-0.0" (detected via math.Signbit).
//  4. Fixed notation is used for |x| in [1e-6, 1e21); scientific outside.
//     Zero is a carve-out: 0.0 and -0.0 are always fixed ("0.0"/"-0.0").
//  5. Scientific uses a lowercase 'e', an explicit sign, and no exponent
//     zero-padding: "1e+21", "1e-7", "1.5e+300".
//  6. The trailing ".0" is only ever added in the fixed branch, never in the
//     scientific branch -- so scientific output can never gain a spurious ".0".
func formatFloatCanonical(v float64) string {
	// Zero carve-out: always fixed, sign preserved via the sign bit.
	if v == 0 {
		if math.Signbit(v) {
			return "-0.0"
		}
		return "0.0"
	}

	abs := math.Abs(v)
	if abs >= 1e-6 && abs < 1e21 {
		// Fixed notation. 'f' with -1 precision yields the shortest
		// round-tripping fixed-point digit string.
		s := strconv.FormatFloat(v, 'f', -1, 64)
		if !strings.Contains(s, ".") {
			s += ".0"
		}
		return s
	}

	// Scientific notation. 'e' with -1 precision yields the shortest
	// round-tripping mantissa with a lowercase 'e', an explicit exponent
	// sign, and an exponent zero-padded to at least two digits. Strip the
	// padding so the exponent carries only significant digits.
	s := strconv.FormatFloat(v, 'e', -1, 64)
	eIdx := strings.IndexByte(s, 'e')
	mantissa := s[:eIdx]
	exp := s[eIdx+1:] // e.g. "+21", "-07"
	sign := exp[0]
	digits := strings.TrimLeft(exp[1:], "0")
	if digits == "" {
		digits = "0"
	}
	return mantissa + "e" + string(sign) + digits
}
