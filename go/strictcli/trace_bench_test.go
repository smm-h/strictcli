package strictcli

import "testing"

// BenchmarkTraceWriteEntry pins the write's cost against a child process start:
// the store's whole design (one append, no lock, no daemon) rests on the write
// being negligible next to the milliseconds a spawn costs.
func BenchmarkTraceWriteEntry(b *testing.B) {
	dir := b.TempDir()
	b.Setenv("HOME", dir)
	identity := traceIdentity{
		app: "app", version: "1.2.3", command: "release.run", hasCommand: true,
		effect: "mutating",
	}
	traceWriteEntry(identity)
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		traceWriteEntry(identity)
	}
}
