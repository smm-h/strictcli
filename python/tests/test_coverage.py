"""Tests for the cli-test-coverage mechanism.

Verifies that:
- test_coverage=True enables recording of command hits
- test() and call() both record to per-process shard files
- The cli-test-coverage check merges shards, compares against the command
  surface, and FAILs listing uncovered commands
- Full coverage produces a PASS
- Empty/stale manifest is a hard error
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

import strictcli


@dataclass
class SimpleCtx:
    project_root: Path


def _make_app(tmp_path):
    """Build a 3-command app with test_coverage enabled, rooted in tmp_path."""
    os.chdir(tmp_path)
    app = strictcli.App(
        name="coverapp", version="1.0.0", help="coverage test app",
        test_coverage=True,
    )

    @app.command(name="deploy", help="deploy the app")
    def cmd_deploy(ctx, **_kw):
        pass

    @app.command(name="status", help="show status")
    def cmd_status(ctx, **_kw):
        pass

    @app.command(name="build", help="build the app")
    def cmd_build(ctx, **_kw):
        pass

    app.set_check_context(lambda: SimpleCtx(project_root=tmp_path))
    return app


def _make_grouped_app(tmp_path):
    """Build an app with grouped commands for dotted-path coverage."""
    os.chdir(tmp_path)
    app = strictcli.App(
        name="grpapp", version="1.0.0", help="grouped coverage test",
        test_coverage=True,
    )

    grp = app.group("infra", help="infrastructure commands")

    @grp.command(name="deploy", help="deploy infra")
    def cmd_infra_deploy(ctx, **_kw):
        pass

    @grp.command(name="teardown", help="tear down infra")
    def cmd_infra_teardown(ctx, **_kw):
        pass

    @app.command(name="status", help="show status")
    def cmd_status(ctx, **_kw):
        pass

    app.set_check_context(lambda: SimpleCtx(project_root=tmp_path))
    return app


class TestCoverageRecording:
    def test_test_creates_shard_file(self, tmp_path):
        app = _make_app(tmp_path)
        app.test(["deploy"])

        coverage_dir = tmp_path / ".strictcli" / "coverage"
        assert coverage_dir.is_dir()
        shards = list(coverage_dir.glob("*.jsonl"))
        assert len(shards) >= 1

        entries = []
        for shard in shards:
            for line in shard.read_text().strip().splitlines():
                entries.append(json.loads(line))

        commands = {e["command"] for e in entries}
        assert "deploy" in commands

    def test_call_records_coverage(self, tmp_path):
        app = _make_app(tmp_path)
        app.call("status")

        coverage_dir = tmp_path / ".strictcli" / "coverage"
        shards = list(coverage_dir.glob("*.jsonl"))
        assert len(shards) >= 1

        entries = []
        for shard in shards:
            for line in shard.read_text().strip().splitlines():
                entries.append(json.loads(line))

        commands = {e["command"] for e in entries}
        assert "status" in commands

    def test_multiple_calls_accumulate(self, tmp_path):
        app = _make_app(tmp_path)
        app.test(["deploy"])
        app.test(["status"])
        app.call("build")

        coverage_dir = tmp_path / ".strictcli" / "coverage"
        entries = []
        for shard in coverage_dir.glob("*.jsonl"):
            for line in shard.read_text().strip().splitlines():
                entries.append(json.loads(line))

        commands = {e["command"] for e in entries}
        assert commands == {"deploy", "status", "build"}

    def test_grouped_command_dotted_path(self, tmp_path):
        app = _make_grouped_app(tmp_path)
        app.test(["infra", "deploy"])

        coverage_dir = tmp_path / ".strictcli" / "coverage"
        entries = []
        for shard in coverage_dir.glob("*.jsonl"):
            for line in shard.read_text().strip().splitlines():
                entries.append(json.loads(line))

        commands = {e["command"] for e in entries}
        assert "infra.deploy" in commands


class TestCoverageCheck:
    def test_partial_coverage_fails_naming_uncovered(self, tmp_path):
        """One command tested out of 3 -> check FAILs naming the untested two."""
        app = _make_app(tmp_path)
        # Only test one command
        app.test(["deploy"])

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "fail"
        # Should list the two uncovered commands
        problem_texts = [p.text for p in cov_result.problems]
        uncovered_cmds = set()
        for text in problem_texts:
            if "no test coverage for command:" in text:
                cmd = text.split("no test coverage for command: ")[1]
                uncovered_cmds.add(cmd)
        assert "status" in uncovered_cmds
        assert "build" in uncovered_cmds
        assert "deploy" not in uncovered_cmds

    def test_full_coverage_passes(self, tmp_path):
        """All 3 commands tested -> check PASSes."""
        app = _make_app(tmp_path)
        app.test(["deploy"])
        app.test(["status"])
        app.test(["build"])

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "pass"

    def test_empty_coverage_fails_naming_all(self, tmp_path):
        """No shards and no manifest -> deterministic FAIL naming every command.

        The verdict is derived from committed state (manifest union shards), so an
        empty everything state fails by listing every uncovered command rather than
        the old machine-dependent "no coverage data" error.
        """
        app = _make_app(tmp_path)
        # Don't run any test() or call() -- no shards, no manifest

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "fail"
        problem_texts = [p.text for p in cov_result.problems]
        uncovered = {
            t.split("no test coverage for command: ")[1]
            for t in problem_texts
            if "no test coverage for command:" in t
        }
        assert uncovered == {"build", "deploy", "status"}

    def test_manifest_written_on_check(self, tmp_path):
        """The check writes .strictcli/test-coverage.json with covered commands."""
        app = _make_app(tmp_path)
        app.test(["deploy"])
        app.test(["status"])
        app.test(["build"])

        app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )

        manifest_path = tmp_path / ".strictcli" / "test-coverage.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())
        assert sorted(manifest) == ["build", "deploy", "status"]

    def test_grouped_commands_coverage(self, tmp_path):
        """Grouped commands use dotted paths in coverage tracking."""
        app = _make_grouped_app(tmp_path)
        # Test all commands
        app.test(["infra", "deploy"])
        app.test(["infra", "teardown"])
        app.test(["status"])

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "pass"

    def test_grouped_partial_coverage_fails(self, tmp_path):
        """Missing a grouped command -> check FAILs naming it."""
        app = _make_grouped_app(tmp_path)
        app.test(["infra", "deploy"])
        app.test(["status"])
        # infra.teardown is not tested

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "fail"
        problem_texts = [p.text for p in cov_result.problems]
        assert any("infra.teardown" in t for t in problem_texts)


class TestCoverageChdirSafety:
    def test_record_anchored_to_construction_cwd(self, tmp_path):
        """test() records into the construction-time coverage dir, not the cwd
        that a test happened to chdir into."""
        app = _make_app(tmp_path)  # constructs with cwd == tmp_path
        other = tmp_path / "elsewhere"
        other.mkdir()
        os.chdir(other)

        app.test(["deploy"])

        construction_shards = list(
            (tmp_path / ".strictcli" / "coverage").glob("*.jsonl")
        )
        assert construction_shards, "shard must land under the construction cwd"
        foreign = other / ".strictcli" / "coverage"
        assert not foreign.exists(), "must not record into the chdir'd cwd"


class TestManifestUnionVerdict:
    def test_manifest_present_shards_absent_passes(self, tmp_path):
        """Committed manifest covering every command -> deterministic PASS even
        with no shard files (the machine never ran the suite)."""
        app = _make_app(tmp_path)
        manifest_path = tmp_path / ".strictcli" / "test-coverage.json"
        manifest_path.write_text(
            json.dumps(["build", "deploy", "status"], indent=2) + "\n"
        )

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "pass"

    def test_check_from_foreign_cwd_reads_app_state(self, tmp_path):
        """The check evaluated from a foreign cwd reads the app's own repo state
        (anchored manifest), not the foreign directory."""
        app = _make_app(tmp_path)
        manifest_path = tmp_path / ".strictcli" / "test-coverage.json"
        manifest_path.write_text(
            json.dumps(["build", "deploy", "status"], indent=2) + "\n"
        )
        other = tmp_path / "foreign"
        other.mkdir()
        os.chdir(other)

        results, _, code = app.run_checks(
            SimpleCtx(project_root=tmp_path),
            run_all=True,
        )
        cov_result = next(r for r in results if r.name == "cli-test-coverage")
        assert cov_result.status == "pass"

    def test_manifest_union_is_monotonic(self, tmp_path):
        """A run recording only a subset keeps prior commands covered (union)."""
        app = _make_app(tmp_path)
        manifest_path = tmp_path / ".strictcli" / "test-coverage.json"
        manifest_path.write_text(
            json.dumps(["build", "deploy", "status"], indent=2) + "\n"
        )
        app.test(["deploy"])  # only one recorded this run

        app.run_checks(SimpleCtx(project_root=tmp_path), run_all=True)

        manifest = json.loads(manifest_path.read_text())
        assert sorted(manifest) == ["build", "deploy", "status"]

    def test_manifest_not_rewritten_when_unchanged(self, tmp_path):
        """A pure check must not dirty a byte-identical manifest."""
        app = _make_app(tmp_path)
        app.test(["deploy"])
        app.test(["status"])
        app.test(["build"])
        app.run_checks(SimpleCtx(project_root=tmp_path), run_all=True)

        manifest_path = tmp_path / ".strictcli" / "test-coverage.json"
        content1 = manifest_path.read_text()
        mtime1 = manifest_path.stat().st_mtime_ns

        app.run_checks(SimpleCtx(project_root=tmp_path), run_all=True)

        assert manifest_path.read_text() == content1
        assert manifest_path.stat().st_mtime_ns == mtime1


class TestCoverageDisabled:
    def test_no_recording_when_disabled(self, tmp_path):
        """test_coverage=False (default) produces no shard files."""
        os.chdir(tmp_path)
        app = strictcli.App(
            name="nocover", version="1.0.0", help="no coverage",
        )

        @app.command(name="greet", help="say hello")
        def cmd_greet(ctx, **_kw):
            pass

        app.test(["greet"])

        coverage_dir = tmp_path / ".strictcli" / "coverage"
        assert not coverage_dir.exists()
