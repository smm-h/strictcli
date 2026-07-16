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
	// PureOnly enables the purity partition: only checks that are declared pure
	// AND do not need network access are executed; every other selected check is
	// returned in the impureListed name list (see RunChecks) without being run
	// and without contributing to the exit code. Off by default -- the zero
	// value preserves today's behavior byte-for-byte.
	PureOnly bool
}

// RunChecks executes checks programmatically and returns the executed results,
// the ordered names of checks left unexecuted by the purity partition, the exit
// code, and any error. The exit code follows the same rules as the check
// command: 0 for all pass (or warn with IgnoreWarnings), 1 for any
// failure/warn/cascade-skip. impureListed is empty unless opts.PureOnly is set;
// listed checks contribute nothing to the exit code (a consumer renders them as
// e.g. "would run: <name> (impure)").
func (a *App) RunChecks(ctx CheckContext, opts RunChecksOptions) ([]CheckRunResult, []string, int, error) {
	if !a.checksEnabled {
		return nil, nil, 0, fmt.Errorf("checks are not enabled on this App")
	}

	// Materialize provider-sourced checks before any registry read.
	a.materializeCheckProviders()

	if errMsg := a.validateCheckRegistrations(); errMsg != "" {
		return nil, nil, 0, fmt.Errorf("%s", errMsg)
	}

	selected, err := filterChecks(a.checkDefs, opts.TagExpr, opts.NameGlob, opts.RunAll)
	if err != nil {
		return nil, nil, 0, err
	}

	if len(selected) == 0 {
		return []CheckRunResult{}, nil, 0, nil
	}

	order, err := resolveCheckOrder(a.checkDefs, selected)
	if err != nil {
		return nil, nil, 0, err
	}

	results, impureListed, exitCode := runChecks(a.checkDefs, order, ctx, opts.IgnoreWarnings, opts.PureOnly)
	return results, impureListed, exitCode, nil
}

// FormatCheckResults formats check results as a human-readable string.
// Layout: the derived status label, name, and message, with minted problems
// listed under the check row grouped by severity (error problems first, then
// warn problems), each tagged with its severity. Problems are shown for
// fail/warn/skip outcomes or when verbose is true. No trailing newline --
// callers use fmt.Println().
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
		status := r.Status()
		label := statusLabel[status]
		if label == "" {
			label = strings.ToUpper(status)
		}
		fmt.Fprintf(&b, "%-4s  %-*s    %s", label, nameWidth, r.Name, r.Outcome.message)

		showProblems := status == "fail" || status == "warn" || status == "skip" || verbose
		if showProblems {
			for _, p := range r.Outcome.orderedProblems() {
				fmt.Fprintf(&b, "\n        [%s] %s", p.severity, p.text)
			}
		}

		if i < len(results)-1 {
			b.WriteByte('\n')
		}
	}
	return b.String()
}

// FormatCheckResultsJSON formats check results as a JSON array string. Each
// entry carries the derived status plus the minted problems (each with its
// severity and text). Empty problems serialize as [] rather than null. No
// trailing newline.
func FormatCheckResultsJSON(results []CheckRunResult) string {
	type jsonProblem struct {
		Severity string `json:"severity"`
		Text     string `json:"text"`
	}
	type jsonResult struct {
		Name     string        `json:"name"`
		Status   string        `json:"status"`
		Message  string        `json:"message"`
		Problems []jsonProblem `json:"problems"`
	}

	entries := make([]jsonResult, len(results))
	for i, r := range results {
		problems := make([]jsonProblem, 0, len(r.Outcome.problems))
		for _, p := range r.Outcome.problems {
			problems = append(problems, jsonProblem{Severity: p.severity, Text: p.text})
		}
		entries[i] = jsonResult{
			Name:     r.Name,
			Status:   r.Status(),
			Message:  r.Outcome.message,
			Problems: problems,
		}
	}

	data, err := json.Marshal(entries)
	if err != nil {
		return fmt.Sprintf("error: %s", err)
	}
	return string(data)
}
