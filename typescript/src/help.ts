/**
 * Help rendering at app/group/command levels, byte-identical to the siblings
 * (Go help.go, Python _format_app_help/_format_group_help/_format_command_help)
 * and pinned by conformance/cases/help.json (plus the help expectations
 * scattered across the other case files).
 *
 * Sibling divergences resolved here:
 * - App-level "Global flags:" section: Python renders it (name/short + help,
 *   no meta), Go omits it entirely; no conformance case covers it. TS follows
 *   Python (the divergence ground truth).
 * - "[optional]" for explicitly-optional flags (default: null): Go-only
 *   behavior (the Default(nil) fix); Python cannot express it. TS supports
 *   default: null, so it adopts the Go rendering.
 * - List carriers render "[repeatable]" when declared with repeatable: true
 *   (the sibling scalar-repeatable shape) and "[list]" otherwise (the sibling
 *   compound-list shape).
 */

import type { AppImpl, GroupImpl, RegisteredCommand } from "./app.js";
import {
	type AnyArg,
	type AnyFlag,
	elemSchemaOf,
	flagOpts,
	schemaKind,
} from "./factories.js";
import { formatFloatCanonical } from "./float.js";
import {
	formatChoices,
	formatDictForDisplay,
	formatValueForError,
} from "./values.js";

export function formatVersion(app: AppImpl): string {
	return `${app.name} ${app.version}`;
}

/** Two-column section body: "  name<pad>text" with 4-space gutter. */
function twoColumn(rows: readonly (readonly [string, string])[]): string[] {
	const maxLen = Math.max(...rows.map(([left]) => left.length));
	return rows.map(
		([left, right]) =>
			`  ${left}${" ".repeat(maxLen - left.length + 4)}${right}`,
	);
}

function commandsSection(
	lines: string[],
	label: string,
	entries: readonly (readonly [string, string])[],
): void {
	if (entries.length > 0) {
		lines.push("", label, ...twoColumn(entries));
	}
}

export function formatAppHelp(app: AppImpl): string {
	const lines: string[] = [`${app.name} v${app.version} -- ${app.help}`];

	commandsSection(
		lines,
		"Commands:",
		[...app.commands.values()]
			.filter((c) => !c.hidden)
			.map((c) => [c.name, c.help] as const),
	);
	commandsSection(
		lines,
		"Groups:",
		[...app.groups.values()]
			.filter((g) => !g.hidden)
			.map((g) => [g.name, g.help] as const),
	);
	commandsSection(
		lines,
		"Deprecated:",
		[...app.deprecated.entries()].map(([n, msg]) => [n, msg] as const),
	);

	if (app.globalFlags.length > 0) {
		// App-level global flags render name + short + help only (no meta),
		// mirroring Python's app help (Go has no app-level section at all).
		const rows = app.globalFlags.map((f) => {
			const parts = [`--${f.name}`];
			const short = flagOpts(f).short;
			if (short !== undefined && short !== "") {
				parts.push(`-${short}`);
			}
			return [parts.join(", "), f.opts.help] as const;
		});
		lines.push("", "Global flags:", ...twoColumn(rows));
	}

	if (app.infraRoots.size > 0 || app.handshakeEnvs.size > 0) {
		lines.push(
			"",
			"Infrastructure:",
			"  (location/handshake env vars; not suppressed by --hermetic)",
		);
		const rows: (readonly [string, string])[] = [
			...[...app.infraRoots.keys()].map(
				(ev) =>
					[
						ev,
						`root (default: ${app.infraRootDefaults.get(ev) ?? ""})`,
					] as const,
			),
			...[...app.handshakeEnvs.entries()].map(
				([ev, helpText]) => [ev, helpText] as const,
			),
		];
		lines.push(...twoColumn(rows));
	}

	lines.push("", `Use '${app.name} <command> --help' for more information.`);
	return lines.join("\n");
}

export function formatGroupHelp(
	app: AppImpl,
	group: GroupImpl,
	path: readonly string[],
): string {
	const fullPath = path.join(" ");
	const lines: string[] = [`${app.name} ${fullPath} -- ${group.help}`];

	commandsSection(
		lines,
		"Commands:",
		[...group.commands.values()]
			.filter((c) => !c.hidden)
			.map((c) => [c.name, c.help] as const),
	);
	commandsSection(
		lines,
		"Groups:",
		[...group.groups.values()]
			.filter((g) => !g.hidden)
			.map((g) => [g.name, g.help] as const),
	);
	commandsSection(
		lines,
		"Deprecated:",
		[...group.deprecated.entries()].map(([n, msg]) => [n, msg] as const),
	);

	lines.push(
		"",
		`Use '${app.name} ${fullPath} <command> --help' for more information.`,
	);
	return lines.join("\n");
}

/** Formats a default value for help text (floats via SCF, dicts sorted). */
function formatDefaultForHelp(value: unknown): string {
	if (typeof value === "number") {
		return formatFloatCanonical(value);
	}
	if (value instanceof Map) {
		return formatDictForDisplay(value as ReadonlyMap<string, unknown>);
	}
	return String(value);
}

/** Left-column spec string for a flag (e.g. "--target, -t <str>"). */
export function buildFlagSpec(f: AnyFlag): string {
	const o = flagOpts(f);
	const parts: string[] = [];
	if (f.schema === "bool" && o.negatable !== false) {
		parts.push(`--${f.name}, --no-${f.name}`);
	} else {
		parts.push(`--${f.name}`);
	}
	if (o.short !== undefined && o.short !== "") {
		parts.push(`-${o.short}`);
	}
	let spec = parts.join(", ");
	const kind = schemaKind(f.schema);
	if (kind === "list") {
		spec += ` <${elemSchemaOf(f.carrier)}>`;
	} else if (kind === "dict") {
		spec += ` <key=${elemSchemaOf(f.carrier)}>`;
	} else if (f.schema !== "bool") {
		spec += ` <${f.schema}>`;
	}
	return spec;
}

/** Bracketed metadata suffix for a flag (" [x] [y]" form). */
export function buildFlagMeta(f: AnyFlag): string {
	const o = flagOpts(f);
	const kind = schemaKind(f.schema);
	const metaParts: string[] = [];
	if (kind === "dict") {
		metaParts.push("dict");
	} else if (kind === "list") {
		metaParts.push(o.repeatable === true ? "repeatable" : "list");
	}
	if (o.unique === true) {
		metaParts.push("unique");
	}
	if (o.choices !== undefined) {
		metaParts.push(`choices: ${formatChoices(o.choices)}`);
	}
	if (o.env !== undefined) {
		metaParts.push(
			o.envSeparator !== undefined
				? `env: ${o.env} (sep: ${o.envSeparator})`
				: `env: ${o.env}`,
		);
	}
	const dflt = o.default;
	if (kind === "dict") {
		// Dict flags are never required; show the default only if non-empty.
		if (dflt instanceof Map && dflt.size > 0) {
			metaParts.push(`default: ${formatDefaultForHelp(dflt)}`);
		}
	} else if (f.schema === "bool" && dflt !== undefined && dflt !== null) {
		metaParts.push(`default: ${dflt === true ? "true" : "false"}`);
	} else if (kind === "list") {
		// List flags are never required; show the default only if non-empty.
		if (Array.isArray(dflt) && dflt.length > 0) {
			metaParts.push(`default: ${dflt.map(formatValueForError).join(", ")}`);
		}
	} else if (dflt !== undefined && dflt !== null) {
		metaParts.push(`default: ${formatDefaultForHelp(dflt)}`);
	} else if (dflt === null) {
		metaParts.push("optional");
	} else {
		metaParts.push("required");
	}
	return ` [${metaParts.join("] [")}]`;
}

function flagRows(flags: readonly AnyFlag[]): (readonly [string, string])[] {
	return flags.map(
		(f) => [buildFlagSpec(f), `${f.opts.help}${buildFlagMeta(f)}`] as const,
	);
}

function argDisplayName(a: AnyArg): string {
	return a.opts.variadic === true ? `${a.name}...` : a.name;
}

function argMeta(a: AnyArg): string {
	const metaParts: string[] = [];
	if (a.schema !== "str") {
		metaParts.push(`type: ${a.schema}`);
	}
	const opts = a.opts as {
		readonly choices?: readonly unknown[];
	} & AnyArg["opts"];
	if (opts.choices !== undefined) {
		metaParts.push(`choices: ${formatChoices(opts.choices)}`);
	}
	if (a.opts.required === false) {
		if ("default" in a.opts) {
			metaParts.push(`default: ${formatDefaultForHelp(a.opts.default)}`);
		} else {
			metaParts.push("optional");
		}
	}
	return metaParts.length > 0 ? ` [${metaParts.join("] [")}]` : "";
}

export function formatCommandHelp(
	app: AppImpl,
	cmd: RegisteredCommand,
	prefix: string,
): string {
	const lines: string[] = [`${app.name} ${prefix}${cmd.name} -- ${cmd.help}`];

	// Passthrough commands show only the header line.
	if (cmd.def.kind === "passthrough") {
		return lines.join("\n");
	}
	const def = cmd.def;

	if (def.args.length > 0) {
		const rows = def.args.map(
			(a) => [argDisplayName(a), `${a.opts.help}${argMeta(a)}`] as const,
		);
		lines.push("", "Arguments:", ...twoColumn(rows));
	}

	const mutexFlagNames = new Set<string>();
	for (const mg of def.mutex) {
		for (const f of Object.values(mg.flags)) {
			mutexFlagNames.add(f.name);
		}
	}
	const regularFlags = cmd.flags.filter((f) => !mutexFlagNames.has(f.name));

	if (regularFlags.length > 0) {
		lines.push("", "Flags:", ...twoColumn(flagRows(regularFlags)));
	}
	for (const mg of def.mutex) {
		lines.push(
			"",
			"Flags (mutually exclusive):",
			...twoColumn(flagRows(Object.values(mg.flags))),
		);
	}
	if (app.globalFlags.length > 0) {
		lines.push("", "Global flags:", ...twoColumn(flagRows(app.globalFlags)));
	}

	return lines.join("\n");
}
