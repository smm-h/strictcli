/**
 * Env var value resolution for a single flag, mirroring the env-resolution
 * blocks of Go parseCommand/extractGlobalFlags and Python's step-4 loops.
 * Env-prefix conformance is a registration-time concern (app.ts); this module
 * only turns an env var's string value into a typed flag value.
 *
 * Per-type rules:
 * - dict: the env value is a whole JSON object.
 * - list: split on the declared envSeparator (escape-aware), coerce each
 *   element by the element schema; str elements resolve the @-prefix.
 * - bool: strict bool strings (1|true|yes / 0|false|no, case-insensitive).
 * - int/float: strict parse, errors suffixed with "(from env var '<VAR>')".
 * - str: @-prefix resolution (its errors carry no env suffix, matching the
 *   siblings).
 */

import { resolveAtPrefix, type StdinTracker } from "./atprefix.js";
import {
	errFlagDuplicateValueFromEnv,
	errFlagErrFromEnvVar,
	errInvalidBoolEnvValue,
	errListFlagEnvRequiresSeparator,
	errWrappedFromEnvVar,
	ParseError,
} from "./errors.js";
import {
	type AnyFlag,
	elemSchemaOf,
	flagOpts,
	schemaKind,
} from "./factories.js";
import {
	findDuplicate,
	formatValueForError,
	parseBoolStrict,
	parseDictEnvValue,
	parseFloatStrictFlag,
	parseIntStrict,
	splitEscaped,
} from "./values.js";

/**
 * Resolves envVal (the raw string value of envVar) into the typed value for
 * flag f. Throws ParseError with sibling-exact messages.
 */
export function resolveEnvValue(
	f: AnyFlag,
	envVar: string,
	envVal: string,
	tracker: StdinTracker,
): unknown {
	const o = flagOpts(f);
	const kind = schemaKind(f.schema);
	const elem = elemSchemaOf(f.carrier);
	if (kind === "dict") {
		return parseDictEnvValue(f.name, envVar, envVal, elem);
	}
	if (kind === "list") {
		// Registration guarantees list+env implies envSeparator; kept as a hard
		// error for parity with Go's runtime check.
		if (o.envSeparator === undefined) {
			throw new ParseError(errListFlagEnvRequiresSeparator(f.name));
		}
		const parts = splitEscaped(envVal, o.envSeparator);
		const coerced: unknown[] = [];
		for (const element of parts) {
			switch (elem) {
				case "int":
					try {
						coerced.push(parseIntStrict(element));
					} catch (e) {
						throw new ParseError(
							errFlagErrFromEnvVar(f.name, (e as Error).message, envVar),
						);
					}
					break;
				case "float":
					try {
						coerced.push(parseFloatStrictFlag(f.name, element));
					} catch (e) {
						throw new ParseError(
							errWrappedFromEnvVar((e as Error).message, envVar),
						);
					}
					break;
				default:
					// str: @-prefix errors propagate without the env suffix.
					coerced.push(resolveAtPrefix(f.name, element, tracker));
					break;
			}
		}
		if (o.unique === true) {
			const dup = findDuplicate(coerced);
			if (dup !== undefined) {
				throw new ParseError(
					errFlagDuplicateValueFromEnv(
						f.name,
						formatValueForError(dup),
						envVar,
					),
				);
			}
		}
		return coerced;
	}
	switch (f.schema) {
		case "bool":
			try {
				return parseBoolStrict(envVal);
			} catch {
				throw new ParseError(errInvalidBoolEnvValue(envVal, envVar, f.name));
			}
		case "int":
			try {
				return parseIntStrict(envVal);
			} catch (e) {
				throw new ParseError(
					errFlagErrFromEnvVar(f.name, (e as Error).message, envVar),
				);
			}
		case "float":
			try {
				return parseFloatStrictFlag(f.name, envVal);
			} catch (e) {
				throw new ParseError(
					errWrappedFromEnvVar((e as Error).message, envVar),
				);
			}
		default:
			// str: @-prefix errors propagate without the env suffix.
			return resolveAtPrefix(f.name, envVal, tracker);
	}
}
