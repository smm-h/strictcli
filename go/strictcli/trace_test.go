package strictcli

// The process trace store (docs/process-trace-store.md).
//
// Every test here pins HOME to a temp directory, which is what makes the suite
// hermetic: the store path is the literal ~/.local/share/strictcli/trace/,
// expanded from HOME and nothing else, so a poisoned HOME is a private store.
//
// The reader used below is a TEST-side reader on purpose. The framework exposes
// no accessor for ancestry (effects contract §20.2) and no code path branches on
// the store's content -- a consumer that wants the chain parses the environment
// variable and reads the store itself, exactly as this file does.

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"
)

var entryKeys = []string{
	"id", "parent_id", "app", "version", "command", "dry_run", "machine_mode",
	"quiet", "verbose", "approve_consequential", "effect", "pid", "spawned_at",
}

// traceHome pins HOME to a fresh temp directory and clears any inherited
// ancestry, so the store this test writes to is its own.
func traceHome(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("HOME", dir)
	t.Setenv(traceParentEnv, "")
	os.Unsetenv(traceParentEnv)
	return dir
}

func traceDirOf(home string) string {
	return filepath.Join(home, ".local", "share", "strictcli", "trace")
}

// tracePartitions lists partition files in name order. Anything else in the
// directory -- the failure marker included -- is ignored, per the reader rule.
func tracePartitions(t *testing.T, home string) []string {
	t.Helper()
	entries, err := os.ReadDir(traceDirOf(home))
	if err != nil {
		return nil
	}
	var out []string
	for _, e := range entries {
		if tracePartitionRe.MatchString(e.Name()) {
			out = append(out, filepath.Join(traceDirOf(home), e.Name()))
		}
	}
	sort.Strings(out)
	return out
}

// entriesIn returns one partition's well-formed entries and its anomalies.
func entriesIn(t *testing.T, path string) ([]map[string]interface{}, []string) {
	t.Helper()
	var entries []map[string]interface{}
	var anomalies []string
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	for _, line := range strings.Split(string(data), "\n") {
		if line == "" {
			continue
		}
		var obj map[string]interface{}
		if err := json.Unmarshal([]byte(line), &obj); err != nil {
			anomalies = append(anomalies, line)
			continue
		}
		complete := len(obj) == len(entryKeys)
		for _, key := range entryKeys {
			if _, ok := obj[key]; !ok {
				complete = false
			}
		}
		if !complete {
			anomalies = append(anomalies, line)
			continue
		}
		entries = append(entries, obj)
	}
	return entries, anomalies
}

// readEntries returns the well-formed entries and the anomalies. A torn or
// malformed line is recorded verbatim as an anomaly and skipped -- never
// discarded silently.
func readEntries(t *testing.T, home string) ([]map[string]interface{}, []string) {
	t.Helper()
	var entries []map[string]interface{}
	var anomalies []string
	for _, path := range tracePartitions(t, home) {
		found, bad := entriesIn(t, path)
		entries = append(entries, found...)
		anomalies = append(anomalies, bad...)
	}
	return entries, anomalies
}

// resolveEntry implements the spec's lookup rule (docs/process-trace-store.md,
// Partitions): binary-search the sorted labels for the greatest label NOT AFTER
// the identifier's embedded timestamp, read that partition, and on a miss walk
// backward through older partitions until the entry is found or the partitions
// are exhausted. The backward walk is required for correctness: the clamp
// invariant is one-sided, so a file that has not rolled keeps taking entries
// after a newer-labelled partition exists.
//
// walkBack=false is the pre-amendment rule -- one binary search and nothing
// else -- kept so a test can pin what it misses.
func resolveEntry(t *testing.T, home, entryID string, walkBack bool) map[string]interface{} {
	t.Helper()
	ms, ok := ulidTimestamp(entryID)
	if !ok {
		return nil
	}
	parts := tracePartitions(t, home)
	labels := make([]string, len(parts))
	for i, p := range parts {
		labels[i] = strings.TrimSuffix(filepath.Base(p), ".jsonl")
	}
	target := traceLabel(ms)
	// The greatest label not after the target: sort.SearchStrings finds the
	// first label >= target, so step back over it unless it equals the target.
	index := sort.SearchStrings(labels, target)
	if index == len(labels) || labels[index] != target {
		index--
	}
	for ; index >= 0; index-- {
		found, _ := entriesIn(t, parts[index])
		for _, entry := range found {
			if entry["id"] == entryID {
				return entry
			}
		}
		if !walkBack {
			return nil
		}
	}
	return nil
}

// flattenAncestry walks parent_id to the root, resolving each link through the
// store's own lookup rule; a dangling reference ends the walk.
func flattenAncestry(t *testing.T, home, leafID string) []string {
	t.Helper()
	var chain []string
	current := leafID
	for {
		entry := resolveEntry(t, home, current, true)
		if entry == nil {
			return chain
		}
		chain = append(chain, current)
		parent, ok := entry["parent_id"].(string)
		if !ok {
			return chain
		}
		current = parent
	}
}

func testIdentity() traceIdentity {
	return traceIdentity{
		app: "app", version: "1.2.3", command: "build.run", hasCommand: true,
		effect: "mutating",
	}
}

func mustWrite(t *testing.T, identity traceIdentity) string {
	t.Helper()
	id, ok := traceWriteEntry(identity)
	if !ok {
		t.Fatal("traceWriteEntry reported a failure")
	}
	return id
}

// --- the store's location and shape ---------------------------------------

func TestTraceStorePathIsTheLiteralOne(t *testing.T) {
	home := traceHome(t)
	got, err := traceStoreDir()
	if err != nil {
		t.Fatal(err)
	}
	if got != traceDirOf(home) {
		t.Fatalf("store dir %q, want %q", got, traceDirOf(home))
	}
}

func TestTraceStoreIgnoresXDGDataHome(t *testing.T) {
	home := traceHome(t)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "elsewhere"))
	got, _ := traceStoreDir()
	if got != traceDirOf(home) {
		t.Fatalf("store dir %q, want %q", got, traceDirOf(home))
	}
}

func TestTraceStoreDirectoryIsCreatedOnWriteWithMode0700(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	info, err := os.Stat(traceDirOf(home))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o700 {
		t.Fatalf("store dir mode %v, want 0700", info.Mode().Perm())
	}
}

func TestTracePartitionFileModeIs0600(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	info, err := os.Stat(tracePartitions(t, home)[0])
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Fatalf("partition mode %v, want 0600", info.Mode().Perm())
	}
}

func TestTraceDeletedStoreResumesFromEmpty(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	if err := os.RemoveAll(traceDirOf(home)); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, testIdentity())
	entries, _ := readEntries(t, home)
	if len(entries) != 1 {
		t.Fatalf("got %d entries, want 1", len(entries))
	}
}

// --- the entry ------------------------------------------------------------

func TestTraceEntryCarriesEveryKeyWithItsPinnedType(t *testing.T) {
	home := traceHome(t)
	identity := testIdentity()
	identity.quiet = true
	identity.verbose = true
	identity.machineMode = true
	identity.approveConsequential = true
	id := mustWrite(t, identity)

	entries, anomalies := readEntries(t, home)
	if len(anomalies) != 0 {
		t.Fatalf("anomalies: %v", anomalies)
	}
	if len(entries) != 1 {
		t.Fatalf("got %d entries, want 1", len(entries))
	}
	entry := entries[0]
	want := map[string]interface{}{
		"id": id, "parent_id": nil, "app": "app", "version": "1.2.3",
		"command": "build.run", "dry_run": false, "machine_mode": true,
		"quiet": true, "verbose": true, "approve_consequential": true,
		"effect": "mutating", "pid": float64(os.Getpid()),
	}
	for key, expected := range want {
		if entry[key] != expected {
			t.Errorf("%s = %#v, want %#v", key, entry[key], expected)
		}
	}
	if !strings.HasSuffix(entry["spawned_at"].(string), "Z") {
		t.Errorf("spawned_at = %v", entry["spawned_at"])
	}
}

func TestTraceEntryCommandMayBeNull(t *testing.T) {
	home := traceHome(t)
	identity := testIdentity()
	identity.hasCommand = false
	identity.command = ""
	mustWrite(t, identity)
	entries, _ := readEntries(t, home)
	if entries[0]["command"] != nil {
		t.Fatalf("command = %#v, want null", entries[0]["command"])
	}
}

func TestTraceEntryIsOneLineTerminatedByExactlyOneNewline(t *testing.T) {
	home := traceHome(t)
	for i := 0; i < 3; i++ {
		mustWrite(t, testIdentity())
	}
	data, err := os.ReadFile(tracePartitions(t, home)[0])
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if strings.Count(text, "\n") != 3 {
		t.Fatalf("got %d newlines, want 3", strings.Count(text, "\n"))
	}
	if !strings.HasSuffix(text, "\n") || strings.HasSuffix(text, "\n\n") {
		t.Fatal("the file must end with exactly one newline")
	}
	if strings.Contains(text, ", ") || strings.Contains(text, `": `) {
		t.Fatal("the line must be compact JSON")
	}
}

func TestTraceSpawnedAtIsTheMillisecondEmbeddedInTheID(t *testing.T) {
	home := traceHome(t)
	id := mustWrite(t, testIdentity())
	entries, _ := readEntries(t, home)
	ms, ok := ulidTimestamp(id)
	if !ok {
		t.Fatalf("minted id %q is not canonical", id)
	}
	if entries[0]["spawned_at"] != traceTimestamp(ms) {
		t.Fatalf("spawned_at = %v, want %v", entries[0]["spawned_at"], traceTimestamp(ms))
	}
}

func TestTraceTimestampFormat(t *testing.T) {
	cases := []struct {
		ms   int64
		want string
	}{
		{0, "1970-01-01T00:00:00.000Z"},
		{1, "1970-01-01T00:00:00.001Z"},
		{1786594672913, "2026-08-13T04:17:52.913Z"},
	}
	for _, c := range cases {
		if got := traceTimestamp(c.ms); got != c.want {
			t.Errorf("traceTimestamp(%d) = %q, want %q", c.ms, got, c.want)
		}
	}
}

func TestTraceLabelIsTheRangeStartInUTC(t *testing.T) {
	if got := traceLabel(1786594672913); got != "2026-08-13T04" {
		t.Errorf("traceLabel = %q", got)
	}
	if got := traceLabel(0); got != "1970-01-01T00" {
		t.Errorf("traceLabel = %q", got)
	}
	for _, ms := range []int64{0, 1786594672913, 1234567890123} {
		label := traceLabel(ms)
		start, err := traceLabelStartMs(label)
		if err != nil {
			t.Fatal(err)
		}
		if start > ms || ms-start >= msPerHour || traceLabel(start) != label {
			t.Errorf("label %q start %d does not bracket %d", label, start, ms)
		}
	}
}

// --- partitions -----------------------------------------------------------

func TestTraceFirstWriteCreatesTheCurrentHour(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	want := traceLabel(time.Now().UnixMilli()) + ".jsonl"
	parts := tracePartitions(t, home)
	if len(parts) != 1 || filepath.Base(parts[0]) != want {
		t.Fatalf("partitions %v, want [%s]", parts, want)
	}
}

func TestTraceWritersAppendToTheGreatestNamedFile(t *testing.T) {
	home := traceHome(t)
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"2020-01-01T00.jsonl", "2020-01-01T05.jsonl"} {
		if err := os.WriteFile(filepath.Join(dir, name), nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	mustWrite(t, testIdentity())
	older, _ := os.ReadFile(filepath.Join(dir, "2020-01-01T00.jsonl"))
	newer, _ := os.ReadFile(filepath.Join(dir, "2020-01-01T05.jsonl"))
	if len(older) != 0 || len(newer) == 0 {
		t.Fatalf("wrote to the wrong partition (older %d bytes, newer %d bytes)", len(older), len(newer))
	}
}

func TestTraceNoRollWhenTheFileIsSmall(t *testing.T) {
	home := traceHome(t)
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "2020-01-01T00.jsonl"), make([]byte, 1024), 0o600); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, testIdentity())
	if parts := tracePartitions(t, home); len(parts) != 1 {
		t.Fatalf("partitions %v, want exactly one", parts)
	}
}

func TestTraceNoRollWhenTheHourHasNotAdvanced(t *testing.T) {
	home := traceHome(t)
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	label := traceLabel(time.Now().UnixMilli())
	if err := os.WriteFile(filepath.Join(dir, label+".jsonl"), make([]byte, traceRollBytes), 0o600); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, testIdentity())
	if parts := tracePartitions(t, home); len(parts) != 1 {
		t.Fatalf("partitions %v, want exactly one", parts)
	}
}

func TestTraceRollsWhenBothConditionsHold(t *testing.T) {
	home := traceHome(t)
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "2020-01-01T00.jsonl"), make([]byte, traceRollBytes), 0o600); err != nil {
		t.Fatal(err)
	}
	mustWrite(t, testIdentity())
	parts := tracePartitions(t, home)
	want := traceLabel(time.Now().UnixMilli()) + ".jsonl"
	if len(parts) != 2 || filepath.Base(parts[1]) != want {
		t.Fatalf("partitions %v, want the second to be %s", parts, want)
	}
	data, _ := os.ReadFile(parts[1])
	if !strings.HasSuffix(string(data), "\n") {
		t.Fatal("the new partition did not receive the entry")
	}
}

func TestTraceClampKeepsEveryEntryAtOrAfterItsFilesLabel(t *testing.T) {
	// A partition labelled in the future stands for a clock that jumped
	// backwards. The minted timestamp clamps up to the range start. The clamp
	// is ONE-SIDED (spec page, amended at the lookup-rule audit): nothing
	// bounds an entry from above.
	home := traceHome(t)
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	future := time.Now().UnixMilli() + 5*msPerHour
	label := traceLabel(future)
	if err := os.WriteFile(filepath.Join(dir, label+".jsonl"), nil, 0o600); err != nil {
		t.Fatal(err)
	}
	id := mustWrite(t, testIdentity())
	start, err := traceLabelStartMs(label)
	if err != nil {
		t.Fatal(err)
	}
	ms, _ := ulidTimestamp(id)
	if ms != start {
		t.Fatalf("minted timestamp %d, want the clamped %d", ms, start)
	}
	entries, _ := readEntries(t, home)
	if entries[0]["spawned_at"] != traceTimestamp(start) {
		t.Fatalf("spawned_at = %v, want %v", entries[0]["spawned_at"], traceTimestamp(start))
	}
}

func TestTraceReadersIgnoreNonPartitionFiles(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	dir := traceDirOf(home)
	for name, content := range map[string]string{
		traceMarkerName:           "2020-01-01T00:00:00.000Z\n",
		"notes.txt":               "not a partition\n",
		"2020-01-01T00.jsonl.bak": "junk\n",
	} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	entries, anomalies := readEntries(t, home)
	if len(entries) != 1 || len(anomalies) != 0 {
		t.Fatalf("got %d entries and %d anomalies, want 1 and 0", len(entries), len(anomalies))
	}
}

// --- the lookup rule ------------------------------------------------------

// strandedStore builds the store the lookup-rule audit constructed, using the
// real writer.
//
//  1. A partition labelled for the PREVIOUS hour is the greatest-named file, so
//     the writer appends to it and mints a timestamp in the CURRENT hour: that
//     entry is stranded above its own file's label.
//  2. Padding that file past the roll threshold makes the next write roll, and
//     the new partition is labelled for the current hour -- the very label the
//     stranded entry's timestamp points at.
//
// It returns (strandedID, rolledID). When link is true the rolled entry
// inherits the stranded one as its parent, so the pair is a chain that crosses
// the strand.
func strandedStore(t *testing.T, home string, link bool) (string, string) {
	t.Helper()
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	prevLabel := traceLabel(time.Now().UnixMilli() - msPerHour)
	prev := filepath.Join(dir, prevLabel+".jsonl")
	if err := os.WriteFile(prev, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	stranded := mustWrite(t, testIdentity())
	// Padding past the roll threshold. It is one anomalous line, which every
	// reader here skips.
	appendRaw(t, prev, strings.Repeat("x", traceRollBytes)+"\n")
	if link {
		t.Setenv(traceParentEnv, stranded)
	}
	rolled := mustWrite(t, testIdentity())
	if parts := tracePartitions(t, home); len(parts) != 2 {
		t.Fatalf("partitions %v, want exactly two", parts)
	}
	return stranded, rolled
}

func TestTraceRangeIsNotBoundedAtTheTop(t *testing.T) {
	// The falsifying store: an entry whose timestamp is at or beyond the NEXT
	// partition's label, living in the older file.
	home := traceHome(t)
	stranded, _ := strandedStore(t, home, false)
	parts := tracePartitions(t, home)
	older, _ := entriesIn(t, parts[0])
	if len(older) != 1 || older[0]["id"] != stranded {
		t.Fatalf("the stranded entry is not in the older partition: %#v", older)
	}
	newerLabel := strings.TrimSuffix(filepath.Base(parts[1]), ".jsonl")
	start, err := traceLabelStartMs(newerLabel)
	if err != nil {
		t.Fatal(err)
	}
	ms, _ := ulidTimestamp(stranded)
	if ms < start {
		t.Fatalf("stranded timestamp %d is below the newer label's start %d", ms, start)
	}
}

func TestTraceStrandedEntryIsFoundByWalkingBackward(t *testing.T) {
	home := traceHome(t)
	stranded, _ := strandedStore(t, home, false)
	entry := resolveEntry(t, home, stranded, true)
	if entry == nil || entry["id"] != stranded {
		t.Fatalf("resolveEntry returned %#v, want the stranded entry", entry)
	}
}

func TestTraceOneBinarySearchAloneMissesTheStrandedEntry(t *testing.T) {
	// The rule the spec page carried until the lookup-rule audit: search the
	// partition the timestamp points at and stop. It reports a live entry as
	// missing, which a consumer records as a dangling parent.
	home := traceHome(t)
	stranded, _ := strandedStore(t, home, false)
	if entry := resolveEntry(t, home, stranded, false); entry != nil {
		t.Fatalf("the single search found %#v; the amendment exists because it does not", entry)
	}
}

func TestTraceUnstrandedEntryIsFoundByTheFirstSearch(t *testing.T) {
	home := traceHome(t)
	_, rolled := strandedStore(t, home, false)
	if entry := resolveEntry(t, home, rolled, false); entry == nil {
		t.Fatal("the entry in the newest partition must be found by the first search")
	}
}

func TestTraceChainAcrossTheStrandStillFlattens(t *testing.T) {
	home := traceHome(t)
	stranded, rolled := strandedStore(t, home, true)
	chain := flattenAncestry(t, home, rolled)
	if len(chain) != 2 || chain[0] != rolled || chain[1] != stranded {
		t.Fatalf("chain %v, want [%s %s]", chain, rolled, stranded)
	}
}

func TestTraceIdentifierNoStoreHoldsResolvesToNothing(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	if entry := resolveEntry(t, home, "01JZ8X4M6N7QK2WVBD3F5RTYAC", true); entry != nil {
		t.Fatalf("resolved %#v for an identifier no store holds", entry)
	}
}

func TestTraceUnparseableIdentifierResolvesToNothing(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	if entry := resolveEntry(t, home, "not-a-ulid", true); entry != nil {
		t.Fatalf("resolved %#v for an unparseable identifier", entry)
	}
}

// --- propagation ----------------------------------------------------------

func TestTraceParentIDIsTheInheritedIdentifier(t *testing.T) {
	home := traceHome(t)
	parent, err := ulidMint(1786594672913)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv(traceParentEnv, parent)
	mustWrite(t, testIdentity())
	entries, _ := readEntries(t, home)
	if entries[0]["parent_id"] != parent {
		t.Fatalf("parent_id = %#v, want %q", entries[0]["parent_id"], parent)
	}
}

func TestTraceMalformedInheritedValueRecordsANullParent(t *testing.T) {
	for _, polluted := range []string{
		"", "not-a-ulid", "01jz8x4m6n7qk2wvbd3f5rtyac",
		"ZZZZZZZZZZZZZZZZZZZZZZZZZZ", "01JZ8X4M6N7QK2WVBD3F5RTYA",
	} {
		t.Run(strconv.Quote(polluted), func(t *testing.T) {
			home := traceHome(t)
			t.Setenv(traceParentEnv, polluted)
			mustWrite(t, testIdentity()) // never bricks the run
			entries, anomalies := readEntries(t, home)
			if entries[0]["parent_id"] != nil || len(anomalies) != 0 {
				t.Fatalf("parent_id = %#v, anomalies %v", entries[0]["parent_id"], anomalies)
			}
		})
	}
}

func TestTraceChildEnvComposesTheIdentifierAfterTheHandlerMerge(t *testing.T) {
	home := traceHome(t)
	t.Setenv(traceParentEnv, "01JZ8X4M6N7QK2WVBD3F5RTYAC")
	base := mergedEnv(map[string]string{
		traceParentEnv: "01JZ8X4M6N7QK2WVBD3F5RTYAC",
		"MY_KEY":       "mine",
	})
	out := traceChildEnv(base, testIdentity())
	entries, _ := readEntries(t, home)
	wantID, _ := entries[0]["id"].(string)

	var seenTraceParent, seenMyKey string
	count := 0
	for _, entry := range out {
		if strings.HasPrefix(entry, traceParentEnv+"=") {
			seenTraceParent = strings.TrimPrefix(entry, traceParentEnv+"=")
			count++
		}
		if strings.HasPrefix(entry, "MY_KEY=") {
			seenMyKey = strings.TrimPrefix(entry, "MY_KEY=")
		}
	}
	if count != 1 || seenTraceParent != wantID {
		t.Fatalf("child got %s=%q (%d occurrences), want the framework's %q",
			traceParentEnv, seenTraceParent, count, wantID)
	}
	if seenMyKey != "mine" {
		t.Fatalf("every other handler key must still win, got MY_KEY=%q", seenMyKey)
	}
	// The spawning process's own environment is never mutated.
	if os.Getenv(traceParentEnv) != "01JZ8X4M6N7QK2WVBD3F5RTYAC" {
		t.Fatal("the spawning process's environment was mutated")
	}
}

func TestTraceChildEnvRemovesTheVariableWhenTheStoreIsBroken(t *testing.T) {
	// A lost record must not silently re-attribute the child to its
	// grandparent, so the inherited value is dropped rather than passed on.
	home := traceHome(t)
	breakStore(t, home)
	t.Setenv(traceParentEnv, "01JZ8X4M6N7QK2WVBD3F5RTYAC")
	for _, entry := range traceChildEnv(nil, testIdentity()) {
		if strings.HasPrefix(entry, traceParentEnv+"=") {
			t.Fatalf("the child still carries %q", entry)
		}
	}
}

// --- the seam -------------------------------------------------------------

func traceApp(effect string, fn func(ctx *Context) Outcome, opts ...CmdOption) *App {
	app := NewApp("app", "1.2.3", "trace fixture")
	all := append([]CmdOption{WithEffect(effect)}, opts...)
	app.Command("go", "run the fixture handler",
		func(ctx *Context, kwargs map[string]interface{}) Outcome { return fn(ctx) }, all...)
	return app
}

func TestTraceLiveRunWritesOneEntry(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		if _, err := ctx.Effects().Run([]interface{}{"true"}); err != nil {
			t.Fatal(err)
		}
		return Exit(0)
	})
	if r := app.Test([]string{"go"}); r.ExitCode != 0 {
		t.Fatalf("exit %d: %s", r.ExitCode, r.Stderr)
	}
	entries, _ := readEntries(t, home)
	if len(entries) != 1 || entries[0]["command"] != "go" || entries[0]["dry_run"] != false {
		t.Fatalf("entries: %#v", entries)
	}
}

func TestTraceLiveSpawnWritesOneEntry(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		s, err := ctx.Effects().Spawn([]interface{}{"true"})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := s.Wait(); err != nil {
			t.Fatal(err)
		}
		return Exit(0)
	})
	app.Test([]string{"go"})
	entries, _ := readEntries(t, home)
	if len(entries) != 1 {
		t.Fatalf("got %d entries, want 1", len(entries))
	}
}

func TestTraceRecordedDryModeSpawnWritesNothing(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		ctx.Effects().Spawn([]interface{}{"true"})
		return Exit(0)
	})
	app.Test([]string{"--dry-run", "go"})
	if entries, _ := readEntries(t, home); len(entries) != 0 {
		t.Fatalf("a recorded spawn started nothing, so it must trace nothing: %#v", entries)
	}
}

func TestTraceRecordedDryModeRunWritesNothing(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		ctx.Effects().Run([]interface{}{"true"})
		return Exit(0)
	})
	app.Test([]string{"--dry-run", "go"})
	if entries, _ := readEntries(t, home); len(entries) != 0 {
		t.Fatalf("entries: %#v", entries)
	}
}

func TestTraceAllowlistedObserveInDryModeWritesAnEntry(t *testing.T) {
	// An observe genuinely executes in dry mode, so a real child starts -- and
	// the entry carries dry_run: true, which is the only way that field can
	// ever be true.
	home := traceHome(t)
	app := NewApp("app", "1.2.3", "trace fixture",
		WithProcObserveAllowlist([][]string{{"true", "--ok"}}))
	app.Command("go", "run the fixture handler",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Effects().Run([]interface{}{"true", "--ok"})
			return Exit(0)
		}, WithEffect(EffectReadOnly))
	app.Test([]string{"--dry-run", "go"})
	entries, _ := readEntries(t, home)
	if len(entries) != 1 || entries[0]["dry_run"] != true || entries[0]["effect"] != EffectReadOnly {
		t.Fatalf("entries: %#v", entries)
	}
}

func TestTraceStaleObserveInDryModeWritesNothing(t *testing.T) {
	// After a recorded mutation the observe is not executed at all, so no
	// child starts and no entry is written.
	home := traceHome(t)
	app := NewApp("app", "1.2.3", "trace fixture",
		WithProcObserveAllowlist([][]string{{"true", "--ok"}}))
	app.Command("go", "run the fixture handler",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			ctx.Effects().Mkdir(filepath.Join(t.TempDir(), "d"))
			ctx.Effects().Run([]interface{}{"true", "--ok"})
			return Exit(0)
		}, WithEffect("mutating"))
	app.Test([]string{"--dry-run", "go"})
	if entries, _ := readEntries(t, home); len(entries) != 0 {
		t.Fatalf("entries: %#v", entries)
	}
}

func TestTraceRecordsTheReservedFlagState(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		ctx.Effects().Run([]interface{}{"true"})
		return Exit(0)
	}, WithConsequential())
	app.Test([]string{"go", "--quiet", "--approve-consequential"})
	entries, _ := readEntries(t, home)
	if entries[0]["quiet"] != true || entries[0]["verbose"] != false ||
		entries[0]["approve_consequential"] != true || entries[0]["machine_mode"] != false {
		t.Fatalf("entry: %#v", entries[0])
	}
}

func TestTraceRecordsMachineMode(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		ctx.Effects().Run([]interface{}{"true"})
		return Exit(0)
	})
	app.Test([]string{"go", "--json"})
	entries, _ := readEntries(t, home)
	if entries[0]["machine_mode"] != true {
		t.Fatalf("entry: %#v", entries[0])
	}
}

func TestTraceNeverRecordsArgv(t *testing.T) {
	home := traceHome(t)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		ctx.Effects().Run([]interface{}{"true", "s3cr3t-token"})
		return Exit(0)
	})
	app.Test([]string{"go"})
	data, err := os.ReadFile(tracePartitions(t, home)[0])
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "s3cr3t-token") {
		t.Fatal("argv reached the store")
	}
}

func TestTraceChildReceivesTheEntrysIdentifier(t *testing.T) {
	home := traceHome(t)
	var seen string
	app := traceApp("mutating", func(ctx *Context) Outcome {
		out, err := ctx.Effects().Run([]interface{}{
			"sh", "-c", "printf %s \"${STRICTCLI_TRACE_PARENT:-<unset>}\"",
		})
		if err != nil {
			t.Fatal(err)
		}
		seen = out.Stdout()
		return Exit(0)
	})
	app.Test([]string{"go"})
	entries, _ := readEntries(t, home)
	if len(entries) != 1 || seen != entries[0]["id"] {
		t.Fatalf("child saw %q, entries %#v", seen, entries)
	}
}

// --- failure policy -------------------------------------------------------

func breakStore(t *testing.T, home string) string {
	t.Helper()
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(dir, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o700) })
	return dir
}

func TestTraceWriteFailureNeverFailsTheRunAndPrintsNothing(t *testing.T) {
	home := traceHome(t)
	breakStore(t, home)
	app := traceApp("mutating", func(ctx *Context) Outcome {
		ctx.Effects().Run([]interface{}{"true"})
		return Exit(0)
	})
	r := app.Test([]string{"go"})
	if r.ExitCode != 0 || r.Stdout != "" || r.Stderr != "" {
		t.Fatalf("exit %d, stdout %q, stderr %q", r.ExitCode, r.Stdout, r.Stderr)
	}
}

func TestTraceWriteFailureReturnsNoIdentifier(t *testing.T) {
	home := traceHome(t)
	breakStore(t, home)
	if id, ok := traceWriteEntry(testIdentity()); ok {
		t.Fatalf("got id %q, want a swallowed failure", id)
	}
}

func TestTraceFirstFailureWritesTheWriteOnceMarker(t *testing.T) {
	home := traceHome(t)
	dir := traceDirOf(home)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	// A directory the writer can create the marker in, but whose partition
	// path cannot be opened as a file.
	label := traceLabel(time.Now().UnixMilli())
	if err := os.Mkdir(filepath.Join(dir, label+".jsonl"), 0o700); err != nil {
		t.Fatal(err)
	}
	if _, ok := traceWriteEntry(testIdentity()); ok {
		t.Fatal("the write should have failed")
	}
	marker := filepath.Join(dir, traceMarkerName)
	data, err := os.ReadFile(marker)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	if strings.Count(text, "\n") != 1 || !strings.HasSuffix(text, "\n") {
		t.Fatalf("marker content %q", text)
	}
	stamp := strings.TrimSuffix(text, "\n")
	if !regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`).MatchString(stamp) {
		t.Fatalf("marker timestamp %q is not in spawned_at's format", stamp)
	}
	// Write-once: three more failures leave the first content untouched.
	time.Sleep(5 * time.Millisecond)
	for i := 0; i < 3; i++ {
		traceWriteEntry(testIdentity())
	}
	again, _ := os.ReadFile(marker)
	if string(again) != text {
		t.Fatalf("marker was rewritten: %q then %q", text, string(again))
	}
}

func TestTraceMarkerFailureIsSwallowedToo(t *testing.T) {
	home := traceHome(t)
	dir := breakStore(t, home)
	if _, ok := traceWriteEntry(testIdentity()); ok {
		t.Fatal("the write should have failed")
	}
	if _, err := os.Stat(filepath.Join(dir, traceMarkerName)); err == nil {
		t.Fatal("the marker cannot exist in an unwritable directory")
	}
}

func TestTraceStorePathThatIsAFileIsSwallowed(t *testing.T) {
	home := traceHome(t)
	parent := filepath.Join(home, ".local", "share", "strictcli")
	if err := os.MkdirAll(parent, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(parent, "trace"), []byte("not a directory"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, ok := traceWriteEntry(testIdentity()); ok {
		t.Fatal("the write should have failed")
	}
}

// --- malformed data -------------------------------------------------------

func TestTraceTornLineIsSkippedAndRecordedAsAnAnomaly(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	path := tracePartitions(t, home)[0]
	appendRaw(t, path, `{"id":"01JZ8X4M6N7QK2WVBD3F5RTYAC","parent`+"\n")
	mustWrite(t, testIdentity())
	entries, anomalies := readEntries(t, home)
	if len(entries) != 2 || len(anomalies) != 1 {
		t.Fatalf("got %d entries and %d anomalies, want 2 and 1", len(entries), len(anomalies))
	}
}

func TestTraceTruncatedFinalLineDoesNotDisturbWriters(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	appendRaw(t, tracePartitions(t, home)[0], `{"id":"01JZ8X4M6N7QK2WVBD3F5R`)
	if _, ok := traceWriteEntry(testIdentity()); !ok {
		t.Fatal("a torn line must not stop a writer")
	}
	if _, err := os.Stat(filepath.Join(traceDirOf(home), traceMarkerName)); err == nil {
		t.Fatal("a torn line is not a write failure")
	}
	entries, anomalies := readEntries(t, home)
	if len(entries) != 1 || len(anomalies) != 1 {
		t.Fatalf("got %d entries and %d anomalies, want 1 and 1", len(entries), len(anomalies))
	}
}

func TestTraceEntryMissingAKeyIsAnAnomalyNotADefault(t *testing.T) {
	home := traceHome(t)
	mustWrite(t, testIdentity())
	appendRaw(t, tracePartitions(t, home)[0], `{"id":"01JZ8X4M6N7QK2WVBD3F5RTYAC"}`+"\n")
	entries, anomalies := readEntries(t, home)
	if len(entries) != 1 || len(anomalies) != 1 {
		t.Fatalf("got %d entries and %d anomalies, want 1 and 1", len(entries), len(anomalies))
	}
}

func appendRaw(t *testing.T, path, text string) {
	t.Helper()
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString(text); err != nil {
		t.Fatal(err)
	}
	if err := f.Close(); err != nil {
		t.Fatal(err)
	}
}

// --- the chain ------------------------------------------------------------

const chainDepthEnv = "STRICTCLI_TEST_CHAIN_DEPTH"

// TestTraceSpawnChainHelper is the chain's link. Run normally it is a no-op;
// run with chainDepthEnv set it is a strictcli app whose handler spawns the
// next link and waits, which is how a real multi-process chain is built out of
// the test binary itself.
func TestTraceSpawnChainHelper(t *testing.T) {
	depthText := os.Getenv(chainDepthEnv)
	if depthText == "" {
		t.Skip("not a chain link")
	}
	depth, err := strconv.Atoi(depthText)
	if err != nil {
		fmt.Fprintln(os.Stderr, "bad depth:", err)
		os.Exit(2)
	}
	app := NewApp("chain", "9.9.9", "chain")
	app.Command("go", "start the next link",
		func(ctx *Context, kwargs map[string]interface{}) Outcome {
			if depth > 0 {
				s, err := ctx.Effects().Spawn(
					[]interface{}{os.Args[0], "-test.run=TestTraceSpawnChainHelper"},
					EffectEnv(map[string]string{chainDepthEnv: strconv.Itoa(depth - 1)}),
				)
				if err != nil {
					fmt.Fprintln(os.Stderr, "spawn:", err)
					os.Exit(3)
				}
				if _, err := s.Wait(); err != nil {
					fmt.Fprintln(os.Stderr, "wait:", err)
					os.Exit(4)
				}
			}
			return Exit(0)
		}, WithEffect("mutating"))
	r := app.Test([]string{"go"})
	os.Exit(r.ExitCode)
}

func TestTraceThreeDeepSpawnChainYieldsAFlattenedAncestry(t *testing.T) {
	home := traceHome(t)
	cmd := exec.Command(os.Args[0], "-test.run=TestTraceSpawnChainHelper")
	cmd.Env = append(os.Environ(), chainDepthEnv+"=3")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("chain root failed: %v\n%s", err, out)
	}

	entries, anomalies := readEntries(t, home)
	if len(anomalies) != 0 {
		t.Fatalf("anomalies: %v", anomalies)
	}
	// Four processes, three of which start a child: three entries.
	if len(entries) != 3 {
		t.Fatalf("got %d entries, want 3", len(entries))
	}
	parents := map[string]bool{}
	for _, e := range entries {
		if e["app"] != "chain" || e["command"] != "go" {
			t.Fatalf("unexpected entry: %#v", e)
		}
		if parent, ok := e["parent_id"].(string); ok {
			parents[parent] = true
		}
	}
	var leaf string
	for _, e := range entries {
		if !parents[e["id"].(string)] {
			if leaf != "" {
				t.Fatal("more than one leaf entry")
			}
			leaf = e["id"].(string)
		}
	}
	chain := flattenAncestry(t, home, leaf)
	if len(chain) != 3 {
		t.Fatalf("flattened ancestry %v, want three links", chain)
	}
	byID := map[string]map[string]interface{}{}
	for _, e := range entries {
		byID[e["id"].(string)] = e
	}
	if byID[chain[2]]["parent_id"] != nil {
		t.Fatalf("the root must have no parent, got %#v", byID[chain[2]]["parent_id"])
	}
	pids := map[float64]bool{}
	for _, id := range chain {
		pids[byID[id]["pid"].(float64)] = true
	}
	if len(pids) != 3 {
		t.Fatalf("the chain must witness three distinct pids, got %v", pids)
	}
}
