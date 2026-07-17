#!/usr/bin/env python3
"""Generate conformance/float_vectors.json -- cross-language SCF float vectors.

Each vector pairs an IEEE-754 double (encoded as its raw uint64 bit pattern in
hex) with the canonical strictcli float string (SCF) produced by the PYTHON
formatter, which is the reference implementation. The Python and Go float
formatter test suites both replay these vectors and assert byte-for-byte
agreement with the recorded SCF strings.

Contents:
  * The 16-value SCF battery (the agreed representative set).
  * An adversarial set:
      - nextafter straddlers on both sides of the 1e-6 and 1e21 notation
        thresholds (the fixed/scientific boundary);
      - subnormals: the minimum and maximum subnormal plus a few between;
      - 2**53-1, 2**53, 2**53+1 (the integer-exactness boundary);
      - powers of ten from 1e-300 to 1e300;
      - ~200 deterministic pseudorandom finite doubles from a FIXED seed.

No NaN or Inf is ever emitted (SCF rejects them upstream).

Regeneration is byte-stable: vectors are keyed by their uint64 bit pattern
(automatic dedup) and emitted in ascending bit-pattern order, and the random
draw uses the fixed seed below. Running this script twice yields identical
bytes.
"""

from __future__ import annotations

import json
import math
import random
import struct
from pathlib import Path

import strictcli

# Fixed seed for the pseudorandom draw. Recorded here so regeneration is
# byte-stable; changing it reshuffles (and thus rewrites) the random tail.
FIXED_SEED = 0x5CF_F10A7  # "SCF FLOAT"
NUM_RANDOM = 200

OUT_PATH = Path(__file__).resolve().parent / "float_vectors.json"


def _bits(x: float) -> int:
    """Return the raw uint64 bit pattern of a double."""
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def _from_bits(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def _battery() -> list[float]:
    """The agreed 16-value SCF battery."""
    return [
        1.0,
        -1.0,
        0.5,
        -0.0,
        0.0,
        100.0,
        1e15,
        1e16,
        1e20,
        1e21,
        1e-4,
        1e-5,
        1e-7,
        0.1,
        9007199254740992.0,  # 2**53
        1.5e300,
    ]


def _threshold_straddlers() -> list[float]:
    """nextafter values straddling the 1e-6 and 1e21 notation thresholds."""
    vals: list[float] = []
    for edge in (1e-6, 1e21):
        vals.append(math.nextafter(edge, -math.inf))  # just below
        vals.append(edge)  # exactly on the edge
        vals.append(math.nextafter(edge, math.inf))  # just above
        # Mirror on the negative side (sign must not perturb notation choice).
        vals.append(-edge)
        vals.append(math.nextafter(-edge, -math.inf))
        vals.append(math.nextafter(-edge, math.inf))
    return vals


def _subnormals() -> list[float]:
    """Minimum and maximum subnormal doubles plus a few between."""
    # Subnormal bit patterns have a zero exponent field (bits 62..52) and a
    # non-zero mantissa: 0x0000000000000001 .. 0x000FFFFFFFFFFFFF.
    patterns = [
        0x0000000000000001,  # min positive subnormal (5e-324)
        0x0000000000000002,
        0x00000000000FFFFF,
        0x0000000080000000,
        0x0008000000000000,
        0x000CCCCCCCCCCCCC,
        0x000FFFFFFFFFFFFF,  # max subnormal
    ]
    vals = [_from_bits(p) for p in patterns]
    # Include the negatives of the extremes too.
    vals.append(-_from_bits(0x0000000000000001))
    vals.append(-_from_bits(0x000FFFFFFFFFFFFF))
    return vals


def _integer_boundary() -> list[float]:
    """The 2**53 integer-exactness boundary (below/at/above)."""
    return [
        float(2**53 - 1),
        float(2**53),
        float(2**53 + 1),  # rounds to 2**53 (not exactly representable)
        float(2**53 + 2),  # first representable value above 2**53
    ]


def _powers_of_ten() -> list[float]:
    """Powers of ten from 1e-300 to 1e300 inclusive."""
    return [float(f"1e{e}") for e in range(-300, 301)]


def _random_doubles() -> list[float]:
    """~200 deterministic pseudorandom finite doubles from the fixed seed."""
    rng = random.Random(FIXED_SEED)
    out: list[float] = []
    while len(out) < NUM_RANDOM:
        bits = rng.getrandbits(64)
        x = _from_bits(bits)
        if math.isnan(x) or math.isinf(x):
            continue
        out.append(x)
    return out


def collect() -> dict[int, float]:
    """Collect all source values keyed by uint64 bit pattern (dedup)."""
    values: list[float] = []
    values += _battery()
    values += _threshold_straddlers()
    values += _subnormals()
    values += _integer_boundary()
    values += _powers_of_ten()
    values += _random_doubles()

    by_bits: dict[int, float] = {}
    for v in values:
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"refusing to emit non-finite value: {v!r}")
        by_bits[_bits(v)] = v
    return by_bits


def build() -> dict:
    by_bits = collect()
    vectors = []
    for bits in sorted(by_bits):
        x = by_bits[bits]
        scf = strictcli._format_float_canonical(x)
        vectors.append({"bits": f"{bits:016x}", "scf": scf})
    return {
        "_comment": (
            "Generated by conformance/gen_float_vectors.py -- do not edit. "
            "Expected SCF strings come from the Python reference formatter."
        ),
        "seed": f"{FIXED_SEED:#x}",
        "count": len(vectors),
        "vectors": vectors,
    }


def main() -> None:
    doc = build()
    text = json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
    OUT_PATH.write_text(text)
    print(f"wrote {doc['count']} vectors to {OUT_PATH}")


if __name__ == "__main__":
    main()
