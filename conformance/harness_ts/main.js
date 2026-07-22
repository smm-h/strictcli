// TypeScript conformance harness. Mirrors conformance/harness/main.go in
// contract: reads the app-definition JSON file path from the
// CONFORMANCE_APP_DEF env var, builds the app through the TS public API
// (typescript/dist), and runs app.run() against process.argv.slice(2).
// Registration errors print "error: <msg>" to stderr and exit 1 (the Go
// harness's recover semantics / the Python ref's `except ValueError` wrap).
//
// Import mechanism: direct relative import of the built dist. The harness is
// plain Node ESM (no tsconfig, no install, no build of its own); its only
// prerequisite is `cd typescript && npm run build`. Bare specifiers used by
// the dist itself (smol-toml) resolve through typescript/node_modules via
// Node's directory walk-up, because the imported files live under typescript/.
import { readFileSync, writeFileSync } from "node:fs";

import {
	errCommandDuplicateFlag,
	errCommandPassthroughCannotHave,
	errDuplicateGlobalFlag,
	errFlagRepeatableRequiresExplicitUnique,
} from "../../typescript/dist/errors.js";
import { formatFloatCanonical } from "../../typescript/dist/float.js";
import {
	arg,
	coRequired,
	createApp,
	defineCommand,
	deprecated,
	errorCheckSpec,
	flag,
	flagSet,
	implies,
	mutexGroup,
	outcome,
	passthrough,
	relativeToRoot,
	requires,
	t,
	warnCheckSpec,
} from "../../typescript/dist/index.js";

function underscore(name) {
	return name.replaceAll("-", "_");
}

/** Literal (non-regex, non-$-pattern) replace-all. */
function subst(text, needle, replacement) {
	return text.split(needle).join(replacement);
}

// ---------------------------------------------------------------------------
// Value rendering (the cross-target template vocabulary): bool -> true/false,
// nil/None -> None, int (bigint) -> decimal, float -> canonical form, lists/
// variadics comma-join, dicts (Maps) comma-join k=v with keys sorted.
// ---------------------------------------------------------------------------
function render(v) {
	if (v === undefined || v === null) {
		return "None";
	}
	switch (typeof v) {
		case "boolean":
			return v ? "true" : "false";
		case "bigint":
			return v.toString();
		case "number":
			return formatFloatCanonical(v);
		case "string":
			return v;
		default:
			break;
	}
	if (Array.isArray(v)) {
		return v.map(render).join(",");
	}
	if (v instanceof Map) {
		return [...v.keys()]
			.sort()
			.map((k) => `${k}=${render(v.get(k))}`)
			.join(",");
	}
	return String(v);
}

// ---------------------------------------------------------------------------
// Carriers
// ---------------------------------------------------------------------------
function scalarCarrier(typeName) {
	switch (typeName) {
		case "bool":
			return t.bool;
		case "int":
			return t.int;
		case "float":
			return t.float;
		default:
			return t.str;
	}
}

/** Scalar JSON value -> the TS runtime value for a strictcli type. */
function convertScalar(typeName, v) {
	if (v === null || v === undefined) {
		return v;
	}
	// Only JSON numbers become bigints; a mistyped value (e.g. a string
	// default on an int flag) carries over as-is so the framework mints its
	// own default-type registration error (the Go harness's `if float64`
	// pattern).
	if (typeName === "int" && typeof v === "number") {
		return BigInt(v);
	}
	return v; // bool, float, str carry over as-is
}

/** Element type of "list[int]" / "dict[str,int]" -> "int". */
function elemTypeOf(ftype) {
	if (ftype.startsWith("list[")) {
		return ftype.slice(5, -1);
	}
	if (ftype.startsWith("dict[")) {
		return ftype.slice(9, -1);
	}
	return ftype;
}

// ---------------------------------------------------------------------------
// Flag construction
// ---------------------------------------------------------------------------
function buildFlag(fd) {
	const name = fd.name;
	const ftype = fd.type ?? "str";
	const isList = ftype.startsWith("list[");
	const isDict = ftype.startsWith("dict[");
	const repeatable = fd.repeatable === true;
	const elemType = elemTypeOf(ftype);

	// Scalar repeatable-without-unique is inexpressible through the TS
	// factory API (the list carrier that a repeatable scalar maps to defaults
	// unique like Python's list[T] does), so the framework's guard is
	// replayed here with its own catalog message. bool + repeatable is
	// excluded: the framework's bool-incompatibility error fires first,
	// matching the sibling validation order.
	if (
		repeatable &&
		!isList &&
		!isDict &&
		ftype !== "bool" &&
		!("unique" in fd)
	) {
		throw new Error(errFlagRepeatableRequiresExplicitUnique(name));
	}

	// Carrier: list/dict types map directly; a repeatable scalar becomes a
	// list carrier (in TS, list carriers ARE the repeatable flags -- scalar
	// repeatable does not exist). bool + repeatable keeps the scalar carrier
	// so the framework mints the repeatable-incompatible-with-bool error.
	let carrier;
	if (isList || (repeatable && ftype !== "bool")) {
		carrier = t.list(scalarCarrier(elemType));
	} else if (isDict) {
		carrier = t.dict(scalarCarrier(elemType));
	} else {
		carrier = scalarCarrier(ftype);
	}

	const opts = { help: fd.help };
	if ("short" in fd) {
		opts.short = fd.short;
	}
	if ("default_relative_to_root" in fd) {
		const rtr = fd.default_relative_to_root;
		opts.default = relativeToRoot(rtr.env_var, ...(rtr.parts ?? []));
	}
	if ("default" in fd) {
		const dv = fd.default;
		if (dv === null) {
			opts.default = null; // explicitly-optional flag (Go Default(nil))
		} else if (Array.isArray(dv)) {
			opts.default = dv.map((el) => convertScalar(elemType, el));
		} else {
			opts.default = convertScalar(ftype, dv);
		}
	}
	if ("env" in fd) {
		opts.env = fd.env;
	}
	if ("prefixed" in fd) {
		opts.prefixed = fd.prefixed;
	}
	if ("choices_str" in fd) {
		opts.choices = fd.choices_str;
	}
	if ("choices_int" in fd) {
		opts.choices = fd.choices_int.map((c) => BigInt(c));
	}
	if ("choices_float" in fd) {
		opts.choices = fd.choices_float;
	}
	if (repeatable) {
		opts.repeatable = true;
	}
	if ("unique" in fd) {
		opts.unique = fd.unique;
	}
	if ("conflict_mode" in fd) {
		opts.conflictMode = fd.conflict_mode;
	}
	if ("env_separator" in fd) {
		opts.envSeparator = fd.env_separator;
	}
	if ("negatable" in fd && fd.negatable === false) {
		opts.negatable = false;
	}
	return flag(name, carrier, opts);
}

/**
 * Builds a FlagMap keyed by the underscore form of each flag name. A JS
 * object would silently collapse a same-name duplicate, so the framework's
 * duplicate check is replayed here first with the framework's own catalog
 * message (dupMessage receives the colliding flag name).
 */
function flagMapOf(flagDefs, dupMessage) {
	const fm = {};
	for (const fd of flagDefs) {
		const key = underscore(fd.name);
		if (key in fm) {
			throw new Error(dupMessage(fd.name));
		}
		fm[key] = buildFlag(fd);
	}
	return fm;
}

// ---------------------------------------------------------------------------
// Arg construction
// ---------------------------------------------------------------------------
function buildArg(ad) {
	const atype = ad.type ?? "str";
	const opts = { help: ad.help };
	if ("required" in ad) {
		opts.required = ad.required;
	}
	if ("default" in ad) {
		opts.default = ad.default === null ? null : convertScalar(atype, ad.default);
	}
	if (ad.variadic === true) {
		opts.variadic = true;
	}
	if ("choices_str" in ad) {
		opts.choices = ad.choices_str;
	}
	if ("choices_int" in ad) {
		opts.choices = ad.choices_int.map((c) => BigInt(c));
	}
	if ("choices_float" in ad) {
		opts.choices = ad.choices_float;
	}
	return arg(ad.name, scalarCarrier(atype), opts);
}

// ---------------------------------------------------------------------------
// Dependencies
// ---------------------------------------------------------------------------
function buildDependency(dd) {
	switch (dd.type) {
		case "co_required":
			return coRequired(dd.flags);
		case "requires":
			return requires({ flag: dd.flag, dependsOn: dd.depends_on });
		case "implies":
			return implies({ flag: dd.flag, implies: dd.implies, value: dd.value });
		default:
			throw new Error(`unknown dependency type: ${dd.type}`);
	}
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

/** All flag defs visible to a command's handler: global + direct + flag sets + mutex. */
function collectAllFlagDefs(cmdDef, globalFlags) {
	const all = [...globalFlags];
	all.push(...(cmdDef.flags ?? []));
	for (const fs of cmdDef.flag_sets ?? []) {
		all.push(...fs.flags);
	}
	for (const mg of cmdDef.mutex ?? []) {
		all.push(...mg.flags);
	}
	return all;
}

function makeHandler(cmdDef, globalFlags) {
	// handler_returns pins an explicit return (survivor-contract cases): the
	// template-printing path is skipped entirely. Kinds mirror ref_python's
	// _emit_handler_return; "bad" returns a non-outcome to trigger the
	// framework's hard error (expressible in TS, unlike Go).
	if ("handler_returns" in cmdDef) {
		const hr = cmdDef.handler_returns;
		const code = hr.code ?? 0;
		return () => {
			switch (hr.kind) {
				case "data":
					return outcome(0, hr.data);
				case "exit_data":
					return outcome(code, hr.data);
				case "exit":
					return code;
				case "none":
					return undefined;
				default:
					return ["not-an-outcome"];
			}
		};
	}

	const template = cmdDef.handler_prints;
	const exitCode = cmdDef.handler_exit_code ?? 0;
	const allFlags = collectAllFlagDefs(cmdDef, globalFlags);
	const argDefs = cmdDef.args ?? [];

	return (args, ctx) => {
		let out = template;

		// {source:name} provenance references resolve via ctx.source().
		for (const fd of allFlags) {
			const sourceKey = `{source:${fd.name}}`;
			if (out.includes(sourceKey)) {
				out = subst(out, sourceKey, ctx.source(fd.name));
			}
		}

		// Flags: values arrive under the underscore key (globals included).
		for (const fd of allFlags) {
			out = subst(out, `{${fd.name}}`, render(args[underscore(fd.name)]));
		}

		// Args: keyed by name as-is.
		for (const ad of argDefs) {
			out = subst(out, `{${ad.name}}`, render(args[ad.name]));
		}

		ctx.info(out);
		return exitCode;
	};
}

function makePassthroughHandler(cmdDef, globalFlags) {
	const exitCode = cmdDef.handler_exit_code ?? 0;
	return (pt, ctx) => {
		// Print global flag values (name=value lines) first.
		for (const gf of globalFlags) {
			ctx.info(`${gf.name}=${render(pt.globals[underscore(gf.name)])}`);
		}
		// Then the passthrough_handler_prints template, or the default format.
		const template = cmdDef.passthrough_handler_prints;
		if (template !== undefined) {
			let out = subst(template, "{name}", pt.name);
			out = subst(out, "{args}", pt.args.join(","));
			ctx.info(out);
		} else {
			ctx.info(`${pt.name}:${pt.args.join(",")}`);
		}
		return exitCode;
	};
}

// ---------------------------------------------------------------------------
// Command / group registration
// ---------------------------------------------------------------------------
function registerCommand(cmdDef, target, globalFlags) {
	const name = cmdDef.name;

	// Deprecated command.
	if (cmdDef.deprecated === true) {
		target.deprecate(deprecated(name, cmdDef.deprecated_message ?? ""));
		return;
	}

	// Passthrough command. The TS factory API makes passthrough-with-parsing
	// declarations inexpressible (passthrough() takes no flags/args/flag
	// sets/mutex), so the framework's registration guard is replayed here
	// with its own catalog message, in the sibling part order.
	if (cmdDef.passthrough === true) {
		const parts = [];
		if ((cmdDef.flags ?? []).length > 0) {
			parts.push("flags");
		}
		if ((cmdDef.args ?? []).length > 0) {
			parts.push("args");
		}
		if ((cmdDef.flag_sets ?? []).length > 0) {
			parts.push("flag sets");
		}
		if ((cmdDef.mutex ?? []).length > 0) {
			parts.push("mutex groups");
		}
		if (parts.length > 0) {
			throw new Error(errCommandPassthroughCannotHave(name, parts.join(", ")));
		}
		const spec = {
			help: cmdDef.help,
			handler: makePassthroughHandler(cmdDef, globalFlags),
		};
		if ("tags" in cmdDef) {
			spec.tags = cmdDef.tags;
		}
		if (cmdDef.hidden === true) {
			spec.hidden = true;
		}
		target.command(passthrough(name, spec));
		return;
	}

	// Normal command.
	const spec = {
		help: cmdDef.help,
		handler: makeHandler(cmdDef, globalFlags),
	};
	if ("args" in cmdDef) {
		spec.args = cmdDef.args.map(buildArg);
	}
	if ("flags" in cmdDef) {
		spec.flags = flagMapOf(cmdDef.flags, (fn) =>
			errCommandDuplicateFlag(name, fn),
		);
	}
	if ("flag_sets" in cmdDef) {
		spec.flagSets = cmdDef.flag_sets.map((fs) =>
			flagSet(
				fs.name,
				flagMapOf(fs.flags, (fn) => errCommandDuplicateFlag(name, fn)),
			),
		);
	}
	if ("mutex" in cmdDef) {
		spec.mutex = cmdDef.mutex.map((mg) =>
			mutexGroup(flagMapOf(mg.flags, (fn) => errCommandDuplicateFlag(name, fn))),
		);
	}
	if ("dependencies" in cmdDef) {
		spec.dependencies = cmdDef.dependencies.map(buildDependency);
	}
	if ("tags" in cmdDef) {
		spec.tags = cmdDef.tags;
	}
	if ("config_fields" in cmdDef) {
		spec.configFields = cmdDef.config_fields;
	}
	if (cmdDef.hidden === true) {
		spec.hidden = true;
	}
	if (cmdDef.interactive === true) {
		spec.interactive = true;
	}
	target.command(defineCommand(name, spec));
}

function buildGroup(groupDef, parent, globalFlags) {
	const spec = { help: groupDef.help };
	if ("tags" in groupDef) {
		spec.tags = groupDef.tags;
	}
	if (groupDef.hidden === true) {
		spec.hidden = true;
	}
	const group = parent.group(groupDef.name, spec);
	for (const c of groupDef.commands ?? []) {
		registerCommand(c, group, globalFlags);
	}
	for (const g of groupDef.groups ?? []) {
		buildGroup(g, group, globalFlags);
	}
}

// ---------------------------------------------------------------------------
// Checks
// ---------------------------------------------------------------------------

/**
 * Replays the case's notes and problems onto the reporter and mints the
 * requested terminal outcome. A warn-form reporter replays every problem as
 * a warn (it structurally lacks error-minting), mirroring mintWarnOutcome.
 */
function mintOutcome(reporter, warnForm, cd) {
	for (const n of cd.notes ?? []) {
		reporter.note(n);
	}
	for (const p of cd.problems ?? []) {
		if (!warnForm && p.severity === "error") {
			reporter.error(p.text);
		} else {
			reporter.warn(p.text);
		}
	}
	switch (cd.mint) {
		case "passed":
			return reporter.passed(cd.message);
		case "skipped":
			return reporter.skipped(cd.message);
		default:
			return reporter.found(cd.message);
	}
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
	const defPath = process.env.CONFORMANCE_APP_DEF;
	if (!defPath) {
		process.stderr.write("CONFORMANCE_APP_DEF environment variable not set\n");
		process.exit(2);
	}

	let raw;
	try {
		raw = readFileSync(defPath, "utf8");
	} catch (e) {
		process.stderr.write(`failed to read app def: ${e.message}\n`);
		process.exit(2);
	}

	let appDef;
	try {
		appDef = JSON.parse(raw);
	} catch (e) {
		process.stderr.write(`failed to parse app def: ${e.message}\n`);
		process.exit(2);
	}

	// Build app spec.
	const spec = {
		name: appDef.name,
		version: appDef.version,
		help: appDef.help,
	};
	if ("env_prefix" in appDef) {
		spec.envPrefix = appDef.env_prefix;
	}
	if (appDef.config === true) {
		spec.config = true;
	}
	if ("config_path" in appDef && appDef.config_path !== null) {
		spec.configPath = appDef.config_path;
	}
	if ("config_format" in appDef && appDef.config_format !== "json") {
		spec.configFormat = appDef.config_format;
	}
	if (
		"config_conflict_mode" in appDef &&
		appDef.config_conflict_mode !== "cli-wins"
	) {
		spec.configConflictMode = appDef.config_conflict_mode;
	}
	if (appDef.no_default_config_path === true) {
		spec.noDefaultConfigPath = true;
	}
	if ("infra_root" in appDef) {
		spec.infraRoot = appDef.infra_root;
	}
	if ("handshake_env" in appDef) {
		spec.handshakeEnv = appDef.handshake_env;
	}
	if ("checks_toml" in appDef) {
		spec.checksEmbed = appDef.checks_toml;
	}
	if (appDef.test_coverage === true) {
		spec.testCoverage = true;
	}

	// Global flags go into the createApp spec (TS has no post-construction
	// global-flag registration; the framework replays the same validations).
	const globalFlags = appDef.global_flags ?? [];
	if (globalFlags.length > 0) {
		spec.flags = flagMapOf(globalFlags, (fn) => errDuplicateGlobalFlag(fn));
	}

	const app = createApp(spec);

	// Register config fields (before commands, since commands may bind to them).
	for (const cfDef of appDef.config_fields_def ?? []) {
		const cfType = cfDef.type ?? "str";
		const cfSpec = { type: scalarCarrier(cfType), help: cfDef.help };
		if ("default" in cfDef) {
			cfSpec.default = convertScalar(cfType, cfDef.default);
		}
		app.configField(cfDef.name, cfSpec);
	}

	// Register groups (recursive), then top-level commands (main.go order).
	for (const g of appDef.groups ?? []) {
		buildGroup(g, app, globalFlags);
	}
	for (const c of appDef.commands ?? []) {
		registerCommand(c, app, globalFlags);
	}

	// Register tag contracts.
	for (const [tag, contract] of Object.entries(appDef.tag_contracts ?? {})) {
		app.tagContract(tag, contract.requires_flag);
	}

	// Register checks. The registration FORM (error vs warn) is derived from
	// the check's declared severity in the embedded checks_toml -- read back
	// from the app's parsed defs (createApp already parsed the TOML), with
	// the Go harness's fallback to error-form for undeclared names so the
	// framework's double-entry cross-check surfaces genuine mismatches.
	if ("checks_toml" in appDef) {
		for (const cd of appDef.checks ?? []) {
			const severity = app.checks?.defs?.get(cd.name)?.severity ?? "error";
			if (severity === "warn") {
				app.warnCheck(cd.name, (_ctx, r) => mintOutcome(r, true, cd));
			} else {
				app.errorCheck(cd.name, (_ctx, r) => mintOutcome(r, false, cd));
			}
		}
	}

	// Register check providers. Each provider is a list of specs carrying the
	// 8 meta fields inline; the builder (errorCheckSpec vs warnCheckSpec) is
	// the spec's impl_form (defaults to its meta severity). Specs are built
	// lazily inside the provider, mirroring main.go.
	for (const specDefs of appDef.providers ?? []) {
		app.registerCheckProvider(() =>
			specDefs.map((sd) => {
				const implForm = sd.impl_form ?? sd.severity;
				const init = {
					name: sd.name,
					tags: sd.tags ?? [],
					severity: sd.severity,
					fast: sd.fast,
					pure: sd.pure,
					needsNetwork: sd.needs_network,
					dependsOn: sd.depends_on ?? [],
					scope: sd.scope ?? "",
				};
				if (implForm === "warn") {
					return warnCheckSpec({
						...init,
						impl: (_ctx, r) => mintOutcome(r, true, sd),
					});
				}
				return errorCheckSpec({
					...init,
					impl: (_ctx, r) => mintOutcome(r, false, sd),
				});
			}),
		);
	}

	if (
		"checks_toml" in appDef ||
		"providers" in appDef ||
		"test_coverage" in appDef
	) {
		app.setCheckContext(() => ({ projectRoot: "." }));
	}

	// Write config_content_late AFTER construction but BEFORE run.
	if ("config_content_late" in appDef) {
		const configPath = appDef.config_path ?? "";
		if (configPath !== "") {
			writeFileSync(configPath, appDef.config_content_late);
		}
	}

	// Pre-test argv lists: run app.test() for each before the main app.run().
	for (const argv of appDef.pre_test ?? []) {
		await app.test(argv);
	}

	await app.run();
}

main().catch((e) => {
	process.stderr.write(`error: ${e instanceof Error ? e.message : e}\n`);
	process.exit(1);
});
