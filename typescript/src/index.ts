/** strictcli - TS-native strict CLI framework. Implementation lands module by module. */
export const VERSION = "0.31.0";

export type { App, AppSpec, Group, GroupSpec } from "./app.js";
export { createApp } from "./app.js";
export { ParseError, RegistrationError } from "./errors.js";
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
export type {
	Carrier,
	Context,
	DictSchema,
	ElemSchema,
	HandlerResult,
	HandlerReturn,
	ListSchema,
	Outcome,
	ScalarSchema,
	Schema,
} from "./types.js";
export { t } from "./types.js";
