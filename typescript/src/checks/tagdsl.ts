/**
 * Tag DSL: set-operation expressions over check tags. Operators by precedence
 * (tightest first): ! (NOT), & (AND), ^ (XOR), | (OR), - (DIFF). Parentheses
 * group. Error positions are byte offsets into the expression string.
 *
 * Parity sources: go/strictcli/tagdsl.go and Python _tagdsl_* (~6661-6834).
 * Errors are thrown as plain Error (the Python ValueError analog at run
 * time); callers surface them per the sibling contract.
 */

import {
	errTagExprEmpty,
	errTagExprExpectedRParen,
	errTagExprUnexpectedChar,
	errTagExprUnexpectedEnd,
	errTagExprUnexpectedToken,
} from "../errors.js";

type TagTokenType =
	| "ident"
	| "and"
	| "or"
	| "xor"
	| "diff"
	| "not"
	| "lparen"
	| "rparen";

interface TagToken {
	readonly typ: TagTokenType;
	readonly val: string;
	readonly pos: number;
}

type TagNode =
	| { readonly kind: "ident"; readonly name: string }
	| { readonly kind: "not"; readonly operand: TagNode }
	| {
			readonly kind: "and" | "or" | "xor" | "diff";
			readonly left: TagNode;
			readonly right: TagNode;
	  };

const SINGLE_CHAR_TOKENS: ReadonlyMap<string, TagTokenType> = new Map([
	["&", "and"],
	["|", "or"],
	["^", "xor"],
	["-", "diff"],
	["!", "not"],
	["(", "lparen"],
	[")", "rparen"],
]);

function isIdentStart(ch: string): boolean {
	return ch >= "a" && ch <= "z";
}

function isIdentPart(ch: string): boolean {
	return (ch >= "a" && ch <= "z") || (ch >= "0" && ch <= "9") || ch === "-";
}

function tokenize(expr: string): TagToken[] {
	const tokens: TagToken[] = [];
	let i = 0;
	while (i < expr.length) {
		const ch = expr[i] as string;
		if (ch === " " || ch === "\t" || ch === "\n" || ch === "\r") {
			i++;
			continue;
		}
		const typ = SINGLE_CHAR_TOKENS.get(ch);
		if (typ !== undefined) {
			// A leading identifier character wins over the DIFF operator inside
			// names: identifiers are consumed greedily below, so "-" only
			// tokenizes as DIFF when it does not continue an identifier.
			tokens.push({ typ, val: ch, pos: i });
			i++;
			continue;
		}
		if (isIdentStart(ch)) {
			const start = i;
			i++;
			while (i < expr.length && isIdentPart(expr[i] as string)) {
				i++;
			}
			tokens.push({ typ: "ident", val: expr.slice(start, i), pos: start });
			continue;
		}
		throw new Error(errTagExprUnexpectedChar(ch, i));
	}
	return tokens;
}

/** Recursive-descent parser state over the token list. */
class TagParser {
	private pos = 0;

	constructor(private readonly tokens: readonly TagToken[]) {}

	private peek(): TagToken | undefined {
		return this.tokens[this.pos];
	}

	private advance(): TagToken {
		const tok = this.tokens[this.pos] as TagToken;
		this.pos++;
		return tok;
	}

	private endPos(): number {
		if (this.tokens.length === 0) {
			return 0;
		}
		const last = this.tokens[this.tokens.length - 1] as TagToken;
		return last.pos + last.val.length;
	}

	parse(): TagNode {
		const node = this.parseDiff();
		const tok = this.peek();
		if (tok !== undefined) {
			throw new Error(errTagExprUnexpectedToken(tok.val, tok.pos));
		}
		return node;
	}

	/** DIFF (-) is the loosest-binding operator. */
	private parseDiff(): TagNode {
		let left = this.parseOr();
		while (this.peek()?.typ === "diff") {
			this.advance();
			left = { kind: "diff", left, right: this.parseOr() };
		}
		return left;
	}

	private parseOr(): TagNode {
		let left = this.parseXor();
		while (this.peek()?.typ === "or") {
			this.advance();
			left = { kind: "or", left, right: this.parseXor() };
		}
		return left;
	}

	private parseXor(): TagNode {
		let left = this.parseAnd();
		while (this.peek()?.typ === "xor") {
			this.advance();
			left = { kind: "xor", left, right: this.parseAnd() };
		}
		return left;
	}

	private parseAnd(): TagNode {
		let left = this.parseNot();
		while (this.peek()?.typ === "and") {
			this.advance();
			left = { kind: "and", left, right: this.parseNot() };
		}
		return left;
	}

	/** NOT (!) is a prefix unary operator and binds tightest. */
	private parseNot(): TagNode {
		const tok = this.peek();
		if (tok !== undefined && tok.typ === "not") {
			this.advance();
			return { kind: "not", operand: this.parseNot() };
		}
		return this.parsePrimary();
	}

	private parsePrimary(): TagNode {
		const tok = this.peek();
		if (tok === undefined) {
			throw new Error(errTagExprUnexpectedEnd(this.endPos()));
		}
		if (tok.typ === "ident") {
			this.advance();
			return { kind: "ident", name: tok.val };
		}
		if (tok.typ === "lparen") {
			this.advance();
			const node = this.parseDiff();
			const closing = this.peek();
			if (closing === undefined || closing.typ !== "rparen") {
				throw new Error(errTagExprExpectedRParen(this.endPos()));
			}
			this.advance();
			return node;
		}
		throw new Error(errTagExprUnexpectedToken(tok.val, tok.pos));
	}
}

function evaluate(node: TagNode, tags: ReadonlySet<string>): boolean {
	switch (node.kind) {
		case "ident":
			return tags.has(node.name);
		case "not":
			return !evaluate(node.operand, tags);
		case "and":
			return evaluate(node.left, tags) && evaluate(node.right, tags);
		case "or":
			return evaluate(node.left, tags) || evaluate(node.right, tags);
		case "xor":
			return evaluate(node.left, tags) !== evaluate(node.right, tags);
		case "diff":
			return evaluate(node.left, tags) && !evaluate(node.right, tags);
	}
}

/**
 * Tokenizes, parses, and evaluates a tag expression against a tag set.
 * Throws on malformed expressions (empty, bad characters, syntax errors).
 */
export function matchTagExpr(expr: string, tags: ReadonlySet<string>): boolean {
	const tokens = tokenize(expr);
	if (tokens.length === 0) {
		throw new Error(errTagExprEmpty());
	}
	const node = new TagParser(tokens).parse();
	return evaluate(node, tags);
}
