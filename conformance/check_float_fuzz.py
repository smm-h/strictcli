#!/usr/bin/env python3
"""Cross-language float differential fuzz.

Draws a fixed committed sample of doubles, formats each with the Python, Go,
and TypeScript canonical float formatters (SCF), and asserts three-way
byte-for-byte agreement plus round-trip identity.

The Python formatter runs in-process. The Go formatter runs in exactly ONE
process: a package-internal `go test` stdin->file filter
(``TestFloatFuzzFilter`` in ``go/strictcli/float_fuzz_filter_test.go``) reads
the whole batch of hex bit patterns on stdin and writes canonical strings to a
temp file. The TypeScript formatter also runs in exactly ONE process: a batch
stdin->stdout filter (``typescript/tests/float_fuzz_filter.ts``, compiled by
``tsc -p tsconfig.test.json``) reads the same batch on stdin and writes
canonical strings to stdout. No per-value process spawning anywhere.

Exit 0 on full agreement; exit 1 (printing the offending uint64 hex patterns)
otherwise.
"""

from __future__ import annotations

import math
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import strictcli

CONFORMANCE_DIR = Path(__file__).resolve().parent
GO_DIR = CONFORMANCE_DIR.parent / "go"
TS_DIR = CONFORMANCE_DIR.parent / "typescript"
TS_FILTER = TS_DIR / "dist-test" / "tests" / "float_fuzz_filter.js"

# Fixed committed seed and sample size for the differential fuzz. Deterministic
# so failures are reproducible and CI is stable.
FIXED_SEED = 0x0FF5_CF12  # "OFF SCF 12"
SAMPLE_SIZE = 2000


def _from_bits(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def _sample_bits() -> list[int]:
    """Deterministic uint64 bit patterns for finite doubles (no NaN/Inf)."""
    rng = random.Random(FIXED_SEED)
    out: list[int] = []
    while len(out) < SAMPLE_SIZE:
        bits = rng.getrandbits(64)
        x = _from_bits(bits)
        if math.isnan(x) or math.isinf(x):
            continue
        out.append(bits)
    return out


def _go_format(bit_patterns: list[int]) -> list[str]:
    """Format every bit pattern via the Go formatter in a single Go process.

    The Go side is a package-internal test function used as a stdin->file
    filter. ``go test`` itself detaches the test binary's stdin, so we compile
    the test binary once (``go test -c``) and then run it once, feeding the
    whole batch on stdin. That is a single formatting process -- no per-value
    spawning.
    """
    stdin_text = "".join(f"{b:016x}\n" for b in bit_patterns)
    with tempfile.TemporaryDirectory() as tmp:
        bin_path = str(Path(tmp) / "strictcli_fuzz.test")
        out_path = str(Path(tmp) / "canonical.txt")

        build = subprocess.run(
            ["go", "test", "-c", "-o", bin_path, "./strictcli/"],
            cwd=str(GO_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if build.returncode != 0:
            raise RuntimeError(f"go test -c failed:\n{build.stderr}")

        run = subprocess.run(
            [bin_path, "-test.run", "^TestFloatFuzzFilter$"],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=300,
            env={
                **_base_env(),
                "STRICTCLI_FUZZ_STDIN": "1",
                "STRICTCLI_FUZZ_OUT": out_path,
            },
        )
        if run.returncode != 0:
            raise RuntimeError(
                "go fuzz filter failed:\n"
                f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}"
            )
        lines = Path(out_path).read_text().splitlines()

    if len(lines) != len(bit_patterns):
        raise RuntimeError(
            f"go produced {len(lines)} lines for {len(bit_patterns)} inputs"
        )
    return lines


def _ts_format(bit_patterns: list[int]) -> list[str]:
    """Format every bit pattern via the TS formatter in a single Node process.

    The TS side is a plain stdin->stdout batch filter
    (``typescript/tests/float_fuzz_filter.ts``). It is compiled once
    (``tsc -p tsconfig.test.json`` -> ``dist-test/``) and then run once,
    feeding the whole batch on stdin -- a single formatting process, no
    per-value spawning. Node stdout is clean (no test-runner noise), so the
    canonical strings come straight back on stdout.
    """
    stdin_text = "".join(f"{b:016x}\n" for b in bit_patterns)

    build = subprocess.run(
        ["npx", "tsc", "-p", "tsconfig.test.json"],
        cwd=str(TS_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if build.returncode != 0:
        raise RuntimeError(
            f"tsc -p tsconfig.test.json failed:\n{build.stdout}\n{build.stderr}"
        )

    run = subprocess.run(
        ["node", str(TS_FILTER)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if run.returncode != 0:
        raise RuntimeError(
            "ts fuzz filter failed:\n"
            f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}"
        )
    lines = run.stdout.splitlines()

    if len(lines) != len(bit_patterns):
        raise RuntimeError(
            f"typescript produced {len(lines)} lines for {len(bit_patterns)} inputs"
        )
    return lines


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def main() -> int:
    bit_patterns = _sample_bits()
    py = [strictcli._format_float_canonical(_from_bits(b)) for b in bit_patterns]
    go = _go_format(bit_patterns)
    ts = _ts_format(bit_patterns)

    mismatches: list[str] = []
    for bits, ps, gs, ts_s in zip(bit_patterns, py, go, ts):
        x = _from_bits(bits)
        # 1. Byte-equality across all three implementations.
        if not (ps == gs == ts_s):
            mismatches.append(
                f"  bits={bits:016x} python={ps!r} go={gs!r} "
                f"typescript={ts_s!r} (byte mismatch)"
            )
            continue
        # 2. Round-trip: the shared canonical string must parse back to the
        #    identical double.
        back = float(ps)
        if struct.pack("<Q", bits) != struct.pack("<d", back):
            mismatches.append(
                f"  bits={bits:016x} scf={ps!r} did not round-trip"
            )

    if mismatches:
        print(
            f"float differential fuzz FAILED "
            f"({len(mismatches)}/{len(bit_patterns)} offending):"
        )
        for m in mismatches:
            print(m)
        return 1

    print(
        f"float differential fuzz passed: {len(bit_patterns)} doubles agree "
        f"byte-for-byte across python/go/typescript and round-trip "
        f"(seed={FIXED_SEED:#x})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
