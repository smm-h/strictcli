package strictcli

// The process trace store.
//
// The normative specification is docs/process-trace-store.md; the effects
// contract's §20 carries the two contract items (observational-only, and the
// best-effort failure carve-out). Nothing here is ever read back into a
// decision: the framework mints an identifier, appends one line, and composes
// the identifier into the CHILD's environment. There is no accessor.

import (
	"bytes"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

// traceParentEnv is the one variable ancestry travels through. It carries
// exactly one thing: the parent entry's identifier.
const traceParentEnv = "STRICTCLI_TRACE_PARENT"

// crockford is the exact alphabet: no I, L, O or U.
const crockford = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

const (
	ulidLen         = 26
	traceRollBytes  = 8 * 1024 * 1024
	traceMarkerName = "write-failure.marker"
	traceFileMode   = 0o600
	traceDirMode    = 0o700
	msPerHour       = 3600000
)

var tracePartitionRe = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}T\d{2}\.jsonl$`)

// ulidEncode encodes 48 timestamp bits plus 80 random bits as 26 Crockford
// characters. 26 characters carry 130 bits, so the 128-bit value is left-padded
// with two zero bits -- which is exactly why a canonical identifier's first
// character never exceeds '7'.
func ulidEncode(ms int64, randomness []byte) string {
	value := new(big.Int).SetInt64(ms)
	value.Lsh(value, 80)
	value.Or(value, new(big.Int).SetBytes(randomness))
	out := make([]byte, ulidLen)
	mask := big.NewInt(0x1F)
	digit := new(big.Int)
	shifted := new(big.Int)
	for i := 0; i < ulidLen; i++ {
		shift := uint(125 - 5*i)
		shifted.Rsh(value, shift)
		digit.And(shifted, mask)
		out[i] = crockford[digit.Int64()]
	}
	return string(out)
}

// ulidMint mints an identifier from this writer's clock plus 80 CSPRNG bits.
func ulidMint(ms int64) (string, error) {
	randomness := make([]byte, 10)
	if _, err := rand.Read(randomness); err != nil {
		return "", err
	}
	return ulidEncode(ms, randomness), nil
}

// ulidTimestamp parses under the strict profile and returns the millisecond.
//
// Rejected, never repaired: any length but 26, any character outside the
// canonical uppercase alphabet (lowercase included -- one identifier must have
// exactly one spelling), and a 130-bit value that overflows 128 bits.
func ulidTimestamp(text string) (int64, bool) {
	if len([]rune(text)) != ulidLen || len(text) != ulidLen {
		return 0, false
	}
	value := new(big.Int)
	for i := 0; i < ulidLen; i++ {
		index := strings.IndexByte(crockford, text[i])
		if index < 0 {
			return 0, false
		}
		value.Lsh(value, 5)
		value.Or(value, big.NewInt(int64(index)))
	}
	if value.BitLen() > 128 {
		return 0, false
	}
	return value.Rsh(value, 80).Int64(), true
}

func ulidValid(text string) bool {
	_, ok := ulidTimestamp(text)
	return ok
}

// traceStoreDir is the literal store path. ~ is expanded and nothing else is
// consulted -- deliberately NOT XDG_DATA_HOME, because two conforming writers
// that disagreed about the location would produce two stores on one machine and
// a chain crossing them would dangle at both ends.
func traceStoreDir() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".local", "share", "strictcli", "trace"), nil
}

// traceLabel is the UTC-hour label for an instant: the partition's range start.
func traceLabel(ms int64) string {
	return time.Unix((ms/msPerHour)*3600, 0).UTC().Format("2006-01-02T15")
}

// traceLabelStartMs is the inverse: a label's range start in epoch milliseconds.
func traceLabelStartMs(label string) (int64, error) {
	t, err := time.ParseInLocation("2006-01-02T15", label, time.UTC)
	if err != nil {
		return 0, err
	}
	return t.Unix() * 1000, nil
}

// traceTimestamp renders RFC 3339 in UTC with exactly three fractional digits
// and a Z suffix.
func traceTimestamp(ms int64) string {
	return fmt.Sprintf(
		"%s.%03dZ",
		time.Unix(ms/1000, 0).UTC().Format("2006-01-02T15:04:05"),
		ms%1000,
	)
}

// traceActiveLabel selects the partition to append to, rolling when both
// conditions hold. The greatest-named file is the active partition; a new one is
// created with O_EXCL when the active file is at least 8 MB AND the current UTC
// hour is later than its label. Losing the creation race is not an error -- the
// loser appends to the winner's file.
func traceActiveLabel(store string, nowMs int64) (string, error) {
	nowLabel := traceLabel(nowMs)
	names, err := os.ReadDir(store)
	if err != nil {
		return "", err
	}
	active := ""
	for _, entry := range names {
		name := entry.Name()
		if tracePartitionRe.MatchString(name) && name > active {
			active = name
		}
	}
	if active == "" {
		traceCreatePartition(store, nowLabel)
		return nowLabel, nil
	}
	label := strings.TrimSuffix(active, ".jsonl")
	if nowLabel > label {
		if info, err := os.Stat(filepath.Join(store, active)); err == nil &&
			info.Size() >= traceRollBytes {
			traceCreatePartition(store, nowLabel)
			return nowLabel, nil
		}
	}
	return label, nil
}

func traceCreatePartition(store, label string) {
	f, err := os.OpenFile(
		filepath.Join(store, label+".jsonl"),
		os.O_WRONLY|os.O_CREATE|os.O_EXCL,
		traceFileMode,
	)
	if err != nil {
		return // another writer won the race; append to its file
	}
	_ = f.Close()
}

// traceIdentity is what an entry says about the invocation doing the spawning.
type traceIdentity struct {
	app                  string
	version              string
	command              string
	hasCommand           bool
	dryRun               bool
	machineMode          bool
	quiet                bool
	verbose              bool
	approveConsequential bool
	effect               string
}

// traceEntry is the line's shape. Every key is always present: an absent key is
// a malformed line, not a defaulted one.
type traceEntry struct {
	ID                   string  `json:"id"`
	ParentID             *string `json:"parent_id"`
	App                  string  `json:"app"`
	Version              string  `json:"version"`
	Command              *string `json:"command"`
	DryRun               bool    `json:"dry_run"`
	MachineMode          bool    `json:"machine_mode"`
	Quiet                bool    `json:"quiet"`
	Verbose              bool    `json:"verbose"`
	ApproveConsequential bool    `json:"approve_consequential"`
	Effect               string  `json:"effect"`
	PID                  int     `json:"pid"`
	SpawnedAt            string  `json:"spawned_at"`
}

// traceWriteEntry appends one entry for a real child-process start and returns
// its identifier.
//
// Returns ("", false) when anything at all went wrong: tracing is best-effort by
// declared design (contract §20.3), so a failure never fails the run, never
// prints, and is never retried. The first failure leaves a write-once marker.
func traceWriteEntry(identity traceIdentity) (string, bool) {
	id, err := traceWrite(identity)
	if err != nil {
		traceMarkFailure()
		return "", false
	}
	return id, true
}

func traceWrite(identity traceIdentity) (string, error) {
	store, err := traceStoreDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(store, traceDirMode); err != nil {
		return "", err
	}
	nowMs := time.Now().UnixMilli()
	label, err := traceActiveLabel(store, nowMs)
	if err != nil {
		return "", err
	}
	start, err := traceLabelStartMs(label)
	if err != nil {
		return "", err
	}
	// The clamp invariant: an entry always lies inside its file's range, which
	// is what makes lookup a binary search over filenames.
	ms := nowMs
	if start > ms {
		ms = start
	}
	id, err := ulidMint(ms)
	if err != nil {
		return "", err
	}
	entry := traceEntry{
		ID:                   id,
		App:                  identity.app,
		Version:              identity.version,
		DryRun:               identity.dryRun,
		MachineMode:          identity.machineMode,
		Quiet:                identity.quiet,
		Verbose:              identity.verbose,
		ApproveConsequential: identity.approveConsequential,
		Effect:               identity.effect,
		PID:                  os.Getpid(),
		SpawnedAt:            traceTimestamp(ms),
	}
	if inherited := os.Getenv(traceParentEnv); ulidValid(inherited) {
		value := inherited
		entry.ParentID = &value
	}
	if identity.hasCommand {
		value := identity.command
		entry.Command = &value
	}
	var buf bytes.Buffer
	encoder := json.NewEncoder(&buf)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(entry); err != nil { // Encode appends the newline
		return "", err
	}
	f, err := os.OpenFile(
		filepath.Join(store, label+".jsonl"),
		os.O_WRONLY|os.O_APPEND|os.O_CREATE,
		traceFileMode,
	)
	if err != nil {
		return "", err
	}
	if _, err := f.Write(buf.Bytes()); err != nil {
		_ = f.Close()
		return "", err
	}
	if err := f.Close(); err != nil {
		return "", err
	}
	return id, nil
}

// traceMarkFailure creates the write-once failure marker. No counter, no retry,
// no noise: a disk-full condition blinds the marker too, and that is accepted.
func traceMarkFailure() {
	store, err := traceStoreDir()
	if err != nil {
		return
	}
	f, err := os.OpenFile(
		filepath.Join(store, traceMarkerName),
		os.O_WRONLY|os.O_CREATE|os.O_EXCL,
		traceFileMode,
	)
	if err != nil {
		return
	}
	_, _ = f.WriteString(traceTimestamp(time.Now().UnixMilli()) + "\n")
	_ = f.Close()
}

// traceChildEnv composes the child's environment at a real child-process start.
//
// The handler's env merge happens first; the framework's ancestry composition is
// applied AFTER it and wins (contract §2.5), so a handler can neither sever the
// chain by clearing the variable nor forge a different ancestor by setting it.
// When the entry could not be written the variable is REMOVED rather than left
// inherited: a lost record must not silently re-attribute the child to its
// grandparent.
func traceChildEnv(base []string, identity traceIdentity) []string {
	if base == nil {
		base = os.Environ()
	}
	id, ok := traceWriteEntry(identity)
	out := make([]string, 0, len(base)+1)
	for _, entry := range base {
		if eq := strings.IndexByte(entry, '='); eq >= 0 &&
			entry[:eq] == traceParentEnv {
			continue
		}
		out = append(out, entry)
	}
	if ok {
		out = append(out, traceParentEnv+"="+id)
	}
	return out
}
