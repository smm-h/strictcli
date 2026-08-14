"""Stacked @strictcli.arg decorators bind in top-down declaration order.

Python applies decorators bottom-to-top, so the list a handler accumulates is
in reverse declaration order. The registration path must undo that for args
exactly as it does for flags -- otherwise argv binds to the wrong names and
help lists the arguments backwards.
"""

import strictcli


def _app():
    return strictcli.App(name="test", version="1.0.0", help="test app")


def test_two_stacked_args_bind_top_down():
    app = _app()

    @app.command("deploy", effect="read_only", help="deploy something")
    @strictcli.arg("environment", help="target environment", presence="required")
    @strictcli.arg("version", help="version to deploy", presence="required")
    def deploy(ctx, environment, version):
        print(f"environment={environment} version={version}")

    r = app.test(["deploy", "prod", "1.2.3"])
    assert r.exit_code == 0
    assert "environment=prod version=1.2.3" in r.stdout


def test_two_stacked_args_appear_in_declaration_order_in_help():
    app = _app()

    @app.command("deploy", effect="read_only", help="deploy something")
    @strictcli.arg("environment", help="target environment", presence="required")
    @strictcli.arg("version", help="version to deploy", presence="required")
    def deploy(ctx, environment, version):
        pass

    r = app.test(["deploy", "--help"])
    assert r.exit_code == 0
    assert r.stdout.index("environment") < r.stdout.index("version")


def test_three_stacked_args_bind_top_down():
    app = _app()

    @app.command("copy", effect="read_only", help="copy something")
    @strictcli.arg("source", help="source path", presence="required")
    @strictcli.arg("dest", help="destination path", presence="required")
    @strictcli.arg("mode", help="copy mode", presence="required")
    def copy(ctx, source, dest, mode):
        print(f"source={source} dest={dest} mode={mode}")

    r = app.test(["copy", "a", "b", "fast"])
    assert r.exit_code == 0
    assert "source=a dest=b mode=fast" in r.stdout


def test_three_stacked_args_appear_in_declaration_order_in_help():
    app = _app()

    @app.command("copy", effect="read_only", help="copy something")
    @strictcli.arg("source", help="source path", presence="required")
    @strictcli.arg("dest", help="destination path", presence="required")
    @strictcli.arg("mode", help="copy mode", presence="required")
    def copy(ctx, source, dest, mode):
        pass

    r = app.test(["copy", "--help"])
    assert r.exit_code == 0
    assert r.stdout.index("source") < r.stdout.index("dest") < r.stdout.index("mode")


def test_stacked_args_match_the_equivalent_args_list_form():
    """The decorator form and the args=[...] list form must agree."""
    listed = _app()

    @listed.command(
        "deploy",
        effect="read_only",
        help="deploy something",
        args=[
            strictcli.Arg(name="environment", help="target environment", presence="required"),
            strictcli.Arg(name="version", help="version to deploy", presence="required"),
        ],
    )
    def deploy_listed(ctx, environment, version):
        print(f"environment={environment} version={version}")

    stacked = _app()

    @stacked.command("deploy", effect="read_only", help="deploy something")
    @strictcli.arg("environment", help="target environment", presence="required")
    @strictcli.arg("version", help="version to deploy", presence="required")
    def deploy_stacked(ctx, environment, version):
        print(f"environment={environment} version={version}")

    argv = ["deploy", "prod", "1.2.3"]
    assert listed.test(argv).stdout == stacked.test(argv).stdout


def test_stacked_args_and_flags_both_bind_top_down():
    """Args and flags declared together each keep declaration order."""
    app = _app()

    @app.command("run", effect="read_only", help="run something")
    @strictcli.flag("alpha", type=str, help="alpha", presence="optional")
    @strictcli.flag("beta", type=str, help="beta", presence="optional")
    @strictcli.arg("first", help="first arg", presence="required")
    @strictcli.arg("second", help="second arg", presence="required")
    def run(ctx, alpha, beta, first, second):
        print(f"first={first} second={second}")

    r = app.test(["run", "one", "two"])
    assert r.exit_code == 0
    assert "first=one second=two" in r.stdout

    h = app.test(["run", "--help"])
    assert h.stdout.index("--alpha") < h.stdout.index("--beta")
    assert h.stdout.index("first") < h.stdout.index("second")
