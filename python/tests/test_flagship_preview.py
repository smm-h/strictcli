"""The three flagship preview shapes, asserted byte-for-byte."""

from flagship_app import build_app


class TestCompleteDataFlowPreview:
    """(a) A multi-step preview with forwarding and inline brands."""

    def test_preview_is_complete_and_byte_exact(self):
        app = build_app()
        r = app.test(["--dry-run", "release", "run", "1.2.3"])
        assert r.exit_code == 0
        assert r.stdout == (
            "DRY RUN — no changes were made. Would do:\n"
            "  1. run: make build VERSION=1.2.3\n"
            "  2. write: CHANGELOG.md («step 1 output»)\n"
            "  3. run: git tag v1.2.3\n"
            "  4. run: git push origin v1.2.3"
            " (granted: push — release engine owns remote refs)\n"
            "  5. net: POST https://api.github.test/repos/o/r/releases"
            " [unless resource 'gh-release:v1.2.3' already current]\n"
            "  6. run: gh release view «step 5 output»\n"
            "  7. spawn: notify --release v1.2.3\n"
        )
        assert r.stderr == ""

    def test_nothing_executed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        build_app().test(["--dry-run", "release", "run", "1.2.3"])
        assert not (tmp_path / "CHANGELOG.md").exists()

    def test_structured_log_carries_the_declared_metadata(self):
        app = build_app()
        app.test(["--dry-run", "release", "run", "1.2.3"])
        assert app.effect_log() == [
            {"seq": 1, "kind": "proc_mutate", "verb": "run",
             "detail": "make build VERSION=1.2.3", "recorded": True,
             "resource": "artifact:1.2.3"},
            {"seq": 2, "kind": "file_write", "verb": "write",
             "detail": "CHANGELOG.md («step 1 output»)", "recorded": True},
            {"seq": 3, "kind": "proc_mutate", "verb": "run",
             "detail": "git tag v1.2.3", "recorded": True,
             "resource": "tag:v1.2.3"},
            {"seq": 4, "kind": "proc_mutate", "verb": "run",
             "detail": "git push origin v1.2.3", "recorded": True,
             "resource": "remote:origin", "grant": "push"},
            {"seq": 5, "kind": "net_mutate", "verb": "net",
             "detail": "POST https://api.github.test/repos/o/r/releases",
             "recorded": True, "resource": "gh-release:v1.2.3",
             "skip_if_current": "gh-release:v1.2.3"},
            {"seq": 6, "kind": "proc_mutate", "verb": "run",
             "detail": "gh release view «step 5 output»", "recorded": True},
            {"seq": 7, "kind": "proc_spawn", "verb": "spawn",
             "detail": "notify --release v1.2.3", "recorded": True},
        ]

    def test_the_pre_mutation_observe_is_never_logged(self):
        app = build_app()
        r = app.test(["--dry-run", "release", "run", "1.2.3"])
        # The observe ran for real and its result was branched on, but a read
        # is not a change: it appears in neither the rendered nor the
        # structured log.
        assert "print(" not in r.stdout
        assert all(rec["verb"] != "run" or "print(" not in rec["detail"]
                   for rec in app.effect_log())


class TestHonestTruncation:
    """(b) Branching on an unsettled value stops the preview."""

    def test_truncation_is_byte_exact(self):
        app = build_app()
        r = app.test(["--dry-run", "release", "verify"])
        assert r.exit_code == 1
        assert r.stdout == (
            "DRY RUN — no changes were made. Would do:\n"
            "  1. run: git tag v9\n"
            "  2. run: git describe --tags\n"
        )
        assert r.stderr == (
            "error: dry-run preview ends at step 3: release.verify branched on "
            "unsettled value «step 2 output» — cannot preview past this point\n"
        )

    def test_the_unreachable_step_was_never_recorded(self):
        app = build_app()
        app.test(["--dry-run", "release", "verify"])
        assert len(app.effect_log()) == 2


class TestReadOnlyBareValues:
    """(c) A read_only command gets real values and an empty would-do body."""

    def test_bare_values_in_live_mode(self):
        r = build_app().test(["status"])
        assert r.exit_code == 0
        assert r.data == {"head": "a1b2c3d", "clean": True, "exit_code": 0}

    def test_bare_values_in_dry_mode_too(self):
        r = build_app().test(["--dry-run", "status"])
        assert r.exit_code == 0
        assert r.data == {"head": "a1b2c3d", "clean": True, "exit_code": 0}

    def test_would_do_body_is_empty(self):
        r = build_app().test(["--dry-run", "status"])
        assert r.stdout.endswith("DRY RUN — no changes were made. Would do:\n")

    def test_effect_log_is_empty(self):
        app = build_app()
        app.test(["--dry-run", "status"])
        assert app.effect_log() == []

    def test_quiet_hides_info_but_not_the_header(self):
        r = build_app().test(["--quiet", "--dry-run", "status"])
        assert "head: a1b2c3d" not in r.stdout
        assert "DRY RUN — no changes were made. Would do:" in r.stdout


class TestClassificationIsVisible:
    def test_schema_carries_the_regime_declarations(self):
        schema = build_app().dump_schema_dict()
        assert schema["commands"]["status"]["effect"] == "read_only"
        rel = schema["groups"]["release"]["commands"]
        assert rel["run"]["effect"] == "mutating"
        assert rel["run"]["grants"] == [{
            "name": "push",
            "reason": "release engine owns remote refs",
            "kind": "proc_mutate",
        }]
        assert rel["verify"]["effect"] == "mutating"
        assert schema["proc_observe_allowlist"]
