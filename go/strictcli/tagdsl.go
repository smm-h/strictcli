package strictcli

import (
	"fmt"
	"strings"
)

// tagTokenType represents the type of a token in a tag expression.
type tagTokenType int

const (
	tagTokenIdent  tagTokenType = iota // identifier (tag name)
	tagTokenAnd                        // &
	tagTokenOr                         // |
	tagTokenXor                        // ^
	tagTokenDiff                       // -
	tagTokenNot                        // !
	tagTokenLParen                     // (
	tagTokenRParen                     // )
)

// tagToken is a single token from a tag expression.
type tagToken struct {
	typ tagTokenType
	val string
	pos int
}

// tagNode is a node in the tag expression AST.
type tagNode interface {
	eval(tags map[string]bool) bool
}

// tagIdent is a leaf node representing a tag name.
type tagIdent struct {
	name string
}

func (n *tagIdent) eval(tags map[string]bool) bool {
	return tags[n.name]
}

// tagNot is a unary NOT node.
type tagNot struct {
	operand tagNode
}

func (n *tagNot) eval(tags map[string]bool) bool {
	return !n.operand.eval(tags)
}

// tagAnd is a binary AND node.
type tagAnd struct {
	left, right tagNode
}

func (n *tagAnd) eval(tags map[string]bool) bool {
	return n.left.eval(tags) && n.right.eval(tags)
}

// tagOr is a binary OR node.
type tagOr struct {
	left, right tagNode
}

func (n *tagOr) eval(tags map[string]bool) bool {
	return n.left.eval(tags) || n.right.eval(tags)
}

// tagXor is a binary XOR node.
type tagXor struct {
	left, right tagNode
}

func (n *tagXor) eval(tags map[string]bool) bool {
	return n.left.eval(tags) != n.right.eval(tags)
}

// tagDiff is a binary DIFF node (left AND NOT right).
type tagDiff struct {
	left, right tagNode
}

func (n *tagDiff) eval(tags map[string]bool) bool {
	return n.left.eval(tags) && !n.right.eval(tags)
}

// tagdslTokenize splits a tag expression string into tokens.
func tagdslTokenize(expr string) ([]tagToken, error) {
	var tokens []tagToken
	i := 0
	for i < len(expr) {
		ch := expr[i]

		// Skip whitespace
		if ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r' {
			i++
			continue
		}

		switch ch {
		case '&':
			tokens = append(tokens, tagToken{typ: tagTokenAnd, val: "&", pos: i})
			i++
		case '|':
			tokens = append(tokens, tagToken{typ: tagTokenOr, val: "|", pos: i})
			i++
		case '^':
			tokens = append(tokens, tagToken{typ: tagTokenXor, val: "^", pos: i})
			i++
		case '-':
			tokens = append(tokens, tagToken{typ: tagTokenDiff, val: "-", pos: i})
			i++
		case '!':
			tokens = append(tokens, tagToken{typ: tagTokenNot, val: "!", pos: i})
			i++
		case '(':
			tokens = append(tokens, tagToken{typ: tagTokenLParen, val: "(", pos: i})
			i++
		case ')':
			tokens = append(tokens, tagToken{typ: tagTokenRParen, val: ")", pos: i})
			i++
		default:
			// Try to read an identifier: [a-z][a-z0-9-]*
			if ch >= 'a' && ch <= 'z' {
				start := i
				i++
				for i < len(expr) {
					c := expr[i]
					if (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' {
						i++
					} else {
						break
					}
				}
				tokens = append(tokens, tagToken{typ: tagTokenIdent, val: expr[start:i], pos: start})
			} else {
				return nil, fmt.Errorf("tag expression: unexpected character %q at position %d", string(ch), i)
			}
		}
	}
	return tokens, nil
}

// tagdslParser holds state during recursive descent parsing.
type tagdslParser struct {
	tokens []tagToken
	pos    int
}

// tagdslParse parses a token list into an AST using recursive descent.
// Precedence (tightest first): NOT, AND, XOR, OR, DIFF.
func tagdslParse(tokens []tagToken) (tagNode, error) {
	if len(tokens) == 0 {
		return nil, fmt.Errorf("tag expression: empty expression")
	}
	p := &tagdslParser{tokens: tokens, pos: 0}
	node, err := p.parseDiff()
	if err != nil {
		return nil, err
	}
	if p.pos < len(p.tokens) {
		tok := p.tokens[p.pos]
		return nil, fmt.Errorf("tag expression: unexpected token %q at position %d", tok.val, tok.pos)
	}
	return node, nil
}

// peek returns the current token without consuming it, or nil if at end.
func (p *tagdslParser) peek() *tagToken {
	if p.pos >= len(p.tokens) {
		return nil
	}
	return &p.tokens[p.pos]
}

// advance consumes and returns the current token.
func (p *tagdslParser) advance() tagToken {
	tok := p.tokens[p.pos]
	p.pos++
	return tok
}

// parseDiff handles the lowest-precedence operator: DIFF (-)
func (p *tagdslParser) parseDiff() (tagNode, error) {
	left, err := p.parseOr()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		if tok == nil || tok.typ != tagTokenDiff {
			break
		}
		p.advance()
		right, err := p.parseOr()
		if err != nil {
			return nil, err
		}
		left = &tagDiff{left: left, right: right}
	}
	return left, nil
}

// parseOr handles OR (|)
func (p *tagdslParser) parseOr() (tagNode, error) {
	left, err := p.parseXor()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		if tok == nil || tok.typ != tagTokenOr {
			break
		}
		p.advance()
		right, err := p.parseXor()
		if err != nil {
			return nil, err
		}
		left = &tagOr{left: left, right: right}
	}
	return left, nil
}

// parseXor handles XOR (^)
func (p *tagdslParser) parseXor() (tagNode, error) {
	left, err := p.parseAnd()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		if tok == nil || tok.typ != tagTokenXor {
			break
		}
		p.advance()
		right, err := p.parseAnd()
		if err != nil {
			return nil, err
		}
		left = &tagXor{left: left, right: right}
	}
	return left, nil
}

// parseAnd handles AND (&)
func (p *tagdslParser) parseAnd() (tagNode, error) {
	left, err := p.parseNot()
	if err != nil {
		return nil, err
	}
	for {
		tok := p.peek()
		if tok == nil || tok.typ != tagTokenAnd {
			break
		}
		p.advance()
		right, err := p.parseNot()
		if err != nil {
			return nil, err
		}
		left = &tagAnd{left: left, right: right}
	}
	return left, nil
}

// parseNot handles NOT (!) as a prefix unary operator.
func (p *tagdslParser) parseNot() (tagNode, error) {
	tok := p.peek()
	if tok != nil && tok.typ == tagTokenNot {
		p.advance()
		operand, err := p.parseNot()
		if err != nil {
			return nil, err
		}
		return &tagNot{operand: operand}, nil
	}
	return p.parsePrimary()
}

// parsePrimary handles identifiers and parenthesized expressions.
func (p *tagdslParser) parsePrimary() (tagNode, error) {
	tok := p.peek()
	if tok == nil {
		lastPos := 0
		if len(p.tokens) > 0 {
			last := p.tokens[len(p.tokens)-1]
			lastPos = last.pos + len(last.val)
		}
		return nil, fmt.Errorf("tag expression: unexpected end of expression at position %d", lastPos)
	}

	switch tok.typ {
	case tagTokenIdent:
		p.advance()
		return &tagIdent{name: tok.val}, nil
	case tagTokenLParen:
		p.advance()
		node, err := p.parseDiff()
		if err != nil {
			return nil, err
		}
		closing := p.peek()
		if closing == nil || closing.typ != tagTokenRParen {
			return nil, fmt.Errorf("tag expression: expected \")\" at position %d", p.endPos())
		}
		p.advance()
		return node, nil
	default:
		return nil, fmt.Errorf("tag expression: unexpected token %q at position %d", tok.val, tok.pos)
	}
}

// endPos returns the position after the last token, for error messages.
func (p *tagdslParser) endPos() int {
	if len(p.tokens) == 0 {
		return 0
	}
	last := p.tokens[len(p.tokens)-1]
	return last.pos + len(last.val)
}

// tagdslEvaluate evaluates an AST node against a set of tags.
func tagdslEvaluate(node tagNode, tags map[string]bool) bool {
	return node.eval(tags)
}

// matchTagExpr tokenizes, parses, and evaluates a tag expression against a tag set.
func matchTagExpr(expr string, tags map[string]bool) (bool, error) {
	expr = strings.TrimSpace(expr)
	if expr == "" {
		return false, fmt.Errorf("tag expression: empty expression")
	}
	tokens, err := tagdslTokenize(expr)
	if err != nil {
		return false, err
	}
	if len(tokens) == 0 {
		return false, fmt.Errorf("tag expression: empty expression")
	}
	node, err := tagdslParse(tokens)
	if err != nil {
		return false, err
	}
	return tagdslEvaluate(node, tags), nil
}
