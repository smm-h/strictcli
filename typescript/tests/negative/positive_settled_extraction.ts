/**
 * POSITIVE fixture (must compile cleanly): the declared return types are the
 * SETTLED shapes only, so extracting from a result typechecks. The mismatch
 * surfaces at RUNTIME in dry mode, via the Proxy seal -- which is the whole
 * one-body-both-modes model. There is no `| Unsettled` union to narrow and no
 * isUnsettled() predicate, by construction.
 */

import { defineMutatingCommand } from "../../src/index.js";

export const good = defineMutatingCommand("go", {
	help: "h",
	handler: (_args, ctx) => {
		const built = ctx.effects.run(["make"]);
		// Settled-typed: exitCode/stdout/stderr are all statically present.
		const code: number = built.exitCode;
		const text: string = built.stdout;
		// Forwarding is legal and typechecks at every accepting position.
		ctx.effects.write("out", built);
		ctx.effects.run(["upload", built]);
		const res = ctx.effects.http("POST", "https://x.test");
		ctx.effects.run(["view", res]);
		ctx.effects.rename(built, res);
		const child = ctx.effects.spawn(["notify"]);
		const pid: number = child.pid;
		const done = child.wait({ check: false });
		return code + text.length + pid + done.exitCode;
	},
});
