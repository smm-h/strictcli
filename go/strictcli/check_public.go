package strictcli

import (
	"encoding/json"
	"fmt"
	"strings"
)

// RunChecksOptions configures which checks to run and how to handle results.
type RunChecksOptions struct {
	TagExpr        string
	NameGlob       string
	RunAll         bool
	IgnoreWarnings bool
}

// RunChecks executes checks programmatically and returns the results, exit code, and any error.
// The exit code follows the same rules as the check command: 0 for all pass (or warn with
// IgnoreWarnings), 1 for any failure/warn/cascade-skip.
func (a *App) RunChecks(ctx CheckContext, opts RunChecksOptions) ([]CheckRunResult, int, error) {
	if !a.checksEnabled {
		return nil, 0, fmt.Errorf("checks are not enabled on this App")
	}

	if errMsg := a.validateCheckRegistrations(); errMsg != "" {
		return nil, 0, fmt.Errorf("%s", errMsg)
	}

	selected, err := filterChecks(a.checkDefs, opts.TagExpr, opts.NameGlob, opts.RunAll)
	if err != nil {
		return nil, 0, err
	}

	if len(selected) == 0 {
		return []CheckRunResult{}, 0, nil
	}

	order, err := resolveCheckOrder(a.checkDefs, selected)
	if err != nil {
		return nil, 0, err
	}

	results, exitCode := runChecks(a.checkDefs, order, ctx, opts.IgnoreWarnings)
	return results, exitCode, nil
}

// FormatCheckResults formats check results as a human-readable string.
// Same layout as the check command's human output: status label, name, message, and details.
// When verbose is true, details are shown for passing checks too.
// No trailing newline -- callers use fmt.Println().
func FormatCheckResults(results []CheckRunResult, verbose bool) string {
	if len(results) == 0 {
		return ""
	}

	statusLabel := map[string]string{
		"pass": "PASS",
		"fail": "FAIL",
		"warn": "WARN",
		"skip": "SKIP",
	}

	// Compute dynamic name column width
	nameWidth := 0
	for _, r := range results {
		if len(r.Name) > nameWidth {
			nameWidth = len(r.Name)
		}
	}

	var b strings.Builder
	for i, r := range results {
		label := statusLabel[r.Result.Status]
		if label == "" {
			label = strings.ToUpper(r.Result.Status)
		}
		fmt.Fprintf(&b, "%-4s  %-*s    %s", label, nameWidth, r.Name, r.Result.Message)

		showDetails := r.Result.Status == "fail" || r.Result.Status == "warn" || r.Result.Status == "skip" || verbose
		if showDetails {
			for _, detail := range r.Result.Details {
				fmt.Fprintf(&b, "\n        %s", detail)
			}
		}

		if i < len(results)-1 {
			b.WriteByte('\n')
		}
	}
	return b.String()
}

// FormatCheckResultsJSON formats check results as a JSON array string.
// Same schema as the check command's JSON output. Empty details are serialized as []
// rather than null. No trailing newline.
func FormatCheckResultsJSON(results []CheckRunResult) string {
	type jsonResult struct {
		Name    string   `json:"name"`
		Status  string   `json:"status"`
		Message string   `json:"message"`
		Details []string `json:"details"`
	}

	entries := make([]jsonResult, len(results))
	for i, r := range results {
		details := r.Result.Details
		if details == nil {
			details = []string{}
		}
		entries[i] = jsonResult{
			Name:    r.Name,
			Status:  r.Result.Status,
			Message: r.Result.Message,
			Details: details,
		}
	}

	data, err := json.Marshal(entries)
	if err != nil {
		return fmt.Sprintf("error: %s", err)
	}
	return string(data)
}
