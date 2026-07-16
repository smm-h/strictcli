"""Conformance validation tool for strictcli -- dogfoods the check system."""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from strictcli import App, ErrorReporter

TOOL_DIR = Path(__file__).resolve().parent
CONFORMANCE_DIR = TOOL_DIR.parent
PROJECT_ROOT = CONFORMANCE_DIR.parent


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


@app.error_check("conformance-parity")
def check_conformance_parity(ctx, reporter):
    return _run_script(reporter, "run.py", "--both")


def main():
    app.run()
