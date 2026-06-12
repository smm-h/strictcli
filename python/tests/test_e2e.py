"""End-to-end tests with a realistic rlsbl-like app."""

import strictcli


def _build_rlsbl_app():
    """Build a mini rlsbl-like CLI app with commands, groups, flag sets, and env vars."""
    auth_flag_set = strictcli.FlagSet(
        name="auth",
        flags=[
            strictcli.Flag(
                name="token",
                type=str,
                help="GitHub auth token",
                env="RLSBL_TOKEN",
                default="",
            ),
        ],
    )

    app = strictcli.App(
        name="rlsbl",
        version="3.1.0",
        help="release orchestration tool",
        env_prefix="RLSBL",
    )

    # Top-level commands
    @app.command("status", help="show release status", flag_sets=[auth_flag_set])
    def status(token):
        print(f"status: token={'set' if token else 'unset'}")

    @app.command(
        "release",
        help="create a new release",
        args=[strictcli.Arg(name="bump", help="version bump type")],
        flag_sets=[auth_flag_set],
    )
    @strictcli.flag("dry-run", type=bool, help="preview without making changes")
    @strictcli.flag("yes", type=bool, help="non-interactive mode")
    def release(bump, token, dry_run, yes):
        parts = [f"releasing {bump}"]
        if dry_run:
            parts.append("(dry-run)")
        if yes:
            parts.append("(non-interactive)")
        if token:
            parts.append(f"token={'set' if token else 'unset'}")
        print(" ".join(parts))

    @app.command(
        "watch",
        help="monitor CI for a commit",
        args=[strictcli.Arg(name="sha", help="commit SHA")],
    )
    def watch(sha):
        print(f"watching {sha}")

    # Group: config
    config = app.group("config", help="manage rlsbl configuration")

    @config.command("show", help="display current config")
    @strictcli.flag("format", type=str, help="output format", default="text", env="RLSBL_FORMAT")
    def config_show(format):
        print(f"config format={format}")

    @config.command("set", help="set a config value")
    @strictcli.flag("key", type=str, help="config key")
    @strictcli.flag("value", type=str, help="config value")
    def config_set(key, value):
        print(f"config {key}={value}")

    return app


def test_e2e_status_command():
    """Status command dispatches and runs correctly."""
    app = _build_rlsbl_app()
    r = app.test(["status"])
    assert r.exit_code == 0
    assert "status: token=unset" in r.stdout


def test_e2e_status_with_token(monkeypatch):
    """Status command picks up token from env var."""
    app = _build_rlsbl_app()
    monkeypatch.setenv("RLSBL_TOKEN", "ghp_abc123")
    r = app.test(["status"])
    assert r.exit_code == 0
    assert "status: token=set" in r.stdout


def test_e2e_release_full():
    """Release command with all flags and args."""
    app = _build_rlsbl_app()
    r = app.test(["release", "--dry-run", "--yes", "minor"])
    assert r.exit_code == 0
    assert "releasing minor" in r.stdout
    assert "(dry-run)" in r.stdout
    assert "(non-interactive)" in r.stdout


def test_e2e_release_minimal():
    """Release command with just the required arg."""
    app = _build_rlsbl_app()
    r = app.test(["release", "patch"])
    assert r.exit_code == 0
    assert "releasing patch" in r.stdout
    assert "(dry-run)" not in r.stdout


def test_e2e_watch():
    """Watch command with positional arg."""
    app = _build_rlsbl_app()
    r = app.test(["watch", "abc1234"])
    assert r.exit_code == 0
    assert "watching abc1234" in r.stdout


def test_e2e_group_show():
    """Group subcommand: config show."""
    app = _build_rlsbl_app()
    r = app.test(["config", "show"])
    assert r.exit_code == 0
    assert "config format=text" in r.stdout


def test_e2e_group_show_with_format():
    """Group subcommand: config show with --format flag."""
    app = _build_rlsbl_app()
    r = app.test(["config", "show", "--format", "json"])
    assert r.exit_code == 0
    assert "config format=json" in r.stdout


def test_e2e_group_show_from_env(monkeypatch):
    """Group subcommand: config show picks up format from env."""
    app = _build_rlsbl_app()
    monkeypatch.setenv("RLSBL_FORMAT", "yaml")
    r = app.test(["config", "show"])
    assert r.exit_code == 0
    assert "config format=yaml" in r.stdout


def test_e2e_group_set():
    """Group subcommand: config set."""
    app = _build_rlsbl_app()
    r = app.test(["config", "set", "--key", "target", "--value", "npm"])
    assert r.exit_code == 0
    assert "config target=npm" in r.stdout


def test_e2e_app_help():
    """App-level help shows all commands and groups."""
    app = _build_rlsbl_app()
    r = app.test([])
    assert r.exit_code == 0
    assert "rlsbl v3.1.0" in r.stdout
    assert "Commands:" in r.stdout
    assert "status" in r.stdout
    assert "release" in r.stdout
    assert "watch" in r.stdout
    assert "Groups:" in r.stdout
    assert "config" in r.stdout


def test_e2e_version():
    """--version shows app name and version."""
    app = _build_rlsbl_app()
    r = app.test(["--version"])
    assert r.exit_code == 0
    assert "rlsbl 3.1.0" in r.stdout


def test_e2e_group_help():
    """Group help shows subcommands."""
    app = _build_rlsbl_app()
    r = app.test(["config", "--help"])
    assert r.exit_code == 0
    assert "show" in r.stdout
    assert "set" in r.stdout


def test_e2e_command_help():
    """Command help shows flags and args."""
    app = _build_rlsbl_app()
    r = app.test(["release", "--help"])
    assert r.exit_code == 0
    assert "--dry-run" in r.stdout
    assert "--yes" in r.stdout
    assert "--token" in r.stdout
    assert "bump" in r.stdout


def test_e2e_unknown_command():
    """Unknown command gives error."""
    app = _build_rlsbl_app()
    r = app.test(["deploy"])
    assert r.exit_code == 1
    assert "unknown command" in r.stderr


def test_e2e_missing_required_arg():
    """Missing required arg gives error."""
    app = _build_rlsbl_app()
    r = app.test(["release"])
    assert r.exit_code == 1
    assert "missing required argument" in r.stderr


def test_e2e_unknown_group_subcommand():
    """Unknown group subcommand gives error."""
    app = _build_rlsbl_app()
    r = app.test(["config", "delete"])
    assert r.exit_code == 1
    assert "unknown command" in r.stderr


# --- **kwargs handler tests ---


def _build_kwargs_app():
    """Build a CLI app with a **kwargs handler to verify dispatch and parameter passing."""
    app = strictcli.App(
        name="kw",
        version="1.0.0",
        help="kwargs test app",
    )

    @app.command(
        "deploy",
        help="deploy the app",
        args=[strictcli.Arg(name="target", help="deploy target")],
    )
    @strictcli.flag("dry-run", type=bool, help="preview without making changes")
    @strictcli.flag("replicas", type=int, help="number of replicas", default=1)
    def deploy_handler(**kwargs):
        parts = [f"target={kwargs['target']}"]
        parts.append(f"dry_run={kwargs['dry_run']}")
        parts.append(f"replicas={kwargs['replicas']}")
        print(" ".join(parts))
        return 0

    return app


def test_e2e_kwargs_handler_dispatches():
    """Command with **kwargs handler dispatches and receives all parameters."""
    app = _build_kwargs_app()
    r = app.test(["deploy", "--dry-run", "--replicas", "3", "production"])
    assert r.exit_code == 0
    assert "target=production" in r.stdout
    assert "dry_run=True" in r.stdout
    assert "replicas=3" in r.stdout


def test_e2e_kwargs_handler_defaults():
    """Command with **kwargs handler receives default values for unset flags."""
    app = _build_kwargs_app()
    r = app.test(["deploy", "staging"])
    assert r.exit_code == 0
    assert "target=staging" in r.stdout
    assert "dry_run=False" in r.stdout
    assert "replicas=1" in r.stdout


def test_e2e_kwargs_handler_with_flag_sets():
    """Command with **kwargs handler and flag sets receives flag set flag values."""
    auth_flag_set = strictcli.FlagSet(
        name="auth",
        flags=[
            strictcli.Flag(name="token", type=str, help="auth token", default=""),
        ],
    )

    app = strictcli.App(name="kw", version="1.0.0", help="kwargs test app")

    @app.command("push", help="push changes", flag_sets=[auth_flag_set])
    def push_handler(**kwargs):
        print(f"token={kwargs['token']}")
        return 0

    r = app.test(["push", "--token", "abc123"])
    assert r.exit_code == 0
    assert "token=abc123" in r.stdout


def test_e2e_kwargs_handler_with_global_flags():
    """Command with **kwargs handler receives global flag values."""
    app = strictcli.App(
        name="kw",
        version="1.0.0",
        help="kwargs test app",
        flags=[
            strictcli.Flag(name="verbose", type=bool, help="verbose output"),
        ],
    )

    @app.command("run", help="run something")
    def run_handler(**kwargs):
        print(f"verbose={kwargs['verbose']}")
        return 0

    r = app.test(["--verbose", "run"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


def test_e2e_kwargs_handler_registration_no_error():
    """Registering a command with **kwargs handler does not raise on missing/extra params."""
    app = strictcli.App(name="kw", version="1.0.0", help="kwargs test app")

    # This should not raise ValueError even though the handler has no named params
    @app.command(
        "cmd",
        help="a command",
        args=[strictcli.Arg(name="name", help="a name")],
    )
    @strictcli.flag("count", type=int, help="a count", default=0)
    @strictcli.flag("force", type=bool, help="force it")
    def cmd_handler(**kwargs):
        return 0

    r = app.test(["cmd", "--count", "5", "hello"])
    assert r.exit_code == 0
