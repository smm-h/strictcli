"""Conformance validation tool for strictcli -- dogfoods the check system."""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from strictcli import App, CheckResult

TOOL_DIR = Path(__file__).resolve().parent
CONFORMANCE_DIR = TOOL_DIR.parent
PROJECT_ROOT = CONFORMANCE_DIR.parent


@dataclass
class ConformanceContext:
    project_root: Path


# chdir so App discovers conformance_tool/.strictcli/checks.toml
# instead of conformance/.strictcli/ (which would conflict with
# generated test scripts that also run from conformance/).
_prev_cwd = os.getcwd()
os.chdir(TOOL_DIR)

app = App(
    name="conformance",
    version=(CONFORMANCE_DIR / "VERSION").read_text().strip(),
    help="Conformance validation tool for strictcli",
)

os.chdir(_prev_cwd)

app.set_check_context(lambda: ConformanceContext(project_root=PROJECT_ROOT))


def _run_script(script: str, *args: str) -> CheckResult:
    """Run a conformance script and return a CheckResult."""
    script_path = CONFORMANCE_DIR / script
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        cwd=str(CONFORMANCE_DIR),
    )
    if result.returncode == 0:
        return CheckResult(status="pass", message=f"{script} passed")
    details = []
    if result.stdout.strip():
        details.append(result.stdout.strip())
    if result.stderr.strip():
        details.append(result.stderr.strip())
    return CheckResult(
        status="fail",
        message=f"{script} failed (exit code {result.returncode})",
        details=details,
    )


@app.check("api-surface")
def check_api_surface(ctx):
    return _run_script("check_api_surface.py")


@app.check("error-parity")
def check_error_parity(ctx):
    return _run_script("check_error_parity.py")


@app.check("conformance-python")
def check_conformance_python(ctx):
    return _run_script("run.py", "--target", "python")


@app.check("conformance-go")
def check_conformance_go(ctx):
    return _run_script("run.py", "--target", "go")


@app.check("conformance-parity")
def check_conformance_parity(ctx):
    return _run_script("run.py", "--both")


def main():
    app.run()
