/**
 * Structured output context for command handlers, mirroring Go's Context
 * (context.go) with Python's Context as the divergence ground truth. Always
 * injected as the second argument to every handler ((args, ctx) signature).
 * app.ts builds the InfraAccess view (infra.ts buildInfraAccess) per
 * dispatch; it is null when the app declares no roots or handshakes, so
 * every infraValue() call throws the not-declared error.
 */

import type { MutatingEffects, ReadOnlyEffects } from "./effects.js";
import {
	errConnectionValueUndeclared,
	errEffectsUnavailable,
	errInfraValueUndeclared,
	errNoSourceInfo,
	errPayloadAlreadySet,
	errPayloadInvalid,
	errPayloadNoSchema,
} from "./errors.js";
import { validatePayloadValue } from "./payload_schema.js";
import { PROVIDED_SOURCES } from "./sources.js";
import type { UpdateState } from "./update.js";

/** Minimal sink for output streams (process.stdout/stderr or test captures). */
export interface Writer {
	write(text: string): void;
}

/**
 * A Context's view of infrastructure env vars: root values resolved eagerly
 * at app construction, the set of declared handshake vars (read live), and the
 * set of declared connection vars (read live, but suppressed under --hermetic).
 */
export interface InfraAccess {
	readonly roots: ReadonlyMap<string, string>;
	readonly handshakes: ReadonlySet<string>;
	readonly connections: ReadonlySet<string>;
	readonly hermetic: boolean;
}

/**
 * OPTIONAL capability a check context may expose: the value of a declared
 * connection env, read live -- EXCEPT under --hermetic, where it resolves as
 * absent [undefined, false] so a check can skip visibly instead of connecting.
 * The check command wraps the tool-supplied check context in a value that
 * satisfies this interface, backed by the app's declared connection envs and
 * the invocation's hermetic state.
 *
 * `isHermetic()` reports whether the invocation ran under --hermetic. It exists
 * so a check can DISTINGUISH the two cases that `connectionEnvValue`'s
 * `present === false` otherwise conflates: "--hermetic suppressed the connection
 * env" vs "the env var is simply unset". A check that layers config fallbacks
 * below the env must honor hermetic even when the env is unset -- otherwise it
 * falls through to a config URL and connects, violating the hermetic guarantee:
 *
 *     const [dsn, present] = r.connectionEnvValue("DATABASE_URL");
 *     if (!present) {
 *       if (r.isHermetic()) return rep.skipped("hermetic: connection suppressed");
 *       // env unset but not hermetic -- config fallback is allowed here
 *     }
 */
export interface ConnectionEnvReader {
	connectionEnvValue(
		envVar: string,
	): [value: string | undefined, present: boolean];
	isHermetic(): boolean;
}

/**
 * The effects-regime reserved flag quartet, extracted by the position-aware
 * pre-scan and delivered on the Context (never as handler kwargs).
 */
export interface ReservedFlags {
	readonly dryRun: boolean;
	readonly approveConsequential: boolean;
	readonly quiet: boolean;
	readonly verbose: boolean;
	/**
	 * Machine mode (contract §19.1). Reserved BESIDE the quartet on the same
	 * unconditional tier, not as a fifth member of it.
	 */
	readonly json: boolean;
}

/** The four levels a context writer carries (contract §19.2). */
export type DiagnosticLevel = "debug" | "info" | "warn" | "error";

/**
 * One entry of the envelope's diagnostics array (§19.2). The property order is
 * the serialized key order.
 */
export interface DiagnosticRecord {
	readonly level: DiagnosticLevel;
	readonly message: string;
}

/** The quartet's all-false value: the programmatic dispatch paths' state. */
export const NO_RESERVED_FLAGS: ReservedFlags = {
	dryRun: false,
	approveConsequential: false,
	quiet: false,
	verbose: false,
	json: false,
};

/**
 * Everything a handler's context carries except the effects handle. The two
 * classification-narrowed context types differ in that one member and in
 * nothing else.
 */
interface ContextBase {
	/** True when the framework-owned --dry-run flag was passed. */
	readonly dryRun: boolean;
	/** True when the framework-owned --approve-consequential flag was passed. */
	readonly approveConsequential: boolean;
	/** True when the framework-owned --quiet flag was passed. */
	readonly quiet: boolean;
	/** True when the framework-owned --verbose flag was passed. */
	readonly verbose: boolean;
	/** True when the framework-owned --json flag was passed (machine mode). */
	readonly json: boolean;
	/** Supplies this dispatch's machine payload (contract §19.4). */
	payload(value: unknown): void;
	info(msg: string): void;
	warn(msg: string): void;
	debug(msg: string): void;
	error(msg: string): void;
	source(name: string): string;
	provided(name: string): boolean;
	unset(name: string): boolean;
	infraValue(envVar: string): [value: string | undefined, isSet: boolean];
	connectionEnvValue(
		envVar: string,
	): [value: string | undefined, present: boolean];
}

/**
 * The context a `read_only` command's handler receives: its effects handle
 * exposes only `run`, so a `.write()` inside a read-only command is a COMPILE
 * error. The runtime seal fires regardless, because plain-JS consumers bypass
 * the type system entirely.
 */
export interface ReadOnlyContext extends ContextBase {
	readonly effects: ReadOnlyEffects;
}

/** The context a `mutating` command's handler receives: the full handle. */
export interface MutatingContext extends ContextBase {
	readonly effects: MutatingEffects;
}

export class Context implements MutatingContext {
	private readonly stdout: Writer;
	private readonly stderr: Writer;
	private readonly sources: Readonly<Record<string, string>>;
	private readonly infra: InfraAccess | null;
	private readonly reserved: ReservedFlags;
	private readonly effectsHandle: MutatingEffects | null;
	// The payload slot (contract §19.4): at most one value per dispatch,
	// settable only on a command that declared a payload schema.
	private readonly commandName: string;
	private readonly payloadSchema: Readonly<Record<string, unknown>> | null;
	// Read back through the widened cast in readPayload/emitPayload below,
	// which the linter cannot follow -- the slot is private on purpose, so the
	// framework's own two readers are the only way to it.
	// biome-ignore lint/correctness/noUnusedPrivateClassMembers: read via the widened cast in readPayload
	private payloadValue: unknown = undefined;
	private payloadSet = false;
	/**
	 * The diagnostics this dispatch emitted, in emission order (contract
	 * §19.2). In machine mode the writers below record here instead of
	 * writing: what they were asked to say rides the envelope. Outside machine
	 * mode the array stays empty and nothing changes.
	 */
	private readonly diagnosticRecords: DiagnosticRecord[] = [];
	/**
	 * The update-command construct's two per-dispatch facts (contract §27).
	 * `writes` is the write set the would-do log's unnumbered line and the
	 * envelope's `writes` member both render; `unsets` names the properties
	 * this invocation CLEARED, which is what `unset` answers off -- the minted
	 * `--unset-<prop>` delivers no key of its own. Both are attached by the
	 * dispatch sites through attachUpdateState below.
	 */
	// biome-ignore lint/correctness/noUnusedPrivateClassMembers: read via the widened cast in contextWrites
	private writes: UpdateState | null = null;
	private unsets: ReadonlySet<string> = new Set();

	constructor(
		stdout: Writer,
		stderr: Writer,
		sources: Readonly<Record<string, string>>,
		infra: InfraAccess | null,
		reserved: ReservedFlags = NO_RESERVED_FLAGS,
		effects: MutatingEffects | null = null,
		commandName = "",
		payloadSchema: Readonly<Record<string, unknown>> | null = null,
	) {
		this.stdout = stdout;
		this.stderr = stderr;
		this.sources = sources;
		this.infra = infra;
		this.reserved = reserved;
		this.effectsHandle = effects;
		this.commandName = commandName;
		this.payloadSchema = payloadSchema;
	}

	/** True when the framework-owned --dry-run flag was passed. */
	get dryRun(): boolean {
		return this.reserved.dryRun;
	}

	/** True when the framework-owned --approve-consequential flag was passed. */
	get approveConsequential(): boolean {
		return this.reserved.approveConsequential;
	}

	/** True when the framework-owned --quiet flag was passed. */
	get quiet(): boolean {
		return this.reserved.quiet;
	}

	/** True when the framework-owned --verbose flag was passed. */
	get verbose(): boolean {
		return this.reserved.verbose;
	}

	/**
	 * True when the framework-owned --json flag was passed, which is what
	 * selects machine mode (contract §19.1).
	 *
	 * Handlers do not branch on it to decide whether to build a payload --
	 * `payload()` is mode-independent and the framework decides what to do with
	 * the value -- but it is exposed for symmetry with the quartet and for apps
	 * that propagate it to a child process.
	 */
	get json(): boolean {
		return this.reserved.json;
	}

	/**
	 * Supplies this dispatch's machine payload (contract §19.4).
	 *
	 * The call is mode-independent: a handler calls it identically in both
	 * modes and never branches on `json`. In machine mode the value is
	 * emitted; outside machine mode it is not printed at all. `test()` and
	 * `call()` capture it either way.
	 *
	 * Throws at call time on §19.4's own two rules: when the command declared no
	 * payload schema (there is nothing to validate the value against) and when a
	 * payload was already supplied in this dispatch (one slot, one answer).
	 *
	 * The value itself is validated against the declared schema at the EMISSION
	 * seam (§19.4, §19.5) -- only where machine mode actually writes the
	 * envelope. Validating here instead would make a payload that is legal in
	 * human mode fail a run that was never going to emit it, which §19.4's
	 * call-unconditionally rule forbids.
	 */
	payload(value: unknown): void {
		if (this.payloadSchema === null) {
			throw new Error(errPayloadNoSchema(this.commandName));
		}
		if (this.payloadSet) {
			throw new Error(errPayloadAlreadySet(this.commandName));
		}
		this.payloadValue = value;
		this.payloadSet = true;
	}

	/**
	 * The effects handle for this run: the eight recorded operations. Under
	 * --dry-run they are recorded instead of executed. Throws when the Context
	 * was constructed outside a command dispatch.
	 */
	get effects(): MutatingEffects {
		if (this.effectsHandle === null) {
			throw new Error(errEffectsUnavailable());
		}
		return this.effectsHandle;
	}

	/**
	 * Records a diagnostic in machine mode, reporting whether it was recorded.
	 * In machine mode the writers below write nothing and what they were asked
	 * to say rides the envelope's diagnostics instead (§19.1). The recording is
	 * NOT filtered by --quiet or --verbose: the envelope's content is a
	 * function of what the run produced, never of how a terminal was
	 * configured (§19.2).
	 */
	#diagnostic(level: DiagnosticLevel, msg: string): boolean {
		if (!this.reserved.json) {
			return false;
		}
		this.diagnosticRecords.push({ level, message: msg });
		return true;
	}

	/** Writes an informational message to stdout (hidden under --quiet). */
	info(msg: string): void {
		if (this.#diagnostic("info", msg)) {
			return;
		}
		if (this.reserved.quiet) {
			return;
		}
		this.stdout.write(`${msg}\n`);
	}

	/** Writes a warning message to stderr (never suppressed). */
	warn(msg: string): void {
		if (this.#diagnostic("warn", msg)) {
			return;
		}
		this.stderr.write(`${msg}\n`);
	}

	/**
	 * Writes a debug message to stdout, shown only under --verbose.
	 * --quiet DOMINATES --verbose: passing both hides debug output.
	 */
	debug(msg: string): void {
		if (this.#diagnostic("debug", msg)) {
			return;
		}
		if (this.reserved.quiet || !this.reserved.verbose) {
			return;
		}
		this.stdout.write(`${msg}\n`);
	}

	/** Writes an error message to stderr (never suppressed). */
	error(msg: string): void {
		if (this.#diagnostic("error", msg)) {
			return;
		}
		this.stderr.write(`${msg}\n`);
	}

	/**
	 * Returns the provenance source label for a flag: one of "cli", "env",
	 * "config", "default", "implied", "infra". Accepts dashed or underscored
	 * names (underscore form is tried first, like the siblings). Throws if the
	 * flag name is unknown.
	 */
	source(name: string): string {
		const key = name.replaceAll("-", "_");
		const byKey = this.sources[key];
		if (byKey !== undefined) {
			return byKey;
		}
		const byName = this.sources[name];
		if (byName !== undefined) {
			return byName;
		}
		throw new Error(errNoSourceInfo(name));
	}

	/**
	 * Was this flag's value caused by the INVOCATION rather than by the
	 * declaration (contract §23.6)? True for the sources the invocation
	 * supplies -- "cli", "env", "config" and "implied" -- and false for
	 * "default" and "infra", which are the declaration deciding.
	 *
	 * An optional flag that received nothing carries source "default" and is
	 * therefore not provided: an optional declaration deciding on absence IS
	 * the declaration deciding. Unknown names behave exactly as source()'s do,
	 * through the same lookup and the same message.
	 */
	provided(name: string): boolean {
		return PROVIDED_SOURCES.has(this.source(name));
	}

	/**
	 * Did this invocation CLEAR the named property of an update command
	 * (contract §27.6)? True for `--unset-<prop>` on the command line, and for
	 * `null` on the property's own key at a machine door.
	 *
	 * An unset property delivers absence -- the same `undefined` an untouched
	 * property delivers -- and reports `provided` true, the invocation having
	 * caused the write. This is what saves a handler from reconstructing that
	 * boolean out of two facts, which is §23.6's own reason for existing.
	 *
	 * It accepts dashed or underscored names and throws on an unknown name with
	 * the same message `source` and `provided` use: it reads the same per-parse
	 * store, so a name with no source has no clear either.
	 */
	unset(name: string): boolean {
		// The lookup is source()'s, for its refusal; the answer is the clear's.
		this.source(name);
		return this.unsets.has(name.replaceAll("_", "-"));
	}

	/**
	 * Returns the value of a declared infrastructure env var as
	 * [value, isSet]. For a declared root the value is the construction-time
	 * resolution and isSet is always true; for a declared handshake var the
	 * environment is read LIVE and isSet means "is set". Throws when envVar is
	 * neither -- declare everything.
	 */
	infraValue(envVar: string): [value: string | undefined, isSet: boolean] {
		if (this.infra !== null) {
			const root = this.infra.roots.get(envVar);
			if (root !== undefined) {
				return [root, true];
			}
			if (this.infra.handshakes.has(envVar)) {
				const live = process.env[envVar];
				return live !== undefined ? [live, true] : [undefined, false];
			}
			if (this.infra.connections.has(envVar)) {
				if (this.infra.hermetic) {
					return [undefined, false];
				}
				const live = process.env[envVar];
				return live !== undefined ? [live, true] : [undefined, false];
			}
		}
		throw new Error(errInfraValueUndeclared(envVar));
	}

	/**
	 * Returns the value of a declared connection env as [value, present], read
	 * LIVE -- EXCEPT under --hermetic, where it resolves as absent
	 * [undefined, false]. Throws when envVar is not a declared connection env.
	 * This is the handler-side accessor for the connection-URL kind; see also
	 * infraValue, which resolves all three kinds.
	 */
	connectionEnvValue(
		envVar: string,
	): [value: string | undefined, present: boolean] {
		if (this.infra?.connections.has(envVar) === true) {
			if (this.infra.hermetic) {
				return [undefined, false];
			}
			const live = process.env[envVar];
			return live !== undefined ? [live, true] : [undefined, false];
		}
		throw new Error(errConnectionValueUndeclared(envVar));
	}
}

/**
 * Package-internal accessor (NOT re-exported from index.ts): the machine
 * payload a dispatch's handler supplied, read by the one exit step in app.ts
 * and by the programmatic invocation path.
 */
export function contextPayload(ctx: Context): {
	readonly set: boolean;
	readonly value: unknown;
} {
	const c = ctx as unknown as { payloadSet: boolean; payloadValue: unknown };
	return { set: c.payloadSet, value: c.payloadValue };
}

/**
 * Package-internal (NOT re-exported from index.ts): validates the payload the
 * envelope is about to carry (contract §19.5). The schema check, JSON
 * representability and the 2^53 magnitude guard all live at this one seam,
 * where the value becomes a document -- a human-mode run never reaches it, so a
 * payload the envelope could not represent costs it nothing. A deviation fails
 * the run rather than shipping a wrong shape.
 */
export function validateEmittedPayload(ctx: Context): void {
	const c = ctx as unknown as {
		payloadSet: boolean;
		payloadValue: unknown;
		payloadSchema: Readonly<Record<string, unknown>> | null;
		commandName: string;
	};
	if (!c.payloadSet || c.payloadSchema === null) {
		return;
	}
	const found = validatePayloadValue(
		c.payloadValue,
		c.payloadSchema as Record<string, unknown>,
	);
	if (found !== null) {
		throw new Error(errPayloadInvalid(c.commandName, found.path, found.detail));
	}
}

/**
 * Package-internal accessor (NOT re-exported from index.ts): the diagnostics a
 * dispatch emitted, in emission order, read by the one exit step in app.ts when
 * it builds the envelope's `diagnostics` member (§19.2).
 */
/**
 * Package-internal (NOT re-exported from index.ts): attaches one dispatch's
 * update facts to the Context (contract §27.5, §27.6). The dispatch sites call
 * it once, exactly where they attach every other per-dispatch fact; the cast
 * reaches the private slots without widening the handler-side surface.
 */
export function attachUpdateState(
	ctx: Context,
	writes: UpdateState | null,
	unsets: ReadonlySet<string>,
): void {
	const c = ctx as unknown as {
		writes: UpdateState | null;
		unsets: ReadonlySet<string>;
	};
	c.writes = writes;
	c.unsets = unsets;
}

/**
 * Package-internal (NOT re-exported from index.ts): the write set this
 * dispatch computed, which the envelope carries in both modes (§19.2's
 * amendment, §27.5). Null on every command that declares no update.
 */
export function contextWrites(ctx: Context): UpdateState | null {
	return (ctx as unknown as { writes: UpdateState | null }).writes;
}

export function contextDiagnostics(ctx: Context): readonly DiagnosticRecord[] {
	return (ctx as unknown as { diagnosticRecords: DiagnosticRecord[] })
		.diagnosticRecords;
}

/**
 * Package-internal accessor (NOT re-exported from index.ts, so not part of the
 * public API): reports whether a framework Context ran under --hermetic. Used by
 * the check-side ConnectionEnvReader wrapper so a check can distinguish
 * "--hermetic suppressed the connection env" from "env var simply unset".
 * Mirrors Go's wrapper reading frameworkCtx.infra directly and Python's
 * _last_hermetic; the cast reaches the private infra snapshot without widening
 * the handler-side Context surface.
 */
export function contextIsHermetic(ctx: Context): boolean {
	return (
		(ctx as unknown as { infra: InfraAccess | null }).infra?.hermetic ?? false
	);
}
