"""Tests for CheckResult, CheckContext, and _CheckDef types."""

from pathlib import Path

import pytest

from strictcli import CheckResult, CheckContext


class TestCheckResult:
    def test_valid_status_pass(self):
        r = CheckResult(status="pass", message="All good")
        assert r.status == "pass"
        assert r.message == "All good"

    def test_valid_status_fail(self):
        r = CheckResult(status="fail", message="Something broke")
        assert r.status == "fail"

    def test_valid_status_warn(self):
        r = CheckResult(status="warn", message="Heads up")
        assert r.status == "warn"

    def test_valid_status_skip(self):
        r = CheckResult(status="skip", message="Not applicable")
        assert r.status == "skip"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="must be one of"):
            CheckResult(status="error", message="Bad")

    def test_empty_message_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            CheckResult(status="pass", message="")

    def test_whitespace_message_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            CheckResult(status="pass", message="   ")

    def test_non_string_message_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            CheckResult(status="pass", message=42)  # type: ignore[arg-type]

    def test_default_details_is_empty_list(self):
        r = CheckResult(status="pass", message="OK")
        assert r.details == []

    def test_details_with_values(self):
        r = CheckResult(status="fail", message="Issues", details=["a", "b"])
        assert r.details == ["a", "b"]

    def test_details_independent_between_instances(self):
        r1 = CheckResult(status="pass", message="OK")
        r2 = CheckResult(status="pass", message="OK")
        r1.details.append("x")
        assert r2.details == []


class TestCheckContext:
    def test_class_with_project_root_satisfies_protocol(self):
        class MyContext:
            def __init__(self):
                self.project_root = Path("/some/path")

        ctx = MyContext()
        assert isinstance(ctx, CheckContext)

    def test_class_without_project_root_does_not_satisfy(self):
        class BadContext:
            pass

        ctx = BadContext()
        assert not isinstance(ctx, CheckContext)
