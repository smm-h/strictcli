/** strictcli - TS-native strict CLI framework. Implementation lands module by module. */
export const VERSION = "0.31.0";

export type {
	AnyArg,
	AnyCommand,
	AnyFlag,
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
export type { InferHandler, InferHandlerArgs } from "./infer.js";
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
