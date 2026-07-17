package strictcli

import (
	"bufio"
	"fmt"
	"math"
	"os"
	"strconv"
	"strings"
	"testing"
)

// TestFloatFuzzFilter is the Go half of the cross-language float differential
// fuzz driven by conformance/check_float_fuzz.py. It is NOT a conventional
// assertion test: gated behind STRICTCLI_FUZZ_STDIN=1 it acts as a stdin->file
// filter, reading hex uint64 bit patterns (one per line) from stdin, formatting
// each via the real (unexported) formatFloatCanonical, and writing the
// canonical strings (one per line, same order) to the file named by
// STRICTCLI_FUZZ_OUT. Without the env gate it skips immediately, so a normal
// `go test` never touches stdin.
//
// It lives in package strictcli, and thus reaches the unexported formatter
// directly, so the fuzz can exercise the true Go implementation without growing
// the public API surface (which would also break privacy parity with Python's
// private _format_float_canonical). Canonical output goes to a file rather than
// stdout so the go-test framework's own stdout noise never contaminates it.
func TestFloatFuzzFilter(t *testing.T) {
	if os.Getenv("STRICTCLI_FUZZ_STDIN") != "1" {
		t.Skip("float fuzz filter runs only under STRICTCLI_FUZZ_STDIN=1")
	}
	outPath := os.Getenv("STRICTCLI_FUZZ_OUT")
	if outPath == "" {
		t.Fatal("STRICTCLI_FUZZ_OUT must name the canonical-output file")
	}
	out, err := os.Create(outPath)
	if err != nil {
		t.Fatalf("create output file: %v", err)
	}
	defer out.Close()
	w := bufio.NewWriter(out)
	defer w.Flush()

	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		bits, err := strconv.ParseUint(line, 16, 64)
		if err != nil {
			t.Fatalf("bad hex bit pattern %q: %v", line, err)
		}
		x := math.Float64frombits(bits)
		if _, err := fmt.Fprintln(w, formatFloatCanonical(x)); err != nil {
			t.Fatalf("write canonical: %v", err)
		}
	}
	if err := sc.Err(); err != nil {
		t.Fatalf("read stdin: %v", err)
	}
}
