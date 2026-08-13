package strictcli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"sort"
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

// JSON-RPC and MCP error codes. -32020 (HeaderMismatch) belongs to the HTTP
// transport, which this server does not speak; -32021
// (MissingRequiredClientCapability) is fired by the confirmation round-trip.
const (
	mcpErrMethodNotFound             = -32601
	mcpErrInvalidParams              = -32602
	mcpErrInternal                   = -32603
	mcpErrUnsupportedProtocolVersion = -32022
)

// The server speaks two eras (effects contract §22):
//
//	MODERN (2026-07-28) -- stateless. There is no handshake: every request
//	carries its protocol version and the client's capabilities in `_meta`,
//	every result carries a `resultType`, and `server/discover` advertises the
//	supported versions, the capabilities and the server identity that the
//	handshake used to carry.
//
//	LEGACY (2024-11-05) -- the `initialize` handshake. It is selected by an
//	`initialize` request and scoped to this process, which is exactly the
//	dual-era rule the modern revision specifies for a server serving both.
//
// A request that carries neither the modern metadata nor a preceding
// `initialize` is malformed and is refused. Nothing is inferred.
const (
	mcpProtocolVersion       = "2026-07-28"
	mcpLegacyProtocolVersion = "2024-11-05"
)

// The reserved `_meta` keys of the modern revision.
const (
	mcpMetaProtocolVersion    = "io.modelcontextprotocol/protocolVersion"
	mcpMetaClientCapabilities = "io.modelcontextprotocol/clientCapabilities"
	mcpMetaClientInfo         = "io.modelcontextprotocol/clientInfo"
	mcpMetaServerInfo         = "io.modelcontextprotocol/serverInfo"
	mcpMetaLogLevel           = "io.modelcontextprotocol/logLevel"
	mcpMetaSubscriptionID     = "io.modelcontextprotocol/subscriptionId"
)

// mcpRecognizedReservedMetaKeys are the keys this revision defines under a
// prefix the protocol reserves for itself. Any other key under a reserved
// prefix is refused rather than ignored.
var mcpRecognizedReservedMetaKeys = map[string]bool{
	mcpMetaProtocolVersion:    true,
	mcpMetaClientCapabilities: true,
	mcpMetaClientInfo:         true,
	mcpMetaLogLevel:           true,
	mcpMetaSubscriptionID:     true,
}

// mcpFeatureConsequentialConfirmation is the named feature the server declares
// (campaign decision 26). A NAME, never a version number: a new name appears
// only if the confirmation dance changes incompatibly.
const mcpFeatureConsequentialConfirmation = "dev.smmh.strictcli/consequential-confirmation"

// Cacheability of the list surfaces. The tool list is derived from the app's
// static command registration, so it cannot vary per client (public) and cannot
// change while the process runs.
const (
	mcpCacheTTLMs = 3600000
	mcpCacheScope = "public"
)

var (
	mcpMetaPrefixLabelRe = regexp.MustCompile(`^[A-Za-z](?:[A-Za-z0-9-]*[A-Za-z0-9])?$`)
	mcpMetaNameRe        = regexp.MustCompile(`^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$`)
)

// mcpMetaKeyValid reports whether key matches the protocol's `_meta` key-name
// grammar: an optional dot-separated prefix, a slash, and a name. The name may
// be empty; when it is not, it begins and ends alphanumeric and may carry
// hyphens, underscores and dots in between.
func mcpMetaKeyValid(key string) bool {
	parts := strings.Split(key, "/")
	var name string
	switch len(parts) {
	case 1:
		name = parts[0]
	case 2:
		for _, label := range strings.Split(parts[0], ".") {
			if !mcpMetaPrefixLabelRe.MatchString(label) {
				return false
			}
		}
		name = parts[1]
	default:
		return false
	}
	return name == "" || mcpMetaNameRe.MatchString(name)
}

// mcpMetaKeyReserved reports whether key sits under a prefix the protocol
// reserves for itself: any prefix whose SECOND label is `modelcontextprotocol`
// or `mcp`. So `io.modelcontextprotocol/` and `com.mcp.tools/` are reserved and
// `com.example.mcp/` is not.
func mcpMetaKeyReserved(key string) bool {
	parts := strings.Split(key, "/")
	if len(parts) != 2 {
		return false
	}
	labels := strings.Split(parts[0], ".")
	return len(labels) >= 2 && (labels[1] == "modelcontextprotocol" || labels[1] == "mcp")
}

// mcpValidateMeta validates one request's `_meta` block, returning the refusal
// text or "". It is called only once the block is known to carry the protocol
// version, which is what selects the modern era in the first place.
func mcpValidateMeta(meta map[string]interface{}) string {
	// Sorted so the refusal is deterministic when a request carries more than
	// one offending key: Go map iteration is randomized.
	keys := make([]string, 0, len(meta))
	for key := range meta {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		if !mcpMetaKeyValid(key) {
			return fmt.Sprintf("invalid _meta key name: '%s'", key)
		}
		if mcpMetaKeyReserved(key) && !mcpRecognizedReservedMetaKeys[key] {
			return fmt.Sprintf("unrecognized reserved _meta key: '%s'", key)
		}
	}
	if _, ok := meta[mcpMetaProtocolVersion].(string); !ok {
		return fmt.Sprintf("_meta['%s'] must be a string", mcpMetaProtocolVersion)
	}
	caps, ok := meta[mcpMetaClientCapabilities]
	if !ok {
		return fmt.Sprintf("missing required request metadata: _meta['%s']", mcpMetaClientCapabilities)
	}
	if _, ok := caps.(map[string]interface{}); !ok {
		return fmt.Sprintf("_meta['%s'] must be an object", mcpMetaClientCapabilities)
	}
	if info, present := meta[mcpMetaClientInfo]; present {
		if _, ok := info.(map[string]interface{}); !ok {
			return fmt.Sprintf("_meta['%s'] must be an object", mcpMetaClientInfo)
		}
	}
	return ""
}

// mcpServerInfo is the identity every modern result carries in its own `_meta`.
func (a *App) mcpServerInfo() map[string]interface{} {
	return map[string]interface{}{
		mcpMetaServerInfo: map[string]interface{}{
			"name":    a.Name,
			"version": a.Version,
		},
	}
}

// mcpCompleteResult wraps a modern result body with its result type and the
// server identity.
func (a *App) mcpCompleteResult(reqID interface{}, body map[string]interface{}) mcpResponse {
	result := map[string]interface{}{"resultType": "complete"}
	for k, v := range body {
		result[k] = v
	}
	result["_meta"] = a.mcpServerInfo()
	return mcpResponse{Jsonrpc: "2.0", ID: reqID, Result: result}
}

// mcpErrorResponse builds a JSON-RPC error response, with optional data.
func mcpErrorResponse(reqID interface{}, code int, message string, data interface{}) mcpResponse {
	return mcpResponse{
		Jsonrpc: "2.0",
		ID:      reqID,
		Error:   &mcpError{Code: code, Message: message, Data: data},
	}
}

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

	// The one piece of connection state a dual-era server is allowed: an
	// `initialize` request selects legacy semantics for this process. Modern
	// requests carry everything they need and never consult it.
	legacyEra := false

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

		resp := a.handleMCPRequest(req, &legacyEra)
		writeMCPResponse(out, resp)
	}
}

// handleMCPRequest routes one request to its era and dispatches it there.
func (a *App) handleMCPRequest(req mcpRequest, legacyEra *bool) mcpResponse {
	if req.Method == "initialize" {
		*legacyEra = true
		return a.handleMCPInitialize(req)
	}

	metaVal, present := req.Params["_meta"]
	meta, isObject := metaVal.(map[string]interface{})
	switch {
	case present && !isObject:
		return mcpErrorResponse(req.ID, mcpErrInvalidParams,
			"parameter '_meta' must be an object", nil)
	case isObject && hasKey(meta, mcpMetaProtocolVersion):
		return a.dispatchMCPModern(req, meta)
	case *legacyEra:
		return a.dispatchMCPLegacy(req)
	default:
		return mcpErrorResponse(req.ID, mcpErrInvalidParams,
			fmt.Sprintf("missing required request metadata: _meta['%s']", mcpMetaProtocolVersion), nil)
	}
}

// hasKey reports whether a decoded JSON object carries a key at all, including
// one whose value is null.
func hasKey(obj map[string]interface{}, key string) bool {
	_, ok := obj[key]
	return ok
}

// dispatchMCPModern dispatches one modern-era request: metadata, then version,
// then method.
func (a *App) dispatchMCPModern(req mcpRequest, meta map[string]interface{}) mcpResponse {
	if invalid := mcpValidateMeta(meta); invalid != "" {
		return mcpErrorResponse(req.ID, mcpErrInvalidParams, invalid, nil)
	}
	version, _ := meta[mcpMetaProtocolVersion].(string)
	if version != mcpProtocolVersion {
		return mcpErrorResponse(req.ID, mcpErrUnsupportedProtocolVersion,
			"Unsupported protocol version", map[string]interface{}{
				"supported": []interface{}{mcpProtocolVersion},
				"requested": version,
			})
	}
	switch req.Method {
	case "server/discover":
		return a.handleMCPDiscover(req)
	case "tools/list":
		return a.handleMCPToolsList(req, true)
	case "tools/call":
		return a.handleMCPToolsCall(req, true)
	default:
		return mcpErrorResponse(req.ID, mcpErrMethodNotFound,
			fmt.Sprintf("Method not found: %s", req.Method), nil)
	}
}

// dispatchMCPLegacy dispatches one legacy-era request, unchanged from the
// handshake revision.
func (a *App) dispatchMCPLegacy(req mcpRequest) mcpResponse {
	switch req.Method {
	case "tools/list":
		return a.handleMCPToolsList(req, false)
	case "tools/call":
		return a.handleMCPToolsCall(req, false)
	default:
		return mcpErrorResponse(req.ID, mcpErrMethodNotFound,
			fmt.Sprintf("Method not found: %s", req.Method), nil)
	}
}

// handleMCPInitialize answers the legacy-era handshake, and selects that era.
//
// The modern revision has no handshake; this method is what a legacy client
// opens with, and answering it is what puts this process into legacy semantics
// for every later request that carries no modern metadata.
func (a *App) handleMCPInitialize(req mcpRequest) mcpResponse {
	return mcpResponse{
		Jsonrpc: "2.0",
		ID:      req.ID,
		Result: map[string]interface{}{
			"protocolVersion": mcpLegacyProtocolVersion,
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

// handleMCPDiscover answers `server/discover`, the modern era's mandatory
// discovery call. It replaces the handshake: supported versions, capabilities
// and identity in one request. The declared feature is a NAME rather than a
// version number, so a client learns that this server runs the confirmation
// dance without having to infer it from a revision date.
func (a *App) handleMCPDiscover(req mcpRequest) mcpResponse {
	return a.mcpCompleteResult(req.ID, map[string]interface{}{
		"supportedVersions": []interface{}{mcpProtocolVersion},
		"capabilities": map[string]interface{}{
			"tools": map[string]interface{}{},
			"extensions": map[string]interface{}{
				mcpFeatureConsequentialConfirmation: map[string]interface{}{},
			},
		},
		"instructions": a.Help,
		"ttlMs":        mcpCacheTTLMs,
		"cacheScope":   mcpCacheScope,
	})
}

// handleMCPToolsList responds with tool definitions for all non-hidden,
// non-interactive commands.
func (a *App) handleMCPToolsList(req mcpRequest, modern bool) mcpResponse {
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

	if !modern {
		return mcpResponse{
			Jsonrpc: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{
				"tools": toolDefs,
			},
		}
	}
	return a.mcpCompleteResult(req.ID, map[string]interface{}{
		"tools":      toolDefs,
		"ttlMs":      mcpCacheTTLMs,
		"cacheScope": mcpCacheScope,
	})
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

// mcpToolResult builds a tool result -- the one place the two eras' shapes
// differ.
func (a *App) mcpToolResult(reqID interface{}, text string, modern, isError bool) mcpResponse {
	body := map[string]interface{}{
		"content": []interface{}{
			map[string]interface{}{"type": "text", "text": text},
		},
	}
	if isError {
		body["isError"] = true
	}
	if !modern {
		return mcpResponse{Jsonrpc: "2.0", ID: reqID, Result: body}
	}
	return a.mcpCompleteResult(reqID, body)
}

// handleMCPToolsCall validates params, calls the command, and returns the result.
func (a *App) handleMCPToolsCall(req mcpRequest, modern bool) mcpResponse {
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
		return a.mcpToolResult(req.ID, err.Error(), modern, true)
	}

	// Marshal result to JSON text
	resultJSON, jsonErr := json.Marshal(result)
	if jsonErr != nil {
		return mcpErrorResponse(req.ID, mcpErrInternal,
			fmt.Sprintf("failed to marshal result: %s", jsonErr), nil)
	}

	return a.mcpToolResult(req.ID, string(resultJSON), modern, false)
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
