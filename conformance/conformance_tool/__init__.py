"""Conformance validation tool for strictcli -- dogfoods the check system."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from strictcli import App, ErrorReporter

TOOL_DIR = Path(__file__).resolve().parent
CONFORMANCE_DIR = TOOL_DIR.parent
PROJECT_ROOT = CONFORMANCE_DIR.parent

# Canonical committed schema location. `conformance --dump-schema` derives
# project_id from pyproject.toml in the cwd and writes to cwd/.strictcli; the
# only cwd where the id resolves is CONFORMANCE_DIR (which holds pyproject.toml
# with name "strictcli-conformance"), so the reproducible schema lives here.
SCHEMA_PATH = CONFORMANCE_DIR / ".strictcli" / "schema.json"


@dataclass
class ConformanceContext:
    project_root: Path


app = App(
    name="conformance",
    version=(CONFORMANCE_DIR / "VERSION").read_text().strip(),
    help="Conformance validation tool for strictcli",
    checks_path=TOOL_DIR / ".strictcli" / "checks.toml",
)

app.set_check_context(lambda: ConformanceContext(project_root=PROJECT_ROOT))


def _run_script(reporter: ErrorReporter, script: str, *args: str):
    """Run a conformance script and mint an outcome via the reporter.

    Exit 0 mints a terminal pass; a non-zero exit mints error-severity problems
    (the script's stdout/stderr) and a terminal ``found`` outcome, which derives
    to FAIL. All conformance checks are error-severity, so a failure gates.
    """
    script_path = CONFORMANCE_DIR / script
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        cwd=str(CONFORMANCE_DIR),
    )
    if result.returncode == 0:
        return reporter.passed(f"{script} passed")
    problems = []
    if result.stdout.strip():
        problems.append(result.stdout.strip())
    if result.stderr.strip():
        problems.append(result.stderr.strip())
    if not problems:
        problems.append(f"exited with code {result.returncode} and no output")
    for text in problems:
        reporter.error(text)
    return reporter.found(f"{script} failed (exit code {result.returncode})")


@app.error_check("api-surface")
def check_api_surface(ctx, reporter):
    return _run_script(reporter, "check_api_surface.py")


@app.error_check("error-parity")
def check_error_parity(ctx, reporter):
    return _run_script(reporter, "check_error_parity.py")


@app.error_check("conformance-python")
def check_conformance_python(ctx, reporter):
    return _run_script(reporter, "run.py", "--target", "python")


@app.error_check("conformance-go")
def check_conformance_go(ctx, reporter):
    return _run_script(reporter, "run.py", "--target", "go")


@app.error_check("conformance-typescript")
def check_conformance_typescript(ctx, reporter):
    return _run_script(reporter, "run.py", "--target", "typescript")


@app.error_check("conformance-parity")
def check_conformance_parity(ctx, reporter):
    return _run_script(reporter, "run.py", "--both")


@app.error_check("schema-parity")
def check_schema_parity(ctx, reporter):
    return _run_script(reporter, "check_schema_parity.py")


@app.error_check("float-fuzz")
def check_float_fuzz(ctx, reporter):
    return _run_script(reporter, "check_float_fuzz.py")


@app.error_check("schema-freshness")
def check_schema_freshness(ctx, reporter):
    """Fail when the committed schema no longer matches the tool's own schema.

    This tool is a dev_node: it is never released, so rlsbl's release-time
    schema auto-regen never fires for it. The check gate (run by CI on every
    relevant push) is therefore the only freshness trigger. Comparison uses the
    CWD-free ``dump_schema_dict()`` accessor (id-free) against the parsed
    committed file with ``project_id`` excluded, so key order is irrelevant but
    list order (which is semantic) still counts.
    """
    current = app.dump_schema_dict()
    remediation = (
        f"Regenerate with `conformance --dump-schema` run from {CONFORMANCE_DIR}."
    )
    if not SCHEMA_PATH.exists():
        reporter.error(f"Committed schema {SCHEMA_PATH} is missing. {remediation}")
        return reporter.found("schema-freshness failed (schema file missing)")
    try:
        committed = json.loads(SCHEMA_PATH.read_text())
    except (OSError, ValueError) as exc:
        reporter.error(
            f"Committed schema {SCHEMA_PATH} is unreadable ({exc}). {remediation}"
        )
        return reporter.found("schema-freshness failed (schema file unreadable)")
    committed.pop("project_id", None)
    if committed != current:
        reporter.error(
            f"Committed schema {SCHEMA_PATH} is stale (does not match the tool's "
            f"current in-memory schema). {remediation}"
        )
        return reporter.found("schema-freshness failed (committed schema is stale)")
    return reporter.passed("committed schema matches the current in-memory schema")


def main():
    app.run()
