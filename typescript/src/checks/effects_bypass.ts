/**
 * The built-in `effects-bypass` check provider.
 *
 * It statically analyses the consumer's own sources and fails on any direct
 * process, filesystem-mutation or network call reachable from a handler that
 * opted into `ctx.effects`. Opting in is the trigger: a function that uses the
 * effects handle must route ALL of its effects through it, or the preview it
 * promises is a lie.
 *
 * Additionally -- and this part is TypeScript-specific -- it flags the two
 * accepted Proxy ceilings: a bare truthiness test and an identity comparison
 * against a value the analyser can trace to an effects-handle return. Those two
 * are the only things the runtime seal cannot catch, so lint is the sole line
 * of defence and the check names them explicitly.
 *
 * ANALYSER: the TypeScript compiler API, a REGULAR dependency -- `typescript`
 * sits in `dependencies`, not `devDependencies`, and there is no optional
 * import and no soft degradation. Concretely it is the compiler's own scanner
 * (`createScanner` from `typescript/unstable/ast`). The compiler package at
 * version 7 is the native port: it ships the scanner, the SyntaxKind enum and
 * the AST node predicates, but NO in-process parser -- building a syntax tree
 * there means spawning the native language server against a resolved tsconfig,
 * which a check declared `fast` and `pure` must not do. The scope rule below is
 * therefore expressed over brace blocks rather than function nodes: a call is a
 * finding when some brace block contains BOTH the call and an `.effects`
 * mention, which is the token-level reading of "reachable from a handler that
 * opted in".
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import {
	computeLineStarts,
	createScanner,
	SyntaxKind,
} from "typescript/unstable/ast";
import type { AppImpl } from "../app.js";
import { type CheckSpec, errorCheckSpec } from "./provider.js";

/** Process starts. Matched on the called name, bare or through a receiver. */
const BYPASS_PROCESS: ReadonlySet<string> = new Set([
	"spawn",
	"spawnSync",
	"exec",
	"execSync",
	"execFile",
	"execFileSync",
	"fork",
]);

/** Filesystem mutations (sync and promise forms). */
const BYPASS_FILESYSTEM: ReadonlySet<string> = new Set([
	"writeFileSync",
	"appendFileSync",
	"mkdirSync",
	"mkdtempSync",
	"rmSync",
	"rmdirSync",
	"unlinkSync",
	"renameSync",
	"chmodSync",
	"chownSync",
	"symlinkSync",
	"linkSync",
	"truncateSync",
	"copyFileSync",
	"cpSync",
	"createWriteStream",
	"writeFile",
	"appendFile",
	"mkdir",
	"mkdtemp",
	"rm",
	"rmdir",
	"unlink",
	"rename",
	"chmod",
	"chown",
	"symlink",
	"link",
	"truncate",
	"copyFile",
	"cp",
]);

/** Network calls, banned only through the receivers below. */
const BYPASS_NETWORK: ReadonlySet<string> = new Set([
	"request",
	"get",
	"post",
	"put",
	"patch",
	"delete",
	"head",
	"createConnection",
	"connect",
]);

/**
 * Network members are banned only through these receivers, so an ordinary
 * `map.get(...)` inside a handler is not a finding.
 */
const BYPASS_NETWORK_RECEIVERS: ReadonlySet<string> = new Set([
	"http",
	"https",
	"axios",
	"got",
	"undici",
	"net",
	"tls",
	"request",
	"client",
	"session",
	"agent",
]);

const SKIP_DIRS: ReadonlySet<string> = new Set([
	"node_modules",
	"dist",
	"dist-test",
	"build",
	"out",
	"coverage",
	"vendor",
]);

const SOURCE_EXTS = [".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs"];

/** One reported bypass. */
export interface BypassFinding {
	readonly file: string;
	readonly line: number;
	readonly text: string;
	readonly kind: "call" | "ceiling";
}

/** Collects source files under `root`, in directory-then-name order. */
function collectSourceFiles(root: string): string[] {
	const out: string[] = [];
	const walk = (dir: string): void => {
		let entries: string[];
		try {
			entries = readdirSync(dir).sort();
		} catch {
			return;
		}
		const files: string[] = [];
		const dirs: string[] = [];
		for (const entry of entries) {
			if (entry.startsWith(".")) {
				continue;
			}
			const full = join(dir, entry);
			let isDir = false;
			try {
				isDir = statSync(full).isDirectory();
			} catch {
				continue;
			}
			if (isDir) {
				if (!SKIP_DIRS.has(entry)) {
					dirs.push(full);
				}
			} else if (SOURCE_EXTS.some((ext) => entry.endsWith(ext))) {
				files.push(full);
			}
		}
		out.push(...files);
		for (const d of dirs) {
			walk(d);
		}
	};
	walk(root);
	return out;
}

interface Tok {
	readonly kind: SyntaxKind;
	readonly text: string;
	readonly start: number;
}

/**
 * Tokenizes with the compiler's scanner, dropping trivia.
 *
 * The scanner is a pure lexer: it cannot leave a template-substitution state on
 * its own, because in a real compile the PARSER decides when a `}` closes a
 * `${` and calls back into `reScanTemplateToken`. Without that cooperation the
 * scanner stalls at the closing brace, returning a zero-width token forever.
 * Progress is therefore asserted explicitly: on a stall, re-scan as a template
 * continuation, and if even that does not advance, step one character and carry
 * on. Both recoveries are lossless for this analyser, which reads names,
 * punctuation and brace depth -- never template contents.
 */
function tokenize(text: string): Tok[] {
	const scanner = createScanner(/* skipTrivia */ true);
	scanner.setText(text);
	const toks: Tok[] = [];
	let lastEnd = -1;
	for (;;) {
		let kind = scanner.scan();
		if (kind === SyntaxKind.EndOfFile) {
			break;
		}
		if (scanner.getTokenEnd() <= lastEnd) {
			kind = scanner.reScanTemplateToken(/* isTaggedTemplate */ false);
			if (scanner.getTokenEnd() <= lastEnd) {
				if (lastEnd + 1 >= text.length) {
					break;
				}
				scanner.resetTokenState(lastEnd + 1);
				lastEnd += 1;
				continue;
			}
		}
		lastEnd = scanner.getTokenEnd();
		toks.push({
			kind,
			text: scanner.getTokenText(),
			start: scanner.getTokenStart(),
		});
	}
	return toks;
}

function lineOf(lineStarts: readonly number[], pos: number): number {
	let lo = 0;
	let hi = lineStarts.length - 1;
	while (lo < hi) {
		const mid = (lo + hi + 1) >> 1;
		if ((lineStarts[mid] as number) <= pos) {
			lo = mid;
		} else {
			hi = mid - 1;
		}
	}
	return lo + 1;
}

/** True when the token is an identifier or a keyword usable as a member name. */
function isNameToken(t: Tok | undefined): boolean {
	return (
		t !== undefined &&
		/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(t.text) &&
		t.kind !== SyntaxKind.StringLiteral
	);
}

/**
 * Scans one tokenized file. A call is a finding when some brace block contains
 * both the call site and an `.effects` mention.
 */
export function scanTokens(
	toks: readonly Tok[],
	text: string,
	rel: string,
): BypassFinding[] {
	const lineStarts = computeLineStarts(text);
	const findings: BypassFinding[] = [];

	// Brace blocks: blockOf[i] is the index of the innermost block containing
	// token i; blocks are (open, close) index pairs.
	const openStack: number[] = [];
	const blockParent: number[] = []; // per token: enclosing block id, or -1
	const blockOpenIdx: number[] = [];
	const blockEnclosing: number[] = [];
	const blockOfToken: number[] = new Array(toks.length).fill(-1);
	for (let i = 0; i < toks.length; i++) {
		const t = toks[i] as Tok;
		if (t.kind === SyntaxKind.CloseBraceToken) {
			openStack.pop();
		}
		const current =
			openStack.length > 0 ? (openStack[openStack.length - 1] as number) : -1;
		blockOfToken[i] = current;
		if (t.kind === SyntaxKind.OpenBraceToken) {
			const id = blockOpenIdx.length;
			blockOpenIdx.push(i);
			blockEnclosing.push(current);
			blockParent.push(current);
			openStack.push(id);
		}
	}

	// Blocks that (transitively) contain an `.effects` mention: for each
	// occurrence, every enclosing block opts in -- the token-level reading of
	// "every enclosing function opts in".
	const optedIn = new Set<number>();
	for (let i = 1; i < toks.length; i++) {
		if (
			(toks[i] as Tok).text === "effects" &&
			(toks[i - 1] as Tok).kind === SyntaxKind.DotToken
		) {
			let b = blockOfToken[i] as number;
			while (b !== -1) {
				optedIn.add(b);
				b = blockEnclosing[b] as number;
			}
		}
	}
	const inOptedInScope = (i: number): boolean =>
		optedIn.has(blockOfToken[i] as number);
	if (optedIn.size === 0) {
		return findings;
	}

	// Identifiers bound to an effects-handle return, so the Proxy-ceiling
	// checks have something concrete to trace.
	const carriers = new Set<string>();
	for (let i = 0; i + 2 < toks.length; i++) {
		const t = toks[i] as Tok;
		if (
			t.kind !== SyntaxKind.ConstKeyword &&
			t.kind !== SyntaxKind.LetKeyword &&
			t.kind !== SyntaxKind.VarKeyword
		) {
			continue;
		}
		const nameTok = toks[i + 1] as Tok;
		if (!isNameToken(nameTok)) {
			continue;
		}
		// Walk the initializer to the end of the statement looking for
		// `.effects.<method>(`.
		let j = i + 2;
		let sawEquals = false;
		let sawEffectsCall = false;
		for (; j < toks.length; j++) {
			const tj = toks[j] as Tok;
			if (tj.kind === SyntaxKind.SemicolonToken) {
				break;
			}
			if (tj.kind === SyntaxKind.EqualsToken) {
				sawEquals = true;
				continue;
			}
			if (
				sawEquals &&
				tj.text === "effects" &&
				(toks[j - 1] as Tok).kind === SyntaxKind.DotToken &&
				(toks[j + 1] as Tok | undefined)?.kind === SyntaxKind.DotToken &&
				(toks[j + 3] as Tok | undefined)?.kind === SyntaxKind.OpenParenToken
			) {
				sawEffectsCall = true;
			}
		}
		if (sawEquals && sawEffectsCall) {
			carriers.add(nameTok.text);
		}
	}

	const isCarrierAt = (i: number): boolean =>
		i >= 0 && i < toks.length && carriers.has((toks[i] as Tok).text);

	const push = (i: number, kind: "call" | "ceiling", text: string): void => {
		findings.push({
			file: rel,
			line: lineOf(lineStarts, (toks[i] as Tok).start),
			kind,
			text,
		});
	};

	for (let i = 0; i < toks.length; i++) {
		const t = toks[i] as Tok;
		if (!inOptedInScope(i)) {
			continue;
		}

		// --- direct effect calls ---
		if (
			isNameToken(t) &&
			(toks[i + 1] as Tok | undefined)?.kind === SyntaxKind.OpenParenToken
		) {
			const prevDot =
				(toks[i - 1] as Tok | undefined)?.kind === SyntaxKind.DotToken;
			const receiver = prevDot
				? (toks[i - 2] as Tok | undefined)?.text
				: undefined;
			// Anything reached through `.effects.` is exactly what we want.
			const throughEffects = prevDot && receiver === "effects";
			if (!throughEffects) {
				const leaf = t.text;
				const target = receiver !== undefined ? `${receiver}.${leaf}` : leaf;
				const banned =
					BYPASS_PROCESS.has(leaf) ||
					BYPASS_FILESYSTEM.has(leaf) ||
					(leaf === "fetch" && !prevDot) ||
					(BYPASS_NETWORK.has(leaf) &&
						receiver !== undefined &&
						BYPASS_NETWORK_RECEIVERS.has(receiver));
				if (banned) {
					push(
						i,
						"call",
						`calls ${target} directly; route it through ctx.effects`,
					);
					continue;
				}
			}
		}

		// --- Proxy ceiling 1: truthiness ---
		const truthyHere =
			// if (C) / while (C)
			((t.kind === SyntaxKind.IfKeyword ||
				t.kind === SyntaxKind.WhileKeyword) &&
				(toks[i + 1] as Tok | undefined)?.kind === SyntaxKind.OpenParenToken &&
				isCarrierAt(i + 2) &&
				(toks[i + 3] as Tok | undefined)?.kind ===
					SyntaxKind.CloseParenToken) ||
			// !C
			(t.kind === SyntaxKind.ExclamationToken && isCarrierAt(i + 1)) ||
			// C ? / C && / C ||
			(isCarrierAt(i) &&
				[
					SyntaxKind.QuestionToken,
					SyntaxKind.AmpersandAmpersandToken,
					SyntaxKind.BarBarToken,
				].includes((toks[i + 1] as Tok | undefined)?.kind as SyntaxKind)) ||
			// && C / || C
			([SyntaxKind.AmpersandAmpersandToken, SyntaxKind.BarBarToken].includes(
				t.kind,
			) &&
				isCarrierAt(i + 1));
		if (truthyHere) {
			push(
				i,
				"ceiling",
				"branches on the truthiness of an effects result; a Proxy cannot trap truthiness -- read ctx.dryRun, or forward the value instead",
			);
			continue;
		}

		// --- Proxy ceiling 2: identity comparison ---
		const identityKinds = [
			SyntaxKind.EqualsEqualsEqualsToken,
			SyntaxKind.ExclamationEqualsEqualsToken,
			SyntaxKind.EqualsEqualsToken,
			SyntaxKind.ExclamationEqualsToken,
		];
		if (
			identityKinds.includes(t.kind) &&
			(isCarrierAt(i - 1) || isCarrierAt(i + 1))
		) {
			push(
				i,
				"ceiling",
				"compares an effects result with ===; a Proxy cannot trap === -- forward the value instead",
			);
		}
	}
	return findings;
}

/**
 * Finds direct effect calls and untrappable carrier uses in sources under
 * `root`. Returns findings in file-then-line order.
 */
export function scanEffectsBypasses(root: string): BypassFinding[] {
	const findings: BypassFinding[] = [];
	let isDir = false;
	try {
		isDir = statSync(root).isDirectory();
	} catch {
		return findings;
	}
	if (!isDir) {
		return findings;
	}
	for (const path of collectSourceFiles(root)) {
		let text: string;
		try {
			text = readFileSync(path, "utf8");
		} catch {
			// A file the analyser cannot read is not evidence of a bypass.
			continue;
		}
		let toks: Tok[];
		try {
			toks = tokenize(text);
		} catch {
			continue;
		}
		findings.push(...scanTokens(toks, text, relative(root, path)));
	}
	return findings;
}

/**
 * The built-in provider. Registered whenever the check system turns on, so a
 * consumer that adopts checks at all gets the lint without a TOML declaration.
 */
export function effectsBypassProvider(_app: AppImpl): () => CheckSpec[] {
	// Named so tests can identify and drop the framework's own provider
	// (tests/helpers.ts dropBuiltinCheckProviders), mirroring Python's
	// conftest helper which filters on the provider function's __name__.
	return function effectsBypassCheckProvider(): CheckSpec[] {
		return [
			errorCheckSpec({
				name: "effects-bypass",
				tags: ["effects", "quality"],
				fast: true,
				pure: true,
				needsNetwork: false,
				dependsOn: [],
				impl: (ctx, reporter) => {
					const findings = scanEffectsBypasses(ctx.projectRoot);
					for (const f of findings) {
						reporter.error(`${f.file}:${f.line}: ${f.text}`);
					}
					if (findings.length === 0) {
						return reporter.passed("no direct effect calls bypass ctx.effects");
					}
					const direct = findings.filter((f) => f.kind === "call").length;
					const ceilings = findings.length - direct;
					if (ceilings === 0) {
						return reporter.found(
							`${direct} direct effect call(s) bypassing ctx.effects`,
						);
					}
					return reporter.found(
						`${direct} direct effect call(s) bypassing ctx.effects and ` +
							`${ceilings} untrappable carrier use(s)`,
					);
				},
			}),
		];
	};
}
