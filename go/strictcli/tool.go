package strictcli

import (
	"fmt"
	"strings"
)

// Tool is a descriptor for exposing CLI commands to tool-using LLM agents.
//
// Effect and Consequential publish the effects-regime classification BESIDE
// the argument schema (never inside it): a consumer rendering this tool must
// be able to see that the command changes things and that calling it requires
// stating consent. Same vocabulary as the schema dump: Effect is mandatory,
// Consequential defaults to false.
type Tool struct {
	Name          string
	Description   string
	Parameters    map[string]interface{}
	Effect        string
	Consequential bool
	Execute       func(map[string]interface{}, ...CallOption) (interface{}, error)
}

// jsonSchemaType maps scalar FlagType values to JSON Schema type strings.
var jsonSchemaType = map[FlagType]string{
	TypeStr:   "string",
	TypeBool:  "boolean",
	TypeInt:   "integer",
	TypeFloat: "number",
}

// buildJSONSchema builds a JSON Schema parameters object for a command's
// flags and positional args.
func buildJSONSchema(cmd *Command) map[string]interface{} {
	properties := map[string]interface{}{}
	// Initialized rather than declared nil: encoding/json renders a nil slice
	// as null, and "required": null is not valid JSON Schema. A command with
	// no required parameters must publish an empty list, as Python and
	// TypeScript do.
	required := []interface{}{}

	for i := range cmd.flags {
		f := &cmd.flags[i]
		paramName := flagParamName(f.Name)
		prop := map[string]interface{}{}

		if IsDictType(f.Type) {
			prop["type"] = "object"
			prop["additionalProperties"] = map[string]interface{}{
				"type": jsonSchemaType[ItemType(f.Type)],
			}
		} else if IsListType(f.Type) || f.Repeatable {
			prop["type"] = "array"
			prop["items"] = map[string]interface{}{
				"type": jsonSchemaType[ItemType(f.Type)],
			}
		} else {
			prop["type"] = jsonSchemaType[f.Type]
		}

		if f.Choices != nil {
			choices := make([]interface{}, len(f.Choices))
			copy(choices, f.Choices)
			prop["enum"] = choices
		}

		prop["description"] = f.Help

		properties[paramName] = prop

		// A parameter is required iff its DECLARED presence is required
		// (contract §13's presence-round amendment, §23.7). The old
		// four-clause derivation is gone, and with it the exclusion of bools:
		// "bool flags always have a default" is false by construction now.
		if f.presence == presenceRequired {
			required = append(required, paramName)
		}
	}

	for i := range cmd.args {
		a := &cmd.args[i]
		prop := map[string]interface{}{}

		if a.IsVariadic {
			prop["type"] = "array"
			prop["items"] = map[string]interface{}{
				"type": jsonSchemaType[a.Type],
			}
		} else {
			prop["type"] = jsonSchemaType[a.Type]
		}

		if a.Choices != nil {
			choices := make([]interface{}, len(a.Choices))
			copy(choices, a.Choices)
			prop["enum"] = choices
		}

		prop["description"] = a.Help

		properties[a.Name] = prop

		if a.presence == presenceRequired {
			required = append(required, a.Name)
		}
	}

	schema := map[string]interface{}{
		"type":                 "object",
		"properties":           properties,
		"required":             required,
		"additionalProperties": false,
	}
	return schema
}

// JsonSchema produces a JSON Schema parameters object for a command's flags
// and positional args.
//
// commandPath is a dot-separated path to the command (e.g. "deploy" or
// "config.show").
//
// Returns a JSON Schema object with "type": "object", "properties",
// "required", and "additionalProperties": false.
//
// Panics if the command path is invalid or resolves to a group.
func (a *App) JsonSchema(commandPath string) map[string]interface{} {
	segments := strings.Split(commandPath, ".")
	route := a.resolveCommand(segments)
	if route.err != "" {
		panic(errJsonSchemaRouteError(route.err))
	}
	if route.cmd == nil {
		panic(errJsonSchemaIsGroup(commandPath))
	}
	return buildJSONSchema(route.cmd)
}

// AsTools exports non-hidden, non-interactive leaf commands as Tool
// descriptors. Returns a list of Tool objects, one per eligible command plus
// a router tool. Each tool's Execute function wraps App.Call().
func (a *App) AsTools() []Tool {
	var tools []Tool
	var commandPaths []string

	// Collect leaf commands from top-level in insertion order
	for _, name := range a.cmdOrder {
		cmd, ok := a.commands[name]
		if !ok {
			continue
		}
		if cmd.Hidden || cmd.Interactive {
			continue
		}
		tools = append(tools, a.makeTool(name, cmd))
		commandPaths = append(commandPaths, name)
	}

	// Collect leaf commands from groups (recursive) in insertion order
	for _, groupName := range a.groupOrder {
		grp, ok := a.groups[groupName]
		if !ok {
			continue
		}
		a.collectToolsFromGroup(grp, []string{groupName}, &tools, &commandPaths)
	}

	// Build the router tool
	tools = append(tools, a.makeRouterTool(commandPaths))

	return tools
}

// collectToolsFromGroup recursively collects non-hidden, non-interactive
// commands from a group and its subgroups.
func (a *App) collectToolsFromGroup(
	group *Group,
	path []string,
	tools *[]Tool,
	commandPaths *[]string,
) {
	if group.Hidden {
		return
	}

	// Commands in insertion order
	for _, cmdName := range group.order {
		cmd, ok := group.Commands[cmdName]
		if !ok {
			continue
		}
		if cmd.Hidden || cmd.Interactive {
			continue
		}
		dotted := strings.Join(append(path, cmdName), ".")
		*tools = append(*tools, a.makeTool(dotted, cmd))
		*commandPaths = append(*commandPaths, dotted)
	}

	// Subgroups in insertion order
	for _, subName := range group.groupOrder {
		subGroup, ok := group.Groups[subName]
		if !ok {
			continue
		}
		a.collectToolsFromGroup(subGroup, append(path, subName), tools, commandPaths)
	}
}

// makeTool builds a Tool for a single command.
func (a *App) makeTool(commandPath string, cmd *Command) Tool {
	return Tool{
		Name:          commandPath,
		Description:   cmd.Help,
		Parameters:    buildJSONSchema(cmd),
		Effect:        cmd.Effect,
		Consequential: cmd.Consequential,
		Execute: func(kwargs map[string]interface{}, opts ...CallOption) (interface{}, error) {
			return a.Call(commandPath, kwargs, opts...)
		},
	}
}

// makeRouterTool builds the router tool that lists and dispatches to
// per-command tools.
func (a *App) makeRouterTool(commandPaths []string) Tool {
	// Copy to avoid aliasing
	paths := make([]string, len(commandPaths))
	copy(paths, commandPaths)

	// Build enum list as []interface{} for JSON schema
	enumValues := make([]interface{}, len(paths))
	for i, p := range paths {
		enumValues[i] = p
	}

	parameters := map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"command": map[string]interface{}{
				"type":        "string",
				"description": "Command to execute (dot-separated path)",
				"enum":        enumValues,
			},
		},
		"required":             []interface{}{"command"},
		"additionalProperties": false,
	}

	// The router can reach a mutating command, so it classifies as mutating. It
	// is NOT itself consequential: the routed command's own requirement is
	// checked when the call reaches it, and the router forwards the caller's
	// consent unchanged. Marking the router consequential would demand consent
	// for routing to a read_only command, which confirms nothing.
	return Tool{
		Name:          a.Name,
		Description:   fmt.Sprintf("Route to %s commands", a.Name),
		Parameters:    parameters,
		Effect:        EffectMutating,
		Consequential: false,
		Execute: func(kwargs map[string]interface{}, opts ...CallOption) (interface{}, error) {
			cmdVal, ok := kwargs["command"]
			if !ok {
				// No command specified -- return list of available commands
				result := make([]string, len(paths))
				copy(result, paths)
				return result, nil
			}
			cmdPath, ok := cmdVal.(string)
			if !ok {
				return nil, &InvokeError{Message: "command must be a string"}
			}
			// Strip "command" before forwarding to Call
			fwd := make(map[string]interface{}, len(kwargs)-1)
			for k, v := range kwargs {
				if k != "command" {
					fwd[k] = v
				}
			}
			return a.Call(cmdPath, fwd, opts...)
		},
	}
}
