import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { InferHandler } from "../src/index.js";
import {
	arg,
	defineReadOnlyCommand,
	flag,
	mutexGroup,
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

// --- Presence drives optionality, including for mutex members ---
// Before the presence declaration a mutex member declared no default, was
// typed as an always-present non-nullable key, and was handed `undefined` by
// the parser through the exemption contract §23.4 deletes. The member now
// declares `presence: "optional"` like anything else and the handler-args type
// follows the declaration by construction.

const pick = defineReadOnlyCommand("pick", {
	help: "Pick a source",
	mutex: [
		mutexGroup({
			from_file: flag("from-file", t.str, {
				help: "From a file",
				presence: "optional",
			}),
			from_url: flag("from-url", t.str, {
				help: "From a URL",
				presence: "default",
				default: "https://example.test",
			}),
		}),
	],
	handler: (args) => (args.from_file === undefined ? args.from_url.length : 0),
});

// A mutex group's flags reach the handler-args type through an intersection
// that TS keeps deferred, so these are assignability assertions rather than
// the Equals identity check the plain flag/arg cases use.
declare const pickArgs: InferHandler<typeof pick>;
void [
	// @ts-expect-error an optional mutex member is possibly undefined
	(): string => pickArgs.from_file,
	(): string | undefined => pickArgs.from_file,
	// A member declaring a default is always present and never undefined.
	(): string => pickArgs.from_url,
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
