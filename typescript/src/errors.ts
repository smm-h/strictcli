/**
 * errors.ts centralizes every user-facing error/panic message template used
 * across the strictcli package. It mirrors go/strictcli/errors.go one-to-one:
 * same section grouping (headers keep the Go source-file labels for catalog
 * traceability -- conformance/check_error_parity.py extracts the Go catalog
 * from those sections), same "(parse-time)" section markers, and byte-identical
 * output for identical inputs.
 *
 * Conventions:
 * - Go %q slots are reproduced via q() (strconv.Quote semantics).
 * - Slots that embed pre-formatted values (Go %v / %T, and any float) take the
 *   already-formatted string as the parameter, so this module stays
 *   formatting-agnostic (the shortest-canonical float formatter lands in
 *   float.ts in a later subphase).
 * - Go %d slots take number parameters.
 * - Go error-typed parameters become errStr: string (the message text).
 */

/** Thrown for registration-time validation failures (Go: panic / Python: ValueError). */
export class RegistrationError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "RegistrationError";
	}
}

/** Thrown for parse-time failures (printed to stderr, exit 1). */
export class ParseError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "ParseError";
	}
}

/**
 * Thrown by app.call() / app.jsonSchema() when programmatic invocation fails
 * (unknown command, missing required flags, mutex violations, dependency
 * errors). Mirrors Go's InvokeError (invoke.go) and Python's InvokeError.
 */
export class InvokeError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "InvokeError";
	}
}

/**
 * Go strconv.Quote: wrap in double quotes, escape backslash and double quote,
 * use the standard named escapes for ASCII control characters, and \xNN for
 * the rest of the control range. Code points above 0x7f pass through -- Go
 * would escape non-printable Unicode, but every %q slot in this catalog
 * receives ASCII identifiers (flag/check/command names, env vars, modes).
 */
function q(s: string): string {
	let out = '"';
	for (const ch of s) {
		const code = ch.codePointAt(0) as number;
		if (ch === '"' || ch === "\\") {
			out += `\\${ch}`;
		} else if (code >= 0x20 && code !== 0x7f) {
			out += ch;
		} else {
			switch (ch) {
				case "\x07":
					out += "\\a";
					break;
				case "\b":
					out += "\\b";
					break;
				case "\f":
					out += "\\f";
					break;
				case "\n":
					out += "\\n";
					break;
				case "\r":
					out += "\\r";
					break;
				case "\t":
					out += "\\t";
					break;
				case "\x0b":
					out += "\\v";
					break;
				default:
					out += `\\x${code.toString(16).padStart(2, "0")}`;
					break;
			}
		}
	}
	return `${out}"`;
}

// ---------------------------------------------------------------------------
// strictcli.go — type constructors (ListOf, DictOf)
// ---------------------------------------------------------------------------

export function errListOfBadItemType(itemType: number): string {
	return `ListOf: item type must be str, int, or float, got ${itemType}`;
}

export function errDictOfBadValueType(valueType: number): string {
	return `DictOf: value type must be str, int, or float, got ${valueType}`;
}

// ---------------------------------------------------------------------------
// strictcli.go — option constructors (WithConfigConflictMode, etc.)
// ---------------------------------------------------------------------------

export function errWithConfigConflictModeBadMode(mode: string): string {
	return `WithConfigConflictMode: mode must be "cli-wins" or "error", got ${q(mode)}`;
}

export function errHandshakeEnvVarEmptyHelp(envVar: string): string {
	return `handshake env var ${q(envVar)}: help must be a non-empty string`;
}

export function errDuplicateHandshakeEnvVar(envVar: string): string {
	return `duplicate handshake env var ${q(envVar)}`;
}

export function errConflictModeBadMode(mode: string): string {
	return `ConflictMode: mode must be "cli-wins" or "error", got ${q(mode)}`;
}

// ---------------------------------------------------------------------------
// strictcli.go — tag validation
// ---------------------------------------------------------------------------

export function errInvalidTagName(t: string): string {
	return `invalid tag name ${q(t)}: must match [a-z][a-z0-9-]*`;
}

// ---------------------------------------------------------------------------
// strictcli.go — NewArg validation
// ---------------------------------------------------------------------------

export function errArgHelpEmpty(): string {
	return "Arg.help must be a non-empty string";
}

export function errRequiredArgCannotHaveDefault(): string {
	return "required arg cannot have a default";
}

export function errArgListTypeRequiresVariadic(name: string): string {
	return `Arg ${q(name)}: list type requires variadic=true`;
}

export function errArgListItemTypeBad(name: string): string {
	return `Arg ${q(name)}: list item type must be str, int, or float`;
}

export function errArgDictTypeNotSupported(name: string): string {
	return `Arg ${q(name)}: dict type is not supported on positional arguments`;
}

export function errArgTypeBad(t: number): string {
	return `Arg.type must be str, bool, int, or float, got ${t}`;
}

export function errArgChoicesIncompatibleListType(name: string): string {
	return `Arg ${q(name)}: choices is incompatible with list type`;
}

export function errArgChoicesIncompatibleBool(name: string): string {
	return `Arg ${q(name)}: choices is incompatible with type=bool`;
}

export function errArgChoicesEmpty(name: string): string {
	return `Arg ${q(name)}: choices must be a non-empty list`;
}

export function errArgChoiceTypeMismatch(
	name: string,
	c: string,
	typeName: string,
): string {
	return `Arg ${q(name)}: choice ${c} is not of type ${typeName}`;
}

export function errArgListDefaultMustBeList(name: string): string {
	return `Arg ${q(name)}: list arg default must be a list`;
}

export function errArgExplicitEmptyDefaultRedundantList(name: string): string {
	return `Arg ${q(name)}: explicit empty default is redundant for list args, omit the default`;
}

export function errArgDefaultElementTypeMismatch(
	name: string,
	i: number,
	typeName: string,
): string {
	return `Arg ${q(name)}: default element ${i} is not of type ${typeName}`;
}

export function errArgStrDefaultTypeMismatch(
	name: string,
	gotType: string,
): string {
	return `Arg ${q(name)}: type=str requires a str default, got '${gotType}'`;
}

export function errArgIntDefaultTypeMismatch(
	name: string,
	gotType: string,
): string {
	return `Arg ${q(name)}: type=int requires an int default, got '${gotType}'`;
}

export function errArgFloatDefaultTypeMismatch(
	name: string,
	gotType: string,
): string {
	return `Arg ${q(name)}: type=float requires a float default, got '${gotType}'`;
}

export function errArgBoolDefaultTypeMismatch(
	name: string,
	gotType: string,
): string {
	return `Arg ${q(name)}: type=bool requires a bool default, got '${gotType}'`;
}

export function errArgDefaultNotInChoices(
	name: string,
	dflt: string,
	choicesStr: string,
): string {
	return `Arg ${q(name)}: default '${dflt}' is not in choices [${choicesStr}]`;
}

// ---------------------------------------------------------------------------
// strictcli.go — validateFlagConfig
// ---------------------------------------------------------------------------

export function errFlagHelpEmpty(): string {
	return "Flag.help must be a non-empty string";
}

export function errFlagForceReserved(): string {
	return "flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'";
}

export function errFlagNoPrefixReserved(name: string): string {
	return `flag '${name}': names starting with 'no-' are reserved for the negation system; use a positive name instead`;
}

export function errFlagRepeatableIncompatibleBool(name: string): string {
	return `Flag ${q(name)}: repeatable is incompatible with type=bool`;
}

export function errFlagChoicesIncompatibleCompound(name: string): string {
	return `Flag ${q(name)}: choices is incompatible with compound types (list/dict)`;
}

export function errFlagRepeatableRequiresExplicitUnique(name: string): string {
	return `Flag ${q(name)}: repeatable requires explicit unique (unique=True or unique=False)`;
}

export function errFlagUniqueRequiresRepeatable(name: string): string {
	return `Flag ${q(name)}: unique requires repeatable=True`;
}

export function errFlagEnvSeparatorRequiresRepeatable(name: string): string {
	return `Flag ${q(name)}: env_separator requires repeatable=True`;
}

export function errFlagEnvSeparatorRequiresEnv(name: string): string {
	return `Flag ${q(name)}: env_separator requires env`;
}

export function errFlagRepeatableEnvRequiresSeparator(name: string): string {
	return `Flag ${q(name)}: repeatable flag with env requires env_separator`;
}

export function errFlagEnvSeparatorSingleChar(name: string): string {
	return `Flag ${q(name)}: env_separator must be a single character`;
}

export function errFlagEnvSeparatorBackslash(name: string): string {
	return `Flag ${q(name)}: env_separator cannot be a backslash`;
}

export function errFlagChoicesIncompatibleBool(name: string): string {
	return `Flag ${q(name)}: choices is incompatible with type=bool`;
}

export function errFlagChoicesEmpty(name: string): string {
	return `Flag ${q(name)}: choices must be a non-empty list`;
}

export function errFlagChoiceTypeMismatch(
	name: string,
	c: string,
	typeName: string,
): string {
	return `Flag ${q(name)}: choice ${c} is not of type ${typeName}`;
}

export function errFlagIntDefaultTypeMismatch(
	name: string,
	gotType: string,
): string {
	return `Flag ${q(name)}: type=int requires an int default, got '${gotType}'`;
}

export function errFlagFloatDefaultTypeMismatch(
	name: string,
	gotType: string,
): string {
	return `Flag ${q(name)}: type=float requires a float default, got '${gotType}'`;
}

export function errFlagDictDefaultMustBeMap(name: string): string {
	return `Flag ${q(name)}: dict flag default must be a map[string]interface{}`;
}

export function errFlagExplicitEmptyDefaultRedundantDict(name: string): string {
	return `Flag ${q(name)}: explicit empty default is redundant for dict flags, omit the default`;
}

export function errFlagDefaultValueForKey(
	name: string,
	k: string,
	errStr: string,
): string {
	return `Flag ${q(name)}: default value for key ${q(k)}: ${errStr}`;
}

export function errFlagListDefaultMustBeSlice(name: string): string {
	return `Flag ${q(name)}: list flag default must be a []interface{}`;
}

export function errFlagExplicitEmptyDefaultRedundantList(name: string): string {
	return `Flag ${q(name)}: explicit empty default is redundant for list flags, omit the default`;
}

export function errFlagDefaultElementError(
	name: string,
	i: number,
	errStr: string,
): string {
	return `Flag ${q(name)}: default element ${i}: ${errStr}`;
}

export function errFlagRepeatableDefaultMustBeList(name: string): string {
	return `Flag ${q(name)}: repeatable flag default must be a list`;
}

export function errFlagExplicitEmptyDefaultRedundantRepeatable(
	name: string,
): string {
	return `Flag ${q(name)}: explicit empty default is redundant for repeatable flags, omit the default`;
}

export function errFlagDefaultElementTypeMismatch(
	name: string,
	i: number,
	typeName: string,
): string {
	return `Flag ${q(name)}: default element ${i} is not of type ${typeName}`;
}

export function errFlagDefaultNotInChoices(
	name: string,
	dflt: string,
	choicesStr: string,
): string {
	return `Flag ${q(name)}: default '${dflt}' is not in choices [${choicesStr}]`;
}

// ---------------------------------------------------------------------------
// strictcli.go — NewApp
// ---------------------------------------------------------------------------

export function errAppHelpEmpty(): string {
	return "App.help must be a non-empty string";
}

export function errDuplicateInfraRootEnvVar(envVar: string): string {
	return `duplicate infra root env var ${q(envVar)}`;
}

export function errHandshakeIsAlreadyInfraRoot(ev: string): string {
	return `handshake env var ${q(ev)} is already declared as an infra root`;
}

export function errCannotUseBothChecksAndEmbed(): string {
	return "cannot use both WithChecks and WithChecksEmbed";
}

export function errChecksPathNotExist(path: string): string {
	return `checks_path does not exist: ${path}`;
}

export function errChecksTomlAppMismatch(
	appName: string,
	expected: string,
): string {
	return `checks.toml: app ${q(appName)} does not match app name ${q(expected)}`;
}

export function errTestCoverageCannotCreateDir(errStr: string): string {
	return `test-coverage: cannot create .strictcli/coverage/: ${errStr}`;
}

// ---------------------------------------------------------------------------
// strictcli.go — check registration
// ---------------------------------------------------------------------------

export function errCannotRegisterCheckNotEnabled(name: string): string {
	return `cannot register check ${q(name)}: checks not enabled`;
}

export function errCannotRegisterCheckNotDeclared(name: string): string {
	return `cannot register check ${q(name)}: not declared in checks.toml`;
}

export function errCheckDuplicateRegistration(name: string): string {
	return `check ${q(name)}: duplicate registration`;
}

export function errCheckSeverityMismatch(
	name: string,
	severity: string,
	used: string,
	want: string,
): string {
	return `check ${q(name)}: declared severity ${q(severity)} in checks.toml but registered via ${used}; use ${want}`;
}

// ---------------------------------------------------------------------------
// strictcli.go — TagContract
// ---------------------------------------------------------------------------

// errInvalidTagName is reused from the tag validation section above.

export function errTagContractViolation(
	cmdName: string,
	tag: string,
	requiredFlag: string,
): string {
	return `command ${q(cmdName)}: tag ${q(tag)} requires flag "--${requiredFlag}"`;
}

// ---------------------------------------------------------------------------
// strictcli.go — validateConfigFieldBindings
// ---------------------------------------------------------------------------

export function errCommandConfigFieldsUnknownField(
	cmdName: string,
	field: string,
): string {
	return `command ${q(cmdName)}: config_fields references unknown config field ${q(field)}`;
}

// ---------------------------------------------------------------------------
// strictcli.go — checkFlagConfigFieldDefault
// ---------------------------------------------------------------------------

export function errConfigFieldFlagDefaultDisagree(
	cfName: string,
	flagName: string,
	cfDefault: string,
	flagDefault: string,
): string {
	return `config field ${q(cfName)} collides with flag ${q(flagName)} but their defaults disagree (${cfDefault} vs ${flagDefault}); remove one default or make them equal`;
}

// ---------------------------------------------------------------------------
// strictcli.go — resolveInfraRootPath
// ---------------------------------------------------------------------------

export function errRelativeToRootUndeclared(envVar: string): string {
	return `RelativeToRoot references undeclared infra root ${q(envVar)}; declare it as an infra root`;
}

// ---------------------------------------------------------------------------
// strictcli.go — validateFlagInfraMarker
// ---------------------------------------------------------------------------

export function errFlagRelativeToRootUndeclared(
	flagName: string,
	envVar: string,
): string {
	return `flag ${q(flagName)}: RelativeToRoot references undeclared infra root ${q(envVar)}; declare it as an infra root`;
}

// The command-scoped variant mirrors Python's _build_and_validate_command
// message (the divergence ground truth). Go has no command-context marker
// validation -- it validates per-flag -- so this template has no errors.go
// counterpart (see check_error_parity.py, "InfraEnv structural" exclusions).
export function errCommandFlagRelativeToRootUndeclared(
	cmdName: string,
	flagName: string,
	envVar: string,
): string {
	return `command ${q(cmdName)}: flag ${q(flagName)}: RelativeToRoot references undeclared infra root ${q(envVar)}; declare it as an infra root`;
}

// ---------------------------------------------------------------------------
// strictcli.go — command registration
// ---------------------------------------------------------------------------

export function errCommandMissingHelp(name: string): string {
	return `command ${q(name)}: missing help text`;
}

export function errCommandPassthroughCannotHave(
	name: string,
	parts: string,
): string {
	return `command ${q(name)}: passthrough commands cannot have ${parts}`;
}

export function errGlobalFlagNameReserved(name: string): string {
	return `global flag name ${q(name)} is reserved`;
}

export function errGlobalShortFlagReserved(short: string): string {
	return `global short flag ${q(short)} is reserved`;
}

export function errDuplicateGlobalFlag(name: string): string {
	return `duplicate global flag name ${q(name)}`;
}

export function errGroupHelpEmpty(): string {
	return "Group.help must be a non-empty string";
}

export function errGroupCollidesWithCommand(name: string): string {
	return `group ${q(name)} collides with an existing command`;
}

export function errGroupAlreadyRegistered(name: string): string {
	return `group ${q(name)} is already registered`;
}

export function errCommandCollidesWithGroup(name: string): string {
	return `command ${q(name)} collides with an existing group`;
}

export function errDeprecatedNameEmpty(): string {
	return "deprecated command name must be a non-empty string";
}

export function errDeprecatedMessageEmpty(name: string): string {
	return `deprecated command ${q(name)}: message must not be empty`;
}

export function errDeprecatedCollidesCommand(name: string): string {
	return `deprecated command ${q(name)} collides with an existing command`;
}

export function errDeprecatedCollidesGroup(name: string): string {
	return `deprecated command ${q(name)} collides with an existing group`;
}

export function errDeprecatedAlreadyRegistered(name: string): string {
	return `deprecated command ${q(name)} is already registered`;
}

// ---------------------------------------------------------------------------
// strictcli.go — buildAndValidateCommand
// ---------------------------------------------------------------------------

export function errCommandMutexMinFlags(name: string, count: number): string {
	return `command ${q(name)}: mutex group must have at least 2 flags, got ${count}`;
}

export function errCommandFlagInMultipleMutex(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: flag ${q(flagName)} appears in multiple mutex groups`;
}

export function errCommandFlagCollidesGlobal(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: flag ${q(flagName)} collides with a global flag`;
}

export function errCommandDuplicateFlag(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: duplicate flag name ${q(flagName)}`;
}

export function errCommandDuplicateArg(name: string, argName: string): string {
	return `command ${q(name)}: duplicate arg name ${q(argName)}`;
}

export function errCommandAtMostOneVariadic(name: string): string {
	return `command ${q(name)}: at most one variadic arg is allowed`;
}

export function errCommandVariadicMustBeLast(
	name: string,
	argName: string,
): string {
	return `command ${q(name)}: variadic arg ${q(argName)} must be the last arg`;
}

export function errCommandFlagMissingHelp(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: flag ${q(flagName)} missing help text`;
}

export function errCommandEnvVarPrefix(
	name: string,
	envVar: string,
	flagName: string,
	expectedPrefix: string,
): string {
	return `command ${q(name)}: env var ${q(envVar)} for flag ${q(flagName)} must start with ${q(expectedPrefix)} (or set prefixed=false)`;
}

export function errCommandCoRequiredMinFlags(
	name: string,
	count: number,
): string {
	return `command ${q(name)}: CoRequired must have at least 2 flags, got ${count}`;
}

export function errCommandCoRequiredUnknownFlag(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: CoRequired references unknown flag ${q(flagName)}`;
}

export function errCommandCoRequiredDuplicate(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: CoRequired has duplicate flag ${q(flagName)}`;
}

export function errCommandRequiresSameFlag(name: string, flag: string): string {
	return `command ${q(name)}: Requires flag and depends_on cannot be the same (${q(flag)})`;
}

export function errCommandRequiresUnknownFlag(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: Requires references unknown flag ${q(flagName)}`;
}

export function errCommandImpliesSameFlag(name: string, flag: string): string {
	return `command ${q(name)}: Implies flag and implies cannot be the same (${q(flag)})`;
}

export function errCommandImpliesUnknownFlag(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: Implies references unknown flag ${q(flagName)}`;
}

export function errCommandImpliesTriggerNotBool(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: Implies trigger flag ${q(flagName)} must be a bool flag`;
}

export function errCommandImpliesTargetNotBool(
	name: string,
	flagName: string,
): string {
	return `command ${q(name)}: Implies target flag ${q(flagName)} must be a bool flag`;
}

// ---------------------------------------------------------------------------
// strictcli.go — validateScalarType (parse-time)
// ---------------------------------------------------------------------------

export function errExpectedStrGot(typeDesc: string): string {
	return `expected str, got ${typeDesc}`;
}

export function errExpectedIntGot(typeDesc: string): string {
	return `expected int, got ${typeDesc}`;
}

export function errExpectedFloatGot(typeDesc: string): string {
	return `expected float, got ${typeDesc}`;
}

export function errExpectedBoolGot(typeDesc: string): string {
	return `expected bool, got ${typeDesc}`;
}

// ---------------------------------------------------------------------------
// strictcli.go — doParse hermetic mode (parse-time)
// ---------------------------------------------------------------------------

export function errHermeticConfigMutuallyExclusive(): string {
	return "--hermetic and --config are mutually exclusive";
}

export function errHermeticWithConfigCommands(): string {
	return "--hermetic cannot be used with config commands";
}

// ---------------------------------------------------------------------------
// parse.go — strict parsing
// ---------------------------------------------------------------------------

export function errExpectedBoolean(s: string): string {
	return `expected boolean, got '${s}'`;
}

export function errExpectedInteger(s: string): string {
	return `expected integer, got '${s}'`;
}

export function errExpectedFloat(s: string): string {
	return `expected float, got '${s}'`;
}

export function errNaNNotAllowed(): string {
	return "NaN is not allowed";
}

export function errInfNotAllowed(): string {
	return "Inf is not allowed";
}

// ---------------------------------------------------------------------------
// parse.go — resolveAtPrefix @-prefix resolution (parse-time)
// ---------------------------------------------------------------------------

export function errAtPrefixStdinOnce(flagName: string): string {
	return `--${flagName}: stdin (@-) can only be used once per invocation`;
}

export function errAtPrefixCannotReadStdin(flagName: string): string {
	return `--${flagName}: cannot read stdin`;
}

export function errAtPrefixFileTooLarge(flagName: string): string {
	return `--${flagName}: file exceeds 1 MB limit`;
}

export function errAtPrefixFileNotFound(
	flagName: string,
	path: string,
): string {
	return `--${flagName}: file not found: ${path}`;
}

export function errAtPrefixCannotReadFile(
	flagName: string,
	path: string,
): string {
	return `--${flagName}: cannot read file: ${path}`;
}

// ---------------------------------------------------------------------------
// parse.go / strictcli.go — flag token parsing (parse-time)
// (parseCommand and extractGlobalFlags share these templates)
// ---------------------------------------------------------------------------

export function errBoolFlagNoValue(flagPart: string): string {
	return `flag '${flagPart}' is a boolean flag and does not take a value`;
}

export function errBoolNegationNoValue(flagPart: string): string {
	return `flag '${flagPart}' is a boolean negation and does not take a value`;
}

export function errUnknownFlag(tok: string): string {
	return `unknown flag '${tok}'`;
}

export function errFlagRequiresValue(tok: string): string {
	return `flag '${tok}' requires a value`;
}

export function errFlagDuplicateValue(flagName: string, value: string): string {
	return `--${flagName}: duplicate value '${value}'`;
}

// ---------------------------------------------------------------------------
// parse.go / strictcli.go — env var resolution (parse-time)
// (parseCommand and extractGlobalFlags share these templates)
// ---------------------------------------------------------------------------

export function errWrappedFromEnvVar(errStr: string, envVar: string): string {
	return `${errStr} (from env var '${envVar}')`;
}

export function errListFlagEnvRequiresSeparator(flagName: string): string {
	return `--${flagName}: list flag with env requires env_separator`;
}

export function errFlagDuplicateValueFromEnv(
	flagName: string,
	value: string,
	envVar: string,
): string {
	return `--${flagName}: duplicate value '${value}' (from env var '${envVar}')`;
}

export function errInvalidBoolEnvValue(
	envVal: string,
	envVar: string,
	flagName: string,
): string {
	return `invalid boolean value '${envVal}' for env var '${envVar}' (flag '--${flagName}')`;
}

export function errFlagErrFromEnvVar(
	flagName: string,
	errStr: string,
	envVar: string,
): string {
	return `--${flagName}: ${errStr} (from env var '${envVar}')`;
}

// ---------------------------------------------------------------------------
// parse.go / strictcli.go — config value resolution (parse-time)
// (parseCommand and extractGlobalFlags share these templates)
// ---------------------------------------------------------------------------

export function errConfigValueError(flagName: string, errStr: string): string {
	return `--${flagName}: config value error: ${errStr}`;
}

export function errFlagSetInBothAndConfig(
	flagName: string,
	existingSource: string,
): string {
	return `flag '${flagName}' set in both ${existingSource} and config; remove one`;
}

export function errConfigValueDuplicate(
	flagName: string,
	value: string,
): string {
	return `--${flagName}: config value error: duplicate value '${value}'`;
}

export function errFlagSetInBothCliAndConfig(flagName: string): string {
	return `flag '${flagName}' set in both cli and config; remove one`;
}

// ---------------------------------------------------------------------------
// parse.go — validateAndBuildKwargs (parse-time)
// (mutex, dependencies, custom validation, positional args)
// ---------------------------------------------------------------------------

export function errMutuallyExclusive(setFlags: string): string {
	return `${setFlags} are mutually exclusive`;
}

export function errOneOfRequired(names: string): string {
	return `one of ${names} is required`;
}

export function errImpliesConflict(
	flag: string,
	neg: string,
	target: string,
	explicitNeg: string,
): string {
	return `flag '--${flag}' implies '--${neg}${target}', but '--${explicitNeg}${target}' was explicitly provided`;
}

export function errFlagsMustBeUsedTogether(names: string): string {
	return `flags ${names} must be used together`;
}

export function errFlagRequiresFlag(flag: string, dependsOn: string): string {
	return `flag '--${flag}' requires '--${dependsOn}'`;
}

export function errFlagValueError(flagName: string, msg: string): string {
	return `--${flagName}: ${msg}`;
}

export function errMissingRequiredArgument(name: string): string {
	return `missing required argument '${name}'`;
}

export function errUnexpectedArgument(value: string): string {
	return `unexpected argument '${value}'`;
}

// ---------------------------------------------------------------------------
// parse.go — validateChoices (parse-time)
// ---------------------------------------------------------------------------

export function errArgInvalidChoice(
	name: string,
	value: string,
	choices: string,
): string {
	return `argument '${name}': invalid value '${value}', must be one of: ${choices}`;
}

export function errFlagInvalidChoice(
	name: string,
	value: string,
	choices: string,
): string {
	return `--${name}: invalid value '${value}', must be one of: ${choices}`;
}

// ---------------------------------------------------------------------------
// config.go — ConfigField registration
// ---------------------------------------------------------------------------

export function errConfigFieldNameInvalid(name: string): string {
	return `ConfigField name ${q(name)} is invalid: must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)`;
}

export function errConfigFieldNameReserved(name: string): string {
	return `config field name ${q(name)} is reserved: names starting with underscore are reserved for framework fields`;
}

export function errConfigFieldHelpRequired(name: string): string {
	return `config field ${q(name)}: help text is required`;
}

export function errConfigFieldTypeBad(t: number | string): string {
	return `ConfigField.type must be str, bool, int, or float, got ${t}`;
}

export function errDuplicateConfigField(name: string): string {
	return `duplicate config field name ${q(name)}`;
}

export function errConfigFieldConflictsFramework(name: string): string {
	return `config field name ${q(name)} conflicts with framework field`;
}

// ---------------------------------------------------------------------------
// config.go — framework field registration
// ---------------------------------------------------------------------------

export function errFrameworkFieldMustStartUnderscore(name: string): string {
	return `framework field name ${q(name)} must start with underscore`;
}

export function errFrameworkFieldNameInvalid(name: string): string {
	return `framework field ${q(name)}: invalid name, must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)`;
}

export function errFrameworkFieldHelpRequired(name: string): string {
	return `framework field ${q(name)}: help text is required`;
}

export function errDuplicateFrameworkField(name: string): string {
	return `duplicate framework field name ${q(name)}`;
}

export function errFrameworkFieldConflictsUser(name: string): string {
	return `framework field name ${q(name)} conflicts with user config field`;
}

// ---------------------------------------------------------------------------
// config.go — validateConfigFieldDefault
// ---------------------------------------------------------------------------

export function errConfigFieldDefaultMismatch(
	name: string,
	value: string,
	typeName: string,
): string {
	return `ConfigField ${q(name)}: default value ${value} does not match type ${typeName}`;
}

// ---------------------------------------------------------------------------
// config.go — coerceConfigScalarLong (long type names)
// (the float branch reuses errExpectedFloatGot from the validateScalarType
// section above)
// ---------------------------------------------------------------------------

export function errConfigExpectedBooleanGot(typeDesc: string): string {
	return `expected boolean, got ${typeDesc}`;
}

export function errConfigExpectedIntegerGotFloat(): string {
	return "expected integer, got float";
}

export function errConfigExpectedIntegerGot(typeDesc: string): string {
	return `expected integer, got ${typeDesc}`;
}

export function errConfigExpectedStringGot(typeDesc: string): string {
	return `expected string, got ${typeDesc}`;
}

export function errConfigUnsupportedFlagType(t: number): string {
	return `unsupported flag type ${t}`;
}

// ---------------------------------------------------------------------------
// config.go — coerceConfigScalarShort (short type names)
// (the bool/int/float/str branches reuse errExpectedBoolGot, errExpectedIntGot,
// errExpectedFloatGot, and errExpectedStrGot from the validateScalarType
// section above; the unsupported-type branch reuses errConfigUnsupportedFlagType)
// ---------------------------------------------------------------------------

export function errConfigExpectedIntGotFloat(): string {
	return "expected int, got float";
}

// ---------------------------------------------------------------------------
// config.go — coerceConfigValue (compound config value coercion)
// ---------------------------------------------------------------------------

export function errConfigExpectedObjectForDictFlag(typeDesc: string): string {
	return `expected object for dict flag, got ${typeDesc}`;
}

export function errConfigDictKeyTypeMismatch(
	k: string,
	wantType: string,
	gotType: string,
): string {
	// Divergence: Go spells the key %q (double quotes), Python '{k}' (single).
	// Python is the divergence ground truth.
	return `key '${k}': expected ${wantType}, got ${gotType}`;
}

export function errConfigExpectedArrayForListFlag(typeDesc: string): string {
	return `expected array for list flag, got ${typeDesc}`;
}

export function errConfigElementTypeMismatch(
	i: number,
	wantType: string,
	gotType: string,
): string {
	return `element ${i}: expected ${wantType}, got ${gotType}`;
}

export function errConfigExpectedScalarGotArray(): string {
	return "expected scalar, got array";
}

export function errConfigExpectedArrayForRepeatableFlag(
	typeDesc: string,
): string {
	return `expected array for repeatable flag, got ${typeDesc}`;
}

// ---------------------------------------------------------------------------
// routing.go — resolveCommand (parse-time)
// ---------------------------------------------------------------------------

export function errCommandDeprecated(token: string, msg: string): string {
	return `command '${token}' is deprecated: ${msg}`;
}

export function errUnknownCommandInGroup(
	token: string,
	groupPath: string,
): string {
	return `unknown command '${token}' in '${groupPath}'`;
}

export function errUnknownCommand(token: string): string {
	return `unknown command '${token}'`;
}

export function errNoCommandSpecified(): string {
	return "no command specified";
}

// ---------------------------------------------------------------------------
// invoke.go — invoke (parse-time)
// ---------------------------------------------------------------------------

export function errPassthroughArgsNotStringSlice(): string {
	return "passthrough command: _args must be []string";
}

export function errUnknownParameterForPassthroughCommand(
	key: string,
	commandPath: string,
): string {
	return `unknown parameter ${q(key)} for passthrough command ${q(commandPath)}`;
}

export function errUnknownParameterForCommand(
	paramName: string,
	commandPath: string,
): string {
	return `unknown parameter ${q(paramName)} for command ${q(commandPath)}`;
}

/**
 * Python divergence (the ground truth for call()): a path that resolves to a
 * group raises "'path' is a group, not a command" (Go says "no command
 * resolved from path: <path>"; no conformance case distinguishes them).
 */
export function errCallPathIsGroup(commandPath: string): string {
	return `'${commandPath}' is a group, not a command`;
}

// ---------------------------------------------------------------------------
// invoke.go — coerceInvokeDict
// ---------------------------------------------------------------------------

export function errDictFlagExpectedMapType(
	name: string,
	gotType: string,
): string {
	return `dict flag ${q(name)}: expected map type, got ${gotType}`;
}

// ---------------------------------------------------------------------------
// check.go — reporter methods
// ---------------------------------------------------------------------------

export function errNoteTextEmpty(): string {
	return "note text must be a non-empty string";
}

export function errProblemTextEmpty(): string {
	return "problem text must be a non-empty string";
}

export function errOutcomeMessageEmpty(): string {
	return "outcome message must be a non-empty string";
}

export function errPassedWithProblems(): string {
	return "problems were reported; a check that found problems cannot pass -- use found instead";
}

export function errSkipReasonEmpty(): string {
	return "skip reason must be a non-empty string";
}

export function errSkippedWithProblems(): string {
	return "problems were reported; a check that found problems cannot skip";
}

export function errFoundNoProblems(): string {
	return "no problems were reported; nothing found means pass -- use passed instead";
}

// ---------------------------------------------------------------------------
// checks/framework.ts — outcome mint guard (Python _CheckOutcome.__post_init__)
//
// Go seals CheckOutcome structurally (unexported fields); Python guards the
// constructor with a module-private mint token and raises TypeError. TS uses
// the token approach, so it needs Python's guard message (with the class name
// unprefixed, matching the public TS surface).
// ---------------------------------------------------------------------------

export function errCheckOutcomeDirectConstruction(): string {
	return "CheckOutcome cannot be constructed directly; obtain one from a reporter (passed/skipped/found)";
}

// ---------------------------------------------------------------------------
// check.go — deriveStatus
// ---------------------------------------------------------------------------

export function errUnknownCheckOutcomeKind(kind: string): string {
	return `unknown check outcome kind ${q(kind)}`;
}

// ---------------------------------------------------------------------------
// check.go — addCheckDef
// ---------------------------------------------------------------------------

export function errDuplicateCheckDef(name: string): string {
	return `duplicate check definition ${q(name)}`;
}

// ---------------------------------------------------------------------------
// check.go — parseChecksToml
// ---------------------------------------------------------------------------

export function errChecksTomlParse(errStr: string): string {
	return `checks.toml: ${errStr}`;
}

export function errChecksTomlUnknownTopLevelKey(key: string): string {
	return `checks.toml: unknown top-level key ${q(key)}`;
}

export function errChecksTomlMissingApp(): string {
	return 'checks.toml: missing required top-level key "app"';
}

export function errChecksTomlAppNotString(): string {
	return 'checks.toml: "app" must be a non-empty string';
}

export function errChecksTomlChecksMustBeTable(): string {
	return "checks.toml: [checks] must be a table";
}

export function errChecksTomlInvalidCheckName(name: string): string {
	return `checks.toml: invalid check name ${q(name)} (must match [a-z][a-z0-9-]*)`;
}

export function errChecksTomlCheckMustBeTable(name: string): string {
	return `checks.toml: check ${q(name)} must be a table`;
}

export function errChecksTomlUnknownField(name: string, field: string): string {
	return `checks.toml: check ${q(name)}: unknown field ${q(field)}`;
}

export function errChecksTomlMissingField(name: string, field: string): string {
	return `checks.toml: check ${q(name)}: missing required field ${q(field)}`;
}

export function errChecksTomlTagsMustBeStrings(name: string): string {
	return `checks.toml: check ${q(name)}: "tags" must be a list of strings`;
}

export function errChecksTomlTagsEntriesMustBeStrings(name: string): string {
	return `checks.toml: check ${q(name)}: "tags" entries must be non-empty strings`;
}

export function errChecksTomlSeverityInvalid(
	name: string,
	raw: string,
): string {
	return `checks.toml: check ${q(name)}: "severity" must be "error" or "warn", got ${q(raw)}`;
}

export function errChecksTomlBoolFieldInvalid(
	name: string,
	field: string,
	typeDesc: string,
): string {
	return `checks.toml: check ${q(name)}: ${q(field)} must be a boolean, got ${typeDesc}`;
}

export function errChecksTomlDependsOnMustBeStrings(name: string): string {
	return `checks.toml: check ${q(name)}: "depends_on" must be a list of strings`;
}

export function errChecksTomlDependsOnEntriesMustBeStrings(
	name: string,
): string {
	return `checks.toml: check ${q(name)}: "depends_on" entries must be strings`;
}

export function errChecksTomlScopeMustBeString(
	name: string,
	typeDesc: string,
): string {
	return `checks.toml: check ${q(name)}: "scope" must be a string, got ${typeDesc}`;
}

export function errChecksTomlDependsOnUnknown(
	name: string,
	dep: string,
): string {
	return `checks.toml: check ${q(name)}: depends_on references unknown check ${q(dep)}`;
}

// ---------------------------------------------------------------------------
// check_runner.go
// ---------------------------------------------------------------------------

export function errCheckDependencyCycleInvolving(name: string): string {
	return `check dependency cycle detected involving ${q(name)}`;
}

export function errCheckDependencyCycle(cyclePath: string): string {
	return `check dependency cycle: ${cyclePath}`;
}

export function errCheckDependencyCycleDetected(): string {
	return "check dependency cycle detected";
}

export function errCheckOutcomeNotMinted(name: string): string {
	return `check ${q(name)} returned an outcome not minted by its reporter; use reporter methods (Passed/Skipped/Found)`;
}

export function errInvalidGlobPattern(pattern: string, errStr: string): string {
	return `invalid glob pattern ${q(pattern)}: ${errStr}`;
}

// ---------------------------------------------------------------------------
// check_provider.go
// ---------------------------------------------------------------------------

export function errCheckProviderSeverityMismatch(
	name: string,
	severity: string,
	used: string,
	want: string,
): string {
	return `check ${q(name)}: declared severity ${q(severity)} but registered via ${used}; use ${want}`;
}

// ---------------------------------------------------------------------------
// check_public.go
// ---------------------------------------------------------------------------

export function errChecksNotEnabled(): string {
	return "checks are not enabled on this App";
}

// ---------------------------------------------------------------------------
// schema.go
// ---------------------------------------------------------------------------

// The three project_id templates mirror Go's decomposition (not found / read
// error / no identifying directive) with the TS ecosystem project file:
// package.json "name" is the analog of Go's go.mod module path and Python's
// pyproject.toml [project].name. Each language names its own file here (the
// parity checker excludes these as language-specific).

export function errCannotDetermineProjectIDNoPackageJson(): string {
	return "Cannot determine project_id: package.json not found";
}

export function errCannotDetermineProjectIDReadError(errStr: string): string {
	return `Cannot determine project_id: error reading package.json: ${errStr}`;
}

export function errCannotDetermineProjectIDNoName(): string {
	return "Cannot determine project_id: no name field in package.json";
}

export function errSchemaMismatch(existingID: string, newID: string): string {
	return `Schema mismatch: existing schema belongs to project '${existingID}', not '${newID}'. Run from the correct project directory.`;
}

// ---------------------------------------------------------------------------
// tagdsl.go
// ---------------------------------------------------------------------------

export function errTagExprUnexpectedChar(ch: string, pos: number): string {
	return `tag expression: unexpected character ${q(ch)} at position ${pos}`;
}

export function errTagExprEmpty(): string {
	return "tag expression: empty expression";
}

export function errTagExprUnexpectedToken(val: string, pos: number): string {
	return `tag expression: unexpected token ${q(val)} at position ${pos}`;
}

export function errTagExprUnexpectedEnd(pos: number): string {
	return `tag expression: unexpected end of expression at position ${pos}`;
}

export function errTagExprExpectedRParen(pos: number): string {
	return `tag expression: expected ")" at position ${pos}`;
}

// ---------------------------------------------------------------------------
// context.go
// ---------------------------------------------------------------------------

export function errInfraValueUndeclared(envVar: string): string {
	return `InfraValue: ${q(envVar)} is not a declared infra root or handshake env var`;
}

export function errNoSourceInfo(name: string): string {
	return `no source info for flag ${q(name)}`;
}

// ---------------------------------------------------------------------------
// outcome.go / Python _interpret_handler_return
// ---------------------------------------------------------------------------

// Python's template with the permitted types renamed to the TS contract
// (number | undefined | outcome(...)); the conformance oracle pins only the
// "command handler must return" prefix (outcome_contract.json, bad-return).
export function errHandlerReturnInvalid(got: string): string {
	return `command handler must return number (exit code), undefined (exit 0), or strictcli.outcome(...); got ${got}`;
}

export function errOutcomeExitCodeNotInteger(got: string): string {
	return `strictcli.outcome: exit_code must be an integer number; got ${got}`;
}

export function errGetNoSuchKey(name: string): string {
	return `strictcli.Get: no such key ${q(name)}`;
}

export function errGetKeyNil(name: string): string {
	return `strictcli.Get: key ${q(name)} is nil (not provided); use GetOpt for optional values`;
}

export function errGetTypeMismatch(
	name: string,
	gotType: string,
	wantType: string,
): string {
	return `strictcli.Get: key ${q(name)} has dynamic type ${gotType}, want ${wantType}`;
}

export function errGetOptNoSuchKey(name: string): string {
	return `strictcli.GetOpt: no such key ${q(name)}`;
}

export function errGetOptTypeMismatch(
	name: string,
	gotType: string,
	wantType: string,
): string {
	return `strictcli.GetOpt: key ${q(name)} has dynamic type ${gotType}, want ${wantType}`;
}

// ---------------------------------------------------------------------------
// tool.go
// ---------------------------------------------------------------------------

export function errJsonSchemaRouteError(errMsg: string): string {
	return `JsonSchema: ${errMsg}`;
}

export function errJsonSchemaIsGroup(commandPath: string): string {
	return `JsonSchema: '${commandPath}' is a group, not a command`;
}

export function errRouterCommandMustBeString(): string {
	return "command must be a string";
}

// ---------------------------------------------------------------------------
// toml.ts — TOML 1.0 acceptance gate (TS-only; parse-time)
//
// No Go/Python counterpart: the siblings' TOML parsers (go-toml-edit, tomllib)
// are TOML-1.0-native and reject 1.1-only constructs with their own parser
// errors. The TS stack parses with smol-toml (which accepts TOML 1.1), so an
// explicit gate rejects the six 1.1-only constructs pinned in ts-port-spec.md.
// ---------------------------------------------------------------------------

export function errTomlBasicStringEscape(esc: string): string {
	return `invalid escape sequence '\\${esc}' in basic string (TOML 1.1 construct; strictcli requires TOML 1.0)`;
}

export function errTomlInlineTableNewline(): string {
	return "newline inside inline table (TOML 1.1 construct; strictcli requires TOML 1.0)";
}

export function errTomlInlineTableTrailingComma(): string {
	return "trailing comma in inline table (TOML 1.1 construct; strictcli requires TOML 1.0)";
}

export function errTomlTimeMissingSeconds(): string {
	return "time without seconds (TOML 1.1 construct; strictcli requires TOML 1.0)";
}

export function errTomlDatetimeMissingSeconds(): string {
	return "datetime without seconds (TOML 1.1 construct; strictcli requires TOML 1.0)";
}

// ---------------------------------------------------------------------------
// toml.ts — single-key splicer verification (TS-only)
//
// The comment/order-preserving `config set` splicer re-parses both file
// versions and asserts that only the target key changed. A verification
// failure is an internal invariant violation, never expected in normal use.
// ---------------------------------------------------------------------------

export function errTomlSpliceVerifyFailed(key: string): string {
	return `internal: TOML splice verification failed: keys other than "${key}" changed`;
}

export function errTomlSpliceKeyNotFound(key: string): string {
	return `internal: TOML splice: key "${key}" not found in document`;
}

// ---------------------------------------------------------------------------
// app.ts — config option validation (Python App.__post_init__ spelling)
//
// Go spells these via WithConfigFormat/WithConfigConflictMode panics (see the
// option-constructor section above); Python raises ValueError with the App.*
// spelling. Python is the divergence ground truth for registration errors, so
// the app-level checks use these templates. Slots take pre-formatted reprs.
// ---------------------------------------------------------------------------

export function errAppConfigFormatBad(gotRepr: string): string {
	return `App.config_format must be "json" or "toml", got ${gotRepr}`;
}

export function errAppConfigConflictModeBad(gotRepr: string): string {
	return `App.config_conflict_mode must be "cli-wins" or "error", got ${gotRepr}`;
}
