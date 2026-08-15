/**
 * tsc-level negative tests for the compile-time ctx narrowing (§2.4).
 *
 * `defineReadOnlyCommand` narrows the handler's `ctx` to a ReadOnlyContext
 * whose `effects` member exposes only `run`, so a `.write()` inside a read-only
 * command is a COMPILE error. The fixtures live in tests/negative/ (excluded
 * from the ordinary test build, which must stay clean) and are compiled here
 * through their own tsconfig.
 *
 * The positive fixture is the other half of the pin: extracting from a
 * settled-typed result typechecks fine, because TypeScript declares the settled
 * types ONLY -- no `| Unsettled` union, no narrowing predicate. The mismatch
 * surfaces at runtime, via the Proxy seal, which is where it is honest.
 */

import { strict as assert } from "node:assert";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const PROJECT = fileURLToPath(new URL("../../tests/negative", import.meta.url));

interface Diagnostic {
	readonly file: string;
	readonly code: string;
	readonly text: string;
}

let cached: Diagnostic[] | undefined;
/** The compiler's raw output, including the elaboration lines diagnostics() drops. */
let cachedRaw = "";

/** Compiles tests/negative once and returns its parsed diagnostics. */
function diagnostics(): Diagnostic[] {
	if (cached !== undefined) {
		return cached;
	}
	const res = spawnSync(
		process.execPath,
		[
			fileURLToPath(
				new URL("../../node_modules/typescript/bin/tsc", import.meta.url),
			),
			"-p",
			`${PROJECT}/tsconfig.json`,
		],
		{ encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
	);
	const out = `${res.stdout ?? ""}${res.stderr ?? ""}`;
	cachedRaw = out;
	cached = out
		.split("\n")
		.filter((l) => l.includes("): error TS"))
		.map((l) => {
			const m = /^(.*?)\(\d+,\d+\): error (TS\d+): (.*)$/.exec(l);
			return {
				file: (m?.[1] ?? l).replace(/\\/g, "/"),
				code: m?.[2] ?? "",
				text: m?.[3] ?? l,
			};
		});
	return cached;
}

test("negative types: .write() inside a read_only command does not compile", () => {
	const d = diagnostics().filter((x) =>
		x.file.endsWith("write_in_read_only.ts"),
	);
	assert.equal(d.length, 1, JSON.stringify(diagnostics()));
	assert.equal(d[0]?.code, "TS2339");
	assert.equal(
		d[0]?.text,
		"Property 'write' does not exist on type 'ReadOnlyEffects'.",
	);
});

test("negative types: .spawn() inside a read_only command does not compile", () => {
	const d = diagnostics().filter((x) =>
		x.file.endsWith("spawn_in_read_only.ts"),
	);
	assert.equal(d.length, 1);
	assert.equal(
		d[0]?.text,
		"Property 'spawn' does not exist on type 'ReadOnlyEffects'.",
	);
});

test("negative types: the passthrough twins narrow ctx the same way", () => {
	const d = diagnostics().filter((x) =>
		x.file.endsWith("read_only_passthrough_write.ts"),
	);
	assert.equal(d.length, 1);
	assert.equal(
		d[0]?.text,
		"Property 'mkdir' does not exist on type 'ReadOnlyEffects'.",
	);
});

test("negative types: extracting from a SETTLED-typed result compiles cleanly", () => {
	// No `| Unsettled` union and no narrowing predicate: one handler body
	// typechecks once and is correct in both modes. The runtime seal is what
	// catches the dry-mode extraction (see tests/effects.test.ts).
	const d = diagnostics().filter((x) =>
		x.file.endsWith("positive_settled_extraction.ts"),
	);
	assert.deepEqual(d, []);
});

test("negative types: a COMPUTED choice key does not compile, naming itself", () => {
	// A computed key would silently degrade the delivered tag to `string` and
	// make assertNever accept anything. Since silence is the failure mode, the
	// choice map is constrained to literal keys (contract §24.12).
	const d = diagnostics().filter((x) =>
		x.file.endsWith("computed_choice_key.ts"),
	);
	assert.equal(d.length, 1, JSON.stringify(d));
	assert.equal(d[0]?.code, "TS2345");
	// The constraint names itself in the compiler's elaboration, which is the
	// "compile error naming itself" §24.12 asks for.
	assert.match(cachedRaw, /__choice_keys_must_be_literal/);
});

test("negative types: the two-member floor and the `when` union are compile errors", () => {
	// §26.6's two TypeScript payoffs. The floor makes a one-member constraint
	// unwritable by an ordinary caller, and the literal union makes a `when`
	// typo a compile error rather than a registration one.
	const d = diagnostics().filter((x) =>
		x.file.endsWith("constraint_member_floor.ts"),
	);
	assert.equal(d.length, 2, JSON.stringify(d));
	assert.equal(d[0]?.code, "TS2322");
	assert.equal(
		d[0]?.text,
		"Type '[{ name: string; }]' is not assignable to type 'ConstraintMembers'.",
	);
	assert.equal(d[1]?.code, "TS2820");
	assert.equal(
		d[1]?.text,
		`Type '"nonempty"' is not assignable to type 'When'. Did you mean '"non_empty"'?`,
	);
});

test("negative types: a selector default naming no choice does not compile", () => {
	// Typed `keyof C & string`, so the mistake is a COMPILE error before it is
	// a registration error (§24.12).
	const d = diagnostics().filter((x) =>
		x.file.endsWith("selector_default_unknown_choice.ts"),
	);
	assert.equal(d.length, 1, JSON.stringify(d));
	assert.equal(d[0]?.code, "TS2322");
	assert.equal(
		d[0]?.text,
		`Type '"pigeon"' is not assignable to type '"email" | "sms"'.`,
	);
});

test("negative types: a sub-flag is not a top-level arg, and the switch is exhaustive", () => {
	// The structural fix for infer.ts's remaining unsoundness: a scope's flags
	// are unreachable except through the tag that proves the scope was elected
	// (§24.12).
	const d = diagnostics().filter((x) =>
		x.file.endsWith("scoped_flag_is_not_top_level.ts"),
	);
	assert.equal(d.length, 2, JSON.stringify(d));
	assert.equal(d[0]?.code, "TS2339");
	assert.match(d[0]?.text ?? "", /^Property 'subject' does not exist on type/);
	// assertNever refuses the unhandled `sms` member: the missing case is a
	// compile error at the default branch.
	assert.equal(d[1]?.code, "TS2345");
	assert.match(d[1]?.text ?? "", /readonly choice: "sms"/);
	assert.match(
		d[1]?.text ?? "",
		/is not assignable to parameter of type 'never'/,
	);
});

test("negative types: the fixture project produces exactly the pinned errors", () => {
	assert.equal(diagnostics().length, 9, JSON.stringify(diagnostics()));
});
