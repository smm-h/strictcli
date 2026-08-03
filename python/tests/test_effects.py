"""Tests for the ctx.effects handle, dry mode, and the Unsettled carriers."""

import json
import os
import sys

import pytest

import strictcli as sc

PY = sys.executable


def _app(**kwargs):
    return sc.App(name="app", version="1.0.0", help="app", **kwargs)


class TestHandleAvailability:
    """The seal is armed at every ctx-construction site that dispatches."""

    def test_available_in_test_dispatch(self):
        app = _app()
        seen = {}

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            seen["effects"] = ctx.effects
            return 0

        assert app.test(["run"]).exit_code == 0
        assert isinstance(seen["effects"], sc._Effects)

    def test_available_in_invoke_dispatch(self):
        app = _app()
        seen = {}

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            seen["effects"] = ctx.effects
            return 0

        app.call("run")
        assert isinstance(seen["effects"], sc._Effects)

    def test_available_in_passthrough_invoke_dispatch(self):
        app = _app()
        seen = {}

        def _pt(ctx, name, args, globals):
            seen["effects"] = ctx.effects
            return 0

        @app.command("exec", help="exec", effect="read_only",
                     passthrough=sc.Passthrough(handler=_pt))
        def _e(ctx, **kw):
            return 0

        app.call("exec", _args=["x"])
        assert isinstance(seen["effects"], sc._Effects)

    def test_available_in_run_dispatch(self, monkeypatch, tmp_path):
        app = _app()
        seen = {}

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            seen["effects"] = ctx.effects
            seen["dry_run"] = ctx.dry_run
            return 0

        monkeypatch.setattr(sys, "argv", ["app", "--dry-run", "run"])
        with pytest.raises(SystemExit) as exc:
            app.run()
        assert exc.value.code == 0
        assert isinstance(seen["effects"], sc._Effects)
        assert seen["dry_run"] is True

    def test_effects_unavailable_on_a_bare_context(self):
        ctx = sc.Context()
        with pytest.raises(RuntimeError, match="outside a command dispatch"):
            ctx.effects

    def test_dry_run_is_not_reachable_programmatically(self):
        """call()/_invoke bypass argv entirely, so the run is never dry."""
        app = _app()
        seen = {}

        @app.command("run", help="run", effect="mutating")
        def _run(ctx):
            seen["dry_run"] = ctx.dry_run
            return 0

        app.call("run")
        assert seen["dry_run"] is False


class TestWouldDoLog:
    def test_read_only_dry_run_is_header_with_empty_body(self):
        app = _app()

        @app.command("look", help="look", effect="read_only")
        def _look(ctx):
            ctx.info("listing")
            return 0

        r = app.test(["--dry-run", "look"])
        assert r.exit_code == 0
        assert r.stdout == "listing\nDRY RUN — no changes were made. Would do:\n"

    def test_log_renders_every_verb(self):
        app = _app()

        @app.command("all", help="all", effect="mutating")
        def _all(ctx):
            ctx.effects.run(["git", "tag", "v1"])
            ctx.effects.spawn(["daemon", "--start"])
            ctx.effects.write("a.txt", "hello")
            ctx.effects.mkdir("build")
            ctx.effects.remove("stale")
            ctx.effects.rename("old", "new")
            ctx.effects.chmod("bin/x", 0o755)
            ctx.effects.http("POST", "https://example.test/x")
            return 0

        r = app.test(["--dry-run", "all"])
        assert r.stdout == (
            "DRY RUN — no changes were made. Would do:\n"
            "  1. run: git tag v1\n"
            "  2. spawn: daemon --start\n"
            "  3. write: a.txt (5 bytes)\n"
            "  4. mkdir: build\n"
            "  5. remove: stale\n"
            "  6. rename: old -> new\n"
            "  7. chmod: bin/x 0755\n"
            "  8. net: POST https://example.test/x\n"
        )

    def test_grant_suffix_precedes_conditional_suffix(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating",
                     grants=[sc.Grant("push", "engine owns remote refs", sc.PROC_MUTATE)])
        def _rel(ctx):
            ctx.effects.run(["git", "push"], grant="push",
                            resource="remote:origin/main",
                            skip_if_current="remote:origin/main")
            return 0

        r = app.test(["--dry-run", "rel"])
        assert r.stdout.splitlines()[1] == (
            "  1. run: git push (granted: push — engine owns remote refs)"
            " [unless resource 'remote:origin/main' already current]"
        )

    def test_log_is_never_suppressed_by_quiet(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.info("chatter")
            ctx.effects.mkdir("build")
            return 0

        r = app.test(["--quiet", "--dry-run", "rel"])
        assert "chatter" not in r.stdout
        assert "DRY RUN — no changes were made. Would do:" in r.stdout
        assert "  1. mkdir: build" in r.stdout

    def test_log_follows_structured_handler_output(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            return sc.outcome(data={"planned": True})

        r = app.test(["--dry-run", "rel"])
        lines = r.stdout.splitlines()
        assert lines[0] == '{"planned":true}'
        assert lines[1] == "DRY RUN — no changes were made. Would do:"

    def test_dry_run_exits_with_the_handler_exit_code(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            return 3

        assert app.test(["--dry-run", "rel"]).exit_code == 3

    def test_no_log_outside_dry_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            return 0

        r = app.test(["rel"])
        assert "DRY RUN" not in r.stdout
        assert (tmp_path / "build").is_dir()


class TestTruncation:
    def test_branching_on_a_carrier_truncates(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run(["git", "tag", "v1"])
            out = ctx.effects.run(["git", "describe"])
            if out.exit_code == 0:
                ctx.effects.run(["echo", "unreachable"])
            return 0

        r = app.test(["--dry-run", "rel"])
        assert r.exit_code == 1
        assert r.stdout == (
            "DRY RUN — no changes were made. Would do:\n"
            "  1. run: git tag v1\n"
            "  2. run: git describe\n"
        )
        assert r.stderr == (
            "error: dry-run preview ends at step 3: rel branched on unsettled "
            "value «step 2 output» — cannot preview past this point\n"
        )

    def test_truncation_names_the_dotted_command_path(self):
        app = _app()
        grp = app.group("release", help="release")

        @grp.command("run", help="run", effect="mutating")
        def _run(ctx):
            carrier = ctx.effects.mkdir("build")
            if carrier:
                pass
            return 0

        r = app.test(["--dry-run", "release", "run"])
        assert "ends at step 2: release.run branched on unsettled value" in r.stderr
        assert "«step 1 output»" in r.stderr

    def test_stale_observe_brand_renders_in_the_truncation(self):
        app = _app(proc_observe_allowlist=[["git", "status"]])

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            status = ctx.effects.run(["git", "status", "--short"])
            if status.stdout:
                pass
            return 0

        r = app.test(["--dry-run", "rel"])
        assert r.exit_code == 1
        assert "«stale: git status --short»" in r.stderr

    def test_handler_cannot_swallow_the_truncation(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            carrier = ctx.effects.mkdir("build")
            try:
                bool(carrier)
            except Exception:
                ctx.info("swallowed")
            return 0

        r = app.test(["--dry-run", "rel"])
        assert r.exit_code == 1
        assert "swallowed" not in r.stdout


class TestCarriers:
    def _carrier(self, app):
        holder = {}

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            holder["c"] = ctx.effects.run(["git", "tag", "v1"])
            holder["void"] = ctx.effects.mkdir("build")
            holder["spawned"] = ctx.effects.spawn(["daemon"])
            return 0

        app.test(["--dry-run", "rel"])
        return holder

    def test_repr_is_the_single_non_poisoned_dunder(self):
        h = self._carrier(_app())
        assert repr(h["c"]) == "Unsettled(«step 1 output»)"

    def test_isinstance_still_works(self):
        h = self._carrier(_app())
        assert isinstance(h["c"], sc.Unsettled)

    @pytest.mark.parametrize("op", [
        lambda c: bool(c),
        lambda c: c == 1,
        lambda c: c != 1,
        lambda c: c < 1,
        lambda c: c <= 1,
        lambda c: c > 1,
        lambda c: c >= 1,
        lambda c: hash(c),
        lambda c: len(c),
        lambda c: list(c),
        lambda c: 1 in c,
        lambda c: c[0],
        lambda c: c.stdout,
        lambda c: int(c),
        lambda c: float(c),
        lambda c: "x"[c],
        lambda c: str(c),
        lambda c: format(c),
        lambda c: bytes(c),
        lambda c: c + "x",
        lambda c: "x" + c,
        lambda c: c % "x",
        lambda c: c.__rmod__("x"),
        lambda c: c(),
    ])
    def test_every_poisoned_dunder_raises(self, op):
        h = self._carrier(_app())
        with pytest.raises(BaseException) as exc:
            op(h["c"])
        assert "dry-run preview ends at step" in str(exc.value)

    def test_f_string_interpolation_is_extraction(self):
        h = self._carrier(_app())
        with pytest.raises(BaseException, match="dry-run preview ends"):
            f"{h['c']}"

    def test_void_carrier_is_never_forwardable(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            void = ctx.effects.mkdir("build")
            ctx.effects.write(void, "data")
            return 0

        with pytest.raises(ValueError) as exc:
            app.test(["--dry-run", "rel"])
        assert str(exc.value) == (
            'command "rel": effects.write parameter \'path\' does not accept '
            "an unsettled value"
        )

    def test_spawn_carrier_is_never_forwardable(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            spawned = ctx.effects.spawn(["daemon"])
            ctx.effects.run(["echo", spawned])
            return 0

        with pytest.raises(ValueError, match=r"parameter 'argv\[1\]' does not accept"):
            app.test(["--dry-run", "rel"])

    def test_forwarding_does_not_consume_the_carrier(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            c = ctx.effects.run(["make", "build"])
            ctx.effects.run(["upload", c])
            ctx.effects.run(["archive", c])
            return 0

        r = app.test(["--dry-run", "rel"])
        assert "  2. run: upload «step 1 output»" in r.stdout
        assert "  3. run: archive «step 1 output»" in r.stdout

    @pytest.mark.parametrize("param", ["cwd", "env"])
    def test_carrier_rejected_by_non_accepting_parameters(self, param):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            c = ctx.effects.run(["make"])
            kwargs = {param: c if param == "cwd" else {"K": "v"}}
            if param == "env":
                kwargs = {"env": {"K": c}}
            ctx.effects.run(["echo"], **kwargs)
            return 0

        with pytest.raises(ValueError) as exc:
            app.test(["--dry-run", "rel"])
        assert f"parameter '{param}' does not accept an unsettled value" in str(exc.value)

    def test_carrier_rejected_by_mode(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            c = ctx.effects.run(["make"])
            ctx.effects.chmod("x", c)
            return 0

        with pytest.raises(ValueError, match=r"parameter 'mode' does not accept"):
            app.test(["--dry-run", "rel"])

    def test_carrier_rejected_by_resource(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            c = ctx.effects.run(["make"])
            ctx.effects.mkdir("x", resource=c)
            return 0

        with pytest.raises(ValueError, match=r"parameter 'resource' does not accept"):
            app.test(["--dry-run", "rel"])


class TestDeclaredSignatures:
    """The surface declares the SETTLED types only.

    A declared ``Completed | Unsettled`` would oblige a type-checked handler to
    narrow before touching ``.stdout``, and narrowing on unsettledness is
    mode-branching -- exactly what the truncation mechanism exists to make
    impossible to do silently. The runtime still hands back an ``Unsettled``
    carrier in dry mode; the annotation simply does not advertise a union that
    callers must not branch on.
    """

    # (method, declared return annotation)
    RETURNS = [
        ("run", "Completed"),
        ("spawn", "Spawned"),
        ("write", "None"),
        ("mkdir", "None"),
        ("remove", "None"),
        ("rename", "None"),
        ("chmod", "None"),
        ("http", "Response"),
    ]

    # (method, parameter, declared annotation) for the six carrier-accepting
    # positions. Everything else is deliberately unannotated.
    PARAMS = [
        ("run", "argv", "Sequence[str | Completed | Response]"),
        ("spawn", "argv", "Sequence[str | Completed | Response]"),
        ("write", "path", "str | Completed | Response"),
        ("write", "content", "str | bytes | Completed | Response"),
        ("mkdir", "path", "str | Completed | Response"),
        ("remove", "path", "str | Completed | Response"),
        ("rename", "src", "str | Completed | Response"),
        ("rename", "dst", "str | Completed | Response"),
        ("chmod", "path", "str | Completed | Response"),
        ("http", "url", "str | Completed | Response"),
    ]

    @pytest.mark.parametrize("method,expected", RETURNS)
    def test_declared_return_is_settled_only(self, method, expected):
        ann = getattr(sc._Effects, method).__annotations__
        assert ann["return"] == expected

    def test_spawned_wait_declares_completed(self):
        assert sc.Spawned.wait.__annotations__["return"] == "Completed"

    @pytest.mark.parametrize("method,param,expected", PARAMS)
    def test_carrier_accepting_parameter_annotations(self, method, param, expected):
        ann = getattr(sc._Effects, method).__annotations__
        assert ann[param] == expected

    @pytest.mark.parametrize("method,_expected", RETURNS)
    def test_no_declared_annotation_mentions_unsettled(self, method, _expected):
        ann = getattr(sc._Effects, method).__annotations__
        for name, text in ann.items():
            assert "Unsettled" not in text, f"{method}.{name} declares Unsettled"

    def test_no_narrowing_predicate_exists(self):
        """No is_unsettled(): branching on unsettledness is mode-branching."""
        assert not hasattr(sc.Unsettled, "is_unsettled")
        assert not hasattr(sc._Effects, "is_unsettled")
        assert not any(
            "unsettled" in name.lower() for name in sc.__all__
            if name != "Unsettled"
        )

    def test_runtime_still_returns_unsettled_despite_the_declaration(self):
        """The declaration is settled-only; the runtime value is not.

        This is the whole point of the settled-only ruling: the static type
        stays out of the way while the runtime seal keeps its teeth.
        """
        holder = {}
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            holder["run"] = ctx.effects.run(["git", "tag", "v1"])
            holder["spawn"] = ctx.effects.spawn(["daemon"])
            holder["write"] = ctx.effects.write("f", "x")
            holder["mkdir"] = ctx.effects.mkdir("d")
            holder["remove"] = ctx.effects.remove("d")
            holder["rename"] = ctx.effects.rename("a", "b")
            holder["chmod"] = ctx.effects.chmod("f", 0o755)
            holder["http"] = ctx.effects.http("POST", "https://x/y")
            return 0

        app.test(["--dry-run", "rel"])
        assert set(holder) == {
            "run", "spawn", "write", "mkdir", "remove", "rename", "chmod",
            "http",
        }
        for name, value in holder.items():
            assert isinstance(value, sc.Unsettled), name

    def test_live_mode_still_returns_the_real_settled_result(self, tmp_path,
                                                             monkeypatch):
        monkeypatch.chdir(tmp_path)
        holder = {}
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            holder["run"] = ctx.effects.run([PY, "-c", "print('hi')"])
            holder["mkdir"] = ctx.effects.mkdir("d")
            return 0

        app.test(["rel"])
        assert isinstance(holder["run"], sc.Completed)
        assert holder["run"].stdout == "hi"
        assert holder["mkdir"] is None


class TestObserves:
    def test_observe_returns_a_real_value_in_dry_mode(self):
        app = _app(proc_observe_allowlist=[[PY, "-c"]])

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            out = ctx.effects.run([PY, "-c", "print('hello')"])
            ctx.effects.run(["echo", out])
            return 0

        r = app.test(["--dry-run", "rel"])
        assert r.stdout == (
            "DRY RUN — no changes were made. Would do:\n"
            "  1. run: echo hello\n"
        )

    def test_observe_is_never_logged(self):
        app = _app(proc_observe_allowlist=[[PY]])

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        r = app.test(["--dry-run", "rel"])
        assert r.stdout == "DRY RUN — no changes were made. Would do:\n"
        assert app.effect_log() == []

    def test_post_mutation_observe_is_unsettled(self):
        app = _app(proc_observe_allowlist=[[PY]])
        holder = {}

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            holder["o"] = ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["--dry-run", "rel"])
        assert isinstance(holder["o"], sc.Unsettled)
        assert repr(holder["o"]).startswith("Unsettled(«stale: ")

    def test_observe_is_allowed_in_a_read_only_command(self):
        app = _app(proc_observe_allowlist=[[PY, "-c"]])

        @app.command("look", help="look", effect="read_only")
        def _look(ctx):
            out = ctx.effects.run([PY, "-c", "print('ok')"])
            return sc.outcome(data={"stdout": out.stdout})

        r = app.test(["look"])
        assert r.data == {"stdout": "ok"}

    def test_prefix_matching_is_element_wise_string_equality(self):
        app = _app(proc_observe_allowlist=[["git", "rev-parse"]])

        @app.command("rel", help="rel", effect="read_only")
        def _rel(ctx):
            ctx.effects.run(["git", "rev-parse-hard"])
            return 0

        with pytest.raises(ValueError, match="not on the app's proc_observe_allowlist"):
            app.test(["rel"])

    def test_grant_on_an_observe_is_a_call_time_error(self):
        app = _app(proc_observe_allowlist=[["git", "status"]])

        @app.command("rel", help="rel", effect="mutating",
                     grants=[sc.Grant("g", "why", sc.PROC_MUTATE)])
        def _rel(ctx):
            ctx.effects.run(["git", "status"], grant="g")
            return 0

        with pytest.raises(ValueError) as exc:
            app.test(["rel"])
        assert str(exc.value) == (
            'command "rel": grant \'g\' cannot be used on an observe '
            "(an allowlisted effects.run changes nothing)"
        )

    def test_allowlist_is_emitted_in_the_schema(self):
        app = _app(proc_observe_allowlist=[["git", "status"], ["gh", "release", "view"]])
        schema = app.dump_schema_dict()
        assert schema["proc_observe_allowlist"] == [
            ["git", "status"], ["gh", "release", "view"],
        ]

    def test_allowlist_omitted_when_empty(self):
        assert "proc_observe_allowlist" not in _app().dump_schema_dict()

    @pytest.mark.parametrize("bad", ["git", [[]], [[1]]])
    def test_allowlist_shape_is_validated(self, bad):
        with pytest.raises(ValueError, match="proc_observe_allowlist"):
            _app(proc_observe_allowlist=[bad] if isinstance(bad, str) else bad)


class TestReadOnlyEnforcement:
    @pytest.mark.parametrize("call", [
        lambda e: e.write("a", "b"),
        lambda e: e.mkdir("a"),
        lambda e: e.remove("a"),
        lambda e: e.rename("a", "b"),
        lambda e: e.chmod("a", 0o755),
        lambda e: e.http("POST", "https://x.test"),
        lambda e: e.spawn(["x"]),
    ])
    def test_mutating_members_are_call_time_errors(self, call):
        app = _app()

        @app.command("look", help="look", effect="read_only")
        def _look(ctx):
            call(ctx.effects)
            return 0

        with pytest.raises(ValueError) as exc:
            app.test(["look"])
        assert 'command "look" is classified read_only; effects.' in str(exc.value)
        assert "is a mutating operation" in str(exc.value)

    def test_enforcement_is_at_call_time_not_registration(self):
        app = _app()

        @app.command("look", help="look", effect="read_only")
        def _look(ctx):
            return 0
        # Registration succeeded; only the call would fail.
        assert app._commands["look"].effect == "read_only"


class TestGrants:
    def test_undeclared_grant(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("x", grant="nope")
            return 0

        with pytest.raises(ValueError) as exc:
            app.test(["--dry-run", "rel"])
        assert str(exc.value) == (
            'command "rel": grant \'nope\' is not declared on this command'
        )

    def test_grant_kind_mismatch(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating",
                     grants=[sc.Grant("push", "why", sc.PROC_MUTATE)])
        def _rel(ctx):
            ctx.effects.mkdir("x", grant="push")
            return 0

        with pytest.raises(ValueError) as exc:
            app.test(["--dry-run", "rel"])
        assert str(exc.value) == (
            'command "rel": grant \'push\' is declared for kind proc_mutate '
            "but was used for a file_write effect"
        )

    @pytest.mark.parametrize("bad", ["Push", "1push", "push_it", "", "push!"])
    def test_invalid_grant_name(self, bad):
        app = _app()
        with pytest.raises(ValueError) as exc:
            @app.command("rel", help="rel", effect="mutating",
                         grants=[sc.Grant(bad, "why", sc.PROC_MUTATE)])
            def _rel(ctx):
                return 0
        assert str(exc.value) == (
            f'command "rel": invalid grant name \'{bad}\': '
            f"must match [a-z][a-z0-9-]*"
        )

    def test_duplicate_grant(self):
        app = _app()
        with pytest.raises(ValueError) as exc:
            @app.command("rel", help="rel", effect="mutating",
                         grants=[sc.Grant("push", "a", sc.PROC_MUTATE),
                                 sc.Grant("push", "b", sc.NET_MUTATE)])
            def _rel(ctx):
                return 0
        assert str(exc.value) == 'command "rel": duplicate grant \'push\''

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_empty_grant_reason(self, bad):
        app = _app()
        with pytest.raises(ValueError) as exc:
            @app.command("rel", help="rel", effect="mutating",
                         grants=[sc.Grant("push", bad, sc.PROC_MUTATE)])
            def _rel(ctx):
                return 0
        assert str(exc.value) == (
            'command "rel": grant \'push\' reason must be a non-empty string'
        )

    def test_invalid_grant_kind(self):
        app = _app()
        with pytest.raises(ValueError) as exc:
            @app.command("rel", help="rel", effect="mutating",
                         grants=[sc.Grant("push", "why", "cache_write")])
            def _rel(ctx):
                return 0
        assert "invalid kind 'cache_write'" in str(exc.value)

    def test_grants_are_emitted_in_the_schema(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating",
                     grants=[sc.Grant("push", "engine owns refs", sc.PROC_MUTATE)])
        def _rel(ctx):
            return 0

        assert app.dump_schema_dict()["commands"]["rel"]["grants"] == [
            {"name": "push", "reason": "engine owns refs", "kind": "proc_mutate"},
        ]

    def test_grants_omitted_when_empty(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            return 0

        assert "grants" not in app.dump_schema_dict()["commands"]["rel"]


class TestConditionalAnnotation:
    def test_real_mode_executes_unconditionally(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build", resource="dir:build",
                              skip_if_current="dir:build")
            ctx.effects.mkdir("build", skip_if_current="dir:build")
            return 0

        assert app.test(["rel"]).exit_code == 0
        assert (tmp_path / "build").is_dir()
        log = app.effect_log()
        assert len(log) == 2
        assert all(rec["recorded"] is False for rec in log)

    def test_resource_and_skip_if_current_may_name_the_same_token(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build", resource="dir:build",
                              skip_if_current="dir:build")
            return 0

        r = app.test(["--dry-run", "rel"])
        assert "  1. mkdir: build [unless resource 'dir:build' already current]" in r.stdout
        assert app.effect_log()[0]["resource"] == "dir:build"
        assert app.effect_log()[0]["skip_if_current"] == "dir:build"


class TestEffectLog:
    def test_populated_in_live_mode_with_recorded_false(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            return 0

        app.test(["rel"])
        assert app.effect_log() == [{
            "seq": 1, "kind": "file_write", "verb": "mkdir",
            "detail": "build", "recorded": False,
        }]

    def test_recorded_true_in_dry_mode(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            return 0

        app.test(["--dry-run", "rel"])
        assert app.effect_log()[0]["recorded"] is True

    def test_log_is_reset_per_dispatch(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("build")
            return 0

        app.test(["rel"])
        app.test(["rel"])
        assert len(app.effect_log()) == 1

    def test_write_with_carrier_content_reports_no_byte_count(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            body = ctx.effects.run(["render", "changelog"])
            ctx.effects.write("CHANGELOG.md", body)
            return 0

        r = app.test(["--dry-run", "rel"])
        assert "  2. write: CHANGELOG.md («step 1 output»)" in r.stdout
        assert "bytes" not in app.effect_log()[1]


class TestCacheWrites:
    def test_schema_dump_records_a_cache_write(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        app = _app()

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            return 0

        r = app.test(["--dump-schema"])
        assert r.exit_code == 0
        log = app.effect_log()
        assert log[-1]["kind"] == "cache_write"
        assert log[-1]["verb"] == "cache"
        assert log[-1]["recorded"] is False
        assert log[-1]["detail"].endswith("schema.json")

    def test_cache_writes_execute_in_dry_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        app = _app()

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            return 0

        app.test(["--dry-run", "--dump-schema"])
        assert (tmp_path / ".strictcli" / "schema.json").is_file()

    def test_cache_writes_never_appear_in_the_would_do_log(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app(test_coverage=True)

        @app.command("run", help="run", effect="read_only")
        def _run(ctx):
            return 0

        r = app.test(["--dry-run", "run"])
        assert r.stdout == "DRY RUN — no changes were made. Would do:\n"
        assert any(rec["kind"] == "cache_write" for rec in app.effect_log())

    def test_no_public_way_to_mint_a_cache_write(self):
        app = _app()
        seen = {}

        @app.command("run", help="run", effect="mutating")
        def _run(ctx):
            seen["methods"] = {
                m for m in dir(ctx.effects) if not m.startswith("_")
            }
            return 0

        app.test(["--dry-run", "run"])
        assert seen["methods"] == {
            "run", "spawn", "write", "mkdir", "remove", "rename", "chmod", "http",
        }


class TestLiveExecution:
    def test_run_captures_decoded_output(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            out = ctx.effects.run([PY, "-c", "print('hi')"])
            return sc.outcome(data={"stdout": out.stdout, "code": out.exit_code})

        assert app.test(["rel"]).data == {"stdout": "hi", "code": 0}

    def test_nonzero_exit_raises_by_default(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run([PY, "-c", "raise SystemExit(3)"])
            return 0

        with pytest.raises(sc.EffectFailed) as exc:
            app.test(["rel"])
        assert 'command "rel": effects.run failed: ' in str(exc.value)
        assert "exited 3" in str(exc.value)

    def test_check_false_returns_the_status(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            out = ctx.effects.run([PY, "-c", "raise SystemExit(3)"], check=False)
            return sc.outcome(data={"code": out.exit_code})

        assert app.test(["rel"]).data == {"code": 3}

    def test_invalid_utf8_output_fails(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run([
                PY, "-c",
                "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')",
            ])
            return 0

        with pytest.raises(sc.EffectFailed) as exc:
            app.test(["rel"])
        assert str(exc.value) == (
            'command "rel": effects.run produced output that is not valid UTF-8'
        )

    def test_env_merges_over_the_inherited_environment(self, monkeypatch):
        monkeypatch.setenv("KEEP_ME", "kept")
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            out = ctx.effects.run([
                PY, "-c",
                "import os; print(os.environ['KEEP_ME'], os.environ['EXTRA'])",
            ], env={"EXTRA": "added"})
            return sc.outcome(data={"stdout": out.stdout})

        assert app.test(["rel"]).data == {"stdout": "kept added"}

    def test_stream_leaves_captured_output_empty(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            out = ctx.effects.run([PY, "-c", "pass"], stream=True)
            return sc.outcome(data={"stdout": out.stdout, "stderr": out.stderr})

        assert app.test(["rel"]).data == {"stdout": "", "stderr": ""}

    def test_spawn_and_wait(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            s = ctx.effects.spawn([PY, "-c", "pass"])
            done = s.wait()
            return sc.outcome(data={"code": done.exit_code, "has_pid": s.pid > 0})

        assert app.test(["rel"]).data == {"code": 0, "has_pid": True}

    def test_spawn_wait_check_raises_on_failure(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.spawn([PY, "-c", "raise SystemExit(4)"]).wait()
            return 0

        with pytest.raises(sc.EffectFailed) as exc:
            app.test(["rel"])
        assert 'effects.spawn failed: ' in str(exc.value)
        assert "exited 4" in str(exc.value)

    def test_spawn_wait_check_false(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            done = ctx.effects.spawn([PY, "-c", "raise SystemExit(4)"]).wait(check=False)
            return sc.outcome(data={"code": done.exit_code})

        assert app.test(["rel"]).data == {"code": 4}

    def test_file_effects(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("deep/nested")
            ctx.effects.mkdir("deep/nested")  # existing dir is not an error
            ctx.effects.write("deep/nested/a.txt", "hello")
            ctx.effects.rename("deep/nested/a.txt", "deep/nested/b.txt")
            ctx.effects.chmod("deep/nested/b.txt", 0o600)
            ctx.effects.remove("deep/nested/b.txt")
            ctx.effects.remove("deep/nested/missing")  # missing path is not an error
            ctx.effects.write("bytes.bin", b"\x00\x01")
            return 0

        assert app.test(["rel"]).exit_code == 0
        assert not (tmp_path / "deep/nested/b.txt").exists()
        assert (tmp_path / "bytes.bin").read_bytes() == b"\x00\x01"

    def test_remove_is_recursive(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tree" / "sub").mkdir(parents=True)
        (tmp_path / "tree" / "sub" / "f").write_text("x")
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.remove("tree")
            return 0

        app.test(["rel"])
        assert not (tmp_path / "tree").exists()

    def test_forwarding_a_completed_projects_its_stdout(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            name = ctx.effects.run([PY, "-c", "print('out.txt')"])
            ctx.effects.write(name, "content")
            return 0

        app.test(["rel"])
        assert (tmp_path / "out.txt").read_text() == "content"


class TestParameterValidation:
    def test_argv_must_be_a_sequence(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run("git status")
            return 0

        with pytest.raises(TypeError, match="argv must be a sequence"):
            app.test(["--dry-run", "rel"])

    def test_argv_must_not_be_empty(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run([])
            return 0

        with pytest.raises(ValueError, match="argv must not be empty"):
            app.test(["--dry-run", "rel"])

    def test_inapplicable_option_is_a_call_time_error(self):
        """No method accepts an option it does not declare."""
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir("x", check=False)
            return 0

        with pytest.raises(TypeError, match="check"):
            app.test(["--dry-run", "rel"])

    def test_no_shell_parameter_anywhere(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.run(["echo"], shell=True)
            return 0

        with pytest.raises(TypeError, match="shell"):
            app.test(["--dry-run", "rel"])

    def test_mode_must_be_an_int(self):
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.chmod("x", "755")
            return 0

        with pytest.raises(TypeError, match="'mode' must be an int"):
            app.test(["--dry-run", "rel"])

    def test_path_accepts_pathlike(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        app = _app()

        @app.command("rel", help="rel", effect="mutating")
        def _rel(ctx):
            ctx.effects.mkdir(tmp_path / "made")
            return 0

        app.test(["rel"])
        assert (tmp_path / "made").is_dir()
