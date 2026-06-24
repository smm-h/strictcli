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
	a.Command("check", "Run registered project checks and report diagnostic results", func(args map[string]interface{}) int {
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
			BoolFlag("all", "Run every registered check regardless of tag filters"),
			StringFlag("tag", "Tag DSL expression to select which checks should run", Default("")),
			StringFlag("name", "Glob pattern to select checks by their registered name", Default("")),
			BoolFlag("list", "List all registered checks with their tags and severity"),
			BoolFlag("json", "Format output as machine-readable JSON instead of text"),
			BoolFlag("ignore-warnings", "Treat warnings as non-fatal so only errors cause failure"),
			BoolFlag("verbose", "Show detailed diagnostic output for each check result"),
			BoolFlag("dry-run", "Show which checks would run without actually executing"),
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
		Scope    string   `json:"scope,omitempty"`
	}

	entries := make([]checkEntry, len(a.checkOrder))
	for i, name := range a.checkOrder {
		def := a.checkDefs[name]
		entries[i] = checkEntry{
			Name:     name,
			Tags:     def.tags,
			Severity: def.severity,
			Scope:    def.scope,
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

	ctx := a.checkContextFactory()
	results, exitCode, err := a.RunChecks(ctx, RunChecksOptions{
		TagExpr:        tagExpr,
		NameGlob:       nameGlob,
		RunAll:         runAll,
		IgnoreWarnings: ignoreWarnings,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	if len(results) == 0 {
		fmt.Println("No checks matched the given filters.")
		return 0
	}

	if jsonOut {
		fmt.Println(FormatCheckResultsJSON(results))
	} else {
		fmt.Println(FormatCheckResults(results, verbose))
	}

	return exitCode
}
