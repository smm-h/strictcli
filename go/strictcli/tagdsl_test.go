package strictcli

import (
	"strings"
	"testing"
)

func TestTagdslTokenize(t *testing.T) {
	t.Run("simple ident", func(t *testing.T) {
		tokens, err := tagdslTokenize("release")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(tokens) != 1 {
			t.Fatalf("expected 1 token, got %d", len(tokens))
		}
		if tokens[0].typ != tagTokenIdent || tokens[0].val != "release" {
			t.Errorf("unexpected token: %+v", tokens[0])
		}
	})

	t.Run("all operators", func(t *testing.T) {
		tokens, err := tagdslTokenize("a & b | c ^ d - e ! f")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		expected := []struct {
			typ tagTokenType
			val string
		}{
			{tagTokenIdent, "a"},
			{tagTokenAnd, "&"},
			{tagTokenIdent, "b"},
			{tagTokenOr, "|"},
			{tagTokenIdent, "c"},
			{tagTokenXor, "^"},
			{tagTokenIdent, "d"},
			{tagTokenDiff, "-"},
			{tagTokenIdent, "e"},
			{tagTokenNot, "!"},
			{tagTokenIdent, "f"},
		}
		if len(tokens) != len(expected) {
			t.Fatalf("expected %d tokens, got %d", len(expected), len(tokens))
		}
		for i, exp := range expected {
			if tokens[i].typ != exp.typ || tokens[i].val != exp.val {
				t.Errorf("token %d: expected (%d, %q), got (%d, %q)", i, exp.typ, exp.val, tokens[i].typ, tokens[i].val)
			}
		}
	})

	t.Run("parentheses", func(t *testing.T) {
		tokens, err := tagdslTokenize("(a | b)")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(tokens) != 5 {
			t.Fatalf("expected 5 tokens, got %d", len(tokens))
		}
		if tokens[0].typ != tagTokenLParen {
			t.Errorf("expected LPAREN, got %+v", tokens[0])
		}
		if tokens[4].typ != tagTokenRParen {
			t.Errorf("expected RPAREN, got %+v", tokens[4])
		}
	})

	t.Run("ident with hyphens and digits", func(t *testing.T) {
		tokens, err := tagdslTokenize("check-deps-v2")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if len(tokens) != 1 || tokens[0].val != "check-deps-v2" {
			t.Fatalf("expected single ident 'check-deps-v2', got %v", tokens)
		}
	})

	t.Run("unexpected character", func(t *testing.T) {
		_, err := tagdslTokenize("a @ b")
		if err == nil {
			t.Fatal("expected error")
		}
		if !strings.Contains(err.Error(), `unexpected character "@" at position 2`) {
			t.Errorf("unexpected error: %v", err)
		}
	})

	t.Run("uppercase rejected", func(t *testing.T) {
		_, err := tagdslTokenize("A")
		if err == nil {
			t.Fatal("expected error for uppercase character")
		}
		if !strings.Contains(err.Error(), "unexpected character") {
			t.Errorf("unexpected error: %v", err)
		}
	})
}

func TestTagdslParse_SimpleIdent(t *testing.T) {
	tokens, _ := tagdslTokenize("release")
	node, err := tagdslParse(tokens)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	ident, ok := node.(*tagIdent)
	if !ok {
		t.Fatalf("expected tagIdent, got %T", node)
	}
	if ident.name != "release" {
		t.Errorf("expected 'release', got %q", ident.name)
	}
}

func TestTagdslParse_Not(t *testing.T) {
	tokens, _ := tagdslTokenize("!slow")
	node, err := tagdslParse(tokens)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	notNode, ok := node.(*tagNot)
	if !ok {
		t.Fatalf("expected tagNot, got %T", node)
	}
	ident, ok := notNode.operand.(*tagIdent)
	if !ok {
		t.Fatalf("expected tagIdent operand, got %T", notNode.operand)
	}
	if ident.name != "slow" {
		t.Errorf("expected 'slow', got %q", ident.name)
	}
}

func TestTagdslParse_Precedence_AndOverOr(t *testing.T) {
	// a | b & c should parse as a | (b & c)
	tokens, _ := tagdslTokenize("a | b & c")
	node, err := tagdslParse(tokens)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Top-level should be DIFF (identity) -> OR
	orNode, ok := node.(*tagOr)
	if !ok {
		t.Fatalf("expected top-level tagOr, got %T", node)
	}
	// Left is ident "a"
	if ident, ok := orNode.left.(*tagIdent); !ok || ident.name != "a" {
		t.Errorf("expected left=tagIdent('a'), got %T", orNode.left)
	}
	// Right is AND(b, c)
	andNode, ok := orNode.right.(*tagAnd)
	if !ok {
		t.Fatalf("expected right=tagAnd, got %T", orNode.right)
	}
	if ident, ok := andNode.left.(*tagIdent); !ok || ident.name != "b" {
		t.Errorf("expected and.left=tagIdent('b'), got %T", andNode.left)
	}
	if ident, ok := andNode.right.(*tagIdent); !ok || ident.name != "c" {
		t.Errorf("expected and.right=tagIdent('c'), got %T", andNode.right)
	}
}

func TestTagdslParse_Parentheses(t *testing.T) {
	// (a | b) & c should parse as AND(OR(a, b), c)
	tokens, _ := tagdslTokenize("(a | b) & c")
	node, err := tagdslParse(tokens)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	andNode, ok := node.(*tagAnd)
	if !ok {
		t.Fatalf("expected top-level tagAnd, got %T", node)
	}
	orNode, ok := andNode.left.(*tagOr)
	if !ok {
		t.Fatalf("expected left=tagOr, got %T", andNode.left)
	}
	if ident, ok := orNode.left.(*tagIdent); !ok || ident.name != "a" {
		t.Errorf("expected or.left=tagIdent('a')")
	}
	if ident, ok := orNode.right.(*tagIdent); !ok || ident.name != "b" {
		t.Errorf("expected or.right=tagIdent('b')")
	}
	if ident, ok := andNode.right.(*tagIdent); !ok || ident.name != "c" {
		t.Errorf("expected and.right=tagIdent('c')")
	}
}

func TestTagdslParse_EmptyExpression(t *testing.T) {
	_, err := tagdslParse(nil)
	if err == nil {
		t.Fatal("expected error for empty expression")
	}
	if !strings.Contains(err.Error(), "empty expression") {
		t.Errorf("unexpected error: %v", err)
	}
}

func TestTagdslParse_UnexpectedToken(t *testing.T) {
	tokens, _ := tagdslTokenize(")")
	_, err := tagdslParse(tokens)
	if err == nil {
		t.Fatal("expected error for unexpected token")
	}
	if !strings.Contains(err.Error(), `unexpected token ")" at position 0`) {
		t.Errorf("unexpected error: %v", err)
	}
}

func TestTagdslParse_MismatchedParen(t *testing.T) {
	tokens, _ := tagdslTokenize("(a | b")
	_, err := tagdslParse(tokens)
	if err == nil {
		t.Fatal("expected error for mismatched parentheses")
	}
	if !strings.Contains(err.Error(), `expected ")"`) {
		t.Errorf("unexpected error: %v", err)
	}
}

func TestTagdslEvaluate(t *testing.T) {
	tests := []struct {
		name   string
		expr   string
		tags   map[string]bool
		expect bool
	}{
		{
			name:   "simple match",
			expr:   "release",
			tags:   map[string]bool{"release": true},
			expect: true,
		},
		{
			name:   "simple no match",
			expr:   "release",
			tags:   map[string]bool{"debug": true},
			expect: false,
		},
		{
			name:   "NOT true",
			expr:   "!slow",
			tags:   map[string]bool{"fast": true},
			expect: true,
		},
		{
			name:   "NOT false",
			expr:   "!slow",
			tags:   map[string]bool{"slow": true},
			expect: false,
		},
		{
			name:   "AND both true",
			expr:   "a & b",
			tags:   map[string]bool{"a": true, "b": true},
			expect: true,
		},
		{
			name:   "AND one false",
			expr:   "a & b",
			tags:   map[string]bool{"a": true},
			expect: false,
		},
		{
			name:   "OR one true",
			expr:   "a | b",
			tags:   map[string]bool{"a": true},
			expect: true,
		},
		{
			name:   "OR neither true",
			expr:   "a | b",
			tags:   map[string]bool{"c": true},
			expect: false,
		},
		{
			name:   "XOR one true",
			expr:   "a ^ b",
			tags:   map[string]bool{"a": true},
			expect: true,
		},
		{
			name:   "XOR both true",
			expr:   "a ^ b",
			tags:   map[string]bool{"a": true, "b": true},
			expect: false,
		},
		{
			name:   "XOR neither true",
			expr:   "a ^ b",
			tags:   map[string]bool{},
			expect: false,
		},
		{
			name:   "DIFF",
			expr:   "a - b",
			tags:   map[string]bool{"a": true},
			expect: true,
		},
		{
			name:   "DIFF both present",
			expr:   "a - b",
			tags:   map[string]bool{"a": true, "b": true},
			expect: false,
		},
		{
			name:   "complex: (release | changelog) & !slow",
			expr:   "(release | changelog) & !slow",
			tags:   map[string]bool{"release": true},
			expect: true,
		},
		{
			name:   "complex: (release | changelog) & !slow with slow",
			expr:   "(release | changelog) & !slow",
			tags:   map[string]bool{"release": true, "slow": true},
			expect: false,
		},
		{
			name:   "complex: (release | changelog) & !slow with changelog",
			expr:   "(release | changelog) & !slow",
			tags:   map[string]bool{"changelog": true},
			expect: true,
		},
		{
			name:   "double NOT",
			expr:   "!!a",
			tags:   map[string]bool{"a": true},
			expect: true,
		},
		{
			name:   "precedence: NOT binds tighter than AND",
			expr:   "!a & b",
			tags:   map[string]bool{"b": true},
			expect: true,
		},
		{
			name:   "precedence: AND binds tighter than XOR",
			expr:   "a ^ b & c",
			tags:   map[string]bool{"a": true, "b": true, "c": true},
			expect: false, // a ^ (b & c) = true ^ true = false
		},
		{
			name:   "precedence: XOR binds tighter than OR",
			expr:   "a | b ^ c",
			tags:   map[string]bool{"b": true, "c": true},
			expect: false, // a | (b ^ c) = false | false = false
		},
		{
			name:   "precedence: OR binds tighter than DIFF",
			expr:   "a - b | c",
			tags:   map[string]bool{"a": true, "c": true},
			expect: false, // a - (b | c) = true - true = false
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			result, err := matchTagExpr(tc.expr, tc.tags)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if result != tc.expect {
				t.Errorf("matchTagExpr(%q, %v) = %v, want %v", tc.expr, tc.tags, result, tc.expect)
			}
		})
	}
}

func TestMatchTagExpr_Errors(t *testing.T) {
	t.Run("empty expression", func(t *testing.T) {
		_, err := matchTagExpr("", nil)
		if err == nil {
			t.Fatal("expected error for empty expression")
		}
		if !strings.Contains(err.Error(), "empty expression") {
			t.Errorf("unexpected error: %v", err)
		}
	})

	t.Run("whitespace only", func(t *testing.T) {
		_, err := matchTagExpr("   ", nil)
		if err == nil {
			t.Fatal("expected error for whitespace-only expression")
		}
		if !strings.Contains(err.Error(), "empty expression") {
			t.Errorf("unexpected error: %v", err)
		}
	})

	t.Run("unexpected character", func(t *testing.T) {
		_, err := matchTagExpr("a + b", nil)
		if err == nil {
			t.Fatal("expected error for unexpected character")
		}
		if !strings.Contains(err.Error(), "unexpected character") {
			t.Errorf("unexpected error: %v", err)
		}
	})

	t.Run("mismatched parens", func(t *testing.T) {
		_, err := matchTagExpr("(a | b", nil)
		if err == nil {
			t.Fatal("expected error for mismatched parentheses")
		}
	})

	t.Run("trailing operator", func(t *testing.T) {
		_, err := matchTagExpr("a &", nil)
		if err == nil {
			t.Fatal("expected error for trailing operator")
		}
	})

	t.Run("extra closing paren", func(t *testing.T) {
		_, err := matchTagExpr("a)", nil)
		if err == nil {
			t.Fatal("expected error for extra closing paren")
		}
		if !strings.Contains(err.Error(), `unexpected token ")"`) {
			t.Errorf("unexpected error: %v", err)
		}
	})
}
