"""Machine mode: the reserved --json flag and the payload API.

Contract §19.1 (the flag and its delivery), §19.4 (the payload API) and
§7.1's 2026-08-13 amendment (the unconditional every-level name ban).
"""

import pytest

import strictcli


def _app():
    return strictcli.App(name="app", version="1.0.0", help="app")


# ---------------------------------------------------------------------------
# The name ban -- unconditional, at every level
# ---------------------------------------------------------------------------

_RESERVED = "flag name 'json' is reserved by the framework"


class TestJsonNameIsReserved:
    def test_command_flag(self):
        with pytest.raises(ValueError, match=_RESERVED):
            strictcli.Flag(name="json", type=bool, default=False, help="h")

    def test_flag_decorator_at_command_registration(self):
        # The @flag decorator defers construction to command build time, which
        # is where the quartet's ban fires too.
        app = _app()
        with pytest.raises(ValueError, match=_RESERVED):
            @app.command("run", effect="read_only", help="run")
            @strictcli.flag("json", type=bool, default=False, help="h")
            def _run(ctx, json):
                return 0

    def test_app_global_flag(self):
        with pytest.raises(ValueError, match=_RESERVED):
            strictcli.App(
                name="app", version="1.0.0", help="app",
                flags=[strictcli.Flag(name="json", type=bool, default=False,
                                      help="h")],
            )

    def test_flag_set_flag(self):
        with pytest.raises(ValueError, match=_RESERVED):
            strictcli.FlagSet(flags=[
                strictcli.Flag(name="json", type=bool, default=False, help="h"),
            ])

    def test_mutex_group_flag(self):
        with pytest.raises(ValueError, match=_RESERVED):
            strictcli.MutexGroup(flags=[
                strictcli.Flag(name="json", type=bool, default=False, help="h"),
                strictcli.Flag(name="text", type=bool, default=False, help="h"),
            ])

    def test_positional_arg_named_json_is_unaffected(self):
        # The ban covers the flag surface only: an arg has no `--` spelling.
        strictcli.Arg(name="json", help="a file named json")


# ---------------------------------------------------------------------------
# Delivery: recognized anywhere in argv, stripped, on the Context
# ---------------------------------------------------------------------------

def _flag_reader_app():
    app = _app()

    @app.command("run", effect="read_only", help="run", payload_schema={})
    def _run(ctx):
        ctx.payload({"json": ctx.json})
        return strictcli.outcome()

    return app


class TestJsonDelivery:
    def test_absent_by_default(self):
        r = _flag_reader_app().test(["run"])
        assert r.data == {"json": False}
        assert r.stdout == ""

    def test_before_the_command(self):
        r = _flag_reader_app().test(["--json", "run"])
        assert r.data == {"json": True}
        assert r.stdout == '{"json":true}\n'

    def test_after_the_command(self):
        r = _flag_reader_app().test(["run", "--json"])
        assert r.data == {"json": True}
        assert r.stdout == '{"json":true}\n'

    def test_never_a_handler_kwarg(self):
        app = _app()

        @app.command("run", effect="read_only", help="run")
        def _run(ctx):
            return 0

        # A handler declaring no parameters still dispatches: the token is
        # stripped from argv before command parsing.
        assert app.test(["run", "--json"]).exit_code == 0

    def test_after_a_bare_double_dash_is_data(self):
        app = _app()

        @app.command("run", effect="read_only", help="run", payload_schema={})
        @strictcli.arg("rest", help="rest", variadic=True)
        def _run(ctx, rest):
            ctx.payload({"json": ctx.json, "rest": rest})
            return strictcli.outcome()

        r = app.test(["run", "--", "--json"])
        assert r.data == {"json": False, "rest": ["--json"]}


# ---------------------------------------------------------------------------
# The payload API
# ---------------------------------------------------------------------------

class TestPayloadApi:
    def test_requires_a_declared_schema(self):
        app = _app()

        @app.command("run", effect="read_only", help="run")
        def _run(ctx):
            ctx.payload({"k": 1})
            return strictcli.outcome()

        with pytest.raises(RuntimeError, match="requires a declared payload schema"):
            app.test(["run"])

    def test_at_most_once_per_dispatch(self):
        app = _app()

        @app.command("run", effect="read_only", help="run", payload_schema={})
        def _run(ctx):
            ctx.payload({"k": 1})
            ctx.payload({"k": 2})
            return strictcli.outcome()

        with pytest.raises(RuntimeError, match="was already called"):
            app.test(["run"])

    def test_call_returns_the_payload(self):
        app = _app()

        @app.command("run", effect="read_only", help="run", payload_schema={})
        def _run(ctx):
            ctx.payload(["a", "b"])
            return strictcli.outcome()

        assert app.call("run") == ["a", "b"]

    def test_escaping_is_plain_utf8(self):
        """Contract §19.5: escape only what JSON mandates."""
        app = _app()

        @app.command("run", effect="read_only", help="run", payload_schema={})
        def _run(ctx):
            ctx.payload({"text": "héllo <b>&</b> 日本語"})
            return strictcli.outcome()

        r = app.test(["run", "--json"])
        assert r.stdout == '{"text":"héllo <b>&</b> 日本語"}\n'
