"""Tests for the tag DSL tokenizer, parser, and evaluator."""

import pytest

from strictcli import _match_tag_expr, _tagdsl_tokenize, _tagdsl_parse, _tagdsl_evaluate


class TestSimpleMatches:
    def test_single_tag_matches(self):
        assert _match_tag_expr("release", {"release"}) is True

    def test_single_tag_not_present(self):
        assert _match_tag_expr("release", {"changelog"}) is False

    def test_single_tag_empty_set(self):
        assert _match_tag_expr("release", set()) is False


class TestAnd:
    def test_both_present(self):
        assert _match_tag_expr("release & fast", {"release", "fast"}) is True

    def test_one_missing(self):
        assert _match_tag_expr("release & fast", {"release"}) is False

    def test_neither_present(self):
        assert _match_tag_expr("release & fast", {"other"}) is False


class TestOr:
    def test_first_present(self):
        assert _match_tag_expr("release | changelog", {"release"}) is True

    def test_second_present(self):
        assert _match_tag_expr("release | changelog", {"changelog"}) is True

    def test_both_present(self):
        assert _match_tag_expr("release | changelog", {"release", "changelog"}) is True

    def test_neither_present(self):
        assert _match_tag_expr("release | changelog", {"other"}) is False


class TestNot:
    def test_not_absent(self):
        assert _match_tag_expr("!slow", {"fast"}) is True

    def test_not_present(self):
        assert _match_tag_expr("!slow", {"slow"}) is False

    def test_not_empty_set(self):
        assert _match_tag_expr("!slow", set()) is True


class TestXor:
    def test_first_only(self):
        assert _match_tag_expr("a ^ b", {"a"}) is True

    def test_second_only(self):
        assert _match_tag_expr("a ^ b", {"b"}) is True

    def test_both_present(self):
        assert _match_tag_expr("a ^ b", {"a", "b"}) is False

    def test_neither_present(self):
        assert _match_tag_expr("a ^ b", set()) is False


class TestDiff:
    def test_left_without_right(self):
        assert _match_tag_expr("release - slow", {"release"}) is True

    def test_both_present(self):
        assert _match_tag_expr("release - slow", {"release", "slow"}) is False

    def test_right_only(self):
        assert _match_tag_expr("release - slow", {"slow"}) is False

    def test_neither(self):
        assert _match_tag_expr("release - slow", set()) is False


class TestPrecedence:
    def test_and_binds_tighter_than_or(self):
        # "a | b & c" should parse as "a | (b & c)"
        # With tags {"a"}: a=True, b&c=False, so a | False = True
        assert _match_tag_expr("a | b & c", {"a"}) is True
        # With tags {"b", "c"}: a=False, b&c=True, so False | True = True
        assert _match_tag_expr("a | b & c", {"b", "c"}) is True
        # With tags {"b"}: a=False, b&c=False, so False | False = False
        assert _match_tag_expr("a | b & c", {"b"}) is False


class TestParentheses:
    def test_parens_override_precedence(self):
        # "(a | b) & c" requires c to be present
        assert _match_tag_expr("(a | b) & c", {"a", "c"}) is True
        assert _match_tag_expr("(a | b) & c", {"a"}) is False
        assert _match_tag_expr("(a | b) & c", {"b", "c"}) is True
        assert _match_tag_expr("(a | b) & c", {"c"}) is False


class TestComplex:
    def test_release_or_changelog_and_not_slow(self):
        expr = "(release | changelog) & !slow"
        assert _match_tag_expr(expr, {"release", "fast"}) is True
        assert _match_tag_expr(expr, {"release", "slow"}) is False
        assert _match_tag_expr(expr, {"changelog"}) is True
        assert _match_tag_expr(expr, {"changelog", "slow"}) is False
        assert _match_tag_expr(expr, {"other"}) is False

    def test_nested_parens(self):
        expr = "((a & b) | (c & d))"
        assert _match_tag_expr(expr, {"a", "b"}) is True
        assert _match_tag_expr(expr, {"c", "d"}) is True
        assert _match_tag_expr(expr, {"a", "c"}) is False

    def test_double_not(self):
        assert _match_tag_expr("!!a", {"a"}) is True
        assert _match_tag_expr("!!a", set()) is False


class TestErrors:
    def test_empty_expression(self):
        with pytest.raises(ValueError, match="empty expression"):
            _match_tag_expr("", {"a"})

    def test_whitespace_only_expression(self):
        with pytest.raises(ValueError, match="empty expression"):
            _match_tag_expr("   ", {"a"})

    def test_unexpected_character(self):
        with pytest.raises(ValueError, match='unexpected character "\\$" at position 0'):
            _match_tag_expr("$bad", {"a"})

    def test_unexpected_character_mid_expr(self):
        with pytest.raises(ValueError, match='unexpected character "@" at position 2'):
            _match_tag_expr("a @b", {"a"})

    def test_mismatched_parenthesis_open(self):
        with pytest.raises(ValueError, match="expected closing parenthesis"):
            _match_tag_expr("(a | b", {"a"})

    def test_mismatched_parenthesis_close(self):
        with pytest.raises(ValueError, match="unexpected token"):
            _match_tag_expr("a | b)", {"a"})

    def test_operator_without_left_operand(self):
        with pytest.raises(ValueError, match="unexpected token"):
            _match_tag_expr("& a", {"a"})

    def test_operator_without_right_operand(self):
        with pytest.raises(ValueError, match="unexpected end of expression"):
            _match_tag_expr("a &", {"a"})

    def test_consecutive_operators(self):
        with pytest.raises(ValueError, match="unexpected token"):
            _match_tag_expr("a & | b", {"a", "b"})


class TestTokenizer:
    def test_all_token_types(self):
        tokens = _tagdsl_tokenize("a & b | c ^ d - !e (f)")
        types = [t[0] for t in tokens]
        assert types == [
            "IDENT", "AND", "IDENT", "OR", "IDENT", "XOR",
            "IDENT", "DIFF", "NOT", "IDENT", "LPAREN", "IDENT", "RPAREN",
        ]

    def test_no_whitespace(self):
        tokens = _tagdsl_tokenize("a&b|c")
        types = [t[0] for t in tokens]
        assert types == ["IDENT", "AND", "IDENT", "OR", "IDENT"]

    def test_positions_are_correct(self):
        tokens = _tagdsl_tokenize("ab & cd")
        assert tokens[0] == ("IDENT", "ab", 0)
        assert tokens[1] == ("AND", "&", 3)
        assert tokens[2] == ("IDENT", "cd", 5)

    def test_hyphenated_tag_name(self):
        tokens = _tagdsl_tokenize("my-tag & other-tag2")
        assert tokens[0] == ("IDENT", "my-tag", 0)
        assert tokens[2] == ("IDENT", "other-tag2", 9)
