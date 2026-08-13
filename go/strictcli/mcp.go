package strictcli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
)

// mcpRequest represents an incoming JSON-RPC 2.0 request or notification.
type mcpRequest struct {
	Jsonrpc string                 `json:"jsonrpc"`
	ID      interface{}            `json:"id,omitempty"` // nil for notifications
	Method  string                 `json:"method"`
	Params  map[string]interface{} `json:"params,omitempty"`
}

// mcpResponse represents an outgoing JSON-RPC 2.0 response.
type mcpResponse struct {
	Jsonrpc string      `json:"jsonrpc"`
	ID      interface{} `json:"id"`
	Result  interface{} `json:"result,omitempty"`
	Error   *mcpError   `json:"error,omitempty"`
}

// mcpError represents a JSON-RPC 2.0 error object.
type mcpError struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// JSON-RPC error codes
const (
	mcpErrMethodNotFound = -32601
	mcpErrInvalidParams  = -32602
	mcpErrInternal       = -32603
)

// ServeMCP starts a JSON-RPC 2.0 server on stdin/stdout implementing the
// Model Context Protocol. It reads one JSON object per line from stdin and
// writes one JSON object per line to stdout. The server handles initialize,
// tools/list, and tools/call requests.
func (a *App) ServeMCP() {
	a.serveMCPIO(os.Stdin, os.Stdout)
}

// serveMCPIO is the internal implementation of ServeMCP that accepts custom
// reader/writer for testability.
func (a *App) serveMCPIO(in io.Reader, out io.Writer) {
	scanner := bufio.NewScanner(in)
	// Increase buffer size for large JSON objects
	scanner.Buffer(make([]byte, 0, 1024*1024), 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if strings.TrimSpace(line) == "" {
			continue
		}

		var req mcpRequest
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			// Invalid JSON -- send parse error if we can extract an ID
			resp := mcpResponse{
				Jsonrpc: "2.0",
				ID:      nil,
				Error: &mcpError{
					Code:    -32700,
					Message: "Parse error",
				},
			}
			writeMCPResponse(out, resp)
			continue
		}

		// Notifications have no ID and expect no response
		if req.ID == nil {
			// notifications/initialized and any other notification: silently ignore
			continue
		}

		resp := a.handleMCPRequest(req)
		writeMCPResponse(out, resp)
	}
}

// handleMCPRequest dispatches a JSON-RPC request to the appropriate handler.
func (a *App) handleMCPRequest(req mcpRequest) mcpResponse {
	switch req.Method {
	case "initialize":
		return a.handleMCPInitialize(req)
	case "tools/list":
		return a.handleMCPToolsList(req)
	case "tools/call":
		return a.handleMCPToolsCall(req)
	default:
		return mcpResponse{
			Jsonrpc: "2.0",
			ID:      req.ID,
			Error: &mcpError{
				Code:    mcpErrMethodNotFound,
				Message: fmt.Sprintf("Method not found: %s", req.Method),
			},
		}
	}
}

// handleMCPInitialize responds to the initialize request with server capabilities.
func (a *App) handleMCPInitialize(req mcpRequest) mcpResponse {
	return mcpResponse{
		Jsonrpc: "2.0",
		ID:      req.ID,
		Result: map[string]interface{}{
			"protocolVersion": "2024-11-05",
			"capabilities": map[string]interface{}{
				"tools": map[string]interface{}{},
			},
			"serverInfo": map[string]interface{}{
				"name":    a.Name,
				"version": a.Version,
			},
		},
	}
}

// handleMCPToolsList responds with tool definitions for all non-hidden,
// non-interactive commands.
func (a *App) handleMCPToolsList(req mcpRequest) mcpResponse {
	// Initialized rather than declared nil for the same reason buildJSONSchema
	// initializes `required`: encoding/json renders a nil slice as null, and an
	// app with no exportable command must publish an empty tools list, as
	// Python and TypeScript do.
	toolDefs := []interface{}{}

	// Collect leaf commands from top-level in insertion order
	for _, name := range a.cmdOrder {
		cmd, ok := a.commands[name]
		if !ok || cmd.Hidden || cmd.Interactive {
			continue
		}
		toolDefs = append(toolDefs, buildMCPToolDef(name, cmd))
	}

	// Collect leaf commands from groups (recursive) in insertion order
	for _, groupName := range a.groupOrder {
		grp, ok := a.groups[groupName]
		if !ok {
			continue
		}
		collectMCPToolsFromGroup(grp, []string{groupName}, &toolDefs)
	}

	return mcpResponse{
		Jsonrpc: "2.0",
		ID:      req.ID,
		Result: map[string]interface{}{
			"tools": toolDefs,
		},
	}
}

// collectMCPToolsFromGroup recursively collects MCP tool definitions from
// a group and its subgroups.
func collectMCPToolsFromGroup(group *Group, path []string, toolDefs *[]interface{}) {
	if group.Hidden {
		return
	}

	for _, cmdName := range group.order {
		cmd, ok := group.Commands[cmdName]
		if !ok || cmd.Hidden || cmd.Interactive {
			continue
		}
		dotted := strings.Join(append(path, cmdName), ".")
		*toolDefs = append(*toolDefs, buildMCPToolDef(dotted, cmd))
	}

	for _, subName := range group.groupOrder {
		subGroup, ok := group.Groups[subName]
		if !ok {
			continue
		}
		collectMCPToolsFromGroup(subGroup, append(path, subName), toolDefs)
	}
}

// buildMCPToolDef builds an MCP tool definition for a single command.
// The tool name IS the dotted command path: dots are legal in MCP tool names,
// and the two sibling implementations have always published them unchanged.
//
// The classification sits BESIDE inputSchema, never inside it: it describes
// the tool, not an argument the caller passes. Same emission rule as the
// schema dump -- "effect" always, "consequential" only when true (absence
// means "not consequential").
func buildMCPToolDef(commandPath string, cmd *Command) map[string]interface{} {
	def := map[string]interface{}{
		"name":        commandPath,
		"description": cmd.Help,
		"effect":      cmd.Effect,
		"inputSchema": buildJSONSchema(cmd),
	}
	if cmd.Consequential {
		def["consequential"] = true
	}
	return def
}

// handleMCPToolsCall validates params, calls the command, and returns the result.
func (a *App) handleMCPToolsCall(req mcpRequest) mcpResponse {
	params := req.Params

	// Extract tool name
	nameVal, ok := params["name"]
	if !ok {
		return mcpResponse{
			Jsonrpc: "2.0",
			ID:      req.ID,
			Error: &mcpError{
				Code:    mcpErrInvalidParams,
				Message: "missing required parameter: name",
			},
		}
	}
	toolName, ok := nameVal.(string)
	if !ok {
		return mcpResponse{
			Jsonrpc: "2.0",
			ID:      req.ID,
			Error: &mcpError{
				Code:    mcpErrInvalidParams,
				Message: "parameter 'name' must be a string",
			},
		}
	}

	// The tool name is the command path verbatim -- there is no name mangling
	// to undo, and therefore no ambiguity to guess at. An unresolvable name
	// reaches Call unchanged and surfaces as a tool-result error naming what
	// the caller actually sent.
	commandPath := toolName

	// Extract arguments (may be nil)
	var callArgs map[string]interface{}
	if argsVal, ok := params["arguments"]; ok {
		if argsMap, ok := argsVal.(map[string]interface{}); ok {
			callArgs = argsMap
		} else {
			return mcpResponse{
				Jsonrpc: "2.0",
				ID:      req.ID,
				Error: &mcpError{
					Code:    mcpErrInvalidParams,
					Message: "parameter 'arguments' must be an object",
				},
			}
		}
	}
	if callArgs == nil {
		callArgs = map[string]interface{}{}
	}

	// Consent is a top-level param, a sibling of "name" and "arguments" --
	// never a member of "arguments", which is the command's own argument
	// namespace and is published with additionalProperties: false. There is no
	// server-side default: absent means "not consented", and a consequential
	// tool is then refused.
	var callOpts []CallOption
	if consentVal, ok := params["approve_consequential"]; ok {
		consent, ok := consentVal.(bool)
		if !ok {
			return mcpResponse{
				Jsonrpc: "2.0",
				ID:      req.ID,
				Error: &mcpError{
					Code:    mcpErrInvalidParams,
					Message: "parameter 'approve_consequential' must be a boolean",
				},
			}
		}
		if consent {
			callOpts = append(callOpts, WithApproveConsequential())
		}
	}

	// Call the command
	result, err := a.Call(commandPath, callArgs, callOpts...)
	if err != nil {
		return mcpResponse{
			Jsonrpc: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{
				"content": []interface{}{
					map[string]interface{}{
						"type": "text",
						"text": err.Error(),
					},
				},
				"isError": true,
			},
		}
	}

	// Marshal result to JSON text
	resultJSON, jsonErr := json.Marshal(result)
	if jsonErr != nil {
		return mcpResponse{
			Jsonrpc: "2.0",
			ID:      req.ID,
			Error: &mcpError{
				Code:    mcpErrInternal,
				Message: fmt.Sprintf("failed to marshal result: %s", jsonErr),
			},
		}
	}

	return mcpResponse{
		Jsonrpc: "2.0",
		ID:      req.ID,
		Result: map[string]interface{}{
			"content": []interface{}{
				map[string]interface{}{
					"type": "text",
					"text": string(resultJSON),
				},
			},
		},
	}
}

// writeMCPResponse marshals and writes a JSON-RPC response as a single line.
func writeMCPResponse(out io.Writer, resp mcpResponse) {
	data, err := json.Marshal(resp)
	if err != nil {
		// Last resort: write a minimal error
		fmt.Fprintf(out, `{"jsonrpc":"2.0","id":null,"error":{"code":-32603,"message":"marshal error"}}`+"\n")
		return
	}
	fmt.Fprintf(out, "%s\n", data)
}
