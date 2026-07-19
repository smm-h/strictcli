/**
 * @-prefix resolution for string flag values, mirroring Go resolveAtPrefix
 * (parse.go) and Python _resolve_at_prefix: "@path" reads a file, "@-" reads
 * stdin (once per invocation), "@@literal" strips the leading "@". Content is
 * trimmed of trailing space/tab/CR/LF only (never other whitespace), and
 * capped at 1 MB.
 */

import { readFileSync, readSync, type Stats, statSync } from "node:fs";
import {
	errAtPrefixCannotReadFile,
	errAtPrefixCannotReadStdin,
	errAtPrefixFileNotFound,
	errAtPrefixFileTooLarge,
	errAtPrefixStdinOnce,
	ParseError,
} from "./errors.js";

export const AT_PREFIX_MAX_SIZE = 1024 * 1024; // 1 MB

/** Tracks which flag consumed stdin ("@-" is single-use per invocation). */
export interface StdinTracker {
	consumedBy: string | null;
}

export function newStdinTracker(): StdinTracker {
	return { consumedBy: null };
}

/**
 * Reads all of stdin, returning at most AT_PREFIX_MAX_SIZE + 1 bytes (the +1
 * lets the caller detect over-limit input, like Go's LimitReader). Injectable
 * for tests.
 */
export type StdinReader = () => Buffer;

function readStdinDefault(): Buffer {
	const chunks: Buffer[] = [];
	let total = 0;
	const buf = Buffer.alloc(65536);
	while (total <= AT_PREFIX_MAX_SIZE) {
		const n = readSync(0, buf, 0, buf.length, null);
		if (n === 0) {
			break;
		}
		chunks.push(Buffer.from(buf.subarray(0, n)));
		total += n;
	}
	return Buffer.concat(chunks);
}

/** Trims trailing characters from the cutset space/tab/LF/CR only. */
function trimContentEnd(s: string): string {
	let end = s.length;
	while (end > 0 && " \t\n\r".includes(s.charAt(end - 1))) {
		end--;
	}
	return s.slice(0, end);
}

/**
 * Resolves the @-prefix for a raw string flag value. Returns the value
 * unchanged when it does not start with "@". Throws ParseError with the
 * sibling-exact messages on failure.
 */
export function resolveAtPrefix(
	flagName: string,
	raw: string,
	tracker: StdinTracker,
	readStdin: StdinReader = readStdinDefault,
): string {
	if (!raw.startsWith("@")) {
		return raw;
	}
	if (raw.startsWith("@@")) {
		return raw.slice(1); // strip leading @
	}
	if (raw === "@-") {
		if (tracker.consumedBy !== null) {
			throw new ParseError(errAtPrefixStdinOnce(flagName));
		}
		let data: Buffer;
		try {
			data = readStdin();
		} catch {
			throw new ParseError(errAtPrefixCannotReadStdin(flagName));
		}
		if (data.byteLength > AT_PREFIX_MAX_SIZE) {
			throw new ParseError(errAtPrefixFileTooLarge(flagName));
		}
		tracker.consumedBy = flagName;
		return trimContentEnd(data.toString("utf8"));
	}
	// @path
	const path = raw.slice(1);
	let info: Stats;
	try {
		info = statSync(path);
	} catch (e) {
		if ((e as NodeJS.ErrnoException).code === "ENOENT") {
			throw new ParseError(errAtPrefixFileNotFound(flagName, path));
		}
		throw new ParseError(errAtPrefixCannotReadFile(flagName, path));
	}
	if (info.isDirectory()) {
		throw new ParseError(errAtPrefixCannotReadFile(flagName, path));
	}
	if (info.size > AT_PREFIX_MAX_SIZE) {
		throw new ParseError(errAtPrefixFileTooLarge(flagName));
	}
	let data: Buffer;
	try {
		data = readFileSync(path);
	} catch {
		throw new ParseError(errAtPrefixCannotReadFile(flagName, path));
	}
	return trimContentEnd(data.toString("utf8"));
}
