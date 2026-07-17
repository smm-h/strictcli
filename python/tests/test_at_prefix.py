"""Tests for @-prefix feature: read flag values from files, stdin, or escape."""

import io

import strictcli


def _make_app():
    """Helper: app with a str flag on a command."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, help="message")
    def cmd(ctx, msg):
        print(f"msg={msg}")

    return app


def _make_two_str_flags_app():
    """Helper: app with two str flags on a command."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("first", type=str, help="first value")
    @strictcli.flag("second", type=str, help="second value")
    def cmd(ctx, first, second):
        print(f"first={first}")
        print(f"second={second}")

    return app


def _make_global_and_cmd_str_app():
    """Helper: app with a global str flag and a command str flag."""
    app = strictcli.App(
        name="test", version="1.0.0", help="test app",
        flags=[strictcli.Flag(name="token", type=str, help="auth token", default="none")],
    )

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, help="message")
    def cmd(ctx, msg, token):
        print(f"msg={msg}")
        print(f"token={token}")

    return app


# --- @file basic ---

def test_at_file_basic(tmp_path):
    """Flag value read from file, trailing whitespace stripped."""
    f = tmp_path / "data.txt"
    f.write_text("hello world")
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 0
    assert "msg=hello world" in r.stdout


def test_at_file_multiline(tmp_path):
    """File with multiple lines: only trailing whitespace stripped, internal newlines preserved."""
    f = tmp_path / "data.txt"
    f.write_text("line one\nline two\nline three\n")
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 0
    assert "msg=line one\nline two\nline three" in r.stdout


def test_at_file_trailing_whitespace_strip(tmp_path):
    """File ending with mixed trailing whitespace has it all stripped."""
    f = tmp_path / "data.txt"
    f.write_text("content\n\n  \t\n")
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 0
    assert "msg=content" in r.stdout


def test_at_file_trim_matches_go_cutset(tmp_path):
    """@-file trailing trim must match Go's TrimRight cutset (only ' \\t\\n\\r').

    Go trims a fixed ASCII cutset, not the broader Unicode whitespace set that
    Python's bare str.rstrip() would remove. Vertical tab and form feed are NOT
    in Go's cutset and must be preserved; a trailing newline IS trimmed.
    """
    f = tmp_path / "data.txt"
    f.write_text("content\v\f\n")
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 0
    assert r.stdout == "msg=content\v\f\n"


def test_at_file_trim_removes_ascii_cutset(tmp_path):
    """Only the Go cutset chars (space, tab, CR, LF) are trimmed from the tail."""
    f = tmp_path / "data.txt"
    f.write_text("content \t\r\n")
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 0
    assert "msg=content" in r.stdout


def test_at_file_empty(tmp_path):
    """Empty file yields empty string."""
    f = tmp_path / "data.txt"
    f.write_text("")
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 0
    assert "msg=" in r.stdout


def test_at_file_equals_form(tmp_path):
    """@file works with --flag=@path form."""
    f = tmp_path / "data.txt"
    f.write_text("from-file")
    app = _make_app()
    r = app.test(["cmd", f"--msg=@{f}"])
    assert r.exit_code == 0
    assert "msg=from-file" in r.stdout


# --- @- stdin ---

def test_at_stdin(monkeypatch):
    """Flag value read from stdin."""
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin\n"))
    app = _make_app()
    r = app.test(["cmd", "--msg", "@-"])
    assert r.exit_code == 0
    assert "msg=from stdin" in r.stdout


def test_at_stdin_trailing_whitespace(monkeypatch):
    """Stdin content has trailing whitespace stripped."""
    monkeypatch.setattr("sys.stdin", io.StringIO("data\n\n  \n"))
    app = _make_app()
    r = app.test(["cmd", "--msg", "@-"])
    assert r.exit_code == 0
    assert "msg=data" in r.stdout


# --- @@ escape ---

def test_at_escape():
    """@@foo becomes @foo."""
    app = _make_app()
    r = app.test(["cmd", "--msg", "@@foo"])
    assert r.exit_code == 0
    assert "msg=@foo" in r.stdout


def test_at_escape_double():
    """@@@ becomes @@."""
    app = _make_app()
    r = app.test(["cmd", "--msg", "@@@"])
    assert r.exit_code == 0
    assert "msg=@@" in r.stdout


def test_at_escape_equals_form():
    """@@literal works with --flag=@@literal form."""
    app = _make_app()
    r = app.test(["cmd", "--msg=@@literal"])
    assert r.exit_code == 0
    assert "msg=@literal" in r.stdout


# --- Error cases ---

def test_at_file_not_found():
    """File not found produces correct error message."""
    app = _make_app()
    r = app.test(["cmd", "--msg", "@/nonexistent/path.txt"])
    assert r.exit_code == 1
    assert "--msg: file not found: /nonexistent/path.txt" in r.stderr


def test_at_file_too_large(tmp_path):
    """File exceeding 1 MB limit produces correct error message."""
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * (1024 * 1024 + 1))
    app = _make_app()
    r = app.test(["cmd", "--msg", f"@{f}"])
    assert r.exit_code == 1
    assert "--msg: file exceeds 1 MB limit" in r.stderr


def test_at_stdin_duplicate(monkeypatch):
    """Two flags both using @- produces an error on the second."""
    monkeypatch.setattr("sys.stdin", io.StringIO("data"))
    app = _make_two_str_flags_app()
    r = app.test(["cmd", "--first", "@-", "--second", "@-"])
    assert r.exit_code == 1
    assert "--second: stdin (@-) can only be used once per invocation" in r.stderr


def test_at_stdin_duplicate_across_global_and_command(monkeypatch):
    """Global flag uses @-, command flag tries @- -- error on the second."""
    monkeypatch.setattr("sys.stdin", io.StringIO("data"))
    app = _make_global_and_cmd_str_app()
    r = app.test(["--token", "@-", "cmd", "--msg", "@-"])
    assert r.exit_code == 1
    assert "--msg: stdin (@-) can only be used once per invocation" in r.stderr


# --- Non-string flags ignore @ ---

def test_int_flag_ignores_at_prefix():
    """@5 with int flag does NOT try to read a file -- it fails as invalid int."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("count", type=int, help="count")
    def cmd(ctx, count):
        print(f"count={count}")

    r = app.test(["cmd", "--count", "@5"])
    assert r.exit_code == 1
    assert "expected integer" in r.stderr


def test_float_flag_ignores_at_prefix():
    """@1.5 with float flag does NOT try to read a file."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("rate", type=float, help="rate")
    def cmd(ctx, rate):
        print(f"rate={rate}")

    r = app.test(["cmd", "--rate", "@1.5"])
    assert r.exit_code == 1
    assert "expected float" in r.stderr


def test_bool_flag_ignores_at_prefix():
    """Bool flags are unaffected by @ prefix (they don't take values)."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("verbose", type=bool, default=False, help="verbose")
    def cmd(ctx, verbose):
        print(f"verbose={verbose}")

    r = app.test(["cmd", "--verbose"])
    assert r.exit_code == 0
    assert "verbose=True" in r.stdout


# --- Env var with @ ---

def test_env_var_at_file(tmp_path, monkeypatch):
    """Env var value @/path/to/file reads the file."""
    f = tmp_path / "secret.txt"
    f.write_text("env-secret-value\n")
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, help="message", default="fallback", env="TEST_MSG")
    def cmd(ctx, msg):
        print(f"msg={msg}")

    monkeypatch.setenv("TEST_MSG", f"@{f}")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "msg=env-secret-value" in r.stdout


def test_env_var_at_stdin(monkeypatch):
    """Env var value @- reads stdin."""
    monkeypatch.setattr("sys.stdin", io.StringIO("from-stdin-env"))
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, help="message", default="fallback", env="TEST_MSG")
    def cmd(ctx, msg):
        print(f"msg={msg}")

    monkeypatch.setenv("TEST_MSG", "@-")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "msg=from-stdin-env" in r.stdout


def test_env_var_at_escape(monkeypatch):
    """Env var value @@literal becomes @literal."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, help="message", default="fallback", env="TEST_MSG")
    def cmd(ctx, msg):
        print(f"msg={msg}")

    monkeypatch.setenv("TEST_MSG", "@@literal")
    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "msg=@literal" in r.stdout


# --- Short form flags ---

def test_at_file_short_flag(tmp_path):
    """@file works with -m short form."""
    f = tmp_path / "data.txt"
    f.write_text("short-form-value")
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, short="m", help="message")
    def cmd(ctx, msg):
        print(f"msg={msg}")

    r = app.test(["cmd", "-m", f"@{f}"])
    assert r.exit_code == 0
    assert "msg=short-form-value" in r.stdout


# --- Global flag @-prefix ---

def test_global_flag_at_file(tmp_path):
    """@file works for global flags."""
    f = tmp_path / "token.txt"
    f.write_text("secret-token\n")
    app = _make_global_and_cmd_str_app()
    r = app.test(["--token", f"@{f}", "cmd", "--msg", "hello"])
    assert r.exit_code == 0
    assert "token=secret-token" in r.stdout
    assert "msg=hello" in r.stdout


def test_global_flag_at_escape():
    """@@literal works for global flags."""
    app = _make_global_and_cmd_str_app()
    r = app.test(["--token", "@@at-sign", "cmd", "--msg", "hello"])
    assert r.exit_code == 0
    assert "token=@at-sign" in r.stdout


# --- No @-prefix on default or config values ---

def test_default_value_not_resolved():
    """Default values are NOT subject to @-prefix resolution."""
    app = strictcli.App(name="test", version="1.0.0", help="test app")

    @app.command("cmd", help="a command")
    @strictcli.flag("msg", type=str, help="message", default="@some-file")
    def cmd(ctx, msg):
        print(f"msg={msg}")

    r = app.test(["cmd"])
    assert r.exit_code == 0
    assert "msg=@some-file" in r.stdout


# --- Plain values (no prefix) ---

def test_plain_value_unchanged():
    """Values without @ prefix are used as-is."""
    app = _make_app()
    r = app.test(["cmd", "--msg", "plain-value"])
    assert r.exit_code == 0
    assert "msg=plain-value" in r.stdout
