package strictcli

import "fmt"

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
