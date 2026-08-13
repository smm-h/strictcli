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
	errPayloadNoSchema,
} from "./errors.js";

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
	private payloadValue: unknown = undefined;
	private payloadSet = false;
	/**
	 * The diagnostics this dispatch emitted, in emission order (contract
	 * §19.2). In machine mode the writers below record here instead of
	 * writing: what they were asked to say rides the envelope. Outside machine
	 * mode the array stays empty and nothing changes.
	 */
	private readonly diagnosticRecords: DiagnosticRecord[] = [];

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
	 * Throws when the command declared no payload schema (there is nothing to
	 * validate the value against) and when a payload was already supplied in
	 * this dispatch (one slot, one answer).
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
 * Package-internal accessor (NOT re-exported from index.ts): the diagnostics a
 * dispatch emitted, in emission order, read by the one exit step in app.ts when
 * it builds the envelope's `diagnostics` member (§19.2).
 */
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
