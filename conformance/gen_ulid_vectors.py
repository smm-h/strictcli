#!/usr/bin/env python3
"""Generate conformance/ulid_vectors.json.

Cross-language vectors for the strict ULID profile of the process trace store
(docs/process-trace-store.md, "Identifiers"). Every vector is authored here --
nothing is derived from any implementation -- and all three implementations
replay the committed file in their own unit suites.

Two families:

* ``encode_vectors`` -- the layout. A vector carries a millisecond timestamp
  and the 80 random bits as 20 hex characters, plus the exact 26-character
  canonical encoding they must produce. This pins the bit layout (48-bit
  timestamp first, 80 random bits after) and the alphabet's digit order.
* ``parse_vectors`` -- the strict profile's acceptances and rejections. A
  vector carries the text and either ``valid: true`` with the millisecond the
  parse must yield, or ``valid: false`` with the ``reason`` (informative: an
  implementation reports no reason, it only rejects).

The profile rejects rather than repairs: lowercase is not case-normalized, a
130-bit value that overflows 128 bits is not truncated, and a character outside
the alphabet -- I, L, O, U included -- is not mapped to a lookalike.

Regeneration is byte-stable: the tables below are literal and ordered.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "ulid_vectors.json"

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(ms: int, random_hex: str) -> str:
    """The reference encoder, used only to fill in the expected strings."""
    value = (ms << 80) | int(random_hex, 16)
    return "".join(_CROCKFORD[(value >> shift) & 0x1F] for shift in range(125, -1, -5))


# (name, ms, 20 hex characters = 80 random bits)
ENCODE_INPUTS: list[tuple[str, int, str]] = [
    ("epoch zero, zero randomness", 0, "00000000000000000000"),
    ("epoch zero, one", 0, "00000000000000000001"),
    ("epoch zero, all random bits set", 0, "ffffffffffffffffffff"),
    ("one millisecond", 1, "00000000000000000000"),
    ("the documented instant", 1786681072913, "5a3c9e01f7b46d28c0a5"),
    ("the spec page's spawned_at instant", 1786594672913, "00000000000000000000"),
    ("a mid-range timestamp", 1234567890123, "0123456789abcdef0123"),
    ("timestamp with every low bit set", 0xFFFFFFFFFFF, "0f0f0f0f0f0f0f0f0f0f"),
    ("the maximum 48-bit timestamp", 0xFFFFFFFFFFFF, "ffffffffffffffffffff"),
    ("the maximum timestamp, zero randomness", 0xFFFFFFFFFFFF, "00000000000000000000"),
]

# (name, text, valid, ms_or_None, reason)
PARSE_INPUTS: list[tuple[str, str, bool, int | None, str]] = [
    (
        "canonical, all zeros",
        "00000000000000000000000000",
        True,
        0,
        "",
    ),
    (
        "canonical, the documented example",
        "01JZ8X4M6N7QK2WVBD3F5RTYAC",
        True,
        1751571910869,
        "",
    ),
    (
        "canonical, first character 7 is the largest legal one",
        "7ZZZZZZZZZZZZZZZZZZZZZZZZZ",
        True,
        281474976710655,
        "",
    ),
    (
        "canonical, every alphabet character in order",
        "0123456789ABCDEFGHJKMNPQRS",
        True,
        1171591994633,
        "",
    ),
    (
        "lowercase is rejected, not case-normalized",
        "01jz8x4m6n7qk2wvbd3f5rtyac",
        False,
        None,
        "lowercase",
    ),
    (
        "one lowercase character is enough to reject",
        "01JZ8X4M6N7QK2WVBD3F5RTYAc",
        False,
        None,
        "lowercase",
    ),
    (
        "overflow: first character 8 exceeds 128 bits",
        "80000000000000000000000000",
        False,
        None,
        "overflow",
    ),
    (
        "overflow: first character Z is the largest overflow",
        "ZZZZZZZZZZZZZZZZZZZZZZZZZZ",
        False,
        None,
        "overflow",
    ),
    (
        "alphabet: I is not in the alphabet",
        "0123456789ABCDEFGHIKMNPQRS",
        False,
        None,
        "alphabet",
    ),
    (
        "alphabet: L is not in the alphabet",
        "0123456789ABCDEFGHJLMNPQRS",
        False,
        None,
        "alphabet",
    ),
    (
        "alphabet: O is not in the alphabet",
        "0123456789ABCDEFGHJKMNOQRS",
        False,
        None,
        "alphabet",
    ),
    (
        "alphabet: U is not in the alphabet",
        "0123456789ABCDEFGHJKMNPQRU",
        False,
        None,
        "alphabet",
    ),
    (
        "alphabet: a hyphen is not in the alphabet",
        "0123456789ABCDEFGHJKMNPQR-",
        False,
        None,
        "alphabet",
    ),
    (
        "alphabet: a space is not in the alphabet",
        "0123456789ABCDEFGHJKMNPQR ",
        False,
        None,
        "alphabet",
    ),
    (
        "alphabet: a non-ASCII character is not in the alphabet",
        "0123456789ABCDEFGHJKMNPQRÉ",
        False,
        None,
        "alphabet",
    ),
    (
        "length: 25 characters is too short",
        "0123456789ABCDEFGHJKMNPQR",
        False,
        None,
        "length",
    ),
    (
        "length: 27 characters is too long",
        "0123456789ABCDEFGHJKMNPQRST",
        False,
        None,
        "length",
    ),
    ("length: the empty string", "", False, None, "length"),
    (
        "length: a 32-hex-character re-encoding is not the canonical form",
        "01jz8x4m6n7qk2wvbd3f5rtyac000000",
        False,
        None,
        "length",
    ),
]


def main() -> None:
    encode_vectors = [
        {
            "name": name,
            "ms": ms,
            "random_hex": random_hex,
            "ulid": _encode(ms, random_hex),
        }
        for name, ms, random_hex in ENCODE_INPUTS
    ]
    parse_vectors = []
    for name, text, valid, ms, reason in PARSE_INPUTS:
        vec: dict = {"name": name, "text": text, "valid": valid}
        if valid:
            vec["ms"] = ms
        else:
            vec["reason"] = reason
        parse_vectors.append(vec)

    # Every encode vector is also a parse vector by construction: the encoding
    # must round-trip to the millisecond it carries.
    seen: set[str] = set()
    for vec in encode_vectors + parse_vectors:
        if vec["name"] in seen:
            raise SystemExit(f"duplicate vector name: {vec['name']}")
        seen.add(vec["name"])

    doc = {
        "_comment": (
            "Generated by conformance/gen_ulid_vectors.py -- do not edit. "
            "Cross-language vectors for the strict ULID profile of the process "
            "trace store (docs/process-trace-store.md). Replayed by the "
            "Python, Go and TypeScript unit suites."
        ),
        "encode_vector_count": len(encode_vectors),
        "parse_vector_count": len(parse_vectors),
        "encode_vectors": encode_vectors,
        "parse_vectors": parse_vectors,
    }
    OUT_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(encode_vectors)} encode vectors and "
        f"{len(parse_vectors)} parse vectors to {OUT_PATH}"
    )


if __name__ == "__main__":
    main()
