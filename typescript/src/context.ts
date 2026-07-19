/**
 * Structured output context for command handlers, mirroring Go's Context
 * (context.go) with Python's Context as the divergence ground truth. Always
 * injected as the second argument to every handler ((args, ctx) signature).
 * app.ts builds the InfraAccess view (infra.ts buildInfraAccess) per
 * dispatch; it is null when the app declares no roots or handshakes, so
 * every infraValue() call throws the not-declared error.
 */

import { errInfraValueUndeclared, errNoSourceInfo } from "./errors.js";

/** Minimal sink for output streams (process.stdout/stderr or test captures). */
export interface Writer {
	write(text: string): void;
}

/**
 * A Context's view of infrastructure env vars: root values resolved eagerly
 * at app construction, plus the set of declared handshake vars (read live).
 */
export interface InfraAccess {
	readonly roots: ReadonlyMap<string, string>;
	readonly handshakes: ReadonlySet<string>;
}

export class Context {
	private readonly stdout: Writer;
	private readonly stderr: Writer;
	private readonly sources: Readonly<Record<string, string>>;
	private readonly infra: InfraAccess | null;

	constructor(
		stdout: Writer,
		stderr: Writer,
		sources: Readonly<Record<string, string>>,
		infra: InfraAccess | null,
	) {
		this.stdout = stdout;
		this.stderr = stderr;
		this.sources = sources;
		this.infra = infra;
	}

	/** Writes an informational message to stdout. */
	info(msg: string): void {
		this.stdout.write(`${msg}\n`);
	}

	/** Writes a warning message to stderr. */
	warn(msg: string): void {
		this.stderr.write(`${msg}\n`);
	}

	/** Writes a debug message to stdout. */
	debug(msg: string): void {
		this.stdout.write(`${msg}\n`);
	}

	/** Writes an error message to stderr. */
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
		}
		throw new Error(errInfraValueUndeclared(envVar));
	}
}
