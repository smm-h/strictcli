"""Tests for _load_checks_toml TOML loading and validation."""

import pytest

from strictcli import _CheckDef
from strictcli import _load_checks_toml


VALID_TOML = """\
[checks.lint-code]
tags = ["code", "fast"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []

[checks.check-deps]
tags = ["deps"]
severity = "warn"
fast = false
pure = false
needs_network = true
depends_on = ["lint-code"]
"""


class TestLoadChecksToml:
    def test_valid_toml_multiple_checks(self, tmp_path):
        f = tmp_path / "checks.toml"
        f.write_text(VALID_TOML)
        result = _load_checks_toml(f)
        assert len(result) == 2
        assert "lint-code" in result
        assert "check-deps" in result

        lint = result["lint-code"]
        assert isinstance(lint, _CheckDef)
        assert lint.name == "lint-code"
        assert lint.tags == ["code", "fast"]
        assert lint.severity == "error"
        assert lint.fast is True
        assert lint.pure is True
        assert lint.needs_network is False
        assert lint.depends_on == []
        assert lint.impl is None

        deps = result["check-deps"]
        assert deps.depends_on == ["lint-code"]
        assert deps.needs_network is True

    def test_missing_required_field(self, tmp_path):
        toml = """\
[checks.my-check]
tags = ["a"]
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='missing required field "severity"'):
            _load_checks_toml(f)

    def test_wrong_type_string_where_bool_expected(self, tmp_path):
        toml = """\
[checks.my-check]
tags = ["a"]
severity = "error"
fast = "yes"
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='"fast" must be a boolean'):
            _load_checks_toml(f)

    def test_unknown_field(self, tmp_path):
        toml = """\
[checks.my-check]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
extra = "nope"
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='unknown field "extra"'):
            _load_checks_toml(f)

    def test_unknown_top_level_key(self, tmp_path):
        toml = """\
[metadata]
version = "1.0"

[checks.my-check]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='unknown top-level key "metadata"'):
            _load_checks_toml(f)

    def test_invalid_check_name_uppercase(self, tmp_path):
        toml = """\
[checks.MyCheck]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='invalid check name "MyCheck"'):
            _load_checks_toml(f)

    def test_invalid_check_name_dots(self, tmp_path):
        toml = """\
[checks."my.check"]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match="invalid check name"):
            _load_checks_toml(f)

    def test_invalid_check_name_spaces(self, tmp_path):
        toml = """\
[checks."my check"]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match="invalid check name"):
            _load_checks_toml(f)

    def test_depends_on_nonexistent_check(self, tmp_path):
        toml = """\
[checks.my-check]
tags = ["a"]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = ["nonexistent"]
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='depends_on references unknown check "nonexistent"'):
            _load_checks_toml(f)

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "checks.toml"
        f.write_text("")
        result = _load_checks_toml(f)
        assert result == {}

    def test_invalid_toml_syntax(self, tmp_path):
        f = tmp_path / "checks.toml"
        f.write_text("[checks.foo\n  this is not valid toml")
        with pytest.raises(ValueError, match="checks.toml:"):
            _load_checks_toml(f)

    def test_invalid_severity_value(self, tmp_path):
        toml = """\
[checks.my-check]
tags = ["a"]
severity = "critical"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='"severity" must be "error" or "warn"'):
            _load_checks_toml(f)

    def test_tags_empty_list(self, tmp_path):
        toml = """\
[checks.my-check]
tags = []
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='"tags" must be a non-empty list'):
            _load_checks_toml(f)

    def test_tags_with_empty_string(self, tmp_path):
        toml = """\
[checks.my-check]
tags = [""]
severity = "error"
fast = true
pure = true
needs_network = false
depends_on = []
"""
        f = tmp_path / "checks.toml"
        f.write_text(toml)
        with pytest.raises(ValueError, match='"tags" entries must be non-empty strings'):
            _load_checks_toml(f)

    def test_file_not_found(self, tmp_path):
        f = tmp_path / "nonexistent.toml"
        with pytest.raises(ValueError, match="checks.toml:"):
            _load_checks_toml(f)
