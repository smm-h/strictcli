/** NEGATIVE fixture: `.spawn()` inside a read_only command must not compile. */

import { defineReadOnlyCommand } from "../../src/index.js";

export const bad = defineReadOnlyCommand("look", {
	help: "h",
	handler: (_args, ctx) => {
		ctx.effects.spawn(["notify"]);
		return 0;
	},
});
