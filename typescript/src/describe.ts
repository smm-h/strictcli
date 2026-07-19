/**
 * describe.ts -- dev-only self-dump of the TS public API surface, shape-
 * aligned with conformance/describe_go/main.go's output (schema_version,
 * package, structs, option_constructors, functions, methods, constants).
 * TypeScript has no runtime type info, so instead of reflection the surface
 * is a hand-maintained registry (SURFACE below) whose accuracy is enforced
 * by tests/describe.test.ts in both directions: every listed name must exist
 * on the real exports (runtime typeof checks plus compile-time keyof
 * equality assertions), and every src/index.ts export must be listed.
 *
 * TS analogs of the Go dumper's sections:
 * - structs: member lists of exported interfaces/classes that carry data
 *   (spec/option object types owned by a factory live under that factory's
 *   option_keys instead of here).
 * - option_constructors: factories that take an options/spec object, with
 *   the object's keys; flag/arg additionally record per-carrier
 *   applicability (never-typed keys are inexpressible for that carrier).
 * - functions: exported value functions that take only positional args.
 * - methods: receiver + name for interface/class method surfaces.
 * - constants: exported non-function values.
 * - classes / types / check_system: TS-only sections. classes are exported
 *   class values, types are the type-only index.ts exports (no Go analog --
 *   Go types are all values of the AST), check_system is the flat list of
 *   check-system public names.
 *
 * This module is intentionally NOT exported through index.ts: it is dev
 * tooling, not public API. Bin-style usage: node dist/describe.js
 */

import { pathToFileURL } from "node:url";

export const SCHEMA_VERSION = 1;

/**
 * The single source of truth for the TS public API surface. Set-like name
 * lists (option_keys, per_carrier, functions, classes, types, check_system)
 * are kept alphabetically sorted; struct member lists are in declaration
 * order (mirroring the Go dumper, which sorts every list except struct
 * fields). Phantom type-only members that never exist at runtime (_out) are
 * listed because keyof sees them; tests filter them for runtime key checks.
 */
export const SURFACE = {
	schema_version: SCHEMA_VERSION,
	package: "strictcli",

	structs: [
		{ name: "App", members: ["name", "version", "help"] },
		{ name: "Group", members: ["name", "help", "tags", "hidden"] },
		{ name: "GroupSpec", members: ["help", "tags", "hidden"] },
		{ name: "Result", members: ["stdout", "stderr", "exitCode", "data"] },
		{
			name: "RunChecksOptions",
			members: ["tagExpr", "nameGlob", "runAll", "ignoreWarnings", "pureOnly"],
		},
		{
			name: "RunChecksResult",
			members: ["results", "impureListed", "exitCode"],
		},
		{
			// The command carrier built by defineCommand.
			name: "CommandDef",
			members: [
				"kind",
				"name",
				"help",
				"flags",
				"args",
				"flagSets",
				"mutex",
				"dependencies",
				"allFlags",
				"handler",
				"tags",
				"hidden",
				"interactive",
				"configFields",
			],
		},
		{
			name: "FlagDef",
			members: ["kind", "name", "schema", "carrier", "opts", "_out"],
		},
		{
			name: "ArgDef",
			members: ["kind", "name", "schema", "carrier", "opts", "_out"],
		},
		{ name: "FlagSet", members: ["kind", "name", "flags"] },
		{ name: "MutexGroup", members: ["kind", "flags"] },
		{ name: "CoRequired", members: ["kind", "flags"] },
		{ name: "Requires", members: ["kind", "flag", "dependsOn"] },
		{ name: "Implies", members: ["kind", "flag", "implies", "value"] },
		{
			name: "PassthroughDef",
			members: ["kind", "name", "help", "handler", "tags", "hidden"],
		},
		{ name: "PassthroughArgs", members: ["name", "args", "globals"] },
		{ name: "DeprecatedDef", members: ["kind", "name", "message"] },
		{ name: "Outcome", members: ["exitCode", "data"] },
		{ name: "Carrier", members: ["_out", "schema", "parse", "elem"] },
		{
			name: "Tool",
			members: ["name", "description", "parameters", "execute"],
		},
		{ name: "ConfigFieldSpec", members: ["type", "help", "default"] },
		{ name: "InfraAccess", members: ["roots", "handshakes"] },
		{ name: "Writer", members: ["write"] },
		{ name: "InfraRootPath", members: ["envVar", "parts"] },
		{ name: "McpIO", members: ["input", "output"] },
		{ name: "CheckContext", members: ["projectRoot"] },
		{ name: "CheckProblem", members: ["severity", "text"] },
		{
			name: "CheckOutcome",
			members: ["kind", "message", "problems", "notes"],
		},
		{
			// gated()/warned() are under methods; these are fields and getters.
			name: "CheckRunResult",
			members: [
				"name",
				"outcome",
				"durationMs",
				"status",
				"message",
				"problems",
				"notes",
			],
		},
		{
			name: "CheckSpec",
			members: [
				"name",
				"tags",
				"severity",
				"fast",
				"pure",
				"needsNetwork",
				"dependsOn",
				"scope",
				"impl",
				"implForm",
			],
		},
	],

	option_constructors: [
		{
			name: "flag",
			options_type: "FlagOpts",
			option_keys: [
				"choices",
				"conflictMode",
				"default",
				"env",
				"envSeparator",
				"help",
				"negatable",
				"prefixed",
				"repeatable",
				"short",
				"unique",
				"validate",
			],
			// Keys expressible per carrier kind (never-typed keys excluded).
			// scalar = str/int/float.
			per_carrier: {
				bool: [
					"conflictMode",
					"default",
					"env",
					"help",
					"negatable",
					"prefixed",
					"short",
					"validate",
				],
				scalar: [
					"choices",
					"conflictMode",
					"default",
					"env",
					"help",
					"prefixed",
					"short",
					"validate",
				],
				list: [
					"choices",
					"conflictMode",
					"default",
					"env",
					"envSeparator",
					"help",
					"prefixed",
					"repeatable",
					"short",
					"unique",
					"validate",
				],
				dict: [
					"conflictMode",
					"default",
					"env",
					"help",
					"prefixed",
					"short",
					"validate",
				],
			},
		},
		{
			name: "arg",
			options_type: "ArgOpts",
			option_keys: ["choices", "default", "help", "required", "variadic"],
			// scalar = str/int/float; bool args cannot take choices.
			per_carrier: {
				bool: ["default", "help", "required", "variadic"],
				scalar: ["choices", "default", "help", "required", "variadic"],
			},
		},
		{
			name: "defineCommand",
			options_type: "CommandSpec",
			option_keys: [
				"args",
				"configFields",
				"dependencies",
				"flagSets",
				"flags",
				"handler",
				"help",
				"hidden",
				"interactive",
				"mutex",
				"tags",
			],
		},
		{
			name: "createApp",
			options_type: "AppSpec",
			option_keys: [
				"checksEmbed",
				"checksPath",
				"config",
				"configConflictMode",
				"configFormat",
				"configPath",
				"envPrefix",
				"flags",
				"handshakeEnv",
				"help",
				"infraRoot",
				"name",
				"noDefaultConfigPath",
				"testCoverage",
				"version",
			],
		},
		{
			name: "passthrough",
			options_type: "(inline spec)",
			option_keys: ["handler", "help", "hidden", "tags"],
		},
		{
			name: "requires",
			options_type: "(inline spec)",
			option_keys: ["dependsOn", "flag"],
		},
		{
			name: "implies",
			options_type: "(inline spec)",
			option_keys: ["flag", "implies", "value"],
		},
		{
			name: "errorCheckSpec",
			options_type: "ErrorCheckSpecInit",
			option_keys: [
				"dependsOn",
				"fast",
				"impl",
				"name",
				"needsNetwork",
				"pure",
				"scope",
				"severity",
				"tags",
			],
		},
		{
			name: "warnCheckSpec",
			options_type: "WarnCheckSpecInit",
			option_keys: [
				"dependsOn",
				"fast",
				"impl",
				"name",
				"needsNetwork",
				"pure",
				"scope",
				"severity",
				"tags",
			],
		},
	],

	functions: [
		"coRequired",
		"deprecated",
		"flagSet",
		"formatCheckResults",
		"formatCheckResultsJSON",
		"mutexGroup",
		"outcome",
		"relativeToRoot",
	],

	methods: [
		{ receiver: "App", name: "command" },
		{ receiver: "App", name: "group" },
		{ receiver: "App", name: "deprecate" },
		{ receiver: "App", name: "configField" },
		{ receiver: "App", name: "tagContract" },
		{ receiver: "App", name: "errorCheck" },
		{ receiver: "App", name: "warnCheck" },
		{ receiver: "App", name: "setCheckContext" },
		{ receiver: "App", name: "registerCheckProvider" },
		{ receiver: "App", name: "resetCheckProviderCache" },
		{ receiver: "App", name: "runChecks" },
		{ receiver: "App", name: "dumpSchemaDict" },
		{ receiver: "App", name: "call" },
		{ receiver: "App", name: "jsonSchema" },
		{ receiver: "App", name: "asTools" },
		{ receiver: "App", name: "serveMcp" },
		{ receiver: "App", name: "run" },
		{ receiver: "App", name: "test" },
		{ receiver: "Group", name: "command" },
		{ receiver: "Group", name: "group" },
		{ receiver: "Group", name: "deprecate" },
		{ receiver: "Context", name: "info" },
		{ receiver: "Context", name: "warn" },
		{ receiver: "Context", name: "debug" },
		{ receiver: "Context", name: "error" },
		{ receiver: "Context", name: "source" },
		{ receiver: "Context", name: "infraValue" },
		{ receiver: "ErrorReporter", name: "note" },
		{ receiver: "ErrorReporter", name: "warn" },
		{ receiver: "ErrorReporter", name: "error" },
		{ receiver: "ErrorReporter", name: "passed" },
		{ receiver: "ErrorReporter", name: "skipped" },
		{ receiver: "ErrorReporter", name: "found" },
		{ receiver: "WarnReporter", name: "note" },
		{ receiver: "WarnReporter", name: "warn" },
		{ receiver: "WarnReporter", name: "passed" },
		{ receiver: "WarnReporter", name: "skipped" },
		{ receiver: "WarnReporter", name: "found" },
		{ receiver: "CheckRunResult", name: "gated" },
		{ receiver: "CheckRunResult", name: "warned" },
	],

	constants: [
		{ name: "VERSION", type: "string" },
		{ name: "t", type: "object" },
	],

	classes: [
		"CheckRunResult",
		"CheckSpec",
		"Context",
		"ErrorReporter",
		"InvokeError",
		"WarnReporter",
	],

	types: [
		"AnyArg",
		"AnyCommand",
		"AnyFlag",
		"AnyFlagSet",
		"AnyMutexGroup",
		"App",
		"AppSpec",
		"ArgDef",
		"ArgOpts",
		"Carrier",
		"CheckContext",
		"CheckOutcome",
		"CheckProblem",
		"CheckSeverity",
		"CheckStatus",
		"CoRequired",
		"CommandDef",
		"CommandSpec",
		"ConfigFieldSpec",
		"ConflictMode",
		"Dependency",
		"DeprecatedDef",
		"DictSchema",
		"ElemSchema",
		"ElementOf",
		"ErrorCheckSpecInit",
		"FlagDef",
		"FlagMap",
		"FlagOpts",
		"FlagSet",
		"Group",
		"GroupSpec",
		"Handler",
		"HandlerArgs",
		"HandlerResult",
		"HandlerReturn",
		"Implies",
		"InferHandler",
		"InferHandlerArgs",
		"InfraAccess",
		"InfraRootPath",
		"ListSchema",
		"McpIO",
		"MutexGroup",
		"Outcome",
		"PassthroughArgs",
		"PassthroughDef",
		"PassthroughHandler",
		"Requires",
		"Result",
		"RunChecksOptions",
		"RunChecksResult",
		"ScalarSchema",
		"Schema",
		"Tool",
		"WarnCheckSpecInit",
		"Writer",
	],

	check_system: [
		"CheckContext",
		"CheckOutcome",
		"CheckProblem",
		"CheckRunResult",
		"CheckSeverity",
		"CheckSpec",
		"CheckStatus",
		"ErrorCheckSpecInit",
		"ErrorReporter",
		"RunChecksOptions",
		"RunChecksResult",
		"WarnCheckSpecInit",
		"WarnReporter",
		"errorCheckSpec",
		"formatCheckResults",
		"formatCheckResultsJSON",
		"warnCheckSpec",
	],
} as const;

/** JSON dump shape (the plain-object mirror of SURFACE, deterministically sorted). */
export interface SurfaceDump {
	schema_version: number;
	package: string;
	structs: { name: string; members: string[] }[];
	option_constructors: {
		name: string;
		options_type: string;
		option_keys: string[];
		per_carrier?: Record<string, string[]>;
	}[];
	functions: string[];
	methods: { receiver: string; name: string }[];
	constants: { name: string; type: string }[];
	classes: string[];
	types: string[];
	check_system: string[];
}

function cmp(a: string, b: string): number {
	return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Returns the surface as a deterministically-sorted plain object, applying
 * the Go dumper's sort discipline: every list is sorted by name before
 * emission EXCEPT struct member lists, which retain declaration order.
 */
export function describeSurface(): SurfaceDump {
	return {
		schema_version: SURFACE.schema_version,
		package: SURFACE.package,
		structs: SURFACE.structs
			.map((s) => ({ name: s.name, members: [...s.members] }))
			.sort((a, b) => cmp(a.name, b.name)),
		option_constructors: SURFACE.option_constructors
			.map((c) => {
				const entry: SurfaceDump["option_constructors"][number] = {
					name: c.name,
					options_type: c.options_type,
					option_keys: [...c.option_keys].sort(cmp),
				};
				if ("per_carrier" in c) {
					const pc: Record<string, string[]> = {};
					for (const [kind, keys] of Object.entries(c.per_carrier)) {
						pc[kind] = [...keys].sort(cmp);
					}
					entry.per_carrier = pc;
				}
				return entry;
			})
			.sort((a, b) => cmp(a.name, b.name)),
		functions: [...SURFACE.functions].sort(cmp),
		methods: SURFACE.methods
			.map((m) => ({ receiver: m.receiver, name: m.name }))
			.sort((a, b) => cmp(a.receiver, b.receiver) || cmp(a.name, b.name)),
		constants: SURFACE.constants
			.map((c) => ({ name: c.name, type: c.type }))
			.sort((a, b) => cmp(a.name, b.name)),
		classes: [...SURFACE.classes].sort(cmp),
		types: [...SURFACE.types].sort(cmp),
		check_system: [...SURFACE.check_system].sort(cmp),
	};
}

/** The dump as pretty-printed JSON with a trailing newline (bin output). */
export function describeSurfaceJson(): string {
	return `${JSON.stringify(describeSurface(), null, 2)}\n`;
}

// Bin-style entry: `node dist/describe.js` prints the surface JSON. The
// guard keeps imports silent (test runner, library consumers).
if (
	process.argv[1] !== undefined &&
	import.meta.url === pathToFileURL(process.argv[1]).href
) {
	process.stdout.write(describeSurfaceJson());
}
