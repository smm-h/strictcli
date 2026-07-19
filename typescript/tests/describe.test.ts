/**
 * Accuracy enforcement for the hand-maintained SURFACE registry in
 * src/describe.ts, in both directions:
 *
 * - Forward: every listed name exists on the real exports. Value names are
 *   checked at runtime (typeof against the index namespace, prototype walks
 *   for classes, Object.keys for factory-built carriers); type names and
 *   member lists are checked at compile time (keyof equality assertions and
 *   a witness object covering every entry of SURFACE.types), which the test
 *   build enforces because tests compile with tsc before running.
 * - Reverse: every src/index.ts export (value and type) is listed in the
 *   registry, by parsing the index source. The registry universe and the
 *   index export set must be EQUAL -- surface closure.
 */

import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
	describeSurface,
	describeSurfaceJson,
	SURFACE,
} from "../src/describe.js";
import * as api from "../src/index.js";

// --- Compile-time machinery (see ts-port-spec.md, "Equals type-assertion technique") ---

type Equals<A, B> =
	(<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
		? true
		: false;
type Assert<T extends true> = T;
type KeysOfUnion<T> = T extends unknown ? keyof T & string : never;
/** Keys of T whose (non-optional, non-null) value type is not `never`. */
type NonNeverKeys<T> = {
	[K in keyof T]-?: [NonNullable<T[K]>] extends [never] ? never : K & string;
}[keyof T];
type NonNeverKeysOfUnion<T> = T extends unknown ? NonNeverKeys<T> : never;

// Registry lookups: struct members, method names per receiver, option keys.
type StructEntry<N extends string> = Extract<
	(typeof SURFACE.structs)[number],
	{ readonly name: N }
>;
type Members<N extends string> = StructEntry<N>["members"][number];
type Methods<R extends string> = Extract<
	(typeof SURFACE.methods)[number],
	{ readonly receiver: R }
>["name"];
type Listed<N extends string> = Members<N> | Methods<N>;
type OC<N extends string> = Extract<
	(typeof SURFACE.option_constructors)[number],
	{ readonly name: N }
>;
type OCKeys<N extends string> = OC<N>["option_keys"][number];

// --- Compile-time: struct/method member lists match the real types exactly ---

export type _App = Assert<Equals<keyof api.App & string, Listed<"App">>>;
export type _Group = Assert<Equals<keyof api.Group & string, Listed<"Group">>>;
export type _GroupSpec = Assert<
	Equals<keyof api.GroupSpec & string, Listed<"GroupSpec">>
>;
export type _Result = Assert<
	Equals<keyof api.Result & string, Listed<"Result">>
>;
export type _RunChecksOptions = Assert<
	Equals<keyof api.RunChecksOptions & string, Listed<"RunChecksOptions">>
>;
export type _RunChecksResult = Assert<
	Equals<keyof api.RunChecksResult & string, Listed<"RunChecksResult">>
>;
export type _CommandDef = Assert<
	Equals<
		keyof api.CommandDef<string, api.FlagMap, readonly api.AnyArg[]> & string,
		Listed<"CommandDef">
	>
>;
export type _AnyCommandSameKeys = Assert<
	Equals<keyof api.AnyCommand & string, Listed<"CommandDef">>
>;
export type _FlagDef = Assert<
	Equals<
		keyof api.FlagDef<string, string, "str", api.FlagOpts<string, "str">> &
			string,
		Listed<"FlagDef">
	>
>;
export type _ArgDef = Assert<
	Equals<
		keyof api.ArgDef<string, string, "str", api.ArgOpts<string, "str">> &
			string,
		Listed<"ArgDef">
	>
>;
export type _FlagSet = Assert<
	Equals<keyof api.FlagSet<string, api.FlagMap> & string, Listed<"FlagSet">>
>;
export type _MutexGroup = Assert<
	Equals<keyof api.MutexGroup<api.FlagMap> & string, Listed<"MutexGroup">>
>;
export type _CoRequired = Assert<
	Equals<keyof api.CoRequired & string, Listed<"CoRequired">>
>;
export type _Requires = Assert<
	Equals<keyof api.Requires & string, Listed<"Requires">>
>;
export type _Implies = Assert<
	Equals<keyof api.Implies & string, Listed<"Implies">>
>;
export type _PassthroughDef = Assert<
	Equals<keyof api.PassthroughDef<string> & string, Listed<"PassthroughDef">>
>;
export type _PassthroughArgs = Assert<
	Equals<keyof api.PassthroughArgs & string, Listed<"PassthroughArgs">>
>;
export type _DeprecatedDef = Assert<
	Equals<keyof api.DeprecatedDef<string> & string, Listed<"DeprecatedDef">>
>;
export type _Outcome = Assert<
	Equals<keyof api.Outcome & string, Listed<"Outcome">>
>;
export type _Carrier = Assert<
	Equals<keyof api.Carrier<string, "str"> & string, Listed<"Carrier">>
>;
export type _Tool = Assert<Equals<keyof api.Tool & string, Listed<"Tool">>>;
export type _ConfigFieldSpec = Assert<
	Equals<keyof api.ConfigFieldSpec & string, Listed<"ConfigFieldSpec">>
>;
export type _InfraAccess = Assert<
	Equals<keyof api.InfraAccess & string, Listed<"InfraAccess">>
>;
export type _Writer = Assert<
	Equals<keyof api.Writer & string, Listed<"Writer">>
>;
export type _InfraRootPath = Assert<
	Equals<keyof api.InfraRootPath & string, Listed<"InfraRootPath">>
>;
export type _McpIO = Assert<Equals<keyof api.McpIO & string, Listed<"McpIO">>>;
export type _CheckContext = Assert<
	Equals<keyof api.CheckContext & string, Listed<"CheckContext">>
>;
export type _CheckProblem = Assert<
	Equals<keyof api.CheckProblem & string, Listed<"CheckProblem">>
>;
export type _CheckOutcome = Assert<
	Equals<keyof api.CheckOutcome & string, Listed<"CheckOutcome">>
>;
export type _CheckRunResult = Assert<
	Equals<keyof api.CheckRunResult & string, Listed<"CheckRunResult">>
>;
export type _CheckSpec = Assert<
	Equals<keyof api.CheckSpec & string, Listed<"CheckSpec">>
>;
// Method-only receivers (no data members).
export type _Context = Assert<
	Equals<keyof api.Context & string, Listed<"Context">>
>;
export type _ErrorReporter = Assert<
	Equals<keyof api.ErrorReporter & string, Listed<"ErrorReporter">>
>;
export type _WarnReporter = Assert<
	Equals<keyof api.WarnReporter & string, Listed<"WarnReporter">>
>;

// --- Compile-time: option constructor keys match the real option types ---

export type _FlagOptKeys = Assert<
	Equals<keyof api.FlagOpts<string, "str"> & string, OCKeys<"flag">>
>;
export type _ArgOptKeys = Assert<
	Equals<KeysOfUnion<api.ArgOpts<string, "str">>, OCKeys<"arg">>
>;
export type _CommandSpecKeys = Assert<
	Equals<
		keyof api.CommandSpec<api.FlagMap, readonly api.AnyArg[]> & string,
		OCKeys<"defineCommand">
	>
>;
export type _AppSpecKeys = Assert<
	Equals<keyof api.AppSpec & string, OCKeys<"createApp">>
>;
export type _PassthroughSpecKeys = Assert<
	Equals<
		keyof Parameters<typeof api.passthrough>[1] & string,
		OCKeys<"passthrough">
	>
>;
export type _RequiresSpecKeys = Assert<
	Equals<keyof Parameters<typeof api.requires>[0] & string, OCKeys<"requires">>
>;
export type _ImpliesSpecKeys = Assert<
	Equals<keyof Parameters<typeof api.implies>[0] & string, OCKeys<"implies">>
>;
export type _ErrorCheckSpecKeys = Assert<
	Equals<keyof api.ErrorCheckSpecInit & string, OCKeys<"errorCheckSpec">>
>;
export type _WarnCheckSpecKeys = Assert<
	Equals<keyof api.WarnCheckSpecInit & string, OCKeys<"warnCheckSpec">>
>;

// Per-carrier applicability: keys whose option type is not `never` for that
// carrier kind must match the registry's per_carrier lists exactly.
type FlagPC = OC<"flag">["per_carrier"];
export type _FlagPCBool = Assert<
	Equals<NonNeverKeys<api.FlagOpts<boolean, "bool">>, FlagPC["bool"][number]>
>;
export type _FlagPCScalar = Assert<
	Equals<NonNeverKeys<api.FlagOpts<string, "str">>, FlagPC["scalar"][number]>
>;
export type _FlagPCList = Assert<
	Equals<
		NonNeverKeys<api.FlagOpts<string[], "list[str]">>,
		FlagPC["list"][number]
	>
>;
export type _FlagPCDict = Assert<
	Equals<
		NonNeverKeys<api.FlagOpts<Map<string, string>, "dict[str,str]">>,
		FlagPC["dict"][number]
	>
>;
type ArgPC = OC<"arg">["per_carrier"];
export type _ArgPCBool = Assert<
	Equals<
		NonNeverKeysOfUnion<api.ArgOpts<boolean, "bool">>,
		ArgPC["bool"][number]
	>
>;
export type _ArgPCScalar = Assert<
	Equals<
		NonNeverKeysOfUnion<api.ArgOpts<string, "str">>,
		ArgPC["scalar"][number]
	>
>;

// --- Compile-time: every SURFACE.types entry names a real type export ---

type TypeName = (typeof SURFACE.types)[number];
function witnessType<T>(): T | undefined {
	return undefined;
}
// Record<TypeName, ...> forces exactly the registry's names (missing keys
// and excess keys are both compile errors); each value references the api
// type, so a listed-but-nonexistent type is a compile error too.
const typeWitness: Record<TypeName, unknown> = {
	AnyArg: witnessType<api.AnyArg>(),
	AnyCommand: witnessType<api.AnyCommand>(),
	AnyFlag: witnessType<api.AnyFlag>(),
	AnyFlagSet: witnessType<api.AnyFlagSet>(),
	AnyMutexGroup: witnessType<api.AnyMutexGroup>(),
	App: witnessType<api.App>(),
	AppSpec: witnessType<api.AppSpec>(),
	ArgDef:
		witnessType<
			api.ArgDef<string, string, "str", api.ArgOpts<string, "str">>
		>(),
	ArgOpts: witnessType<api.ArgOpts<string, "str">>(),
	Carrier: witnessType<api.Carrier<string, "str">>(),
	CheckContext: witnessType<api.CheckContext>(),
	CheckOutcome: witnessType<api.CheckOutcome>(),
	CheckProblem: witnessType<api.CheckProblem>(),
	CheckSeverity: witnessType<api.CheckSeverity>(),
	CheckStatus: witnessType<api.CheckStatus>(),
	CoRequired: witnessType<api.CoRequired>(),
	CommandDef:
		witnessType<api.CommandDef<string, api.FlagMap, readonly api.AnyArg[]>>(),
	CommandSpec:
		witnessType<api.CommandSpec<api.FlagMap, readonly api.AnyArg[]>>(),
	ConfigFieldSpec: witnessType<api.ConfigFieldSpec>(),
	ConflictMode: witnessType<api.ConflictMode>(),
	Dependency: witnessType<api.Dependency>(),
	DeprecatedDef: witnessType<api.DeprecatedDef<string>>(),
	DictSchema: witnessType<api.DictSchema>(),
	ElemSchema: witnessType<api.ElemSchema>(),
	ElementOf: witnessType<api.ElementOf<string[]>>(),
	ErrorCheckSpecInit: witnessType<api.ErrorCheckSpecInit>(),
	FlagDef:
		witnessType<
			api.FlagDef<string, string, "str", api.FlagOpts<string, "str">>
		>(),
	FlagMap: witnessType<api.FlagMap>(),
	FlagOpts: witnessType<api.FlagOpts<string, "str">>(),
	FlagSet: witnessType<api.FlagSet<string, api.FlagMap>>(),
	Group: witnessType<api.Group>(),
	GroupSpec: witnessType<api.GroupSpec>(),
	Handler: witnessType<api.Handler<api.FlagMap, readonly api.AnyArg[]>>(),
	HandlerArgs:
		witnessType<
			api.HandlerArgs<
				api.FlagMap,
				readonly api.AnyArg[],
				readonly [],
				readonly []
			>
		>(),
	HandlerResult: witnessType<api.HandlerResult>(),
	HandlerReturn: witnessType<api.HandlerReturn>(),
	Implies: witnessType<api.Implies>(),
	InferHandler: witnessType<api.InferHandler<api.AnyCommand>>(),
	InferHandlerArgs:
		witnessType<api.InferHandlerArgs<api.FlagMap, readonly api.AnyArg[]>>(),
	InfraAccess: witnessType<api.InfraAccess>(),
	InfraRootPath: witnessType<api.InfraRootPath>(),
	ListSchema: witnessType<api.ListSchema>(),
	McpIO: witnessType<api.McpIO>(),
	MutexGroup: witnessType<api.MutexGroup<api.FlagMap>>(),
	Outcome: witnessType<api.Outcome>(),
	PassthroughArgs: witnessType<api.PassthroughArgs>(),
	PassthroughDef: witnessType<api.PassthroughDef<string>>(),
	PassthroughHandler: witnessType<api.PassthroughHandler>(),
	Requires: witnessType<api.Requires>(),
	Result: witnessType<api.Result>(),
	RunChecksOptions: witnessType<api.RunChecksOptions>(),
	RunChecksResult: witnessType<api.RunChecksResult>(),
	ScalarSchema: witnessType<api.ScalarSchema>(),
	Schema: witnessType<api.Schema>(),
	Tool: witnessType<api.Tool>(),
	WarnCheckSpecInit: witnessType<api.WarnCheckSpecInit>(),
	Writer: witnessType<api.Writer>(),
};

// --- Runtime: registry universe and value-name helpers ---

const constructorNames = SURFACE.option_constructors.map((c) => c.name);
const constantNames = SURFACE.constants.map((c) => c.name);
const valueNames: string[] = [
	...SURFACE.functions,
	...constructorNames,
	...SURFACE.classes,
	...constantNames,
];
const universe = new Set<string>([...valueNames, ...SURFACE.types]);
const apiRecord = api as unknown as Record<string, unknown>;

test("registry: value names are unique across sections", () => {
	assert.equal(new Set(valueNames).size, valueNames.length);
	// Types must not repeat value names (classes are listed as values only).
	for (const t of SURFACE.types) {
		assert.ok(!valueNames.includes(t), `type name also listed as value: ${t}`);
	}
});

test("registry: every listed value name exists on the index exports", () => {
	for (const name of [...SURFACE.functions, ...constructorNames]) {
		assert.equal(
			typeof apiRecord[name],
			"function",
			`missing function ${name}`,
		);
	}
	for (const name of SURFACE.classes) {
		assert.equal(typeof apiRecord[name], "function", `missing class ${name}`);
	}
	for (const c of SURFACE.constants) {
		assert.equal(typeof apiRecord[c.name], c.type, `constant ${c.name}`);
	}
});

test("registry: runtime index exports are exactly the registry value names", () => {
	assert.deepEqual(
		Object.keys(apiRecord).sort(),
		[...new Set(valueNames)].sort(),
	);
});

test("registry: every index.ts export (value and type) is listed, and vice versa", () => {
	const indexPath = new URL("../../src/index.ts", import.meta.url);
	const source = readFileSync(fileURLToPath(indexPath), "utf8");
	const exported = new Set<string>();
	for (const m of source.matchAll(
		/export\s+(?:type\s+)?\{([\s\S]*?)\}\s+from/g,
	)) {
		const body = m[1] as string;
		for (const raw of body.split(",")) {
			const name = raw.trim();
			if (name === "") {
				continue;
			}
			// `X as Y` re-exports would surface as Y; none exist today.
			const parts = name.split(/\s+as\s+/);
			exported.add((parts[parts.length - 1] as string).trim());
		}
	}
	for (const m of source.matchAll(/export\s+const\s+(\w+)/g)) {
		exported.add(m[1] as string);
	}
	assert.deepEqual(
		[...exported].sort(),
		[...universe].sort(),
		"registry universe and index.ts export set must be equal",
	);
});

test("registry: check_system names are all part of the surface", () => {
	for (const name of SURFACE.check_system) {
		assert.ok(universe.has(name), `check_system name not in surface: ${name}`);
	}
});

test("registry: struct names and method receivers are part of the surface", () => {
	for (const s of SURFACE.structs) {
		assert.ok(universe.has(s.name), `struct name not in surface: ${s.name}`);
	}
	for (const m of SURFACE.methods) {
		assert.ok(
			universe.has(m.receiver),
			`receiver not in surface: ${m.receiver}`,
		);
	}
});

// --- Runtime: factory-built carriers expose exactly the listed members ---

function members(name: string): readonly string[] {
	const entry = SURFACE.structs.find((s) => s.name === name);
	assert.ok(entry, `no struct entry for ${name}`);
	return entry.members;
}

/** Registry members minus phantom type-only members (never set at runtime). */
function runtimeMembers(name: string): string[] {
	return members(name).filter((m) => m !== "_out");
}

test("registry: runtime keys of factory-built carriers match declaration order", () => {
	const f = api.flag("target", api.t.str, { help: "h" });
	assert.deepEqual(Object.keys(f), runtimeMembers("FlagDef"));
	const a = api.arg("src", api.t.str, { help: "h" });
	assert.deepEqual(Object.keys(a), runtimeMembers("ArgDef"));
	const cmd = api.defineCommand("run", {
		help: "h",
		handler: () => 0,
	});
	assert.deepEqual(Object.keys(cmd), runtimeMembers("CommandDef"));
	const fs = api.flagSet("common", { target: f });
	assert.deepEqual(Object.keys(fs), runtimeMembers("FlagSet"));
	const mg = api.mutexGroup({
		json: api.flag("json", api.t.bool, { help: "h", default: false }),
		plain: api.flag("plain", api.t.bool, { help: "h", default: false }),
	});
	assert.deepEqual(Object.keys(mg), runtimeMembers("MutexGroup"));
	assert.deepEqual(
		Object.keys(api.coRequired(["a", "b"])),
		runtimeMembers("CoRequired"),
	);
	assert.deepEqual(
		Object.keys(api.requires({ flag: "a", dependsOn: "b" })),
		runtimeMembers("Requires"),
	);
	assert.deepEqual(
		Object.keys(api.implies({ flag: "a", implies: "b", value: true })),
		runtimeMembers("Implies"),
	);
	const p = api.passthrough("git", { help: "h", handler: () => 0 });
	assert.deepEqual(Object.keys(p), runtimeMembers("PassthroughDef"));
	assert.deepEqual(
		Object.keys(api.deprecated("old", "gone")),
		runtimeMembers("DeprecatedDef"),
	);
	assert.deepEqual(Object.keys(api.outcome(0)), runtimeMembers("Outcome"));
	// relativeToRoot markers additionally carry a toString own-property
	// (Python repr parity), so containment rather than exact equality.
	const marker = api.relativeToRoot("MYROOT", "cache") as unknown as Record<
		string,
		unknown
	>;
	for (const m of runtimeMembers("InfraRootPath")) {
		assert.ok(m in marker, `InfraRootPath missing ${m}`);
	}
});

test("registry: class prototypes expose the listed methods", () => {
	const contextMethods = SURFACE.methods
		.filter((m) => m.receiver === "Context")
		.map((m) => m.name)
		.sort();
	assert.deepEqual(
		Object.getOwnPropertyNames(api.Context.prototype)
			.filter((n) => n !== "constructor")
			.sort(),
		contextMethods,
	);
	// Reporter methods live on a shared (unexported) base prototype; check
	// presence through the chain instead of own-property equality.
	const protoHas = (proto: object, name: string): boolean =>
		typeof (proto as Record<string, unknown>)[name] === "function";
	for (const m of SURFACE.methods.filter(
		(m) => m.receiver === "ErrorReporter",
	)) {
		assert.ok(
			protoHas(api.ErrorReporter.prototype, m.name),
			`ErrorReporter.${m.name}`,
		);
	}
	for (const m of SURFACE.methods.filter(
		(m) => m.receiver === "WarnReporter",
	)) {
		assert.ok(
			protoHas(api.WarnReporter.prototype, m.name),
			`WarnReporter.${m.name}`,
		);
	}
	// WarnReporter structurally lacks error-minting.
	assert.ok(!protoHas(api.WarnReporter.prototype, "error"));
	// CheckRunResult: fields arrive via constructor; getters and methods are
	// on the prototype.
	for (const name of ["status", "message", "problems", "notes"]) {
		assert.ok(
			Object.getOwnPropertyDescriptor(api.CheckRunResult.prototype, name)
				?.get !== undefined,
			`CheckRunResult getter ${name}`,
		);
	}
	for (const m of SURFACE.methods.filter(
		(m) => m.receiver === "CheckRunResult",
	)) {
		assert.ok(
			protoHas(api.CheckRunResult.prototype, m.name),
			`CheckRunResult.${m.name}`,
		);
	}
});

test("registry: app.test() results carry only listed Result members", async () => {
	const app = api.createApp({ name: "myapp", version: "1.0.0", help: "demo" });
	app.command(api.defineCommand("run", { help: "h", handler: () => 0 }));
	const res = await app.test(["run"]);
	const listed = members("Result");
	for (const key of Object.keys(res)) {
		assert.ok(listed.includes(key), `unlisted Result member: ${key}`);
	}
	for (const required of ["stdout", "stderr", "exitCode"]) {
		assert.ok(required in res, `Result missing ${required}`);
	}
});

// --- The dump itself ---

test("describeSurface: shape-aligned, deterministically sorted, JSON round-trips", () => {
	const dump = describeSurface();
	assert.deepEqual(Object.keys(dump), [
		"schema_version",
		"package",
		"structs",
		"option_constructors",
		"functions",
		"methods",
		"constants",
		"classes",
		"types",
		"check_system",
	]);
	assert.equal(dump.schema_version, 1);
	assert.equal(dump.package, "strictcli");
	const structNames = dump.structs.map((s) => s.name);
	assert.deepEqual(structNames, [...structNames].sort());
	const ctorNames = dump.option_constructors.map((c) => c.name);
	assert.deepEqual(ctorNames, [...ctorNames].sort());
	assert.deepEqual(dump.functions, [...dump.functions].sort());
	assert.deepEqual(dump.types, [...dump.types].sort());
	assert.deepEqual(dump.classes, [...dump.classes].sort());
	assert.deepEqual(dump.check_system, [...dump.check_system].sort());
	// The bin output is the same object, pretty-printed with a trailing newline.
	const parsed = JSON.parse(describeSurfaceJson());
	assert.deepEqual(parsed, dump);
	assert.ok(describeSurfaceJson().endsWith("}\n"));
	// The witness object is compile-time machinery; anchor it to the test so
	// it is used at runtime too.
	assert.equal(Object.keys(typeWitness).length, SURFACE.types.length);
});
