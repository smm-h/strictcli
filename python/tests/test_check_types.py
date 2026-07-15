"""Tests for the ceiling-typed check outcome core: reporters, outcomes, context."""

from pathlib import Path

import pytest

from strictcli import CheckContext, CheckRunResult, ErrorReporter, WarnReporter
from strictcli import _CheckOutcome, _MINT_TOKEN, _derive_status


class TestReporterMinting:
    def test_passed_derives_pass(self):
        outcome = ErrorReporter().passed("all good")
        assert _derive_status(outcome) == "pass"
        assert outcome.message == "all good"
        assert outcome.problems == ()

    def test_skipped_derives_skip(self):
        outcome = WarnReporter().skipped("not applicable")
        assert _derive_status(outcome) == "skip"

    def test_found_with_error_derives_fail(self):
        r = ErrorReporter()
        r.error("something broke")
        outcome = r.found("failures found")
        assert _derive_status(outcome) == "fail"
        assert len(outcome.problems) == 1
        assert outcome.problems[0].severity == "error"

    def test_found_with_only_warns_derives_warn(self):
        r = WarnReporter()
        r.warn("heads up")
        outcome = r.found("warnings found")
        assert _derive_status(outcome) == "warn"

    def test_mixed_problems_derive_fail_and_order_errors_first(self):
        r = ErrorReporter()
        r.warn("a warning")
        r.error("an error")
        outcome = r.found("mixed")
        assert _derive_status(outcome) == "fail"
        ordered = outcome._ordered_problems()
        assert [p.severity for p in ordered] == ["error", "warn"]

    def test_passed_after_problem_raises(self):
        r = ErrorReporter()
        r.error("x")
        with pytest.raises(ValueError, match="cannot pass"):
            r.passed("all good")

    def test_skipped_after_problem_raises(self):
        r = WarnReporter()
        r.warn("x")
        with pytest.raises(ValueError, match="cannot skip"):
            r.skipped("n/a")

    def test_empty_found_raises(self):
        with pytest.raises(ValueError, match="use passed"):
            ErrorReporter().found("nothing")

    @pytest.mark.parametrize("bad", ["", "   ", 42])
    def test_empty_or_nonstring_inputs_raise(self, bad):
        with pytest.raises(ValueError, match="non-empty string"):
            ErrorReporter().passed(bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="non-empty string"):
            ErrorReporter().error(bad)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="non-empty string"):
            WarnReporter().warn(bad)  # type: ignore[arg-type]

    def test_warn_reporter_lacks_error(self):
        # Structural guarantee: WarnReporter has no error() method (mypy error
        # + runtime AttributeError). A warn check cannot mint an error problem.
        assert not hasattr(WarnReporter(), "error")
        with pytest.raises(AttributeError):
            WarnReporter().error("nope")  # type: ignore[attr-defined]

    def test_error_reporter_has_error(self):
        assert hasattr(ErrorReporter(), "error")

    def test_outcome_cannot_be_constructed_directly(self):
        with pytest.raises(TypeError, match="cannot be constructed directly"):
            _CheckOutcome(kind="passed", message="x")

    def test_outcome_mint_token_seals_construction(self):
        # Even with the internal token, construction is possible (that is the
        # intended mint path), proving the guard keys on the token.
        outcome = _CheckOutcome(kind="passed", message="x", _token=_MINT_TOKEN)
        assert outcome.kind == "passed"


class TestCheckRunResultAccessors:
    def test_pass_accessors(self):
        r = CheckRunResult(name="c", outcome=ErrorReporter().passed("ok"))
        assert r.status == "pass"
        assert r.message == "ok"
        assert r.gated() is False
        assert r.warned() is False

    def test_fail_accessors(self):
        rep = ErrorReporter()
        rep.error("boom")
        r = CheckRunResult(name="c", outcome=rep.found("bad"))
        assert r.status == "fail"
        assert r.gated() is True
        assert r.warned() is False

    def test_warn_accessors(self):
        rep = WarnReporter()
        rep.warn("hmm")
        r = CheckRunResult(name="c", outcome=rep.found("soft"))
        assert r.status == "warn"
        assert r.gated() is False
        assert r.warned() is True


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
