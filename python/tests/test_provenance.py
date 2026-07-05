"""Tests for source-filtered presence semantics (Phase 0c provenance)."""

import strictcli


# ---------------------------------------------------------------------------
# Test 1: Mutex group where one flag is default -- NOT trigger violation
# ---------------------------------------------------------------------------

def test_mutex_default_source_not_present_cli():
    """A flag with source=default should NOT be 'present' for mutex evaluation."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=bool, default=False, help="JSON output"),
            strictcli.Flag(name="text", type=bool, default=False, help="text output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("out", help="output command", mutex=[mg])
    def out(json, text):
        print(f"json={json} text={text}")

    # Provide only --json. --text has Default(False), so it gets source=default.
    # Mutex should see only --json as "present" and NOT fire.
    r = app.test(["out", "--json"])
    assert r.exit_code == 0, f"expected success, got: {r.stderr}"


def test_mutex_default_source_not_present_invoke():
    """Invoke path: absent kwarg gets source=default, not present for mutex."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=bool, default=False, help="JSON output"),
            strictcli.Flag(name="text", type=bool, default=False, help="text output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("out", help="output command", mutex=[mg])
    def out(json, text):
        print(f"json={json} text={text}")

    # Provide only "json" via invoke. "text" is absent, gets defaulted.
    # Should succeed -- default does not trigger mutex.
    # call() returns None when handler returns None (print returns None).
    app.call("out", json=True)


# ---------------------------------------------------------------------------
# Test 2: Mutex group where one flag is implied -- NOT trigger violation
# ---------------------------------------------------------------------------

def test_mutex_implied_source_not_present():
    """A flag with source=implied should NOT be 'present' for mutex evaluation."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=bool, default=None, help="JSON output"),
            strictcli.Flag(name="text", type=bool, default=None, help="text output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "out", help="output command", mutex=[mg],
        dependencies=[
            # --verbose implies --text=true
            strictcli.Implies(flag="verbose", implies="text", value=True),
        ],
    )
    @strictcli.flag("verbose", type=bool, default=False, help="verbose mode")
    def out(json, text, verbose):
        print(f"json={json} text={text}")

    # Provide --json and --verbose. --verbose implies --text=True (source=implied).
    # Mutex should see only --json as present, NOT fire.
    r = app.test(["out", "--json", "--verbose"])
    assert r.exit_code == 0, f"expected success, got: {r.stderr}"


# ---------------------------------------------------------------------------
# Test 3: Mutex cli + config -- SHOULD trigger (trivially passes for now)
# ---------------------------------------------------------------------------

def test_mutex_cli_and_config_both_present():
    """When both CLI and config values are in a mutex group, it should error.

    Since config is temporarily marked as _Source.CLI (Phase 2a will give
    it _Source.CONFIG), this test passes trivially because both flags
    will be seen as SourceCLI. The test documents the intended behavior
    and will become meaningful after Phase 2a.
    """
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=str, default=None, help="JSON output"),
            strictcli.Flag(name="text", type=str, default=None, help="text output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("out", help="output command", mutex=[mg])
    def out(json, text):
        print(f"json={json} text={text}")

    # Provide both via invoke (both SourceCLI). Should error.
    try:
        app.call("out", json="data", text="data")
        assert False, "expected InvokeError"
    except strictcli.InvokeError as e:
        assert "mutually exclusive" in str(e)


# ---------------------------------------------------------------------------
# Test 4: Requires where required flag is implied -- should PASS
# ---------------------------------------------------------------------------

def test_requires_implied_source_counts_as_present():
    """Implied values count as 'present' for Requires dependency checks."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "deploy", help="deploy",
        dependencies=[
            # --all implies --verbose=true
            strictcli.Implies(flag="all", implies="verbose", value=True),
            # --target requires --verbose
            strictcli.Requires(flag="target", depends_on="verbose"),
        ],
    )
    @strictcli.flag("all", type=bool, default=False, help="deploy all")
    @strictcli.flag("verbose", type=bool, default=False, help="verbose mode")
    @strictcli.flag("target", type=str, help="deploy target")
    def deploy(all, verbose, target):
        print(f"all={all} verbose={verbose} target={target}")

    # Provide --all and --target. --all implies --verbose (source=implied).
    # --target requires --verbose. Implied counts for deps, so should succeed.
    r = app.test(["deploy", "--all", "--target", "prod"])
    assert r.exit_code == 0, f"expected success, got: {r.stderr}"


# ---------------------------------------------------------------------------
# Test 5: Requires where required flag is default -- should FAIL
# ---------------------------------------------------------------------------

def test_requires_default_source_not_present():
    """Default values do NOT count as 'present' for Requires dependency checks."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "deploy", help="deploy",
        dependencies=[
            # --target requires --verbose
            strictcli.Requires(flag="target", depends_on="verbose"),
        ],
    )
    @strictcli.flag("target", type=str, help="deploy target")
    @strictcli.flag("verbose", type=bool, default=False, help="verbose mode")
    def deploy(target, verbose):
        print(f"target={target} verbose={verbose}")

    # Provide --target but NOT --verbose. --verbose has default=False,
    # so it gets source=default. Default does NOT count for deps.
    r = app.test(["deploy", "--target", "prod"])
    assert r.exit_code == 1
    assert "requires" in r.stderr


# ---------------------------------------------------------------------------
# Invoke path tests
# ---------------------------------------------------------------------------

def test_invoke_mutex_provided_kwarg_is_cli_source():
    """Invoke: provided kwargs are SourceCLI, count for mutex."""
    mg = strictcli.MutexGroup(
        flags=[
            strictcli.Flag(name="json", type=str, default=None, help="JSON output"),
            strictcli.Flag(name="text", type=str, default=None, help="text output"),
        ],
    )
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("out", help="output command", mutex=[mg])
    def out(json, text):
        print(f"json={json} text={text}")

    # Provide exactly one mutex flag via invoke -- should succeed.
    app.call("out", json="data")


def test_invoke_defaulted_not_present_for_requires():
    """Invoke: absent kwarg gets source=default, not present for Requires."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command(
        "deploy", help="deploy",
        dependencies=[
            strictcli.Requires(flag="target", depends_on="verbose"),
        ],
    )
    @strictcli.flag("target", type=str, help="deploy target")
    @strictcli.flag("verbose", type=bool, default=False, help="verbose mode")
    def deploy(target, verbose):
        print(f"target={target} verbose={verbose}")

    # Provide target but not verbose. verbose will be defaulted.
    try:
        app.call("deploy", target="prod")
        assert False, "expected InvokeError for requires violation"
    except strictcli.InvokeError as e:
        assert "requires" in str(e)
