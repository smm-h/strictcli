/**
 * Per-parse provenance store, mirroring Go's sourcedStore (parse.go) and
 * Python's _SourcedStore. Every resolved flag value carries a source label;
 * mutex and dependency checks are source-filtered so defaulted values never
 * trigger violations.
 *
 * Label strings are the cross-language provenance vocabulary and must match
 * the siblings byte-for-byte (ctx.source() and `config show` expose them).
 */

export type SourceLabel =
	| "cli"
	| "env"
	| "config"
	| "default"
	| "implied"
	| "infra";

export interface SourcedEntry {
	/** `undefined` is the TS analog of the siblings' nil/None flag value. */
	readonly value: unknown;
	readonly source: SourceLabel;
}

export class SourcedStore {
	private readonly entries = new Map<string, SourcedEntry>();

	set(name: string, value: unknown, source: SourceLabel): void {
		this.entries.set(name, { value, source });
	}

	/**
	 * Returns the stored value, or undefined when absent. A stored value can
	 * itself be undefined (an unset mutex flag / explicitly-optional flag), so
	 * presence checks must go through has(), never through get().
	 */
	get(name: string): unknown {
		return this.entries.get(name)?.value;
	}

	getEntry(name: string): SourcedEntry | undefined {
		return this.entries.get(name);
	}

	has(name: string): boolean {
		return this.entries.has(name);
	}

	/**
	 * "Present" for mutex evaluation: only cli, env, and config sources count.
	 * Default and implied values do NOT trigger mutex violations.
	 */
	isPresentForMutex(name: string): boolean {
		const e = this.entries.get(name);
		if (e === undefined) {
			return false;
		}
		return e.source === "cli" || e.source === "env" || e.source === "config";
	}

	/**
	 * "Present" for dependency checks (coRequired, requires): cli, env,
	 * config, and implied sources count. Default values do NOT.
	 */
	isPresentForDeps(name: string): boolean {
		const e = this.entries.get(name);
		if (e === undefined) {
			return false;
		}
		return e.source !== "default";
	}

	/** Flag name -> source label for every stored entry. */
	sourceMap(): Map<string, SourceLabel> {
		const m = new Map<string, SourceLabel>();
		for (const [k, e] of this.entries) {
			m.set(k, e.source);
		}
		return m;
	}
}
