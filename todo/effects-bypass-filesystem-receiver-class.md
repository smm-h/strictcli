# effects-bypass: remaining receiver-blind filesystem leaves

The 2026-08-09 fix made process/network leaves receiver-aware (Python import-binding table;
TS receiver scoping; Go was already correct). The same false-positive class persists for
FILESYSTEM leaves: e.g. Python flags `truncate` on an io.StringIO; Go flags
bytes.Buffer.Truncate. Sweep the fs ban set through the same receiver machinery, red-green,
all three languages, plus a contract §11.1 note.

Effort: small.
