/**
 * Handler outcome: the branded structured-result type and the strict
 * interpretation of handler return values. Mirrors Python's Outcome /
 * outcome() / _interpret_handler_return (the divergence ground truth; Go's
 * type system makes bad returns inexpressible).
 *
 * Data JSON serialization lives here too: one compact line, BigInt values as
 * bare integer tokens (JSON.stringify cannot emit those, hence the custom
 * serializer). Map keys are emitted sorted (the TS dict type mirrors Go maps,
 * which json.Marshal sorts); plain objects keep insertion order (mirroring
 * Python dicts under json.dumps).
 */

import {
	errHandlerReturnInvalid,
	errOutcomeExitCodeNotInteger,
} from "./errors.js";

// Phantom brand: never present at runtime. The runtime brand is MINTED below.
declare const OutcomeBrand: unique symbol;

/**
 * A structured result returned by a command handler. Built exclusively via
 * the outcome() factory -- the mint set is module-private, so hand-forged
 * objects are never recognized as outcomes (no structural shape detection).
 */
export interface Outcome {
	readonly [OutcomeBrand]: true;
	readonly exitCode: number;
	readonly data: unknown;
}

// Module-private mint registry: the runtime analog of Python's _OUTCOME_TOKEN.
const MINTED = new WeakSet<object>();

/**
 * Builds an Outcome for a command handler to return. `exitCode` defaults to 0.
 * When `data` is not undefined/null it is JSON-printed to stdout as one
 * compact line and captured by test()/call().
 */
export function outcome(exitCode = 0, data?: unknown): Outcome {
	if (typeof exitCode !== "number" || !Number.isInteger(exitCode)) {
		throw new TypeError(errOutcomeExitCodeNotInteger(returnTypeName(exitCode)));
	}
	const o = Object.freeze({ exitCode, data });
	MINTED.add(o);
	return o as unknown as Outcome;
}

export function isOutcome(v: unknown): v is Outcome {
	return typeof v === "object" && v !== null && MINTED.has(v);
}

/** Interpreted handler return: exit code plus the optional data payload. */
export interface InterpretedReturn {
	readonly exitCode: number;
	/** False when there is no structured payload to emit (Python's _MISSING). */
	readonly hasData: boolean;
	readonly data: unknown;
}

/** Runtime type name for the bad-return error message (TS vocabulary). */
function returnTypeName(v: unknown): string {
	if (v === null) {
		return "null";
	}
	if (typeof v === "number") {
		// Integers are accepted upstream; only non-integer numbers reach here.
		return "non-integer number";
	}
	if (typeof v !== "object") {
		return typeof v;
	}
	if (Array.isArray(v)) {
		return "Array";
	}
	const ctor = (v as { constructor?: { name?: string } }).constructor?.name;
	return ctor !== undefined && ctor !== "" ? ctor : "object";
}

/**
 * Maps a command handler's (awaited) return value to exit code + data. The
 * only permitted returns are an integer number (exit code), undefined
 * (exit 0), or an outcome() -- anything else is a hard error (TypeError),
 * mirroring Python's _interpret_handler_return.
 */
export function interpretHandlerReturn(result: unknown): InterpretedReturn {
	if (result === undefined) {
		return { exitCode: 0, hasData: false, data: undefined };
	}
	if (isOutcome(result)) {
		// undefined AND null both mean "no data", matching Python's `data is
		// None` and Go's nil-data checks -- neither sibling can emit JSON null.
		const hasData = result.data !== undefined && result.data !== null;
		return { exitCode: result.exitCode, hasData, data: result.data };
	}
	if (typeof result === "number" && Number.isInteger(result)) {
		return { exitCode: result, hasData: false, data: undefined };
	}
	throw new TypeError(errHandlerReturnInvalid(returnTypeName(result)));
}

/**
 * Serializes outcome data as one compact JSON line (no whitespace). BigInt
 * values become bare integer tokens; Maps become objects with sorted keys;
 * plain objects keep insertion order and skip undefined-valued properties
 * (JSON.stringify semantics).
 */
export function jsonCompact(value: unknown): string {
	const s = serialize(value);
	// Top-level undefined cannot occur: callers only serialize present data.
	return s ?? "null";
}

function serialize(v: unknown): string | undefined {
	if (v === null) {
		return "null";
	}
	switch (typeof v) {
		case "bigint":
			return v.toString();
		case "number":
		case "boolean":
		case "string":
			return JSON.stringify(v);
		case "undefined":
		case "function":
		case "symbol":
			return undefined;
		case "object": {
			if (Array.isArray(v)) {
				return `[${v.map((el) => serialize(el) ?? "null").join(",")}]`;
			}
			if (v instanceof Map) {
				const entries = [...(v as Map<unknown, unknown>).entries()]
					.map(([k, val]): [string, unknown] => [String(k), val])
					.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
				const parts: string[] = [];
				for (const [k, val] of entries) {
					const s = serialize(val);
					if (s !== undefined) {
						parts.push(`${JSON.stringify(k)}:${s}`);
					}
				}
				return `{${parts.join(",")}}`;
			}
			const withToJSON = v as { toJSON?: (key?: string) => unknown };
			if (typeof withToJSON.toJSON === "function") {
				return serialize(withToJSON.toJSON());
			}
			const parts: string[] = [];
			for (const [k, val] of Object.entries(v)) {
				const s = serialize(val);
				if (s !== undefined) {
					parts.push(`${JSON.stringify(k)}:${s}`);
				}
			}
			return `{${parts.join(",")}}`;
		}
	}
}
