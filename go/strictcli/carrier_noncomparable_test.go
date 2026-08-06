package strictcli

// Compile-FAIL harness for the carrier non-comparability guarantee (§17).
//
// The four Unsettled-family carriers each carry a leading `_ [0]func()` field
// whose only effect is to make the struct non-comparable, so that `a == b` on a
// carrier is a COMPILE error instead of a silently wrong answer. No runtime
// test can observe that field: deleting it changes no behavior. This harness is
// the pin -- it compiles testdata/noncomparable (a package the ordinary test
// run never builds, because the go tool skips `testdata` directories) and
// asserts one diagnostic per fixture file, naming the field verbatim.
//
// Modelled on the TypeScript sibling, typescript/tests/negative_types.test.ts,
// which compiles tests/negative/ through tsc and asserts per-file diagnostics.

import (
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// nonComparableFixturePkg is the import path suffix of the compile-fail package,
// relative to this package's directory.
const nonComparableFixturePkg = "./testdata/noncomparable"

// nonComparableDiagnostic is the exact gc wording for a `==` on a struct whose
// first non-comparable field is the zero-length func array. Asserting the full
// text (not merely "does not compile") is what pins the FIELD: Response would
// still fail to compile without it, but with a diagnostic about `body []byte`.
const nonComparableDiagnostic = "invalid operation: a == b (struct containing [0]func() cannot be compared)"

// goDiagnostic is one parsed compiler error: `file:line:col: message`.
type goDiagnostic struct {
	file    string
	message string
}

var goDiagnosticRe = regexp.MustCompile(`^(.+\.go):(\d+):(\d+): (.+)$`)

// compileNonComparableFixtures builds the fixture package and returns its
// diagnostics. A successful build returns no diagnostics, which is itself a
// failure for every caller here.
func compileNonComparableFixtures(t *testing.T) []goDiagnostic {
	t.Helper()
	goBin, err := exec.LookPath("go")
	if err != nil {
		t.Fatalf("the go tool must be on PATH to run the compile-fail harness: %v", err)
	}
	cmd := exec.Command(goBin, "build", nonComparableFixturePkg)
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("%s compiled cleanly -- the carrier [0]func() fields are gone; output:\n%s",
			nonComparableFixturePkg, out)
	}
	var diags []goDiagnostic
	for _, line := range strings.Split(string(out), "\n") {
		m := goDiagnosticRe.FindStringSubmatch(strings.TrimSpace(line))
		if m == nil {
			// The `# import/path` banner and any blank tail.
			continue
		}
		diags = append(diags, goDiagnostic{file: filepath.Base(m[1]), message: m[4]})
	}
	return diags
}

// TestCarriersAreNonComparable pins all four `[0]func()` fields at once: one
// fixture file per carrier, each expected to yield exactly the field's
// diagnostic.
func TestCarriersAreNonComparable(t *testing.T) {
	diags := compileNonComparableFixtures(t)

	byFile := map[string][]goDiagnostic{}
	for _, d := range diags {
		byFile[d.file] = append(byFile[d.file], d)
	}

	for _, fixture := range []struct {
		file    string
		carrier string
	}{
		{"compare_unsettled.go", "Unsettled"},
		{"compare_completed.go", "Completed"},
		{"compare_spawned.go", "Spawned"},
		{"compare_response.go", "Response"},
	} {
		got := byFile[fixture.file]
		if len(got) != 1 {
			t.Fatalf("%s (%s): want exactly 1 diagnostic, got %d: %v",
				fixture.file, fixture.carrier, len(got), got)
		}
		if got[0].message != nonComparableDiagnostic {
			t.Errorf("%s (%s): diagnostic\n got: %s\nwant: %s",
				fixture.file, fixture.carrier, got[0].message, nonComparableDiagnostic)
		}
	}

	if len(diags) != 4 {
		t.Errorf("want exactly 4 diagnostics (one per carrier), got %d: %v", len(diags), diags)
	}
}

// TestCarrierNonComparableHarnessPositiveFixture is the counterweight: the
// carriers stay usable everywhere a comparison is not attempted, so the
// positive fixture must draw no diagnostic. A regression here would mean the
// harness blames whole packages rather than files, which would let a deleted
// field hide behind a neighbour's error.
func TestCarrierNonComparableHarnessPositiveFixture(t *testing.T) {
	for _, d := range compileNonComparableFixtures(t) {
		if d.file == "positive_carrier_use.go" {
			t.Errorf("positive_carrier_use.go must compile clean, got: %s", d.message)
		}
	}
}
