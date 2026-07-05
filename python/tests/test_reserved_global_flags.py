"""Tests for reserved global flag name enforcement."""

import pytest

import strictcli


class TestReservedGlobalFlagNames:
    """App() must reject global flags whose name collides with a reserved name."""

    @pytest.mark.parametrize("name", ["help", "version", "dump-schema", "mcp"])
    def test_reserved_name_rejected(self, name: str) -> None:
        with pytest.raises(ValueError, match="reserved"):
            strictcli.App(
                name="testapp",
                version="1.0.0",
                help="test",
                flags=[strictcli.Flag(name=name, type=str, help="test flag")],
            )

    @pytest.mark.parametrize("short", ["h", "v"])
    def test_reserved_short_rejected(self, short: str) -> None:
        with pytest.raises(ValueError, match="reserved"):
            strictcli.App(
                name="testapp",
                version="1.0.0",
                help="test",
                flags=[
                    strictcli.Flag(
                        name="custom", type=str, help="test flag", short=short
                    )
                ],
            )

    def test_non_reserved_allowed(self) -> None:
        """Non-reserved names must register without error."""
        app = strictcli.App(
            name="testapp",
            version="1.0.0",
            help="test",
            flags=[
                strictcli.Flag(
                    name="verbose", type=bool, help="enable verbose", default=False
                ),
                strictcli.Flag(name="output", type=str, help="output file"),
            ],
        )
        assert len(app.flags) == 2
