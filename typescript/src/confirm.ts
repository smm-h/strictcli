/**
 * The framework-owned confirm protocol for `mutating` commands.
 *
 * Fires before dispatching a mutating command on the REAL CLI path when
 * neither --dry-run nor --yes was passed. It never fires for read_only
 * commands, and never on the programmatic paths (test/call/invoke/MCP), which
 * have no TTY contract and would hang the caller.
 *
 * A mutating PASSTHROUGH is not exempt: that its args are opaque to the
 * framework is a reason to confirm, not a reason to skip -- the framework knows
 * LESS about what is about to happen, not more.
 *
 * There is no bypass. `--yes` answers the prompt; it disables nothing else.
 */

import { readSync } from "node:fs";
import type { Writer } from "./context.js";
import {
	errConfirmDeclined,
	errConfirmNonInteractive,
	promptConfirmMutating,
} from "./errors.js";

/** The stdin side of the protocol, isolated so tests can drive it. */
export interface ConfirmIO {
	/** True when stdin is a TTY (Python sys.stdin.isatty()). */
	isInteractive(): boolean;
	/** Reads one line from stdin, without its trailing newline. */
	readLine(): string;
}

/** Reads one line from fd 0 synchronously, tolerating a non-blocking TTY. */
function readLineFromStdin(): string {
	const buf = Buffer.alloc(1);
	let line = "";
	for (;;) {
		let n: number;
		try {
			n = readSync(0, buf, 0, 1, null);
		} catch (e) {
			if ((e as NodeJS.ErrnoException).code === "EAGAIN") {
				continue;
			}
			// EOF or a closed descriptor: treat as an empty answer (declines).
			break;
		}
		if (n === 0) {
			break;
		}
		const ch = buf.toString("utf8", 0, 1);
		if (ch === "\n") {
			break;
		}
		line += ch;
	}
	return line;
}

const DEFAULT_CONFIRM_IO: ConfirmIO = {
	isInteractive: () => process.stdin.isTTY === true,
	readLine: readLineFromStdin,
};

let confirmIO: ConfirmIO = DEFAULT_CONFIRM_IO;

/**
 * Package-internal seam (never re-exported from index.ts): swaps the stdin
 * side of the protocol so the prompt, the non-TTY error and the decline path
 * are all testable. Passing null restores the real stdin reader. This is the
 * TS analog of Python's tests monkeypatching sys.stdin -- it changes WHERE the
 * answer comes from, never WHETHER the protocol runs.
 */
export function setConfirmIO(io: ConfirmIO | null): void {
	confirmIO = io ?? DEFAULT_CONFIRM_IO;
}

/**
 * Runs the confirm protocol. Returns true to proceed, false to abort (the
 * caller exits 1 after this function has written the reason to stderr).
 */
export function confirmMutating(cmdPath: string, err: Writer): boolean {
	if (!confirmIO.isInteractive()) {
		err.write(`${errConfirmNonInteractive()}\n`);
		return false;
	}
	// The prompt carries its own trailing space and NO trailing newline.
	err.write(promptConfirmMutating(cmdPath));
	const answer = confirmIO.readLine();
	if (answer !== "y" && answer !== "Y") {
		err.write(`${errConfirmDeclined()}\n`);
		return false;
	}
	return true;
}
