import { strict as assert } from "node:assert";
import { test } from "node:test";
import type { InferHandler } from "../src/index.js";
import { arg, defineCommand, flag, t } from "../src/index.js";

// Exact type equality via the conditional-generic-signature trick (see
// ts-port-spec.md, "Equals type-assertion technique").
type Equals<A, B> =
	(<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
		? true
		: false;
type Assert<T extends true> = T;

// --- Canonical 5-member example from the spec ---

const build = defineCommand("build", {
	help: "Build the project",
	flags: {
		dry_run: flag("dry-run", t.bool, { help: "Dry run", default: true }),
		count: flag("count", t.int, { help: "How many" }),
		tag: flag("tag", t.list(t.str), { help: "Tags" }),
		meta: flag("meta", t.dict(t.int), { help: "Metadata" }),
	},
	args: [arg("values", t.float, { help: "Values", variadic: true })],
	handler: (args) => {
		// Assignment checks inside the handler mirror the spike.
		const used: [boolean, bigint, string[], Map<string, bigint>, number[]] = [
			args.dry_run,
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
	dry_run: boolean;
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

test("defineCommand normalizes carrier fields", () => {
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
	const ping = defineCommand("ping", { help: "Ping", handler: () => 0 });
	assert.deepEqual(ping.flags, {});
	assert.deepEqual(ping.args, []);
});

// --- True optional-key modifier for explicitly-optional scalars ---

const fetchCmd = defineCommand("fetch", {
	help: "Fetch a resource",
	flags: {
		url: flag("url", t.str, { help: "URL", default: null }),
		retries: flag("retries", t.int, { help: "Retries", default: 3n }),
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

const cp = defineCommand("cp", {
	help: "Copy a file",
	args: [
		arg("src", t.str, { help: "Source" }),
		arg("dest", t.str, { help: "Destination", required: false }),
		arg("mode", t.str, { help: "Mode", required: false, default: "fast" }),
	],
	handler: (args) => (args.dest === undefined ? args.mode.length : 0),
});

export type _ArgOptionality = Assert<
	Equals<InferHandler<typeof cp>, { src: string; dest?: string; mode: string }>
>;
