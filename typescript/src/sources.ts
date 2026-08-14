/**
 * Per-parse provenance store, mirroring Go's sourcedStore (parse.go) and
 * Python's _SourcedStore, where every resolved flag value carries a source
 * label. Mutex and dependency checks are source-filtered so defaulted values
 * never trigger violations.
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

/**
 * The source labels that mean the INVOCATION caused the value, i.e. the ONE
 * definition of "was this supplied" (contract §23.6). `default` and `infra`
 * are the declaration deciding -- `infra` is a RelativeToRoot default whose
 * label merely says WHICH default it was -- so neither counts.
 *
 * Both consumers read this set: the dependency predicate below
 * (CoRequired/Requires/Implies presence, plus the custom-validation step,
 * which never runs on a declared default) and `ctx.provided`.
 */
export const PROVIDED_SOURCES: ReadonlySet<string> = new Set<SourceLabel>([
	"cli",
	"env",
	"config",
	"implied",
]);

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
	 * itself be undefined (a flag declaring `presence: "optional"`), so
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
	 * The value came from a command-line token. Mutex election is CLI-only
	 * (effects contract §21.3): env and config sources neither elect a member
	 * nor supply its value.
	 */
	isCli(name: string): boolean {
		return this.entries.get(name)?.source === "cli";
	}

	/** The value came from an env var or the config file. */
	isEnvOrConfig(name: string): boolean {
		const source = this.entries.get(name)?.source;
		return source === "env" || source === "config";
	}

	/** Drop an entry entirely, so defaults apply to it later. */
	delete(name: string): void {
		this.entries.delete(name);
	}

	/**
	 * "Present" for dependency checks (coRequired, requires, implies): the
	 * invocation caused the value. This is the one shared definition
	 * (contract §23.6) -- cli, env, config and implied count; `default` and
	 * `infra` do not, both being the declaration deciding. `ctx.provided`
	 * answers off the same set.
	 */
	isPresentForDeps(name: string): boolean {
		const e = this.entries.get(name);
		if (e === undefined) {
			return false;
		}
		return PROVIDED_SOURCES.has(e.source);
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
