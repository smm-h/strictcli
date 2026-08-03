"""Tests for the built-in `effects-bypass` check provider."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

import strictcli


@dataclass
class SimpleContext:
    project_root: Path


CHECKS_TOML = 'app = "testapp"\n'


def _app(tmp_path, project_root=None):
    toml_file = tmp_path / "checks.toml"
    toml_file.write_text(CHECKS_TOML)
    app = strictcli.App(
        name="testapp", version="1.0.0", help="test app",
        checks_path=str(toml_file),
    )
    root = project_root if project_root is not None else tmp_path / "src"
    root.mkdir(parents=True, exist_ok=True)
    app.set_check_context(lambda: SimpleContext(project_root=root))
    return app, root


class TestRegistration:
    def test_registered_when_checks_are_enabled(self, tmp_path):
        app, _ = _app(tmp_path)
        r = app.test(["check", "--list"])
        assert r.exit_code == 0
        assert "effects-bypass" in r.stdout

    def test_metadata(self, tmp_path):
        app, _ = _app(tmp_path)
        r = app.test(["check", "--list", "--json"])
        entry = next(
            e for e in json.loads(r.stdout.strip()) if e["name"] == "effects-bypass"
        )
        assert entry["severity"] == "error"
        assert sorted(entry["tags"]) == ["effects", "quality"]

    def test_schema_metadata(self, tmp_path):
        app, _ = _app(tmp_path)
        app.test(["check", "--list"])  # materialize providers
        entry = app.dump_schema_dict()["checks"]["effects-bypass"]
        assert entry == {
            "tags": ["effects", "quality"],
            "severity": "error",
            "fast": True,
            "pure": True,
            "needs_network": False,
            "depends_on": [],
        }

    def test_not_registered_without_checks(self):
        app = strictcli.App(name="testapp", version="1.0.0", help="test app")
        assert "check" not in app._commands


class TestFindings:
    def _run(self, tmp_path, source):
        app, root = _app(tmp_path)
        (root / "handlers.py").write_text(source)
        return app.test(["check", "--name", "effects-bypass"])

    def test_clean_effects_handler_passes(self, tmp_path):
        r = self._run(tmp_path, '''
def deploy(ctx):
    ctx.effects.run(["git", "push"])
    ctx.effects.write("a.txt", "hi")
    ctx.effects.remove("stale")
''')
        assert r.exit_code == 0
        assert "no direct effect calls bypass ctx.effects" in r.stdout

    @pytest.mark.parametrize("bad,target", [
        ('subprocess.run(["git", "push"])', "subprocess.run"),
        ('subprocess.Popen(["daemon"])', "subprocess.Popen"),
        ('os.system("rm -rf /")', "os.system"),
        ('os.remove("x")', "os.remove"),
        ('os.makedirs("x")', "os.makedirs"),
        ('os.chmod("x", 0o755)', "os.chmod"),
        ('shutil.rmtree("x")', "shutil.rmtree"),
        ('Path("x").write_text("y")', "write_text"),
        ('requests.post("https://x.test")', "requests.post"),
        ('urllib.request.urlopen("https://x.test")', "urllib.request.urlopen"),
        ('open("x", "w")', "open"),
    ])
    def test_direct_calls_are_findings(self, tmp_path, bad, target):
        r = self._run(tmp_path, f'''
def deploy(ctx):
    ctx.effects.run(["true"])
    {bad}
''')
        assert r.exit_code == 1
        assert "1 direct effect call(s) bypassing ctx.effects" in r.stdout
        assert f"deploy calls {target} directly; route it through ctx.effects" in r.stdout

    def test_read_only_open_is_not_a_finding(self, tmp_path):
        r = self._run(tmp_path, '''
def deploy(ctx):
    ctx.effects.run(["true"])
    open("x")
    open("y", "r")
''')
        assert r.exit_code == 0

    def test_functions_that_never_opt_in_are_not_analysed(self, tmp_path):
        r = self._run(tmp_path, '''
import subprocess

def helper():
    subprocess.run(["anything"])
''')
        assert r.exit_code == 0

    def test_finding_names_file_and_line(self, tmp_path):
        r = self._run(tmp_path, '''
def deploy(ctx):
    ctx.effects.run(["true"])
    os.remove("x")
''')
        assert "handlers.py:4: deploy calls os.remove directly" in r.stdout

    def test_multiple_findings_are_all_reported(self, tmp_path):
        r = self._run(tmp_path, '''
def deploy(ctx):
    ctx.effects.run(["true"])
    os.remove("a")
    os.remove("b")
''')
        assert "2 direct effect call(s) bypassing ctx.effects" in r.stdout

    def test_ordinary_get_is_not_a_network_finding(self, tmp_path):
        r = self._run(tmp_path, '''
def deploy(ctx, mapping):
    ctx.effects.run(["true"])
    return mapping.get("k")
''')
        assert r.exit_code == 0

    def test_unparseable_file_is_not_a_finding(self, tmp_path):
        app, root = _app(tmp_path)
        (root / "broken.py").write_text("def (:\n")
        r = app.test(["check", "--name", "effects-bypass"])
        assert r.exit_code == 0

    def test_skipped_directories_are_not_scanned(self, tmp_path):
        app, root = _app(tmp_path)
        vendored = root / "node_modules"
        vendored.mkdir()
        (vendored / "handlers.py").write_text('''
def deploy(ctx):
    ctx.effects.run(["true"])
    os.remove("x")
''')
        assert app.test(["check", "--name", "effects-bypass"]).exit_code == 0

    def test_a_handler_that_never_mentions_effects_is_analysed(self, tmp_path):
        """Escape shape 1: opting in cannot be the trigger.

        §11 scopes the lint to calls REACHABLE FROM A REGISTERED COMMAND
        HANDLER. A handler that mentions the handle nowhere is the easiest
        possible bypass, and a lint that only looked at effects-using functions
        would wave it straight through.
        """
        r = self._run(tmp_path, '''
import os
import shutil
import subprocess

import strictcli

app = strictcli.App(name="a", version="1.0.0", help="a")


@app.command("deploy", help="deploy", effect="mutating")
def deploy(ctx):
    subprocess.run(["git", "push"])
    os.makedirs("build")
    shutil.rmtree("stale")
    return 0
''')
        assert r.exit_code == 1
        assert "3 direct effect call(s) bypassing ctx.effects" in r.stdout
        assert "deploy calls subprocess.run directly" in r.stdout
        assert "deploy calls os.makedirs directly" in r.stdout
        assert "deploy calls shutil.rmtree directly" in r.stdout

    def test_a_bypass_one_helper_call_away_is_analysed(self, tmp_path):
        """Escape shape 2: reachability, not the immediate body."""
        r = self._run(tmp_path, '''
import subprocess

import strictcli

app = strictcli.App(name="a", version="1.0.0", help="a")


def _publish(path):
    subprocess.run(["rsync", path, "remote:/srv"])


@app.command("deploy", help="deploy", effect="mutating")
def deploy(ctx):
    ctx.effects.run(["make", "build"])
    _publish("build")
    return 0
''')
        assert r.exit_code == 1
        assert "1 direct effect call(s) bypassing ctx.effects" in r.stdout
        assert "_publish calls subprocess.run directly" in r.stdout

    def test_reachability_is_transitive(self, tmp_path):
        r = self._run(tmp_path, '''
import os

import strictcli

app = strictcli.App(name="a", version="1.0.0", help="a")


def _inner():
    os.remove("x")


def _outer():
    _inner()


@app.command("deploy", help="deploy", effect="mutating")
def deploy(ctx):
    _outer()
    return 0
''')
        assert r.exit_code == 1
        assert "_inner calls os.remove directly" in r.stdout

    def test_a_handler_named_through_the_handler_keyword_is_a_root(self, tmp_path):
        r = self._run(tmp_path, '''
import subprocess


def _pt(ctx, name, args, globals):
    subprocess.run(["docker"] + args)
    return 0


spec = Passthrough(handler=_pt)
''')
        assert r.exit_code == 1
        assert "_pt calls subprocess.run directly" in r.stdout

    def test_a_local_alias_of_the_handle_is_not_a_bypass(self, tmp_path):
        r = self._run(tmp_path, '''
import strictcli

app = strictcli.App(name="a", version="1.0.0", help="a")


@app.command("deploy", help="deploy", effect="mutating")
def deploy(ctx):
    e = ctx.effects
    e.mkdir("build")
    e.remove("stale")
    return 0
''')
        assert r.exit_code == 0

    def test_an_unreachable_helper_is_still_not_analysed(self, tmp_path):
        """The scope is reachability, not "every function in the tree"."""
        r = self._run(tmp_path, '''
import subprocess

import strictcli

app = strictcli.App(name="a", version="1.0.0", help="a")


def _never_called():
    subprocess.run(["anything"])


@app.command("deploy", help="deploy", effect="mutating")
def deploy(ctx):
    ctx.effects.run(["make"])
    return 0
''')
        assert r.exit_code == 0

    def test_a_bypass_is_reported_once_per_call_site(self, tmp_path):
        r = self._run(tmp_path, '''
import os

import strictcli

app = strictcli.App(name="a", version="1.0.0", help="a")


@app.command("deploy", help="deploy", effect="mutating")
def deploy(ctx):
    ctx.effects.run(["make"])

    def _nested():
        os.remove("x")

    _nested()
    return 0
''')
        assert r.exit_code == 1
        assert "1 direct effect call(s) bypassing ctx.effects" in r.stdout

    def test_async_handlers_are_analysed(self, tmp_path):
        r = self._run(tmp_path, '''
async def deploy(ctx):
    ctx.effects.run(["true"])
    os.remove("x")
''')
        assert r.exit_code == 1


class TestObserveAllowlistBreadth:
    """§6.2's hazard, surfaced as a WARNING and never as an error.

    `proc_observe_allowlist=[["git"]]` makes EVERY git invocation an observe:
    it really executes under --dry-run, is never logged, and is legal in a
    read_only command. That may be exactly what the app wants -- the allowlist
    is a declared, source-visible choice that authorizes real execution in dry
    mode -- so the framework says so out loud instead of inventing a
    specificity rule.
    """

    def _app(self, tmp_path, allowlist):
        toml_file = tmp_path / "checks.toml"
        toml_file.write_text(CHECKS_TOML)
        app = strictcli.App(
            name="testapp", version="1.0.0", help="test app",
            checks_path=str(toml_file),
            proc_observe_allowlist=allowlist,
        )
        root = tmp_path / "src"
        root.mkdir(parents=True, exist_ok=True)
        app.set_check_context(lambda: SimpleContext(project_root=root))
        return app

    def test_metadata_is_warn_severity(self, tmp_path):
        app = self._app(tmp_path, [])
        r = app.test(["check", "--list", "--json"])
        entry = next(
            e for e in json.loads(r.stdout.strip())
            if e["name"] == "observe-allowlist-breadth"
        )
        assert entry["severity"] == "warn"
        assert sorted(entry["tags"]) == ["effects", "quality"]

    def test_a_single_token_prefix_warns(self, tmp_path):
        app = self._app(tmp_path, [["git"]])
        r = app.test(["check", "--name", "observe-allowlist-breadth"])
        assert "WARN" in r.stdout
        assert "EVERY 'git' invocation becomes an observe" in r.stdout
        assert "really executes under --dry-run" in r.stdout

    def test_a_warning_is_not_an_error(self, tmp_path):
        """--ignore-warnings clears it; an error-severity check could not."""
        app = self._app(tmp_path, [["git"]])
        assert app.test([
            "check", "--name", "observe-allowlist-breadth", "--ignore-warnings",
        ]).exit_code == 0

    def test_multi_token_prefixes_pass(self, tmp_path):
        app = self._app(tmp_path, [["git", "status"], ["gh", "release", "view"]])
        r = app.test(["check", "--name", "observe-allowlist-breadth"])
        assert r.exit_code == 0
        assert "no single-token proc_observe_allowlist prefixes" in r.stdout

    def test_an_empty_allowlist_passes(self, tmp_path):
        app = self._app(tmp_path, [])
        assert app.test(["check", "--name", "observe-allowlist-breadth"]).exit_code == 0
