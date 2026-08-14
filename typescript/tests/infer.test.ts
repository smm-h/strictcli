import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { InferHandler } from "../src/index.js";
import {
	arg,
	assertNever,
	choice,
	defineReadOnlyCommand,
	flag,
	memberChoiceFlag,
	t,
} from "../src/index.js";

// Exact type equality via the conditional-generic-signature trick (see
// docs/history/_ts-port-spec.md, "Equals type-assertion technique").
type Equals<A, B> =
	(<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
		? true
		: false;
type Assert<T extends true> = T;

// --- Canonical 5-member example from the spec ---

const build = defineReadOnlyCommand("build", {
	help: "Build the project",
	flags: {
		sim_run: flag("sim-run", t.bool, {
			help: "Dry run",
			presence: "default",
			default: true,
		}),
		count: flag("count", t.int, { help: "How many", presence: "required" }),
		tag: flag("tag", t.list(t.str), {
			help: "Tags",
			presence: "default",
			default: [],
		}),
		meta: flag("meta", t.dict(t.int), {
			help: "Metadata",
			presence: "default",
			default: new Map(),
		}),
	},
	args: [
		arg("values", t.float, {
			help: "Values",
			variadic: true,
			presence: "required",
		}),
	],
	handler: (args) => {
		// Assignment checks inside the handler mirror the spike.
		const used: [boolean, bigint, string[], Map<string, bigint>, number[]] = [
			args.sim_run,
			args.count,
			args.tag,
			args.meta,
			args.values,
		];
		return used.length - 5;
	},
});

type BuildArgs = InferHandler<typeof build>;
type Expected = {
	sim_run: boolean;
	count: bigint;
	tag: string[];
	meta: Map<string, bigint>;
	values: number[];
};
export type _Canonical = Assert<Equals<BuildArgs, Expected>>;

// Negative control: a deliberately wrong shape must NOT be equal.
export type _CanonicalNegative = Assert<
	Equals<Equals<BuildArgs, Omit<Expected, "count">>, false>
>;

test("defineReadOnlyCommand normalizes carrier fields", () => {
	assert.equal(build.kind, "command");
	assert.equal(build.name, "build");
	assert.equal(build.help, "Build the project");
	assert.deepEqual(build.tags, []);
	assert.equal(build.hidden, false);
	assert.equal(build.interactive, false);
	assert.deepEqual(build.configFields, []);
	assert.equal(build.args.length, 1);
	assert.equal(build.flags.count.schema, "int");
});

test("flags and args default to empty when omitted", () => {
	const ping = defineReadOnlyCommand("ping", {
		help: "Ping",
		handler: () => 0,
	});
	assert.deepEqual(ping.flags, {});
	assert.deepEqual(ping.args, []);
});

// --- True optional-key modifier for explicitly-optional scalars ---

const fetchCmd = defineReadOnlyCommand("fetch", {
	help: "Fetch a resource",
	flags: {
		url: flag("url", t.str, { help: "URL", presence: "optional" }),
		retries: flag("retries", t.int, {
			help: "Retries",
			presence: "default",
			default: 3n,
		}),
	},
	handler: (args) => (args.url === undefined ? Number(args.retries) : 0),
});

type FetchArgs = InferHandler<typeof fetchCmd>;
export type _TrueOptional = Assert<
	Equals<FetchArgs, { url?: string; retries: bigint }>
>;
// The distinction that matters: `url?: string` is NOT `url: string | undefined`.
export type _NotUndefinedUnion = Assert<
	Equals<Equals<FetchArgs, { url: string | undefined; retries: bigint }>, false>
>;

// --- Arg optionality: required present, optional-no-default gets `?:` ---

const cp = defineReadOnlyCommand("cp", {
	help: "Copy a file",
	args: [
		arg("src", t.str, { help: "Source", presence: "required" }),
		arg("dest", t.str, { help: "Destination", presence: "optional" }),
		arg("mode", t.str, { help: "Mode", presence: "default", default: "fast" }),
	],
	handler: (args) => (args.dest === undefined ? args.mode.length : 0),
});

export type _ArgOptionality = Assert<
	Equals<InferHandler<typeof cp>, { src: string; dest?: string; mode: string }>
>;

// --- A selector delivers ONE tagged value; sub-flags are never top-level ---
// Before this construct, mutex members were intersected into the top-level
// args as always-present non-nullable keys while the parser handed them
// `undefined`. A scope's flags are now reachable ONLY through the tag that
// proves the scope was elected, so the failure mode is inexpressible
// (contract §23.2, §24.12).

const pick = defineReadOnlyCommand("pick", {
	help: "Pick a source",
	flags: {
		source: memberChoiceFlag(
			"source",
			{
				"from-file": choice({ help: "From a file", value: t.str }),
				"from-url": choice({
					help: "From a URL",
					flags: {
						retries: flag("retries", t.int, {
							help: "Retry count",
							presence: "default",
							default: 3n,
						}),
						proxy: flag("proxy", t.str, {
							help: "Proxy",
							presence: "optional",
						}),
					},
				}),
			},
			{ help: "Where to read from", presence: "required" },
		),
	},
	handler: (args) => {
		switch (args.source.choice) {
			case "from-file":
				return args.source.value.length;
			case "from-url":
				return Number(args.source.retries);
			default:
				return assertNever(args.source);
		}
	},
});

declare const pickArgs: InferHandler<typeof pick>;
void [
	// The delivered union is exact: the tag narrows to the literal names.
	(): "from-file" | "from-url" => pickArgs.source.choice,
	// A sub-flag is NEVER a top-level key.
	// @ts-expect-error `retries` belongs to the from-url scope, not to args
	(): unknown => pickArgs.retries,
	// A scoped optional sub-flag's key is optional in the derived union.
	(): string | undefined =>
		pickArgs.source.choice === "from-url" ? pickArgs.source.proxy : undefined,
	// A scoped defaulted sub-flag is always present.
	(): bigint | undefined =>
		pickArgs.source.choice === "from-url" ? pickArgs.source.retries : undefined,
	// The payload of a value-carrying member reaches its own branch only.
	(): unknown =>
		pickArgs.source.choice === "from-url"
			? // @ts-expect-error `value` exists only on the from-file member
				pickArgs.source.value
			: "",
];

// --- Optionality reaches compound carriers too ---

const gather = defineReadOnlyCommand("gather", {
	help: "Gather things",
	flags: {
		tag: flag("tag", t.list(t.str), { help: "Tags", presence: "optional" }),
		meta: flag("meta", t.dict(t.int), { help: "Meta", presence: "optional" }),
		port: flag("port", t.int, { help: "Port", presence: "required" }),
	},
	handler: (args) => (args.tag === undefined ? Number(args.port) : 0),
});

export type _CompoundOptionality = Assert<
	Equals<
		InferHandler<typeof gather>,
		{ port: bigint; tag?: string[]; meta?: Map<string, bigint> }
	>
>;

// --- A variadic arg is always present, whatever its presence declaration ---

const collect = defineReadOnlyCommand("collect", {
	help: "Collect files",
	args: [
		arg("files", t.str, {
			help: "Files",
			variadic: true,
			presence: "optional",
		}),
	],
	handler: (args) => args.files.length,
});

export type _VariadicAlwaysPresent = Assert<
	Equals<InferHandler<typeof collect>, { files: string[] }>
>;
