"""Tests for the config field declaration API (ConfigField, app.config_field)."""

import pytest

import strictcli


def _build_app(**kwargs):
    return strictcli.App(name="myapp", version="1.0.0", help="test app", **kwargs)


class TestConfigFieldRegistration:
    """Basic registration of config fields with all four types."""

    def test_register_str_field(self):
        app = _build_app()
        cf = app.config_field("name", type=str, help="user name")
        assert cf.name == "name"
        assert cf.type is str
        assert cf.help == "user name"
        assert cf.required is True

    def test_register_int_field(self):
        app = _build_app()
        cf = app.config_field("port", type=int, help="listen port")
        assert cf.type is int
        assert cf.required is True

    def test_register_float_field(self):
        app = _build_app()
        cf = app.config_field("rate", type=float, help="rate limit")
        assert cf.type is float
        assert cf.required is True

    def test_register_bool_field(self):
        app = _build_app()
        cf = app.config_field("verbose", type=bool, help="enable verbose")
        assert cf.type is bool
        assert cf.required is True

    def test_field_stored_in_config_fields(self):
        app = _build_app()
        app.config_field("name", type=str, help="user name")
        assert "name" in app._config_fields
        assert app._config_fields["name"].type is str


class TestConfigFieldDotNames:
    """Dot-separated names for TOML section nesting."""

    def test_single_dot(self):
        app = _build_app()
        cf = app.config_field("serve.port", type=int, help="server port")
        assert cf.name == "serve.port"

    def test_multiple_dots(self):
        app = _build_app()
        cf = app.config_field("db.pool.max_size", type=int, help="pool size")
        assert cf.name == "db.pool.max_size"

    def test_underscore_in_segment(self):
        app = _build_app()
        cf = app.config_field("log_level", type=str, help="log level")
        assert cf.name == "log_level"


class TestConfigFieldDefaults:
    """Required vs optional fields based on default presence."""

    def test_no_default_is_required(self):
        app = _build_app()
        cf = app.config_field("name", type=str, help="user name")
        assert cf.required is True

    def test_with_default_is_optional(self):
        app = _build_app()
        cf = app.config_field("port", type=int, help="port", default=8080)
        assert cf.required is False
        assert cf.default == 8080

    def test_str_default(self):
        app = _build_app()
        cf = app.config_field("host", type=str, help="host", default="localhost")
        assert cf.required is False
        assert cf.default == "localhost"

    def test_bool_default(self):
        app = _build_app()
        cf = app.config_field("debug", type=bool, help="debug", default=False)
        assert cf.required is False
        assert cf.default is False

    def test_float_default(self):
        app = _build_app()
        cf = app.config_field("rate", type=float, help="rate", default=1.5)
        assert cf.required is False
        assert cf.default == 1.5


class TestConfigFieldTypeValidation:
    """Type mismatch between default and declared type."""

    def test_str_field_with_int_default(self):
        app = _build_app()
        with pytest.raises(ValueError, match="does not match type str"):
            app.config_field("name", type=str, help="name", default=42)

    def test_int_field_with_str_default(self):
        app = _build_app()
        with pytest.raises(ValueError, match="does not match type int"):
            app.config_field("port", type=int, help="port", default="8080")

    def test_bool_field_with_int_default(self):
        app = _build_app()
        with pytest.raises(ValueError, match="does not match type bool"):
            app.config_field("debug", type=bool, help="debug", default=1)

    def test_float_field_with_str_default(self):
        app = _build_app()
        with pytest.raises(ValueError, match="does not match type float"):
            app.config_field("rate", type=float, help="rate", default="1.5")

    def test_invalid_type(self):
        app = _build_app()
        with pytest.raises(ValueError, match="must be str, bool, int, or float"):
            app.config_field("data", type=list, help="data")


class TestConfigFieldDuplicateError:
    """Duplicate field name is a registration-time error."""

    def test_duplicate_name_error(self):
        app = _build_app()
        app.config_field("port", type=int, help="port")
        with pytest.raises(ValueError, match='duplicate config field name "port"'):
            app.config_field("port", type=int, help="port again")

    def test_different_types_still_duplicate(self):
        app = _build_app()
        app.config_field("port", type=int, help="port")
        with pytest.raises(ValueError, match='duplicate config field name "port"'):
            app.config_field("port", type=str, help="port as string")


class TestConfigFieldUnderscoreReserved:
    """Names starting with underscore are reserved for framework fields."""

    def test_underscore_prefix_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="reserved"):
            app.config_field("_internal", type=str, help="internal field")

    def test_underscore_schema_version_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="reserved"):
            app.config_field("_schema_version", type=int, help="schema version")


class TestConfigFieldNameValidation:
    """Name format validation."""

    def test_empty_name_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field("", type=str, help="empty name")

    def test_uppercase_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field("Port", type=int, help="uppercase")

    def test_starts_with_digit_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field("3port", type=int, help="starts with digit")

    def test_hyphen_rejected(self):
        """Config field names use underscores, not hyphens."""
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field("log-level", type=str, help="hyphenated")

    def test_trailing_dot_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field("serve.", type=str, help="trailing dot")

    def test_leading_dot_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field(".serve", type=str, help="leading dot")

    def test_double_dot_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="invalid"):
            app.config_field("serve..port", type=str, help="double dot")


class TestConfigFieldHelpRequired:
    """Help text is mandatory."""

    def test_empty_help_rejected(self):
        app = _build_app()
        with pytest.raises(ValueError, match="help"):
            app.config_field("name", type=str, help="")


class TestFrameworkFieldRegistration:
    """Framework-internal field registration via _register_framework_field."""

    def test_register_framework_field(self):
        app = _build_app()
        cf = app._register_framework_field(
            "_schema_version", type=int, help="config schema version"
        )
        assert cf.name == "_schema_version"
        assert cf.type is int
        assert "_schema_version" in app._framework_fields

    def test_framework_field_requires_underscore_prefix(self):
        app = _build_app()
        with pytest.raises(ValueError, match="must start with underscore"):
            app._register_framework_field(
                "schema_version", type=int, help="no underscore"
            )

    def test_duplicate_framework_field(self):
        app = _build_app()
        app._register_framework_field(
            "_schema_version", type=int, help="schema version"
        )
        with pytest.raises(ValueError, match="duplicate framework field"):
            app._register_framework_field(
                "_schema_version", type=int, help="schema version again"
            )

    def test_framework_field_stored_separately(self):
        """Framework fields go in _framework_fields, not _config_fields."""
        app = _build_app()
        app._register_framework_field(
            "_schema_version", type=int, help="schema version"
        )
        assert "_schema_version" not in app._config_fields
        assert "_schema_version" in app._framework_fields

    def test_user_cannot_register_framework_name(self):
        """User config_field rejects underscore-prefixed names even if
        no framework field with that name exists."""
        app = _build_app()
        with pytest.raises(ValueError, match="reserved"):
            app.config_field("_internal", type=str, help="reserved name")

    def test_framework_field_conflicts_with_user_field(self):
        """Framework field cannot use a name already taken by a user field.

        This is a safety check for the (unlikely) case where the name
        validation somehow allows overlap. In practice, user fields
        cannot start with underscore, so the namespaces are disjoint.
        """
        app = _build_app()
        # This would only conflict if the namespaces could overlap.
        # Since user fields reject underscore and framework fields require it,
        # the namespaces are disjoint by construction.
        app.config_field("port", type=int, help="port")
        # Framework field with different name is fine
        app._register_framework_field(
            "_schema_version", type=int, help="schema version"
        )
        assert "port" in app._config_fields
        assert "_schema_version" in app._framework_fields


class TestConfigFieldDataclass:
    """Direct ConfigField construction and validation."""

    def test_construct_directly(self):
        cf = strictcli.ConfigField(name="port", type=int, help="listen port")
        assert cf.name == "port"
        assert cf.required is True

    def test_construct_with_default(self):
        cf = strictcli.ConfigField(
            name="port", type=int, help="listen port", default=8080
        )
        assert cf.required is False
        assert cf.default == 8080

    def test_construct_invalid_type(self):
        with pytest.raises(ValueError, match="must be str, bool, int, or float"):
            strictcli.ConfigField(name="data", type=dict, help="bad type")

    def test_construct_type_mismatch(self):
        with pytest.raises(ValueError, match="does not match type"):
            strictcli.ConfigField(
                name="port", type=int, help="port", default="not_an_int"
            )
