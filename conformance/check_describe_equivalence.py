#!/usr/bin/env python3
"""Equivalence check: go/ast dumper vs legacy regex extraction.

Phase 8.5 builds `conformance/describe_go` -- a go/ast + go/parser program that
describes the strictcli Go API surface as JSON. This script proves the dumper
is a safe replacement input source for the brittle regex extraction currently
living in check_api_surface.py.

It runs the dumper (reading the CURRENT go/ source, not a snapshot) and compares
its extraction against check_api_surface.get_go_fields() run over the CURRENT go/
source, for the two categories the regex covers:

  1. Exported structs and their exported field names.
  2. Exported option-constructor functions.

The dumper is authoritative and is expected to find MORE (unexported struct
fields, unexported structs it intentionally omits, ConfigFieldOption
constructors the regex never matched). Those extras are reported, not failed.

FAIL (exit 1) only on regex-found-but-dumper-missed items:
  - an exported struct the regex found but the dumper omitted,
  - an exported field the regex found but the dumper's struct lacks,
  - an option function the regex found but the dumper's constructors lack.

Exit 0 when there are zero missed items.

This script is intentionally NOT registered in checks.toml -- Phase 9 decides
its final home once check_api_surface.py is rewired onto the dumper.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

CONFORMANCE_DIR = Path(__file__).resolve().parent
DESCRIBE_GO_DIR = CONFORMANCE_DIR / "describe_go"

sys.path.insert(0, str(CONFORMANCE_DIR))
import check_api_surface as cas  # noqa: E402  (path insert must precede import)


def run_dumper() -> dict:
    """Build+run the go/ast dumper over the current go/ source, return its JSON.

    Uses `go run` so the source is reparsed on every invocation -- the check
    always reflects the current working-tree state, never a cached snapshot.
    """
    proc = subprocess.run(
        ["go", "run", "."],
        cwd=DESCRIBE_GO_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"dumper failed (exit {proc.returncode}):\n{proc.stderr}"
        )
    return json.loads(proc.stdout)


def regex_extraction() -> tuple[dict[str, set[str]], set[str]]:
    """Return (regex_structs, regex_option_funcs) from the CURRENT go/ source."""
    source = cas.get_go_source()
    go_fields = cas.get_go_fields(source)
    option_funcs = go_fields.pop("_option_funcs", set())
    return go_fields, option_funcs


def main() -> int:
    dumper = run_dumper()
    regex_structs, regex_option_funcs = regex_extraction()

    # Index dumper output.
    dumper_structs: dict[str, dict[str, bool]] = {}
    for s in dumper["structs"]:
        dumper_structs[s["name"]] = {f["name"]: f["exported"] for f in s["fields"]}
    dumper_option_ctors: set[str] = {f["name"] for f in dumper["option_constructors"]}

    missed_structs: list[str] = []
    missed_fields: list[str] = []
    missed_option_funcs: list[str] = []

    out_of_scope_structs: list[str] = []  # regex unexported structs; dumper omits by design
    extra_fields: list[str] = []          # dumper fields the regex never found
    extra_option_funcs: list[str] = []    # dumper option ctors the regex never matched
    extra_structs: list[str] = []         # exported structs only the dumper found

    # --- Structs + fields ---------------------------------------------------
    for name, rfields in sorted(regex_structs.items()):
        exported_struct = name[:1].isupper()
        if name not in dumper_structs:
            if exported_struct:
                missed_structs.append(name)
            else:
                # Unexported struct with exported fields: outside the dumper's
                # declared scope (exported structs only). Informational.
                out_of_scope_structs.append(name)
            continue
        dfields = dumper_structs[name]
        for fld in sorted(rfields):
            if fld not in dfields:
                missed_fields.append(f"{name}.{fld}")

    for name, dfields in sorted(dumper_structs.items()):
        if name not in regex_structs:
            extra_structs.append(name)
        rfields = regex_structs.get(name, set())
        for fld, exported in sorted(dfields.items()):
            if fld not in rfields:
                kind = "exported" if exported else "unexported"
                extra_fields.append(f"{name}.{fld} ({kind})")

    # --- Option constructors ------------------------------------------------
    for fn in sorted(regex_option_funcs):
        if fn not in dumper_option_ctors:
            missed_option_funcs.append(fn)
    for fn in sorted(dumper_option_ctors):
        if fn not in regex_option_funcs:
            ot = next(
                (x["result_option_type"] for x in dumper["option_constructors"]
                 if x["name"] == fn),
                "?",
            )
            extra_option_funcs.append(f"{fn} -> {ot}")

    # --- Report -------------------------------------------------------------
    print("=" * 72)
    print("describe_go dumper vs regex extraction -- equivalence check")
    print("=" * 72)
    print(f"schema_version:            {dumper.get('schema_version')}")
    print(f"regex structs:             {len(regex_structs)}")
    print(f"dumper structs (exported): {len(dumper_structs)}")
    print(f"regex option funcs:        {len(regex_option_funcs)}")
    print(f"dumper option ctors:       {len(dumper_option_ctors)}")
    print()

    print(f"EXTRAS (dumper found more -- expected, informational):")
    print(f"  exported structs only in dumper:   {len(extra_structs)}")
    if extra_structs:
        for s in extra_structs:
            print(f"      + {s}")
    print(f"  regex unexported structs (out of dumper scope): {len(out_of_scope_structs)}")
    for s in out_of_scope_structs:
        print(f"      ~ {s}")
    print(f"  struct fields only in dumper:       {len(extra_fields)}")
    for f in extra_fields:
        print(f"      + {f}")
    print(f"  option constructors only in dumper: {len(extra_option_funcs)}")
    for f in extra_option_funcs:
        print(f"      + {f}")
    print()

    total_missed = len(missed_structs) + len(missed_fields) + len(missed_option_funcs)
    print(f"MISSED (regex found, dumper did NOT -- failures): {total_missed}")
    for s in missed_structs:
        print(f"      ! struct missing: {s}")
    for f in missed_fields:
        print(f"      ! field missing:  {f}")
    for fn in missed_option_funcs:
        print(f"      ! option func missing: {fn}")
    print("=" * 72)

    if total_missed:
        print("RESULT: FAIL -- dumper missed regex-found items (see above)")
        return 1
    print("RESULT: PASS -- dumper covers every regex-found struct field and "
          "option function (extras are the point)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
