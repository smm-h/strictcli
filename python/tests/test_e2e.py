"""End-to-end tests with a realistic rlsbl-like app."""

import strictcli


def _build_rlsbl_app():
    """Build a mini rlsbl-like CLI app with commands, groups, tags, and env vars."""
    auth_tag = strictcli.Tag(
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
    @app.command("status", help="show release status", tags=[auth_tag])
    def status(token):
        print(f"status: token={'set' if token else 'unset'}")

    @app.command(
        "release",
        help="create a new release",
        args=[strictcli.Arg(name="bump", help="version bump type")],
        tags=[auth_tag],
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
