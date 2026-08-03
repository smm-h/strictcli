/**
 * Structured output context for command handlers, mirroring Go's Context
 * (context.go) with Python's Context as the divergence ground truth. Always
 * injected as the second argument to every handler ((args, ctx) signature).
 * app.ts builds the InfraAccess view (infra.ts buildInfraAccess) per
 * dispatch; it is null when the app declares no roots or handshakes, so
 * every infraValue() call throws the not-declared error.
 */

import type { MutatingEffects } from "./effects.js";
import {
	errConnectionValueUndeclared,
	errEffectsUnavailable,
	errInfraValueUndeclared,
	errNoSourceInfo,
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
	readonly yes: boolean;
	readonly quiet: boolean;
	readonly verbose: boolean;
}

/** The quartet's all-false value: the programmatic dispatch paths' state. */
export const NO_RESERVED_FLAGS: ReservedFlags = {
	dryRun: false,
	yes: false,
	quiet: false,
	verbose: false,
};

export class Context {
	private readonly stdout: Writer;
	private readonly stderr: Writer;
	private readonly sources: Readonly<Record<string, string>>;
	private readonly infra: InfraAccess | null;
	private readonly reserved: ReservedFlags;
	private readonly effectsHandle: MutatingEffects | null;

	constructor(
		stdout: Writer,
		stderr: Writer,
		sources: Readonly<Record<string, string>>,
		infra: InfraAccess | null,
		reserved: ReservedFlags = NO_RESERVED_FLAGS,
		effects: MutatingEffects | null = null,
	) {
		this.stdout = stdout;
		this.stderr = stderr;
		this.sources = sources;
		this.infra = infra;
		this.reserved = reserved;
		this.effectsHandle = effects;
	}

	/** True when the framework-owned --dry-run flag was passed. */
	get dryRun(): boolean {
		return this.reserved.dryRun;
	}

	/** True when the framework-owned --yes flag was passed. */
	get yes(): boolean {
		return this.reserved.yes;
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

	/** Writes an informational message to stdout (hidden under --quiet). */
	info(msg: string): void {
		if (this.reserved.quiet) {
			return;
		}
		this.stdout.write(`${msg}\n`);
	}

	/** Writes a warning message to stderr (never suppressed). */
	warn(msg: string): void {
		this.stderr.write(`${msg}\n`);
	}

	/**
	 * Writes a debug message to stdout, shown only under --verbose.
	 * --quiet DOMINATES --verbose: passing both hides debug output.
	 */
	debug(msg: string): void {
		if (this.reserved.quiet || !this.reserved.verbose) {
			return;
		}
		this.stdout.write(`${msg}\n`);
	}

	/** Writes an error message to stderr (never suppressed). */
	error(msg: string): void {
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
		if (this.infra !== null && this.infra.connections.has(envVar)) {
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
