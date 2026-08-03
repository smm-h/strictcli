/** NEGATIVE fixture: the passthrough twins narrow ctx the same way. */

import { readOnlyPassthrough } from "../../src/index.js";

export const bad = readOnlyPassthrough("show", {
	help: "h",
	handler: (_args, ctx) => {
		ctx.effects.mkdir("d");
		return 0;
	},
});
