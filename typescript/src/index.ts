/** strictcli - TS-native strict CLI framework. Implementation lands module by module. */
export const VERSION = "0.31.0";

export type {
	App,
	AppSpec,
	Group,
	GroupSpec,
	Result,
	RunChecksOptions,
	RunChecksResult,
} from "./app.js";
export { createApp } from "./app.js";
export {
	formatCheckResults,
	formatCheckResultsJSON,
} from "./checks/cmd.js";
export type {
	CheckContext,
	CheckOutcome,
	CheckProblem,
	CheckSeverity,
	CheckStatus,
} from "./checks/framework.js";
export {
	CheckRunResult,
	ErrorReporter,
	WarnReporter,
} from "./checks/framework.js";
export type {
	ErrorCheckSpecInit,
	WarnCheckSpecInit,
} from "./checks/provider.js";
export {
	CheckSpec,
	errorCheckSpec,
	warnCheckSpec,
} from "./checks/provider.js";
export type { ConfigFieldSpec } from "./config.js";
export type { InfraAccess, Writer } from "./context.js";
export { Context } from "./context.js";
// ParseError and RegistrationError stay internal (sibling parity: Python's
// __all__ and Go both export only InvokeError -- registration failures are
// Go panics / Python ValueError, parse failures print to stderr and exit 1).
export { InvokeError } from "./errors.js";
export type {
	AnyArg,
	AnyCommand,
	AnyFlag,
	AnyFlagSet,
	AnyMutexGroup,
	ArgDef,
	ArgOpts,
	CommandDef,
	CommandSpec,
	ConflictMode,
	CoRequired,
	Dependency,
	DeprecatedDef,
	ElementOf,
	FlagDef,
	FlagMap,
	FlagOpts,
	FlagSet,
	Handler,
	Implies,
	MutexGroup,
	PassthroughArgs,
	PassthroughDef,
	PassthroughHandler,
	Requires,
} from "./factories.js";
export {
	arg,
	coRequired,
	defineCommand,
	deprecated,
	flag,
	flagSet,
	implies,
	mutexGroup,
	passthrough,
	requires,
} from "./factories.js";
export type { HandlerArgs, InferHandler, InferHandlerArgs } from "./infer.js";
export type { InfraRootPath } from "./infra.js";
export { relativeToRoot } from "./infra.js";
export type { McpIO } from "./mcp.js";
export type { Outcome } from "./outcome.js";
export { outcome } from "./outcome.js";
export type { Tool } from "./tool.js";
export type {
	Carrier,
	DictSchema,
	ElemSchema,
	HandlerResult,
	HandlerReturn,
	ListSchema,
	ScalarSchema,
	Schema,
} from "./types.js";
export { t } from "./types.js";
