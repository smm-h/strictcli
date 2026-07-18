package strictcli

import "fmt"

// errors.go centralizes all error/panic format templates used across the
// strictcli package. Functions are grouped by their original source file for
// traceability. Message strings are byte-identical to the originals — this is
// a pure extraction, not a rewrite.

// ---------------------------------------------------------------------------
// strictcli.go — type constructors (ListOf, DictOf)
// ---------------------------------------------------------------------------

func errListOfBadItemType(itemType FlagType) string {
	return fmt.Sprintf("ListOf: item type must be str, int, or float, got %d", itemType)
}

func errDictOfBadValueType(valueType FlagType) string {
	return fmt.Sprintf("DictOf: value type must be str, int, or float, got %d", valueType)
}

// ---------------------------------------------------------------------------
// strictcli.go — option constructors (WithConfigConflictMode, etc.)
// ---------------------------------------------------------------------------

func errWithConfigConflictModeBadMode(mode string) string {
	return fmt.Sprintf("WithConfigConflictMode: mode must be \"cli-wins\" or \"error\", got %q", mode)
}

func errHandshakeEnvVarEmptyHelp(envVar string) string {
	return fmt.Sprintf("handshake env var %q: help must be a non-empty string", envVar)
}

func errDuplicateHandshakeEnvVar(envVar string) string {
	return fmt.Sprintf("duplicate handshake env var %q", envVar)
}

func errConflictModeBadMode(mode string) string {
	return fmt.Sprintf("ConflictMode: mode must be \"cli-wins\" or \"error\", got %q", mode)
}

// ---------------------------------------------------------------------------
// strictcli.go — tag validation
// ---------------------------------------------------------------------------

func errInvalidTagName(t string) string {
	return fmt.Sprintf("invalid tag name %q: must match [a-z][a-z0-9-]*", t)
}

// ---------------------------------------------------------------------------
// strictcli.go — NewArg validation
// ---------------------------------------------------------------------------

const errArgHelpEmpty = "Arg.help must be a non-empty string"

const errRequiredArgCannotHaveDefault = "required arg cannot have a default"

func errArgListTypeRequiresVariadic(name string) string {
	return fmt.Sprintf("Arg %q: list type requires variadic=true", name)
}

func errArgListItemTypeBad(name string) string {
	return fmt.Sprintf("Arg %q: list item type must be str, int, or float", name)
}

func errArgDictTypeNotSupported(name string) string {
	return fmt.Sprintf("Arg %q: dict type is not supported on positional arguments", name)
}

func errArgTypeBad(t FlagType) string {
	return fmt.Sprintf("Arg.type must be str, bool, int, or float, got %d", t)
}

func errArgChoicesIncompatibleListType(name string) string {
	return fmt.Sprintf("Arg %q: choices is incompatible with list type", name)
}

func errArgChoicesIncompatibleBool(name string) string {
	return fmt.Sprintf("Arg %q: choices is incompatible with type=bool", name)
}

func errArgChoicesEmpty(name string) string {
	return fmt.Sprintf("Arg %q: choices must be a non-empty list", name)
}

func errArgChoiceTypeMismatch(name string, c interface{}, typeName string) string {
	return fmt.Sprintf("Arg %q: choice %v is not of type %s", name, c, typeName)
}

func errArgListDefaultMustBeList(name string) string {
	return fmt.Sprintf("Arg %q: list arg default must be a list", name)
}

func errArgExplicitEmptyDefaultRedundantList(name string) string {
	return fmt.Sprintf("Arg %q: explicit empty default is redundant for list args, omit the default", name)
}

func errArgDefaultElementTypeMismatch(name string, i int, typeName string) string {
	return fmt.Sprintf("Arg %q: default element %d is not of type %s", name, i, typeName)
}

func errArgStrDefaultTypeMismatch(name string, gotType string) string {
	return fmt.Sprintf("Arg %q: type=str requires a str default, got '%s'", name, gotType)
}

func errArgIntDefaultTypeMismatch(name string, gotType string) string {
	return fmt.Sprintf("Arg %q: type=int requires an int default, got '%s'", name, gotType)
}

func errArgFloatDefaultTypeMismatch(name string, gotType string) string {
	return fmt.Sprintf("Arg %q: type=float requires a float default, got '%s'", name, gotType)
}

func errArgBoolDefaultTypeMismatch(name string, gotType string) string {
	return fmt.Sprintf("Arg %q: type=bool requires a bool default, got '%s'", name, gotType)
}

func errArgDefaultNotInChoices(name string, dflt interface{}, choicesStr string) string {
	return fmt.Sprintf("Arg %q: default '%v' is not in choices [%s]", name, dflt, choicesStr)
}

// ---------------------------------------------------------------------------
// strictcli.go — validateFlagConfig
// ---------------------------------------------------------------------------

const errFlagHelpEmpty = "Flag.help must be a non-empty string"

const errFlagForceReserved = "flag 'force' is a reserved name; use a qualified name like 'force-overwrite' or 'force-delete'"

func errFlagNoPrefixReserved(name string) string {
	return fmt.Sprintf("flag '%s': names starting with 'no-' are reserved for the negation system; use a positive name instead", name)
}

func errFlagRepeatableIncompatibleBool(name string) string {
	return fmt.Sprintf("Flag %q: repeatable is incompatible with type=bool", name)
}

func errFlagChoicesIncompatibleCompound(name string) string {
	return fmt.Sprintf("Flag %q: choices is incompatible with compound types (list/dict)", name)
}

func errFlagRepeatableRequiresExplicitUnique(name string) string {
	return fmt.Sprintf("Flag %q: repeatable requires explicit unique (unique=True or unique=False)", name)
}

func errFlagUniqueRequiresRepeatable(name string) string {
	return fmt.Sprintf("Flag %q: unique requires repeatable=True", name)
}

func errFlagEnvSeparatorRequiresRepeatable(name string) string {
	return fmt.Sprintf("Flag %q: env_separator requires repeatable=True", name)
}

func errFlagEnvSeparatorRequiresEnv(name string) string {
	return fmt.Sprintf("Flag %q: env_separator requires env", name)
}

func errFlagRepeatableEnvRequiresSeparator(name string) string {
	return fmt.Sprintf("Flag %q: repeatable flag with env requires env_separator", name)
}

func errFlagEnvSeparatorSingleChar(name string) string {
	return fmt.Sprintf("Flag %q: env_separator must be a single character", name)
}

func errFlagEnvSeparatorBackslash(name string) string {
	return fmt.Sprintf("Flag %q: env_separator cannot be a backslash", name)
}

func errFlagChoicesIncompatibleBool(name string) string {
	return fmt.Sprintf("Flag %q: choices is incompatible with type=bool", name)
}

func errFlagChoicesEmpty(name string) string {
	return fmt.Sprintf("Flag %q: choices must be a non-empty list", name)
}

func errFlagChoiceTypeMismatch(name string, c interface{}, typeName string) string {
	return fmt.Sprintf("Flag %q: choice %v is not of type %s", name, c, typeName)
}

func errFlagIntDefaultTypeMismatch(name string, gotType string) string {
	return fmt.Sprintf("Flag %q: type=int requires an int default, got '%s'", name, gotType)
}

func errFlagFloatDefaultTypeMismatch(name string, gotType string) string {
	return fmt.Sprintf("Flag %q: type=float requires a float default, got '%s'", name, gotType)
}

func errFlagDictDefaultMustBeMap(name string) string {
	return fmt.Sprintf("Flag %q: dict flag default must be a map[string]interface{}", name)
}

func errFlagExplicitEmptyDefaultRedundantDict(name string) string {
	return fmt.Sprintf("Flag %q: explicit empty default is redundant for dict flags, omit the default", name)
}

func errFlagDefaultValueForKey(name string, k string, errStr string) string {
	return fmt.Sprintf("Flag %q: default value for key %q: %s", name, k, errStr)
}

func errFlagListDefaultMustBeSlice(name string) string {
	return fmt.Sprintf("Flag %q: list flag default must be a []interface{}", name)
}

func errFlagExplicitEmptyDefaultRedundantList(name string) string {
	return fmt.Sprintf("Flag %q: explicit empty default is redundant for list flags, omit the default", name)
}

func errFlagDefaultElementError(name string, i int, errStr string) string {
	return fmt.Sprintf("Flag %q: default element %d: %s", name, i, errStr)
}

func errFlagRepeatableDefaultMustBeList(name string) string {
	return fmt.Sprintf("Flag %q: repeatable flag default must be a list", name)
}

func errFlagExplicitEmptyDefaultRedundantRepeatable(name string) string {
	return fmt.Sprintf("Flag %q: explicit empty default is redundant for repeatable flags, omit the default", name)
}

func errFlagDefaultElementTypeMismatch(name string, i int, typeName string) string {
	return fmt.Sprintf("Flag %q: default element %d is not of type %s", name, i, typeName)
}

func errFlagDefaultNotInChoices(name string, dflt interface{}, choicesStr string) string {
	return fmt.Sprintf("Flag %q: default '%v' is not in choices [%s]", name, dflt, choicesStr)
}

// ---------------------------------------------------------------------------
// strictcli.go — NewApp
// ---------------------------------------------------------------------------

const errAppHelpEmpty = "App.help must be a non-empty string"

func errDuplicateInfraRootEnvVar(envVar string) string {
	return fmt.Sprintf("duplicate infra root env var %q", envVar)
}

func errHandshakeIsAlreadyInfraRoot(ev string) string {
	return fmt.Sprintf("handshake env var %q is already declared as an infra root", ev)
}

const errCannotUseBothChecksAndEmbed = "cannot use both WithChecks and WithChecksEmbed"

func errChecksPathNotExist(path string) string {
	return fmt.Sprintf("checks_path does not exist: %s", path)
}

func errChecksTomlAppMismatch(appName string, expected string) string {
	return fmt.Sprintf("checks.toml: app %q does not match app name %q", appName, expected)
}

func errTestCoverageCannotCreateDir(err error) string {
	return fmt.Sprintf("test-coverage: cannot create .strictcli/coverage/: %s", err)
}

// ---------------------------------------------------------------------------
// strictcli.go — check registration
// ---------------------------------------------------------------------------

func errCannotRegisterCheckNotEnabled(name string) string {
	return fmt.Sprintf("cannot register check %q: checks not enabled", name)
}

func errCannotRegisterCheckNotDeclared(name string) string {
	return fmt.Sprintf("cannot register check %q: not declared in checks.toml", name)
}

func errCheckDuplicateRegistration(name string) string {
	return fmt.Sprintf("check %q: duplicate registration", name)
}

func errCheckSeverityMismatch(name string, severity string, used string, want string) string {
	return fmt.Sprintf(
		"check %q: declared severity %q in checks.toml but registered via %s; use %s",
		name, severity, used, want,
	)
}

// ---------------------------------------------------------------------------
// strictcli.go — TagContract
// ---------------------------------------------------------------------------

// errInvalidTagName is reused from the tag validation section above.

// ---------------------------------------------------------------------------
// strictcli.go — checkFlagConfigFieldDefault
// ---------------------------------------------------------------------------

func errConfigFieldFlagDefaultDisagree(cfName string, flagName string, cfDefault interface{}, flagDefault interface{}) string {
	return fmt.Sprintf(
		"config field %q collides with flag %q but their defaults disagree (%v vs %v); remove one default or make them equal",
		cfName, flagName, cfDefault, flagDefault,
	)
}

// ---------------------------------------------------------------------------
// strictcli.go — resolveInfraRootPath
// ---------------------------------------------------------------------------

func errRelativeToRootUndeclared(envVar string) error {
	return fmt.Errorf("RelativeToRoot references undeclared infra root %q; declare it as an infra root", envVar)
}

// ---------------------------------------------------------------------------
// strictcli.go — validateFlagInfraMarker
// ---------------------------------------------------------------------------

func errFlagRelativeToRootUndeclared(flagName string, envVar string) string {
	return fmt.Sprintf("flag %q: RelativeToRoot references undeclared infra root %q; declare it as an infra root", flagName, envVar)
}

// ---------------------------------------------------------------------------
// strictcli.go — command registration
// ---------------------------------------------------------------------------

func errCommandMissingHelp(name string) string {
	return fmt.Sprintf("command %q: missing help text", name)
}

func errCommandPassthroughCannotHave(name string, parts string) string {
	return fmt.Sprintf("command %q: passthrough commands cannot have %s", name, parts)
}

func errGlobalFlagNameReserved(name string) string {
	return fmt.Sprintf("global flag name %q is reserved", name)
}

func errGlobalShortFlagReserved(short string) string {
	return fmt.Sprintf("global short flag %q is reserved", short)
}

func errDuplicateGlobalFlag(name string) string {
	return fmt.Sprintf("duplicate global flag name %q", name)
}

const errGroupHelpEmpty = "Group.help must be a non-empty string"

func errGroupCollidesWithCommand(name string) string {
	return fmt.Sprintf("group %q collides with an existing command", name)
}

func errGroupAlreadyRegistered(name string) string {
	return fmt.Sprintf("group %q is already registered", name)
}

func errCommandCollidesWithGroup(name string) string {
	return fmt.Sprintf("command %q collides with an existing group", name)
}

const errDeprecatedNameEmpty = "deprecated command name must be a non-empty string"

func errDeprecatedMessageEmpty(name string) string {
	return fmt.Sprintf("deprecated command %q: message must not be empty", name)
}

func errDeprecatedCollidesCommand(name string) string {
	return fmt.Sprintf("deprecated command %q collides with an existing command", name)
}

func errDeprecatedCollidesGroup(name string) string {
	return fmt.Sprintf("deprecated command %q collides with an existing group", name)
}

func errDeprecatedAlreadyRegistered(name string) string {
	return fmt.Sprintf("deprecated command %q is already registered", name)
}

// ---------------------------------------------------------------------------
// strictcli.go — buildAndValidateCommand
// ---------------------------------------------------------------------------

func errCommandMutexMinFlags(name string, count int) string {
	return fmt.Sprintf("command %q: mutex group must have at least 2 flags, got %d", name, count)
}

func errCommandFlagInMultipleMutex(name string, flagName string) string {
	return fmt.Sprintf("command %q: flag %q appears in multiple mutex groups", name, flagName)
}

func errCommandFlagCollidesGlobal(name string, flagName string) string {
	return fmt.Sprintf("command %q: flag %q collides with a global flag", name, flagName)
}

func errCommandDuplicateFlag(name string, flagName string) string {
	return fmt.Sprintf("command %q: duplicate flag name %q", name, flagName)
}

func errCommandDuplicateArg(name string, argName string) string {
	return fmt.Sprintf("command %q: duplicate arg name %q", name, argName)
}

func errCommandAtMostOneVariadic(name string) string {
	return fmt.Sprintf("command %q: at most one variadic arg is allowed", name)
}

func errCommandVariadicMustBeLast(name string, argName string) string {
	return fmt.Sprintf("command %q: variadic arg %q must be the last arg", name, argName)
}

func errCommandFlagMissingHelp(name string, flagName string) string {
	return fmt.Sprintf("command %q: flag %q missing help text", name, flagName)
}

func errCommandEnvVarPrefix(name string, envVar string, flagName string, expectedPrefix string) string {
	return fmt.Sprintf(
		"command %q: env var %q for flag %q must start with %q (or set prefixed=false)",
		name, envVar, flagName, expectedPrefix,
	)
}

func errCommandCoRequiredMinFlags(name string, count int) string {
	return fmt.Sprintf("command %q: CoRequired must have at least 2 flags, got %d", name, count)
}

func errCommandCoRequiredUnknownFlag(name string, flagName string) string {
	return fmt.Sprintf("command %q: CoRequired references unknown flag %q", name, flagName)
}

func errCommandCoRequiredDuplicate(name string, flagName string) string {
	return fmt.Sprintf("command %q: CoRequired has duplicate flag %q", name, flagName)
}

func errCommandRequiresSameFlag(name string, flag string) string {
	return fmt.Sprintf("command %q: Requires flag and depends_on cannot be the same (%q)", name, flag)
}

func errCommandRequiresUnknownFlag(name string, flagName string) string {
	return fmt.Sprintf("command %q: Requires references unknown flag %q", name, flagName)
}

func errCommandImpliesSameFlag(name string, flag string) string {
	return fmt.Sprintf("command %q: Implies flag and implies cannot be the same (%q)", name, flag)
}

func errCommandImpliesUnknownFlag(name string, flagName string) string {
	return fmt.Sprintf("command %q: Implies references unknown flag %q", name, flagName)
}

func errCommandImpliesTriggerNotBool(name string, flagName string) string {
	return fmt.Sprintf("command %q: Implies trigger flag %q must be a bool flag", name, flagName)
}

func errCommandImpliesTargetNotBool(name string, flagName string) string {
	return fmt.Sprintf("command %q: Implies target flag %q must be a bool flag", name, flagName)
}

// ---------------------------------------------------------------------------
// parse.go — strict parsing
// ---------------------------------------------------------------------------

func errExpectedBoolean(s string) error {
	return fmt.Errorf("expected boolean, got '%s'", s)
}

func errExpectedInteger(s string) error {
	return fmt.Errorf("expected integer, got '%s'", s)
}

func errExpectedFloat(s string) error {
	return fmt.Errorf("expected float, got '%s'", s)
}

func errNaNNotAllowed() error {
	return fmt.Errorf("NaN is not allowed")
}

func errInfNotAllowed() error {
	return fmt.Errorf("Inf is not allowed")
}

// ---------------------------------------------------------------------------
// config.go — ConfigField registration
// ---------------------------------------------------------------------------

func errConfigFieldNameInvalid(name string) string {
	return fmt.Sprintf("ConfigField name %q is invalid: must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)", name)
}

func errConfigFieldNameReserved(name string) string {
	return fmt.Sprintf("config field name %q is reserved: names starting with underscore are reserved for framework fields", name)
}

func errConfigFieldHelpRequired(name string) string {
	return fmt.Sprintf("config field %q: help text is required", name)
}

func errConfigFieldTypeBad(t FlagType) string {
	return fmt.Sprintf("ConfigField.type must be str, bool, int, or float, got %d", t)
}

func errDuplicateConfigField(name string) string {
	return fmt.Sprintf("duplicate config field name %q", name)
}

func errConfigFieldConflictsFramework(name string) string {
	return fmt.Sprintf("config field name %q conflicts with framework field", name)
}

// ---------------------------------------------------------------------------
// config.go — framework field registration
// ---------------------------------------------------------------------------

func errFrameworkFieldMustStartUnderscore(name string) string {
	return fmt.Sprintf("framework field name %q must start with underscore", name)
}

func errFrameworkFieldNameInvalid(name string) string {
	return fmt.Sprintf("framework field %q: invalid name, must match [a-z][a-z0-9_]*(.[a-z][a-z0-9_]*)* (lowercase, dots for sections)", name)
}

func errFrameworkFieldHelpRequired(name string) string {
	return fmt.Sprintf("framework field %q: help text is required", name)
}

func errDuplicateFrameworkField(name string) string {
	return fmt.Sprintf("duplicate framework field name %q", name)
}

func errFrameworkFieldConflictsUser(name string) string {
	return fmt.Sprintf("framework field name %q conflicts with user config field", name)
}

// ---------------------------------------------------------------------------
// config.go — validateConfigFieldDefault
// ---------------------------------------------------------------------------

func errConfigFieldDefaultMismatch(name string, value interface{}, typeName string) string {
	return fmt.Sprintf("ConfigField %q: default value %v does not match type %s", name, value, typeName)
}

// ---------------------------------------------------------------------------
// check.go — reporter methods
// ---------------------------------------------------------------------------

const errNoteTextEmpty = "note text must be a non-empty string"

const errProblemTextEmpty = "problem text must be a non-empty string"

const errOutcomeMessageEmpty = "outcome message must be a non-empty string"

const errPassedWithProblems = "problems were reported; a check that found problems cannot pass -- use found instead"

const errSkipReasonEmpty = "skip reason must be a non-empty string"

const errSkippedWithProblems = "problems were reported; a check that found problems cannot skip"

const errFoundNoProblems = "no problems were reported; nothing found means pass -- use passed instead"

// ---------------------------------------------------------------------------
// check.go — deriveStatus
// ---------------------------------------------------------------------------

func errUnknownCheckOutcomeKind(kind string) string {
	return fmt.Sprintf("unknown check outcome kind %q", kind)
}

// ---------------------------------------------------------------------------
// check.go — addCheckDef
// ---------------------------------------------------------------------------

func errDuplicateCheckDef(name string) error {
	return fmt.Errorf("duplicate check definition %q", name)
}

// ---------------------------------------------------------------------------
// check.go — parseChecksToml
// ---------------------------------------------------------------------------

func errChecksTomlParse(err error) error {
	return fmt.Errorf("checks.toml: %s", err)
}

func errChecksTomlUnknownTopLevelKey(key string) error {
	return fmt.Errorf("checks.toml: unknown top-level key %q", key)
}

func errChecksTomlMissingApp() error {
	return fmt.Errorf("checks.toml: missing required top-level key \"app\"")
}

func errChecksTomlAppNotString() error {
	return fmt.Errorf("checks.toml: \"app\" must be a non-empty string")
}

func errChecksTomlChecksMustBeTable() error {
	return fmt.Errorf("checks.toml: [checks] must be a table")
}

func errChecksTomlInvalidCheckName(name string) error {
	return fmt.Errorf("checks.toml: invalid check name %q (must match [a-z][a-z0-9-]*)", name)
}

func errChecksTomlCheckMustBeTable(name string) error {
	return fmt.Errorf("checks.toml: check %q must be a table", name)
}

func errChecksTomlUnknownField(name string, field string) error {
	return fmt.Errorf("checks.toml: check %q: unknown field %q", name, field)
}

func errChecksTomlMissingField(name string, field string) error {
	return fmt.Errorf("checks.toml: check %q: missing required field %q", name, field)
}

func errChecksTomlTagsMustBeStrings(name string) error {
	return fmt.Errorf("checks.toml: check %q: \"tags\" must be a list of strings", name)
}

func errChecksTomlTagsEntriesMustBeStrings(name string) error {
	return fmt.Errorf("checks.toml: check %q: \"tags\" entries must be non-empty strings", name)
}

func errChecksTomlSeverityInvalid(name string, raw interface{}) error {
	return fmt.Errorf("checks.toml: check %q: \"severity\" must be \"error\" or \"warn\", got %q", name, raw)
}

func errChecksTomlBoolFieldInvalid(name string, field string, raw interface{}) error {
	return fmt.Errorf("checks.toml: check %q: %q must be a boolean, got %s", name, field, tomlTypeName(raw))
}

func errChecksTomlDependsOnMustBeStrings(name string) error {
	return fmt.Errorf("checks.toml: check %q: \"depends_on\" must be a list of strings", name)
}

func errChecksTomlDependsOnEntriesMustBeStrings(name string) error {
	return fmt.Errorf("checks.toml: check %q: \"depends_on\" entries must be strings", name)
}

func errChecksTomlScopeMustBeString(name string, raw interface{}) error {
	return fmt.Errorf("checks.toml: check %q: \"scope\" must be a string, got %s", name, tomlTypeName(raw))
}

func errChecksTomlDependsOnUnknown(name string, dep string) error {
	return fmt.Errorf("checks.toml: check %q: depends_on references unknown check %q", name, dep)
}

// ---------------------------------------------------------------------------
// check_runner.go
// ---------------------------------------------------------------------------

func errCheckDependencyCycleInvolving(name string) error {
	return fmt.Errorf("check dependency cycle detected involving %q", name)
}

func errCheckDependencyCycle(cyclePath string) error {
	return fmt.Errorf("check dependency cycle: %s", cyclePath)
}

func errCheckDependencyCycleDetected() error {
	return fmt.Errorf("check dependency cycle detected")
}

func errCheckOutcomeNotMinted(name string) string {
	return fmt.Sprintf("check %q returned an outcome not minted by its reporter; use reporter methods (Passed/Skipped/Found)", name)
}

func errInvalidGlobPattern(pattern string, err error) error {
	return fmt.Errorf("invalid glob pattern %q: %s", pattern, err)
}

// ---------------------------------------------------------------------------
// check_provider.go
// ---------------------------------------------------------------------------

func errCheckProviderSeverityMismatch(name string, severity string, used string, want string) string {
	return fmt.Sprintf(
		"check %q: declared severity %q but registered via %s; use %s",
		name, severity, used, want,
	)
}

// ---------------------------------------------------------------------------
// check_public.go
// ---------------------------------------------------------------------------

func errChecksNotEnabled() error {
	return fmt.Errorf("checks are not enabled on this App")
}

// ---------------------------------------------------------------------------
// schema.go
// ---------------------------------------------------------------------------

func errCannotDetermineProjectIDNoGoMod() error {
	return fmt.Errorf("Cannot determine project_id: go.mod not found")
}

func errCannotDetermineProjectIDReadError(err error) error {
	return fmt.Errorf("Cannot determine project_id: error reading go.mod: %w", err)
}

func errCannotDetermineProjectIDNoModule() error {
	return fmt.Errorf("Cannot determine project_id: no module directive in go.mod")
}

func errSchemaMismatch(existingID string, newID string) error {
	return fmt.Errorf(
		"Schema mismatch: existing schema belongs to project '%s', not '%s'. Run from the correct project directory.",
		existingID, newID,
	)
}

// ---------------------------------------------------------------------------
// tagdsl.go
// ---------------------------------------------------------------------------

func errTagExprUnexpectedChar(ch string, pos int) error {
	return fmt.Errorf("tag expression: unexpected character %q at position %d", ch, pos)
}

func errTagExprEmpty() error {
	return fmt.Errorf("tag expression: empty expression")
}

func errTagExprUnexpectedToken(val string, pos int) error {
	return fmt.Errorf("tag expression: unexpected token %q at position %d", val, pos)
}

func errTagExprUnexpectedEnd(pos int) error {
	return fmt.Errorf("tag expression: unexpected end of expression at position %d", pos)
}

func errTagExprExpectedRParen(pos int) error {
	return fmt.Errorf("tag expression: expected \")\" at position %d", pos)
}

// ---------------------------------------------------------------------------
// context.go
// ---------------------------------------------------------------------------

func errInfraValueUndeclared(envVar string) string {
	return fmt.Sprintf("InfraValue: %q is not a declared infra root or handshake env var", envVar)
}

func errNoSourceInfo(name string) string {
	return fmt.Sprintf("no source info for flag %q", name)
}

// ---------------------------------------------------------------------------
// outcome.go
// ---------------------------------------------------------------------------

func errGetNoSuchKey(name string) string {
	return fmt.Sprintf("strictcli.Get: no such key %q", name)
}

func errGetKeyNil(name string) string {
	return fmt.Sprintf("strictcli.Get: key %q is nil (not provided); use GetOpt for optional values", name)
}

func errGetTypeMismatch(name string, v interface{}, zero interface{}) string {
	return fmt.Sprintf("strictcli.Get: key %q has dynamic type %T, want %T", name, v, zero)
}

func errGetOptNoSuchKey(name string) string {
	return fmt.Sprintf("strictcli.GetOpt: no such key %q", name)
}

func errGetOptTypeMismatch(name string, v interface{}, zero interface{}) string {
	return fmt.Sprintf("strictcli.GetOpt: key %q has dynamic type %T, want %T", name, v, zero)
}

// ---------------------------------------------------------------------------
// tool.go
// ---------------------------------------------------------------------------

func errJsonSchemaRouteError(errMsg string) string {
	return fmt.Sprintf("JsonSchema: %s", errMsg)
}

func errJsonSchemaIsGroup(commandPath string) string {
	return fmt.Sprintf("JsonSchema: '%s' is a group, not a command", commandPath)
}
