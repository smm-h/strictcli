package strictcli

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// registerCheckCommand registers the auto-generated "check" command.
// Called from NewApp when checksEnabled is true.
func (a *App) registerCheckCommand() {
	a.Command("check", "Run project checks", func(args map[string]interface{}) int {
		runAll := args["all"].(bool)
		tagExpr := args["tag"].(string)
		nameGlob := args["name"].(string)
		list := args["list"].(bool)
		jsonOut := args["json"].(bool)
		ignoreWarnings := args["ignore_warnings"].(bool)
		verbose := args["verbose"].(bool)
		dryRun := args["dry_run"].(bool)

		if list {
			return a.checkList(jsonOut)
		}

		if dryRun {
			return a.checkDryRun(runAll, tagExpr, nameGlob)
		}

		if runAll || tagExpr != "" || nameGlob != "" {
			return a.checkRun(runAll, tagExpr, nameGlob, jsonOut, ignoreWarnings, verbose)
		}

		// No flags: show help
		cmd := a.commands["check"]
		fmt.Println(formatCommandHelp(a, cmd, ""))
		return 0
	},
		WithFlags(
			BoolFlag("all", "Run all checks"),
			StringFlag("tag", "Tag DSL expression", Default("")),
			StringFlag("name", "Glob pattern for check names", Default("")),
			BoolFlag("list", "List checks and tags"),
			BoolFlag("json", "JSON output"),
			BoolFlag("ignore-warnings", "Warnings do not cause failure"),
			BoolFlag("verbose", "Show all details"),
			BoolFlag("dry-run", "Show plan without executing"),
		),
	)
}

// checkList implements the --list mode.
func (a *App) checkList(jsonOut bool) int {
	if jsonOut {
		return a.checkListJSON()
	}
	return a.checkListHuman()
}

// checkListHuman prints an aligned table of checks.
func (a *App) checkListHuman() int {
	order := a.checkOrder

	// Compute column widths
	maxName := len("NAME")
	maxTags := len("TAGS")
	for _, name := range order {
		if len(name) > maxName {
			maxName = len(name)
		}
		def := a.checkDefs[name]
		tagsStr := strings.Join(def.tags, ", ")
		if len(tagsStr) > maxTags {
			maxTags = len(tagsStr)
		}
	}

	// Print header
	fmt.Printf("%-*s   %-*s   %s\n", maxName, "NAME", maxTags, "TAGS", "SEVERITY")
	for _, name := range order {
		def := a.checkDefs[name]
		tagsStr := strings.Join(def.tags, ", ")
		fmt.Printf("%-*s   %-*s   %s\n", maxName, name, maxTags, tagsStr, def.severity)
	}
	return 0
}

// checkListJSON prints checks as a JSON array.
func (a *App) checkListJSON() int {
	type checkEntry struct {
		Name     string   `json:"name"`
		Tags     []string `json:"tags"`
		Severity string   `json:"severity"`
	}

	entries := make([]checkEntry, len(a.checkOrder))
	for i, name := range a.checkOrder {
		def := a.checkDefs[name]
		entries[i] = checkEntry{
			Name:     name,
			Tags:     def.tags,
			Severity: def.severity,
		}
	}

	data, err := json.Marshal(entries)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}
	fmt.Println(string(data))
	return 0
}

// checkDryRun shows which checks would run and in what order.
func (a *App) checkDryRun(runAll bool, tagExpr, nameGlob string) int {
	selected, err := filterChecks(a.checkDefs, tagExpr, nameGlob, runAll)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	order, err := resolveCheckOrder(a.checkDefs, selected)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	noun := "checks"
	if len(order) == 1 {
		noun = "check"
	}
	fmt.Printf("Would run %d %s:\n", len(order), noun)
	for i, name := range order {
		def := a.checkDefs[name]
		if len(def.dependsOn) > 0 {
			fmt.Printf("  %d. %s (depends on: %s)\n", i+1, name, strings.Join(def.dependsOn, ", "))
		} else {
			fmt.Printf("  %d. %s\n", i+1, name)
		}
	}
	return 0
}

// checkRun executes checks and formats output.
func (a *App) checkRun(runAll bool, tagExpr, nameGlob string, jsonOut, ignoreWarnings, verbose bool) int {
	if a.checkContextFactory == nil {
		fmt.Fprintln(os.Stderr, "error: no check context factory set (call SetCheckContext before running checks)")
		return 1
	}

	selected, err := filterChecks(a.checkDefs, tagExpr, nameGlob, runAll)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	order, err := resolveCheckOrder(a.checkDefs, selected)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	ctx := a.checkContextFactory()
	results, exitCode := runChecks(a.checkDefs, order, ctx, ignoreWarnings)

	if jsonOut {
		a.checkOutputJSON(results)
	} else {
		a.checkOutputHuman(results, verbose)
	}

	return exitCode
}

// checkOutputHuman prints human-readable check results.
func (a *App) checkOutputHuman(results []checkRunResult, verbose bool) {
	// Status labels are fixed 4 chars, uppercase
	statusLabel := map[string]string{
		"pass": "PASS",
		"fail": "FAIL",
		"warn": "WARN",
		"skip": "SKIP",
	}

	// Compute dynamic name column width
	nameWidth := 0
	for _, r := range results {
		if len(r.name) > nameWidth {
			nameWidth = len(r.name)
		}
	}

	for _, r := range results {
		label := statusLabel[r.result.Status]
		if label == "" {
			label = strings.ToUpper(r.result.Status)
		}
		fmt.Printf("%-4s  %-*s    %s\n", label, nameWidth, r.name, r.result.Message)

		showDetails := r.result.Status == "fail" || r.result.Status == "warn" || r.result.Status == "skip" || verbose
		if showDetails {
			for _, detail := range r.result.Details {
				fmt.Printf("        %s\n", detail)
			}
		}
	}
}

// checkOutputJSON prints check results as a JSON array.
func (a *App) checkOutputJSON(results []checkRunResult) {
	type jsonResult struct {
		Name    string   `json:"name"`
		Status  string   `json:"status"`
		Message string   `json:"message"`
		Details []string `json:"details"`
	}

	entries := make([]jsonResult, len(results))
	for i, r := range results {
		details := r.result.Details
		if details == nil {
			details = []string{}
		}
		entries[i] = jsonResult{
			Name:    r.name,
			Status:  r.result.Status,
			Message: r.result.Message,
			Details: details,
		}
	}

	data, err := json.Marshal(entries)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return
	}
	fmt.Println(string(data))
}
