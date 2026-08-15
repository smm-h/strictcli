"""Tests for the InfraEnv primitive: location roots, handshake vars, markers."""

import json
import os

import pytest
from conftest import payload

import strictcli
from strictcli import App, Context, RelativeToRoot
from strictcli import choice, choice_flag, member_value, sub_flag


# --- Eager root resolution ---


def test_infra_root_env_set(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    assert app._infra_roots["MYAPP_HOME"] == "/opt/data"
    assert app._infra_root_from_env["MYAPP_HOME"] is True


def test_infra_root_unset(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    assert app._infra_roots["MYAPP_HOME"] == "/var/lib/myapp"
    assert app._infra_root_from_env["MYAPP_HOME"] is False


def test_infra_root_tilde_expansion(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "~/.myapp"})
    assert app._infra_roots["MYAPP_HOME"] == os.path.join(os.path.expanduser("~"), ".myapp")


def test_infra_root_tilde_expansion_from_env(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "~/data")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    assert app._infra_roots["MYAPP_HOME"] == os.path.join(os.path.expanduser("~"), "data")


# --- Flag-default marker + infra provenance ---


def _make_flag_app(monkeypatch):
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured = {}

    @app.command("run", effect="read_only", help="run it")
    @strictcli.flag("db", help="db path", default=RelativeToRoot("MYAPP_HOME", "db.sqlite"))
    def run(ctx, db):
        captured["db"] = db
        return 0

    return app, captured


def test_flag_default_marker_infra_provenance(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_flag_app(monkeypatch)
    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["db"] == "/var/lib/myapp/db.sqlite"
    assert app._last_sources["db"] == "infra"


def test_flag_default_marker_hermetic_immune(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app, captured = _make_flag_app(monkeypatch)
    # Even under --hermetic, the root resolves (no argv dependency).
    r = app.test(["--hermetic", "run"])
    assert r.exit_code == 0, r.stderr
    assert captured["db"] == "/opt/data/db.sqlite"
    assert app._last_sources["db"] == "infra"


def test_cli_override_not_infra(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_flag_app(monkeypatch)
    r = app.test(["run", "--db", "/tmp/custom.db"])
    assert r.exit_code == 0, r.stderr
    assert captured["db"] == "/tmp/custom.db"
    assert app._last_sources["db"] == "cli"


# --- The same marker, declared INSIDE a scope (§23.5, §24.6) ---
#
# §18.23 item 237. A scope is not a second declaration language: `RelativeToRoot`
# means inside a scope exactly what it means at root scope, so a scoped flag's
# declared marker reaches the handler as the resolved PATH, labelled infra
# wherever the record exposes a source and `provided` false either way -- never
# as the marker itself, which no handler should have to resolve.


@choice("email", help="an email message")
class _Email:
    cache: str = sub_flag(
        help="where the cache lives",
        default=RelativeToRoot("MYAPP_HOME", "cache", "email.db"),
    )


@choice("sms", help="a text message")
class _Sms:
    pass


@choice("profile", help="a profile")
class _Profile:
    value: str = member_value(help="the profile name")
    store: str = sub_flag(
        help="where the profile lives",
        default=RelativeToRoot("MYAPP_HOME", "profiles"),
    )


@choice("all-profiles", help="every profile")
class _AllProfiles:
    pass


def _make_scoped_marker_app():
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured: dict = {}

    @app.command("run", effect="read_only", help="run it")
    @choice_flag("via", help="delivery channel", presence="required",
                 elect_by="selector-token", choices=[_Email, _Sms])
    @choice_flag("mode", help="which profiles", presence="required",
                 elect_by="member-flags", choices=[_Profile, _AllProfiles])
    def run(ctx, via: "_Email | _Sms", mode: "_Profile | _AllProfiles"):
        captured["via"] = via
        captured["mode"] = mode
        return 0

    return app, captured


def test_scoped_flag_default_marker_resolves(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_scoped_marker_app()
    r = app.test(["run", "--via", "email", "--profile", "work"])
    assert r.exit_code == 0, r.stderr
    assert captured["via"].cache == "/var/lib/myapp/cache/email.db"


def test_member_scope_flag_default_marker_resolves(monkeypatch):
    """A member's scope is a scope like any other, at any depth."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_scoped_marker_app()
    r = app.test(["run", "--via", "sms", "--profile", "work"])
    assert r.exit_code == 0, r.stderr
    assert captured["mode"].store == "/var/lib/myapp/profiles"


def test_scoped_flag_default_marker_is_not_provided(monkeypatch):
    """Source `infra` says the DECLARATION decided, so provided-ness is false
    inside a scope exactly as it is on the root surface."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_scoped_marker_app()
    app.test(["run", "--via", "email", "--profile", "work"])
    assert strictcli.provided(captured["via"], "cache") is False
    assert strictcli.provided(captured["mode"], "store") is False
    # The label the record carries says WHICH default it was, as it does on
    # the root surface -- `infra`, not the plain `default` it reported before.
    sources = getattr(captured["via"], strictcli._RECORD_SOURCES_ATTR)
    assert sources["cache"] == "infra"


def test_scoped_flag_default_marker_reads_the_env_root(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app, captured = _make_scoped_marker_app()
    r = app.test(["run", "--via", "email", "--profile", "work"])
    assert r.exit_code == 0, r.stderr
    assert captured["via"].cache == "/opt/data/cache/email.db"


def test_scoped_flag_default_marker_is_hermetic_immune(monkeypatch):
    """A root has no argv dependency, so `--hermetic` cannot suppress it."""
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app, captured = _make_scoped_marker_app()
    r = app.test(["--hermetic", "run", "--via", "email", "--profile", "work"])
    assert r.exit_code == 0, r.stderr
    assert captured["via"].cache == "/opt/data/cache/email.db"


def test_scoped_cli_value_overrides_the_marker(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_scoped_marker_app()
    r = app.test([
        "run", "--via", "email", "--cache", "/tmp/custom.db", "--profile", "work",
    ])
    assert r.exit_code == 0, r.stderr
    assert captured["via"].cache == "/tmp/custom.db"
    assert strictcli.provided(captured["via"], "cache") is True


def test_scoped_flag_default_marker_resolves_at_the_flat_boundary(monkeypatch):
    """The flat machine form runs the same presence phase, so it delivers the
    same resolved path rather than a marker no MCP caller could interpret."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_scoped_marker_app()
    app._call_with_kwargs(
        "run", {"via": "email", "profile": "work"},
        approve_consequential=False, flat=True,
    )
    assert captured["via"].cache == "/var/lib/myapp/cache/email.db"
    assert captured["mode"].store == "/var/lib/myapp/profiles"


def test_scoped_marker_naming_an_undeclared_root_is_a_parse_error(monkeypatch):
    """Registration does not see inside a scope, so the refusal arrives at
    parse time -- carrying the scope it was declared in."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)

    @choice("email", help="an email message")
    class Email:
        cache: str = sub_flag(
            help="where the cache lives",
            default=RelativeToRoot("NOPE", "cache"),
        )

    @choice("sms", help="a text message")
    class Sms:
        pass

    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})

    @app.command("run", effect="read_only", help="run it")
    @choice_flag("via", help="delivery channel", presence="required",
                 elect_by="selector-token", choices=[Email, Sms])
    def run(ctx, via: "Email | Sms"):
        return 0

    r = app.test(["run", "--via", "email"])
    assert r.exit_code == 1
    assert (
        'error: RelativeToRoot references undeclared infra root "NOPE"; '
        "declare it as an infra root under '--via email'\n"
    ) in r.stderr


# --- Config-path marker rewrite ---


def test_config_path_marker_rewrite(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app = App(name="myapp", version="1.0.0", help="t",
              config=True,
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              config_path=RelativeToRoot("MYAPP_HOME", "config.json"))
    assert app.config_path == "/opt/data/config.json"
    r = app.test(["config", "path"])
    assert "/opt/data/config.json" in r.stdout


# --- Undeclared root marker: registration hard error ---


def test_undeclared_root_marker_raises(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    with pytest.raises(ValueError, match="undeclared infra root"):
        @app.command("run", effect="read_only", help="run it")
        @strictcli.flag("db", help="db path", default=RelativeToRoot("NOPE", "x"))
        def run(ctx, db):
            return 0


def test_config_path_marker_undeclared_raises():
    with pytest.raises(ValueError, match="undeclared infra root"):
        App(name="myapp", version="1.0.0", help="t",
            config=True,
            config_path=RelativeToRoot("NOPE", "config.json"))


# --- Handshake + accessor ---


def test_infra_value_root_and_handshake_live(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    monkeypatch.setenv("CI_TOKEN", "abc123")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})
    captured = {}

    @app.command("run", effect="read_only", help="run it")
    def run(ctx: Context):
        captured["root"] = ctx.infra_value("MYAPP_HOME")
        captured["hs"] = ctx.infra_value("CI_TOKEN")
        return 0

    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["root"] == ("/opt/data", True)
    assert captured["hs"] == ("abc123", True)


def test_infra_value_handshake_unset(monkeypatch):
    monkeypatch.delenv("CI_TOKEN", raising=False)
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})
    captured = {}

    @app.command("run", effect="read_only", help="run it")
    def run(ctx: Context):
        captured["hs"] = ctx.infra_value("CI_TOKEN")
        return 0

    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["hs"] == (None, False)


def test_infra_value_undeclared_raises(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured = {}

    @app.command("run", effect="read_only", help="run it")
    def run(ctx: Context):
        try:
            ctx.infra_value("UNDECLARED_VAR")
        except KeyError:
            captured["raised"] = True
        return 0

    app.test(["run"])
    assert captured.get("raised") is True


def test_handshake_duplicate_root_raises():
    with pytest.raises(ValueError, match="already declared as an infra root"):
        App(name="myapp", version="1.0.0", help="t",
            infra_root={"SHARED": "/x"},
            handshake_env={"SHARED": "collides"})


def test_handshake_empty_help_raises():
    with pytest.raises(ValueError, match="help must be a non-empty string"):
        App(name="myapp", version="1.0.0", help="t",
            handshake_env={"CI_TOKEN": ""})


# --- Surfaces: schema, help, config show ---


def test_infra_schema_surface(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})
    schema = app.dump_schema_dict()
    assert "infra" in schema
    root0 = schema["infra"]["roots"][0]
    assert root0 == {"env_var": "MYAPP_HOME", "default": "/var/lib/myapp"}
    # Machine-stable: resolved value must NOT be present.
    assert "resolved" not in root0
    hs0 = schema["infra"]["handshakes"][0]
    assert hs0 == {"env_var": "CI_TOKEN", "help": "CI auth token"}


def test_infra_schema_absent_when_undeclared():
    app = App(name="myapp", version="1.0.0", help="t")
    assert "infra" not in app.dump_schema_dict()


def test_infra_help_surface(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})

    @app.command("run", effect="read_only", help="run it")
    def run(ctx):
        return 0

    r = app.test(["--help"])
    assert "Infrastructure:" in r.stdout
    assert "MYAPP_HOME" in r.stdout
    assert "CI_TOKEN" in r.stdout


def test_infra_config_show_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    monkeypatch.delenv("CI_TOKEN", raising=False)
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    app = App(name="myapp", version="1.0.0", help="t",
              config=True, config_path=str(config_file),
              infra_root={"MYAPP_HOME": "/var/lib/myapp"},
              handshake_env={"CI_TOKEN": "CI auth token"})

    r = app.test(["config", "show", "--plain"])
    assert "Infrastructure:" in r.stdout
    assert "MYAPP_HOME (root) = /opt/data" in r.stdout
    assert "source: env-set" in r.stdout
    assert "CI_TOKEN (handshake) = <unset>" in r.stdout

    rj = app.test(["config", "show", "--json"])
    result = payload(rj)
    infra = result["__infrastructure__"]
    assert infra["MYAPP_HOME"]["resolved"] == "/opt/data"
    assert infra["MYAPP_HOME"]["source"] == "env"
    assert infra["CI_TOKEN"]["set"] is False


# --- The same marker, carried by a DEFAULTED SELECTION's declared instance ---
#
# A defaulted selection is COMPLETE by declaration (§24.5) and the walk stops at
# it: nothing under it was supplied, so nothing under it is read from the
# invocation. Its fields are still DECLARED DEFAULTS, and a `RelativeToRoot`
# default is resolved wherever a declared default is applied -- so the marker is
# resolved at DELIVERY, at every door, and the handler reads the path rather
# than a marker it would have to resolve itself.


@choice("deep", help="deeper still")
class _Deep:
    trace: str = sub_flag(
        help="where the trace goes",
        default=RelativeToRoot("MYAPP_HOME", "trace"),
    )


@choice("shallow", help="not deep")
class _Shallow:
    pass


@choice("file", help="write to a file")
class _ToFile:
    path: str = sub_flag(
        help="where to write",
        default=RelativeToRoot("MYAPP_HOME", "out", "log.txt"),
    )
    depth: "_Deep | _Shallow" = strictcli.sub_choice_flag(
        help="how deep", default=_Deep(), elect_by="selector-token",
        choices=[_Deep, _Shallow],
    )


@choice("silent", help="no delivery")
class _Silent:
    pass


def _make_defaulted_selection_app():
    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured: dict = {}

    @app.command("run", effect="read_only", help="run it")
    @choice_flag("via", help="delivery channel", default=_ToFile(),
                 elect_by="selector-token", choices=[_ToFile, _Silent])
    def run(ctx, via: "_ToFile | _Silent"):
        captured["via"] = via
        return 0

    return app, captured


def test_defaulted_selection_marker_resolves_on_the_command_line(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_defaulted_selection_app()
    r = app.test(["run"])
    assert r.exit_code == 0, r.stderr
    assert captured["via"].path == "/var/lib/myapp/out/log.txt"


def test_defaulted_selection_marker_resolves_at_the_flat_boundary(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_defaulted_selection_app()
    app._call_with_kwargs(
        "run", {}, approve_consequential=False, flat=True,
    )
    assert captured["via"].path == "/var/lib/myapp/out/log.txt"


def test_defaulted_selection_marker_resolves_at_the_record_door(monkeypatch):
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    app, captured = _make_defaulted_selection_app()
    app.call("run")
    assert captured["via"].path == "/var/lib/myapp/out/log.txt"


def test_defaulted_selection_marker_resolves_at_every_depth(monkeypatch):
    """A selection defaulted inside a defaulted selection is the same fact one
    level down."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    for delivered in _each_door_delivery():
        assert delivered.depth.trace == "/var/lib/myapp/trace"


def _each_door_delivery():
    """The delivered `via` record from all three doors, in turn."""
    app, captured = _make_defaulted_selection_app()
    app.test(["run"])
    yield captured["via"]
    app, captured = _make_defaulted_selection_app()
    app._call_with_kwargs("run", {}, approve_consequential=False, flat=True)
    yield captured["via"]
    app, captured = _make_defaulted_selection_app()
    app.call("run")
    yield captured["via"]


def test_defaulted_selection_marker_reads_the_env_root(monkeypatch):
    monkeypatch.setenv("MYAPP_HOME", "/opt/data")
    for delivered in _each_door_delivery():
        assert delivered.path == "/opt/data/out/log.txt"


def test_defaulted_selection_marker_reports_infra_and_is_not_provided(monkeypatch):
    """Source `infra` says WHICH default it was, exactly as it does for a
    marker inside an elected scope."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)
    for delivered in _each_door_delivery():
        sources = getattr(delivered, strictcli._RECORD_SOURCES_ATTR)
        assert sources["path"] == "infra"
        assert sources["depth"] == "default"
        assert strictcli.provided(delivered, "path") is False


def test_a_defaulted_selection_still_delivers_its_plain_defaults(monkeypatch):
    """Only the markers are resolved: every other field is the value the
    declaration wrote, untouched."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)

    @choice("plainly", help="plainly")
    class Plainly:
        retries: int = sub_flag(help="how many", default=3)

    @choice("otherwise", help="otherwise")
    class Otherwise:
        pass

    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured: dict = {}

    @app.command("run", effect="read_only", help="run it")
    @choice_flag("via", help="delivery channel", default=Plainly(),
                 elect_by="selector-token", choices=[Plainly, Otherwise])
    def run(ctx, via: "Plainly | Otherwise"):
        captured["via"] = via
        return 0

    app.call("run")
    assert captured["via"].retries == 3
    # Nothing needed resolving, so the declaration's own object is delivered.
    assert captured["via"] is app._commands["run"].selectors[0].default


def test_defaulted_selection_marker_naming_an_undeclared_root_is_refused(monkeypatch):
    """Registration does not see inside a scope, so the refusal arrives at
    delivery -- carrying the scope the declaration lives in."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)

    @choice("elsewhere", help="write elsewhere")
    class Elsewhere:
        path: str = sub_flag(
            help="where to write", default=RelativeToRoot("NOPE", "out"),
        )

    @choice("silent", help="no delivery")
    class Silent:
        pass

    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})

    @app.command("run", effect="read_only", help="run it")
    @choice_flag("via", help="delivery channel", default=Elsewhere(),
                 elect_by="selector-token", choices=[Elsewhere, Silent])
    def run(ctx, via: "Elsewhere | Silent"):
        return 0

    r = app.test(["run"])
    assert r.exit_code == 1
    assert (
        'error: RelativeToRoot references undeclared infra root "NOPE"; '
        "declare it as an infra root under '--via elsewhere'\n"
    ) in r.stderr
    with pytest.raises(strictcli.InvokeError) as exc:
        app.call("run")
    assert str(exc.value) == (
        'RelativeToRoot references undeclared infra root "NOPE"; '
        "declare it as an infra root under '--via elsewhere'"
    )


def test_a_defaulted_selection_copies_its_compound_defaults(monkeypatch):
    """§24.5: "delivered as declared" is the declaration's SEMANTICS, so a
    compound default is copied at delivery exactly as it is anywhere else --
    a handler that appends to what it was handed cannot reach into the
    declaration every later run reads."""
    monkeypatch.delenv("MYAPP_HOME", raising=False)

    @choice("batched", help="in batches")
    class Batched:
        tags: list[str] = sub_flag(
            help="the tags", repeatable=True, unique=False, default=[],
        )
        limits: dict[str, str] = sub_flag(help="the limits", default={})

    @choice("single", help="one at a time")
    class Single:
        pass

    app = App(name="myapp", version="1.0.0", help="t",
              infra_root={"MYAPP_HOME": "/var/lib/myapp"})
    captured: dict = {}

    @app.command("run", effect="read_only", help="run it")
    @choice_flag("via", help="delivery channel", default=Batched(),
                 elect_by="selector-token", choices=[Batched, Single])
    def run(ctx, via: "Batched | Single"):
        captured["via"] = via
        return 0

    app.call("run")
    captured["via"].tags.append("mutated")
    captured["via"].limits["cpu"] = "2"
    declared = app._commands["run"].selectors[0].default
    assert declared.tags == []
    assert declared.limits == {}
    app.call("run")
    assert captured["via"].tags == []
    assert captured["via"].limits == {}
