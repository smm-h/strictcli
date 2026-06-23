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
	var toolDefs []interface{}

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
// The tool name uses underscores (MCP convention) instead of dots.
func buildMCPToolDef(commandPath string, cmd *Command) map[string]interface{} {
	// MCP tool names use underscores instead of dots for nested commands
	toolName := strings.ReplaceAll(commandPath, ".", "_")
	return map[string]interface{}{
		"name":        toolName,
		"description": cmd.Help,
		"inputSchema": buildJSONSchema(cmd),
	}
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

	// Convert MCP tool name (underscores) back to command path (dots)
	commandPath := mcpNameToCommandPath(a, toolName)

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

	// Call the command
	result, err := a.Call(commandPath, callArgs)
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

// mcpNameToCommandPath converts an MCP tool name (underscores for nesting)
// back to a dot-separated command path. It resolves ambiguity by checking
// which interpretation matches an actual command in the app's tree.
//
// For example, with a group "dns" containing command "zone-list":
//   - MCP name "dns_zone_list" could be "dns.zone.list" or "dns.zone-list"
//   - We try all possible splits and return the first that resolves to a command
func mcpNameToCommandPath(a *App, mcpName string) string {
	// Fast path: if the name has no underscores, it's a top-level command
	if !strings.Contains(mcpName, "_") {
		return mcpName
	}

	// Try all possible interpretations by splitting underscores into dots or dashes.
	// We use a recursive approach to try each underscore as either a dot (group separator)
	// or a dash (within a command/group name).
	parts := strings.Split(mcpName, "_")
	result := findValidCommandPath(a, parts, 0, "")
	if result != "" {
		return result
	}

	// Fallback: replace all underscores with dots (original simple behavior)
	return strings.ReplaceAll(mcpName, "_", ".")
}

// findValidCommandPath recursively tries to resolve MCP name parts into a
// valid command path by treating each underscore as either a dot or a dash.
func findValidCommandPath(a *App, parts []string, idx int, current string) string {
	if idx >= len(parts) {
		// Check if current resolves to a command
		segments := strings.Split(current, ".")
		route := a.resolveCommand(segments)
		if route.err == "" && route.cmd != nil {
			return current
		}
		return ""
	}

	if current == "" {
		return findValidCommandPath(a, parts, idx+1, parts[idx])
	}

	// Try dot (group separator)
	dotPath := findValidCommandPath(a, parts, idx+1, current+"."+parts[idx])
	if dotPath != "" {
		return dotPath
	}

	// Try dash (within-name separator)
	dashPath := findValidCommandPath(a, parts, idx+1, current+"-"+parts[idx])
	if dashPath != "" {
		return dashPath
	}

	return ""
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
