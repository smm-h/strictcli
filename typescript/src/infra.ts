/**
 * Infrastructure env vars: location roots, handshake signals, and the
 * RelativeToRoot path marker. Mirrors Go WithInfraRoot/WithHandshakeEnv/
 * RelativeToRoot (strictcli.go) with Python's infra_root/handshake_env as the
 * divergence ground truth.
 *
 * Roots are resolved EAGERLY at app construction: the env var's value if set,
 * else the declared default, with a leading ~ expanded. Resolution has no
 * argv dependency, which is exactly why roots are hermetic-immune --
 * --hermetic only suppresses argv-derived config/env behavior. Handshake vars
 * are never captured; they are read LIVE from the environment at
 * ctx.infraValue() time.
 */

import { homedir } from "node:os";
import { join } from "node:path";
import type { InfraAccess } from "./context.js";
import {
	errCommandFlagRelativeToRootUndeclared,
	errFlagRelativeToRootUndeclared,
	errRelativeToRootUndeclared,
	RegistrationError,
} from "./errors.js";

// Phantom brand: never present at runtime. The runtime brand is MINTED below.
declare const InfraRootPathBrand: unique symbol;

/**
 * Opaque marker for a filesystem path built from a declared infrastructure
 * root (identified by its env var name) joined with zero or more path parts.
 * Built exclusively via the relativeToRoot() factory (branded like Outcome --
 * hand-forged objects are never recognized as markers). Accepted as a flag
 * `default:` (resolved when defaults are applied at parse time; source label
 * "infra") and as the config path (resolved eagerly at construction). A
 * marker referencing an undeclared root is a registration-time hard error.
 */
export interface InfraRootPath {
	readonly [InfraRootPathBrand]: true;
	readonly envVar: string;
	readonly parts: readonly string[];
}

// Module-private mint registry (the outcome() pattern).
const MINTED = new WeakSet<object>();

/**
 * Python repr() of a string, for the marker's display form (registration
 * errors and help meta render the Python repr -- the divergence ground truth).
 */
function pyStrRepr(s: string): string {
	if (s.includes("'") && !s.includes('"')) {
		return `"${s.replaceAll("\\", "\\\\")}"`;
	}
	return `'${s.replaceAll("\\", "\\\\").replaceAll("'", "\\'")}'`;
}

/**
 * Builds a marker representing a path relative to a declared infrastructure
 * root. envVar names the root (declared via createApp's `infraRoot`); parts
 * are joined onto the resolved root path.
 */
export function relativeToRoot(
	envVar: string,
	...parts: string[]
): InfraRootPath {
	const marker = Object.freeze({
		envVar,
		parts: Object.freeze([...parts]),
		// Python __repr__ parity, including the trailing ", " when parts is
		// empty (repr(RelativeToRoot('E')) == "RelativeToRoot('E', )").
		toString(): string {
			return `RelativeToRoot(${pyStrRepr(envVar)}, ${parts
				.map(pyStrRepr)
				.join(", ")})`;
		},
	});
	MINTED.add(marker);
	return marker as unknown as InfraRootPath;
}

export function isInfraRootPath(v: unknown): v is InfraRootPath {
	return typeof v === "object" && v !== null && MINTED.has(v);
}

/** Expands a leading ~ (as ~ or ~/...) to the user's home directory. */
export function expandTilde(p: string): string {
	if (p === "~") {
		return homedir();
	}
	if (p.startsWith("~/")) {
		return join(homedir(), p.slice(2));
	}
	return p;
}

/**
 * Resolves a marker against the resolved roots map (env var -> path). Throws
 * a plain Error (message from the catalog) when the marker references an
 * undeclared root -- callers wrap it per context (registration validation
 * throws RegistrationError first, so parse-time resolution cannot fail).
 */
export function resolveInfraRootPath(
	ref: InfraRootPath,
	roots: ReadonlyMap<string, string>,
): string {
	const root = roots.get(ref.envVar);
	if (root === undefined) {
		throw new Error(errRelativeToRootUndeclared(ref.envVar));
	}
	return join(root, ...ref.parts);
}

/** Flag-shaped structural view (no factories import, keeping this module leaf-level). */
interface FlagDefaultView {
	readonly name: string;
	readonly opts: Readonly<Record<string, unknown>>;
}

/**
 * Registration-time hard error for a flag whose default is a marker
 * referencing an undeclared root. cmdName selects the command-scoped message
 * (Python's _build_and_validate_command form); global flags use the
 * flag-scoped message both siblings share.
 */
export function validateFlagInfraMarker(
	f: FlagDefaultView,
	roots: ReadonlyMap<string, string>,
	cmdName?: string,
): void {
	const dflt = f.opts.default;
	if (isInfraRootPath(dflt) && !roots.has(dflt.envVar)) {
		throw new RegistrationError(
			cmdName === undefined
				? errFlagRelativeToRootUndeclared(f.name, dflt.envVar)
				: errCommandFlagRelativeToRootUndeclared(cmdName, f.name, dflt.envVar),
		);
	}
}

/**
 * Snapshots an app's infra data for a Context (Go infraAccess): resolved root
 * values plus the set of declared handshake vars. Null when nothing is
 * declared, so ctx.infraValue() throws the not-declared error for everything.
 */
export function buildInfraAccess(
	roots: ReadonlyMap<string, string>,
	handshakeEnvs: ReadonlyMap<string, string>,
): InfraAccess | null {
	if (roots.size === 0 && handshakeEnvs.size === 0) {
		return null;
	}
	return { roots: new Map(roots), handshakes: new Set(handshakeEnvs.keys()) };
}
