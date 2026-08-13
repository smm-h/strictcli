/**
 * The process trace store.
 *
 * The normative specification is docs/process-trace-store.md; the effects
 * contract's §20 carries the two contract items (observational-only, and the
 * best-effort failure carve-out). Nothing here is ever read back into a
 * decision: the framework mints an identifier, appends one line, and composes
 * the identifier into the CHILD's environment. There is no accessor, and this
 * module is not re-exported from the package surface.
 *
 * Parity source: python/strictcli/__init__.py (the reference implementation).
 */

import { randomBytes } from "node:crypto";
import {
	closeSync,
	constants as fsConstants,
	mkdirSync,
	openSync,
	readdirSync,
	statSync,
	writeSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * The one variable ancestry travels through. It carries exactly one thing: the
 * parent entry's identifier.
 */
export const TRACE_PARENT_ENV = "STRICTCLI_TRACE_PARENT";

/** Crockford base32, the exact alphabet: no I, L, O or U. */
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const ULID_LEN = 26;
const TRACE_ROLL_BYTES = 8 * 1024 * 1024;
const TRACE_MARKER_NAME = "write-failure.marker";
const TRACE_FILE_MODE = 0o600;
const TRACE_DIR_MODE = 0o700;
const MS_PER_HOUR = 3600000;

export const TRACE_PARTITION_RE = /^\d{4}-\d{2}-\d{2}T\d{2}\.jsonl$/;

/**
 * Encodes 48 timestamp bits plus 80 random bits as 26 Crockford characters.
 * 26 characters carry 130 bits, so the 128-bit value is left-padded with two
 * zero bits -- which is exactly why a canonical identifier's first character
 * never exceeds `7`.
 */
export function ulidEncode(ms: number, randomness: Uint8Array): string {
	let rand = 0n;
	for (const byte of randomness) {
		rand = (rand << 8n) | BigInt(byte);
	}
	const value = (BigInt(ms) << 80n) | rand;
	let out = "";
	for (let shift = 125n; shift >= 0n; shift -= 5n) {
		out += CROCKFORD[Number((value >> shift) & 0x1fn)];
	}
	return out;
}

/** Mints an identifier from this writer's clock plus 80 CSPRNG bits. */
export function ulidMint(ms: number): string {
	return ulidEncode(ms, randomBytes(10));
}

/**
 * Parses under the strict profile and returns the millisecond, or null.
 *
 * Rejected, never repaired: any length but 26, any character outside the
 * canonical uppercase alphabet (lowercase included -- one identifier must have
 * exactly one spelling), and a 130-bit value that overflows 128 bits.
 */
export function ulidTimestamp(text: unknown): number | null {
	if (typeof text !== "string" || text.length !== ULID_LEN) {
		return null;
	}
	let value = 0n;
	for (const ch of text) {
		const index = CROCKFORD.indexOf(ch);
		if (index < 0) {
			return null;
		}
		value = (value << 5n) | BigInt(index);
	}
	if (value >> 128n) {
		return null;
	}
	return Number(value >> 80n);
}

export function ulidValid(text: unknown): boolean {
	return ulidTimestamp(text) !== null;
}

/**
 * The literal store path. `~` is expanded and nothing else is consulted --
 * deliberately NOT XDG_DATA_HOME, because two conforming writers that
 * disagreed about the location would produce two stores on one machine and a
 * chain crossing them would dangle at both ends.
 */
export function traceStoreDir(): string {
	return join(homedir(), ".local", "share", "strictcli", "trace");
}

/** The UTC-hour label for an instant: the partition's range start. */
export function traceLabel(ms: number): string {
	return new Date(Math.floor(ms / MS_PER_HOUR) * MS_PER_HOUR)
		.toISOString()
		.slice(0, 13);
}

/** The inverse: a label's range start in epoch milliseconds. */
export function traceLabelStartMs(label: string): number {
	const ms = Date.parse(`${label}:00:00.000Z`);
	if (Number.isNaN(ms)) {
		throw new Error(`not a partition label: ${label}`);
	}
	return ms;
}

/** RFC 3339 in UTC with exactly three fractional digits and a Z suffix. */
export function traceTimestamp(ms: number): string {
	return new Date(ms).toISOString();
}

/**
 * Selects the partition to append to, rolling when both conditions hold. The
 * greatest-named file is the active partition; a new one is created with
 * O_EXCL when the active file is at least 8 MB AND the current UTC hour is
 * later than its label. Losing the creation race is not an error -- the loser
 * appends to the winner's file.
 */
function traceActiveLabel(store: string, nowMs: number): string {
	const nowLabel = traceLabel(nowMs);
	let active = "";
	for (const name of readdirSync(store)) {
		if (TRACE_PARTITION_RE.test(name) && name > active) {
			active = name;
		}
	}
	if (active === "") {
		traceCreatePartition(store, nowLabel);
		return nowLabel;
	}
	const label = active.slice(0, -".jsonl".length);
	if (nowLabel > label) {
		let size = 0;
		try {
			size = statSync(join(store, active)).size;
		} catch {
			size = 0;
		}
		if (size >= TRACE_ROLL_BYTES) {
			traceCreatePartition(store, nowLabel);
			return nowLabel;
		}
	}
	return label;
}

function traceCreatePartition(store: string, label: string): void {
	try {
		closeSync(
			openSync(
				join(store, `${label}.jsonl`),
				fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL,
				TRACE_FILE_MODE,
			),
		);
	} catch {
		// another writer won the race; append to its file
	}
}

/** What an entry says about the invocation doing the spawning. */
export interface TraceIdentity {
	readonly app: string;
	readonly version: string;
	readonly command: string | null;
	readonly dryRun: boolean;
	readonly machineMode: boolean;
	readonly quiet: boolean;
	readonly verbose: boolean;
	readonly approveConsequential: boolean;
	readonly effect: string;
}

/**
 * Appends one entry for a real child-process start and returns its identifier.
 *
 * Returns null when anything at all went wrong: tracing is best-effort by
 * declared design (contract §20.3), so a failure never fails the run, never
 * prints, and is never retried. The first failure leaves a write-once marker.
 */
export function traceWriteEntry(identity: TraceIdentity): string | null {
	try {
		const store = traceStoreDir();
		mkdirSync(store, { recursive: true, mode: TRACE_DIR_MODE });
		const nowMs = Date.now();
		const label = traceActiveLabel(store, nowMs);
		// The clamp invariant: an entry always lies inside its file's range,
		// which is what makes lookup a binary search over filenames.
		const ms = Math.max(nowMs, traceLabelStartMs(label));
		const id = ulidMint(ms);
		const inherited = process.env[TRACE_PARENT_ENV];
		const entry = {
			id,
			parent_id: ulidValid(inherited) ? (inherited as string) : null,
			app: identity.app,
			version: identity.version,
			command: identity.command,
			dry_run: identity.dryRun,
			machine_mode: identity.machineMode,
			quiet: identity.quiet,
			verbose: identity.verbose,
			approve_consequential: identity.approveConsequential,
			effect: identity.effect,
			pid: process.pid,
			spawned_at: traceTimestamp(ms),
		};
		const fd = openSync(
			join(store, `${label}.jsonl`),
			fsConstants.O_WRONLY | fsConstants.O_APPEND | fsConstants.O_CREAT,
			TRACE_FILE_MODE,
		);
		try {
			writeSync(fd, `${JSON.stringify(entry)}\n`);
		} finally {
			closeSync(fd);
		}
		return id;
	} catch {
		traceMarkFailure();
		return null;
	}
}

/**
 * Creates the write-once failure marker. No counter, no retry, no noise: a
 * disk-full condition blinds the marker too, and that is accepted.
 */
function traceMarkFailure(): void {
	try {
		const fd = openSync(
			join(traceStoreDir(), TRACE_MARKER_NAME),
			fsConstants.O_WRONLY | fsConstants.O_CREAT | fsConstants.O_EXCL,
			TRACE_FILE_MODE,
		);
		try {
			writeSync(fd, `${traceTimestamp(Date.now())}\n`);
		} finally {
			closeSync(fd);
		}
	} catch {
		// swallowed, deliberately
	}
}

/**
 * Composes the child's environment at a real child-process start.
 *
 * The handler's `env` merge happens first; the framework's ancestry
 * composition is applied AFTER it and wins (contract §2.5), so a handler can
 * neither sever the chain by clearing the variable nor forge a different
 * ancestor by setting it. When the entry could not be written the variable is
 * REMOVED rather than left inherited: a lost record must not silently
 * re-attribute the child to its grandparent.
 */
export function traceChildEnv(
	base: Record<string, string> | undefined,
	identity: TraceIdentity,
): Record<string, string> {
	const merged: Record<string, string> = {};
	if (base === undefined) {
		for (const [k, v] of Object.entries(process.env)) {
			if (v !== undefined) {
				merged[k] = v;
			}
		}
	} else {
		Object.assign(merged, base);
	}
	const id = traceWriteEntry(identity);
	if (id === null) {
		delete merged[TRACE_PARENT_ENV];
	} else {
		merged[TRACE_PARENT_ENV] = id;
	}
	return merged;
}
