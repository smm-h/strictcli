/**
 * NEGATIVE fixture: a `.write()` inside a read_only command must not compile.
 *
 * defineReadOnlyCommand narrows the handler's ctx to ReadOnlyContext, whose
 * effects member exposes only `run`. Compiled by tests/negative_types.test.ts,
 * which pins the error; it is deliberately excluded from the main test build.
 */

import { defineReadOnlyCommand } from "../../src/index.js";

export const bad = defineReadOnlyCommand("look", {
	help: "h",
	handler: (_args, ctx) => {
		ctx.effects.write("VERSION", "1.2.3");
		return 0;
	},
});
